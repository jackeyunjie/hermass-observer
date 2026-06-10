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


def test_chat_query_workflow_answer_discloses_no_local_support():
    client = TestClient(app)
    workflow_payload = {
        "answer": "这是外部工作流扩展回答。",
        "why": "由 N8N 知识工作流返回。",
        "multi_cycle_view": "",
        "single_cycle_position": "",
        "avoid": "不要当成本地数据结论。",
        "next_actions": [],
        "sources": ["external_workflow", "workflow_n8n"],
        "freshness_note": "",
        "provider": "workflow_n8n",
        "workflow_provider": "n8n",
        "enhancement_used": True,
    }

    with patch("web.main._llm_chat_answer", return_value=workflow_payload):
        response = client.post(
            "/api/chat/query",
            json={
                "message": "解释一个本地没有覆盖的问题",
                "page_context": "/",
                "mode": "chat",
                "use_llm": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "workflow_n8n"
    assert payload["answer_origin"] == "workflow"
    assert payload["data_support"] == "llm_only"
    assert "暂无实际数据支持" in payload["support_note"]


def test_chat_query_workflow_answer_with_local_sources_keeps_origin_workflow():
    client = TestClient(app)
    workflow_payload = {
        "answer": "这是外部工作流扩展回答。",
        "why": "由 Dify 工作流返回。",
        "multi_cycle_view": "",
        "single_cycle_position": "",
        "avoid": "不要当成自动交易建议。",
        "next_actions": [],
        "sources": ["daily_snapshot", "workflow_dify"],
        "freshness_note": "",
        "provider": "workflow_dify",
        "workflow_provider": "dify",
        "enhancement_used": True,
    }

    with patch("web.main._llm_chat_answer", return_value=workflow_payload):
        response = client.post(
            "/api/chat/query",
            json={
                "message": "解释一个本地有支持的问题",
                "page_context": "/",
                "mode": "chat",
                "use_llm": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "workflow_dify"
    assert payload["answer_origin"] == "workflow"
    assert payload["data_support"] == "local_data"
    assert "已结合本地数据证据" in payload["support_note"]
