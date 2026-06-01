from random import choice, shuffle

KNOWLEDGE_BASE = {
    "state": {
        "title": "State 多周期状态系统",
        "concepts": [
            {
                "name": "State 是什么",
                "answer": "State 是 Hermass Observer 系统的核心概念。它用一个 0-15 的数字（十六进制 0-F）描述一只股票在某个周期（日线 D1、周线 W1、月线 MN1）上的综合状态。\n\n公式：state_score = base + trend_bit × 4 + position_bit + volatility_bit\n\n四个维度：\n- base（基数）：0=收缩，8=扩张\n- trend_bit（趋势）：0=无趋势，1=有趋势（牛/熊）\n- position_bit（位置）：0=区间内，2=突破支撑/阻力\n- volatility_bit（波动）：0=稳定，1=波动扩张\n\n例如：score=14（hex='E'）= 扩(8) + 有趋势(4) + 突破(2) + 稳(0)",
            },
            {
                "name": "E 和 F 状态的含义",
                "answer": "E（score=14）和 F（score=15）是系统中最强的两个状态。\n\nE = 扩张 + 有趋势 + 突破 + 稳定\nF = 扩张 + 有趋势 + 突破 + 波动扩张\n\nE 被称为'最优质状态'——趋势+突破但不伴随过度波动。\nF 是'最强状态'——包含所有四个维度，但波动扩张可能预示过热。\n\nE/F 状态永远是正值。负值的 '-E'、'-F' 不算 E/F 状态。",
            },
            {
                "name": "ef_count 的含义",
                "answer": "ef_count 是 MN1/W1/D1 三周期中处于 E 或 F 状态的周期数量，取值范围 0-3。\n\nef_count=3：三周期共振（最强信号，多周期合力确认）\nef_count=2：双周期共振（大概率信号，至少两个周期确认）\nef_count=1：单周期信号（仅一个周期强势，需注意大周期背景）\nef_count=0：无 E/F 状态\n\n系统筛选'全三 E/F 池'的标准是 ef_count >= 2。",
            },
            {
                "name": "D1 视角天条",
                "answer": "D1 视角天条是 State 底座的核心规则（不可修改）：\n\n所有周期的 position 计算都使用 D1 日线收盘价比较各自周期的 SR（支撑/阻力）关键位。\n\n- MN1 position = D1 close vs MN1 SR（月线关键位）\n- W1 position = D1 close vs W1 SR（周线关键位）\n- D1 position = D1 close vs D1 SR（日线关键位）\n\n但 trend、base、volatility 使用各自周期的指标数据。\n\n这意味着：同一只股票在周三看到的 W1 State 反映的是'日线价格在周线结构中的位置'，而非周线自身的状态（后者需等周五收盘后由独立周线系统计算）。",
            },
            {
                "name": "收缩与扩张",
                "answer": "收缩（base=0）：布林带带宽处于历史低位（低于 Q20 分位），表示市场处于横盘整理、筹码积累阶段。\n\n扩张（base=8）：布林带带宽突破历史低位，表示市场开始选择方向。扩张是趋势启动的前兆信号。\n\n典型路径：收缩 → 收缩后释放（等于 VCP 突破）→ 扩张+趋势 → 延展\n\n收缩后释放是最有价值的交易信号之一——在收缩环境中蓄力后突破，往往有较好的持续性。",
            },
        ],
    },
    "vcp": {
        "title": "VCP 波幅收缩突破策略",
        "concepts": [
            {
                "name": "VCP 策略简介",
                "answer": "VCP（Volatility Contraction Pattern，波幅收缩形态）是 Mark Minervini 提出的突破交易策略。\n\n核心逻辑：股票经历一系列'收缩→释放'的交替过程，每次收缩的幅度越来越小（波幅递减），在最后一次收缩后放量突破。\n\nVCP 信号类型：\n- breakthrough：放量突破（最优）\n- breakthrough_weak_vol：弱放量突破\n- breakthrough_no_vol：无放量突破\n- contraction：收缩结构（观察阶段）",
            },
            {
                "name": "VCP 与 State E/F 的关系",
                "answer": "VCP 策略与 State 系统的适配关系：\n\n最佳 State 组合（E/E/F）：MN1=E, W1=E, D1=F → 大周期支撑+日线最强突破\n最优 State 组合（E/E/E）：三周期全 E → 波动稳定，趋势可靠\n\n系统验收发现：VCP 信号在 E/E/F 组合下 20 日超额收益 +17.02%（胜率 63.64%）。\n\n不适用场景：D1 未处于收缩后释放路径，或 ef_count=0 时 VCP 突破假信号率显著上升。",
            },
        ],
    },
    "ma2560": {
        "title": "MA2560 趋势跟踪策略",
        "concepts": [
            {
                "name": "2560 策略简介",
                "answer": "2560 策略是基于两条均线（MA25 和 MA60）的趋势跟踪系统。\n\n信号类型：\n- golden_cross：MA25 金叉 MA60（做多入场）\n- strong_hold：MA25 和 MA60 多头排列+强势持仓结构\n- aligned：MA25 和 MA60 多头排列\n- death_cross_exit：MA25 死叉 MA60（出场信号）\n- bearish：空头排列（风险警示）\n\n核心原则：只在趋势明确的环境中使用，不参与横盘震荡。",
            },
            {
                "name": "2560 的出场规则",
                "answer": "2560 策略的出场条件：\n\n1. MA25 跌破 MA60（死叉）→ 强制出场\n2. 连续 3 日收盘价低于 MA25 → 减仓信号\n3. W1 视角转为 non-E/F  → 降低趋势置信度\n\n不适合 2560 的环境：\n- 市场整体处于震荡（收缩期占比高）\n- ef_count=0 时大周期不支持趋势策略\n- ADX < 20 时趋势动能不足",
            },
        ],
    },
    "bollinger_bandit": {
        "title": "布林强盗策略",
        "concepts": [
            {
                "name": "布林强盗策略简介",
                "answer": "布林强盗（Bollinger Bandit）策略是基于布林带的趋势跟踪和均值回归系统。\n\n核心信号：bb_bandit_long_entry（多头触发）\n\n触发条件：价格从布林带下轨反弹并站上中轨，同时带宽开始扩张。\n\n出场使用递减均线：当价格跌破递减均线时触发退出。\n\n系统验收发现：布林强盗在 D1 volatility_bit=0（波动稳定）时表现更优，KIMI 推荐的波动扩张候选被本地数据拒绝。",
            },
        ],
    },
    "risk": {
        "title": "风险管理基础",
        "concepts": [
            {
                "name": "止损方法",
                "answer": "Hermass 系统支持三种止损方法：\n\n1. SR 支撑止损：止损位 = D1 SR 支撑位 - 3% 缓冲\n   适用场景：SR 关键位已就绪（sr_ready=true）\n\n2. ATR 止损：止损位 = 入场价 - ATR × 2\n   适用场景：自适应波动率，震荡股止损窄、趋势股止损宽\n\n3. 组合止损：SR 止损（60%）+ ATR 止损（40%）加权\n   适用场景：兼顾结构位和波动率\n\n止损不能过远（最多 -15%）也不能过近（最多 -5%）。",
            },
            {
                "name": "仓位管理",
                "answer": "仓位管理的核心原则：\n\n1. 单只股票最大仓位：不超过总资金的 20%\n2. 回撤保护：\n   - 回撤 < 5%：正常交易\n   - 回撤 5-10%：仓位降至 85%\n   - 回撤 10-15%：仓位降至 60%\n   - 回撤 > 15%：暂停新开仓\n   - 回撤 > 20%：强制减仓\n\n3. 环境适配：\n   - ef_count=3 环境：正常仓位\n   - ef_count=2 环境：正常仓位\n   - ef_count=1 环境：减仓至 70%\n   - ef_count=0 环境：降至 30% 或暂停",
            },
        ],
    },
    "system": {
        "title": "系统使用指南",
        "concepts": [
            {
                "name": "如何解读每日简报",
                "answer": "每日简报包含：\n\n1. 市场环境概览：当前阶段（趋势行进/收缩/震荡）、全三 E/F 池规模\n2. 策略适配度：各策略在当日环境下的适配评级\n3. 优质信号：当日最佳适配信号列表\n4. 风险提示：异常波动、大周期背景、重要事件\n\n阅读顺序：先看环境 → 确定策略 → 浏览信号 → 关注风险提示",
            },
            {
                "name": "如何提高认知水平",
                "answer": "系统推荐的认知提升路径：\n\n阶段 1（1-2 周）：每天阅读市场简报，熟悉 State 概念\n阶段 2（2-4 周）：学习一种策略（建议从 2560 开始），跟踪信号\n阶段 3（4-8 周）：对比策略信号与市场实际走势，培养盘感\n阶段 4（8 周+）：形成自己的交易框架，系统作为辅助决策工具\n\n定期查看自己的认知画像（cognitive profile），关注盲点改进。",
            },
        ],
    },
}

