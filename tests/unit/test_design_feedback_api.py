from __future__ import annotations

import json

from fastapi.testclient import TestClient

import web.main as web_main
from web.main import app


def test_feedback_page_renders() -> None:
    client = TestClient(app)
    response = client.get("/feedback")

    assert response.status_code == 200
    assert "设计反馈" in response.text
    assert "提交反馈" in response.text


def test_design_feedback_api_rejects_empty_specific_feedback(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(web_main, "DESIGN_FEEDBACK_PATH", tmp_path / "design_feedback.jsonl")
    client = TestClient(app)

    response = client.post("/api/design-feedback", json={"role": "投资研究", "rating": "4"})

    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "请至少填写一条具体反馈"}


def test_design_feedback_api_writes_jsonl(tmp_path, monkeypatch) -> None:
    feedback_path = tmp_path / "design_feedback.jsonl"
    monkeypatch.setattr(web_main, "DESIGN_FEEDBACK_PATH", feedback_path)
    client = TestClient(app)

    response = client.post(
        "/api/design-feedback",
        json={
            "role": "交易执行",
            "page": "首页观察候选",
            "rating": "3",
            "biggest_blocker": "不知道创建观察后在哪里看。",
            "most_useful": "今日判断很有用。",
            "missing": "希望有更明确的新手路径。",
            "contact": "qa@example.com",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    rows = feedback_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    record = json.loads(rows[0])
    assert record["role"] == "交易执行"
    assert record["rating"] == 3
    assert record["page"] == "首页观察候选"
    assert record["biggest_blocker"] == "不知道创建观察后在哪里看。"
