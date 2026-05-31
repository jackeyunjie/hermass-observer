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


def _pick_prompt(question_type: str, context: dict[str, Any]) -> tuple[str, str, str]:
    """根据场景选择系统提示词、指令和 payload。

    返回 (system_prompt, instruct, payload_json)
    """
    system = (
        "你是 Hermass 多周期观测台的 AI 助手。你只做解释、翻译和导航，不做投资建议。"
        "你必须坚持多周期环境、单周期位置、风险控制这条主线。"
        "输出必须是 JSON，字段包含 answer, why, multi_cycle_view, single_cycle_position, "
        "avoid, next_actions, sources, freshness_note。"
    )

    templates: dict[str, tuple[str, str]] = {
        "market": ("请根据以下市场数据回答用户关于市场环境的问题。", "market_data"),
        "industry": ("请根据以下行业轮动数据回答用户关于行业方向的问题。", "industry_data"),
        "value_research": ("请根据以下价值研究数据回答用户关于个股价值分析的问题。", "research_context"),
        "stock": ("请根据以下个股数据回答用户关于个股结构和策略适配的问题。", "stock_context"),
    }

    instruct, key = templates.get(question_type, ("请回答用户问题。", "context"))
    payload = json.dumps({key: context}, ensure_ascii=False, indent=2)
    return system, instruct, payload


def qa_ask(question_type: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """统一问答入口。

    Args:
        question_type: market / industry / value_research / stock
        context: 该场景需要的结构化数据（如 market_data, industry_data 等）

    Returns:
        Agently 结构化 JSON 或 None（失败时调用方应回退规则回答）
    """
    if not _init_settings():
        return None

    try:
        agent = Agently.create_agent()
        system, instruct, payload = _pick_prompt(question_type, context)
        agent.system(system)
        agent.instruct(instruct)
        agent.input(
            "请根据以下结构化输入回答，并严格输出 JSON，不要输出 Markdown。\n" + payload
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

        response = agent.get_response()
        result = response.result.get_data() if response.result else {}
        return result if isinstance(result, dict) else None
    except Exception:
        return None
