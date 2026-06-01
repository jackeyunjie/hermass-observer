#!/usr/bin/env python3
"""Search historical State environments for MA2560 signals.

This is a read-only research tool. It does not modify the State foundation,
strategy definitions, signal ledger, calibration config, or reminder layer.

The core question is deliberately narrow:
    when an authoritative MA2560 signal appears, which MN1/W1/D1 State
    combinations have historically produced better future excess returns?

    The script computes MA2560 signals from the existing foundation database using
    the same rule as backtest.strategy_signals.ma2560, attaches future labels with
    the existing calibration labeler, then reports exact MN1/W1/D1 State combos and
    coarser bit-pattern groups.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

from calibrate_strategy_evidence import attach_labels, code6, foundation_db_for, safe_float, ymd
from bootstrap_stats import metric_row, pct, fmt_num


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "strategy_evaluation"

CURRENT_RULE_HEX = {"E/E/F", "E/F/F", "E/F/E"}


def state_hex(value: int | None) -> str:
    if value is None:
        return "NA"
    if -15 <= value <= 15:
        prefix = "-" if value < 0 else ""
        return prefix + format(abs(value), "X")
    return str(value)


def decode_state(value: int | None) -> dict[str, Any]:
    """Decode signed Hermass state score into direction and bit components."""
    if value is None:
        return {
            "state": None,
            "hex": "NA",
            "direction": None,
            "base": None,
            "trend": None,
            "position": None,
            "volatility": None,
            "label": "NA",
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


def combo_key(sample: dict[str, Any]) -> str:
    return f"{sample['mn1_state']}/{sample['w1_state']}/{sample['d1_state']}"


def hex_combo_key(sample: dict[str, Any]) -> str:
    return f"{state_hex(sample['mn1_state'])}/{state_hex(sample['w1_state'])}/{state_hex(sample['d1_state'])}"


def bit_signature(sample: dict[str, Any]) -> str:
    """A coarser State signature to reduce exact-combo overfit."""
    parts = []
    for prefix in ["mn1", "w1", "d1"]:
        decoded = decode_state(sample.get(f"{prefix}_state"))
        parts.append(
            "".join(
                [
                    "S-" if decoded["direction"] == "空向" else "S+",
                    "B8" if decoded["base"] == 8 else "B0",
                    "T1" if decoded["trend"] else "T0",
                    "P1" if decoded["position"] else "P0",
                    "V1" if decoded["volatility"] else "V0",
                ]
            )
        )
    return "/".join(parts)


def signal_name(raw_signal: str) -> str:
    return {
        "ma2560_golden_cross": "2560金叉",
        "ma2560_strong_hold": "2560强多头结构",
        "ma2560_aligned": "2560多头排列",
        "ma2560_death_cross_exit": "2560死叉风险",
        "ma2560_bearish": "2560空头排列",
    }.get(raw_signal, raw_signal)


def ma2560_raw_signal(
    ma25: float | None,
    ma60: float | None,
    ma25_prev: float | None,
    ma60_prev: float | None,
    close: float | None,
) -> str | None:
    """Mirror backtest.strategy_signals.ma2560.ma2560_signal."""
    if ma25 is None or ma60 is None or close is None or close <= 0:
        return None
    aligned = ma25 > ma60
    aligned_prev = (ma25_prev or 0.0) > (ma60_prev or 0.0)
    if aligned and not aligned_prev:
        return "ma2560_golden_cross"
    if not aligned and aligned_prev:
        return "ma2560_death_cross_exit"
    if close > ma25 > ma60:
        return "ma2560_strong_hold"
    if aligned:
        return "ma2560_aligned"
    if ma25 < ma60:
        return "ma2560_bearish"
    return None


def load_ma2560_samples(
    db_path: Path,
    start_date: str,
    end_date: str,
    raw_signals: set[str],
    min_ef_count: int | None = None,
    max_ef_count: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compute MA2560 signals and attach State combos for all stocks/dates."""
    start = date.fromisoformat(start_date)
    warmup = (start - timedelta(days=180)).isoformat()
    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute(
        """
        WITH bars_base AS (
            SELECT
                stock_code,
                date,
                close,
                AVG(close) OVER w25 AS ma25,
                AVG(close) OVER w60 AS ma60
            FROM daily_bars
            WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
            WINDOW
                w25 AS (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 24 PRECEDING AND CURRENT ROW),
                w60 AS (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)
        ),
        bars AS (
            SELECT
                *,
                LAG(ma25, 1) OVER (PARTITION BY stock_code ORDER BY date) AS ma25_prev,
                LAG(ma60, 1) OVER (PARTITION BY stock_code ORDER BY date) AS ma60_prev
            FROM bars_base
        )
        SELECT
            s.stock_code,
            s.state_date::VARCHAR AS date,
            s.mn1_state_score,
            s.w1_state_score,
            s.d1_state_score,
            s.mn1_state_hex,
            s.w1_state_hex,
            s.d1_state_hex,
            s.ef_count,
            s.mn1_base,
            s.w1_base,
            s.d1_base,
            s.mn1_trend_bit,
            s.w1_trend_bit,
            s.d1_trend_bit,
            s.mn1_position_bit,
            s.w1_position_bit,
            s.d1_position_bit,
            s.mn1_volatility_bit,
            s.w1_volatility_bit,
            s.d1_volatility_bit,
            b.close,
            b.ma25,
            b.ma60,
            b.ma25_prev,
            b.ma60_prev
        FROM d1_perspective_state s
        JOIN bars b
          ON b.stock_code = s.stock_code
         AND b.date = s.state_date
        WHERE s.state_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        ORDER BY s.state_date, s.stock_code
        """,
        (warmup, end_date, start_date, end_date),
    ).fetchall()
    con.close()

    samples: list[dict[str, Any]] = []
    signal_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        (
            stock_code,
            d,
            mn1_state,
            w1_state,
            d1_state,
            mn1_hex,
            w1_hex,
            d1_hex,
            ef_count,
            mn1_base,
            w1_base,
            d1_base,
            mn1_trend_bit,
            w1_trend_bit,
            d1_trend_bit,
            mn1_position_bit,
            w1_position_bit,
            d1_position_bit,
            mn1_volatility_bit,
            w1_volatility_bit,
            d1_volatility_bit,
            close,
            ma25,
            ma60,
            ma25_prev,
            ma60_prev,
        ) = row
        raw_signal = ma2560_raw_signal(
            safe_float(ma25, None),
            safe_float(ma60, None),
            safe_float(ma25_prev, None),
            safe_float(ma60_prev, None),
            safe_float(close, None),
        )
        if not raw_signal:
            continue
        signal_counts[raw_signal] += 1
        if raw_signal not in raw_signals:
            continue
        ef_count_value = int(ef_count or 0)
        if min_ef_count is not None and ef_count_value < min_ef_count:
            continue
        if max_ef_count is not None and ef_count_value > max_ef_count:
            continue
        sample = {
            "date": d,
            "stock_code": stock_code,
            "stock_code_6": code6(stock_code),
            "strategy_id": "ma2560",
            "raw_signal": raw_signal,
            "signal_name": signal_name(raw_signal),
            "mn1_state": int(mn1_state) if mn1_state is not None else None,
            "w1_state": int(w1_state) if w1_state is not None else None,
            "d1_state": int(d1_state) if d1_state is not None else None,
            "mn1_state_hex": str(mn1_hex or state_hex(mn1_state)),
            "w1_state_hex": str(w1_hex or state_hex(w1_state)),
            "d1_state_hex": str(d1_hex or state_hex(d1_state)),
            "ef_count": ef_count_value,
            "mn1_base": int(mn1_base or 0),
            "w1_base": int(w1_base or 0),
            "d1_base": int(d1_base or 0),
            "mn1_trend_bit": int(mn1_trend_bit or 0),
            "w1_trend_bit": int(w1_trend_bit or 0),
            "d1_trend_bit": int(d1_trend_bit or 0),
            "mn1_position_bit": int(mn1_position_bit or 0),
            "w1_position_bit": int(w1_position_bit or 0),
            "d1_position_bit": int(d1_position_bit or 0),
            "mn1_volatility_bit": int(mn1_volatility_bit or 0),
            "w1_volatility_bit": int(w1_volatility_bit or 0),
            "d1_volatility_bit": int(d1_volatility_bit or 0),
            "close": safe_float(close, None),
            "ma25": safe_float(ma25, None),
            "ma60": safe_float(ma60, None),
        }
        sample["state_combo"] = combo_key(sample)
        sample["state_hex_combo"] = hex_combo_key(sample)
        sample["state_bit_signature"] = bit_signature(sample)
        sample["current_rule_match"] = sample["state_hex_combo"] in CURRENT_RULE_HEX
        samples.append(sample)

    diagnostics = {
        "db_path": str(db_path),
        "date_range": [start_date, end_date],
        "warmup_start": warmup,
        "rows_scanned": len(rows),
        "raw_signal_counts_all": dict(sorted(signal_counts.items())),
        "selected_raw_signals": sorted(raw_signals),
        "min_ef_count": min_ef_count,
        "max_ef_count": max_ef_count,
        "samples_selected": len(samples),
    }
    return samples, diagnostics


