from datetime import datetime, timezone

from .cognitive_ledger import get_event_summary, load_events
from .cognitive_scorer import compute_cognitive_scores


def build_cognitive_profile(user_id: str) -> dict:
    summary = get_event_summary(user_id)
    scores = compute_cognitive_scores(user_id)

    if scores.get("data_insufficient"):
        return {
            "user_id": user_id,
            "profile_version": "v1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_period": {
                "from": summary.get("first_event_at", ""),
                "to": summary.get("last_event_at", ""),
            },
            "sample_size": {
                "events": summary["total_events"],
                "active_days": summary["active_days"],
            },
            "confidence": scores["confidence"],
            "status": "insufficient_data",
            "summary": scores["message"],
            "strengths": [],
            "blind_spots": [],
            "recommended_path": "",
            "dimensions": {},
        }

    dims = scores.get("dimensions", {})
    sorted_dims = sorted(dims.values(), key=lambda x: x["value"], reverse=True)

    strengths_labels = [d["label"] for d in sorted_dims[:2] if d["value"] >= 0.5]
    blind_spots_labels = [d["label"] for d in sorted_dims[-2:] if d["value"] < 0.5]

    profile_label = _profile_label(scores)
    recommended_path = _recommend_path(scores)
    summary_text = _generate_summary(summary, scores, profile_label)

    return {
        "user_id": user_id,
        "profile_version": "v1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_period": {
            "from": summary.get("first_event_at", ""),
            "to": summary.get("last_event_at", ""),
        },
        "sample_size": {
            "events": summary["total_events"],
            "active_days": summary["active_days"],
        },
        "confidence": scores["confidence"],
        "status": "ready",
        "profile_label": profile_label,
        "summary": summary_text,
        "strengths": strengths_labels,
        "blind_spots": blind_spots_labels,
        "recommended_path": recommended_path,
        "dimensions": dims,
    }


def _profile_label(scores: dict) -> str:
    dims = scores.get("dimensions", {})
    sa = dims.get("strategy_awareness", {}).get("value", 0.3)
    le = dims.get("learning_engagement", {}).get("value", 0.3)
    ra = dims.get("risk_awareness", {}).get("value", 0.3)

    if sa >= 0.7 and le >= 0.5:
        return "策略型学习者"
    if ra >= 0.7:
        return "风险敏感型"
    if sa >= 0.5:
        return "策略探索者"
    if le >= 0.5:
        return "知识探索者"
    return "市场观察者"


def _recommend_path(scores: dict) -> str:
    dims = scores.get("dimensions", {})
    sa = dims.get("strategy_awareness", {}).get("value", 0.3)
    ra = dims.get("risk_awareness", {}).get("value", 0.3)
    sl = dims.get("state_literacy", {}).get("value", 0.3)

    if sa >= 0.6 and sl >= 0.4:
        return "建议深入 2560 策略学习，结合 State 信号做趋势跟踪"
    if ra >= 0.6:
        return "建议先巩固风控知识，学习止损和仓位管理"
    if sl >= 0.5:
        return "建议开始学习策略信号解读，从 VCP 收缩突破入手"
    return "建议从市场环境认知开始，每天查看市场简报积累 State 概念"


def _generate_summary(summary: dict, scores: dict, label: str) -> str:
    total = summary.get("total_events", 0)
    days = summary.get("active_days", 0)
    ws = scores.get("weighted_score", 0)

    return f"认知画像：{label}。基于 {total} 次交互（{days} 个活跃日），综合认知评分 {ws}/100。"
