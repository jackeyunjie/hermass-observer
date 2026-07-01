"""DeepSeek / Agently 共享调用层，统一模型别名、初始化与 JSON 解析。"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

try:
    from agently import Agently
except ImportError:  # pragma: no cover
    Agently = None  # type: ignore[misc, assignment]

from agently_adapter.agents.base import _ensure_settings  # noqa: F401
from agently_adapter.tools import run_tool


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
    system_prompt: str = "",
    instruct: str = "",
    tools: list[dict[str, Any]] | None = None,
    allowed_tools: list[str] | None = None,
    user: str = "anonymous",
    trace_id: str = "",
    max_tool_rounds: int = 2,
    max_permission: str = "read",
) -> dict[str, Any] | None:
    """统一 DeepSeek 调用。

    When tools are supplied, use the OpenAI-compatible HTTP API because it
    exposes tool_calls directly. Without tools, keep the existing Agently path.
    """
    if tools:
        return call_with_tools(
            payload,
            system_prompt=system_prompt,
            instruct=instruct,
            tools=tools,
            allowed_tools=allowed_tools,
            user=user,
            trace_id=trace_id,
            max_tool_rounds=max_tool_rounds,
            max_permission=max_permission,
        )
    if Agently is None or not _ensure_settings():
        return None
    try:
        agent = Agently.create_agent()
        agent.system(system_prompt or DEFAULT_SYSTEM_PROMPT)
        agent.instruct(instruct or DEFAULT_INSTRUCT)
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


DEFAULT_SYSTEM_PROMPT = (
    "你是 Hermass 观象助手，只做研究解释、证据整理和导航，不做交易执行。"
    "回答必须先给结论，再给证据、风险边界和下一步。"
)

DEFAULT_INSTRUCT = "请根据结构化输入回答，并严格输出 JSON，不要输出 Markdown。"


def call_with_tools(
    payload: dict[str, Any],
    *,
    system_prompt: str = "",
    instruct: str = "",
    tools: list[dict[str, Any]],
    allowed_tools: list[str] | None = None,
    user: str = "anonymous",
    trace_id: str = "",
    max_tool_rounds: int = 2,
    max_permission: str = "read",
) -> dict[str, Any] | None:
    """Call DeepSeek with a bounded local tool loop."""
    client = _DeepSeekHttpClient.from_env()
    if client is None:
        return None

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                (instruct or DEFAULT_INSTRUCT)
                + "\n\n结构化输入：\n"
                + json.dumps(payload, ensure_ascii=False, indent=2, default=str)
                + "\n\n输出必须是 JSON，字段至少包含 answer/why/multi_cycle_view/single_cycle_position/avoid/next_actions/sources/freshness_note。"
            ),
        },
    ]
    tool_audit: list[dict[str, Any]] = []

    for _ in range(max(0, max_tool_rounds)):
        message = client.chat(messages, tools=tools)
        if message is None:
            return None
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return _parse_message_content(message, tool_audit)

        messages.append(message)
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            name = str(function.get("name") or "")
            args = _parse_tool_arguments(function.get("arguments"))
            result = run_tool(
                name,
                args,
                user=user,
                trace_id=trace_id,
                allowed_tools=allowed_tools,
                max_permission=max_permission,
            )
            tool_audit.append({
                "tool": name,
                "ok": result.get("ok", False),
                "error": result.get("error", ""),
                "elapsed_ms": result.get("elapsed_ms", 0),
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })

    final_message = client.chat(messages, tools=None)
    return _parse_message_content(final_message, tool_audit) if final_message else None


class _DeepSeekHttpClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 25):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "_DeepSeekHttpClient | None":
        api_key = (
            os.environ.get("HERMASS_DEEPSEEK_API_KEY", "").strip()
            or os.environ.get("DEEPSEEK_API_KEY", "").strip()
        )
        if not api_key:
            return None
        base_url = (
            os.environ.get("HERMASS_DEEPSEEK_BASE_URL", "").strip()
            or os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").strip()
        )
        if not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        model = (
            os.environ.get("HERMASS_DEEPSEEK_MODEL", "").strip()
            or os.environ.get("HERMASS_LLM_MODEL", "deepseek-chat").strip()
        )
        model = model if model != "deepseekV4" else "deepseek-chat"
        return cls(base_url=base_url, api_key=api_key, model=model)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any] | None:
        request_json: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 1800,
            "response_format": {"type": "json_object"},
        }
        if tools:
            request_json["tools"] = tools
            request_json["tool_choice"] = "auto"

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_json,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            message = data.get("choices", [{}])[0].get("message")
            return message if isinstance(message, dict) else None
        except Exception:
            return None


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str) or not arguments.strip():
        return {}
    try:
        parsed = json.loads(arguments)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _parse_message_content(
    message: dict[str, Any],
    tool_audit: list[dict[str, Any]],
) -> dict[str, Any] | None:
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        parsed = json.loads(content)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    if tool_audit:
        trace = dict(parsed.get("trace") or {})
        trace.setdefault("llm_tools", tool_audit)
        parsed["trace"] = trace
    return parsed
