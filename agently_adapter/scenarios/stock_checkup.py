"""个股问诊场景 —— 翻译 → 诊断 → 翻译 → 融合"""

from __future__ import annotations

from typing import Any

from agently_adapter.agents import translator, diagnoser, fusion


def run(user_input: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """个股问诊场景编排链。"""
    symbol = context.get("symbol", "")
    states = context.get("stock_states", {})

    # Step 1: 翻译 —— 把原始 State 翻译成人话
    trans1_ctx = {
        "raw_data": states,
        "user_type": context.get("user_type", "执行型"),
    }
    trans1_result = translator.run(trans1_ctx)
    if trans1_result is None:
        trans1_result = {"raw_fallback": str(states)}

    # Step 2: 诊断 —— 多周期体检
    diag_ctx = {
        "symbol": symbol,
        "name": context.get("stock_name", ""),
        "states": states,
        "ef_count": context.get("ef_count", 0),
        "capital_flow": context.get("capital_flow", {}),
        "breakout_status": context.get("breakout_status", ""),
        "sustained_days": context.get("sustained_days", 0),
    }
    diag_result = diagnoser.run(diag_ctx)
    if diag_result is None:
        diag_result = {"conclusion": f"{symbol} 诊断失败，返回规则摘要"}

    # Step 3: 翻译 —— 把诊断结论再翻译一遍（面向用户）
    trans2_ctx = {
        "raw_data": diag_result,
        "user_type": context.get("user_type", "执行型"),
    }
    trans2_result = translator.run(trans2_ctx)
    if trans2_result is None:
        trans2_result = diag_result

    # Step 4: 融合
    fusion_ctx = {
        "source_scenario": "stock_checkup",
        "draft": {
            "state_translation": trans1_result,
            "diagnosis": diag_result,
            "diagnosis_translation": trans2_result,
        },
        "user_type": context.get("user_type", "执行型"),
        "recent_turns": context.get("recent_turns", []),
    }
    return fusion.run(fusion_ctx)
