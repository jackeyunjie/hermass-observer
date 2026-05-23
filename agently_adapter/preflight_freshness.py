#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = [
    "blackwolf_actions/download_daily.py",
    "blackwolf_actions/download_moneyflow_recent.py",
    "agently_adapter/stockpool_daily_runner.py",
    "scripts/build_p116_foundation.py",
    "scripts/export_daily_all_three_ef.py",
    "recommendation/run_recommendation_workflow.py",
    "recommendation/build_shareable_table.py",
    "workflows/agently_stockpool_dag/stockpool_daily_update.yaml",
]
MIN_MTIME_MARKERS = {
    "blackwolf_actions/download_moneyflow_recent.py": "2026-05-21T09:15:00+00:00",
    "agently_adapter/stockpool_daily_runner.py": "2026-05-21T09:15:00+00:00",
}


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def git_revision() -> str:
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip()
    return "no-git"


def mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")


def assert_not_stale_output(path: Path, date_str: str, errors: list[str]) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8", errors="ignore")[:5000]
    if date_str not in text and ymd(date_str) not in str(path):
        errors.append(f"existing output may be stale: {path}")


def run_preflight(date_str: str, previous_date: str) -> dict[str, Any]:
    errors: list[str] = []
    files = []
    for rel in REQUIRED_FILES:
        path = ROOT / rel
        if not path.exists():
            errors.append(f"required file missing: {rel}")
            continue
        item = {"path": rel, "mtime": mtime_iso(path), "size": path.stat().st_size}
        marker = MIN_MTIME_MARKERS.get(rel)
        if marker and datetime.fromisoformat(item["mtime"]) < datetime.fromisoformat(marker):
            errors.append(f"required file is older than marker: {rel} mtime={item['mtime']} marker={marker}")
        files.append(item)

    if previous_date >= date_str:
        errors.append(f"previous_date must be before date: previous_date={previous_date}, date={date_str}")

    for rel in [
        f"public/p116_all_three_ef_{ymd(date_str)}.html",
        f"public/p116_recommendation_{ymd(date_str)}.html",
        f"public/p116_recommendation_shareable_{ymd(date_str)}.html",
    ]:
        assert_not_stale_output(ROOT / rel, date_str, errors)

    status = "PASS" if not errors else "FAIL"
    payload = {
        "schema_version": "stockpool_preflight_freshness_v1",
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "date": date_str,
        "previous_date": previous_date,
        "git_revision": git_revision(),
        "required_files": files,
        "errors": errors,
    }
    out = ROOT / "reports" / "blackwolf_actions" / f"preflight_freshness_{ymd(date_str)}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise RuntimeError(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight freshness checks for Agently stockpool DAG.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--previous-date", required=True)
    args = parser.parse_args()
    print(json.dumps(run_preflight(args.date, args.previous_date), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
