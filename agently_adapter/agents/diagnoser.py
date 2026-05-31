"""诊断 Agent —— 个股多周期体检。"""

from __future__ import annotations

from typing import Any

from agently_adapter.agents.base import create_agent, safe_get_response

PROMPT = (
    "你是 Hermass 的「个股诊断师」。你基于多周期 State 模型，给一只股票做快速体检。"
    "你的诊断要像医院报告——有指标、有结论、有建议，没有抒情。\n\n"
    "## 诊断规则\n"
    "1. ef=3 + 资金流入 + 真突破 → 「标准跟踪」\n"
    "2. ef=3 + 资金流出 → 「假突破风险，观察」\n"
    "3. ef=0 + 全逆位 → 「回避，不做多」\n"
    "4. ef=1 + 破土期 + 资金流入 → 「列入观察，等确认」\n"
    "5. 持续天数 >15 + ef 从 3 降到 2 → 「秋收期，不宜新开仓」\n\n"
    "## 禁止\n"
    "- 禁止说「基本面良好」「业绩支撑」「估值合理」\n"
    "- 禁止预测具体涨幅（如「有望涨 20%」）\n"
    "- 禁止给出买入价位"
)


def run(context: dict[str, Any]) -> dict[str, Any] | None:
    """输入 context 需包含 symbol, name, states, capital_flow, breakout_status, sustained_days。"""
    agent = create_agent()
    agent.system(PROMPT)
    agent.instruct("根据以下个股数据，给出多周期诊断。")
    agent.input(
        f"股票代码：{context.get('symbol', '')}\n"
        f"股票名称：{context.get('name', '')}\n"
        f"多周期 State：{context.get('states', {})}\n"
        f"ef_count：{context.get('ef_count', 0)}\n"
        f"资金流向：{context.get('capital_flow', {})}\n"
        f"突破状态：{context.get('breakout_status', '')}\n"
        f"持续天数：{context.get('sustained_days', 0)}"
    )
    agent.output({
        "conclusion": (str, "结论：30字内，明确 yes/no/观察 + 节奏标签", True),
        "cycle_position": (str, "周期定位：MN1/W1/D1 分别一句话，只说状态和含义", True),
        "capital_structure": (str, "资金与结构：资金流向 + 突破状态，2句话", True),
        "next_step": (str, "下一步：建议动作 + 风险提示", True),
        "risk_flag": (str, "风险标记：none|fake_breakout|reversal|overbought|watch_only", True),
    })
    return safe_get_response(agent)
