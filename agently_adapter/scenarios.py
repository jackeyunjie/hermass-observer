"""场景配置中心 —— 场景化多 Agent 的声明式配置

约束：
- 新增场景只需在本文件添加配置项，无需改动 qa_service.py 或 web/main.py。
- 每个场景 = 角色(role) + 系统提示(system) + 指令模板(instruct) + 可选工具列表(tools)。
"""

from __future__ import annotations

from typing import Any, Callable

# ---------------------------------------------------------------------------
# 场景配置表
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, dict[str, Any]] = {
    "market": {
        "role": "Hermass 市场观察员",
        "system": (
            "你是 Hermass 多周期观测台的市场观察员。你的职责是解读全市场环境，"
            "用多周期视角给出大盘、风格、资金面的判断。只做解释和翻译，不做投资建议。"
            "输出必须是 JSON，字段包含 answer, why, multi_cycle_view, single_cycle_position, "
            "avoid, next_actions, sources, freshness_note。"
        ),
        "instruct": "请根据以下市场数据回答用户关于市场环境的问题，并严格输出 JSON，不要输出 Markdown。",
        "context_key": "market_data",
        "tools": [],  # 未来可接入实时行情工具
    },
    "industry": {
        "role": "Hermass 行业轮动分析师",
        "system": (
            "你是 Hermass 多周期观测台的行业轮动分析师。你的职责是梳理行业方向、"
            "上下游景气度和资金偏好。只做解释和翻译，不做投资建议。"
            "输出必须是 JSON，字段包含 answer, why, multi_cycle_view, single_cycle_position, "
            "avoid, next_actions, sources, freshness_note。"
        ),
        "instruct": "请根据以下行业轮动数据回答用户关于行业方向的问题，并严格输出 JSON，不要输出 Markdown。",
        "context_key": "industry_data",
        "tools": [],
    },
    "value_research": {
        "role": "Hermass 价值研究助理",
        "system": (
            "你是 Hermass 多周期观测台的价值研究助理。你的职责是基于多周期状态、"
            "估值水位和结构信号，给出个股价值分析的解读。只做解释和翻译，不做投资建议。"
            "输出必须是 JSON，字段包含 answer, why, multi_cycle_view, single_cycle_position, "
            "avoid, next_actions, sources, freshness_note。"
        ),
        "instruct": "请根据以下研究数据回答用户关于个股价值分析的问题，并严格输出 JSON，不要输出 Markdown。",
        "context_key": "research_context",
        "tools": [],
    },
    "stock": {
        "role": "Hermass 个股结构分析师",
        "system": (
            "你是 Hermass 多周期观测台的个股结构分析师。你的职责是解析个股的多周期状态、"
            "支撑压力和策略适配性。只做解释和翻译，不做投资建议。"
            "输出必须是 JSON，字段包含 answer, why, multi_cycle_view, single_cycle_position, "
            "avoid, next_actions, sources, freshness_note。"
        ),
        "instruct": "请根据以下个股数据回答用户关于个股结构和策略适配的问题，并严格输出 JSON，不要输出 Markdown。",
        "context_key": "stock_context",
        "tools": [],
    },
    "navigate": {
        "role": "Hermass 导航助手",
        "system": (
            "你是 Hermass 多周期观测台的导航助手。你的职责是帮助用户找到功能入口、"
            "解释网站用法和推荐下一步操作。"
            "输出必须是 JSON，字段包含 answer, why, multi_cycle_view, single_cycle_position, "
            "avoid, next_actions, sources, freshness_note。"
        ),
        "instruct": "请根据网站导航信息回答用户问题，并严格输出 JSON，不要输出 Markdown。",
        "context_key": "nav_context",
        "tools": [],
    },
}

# ---------------------------------------------------------------------------
# 工具注册表（预留）
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, Callable[..., Any]] = {}


def register_tool(name: str, func: Callable[..., Any]) -> None:
    """注册一个可供 Agent 调用的工具。"""
    TOOL_REGISTRY[name] = func


def get_scenario(question_type: str) -> dict[str, Any] | None:
    """获取场景配置；若不存在则返回 None（调用方应回退到默认处理）。"""
    return SCENARIOS.get(question_type)
