from __future__ import annotations

import base64

from fastapi.testclient import TestClient

import web.main as main


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
