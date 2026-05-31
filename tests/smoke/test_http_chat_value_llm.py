"""HTTP 层端到端冒烟测试 —— /api/chat/query 的 value 分支。

覆盖：
- FastAPI 路由 /api/chat/query
- _chat_answer() -> _llm_chat_answer() -> _agently_value_deepseek_call() 整条链路
- JSON 响应字段完整
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from web.main import app


def test_http_chat_value_branch() -> None:
    """真实 API 端到端：验证 HTTP value 分支不爆 + 字段完整。"""
    key = os.environ.get("HERMASS_DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError(
            "DeepSeek API key not found. "
            "Set HERMASS_DEEPSEEK_API_KEY or DEEPSEEK_API_KEY."
        )

    client = TestClient(app)
    response = client.post(
        "/api/chat/query",
        json={
            "message": "请做 000021 的价值分析",
            "stock_code": "000021.SZ",
            "page_context": "stock",
            "mode": "chat",
        },
    )

    assert response.status_code == 200, f"HTTP status != 200: {response.status_code} body={response.text[:300]}"
    payload = response.json()

    required_fields = [
        "answer", "why", "multi_cycle_view", "single_cycle_position",
        "avoid", "next_actions", "sources", "freshness_note",
        "remembered_stock_code", "remembered_email", "mode_used",
        "provider", "enhancement_used", "user_id",
    ]
    missing = [f for f in required_fields if f not in payload]
    assert not missing, f"HTTP JSON 合同缺失字段: {missing}"

    assert payload.get("provider") == "agently_deepseek"
    assert payload.get("enhancement_used") is True
    assert payload.get("remembered_stock_code") == "000021.SZ"
    assert payload.get("mode_used") == "chat"

    combined = (payload["answer"] + payload["why"]).lower()
    assert len(payload["answer"]) > 20
    assert len(payload["why"]) > 20
    assert "主营业务" in combined or "计算机" in combined or "通讯" in combined
    assert "营收" in combined or "利润" in combined or "现金流" in combined or "eps" in combined

    print(f"answer: {payload['answer'][:80]}...")
    print(f"why: {payload['why'][:80]}...")
    print(f"user_id: {payload['user_id']}")
    print("PASS http chat value branch")


def test_http_chat_value_branch_injects_search_data() -> None:
    """无网络验证：HTTP value 分支会把 search_data 注入 value payload。"""
    client = TestClient(app)

    captured: dict[str, object] = {}

    def fake_value_call(payload: dict[str, object]) -> dict[str, object]:
        captured["payload"] = payload
        return {
            "answer": "测试回答",
            "why": "测试原因",
            "multi_cycle_view": "测试多周期",
            "single_cycle_position": "测试单周期",
            "avoid": "测试风险",
            "next_actions": [],
            "sources": [],
            "freshness_note": "",
        }

    fake_value_ctx = {
        "main_business": "通信设备制造",
        "latest_financial_report": {"report_period": "2025Q1", "revenue": 123},
        "annual_report_2024": {"report_period": "2024A"},
        "top10_holders": [{"holder_name": "测试股东"}],
        "search_data": {
            "status": "local_market_views_already_present",
            "source": "local_market_views",
            "latest_report": {"institution": "测试机构", "date": "2026-05-29", "rating": "增持"},
            "rating_distribution": {"增持": 2},
            "target_price_count": 1,
            "digest_items": [],
            "policy_event_notes": ["已有本地 market_views 摘要"],
        },
    }

    with patch("web.main._agently_value_deepseek_call", side_effect=fake_value_call), \
         patch("web.main._value_context_for_agent", return_value=fake_value_ctx):
        response = client.post(
            "/api/chat/query",
            json={
                "message": "请做 000021 的价值分析",
                "stock_code": "000021.SZ",
                "page_context": "stock",
                "mode": "chat",
            },
        )

    assert response.status_code == 200
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["search_data"]["status"] == "local_market_views_already_present"
    assert payload["search_data"]["latest_report"]["institution"] == "测试机构"
    assert payload["top10_holders"][0]["holder_name"] == "测试股东"


if __name__ == "__main__":
    test_http_chat_value_branch()
    print("\nHTTP 冒烟通过 —— /api/chat/query value 分支 + 真实 DeepSeek API 全通")
