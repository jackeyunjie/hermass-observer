import re
from dataclasses import dataclass, field

FORBIDDEN_PATTERNS = [
    (re.compile(r"建议买入|建议卖出|建议加仓|建议减仓"), "投资建议"),
    (re.compile(r"推荐买入|推荐卖出|推荐股票"), "投资建议"),
    (re.compile(r"应该买入|应该卖出|应该加仓|应该减仓"), "投资建议"),
    (re.compile(r"必须买入|必须卖出|必须清仓"), "投资建议"),
    (re.compile(r"现在就买|赶紧卖|明天开盘买|马上买入|立刻卖出"), "操作指令"),
    (re.compile(r"挂单|限价|市价买入|市价卖出"), "操作指令"),
    (re.compile(r"满仓|空仓|重仓|轻仓"), "仓位指令"),
    (re.compile(r"必涨|必跌|确定机会|稳赚|无风险"), "确定性判断"),
    (re.compile(r"预计涨到|目标价|上涨空间|下跌空间"), "价格预测"),
    (re.compile(r"保证收益|年化收益|收益率|赚钱"), "收益承诺"),
    (re.compile(r"抄底|逃顶|精准抄底"), "时机判断"),
]

COMPLIANCE_REPLACEMENTS = [
    (re.compile(r"建议买入"), "当前信号处于"),
    (re.compile(r"建议卖出"), "出场规则显示"),
    (re.compile(r"推荐(.+?)策略"), r"当前环境适配 \1 策略"),
    (re.compile(r"应该买"), "可关注"),
    (re.compile(r"应该卖"), "需注意出场条件"),
    (re.compile(r"建议加仓"), "可继续观察"),
    (re.compile(r"建议减仓"), "可参考风控规则"),
    (re.compile(r"预计涨到(.+?)元"), r"历史统计显示该条件下"),
    (re.compile(r"目标价(.+?)元"), r"系统标注的阻力位为"),
]

DISCLAIMER = (
    "\n\n---\n"
    "本回答基于 Hermass Observer 系统输出，仅供研究参考，不构成投资建议。\n"
    "所有交易决策请基于自身风险承受能力独立判断。"
)


@dataclass
class ComplianceResult:
    passed: bool
    violations: list[str] = field(default_factory=list)
    filtered_text: str = ""
    is_trade_related: bool = False

    def needs_disclaimer(self) -> bool:
        return self.is_trade_related


def _check_trade_related(text: str) -> bool:
    trade_keywords = [
        "买入", "卖出", "信号", "策略", "适配", "止损", "止盈", "仓位",
        "持仓", "交易", "行情", "突破", "支撑", "阻力", "回撤",
        "VCP", "2560", "布林强盗", "E/F", "State", "ef_count",
        "市场阶段", "趋势", "收缩", "扩张", "观察池", "最佳适配",
    ]
    for kw in trade_keywords:
        if kw in text:
            return True
    return False


def check_compliance(text: str, source_path: str = "") -> ComplianceResult:
    result = ComplianceResult(passed=True, filtered_text=text)

    for pattern, category in FORBIDDEN_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            for match in matches:
                result.violations.append(f"[{category}] 命中禁止措辞: {match}")
            result.passed = False

    for pattern, replacement in COMPLIANCE_REPLACEMENTS:
        if pattern.search(result.filtered_text):
            result.filtered_text = pattern.sub(replacement, result.filtered_text)
            if result.passed:
                pass

    result.is_trade_related = _check_trade_related(text)

    if result.is_trade_related and source_path:
        pass

    return result


def apply_disclaimer(text: str, source_path: str = "") -> str:
    if source_path:
        return text + DISCLAIMER + f"\n数据来源：{source_path}"
    return text + DISCLAIMER


def get_system_prompt() -> str:
    return (
        "你是 Hermass Observer 系统的 AI 解读助手。\n"
        "你的职责是基于系统输出的市场数据，向用户解读当前市场环境和策略适配度。\n"
        "你是解释层，不是交易执行层。\n"
        "\n"
        "【系统范围】\n"
        "- 当前活跃系统仅限 A 股\n"
        "- MT5 / US / Alpaca 相关内容均为历史归档，不属于当前运行范围\n"
        "- 输出仅供研究参考，不构成投资建议\n"
        "\n"
        "【架构边界】\n"
        "- shared core layer = agently_adapter/a_share_core.py\n"
        "- core flow = agently_adapter/agently_a_share_flow.py\n"
        "- full compatibility workflow = agently_adapter/agently_daily_flow.py\n"
        "- API service layer = hermass_platform/api/a_share_service.py\n"
        "- shell 脚本当前仍存在，但只是过渡入口，不是长期主架构\n"
        "- 飞书是交付层，不是系统本体\n"
        "\n"
        "【State 合同】\n"
        "- 当前活跃生产系统是 A 股 D1 Agent\n"
        "- 不修改 State 公式\n"
        "- 不修改 E=14 / F=15 定义\n"
        "- 不重解释 view_tf × structure_tf 二维坐标命名\n"
        "\n"
        "【合规约束 — 不可违反】\n"
        "- 不输出 买入/卖出/加仓/减仓/推荐/建议买入/建议卖出 等交易指令\n"
        "- 不输出确定性判断（必涨/必跌/稳赚）\n"
        "- 不预测价格或收益（预计涨到/目标价）\n"
        "- 只引用系统输出的事实数据和统计结论\n"
        "- 每条涉及交易的应答必须附带免责声明\n"
        "\n"
        "【应答结构 — 涉及交易时必须遵循】\n"
        "1. 事实层：系统输出了什么\n"
        "2. 环境层：当前环境特征\n"
        "3. 适配层：策略与环境匹配度\n"
        "4. 校准层：统计数据的可信度\n"
        "\n"
        "【描述运行时时必须统一】\n"
        "- 不把 agently_daily_flow.py 描述成主线\n"
        "- 不把 run_daily_pipeline.sh 描述成长期主入口\n"
        "- 不引用 MT5/US 文档作为当前规则源\n"
        "\n"
        '【合规句式参考】\n'
        '- 不说[建议买入] -> 说[当前环境适配该策略，该信号处于XX状态]\n'
        '- 不说[预计涨到XX] -> 说[历史统计显示该条件下XX]\n'
        '- 不说[止损设在XX] -> 说[最近支撑位为XX，策略默认止损价为XX，可参考]\n'
    )
