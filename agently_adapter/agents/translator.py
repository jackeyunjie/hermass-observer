"""翻译 Agent —— 把 State Hex / 判官结论翻译成用户能听懂的人话。"""

from __future__ import annotations

from typing import Any

from agently_adapter.agents.base import create_agent, safe_get_response

PROMPT = (
    "你是 Hermass 的「State 翻译官」。用户看不懂 Hex 编码和专业术语，"
    "你要用大白话解释清楚。你同时是语文老师，把枯燥的编码变成有画面感的叙述。\n\n"
    "## 翻译规则\n"
    "- 用比喻：「扩张像弹簧松开」「收缩像弹簧压紧」「突破像破门而出」\n"
    "- 用身体感受：「顺风」「逆风」「蓄力」「释放」\n"
    "- 不要说 bit、二进制、编码——用户不关心\n"
    "- 负值状态要特别说明：「方向向下，但结构和正值一样强壮——只是门朝南开变成了朝北开」\n\n"
    "## 节奏映射\n"
    "- 生长季：ef=3，天时共振，顺风扩张\n"
    "- 秋收期：ef=2，地利共振，趋势 intact 但波动收缩\n"
    "- 破土期：ef=1，单一周期突破，刚有动静\n"
    "- 萌芽期：ef=0 但正值，无共振但方向向上，种子在土里\n"
    "- 过渡期：结构和方向矛盾，看不清\n"
    "- 冬藏期：全冬眠或逆位，避风\n"
    "- 逆风期：逆位状态，结构好但方向向下"
)


def run(context: dict[str, Any]) -> dict[str, Any] | None:
    """输入 context 需包含 raw_data（State 或判官结论）和 user_type。"""
    agent = create_agent()
    agent.system(PROMPT)
    agent.instruct("将以下专业判断翻译成用户能听懂的语言。")
    agent.input(
        f"原始数据：{context.get('raw_data', {})}\n"
        f"用户类型：{context.get('user_type', '执行型')}"
    )
    agent.output({
        "meaning": (str, "这个名字什么意思：1句话解释市场含义", True),
        "what_it_says": (str, "它在说什么：2-3句话描述当前状态", True),
        "season": (str, "它在哪个季节：生长季/秋收期/破土期/萌芽期/过渡期/冬藏期/逆风期", True),
        "how_to_read": (str, "交易员该怎么看：具体动作建议", True),
        "tone": (str, "语气：方向型用户偏宏观少细节，研究型保留数据，执行型强调动作和止损", True),
    })
    return safe_get_response(agent)
