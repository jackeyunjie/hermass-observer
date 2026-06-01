#!/usr/bin/env python3
"""MN1-stratified signal calibration from historical optimal-state search data.

Reads strategy_evaluation JSON files, extracts per-strategy hex combo data,
classifies each combo by MN1 regime, and outputs stratified calibration statistics.

Output: outputs/calibration/mn1_stratified_calibration.json
"""

import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "outputs" / "strategy_evaluation"
OUT_DIR = ROOT / "outputs" / "calibration"
OUT_DIR.mkdir(parents=True, exist_ok=True)

INPUT_FILES = {
    "vcp": EVAL_DIR / "vcp_optimal_state_search_20260501_breakout_breakout_no_vol_breakout_weak_vol_all.json",
    "ma2560": EVAL_DIR / "ma2560_optimal_state_search_20260501_golden_cross_all.json",
    "bollinger_bandit": EVAL_DIR / "bollinger_optimal_state_search_20260501_entry_all.json",
}

HEX_TO_SCORE = {
    "0": 0,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "A": 10,
    "B": 11,
    "C": 12,
    "D": 13,
    "E": 14,
    "F": 15,
    "-1": -1,
    "-2": -2,
    "-3": -3,
    "-C": -12,
    "-E": -14,
    "-F": -15,
}


def _mn1_score_from_hex(hex_combo: str) -> int | None:
    parts = hex_combo.split("/")
    if len(parts) < 1:
        return None
    mn1_hex = parts[0].strip()
    return HEX_TO_SCORE.get(mn1_hex)


