from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from agently_adapter.tools import user_tasks
from web.main import app


def _basic_auth_header(username: str = "hermass-test", password: str = "Hermass2026!Lab") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_daily_observation_brief_allows_anonymous_without_user_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", tmp_path / "user_task_ledger.json")

    client = TestClient(app)
    response = client.get("/api/daily-observation-brief")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["task_scope"]["site_tasks"] == "config/hermes_cron.json"
    assert payload["task_scope"]["user_tasks"] == "not_authenticated"
    assert payload["active_user_tasks"] == []
    assert "decision" in payload
    assert "watch_candidates" in payload


def test_daily_observation_brief_includes_authenticated_user_tasks(tmp_path, monkeypatch):
    ledger = tmp_path / "user_task_ledger.json"
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", ledger)
    created = user_tasks.create_user_watch_task(
        stock_code="000021.SZ",
        email="test@example.com",
        trigger_type="w1_breakout",
        watch_type="conditional",
        note="突破周线关键位提醒",
        valid_days=30,
        created_by="hermass-test",
    )

    client = TestClient(app)
    response = client.get("/api/daily-observation-brief", headers=_basic_auth_header())

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["task_scope"]["user_tasks"] == "user_task_ledger"
    assert payload["active_user_tasks"][0]["task_id"] == created["task"]["task_id"]
    assert "000021.SZ" in payload["tracked_stock_codes"]
    assert "outputs/user_tasks/user_task_ledger.json" in payload["sources"]
