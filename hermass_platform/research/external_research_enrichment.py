from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

AVAILABLE_ENRICHMENT_PROVIDERS = {
    "industry_competition_external_peers",
    "public_news_digest",
}

PUBLIC_NEWS_EVENT_TYPES = {"earnings", "policy", "capital", "tech"}
PUBLIC_NEWS_IMPACT_HINTS = {"positive", "neutral", "negative"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_ymd_date(value: Any) -> bool:
    text = str(value or "")
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except Exception:
        return False


def build_enrichment_policy(
    enabled: bool = False,
    mode: str = "local_placeholder",
    requested_providers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "mode": mode,
        "priority": "local_evidence_first",
        "requested_providers": requested_providers or [],
        "rules": [
            "Enrichment is optional and must not replace local structured evidence.",
            "External additions must remain traceable and explicitly marked as enrichment.",
            "Default research path stays A-share, research-only, and source-tier aware.",
        ],
    }


def build_industry_competition_external_peers_contract() -> dict[str, Any]:
    return {
        "provider_id": "industry_competition_external_peers",
        "enabled": False,
        "status": "placeholder",
        "priority": "supplement_only",
        "last_attempt_at": None,
        "last_success_at": None,
        "error_count": 0,
        "stale_after_hours": 24,
        "purpose": "Supplement local industry competition evidence with externally sourced peer and industry-structure signals.",
        "must_not": [
            "Must not overwrite local company_profile / industry_state fields.",
            "Must not become the primary source for research conclusions.",
            "Must not introduce investment advice, target prices, or ratings as system judgment.",
        ],
        "expected_output": {
            "peer_candidates": [],
            "industry_structure_notes": [],
            "source_trace": [],
        },
    }


def build_public_news_digest_contract() -> dict[str, Any]:
    return {
        "provider_id": "public_news_digest",
        "enabled": False,
        "status": "placeholder",
        "priority": "supplement_only",
        "last_attempt_at": None,
        "last_success_at": None,
        "error_count": 0,
        "stale_after_hours": 8,
        "purpose": "Supplement local evidence with public-event and policy/news digest items relevant to company and industry changes.",
        "must_not": [
            "Must not overwrite local risk_flags / market_views fields.",
            "Must not turn news headlines into investment advice or trading signals.",
            "Must not treat public news as primary evidence when structured local evidence exists.",
        ],
        "expected_output": {
            "digest_items": [],
            "policy_event_notes": [],
            "source_trace": [],
        },
        "digest_item_schema": {
            "title": "string",
            "date": "YYYY-MM-DD",
            "source": "string",
            "event_type": "earnings | policy | capital | tech",
            "impact_hint": "positive | neutral | negative",
        },
    }


def validate_public_news_digest_output(payload: dict[str, Any]) -> dict[str, Any]:
    digest_items = payload.get("digest_items")
    policy_event_notes = payload.get("policy_event_notes")
    source_trace = payload.get("source_trace")

    if digest_items is None or not isinstance(digest_items, list):
        raise ValueError("public_news_digest.digest_items must be a list")
    if policy_event_notes is None or not isinstance(policy_event_notes, list):
        raise ValueError("public_news_digest.policy_event_notes must be a list")
    if source_trace is None or not isinstance(source_trace, list):
        raise ValueError("public_news_digest.source_trace must be a list")

    normalized_items: list[dict[str, Any]] = []
    for idx, item in enumerate(digest_items):
        if not isinstance(item, dict):
            raise ValueError(f"public_news_digest.digest_items[{idx}] must be an object")
        title = str(item.get("title") or "").strip()
        date = str(item.get("date") or "").strip()
        source = str(item.get("source") or "").strip()
        event_type = str(item.get("event_type") or "").strip()
        impact_hint = str(item.get("impact_hint") or "").strip()

        if not title:
            raise ValueError(f"public_news_digest.digest_items[{idx}].title is required")
        if not _is_ymd_date(date):
            raise ValueError(f"public_news_digest.digest_items[{idx}].date must be YYYY-MM-DD")
        if not source:
            raise ValueError(f"public_news_digest.digest_items[{idx}].source is required")
        if event_type not in PUBLIC_NEWS_EVENT_TYPES:
            raise ValueError(
                f"public_news_digest.digest_items[{idx}].event_type must be one of {sorted(PUBLIC_NEWS_EVENT_TYPES)}"
            )
        if impact_hint not in PUBLIC_NEWS_IMPACT_HINTS:
            raise ValueError(
                f"public_news_digest.digest_items[{idx}].impact_hint must be one of {sorted(PUBLIC_NEWS_IMPACT_HINTS)}"
            )

        normalized_items.append(
            {
                "title": title,
                "date": date,
                "source": source,
                "event_type": event_type,
                "impact_hint": impact_hint,
            }
        )

    return {
        "digest_items": normalized_items,
        "policy_event_notes": [str(item) for item in policy_event_notes],
        "source_trace": [item for item in source_trace],
    }


def apply_optional_enrichment(
    evidence: dict[str, Any],
    *,
    enable: bool = False,
    mode: str = "local_placeholder",
    providers: list[str] | None = None,
) -> dict[str, Any]:
    enriched = deepcopy(evidence)
    enriched.setdefault("meta", {})
    requested_providers = [item for item in (providers or []) if item in AVAILABLE_ENRICHMENT_PROVIDERS]
    active_providers = requested_providers or sorted(AVAILABLE_ENRICHMENT_PROVIDERS)
    enriched["meta"]["enrichment_policy"] = build_enrichment_policy(
        enabled=enable,
        mode=mode,
        requested_providers=requested_providers,
    )

    if not enable:
        enriched["meta"]["enrichment_status"] = "disabled"
        return enriched

    local_hints = []
    company_profile = enriched.get("company_profile", {})
    industry_state = enriched.get("industry_state", {})
    market_views = enriched.get("market_views", {})
    risk_flags = enriched.get("risk_flags", {})

    if company_profile.get("ths_concepts"):
        local_hints.append("ths_concepts_available")
    if company_profile.get("comparable_companies") or company_profile.get("competitor_companies"):
        local_hints.append("peer_companies_available")
    if industry_state.get("sector_resonance") is True:
        local_hints.append("sector_resonance_available")
    if industry_state.get("prosperity_score") not in (None, ""):
        local_hints.append("industry_prosperity_available")

    providers_payload: dict[str, Any] = {}

    if "industry_competition_external_peers" in active_providers:
        peer_provider = build_industry_competition_external_peers_contract()
        peer_provider["last_attempt_at"] = _utc_now()
        if company_profile.get("comparable_companies") or company_profile.get("competitor_companies"):
            peer_provider["status"] = "local_peer_fields_already_present"
            peer_provider["enabled"] = True
            peer_provider["last_success_at"] = peer_provider["last_attempt_at"]
            peer_provider["expected_output"]["peer_candidates"] = [
                {
                    "name": item.strip(),
                    "source": "local_ifind",
                    "confidence": 0.95,
                }
                for item in (
                    str(company_profile.get("comparable_companies") or "")
                    + ","
                    + str(company_profile.get("competitor_companies") or "")
                ).replace("，", ",").split(",")
                if item.strip()
            ][:6]
        elif company_profile.get("ths_concepts") or industry_state.get("sector_resonance") is True:
            peer_provider["status"] = "ready_for_external_peer_supplement"
            peer_provider["enabled"] = True
            peer_provider["last_success_at"] = peer_provider["last_attempt_at"]
        providers_payload["industry_competition_external_peers"] = peer_provider

    if "public_news_digest" in active_providers:
        news_provider = build_public_news_digest_contract()
        news_provider["last_attempt_at"] = _utc_now()
        if market_views.get("latest_report") or market_views.get("rating_distribution"):
            news_provider["status"] = "local_market_views_already_present"
            news_provider["enabled"] = True
            news_provider["last_success_at"] = news_provider["last_attempt_at"]
            news_provider["expected_output"]["policy_event_notes"] = [
                "local market_views already present; external public-news provider should only add event/policy deltas."
            ]
        elif risk_flags.get("data_risks") or company_profile.get("ths_concepts") or industry_state.get("sector_resonance") is True:
            news_provider["status"] = "ready_for_external_news_supplement"
            news_provider["enabled"] = True
            news_provider["last_success_at"] = news_provider["last_attempt_at"]
        providers_payload["public_news_digest"] = news_provider

    enriched["meta"]["enrichment_status"] = "local_placeholder_ready"
    enriched["meta"]["enrichment_hints"] = local_hints
    enriched["enrichment"] = {
        "status": "placeholder",
        "requested_providers": requested_providers,
        "local_hints": local_hints,
        "external_sources": [],
        "providers": providers_payload,
        "notes": [
            "This enrichment layer is a placeholder for future network-backed research augmentation.",
            "Current version only exposes local readiness hints and must not overwrite core evidence fields.",
        ],
    }
    return enriched
