"""端到端 LLM 冒烟测试 —— 用真实 DeepSeek API 验证 stock_checkup 链不爆。

约束：
- 只测一条链（stock_checkup），覆盖 translator → diagnoser → translator → fusion。
- 不测正确性（那是 QA 的事），只测「端到端不爆 + JSON 合同字段完整」。
- 若 LLM router 失败，keyword fallback 会兜底到 stock_checkup（因为 msg 含「怎么样」且 symbol 非空）。

用法：
    export HERMASS_DEEPSEEK_API_KEY=sk-...
    python tests/smoke/test_e2e_llm.py
"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agently_adapter.qa_entry import handle


def _e2e_context() -> dict[str, Any]:
    return {
        "user_type": "执行型",
        "current_page": "stock",
        "symbol": "000021.SZ",
        "mode": "chat",
        "stock_name": "深科技",
        "stock_states": {
            "mn1": "E",
            "w1": "F",
            "d1": "C",
            "mn1_score": 14,
            "w1_score": 15,
            "d1_score": 14,
        },
        "ef_count": 3,
        "capital_flow": {"status": "confirmed", "confirmed": True, "divergence": False, "score": 8.5},
        "breakout_status": "上突",
        "sustained_days": 12,
        "market_data": {"ef2_pct": 11.2, "env_label": "震荡选择环境"},
    }


def test_e2e_stock_checkup() -> None:
    """真实 API 端到端：验证 stock_checkup 链不爆 + JSON 合同完整。"""
    # 前置检查：确保有 API key
    key = os.environ.get("HERMASS_DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError(
            "DeepSeek API key not found. "
            "Set HERMASS_DEEPSEEK_API_KEY or DEEPSEEK_API_KEY."
        )

    ctx = _e2e_context()
    result = handle("000021 怎么样", ctx)

    assert result is not None, (
        "handle() 返回 None —— 可能原因：\n"
        "  1. router 失败且 keyword fallback 未命中\n"
        "  2. stock_checkup 链中某个 Agent 抛异常\n"
        "  3. Agently 设置未初始化（检查 API key）"
    )

    # JSON 合同字段完整性检查
    required_fields = [
        "answer", "why", "multi_cycle_view", "single_cycle_position",
        "avoid", "next_actions", "sources", "freshness_note",
    ]
    missing = [f for f in required_fields if f not in result]
    assert not missing, f"JSON 合同缺失字段: {missing}"

    # 元信息检查
    assert result.get("provider") == "agently_deepseek", (
        f"provider 不匹配: {result.get('provider')}"
    )
    assert result.get("enhancement_used") is True

    # 类型检查（轻量）
    assert isinstance(result["answer"], str)
    assert isinstance(result["why"], str)
    assert isinstance(result["next_actions"], list)
    assert isinstance(result["sources"], list)

    print(f"answer: {result['answer'][:60]}...")
    print(f"why: {result['why'][:60]}...")
    print(f"multi_cycle_view: {result['multi_cycle_view'][:60]}...")
    print("PASS e2e stock_checkup")


if __name__ == "__main__":
    test_e2e_stock_checkup()
    print("\nE2E 冒烟通过 —— stock_checkup 链 + 真实 DeepSeek API 全通")
