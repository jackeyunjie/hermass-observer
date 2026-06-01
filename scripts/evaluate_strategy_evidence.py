#!/usr/bin/env python3
"""Evaluate daily strategy evidence from materialized caches.

This is a read-only research layer. It consumes State cache, strategy evidence,
and pattern lifecycle outputs to produce a compact opportunity brief for UI and
Agently research flows. It does not generate trading advice or write back to
foundation/fundamental facts.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


SCORING_VERSION = "strategy_evidence_scoring_v1_uncalibrated"
TIER_THRESHOLDS = {"A": 82.0, "B": 70.0, "C": 58.0}
STATE_HEX_SCORE = {
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
}


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def code6(value: Any) -> str:
    text = str(value or "").upper().strip()
    digits = "".join(ch for ch in text.split(".", 1)[0] if ch.isdigit())
    return digits[-6:] if digits else text


def load_json(path: Path, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def default_paths(date_str: str) -> dict[str, Path]:
    date_ymd = ymd(date_str)
    return {
        "state_ef": ROOT / "outputs" / "state_cache" / f"state_ef_{date_ymd}.json",
        "state_transition": ROOT / "outputs" / "state_cache" / f"state_transition_{date_ymd}.json",
        "state_duration": ROOT / "outputs" / "state_cache" / f"state_duration_{date_ymd}.json",
        "strategy_evidence": ROOT / "outputs" / "strategy_evidence" / f"strategy_evidence_{date_ymd}.json",
        "pattern_cross": ROOT / "outputs" / "pattern_lifecycle" / f"pattern_cross_ef_{date_ymd}.json",
        "stock_ledger": ROOT / "outputs" / "fundamental" / f"stock_research_ledger_{date_ymd}.json",
    }


def build_transition_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        out[code6(row.get("stock_code"))][str(row.get("period") or "")] = row
    return out


def build_duration_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {code6(row.get("stock_code")): row for row in rows}


def build_pattern_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for section in ["ef_with_structure", "vcp_entered_ef", "golden_cross_ef"]:
        for row in payload.get(section, []) or []:
            key = code6(row.get("stock_code"))
            out.setdefault(key, {})[section] = row
    return out


def build_ledger_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {code6(row.get("stock_code")): row for row in payload.get("rows", []) or []}


def state_int(value: Any, score: Any) -> int:
    text = str(value or "").upper().strip()
    if text in STATE_HEX_SCORE:
        return STATE_HEX_SCORE[text]
    return safe_int(score)


def state_bits(value: int) -> dict[str, float]:
    return {
        "expansion": 1.0 if value & 8 else 0.0,
        "trend": 1.0 if value & 4 else 0.0,
        "position": 1.0 if value & 2 else 0.0,
        "volatility": 1.0 if value & 1 else 0.0,
    }


def decay_recent(days: int, horizon: int = 20) -> float:
    if days <= 0:
        return 0.0
    return max(0.0, 1.0 - min(1.0, (days - 1) / horizon))


def build_environment_tags(
    *,
    volatility_ratio: float,
    volatility_stability: float,
    d1_recent_exit: float,
    d1_prior_depth: float,
    w1_recent_exit: float,
    mn1_recent_exit: float,
    all_three_ef_duration: int,
) -> list[str]:
    """Describe the State environment without turning it into a signal."""

    tags: list[str] = []
    if volatility_stability >= 0.95:
        tags.append("波动稳定")
    elif volatility_ratio >= 0.6667:
        tags.append("波动偏活跃")

    if d1_recent_exit >= 0.65:
        tags.append("D1刚脱离收缩")
    if d1_prior_depth >= 0.50:
        tags.append("D1收缩充分")
    if w1_recent_exit >= 0.65:
        tags.append("W1刚脱离收缩")
    if mn1_recent_exit >= 0.65:
        tags.append("MN1刚脱离收缩")

    if 0 < all_three_ef_duration <= 3:
        tags.append("三周期共振新近形成")
    elif all_three_ef_duration >= 20:
        tags.append("三周期共振延续")

    return tags


def score_row(
    state_row: dict[str, Any],
    strategy_row: dict[str, Any] | None,
    transitions: dict[str, dict[str, Any]],
    duration: dict[str, Any] | None,
    pattern: dict[str, Any],
    ledger: dict[str, Any] | None,
) -> dict[str, Any]:
    state_score = safe_float(state_row.get("score_sum"))
    ef_count = safe_int(state_row.get("ef_count"))
    strategy_score = safe_float((strategy_row or {}).get("strategy_score"))
    vcp_hits = safe_int((strategy_row or {}).get("vcp_hits_lookback"))
    ma_hits = safe_int((strategy_row or {}).get("ma2560_hits_lookback"))

    d1_transition = transitions.get("d1", {})
    w1_transition = transitions.get("w1", {})
    transition_bonus = 0.0
    transition_labels: list[str] = []
    for period, item in [("d1", d1_transition), ("w1", w1_transition)]:
        if not item:
            continue
        from_state = item.get("from_state")
        to_state = item.get("to_state")
        from_score = safe_float(item.get("from_score"))
        to_score = safe_float(item.get("to_score"))
        if to_score > from_score:
            transition_bonus += 5.0 if period == "d1" else 3.0
            transition_labels.append(f"{period}:{from_state}->{to_state}")
        elif to_score < from_score:
            transition_bonus -= 4.0 if period == "d1" else 2.0
            transition_labels.append(f"{period}:{from_state}->{to_state}")

    structure_score = 0.0
    structure_labels: list[str] = []
    ef_structure = pattern.get("ef_with_structure")
    if ef_structure:
        stype = ef_structure.get("structure_type") or ""
        if stype == "dual_structure":
            structure_score += 18.0
        elif stype == "vcp_only":
            structure_score += 10.0
        elif stype == "ma2560_only":
            structure_score += 8.0
        structure_labels.append(stype)
    if pattern.get("vcp_entered_ef"):
        structure_score += 8.0
        structure_labels.append("vcp_entered_ef")
    if pattern.get("golden_cross_ef"):
        structure_score += 12.0
        structure_labels.append("golden_cross_ef")

    ledger_score = 0.0
    ledger_note = ""
    if ledger:
        ledger_score = min(5.0, safe_float(ledger.get("confidence")) * 5.0)
        ledger_note = str(ledger.get("chief_insight") or "")[:140]

    state_points = min(45.0, state_score)
    strategy_signal_points = min(30.0, strategy_score * 0.30)
    strategy_persistence_points = min(10.0, (vcp_hits + ma_hits) * 2.0)
    strategy_points = strategy_signal_points + strategy_persistence_points
    pattern_points = structure_score
    transition_points = transition_bonus
    fundamental_points = ledger_score

    duration = duration or {}
    d1_days_since_exit = safe_int(duration.get("d1_days_since_contraction_exit"))
    w1_days_since_exit = safe_int(duration.get("w1_days_since_contraction_exit"))
    mn1_days_since_exit = safe_int(duration.get("mn1_days_since_contraction_exit"))
    d1_prev_contraction = safe_int(duration.get("d1_prev_contraction_duration"))
    w1_prev_contraction = safe_int(duration.get("w1_prev_contraction_duration"))
    mn1_prev_contraction = safe_int(duration.get("mn1_prev_contraction_duration"))
    lifecycle_points = 0.0
    lifecycle_labels: list[str] = []
    if 0 < d1_days_since_exit <= 5:
        lifecycle_points += 3.0
        lifecycle_labels.append("d1_recent_contraction_exit")
    if d1_prev_contraction >= 5:
        lifecycle_points += 2.0
        lifecycle_labels.append("d1_prior_contraction")

    mn1_value = state_int(state_row.get("mn1_state_hex"), state_row.get("mn1_state_score"))
    w1_value = state_int(state_row.get("w1_state_hex"), state_row.get("w1_state_score"))
    d1_value = state_int(state_row.get("d1_state_hex"), state_row.get("d1_state_score"))
    bit_rows = [state_bits(mn1_value), state_bits(w1_value), state_bits(d1_value)]
    expansion_ratio = sum(item["expansion"] for item in bit_rows) / 3.0
    trend_ratio = sum(item["trend"] for item in bit_rows) / 3.0
    position_ratio = sum(item["position"] for item in bit_rows) / 3.0
    volatility_ratio = sum(item["volatility"] for item in bit_rows) / 3.0
    ef_purity = sum(1 for value in [mn1_value, w1_value, d1_value] if value == 15) / 3.0
    d1_recent_exit = decay_recent(d1_days_since_exit)
    w1_recent_exit = decay_recent(w1_days_since_exit)
    mn1_recent_exit = decay_recent(mn1_days_since_exit)
    d1_prior_depth = min(1.0, d1_prev_contraction / 20.0)
    w1_prior_depth = min(1.0, w1_prev_contraction / 20.0)
    mn1_prior_depth = min(1.0, mn1_prev_contraction / 20.0)
    volatility_stability = 1.0 - (volatility_ratio * 0.5)
    all_three_ef_duration = safe_int(duration.get("all_three_ef_duration"))
    environment_tags = build_environment_tags(
        volatility_ratio=volatility_ratio,
        volatility_stability=volatility_stability,
        d1_recent_exit=d1_recent_exit,
        d1_prior_depth=d1_prior_depth,
        w1_recent_exit=w1_recent_exit,
        mn1_recent_exit=mn1_recent_exit,
        all_three_ef_duration=all_three_ef_duration,
    )
    # In the all-three E/F pool, expansion/trend/position are mostly constant.
    # Diagnostics show that stable volatility and a sufficiently deep prior D1
    # contraction carry more information than simply having more F states.
    state_component = (
        0.40 * volatility_stability + 0.30 * d1_prior_depth + 0.20 * d1_recent_exit + 0.10 * w1_recent_exit
    )
    state_component = max(0.0, min(1.0, state_component))
    state_points = state_component * 45.0

    total = state_points + strategy_points + pattern_points + transition_points + fundamental_points
    total = round(max(0.0, min(100.0, total)), 2)

    if total >= TIER_THRESHOLDS["A"]:
        tier = "A"
    elif total >= TIER_THRESHOLDS["B"]:
        tier = "B"
    elif total >= TIER_THRESHOLDS["C"]:
        tier = "C"
    else:
        tier = "watch"

    code = state_row.get("stock_code")
    factor_breakdown = {
        "schema_version": "strategy_factor_breakdown_v1",
        "components_0_1": {
            "state": round(state_component, 4),
            "strategy": round(min(1.0, strategy_points / 40.0), 4),
            "pattern": round(min(1.0, pattern_points / 30.0), 4),
            "transition": round(max(0.0, min(1.0, transition_points / 8.0)), 4),
            "fundamental": round(min(1.0, fundamental_points / 5.0), 4),
        },
        "state_lifecycle_0_1": {
            "ef_purity": round(ef_purity, 4),
            "expansion_ratio": round(expansion_ratio, 4),
            "trend_ratio": round(trend_ratio, 4),
            "position_ratio": round(position_ratio, 4),
            "volatility_ratio": round(volatility_ratio, 4),
            "volatility_stability": round(volatility_stability, 4),
            "d1_recent_contraction_exit": round(d1_recent_exit, 4),
            "d1_prior_contraction_depth": round(d1_prior_depth, 4),
            "w1_recent_contraction_exit": round(w1_recent_exit, 4),
            "w1_prior_contraction_depth": round(w1_prior_depth, 4),
            "mn1_recent_contraction_exit": round(mn1_recent_exit, 4),
            "mn1_prior_contraction_depth": round(mn1_prior_depth, 4),
        },
        "points": {
            "state": round(state_points, 4),
            "state_lifecycle": round(lifecycle_points, 4),
            "strategy_signal": round(strategy_signal_points, 4),
            "strategy_persistence": round(strategy_persistence_points, 4),
            "strategy_total": round(strategy_points, 4),
            "pattern": round(pattern_points, 4),
            "transition": round(transition_points, 4),
            "fundamental": round(fundamental_points, 4),
        },
        "raw_inputs": {
            "state_score_sum": state_score,
            "strategy_score": strategy_score,
            "vcp_hits_lookback": vcp_hits,
            "ma2560_hits_lookback": ma_hits,
            "ef_count": ef_count,
            "mn1_state_int": mn1_value,
            "w1_state_int": w1_value,
            "d1_state_int": d1_value,
            "mn1_ef_duration": safe_int(duration.get("mn1_ef_duration")),
            "w1_ef_duration": safe_int(duration.get("w1_ef_duration")),
            "d1_ef_duration": safe_int(duration.get("d1_ef_duration")),
            "all_three_ef_duration": all_three_ef_duration,
            "mn1_contraction_duration": safe_int(duration.get("mn1_contraction_duration")),
            "w1_contraction_duration": safe_int(duration.get("w1_contraction_duration")),
            "d1_contraction_duration": safe_int(duration.get("d1_contraction_duration")),
            "mn1_days_since_contraction_exit": mn1_days_since_exit,
            "w1_days_since_contraction_exit": w1_days_since_exit,
            "d1_days_since_contraction_exit": d1_days_since_exit,
            "mn1_prev_contraction_duration": mn1_prev_contraction,
            "w1_prev_contraction_duration": w1_prev_contraction,
            "d1_prev_contraction_duration": d1_prev_contraction,
            "ledger_confidence": safe_float((ledger or {}).get("confidence")),
        },
        "labels": {
            "structure": [label for label in structure_labels if label],
            "transition": transition_labels,
            "state_lifecycle": lifecycle_labels,
            "environment": environment_tags,
        },
        "scoring_version": SCORING_VERSION,
    }
    return {
        "stock_code": code,
        "stock_code_6": code6(code),
        "stock_name": (strategy_row or {}).get("stock_name") or "",
        "sw_l1": (strategy_row or {}).get("sw_l1") or "",
        "sw_l2": (strategy_row or {}).get("sw_l2") or "",
        "date": state_row.get("obs_date"),
        "state": f"{state_row.get('mn1_state_hex')}/{state_row.get('w1_state_hex')}/{state_row.get('d1_state_hex')}",
        "state_score_sum": state_score,
        "ef_count": ef_count,
        "d1_close": state_row.get("d1_close"),
        "strategy_score": strategy_score,
        "best_selection_signal": (strategy_row or {}).get("best_selection_signal") or "",
        "latest_vcp_signal": (strategy_row or {}).get("latest_vcp_signal") or "",
        "latest_2560_signal": (strategy_row or {}).get("latest_2560_signal") or "",
        "vcp_hits_lookback": vcp_hits,
        "ma2560_hits_lookback": ma_hits,
        "structure_labels": ",".join(label for label in structure_labels if label),
        "transition_labels": ",".join(transition_labels),
        "environment_tags": ",".join(environment_tags),
        "factor_breakdown": factor_breakdown,
        "evidence_score": total,
        "evidence_tier": tier,
        "research_note": build_note(strategy_row, structure_labels, transition_labels, ledger_note),
    }


def build_note(
    strategy_row: dict[str, Any] | None,
    structure_labels: list[str],
    transition_labels: list[str],
    ledger_note: str,
) -> str:
    parts: list[str] = []
    if strategy_row and strategy_row.get("selection_note"):
        parts.append(str(strategy_row.get("selection_note")))
    if structure_labels:
        parts.append("长期结构=" + "/".join(label for label in structure_labels if label))
    if transition_labels:
        parts.append("状态转换=" + "/".join(transition_labels))
    if ledger_note:
        parts.append("基本面账本=" + ledger_note)
    if not parts:
        parts.append("仅有三周期 E/F 状态，暂无额外策略或结构证据")
    return "；".join(parts)


def evaluate(date_str: str, top_n: int = 80, paths: dict[str, Path] | None = None) -> dict[str, Any]:
    paths = paths or default_paths(date_str)
    state_ef = load_json(paths["state_ef"])
    transition = load_json(paths["state_transition"])
    duration = load_json(paths["state_duration"], required=False)
    strategy = load_json(paths["strategy_evidence"], required=False)
    pattern = load_json(paths["pattern_cross"], required=False)
    ledger = load_json(paths["stock_ledger"], required=False)

    strategy_map = {
        code6(row.get("stock_code") or row.get("symbol")): row for row in strategy.get("rows", []) or []
    }
    transition_map = build_transition_map(transition.get("rows", []) or [])
    duration_map = build_duration_map(duration.get("rows", []) or [])
    pattern_map = build_pattern_map(pattern)
    ledger_map = build_ledger_map(ledger)

    rows = []
    for state_row in state_ef.get("rows", []) or []:
        key = code6(state_row.get("stock_code"))
        rows.append(
            score_row(
                state_row,
                strategy_map.get(key),
                transition_map.get(key, {}),
                duration_map.get(key),
                pattern_map.get(key, {}),
                ledger_map.get(key),
            )
        )

    rows.sort(
        key=lambda r: (
            -safe_float(r["evidence_score"]),
            -safe_float(r["strategy_score"]),
            str(r["stock_code"]),
        )
    )
    for idx, row in enumerate(rows, 1):
        row["evidence_rank"] = idx

    top_rows = rows[:top_n]
    tier_counts = Counter(row["evidence_tier"] for row in rows)
    industry_counts = Counter(row["sw_l1"] or "unknown" for row in top_rows)
    signal_counts = Counter(row["best_selection_signal"] or "structure_only" for row in rows)

    return {
        "schema_version": "strategy_evidence_evaluation_v1",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_paths": {k: str(v) for k, v in paths.items()},
        "selection_scope": "state_cache all-three E/F raw set",
        "scoring_note": "Research-only evidence ranking. Consumes cached facts and strategy evidence; does not create trading signals.",
        "scoring_version": SCORING_VERSION,
        "thresholds": TIER_THRESHOLDS,
        "factor_schema": {
            "components_0_1": ["state", "strategy", "pattern", "transition", "fundamental"],
            "state_lifecycle_0_1": [
                "volatility_stability",
                "d1_recent_contraction_exit",
                "d1_prior_contraction_depth",
                "w1_recent_contraction_exit",
                "w1_prior_contraction_depth",
                "mn1_recent_contraction_exit",
                "mn1_prior_contraction_depth",
            ],
            "environment_labels": [
                "波动稳定",
                "波动偏活跃",
                "D1刚脱离收缩",
                "D1收缩充分",
                "W1刚脱离收缩",
                "MN1刚脱离收缩",
                "三周期共振新近形成",
                "三周期共振延续",
            ],
            "points": [
                "state",
                "state_lifecycle",
                "strategy_signal",
                "strategy_persistence",
                "strategy_total",
                "pattern",
                "transition",
                "fundamental",
            ],
            "calibration_status": "uncalibrated",
        },
        "total": len(rows),
        "top_n": top_n,
        "tier_counts": dict(tier_counts),
        "top_industries": dict(industry_counts.most_common(12)),
        "signal_counts": dict(signal_counts),
        "rows": rows,
        "top_rows": top_rows,
        "research_only": True,
    }


def write_outputs(payload: dict[str, Any], date_str: str) -> dict[str, str]:
    out_dir = ROOT / "outputs" / "strategy_evaluation"
    pub_dir = ROOT / "public"
    out_dir.mkdir(parents=True, exist_ok=True)
    pub_dir.mkdir(parents=True, exist_ok=True)
    date_ymd = ymd(date_str)

    json_path = out_dir / f"strategy_evaluation_{date_ymd}.json"
    csv_path = out_dir / f"strategy_evaluation_{date_ymd}.csv"
    html_path = pub_dir / f"strategy_evaluation_{date_ymd}.html"
    latest_json = out_dir / "strategy_evaluation_latest.json"
    latest_html = pub_dir / "strategy_evaluation_latest.html"

    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json.write_text(json_text, encoding="utf-8")

    fields = [
        "evidence_rank",
        "stock_code",
        "stock_name",
        "sw_l1",
        "sw_l2",
        "state",
        "state_score_sum",
        "strategy_score",
        "best_selection_signal",
        "latest_vcp_signal",
        "latest_2560_signal",
        "structure_labels",
        "transition_labels",
        "environment_tags",
        "state_component",
        "strategy_component",
        "pattern_component",
        "transition_component",
        "fundamental_component",
        "evidence_score",
        "evidence_tier",
        "research_note",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flatten_row_for_csv(row) for row in payload["rows"])

    html_text = render_html(payload, fields)
    html_path.write_text(html_text, encoding="utf-8")
    latest_html.write_text(html_text, encoding="utf-8")
    return {
        "json": str(json_path),
        "csv": str(csv_path),
        "html": str(html_path),
        "latest_json": str(latest_json),
        "latest_html": str(latest_html),
    }


def flatten_row_for_csv(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    components = row.get("factor_breakdown", {}).get("components_0_1", {})
    out["state_component"] = components.get("state", "")
    out["strategy_component"] = components.get("strategy", "")
    out["pattern_component"] = components.get("pattern", "")
    out["transition_component"] = components.get("transition", "")
    out["fundamental_component"] = components.get("fundamental", "")
    return out


def render_html(payload: dict[str, Any], fields: list[str]) -> str:
    rows = payload["top_rows"]
    head = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
    body = []
    for row in rows:
        tier = row.get("evidence_tier", "")
        flat = flatten_row_for_csv(row)
        body.append(
            f"<tr class='tier-{html.escape(str(tier).lower())}'>"
            + "".join(f"<td>{html.escape(str(flat.get(field, '')))}</td>" for field in fields)
            + "</tr>"
        )
    kpis = [
        ("All-three E/F", payload["total"]),
        ("Top Rows", len(rows)),
        ("Tier A", payload["tier_counts"].get("A", 0)),
        ("Tier B", payload["tier_counts"].get("B", 0)),
    ]
    kpi_html = "".join(
        f"<div class='kpi'><small>{html.escape(label)}</small><strong>{value}</strong></div>"
        for label, value in kpis
    )
    industries = " / ".join(f"{k}:{v}" for k, v in payload["top_industries"].items())
    signals = " / ".join(f"{k}:{v}" for k, v in payload["signal_counts"].items())
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>策略证据评估 - {html.escape(payload["date"])}</title>
  <style>
    body {{ margin:0; padding:24px; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif; color:#17212b; background:#f7f8f6; }}
    header, section {{ background:#fff; border:1px solid #dce4df; border-radius:8px; padding:18px; margin-bottom:16px; }}
    h1 {{ margin:0 0 8px; font-size:24px; }}
    p {{ color:#526071; line-height:1.55; }}
    .kpis {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }}
    .kpi {{ border:1px solid #dce4df; border-radius:8px; padding:10px 12px; min-width:130px; background:#fbfcfb; }}
    .kpi small {{ display:block; color:#64748b; }}
    .kpi strong {{ font-size:22px; }}
    .table-wrap {{ overflow:auto; border:1px solid #dce4df; max-height:76vh; }}
    table {{ border-collapse:collapse; width:100%; font-size:12px; }}
    th, td {{ border-bottom:1px solid #e4e9ef; padding:7px 8px; text-align:left; vertical-align:top; }}
    th {{ background:#f4f7f8; position:sticky; top:0; z-index:1; }}
    tr.tier-a td:first-child {{ border-left:4px solid #0f8b57; }}
    tr.tier-b td:first-child {{ border-left:4px solid #2563eb; }}
    tr.tier-c td:first-child {{ border-left:4px solid #d97706; }}
    .note {{ font-size:12px; color:#637083; }}
  </style>
</head>
<body>
  <header>
    <h1>策略证据评估</h1>
    <p>{html.escape(payload["date"])} · 只读消费 State 缓存、VCP/2560 证据、长期形态与基本面账本。Research-only，不构成投资建议。</p>
    <div class="kpis">{kpi_html}</div>
  </header>
  <section>
    <p><strong>Top industries:</strong> {html.escape(industries)}</p>
    <p><strong>Signals:</strong> {html.escape(signals)}</p>
    <p class="note">{html.escape(payload["scoring_note"])}</p>
  </section>
  <section>
    <div class="table-wrap">
      <table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>
    </div>
  </section>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate strategy evidence from State cache and related read-only outputs."
    )
    parser.add_argument("--date", required=True)
    parser.add_argument("--top-n", type=int, default=80)
    args = parser.parse_args()

    payload = evaluate(args.date, max(1, args.top_n))
    outputs = write_outputs(payload, args.date)
    print(
        json.dumps(
            {
                "ok": True,
                "date": args.date,
                "total": payload["total"],
                "tier_counts": payload["tier_counts"],
                "top_industries": payload["top_industries"],
                "outputs": outputs,
                "research_only": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
