from __future__ import annotations

import json

from scripts import process_watch_command_alerts as executor


def test_watch_executor_loads_user_tasks_separately_from_site_cron(tmp_path, monkeypatch):
    legacy_path = tmp_path / "outputs" / "alerts" / "watch_command_ledger.json"
    user_path = tmp_path / "outputs" / "user_tasks" / "user_task_ledger.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.parent.mkdir(parents=True, exist_ok=True)

    legacy_path.write_text(
        json.dumps({
            "version": "1.0.0",
            "commands": [
                {
                    "watch_id": "watch_legacy_001",
                    "stock_code": "000001.SZ",
                    "trigger_type": "long_term_watch",
                    "status": "active",
                    "email": "legacy@example.com",
                }
            ],
        }),
        encoding="utf-8",
    )
    user_path.write_text(
        json.dumps({
            "version": "1.0.0",
            "tasks": [
                {
                    "task_id": "user_watch_001",
                    "task_type": "watch_command",
                    "stock_code": "000021.SZ",
                    "trigger_type": "w1_breakout",
                    "status": "active",
                    "email": "user@example.com",
                }
            ],
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(executor, "LEDGER", legacy_path)
    monkeypatch.setattr(executor, "USER_TASK_LEDGER", user_path)

    records, legacy, user_tasks = executor._load_watch_records()

    assert len(records) == 2
    assert records[0]["_ledger"] == "watch_command_ledger"
    assert records[1]["_ledger"] == "user_task_ledger"
    assert records[1]["watch_id"] == "user_watch_001"
    assert legacy["commands"][0]["watch_id"] == "watch_legacy_001"
    assert user_tasks["tasks"][0]["task_id"] == "user_watch_001"
