"""Hermass 统一问答服务层（Q&A Service Layer）

通过 Agently 框架统一管理大模型调用。
约束：Web 层不直接调用 Agently runtime，只调用 qa_ask(question_type, context)。
"""

from __future__ import annotations

import json
import os
from typing import Any

try:
    from agently import Agently
except ImportError:  # pragma: no cover
    Agently = None  # type: ignore[misc, assignment]

from agently_adapter.scenarios import get_scenario


def _init_settings() -> bool:
    """初始化 Agently DeepSeek 配置。"""
    if Agently is None:
        return False
    api_key = (
        os.environ.get("HERMASS_DEEPSEEK_API_KEY", "").strip()
        or os.environ.get("DEEPSEEK_API_KEY", "").strip()
    )
    if not api_key:
        return False
    model = (
        os.environ.get("HERMASS_DEEPSEEK_MODEL", "").strip()
        or os.environ.get("HERMASS_LLM_MODEL", "deepseek-chat").strip()
    )
    base_url = (
        os.environ.get("HERMASS_DEEPSEEK_BASE_URL", "").strip()
        or os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").strip()
    )
    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    try:
        Agently.set_settings(
            "OpenAICompatible",
            {"base_url": base_url, "api_key": api_key, "model": model},
        )
        return True
    except Exception:
        return False


def _build_payload(scenario: dict[str, Any], context: dict[str, Any]) -> str:
    """将上下文打包为 JSON payload。"""
    key = scenario.get("context_key", "context")
    return json.dumps({key: context}, ensure_ascii=False, indent=2)


def qa_ask(question_type: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """统一问答入口。

    Args:
        question_type: market / industry / value_research / stock / navigate
        context: 该场景需要的结构化数据（如 market_data, industry_data 等）

    Returns:
        Agently 结构化 JSON 或 None（失败时调用方应回退规则回答）
    """
    if not _init_settings():
        return None

    scenario = get_scenario(question_type)
    if scenario is None:
        return None

    try:
        agent = Agently.create_agent()
        agent.role(scenario["role"])
        agent.system(scenario["system"])
        agent.instruct(
            scenario["instruct"]
            + "\n"
            + _build_payload(scenario, context)
        )
        agent.output({
            "answer": (str, "核心结论，30字以内", True),
            "why": (str, "2-3个理由，用数据说话", True),
            "multi_cycle_view": (str, "多周期视角判断", True),
            "single_cycle_position": (str, "单周期位置判断", True),
            "avoid": (str, "风险提示", True),
            "next_actions": ([{"label": str, "url": str}], "建议动作列表", True),
            "sources": ([str], "数据来源列表", True),
            "freshness_note": (str, "数据时效说明", True),
        })

        # TODO: 注册场景工具（当 Agently DevTools 就绪后启用）
        # for tool_name in scenario.get("tools", []):
        #     ...

        response = agent.get_response()
        result = response.result.get_data() if response.result else {}
        return result if isinstance(result, dict) else None
    except Exception:
        return None
