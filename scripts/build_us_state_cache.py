#!/usr/bin/env python3
"""Build US stock state cache from us_foundation.duckdb.

Reuses StateCacheBuilder logic; iterates all available dates.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

# Add project root to path so we can import state_cache_builder
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from state_cache_builder import StateCacheBuilder

US_FOUNDATION_DB = ROOT / "outputs" / "us_stock" / "us_foundation.duckdb"
US_CACHE_DB = ROOT / "outputs" / "us_stock" / "us_state_cache.duckdb"


def get_available_dates(foundation_db: Path) -> list[str]:
    """Get all distinct state_date values from d1_perspective_state."""
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT state_date FROM d1_perspective_state ORDER BY state_date"
        ).fetchall()
        return [str(r[0]) for r in rows]
    finally:
        con.close()


def get_cached_dates(cache_db: Path) -> set[str]:
    """Get dates already present in cache manifest."""
    if not cache_db.exists():
        return set()
    con = duckdb.connect(str(cache_db))
    try:
        has_table = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='main' AND table_name='state_cache_manifest'"
        ).fetchone()[0]
        if not has_table:
            return set()
        rows = con.execute("SELECT DISTINCT obs_date::TEXT FROM state_cache_manifest").fetchall()
        return set(r[0] for r in rows)
    finally:
        con.close()


def build_all_dates() -> dict:
    if not US_FOUNDATION_DB.exists():
        raise FileNotFoundError(f"Foundation DB not found: {US_FOUNDATION_DB}")

    dates = get_available_dates(US_FOUNDATION_DB)
    cached = get_cached_dates(US_CACHE_DB)
    pending = [d for d in dates if d not in cached]

    print(f"Found {len(dates)} dates in {US_FOUNDATION_DB}")
    print(f"Date range: {dates[0]} ~ {dates[-1]}")
    print(f"Already cached: {len(cached)}, Pending: {len(pending)}")

    results = []
    for i, date_str in enumerate(pending):
        print(f"\n[{i + 1}/{len(pending)}] Building cache for {date_str}...")
        builder = StateCacheBuilder(
            date_str=date_str,
            foundation_db=US_FOUNDATION_DB,
            cache_db=US_CACHE_DB,
            boundary_pct=0.03,
        )
        try:
            result = builder.build()
            print(
                f"  OK: all_three_ef={result['counts']['all_three_ef_count']}, "
                f"distribution={result['counts']['distribution_rows']}, "
                f"transitions={result['counts']['transition_rows']}, "
                f"sr_boundary={result['counts']['sr_boundary_rows']}, "
                f"durations={result['counts']['duration_rows']}"
            )
            results.append({"date": date_str, "ok": True, **result["counts"]})
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"date": date_str, "ok": False, "error": str(e)})

    all_ok = sum(1 for r in results if r["ok"])
    all_failed = sum(1 for r in results if not r["ok"])
    summary = {
        "foundation_db": str(US_FOUNDATION_DB),
        "cache_db": str(US_CACHE_DB),
        "total_dates": len(dates),
        "already_cached": len(cached),
        "newly_built": len(pending),
        "success": all_ok,
        "failed": all_failed,
        "results": results,
    }

    # Save manifest
    manifest_path = US_CACHE_DB.parent / "us_state_cache_manifest.json"
    manifest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n✅ US State Cache complete: {US_CACHE_DB}")
    print(f"   Dates: {summary['success']}/{summary['total_dates']} succeeded")
    print(f"   Manifest: {manifest_path}")

    return summary


if __name__ == "__main__":
    build_all_dates()
