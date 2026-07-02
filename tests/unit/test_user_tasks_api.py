from __future__ import annotations

import base64
import json
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


# ── State Timeline 订阅 CRUD ──


def test_state_timeline_subscriptions_guest_create_list_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", tmp_path / "user_task_ledger.json")
    client = TestClient(app)

    created = client.post(
        "/api/state-observer/subscriptions",
        json={"email": "guest@example.com", "symbol_set": "watchlist", "days": 7, "note": "访客订阅"},
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["created"] is True
    assert payload["task"]["task_type"] == "state_timeline_digest"
    assert payload["task"]["created_by"].startswith("visitor_")

    cookie_header = created.headers.get("set-cookie", "")
    visitor_cookie = SimpleCookie()
    visitor_cookie.load(cookie_header)
    visitor_id = visitor_cookie["hermass_visitor_id"].value
    client.cookies.set("hermass_visitor_id", visitor_id)

    listed = client.get("/api/state-observer/subscriptions")
    assert listed.status_code == 200
    tasks = listed.json()["subscriptions"]
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == payload["task"]["task_id"]

    cancelled = client.post(f"/api/state-observer/subscriptions/{payload['task']['task_id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["task"]["status"] == "cancelled"


def test_state_timeline_subscriptions_user_isolation(tmp_path, monkeypatch):
    ledger = tmp_path / "user_task_ledger.json"
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", ledger)

    user_tasks.create_state_timeline_subscription(
        email="alice@example.com",
        symbol_set="top50",
        days=3,
        created_by="alice",
    )
    user_tasks.create_state_timeline_subscription(
        email="bob@example.com",
        symbol_set="top50",
        days=3,
        created_by="bob",
    )

    client = TestClient(app, headers=_basic_auth_header("alice"))
    listed = client.get("/api/state-observer/subscriptions")
    assert listed.status_code == 200
    emails = {t["email"] for t in listed.json()["subscriptions"]}
    assert emails == {"alice@example.com"}


def test_state_timeline_subscriptions_cancel_forbidden_for_other_user(tmp_path, monkeypatch):
    ledger = tmp_path / "user_task_ledger.json"
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", ledger)

    created = user_tasks.create_state_timeline_subscription(
        email="alice@example.com",
        symbol_set="top50",
        days=3,
        created_by="alice",
    )
    task_id = created["task"]["task_id"]

    client = TestClient(app, headers=_basic_auth_header("bob"))
    response = client.post(f"/api/state-observer/subscriptions/{task_id}/cancel")

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


def test_state_timeline_subscriptions_duplicate_returns_409(tmp_path, monkeypatch):
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", tmp_path / "user_task_ledger.json")
    client = TestClient(app, headers=_basic_auth_header("hermass-test"))
    body = {"email": "dup@example.com", "symbol_set": "top50", "days": 3}

    first = client.post("/api/state-observer/subscriptions", json=body)
    second = client.post("/api/state-observer/subscriptions", json=body)

    assert first.status_code == 200
    assert first.json()["created"] is True
    assert second.status_code == 409
    assert second.json()["created"] is False
    assert second.json()["reason"] == "duplicate_active_subscription"


def test_state_timeline_subscriptions_invalid_email_returns_400(tmp_path, monkeypatch):
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", tmp_path / "user_task_ledger.json")
    client = TestClient(app, headers=_basic_auth_header("hermass-test"))

    response = client.post(
        "/api/state-observer/subscriptions",
        json={"email": "not-an-email", "symbol_set": "top50", "days": 3},
    )

    assert response.status_code == 400
    assert response.json()["created"] is False
    assert response.json()["reason"] == "invalid_email"


def test_state_timeline_subscriptions_invalid_days_returns_400(tmp_path, monkeypatch):
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", tmp_path / "user_task_ledger.json")
    client = TestClient(app, headers=_basic_auth_header("hermass-test"))

    response = client.post(
        "/api/state-observer/subscriptions",
        json={"email": "valid@example.com", "symbol_set": "top50", "days": "soon"},
    )

    assert response.status_code == 400
    assert response.json()["created"] is False
    assert response.json()["reason"] == "invalid_days"


def test_state_timeline_subscriptions_invalid_symbol_set_returns_400(tmp_path, monkeypatch):
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", tmp_path / "user_task_ledger.json")
    client = TestClient(app, headers=_basic_auth_header("hermass-test"))

    response = client.post(
        "/api/state-observer/subscriptions",
        json={"email": "valid@example.com", "symbol_set": "sector42", "days": 3},
    )

    assert response.status_code == 400
    assert response.json()["created"] is False
    assert response.json()["reason"] == "invalid_symbol_set"


def test_state_timeline_subscriptions_update_success(tmp_path, monkeypatch):
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", tmp_path / "user_task_ledger.json")
    client = TestClient(app, headers=_basic_auth_header("hermass-test"))

    created = client.post(
        "/api/state-observer/subscriptions",
        json={"email": "old@example.com", "symbol_set": "top50", "days": 3},
    )
    task_id = created.json()["task"]["task_id"]

    updated = client.post(
        f"/api/state-observer/subscriptions/{task_id}/update",
        json={"email": "new@example.com", "symbol_set": "watchlist", "days": 7},
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["ok"] is True
    assert payload["task"]["email"] == "new@example.com"
    assert payload["task"]["symbol_set"] == "watchlist"
    assert payload["task"]["days"] == 7


def test_state_timeline_subscriptions_update_forbidden_for_other_user(tmp_path, monkeypatch):
    ledger = tmp_path / "user_task_ledger.json"
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", ledger)

    created = user_tasks.create_state_timeline_subscription(
        email="alice@example.com",
        symbol_set="top50",
        days=3,
        created_by="alice",
    )
    task_id = created["task"]["task_id"]

    client = TestClient(app, headers=_basic_auth_header("bob"))
    response = client.post(
        f"/api/state-observer/subscriptions/{task_id}/update",
        json={"email": "bob@example.com", "symbol_set": "all", "days": 5},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


def test_state_timeline_subscriptions_update_rejects_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", tmp_path / "user_task_ledger.json")
    client = TestClient(app, headers=_basic_auth_header("hermass-test"))

    first = client.post(
        "/api/state-observer/subscriptions",
        json={"email": "a@example.com", "symbol_set": "top50", "days": 3},
    )
    client.post(
        "/api/state-observer/subscriptions",
        json={"email": "b@example.com", "symbol_set": "top50", "days": 3},
    )

    task_id = first.json()["task"]["task_id"]
    response = client.post(
        f"/api/state-observer/subscriptions/{task_id}/update",
        json={"email": "b@example.com", "symbol_set": "top50", "days": 3},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "duplicate_active_subscription"


def test_state_timeline_subscriptions_dispatch_logs_user_isolation(tmp_path, monkeypatch):
    from scripts import send_state_timeline_digest_email

    ledger = tmp_path / "user_task_ledger.json"
    log_path = tmp_path / "state_timeline_dispatch_log.jsonl"
    monkeypatch.setattr(user_tasks, "USER_TASK_LEDGER", ledger)
    monkeypatch.setattr(send_state_timeline_digest_email, "DISPATCH_LOG_PATH", log_path)

    created = user_tasks.create_state_timeline_subscription(
        email="alice@example.com",
        symbol_set="top50",
        days=3,
        created_by="alice",
    )
    user_tasks.create_state_timeline_subscription(
        email="bob@example.com",
        symbol_set="top50",
        days=3,
        created_by="bob",
    )

    log_path.write_text(
        json.dumps({
            "task_id": created["task"]["task_id"],
            "email": "alice@example.com",
            "dispatch_date": "2026-07-02",
            "status": "sent",
            "created_by": "alice",
            "symbol_set": "top50",
            "days": 3,
            "timestamp": "2026-07-02",
        }) + "\n",
        encoding="utf-8",
    )

    client = TestClient(app, headers=_basic_auth_header("alice"))
    response = client.get("/api/state-observer/subscriptions/dispatch-logs")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert len(payload["logs"]) == 1
    assert created["task"]["task_id"] in payload["logs"]

    client_bob = TestClient(app, headers=_basic_auth_header("bob"))
    response_bob = client_bob.get("/api/state-observer/subscriptions/dispatch-logs")
    assert response_bob.json()["logs"] == {}
