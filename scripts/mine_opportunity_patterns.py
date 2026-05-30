#!/usr/bin/env python3
"""数据驱动的机会模式挖掘脚本。

核心原则：
    - 数据驱动：不预设"好模式"，让数据按超额收益排序
    - 保持开放：扫描全部压缩后的约 1,024 种有效模式组合
    - 逐步积累：支持增量更新，样本越多结论越稳定

模式定义：
    - D1 跃迁：当日 D1 State vs 前一日 D1 State，保留有实质变化的
    - W1 压缩：扩张有趋势 / 扩张无趋势 / 收缩有趋势 / 收缩无趋势（4 种）
    - MN1 压缩：同 W1 的四分类（4 种）
    - 有效组合：256 × 4 × 4 = 4,096 种理论组合，过滤后约 1,024 种

产出：
    outputs/project/opportunity_patterns_daily.json
    outputs/project/opportunity_patterns_monthly_YYYYMM.md
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bootstrap_stats import metric_row, pct, fmt_num

OUT_DIR = ROOT / "outputs" / "project"

MIN_SAMPLE_SIZE = 30
VERIFIED_SAMPLE_SIZE = 100
WINDOWS = [5, 10, 20]
DEFAULT_TOP_N = 50
DEFAULT_N_BOOTSTRAP = 2000


def state_hex(value: int | None) -> str:
    if value is None:
        return "NA"
    if -15 <= value <= 15:
        prefix = "-" if value < 0 else ""
        return prefix + format(abs(value), "X")
    return str(value)


def decode_state(value: int | None) -> dict[str, Any]:
    if value is None:
        return {
            "state": None, "hex": "NA", "direction": None,
            "base": None, "trend": None, "position": None,
            "volatility": None, "label": "NA",
        }
    magnitude = abs(value)
    base = 8 if magnitude >= 8 else 0
    trend = 4 if magnitude & 4 else 0
    position = 2 if magnitude & 2 else 0
    volatility = 1 if magnitude & 1 else 0
    direction = "空向" if value < 0 else "多向"
    return {
        "state": value,
        "hex": state_hex(value),
        "direction": direction,
        "base": base,
        "trend": trend,
        "position": position,
        "volatility": volatility,
        "label": (
            direction
            + "/"
            + ("扩张" if base else "收缩")
            + "/"
            + ("有趋势" if trend else "无趋势")
            + "/"
            + ("突破" if position else "未突破")
            + "/"
            + ("波动活跃" if volatility else "波动稳定")
        ),
    }


def state_label(value: int | None) -> str:
    if value is None:
        return "NA"
    return decode_state(value)["label"]


def compress_wm(base_tag: str, trend_tag: str) -> str:
    return f"{base_tag}_{trend_tag}"


def encode_pattern(
    d1_from: int,
    d1_to: int,
    w1_base_tag: str,
    w1_trend_tag: str,
    mn1_base_tag: str,
    mn1_trend_tag: str,
) -> str:
    return (f"D{state_hex(d1_from)}_{state_hex(d1_to)}"
            f"_W{compress_wm(w1_base_tag, w1_trend_tag)}"
            f"_M{compress_wm(mn1_base_tag, mn1_trend_tag)}")


def decode_pattern_code(pattern_code: str) -> dict[str, Any]:
    parts = pattern_code.split("_")
    hex_from = parts[0][1:]
    hex_to = parts[1]
    w1_compressed = parts[2][1:] + "_" + parts[3]
    mn1_compressed = parts[4][1:] + "_" + parts[5]
    w1_state_desc = (
        f"{'扩张' if w1_compressed.startswith('exp') else '收缩'}"
        f"{'有趋势' if w1_compressed.endswith('t') else '无趋势'}"
    )
    mn1_state_desc = (
        f"{'扩张' if mn1_compressed.startswith('exp') else '收缩'}"
        f"{'有趋势' if mn1_compressed.endswith('t') else '无趋势'}"
    )
    return {
        "d1_from_hex": hex_from,
        "d1_to_hex": hex_to,
        "d1_transition": f"D1 {hex_from}→{hex_to}",
        "w1_context": w1_state_desc,
        "mn1_context": mn1_state_desc,
        "summary": f"D1 {hex_from}→{hex_to} | W1={w1_state_desc} MN1={mn1_state_desc}",
    }


def is_significant_transition(d1_from: int, d1_to: int) -> bool:
    if abs(abs(d1_to) - abs(d1_from)) >= 4:
        return True
    if (abs(d1_from) >= 8) != (abs(d1_to) >= 8):
        return True
    if (d1_from >= 0) != (d1_to >= 0):
        return True
    return False


def load_transitions_with_returns(
    db_path: Path,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    con = duckdb.connect(str(db_path), read_only=True)
    date_filter = ""
    params = []
    if start_date:
        date_filter += " AND state_date >= ?"
        params.append(start_date)
    if end_date:
        date_filter += " AND state_date <= ?"
        params.append(end_date)

    query = f"""
    WITH transitions AS (
        SELECT
            stock_code,
            state_date,
            d1_state_score,
            LAG(d1_state_score) OVER (PARTITION BY stock_code ORDER BY state_date) as prev_d1_state,
            w1_state_score,
            mn1_state_score,
            d1_close,
            LEAD(d1_close, 5) OVER (PARTITION BY stock_code ORDER BY state_date) as close_5d,
            LEAD(d1_close, 10) OVER (PARTITION BY stock_code ORDER BY state_date) as close_10d,
            LEAD(d1_close, 20) OVER (PARTITION BY stock_code ORDER BY state_date) as close_20d
        FROM d1_perspective_state
        WHERE 1=1 {date_filter}
    ),
    daily_market AS (
        SELECT
            state_date,
            AVG(CASE WHEN close_5d IS NOT NULL THEN close_5d/d1_close - 1 END) as mkt_5d,
            AVG(CASE WHEN close_10d IS NOT NULL THEN close_10d/d1_close - 1 END) as mkt_10d,
            AVG(CASE WHEN close_20d IS NOT NULL THEN close_20d/d1_close - 1 END) as mkt_20d
        FROM transitions
        WHERE close_5d IS NOT NULL
        GROUP BY state_date
    )
    SELECT
        t.stock_code,
        t.state_date,
        t.prev_d1_state,
        t.d1_state_score,
        CASE WHEN ABS(t.w1_state_score) >= 8 THEN 'exp' ELSE 'con' END as w1_base_tag,
        CASE WHEN (ABS(t.w1_state_score) >> 2) & 1 = 1 THEN 't' ELSE 'f' END as w1_trend_tag,
        CASE WHEN ABS(t.mn1_state_score) >= 8 THEN 'exp' ELSE 'con' END as mn1_base_tag,
        CASE WHEN (ABS(t.mn1_state_score) >> 2) & 1 = 1 THEN 't' ELSE 'f' END as mn1_trend_tag,
        t.close_5d/t.d1_close - 1 - m.mkt_5d as excess_5d,
        t.close_10d/t.d1_close - 1 - m.mkt_10d as excess_10d,
        t.close_20d/t.d1_close - 1 - m.mkt_20d as excess_20d
    FROM transitions t
    JOIN daily_market m ON t.state_date = m.state_date
    WHERE t.prev_d1_state IS NOT NULL
      AND t.close_5d IS NOT NULL
      AND t.close_10d IS NOT NULL
      AND t.close_20d IS NOT NULL
      AND (ABS(ABS(t.d1_state_score) - ABS(t.prev_d1_state)) >= 4
           OR (ABS(t.d1_state_score) >= 8) != (ABS(t.prev_d1_state) >= 8)
           OR (t.d1_state_score >= 0) != (t.prev_d1_state >= 0))
    """
    rows = con.execute(query, params).fetchall()
    con.close()

    results = []
    for row in rows:
        results.append({
            "stock_code": row[0],
            "date": str(row[1]),
            "d1_from": int(row[2]),
            "d1_to": int(row[3]),
            "w1_base_tag": row[4],
            "w1_trend_tag": row[5],
            "mn1_base_tag": row[6],
            "mn1_trend_tag": row[7],
            "excess_ret_5d": float(row[8]),
            "excess_ret_10d": float(row[9]),
            "excess_ret_20d": float(row[10]),
        })
    return results


def compute_cross_period_consistency(
    items: list[dict[str, Any]],
    split_date: str = "2022-06-01",
    window: int = 20,
) -> dict[str, Any]:
    periods: dict[str, list[float]] = defaultdict(list)
    for t in items:
        date = str(t.get("date") or t.get("state_date") or "")
        period = "p1" if date < split_date else "p2"
        val = t.get(f"excess_ret_{window}d")
        if val is not None:
            periods[period].append(val)

    period_details = []
    positive_periods = 0
    for period, values in sorted(periods.items()):
        mean = statistics.fmean(values) if values else 0.0
        if mean > 0:
            positive_periods += 1
        period_details.append({
            "period": period,
            "n": len(values),
            "mean_excess": round(mean, 6),
        })

    periods_present = len(periods)
    consistency_ratio = positive_periods / periods_present if periods_present > 0 else 0.0
    return {
        "periods_present": periods_present,
        "positive_periods": positive_periods,
        "consistency_ratio": round(consistency_ratio, 4),
        "period_details": period_details,
    }


def classify_pattern_status(
    n: int,
    mean_excess: float | None,
    ci_lo: float | None,
    cross_period: dict[str, Any] | None,
) -> str:
    if mean_excess is None:
        return "pending"
    if n >= VERIFIED_SAMPLE_SIZE and ci_lo is not None and ci_lo > 0:
        if cross_period and cross_period.get("consistency_ratio", 0) >= 0.6:
            return "verified"
    if n >= MIN_SAMPLE_SIZE and mean_excess > 0:
        return "candidate"
    return "pending"


def mine_patterns(
    transitions: list[dict[str, Any]],
    window: int = 20,
    min_samples: int = MIN_SAMPLE_SIZE,
    top_n: int = DEFAULT_TOP_N,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
    compute_ci: bool = True,
) -> dict[str, Any]:
    by_pattern: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in transitions:
        code = encode_pattern(
            t["d1_from"], t["d1_to"],
            t["w1_base_tag"], t["w1_trend_tag"],
            t["mn1_base_tag"], t["mn1_trend_tag"],
        )
        by_pattern[code].append(t)

    total_patterns = len(by_pattern)
    patterns_with_sufficient = 0
    results = []

    for pattern_code, items in by_pattern.items():
        values = [t[f"excess_ret_{window}d"] for t in items
                  if t.get(f"excess_ret_{window}d") is not None]
        n = len(values)
        if n < min_samples:
            continue

        patterns_with_sufficient += 1
        samples = [{f"excess_ret_{window}d": v} for v in values]
        row = metric_row(pattern_code, samples, window, n_bootstrap=n_bootstrap, skip_ci=not compute_ci)
        cross_period = compute_cross_period_consistency(items, window=window)
        status = classify_pattern_status(
            n=row["n"],
            mean_excess=row.get("mean_excess"),
            ci_lo=row.get("mean_excess_ci_lo"),
            cross_period=cross_period,
        )
        decoded = decode_pattern_code(pattern_code)

        results.append({
            "pattern_code": pattern_code,
            "status": status,
            "d1_from_hex": decoded["d1_from_hex"],
            "d1_to_hex": decoded["d1_to_hex"],
            "d1_transition": decoded["d1_transition"],
            "w1_context": decoded["w1_context"],
            "mn1_context": decoded["mn1_context"],
            "summary": decoded["summary"],
            "n": row["n"],
            "mean_excess": row.get("mean_excess"),
            "mean_excess_ci_lo": row.get("mean_excess_ci_lo"),
            "mean_excess_ci_hi": row.get("mean_excess_ci_hi"),
            "median_excess": row.get("median_excess"),
            "win_rate": row.get("win_rate"),
            "win_rate_ci_lo": row.get("win_rate_ci_lo"),
            "win_rate_ci_hi": row.get("win_rate_ci_hi"),
            "payoff_ratio": row.get("payoff_ratio"),
            "payoff_ratio_ci_lo": row.get("payoff_ratio_ci_lo"),
            "payoff_ratio_ci_hi": row.get("payoff_ratio_ci_hi"),
            "t_stat": row.get("t_stat"),
            "cross_period": cross_period,
        })

    results.sort(key=lambda r: r.get("mean_excess") or -999, reverse=True)
    status_counts = {"verified": 0, "candidate": 0, "pending": 0}
    for r in results:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

    return {
        "total_patterns_scanned": total_patterns,
        "patterns_with_sufficient_samples": patterns_with_sufficient,
        "status_counts": status_counts,
        "patterns": results,
        "patterns_top_n": results[:top_n],
    }


def render_daily_json(
    mined: dict[str, Any],
    db_path: Path,
    start_date: str | None,
    end_date: str | None,
    window: int,
    min_samples: int,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": "opportunity_patterns_v1",
        "date": end_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "generated_at": generated_at,
        "data_range": {"start": start_date, "end": end_date},
        "mode": "d1_w1_mn1_compressed",
        "window": window,
        "min_samples": min_samples,
        "foundation_db": str(db_path),
        "total_patterns_scanned": mined["total_patterns_scanned"],
        "patterns_with_sufficient_samples": mined["patterns_with_sufficient_samples"],
        "status_counts": mined["status_counts"],
        "patterns": mined["patterns"],
        "research_only": True,
    }


def render_monthly_markdown(
    mined: dict[str, Any],
    db_path: Path,
    start_date: str | None,
    end_date: str | None,
    window: int,
    generated_at: str,
    top_n: int = DEFAULT_TOP_N,
) -> str:
    year_month = (end_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:7]
    lines = [
        f"# 机会模式月度报告 — {year_month}",
        "",
        "## 概览",
        f"- 扫描模式数：{mined['total_patterns_scanned']:,}",
        f"- 有效模式（n≥{MIN_SAMPLE_SIZE}）：{mined['patterns_with_sufficient_samples']}",
        f"- 已验证模式：{mined['status_counts'].get('verified', 0)}",
        f"- 候选观察模式：{mined['status_counts'].get('candidate', 0)}",
        f"- 数据范围：{start_date or 'N/A'} 至 {end_date or 'N/A'}",
        f"- 观察窗口：{window} 日超额收益",
        f"- Foundation DB：`{db_path}`",
        "",
        "---",
        "",
    ]

    verified = [p for p in mined["patterns"] if p["status"] == "verified"]
    if verified:
        lines.extend([
            "## 已验证模式",
            "",
            f"| 排名 | 模式 | D1 跃迁 | W1 背景 | MN1 背景 | n | {window}d 超额 | 95% CI | 胜率 | 盈亏比 | t-stat |",
            f"|---:|---|---|---|---|---|---:|---|---:|---:|---:|",
        ])
        for idx, p in enumerate(verified, 1):
            ci_lo = p.get("mean_excess_ci_lo")
            ci_hi = p.get("mean_excess_ci_hi")
            ci_str = f"[{fmt_num(ci_lo, 4)},{fmt_num(ci_hi, 4)}]" if ci_lo is not None and ci_hi is not None else "[-,-]"
            pr = p.get("payoff_ratio")
            pr_str = fmt_num(pr, 3) if pr is not None else "-"
            lines.append(
                f"| {idx} | `{p['pattern_code']}` | {p['d1_transition']} | {p['w1_context']} | {p['mn1_context']} | "
                f"{p['n']:,} | {pct(p.get('mean_excess'), 2)} | {ci_str} | "
                f"{pct(p.get('win_rate'), 1)} | {pr_str} | {fmt_num(p.get('t_stat'), 2)} |"
            )
        lines.append("")

    candidates = [p for p in mined["patterns"] if p["status"] == "candidate"]
    if candidates:
        lines.extend([
            "## 候选观察模式（待积累样本）",
            "",
            f"| 排名 | 模式 | D1 跃迁 | W1 背景 | MN1 背景 | n | {window}d 超额 | 胜率 | 状态 |",
            f"|---:|---|---|---|---|---|---:|---:|:---|",
        ])
        for idx, p in enumerate(candidates, 1):
            lines.append(
                f"| {idx} | `{p['pattern_code']}` | {p['d1_transition']} | {p['w1_context']} | {p['mn1_context']} | "
                f"{p['n']:,} | {pct(p.get('mean_excess'), 2)} | {pct(p.get('win_rate'), 1)} | 候选 |"
            )
        lines.append("")

    top_by_abs = sorted(mined["patterns"], key=lambda r: abs(r.get("mean_excess") or 0), reverse=True)[:top_n]
    lines.extend([
        f"## Top {top_n} 模式（按 |{window}d 超额| 排序）",
        "",
        f"| 排名 | 模式 | D1 跃迁 | W1 背景 | MN1 背景 | n | {window}d 超额 | 胜率 | 状态 |",
        f"|---:|---|---|---|---|---|---:|---:|:---|",
    ])
    for idx, p in enumerate(top_by_abs, 1):
        status_label = {"verified": "已验证", "candidate": "候选", "pending": "待观察"}.get(p["status"], p["status"])
        lines.append(
            f"| {idx} | `{p['pattern_code']}` | {p['d1_transition']} | {p['w1_context']} | {p['mn1_context']} | "
            f"{p['n']:,} | {pct(p.get('mean_excess'), 2)} | {pct(p.get('win_rate'), 1)} | {status_label} |"
        )
    lines.append("")

    lines.extend([
        "---",
        "",
        "## 统计边界说明",
        "",
        "1. **超额收益计算**：个股 forward return 减去当日全市场等权平均 return。",
        f"2. **样本充足标准**：≥{MIN_SAMPLE_SIZE} 个样本。",
        "3. **已验证标准**：n ≥ 100 + 95% CI 不含零 + 跨期方向一致率 ≥ 60%。",
        "4. **t-stat 解读**：|t-stat| > 1.96 表示 95% 置信度下显著不为零。",
        "5. **模式压缩**：W1/MN1 压缩为 4 类（扩张/收缩 × 有趋势/无趋势），降低组合爆炸。",
        "",
        "---",
        "",
        "*本报告为研究性质，不构成交易建议。所有数字均为历史统计，不代表未来表现。*",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="数据驱动的机会模式挖掘脚本")
    parser.add_argument("--foundation-db", type=Path, help="Path to foundation DuckDB")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--window", type=int, default=20, help="Forward return window (default: 20)")
    parser.add_argument("--min-samples", type=int, default=MIN_SAMPLE_SIZE, help=f"Min samples (default: {MIN_SAMPLE_SIZE})")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help=f"Top N patterns (default: {DEFAULT_TOP_N})")
    parser.add_argument("--n-bootstrap", type=int, default=DEFAULT_N_BOOTSTRAP, help=f"Bootstrap iterations (default: {DEFAULT_N_BOOTSTRAP})")
    parser.add_argument("--skip-ci", action="store_true", help="Skip bootstrap CI (faster)")
    parser.add_argument("--output-dir", type=Path, default=OUT_DIR, help="Output directory")
    args = parser.parse_args()

    if args.foundation_db:
        db_path = args.foundation_db
    else:
        candidates = sorted(ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"))
        if not candidates:
            print("No foundation DB found", file=sys.stderr)
            return 1
        db_path = candidates[-1]

    print(f"Foundation DB: {db_path}", file=sys.stderr)
    print(f"Window: {args.window}d, min_samples: {args.min_samples}, top_n: {args.top_n}", file=sys.stderr)

    print("Loading transitions with forward returns...", file=sys.stderr)
    transitions = load_transitions_with_returns(db_path, args.start_date, args.end_date)
    print(f"  -> {len(transitions):,} significant transitions loaded", file=sys.stderr)

    print("Mining patterns...", file=sys.stderr)
    mined = mine_patterns(
        transitions,
        window=args.window,
        min_samples=args.min_samples,
        top_n=args.top_n,
        n_bootstrap=args.n_bootstrap,
        compute_ci=not args.skip_ci,
    )
    print(f"  -> {mined['total_patterns_scanned']} patterns scanned", file=sys.stderr)
    print(f"  -> {mined['patterns_with_sufficient_samples']} with sufficient samples", file=sys.stderr)
    print(f"  -> verified: {mined['status_counts'].get('verified', 0)}, candidate: {mined['status_counts'].get('candidate', 0)}", file=sys.stderr)

    generated_at = datetime.now(timezone.utc).isoformat()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    daily_json = render_daily_json(
        mined, db_path, args.start_date, args.end_date,
        args.window, args.min_samples, generated_at,
    )
    json_path = args.output_dir / "opportunity_patterns_daily.json"
    json_path.write_text(json.dumps(daily_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON written: {json_path}", file=sys.stderr)

    md = render_monthly_markdown(
        mined, db_path, args.start_date, args.end_date,
        args.window, generated_at, top_n=args.top_n,
    )
    year_month = (args.end_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:7]
    md_path = args.output_dir / f"opportunity_patterns_monthly_{year_month}.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"Markdown written: {md_path}", file=sys.stderr)

    result = {
        "ok": True,
        "json": str(json_path),
        "markdown": str(md_path),
        "patterns_scanned": mined["total_patterns_scanned"],
        "patterns_sufficient": mined["patterns_with_sufficient_samples"],
        "verified": mined["status_counts"].get("verified", 0),
        "candidate": mined["status_counts"].get("candidate", 0),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
