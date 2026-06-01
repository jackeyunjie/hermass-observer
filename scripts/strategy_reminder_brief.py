#!/usr/bin/env python3
"""Assemble the daily strategy reminder brief.

This is a pure read-only composition layer. It consumes the normalized strategy
signal ledger, State cache, SR boundary cache, optional fundamental ledger, and
optional calibration output. It does not calculate strategy triggers, infer
missing signals, or write back to source fact tables.
"""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from w1_mn1_env_label import compute_w1_mn1_env_label


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "outputs"
REMINDER_DIR = OUTPUT_ROOT / "strategy_reminders"
PUBLIC_DIR = ROOT / "public"
VCP_RULE_PATH = ROOT / "config" / "vcp_state_market_match_rule.json"

ALLOWED_MATURITY_LABELS = {"趋势新生", "趋势行进", "趋势延展", "防守参考线", "状态值得复核"}
ENTRY_MATURITY = "趋势新生"
MA2560_MATCH_LABELS = {
    "full_match": "2560 full_match",
    "stock_only": "2560 stock_only",
    "market_unsupported": "2560 market_unsupported",
    "not_match": "2560 not_match",
}
VCP_VALIDATED_SUMMARY_FALLBACK = (
    "本地验证有效：D1近20日收缩后释放；10日平均超额+2.30%，20日平均超额+4.69%，20日胜率56.16%。"
)
BOLLINGER_VOL_STABLE_NOTE = (
    "本地统计提示：波动稳定环境下，布林强盗信号历史表现优于波动活跃环境（+0.59% vs -0.49%）"
)
BOLLINGER_VOL_ACTIVE_NOTE = "当前波动活跃，历史上此环境下布林强盗信号表现较弱"

# Mark Minervini 外部验证数据（来自 MARK_MINERVINI_STATE_MATCH_ANALYSIS.md）
MINERVINI_ENV_MATCH_TEXT = "外部验证：该环境与 Mark Minervini 72.4% 的交易选择一致"

# Nicolas Darvas 外部验证数据（来自 DARVAS_2560_STATE_MATCH_ANALYSIS.md）
DARVAS_ENV_MATCH_TEXT = "外部验证：该环境与 Nicolas Darvas 79.3% 的交易选择一致"

# John Bollinger 外部验证数据（来自 BOLLINGER_BANDIT_STATE_MATCH_ANALYSIS.md）
BOLLINGER_ENV_MATCH_TEXT = "外部验证：该环境与 John Bollinger 73.5% 的交易选择一致"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def code6(value: Any) -> str:
    text = str(value or "").upper().strip()
    digits = "".join(ch for ch in text.split(".", 1)[0] if ch.isdigit())
    return digits[-6:] if digits else text


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def load_json(path: Path, required: bool = False) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_matched_pattern(raw: Any) -> dict[str, Any] | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return None


def load_vcp_rule(path: Path = VCP_RULE_PATH) -> dict[str, Any]:
    return load_json(path, required=False)


def default_paths(date_str: str) -> dict[str, Path]:
    date_ymd = ymd(date_str)
    return {
        "signals": OUTPUT_ROOT / "strategy_signals" / f"strategy_signal_daily_{date_ymd}.json",
        "state_ef": OUTPUT_ROOT / "state_cache" / f"state_ef_{date_ymd}.json",
        "state_duration": OUTPUT_ROOT / "state_cache" / f"state_duration_{date_ymd}.json",
        "sr_boundary": OUTPUT_ROOT / "state_cache" / f"sr_boundary_{date_ymd}.json",
        "fundamental_ledger": OUTPUT_ROOT / "fundamental" / f"stock_research_ledger_{date_ymd}.json",
        "strategy_evaluation": OUTPUT_ROOT / "strategy_evaluation" / f"strategy_evaluation_{date_ymd}.json",
        "calibration": OUTPUT_ROOT / "strategy_evaluation" / f"strategy_evidence_calibration_{date_ymd}.json",
        "ifind_financial": OUTPUT_ROOT / "ifind" / f"financial_{date_ymd}.json",
        "ifind_industry": OUTPUT_ROOT / "ifind" / f"industry_{date_ymd}.json",
        "macro_chain_prior": OUTPUT_ROOT / "macro_chain_prior" / f"macro_chain_prior_{date_ymd}.json",
        # "reward_risk": OUTPUT_ROOT / "reward_risk" / f"reward_risk_{date_str}.json",
        # NOTE: reward_risk 已降级为只读分析，不再作为排序/过滤依据
    }


