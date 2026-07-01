#!/usr/bin/env python3
"""Fetch US market / cross-asset observations for realtime event answers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermass_platform.realtime.us_market_fetcher import (  # noqa: E402
    build_us_market_source_observations,
    write_source_observations,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch delayed US market realtime source observations.")
    parser.add_argument("--sample", action="store_true", help="Write deterministic sample observations without network.")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds.")
    parser.add_argument("--print-json", action="store_true", help="Print full payload JSON.")
    parser.add_argument(
        "--write-errors",
        action="store_true",
        help="Write error observations when live fetch fails. By default errors do not overwrite latest observations.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_us_market_source_observations(sample=args.sample, timeout=args.timeout, root=ROOT)
    status = str(payload.get("status") or "")
    paths = {"latest_json": "-"}
    if status in {"ok", "sample"} or args.write_errors:
        paths = write_source_observations(payload, root=ROOT)
    if args.print_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        available = [
            item
            for item in payload.get("source_observations", [])
            if item.get("status") == "available"
        ]
        print(
            "us_market_realtime_sources "
            f"status={status} "
            f"source_count={len(payload.get('source_observations') or [])} "
            f"available={len(available)} "
            f"latest={paths['latest_json']}"
        )
    return 0 if status in {"ok", "sample"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
