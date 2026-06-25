from __future__ import annotations

import json

from agently_adapter.tools import registry, user_tasks
from agently_adapter.tools.registry import ToolDefinition, register_tool, run_tool


def test_tool_registry_runs_allowed_tool_and_writes_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "AUDIT_PATH", tmp_path / "tool_audit.jsonl")

    register_tool(ToolDefinition(
        name="unit_echo_tool",
        description="echo test tool",
        input_schema={
            "message": {"type": "string", "required": True, "description": "message"},
        },
        permission="read",
        timeout_seconds=1,
        rate_limit="100/minute",
        handler=lambda params: {"echo": params["message"]},
    ))

    result = run_tool(
        "unit_echo_tool",
        {"message": "hello"},
        user="tester",
        trace_id="trace1",
        allowed_tools=["unit_echo_tool"],
    )

    assert result["ok"] is True
    assert result["data"] == {"echo": "hello"}

    rows = (tmp_path / "tool_audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    audit = json.loads(rows[0])
    assert audit["tool"] == "unit_echo_tool"
    assert audit["ok"] is True
    assert audit["trace_id"] == "trace1"


def test_tool_registry_blocks_unallowed_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "AUDIT_PATH", tmp_path / "tool_audit.jsonl")

    register_tool(ToolDefinition(
        name="unit_private_tool",
        description="private test tool",
        input_schema={},
        permission="read",
        timeout_seconds=1,
        rate_limit="100/minute",
        handler=lambda params: {"ok": True},
    ))

    result = run_tool(
        "unit_private_tool",
        {},
        user="tester",
        trace_id="trace2",
        allowed_tools=["other_tool"],
    )

    assert result["ok"] is False
    assert result["error"] == "tool_not_allowed"
    audit = json.loads((tmp_path / "tool_audit.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert audit["ok"] is False
    assert audit["error"] == "tool_not_allowed"


def test_tool_registry_blocks_write_tool_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "AUDIT_PATH", tmp_path / "tool_audit.jsonl")

    register_tool(ToolDefinition(
        name="unit_write_tool",
        description="write test tool",
        input_schema={},
        permission="write",
        timeout_seconds=1,
        rate_limit="100/minute",
        handler=lambda params: {"created": True},
    ))

    result = run_tool(
        "unit_write_tool",
        {},
        user="tester",
        trace_id="trace_write",
        allowed_tools=["unit_write_tool"],
    )

    assert result["ok"] is False
    assert result["error"] == "permission_denied:write"


def test_create_user_watch_task_requires_explicit_write_permission(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "AUDIT_PATH", tmp_path / "tool_audit.jsonl")
    monkeypatch.setattr(registry, "ROOT", tmp_path)
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", tmp_path / "outputs" / "user_tasks" / "user_task_ledger.json")

    result = run_tool(
        "create_user_watch_task",
        {
            "stock_code": "000021",
            "email": "test@example.com",
            "trigger_type": "w1_breakout",
            "valid_days": 30,
            "note": "突破周线关键位提醒",
        },
        user="tester",
        trace_id="trace_watch",
        allowed_tools=["create_user_watch_task"],
        max_permission="write",
    )

    assert result["ok"] is True
    assert result["data"]["created"] is True
    ledger = tmp_path / "outputs" / "user_tasks" / "user_task_ledger.json"
    assert ledger.exists()
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    task = payload["tasks"][0]
    assert task["stock_code"] == "000021.SZ"
    assert task["task_type"] == "watch_command"
    assert task["trigger_type"] == "w1_breakout"
    assert task["created_from"] == "guanxiang_user_task"
    assert not (tmp_path / "outputs" / "alerts" / "watch_command_ledger.json").exists()


def test_builtin_tools_are_declared():
    names = {tool["function"]["name"] for tool in registry.list_tools()}
    assert {"get_market_phase", "get_stock_state", "get_chain_position", "create_user_watch_task"} <= names
