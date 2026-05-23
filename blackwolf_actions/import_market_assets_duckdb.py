#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "outputs" / "market_assets" / "market_assets.duckdb"
DEFAULT_DATA_DIR = ROOT / "data" / "blackwolf_market_assets"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def fnum(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS market_asset_daily (
            symbol VARCHAR NOT NULL,
            name VARCHAR,
            asset_type VARCHAR,
            sw_l1 VARCHAR,
            benchmark_group VARCHAR,
            date DATE NOT NULL,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            amount DOUBLE,
            source_csv VARCHAR,
            imported_at TIMESTAMP,
            PRIMARY KEY (symbol, date)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS market_asset_import_log (
            date DATE,
            source_csv VARCHAR,
            csv_row_count BIGINT,
            imported_rows BIGINT,
            imported_at TIMESTAMP
        )
        """
    )


def load_rows(csv_path: Path) -> list[dict[str, Any]]:
    imported_at = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if not row.get("symbol") or not row.get("date"):
                continue
            rows.append(
                {
                    "symbol": row.get("symbol"),
                    "name": row.get("name", ""),
                    "asset_type": row.get("asset_type", ""),
                    "sw_l1": row.get("sw_l1", ""),
                    "benchmark_group": row.get("benchmark_group", ""),
                    "date": row.get("date"),
                    "open": fnum(row.get("open")),
                    "high": fnum(row.get("high")),
                    "low": fnum(row.get("low")),
                    "close": fnum(row.get("close")),
                    "volume": fnum(row.get("volume")),
                    "amount": fnum(row.get("amount")),
                    "source_csv": str(csv_path),
                    "imported_at": imported_at,
                }
            )
    return rows


FIELDS = [
    "symbol",
    "name",
    "asset_type",
    "sw_l1",
    "benchmark_group",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "source_csv",
    "imported_at",
]


def import_market_assets(date_str: str, csv_path: Path | None, db_path: Path) -> dict[str, Any]:
    if csv_path is None:
        csv_path = DEFAULT_DATA_DIR / f"blackwolf_market_assets_{ymd(date_str)}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    csv_rows = max(0, sum(1 for _ in csv_path.open(encoding="utf-8-sig")) - 1)
    rows = load_rows(csv_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM market_asset_daily WHERE date = CAST(? AS DATE)", [date_str])
        if rows:
            con.executemany(
                "INSERT INTO market_asset_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [[row[field] for field in FIELDS] for row in rows],
            )
        con.execute(
            "INSERT INTO market_asset_import_log VALUES (CAST(? AS DATE), ?, ?, ?, ?)",
            [date_str, str(csv_path), csv_rows, len(rows), datetime.now(timezone.utc).replace(tzinfo=None)],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    coverage = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT date), MIN(date), MAX(date) FROM market_asset_daily"
    ).fetchone()
    con.close()
    result = {
        "schema_version": "market_assets_duckdb_import_v1",
        "date": date_str,
        "db": str(db_path),
        "source_csv": str(csv_path),
        "csv_rows": csv_rows,
        "imported_rows": len(rows),
        "database_total_rows": coverage[0],
        "database_date_count": coverage[1],
        "database_min_date": str(coverage[2]) if coverage[2] is not None else None,
        "database_max_date": str(coverage[3]) if coverage[3] is not None else None,
    }
    summary_dir = ROOT / "reports" / "blackwolf_actions" / "market_assets"
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_dir / f"market_assets_import_{ymd(date_str)}.json"
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**result, "summary": str(summary_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Import market index/industry ETF bars into DuckDB.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    print(json.dumps(import_market_assets(args.date, args.csv, args.db), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
