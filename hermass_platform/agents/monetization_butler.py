from hermass_platform.monetization.tier_gate import (
    get_tier_list,
    get_tier_definition,
    get_feature_list,
    get_upgrade_prompt,
    get_additional_products,
    get_beta_default_tier,
)
from hermass_platform.monetization.subscription_manager import (
    get_subscription,
    set_tier,
    check_daily_usage,
    record_usage,
    can_access,
)


def query_subscription_status(user_id: str) -> dict:
    sub = get_subscription(user_id)
    usage = check_daily_usage(sub)
    tier_def = get_tier_definition(sub["tier"])
    features = get_feature_list(sub["tier"])

    quota_text = ""
    if usage["limit"] is None:
        quota_text = "无限制"
    else:
        quota_text = f"今日已用 {usage['used']}/{usage['limit']} 次"

    return {
        "agent_id": "monetization_butler",
        "agent_name": "变现管家",
        "status": "ok",
        "data": {
            "user_id": user_id,
            "tier": sub["tier"],
            "tier_name": tier_def["name"],
            "status": sub["status"],
            "started_at": sub["started_at"],
            "expires_at": sub["expires_at"],
            "source": sub.get("source", ""),
            "features": features,
            "daily_usage": usage,
        },
        "summary": (
            f"当前层级：{tier_def['name']}。"
            f"{quota_text}。"
            f"可享受 {len(features)} 项权益。"
        ),
        "errors": [],
        "generated_at": "",
    }


def query_tier_comparison(user_id: str = "") -> dict:
    tiers = get_tier_list()
    products = get_additional_products()

    comparison = []
    for t in tiers:
        td = get_tier_definition(t["tier"])
        comparison.append({
            "tier": t["tier"],
            "name": t["name"],
            "price": t["price_text"],
            "features": td.get("features", []),
        })

    summary = (
        "会员层级对比：\n" +
        "\n".join(f"{c['name']}: {c['price']}" for c in comparison) +
        f"\n\n附加产品：{'、'.join(p['name'] for p in products)}"
    )

    return {
        "agent_id": "monetization_butler",
        "agent_name": "变现管家",
        "status": "ok",
        "data": {
            "tiers": comparison,
            "additional_products": products,
            "beta_note": "W14 内测期间所有用户默认分配基础会员层级，免费使用。",
        },
        "summary": summary,
        "errors": [],
        "generated_at": "",
    }


def query_upgrade_recommendation(user_id: str) -> dict:
    sub = get_subscription(user_id)
    current = sub["tier"]

    if current == "premium":
        return {
            "agent_id": "monetization_butler",
            "agent_name": "变现管家",
            "status": "ok",
            "data": {"current_tier": "premium", "next_tier": None, "already_highest": True},
            "summary": "你已经是最高级别（高级会员），无需升级。",
            "errors": [],
            "generated_at": "",
        }

    if current == "free":
        next_tier = "basic"
    elif current == "basic":
        next_tier = "premium"
    else:
        next_tier = "basic"

    next_def = get_tier_definition(next_tier)
    current_features = set(get_feature_list(current))
    next_features = set(get_feature_list(next_tier))
    new_features = list(next_features - current_features)

    return {
        "agent_id": "monetization_butler",
        "agent_name": "变现管家",
        "status": "ok",
        "data": {
            "current_tier": current,
            "current_name": get_tier_definition(current)["name"],
            "next_tier": next_tier,
            "next_name": next_def["name"],
            "next_price": next_def.get("price_text", ""),
            "new_features": new_features,
        },
        "summary": (
            f"推荐升级：{get_tier_definition(current)['name']} → {next_def['name']}。"
            f"价格：{next_def.get('price_text', '')}。"
            f"新增权益：{'、'.join(new_features[:3])}等 {len(new_features)} 项。"
        ),
        "errors": [],
        "generated_at": "",
    }
