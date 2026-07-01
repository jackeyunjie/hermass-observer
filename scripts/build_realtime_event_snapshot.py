#!/usr/bin/env python3
"""Build realtime-event source-plan snapshot for the AI assistant."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermass_platform.realtime.event_snapshot import (  # noqa: E402
    DEFAULT_QUERIES,
    build_realtime_event_snapshot,
    write_realtime_event_snapshot,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Hermass realtime event snapshot.")
    parser.add_argument("--date", default="", help="Snapshot date, YYYY-MM-DD. Defaults to today.")
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Question to include in source planning. Can be provided multiple times.",
    )
    parser.add_argument(
        "--source-observations",
        default="",
        help="Optional JSON file with source_observations rows from fetchers.",
    )
    parser.add_argument("--print-json", action="store_true", help="Print full snapshot JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    observation_file = Path(args.source_observations) if args.source_observations else None
    queries = args.query or list(DEFAULT_QUERIES)
    snapshot = build_realtime_event_snapshot(
        queries,
        root=ROOT,
        observation_file=observation_file,
    )
    paths = write_realtime_event_snapshot(snapshot, root=ROOT, as_of_date=args.date or None)
    if args.print_json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        coverage = snapshot.get("coverage", {})
        print(
            "realtime_event_snapshot "
            f"answer_mode={coverage.get('answer_mode')} "
            f"available={len(coverage.get('available_sources') or [])} "
            f"missing={len(coverage.get('missing_sources') or [])} "
            f"latest={paths['latest_json']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
