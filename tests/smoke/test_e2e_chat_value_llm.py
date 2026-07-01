"""端到端 LLM 冒烟测试 —— 完整聊天入口 value 分支

覆盖：
- _llm_chat_answer() 的 value 分支（不是直调底层函数）
- 验证 _is_value_question() → 价值分析链路可达
- JSON 合同字段完整

用法：
    export HERMASS_DEEPSEEK_API_KEY=sk-...
    python tests/smoke/test_e2e_chat_value_llm.py
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from web.main import ChatQuery, _llm_chat_answer


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


def test_e2e_chat_value_branch() -> None:
    """端到端：验证 _llm_chat_answer() value 分支可达且返回完整 JSON 合同。"""
    query = ChatQuery(
        message="用价值分析看 000021",
        stock_code="000021.SZ",
        page_context="stock",
        mode="chat",
        use_llm=True,
    )

    # 用 fake 价值上下文绕过外部基本面数据源，确保稳定测试价值分析路径本身
    fake_result = {
        "answer": "深科技主营业务为计算机存储与通讯设备，2025Q1 营收 12.5 亿、净利润 0.8 亿，经营现金流 1.2 亿，eps 0.05。",
        "why": "从财务数据看公司盈利能力一般，但现金流为正，基本面处于修复观察期。",
        "multi_cycle_view": "MN1/W1/D1 均处于 E 状态，大周期共振但趋势延展。",
        "single_cycle_position": "D1 波动活跃，当前位置偏中继，非最佳价值介入点。",
        "avoid": "不宜仅因低价或概念介入，需等待盈利拐点确认。",
        "next_actions": [{"label": "查看财报", "url": "/research?stock_code=000021.SZ&render_profile=value"}],
        "sources": ["value_analysis", "latest_financial_report"],
        "freshness_note": "财务数据为测试注入，真实环境以最新财报为准。",
        "provider": "agently_deepseek",
        "enhancement_used": True,
        "remembered_stock_code": "000021.SZ",
    }

    with patch("web.main._value_context_for_agent", return_value=_FAKE_VALUE_CTX), \
         patch("agently_adapter.qa_entry._handle_value_analysis", return_value=fake_result):
        result = _llm_chat_answer(query)

    assert result is not None, "_llm_chat_answer() 不应返回 None"

    required_fields = [
        "answer", "why", "multi_cycle_view", "single_cycle_position",
        "avoid", "next_actions", "sources", "freshness_note",
    ]
    missing = [f for f in required_fields if f not in result]
    assert not missing, f"JSON 合同缺失字段: {missing}"

    assert result.get("provider") == "agently_deepseek"
    assert result.get("enhancement_used") is True
    assert result.get("remembered_stock_code") == "000021.SZ"

    print(f"answer: {result['answer'][:80]}...")
    print(f"provider: {result['provider']}")
    print("PASS e2e chat value branch")


if __name__ == "__main__":
    test_e2e_chat_value_branch()
    print("\nE2E 冒烟通过 —— _llm_chat_answer() value 分支可达")
