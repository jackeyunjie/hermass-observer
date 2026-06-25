from __future__ import annotations

from agently_adapter.tools import user_tasks


def test_user_task_ledger_create_list_cancel(tmp_path):
    ledger = tmp_path / "user_task_ledger.json"

    created = user_tasks.create_user_watch_task(
        stock_code="000021.SZ",
        email="test@example.com",
        trigger_type="w1_breakout",
        watch_type="conditional",
        note="突破周线关键位提醒",
        valid_days=30,
        created_by="alice",
        path=ledger,
    )
    assert created["created"] is True
    task_id = created["task"]["task_id"]

    listed = user_tasks.list_user_tasks(user="alice", status="active", path=ledger)
    assert listed["ok"] is True
    assert len(listed["tasks"]) == 1
    assert listed["tasks"][0]["task_id"] == task_id

    forbidden = user_tasks.cancel_user_task(task_id, user="bob", path=ledger)
    assert forbidden == {"ok": False, "error": "forbidden"}

    cancelled = user_tasks.cancel_user_task(task_id, user="alice", path=ledger)
    assert cancelled["ok"] is True
    assert cancelled["task"]["status"] == "cancelled"


def test_user_task_dedup_normalizes_stock_code_and_email(tmp_path):
    ledger = tmp_path / "user_task_ledger.json"

    first = user_tasks.create_user_watch_task(
        stock_code="000021.sz",
        email="TEST@EXAMPLE.COM",
        trigger_type="w1_breakout",
        watch_type="conditional",
        note="突破周线关键位提醒",
        valid_days=30,
        created_by="alice",
        path=ledger,
    )
    second = user_tasks.create_user_watch_task(
        stock_code="000021.SZ",
        email="test@example.com",
        trigger_type="w1_breakout",
        watch_type="conditional",
        note="重复创建",
        valid_days=30,
        created_by="alice",
        path=ledger,
    )

    assert first["created"] is True
    assert first["task"]["stock_code"] == "000021.SZ"
    assert first["task"]["email"] == "test@example.com"
    assert second["created"] is False
    assert second["reason"] == "duplicate_active_watch"
    assert len(user_tasks.load_user_task_ledger(ledger)["tasks"]) == 1
