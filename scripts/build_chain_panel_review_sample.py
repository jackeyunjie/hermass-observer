#!/usr/bin/env python3
"""Build a human review sample for ifind_chain_panel.

The sample is stratified by source/evidence/chain so manual review can catch
both rule-inference and iFinD MCP mapping errors before the panel is promoted
into a production-grade stock pool.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHAIN_DB = ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"
DEFAULT_FUND_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "industry_chain"

REVIEW_COLUMNS = [
    "review_status",
    "reviewed_node_id",
    "reviewer_note",
    "reviewer",
    "reviewed_at",
]


def _connect(chain_db: Path, fund_db: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(chain_db), read_only=True)
    if fund_db.exists():
        escaped = str(fund_db).replace("'", "''")
        con.execute(f"ATTACH '{escaped}' AS fund (READ_ONLY)")
    return con


def _fetch_dicts(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    cur = con.execute(sql, params or [])
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def load_panel_rows(
    chain_db: Path,
    fund_db: Path,
    date_filter: str | None,
    chain_filter: list[str] | None,
    include_verified: bool,
    include_decided: bool,
) -> list[dict[str, Any]]:
    where = []
    params: list[Any] = []
    if date_filter:
        where.append("p.as_of_date = ?")
        params.append(date_filter)
    if chain_filter:
        where.append(f"p.chain_id IN ({', '.join(['?'] * len(chain_filter))})")
        params.extend(chain_filter)
    if not include_verified:
        where.append("p.manual_verified = false")
    if not include_decided:
        where.append(
            """
            NOT EXISTS (
                SELECT 1
                FROM chain_panel_review_decisions d
                WHERE d.chain_id = p.chain_id
                  AND d.node_id = p.node_id
                  AND d.stock_code = p.stock_code
                  AND d.as_of_date = p.as_of_date
                  AND d.review_status IN ('verified', 'rejected')
            )
            """
        )

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    con = _connect(chain_db, fund_db)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if "chain_panel_review_mapping_decisions" in tables and not include_decided:
            where = [
                clause.replace(
                    "chain_panel_review_decisions d",
                    "chain_panel_review_mapping_decisions d",
                ).replace(
                    "                  AND d.as_of_date = p.as_of_date\n",
                    "",
                )
                for clause in where
            ]
            where_sql = "WHERE " + " AND ".join(where) if where else ""
        elif "chain_panel_review_decisions" not in tables and not include_decided:
            include_decided = True
            where = [clause for clause in where if "chain_panel_review_decisions" not in clause]
            where_sql = "WHERE " + " AND ".join(where) if where else ""
        has_fund = any(row[0] == "fund" for row in con.execute("SELECT database_name FROM duckdb_databases()").fetchall())
        profile_sql = """
            WITH profile_latest AS (
                SELECT *
                FROM (
                    SELECT
                        stock_code,
                        as_of_date AS profile_as_of_date,
                        sw_l1,
                        sw_l2,
                        sw_l3,
                        ths_concepts,
                        main_business,
                        main_product_types,
                        main_product_names,
                        ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY as_of_date DESC) AS rn
                    FROM fund.ifind_industry_chain_profile
                )
                WHERE rn = 1
            )
        """ if has_fund else ""
        join_sql = "LEFT JOIN profile_latest pr ON p.stock_code = pr.stock_code" if has_fund else ""
        profile_cols = """
            pr.profile_as_of_date,
            pr.sw_l1,
            pr.sw_l2,
            pr.sw_l3,
            pr.ths_concepts,
            pr.main_business,
            pr.main_product_types,
            pr.main_product_names,
        """ if has_fund else """
            NULL AS profile_as_of_date,
            NULL AS sw_l1,
            NULL AS sw_l2,
            NULL AS sw_l3,
            NULL AS ths_concepts,
            NULL AS main_business,
            NULL AS main_product_types,
            NULL AS main_product_names,
        """
        sql = f"""
            {profile_sql}
            SELECT
                p.chain_id,
                p.chain_name,
                p.node_id,
                p.node_name,
                p.node_position,
                p.stock_code,
                p.stock_name,
                p.role,
                p.source_type,
                p.evidence_level,
                p.confidence,
                p.node_match_method,
                p.manual_verified,
                p.as_of_date,
                {profile_cols}
                p.raw_source_ref
            FROM ifind_chain_panel p
            {join_sql}
            {where_sql}
            ORDER BY p.chain_id, p.node_id, p.source_type, p.stock_code
        """
        return _fetch_dicts(con, sql, params)
    finally:
        con.close()


def stratified_sample(rows: list[dict[str, Any]], sample_size: int, seed: int) -> list[dict[str, Any]]:
    if len(rows) <= sample_size:
        return rows

    rng = random.Random(seed)
    strata: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            str(row.get("source_type") or ""),
            str(row.get("evidence_level") or ""),
            str(row.get("chain_id") or ""),
        )
        strata[key].append(row)

    selected: list[dict[str, Any]] = []
    selected_ids: set[tuple[str, str, str, str, str]] = set()
    for key in sorted(strata):
        bucket = list(strata[key])
        rng.shuffle(bucket)
        row = bucket[0]
        row_id = _row_id(row)
        selected.append(row)
        selected_ids.add(row_id)
        if len(selected) >= sample_size:
            return selected

    remaining = [row for row in rows if _row_id(row) not in selected_ids]
    rng.shuffle(remaining)
    selected.extend(remaining[: max(0, sample_size - len(selected))])
    return selected


def _row_id(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("chain_id")),
        str(row.get("node_id")),
        str(row.get("stock_code")),
        str(row.get("source_type")),
        str(row.get("as_of_date")),
    )


def add_review_columns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        enriched = dict(row)
        enriched["review_status"] = ""
        enriched["reviewed_node_id"] = row.get("node_id") or ""
        enriched["reviewer_note"] = ""
        enriched["reviewer"] = ""
        enriched["reviewed_at"] = ""
        output.append(enriched)
    return output


def write_outputs(rows: list[dict[str, Any]], output_dir: Path, label: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"chain_panel_review_sample_{label}.csv"
    json_path = output_dir / f"chain_panel_review_sample_{label}.json"

    if not rows:
        csv_path.write_text("", encoding="utf-8")
    else:
        cols = [col for col in rows[0].keys() if col not in REVIEW_COLUMNS] + REVIEW_COLUMNS
        with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=cols)
            writer.writeheader()
            writer.writerows(rows)

    summary = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_records": len(rows),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "review_status_values": ["verified", "rejected", "needs_research"],
        "source_type_dist": dict(Counter(str(r.get("source_type")) for r in rows)),
        "evidence_level_dist": dict(Counter(str(r.get("evidence_level")) for r in rows)),
        "chain_dist": dict(Counter(str(r.get("chain_id")) for r in rows)),
    }
    json_path.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def build_sample(
    sample_size: int,
    seed: int,
    date_filter: str | None,
    chain_filter: list[str] | None,
    include_verified: bool,
    include_decided: bool,
    chain_db: Path,
    fund_db: Path,
    output_dir: Path,
) -> dict[str, Any]:
    if not chain_db.exists():
        return {"ok": False, "error": f"Database not found: {chain_db}"}

    rows = load_panel_rows(chain_db, fund_db, date_filter, chain_filter, include_verified, include_decided)
    sample = stratified_sample(rows, sample_size, seed)
    sample = add_review_columns(sample)
    label_date = date_filter.replace("-", "") if date_filter else datetime.now().strftime("%Y%m%d")
    label = f"{label_date}_n{len(sample)}_seed{seed}"
    summary = write_outputs(sample, output_dir, label)
    summary.update(
        {
            "total_candidate_records": len(rows),
            "date_filter": date_filter,
            "chain_filter": chain_filter,
            "include_verified": include_verified,
            "include_decided": include_decided,
        }
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a manual review sample for ifind_chain_panel.")
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260604)
    parser.add_argument("--date", help="Filter ifind_chain_panel.as_of_date, YYYY-MM-DD")
    parser.add_argument("--chains", help="Comma-separated chain_id list")
    parser.add_argument("--include-verified", action="store_true")
    parser.add_argument("--include-decided", action="store_true", help="Allow already verified/rejected review decisions into the sample")
    parser.add_argument("--db", default=str(DEFAULT_CHAIN_DB))
    parser.add_argument("--fund-db", default=str(DEFAULT_FUND_DB))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    chain_filter = [c.strip() for c in args.chains.split(",") if c.strip()] if args.chains else None
    result = build_sample(
        sample_size=args.sample_size,
        seed=args.seed,
        date_filter=args.date,
        chain_filter=chain_filter,
        include_verified=args.include_verified,
        include_decided=args.include_decided,
        chain_db=Path(args.db),
        fund_db=Path(args.fund_db),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
