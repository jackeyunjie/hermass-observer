"""Shared research response helpers for A-share external research replies."""

from .external_research_enrichment import (
    AVAILABLE_ENRICHMENT_PROVIDERS,
    apply_optional_enrichment,
    build_enrichment_policy,
    validate_public_news_digest_output,
)
from .external_research_evidence import build_external_research_evidence
from .external_research_formatters import (
    RENDER_PROFILES,
    format_deep_research_card,
    format_evidence_card,
    format_quick_research_card,
)

__all__ = [
    "build_external_research_evidence",
    "AVAILABLE_ENRICHMENT_PROVIDERS",
    "build_enrichment_policy",
    "apply_optional_enrichment",
    "validate_public_news_digest_output",
    "RENDER_PROFILES",
    "format_quick_research_card",
    "format_deep_research_card",
    "format_evidence_card",
]