def _classify_regime(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score < 0:
        return "破位环境"
    if score in (14, 15):
        return "牛市环境_E/F"
    if score >= 12:
        return "震荡偏强_C/D"
    if score >= 8:
        return "扩张未突破_8-B"
    return "收缩环境_0-7"


def load_combo_data(path: Path) -> list[dict]:
    if not path.exists():
        return []
    d = json.loads(path.read_text())
    combos = d.get("top_exact_combos_primary", [])
    return [
        {
            "hex_combo": c.get("hex_combo", ""),
            "n": c.get("n", 0),
            "mean_excess": c.get("mean_excess"),
            "win_rate": c.get("win_rate"),
            "t_stat": c.get("t_stat"),
            "payoff_ratio": c.get("payoff_ratio"),
            "decoded": c.get("decoded", ""),
        }
        for c in combos
        if c.get("n", 0) >= 5
    ]


def compute_mn1_stratified(strategy_id: str, combos: list[dict]) -> dict:
    regime_data: dict[str, dict] = defaultdict(
        lambda: {
            "weighted_mean_excess": 0.0,
            "weighted_n": 0,
            "total_n": 0,
            "win_rate_samples": [],
            "t_stats": [],
            "combos": 0,
        }
    )

    for c in combos:
        mn1_score = _mn1_score_from_hex(c["hex_combo"])
        regime = _classify_regime(mn1_score)
        n = c.get("n", 0)
        me = c.get("mean_excess")
        wr = c.get("win_rate")
        ts = c.get("t_stat")

        rd = regime_data[regime]
        rd["combos"] += 1
        rd["total_n"] += n
        if me is not None:
            rd["weighted_mean_excess"] += me * n
        rd["weighted_n"] += n
        if wr is not None:
            rd["win_rate_samples"].append((wr, n))
        if ts is not None:
            rd["t_stats"].append(ts)

    result = {}
    for regime, rd in sorted(regime_data.items()):
        wme = rd["weighted_mean_excess"] / max(rd["weighted_n"], 1)
        avg_wr = (
            sum(wr * n for wr, n in rd["win_rate_samples"])
            / max(sum(n for _, n in rd["win_rate_samples"]), 1)
            if rd["win_rate_samples"]
            else 0
        )
        avg_t = statistics.mean(rd["t_stats"]) if rd["t_stats"] else 0

        quality = "高"
        if avg_t < 1.0 or rd["total_n"] < 50:
            quality = "低"
        elif avg_t < 2.0:
            quality = "中"

        result[regime] = {
            "strategy_id": strategy_id,
            "regime": regime,
            "regime_label": _regime_label(regime),
            "sample_combos": rd["combos"],
            "total_samples": rd["total_n"],
            "weighted_mean_excess": round(wme, 4),
            "avg_win_rate": round(avg_wr, 4),
            "avg_t_stat": round(avg_t, 2),
            "signal_quality": quality,
        }
    return result


def _regime_label(regime: str) -> str:
    labels = {
        "牛市环境_E/F": "MN1=E/F：牛市确认",
        "震荡偏强_C/D": "MN1=C/D：震荡偏强",
        "扩张未突破_8-B": "MN1=8-B：扩张未突破",
        "收缩环境_0-7": "MN1=0-7：熊市/收缩",
        "破位环境": "MN1负值：月线破位",
        "unknown": "无法分类",
    }
    return labels.get(regime, regime)


def main():
    all_strategy_results = {}
    overview_rows = []

    for strategy_id, path in INPUT_FILES.items():
        combos = load_combo_data(path)
        if not combos:
            print(f"  {strategy_id}: no data")
            continue

        stratified = compute_mn1_stratified(strategy_id, combos)
        all_strategy_results[strategy_id] = stratified

        print(f"\n{'=' * 65}")
        print(f"  {strategy_id.upper()} — MN1 环境分层校准")
        print(f"  {len(combos)} 个 Hex 组合 (n≥5), 可用")
        print(f"{'=' * 65}")
        print(f"  {'环境':16s} {'样本':>6s} {'超额':>8s} {'胜率':>7s} {'t-stat':>6s} {'质量':>4s}")
        print(f"  {'-' * 50}")

        for regime in ["牛市环境_E/F", "震荡偏强_C/D", "扩张未突破_8-B", "收缩环境_0-7", "破位环境"]:
            rd = stratified.get(regime)
            if rd:
                print(
                    f"  {rd['regime_label'][:14]:14s} {rd['total_samples']:>6d} {rd['weighted_mean_excess']:>8.4f} {rd['avg_win_rate']:>7.4f} {rd['avg_t_stat']:>6.2f} {rd['signal_quality']:>4s}"
                )
                overview_rows.append(rd)

    output = {
        "schema_version": "mn1_stratified_calibration_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "data_source": "strategy_evaluation optimal state search (2025-06 to 2026-05)",
        "regime_definitions": {
            "牛市环境_E/F": "MN1 state score in (14, 15): expansion + trend + breakout",
            "震荡偏强_C/D": "MN1 state score in (12, 13): expansion + trend, not yet breakout",
            "扩张未突破_8-B": "MN1 state score in (8, 11): expansion without trend breakout",
            "收缩环境_0-7": "MN1 state score in (0, 7): contraction phase",
            "破位环境": "MN1 state score < 0: breakdown below support",
        },
        "stratified_results": all_strategy_results,
        "overview": sorted(overview_rows, key=lambda x: -x["total_samples"]),
        "key_findings": _key_findings(all_strategy_results),
    }

    out_path = OUT_DIR / "mn1_stratified_calibration.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n报告已输出: {out_path}")


def _key_findings(results: dict) -> list[str]:
    findings = []
    for sid, stratified in results.items():
        bull = stratified.get("牛市环境_E/F", {})
        breakdown = stratified.get("破位环境", {})
        if bull.get("total_samples", 0) > 0 and breakdown.get("total_samples", 0) > 0:
            bull_me = bull.get("weighted_mean_excess", 0)
            bd_me = breakdown.get("weighted_mean_excess", 0)
            if bull_me > 0 and bd_me < bull_me:
                findings.append(
                    f"{sid}: 牛市 MN1(E/F) 超额={bull_me:.4f} vs 破位超额={bd_me:.4f} "
                    f"→ 分层有效，破位环境信号应自动降噪"
                )
    return findings


if __name__ == "__main__":
    main()
