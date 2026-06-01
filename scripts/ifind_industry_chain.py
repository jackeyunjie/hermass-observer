#!/usr/bin/env python3
"""iFind Industry Chain Agent — 产业链动态证据。

消费 iFinD 智能体广场：
  - 算力行业头部公司动态跟踪助手
  - 行业深度资料/行业中心
  - 产业链上下游/供需分析

输出：
  outputs/industry_chain/industry_chain_evidence.duckdb
    - chain_dynamics        产业链动态
    - industry_position     行业定位（与 fundamental_profile 互补）
    - macro_chain_cross     宏观 × 产业链交叉

用法：
  python3 scripts/ifind_industry_chain.py --date 2026-05-21
  python3 scripts/ifind_industry_chain.py --date 2026-05-21 --import-json /path/to/industry_export.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
CHAIN_DB = ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"
SCHEMA_VERSION = "industry_chain_evidence_v1"


def ymd(d: str) -> str:
    return d.replace("-", "")


CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS chain_dynamics (
        dynamic_id       VARCHAR    PRIMARY KEY,
        industry         VARCHAR    NOT NULL,
        chain_node       VARCHAR,
        event_date       VARCHAR    NOT NULL,
        event_type       VARCHAR    NOT NULL,
        title            VARCHAR,
        summary          VARCHAR,
        companies_affected VARCHAR,
        supply_demand    VARCHAR,
        catalyst_type    VARCHAR,
        source_agent     VARCHAR,
        raw_json         VARCHAR,
        collected_at     VARCHAR    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS industry_position (
        stock_code       VARCHAR    NOT NULL,
        industry         VARCHAR    NOT NULL,
        chain_node       VARCHAR    DEFAULT 'unknown',
        node_rank        INTEGER,
        node_peers       INTEGER,
        value_add        VARCHAR,
        upstream_dependency VARCHAR,
        downstream_reach VARCHAR,
        moat_description VARCHAR,
        source_agent     VARCHAR,
        collected_at     VARCHAR    NOT NULL,
        PRIMARY KEY (stock_code, industry)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chain_event_cross (
        stock_code       VARCHAR    NOT NULL,
        as_of_date       VARCHAR    NOT NULL,
        ef_count         INTEGER,
        chain_events     INTEGER,
        latest_chain_event VARCHAR,
        chain_catalyst   VARCHAR,
        PRIMARY KEY (stock_code, as_of_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chain_run_log (
        run_id           VARCHAR    PRIMARY KEY,
        run_date         VARCHAR    NOT NULL,
        dynamics_imported INTEGER,
        positions_imported INTEGER,
        cross_count      INTEGER,
        source           VARCHAR,
        error            VARCHAR,
        finished_at      VARCHAR
    )
    """,
]


def init_schema(db_path: Path | None = None) -> Path:
    db_path = db_path or CHAIN_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    for stmt in CREATE_STATEMENTS:
        con.execute(stmt)
    con.execute("CREATE TABLE IF NOT EXISTS schema_info (schema_version VARCHAR, created_at VARCHAR)")
    con.execute("DELETE FROM schema_info")
    con.execute(
        "INSERT INTO schema_info VALUES (?, ?)", (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat())
    )
    con.close()
    return db_path


