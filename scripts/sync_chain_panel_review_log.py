#!/usr/bin/env python3
"""Sync chain panel review JSONL decisions into DuckDB.

The JSONL audit log remains the immutable evidence trail. This script builds a
query-friendly latest-decision table so sampling and candidate generation can
exclude mappings already rejected by review.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"
DEFAULT_LOG = ROOT / "outputs" / "industry_chain" / "chain_panel_review_log.jsonl"

CREATE_RAW_SQL = """
CREATE TABLE IF NOT EXISTS chain_panel_review_decisions_raw (
    chain_id VARCHAR NOT NULL,
    node_id VARCHAR NOT NULL,
    stock_code VARCHAR NOT NULL,
    as_of_date VARCHAR NOT NULL,
    source_type VARCHAR,
    review_status VARCHAR NOT NULL,
    reviewed_node_id VARCHAR,
    reviewer_note VARCHAR,
    reviewer VARCHAR,
    reviewed_at VARCHAR NOT NULL,
    synced_at VARCHAR NOT NULL
);
"""


def load_log_rows(log_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not log_path.exists():
        return rows
    with log_path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {log_path}:{line_no}: {exc}") from exc
            rows.append(item)
    return rows


def sync_review_log(db_path: Path = DEFAULT_DB, log_path: Path = DEFAULT_LOG) -> dict[str, Any]:
    if not db_path.exists():
        return {"ok": False, "error": f"Database not found: {db_path}"}

    rows = load_log_rows(log_path)
    synced_at = datetime.now(timezone.utc).isoformat()
    con = duckdb.connect(str(db_path))
    try:
        con.execute(CREATE_RAW_SQL)
        con.execute("DELETE FROM chain_panel_review_decisions_raw")
        if rows:
            con.executemany(
                """
                INSERT INTO chain_panel_review_decisions_raw
                (chain_id, node_id, stock_code, as_of_date, source_type,
                 review_status, reviewed_node_id, reviewer_note, reviewer,
                 reviewed_at, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(row.get("chain_id") or ""),
                        str(row.get("node_id") or ""),
                        str(row.get("stock_code") or ""),
                        str(row.get("as_of_date") or ""),
                        str(row.get("source_type") or ""),
                        str(row.get("review_status") or ""),
                        str(row.get("reviewed_node_id") or row.get("node_id") or ""),
                        str(row.get("reviewer_note") or ""),
                        str(row.get("reviewer") or ""),
                        str(row.get("reviewed_at") or synced_at),
                        synced_at,
                    )
                    for row in rows
                    if row.get("chain_id") and row.get("node_id") and row.get("stock_code") and row.get("as_of_date")
                ],
            )

        con.execute(
            """
            CREATE OR REPLACE TABLE chain_panel_review_decisions AS
            SELECT *
            FROM (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY chain_id, node_id, stock_code, as_of_date
                        ORDER BY reviewed_at DESC, synced_at DESC
                    ) AS rn
                FROM chain_panel_review_decisions_raw
                WHERE review_status IN ('verified', 'rejected', 'needs_research')
            )
            WHERE rn = 1
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TABLE chain_panel_review_mapping_decisions AS
            SELECT *
            FROM (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY chain_id, node_id, stock_code
                        ORDER BY reviewed_at DESC, synced_at DESC
                    ) AS mapping_rn
                FROM chain_panel_review_decisions_raw
                WHERE review_status IN ('verified', 'rejected', 'needs_research')
            )
            WHERE mapping_rn = 1
            """
        )
        summary = {
            "ok": True,
            "log_path": str(log_path),
            "db_path": str(db_path),
            "raw_rows": con.execute("SELECT COUNT(*) FROM chain_panel_review_decisions_raw").fetchone()[0],
            "latest_rows": con.execute("SELECT COUNT(*) FROM chain_panel_review_decisions").fetchone()[0],
            "mapping_latest_rows": con.execute("SELECT COUNT(*) FROM chain_panel_review_mapping_decisions").fetchone()[0],
            "status_dist": con.execute(
                "SELECT review_status, COUNT(*) FROM chain_panel_review_decisions GROUP BY 1 ORDER BY 1"
            ).fetchall(),
            "mapping_status_dist": con.execute(
                "SELECT review_status, COUNT(*) FROM chain_panel_review_mapping_decisions GROUP BY 1 ORDER BY 1"
            ).fetchall(),
            "synced_at": synced_at,
        }
    finally:
        con.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync chain_panel_review_log.jsonl into DuckDB.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--log", default=str(DEFAULT_LOG))
    args = parser.parse_args()

    result = sync_review_log(db_path=Path(args.db), log_path=Path(args.log))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
