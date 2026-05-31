"""场景编排中心 —— 每个场景是 2-4 个 Agent 的固定编排链。"""

from typing import Any

from agently_adapter.scenarios import market_overview, stock_checkup, industry_scan
from agently_adapter.scenarios import strategy_fit, watch_command, learn_topic

SCENARIO_MAP: dict[str, Any] = {
    "market_overview": market_overview,
    "stock_checkup": stock_checkup,
    "industry_scan": industry_scan,
    "strategy_fit": strategy_fit,
    "watch_command": watch_command,
    "learn_topic": learn_topic,
}


def get_scenario_module(name: str):
    """按名称获取场景模块。"""
    return SCENARIO_MAP.get(name)


def list_scenarios() -> list[str]:
    """列出所有可用场景。"""
    return list(SCENARIO_MAP.keys())
