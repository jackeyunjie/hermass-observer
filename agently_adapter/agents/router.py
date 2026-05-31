"""场景路由 Agent —— LLM 判断用户问题对应哪个场景编排链。"""

from __future__ import annotations

from typing import Any

from agently_adapter.agents.base import create_agent, safe_get_response

PROMPT = (
    "你是 Hermass 的「问题路由器」。你只负责判断用户问题的类型，不回答问题本身。\n\n"
    "## 场景定义\n"
    "1. market_overview — 市场全景：「大盘怎么样」「现在能不能做」「市场环境」\n"
    "2. stock_checkup — 个股问诊：「000021 怎么样」「这只股能买吗」「分析这只」\n"
    "3. industry_scan — 行业扫描：「电子行业」「哪些行业在动」「板块轮动」\n"
    "4. strategy_fit — 策略适配：「VCP 适合现在吗」「策略环境」「哪个策略好」\n"
    "5. watch_command — 盯盘任务：「帮我盯着 000021」「突破提醒」「止损提醒」\n"
    "6. learn_topic — 学习训练：「什么是 State」「E 代表什么」「解释一下」\n"
    "7. chitchat — 闲聊/问候/其他\n\n"
    "## 路由规则\n"
    "- 一个问题可能同时命中多个场景（如「现在能不能做电力设备」= market + industry），"
    "  此时选 confidence 最高的主场景，并在 secondary_scenario 中标注次场景。\n"
    "- 如果用户在 watchlist 页面且问题很短（如「这只怎么样」），默认走 stock_checkup。\n"
    "- 包含股票代码的，优先 stock_checkup 或 watch_command。\n"
)


def run(user_input: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """返回路由结果：scenario, confidence, extracted_symbol, extracted_keywords, user_intent"""
    agent = create_agent()
    agent.system(PROMPT)
    agent.instruct("根据以下用户输入和上下文，判断场景类型。")
    agent.input(
        f"用户问题：{user_input}\n"
        f"当前页面：{context.get('current_page', 'unknown')}\n"
        f"当前股票代码：{context.get('symbol', '无')}\n"
        f"用户类型：{context.get('user_type', '执行型')}"
    )
    agent.output({
        "scenario": (str, "主场景：market_overview|stock_checkup|industry_scan|strategy_fit|watch_command|learn_topic|chitchat", True),
        "secondary_scenario": (str, "次场景（如有），否则空字符串", True),
        "confidence": (float, "置信度 0.0-1.0", True),
        "extracted_symbol": (str, "提取的股票代码或空字符串", True),
        "extracted_keywords": ([str], "关键词列表", True),
        "user_intent": (str, "一句话概括用户意图", True),
    })
    return safe_get_response(agent)