def summarize_grouped(
    samples: list[dict[str, Any]],
    group_field: str,
    window: int,
    min_samples: int,
    top_n: int,
) -> list[dict[str, Any]]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        if sample.get(f"excess_ret_{window}d") is None:
            continue
        by_key[str(sample.get(group_field) or "")].append(sample)

    rows = [metric_row(key, items, window, skip_ci=True) for key, items in by_key.items()]
    rows = [row for row in rows if row["n"] >= min_samples]
    rows.sort(
        key=lambda r: (safe_float(r.get("mean_excess"), -999.0), safe_float(r.get("win_rate"), 0.0), r["n"]),
        reverse=True,
    )
    return rows[:top_n]


def summarize_current_rule(samples: list[dict[str, Any]], windows: list[int]) -> dict[str, Any]:
    current = [s for s in samples if s.get("current_rule_match")]
    outside = [s for s in samples if not s.get("current_rule_match")]
    out = {
        "rule_hex_combos": sorted(CURRENT_RULE_HEX),
        "current_rule_samples": len(current),
        "outside_rule_samples": len(outside),
    }
    for label, items in [("current_rule", current), ("outside_rule", outside), ("all_selected", samples)]:
        out[label] = {f"{w}d": metric_row(label, items, w) for w in windows}
    return out


