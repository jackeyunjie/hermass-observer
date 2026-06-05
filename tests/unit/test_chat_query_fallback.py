from unittest.mock import patch

from fastapi.testclient import TestClient

from web.main import app


def test_chat_query_internal_error_returns_readable_fallback():
    client = TestClient(app)

    with patch("web.main._chat_answer", side_effect=RuntimeError("forced chat failure")):
        response = client.post(
            "/api/chat/query",
            json={
                "message": "现在能不能做",
                "page_context": "/",
                "mode": "chat",
                "use_llm": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "rule_based"
    assert payload["enhancement_used"] is False
    assert payload["degraded"] is True
    assert payload["error_type"] == "RuntimeError"
    assert "回答出了点问题" not in payload["answer"]
    assert "规则回答" in payload["answer"]
    assert payload["next_actions"]


def test_chat_query_llm_failure_payload_uses_rule_answer():
    client = TestClient(app)
    failure_payload = {
        "answer": "当前 Agently 多 Agent 链路调用失败，已触发规则回退。",
        "why": "Agently 场景化 Agent 编排链路调用失败。",
        "multi_cycle_view": "",
        "single_cycle_position": "",
        "avoid": "",
        "next_actions": [],
        "sources": ["agently_multi_agent", "rule_fallback"],
        "freshness_note": "Agently 场景化 Agent 编排调用失败。",
        "mode_used": "chat",
        "provider": "agently_deepseek",
        "enhancement_used": False,
        "intent": {"scenario": "fallback", "confidence": 0.0, "secondary_scenario": ""},
    }

    with patch("web.main._llm_chat_answer", return_value=failure_payload):
        response = client.post(
            "/api/chat/query",
            json={
                "message": "现在能不能做",
                "page_context": "/",
                "mode": "chat",
                "use_llm": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "rule_based"
    assert payload["enhancement_used"] is False
    assert payload["degraded"] is True
    assert payload["degraded_reason"] == "llm_unavailable"
    assert "链路调用失败" not in payload["answer"]
    assert "增强解释链路暂不可用" in payload["freshness_note"]
