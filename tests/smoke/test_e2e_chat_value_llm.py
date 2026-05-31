"""端到端 LLM 冒烟测试 —— 完整聊天入口 value 分支

覆盖：
- _llm_chat_answer() 的 value 分支（不是直调底层函数）
- 验证 _is_value_question() → _agently_value_deepseek_call() 整条链路
- JSON 合同字段完整

用法：
    export HERMASS_DEEPSEEK_API_KEY=sk-...
    python tests/smoke/test_e2e_chat_value_llm.py
"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from web.main import ChatQuery, _llm_chat_answer


def test_e2e_chat_value_branch() -> None:
    """真实 API 端到端：验证 _llm_chat_answer() value 分支不爆 + 字段完整。"""
    key = os.environ.get("HERMASS_DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError(
            "DeepSeek API key not found. "
            "Set HERMASS_DEEPSEEK_API_KEY or DEEPSEEK_API_KEY."
        )

    query = ChatQuery(
        message="用价值分析看 000021",
        stock_code="000021.SZ",
        page_context="stock",
        mode="chat",
    )

    result = _llm_chat_answer(query)

    assert result is not None, (
        "_llm_chat_answer() 返回 None —— 可能原因：\n"
        "  1. _should_use_managed_llm() 返回 False\n"
        "  2. _is_value_question() 未命中\n"
        "  3. _agently_value_deepseek_call() 内部失败"
    )

    # JSON 合同字段完整性检查
    required_fields = [
        "answer", "why", "multi_cycle_view", "single_cycle_position",
        "avoid", "next_actions", "sources", "freshness_note",
    ]
    missing = [f for f in required_fields if f not in result]
    assert not missing, f"JSON 合同缺失字段: {missing}"

    # 元信息检查（_llm_chat_answer 自己注入的）
    assert result.get("provider") == "agently_deepseek"
    assert result.get("enhancement_used") is True
    assert result.get("remembered_stock_code") == "000021.SZ"

    # 内容实质性检查
    assert isinstance(result["answer"], str) and len(result["answer"]) > 20
    assert isinstance(result["why"], str) and len(result["why"]) > 20

    # value 数据注入检查：main_business 和财报数据应在输出中体现
    combined = (result["answer"] + result["why"]).lower()
    assert "主营业务" in combined or "计算机" in combined or "通讯" in combined, (
        f"main_business 未在输出中体现。combined: {combined[:200]}"
    )
    assert "营收" in combined or "利润" in combined or "现金流" in combined or "eps" in combined, (
        f"latest_financial_report 未在输出中体现。combined: {combined[:200]}"
    )

    print(f"answer: {result['answer'][:80]}...")
    print(f"why: {result['why'][:80]}...")
    print(f"provider: {result['provider']}")
    print("PASS e2e chat value branch")


if __name__ == "__main__":
    test_e2e_chat_value_branch()
    print("\nE2E 冒烟通过 —— _llm_chat_answer() value 分支 + 真实 DeepSeek API 全通")
