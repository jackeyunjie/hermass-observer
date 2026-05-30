#!/usr/bin/env python3
"""US stock daily pipeline runner.

Orchestrates the complete US stock analysis pipeline:
foundation → state_cache → signal_ledger → forward_observation → daily_brief
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def run_step(name: str, cmd: list[str], timeout: int = 600) -> dict:
    """Run a pipeline step and capture output."""
    print(f"\n{'='*60}")
    print(f"  STEP: {name}")
    print(f"  CMD:  {' '.join(cmd)}")
    print(f"{'='*60}")

    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(ROOT),
        )
        elapsed = time.time() - start

        if result.returncode != 0:
            print(f"  FAILED ({elapsed:.1f}s)")
            print(f"  STDERR: {result.stderr[:500]}")
            return {"step": name, "status": "failed", "elapsed": elapsed, "error": result.stderr[:500]}

        print(f"  OK ({elapsed:.1f}s)")
        # Try to parse JSON output
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            output = {"raw_output": result.stdout[:200]}

        return {"step": name, "status": "ok", "elapsed": elapsed, "output": output}

    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT ({timeout}s)")
        return {"step": name, "status": "timeout", "elapsed": timeout}
    except Exception as e:
        print(f"  ERROR: {e}")
        return {"step": name, "status": "error", "elapsed": 0, "error": str(e)}


def run_pipeline(date_str: str, foundation_db: str | None = None) -> dict:
    """Run the complete US stock daily pipeline."""
    python = sys.executable
    db_arg = foundation_db or str(ROOT / "outputs" / "us_stock" / "us_foundation.duckdb")

    steps = []

    # Step 1: State cache (skip if already exists)
    cache_db = ROOT / "outputs" / "us_stock" / "us_state_cache.duckdb"
    if not cache_db.exists() or not foundation_db:
        steps.append(run_step(
            "Build US Foundation",
            [python, str(SCRIPTS / "build_us_foundation.py"), "--start", "2020-01-01", "--end", date_str],
            timeout=1800,
        ))
        db_arg = str(ROOT / "outputs" / "us_stock" / "us_foundation.duckdb")

    # Step 2: State cache
    steps.append(run_step(
        "Build State Cache",
        [python, str(SCRIPTS / "build_us_state_cache.py")],
        timeout=600,
    ))

    # Step 3: Strategy signal ledger
    steps.append(run_step(
        "Build Strategy Signals",
        [python, str(SCRIPTS / "us_strategy_signal_ledger.py"), "--date", date_str, "--db", db_arg],
        timeout=300,
    ))

    # Step 4: Forward observation
    steps.append(run_step(
        "Build Forward Observation",
        [python, str(SCRIPTS / "us_forward_observation_ledger.py"), "--date", date_str, "--db", db_arg],
        timeout=300,
    ))

    # Step 5: Daily brief
    steps.append(run_step(
        "Build Daily Brief",
        [python, str(SCRIPTS / "build_us_daily_brief.py")],
        timeout=300,
    ))

    result = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
        "all_ok": all(s["status"] == "ok" for s in steps),
    }

    # Write pipeline log
    log_dir = ROOT / "outputs" / "us_stock" / "pipeline_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"pipeline_{date_str.replace('-','')}.json"
    log_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--db", default=None, help="Override foundation DB path")
    args = parser.parse_args()

    result = run_pipeline(args.date, args.db)

    print(f"\n{'='*60}")
    print("PIPELINE SUMMARY")
    print(f"{'='*60}")
    for step in result["steps"]:
        icon = "✓" if step["status"] == "ok" else "✗"
        print(f"  {icon} {step['step']}: {step['status']} ({step['elapsed']:.1f}s)")
    print(f"\nAll OK: {result['all_ok']}")

    return 0 if result["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
