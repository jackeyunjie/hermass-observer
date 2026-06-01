"""市场全景场景 —— 判官 → 翻译 → 融合"""

from __future__ import annotations

from typing import Any

from agently_adapter.agents import judge, translator, fusion


def run(user_input: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """市场全景场景编排链。"""
    # Step 1: 判官 —— 市场定性
    judge_ctx = {"market_data": context.get("market_data", {})}
    judge_result = judge.run(judge_ctx)
    if judge_result is None:
        return None

    # Step 2: 翻译 —— 把判官结论翻译成用户语言
    trans_ctx = {
        "raw_data": judge_result,
        "user_type": context.get("user_type", "执行型"),
    }
    trans_result = translator.run(trans_ctx)
    if trans_result is None:
        trans_result = {"raw_fallback": str(judge_result)}

    # Step 3: 融合 —— 质检+统一格式
    fusion_ctx = {
        "source_scenario": "market_overview",
        "draft": {
            "judge": judge_result,
            "translator": trans_result,
        },
        "user_type": context.get("user_type", "执行型"),
        "recent_turns": context.get("recent_turns", []),
    }
    return fusion.run(fusion_ctx)
