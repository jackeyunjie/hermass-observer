from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

import web.main as main
import web.services.state_timeline_export_worker as export_worker


def _basic_auth(username: str, password: str = "test") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_state_observer_watchlist_uses_visitor_cookie_user_key(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_query_state_timeline(*args, **kwargs):
        captured["user_key"] = kwargs.get("user_key") or ""
        return {
            "ok": True,
            "meta": {
                "row_count": 0,
                "symbol_count": 0,
                "ef_row_count": 0,
                "ab_row_count": 0,
                "zero_row_count": 0,
                "date_min": "2026-07-01",
                "date_max": "2026-07-01",
                "as_of_date": "2026-07-01",
            },
            "rows": [],
        }

    monkeypatch.setattr(main, "query_state_timeline", fake_query_state_timeline)
    client = TestClient(main.app)

    client.cookies.set("hermass_visitor_id", "visitor_test_123")
    response = client.get("/api/state-observer?symbol_set=watchlist&days=5")

    assert response.status_code == 200
    assert captured["user_key"] == "visitor_test_123"


def test_state_observer_watchlist_uses_authenticated_username(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_query_state_timeline(*args, **kwargs):
        captured["user_key"] = kwargs.get("user_key") or ""
        return {
            "ok": True,
            "meta": {
                "row_count": 0,
                "symbol_count": 0,
                "ef_row_count": 0,
                "ab_row_count": 0,
                "zero_row_count": 0,
                "date_min": "2026-07-01",
                "date_max": "2026-07-01",
                "as_of_date": "2026-07-01",
            },
            "rows": [],
        }

    monkeypatch.setattr(main, "query_state_timeline", fake_query_state_timeline)
    client = TestClient(main.app, headers=_basic_auth("hermass-test"))

    response = client.get("/api/state-observer?symbol_set=watchlist&days=5")

    assert response.status_code == 200
    assert captured["user_key"] == "hermass-test"


def test_state_observer_export_uses_visitor_cookie_user_key(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_create_export_task(query, **kwargs):
        captured["user_key"] = query.get("user_key") or ""
        captured["owner_key"] = kwargs.get("owner_key") or ""
        captured["owner_scope"] = kwargs.get("owner_scope") or ""
        return {"ok": True, "status": "sync", "task_id": "", "estimated_rows": 1, "download_path": ""}

    monkeypatch.setattr(export_worker, "create_export_task", fake_create_export_task)
    client = TestClient(main.app)
    client.cookies.set("hermass_visitor_id", "visitor_export_123")

    response = client.post("/api/state-observer/export", json={"symbol_set": "watchlist", "days": 5, "format": "csv"})

    assert response.status_code == 200
    assert captured["user_key"] == "visitor_export_123"
    assert captured["owner_key"] == "visitor_export_123"
    assert captured["owner_scope"] == "guest"


def test_state_observer_export_uses_authenticated_username(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_create_export_task(query, **kwargs):
        captured["user_key"] = query.get("user_key") or ""
        captured["owner_key"] = kwargs.get("owner_key") or ""
        captured["owner_scope"] = kwargs.get("owner_scope") or ""
        return {"ok": True, "status": "sync", "task_id": "", "estimated_rows": 1, "download_path": ""}

    monkeypatch.setattr(export_worker, "create_export_task", fake_create_export_task)
    client = TestClient(main.app, headers=_basic_auth("hermass-test"))

    response = client.post("/api/state-observer/export", json={"symbol_set": "watchlist", "days": 5, "format": "csv"})

    assert response.status_code == 200
    assert captured["user_key"] == "hermass-test"
    assert captured["owner_key"] == "hermass-test"
    assert captured["owner_scope"] == "user"


# ── 导出任务 owner 隔离 ──


def _write_fake_task_record(tmp_path: Path, task_id: str, owner_key: str, owner_scope: str) -> None:
    """在临时导出目录写入一条任务日志记录。"""
    export_dir = tmp_path / "state_timeline_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    task_log = export_dir / "task_log.jsonl"
    record = {
        "task_id": task_id,
        "status": "queued",
        "format": "csv",
        "query": {"symbol_set": "watchlist", "days": 5, "filters": {}},
        "estimated_rows": 100,
        "output_path": str(Path("outputs") / "state_timeline_exports" / f"{task_id}.csv"),
        "row_count": 0,
        "error": "",
        "owner_key": owner_key,
        "owner_scope": owner_scope,
        "created_at": "2026-07-01T00:00:00+00:00",
        "finished_at": "",
    }
    task_log.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")


def test_state_observer_export_status_403_for_non_owner_guest(monkeypatch, tmp_path) -> None:
    task_id = "state_timeline_export_20260701_test01"
    _write_fake_task_record(tmp_path, task_id, "visitor_owner_123", "guest")
    monkeypatch.setattr(export_worker, "TASK_LOG", tmp_path / "state_timeline_exports" / "task_log.jsonl")

    client = TestClient(main.app)
    client.cookies.set("hermass_visitor_id", "visitor_intruder_456")

    response = client.get(f"/api/state-observer/export/{task_id}")
    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


def test_state_observer_export_status_403_when_user_accesses_guest_task(monkeypatch, tmp_path) -> None:
    task_id = "state_timeline_export_20260701_test02"
    _write_fake_task_record(tmp_path, task_id, "visitor_owner_123", "guest")
    monkeypatch.setattr(export_worker, "TASK_LOG", tmp_path / "state_timeline_exports" / "task_log.jsonl")

    client = TestClient(main.app, headers=_basic_auth("hermass-test"))
    response = client.get(f"/api/state-observer/export/{task_id}")

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


def test_state_observer_export_status_403_when_guest_accesses_user_task(monkeypatch, tmp_path) -> None:
    task_id = "state_timeline_export_20260701_test03"
    _write_fake_task_record(tmp_path, task_id, "hermass-test", "user")
    monkeypatch.setattr(export_worker, "TASK_LOG", tmp_path / "state_timeline_exports" / "task_log.jsonl")

    client = TestClient(main.app)
    client.cookies.set("hermass_visitor_id", "visitor_intruder_456")

    response = client.get(f"/api/state-observer/export/{task_id}")

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


def test_state_observer_export_owner_can_access_status(monkeypatch, tmp_path) -> None:
    task_id = "state_timeline_export_20260701_test04"
    _write_fake_task_record(tmp_path, task_id, "visitor_owner_123", "guest")
    monkeypatch.setattr(export_worker, "TASK_LOG", tmp_path / "state_timeline_exports" / "task_log.jsonl")

    client = TestClient(main.app)
    client.cookies.set("hermass_visitor_id", "visitor_owner_123")

    response = client.get(f"/api/state-observer/export/{task_id}")

    assert response.status_code == 200
    assert response.json()["task_id"] == task_id


def test_state_observer_export_download_403_for_non_owner(monkeypatch, tmp_path) -> None:
    task_id = "state_timeline_export_20260701_test05"
    _write_fake_task_record(tmp_path, task_id, "visitor_owner_123", "guest")
    monkeypatch.setattr(export_worker, "TASK_LOG", tmp_path / "state_timeline_exports" / "task_log.jsonl")

    client = TestClient(main.app)
    client.cookies.set("hermass_visitor_id", "visitor_intruder_456")

    response = client.get(f"/api/state-observer/export/{task_id}/download")
    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


def test_state_observer_page_contains_subscription_entry_and_materialized_mode() -> None:
    client = TestClient(main.app)

    response = client.get("/state-observer")

    assert response.status_code == 200
    html = response.text
    assert "邮件订阅" in html
    assert 'id="materialized_mode"' in html
    assert 'id="subscription_email"' in html