def load_reminder_signals(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path, required=True)
    out: list[dict[str, Any]] = []
    for row in payload.get("rows", []) or []:
        if row.get("reminder_eligible") is True and row.get("display_scope") == "reminder":
            out.append(row)
    return out


def build_state_map(state_ef_path: Path, duration_path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in load_json(state_ef_path, required=True).get("rows", []) or []:
        key = code6(row.get("stock_code"))
        out[key] = {
            "stock_code": row.get("stock_code"),
            "d1_close": row.get("d1_close"),
            "mn1_state": row.get("mn1_state_hex"),
            "w1_state": row.get("w1_state_hex"),
            "d1_state": row.get("d1_state_hex"),
            "mn1_state_score": row.get("mn1_state_score"),
            "w1_state_score": row.get("w1_state_score"),
            "d1_state_score": row.get("d1_state_score"),
            "state_score_sum": row.get("score_sum"),
            "ef_count": row.get("ef_count"),
        }

    for row in load_json(duration_path, required=True).get("rows", []) or []:
        key = code6(row.get("stock_code"))
        item = out.setdefault(key, {"stock_code": row.get("stock_code")})
        item.update(
            {
                "stock_code": item.get("stock_code") or row.get("stock_code"),
                "d1_close": item.get("d1_close") or row.get("d1_close"),
                "mn1_state": item.get("mn1_state") or row.get("mn1_state_hex"),
                "w1_state": item.get("w1_state") or row.get("w1_state_hex"),
                "d1_state": item.get("d1_state") or row.get("d1_state_hex"),
                "ef_count": item.get("ef_count") if item.get("ef_count") is not None else row.get("ef_count"),
                "mn1_ef_duration": row.get("mn1_ef_duration"),
                "w1_ef_duration": row.get("w1_ef_duration"),
                "d1_ef_duration": row.get("d1_ef_duration"),
                "all_three_ef_duration": row.get("all_three_ef_duration"),
                "mn1_contraction_duration": row.get("mn1_contraction_duration"),
                "w1_contraction_duration": row.get("w1_contraction_duration"),
                "d1_contraction_duration": row.get("d1_contraction_duration"),
                "mn1_days_since_contraction_exit": row.get("mn1_days_since_contraction_exit"),
                "w1_days_since_contraction_exit": row.get("w1_days_since_contraction_exit"),
                "d1_days_since_contraction_exit": row.get("d1_days_since_contraction_exit"),
                "mn1_prev_contraction_duration": row.get("mn1_prev_contraction_duration"),
                "w1_prev_contraction_duration": row.get("w1_prev_contraction_duration"),
                "d1_prev_contraction_duration": row.get("d1_prev_contraction_duration"),
            }
        )
    return out


def build_sr_map(path: Path) -> dict[str, dict[str, Any]]:
    rows = load_json(path, required=True).get("rows", []) or []
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = code6(row.get("stock_code"))
        distance = float(row.get("distance_pct") or 999.0)
        current = best.get(key)
        if current is None or distance < float(current.get("distance_pct") or 999.0):
            best[key] = row
    return best


def build_fundamental_map(path: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(path, required=False)
    out: dict[str, dict[str, Any]] = {}
    for row in payload.get("rows", []) or []:
        out[code6(row.get("stock_code"))] = {
            "stock_code": row.get("stock_code"),
            "stock_name": row.get("stock_name"),
            "sw_l1": row.get("sw_l1"),
            "summary": row.get("chief_insight"),
            "confidence": row.get("confidence"),
            "evidence_count": row.get("evidence_count"),
        }
    return out


def build_ifind_map(financial_path: Path, industry_path: Path) -> dict[str, dict[str, Any]]:
    financial = load_json(financial_path, required=False).get("by_code", {}) or {}
    industry = load_json(industry_path, required=False).get("by_code", {}) or {}
    out: dict[str, dict[str, Any]] = {}
    for code, row in financial.items():
        key = code6(code)
        out.setdefault(key, {})["financial"] = row
    for code, row in industry.items():
        key = code6(code)
        out.setdefault(key, {})["industry"] = row
    return out


def build_evaluation_map(path: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(path, required=False)
    out: dict[str, dict[str, Any]] = {}
    for row in payload.get("rows", []) or []:
        out[code6(row.get("stock_code"))] = {
            "stock_name": row.get("stock_name"),
            "sw_l1": row.get("sw_l1"),
            "sw_l2": row.get("sw_l2"),
            "evidence_score": row.get("evidence_score"),
            "evidence_tier": row.get("evidence_tier"),
            "evidence_rank": row.get("evidence_rank"),
            "environment_tags": row.get("environment_tags"),
            "factor_breakdown": row.get("factor_breakdown"),
            "research_note": row.get("research_note"),
        }
    return out


def build_prior_map(path: Path) -> dict[str, Any]:
    payload = load_json(path, required=False)
    return {
        "macro_prior": payload.get("macro_prior") or {},
        "market_style_prior": payload.get("market_style_prior") or {},
        "strategy_priors": payload.get("strategy_priors") or {},
        "by_industry": payload.get("by_industry") or {},
    }


def calibration_status(path: Path) -> dict[str, Any]:
    payload = load_json(path, required=False)
    status = payload.get("status")
    if status == "ok":
        return {"status": "已校准", "source": str(path)}
    return {
        "status": "待校准",
        "reason": payload.get("reason") or status or "calibration_not_available",
        "source": str(path) if path.exists() else None,
    }


def maturity_label(signal: dict[str, Any]) -> str:
    signal_type = signal.get("signal_type")
    if signal_type == "entry":
        return ENTRY_MATURITY
    if signal_type == "exit":
        return "防守参考线"
    if signal_type == "risk":
        return "状态值得复核"
    return ENTRY_MATURITY


def sr_note(sr: dict[str, Any] | None) -> str | None:
    if not sr:
        return None
    direction = sr.get("boundary_direction")
    boundary_type = sr.get("boundary_type")
    period = sr.get("boundary_period")
    distance = sr.get("distance_pct")
    if direction == "above_resistance":
        return f"{period} 收盘价位于阻力区间上方"
    if direction == "below_support":
        return f"{period} 收盘价位于支撑区间下方"
    if direction == "inside_range" and distance is not None:
        return f"{period} 收盘价接近{boundary_type}边界"
    return None


def safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def decode_volatility_bit(state_score: Any) -> int | None:
    value = safe_int(state_score)
    if value is None:
        return None
    return abs(value) & 1


def decode_state_hex_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("+-")
    try:
        return sign * int(text, 16)
    except ValueError:
        return safe_int(value)


def decode_state_volatility_bit(state_score: Any, state_hex: Any = None) -> int | None:
    bit = decode_volatility_bit(state_score)
    if bit is not None:
        return bit
    value = decode_state_hex_value(state_hex)
    if value is None:
        return None
    return abs(value) & 1


def percent(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def ma2560_environment(signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "local_combo_pass": bool(signal.get("ma2560_local_combo_pass")),
        "p116_state_match": bool(signal.get("ma2560_p116_state_match")),
        "market_match_level": signal.get("ma2560_market_match_level") or "not_match",
        "state_combo": signal.get("ma2560_state_combo") or "",
    }


def ma2560_match_tag(signal: dict[str, Any]) -> str | None:
    if signal.get("strategy_id") != "ma2560":
        return None
    level = signal.get("ma2560_market_match_level") or "not_match"
    return MA2560_MATCH_LABELS.get(level, f"2560 {level}")


def bollinger_local_stat_note(signal: dict[str, Any], state: dict[str, Any]) -> str:
    if signal.get("strategy_id") != "bollinger_bandit":
        return ""
    d1_vol_bit = decode_state_volatility_bit(
        state.get("d1_state_score") or signal.get("d1_state_score"),
        state.get("d1_state") or signal.get("d1_state"),
    )
    if d1_vol_bit == 0:
        return BOLLINGER_VOL_STABLE_NOTE
    if d1_vol_bit == 1:
        return BOLLINGER_VOL_ACTIVE_NOTE
    return ""


def vcp_environment(signal: dict[str, Any], state: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    if signal.get("strategy_id") != "vcp":
        return {
            "path_match": False,
            "status": "not_vcp",
            "validated_summary": "",
            "d1_days_since_contraction_exit": None,
            "d1_prev_contraction_duration": None,
        }
    strategy_rule = rule.get("strategy") if isinstance(rule.get("strategy"), dict) else {}
    allowed = set(strategy_rule.get("allowed_raw_signals") or rule.get("allowed_raw_signals") or [])
    if allowed and signal.get("raw_signal") not in allowed:
        return {
            "path_match": False,
            "status": "raw_signal_not_in_rule",
            "validated_summary": "",
            "d1_days_since_contraction_exit": state.get("d1_days_since_contraction_exit"),
            "d1_prev_contraction_duration": state.get("d1_prev_contraction_duration"),
        }
    d1_since_exit = safe_int(state.get("d1_days_since_contraction_exit"))
    d1_prev_contraction = safe_int(state.get("d1_prev_contraction_duration"), 0) or 0
    path = rule.get("state_path_match") if isinstance(rule.get("state_path_match"), dict) else {}
    optimal_path = rule.get("optimal_path") if isinstance(rule.get("optimal_path"), dict) else {}
    window = (
        safe_int(path.get("required_recent_d1_contraction_window_days"))
        or safe_int(optimal_path.get("lookback_trading_days"))
        or 20
    )
    path_match = d1_since_exit is not None and 1 <= d1_since_exit <= window and d1_prev_contraction > 0
    evidence = rule.get("evidence") if isinstance(rule.get("evidence"), dict) else {}
    evidence_20260501 = (
        rule.get("evidence_20260501") if isinstance(rule.get("evidence_20260501"), dict) else {}
    )
    summary = (
        evidence.get("display_summary")
        or evidence_20260501.get("display_summary")
        or VCP_VALIDATED_SUMMARY_FALLBACK
    )
    return {
        "path_match": path_match,
        "status": "local_validated" if path_match else "not_path_match",
        "path_rule": "D1近20日收缩后释放",
        "validated_summary": summary if path_match else "",
        "d1_days_since_contraction_exit": d1_since_exit,
        "d1_prev_contraction_duration": d1_prev_contraction,
    }


def build_environment_tags(signal: dict[str, Any], evaluation: dict[str, Any] | None) -> list[str]:
    tags = parse_tags((evaluation or {}).get("environment_tags"))
    match_tag = ma2560_match_tag(signal)
    if match_tag and match_tag not in tags:
        tags.append(match_tag)
    return tags


def build_card(
    signal: dict[str, Any],
    state: dict[str, Any],
    sr: dict[str, Any] | None,
    fundamental: dict[str, Any] | None,
    ifind: dict[str, Any] | None,
    evaluation: dict[str, Any] | None,
    prior_map: dict[str, Any],
    cal: dict[str, Any],
    vcp_rule: dict[str, Any],
    rr: dict[str, Any] | None,
) -> dict[str, Any]:
    label = maturity_label(signal)
    if label not in ALLOWED_MATURITY_LABELS:
        raise ValueError(f"unsupported reminder label: {label}")

    industry = (
        (evaluation or {}).get("sw_l1") or ((ifind or {}).get("industry") or {}).get("sw_l1") or "未分类"
    )
    strategy_id = signal.get("strategy_id")
    industry_prior = (prior_map.get("by_industry") or {}).get(industry) or {}
    strategy_prior = (prior_map.get("strategy_priors") or {}).get(strategy_id) or {}
    return {
        "stock_code": signal.get("stock_code"),
        "stock_code_6": code6(signal.get("stock_code")),
        "stock_name": (evaluation or {}).get("stock_name")
        or (fundamental or {}).get("stock_name")
        or signal.get("stock_name"),
        "maturity": label,
        "strategy": {
            "strategy_id": signal.get("strategy_id"),
            "signal_type": signal.get("signal_type"),
            "signal_name": signal.get("signal_name"),
            "signal_strength": signal.get("signal_strength"),
            "raw_signal": signal.get("raw_signal"),
            "params_json": signal.get("params_json"),
            "source_module": signal.get("source_module"),
        },
        "lifecycle_stage": signal.get("lifecycle_stage") or label,
        "strategy_environment_fit": signal.get("strategy_environment_fit") or "待观察",
        "fit_reasons": signal.get("fit_reasons") or "",
        "ma2560_environment": ma2560_environment(signal),
        "local_stat_note": bollinger_local_stat_note(signal, state),
        "state_environment": {
            "mn1_state": state.get("mn1_state"),
            "w1_state": state.get("w1_state"),
            "d1_state": state.get("d1_state"),
            "mn1_state_score": state.get("mn1_state_score"),
            "w1_state_score": state.get("w1_state_score"),
            "d1_state_score": state.get("d1_state_score"),
            "state_score_sum": state.get("state_score_sum"),
            "ef_count": state.get("ef_count"),
        },
        "state_duration": {
            "mn1_ef_duration": state.get("mn1_ef_duration"),
            "w1_ef_duration": state.get("w1_ef_duration"),
            "d1_ef_duration": state.get("d1_ef_duration"),
            "all_three_ef_duration": state.get("all_three_ef_duration"),
            "mn1_contraction_duration": state.get("mn1_contraction_duration"),
            "w1_contraction_duration": state.get("w1_contraction_duration"),
            "d1_contraction_duration": state.get("d1_contraction_duration"),
            "mn1_days_since_contraction_exit": state.get("mn1_days_since_contraction_exit"),
            "w1_days_since_contraction_exit": state.get("w1_days_since_contraction_exit"),
            "d1_days_since_contraction_exit": state.get("d1_days_since_contraction_exit"),
            "mn1_prev_contraction_duration": state.get("mn1_prev_contraction_duration"),
            "w1_prev_contraction_duration": state.get("w1_prev_contraction_duration"),
            "d1_prev_contraction_duration": state.get("d1_prev_contraction_duration"),
        },
        "sr_position": {
            "boundary_period": (sr or {}).get("boundary_period"),
            "boundary_type": (sr or {}).get("boundary_type"),
            "boundary_direction": (sr or {}).get("boundary_direction"),
            "distance_pct": (sr or {}).get("distance_pct"),
            "close_vs_boundary": (sr or {}).get("close_vs_boundary"),
            "above_resistance": (sr or {}).get("above_resistance"),
            "below_support": (sr or {}).get("below_support"),
            "note": sr_note(sr),
        }
        if sr
        else None,
        # NOTE: reward_risk removed — 阻力位止盈违背"让利润奔跑"原则
        "fundamental": fundamental,
        "ifind": ifind,
        "macro_chain_prior": {
            "macro_prior": prior_map.get("macro_prior") or {},
            "market_style_prior": prior_map.get("market_style_prior") or {},
            "strategy_prior": strategy_prior,
            "industry_prior": industry_prior,
        },
        "scene_tags": build_scene_tags(signal, ifind, evaluation),
        "strategy_evaluation": evaluation,
        "environment_tags": build_environment_tags(signal, evaluation),
        "vcp_environment": vcp_environment(signal, state, vcp_rule),
        "vcp_entry_confirmation": signal.get("vcp_entry_confirmation"),
        "vcp_stop_prices": signal.get("vcp_stop_prices"),
        "matched_pattern": _parse_matched_pattern(signal.get("matched_pattern")),
        "w1_mn1_env": compute_w1_mn1_env_label(state.get("mn1_state_score"), state.get("w1_state_score")),
        "calibration": cal,
        "research_only": True,
    }


def build_scene_tags(
    signal: dict[str, Any], ifind: dict[str, Any] | None, evaluation: dict[str, Any] | None
) -> list[str]:
    tags: list[str] = []
    financial = (ifind or {}).get("financial") or {}
    industry = (ifind or {}).get("industry") or {}
    if industry.get("industry_climate") and industry.get("industry_climate") != "未标注":
        tags.append(f"行业景气{industry['industry_climate']}")
    quality = financial.get("quality_label")
    if quality and quality != "数据不足":
        tags.append(quality)
    cash = financial.get("cash_quality_label")
    if cash in {"现金流健康", "现金流谨慎"}:
        tags.append(cash)
    strategy_id = signal.get("strategy_id")
    env_tags = parse_tags((evaluation or {}).get("environment_tags"))
    if env_tags and strategy_id:
        tags.append(f"{env_tags[0]} + {strategy_id}")
    return tags


def apply_prior_scene_tag(card: dict[str, Any]) -> None:
    industry_prior = (card.get("macro_chain_prior") or {}).get("industry_prior") or {}
    label = industry_prior.get("posterior_adjustment_label")
    if not label:
        return
    tags = card.setdefault("scene_tags", [])
    if label not in tags:
        tags.append(label)


def parse_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def card_sort_key(card: dict[str, Any]) -> tuple[Any, ...]:
    """Sort by: 适配度 > 大周期背景 > 证据分数 > State分数 > 共振持续 > 代码"""
    state = card.get("state_environment") or {}
    duration = card.get("state_duration") or {}
    evaluation = card.get("strategy_evaluation") or {}
    fit = card.get("strategy_environment_fit") or "待观察"
    w1_mn1 = card.get("w1_mn1_env") or {}
    env_priority = {"大周期共振": 0, "大周期过渡": 1, "双重收缩": 2}
    fit_order = {"最佳适配": 0, "适配": 1, "弱适配": 2, "待观察": 3}
    return (
        fit_order.get(fit, 99),
        env_priority.get(w1_mn1.get("label", ""), 99),
        -(float(evaluation.get("evidence_score") or 0.0)),
        -(int(state.get("state_score_sum") or 0)),
        -(int(duration.get("all_three_ef_duration") or 0)),
        str(card.get("stock_code") or ""),
    )


def generate_html(payload: dict[str, Any]) -> str:
    cards = payload["reminders"]
    groups: dict[str, list[dict[str, Any]]] = {
        label: [] for label in ["趋势新生", "趋势行进", "趋势延展", "防守参考线", "状态值得复核"]
    }
    for card in cards:
        groups.setdefault(card["maturity"], []).append(card)

    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    def row(card: dict[str, Any]) -> str:
        state = card.get("state_environment") or {}
        duration = card.get("state_duration") or {}
        strategy = card.get("strategy") or {}
        sr = card.get("sr_position") or {}
        rr = card.get("reward_risk") or {}
        fundamental = card.get("fundamental") or {}
        ifind = card.get("ifind") or {}
        prior = card.get("macro_chain_prior") or {}
        industry_prior = prior.get("industry_prior") or {}
        ifind_financial = ifind.get("financial") or {}
        ifind_industry = ifind.get("industry") or {}
        evaluation = card.get("strategy_evaluation") or {}
        tags = " / ".join(card.get("environment_tags") or []) or "-"
        scene_tags = " / ".join(card.get("scene_tags") or []) or "-"
        w1_mn1_env = card.get("w1_mn1_env") or {}
        w1_mn1_line = (
            (
                f'<br><span style="color:{esc(w1_mn1_env.get("color", "#6b7280"))};font-size:12px;">'
                f"大周期背景：{esc(w1_mn1_env.get('label', '大周期过渡'))}"
                f' <span style="color:#999;">— {esc(w1_mn1_env.get("description", ""))}</span></span>'
            )
            if w1_mn1_env
            else ""
        )
        founder_line = ""
        sid = strategy.get("strategy_id") or ""
        if sid == "vcp":
            vcp_env = card.get("vcp_environment") or {}
            if vcp_env.get("path_match"):
                founder_line = (
                    f'<br><span style="color:#059669;font-size:12px;">{esc(MINERVINI_ENV_MATCH_TEXT)}</span>'
                )
        elif sid == "ma2560":
            ma2560_env = card.get("ma2560_environment") or {}
            if ma2560_env.get("market_match_level") == "full_match":
                founder_line = (
                    f'<br><span style="color:#059669;font-size:12px;">{esc(DARVAS_ENV_MATCH_TEXT)}</span>'
                )
        elif sid == "bollinger_bandit":
            local_note = card.get("local_stat_note") or ""
            state = card.get("state_environment") or {}
            # volatility_bit=0 对应波动稳定环境（D1 state E = 扩张有趋势，波动稳定）
            is_vol_stable = "波动稳定" in str(local_note) or state.get("d1_state") == "E"
            if is_vol_stable:
                founder_line = (
                    f'<br><span style="color:#059669;font-size:12px;">{esc(BOLLINGER_ENV_MATCH_TEXT)}</span>'
                )
        pattern_info = card.get("matched_pattern")
        pattern_line = ""
        if pattern_info and pattern_info.get("pattern_status") == "verified":
            boost = pattern_info.get("pattern_boost", 0)
            pattern_line = (
                f'<br><span style="color:#059669;font-size:12px;">'
                f"跃迁模式：D1{esc(pattern_info.get('pattern_description', ''))} | "
                f"历史{pattern_info.get('pattern_mean_excess', 0):+.1%} | "
                f"n={pattern_info.get('pattern_n', 0)} | "
                f"加成{boost:+.1%}"
                f"</span>"
            )
        strategy = card.get("strategy") or {}
        conviction = strategy.get("conviction_level", "")
        if conviction == "highest":
            pattern_line += ' <span style="color:#d97706;font-weight:bold;">★ 四维共振</span>'
        fit = card.get("strategy_environment_fit") or "待观察"
        lifecycle = card.get("lifecycle_stage") or card.get("maturity")
        fit_reasons = card.get("fit_reasons") or "-"
        local_stat_note = card.get("local_stat_note") or ""
        ma2560 = card.get("ma2560_environment") or {}
        ma2560_level = ma2560.get("market_match_level") or "not_match"
        ma2560_line = ""
        if (strategy.get("strategy_id") or "") == "ma2560":
            ma2560_line = (
                f"<br><span>{esc(MA2560_MATCH_LABELS.get(ma2560_level, f'2560 {ma2560_level}'))} "
                f"{esc(ma2560.get('state_combo') or '')}</span>"
            )
        vcp = card.get("vcp_environment") or {}
        vcp_line = ""
        if (strategy.get("strategy_id") or "") == "vcp" and vcp.get("path_match"):
            vcp_line = f"<br><span>{esc(vcp.get('path_rule'))} | {esc(vcp.get('validated_summary'))}</span>"
        local_stat_line = f"<br><span>{esc(local_stat_note)}</span>" if local_stat_note else ""
        ifind_text = ifind_financial.get("summary") or "-"
        industry_text = ifind_industry.get("summary") or "-"
        return f"""
        <tr>
          <td><strong>{esc(card.get("stock_code"))}</strong><br><span>{esc(card.get("stock_name") or "")}</span></td>
          <td>{esc(lifecycle)}<br><span>{esc(card.get("maturity"))}</span></td>
          <td>{esc(strategy.get("strategy_id"))}<br><span>{esc(strategy.get("signal_name"))}</span></td>
          <td>{esc(fit)}<br><span>{esc(fit_reasons)}</span>{ma2560_line}{vcp_line}{local_stat_line}{pattern_line}</td>
          <td>MN1 {esc(state.get("mn1_state"))} / W1 {esc(state.get("w1_state"))} / D1 {esc(state.get("d1_state"))}<br><span>score {esc(state.get("state_score_sum"))}, ef {esc(state.get("ef_count"))}</span></td>
          <td>D1 {esc(duration.get("d1_ef_duration"))}<br><span>all-three {esc(duration.get("all_three_ef_duration"))}</span></td>
          <td>{esc(sr.get("boundary_direction") or "-")}<br><span>{esc(sr.get("boundary_period") or "")} {esc(sr.get("boundary_type") or "")} {percent(sr.get("distance_pct"))}</span></td>
          <td>{esc(tags)}{w1_mn1_line}{founder_line}</td>
          <td>{esc(ifind_text)}<br><span>{esc(industry_text)}</span><br><span>{esc(scene_tags)}</span><br><span>{esc(industry_prior.get("posterior_adjustment_label") or "")} {esc(industry_prior.get("chain_prior_score") or "")}</span></td>
          <td>{esc(evaluation.get("evidence_tier") or "-")}<br><span>{esc(evaluation.get("evidence_score") or "")}</span></td>
          <td>{esc((fundamental.get("summary") or "")[:120])}</td>
          <td>{esc((card.get("calibration") or {}).get("status"))}</td>
        </tr>
        """

    sections = []
    for label, items in groups.items():
        if not items:
            continue
        rows = "\n".join(row(item) for item in items)
        sections.append(
            f"""
            <section>
              <h2>{esc(label)} <span>{len(items)}</span></h2>
              <table>
                <thead>
                  <tr>
                    <th>代码</th>
                    <th>生命周期</th>
                    <th>策略信号</th>
                    <th>环境适配</th>
                    <th>State环境</th>
                    <th>持续</th>
                    <th>SR位置</th>
                    <th>环境标签</th>
                    <th>iFinD摘要</th>
                    <th>证据档</th>
                    <th>基本面摘要</th>
                    <th>统计</th>
                  </tr>
                </thead>
                <tbody>{rows}</tbody>
              </table>
            </section>
            """
        )

    generated_at = esc(payload["generated_at"])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>策略提醒简报 {esc(payload["date"])}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f7fb; color: #172033; }}
    main {{ max-width: 1440px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    .meta {{ margin: 0 0 20px; color: #5d6b82; }}
    section {{ margin-top: 24px; }}
    h2 {{ font-size: 18px; margin: 0 0 10px; }}
    h2 span {{ color: #667085; font-weight: 500; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e1e6ef; }}
    th, td {{ text-align: left; vertical-align: top; padding: 10px 12px; border-bottom: 1px solid #edf1f7; font-size: 13px; }}
    th {{ background: #f0f3f8; color: #344054; font-weight: 650; }}
    td span {{ color: #667085; font-size: 12px; }}
    tr:last-child td {{ border-bottom: 0; }}
    tr.high-value-rr {{ background: #ecfdf5; }}
    tr.high-value-rr td {{ border-left: 3px solid #16a34a; }}
  </style>
</head>
<body>
  <main>
    <h1>策略提醒简报</h1>
    <p class="meta">日期 {esc(payload["date"])} | 提醒 {payload["total_reminders"]} 条 | 生成 {generated_at}</p>
    {"".join(sections)}
  </main>
</body>
</html>
"""


def build_reminder_brief(date_str: str) -> dict[str, Any]:
    paths = default_paths(date_str)
    generated_at = datetime.now(timezone.utc).isoformat()
    signals = load_reminder_signals(paths["signals"])
    state_map = build_state_map(paths["state_ef"], paths["state_duration"])
    sr_map = build_sr_map(paths["sr_boundary"])
    fundamental_map = build_fundamental_map(paths["fundamental_ledger"])
    ifind_map = build_ifind_map(paths["ifind_financial"], paths["ifind_industry"])
    evaluation_map = build_evaluation_map(paths["strategy_evaluation"])
    prior_map = build_prior_map(paths["macro_chain_prior"])
    cal = calibration_status(paths["calibration"])
    vcp_rule = load_vcp_rule()

    # rr_map = build_rr_map(paths.get("reward_risk", Path()))
    # NOTE: RR 已降级，不再加载

    cards = []
    missing_state = 0
    for signal in signals:
        key = code6(signal.get("stock_code"))
        state = state_map.get(key)
        if not state:
            missing_state += 1
            continue
        cards.append(
            build_card(
                signal,
                state,
                sr_map.get(key),
                fundamental_map.get(key),
                ifind_map.get(key),
                evaluation_map.get(key),
                prior_map,
                cal,
                vcp_rule,
                None,  # rr_map removed
            )
        )
        apply_prior_scene_tag(cards[-1])
    cards.sort(key=card_sort_key)

    maturity_counts = Counter(card["maturity"] for card in cards)
    strategy_counts = Counter((card.get("strategy") or {}).get("strategy_id") for card in cards)
    payload = {
        "schema_version": "strategy_reminder_brief_v2",
        "date": date_str,
        "generated_at": generated_at,
        "total_signals_input": len(signals),
        "total_reminders": len(cards),
        "missing_state_context": missing_state,
        "maturity_distribution": dict(sorted(maturity_counts.items())),
        "strategy_distribution": dict(sorted(strategy_counts.items())),
        "data_sources": {name: str(path) for name, path in paths.items()},
        "guardrails": [
            "Consumes only reminder_eligible strategy ledger rows.",
            "Does not calculate or infer strategy triggers.",
            "Missing calibration remains 待校准.",
            "All labels are restricted to approved research reminder language.",
        ],
        "reminders": cards,
        "research_only": True,
    }

    REMINDER_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    date_ymd = ymd(date_str)
    json_path = REMINDER_DIR / f"reminder_{date_ymd}.json"
    latest_json = REMINDER_DIR / "reminder_latest.json"
    html_path = PUBLIC_DIR / f"strategy_reminder_{date_ymd}.html"
    latest_html = PUBLIC_DIR / "strategy_reminder_latest.html"

    text = json.dumps(payload, ensure_ascii=False, indent=2, default=json_safe)
    json_path.write_text(text, encoding="utf-8")
    latest_json.write_text(text, encoding="utf-8")
    html_text = generate_html(payload)
    html_path.write_text(html_text, encoding="utf-8")
    latest_html.write_text(html_text, encoding="utf-8")

    return {
        "ok": True,
        "date": date_str,
        "total_signals_input": len(signals),
        "total_reminders": len(cards),
        "missing_state_context": missing_state,
        "maturity_distribution": payload["maturity_distribution"],
        "strategy_distribution": payload["strategy_distribution"],
        "json": str(json_path),
        "latest_json": str(latest_json),
        "html": str(html_path),
        "latest_html": str(latest_html),
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build daily strategy reminder brief.")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    result = build_reminder_brief(args.date)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
