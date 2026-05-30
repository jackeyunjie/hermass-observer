#!/usr/bin/env python3
"""Search historical State environments for Bollinger Bandit entry signals.

This is a read-only research tool. It does not modify the State foundation,
strategy definitions, signal ledger, calibration config, or reminder layer.

The question is deliberately narrow:
    when the authoritative Bollinger Bandit entry rule appears, which
    MN1/W1/D1 State environments have historically produced better future
    excess returns?
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

from backtest.strategy_signals.bollinger_bandit import bollinger_bandit_signal
from calibrate_strategy_evidence import attach_labels, code6, foundation_db_for, safe_float, ymd
from bootstrap_stats import metric_row, pct, fmt_num


OUT_DIR = ROOT / "outputs" / "strategy_evaluation"
PROJECT_OUT_DIR = ROOT / "outputs" / "project"

KIMI_D1_STATES = {13, 14, 15}
KIMI_W1_STATES = {14, 15}
KIMI_MN1_STATES = {12, 14, 15}


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


def is_kimi_candidate(sample: dict[str, Any]) -> bool:
    """KIMI research hypothesis: D1 13/14/15, W1 14/15, MN1 12/14/15."""
    return (
        abs(int(sample["d1_state"])) in KIMI_D1_STATES
        and abs(int(sample["w1_state"])) in KIMI_W1_STATES
        and abs(int(sample["mn1_state"])) in KIMI_MN1_STATES
    )


def is_all_three_ef(sample: dict[str, Any]) -> bool:
    return all(abs(int(sample[f"{p}_state"])) in {14, 15} for p in ["mn1", "w1", "d1"])


def load_bollinger_samples(
    db_path: Path,
    start_date: str,
    end_date: str,
    min_ef_count: int | None = None,
    max_ef_count: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compute Bollinger Bandit entries and attach State combos for all stocks/dates."""
    start = date.fromisoformat(start_date)
    warmup = (start - timedelta(days=120)).isoformat()
    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute(
        """
        WITH bars_base AS (
            SELECT
                stock_code,
                date,
                open,
                high,
                low,
                close,
                volume,
                AVG(close) OVER w50 AS ma50,
                STDDEV_SAMP(close) OVER w50 AS std50,
                LAG(close, 1) OVER w AS prev_close,
                LAG(close, 30) OVER w AS close_30_ago
            FROM daily_bars
            WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
            WINDOW
                w AS (PARTITION BY stock_code ORDER BY date),
                w50 AS (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW)
        ),
        bars AS (
            SELECT
                *,
                ma50 + std50 AS bb_upper_50_1,
                LAG(ma50 + std50, 1) OVER (PARTITION BY stock_code ORDER BY date) AS bb_upper_50_1_prev
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
            b.prev_close,
            b.close_30_ago,
            b.bb_upper_50_1,
            b.bb_upper_50_1_prev
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
    rows_with_signal_context = 0
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
            prev_close,
            close_30_ago,
            upper,
            prev_upper,
        ) = row
        row_payload = {"close": safe_float(close, 0.0)}
        ctx = {
            "prev_close": safe_float(prev_close, 0.0),
            "close_30_ago": safe_float(close_30_ago, 0.0),
            "bb_upper_50_1": safe_float(upper, 0.0),
            "bb_upper_50_1_prev": safe_float(prev_upper, 0.0),
        }
        if min([row_payload["close"], *ctx.values()]) > 0:
            rows_with_signal_context += 1
        signal = bollinger_bandit_signal(row_payload, ctx)
        if not signal:
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
            "strategy_id": "bollinger_bandit",
            "raw_signal": signal[0],
            "signal_name": "布林强盗多头触发",
            "signal_strength": signal[1],
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
            "bb_upper_50_1": safe_float(upper, None),
            "close_30_ago": safe_float(close_30_ago, None),
        }
        sample["state_combo"] = combo_key(sample)
        sample["state_hex_combo"] = hex_combo_key(sample)
        sample["state_bit_signature"] = bit_signature(sample)
        sample["kimi_candidate_match"] = is_kimi_candidate(sample)
        sample["all_three_ef_match"] = is_all_three_ef(sample)
        sample["d1_kimi_state_match"] = abs(sample["d1_state"]) in KIMI_D1_STATES
        sample["d1_volatility_active"] = decode_state(sample["d1_state"])["volatility"] == 1
        samples.append(sample)

    diagnostics = {
        "db_path": str(db_path),
        "date_range": [start_date, end_date],
        "warmup_start": warmup,
        "rows_scanned": len(rows),
        "rows_with_signal_context": rows_with_signal_context,
        "selected_raw_signal": "bb_bandit_long_entry",
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
    rows.sort(key=lambda r: (safe_float(r.get("mean_excess"), -999.0), safe_float(r.get("win_rate"), 0.0), r["n"]), reverse=True)
    return rows[:top_n]


def summarize_boolean_group(samples: list[dict[str, Any]], field: str, windows: list[int]) -> dict[str, Any]:
    matched = [s for s in samples if bool(s.get(field))]
    outside = [s for s in samples if not bool(s.get(field))]
    out = {"field": field, "matched_samples": len(matched), "outside_samples": len(outside)}
    for label, items in [("matched", matched), ("outside", outside), ("all_selected", samples)]:
        out[label] = {f"{w}d": metric_row(label, items, w) for w in windows}
    return out


def summarize_research_hypotheses(samples: list[dict[str, Any]], windows: list[int]) -> dict[str, Any]:
    return {
        "kimi_candidate": summarize_boolean_group(samples, "kimi_candidate_match", windows),
        "all_three_ef": summarize_boolean_group(samples, "all_three_ef_match", windows),
        "d1_13_14_15": summarize_boolean_group(samples, "d1_kimi_state_match", windows),
        "d1_volatility_active": summarize_boolean_group(samples, "d1_volatility_active", windows),
    }


def annotate_exact_combo(row: dict[str, Any]) -> dict[str, Any]:
    states = row["key"].split("/")
    if len(states) != 3:
        return row
    mn1, w1, d1 = [int(x) for x in states]
    sample = {"mn1_state": mn1, "w1_state": w1, "d1_state": d1}
    row["hex_combo"] = f"{state_hex(mn1)}/{state_hex(w1)}/{state_hex(d1)}"
    row["decoded"] = {
        "mn1": decode_state(mn1),
        "w1": decode_state(w1),
        "d1": decode_state(d1),
    }
    row["kimi_candidate_match"] = is_kimi_candidate(sample)
    row["all_three_ef_match"] = is_all_three_ef(sample)
    return row


def run_search(args: argparse.Namespace) -> dict[str, Any]:
    windows = args.windows or [5, 10, 20]
    db_path = args.foundation_db or foundation_db_for(args.end_date)
    samples, diagnostics = load_bollinger_samples(
        db_path,
        args.start_date,
        args.end_date,
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
        f"{window}d": [annotate_exact_combo(row) for row in summarize_grouped(labeled, "state_combo", window, args.min_samples, args.top_n)]
        for window in windows
    }

    return {
        "schema_version": "bollinger_optimal_state_search_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "question": "Which MN1/W1/D1 State combinations are historically better for Bollinger Bandit entry signals?",
        "history": {"start_date": args.start_date, "end_date": args.end_date},
        "foundation_db": str(db_path),
        "selected_raw_signal": "bb_bandit_long_entry",
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
        "hypothesis_comparison": summarize_research_hypotheses(labeled, windows),
        "top_exact_combos_primary": exact,
        "top_hex_combos_primary": hex_rows,
        "top_bit_signatures_primary": bit_rows,
        "top_exact_combos_by_window": all_exact_by_window,
        "interpretation_boundaries": [
            "This is historical environment search, not a trading instruction.",
            "KIMI candidate combos are hypotheses until reproduced locally with sample-out validation.",
            "Exact 16x16x16 combos can overfit; prefer candidates that also survive bit-signature or sample-out validation.",
            "State foundation and Bollinger Bandit core signal definitions are not modified by this script.",
            "Do not promote any combo into config before human review and sample-out validation.",
        ],
    }


def render_hypothesis_table(name: str, block: dict[str, Any], windows: list[int]) -> list[str]:
    lines = [
        f"### {name}",
        "",
        f"- 命中样本: `{block['matched_samples']}`",
        f"- 未命中样本: `{block['outside_samples']}`",
        "",
        "| 口径 | 窗口 | n | 平均超额 | 95% CI | 胜率 | 95% CI | 盈亏比 | t-stat |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label in ["matched", "outside", "all_selected"]:
        for window in windows:
            row = block[label][f"{window}d"]
            ci_mean = f"[{pct(row.get('mean_excess_ci_lo'))}, {pct(row.get('mean_excess_ci_hi'))}]"
            ci_wr = f"[{pct(row.get('win_rate_ci_lo'))}, {pct(row.get('win_rate_ci_hi'))}]"
            lines.append(
                f"| {label} | {window}d | {row['n']} | {pct(row['mean_excess'])} | {ci_mean} | "
                f"{pct(row['win_rate'])} | {ci_wr} | {fmt_num(row['payoff_ratio'])} | {fmt_num(row['t_stat'])} |"
            )
    lines.append("")
    return lines


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# 布林强盗最优 State 环境搜索 - {result['history']['end_date']}",
        "",
        f"- 历史区间: `{result['history']['start_date']}` 至 `{result['history']['end_date']}`",
        f"- Foundation DB: `{result['foundation_db']}`",
        f"- 信号口径: `{result['selected_raw_signal']}`",
        f"- 主观察窗口: `{result['primary_window']}d`",
        f"- 最小样本数: `{result['min_samples']}`",
        f"- 已标注样本: `{result['sample_counts']['labeled_samples']}` / `{result['sample_counts']['selected_samples']}`",
        f"- 已标注日期: `{result['sample_counts']['labeled_dates']}`",
        "",
        "## 研究假设对照",
        "",
    ]
    hypotheses = result["hypothesis_comparison"]
    titles = {
        "kimi_candidate": "KIMI候选组合：D1∈{13,14,15}, W1∈{14,15}, MN1∈{12,14,15}",
        "all_three_ef": "三周期 E/F 共振",
        "d1_13_14_15": "D1 ∈ {13,14,15}",
        "d1_volatility_active": "D1 volatility_bit = 1",
    }
    for key, title in titles.items():
        lines.extend(render_hypothesis_table(title, hypotheses[key], result["label_windows"]))

    lines.extend(
        [
            "## 精确 State 组合 Top",
            "",
            "| rank | MN1/W1/D1 | Hex | n | 平均超额 | 胜率 | t-stat | KIMI候选 | 三周期EF | 解读 |",
            "|---:|---|---|---:|---:|---:|---:|---|---|---|",
        ]
    )
    for idx, row in enumerate(result["top_exact_combos_primary"], 1):
        decoded = row.get("decoded", {})
        note = "；".join(
            f"{label}:{decoded.get(label, {}).get('label', '')}"
            for label in ["mn1", "w1", "d1"]
        )
        lines.append(
            f"| {idx} | `{row['key']}` | `{row.get('hex_combo', '')}` | {row['n']} | {pct(row['mean_excess'])} | "
            f"{pct(row['win_rate'])} | {fmt_num(row['t_stat'])} | {'yes' if row.get('kimi_candidate_match') else 'no'} | "
            f"{'yes' if row.get('all_three_ef_match') else 'no'} | {note} |"
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
    scope = "all"
    min_ef = result.get("diagnostics", {}).get("min_ef_count")
    max_ef = result.get("diagnostics", {}).get("max_ef_count")
    if min_ef is not None or max_ef is not None:
        scope = f"ef{'' if min_ef is None else min_ef}to{'' if max_ef is None else max_ef}"
    return f"{date_tag}_entry_{scope}"


def write_outputs(result: dict[str, Any], date_tag: str) -> dict[str, str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PROJECT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = output_tag(result, date_tag)
    json_path = OUT_DIR / f"bollinger_optimal_state_search_{tag}.json"
    md_path = OUT_DIR / f"bollinger_optimal_state_search_{tag}.md"
    project_md_path = PROJECT_OUT_DIR / "bollinger_optimal_state_search.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    rendered = render_markdown(result)
    md_path.write_text(rendered, encoding="utf-8")
    project_md_path.write_text(rendered, encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path), "project_markdown": str(project_md_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Search best MN1/W1/D1 State environments for Bollinger Bandit entry signals.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--foundation-db", type=Path)
    parser.add_argument("--windows", type=int, nargs="*", default=[5, 10, 20])
    parser.add_argument("--primary-window", type=int, default=20)
    parser.add_argument("--min-samples", type=int, default=30)
    parser.add_argument("--min-ef-count", type=int, help="Optional minimum ef_count filter for the signal date.")
    parser.add_argument("--max-ef-count", type=int, help="Optional maximum ef_count filter for the signal date.")
    parser.add_argument("--top-n", type=int, default=30)
    args = parser.parse_args()
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
                "hypothesis_comparison": result["hypothesis_comparison"],
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