def annotate_exact_combo(row: dict[str, Any]) -> dict[str, Any]:
    states = row["key"].split("/")
    if len(states) != 3:
        return row
    mn1, w1, d1 = [int(x) for x in states]
    row["hex_combo"] = f"{state_hex(mn1)}/{state_hex(w1)}/{state_hex(d1)}"
    row["decoded"] = {
        "mn1": decode_state(mn1),
        "w1": decode_state(w1),
        "d1": decode_state(d1),
    }
    row["current_rule_match"] = row["hex_combo"] in CURRENT_RULE_HEX
    return row


def run_search(args: argparse.Namespace) -> dict[str, Any]:
    windows = args.windows or [5, 10, 20]
    raw_signals = set(args.raw_signal)
    db_path = args.foundation_db or foundation_db_for(args.end_date)
    samples, diagnostics = load_ma2560_samples(
        db_path,
        args.start_date,
        args.end_date,
        raw_signals,
        args.min_ef_count,
        args.max_ef_count,
    )
    labeled, label_diag = attach_labels(samples, db_path, windows)

    primary = args.primary_window
    exact = [
        annotate_exact_combo(row)
        for row in summarize_grouped(labeled, "state_combo", primary, args.min_samples, args.top_n)
    ]
    hex_rows = summarize_grouped(labeled, "state_hex_combo", primary, args.min_samples, args.top_n)
    bit_rows = summarize_grouped(labeled, "state_bit_signature", primary, args.min_samples, args.top_n)

    all_exact_by_window = {
        f"{window}d": [
            annotate_exact_combo(row)
            for row in summarize_grouped(labeled, "state_combo", window, args.min_samples, args.top_n)
        ]
        for window in windows
    }

    return {
        "schema_version": "ma2560_optimal_state_search_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "question": "Which MN1/W1/D1 State combinations are historically better for selected MA2560 signals?",
        "history": {"start_date": args.start_date, "end_date": args.end_date},
        "foundation_db": str(db_path),
        "selected_raw_signals": sorted(raw_signals),
        "label_windows": windows,
        "primary_window": primary,
        "min_samples": args.min_samples,
        "diagnostics": diagnostics,
        "label_diagnostics": label_diag,
        "sample_counts": {
            "selected_samples": len(samples),
            "labeled_samples": len(labeled),
            "labeled_dates": len({s["date"] for s in labeled}),
        },
        "current_rule_comparison": summarize_current_rule(labeled, windows),
        "top_exact_combos_primary": exact,
        "top_hex_combos_primary": hex_rows,
        "top_bit_signatures_primary": bit_rows,
        "top_exact_combos_by_window": all_exact_by_window,
        "interpretation_boundaries": [
            "This is historical environment search, not a trading instruction.",
            "Exact 16x16x16 combos can overfit; prefer candidates that also survive bit-signature or sample-out validation.",
            "State foundation and strategy definitions are not modified by this script.",
            "Use sample-out validation before promoting any combo into ma2560_state_market_match_rule.json.",
        ],
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# 2560 最优 State 环境搜索 - {result['history']['end_date']}",
        "",
        f"- 历史区间: `{result['history']['start_date']}` 至 `{result['history']['end_date']}`",
        f"- Foundation DB: `{result['foundation_db']}`",
        f"- 信号口径: `{', '.join(result['selected_raw_signals'])}`",
        f"- 主观察窗口: `{result['primary_window']}d`",
        f"- 最小样本数: `{result['min_samples']}`",
        f"- 已标注样本: `{result['sample_counts']['labeled_samples']}` / `{result['sample_counts']['selected_samples']}`",
        f"- 已标注日期: `{result['sample_counts']['labeled_dates']}`",
        "",
        "## 当前经验规则对照",
        "",
    ]
    comparison = result["current_rule_comparison"]
    lines.append(f"- 当前规则组合: `{', '.join(comparison['rule_hex_combos'])}`")
    lines.append(f"- 命中当前规则样本: `{comparison['current_rule_samples']}`")
    lines.append(f"- 当前规则外样本: `{comparison['outside_rule_samples']}`")
    lines.extend(
        [
            "",
            "| 口径 | 窗口 | n | 平均超额 | 95% CI | 胜率 | 95% CI | 盈亏比 | t-stat |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for label in ["current_rule", "outside_rule", "all_selected"]:
        for window in result["label_windows"]:
            row = comparison[label][f"{window}d"]
            ci_mean = f"[{pct(row.get('mean_excess_ci_lo'))}, {pct(row.get('mean_excess_ci_hi'))}]"
            ci_wr = f"[{pct(row.get('win_rate_ci_lo'))}, {pct(row.get('win_rate_ci_hi'))}]"
            lines.append(
                f"| {label} | {window}d | {row['n']} | {pct(row['mean_excess'])} | {ci_mean} | "
                f"{pct(row['win_rate'])} | {ci_wr} | {fmt_num(row['payoff_ratio'])} | {fmt_num(row['t_stat'])} |"
            )

    lines.extend(
        [
            "",
            "## 精确 State 组合 Top",
            "",
            "| rank | MN1/W1/D1 | Hex | n | 平均超额 | 胜率 | t-stat | 当前规则 | 解读 |",
            "|---:|---|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for idx, row in enumerate(result["top_exact_combos_primary"], 1):
        decoded = row.get("decoded", {})
        note = "；".join(
            f"{label}:{decoded.get(label, {}).get('label', '')}" for label in ["mn1", "w1", "d1"]
        )
        lines.append(
            f"| {idx} | `{row['key']}` | `{row.get('hex_combo', '')}` | {row['n']} | {pct(row['mean_excess'])} | "
            f"{pct(row['win_rate'])} | {fmt_num(row['t_stat'])} | {'yes' if row.get('current_rule_match') else 'no'} | {note} |"
        )

    lines.extend(
        [
            "",
            "## 模糊 bit 形态 Top",
            "",
            "| rank | bit signature | n | 平均超额 | 胜率 | t-stat |",
            "|---:|---|---:|---:|---:|---:|",
        ]
    )
    for idx, row in enumerate(result["top_bit_signatures_primary"], 1):
        lines.append(
            f"| {idx} | `{row['key']}` | {row['n']} | {pct(row['mean_excess'])} | {pct(row['win_rate'])} | {fmt_num(row['t_stat'])} |"
        )

    lines.extend(["", "## 边界", ""])
    for item in result["interpretation_boundaries"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def output_tag(result: dict[str, Any], date_tag: str) -> str:
    raw = "_".join(s.replace("ma2560_", "") for s in result.get("selected_raw_signals", [])) or "signals"
    scope = "all"
    min_ef = result.get("diagnostics", {}).get("min_ef_count")
    max_ef = result.get("diagnostics", {}).get("max_ef_count")
    if min_ef is not None or max_ef is not None:
        scope = f"ef{'' if min_ef is None else min_ef}to{'' if max_ef is None else max_ef}"
    return f"{date_tag}_{raw}_{scope}"


def write_outputs(result: dict[str, Any], date_tag: str) -> dict[str, str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = output_tag(result, date_tag)
    json_path = OUT_DIR / f"ma2560_optimal_state_search_{tag}.json"
    md_path = OUT_DIR / f"ma2560_optimal_state_search_{tag}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search best MN1/W1/D1 State environments for MA2560 historical signals."
    )
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--foundation-db", type=Path)
    parser.add_argument(
        "--raw-signal",
        action="append",
        default=[],
        help="MA2560 raw signal to include. Repeatable. Defaults to ma2560_golden_cross.",
    )
    parser.add_argument("--windows", type=int, nargs="*", default=[5, 10, 20])
    parser.add_argument("--primary-window", type=int, default=20)
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument(
        "--min-ef-count", type=int, help="Optional minimum ef_count filter for the signal date."
    )
    parser.add_argument(
        "--max-ef-count", type=int, help="Optional maximum ef_count filter for the signal date."
    )
    parser.add_argument("--top-n", type=int, default=30)
    args = parser.parse_args()
    if not args.raw_signal:
        args.raw_signal = ["ma2560_golden_cross"]
    if args.primary_window not in args.windows:
        args.windows.append(args.primary_window)
        args.windows = sorted(set(args.windows))

    result = run_search(args)
    outputs = write_outputs(result, ymd(args.end_date))
    print(
        json.dumps(
            {
                "ok": True,
                "research_only": True,
                "selected_samples": result["sample_counts"]["selected_samples"],
                "labeled_samples": result["sample_counts"]["labeled_samples"],
                "labeled_dates": result["sample_counts"]["labeled_dates"],
                "current_rule_comparison": result["current_rule_comparison"],
                "top_exact_combos_primary": result["top_exact_combos_primary"][:5],
                "outputs": outputs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
