import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
SUB_DIR = ROOT / "outputs" / "subscription"
SUB_DIR.mkdir(parents=True, exist_ok=True)


def _user_path(user_id: str) -> Path:
    import hashlib

    safe = hashlib.sha256(user_id.encode()).hexdigest()[:16]
    return SUB_DIR / f"sub_{safe}.json"


def get_subscription(user_id: str) -> dict:
    path = _user_path(user_id)
    if not path.exists():
        from hermass_platform.monetization.tier_gate import get_beta_default_tier

        return {
            "user_id": user_id,
            "tier": get_beta_default_tier(),
            "status": "active",
            "started_at": date.today().isoformat(),
            "expires_at": "",
            "source": "beta_internal",
            "daily_usage": {},
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        from hermass_platform.monetization.tier_gate import get_beta_default_tier

        return {
            "user_id": user_id,
            "tier": get_beta_default_tier(),
            "status": "active",
            "started_at": date.today().isoformat(),
            "expires_at": "",
            "source": "beta_internal",
            "daily_usage": {},
        }


def set_tier(user_id: str, tier: str, source: str = "manual") -> dict:
    from hermass_platform.monetization.tier_gate import get_tier_definition

    td = get_tier_definition(tier)
    sub = {
        "user_id": user_id,
        "tier": tier,
        "tier_name": td["name"],
        "status": "active",
        "started_at": date.today().isoformat(),
        "expires_at": "",
        "source": source,
        "daily_usage": {},
    }
    path = _user_path(user_id)
    path.write_text(json.dumps(sub, ensure_ascii=False, indent=2), encoding="utf-8")
    return sub


def check_daily_usage(sub: dict) -> dict:
    today = date.today().isoformat()
    daily = sub.get("daily_usage", {})
    used = daily.get(today, 0)
    from hermass_platform.monetization.tier_gate import get_limits

    limits = get_limits(sub.get("tier", "free"))
    max_queries = limits.get("daily_queries", 0)

    return {
        "date": today,
        "used": used,
        "limit": max_queries if max_queries > 0 else None,
        "remaining": None if max_queries < 0 else max(0, max_queries - used),
        "is_limited": max_queries > 0,
        "can_query": max_queries < 0 or used < max_queries,
    }


def record_usage(user_id: str, action: str) -> dict:
    sub = get_subscription(user_id)
    if "daily_usage" not in sub:
        sub["daily_usage"] = {}

    today = date.today().isoformat()
    sub["daily_usage"][today] = sub["daily_usage"].get(today, 0) + 1

    path = _user_path(user_id)
    path.write_text(json.dumps(sub, ensure_ascii=False, indent=2), encoding="utf-8")

    return check_daily_usage(sub)


def can_access(user_id: str, feature: str) -> tuple[bool, str]:
    sub = get_subscription(user_id)
    usage = check_daily_usage(sub)

    if usage["is_limited"] and not usage["can_query"]:
        return False, f"今日用量已用完（{usage['used']}/{usage['limit']}）。明天 0 点重置。"

    from hermass_platform.monetization.tier_gate import is_feature_allowed

    if not is_feature_allowed(sub["tier"], feature):
        from hermass_platform.monetization.tier_gate import get_upgrade_prompt

        prompt = get_upgrade_prompt(sub["tier"])
        return False, f"你的 {sub.get('tier_name', sub['tier'])} 层级不支持此功能。{prompt}"

    return True, ""
