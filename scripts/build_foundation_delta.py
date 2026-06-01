#!/usr/bin/env python3
"""Build a small daily delta package from the full Foundation DuckDB."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DELTA_TABLES = {
    "daily_bars": "date = CAST(? AS DATE)",
    "weekly_bars": "period_start = CAST(date_trunc('week', CAST(? AS DATE)) AS DATE)",
    "monthly_bars": "period_start = CAST(date_trunc('month', CAST(? AS DATE)) AS DATE)",
    "timeframe_bars": "period_start IN (CAST(? AS DATE), CAST(date_trunc('week', CAST(? AS DATE)) AS DATE), CAST(date_trunc('month', CAST(? AS DATE)) AS DATE))",
    "sr_levels": "period_start IN (CAST(? AS DATE), CAST(date_trunc('week', CAST(? AS DATE)) AS DATE), CAST(date_trunc('month', CAST(? AS DATE)) AS DATE))",
    "timeframe_indicators": "period_start IN (CAST(? AS DATE), CAST(date_trunc('week', CAST(? AS DATE)) AS DATE), CAST(date_trunc('month', CAST(? AS DATE)) AS DATE))",
    "d1_d_sr": "state_date = CAST(? AS DATE)",
    "d1_w_sr": "state_date = CAST(? AS DATE)",
    "d1_mn1_sr": "state_date = CAST(? AS DATE)",
    "d1_sr_context": "state_date = CAST(? AS DATE)",
    "d1_perspective_state": "state_date = CAST(? AS DATE)",
}


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def default_foundation_db(date_str: str) -> Path:
    return ROOT / "outputs" / f"p116_foundation_{ymd(date_str)}" / "p116_foundation.duckdb"


def default_delta_db(date_str: str) -> Path:
    return ROOT / "outputs" / f"foundation_delta_{ymd(date_str)}" / "foundation_delta.duckdb"


def build_delta(source_db: Path, out_db: Path, date_str: str) -> dict:
    if not source_db.exists():
        raise FileNotFoundError(source_db)

    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()

    con = duckdb.connect(str(out_db))
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"ATTACH '{sql_path(source_db)}' AS src (READ_ONLY)")

    summary: dict[str, object] = {
        "schema_version": "foundation_delta_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "date": date_str,
        "source_db": str(source_db),
        "output_db": str(out_db),
        "tables": {},
    }

    for table, where_sql in DELTA_TABLES.items():
        param_count = where_sql.count("?")
        con.execute(
            f"""
            CREATE TABLE {table} AS
            SELECT *
            FROM src.{table}
            WHERE {where_sql}
            """,
            [date_str] * param_count,
        )
        count = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        summary["tables"][table] = {"where": where_sql, "rows": count}

    con.execute(
        """
        CREATE TABLE foundation_delta_manifest AS
        SELECT
          ? AS schema_version,
          ? AS generated_at,
          ? AS date,
          ? AS source_db,
          ? AS output_db,
          ? AS manifest_json
        """,
        [
            summary["schema_version"],
            summary["generated_at"],
            date_str,
            str(source_db),
            str(out_db),
            json.dumps(summary, ensure_ascii=False, default=str),
        ],
    )
    con.close()

    summary_path = out_db.parent / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a daily Foundation delta DuckDB.")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--source-db", type=Path)
    parser.add_argument("--out-db", type=Path)
    args = parser.parse_args()

    date_str = args.date
    if len(date_str) == 8 and "-" not in date_str:
        date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

    source_db = args.source_db or default_foundation_db(date_str)
    out_db = args.out_db or default_delta_db(date_str)
    summary = build_delta(source_db, out_db, date_str)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
