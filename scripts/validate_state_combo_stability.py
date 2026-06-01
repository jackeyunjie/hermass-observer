#!/usr/bin/env python3
"""State 组合跨时间段稳定性验证脚本。

按半年、市场阶段或滚动固定窗口划分时间段，对固定的 State 组合假设
在每个时间段独立运行验证，输出各时间段的统计指标（超额、胜率、盈亏比、
Bootstrap 95% CI）并计算跨段一致性评分。

关联文档: docs/STATE_COMBO_CROSS_PERIOD_VALIDATION_DESIGN.md
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bootstrap_stats import metric_row, pct, fmt_num
from calibrate_strategy_evidence import attach_labels, code6, safe_float, foundation_db_for

OUT_DIR = ROOT / "outputs" / "project"

DEFAULT_WINDOWS = [5, 10, 20]


# -- 时间段划分 -----------------------------------------------------------------


def split_by_half_year(start: str, end: str) -> list[dict[str, str]]:
    """按自然半年划分。"""
    segments: list[dict[str, str]] = []
    sy, sm = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    year, half = sy, 1 if sm <= 6 else 2
    while True:
        period_start = f"{year}-01-01" if half == 1 else f"{year}-07-01"
        period_end = f"{year}-06-30" if half == 1 else f"{year}-12-31"
        segments.append(
            {
                "period_id": f"{year}H{half}",
                "start": period_start,
                "end": period_end,
            }
        )
        if year == ey and (half == 2 or em <= 6):
            break
        half = 2 if half == 1 else 1
        if half == 1:
            year += 1
    # Trim to actual range
    out: list[dict[str, str]] = []
    for seg in segments:
        ps = max(seg["start"], start)
        pe = min(seg["end"], end)
        if ps <= pe:
            out.append({"period_id": seg["period_id"], "start": ps, "end": pe})
    return out


def split_by_market_phase(start: str, end: str, db_path: Path) -> list[dict[str, str]]:
    """按市场阶段（牛/熊/震荡）划分。

    优先读取 d1_perspective_state 中的 d1_trend 字段作为市场阶段代理：
    - uptrend / strong_uptrend → bull
    - downtrend / strong_downtrend → bear
    - 其他 → oscillation

    如果 d1_trend 不存在，回退到半年划分。
    """
    if not db_path.exists():
        return split_by_half_year(start, end)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT state_date::VARCHAR, d1_trend
            FROM d1_perspective_state
            WHERE state_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
            GROUP BY state_date, d1_trend
            ORDER BY state_date
            """,
            [start, end],
        ).fetchall()
    except Exception:
        con.close()
        return split_by_half_year(start, end)
    con.close()

    # Deduplicate: if multiple rows for same date (different stocks have different trends),
    # pick the most common trend per date
    from collections import Counter

    date_trends: dict[str, list[str]] = defaultdict(list)
    for d, trend in rows:
        date_trends[d].append(str(trend or ""))
    rows = [(d, Counter(trends).most_common(1)[0][0]) for d, trends in sorted(date_trends.items())]

    if not rows:
        return split_by_half_year(start, end)

    # Map d1_trend to bull/bear/oscillation
    def classify(trend: str | None) -> str:
        t = str(trend or "").lower()
        if t in ("uptrend", "strong_uptrend", "bull_start", "bull_trend", "emergence", "progression"):
            return "bull"
        if t in ("downtrend", "strong_downtrend", "bear_start", "bear_trend", "contraction", "risk_release"):
            return "bear"
        return "oscillation"

    # Build raw segments
    segments: list[dict[str, str]] = []
    current_phase = classify(rows[0][1])
    current_start = rows[0][0]
    for d, trend in rows[1:]:
        ph = classify(trend)
        if ph != current_phase:
            segments.append(
                {
                    "period_id": f"{current_phase}_{current_start}_{d}",
                    "phase": current_phase,
                    "start": current_start,
                    "end": d,
                }
            )
            current_phase = ph
            current_start = d
    segments.append(
        {
            "period_id": f"{current_phase}_{current_start}_{rows[-1][0]}",
            "phase": current_phase,
            "start": current_start,
            "end": rows[-1][0],
        }
    )

    # Merge short segments (< 20 trading days) into same-phase neighbors
    MIN_SEGMENT_DAYS = 20
    # First pass: merge adjacent same-phase segments
    merged: list[dict[str, str]] = []
    for seg in segments:
        if merged and seg["phase"] == merged[-1]["phase"]:
            merged[-1]["end"] = seg["end"]
            merged[-1]["period_id"] = f"{merged[-1]['phase']}_{merged[-1]['start']}_{seg['end']}"
        else:
            merged.append(dict(seg))

    # Second pass: merge short segments into neighbors with same phase preference
    final: list[dict[str, str]] = []
    for seg in merged:
        seg_start = date.fromisoformat(seg["start"])
        seg_end = date.fromisoformat(seg["end"])
        seg_days = (seg_end - seg_start).days + 1
        if seg_days < MIN_SEGMENT_DAYS and final:
            # Try to merge with previous if same phase
            if seg["phase"] == final[-1]["phase"]:
                final[-1]["end"] = seg["end"]
                final[-1]["period_id"] = f"{final[-1]['phase']}_{final[-1]['start']}_{seg['end']}"
            else:
                # Absorb into previous regardless (keeps more history)
                final[-1]["end"] = seg["end"]
                final[-1]["period_id"] = f"{final[-1]['phase']}_{final[-1]['start']}_{seg['end']}"
        else:
            final.append(seg)
    return final


