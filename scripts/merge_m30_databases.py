#!/usr/bin/env python3
"""Merge multiple daily M30 DuckDB databases into a single database.

Usage:
    python scripts/merge_m30_databases.py --output data/blackwolf_m30_merged/blackwolf_m30.duckdb \
        data/blackwolf_m30_20260526/blackwolf_m30.duckdb \
        data/blackwolf_m30_20260527/blackwolf_m30.duckdb \
        ...
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb


def merge_m30_databases(input_dbs: list[Path], output_db: Path) -> dict:
    """Merge multiple M30 DuckDB files into one."""
    output_db.parent.mkdir(parents=True, exist_ok=True)
    if output_db.exists():
        output_db.unlink()

    conn = duckdb.connect(str(output_db))
    conn.execute("""
        CREATE TABLE m30_bars (
            stock_code VARCHAR,
            period_start TIMESTAMP,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            amount DOUBLE,
            bar_date DATE
        )
    """)

    total_rows = 0
    total_stocks = set()
    total_dates = set()

    for db_path in input_dbs:
        if not db_path.exists():
            print(f"Warning: {db_path} not found, skipping")
            continue

        try:
            conn.execute(f"ATTACH '{str(db_path).replace(chr(39), chr(39)+chr(39))}' AS src (READ_ONLY)")
            result = conn.execute("""
                INSERT INTO m30_bars
                SELECT stock_code, period_start, open, high, low, close, volume, amount, bar_date
                FROM src.m30_bars
            """).fetchdf()
            conn.execute("DETACH src")

            # Count what we just added
            conn.execute(f"ATTACH '{str(db_path).replace(chr(39), chr(39)+chr(39))}' AS src (READ_ONLY)")
            stats = conn.execute("""
                SELECT COUNT(*) as rc, COUNT(DISTINCT stock_code) as sc, COUNT(DISTINCT bar_date) as dc
                FROM src.m30_bars
            """).fetchdf().iloc[0]
            conn.execute("DETACH src")

            rc = int(stats["rc"])
            sc = int(stats["sc"])
            dc = int(stats["dc"])
            total_rows += rc
            print(f"  {db_path.name}: {rc} rows, {sc} stocks, {dc} dates")
        except Exception as e:
            print(f"Error processing {db_path}: {e}")
            continue

    # Create indexes
    conn.execute("CREATE INDEX idx_m30_stock_date ON m30_bars(stock_code, bar_date)")
    conn.execute("CREATE INDEX idx_m30_period ON m30_bars(stock_code, period_start)")

    # Final stats
    final = conn.execute("""
        SELECT
            COUNT(*) as row_count,
            COUNT(DISTINCT stock_code) as stock_count,
            COUNT(DISTINCT bar_date) as date_count,
            MIN(bar_date) as earliest_date,
            MAX(bar_date) as latest_date
        FROM m30_bars
    """).fetchdf().to_dict("records")[0]

    conn.close()

    return {
        "output_db": str(output_db),
        "total_rows": int(final["row_count"]),
        "stock_count": int(final["stock_count"]),
        "date_count": int(final["date_count"]),
        "earliest_date": str(final["earliest_date"]),
        "latest_date": str(final["latest_date"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge M30 DuckDB databases")
    parser.add_argument("input_dbs", nargs="+", type=Path, help="Input DuckDB files")
    parser.add_argument("--output", "-o", type=Path, required=True, help="Output merged DuckDB")
    args = parser.parse_args()

    result = merge_m30_databases(args.input_dbs, args.output)
    print(f"\nMerged: {result['total_rows']} rows, {result['stock_count']} stocks, {result['date_count']} dates")
    print(f"Date range: {result['earliest_date']} to {result['latest_date']}")
    print(f"Output: {result['output_db']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
