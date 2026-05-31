"""策略适配场景 —— 判官 → 诊断(策略环境) → 融合"""

from __future__ import annotations

from typing import Any

from agently_adapter.agents import judge, diagnoser, fusion


def run(user_input: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """策略适配场景编排链。"""
    strategy_name = context.get("strategy_name", "")

    # Step 1: 判官 —— 当前市场环境
    judge_ctx = {"market_data": context.get("market_data", {})}
    judge_result = judge.run(judge_ctx)
    if judge_result is None:
        judge_result = {"environment": "市场环境未获取"}

    # Step 2: 诊断 —— 把策略当成"个股"来诊断（策略在当前环境下的适配度）
    diag_ctx = {
        "symbol": strategy_name,
        "name": f"{strategy_name} 策略",
        "states": context.get("strategy_states", {}),
        "ef_count": context.get("strategy_ef_count", 0),
        "capital_flow": {},
        "breakout_status": context.get("strategy_fit_status", ""),
        "sustained_days": context.get("strategy_sustained_days", 0),
    }
    diag_result = diagnoser.run(diag_ctx)
    if diag_result is None:
        diag_result = {"conclusion": f"{strategy_name} 适配度诊断未获取"}

    # Step 3: 融合
    fusion_ctx = {
        "source_scenario": "strategy_fit",
        "draft": {
            "market_judge": judge_result,
            "strategy_diagnosis": diag_result,
        },
        "user_type": context.get("user_type", "执行型"),
    }
    return fusion.run(fusion_ctx)
