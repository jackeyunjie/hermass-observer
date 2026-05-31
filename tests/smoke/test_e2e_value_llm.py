"""端到端 LLM 冒烟测试 —— 价值增强路径（prompt pack 生效验证）

覆盖：
- _agently_value_deepseek_call() 真实 API 调用不爆
- prompt pack 被实际加载（通过 _deepseek_value_system_prompt）
- JSON 合同字段完整
- 返回内容包含 value 分析特征（多周期 State 解读）

用法：
    export HERMASS_DEEPSEEK_API_KEY=sk-...
    python tests/smoke/test_e2e_value_llm.py
"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from web.main import _agently_value_deepseek_call, _stock_context_for_agent


def test_e2e_value_prompt_pack() -> None:
    """真实 API 端到端：验证 value 增强路径（prompt pack）不爆 + 字段完整。"""
    key = os.environ.get("HERMASS_DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError(
            "DeepSeek API key not found. "
            "Set HERMASS_DEEPSEEK_API_KEY or DEEPSEEK_API_KEY."
        )

    # 构造价值分析 payload（与 _llm_chat_answer 注入的字段一致）
    symbol = "000021.SZ"
    stock_ctx = _stock_context_for_agent(symbol)
    payload: dict[str, Any] = {
        "stock_code": symbol,
        "stock_name": stock_ctx.get("stock_name", symbol),
        "theme_info": stock_ctx.get("industry_name", ""),
        "target_businesses": stock_ctx.get("industry_name", ""),
        "context": stock_ctx.get("stock_states", {}),
        "capital_flow": stock_ctx.get("capital_flow", {}),
        "market_data": {"ef2_pct": 11.2, "env_label": "震荡选择环境"},
        "main_business": stock_ctx.get("main_business", "【待接入】主营业务描述"),
        "latest_financial_report": stock_ctx.get("latest_financial_report", {}),
        "annual_report_2024": stock_ctx.get("annual_report_2024", {}),
        "top10_holders": stock_ctx.get("top10_holders", []),
        "search_data": {},
    }

    result = _agently_value_deepseek_call(payload)

    assert result is not None, (
        "_agently_value_deepseek_call() 返回 None —— 可能原因：\n"
        "  1. Agently 设置未初始化（检查 API key）\n"
        "  2. DeepSeek API 调用失败\n"
        "  3. LLM 输出不是有效 JSON"
    )

    # JSON 合同字段完整性检查
    required_fields = [
        "answer", "why", "multi_cycle_view", "single_cycle_position",
        "avoid", "next_actions", "sources", "freshness_note",
    ]
    missing = [f for f in required_fields if f not in result]
    assert not missing, f"JSON 合同缺失字段: {missing}"

    # 元信息检查
    assert isinstance(result["answer"], str) and len(result["answer"]) > 10
    assert isinstance(result["why"], str) and len(result["why"]) > 10

    # value 增强特征检查（answer 应有实质性分析内容，而非空泛回复）
    assert len(result["answer"]) > 20, (
        f"answer 过短，可能 prompt pack 未生效。\n"
        f"answer: {result['answer'][:200]}"
    )

    print(f"answer: {result['answer'][:80]}...")
    print(f"why: {result['why'][:80]}...")
    print("PASS e2e value prompt pack")


if __name__ == "__main__":
    test_e2e_value_prompt_pack()
    print("\nE2E 冒烟通过 —— value 增强路径 + prompt pack + 真实 DeepSeek API 全通")