def _add_months(d: date, months: int) -> date:
    """Add months to a date, clamping to month-end if day overflows."""
    total_months = d.year * 12 + d.month - 1 + months
    year = total_months // 12
    month = total_months % 12 + 1
    import calendar

    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def split_by_rolling_window(
    start: str,
    end: str,
    window_months: int = 6,
    step_months: int = 3,
) -> list[dict[str, str]]:
    """滚动固定窗口划分。

    例如 window_months=6, step_months=3 时，每 3 个月前滚一次 6 个月窗口。
    """
    segments: list[dict[str, str]] = []
    current = date.fromisoformat(start)
    end_dt = date.fromisoformat(end)
    period_id = 0

    while True:
        window_end = _add_months(current, window_months) - timedelta(days=1)
        if window_end > end_dt:
            break

        seg_end = min(window_end, end_dt)
        segments.append(
            {
                "period_id": f"window_{period_id:03d}",
                "start": current.isoformat(),
                "end": seg_end.isoformat(),
            }
        )
        period_id += 1

        current = _add_months(current, step_months)
        if current > end_dt:
            break

    return segments


# -- 假设条件函数 ---------------------------------------------------------------


def vcp_compression_release(sample: dict[str, Any]) -> bool:
    """D1 近 20 日经历收缩后释放。

    兼容两种数据源：
    - search_vcp_optimal_state.py 生成的样本有 contraction_release_20 字段
    - 有 d1_days_since_contraction_exit 字段的样本（如 reminder/ledger 数据）
    """
    if "contraction_release_20" in sample:
        return bool(sample.get("contraction_release_20"))
    d1_since_exit = sample.get("d1_days_since_contraction_exit")
    return d1_since_exit is not None and 0 <= d1_since_exit <= 20


def ma2560_state_match(sample: dict[str, Any]) -> bool:
    """State 组合在适配区间。"""
    combo = (
        f"{sample.get('mn1_state_hex', '')}/{sample.get('w1_state_hex', '')}/{sample.get('d1_state_hex', '')}"
    )
    return combo in {"E/E/F", "E/F/F", "E/F/E"}


def bollinger_vol_stable(sample: dict[str, Any]) -> bool:
    """D1 volatility_bit=0。"""
    return sample.get("d1_volatility_bit") == 0


def vcp_compression_release_10d(sample: dict[str, Any]) -> bool:
    """D1 近 10 日经历收缩后释放。"""
    if "contraction_release_10" in sample:
        return bool(sample.get("contraction_release_10"))
    d1_since_exit = sample.get("d1_days_since_contraction_exit")
    return d1_since_exit is not None and 0 <= d1_since_exit <= 10


def vcp_compression_release_5d(sample: dict[str, Any]) -> bool:
    """D1 近 5 日经历收缩后释放。"""
    if "contraction_release_5" in sample:
        return bool(sample.get("contraction_release_5"))
    d1_since_exit = sample.get("d1_days_since_contraction_exit")
    return d1_since_exit is not None and 0 <= d1_since_exit <= 5


HYPOTHESIS_MAP: dict[str, callable] = {
    "contraction_release": vcp_compression_release,
    "contraction_release_20d": vcp_compression_release,
    "contraction_release_10d": vcp_compression_release_10d,
    "contraction_release_5d": vcp_compression_release_5d,
    "compression_release": vcp_compression_release,
    "compression_release_20d": vcp_compression_release,
    "compression_release_10d": vcp_compression_release_10d,
    "compression_release_5d": vcp_compression_release_5d,
    "eef_eff_efe": ma2560_state_match,
    "vol_bit_zero": bollinger_vol_stable,
    "vol_bit_zero_stable": bollinger_vol_stable,
}


