from __future__ import annotations

import base64
from http.cookies import SimpleCookie

from fastapi.testclient import TestClient

from agently_adapter.tools import user_tasks
from web.main import app


def _basic_auth_header(username: str = "hermass-test", password: str = "Hermass2026!Lab") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_user_tasks_api_allows_guest_session_create_list_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", tmp_path / "user_task_ledger.json")
    client = TestClient(app)
    created = client.post(
        "/api/user-tasks",
        json={"stock_code": "000021.SZ", "email": "test@example.com", "note": "免登录观察"},
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["ok"] is True
    assert payload["created"] is True
    assert payload["task"]["created_by"].startswith("visitor_")

    cookie_header = created.headers.get("set-cookie", "")
    assert "hermass_visitor_id=" in cookie_header
    visitor_cookie = SimpleCookie()
    visitor_cookie.load(cookie_header)
    visitor_id = visitor_cookie["hermass_visitor_id"].value

    client.cookies.set("hermass_visitor_id", visitor_id)

    listed = client.get("/api/user-tasks")
    assert listed.status_code == 200
    assert listed.json()["tasks"][0]["task_id"] == payload["task"]["task_id"]

    cancelled = client.post(f"/api/user-tasks/{payload['task']['task_id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["task"]["status"] == "cancelled"


def test_user_tasks_api_lists_and_cancels_user_task(tmp_path, monkeypatch):
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
    task_id = created["task"]["task_id"]

    client = TestClient(app)
    listed = client.get("/api/user-tasks", headers=_basic_auth_header())
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["ok"] is True
    assert payload["tasks"][0]["task_id"] == task_id

    cancelled = client.post(f"/api/user-tasks/{task_id}/cancel", headers=_basic_auth_header())
    assert cancelled.status_code == 200
    assert cancelled.json()["task"]["status"] == "cancelled"


def test_user_tasks_api_creates_task_from_homepage_candidate(tmp_path, monkeypatch):
    ledger = tmp_path / "user_task_ledger.json"
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", ledger)

    client = TestClient(app)
    response = client.post(
        "/api/user-tasks",
        headers=_basic_auth_header(),
        json={
            "stock_code": "000021.SZ",
            "email": "test@example.com",
            "trigger_type": "w1_breakout",
            "watch_type": "conditional",
            "note": "首页候选观察",
            "valid_days": 30,
            "page_context": "/",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["created"] is True
    assert payload["task"]["created_by"] == "hermass-test"
    assert payload["task"]["page_context"] == "/"

    listed = client.get("/api/user-tasks", headers=_basic_auth_header())
    assert listed.json()["tasks"][0]["task_id"] == payload["task"]["task_id"]


def test_user_tasks_api_duplicate_create_does_not_create_new_task(tmp_path, monkeypatch):
    ledger = tmp_path / "user_task_ledger.json"
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", ledger)
    client = TestClient(app)
    body = {
        "stock_code": "000021.SZ",
        "email": "test@example.com",
        "trigger_type": "w1_breakout",
        "watch_type": "conditional",
        "note": "首页候选观察",
        "valid_days": 30,
    }

    first = client.post("/api/user-tasks", headers=_basic_auth_header(), json=body)
    second = client.post("/api/user-tasks", headers=_basic_auth_header(), json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["ok"] is True
    assert second.json()["created"] is False
    assert second.json()["reason"] == "duplicate_active_watch"
    assert len(user_tasks.load_user_task_ledger()["tasks"]) == 1


def test_user_tasks_api_rejects_invalid_create_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", tmp_path / "user_task_ledger.json")
    client = TestClient(app)

    bad_email = client.post(
        "/api/user-tasks",
        headers=_basic_auth_header(),
        json={"stock_code": "000021.SZ", "email": "bad-email"},
    )
    bad_days = client.post(
        "/api/user-tasks",
        headers=_basic_auth_header(),
        json={"stock_code": "000021.SZ", "email": "test@example.com", "valid_days": "soon"},
    )

    assert bad_email.status_code == 400
    assert bad_email.json() == {"ok": False, "error": "缺少或无效的邮箱"}
    assert bad_days.status_code == 400
    assert bad_days.json() == {"ok": False, "error": "valid_days 必须是数字"}
