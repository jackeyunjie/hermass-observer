"""融合 Agent —— 质检、去模糊、加声明、截断、统一格式。"""

from __future__ import annotations

from typing import Any

from agently_adapter.agents.base import create_agent, safe_get_response

PROMPT = (
    "你是 Hermass 的「输出质检员」。你接收其他 Agent 的初稿，进行三关审核：\n"
    "1. 去模糊：检查禁用词\n"
    "2. 加声明：确保有免责声明\n"
    "3. 截断：确保字数合规\n\n"
    "## 处理流程\n"
    "1. 扫描禁用词，发现则替换或删除\n"
    "2. 检查是否有免责声明，无则追加\n"
    "3. 根据 user_type 调整语气：\n"
    "   - 方向型：更宏观，少细节\n"
    "   - 研究型：保留数据，允许稍长\n"
    "   - 执行型：更直接，强调动作和止损\n"
    "4. 质检语气是否符合问题类型——市场类不应有体检报告的冗长，个股类不应有一句话敷衍\n"
    "5. 截断到规定字数\n"
    "6. 统一格式为三段式：【结论】【依据】【下一步】\n\n"
    "## 特殊规则\n"
    "- 如果初稿包含两个矛盾的周期描述，优先采信 ef_count 更高的那个\n"
    "- 如果初稿中出现「暂无」数据描述，删除该句，不保留空壳信息"
)


def run(context: dict[str, Any]) -> dict[str, Any] | None:
    """输入 context 需包含 draft（多 Agent 输出字典）和 user_type。"""
    agent = create_agent()
    agent.system(PROMPT)
    agent.instruct("对以下初稿进行质检和融合，输出标准 JSON。")
    agent.input(
        f"来源 Agent：{context.get('source_scenario', 'unknown')}\n"
        f"初稿内容：{context.get('draft', {})}\n"
        f"用户类型：{context.get('user_type', '执行型')}"
    )
    agent.output({
        "answer": (str, "核心结论，30字以内", True),
        "why": (str, "2-3个理由，用数据说话", True),
        "multi_cycle_view": (str, "多周期视角判断", True),
        "single_cycle_position": (str, "单周期位置判断", True),
        "avoid": (str, "风险提示", True),
        "next_actions": ([{"label": str, "url": str}], "建议动作列表", True),
        "sources": ([str], "数据来源列表", True),
        "freshness_note": (str, "数据时效说明", True),
    })
    return safe_get_response(agent)
