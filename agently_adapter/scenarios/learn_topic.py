"""学习训练场景 —— 翻译(带示例) → 融合"""

from __future__ import annotations

from typing import Any

from agently_adapter.agents import translator, fusion


def run(user_input: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """学习训练场景：把概念翻译成用户能懂的语言，带示例。"""
    # Step 1: 翻译 —— 直接以用户问题为 raw_data，让翻译 Agent 解释概念
    trans_ctx = {
        "raw_data": {
            "user_question": user_input,
            "topic": context.get("topic", user_input),
            "state_hex": context.get("state_hex", ""),
        },
        "user_type": context.get("user_type", "研究型"),  # 学习场景默认研究型语气
    }
    trans_result = translator.run(trans_ctx)
    if trans_result is None:
        trans_result = {
            "meaning": "概念解释未获取",
            "what_it_says": "",
            "season": "",
            "how_to_read": "",
        }

    # Step 2: 融合 —— 统一格式
    fusion_ctx = {
        "source_scenario": "learn_topic",
        "draft": {"translation": trans_result},
        "user_type": context.get("user_type", "研究型"),
    }
    return fusion.run(fusion_ctx)
