#!/usr/bin/env python3
"""Search historical State paths for VCP entry signals.

This is a read-only research tool. It does not modify the State foundation,
strategy definitions, signal ledger, calibration config, or reminder layer.

The question is path-based, not static-state-based:
    when an authoritative VCP entry appears, did D1 recently experience
    compression and then release into expansion/trend confirmation?
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

from backtest.strategy_signals.vcp import vcp_signal
from calibrate_strategy_evidence import attach_labels, code6, foundation_db_for, safe_float, ymd
from bootstrap_stats import metric_row, pct, fmt_num


OUT_DIR = ROOT / "outputs" / "strategy_evaluation"
PROJECT_OUT_DIR = ROOT / "outputs" / "project"

DEFAULT_ENTRY_SIGNALS = {"vcp_breakout", "vcp_breakout_weak_vol", "vcp_breakout_no_vol"}
KIMI_D1_STATES = {10, 12, 14}
KIMI_W1_STATES = {12, 14}
KIMI_MN1_STATES = {4, 12}


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
    return (
        abs(int(sample["d1_state"])) in KIMI_D1_STATES
        and abs(int(sample["w1_state"])) in KIMI_W1_STATES
        and abs(int(sample["mn1_state"])) in KIMI_MN1_STATES
    )


def load_vcp_samples(
    db_path: Path,
    start_date: str,
    end_date: str,
    raw_signals: set[str],
    min_ef_count: int | None = None,
    max_ef_count: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compute VCP signals and attach State combos/path features."""
    start = date.fromisoformat(start_date)
    warmup = (start - timedelta(days=180)).isoformat()
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
                MAX(high) OVER w5 AS high_5d,
                MIN(low) OVER w5 AS low_5d,
                MAX(high) OVER w20 AS high_20d,
                MIN(low) OVER w20 AS low_20d,
                MAX(high) OVER w10prev AS high_10d_prev,
                AVG(volume) OVER w50 AS avg_volume_50d
            FROM daily_bars
            WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
            WINDOW
                w5 AS (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
                w20 AS (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
                w10prev AS (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING),
                w50 AS (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW)
        ),
        state_enriched AS (
            SELECT
                *,
                d1_atr_ratio_pct * d1_close / 100.0 AS atr14,
                LAG(d1_atr_ratio_pct * d1_close / 100.0, 5) OVER w AS atr14_5d_ago,
                LAG(d1_atr_ratio_pct * d1_close / 100.0, 10) OVER w AS atr14_10d_ago,
                SUM(CASE WHEN ABS(d1_state_score) < 8 THEN 1 ELSE 0 END) OVER w5prev AS d1_contraction_count_5,
                SUM(CASE WHEN ABS(d1_state_score) < 8 THEN 1 ELSE 0 END) OVER w10prev AS d1_contraction_count_10,
                SUM(CASE WHEN ABS(d1_state_score) < 8 THEN 1 ELSE 0 END) OVER w20prev AS d1_contraction_count_20,
                SUM(CASE WHEN ABS(d1_state_score) >= 8 THEN 1 ELSE 0 END) OVER w5prev AS d1_expansion_count_5,
                SUM(CASE WHEN ABS(d1_state_score) >= 8 THEN 1 ELSE 0 END) OVER w10prev AS d1_expansion_count_10,
                SUM(CASE WHEN ABS(d1_state_score) >= 8 THEN 1 ELSE 0 END) OVER w20prev AS d1_expansion_count_20
            FROM d1_perspective_state
            WINDOW
                w AS (PARTITION BY stock_code ORDER BY state_date),
                w5prev AS (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
                w10prev AS (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING),
                w20prev AS (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
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
            s.atr14,
            s.atr14_5d_ago,
            s.atr14_10d_ago,
            s.d1_contraction_count_5,
            s.d1_contraction_count_10,
            s.d1_contraction_count_20,
            s.d1_expansion_count_5,
            s.d1_expansion_count_10,
            s.d1_expansion_count_20,
            b.open,
            b.high,
            b.low,
            b.close,
            b.volume,
            b.high_5d,
            b.low_5d,
            b.high_20d,
            b.low_20d,
            b.high_10d_prev,
            b.avg_volume_50d
        FROM state_enriched s
        JOIN bars_base b
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
            atr14,
            atr14_5d_ago,
            atr14_10d_ago,
            d1_contraction_count_5,
            d1_contraction_count_10,
            d1_contraction_count_20,
            d1_expansion_count_5,
            d1_expansion_count_10,
            d1_expansion_count_20,
            open_p,
            high,
            low,
            close,
            volume,
            high_5d,
            low_5d,
            high_20d,
            low_20d,
            high_10d,
            avg_volume_50d,
        ) = row
        row_payload = {"open": safe_float(open_p, 0.0), "close": safe_float(close, 0.0)}
        ctx = {
            "atr14": safe_float(atr14, 0.0),
            "atr14_5d_ago": safe_float(atr14_5d_ago, 0.0),
            "atr14_10d_ago": safe_float(atr14_10d_ago, 0.0),
            "high_5d": safe_float(high_5d, 0.0),
            "low_5d": safe_float(low_5d, 0.0),
            "high_20d": safe_float(high_20d, 0.0),
            "low_20d": safe_float(low_20d, 0.0),
            "high_10d": safe_float(high_10d, 0.0),
            "volume": safe_float(volume, 0.0),
            "volume_ma_50": safe_float(avg_volume_50d, 0.0),
        }
        signal = vcp_signal(row_payload, ctx)
        if not signal:
            continue
        signal_counts[signal[0]] += 1
        if signal[0] not in raw_signals:
            continue
        ef_count_value = int(ef_count or 0)
        if min_ef_count is not None and ef_count_value < min_ef_count:
            continue
        if max_ef_count is not None and ef_count_value > max_ef_count:
            continue
        d1_abs = abs(int(d1_state or 0))
        current_d1_expansion = d1_abs >= 8
        c5 = int(d1_contraction_count_5 or 0)
        c10 = int(d1_contraction_count_10 or 0)
        c20 = int(d1_contraction_count_20 or 0)
        sample = {
            "date": d,
            "stock_code": stock_code,
            "stock_code_6": code6(stock_code),
            "strategy_id": "vcp",
            "raw_signal": signal[0],
            "signal_name": "VCP突破确认",
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
            "d1_contraction_count_5": c5,
            "d1_contraction_count_10": c10,
            "d1_contraction_count_20": c20,
            "d1_expansion_count_5": int(d1_expansion_count_5 or 0),
            "d1_expansion_count_10": int(d1_expansion_count_10 or 0),
            "d1_expansion_count_20": int(d1_expansion_count_20 or 0),
        }
        sample["state_combo"] = combo_key(sample)
        sample["state_hex_combo"] = hex_combo_key(sample)
        sample["state_bit_signature"] = bit_signature(sample)
        sample["kimi_candidate_match"] = is_kimi_candidate(sample)
        sample["d1_10_12_14_match"] = d1_abs in KIMI_D1_STATES
        sample["contraction_release_5"] = current_d1_expansion and c5 > 0
        sample["contraction_release_10"] = current_d1_expansion and c10 > 0
        sample["contraction_release_20"] = current_d1_expansion and c20 > 0
        sample["current_expansion_no_contraction_20"] = current_d1_expansion and c20 == 0
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


def summarize_grouped(samples: list[dict[str, Any]], group_field: str, window: int, min_samples: int, top_n: int) -> list[dict[str, Any]]:
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
        "contraction_release_5": summarize_boolean_group(samples, "contraction_release_5", windows),
        "contraction_release_10": summarize_boolean_group(samples, "contraction_release_10", windows),
        "contraction_release_20": summarize_boolean_group(samples, "contraction_release_20", windows),
        "current_expansion_no_contraction_20": summarize_boolean_group(samples, "current_expansion_no_contraction_20", windows),
        "kimi_candidate": summarize_boolean_group(samples, "kimi_candidate_match", windows),
        "d1_10_12_14": summarize_boolean_group(samples, "d1_10_12_14_match", windows),
    }


def annotate_exact_combo(row: dict[str, Any]) -> dict[str, Any]:
    states = row["key"].split("/")
    if len(states) != 3:
        return row
    mn1, w1, d1 = [int(x) for x in states]
    sample = {"mn1_state": mn1, "w1_state": w1, "d1_state": d1}
    row["hex_combo"] = f"{state_hex(mn1)}/{state_hex(w1)}/{state_hex(d1)}"
    row["decoded"] = {"mn1": decode_state(mn1), "w1": decode_state(w1), "d1": decode_state(d1)}
    row["kimi_candidate_match"] = is_kimi_candidate(sample)
    return row


def run_search(args: argparse.Namespace) -> dict[str, Any]:
    windows = args.windows or [5, 10, 20]
    raw_signals = set(args.raw_signal or sorted(DEFAULT_ENTRY_SIGNALS))
    db_path = args.foundation_db or foundation_db_for(args.end_date)
    samples, diagnostics = load_vcp_samples(db_path, args.start_date, args.end_date, raw_signals, args.min_ef_count, args.max_ef_count)
    labeled, label_diag = attach_labels(samples, db_path, windows)
    primary = args.primary_window
    exact = [annotate_exact_combo(row) for row in summarize_grouped(labeled, "state_combo", primary, args.min_samples, args.top_n)]
    bit_rows = summarize_grouped(labeled, "state_bit_signature", primary, args.min_samples, args.top_n)
    all_exact_by_window = {
        f"{window}d": [annotate_exact_combo(row) for row in summarize_grouped(labeled, "state_combo", window, args.min_samples, args.top_n)]
        for window in windows
    }
    return {
        "schema_version": "vcp_optimal_state_search_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "question": "Do VCP entries work better after recent D1 compression release than static expansion-state matches?",
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
        "hypothesis_comparison": summarize_research_hypotheses(labeled, windows),
        "top_exact_combos_primary": exact,
        "top_bit_signatures_primary": bit_rows,
        "top_exact_combos_by_window": all_exact_by_window,
        "interpretation_boundaries": [
            "This is historical environment search, not a trading instruction.",
            "VCP is evaluated as a compression-release path, not a static State equality.",
            "KIMI candidate combos are hypotheses until reproduced locally with sample-out validation.",
            "State foundation and VCP core signal definitions are not modified by this script.",
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
        f"# VCP 最优 State 路径搜索 - {result['history']['end_date']}",
        "",
        f"- 历史区间: `{result['history']['start_date']}` 至 `{result['history']['end_date']}`",
        f"- Foundation DB: `{result['foundation_db']}`",
        f"- 信号口径: `{', '.join(result['selected_raw_signals'])}`",
        f"- 主观察窗口: `{result['primary_window']}d`",
        f"- 最小样本数: `{result['min_samples']}`",
        f"- 已标注样本: `{result['sample_counts']['labeled_samples']}` / `{result['sample_counts']['selected_samples']}`",
        f"- 已标注日期: `{result['sample_counts']['labeled_dates']}`",
        "",
        "## 研究假设对照",
        "",
    ]
    titles = {
        "contraction_release_5": "D1 近5日经历收缩后释放",
        "contraction_release_10": "D1 近10日经历收缩后释放",
        "contraction_release_20": "D1 近20日经历收缩后释放",
        "current_expansion_no_contraction_20": "当前扩张但近20日无收缩前兆",
        "kimi_candidate": "KIMI候选组合：D1∈{10,12,14}, W1∈{12,14}, MN1∈{4,12}",
        "d1_10_12_14": "D1 ∈ {10,12,14}",
    }
    for key, title in titles.items():
        lines.extend(render_hypothesis_table(title, result["hypothesis_comparison"][key], result["label_windows"]))
    lines.extend(
        [
            "## 精确 State 组合 Top",
            "",
            "| rank | MN1/W1/D1 | Hex | n | 平均超额 | 胜率 | t-stat | KIMI候选 | 解读 |",
            "|---:|---|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for idx, row in enumerate(result["top_exact_combos_primary"], 1):
        decoded = row.get("decoded", {})
        note = "；".join(f"{label}:{decoded.get(label, {}).get('label', '')}" for label in ["mn1", "w1", "d1"])
        lines.append(
            f"| {idx} | `{row['key']}` | `{row.get('hex_combo', '')}` | {row['n']} | {pct(row['mean_excess'])} | "
            f"{pct(row['win_rate'])} | {fmt_num(row['t_stat'])} | {'yes' if row.get('kimi_candidate_match') else 'no'} | {note} |"
        )
    lines.extend(["", "## 模糊 bit 形态 Top", "", "| rank | bit signature | n | 平均超额 | 胜率 | t-stat |", "|---:|---|---:|---:|---:|---:|"])
    for idx, row in enumerate(result["top_bit_signatures_primary"], 1):
        lines.append(f"| {idx} | `{row['key']}` | {row['n']} | {pct(row['mean_excess'])} | {pct(row['win_rate'])} | {fmt_num(row['t_stat'])} |")
    lines.extend(["", "## 边界", ""])
    for item in result["interpretation_boundaries"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def output_tag(result: dict[str, Any], date_tag: str) -> str:
    raw = "_".join(s.replace("vcp_", "") for s in result.get("selected_raw_signals", [])) or "entry"
    scope = "all"
    min_ef = result.get("diagnostics", {}).get("min_ef_count")
    max_ef = result.get("diagnostics", {}).get("max_ef_count")
    if min_ef is not None or max_ef is not None:
        scope = f"ef{'' if min_ef is None else min_ef}to{'' if max_ef is None else max_ef}"
    return f"{date_tag}_{raw}_{scope}"


def write_outputs(result: dict[str, Any], date_tag: str) -> dict[str, str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PROJECT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = output_tag(result, date_tag)
    json_path = OUT_DIR / f"vcp_optimal_state_search_{tag}.json"
    md_path = OUT_DIR / f"vcp_optimal_state_search_{tag}.md"
    project_md_path = PROJECT_OUT_DIR / "vcp_optimal_state_search.md"
    rendered = render_markdown(result)
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(rendered, encoding="utf-8")
    project_md_path.write_text(rendered, encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path), "project_markdown": str(project_md_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Search best MN1/W1/D1 State paths for VCP entry signals.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--foundation-db", type=Path)
    parser.add_argument("--raw-signal", action="append", default=[], help="VCP raw signal to include. Repeatable.")
    parser.add_argument("--windows", type=int, nargs="*", default=[5, 10, 20])
    parser.add_argument("--primary-window", type=int, default=20)
    parser.add_argument("--min-samples", type=int, default=30)
    parser.add_argument("--min-ef-count", type=int, help="Optional minimum ef_count filter for the signal date.")
    parser.add_argument("--max-ef-count", type=int, help="Optional maximum ef_count filter for the signal date.")
    parser.add_argument("--top-n", type=int, default=30)
    args = parser.parse_args()
    if not args.raw_signal:
        args.raw_signal = sorted(DEFAULT_ENTRY_SIGNALS)
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
