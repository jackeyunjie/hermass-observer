#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from recommendation_engine import DEFAULT_CONFIG, build_candidates, load_yaml, write_outputs


def default_moneyflow_csv(date_str: str) -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "outputs" / "moneyflow_evidence" / f"moneyflow_evidence_{date_str.replace('-', '')}.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run P116 recommendation workbench.")
    parser.add_argument("--date", required=True, help="Trading date, e.g. 2026-05-20")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--moneyflow-csv", type=Path, help="Optional moneyflow enhancement CSV.")
    parser.add_argument("--no-default-moneyflow", action="store_true", help="Do not auto-load public/p116_moneyflow_enhanced_top10_YYYYMMDD.csv.")
    args = parser.parse_args()

    config = load_yaml(args.config)
    moneyflow_csv = args.moneyflow_csv
    if moneyflow_csv is None and not args.no_default_moneyflow:
        candidate = default_moneyflow_csv(args.date)
        moneyflow_csv = candidate if candidate.exists() else None

    payload = build_candidates(args.date, config, moneyflow_csv)
    paths = write_outputs(payload, args.date)
    print(
        json.dumps(
            {
                "date": args.date,
                "pool_total": payload["pool_total"],
                "candidate_total": payload["candidate_total"],
                "portfolio_size": payload["portfolio_size"],
                "watchlist_size": payload["watchlist_size"],
                "left_count": payload["left_count"],
                "json": str(paths.json_path),
                "csv": str(paths.csv_path),
                "html": str(paths.html_path),
                "public_csv": str(paths.public_csv_path),
                "latest_html": str(paths.latest_html_path),
                "moneyflow_csv": str(moneyflow_csv) if moneyflow_csv else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