# -- 样本加载 -------------------------------------------------------------------


def load_samples(
    strategy: str,
    start_date: str,
    end_date: str,
    db_path: Path,
    raw_signals: set[str] | None = None,
    min_ef_count: int | None = None,
    max_ef_count: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """从 foundation DB 加载策略样本并计算信号特征。

    复用 search_*_optimal_state.py 中的样本加载逻辑，
    然后调用 attach_labels() 附加超额收益标签。
    """
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    if strategy == "vcp":
        from search_vcp_optimal_state import load_vcp_samples

        if raw_signals is None:
            raw_signals = {"vcp_breakout", "vcp_breakout_weak_vol", "vcp_breakout_no_vol"}
        samples, diagnostics = load_vcp_samples(
            db_path, start_date, end_date, raw_signals, min_ef_count, max_ef_count
        )
    elif strategy == "ma2560":
        from search_2560_optimal_state import load_ma2560_samples

        if raw_signals is None:
            raw_signals = {"ma2560_golden_cross", "ma2560_strong_hold"}
        samples, diagnostics = load_ma2560_samples(
            db_path, start_date, end_date, raw_signals, min_ef_count, max_ef_count
        )
    elif strategy == "bollinger_bandit":
        from search_bollinger_optimal_state import load_bollinger_samples

        samples, diagnostics = load_bollinger_samples(
            db_path, start_date, end_date, min_ef_count, max_ef_count
        )
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    return samples, diagnostics


# -- 跨段验证 -------------------------------------------------------------------


def validate_in_period(
    period: dict[str, str],
    hypothesis_fn: callable,
    all_samples: list[dict[str, Any]],
    windows: list[int],
    n_bootstrap: int = 2000,
) -> dict[str, Any]:
    """在单个时间段内验证固定假设。"""
    period_samples = [
        s
        for s in all_samples
        if period["start"] <= s["date"] <= period["end"]
        and any(s.get(f"excess_ret_{w}d") is not None for w in windows)
    ]

    matched = [s for s in period_samples if hypothesis_fn(s)]
    outside = [s for s in period_samples if not hypothesis_fn(s)]

    out: dict[str, Any] = {
        "period_id": period["period_id"],
        "period_range": f"{period['start']} to {period['end']}",
        "total_samples": len(period_samples),
        "matched_n": len(matched),
        "outside_n": len(outside),
    }

    for label, items in [("matched", matched), ("outside", outside)]:
        out[label] = {}
        for w in windows:
            out[label][f"{w}d"] = metric_row(label, items, w, n_bootstrap)

    # Primary window stats (20d)
    primary = out.get("matched", {}).get("20d", {})
    mean_excess = primary.get("mean_excess")
    ci_lo = primary.get("mean_excess_ci_lo")
    out["direction_positive"] = (mean_excess or 0) > 0
    out["ci_excludes_zero"] = (ci_lo or 0) > 0
    out["matched_mean_excess"] = mean_excess
    out["matched_mean_excess_ci_lo"] = ci_lo
    out["matched_mean_excess_ci_hi"] = primary.get("mean_excess_ci_hi")
    out["matched_win_rate"] = primary.get("win_rate")
    out["matched_win_rate_ci_lo"] = primary.get("win_rate_ci_lo")
    out["matched_win_rate_ci_hi"] = primary.get("win_rate_ci_hi")
    out["matched_payoff_ratio"] = primary.get("payoff_ratio")
    out["matched_payoff_ratio_ci_lo"] = primary.get("payoff_ratio_ci_lo")
    out["matched_payoff_ratio_ci_hi"] = primary.get("payoff_ratio_ci_hi")
    out["matched_t_stat"] = primary.get("t_stat")

    return out


# -- 跨段一致性指标 -------------------------------------------------------------


def direction_consistency(period_results: list[dict[str, Any]]) -> float:
    positive = sum(1 for r in period_results if r.get("direction_positive"))
    return positive / len(period_results) if period_results else 0.0


def cross_period_cv(period_results: list[dict[str, Any]]) -> float:
    means = [r["matched_mean_excess"] for r in period_results if r.get("matched_mean_excess") is not None]
    if len(means) < 2:
        return float("inf")
    m = statistics.fmean(means)
    return statistics.stdev(means) / abs(m) if m != 0 else float("inf")


def detect_time_decay(period_results: list[dict[str, Any]]) -> dict[str, Any]:
    if len(period_results) < 3:
        return {"has_decay": False, "reason": "insufficient_periods"}

    early_means = [
        r["matched_mean_excess"]
        for r in period_results[: len(period_results) // 2]
        if r.get("matched_mean_excess") is not None
    ]
    late_means = [
        r["matched_mean_excess"]
        for r in period_results[len(period_results) // 2 :]
        if r.get("matched_mean_excess") is not None
    ]

    if not early_means or not late_means:
        return {"has_decay": False, "reason": "insufficient_data"}

    early_avg = statistics.fmean(early_means)
    late_avg = statistics.fmean(late_means)
    decay_ratio = late_avg / early_avg if early_avg != 0 else float("inf")

    return {
        "has_decay": decay_ratio < 0.5,
        "early_avg": round(early_avg, 4),
        "late_avg": round(late_avg, 4),
        "decay_ratio": round(decay_ratio, 3),
    }


def stability_verdict(
    direction_rate: float,
    cv: float,
    decay: dict[str, Any],
) -> dict[str, Any]:
    score = 0.0

    if direction_rate >= 0.75:
        score += 0.4
    elif direction_rate >= 0.6:
        score += 0.3
    elif direction_rate >= 0.5:
        score += 0.2

    if cv < 0.5:
        score += 0.3
    elif cv < 1.0:
        score += 0.2
    elif cv < 1.5:
        score += 0.1

    if not decay.get("has_decay", False):
        score += 0.3
    elif decay.get("decay_ratio", 0) > 0.7:
        score += 0.15

    if score >= 0.7:
        return {"score": round(score, 2), "verdict": "stable", "label": "统计稳定"}
    elif score >= 0.4:
        return {"score": round(score, 2), "verdict": "marginal", "label": "边际稳定"}
    else:
        return {"score": round(score, 2), "verdict": "unstable", "label": "不稳定"}


# -- 报告渲染 -------------------------------------------------------------------


def render_markdown(
    result: dict[str, Any],
) -> str:
    lines = [
        f"# State 组合稳定性验证 — {result['strategy']} {result['hypothesis']}",
        "",
        f"- 验证假设: {result['hypothesis']}",
        f"- 总区间: {result['start_date']} 至 {result['end_date']}",
        f"- 划分方式: {result['split_method']}",
        f"- 验证窗口: {result['primary_window']}日超额收益",
        "",
        "## 各时间段结果",
        "",
        "| 时间段 | 匹配样本 | 20d 超额 | 95% CI | 胜率 | 95% CI | 盈亏比 | 方向 | CI 显著 |",
        "|--------|---------|---------|--------|------|--------|--------|------|---------|",
    ]

    for pr in result["period_results"]:
        ci_mean = f"[{pct(pr.get('matched_mean_excess_ci_lo'))}, {pct(pr.get('matched_mean_excess_ci_hi'))}]"
        ci_wr = f"[{pct(pr.get('matched_win_rate_ci_lo'))}, {pct(pr.get('matched_win_rate_ci_hi'))}]"
        dir_mark = "✓" if pr.get("direction_positive") else "✗"
        sig_mark = "✓" if pr.get("ci_excludes_zero") else ""
        lines.append(
            f"| {pr['period_id']} | {pr['matched_n']} | {pct(pr.get('matched_mean_excess'))} | {ci_mean} | "
            f"{pct(pr.get('matched_win_rate'))} | {ci_wr} | {fmt_num(pr.get('matched_payoff_ratio'))} | {dir_mark} | {sig_mark} |"
        )

    lines.extend(
        [
            "",
            "## 跨段一致性",
            "",
            "| 指标 | 值 | 标准 | 判定 |",
            "|------|-----|------|------|",
        ]
    )

    dc = result["direction_consistency"]
    lines.append(f"| 方向一致性率 | {dc:.0%} | >= 60% | {'✓' if dc >= 0.6 else '✗'} |")

    cv = result["cross_period_cv"]
    cv_str = f"{cv:.2f}" if math.isfinite(cv) else "∞"
    lines.append(f"| 跨段变异系数 | {cv_str} | < 1.0 | {'✓' if cv < 1.0 else '✗'} |")

    decay = result["time_decay"]
    if decay.get("has_decay") is False:
        lines.append(f"| 时间衰减 | 无显著衰减 | 后半 >= 前半×50% | ✓ |")
    else:
        lines.append(f"| 时间衰减 | 比率 {decay.get('decay_ratio', 'N/A')} | 后半 >= 前半×50% | ✗ |")

    verdict = result["stability_verdict"]
    lines.extend(
        [
            "",
            f"| **综合评分** | **{verdict['score']}** | **>= 0.7** | **{verdict['label']}** |",
            "",
            "## 边界",
            "",
            "- 本验证为统计稳定性检验，不做参数优化",
            "- State 组合已固定，不做网格搜索",
            "- 任何规则变更仍需人工确认",
        ]
    )

    return "\n".join(lines)


# -- 主流程 ---------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="State combo cross-period stability validation.")
    parser.add_argument("--strategy", required=True, choices=["vcp", "ma2560", "bollinger_bandit"])
    parser.add_argument(
        "--state-hypothesis",
        required=True,
        help="Hypothesis ID (e.g., contraction_release, eef_eff_efe, vol_bit_zero)",
    )
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument(
        "--split", default="half_year", choices=["half_year", "market_phase", "rolling_window"]
    )
    parser.add_argument(
        "--foundation-db", type=Path, help="Foundation DuckDB path (defaults to latest p116_foundation)"
    )
    parser.add_argument("--windows", type=int, nargs="*", default=DEFAULT_WINDOWS)
    parser.add_argument("--primary-window", type=int, default=20)
    parser.add_argument("--n-bootstrap", type=int, default=2000)
    parser.add_argument("--output-dir", type=Path, default=OUT_DIR)
    parser.add_argument(
        "--raw-signal", action="append", default=[], help="Optional raw signal override (repeatable)."
    )
    parser.add_argument("--min-ef-count", type=int)
    parser.add_argument("--max-ef-count", type=int)
    parser.add_argument(
        "--window-months", type=int, default=6, help="Rolling window size in months (default 6)"
    )
    parser.add_argument(
        "--step-months", type=int, default=3, help="Rolling window step in months (default 3)"
    )
    args = parser.parse_args()

    hypothesis_fn = HYPOTHESIS_MAP.get(args.state_hypothesis)
    if hypothesis_fn is None:
        print(f"Unknown hypothesis: {args.state_hypothesis}", file=sys.stderr)
        return 1

    # Resolve foundation DB
    db_path = args.foundation_db
    if db_path is None:
        try:
            db_path = foundation_db_for(args.end_date)
        except FileNotFoundError:
            print("No foundation DB found. Please specify --foundation-db", file=sys.stderr)
            return 1

    # Build raw_signals set from CLI overrides
    raw_signals: set[str] | None = None
    if args.raw_signal:
        raw_signals = set(args.raw_signal)

    # Load samples and attach labels
    samples, load_diag = load_samples(
        args.strategy,
        args.start_date,
        args.end_date,
        db_path,
        raw_signals=raw_signals,
        min_ef_count=args.min_ef_count,
        max_ef_count=args.max_ef_count,
    )
    print(f"Loaded {len(samples)} raw samples for {args.strategy}")

    labeled, label_diag = attach_labels(samples, db_path, args.windows)
    print(f"Labeled {len(labeled)} samples with forward returns")

    # Split periods
    if args.split == "market_phase":
        periods = split_by_market_phase(args.start_date, args.end_date, db_path)
    elif args.split == "rolling_window":
        periods = split_by_rolling_window(
            args.start_date, args.end_date, args.window_months, args.step_months
        )
    else:
        periods = split_by_half_year(args.start_date, args.end_date)

    print(f"Split into {len(periods)} periods")

    # Validate per period
    period_results: list[dict[str, Any]] = []
    for period in periods:
        pr = validate_in_period(period, hypothesis_fn, labeled, args.windows, args.n_bootstrap)
        period_results.append(pr)
        print(
            f"  {pr['period_id']}: n={pr['matched_n']}, "
            f"mean_excess={pct(pr.get('matched_mean_excess'))}, "
            f"wr={pct(pr.get('matched_win_rate'))}, "
            f"pr={fmt_num(pr.get('matched_payoff_ratio'))}"
        )

    # Cross-period metrics
    dc = direction_consistency(period_results)
    cv = cross_period_cv(period_results)
    decay = detect_time_decay(period_results)
    verdict = stability_verdict(dc, cv, decay)

    result = {
        "schema_version": "state_combo_stability_v1",
        "strategy": args.strategy,
        "hypothesis": args.state_hypothesis,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "split_method": args.split,
        "primary_window": args.primary_window,
        "n_bootstrap": args.n_bootstrap,
        "period_results": period_results,
        "direction_consistency": dc,
        "cross_period_cv": cv,
        "time_decay": decay,
        "stability_verdict": verdict,
        "research_only": True,
    }

    # Write outputs
    args.output_dir.mkdir(parents=True, exist_ok=True)
    date_tag = args.end_date.replace("-", "")
    json_path = args.output_dir / f"state_combo_stability_{args.strategy}_{date_tag}.json"
    md_path = args.output_dir / f"state_combo_stability_{args.strategy}_{date_tag}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")

    print(f"\nOutputs written:")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")
    print(f"\nStability verdict: {verdict['label']} (score={verdict['score']})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
