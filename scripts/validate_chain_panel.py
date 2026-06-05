#!/usr/bin/env python3
"""validate_chain_panel.py — 校验 ifind_chain_panel 表的数据质量。

用法：
    source .venv/bin/activate
    python3 scripts/validate_chain_panel.py
    python3 scripts/validate_chain_panel.py --date 2026-05-21
    python3 scripts/validate_chain_panel.py --date 2026-05-21 --chain ai_compute

校验项：
    1. 表是否存在
    2. 必填字段非空
    3. confidence 在 [0, 1] 范围内
    4. source_type / evidence_level 枚举值合规
    5. 同一 (chain_id, node_id, stock_code, as_of_date) 无重复
    6. manual_verified 分布
    7. 按 chain_id / node_id 的覆盖度统计
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHAIN_DB = ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"

VALID_SOURCE_TYPES = {"ifind_terminal_excel", "rule_inference", "manual_override", "agent_debate", "ifind_mcp"}
VALID_EVIDENCE_LEVELS = {"strong", "medium", "weak", "manual_export", "none"}
REQUIRED_FIELDS = [
    "chain_id", "chain_name", "node_id", "node_name",
    "stock_code", "source_type", "evidence_level", "confidence",
    "as_of_date", "updated_at",
]


def _append_condition(where_sql: str, condition: str) -> str:
    """Append a condition to an optional WHERE clause."""
    if where_sql:
        return f"{where_sql} AND {condition}"
    return f"WHERE {condition}"


def validate(
    date_str: str | None = None,
    chain_id_filter: str | None = None,
    db_path: Path = DEFAULT_CHAIN_DB,
) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "ok": False,
            "error": f"Database not found: {db_path}",
            "checks": {},
        }

    con = duckdb.connect(str(db_path), read_only=True)
    checks: dict[str, Any] = {}

    try:
        # 1. Table existence
        tables = {t[0] for t in con.execute("SHOW TABLES").fetchall()}
        checks["table_exists"] = "ifind_chain_panel" in tables
        if not checks["table_exists"]:
            return {"ok": False, "error": "ifind_chain_panel table does not exist", "checks": checks}

        # Build WHERE clause
        where_clauses = []
        params: list[Any] = []
        if date_str:
            where_clauses.append("as_of_date = ?")
            params.append(date_str)
        if chain_id_filter:
            where_clauses.append("chain_id = ?")
            params.append(chain_id_filter)
        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        total = con.execute(f"SELECT COUNT(*) FROM ifind_chain_panel {where_sql}", params).fetchone()[0]
        checks["total_records"] = total

        if total == 0:
            return {"ok": True, "warning": "No records match filter", "checks": checks}

        # 2. Required fields non-null
        null_checks = {}
        for field in REQUIRED_FIELDS:
            query_where = _append_condition(where_sql, f"{field} IS NULL")
            cnt = con.execute(
                f"SELECT COUNT(*) FROM ifind_chain_panel {query_where}",
                params,
            ).fetchone()[0]
            null_checks[field] = {"null_count": cnt, "pass": cnt == 0}
        checks["required_fields"] = null_checks

        # 3. Confidence range
        query_where = _append_condition(where_sql, "(confidence < 0 OR confidence > 1)")
        bad_conf = con.execute(
            f"SELECT COUNT(*) FROM ifind_chain_panel {query_where}",
            params,
        ).fetchone()[0]
        checks["confidence_range"] = {"out_of_range": bad_conf, "pass": bad_conf == 0}

        # 4. Enum compliance
        placeholders = ", ".join(["?"] * len(VALID_SOURCE_TYPES))
        query_where = _append_condition(where_sql, f"source_type NOT IN ({placeholders})")
        bad_source = con.execute(
            f"SELECT COUNT(*) FROM ifind_chain_panel {query_where}",
            params + list(VALID_SOURCE_TYPES),
        ).fetchone()[0]
        placeholders_ev = ", ".join(["?"] * len(VALID_EVIDENCE_LEVELS))
        query_where = _append_condition(where_sql, f"evidence_level NOT IN ({placeholders_ev})")
        bad_ev = con.execute(
            f"SELECT COUNT(*) FROM ifind_chain_panel {query_where}",
            params + list(VALID_EVIDENCE_LEVELS),
        ).fetchone()[0]
        checks["source_type_enum"] = {"invalid_count": bad_source, "pass": bad_source == 0}
        checks["evidence_level_enum"] = {"invalid_count": bad_ev, "pass": bad_ev == 0}

        # 5. Duplicates
        dup = con.execute(
            f"""
            SELECT COUNT(*) FROM (
                SELECT chain_id, node_id, stock_code, as_of_date, COUNT(*) as cnt
                FROM ifind_chain_panel {where_sql}
                GROUP BY chain_id, node_id, stock_code, as_of_date
                HAVING COUNT(*) > 1
            )
            """,
            params,
        ).fetchone()[0]
        checks["duplicates"] = {"duplicate_groups": dup, "pass": dup == 0}

        # 6. manual_verified distribution
        mv_dist = con.execute(
            f"SELECT manual_verified, COUNT(*) FROM ifind_chain_panel {where_sql} GROUP BY manual_verified",
            params,
        ).fetchall()
        checks["manual_verified_dist"] = {str(r[0]): r[1] for r in mv_dist}

        # 7. Coverage by chain_id
        chain_cov = con.execute(
            f"SELECT chain_id, COUNT(DISTINCT node_id) as nodes, COUNT(*) as records FROM ifind_chain_panel {where_sql} GROUP BY chain_id ORDER BY records DESC",
            params,
        ).fetchall()
        checks["chain_coverage"] = [
            {"chain_id": r[0], "distinct_nodes": r[1], "records": r[2]} for r in chain_cov
        ]

        # 8. Coverage by source_type
        source_dist = con.execute(
            f"SELECT source_type, COUNT(*) FROM ifind_chain_panel {where_sql} GROUP BY source_type",
            params,
        ).fetchall()
        checks["source_type_dist"] = {r[0]: r[1] for r in source_dist}

        # 9. Low confidence records (< 0.5)
        query_where = _append_condition(where_sql, "confidence < 0.5")
        low_conf = con.execute(
            f"SELECT COUNT(*) FROM ifind_chain_panel {query_where}",
            params,
        ).fetchone()[0]
        checks["low_confidence"] = {"count": low_conf, "pass": low_conf == 0}

        # Overall pass
        all_pass = all(
            checks[k].get("pass", True)
            for k in ["required_fields", "confidence_range", "source_type_enum", "evidence_level_enum", "duplicates", "low_confidence"]
            if isinstance(checks.get(k), dict)
        )
        # required_fields is nested
        for field, info in checks.get("required_fields", {}).items():
            if not info.get("pass", True):
                all_pass = False

    finally:
        con.close()

    return {
        "ok": all_pass,
        "date_filter": date_str,
        "chain_filter": chain_id_filter,
        "checks": checks,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ifind_chain_panel table.")
    parser.add_argument("--date", help="Filter by as_of_date YYYY-MM-DD")
    parser.add_argument("--chain", help="Filter by chain_id")
    parser.add_argument("--db", default=str(DEFAULT_CHAIN_DB), help="Path to industry_chain_evidence.duckdb")
    args = parser.parse_args()

    result = validate(date_str=args.date, chain_id_filter=args.chain, db_path=Path(args.db))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
