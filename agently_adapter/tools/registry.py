"""Bounded tool registry for Guianxiang / Agently scenarios.

This module intentionally keeps Tool and Skill as one concept: a named,
schema-described, permissioned callable with audit logging. Scenario modules
decide which tools are visible; the registry only enforces the boundary.
"""

from __future__ import annotations

import csv
import json
import re
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "outputs" / "tool_audit.jsonl"

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, dict[str, Any]]
    permission: str
    timeout_seconds: float
    rate_limit: str
    handler: ToolHandler

    def to_openai_tool(self) -> dict[str, Any]:
        """Return a function-calling compatible declaration."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for field, spec in self.input_schema.items():
            field_type = str(spec.get("type", "string"))
            properties[field] = {
                "type": field_type,
                "description": str(spec.get("description", "")),
            }
            if spec.get("required"):
                required.append(field)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        }


_TOOLS: dict[str, ToolDefinition] = {}
_RATE_BUCKETS: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_PERMISSION_RANK = {"read": 1, "write": 2, "admin": 3}


def register_tool(tool: ToolDefinition) -> ToolDefinition:
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,63}", tool.name):
        raise ValueError(f"invalid tool name: {tool.name}")
    if tool.permission not in {"read", "write", "admin"}:
        raise ValueError(f"invalid tool permission: {tool.permission}")
    _TOOLS[tool.name] = tool
    return tool


def get_tool(name: str) -> ToolDefinition | None:
    return _TOOLS.get(name)


def list_tools(names: list[str] | None = None) -> list[dict[str, Any]]:
    selected = names or sorted(_TOOLS.keys())
    return [
        _TOOLS[name].to_openai_tool()
        for name in selected
        if name in _TOOLS
    ]


def run_tool(
    name: str,
    params: dict[str, Any] | None = None,
    *,
    user: str = "anonymous",
    trace_id: str = "",
    allowed_tools: list[str] | None = None,
    max_permission: str = "read",
) -> dict[str, Any]:
    params = dict(params or {})
    started = time.monotonic()
    tool = _TOOLS.get(name)
    if allowed_tools is not None and name not in allowed_tools:
        result = _error(name, "tool_not_allowed", started)
        _audit(name, params, user, trace_id, result)
        return result
    if tool is None:
        result = _error(name, "tool_not_found", started)
        _audit(name, params, user, trace_id, result)
        return result
    if _PERMISSION_RANK.get(tool.permission, 99) > _PERMISSION_RANK.get(max_permission, 1):
        result = _error(name, f"permission_denied:{tool.permission}", started)
        _audit(name, params, user, trace_id, result)
        return result

    validation_error = _validate_params(tool, params)
    if validation_error:
        result = _error(name, validation_error, started)
        _audit(name, params, user, trace_id, result)
        return result

    rate_error = _check_rate_limit(tool, user)
    if rate_error:
        result = _error(name, rate_error, started)
        _audit(name, params, user, trace_id, result)
        return result

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(tool.handler, params)
        data = future.result(timeout=tool.timeout_seconds)
        result = {
            "ok": True,
            "tool": name,
            "data": data,
            "elapsed_ms": _elapsed_ms(started),
        }
    except TimeoutError:
        result = _error(name, "tool_timeout", started)
    except Exception as exc:
        result = _error(name, f"tool_error: {exc.__class__.__name__}", started)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    _audit(name, params, user, trace_id, result)
    return result


def _validate_params(tool: ToolDefinition, params: dict[str, Any]) -> str:
    for field, spec in tool.input_schema.items():
        if spec.get("required") and params.get(field) in (None, ""):
            return f"missing_required_param:{field}"
        if field not in params or params.get(field) in (None, ""):
            continue
        expected = str(spec.get("type", "string"))
        value = params[field]
        if expected == "string" and not isinstance(value, str):
            return f"invalid_param_type:{field}"
        if expected == "number" and not isinstance(value, (int, float)):
            return f"invalid_param_type:{field}"
        if expected == "integer" and not isinstance(value, int):
            return f"invalid_param_type:{field}"
        if expected == "boolean" and not isinstance(value, bool):
            return f"invalid_param_type:{field}"
    return ""


def _check_rate_limit(tool: ToolDefinition, user: str) -> str:
    limit = _parse_rate_limit(tool.rate_limit)
    if not limit:
        return ""
    max_calls, window_seconds = limit
    key = (user or "anonymous", tool.name)
    now = time.monotonic()
    bucket = _RATE_BUCKETS[key]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= max_calls:
        return "rate_limited"
    bucket.append(now)
    return ""


def _parse_rate_limit(rate_limit: str) -> tuple[int, int] | None:
    if not rate_limit:
        return None
    m = re.fullmatch(r"(\d+)/(second|minute|hour)", rate_limit.strip())
    if not m:
        return None
    unit_seconds = {"second": 1, "minute": 60, "hour": 3600}
    return int(m.group(1)), unit_seconds[m.group(2)]


def _error(name: str, message: str, started: float) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": name,
        "error": message,
        "elapsed_ms": _elapsed_ms(started),
    }


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _audit(
    name: str,
    params: dict[str, Any],
    user: str,
    trace_id: str,
    result: dict[str, Any],
) -> None:
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "trace_id": trace_id,
            "user": user or "anonymous",
            "tool": name,
            "permission": _TOOLS[name].permission if name in _TOOLS else "unknown",
            "params": _redact_params(params),
            "ok": bool(result.get("ok")),
            "error": result.get("error", ""),
            "elapsed_ms": result.get("elapsed_ms", 0),
        }
        with AUDIT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _redact_params(params: dict[str, Any]) -> dict[str, Any]:
    redacted = {}
    for key, value in params.items():
        if any(token in key.lower() for token in ("password", "token", "secret", "key")):
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted


def _latest_path(pattern: str) -> Path | None:
    paths = sorted(ROOT.glob(pattern))
    return paths[-1] if paths else None


def _read_json(path: Path | None) -> Any:
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalize_stock_code(stock_code: str) -> str:
    code = str(stock_code or "").strip().upper()
    if "." in code or not re.fullmatch(r"\d{6}", code):
        return code
    suffix = "SH" if code.startswith(("5", "6", "9")) else "SZ"
    return f"{code}.{suffix}"


def _stock_code_candidates(stock_code: str) -> list[str]:
    normalized = _normalize_stock_code(stock_code)
    raw = str(stock_code or "").strip().upper()
    bare = normalized.split(".", 1)[0]
    candidates = [normalized, raw, bare, f"{bare}.SZ", f"{bare}.SH"]
    deduped: list[str] = []
    for item in candidates:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _load_unified_stock_row(stock_code: str) -> dict[str, Any]:
    path = _latest_path("outputs/unified_view/unified_daily_snapshot_*.csv")
    if not path or not path.exists():
        return {}
    candidates = set(_stock_code_candidates(stock_code))
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                code = str(row.get("stock_code", "")).strip().upper()
                if code in candidates:
                    return dict(row)
    except Exception:
        return {}
    return {}


def _get_market_phase(_: dict[str, Any]) -> dict[str, Any]:
    path = _latest_path("outputs/market_phase/market_phase_*.json")
    payload = _read_json(path)
    if not isinstance(payload, dict):
        path = _latest_path("outputs/state_cache/market_phase_*.json")
        payload = _read_json(path)
    if not isinstance(payload, dict):
        return {"available": False, "reason": "market_phase_missing"}

    indicators = payload.get("indicators") or {}
    return {
        "available": True,
        "date": payload.get("date") or payload.get("state_date") or "",
        "phase_label": payload.get("phase_label") or payload.get("label") or "",
        "phase_summary": payload.get("phase_summary") or payload.get("summary") or "",
        "market_phase": payload.get("market_phase") or payload.get("phase") or "",
        "confidence": payload.get("confidence", ""),
        "pool_size": indicators.get("pool_size", ""),
        "pool_change_rate_5d": indicators.get("pool_change_rate_5d", ""),
        "source_path": str(path.relative_to(ROOT)) if path else "",
    }


def _get_stock_state(params: dict[str, Any]) -> dict[str, Any]:
    stock_code = str(params.get("stock_code", "")).strip().upper()
    row = _load_unified_stock_row(stock_code)
    if row:
        return {
            "available": True,
            "source": "unified_daily_snapshot",
            "stock_code": row.get("stock_code") or _normalize_stock_code(stock_code),
            "stock_name": row.get("stock_name") or "",
            "industry_name": row.get("sw_l1") or "",
            "snapshot_date": row.get("snapshot_date") or row.get("obs_date_x") or row.get("obs_date_y") or "",
            "stock_states": {
                "mn1": row.get("mn1_state_hex") or "",
                "w1": row.get("w1_state_hex") or "",
                "d1": row.get("d1_state_hex") or "",
                "mn1_score": row.get("mn1_state_score") or "",
                "w1_score": row.get("w1_state_score") or "",
                "d1_score": row.get("d1_state_score") or "",
            },
            "ef_count": _safe_int(row.get("ef_count"), 0),
            "capital_flow": {
                "status": row.get("moneyflow_status") or "",
                "score": row.get("moneyflow_score") or "",
                "confirmed": _truthy(row.get("moneyflow_confirmed")),
                "divergence": _truthy(row.get("moneyflow_divergence")),
            },
            "breakout_status": row.get("sr_boundary_type") or "",
            "sustained_days": _safe_int(row.get("duration_d1_close"), 0),
        }

    try:
        import duckdb
        from hermass_platform.agents.base_agent import find_foundation_db

        db_path = find_foundation_db()
        if not db_path:
            return {"available": False, "reason": "foundation_db_missing", "stock_code": stock_code}
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            placeholders = ",".join(["?"] * len(_stock_code_candidates(stock_code)))
            rows = con.execute(
                f"""
                SELECT stock_code, state_date, mn1_state_hex, w1_state_hex, d1_state_hex,
                       mn1_state_score, w1_state_score, d1_state_score, ef_count, d1_close
                FROM d1_perspective_state
                WHERE stock_code IN ({placeholders})
                ORDER BY state_date DESC
                LIMIT 1
                """,
                _stock_code_candidates(stock_code),
            ).fetchall()
        finally:
            con.close()
        if not rows:
            return {"available": False, "reason": "stock_not_found", "stock_code": stock_code}
        r = rows[0]
        return {
            "available": True,
            "source": "p116_foundation",
            "stock_code": r[0],
            "snapshot_date": str(r[1]),
            "stock_states": {
                "mn1": r[2] or "",
                "w1": r[3] or "",
                "d1": r[4] or "",
                "mn1_score": r[5] or "",
                "w1_score": r[6] or "",
                "d1_score": r[7] or "",
            },
            "ef_count": _safe_int(r[8], 0),
            "d1_close": r[9],
        }
    except Exception as exc:
        return {"available": False, "reason": f"foundation_query_error:{exc.__class__.__name__}", "stock_code": stock_code}


def _get_chain_position(params: dict[str, Any]) -> dict[str, Any]:
    stock_code = str(params.get("stock_code", "")).strip().upper()
    db_path = ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"
    if not db_path.exists():
        return {"available": False, "reason": "chain_db_missing", "stock_code": stock_code}
    try:
        import duckdb

        con = duckdb.connect(str(db_path), read_only=True)
        try:
            candidates = _stock_code_candidates(stock_code)
            placeholders = ",".join(["?"] * len(candidates))
            rows = con.execute(
                f"""
                SELECT stock_code, stock_name, chain_id, chain_name, node_id, node_name,
                       assistant_score, state_hex, ef_count, review_gate, state_date
                FROM chain_studio_candidates
                WHERE stock_code IN ({placeholders})
                ORDER BY state_date DESC, assistant_score DESC
                LIMIT 5
                """,
                candidates,
            ).fetchall()
        finally:
            con.close()
    except Exception as exc:
        return {"available": False, "reason": f"chain_query_error:{exc.__class__.__name__}", "stock_code": stock_code}

    return {
        "available": bool(rows),
        "stock_code": stock_code,
        "positions": [
            {
                "stock_code": r[0],
                "stock_name": r[1],
                "chain_id": r[2],
                "chain_name": r[3],
                "node_id": r[4],
                "node_name": r[5],
                "assistant_score": r[6],
                "state_hex": r[7],
                "ef_count": r[8],
                "review_gate": r[9],
                "state_date": str(r[10]),
            }
            for r in rows
        ],
    }


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}


def _create_user_watch_task(params: dict[str, Any]) -> dict[str, Any]:
    from agently_adapter.tools.user_tasks import create_user_watch_task

    stock_code = _normalize_stock_code(str(params.get("stock_code", "")))
    email = str(params.get("email", "")).strip()
    trigger_type = str(params.get("trigger_type") or "long_term_watch").strip()
    note = str(params.get("note") or "").strip()
    page_context = str(params.get("page_context") or "").strip()
    valid_days = max(1, min(_safe_int(params.get("valid_days"), 30), 180))

    if not _valid_email(email):
        return {"created": False, "reason": "invalid_email", "stock_code": stock_code}

    allowed_triggers = {
        "long_term_watch": ("long_term", "长期跟踪提醒"),
        "w1_breakout": ("conditional", "突破周线关键位提醒"),
        "state_drop": ("conditional", "D1 从 E/F 跌出提醒"),
        "d1_weakening_3d": ("conditional", "D1 连续走弱提醒"),
    }
    if trigger_type not in allowed_triggers:
        return {"created": False, "reason": "unsupported_trigger_type", "trigger_type": trigger_type}

    watch_type, default_note = allowed_triggers[trigger_type]
    return create_user_watch_task(
        stock_code=stock_code,
        email=email,
        trigger_type=trigger_type,
        watch_type=watch_type,
        note=note or default_note,
        valid_days=valid_days,
        page_context=page_context,
        created_by=str(params.get("created_by") or ""),
    )


def _list_user_tasks(params: dict[str, Any]) -> dict[str, Any]:
    from agently_adapter.tools.user_tasks import list_user_tasks

    return list_user_tasks(
        user=str(params.get("user") or ""),
        status=str(params.get("status") or ""),
        task_type=str(params.get("task_type") or ""),
        limit=_safe_int(params.get("limit"), 100),
    )


def _valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email))


register_tool(ToolDefinition(
    name="get_market_phase",
    description="读取当前市场阶段、宽度变化和阶段置信度。",
    input_schema={},
    permission="read",
    timeout_seconds=2,
    rate_limit="60/minute",
    handler=_get_market_phase,
))

register_tool(ToolDefinition(
    name="get_stock_state",
    description="读取某只股票最新 MN1/W1/D1 状态、EF 数量和资金流摘要。",
    input_schema={
        "stock_code": {"type": "string", "required": True, "description": "股票代码，如 000021 或 000021.SZ"},
    },
    permission="read",
    timeout_seconds=2,
    rate_limit="60/minute",
    handler=_get_stock_state,
))

register_tool(ToolDefinition(
    name="get_chain_position",
    description="读取某只股票在产业链工作台中的链条、节点和候选评分位置。",
    input_schema={
        "stock_code": {"type": "string", "required": True, "description": "股票代码，如 000021 或 000021.SZ"},
    },
    permission="read",
    timeout_seconds=2,
    rate_limit="60/minute",
    handler=_get_chain_position,
))

register_tool(ToolDefinition(
    name="create_user_watch_task",
    description="创建用户级 AI 盯盘任务，写入 user_task_ledger，由网站定时执行器后续消费。",
    input_schema={
        "stock_code": {"type": "string", "required": True, "description": "股票代码，如 000021 或 000021.SZ"},
        "email": {"type": "string", "required": True, "description": "接收提醒的邮箱"},
        "trigger_type": {
            "type": "string",
            "required": False,
            "description": "long_term_watch|w1_breakout|state_drop|d1_weakening_3d",
        },
        "valid_days": {"type": "integer", "required": False, "description": "有效天数，1-180"},
        "note": {"type": "string", "required": False, "description": "提醒备注"},
        "page_context": {"type": "string", "required": False, "description": "创建时所在页面"},
    },
    permission="write",
    timeout_seconds=2,
    rate_limit="5/minute",
    handler=_create_user_watch_task,
))

register_tool(ToolDefinition(
    name="list_user_tasks",
    description="列出用户级任务账本中的任务状态，用于查看已创建的盯盘和后续 AI work 任务。",
    input_schema={
        "user": {"type": "string", "required": False, "description": "用户名；为空时返回未绑定用户的任务"},
        "status": {"type": "string", "required": False, "description": "active|cancelled 等状态过滤"},
        "task_type": {"type": "string", "required": False, "description": "任务类型，如 watch_command"},
        "limit": {"type": "integer", "required": False, "description": "最大返回数量"},
    },
    permission="read",
    timeout_seconds=2,
    rate_limit="30/minute",
    handler=_list_user_tasks,
))
