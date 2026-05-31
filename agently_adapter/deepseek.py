"""DeepSeek / Agently 共享调用层，统一模型别名、初始化与 JSON 解析。"""

from __future__ import annotations

import json
import os
from typing import Any

try:
    from agently import Agently
except ImportError:  # pragma: no cover
    Agently = None  # type: ignore[misc, assignment]

_SETTINGS_READY = False


def _ensure_settings() -> bool:
    """确保 Agently DeepSeek 配置已初始化（幂等）。"""
    global _SETTINGS_READY
    if _SETTINGS_READY:
        return True
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
    model = model if model != "deepseekV4" else "deepseek-chat"
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
        _SETTINGS_READY = True
        return True
    except Exception:
        return False


OUTPUT_SCHEMA = {
    "answer": "string",
    "why": "string",
    "multi_cycle_view": "string",
    "single_cycle_position": "string",
    "avoid": "string",
    "next_actions": [{"label": "string", "url": "string"}],
    "sources": ["string"],
    "freshness_note": "string",
}


def call(
    payload: dict[str, Any],
    *,
    system_prompt: str,
    instruct: str,
) -> dict[str, Any] | None:
    """统一 DeepSeek Agently 调用。"""
    if Agently is None or not _ensure_settings():
        return None
    try:
        agent = Agently.create_agent()
        agent.system(system_prompt)
        agent.instruct(instruct)
        agent.input(
            "请根据以下结构化输入回答，并严格输出 JSON，不要输出 Markdown。\n"
            + json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        )
        agent.output(OUTPUT_SCHEMA)
        response = agent.start()
        if isinstance(response, dict):
            return response
        if isinstance(response, str):
            parsed = json.loads(response)
            return parsed if isinstance(parsed, dict) else None
        return None
    except Exception:
        return None
