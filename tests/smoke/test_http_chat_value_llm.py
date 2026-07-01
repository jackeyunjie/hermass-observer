"""HTTP 层端到端冒烟测试 —— /api/chat/query 的 value 分支。

覆盖：
- FastAPI 路由 /api/chat/query
- _chat_answer() -> _llm_chat_answer() -> 价值分析链路可达
- JSON 响应字段完整
"""

from __future__ import annotations

import base64
import os
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from web.main import app


_FAKE_VALUE_CTX = {
    "main_business": "深科技主营计算机存储、通讯设备及电子制造业务。",
    "latest_financial_report": {
        "report_period": "2025Q1",
        "revenue": 12.5,
        "net_profit": 0.8,
        "operating_cash_flow": 1.2,
        "eps": 0.05,
    },
    "annual_report_2024": {
        "report_period": "2024A",
        "revenue": 52.0,
        "net_profit": 3.5,
    },
    "top10_holders": [{"holder_name": "中国电子有限公司", "hold_ratio": 25.0}],
    "search_data": {
        "status": "local_market_views_already_present",
        "source": "local_market_views",
        "latest_report": {"institution": "测试券商", "date": "2026-05-29", "rating": "增持"},
        "rating_distribution": {"增持": 2},
        "target_price_count": 1,
        "digest_items": [],
        "policy_event_notes": [],
    },
}


def _basic_auth_header(username: str = "hermass-test", password: str = "Hermass2026!Lab") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _fake_value_result() -> dict[str, object]:
    return {
        "answer": "深科技主营业务为计算机存储与通讯设备，2025Q1 营收 12.5 亿、净利润 0.8 亿。",
        "why": "公司现金流为正但盈利一般，基本面处于修复观察期。",
        "multi_cycle_view": "MN1/W1/D1 均处于 E 状态，大周期共振。",
        "single_cycle_position": "D1 波动活跃，当前位置偏中继。",
        "avoid": "不宜仅因低价介入，需等待盈利拐点。",
        "next_actions": [{"label": "查看财报", "url": "/research?stock_code=000021.SZ&render_profile=value"}],
        "sources": ["value_analysis"],
        "freshness_note": "测试数据。",
    }


def test_http_chat_value_branch() -> None:
    """HTTP 端到端：验证 /api/chat/query value 分支可达且返回完整 JSON 合同。"""
    client = TestClient(app)
    with patch("web.main._value_context_for_agent", return_value=_FAKE_VALUE_CTX), \
         patch("agently_adapter.qa_entry._handle_value_analysis", return_value=_fake_value_result()):
        response = client.post(
            "/api/chat/query",
            headers=_basic_auth_header(),
            json={
                "message": "请做 000021 的价值分析",
                "stock_code": "000021.SZ",
                "page_context": "stock",
                "mode": "chat",
                "use_llm": True,
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

    print(f"answer: {payload['answer'][:80]}...")
    print(f"user_id: {payload['user_id']}")
    print("PASS http chat value branch")


def test_http_chat_value_branch_injects_search_data() -> None:
    """无网络验证：HTTP value 分支会把 search_data 注入 value payload。"""
    client = TestClient(app)

    captured: dict[str, object] = {}

    def fake_handle_value_analysis(context: dict[str, object]) -> dict[str, object]:
        captured["payload"] = context.get("value_payload", {})
        return _fake_value_result()

    with patch("agently_adapter.qa_entry._handle_value_analysis", side_effect=fake_handle_value_analysis), \
         patch("web.main._value_context_for_agent", return_value=_FAKE_VALUE_CTX):
        response = client.post(
            "/api/chat/query",
            headers=_basic_auth_header(),
            json={
                "message": "请做 000021 的价值分析",
                "stock_code": "000021.SZ",
                "page_context": "stock",
                "mode": "chat",
                "use_llm": True,
            },
        )

    assert response.status_code == 200, f"HTTP {response.status_code}: {response.text[:300]}"
    assert "payload" in captured, "_handle_value_analysis 未被调用，value payload 未被注入"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["search_data"]["status"] == "local_market_views_already_present"
    assert payload["search_data"]["latest_report"]["institution"] == "测试券商"
    assert payload["top10_holders"][0]["holder_name"] == "中国电子有限公司"


if __name__ == "__main__":
    test_http_chat_value_branch()
    print("\nHTTP 冒烟通过 —— /api/chat/query value 分支可达")
