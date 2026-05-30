import statistics
from collections import Counter

from .cognitive_ledger import load_events, get_event_summary

DIMENSION_WEIGHTS = {
    "strategy_awareness": 0.20,
    "risk_awareness": 0.20,
    "learning_engagement": 0.20,
    "market_curiosity": 0.15,
    "state_literacy": 0.15,
    "decisiveness": 0.10,
}


def compute_cognitive_scores(user_id: str) -> dict:
    events = load_events(user_id, limit=300)
    summary = get_event_summary(user_id)

    if summary["total_events"] < 10:
        return {
            "user_id": user_id,
            "confidence": 0.0,
            "data_insufficient": True,
            "message": f"交互数据不足（当前 {summary['total_events']} 条，需要至少 10 条）",
            "dimensions": {},
        }

    dist = summary.get("event_distribution", {})

    strategy_queries = dist.get("strategy_query", 0) + dist.get("signal_explore", 0)
    risk_queries = dist.get("risk_query", 0)
    learn_queries = dist.get("learn_query", 0) + dist.get("practice_request", 0)
    market_queries = dist.get("market_query", 0) + dist.get("industry_query", 0)
    profile_queries = dist.get("profile_query", 0)
    total = max(summary["total_events"], 1)

    strategy_awareness = _normalize(strategy_queries / total, 0.08, 0.35)
    risk_awareness = _normalize(risk_queries / total, 0.02, 0.20)
    learning_engagement = _normalize(learn_queries / total, 0.02, 0.25)
    market_curiosity = _normalize(market_queries / total, 0.05, 0.35)
    decisiveness = _normalize(strategy_queries / max(total, 1), 0.05, 0.30)

    state_literacy = 0.3
    state_keywords_count = 0
    for e in events:
        payload = e.payload or {}
        text = payload.get("message", "") + payload.get("intent", "") + payload.get("summary", "")
        if any(kw in text for kw in ["E/F", "State", "ef_count", "收缩", "扩张", "突破", "hex", "MN1", "W1"]):
            state_keywords_count += 1
    state_literacy = _normalize(state_keywords_count / max(total, 1), 0.01, 0.30)

    confidence = min(1.0, 0.20 + 0.80 * summary["active_days"] / 14.0 * min(1.0, total / 100.0))

    weighted_total = (
        strategy_awareness * 0.20
        + risk_awareness * 0.20
        + learning_engagement * 0.20
        + market_curiosity * 0.15
        + state_literacy * 0.15
        + decisiveness * 0.10
    )

    return {
        "user_id": user_id,
        "confidence": round(confidence, 2),
        "data_insufficient": False,
        "dimensions": {
            "strategy_awareness": _dim(strategy_awareness, "策略意识", "对交易策略的关注度和理解深度"),
            "risk_awareness": _dim(risk_awareness, "风险意识", "对风控和止损的关注度"),
            "learning_engagement": _dim(learning_engagement, "学习投入", "主动学习的频率和深度"),
            "market_curiosity": _dim(market_curiosity, "市场探索度", "对市场环境和行业的好奇心"),
            "state_literacy": _dim(state_literacy, "State 认知度", "对系统 State 概念的理解程度"),
            "decisiveness": _dim(decisiveness, "决策倾向", "从分析到行动的倾向强度"),
        },
        "weighted_score": round(weighted_total * 100, 1),
    }


def _normalize(value: float, low: float, high: float) -> float:
    if value >= high:
        return 1.0
    if value <= low:
        return 0.2
    return 0.2 + 0.8 * (value - low) / (high - low)


def _dim(score: float, label: str, description: str) -> dict:
    if score >= 0.80:
        level = "高"
    elif score >= 0.50:
        level = "中"
    elif score >= 0.30:
        level = "中低"
    else:
        level = "低"
    return {
        "value": score,
        "percentile": int(score * 100),
        "label": label,
        "level": level,
        "description": description,
    }
