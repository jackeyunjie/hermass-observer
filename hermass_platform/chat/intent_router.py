import re
from dataclasses import dataclass, field
from typing import Optional

INTENT_DEFINITIONS = {
    "market_phase": {
        "keywords": [
            "市场阶段",
            "市场什么阶段",
            "行情怎么样",
            "大盘怎么样",
            "市场环境",
            "市场如何",
            "当前市场",
            "市场状态",
            "现在市场",
        ],
        "agent": "market_analyst",
        "description": "查询当前市场阶段与环境",
    },
    "sector_heat": {
        "keywords": [
            "行业怎么样",
            "板块怎么样",
            "电子行业",
            "新能源",
            "半导体",
            "医药",
            "消费",
            "银行",
            "行业热度",
            "板块热度",
            "哪个行业",
        ],
        "agent": "market_analyst",
        "description": "查询行业/板块热度与 E/F 分布",
    },
    "macro_outlook": {
        "keywords": [
            "宏观",
            "GDP",
            "PMI",
            "利率",
            "货币",
            "CPI",
            "PPI",
            "央行",
            "流动性",
            "经济",
            "降息",
            "降准",
            "通胀",
        ],
        "agent": "market_analyst",
        "description": "查询宏观经济环境",
    },
    "my_profile": {
        "keywords": ["我的风格", "我的交易", "我是什么类型", "我的认知", "我的画像", "我的水平", "我适合"],
        "agent": "cognitive_detective",
        "description": "查询个人认知画像",
    },
    "my_fit": {
        "keywords": ["适合我吗", "我能不能", "我应该用", "推荐策略", "哪个策略适合", "我适合哪个", "适合我"],
        "agent": "strategy_advisor",
        "description": "策略与个人适配度评估",
    },
    "my_risk": {
        "keywords": ["风险", "最大回撤", "我该注意", "注意什么", "有什么风险", "仓位", "持仓风险"],
        "agent": "risk_guardian",
        "description": "个人风险评估",
    },
    "strategy_fit": {
        "keywords": [
            "VCP",
            "2560",
            "布林强盗",
            "哪个策略好",
            "策略适配",
            "策略表现",
            "信号怎么样",
            "策略环境",
            "VCP怎么样",
            "2560怎么样",
            "策略现在",
        ],
        "agent": "strategy_advisor",
        "description": "查询策略在当前环境的适配度",
    },
    "signal_explore": {
        "keywords": [
            "有什么信号",
            "哪些股票",
            "有好信号吗",
            "推荐股票",
            "优质信号",
            "今天有什么",
            "最佳适配",
            "观察池",
            "信号",
        ],
        "agent": "strategy_advisor",
        "description": "探索策略信号与观察池",
    },
    "exit_rule": {
        "keywords": [
            "什么时候走",
            "止损",
            "止盈",
            "出场",
            "该卖吗",
            "什么时候卖",
            "触发退出",
            "卖出",
            "离场",
        ],
        "agent": "risk_guardian",
        "description": "查询出场规则与风控参考",
    },
    "learn_topic": {
        "keywords": [
            "什么是",
            "怎么学",
            "什么叫",
            "教教我",
            "解释一下",
            "不懂",
            "VCP形态",
            "2560战法",
            "布林带宽",
            "State是什么",
            "EF是什么意思",
            "什么叫收缩",
            "什么叫扩张",
        ],
        "agent": "coach",
        "description": "知识学习与概念解释",
    },
    "practice": {
        "keywords": ["测试题", "考考我", "测验", "题目", "练习", "模拟"],
        "agent": "coach",
        "description": "交易知识练习与测试",
    },
    "subscription": {
        "keywords": ["升级", "会员", "付费", "价格", "多少钱", "怎么买", "订阅", "开通", "续费", "收费"],
        "agent": "monetization_butler",
        "description": "会员与付费相关",
    },
    "benefits": {
        "keywords": ["高级版", "权益", "功能对比", "有什么功能", "能做什么", "免费版", "基础版"],
        "agent": "monetization_butler",
        "description": "权益与功能查询",
    },
    "sector_resonance": {
        "keywords": [
            "哪些行业",
            "行业在动",
            "什么行业在涨",
            "板块共振",
            "行业共振",
            "资金在流向什么",
            "哪个板块在涨",
            "什么板块",
            "板块在动",
            "行业在涨",
            "哪个行业好",
        ],
        "agent": "market_analyst",
        "description": "查询当日板块共振信号",
    },
}


@dataclass
class IntentResult:
    intent: str
    agent: str
    confidence: float
    matched_keywords: list[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    return text.strip().lower()


def classify_intent(user_message: str) -> IntentResult:
    message = _normalize(user_message)

    best_intent = "market_phase"
    best_agent = "market_analyst"
    best_score = 0.0
    best_keywords: list[str] = []

    for intent_name, config in INTENT_DEFINITIONS.items():
        keywords = config["keywords"]
        match_count = 0
        matched: list[str] = []
        for kw in keywords:
            if kw.lower() in message:
                match_count += 1
                matched.append(kw)

        score = match_count / max(1, len(keywords))
        if score > best_score:
            best_score = score
            best_intent = intent_name
            best_agent = config["agent"]
            best_keywords = matched

    confidence = min(1.0, best_score * 3.0)

    if confidence < 0.2:
        confidence = 0.2
        if _detect_greeting(message):
            best_intent = "market_phase"
            best_agent = "market_analyst"
            best_keywords = ["问候"]
            confidence = 0.5

    return IntentResult(
        intent=best_intent,
        agent=best_agent,
        confidence=round(confidence, 2),
        matched_keywords=best_keywords,
    )


def _detect_greeting(message: str) -> bool:
    greetings = [
        "你好",
        "嗨",
        "早上好",
        "下午好",
        "晚上好",
        "hello",
        "hi",
        "在吗",
        "在不在",
        "帮我看",
        "帮我",
        "请问",
    ]
    for g in greetings:
        if g in message:
            return True
    return False


def get_agent_for_intent(intent: str) -> str:
    config = INTENT_DEFINITIONS.get(intent)
    if config:
        return config["agent"]
    return "market_analyst"


def list_all_intents() -> list[dict]:
    return [
        {"intent": name, "agent": cfg["agent"], "description": cfg["description"]}
        for name, cfg in INTENT_DEFINITIONS.items()
    ]
