"""External workflow bridge for Guanxiang chat expansion.

This adapter lets the web chat call a configured N8N, Dify, Coze, or generic
webhook without making that workflow a source of truth. It only normalizes the
workflow response into the Hermass chat contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Callable

import requests


RESPONSE_CONTRACT = {
    "answer": "string",
    "why": "string",
    "multi_cycle_view": "string",
    "single_cycle_position": "string",
    "avoid": "string",
    "next_actions": [{"label": "string", "url": "string"}],
    "sources": ["string"],
    "freshness_note": "string",
}

WORKFLOW_CONTEXT_KEYS = (
    "user_type",
    "current_page",
    "symbol",
    "mode",
    "recent_topics",
    "recent_stock_codes",
    "user_focus",
    "user_preferred_scenarios",
    "market_data",
    "industry_distribution",
    "industry_name",
    "stock_states",
    "value_prompt_pack",
    "value_payload",
    "search_data",
)

WORKFLOW_LOCAL_EVIDENCE_TOKENS = {
    "daily_snapshot",
    "industry_rotation",
    "ifind_industry_chain_profile",
    "market_phase",
    "market_views",
    "research_evidence",
    "state_cube",
    "valuation_reference",
    "watch_command",
    "watch_command_ledger",
    "page_context",
    "session_context",
}


@dataclass(frozen=True)
class WorkflowConfig:
    provider: str
    url: str
    api_key: str = ""
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    timeout_sec: float = 12.0


def load_config() -> WorkflowConfig | None:
    provider = os.environ.get("HERMASS_AI_WORKFLOW_PROVIDER", "").strip().lower()
    url = os.environ.get("HERMASS_AI_WORKFLOW_URL", "").strip()
    if not provider or not url:
        return None

    timeout_raw = os.environ.get("HERMASS_AI_WORKFLOW_TIMEOUT_SEC", "12").strip()
    try:
        timeout_sec = max(1.0, min(60.0, float(timeout_raw)))
    except Exception:
        timeout_sec = 12.0

    return WorkflowConfig(
        provider=provider,
        url=url,
        api_key=os.environ.get("HERMASS_AI_WORKFLOW_API_KEY", "").strip(),
        auth_header=os.environ.get("HERMASS_AI_WORKFLOW_AUTH_HEADER", "Authorization").strip()
        or "Authorization",
        auth_scheme=os.environ.get("HERMASS_AI_WORKFLOW_AUTH_SCHEME", "Bearer").strip(),
        timeout_sec=timeout_sec,
    )


def enabled() -> bool:
    return load_config() is not None


def _compact(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "<truncated>"
    if callable(value):
        return "<callable>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= 60:
                out["<truncated>"] = True
                break
            key_text = str(key)
            if key_text.lower() in {"api_key", "token", "password", "secret"}:
                continue
            if key_text in {"recent_turns", "value_call"}:
                continue
            out[key_text] = _compact(item, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_compact(item, depth=depth + 1) for item in list(value)[:30]]
    if isinstance(value, str):
        return value[:5000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[:5000]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return f"<{type(value).__name__}>"


def _workflow_context(context: dict[str, Any]) -> dict[str, Any]:
    return {key: _compact(context[key]) for key in WORKFLOW_CONTEXT_KEYS if key in context}


def _context_has_local_evidence(context: dict[str, Any]) -> bool:
    def _has_value(value: Any) -> bool:
        if value in (None, "", False):
            return False
        if isinstance(value, dict):
            return any(_has_value(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return any(_has_value(item) for item in value)
        return True

    for key in ("market_data", "industry_distribution", "industry_name", "stock_states", "value_payload", "search_data"):
        if key in context and _has_value(context[key]):
            return True
    return False


def build_payload(user_input: str, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "message": user_input,
        "query": user_input,
        "context": _workflow_context(context),
        "local_evidence_available": _context_has_local_evidence(context),
        "response_contract": RESPONSE_CONTRACT,
        "guardrails": {
            "research_only": True,
            "no_trade_execution": True,
            "no_position_sizing": True,
            "must_disclose_if_no_local_evidence": True,
        },
    }


def _headers(config: WorkflowConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        value = config.api_key
        if config.auth_scheme and config.auth_header.lower() == "authorization":
            value = f"{config.auth_scheme} {config.api_key}"
        headers[config.auth_header] = value
    return headers


def _maybe_parse_json_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    try:
        parsed = json.loads(text)
    except Exception:
        return value
    return parsed if isinstance(parsed, (dict, list)) else value


def _iter_response_dicts(raw: Any) -> list[dict[str, Any]]:
    queue: list[Any] = [raw]
    seen: set[int] = set()
    candidates: list[dict[str, Any]] = []

    while queue:
        item = _maybe_parse_json_text(queue.pop(0))
        if isinstance(item, list):
            queue.extend(item)
            continue
        if not isinstance(item, dict):
            continue
        marker = id(item)
        if marker in seen:
            continue
        seen.add(marker)
        candidates.append(item)
        for key in ("data", "result", "output", "outputs", "response", "body", "json", "payload", "messages", "message"):
            if key in item:
                queue.append(item[key])
    return candidates


def _first_nonempty_field(candidates: list[dict[str, Any]], field_names: tuple[str, ...]) -> Any:
    for candidate in candidates:
        for field_name in field_names:
            if field_name not in candidate:
                continue
            value = _maybe_parse_json_text(candidate.get(field_name))
            if value in (None, "", [], {}):
                continue
            return value
    return None


def _normalize_next_actions(raw_actions: Any) -> list[dict[str, str]]:
    if isinstance(raw_actions, dict):
        raw_actions = [raw_actions]
    if not isinstance(raw_actions, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in raw_actions:
        if isinstance(item, str):
            label = item.strip()
            if label:
                normalized.append({"label": label, "url": ""})
            continue
        if not isinstance(item, dict):
            continue
        label = ""
        for key in ("label", "title", "text", "name"):
            candidate = str(item.get(key) or "").strip()
            if candidate:
                label = candidate
                break
        url = ""
        for key in ("url", "href", "link", "path", "uri"):
            candidate = str(item.get(key) or "").strip()
            if candidate:
                url = candidate
                break
        if not label and not url:
            continue
        normalized.append({"label": label or url or "操作", "url": url})
    return normalized[:10]


def _normalize_sources(raw_sources: Any, provider: str) -> list[str]:
    if isinstance(raw_sources, dict):
        raw_sources = list(raw_sources.values())
    elif isinstance(raw_sources, str):
        raw_sources = [raw_sources]
    elif not isinstance(raw_sources, list):
        raw_sources = []

    normalized = ["external_workflow", f"workflow_{provider}"]
    for source in raw_sources:
        source_text = str(source).strip()
        if not source_text or source_text in WORKFLOW_LOCAL_EVIDENCE_TOKENS:
            continue
        if source_text not in normalized:
            normalized.append(source_text)
    return normalized


def _message_answer(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    fallback = ""
    for item in messages:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or item.get("answer") or "").strip()
        if not content:
            continue
        fallback = content
        role = str(item.get("role") or item.get("type") or "").lower()
        if role in {"assistant", "answer", "bot"}:
            return content
    return fallback


def _pick_response_object(raw: Any) -> dict[str, Any]:
    candidates = _iter_response_dicts(raw)
    for candidate in candidates:
        answer_value = _first_nonempty_field(candidate and [candidate] or [], ("answer", "output", "text", "content", "result"))
        if answer_value is not None:
            return candidate
        if _message_answer(candidate.get("messages")):
            return candidate
    return candidates[0] if candidates else {}


def normalize_response(raw: Any, provider: str) -> dict[str, Any] | None:
    candidates = _iter_response_dicts(raw)
    if not candidates:
        return None

    obj = _pick_response_object(raw)

    # 优先从 messages 数组提取 assistant 回答，避免在 candidates 中误匹配 user 消息的 content
    messages_list = obj.get("messages") if isinstance(obj, dict) else None
    if isinstance(messages_list, list):
        answer_value = _message_answer(messages_list)
    else:
        answer_value = _first_nonempty_field(candidates, ("answer", "output", "text", "content", "result"))
        if isinstance(answer_value, dict):
            answer_value = _first_nonempty_field([answer_value], ("answer", "output", "text", "content", "result"))
        if answer_value is None:
            answer_value = _message_answer(_first_nonempty_field(candidates, ("messages",)))

    answer = str(answer_value or "").strip()
    if not answer:
        return None

    sources = _normalize_sources(_first_nonempty_field(candidates, ("sources", "source", "citations", "references")), provider)
    next_actions = _normalize_next_actions(_first_nonempty_field(candidates, ("next_actions", "actions", "links")))

    return {
        "answer": answer,
        "why": str(_first_nonempty_field(candidates, ("why", "reason", "explanation")) or "外部工作流返回。"),
        "multi_cycle_view": str(_first_nonempty_field(candidates, ("multi_cycle_view", "multi_cycle", "market_view")) or ""),
        "single_cycle_position": str(_first_nonempty_field(candidates, ("single_cycle_position", "single_cycle", "position")) or ""),
        "avoid": str(_first_nonempty_field(candidates, ("avoid", "warning", "caution")) or "不要把外部工作流回答直接当成本地数据结论。"),
        "next_actions": next_actions,
        "sources": sources,
        "freshness_note": str(_first_nonempty_field(candidates, ("freshness_note", "freshness", "note")) or ""),
        "provider": f"workflow_{provider}",
        "workflow_provider": provider,
        "enhancement_used": True,
    }


def call_workflow(
    user_input: str,
    context: dict[str, Any],
    *,
    config: WorkflowConfig | None = None,
    post: Callable[..., Any] | None = None,
) -> dict[str, Any] | None:
    config = config or load_config()
    if config is None:
        return None

    post_func = post or requests.post
    payload = build_payload(user_input, context)
    try:
        response = post_func(
            config.url,
            headers=_headers(config),
            json=payload,
            timeout=config.timeout_sec,
        )
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        raw = response.json() if hasattr(response, "json") else response
    except Exception:
        return None

    result = normalize_response(raw, config.provider)
    if result is not None:
        result["workflow_local_support"] = _context_has_local_evidence(context)
    return result
