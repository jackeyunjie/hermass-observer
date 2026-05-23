#!/usr/bin/env python3
"""Build and maintain the local iFinD fundamental tracking pool.

The pool is the durable list of stocks that deserve prepared fundamental data.
Downstream ledgers and recommendation logic should read this local DuckDB first
instead of downloading every stock on demand.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def init_schema() -> None:
    spec = importlib.util.spec_from_file_location(
        "fundamental_evidence_schema",
        str(ROOT / "scripts" / "fundamental_evidence_schema.py"),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load fundamental_evidence_schema.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.init_schema(DB_PATH)


def load_p116(date_str: str) -> list[dict[str, Any]]:
    path = ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_{ymd(date_str)}.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for row in payload.get("rows", []):
        code = row.get("symbol") or row.get("stock_code")
        if not code:
            continue
        rows.append(
            {
                "stock_code": code,
                "stock_name": row.get("stock_name"),
                "sw_l1": row.get("sw_l1"),
                "sw_l2": row.get("sw_l2"),
                "sw_l3": row.get("sw_l3"),
                "source_pool": "p116_all_three_ef",
                "priority_tier": "core",
            }
        )
    return rows


def load_pattern_cross(date_str: str) -> list[dict[str, Any]]:
    path = ROOT / "outputs" / "pattern_lifecycle" / f"pattern_cross_ef_{ymd(date_str)}.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for row in payload.get("ef_with_structure", []):
        code = row.get("stock_code")
        if not code:
            continue
        rows.append(
            {
                "stock_code": code,
                "stock_name": None,
                "sw_l1": None,
                "sw_l2": None,
                "sw_l3": None,
                "source_pool": "pattern_cross_ef",
                "priority_tier": "core",
            }
        )
    return rows


def merge_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    priority = {"core": 3, "watch": 2, "archive": 1}
    for row in rows:
        code = row["stock_code"]
        current = merged.setdefault(code, dict(row))
        for key in ("stock_name", "sw_l1", "sw_l2", "sw_l3"):
            if not current.get(key) and row.get(key):
                current[key] = row[key]
        if row.get("source_pool") and row["source_pool"] not in str(current.get("source_pool", "")):
            current["source_pool"] = ",".join(filter(None, [current.get("source_pool"), row["source_pool"]]))
        if priority.get(row.get("priority_tier", "watch"), 0) > priority.get(current.get("priority_tier", "watch"), 0):
            current["priority_tier"] = row["priority_tier"]
    return sorted(merged.values(), key=lambda item: item["stock_code"])


def rebuild_pool(date_str: str, include: list[str], limit: int = 0) -> dict[str, Any]:
    init_schema()
    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    if "p116" in include:
        rows.extend(load_p116(date_str))
    if "pattern_cross" in include:
        rows.extend(load_pattern_cross(date_str))
    rows = merge_rows(rows)
    if limit > 0:
        rows = rows[:limit]

    con = duckdb.connect(str(DB_PATH))
    for row in rows:
        con.execute(
            """
            INSERT INTO ifind_tracking_pool
                (stock_code, stock_name, sw_l1, sw_l2, sw_l3, source_pool,
                 first_added, last_seen, priority_tier, refresh_frequency, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'weekly', TRUE)
            ON CONFLICT (stock_code) DO UPDATE SET
                stock_name = COALESCE(excluded.stock_name, ifind_tracking_pool.stock_name),
                sw_l1 = COALESCE(excluded.sw_l1, ifind_tracking_pool.sw_l1),
                sw_l2 = COALESCE(excluded.sw_l2, ifind_tracking_pool.sw_l2),
                sw_l3 = COALESCE(excluded.sw_l3, ifind_tracking_pool.sw_l3),
                source_pool = excluded.source_pool,
                last_seen = excluded.last_seen,
                priority_tier = excluded.priority_tier,
                active = TRUE
            """,
            (
                row.get("stock_code"),
                row.get("stock_name"),
                row.get("sw_l1"),
                row.get("sw_l2"),
                row.get("sw_l3"),
                row.get("source_pool"),
                now,
                date_str,
                row.get("priority_tier", "watch"),
            ),
        )
    count = con.execute("SELECT COUNT(*) FROM ifind_tracking_pool WHERE active").fetchone()[0]
    con.close()
    return {
        "schema_version": "ifind_tracking_pool_v1",
        "date": date_str,
        "included_sources": include,
        "upserted": len(rows),
        "active_pool_size": count,
        "db": str(DB_PATH),
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local iFinD fundamental tracking pool.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--include", default="p116,pattern_cross")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    include = [item.strip() for item in args.include.split(",") if item.strip()]
    print(json.dumps(rebuild_pool(args.date, include, args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