PRACTICE_QUESTIONS = [
    {
        "topic": "state",
        "question": "State score=14 的 hex 表示是什么？它的四个维度分别是什么？",
        "hint": "回想 State 编码公式和 16 进制表示",
        "answer": "hex='E'。四个维度：base=8(扩张)、trend_bit=1(有趋势)、position_bit=2(突破)、volatility_bit=0(稳定)。公式：8+4+2+0=14",
    },
    {
        "topic": "state",
        "question": "ef_count=2 代表什么含义？系统筛选的最低标准是多少？",
        "hint": "考虑三周期中 E/F 状态的计数",
        "answer": "ef_count=2 表示 MN1/W1/D1 三个周期中有两个处于 E 或 F 状态。系统筛选的最低标准是 ef_count >= 2。",
    },
    {
        "topic": "state",
        "question": "D1 视角天条中，W1 position 是用什么价格计算的？",
        "hint": "不是周线收盘价",
        "answer": "W1 position 使用 D1 日线收盘价比较 W1 SR（周线支撑/阻力位）。这个规则的目的是确保每日信号与 State 基于同一价格点。",
    },
    {
        "topic": "vcp",
        "question": "VCP 策略在什么 State 组合下 20 日超额收益最高？胜率是多少？",
        "hint": "三周期共振",
        "answer": "E/E/F 组合（MN1=E, W1=E, D1=F）下 20 日超额收益 +17.02%，胜率 63.64%。",
    },
    {
        "topic": "ma2560",
        "question": "2560 策略在什么市场环境下不适合使用？",
        "hint": "考虑 ef_count 和趋势强度",
        "answer": "不适合的环境包括：1) 市场整体收缩期（ef_count=0 时大周期不支持趋势策略）；2) ADX < 20 时趋势动能不足；3) 横盘震荡市场。",
    },
    {
        "topic": "risk",
        "question": "SR 支撑止损的缓冲区是多少？止损范围有什么限制？",
        "hint": "百分比范围",
        "answer": "缓冲区是 SR 支撑位下方 3%。止损范围限制在入场价的 -5% 到 -15% 之间——不能太紧（容易误触发）也不能太远（风险过大）。",
    },
]