def import_chain_export(
    con: duckdb.DuckDBPyConnection, json_path: Path, date_str: str, collected_at: str
) -> dict[str, int]:
    if not json_path.exists():
        return {"dynamics": 0, "positions": 0}

    data = json.loads(json_path.read_text(encoding="utf-8"))
    dynamics_count = 0
    positions_count = 0

    for item in data.get("chain_dynamics", []):
        did = f"chain_{item.get('industry', '')}_{date_str}_{dynamics_count}"
        try:
            con.execute(
                """
                INSERT OR IGNORE INTO chain_dynamics
                (dynamic_id, industry, chain_node, event_date, event_type, title,
                 summary, companies_affected, supply_demand, catalyst_type,
                 source_agent, raw_json, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    did,
                    item.get("industry", ""),
                    item.get("chain_node"),
                    item.get("date", date_str),
                    item.get("type", "industry_update"),
                    item.get("title", ""),
                    item.get("summary", ""),
                    item.get("companies", ""),
                    item.get("supply_demand"),
                    item.get("catalyst_type"),
                    item.get("source_agent", "算力行业头部公司动态跟踪助手"),
                    json.dumps(item, ensure_ascii=False)[:3000],
                    collected_at,
                ),
            )
            dynamics_count += 1
        except Exception:
            pass

    for item in data.get("industry_positions", []):
        try:
            con.execute(
                """
                INSERT OR REPLACE INTO industry_position
                (stock_code, industry, chain_node, node_rank, node_peers,
                 value_add, upstream_dependency, downstream_reach, moat_description, source_agent, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    item.get("stock_code", ""),
                    item.get("industry", ""),
                    item.get("chain_node", "unknown"),
                    item.get("node_rank"),
                    item.get("node_peers"),
                    item.get("value_add"),
                    item.get("upstream"),
                    item.get("downstream"),
                    item.get("moat", ""),
                    item.get("source_agent", "行业深度资料"),
                    collected_at,
                ),
            )
            positions_count += 1
        except Exception:
            pass

    return {"dynamics": dynamics_count, "positions": positions_count}


def cross_with_pool(con: duckdb.DuckDBPyConnection, date_str: str) -> int:
    y = ymd(date_str)
    pool_path = ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_{y}.json"
    if not pool_path.exists():
        return 0

    pool_data = json.loads(pool_path.read_text(encoding="utf-8"))
    code_to_ef = {}
    for row in pool_data.get("rows", []):
        code = row.get("symbol") or row.get("stock_code", "")
        if code and row.get("ef_count", 0) >= 2:
            code_to_ef[code] = row.get("ef_count", 2)

    count = 0
    for code, ef in code_to_ef.items():
        chain_events = con.execute(
            "SELECT COUNT(*) FROM chain_dynamics WHERE companies_affected LIKE ?", (f"%{code}%",)
        ).fetchone()[0]

        latest = con.execute(
            """
            SELECT title, catalyst_type FROM chain_dynamics
            WHERE companies_affected LIKE ? AND event_date = ?
            ORDER BY dynamic_id LIMIT 1
        """,
            (f"%{code}%", date_str),
        ).fetchone()

        con.execute(
            """
            INSERT OR REPLACE INTO chain_event_cross
            (stock_code, as_of_date, ef_count, chain_events, latest_chain_event, chain_catalyst)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                code,
                date_str,
                ef,
                chain_events,
                f"{latest[1]}: {latest[0]}" if latest else "无",
                latest[1] if latest else None,
            ),
        )
        count += 1

    return count


def run(date_str: str, import_json: str | None = None) -> dict:
    collected_at = datetime.now(timezone.utc).isoformat()
    run_id = f"chain_agent_{ymd(date_str)}"

    db_path = init_schema()
    con = duckdb.connect(str(db_path))

    dynamics = 0
    positions = 0
    if import_json:
        result = import_chain_export(con, Path(import_json), date_str, collected_at)
        dynamics = result["dynamics"]
        positions = result["positions"]

    cross_count = cross_with_pool(con, date_str)

    con.execute(
        """
        INSERT OR REPLACE INTO chain_run_log
        (run_id, run_date, dynamics_imported, positions_imported, cross_count, source, finished_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            run_id,
            date_str,
            dynamics,
            positions,
            cross_count,
            import_json or "no_import",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    con.close()

    return {
        "schema_version": SCHEMA_VERSION,
        "date": date_str,
        "dynamics_imported": dynamics,
        "positions_imported": positions,
        "pool_cross": cross_count,
        "db": str(db_path),
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="iFind Industry Chain Agent")
    parser.add_argument("--date", required=True)
    parser.add_argument("--import-json", help="Path to iFind Agent exported JSON")
    args = parser.parse_args()

    result = run(args.date, args.import_json)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
