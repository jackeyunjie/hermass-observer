"""User-level task ledger for Guianxiang.

Website cron entries are infrastructure executors. User-created schedules live
here as product objects and can be consumed by those executors.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
USER_TASK_LEDGER = ROOT / "outputs" / "user_tasks" / "user_task_ledger.json"


def load_user_task_ledger(path: Path | None = None) -> dict[str, Any]:
    ledger_path = path or USER_TASK_LEDGER
    if not ledger_path.exists():
        return {"version": "1.0.0", "tasks": []}
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "1.0.0", "tasks": []}
    if not isinstance(payload, dict):
        return {"version": "1.0.0", "tasks": []}
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        payload["tasks"] = []
    payload.setdefault("version", "1.0.0")
    return payload


def save_user_task_ledger(payload: dict[str, Any], path: Path | None = None) -> None:
    ledger_path = path or USER_TASK_LEDGER
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def list_user_tasks(
    *,
    user: str = "",
    status: str = "",
    task_type: str = "",
    limit: int = 100,
    path: Path | None = None,
) -> dict[str, Any]:
    ledger = load_user_task_ledger(path)
    tasks = []
    for task in ledger.get("tasks", []) or []:
        if user and task.get("created_by") not in ("", None, user):
            continue
        if status and task.get("status") != status:
            continue
        if task_type and task.get("task_type") != task_type:
            continue
        tasks.append(task)
    tasks.sort(key=lambda row: str(row.get("created_at") or row.get("valid_from") or ""), reverse=True)
    return {"ok": True, "tasks": tasks[: max(1, min(int(limit or 100), 500))]}


def create_user_watch_task(
    *,
    stock_code: str,
    email: str,
    trigger_type: str,
    watch_type: str,
    note: str,
    valid_days: int,
    page_context: str = "",
    created_by: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    stock_code = str(stock_code or "").strip().upper()
    email = str(email or "").strip().lower()
    trigger_type = str(trigger_type or "").strip()
    watch_type = str(watch_type or "").strip()
    note = str(note or "").strip()
    today = date.today()
    ledger = load_user_task_ledger(path)
    tasks = ledger.setdefault("tasks", [])

    duplicate = next(
        (
            row for row in tasks
            if row.get("status") == "active"
            and str(row.get("stock_code", "")).strip().upper() == stock_code
            and str(row.get("email", "")).strip().lower() == email
            and row.get("trigger_type") == trigger_type
            and (not created_by or row.get("created_by") in ("", None, created_by))
        ),
        None,
    )
    if duplicate:
        return {
            "created": False,
            "reason": "duplicate_active_watch",
            "task_id": duplicate.get("task_id"),
            "stock_code": stock_code,
            "valid_to": duplicate.get("valid_to"),
        }

    task_id = f"user_watch_{today.strftime('%Y%m%d')}_{stock_code.replace('.', '')}_{len(tasks)+1:03d}"
    record = {
        "task_id": task_id,
        "task_type": "watch_command",
        "stock_code": stock_code,
        "watch_type": watch_type,
        "trigger_type": trigger_type,
        "email": email,
        "valid_from": today.isoformat(),
        "valid_to": (today + timedelta(days=valid_days)).isoformat(),
        "status": "active",
        "note": note,
        "created_from": "guanxiang_user_task",
        "created_by": created_by,
        "created_at": today.isoformat(),
        "page_context": page_context,
        "last_triggered_at": None,
    }
    tasks.append(record)
    ledger["tasks"] = tasks[-500:]
    save_user_task_ledger(ledger, path)
    return {"created": True, "task": record}


def cancel_user_task(task_id: str, *, user: str = "", path: Path | None = None) -> dict[str, Any]:
    ledger = load_user_task_ledger(path)
    for task in ledger.get("tasks", []) or []:
        if task.get("task_id") != task_id:
            continue
        if user and task.get("created_by") not in ("", None, user):
            return {"ok": False, "error": "forbidden"}
        if task.get("status") == "cancelled":
            return {"ok": True, "task": task}
        task["status"] = "cancelled"
        task["cancelled_at"] = date.today().isoformat()
        save_user_task_ledger(ledger, path)
        return {"ok": True, "task": task}
    return {"ok": False, "error": "task_not_found"}


# ── State Timeline 邮件订阅 ──


def _is_valid_email(email: str) -> bool:
    """极简邮箱格式校验。"""
    email = str(email or "").strip().lower()
    if not email or "@" not in email:
        return False
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        return False
    return True


def _normalize_state_timeline_symbol_set(symbol_set: str) -> str:
    value = str(symbol_set or "top50").strip().lower()
    return value or "top50"


def create_state_timeline_subscription(
    *,
    email: str,
    symbol_set: str = "top50",
    days: int = 3,
    note: str = "",
    page_context: str = "/state-observer",
    created_by: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    """创建 State Timeline 邮件订阅任务。

    去重规则：同一 created_by + email + symbol_set + days 的 active 订阅只保留一条。
    """
    email = str(email or "").strip().lower()
    symbol_set = _normalize_state_timeline_symbol_set(symbol_set)
    try:
        days = max(1, min(int(days or 3), 120))
    except (TypeError, ValueError):
        return {"created": False, "reason": "invalid_days", "task": None}
    note = str(note or "").strip()
    page_context = str(page_context or "/state-observer").strip()
    created_by = str(created_by or "").strip()

    if not _is_valid_email(email):
        return {"created": False, "reason": "invalid_email", "task": None}
    if symbol_set not in {"top50", "watchlist", "all"}:
        return {"created": False, "reason": "invalid_symbol_set", "task": None}

    today = date.today()
    ledger = load_user_task_ledger(path)
    tasks = ledger.setdefault("tasks", [])

    duplicate = next(
        (
            row for row in tasks
            if row.get("status") == "active"
            and row.get("task_type") == "state_timeline_digest"
            and str(row.get("email", "")).strip().lower() == email
            and str(row.get("symbol_set", "")).strip().lower() == symbol_set
            and int(row.get("days") or 0) == days
            and (not created_by or row.get("created_by") in ("", None, created_by))
        ),
        None,
    )
    if duplicate:
        return {
            "created": False,
            "reason": "duplicate_active_subscription",
            "task_id": duplicate.get("task_id"),
            "task": duplicate,
        }

    task_id = f"state_timeline_digest_{today.strftime('%Y%m%d')}_{len(tasks)+1:03d}"
    record = {
        "task_id": task_id,
        "task_type": "state_timeline_digest",
        "email": email,
        "symbol_set": symbol_set,
        "days": days,
        "valid_from": today.isoformat(),
        "valid_to": (today + timedelta(days=365)).isoformat(),
        "status": "active",
        "note": note,
        "created_from": "state_timeline_observer",
        "created_by": created_by,
        "created_at": today.isoformat(),
        "page_context": page_context,
        "last_triggered_at": None,
    }
    tasks.append(record)
    ledger["tasks"] = tasks[-500:]
    save_user_task_ledger(ledger, path)
    return {"created": True, "task": record}


def list_state_timeline_subscriptions(
    *,
    user: str = "",
    status: str = "active",
    limit: int = 100,
    path: Path | None = None,
) -> dict[str, Any]:
    """列出指定用户的 State Timeline 订阅。"""
    result = list_user_tasks(
        user=user,
        status=status,
        task_type="state_timeline_digest",
        limit=limit,
        path=path,
    )
    return {"ok": True, "subscriptions": result.get("tasks", [])}


def cancel_state_timeline_subscription(
    task_id: str,
    *,
    user: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    """取消 State Timeline 订阅。"""
    return cancel_user_task(task_id, user=user, path=path)
