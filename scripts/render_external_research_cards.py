#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermass_platform.research.external_research_evidence import build_external_research_evidence
from hermass_platform.research import AVAILABLE_ENRICHMENT_PROVIDERS, RENDER_PROFILES
from hermass_platform.research.external_research_enrichment import apply_optional_enrichment
from hermass_platform.research.external_research_formatters import (
    format_deep_research_card,
    format_evidence_card,
    format_quick_research_card,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render external research cards from shared evidence payload."
    )
    parser.add_argument("--stock-code", required=True, help="A-share stock code")
    parser.add_argument("--date", required=True, help="As-of date in YYYY-MM-DD")
    parser.add_argument("--foundation-db", help="Optional foundation DB override")
    parser.add_argument("--fundamental-db", help="Optional fundamental DB override")
    parser.add_argument("--evidence-json", help="Optional existing evidence payload JSON")
    parser.add_argument(
        "--enable-enrichment", action="store_true", help="Attach optional enrichment placeholder metadata"
    )
    parser.add_argument(
        "--provider",
        action="append",
        choices=sorted(AVAILABLE_ENRICHMENT_PROVIDERS),
        help="Optional enrichment provider to attach. Repeatable. Implies --enable-enrichment.",
    )
    parser.add_argument(
        "--render-profile",
        choices=sorted(RENDER_PROFILES),
        default="full",
        help="Formatter expansion level for the deep research card. Defaults to full.",
    )
    parser.add_argument("--output-dir", help="Optional output directory")
    args = parser.parse_args()

    if args.evidence_json:
        evidence = json.loads(Path(args.evidence_json).read_text(encoding="utf-8"))
    else:
        evidence = build_external_research_evidence(
            stock_code=args.stock_code,
            as_of_date=args.date,
            foundation_db=args.foundation_db,
            fundamental_db=args.fundamental_db,
        )
    if args.enable_enrichment or args.provider:
        evidence = apply_optional_enrichment(evidence, enable=True, providers=args.provider)

    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else (ROOT / "outputs" / "external_research_cards" / args.date.replace("-", ""))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.stock_code.replace(".", "_")

    quick = format_quick_research_card(evidence)
    deep = format_deep_research_card(evidence, render_profile=args.render_profile)
    card = format_evidence_card(evidence)

    paths = {
        "quick": output_dir / f"{prefix}_quick.md",
        "deep": output_dir / f"{prefix}_deep.md",
        "evidence": output_dir / f"{prefix}_evidence.md",
        "payload": output_dir / f"{prefix}_payload.json",
    }
    paths["quick"].write_text(quick + "\n", encoding="utf-8")
    paths["deep"].write_text(deep + "\n", encoding="utf-8")
    paths["evidence"].write_text(card + "\n", encoding="utf-8")
    paths["payload"].write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: str(path) for key, path in paths.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
