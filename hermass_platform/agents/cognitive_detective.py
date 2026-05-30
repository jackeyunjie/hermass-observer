from hermass_platform.cognitive.cognitive_profile_builder import build_cognitive_profile
from hermass_platform.cognitive.cognitive_ledger import record_event, get_event_summary, BehaviorEvent


def get_user_profile(user_id: str) -> dict:
    profile = build_cognitive_profile(user_id)
    return {
        "agent_id": "cognitive_detective",
        "agent_name": "认知检测师",
        "status": "ok",
        "data": profile,
        "summary": profile.get("summary", ""),
        "errors": [],
        "generated_at": profile.get("generated_at", ""),
    }


def record_user_behavior(
    user_id: str,
    event_type: str,
    payload: dict | None = None,
) -> dict:
    if payload is None:
        payload = {}

    event = BehaviorEvent(
        user_id=user_id,
        event_type=event_type,
        payload=payload,
    )
    ok = record_event(event)

    return {
        "agent_id": "cognitive_detective",
        "agent_name": "认知检测师",
        "status": "ok" if ok else "error",
        "data": {"event_type": event_type, "recorded": ok},
        "summary": f"行为事件记录{'成功' if ok else '失败'}：{event_type}",
        "errors": [] if ok else ["无效事件类型"],
        "generated_at": event.timestamp,
    }


def get_user_summary(user_id: str) -> dict:
    summary = get_event_summary(user_id)
    return {
        "agent_id": "cognitive_detective",
        "agent_name": "认知检测师",
        "status": "ok",
        "data": summary,
        "summary": f"用户 {user_id} 共 {summary['total_events']} 次交互 ({summary['active_days']} 活跃日)",
        "errors": [],
        "generated_at": "",
    }