def search_knowledge(query_keywords: list[str]) -> list[dict]:
    results = []
    for topic, topic_data in KNOWLEDGE_BASE.items():
        for concept in topic_data["concepts"]:
            score = 0
            combined = concept["name"] + concept["answer"] + topic_data["title"]
            for kw in query_keywords:
                if kw.lower() in combined.lower():
                    score += 1
            if score > 0:
                results.append(
                    {
                        "topic": topic,
                        "topic_title": topic_data["title"],
                        "concept_name": concept["name"],
                        "answer": concept["answer"],
                        "relevance": min(score / len(query_keywords), 1.0),
                    }
                )
    results.sort(key=lambda x: x["relevance"], reverse=True)
    return results[:5]


def get_learning_path(cognitive_profile: dict | None = None) -> list[dict]:
    path = [
        {
            "phase": 1,
            "title": "市场环境认知（1-2 周）",
            "description": "每天阅读市场简报，熟悉 State 概念、E/F 状态、ef_count",
            "key_term": get_concept("state", "State 是什么"),
        },
        {
            "phase": 2,
            "title": "策略入门（2-4 周）",
            "description": "选择一种策略深入学习，建议从 2560 开始。每天跟踪一个信号，记录观察结果。",
            "key_term": get_concept("ma2560", "2560 策略简介"),
        },
        {
            "phase": 3,
            "title": "策略对比与盘感培养（4-8 周）",
            "description": "对比 2560 和 VCP 两种策略的信号，观察不同市场环境下的表现差异。",
            "key_term": get_concept("vcp", "VCP 策略简介"),
        },
        {
            "phase": 4,
            "title": "框架形成（8 周+）",
            "description": "基于经验形成自己的交易框架。系统作为辅助决策和数据验证工具。",
            "key_term": get_concept("risk", "仓位管理"),
        },
    ]

    if cognitive_profile:
        dims = cognitive_profile.get("dimensions", {})
        risk_score = dims.get("risk_awareness", {}).get("value", 0.3)
        strategy_score = dims.get("strategy_awareness", {}).get("value", 0.3)

        if risk_score < 0.4:
            path.insert(
                0,
                {
                    "phase": 0,
                    "title": "风控基础（优先补课）",
                    "description": "你的风险意识评分偏低，建议先学习止损和仓位管理基础知识。",
                    "key_term": get_concept("risk", "止损方法"),
                },
            )

        if strategy_score < 0.4:
            path.insert(
                1,
                {
                    "phase": 0,
                    "title": "策略基础认知",
                    "description": "建议先了解不同策略的基本逻辑，再进行深入学习。",
                    "key_term": get_concept("state", "E 和 F 状态的含义"),
                },
            )

    return path


def get_concept(topic: str, concept_name: str) -> str | None:
    topic_data = KNOWLEDGE_BASE.get(topic)
    if not topic_data:
        return None
    for c in topic_data["concepts"]:
        if c["name"] == concept_name:
            return c["answer"]
    return None


def get_topic_list() -> list[dict]:
    return [
        {"topic": tid, "title": td["title"], "concept_count": len(td["concepts"])}
        for tid, td in KNOWLEDGE_BASE.items()
    ]


def generate_quiz(topic: str = "", count: int = 3) -> list[dict]:
    pool = [q for q in PRACTICE_QUESTIONS if not topic or q["topic"] == topic]
    if not pool:
        pool = PRACTICE_QUESTIONS
    shuffle(pool)
    selected = pool[: min(count, len(pool))]
    return [
        {
            "question": q["question"],
            "hint": q["hint"],
            "answer": q["answer"],
        }
        for q in selected
    ]
