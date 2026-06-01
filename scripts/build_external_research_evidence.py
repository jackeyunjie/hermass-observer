#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermass_platform.research import (
    AVAILABLE_ENRICHMENT_PROVIDERS,
    apply_optional_enrichment,
    build_external_research_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Phase 1 external research evidence payload.")
    parser.add_argument("--stock-code", required=True, help="A-share stock code, e.g. 000021.SZ or 000021")
    parser.add_argument("--date", required=True, help="As-of date in YYYY-MM-DD")
    parser.add_argument("--foundation-db", help="Optional foundation DB override")
    parser.add_argument("--fundamental-db", help="Optional fundamental DB override")
    parser.add_argument(
        "--enable-enrichment", action="store_true", help="Attach optional enrichment placeholder metadata"
    )
    parser.add_argument(
        "--provider",
        action="append",
        choices=sorted(AVAILABLE_ENRICHMENT_PROVIDERS),
        help="Optional enrichment provider to attach. Repeatable. Implies --enable-enrichment.",
    )
    parser.add_argument("--output", help="Optional output path")
    args = parser.parse_args()

    payload = build_external_research_evidence(
        stock_code=args.stock_code,
        as_of_date=args.date,
        foundation_db=args.foundation_db,
        fundamental_db=args.fundamental_db,
    )
    if args.enable_enrichment or args.provider:
        payload = apply_optional_enrichment(payload, enable=True, providers=args.provider)

    out_path = (
        Path(args.output)
        if args.output
        else (
            ROOT
            / "outputs"
            / "external_research_evidence"
            / f"external_research_evidence_{args.stock_code.replace('.', '_')}_{args.date.replace('-', '')}.json"
        )
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
