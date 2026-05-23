#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_step(cmd: list[str]) -> None:
    print("+ " + " ".join(str(part) for part in cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def default_foundation_db(date_str: str) -> Path:
    return ROOT / "outputs" / f"p116_foundation_{date_str.replace('-', '')}" / "p116_foundation.duckdb"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the standalone daily P116 all-three E/F workflow.")
    parser.add_argument("--date", required=True, help="Trading date, e.g. 2026-05-20")
    parser.add_argument("--raw-db", type=Path, help="Blackwolf raw daily DuckDB for rebuilding foundation.")
    parser.add_argument("--foundation-db", type=Path, help="Existing or target foundation DuckDB.")
    parser.add_argument("--previous-date", help="Previous trading date snapshot for entered/left/stayed comparison.")
    parser.add_argument("--skip-foundation", action="store_true", help="Use an existing foundation DB instead of rebuilding.")
    parser.add_argument("--model", default="deepseekV4", help="Default LLM model for downstream text/report steps.")
    args = parser.parse_args()

    foundation_db = args.foundation_db or default_foundation_db(args.date)
    if not args.skip_foundation:
        cmd = [
            sys.executable,
            "scripts/build_p116_foundation.py",
            "--date",
            args.date,
            "--out-db",
            str(foundation_db),
        ]
        if args.raw_db:
            cmd.extend(["--raw-db", str(args.raw_db)])
        run_step(cmd)
    elif not foundation_db.exists():
        raise FileNotFoundError(f"foundation DB not found: {foundation_db}")

    export_cmd = [
        sys.executable,
        "scripts/export_daily_all_three_ef.py",
        "--date",
        args.date,
        "--foundation-db",
        str(foundation_db),
    ]
    if args.previous_date:
        export_cmd.extend(["--previous-date", args.previous_date])
    run_step(export_cmd)

    # Run DeepSeek report generator
    report_cmd = [
        sys.executable,
        "scripts/generate_deepseek_report.py",
        "--date",
        args.date,
        "--model",
        args.model,
    ]
    try:
        run_step(report_cmd)
        report_md = str(ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_report_{args.date.replace('-', '')}.md")
    except Exception as e:
        print(f"Warning: DeepSeek report generation failed: {e}", file=sys.stderr)
        report_md = "failed"

    summary = {
        "date": args.date,
        "model": args.model,
        "foundation_db": str(foundation_db),
        "snapshot_html": str(ROOT / "public" / f"p116_all_three_ef_{args.date.replace('-', '')}.html"),
        "diff_html": str(ROOT / "public" / f"p116_all_three_ef_diff_{args.date.replace('-', '')}.html"),
        "report_markdown": report_md,
        "latest_html": str(ROOT / "public" / "p116_all_three_ef_latest.html"),
        "latest_diff_html": str(ROOT / "public" / "p116_all_three_ef_diff_latest.html"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
