#!/usr/bin/env python3
"""Generate a trading landing plan from Router and Debate outputs.

This script turns the current multi-agent Router result into a concrete
human-review trading plan:

- what can be watched today
- what must wait for confirmation
- what is only a risk warning
- reference trigger / invalidation / position boundary

It does not place orders and does not bypass red-line checks.

Usage:
    .venv/bin/python scripts/generate_trade_plan_from_router.py --date 2026-06-05
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import duckdb
except Exception:  # pragma: no cover - runtime fallback
    duckdb = None

from hermass_platform.red_lines import DEFAULT_MAX_POSITION_PCT, get_redlines_config


OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DEBATE_DIR = OUTPUTS_DIR / "debate"
ROUTER_DIR = OUTPUTS_DIR / "router"
PLAN_DIR = OUTPUTS_DIR / "trade_plan"
STATE_CUBE_DB = OUTPUTS_DIR / "state_cube" / "state_cube.duckdb"


def _fmt_yyyymmdd(value: str) -> str:
    return value.replace("-", "")


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _resolve_latest(patterns: list[tuple[Path, str]]) -> Path | None:
    files: list[Path] = []
    for root, pattern in patterns:
        files.extend(root.glob(pattern))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _resolve_router_path(target_date: str) -> Path | None:
    ymd = _fmt_yyyymmdd(target_date)
    exact = [
        DEBATE_DIR / f"router_{ymd}.json",
        ROUTER_DIR / f"router_{ymd}.json",
        ROUTER_DIR / f"router_decisions_{ymd}.json",
    ]
    for path in exact:
        if path.exists():
            return path
    return _resolve_latest([(DEBATE_DIR, "router_*.json"), (ROUTER_DIR, "router*.json")])


def _resolve_debate_path(target_date: str) -> Path | None:
    ymd = _fmt_yyyymmdd(target_date)
    exact = DEBATE_DIR / f"debate_{ymd}.json"
    if exact.exists():
        return exact
    return _resolve_latest([(DEBATE_DIR, "debate_*.json")])


def _load_daily_snapshot(target_date: str) -> dict[str, dict[str, Any]]:
    path = OUTPUTS_DIR / "daily_snapshot" / f"daily_snapshot_{_fmt_yyyymmdd(target_date)}.json"
    if not path.exists():
        return {}
    data = _load_json(path)
    rows = data.get("stocks", [])
    if not isinstance(rows, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("c"):
            result[str(row["c"])] = row
    return result


def _load_state_cube_rows(target_date: str, stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    if not stock_codes or duckdb is None or not STATE_CUBE_DB.exists():
        return {}
    try:
        con = duckdb.connect(str(STATE_CUBE_DB), read_only=True)
        placeholders = ",".join(["?"] * len(stock_codes))
        query = f"""
            SELECT stock_code, state_date, mn1_state_hex, w1_state_hex, d1_state_hex,
                   ef_count, d1_close, d1_atr14, d1_adx14,
                   d1_bb20_position, d1_bb20_width, w1_bb20_position, w1_bb20_width
            FROM state_cube
            WHERE stock_code IN ({placeholders})
              AND state_date <= CAST(? AS DATE)
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY stock_code ORDER BY state_date DESC
            ) = 1
        """
        rows = con.execute(query, stock_codes + [target_date]).fetchall()
        cols = [desc[0] for desc in con.description]
        con.close()
        return {str(row[0]): dict(zip(cols, row)) for row in rows}
    except Exception:
        return {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except Exception:
        return default


def _price_context(stock_code: str, snapshot: dict[str, Any], state_row: dict[str, Any]) -> dict[str, Any]:
    price = _safe_float(snapshot.get("p"), _safe_float(state_row.get("d1_close")))
    atr = _safe_float(snapshot.get("atr"), _safe_float(state_row.get("d1_atr14")))
    sr = snapshot.get("sr", {}) if isinstance(snapshot.get("sr"), dict) else {}
    d_sr = sr.get("d", []) if isinstance(sr.get("d"), list) else []
    d_support = _safe_float(d_sr[0]) if len(d_sr) >= 1 else 0.0
    d_resistance = _safe_float(d_sr[1]) if len(d_sr) >= 2 else 0.0
    sr_ready = bool(d_sr[2]) if len(d_sr) >= 3 else False

    state_hex = snapshot.get("hex") if isinstance(snapshot.get("hex"), list) else None
    if state_hex and len(state_hex) >= 3:
        mn1, w1, d1 = state_hex[:3]
    else:
        mn1 = state_row.get("mn1_state_hex", "")
        w1 = state_row.get("w1_state_hex", "")
        d1 = state_row.get("d1_state_hex", "")

    return {
        "stock_code": stock_code,
        "price": round(price, 3) if price else None,
        "atr_pct": round(atr, 3) if atr else None,
        "d1_support": round(d_support, 3) if d_support else None,
        "d1_resistance": round(d_resistance, 3) if d_resistance else None,
        "sr_ready": sr_ready,
        "state_hex": {"MN1": mn1 or "", "W1": w1 or "", "D1": d1 or ""},
        "ef_count": snapshot.get("ef", state_row.get("ef_count")),
        "d1_adx14": round(_safe_float(state_row.get("d1_adx14")), 2)
        if state_row.get("d1_adx14") is not None
        else None,
    }


def _stop_reference(price_ctx: dict[str, Any]) -> dict[str, Any]:
    price = _safe_float(price_ctx.get("price"))
    support = _safe_float(price_ctx.get("d1_support"))
    atr_pct = _safe_float(price_ctx.get("atr_pct"))
    fallback_stop = price * 0.95 if price else 0.0
    atr_stop = price * (1 - min(max(atr_pct / 100 * 2.0, 0.03), 0.12)) if price and atr_pct else 0.0
    candidates = [v for v in [fallback_stop, atr_stop, support] if v > 0 and (not price or v < price)]
    reference = max(candidates) if candidates else fallback_stop
    return {
        "reference_stop": round(reference, 3) if reference else None,
        "method": "max(5% fallback, 2ATR proxy, D1 support)",
        "human_confirmation_required": True,
        "note": "仅作人工确认参考；止损/止盈不可自动执行。",
    }


def _opinion_summary(stock_code: str, debate_data: dict[str, Any]) -> dict[str, Any]:
    summary = debate_data.get("debate_summary", {}) if isinstance(debate_data, dict) else {}
    opinions = summary.get("per_stock_opinions", {}) if isinstance(summary, dict) else {}
    item = opinions.get(stock_code, {}) if isinstance(opinions, dict) else {}
    if not isinstance(item, dict):
        return {}
    return {
        "support_agents": item.get("support_agents", []),
        "oppose_agents": item.get("oppose_agents", []),
        "neutral_agents": item.get("neutral_agents", []),
        "data_missing_agents": item.get("data_missing_agents", []),
        "data_quality_note": item.get("data_quality_note", ""),
        "opinions": item.get("opinions", {}),
    }


def _trade_lane(router_row: dict[str, Any], opinions: dict[str, Any]) -> tuple[str, str]:
    conclusion = router_row.get("conclusion", "neutral")
    data_missing = opinions.get("data_missing_agents") or router_row.get("agent_consensus", {}).get("data_missing_agents", [])
    oppose = opinions.get("oppose_agents") or router_row.get("agent_consensus", {}).get("oppose_agents", [])

    if conclusion == "risk_warning" or "risk_guardian" in oppose:
        return "risk_review", "风险提醒：不进入交易，只进入风险复核和观察。"
    if conclusion in {"strong_observation", "moderate_observation"} and not data_missing:
        return "trade_ready_pending_human", "可进入人工确认交易预案。"
    if conclusion in {"strong_observation", "moderate_observation"} and data_missing:
        return "wait_for_data_confirmation", "结构较强，但关键 Agent 数据缺失，需补确认。"
    return "watch_only", "观察等待：未达到交易预案门槛。"


def _position_policy(lane: str, final_weight: float) -> dict[str, Any]:
    redline_max = float(DEFAULT_MAX_POSITION_PCT)
    if lane == "trade_ready_pending_human":
        initial = min(0.10, redline_max, max(0.03, final_weight * 0.12))
        add_on = min(0.05, redline_max - initial)
    elif lane == "wait_for_data_confirmation":
        initial = 0.0
        add_on = min(0.05, redline_max)
    else:
        initial = 0.0
        add_on = 0.0
    return {
        "initial_position_pct": round(initial, 4),
        "add_on_position_pct": round(max(add_on, 0.0), 4),
        "max_single_stock_pct": redline_max,
        "max_industry_pct": float(
            get_redlines_config()
            .get("redlines", {})
            .get("max_position_enforcement", {})
            .get("max_industry_pct", 0.40)
        ),
        "note": "仓位为上限参考，不是自动执行指令；任何执行需人工确认。",
    }


def _build_card(
    router_row: dict[str, Any],
    price_ctx: dict[str, Any],
    opinions: dict[str, Any],
) -> dict[str, Any]:
    stock_code = router_row.get("stock_code", price_ctx.get("stock_code", ""))
    final_weight = _safe_float(router_row.get("final_weight"))
    lane, lane_label = _trade_lane(router_row, opinions)
    position = _position_policy(lane, final_weight)
    stop = _stop_reference(price_ctx)
    price = _safe_float(price_ctx.get("price"))
    resistance = _safe_float(price_ctx.get("d1_resistance"))

    if lane == "trade_ready_pending_human":
        entry_trigger = "人工确认后，仅在价格站上触发位且资金/成交同步确认时执行。"
    elif lane == "wait_for_data_confirmation":
        entry_trigger = "先补 M30/收缩/资金确认；未补齐前不进入交易。"
    elif lane == "risk_review":
        entry_trigger = "禁止追入；只记录风险来源，等待 Risk Agent 解除反驳。"
    else:
        entry_trigger = "仅观察，不触发交易。"

    trigger_price = None
    if price:
        trigger_base = max(price, resistance) if resistance else price
        trigger_price = round(trigger_base * 1.002, 3)

    invalidation = []
    if stop.get("reference_stop"):
        invalidation.append(f"跌破参考风控位 {stop['reference_stop']}")
    if opinions.get("data_missing_agents"):
        invalidation.append("关键 Agent 数据缺失持续存在")
    if "risk_guardian" in (opinions.get("oppose_agents") or []):
        invalidation.append("Risk Guardian 反对未解除")
    if not invalidation:
        invalidation.append("Router 降级为 neutral/risk_warning")

    return {
        "stock_code": stock_code,
        "lane": lane,
        "lane_label": lane_label,
        "router_conclusion": router_row.get("conclusion", "neutral"),
        "router_action": router_row.get("action", ""),
        "final_weight": round(final_weight, 3),
        "state_hex": price_ctx.get("state_hex", {}),
        "ef_count": price_ctx.get("ef_count"),
        "price": price_ctx.get("price"),
        "trigger_price_reference": trigger_price,
        "entry_trigger": entry_trigger,
        "invalidation_conditions": invalidation,
        "stop_reference": stop,
        "position_policy": position,
        "agent_consensus": {
            "support_agents": opinions.get("support_agents", []),
            "oppose_agents": opinions.get("oppose_agents", []),
            "neutral_agents": opinions.get("neutral_agents", []),
            "data_missing_agents": opinions.get("data_missing_agents", []),
        },
        "data_quality_note": opinions.get("data_quality_note")
        or router_row.get("data_quality_note", ""),
        "human_confirmation_required": True,
    }


def _select_rows(router_data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("top_candidates", "risk_candidates"):
        value = router_data.get(key, [])
        if isinstance(value, list):
            rows.extend([r for r in value if isinstance(r, dict)])
    if not rows:
        all_routed = router_data.get("all_routed", [])
        if isinstance(all_routed, list):
            rows.extend([r for r in all_routed[:20] if isinstance(r, dict)])

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("stock_code", ""))
        if code and code not in seen:
            unique.append(row)
            seen.add(code)
    return unique[:30]


def build_trade_plan(target_date: str) -> dict[str, Any]:
    router_path = _resolve_router_path(target_date)
    if router_path is None:
        raise FileNotFoundError("No router JSON found in outputs/debate or outputs/router")
    debate_path = _resolve_debate_path(target_date)

    router_data = _load_json(router_path)
    debate_data = _load_json(debate_path) if debate_path else {}
    selected_rows = _select_rows(router_data)
    stock_codes = [str(r.get("stock_code")) for r in selected_rows if r.get("stock_code")]
    snapshot_map = _load_daily_snapshot(target_date)
    state_rows = _load_state_cube_rows(target_date, stock_codes)

    cards: list[dict[str, Any]] = []
    for row in selected_rows:
        code = str(row.get("stock_code", ""))
        opinions = _opinion_summary(code, debate_data)
        ctx = _price_context(code, snapshot_map.get(code, {}), state_rows.get(code, {}))
        cards.append(_build_card(row, ctx, opinions))

    lanes = {
        "trade_ready_pending_human": [],
        "wait_for_data_confirmation": [],
        "watch_only": [],
        "risk_review": [],
    }
    for card in cards:
        lanes.setdefault(card["lane"], []).append(card)

    summary = {
        "trade_ready_count": len(lanes["trade_ready_pending_human"]),
        "wait_for_confirmation_count": len(lanes["wait_for_data_confirmation"]),
        "watch_only_count": len(lanes["watch_only"]),
        "risk_review_count": len(lanes["risk_review"]),
        "top_candidates_count": len(router_data.get("top_candidates", []) or []),
        "risk_candidates_count": len(router_data.get("risk_candidates", []) or []),
        "data_quality_issues": router_data.get("data_quality_issues", []),
    }

    if summary["trade_ready_count"] == 0:
        decision = "今日无交易就绪标的；以风险复核、补数据确认和观察为主。"
    else:
        decision = "存在交易预案标的，但仍需人工确认触发条件、风控位和仓位。"

    return {
        "version": "trade_plan_v0.1",
        "target_date": target_date,
        "generated_at": datetime.now().isoformat(),
        "source_files": {
            "router": str(router_path.relative_to(PROJECT_ROOT)),
            "debate": str(debate_path.relative_to(PROJECT_ROOT)) if debate_path else "",
        },
        "redlines": {
            "stop_take_profit_requires_human_confirmation": True,
            "max_single_stock_pct": float(DEFAULT_MAX_POSITION_PCT),
            "auto_ordering": False,
        },
        "decision": decision,
        "summary": summary,
        "lanes": lanes,
    }


def render_markdown(plan: dict[str, Any]) -> str:
    summary = plan["summary"]
    lines = [
        f"# 每日交易预案 - {plan['target_date']}",
        "",
        f"> 生成时间：{plan['generated_at']}",
        f"> 来源：{plan['source_files']['router']}",
        "",
        "## 总结",
        "",
        plan["decision"],
        "",
        "| 分类 | 数量 |",
        "|---|---:|",
        f"| 交易预案待人工确认 | {summary['trade_ready_count']} |",
        f"| 等待补确认 | {summary['wait_for_confirmation_count']} |",
        f"| 仅观察 | {summary['watch_only_count']} |",
        f"| 风险复核 | {summary['risk_review_count']} |",
        "",
    ]
    issues = summary.get("data_quality_issues") or []
    if issues:
        lines.extend(["## 数据质量", ""])
        lines.extend([f"- {issue}" for issue in issues])
        lines.append("")

    sections = [
        ("trade_ready_pending_human", "交易预案待人工确认"),
        ("wait_for_data_confirmation", "等待补确认"),
        ("risk_review", "风险复核"),
        ("watch_only", "仅观察"),
    ]
    for lane_key, title in sections:
        cards = plan["lanes"].get(lane_key, [])
        if not cards:
            continue
        lines.extend([f"## {title}", ""])
        for card in cards[:20]:
            lines.extend(
                [
                    f"### {card['stock_code']} - {card['router_action'] or card['router_conclusion']}",
                    "",
                    f"- 状态：MN1={card['state_hex'].get('MN1', '')} / W1={card['state_hex'].get('W1', '')} / D1={card['state_hex'].get('D1', '')}，EF={card.get('ef_count')}",
                    f"- 参考价格：{card.get('price')}，触发价参考：{card.get('trigger_price_reference')}",
                    f"- 入场触发：{card['entry_trigger']}",
                    f"- 失效条件：{'；'.join(card['invalidation_conditions'])}",
                    f"- 参考风控位：{card['stop_reference'].get('reference_stop')}（{card['stop_reference'].get('note')}）",
                    f"- 仓位边界：初始 {card['position_policy']['initial_position_pct']:.1%}，加仓 {card['position_policy']['add_on_position_pct']:.1%}，单票上限 {card['position_policy']['max_single_stock_pct']:.0%}",
                    f"- Agent：支持 {card['agent_consensus']['support_agents']}；反对 {card['agent_consensus']['oppose_agents']}；缺失 {card['agent_consensus']['data_missing_agents']}",
                ]
            )
            if card.get("data_quality_note"):
                lines.append(f"- 数据质量：{card['data_quality_note']}")
            lines.append("")

    lines.extend(
        [
            "## 执行红线",
            "",
            "- 本文件不是自动下单指令。",
            "- 止损、止盈、退出必须人工确认。",
            "- 单票仓位不得超过红线配置上限。",
            "- Risk Guardian 反对未解除时，不进入交易执行。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate daily trade plan from router/debate outputs")
    parser.add_argument("--date", default=date.today().isoformat(), help="Target date YYYY-MM-DD")
    args = parser.parse_args()

    plan = build_trade_plan(args.date)
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    ymd = _fmt_yyyymmdd(args.date)
    json_path = PLAN_DIR / f"daily_trade_plan_{ymd}.json"
    md_path = PLAN_DIR / f"daily_trade_plan_{ymd}.md"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2, default=str)
    md_path.write_text(render_markdown(plan), encoding="utf-8")
    print(f"[trade-plan] JSON: {json_path}")
    print(f"[trade-plan] Markdown: {md_path}")
    print(f"[trade-plan] Decision: {plan['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
