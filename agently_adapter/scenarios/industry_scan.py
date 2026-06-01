"""行业扫描场景 —— 判官 → 行业 → 翻译 → 融合"""

from __future__ import annotations

from typing import Any

from agently_adapter.agents import judge, industry, translator, fusion


def run(user_input: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """行业扫描场景编排链。"""
    # Step 1: 判官 —— 先看市场环境（行业分析需要市场背景）
    judge_ctx = {"market_data": context.get("market_data", {})}
    judge_result = judge.run(judge_ctx)
    if judge_result is None:
        judge_result = {"environment": "市场环境未获取"}

    # Step 2: 行业 —— 分析具体行业
    industry_ctx = {
        "industry_name": context.get("industry_name", ""),
        "distribution": context.get("industry_distribution", {}),
        "capital_flow": context.get("industry_capital_flow", {}),
    }
    industry_result = industry.run(industry_ctx)
    if industry_result is None:
        industry_result = {"industry_state": "行业分析未获取"}

    # Step 3: 翻译 —— 把行业和判官结论翻译成用户语言
    trans_ctx = {
        "raw_data": {"market": judge_result, "industry": industry_result},
        "user_type": context.get("user_type", "执行型"),
    }
    trans_result = translator.run(trans_ctx)
    if trans_result is None:
        trans_result = {"raw_fallback": str(industry_result)}

    # Step 4: 融合
    fusion_ctx = {
        "source_scenario": "industry_scan",
        "draft": {
            "market_judge": judge_result,
            "industry_analysis": industry_result,
            "translation": trans_result,
        },
        "user_type": context.get("user_type", "执行型"),
        "recent_turns": context.get("recent_turns", []),
    }
    return fusion.run(fusion_ctx)
