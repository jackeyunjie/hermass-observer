"""行业 Agent —— 行业轮动和产业链分析。"""

from __future__ import annotations

from typing import Any

from agently_adapter.agents.base import create_agent, safe_get_response

PROMPT = (
    "你是 Hermass 的「行业分析师」。你分析行业轮动和产业链位置。"
    "你当前的数据有限，必须诚实说明数据来源，没数据就明确说「此块数据待补充」。\n\n"
    "## 规则\n"
    "1. 没有产业链数据时，不要编。直接说「暂无数据，后续接入大模型搜索补充」。\n"
    "2. 行业状态必须基于成分股 State 统计，不要基于新闻感觉。\n"
    "3. 轮动判断基于：行业内 ef≥2 股票占比变化趋势（需最近 5 日数据）。"
)


def run(context: dict[str, Any]) -> dict[str, Any] | None:
    """输入 context 需包含 industry_name, distribution, capital_flow。"""
    agent = create_agent()
    agent.system(PROMPT)
    agent.instruct("根据以下行业数据，给出行业分析。")
    agent.input(
        f"行业名称：{context.get('industry_name', '')}\n"
        f"成分股 State 分布：{context.get('distribution', {})}\n"
        f"行业资金流向：{context.get('capital_flow', {})}"
    )
    agent.output({
        "industry_state": (str, "行业状态：1个词 + 1句话", True),
        "component_scan": (str, "成分股扫描：强势/弱势占比 + 1-2个代表性个股", True),
        "supply_chain": (str, "产业链：上中下游位置 + 景气度；没数据则标注待补充", True),
        "rotation_position": (str, "轮动位置：启动/加速/高潮/退潮 + 依据", True),
        "data_gaps": ([str], "数据缺失项列表", True),
    })
    return safe_get_response(agent)
