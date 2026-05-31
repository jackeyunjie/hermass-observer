"""LLM Agent 集群 —— 每个 Agent 只干一件事，通过场景编排链组合。"""

from agently_adapter.agents.base import create_agent, safe_get_response
from agently_adapter.agents.router import run as router_run
from agently_adapter.agents.judge import run as judge_run
from agently_adapter.agents.translator import run as translator_run
from agently_adapter.agents.diagnoser import run as diagnoser_run
from agently_adapter.agents.industry import run as industry_run
from agently_adapter.agents.fusion import run as fusion_run

__all__ = [
    "create_agent",
    "safe_get_response",
    "router_run",
    "judge_run",
    "translator_run",
    "diagnoser_run",
    "industry_run",
    "fusion_run",
]
