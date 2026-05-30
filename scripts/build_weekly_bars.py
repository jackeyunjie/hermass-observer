#!/usr/bin/env python3
"""Build weekly bars from daily bars via DuckDB aggregation.

A 股周线 K 线聚合规则：
- week_start_date = 该周第一个交易日（通常是周一，节假日顺延）
- week_end_date = 该周最后一个交易日（通常是周五，节假日前提前结束）
- open = 周第一个交易日的开盘价
- high = 周内最高价
- low = 周内最低价
- close = 周最后一个交易日的收盘价
- volume = 周内成交量之和

Usage:
    python3 scripts/build_weekly_bars.py \
        --source-db outputs/p116_foundation_20260522/p116_foundation.duckdb \
        --output-db outputs/weekly_bars/weekly_bars.duckdb
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb


def build_weekly_bars(source_db: Path, output_db: Path) -> dict:
    """Aggregate daily bars into weekly bars."""

    if not source_db.exists():
        raise FileNotFoundError(f"Source DB not found: {source_db}")

    output_db.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(output_db))
    try:
        con.execute(f"ATTACH '{str(source_db).replace(chr(39), chr(39)+chr(39))}' AS src (READ_ONLY)")

        # Create table
        con.execute("""
            CREATE TABLE IF NOT EXISTS weekly_bars (
                stock_code VARCHAR,
                week_start_date DATE,
                week_end_date DATE,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE
            )
        """)

        # Clear existing data if source DB changes
        con.execute("DELETE FROM weekly_bars")

        # Aggregate: daily -> weekly
        con.execute("""
            INSERT INTO weekly_bars
            WITH week_groups AS (
                SELECT
                    stock_code,
                    date_trunc('week', date)::DATE AS week_start_date,
                    date AS trade_date,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    ROW_NUMBER() OVER (
                        PARTITION BY stock_code, date_trunc('week', date)::DATE
                        ORDER BY date
                    ) AS rn_asc,
                    ROW_NUMBER() OVER (
                        PARTITION BY stock_code, date_trunc('week', date)::DATE
                        ORDER BY date DESC
                    ) AS rn_desc
                FROM src.daily_bars
            )
            SELECT
                stock_code,
                week_start_date,
                MAX(trade_date) AS week_end_date,
                MAX(CASE WHEN rn_asc = 1 THEN open END) AS open,
                MAX(high) AS high,
                MIN(low) AS low,
                MAX(CASE WHEN rn_desc = 1 THEN close END) AS close,
                SUM(volume) AS volume
            FROM week_groups
            GROUP BY stock_code, week_start_date
            ORDER BY stock_code, week_start_date
        """)

        # Stats
        row = con.execute("""
            SELECT
                COUNT(DISTINCT stock_code),
                MIN(week_start_date),
                MAX(week_end_date),
                COUNT(*)
            FROM weekly_bars
        """).fetchone()

        return {
            "ok": True,
            "source_db": str(source_db),
            "output_db": str(output_db),
            "tickers": row[0],
            "min_week": str(row[1]),
            "max_week": str(row[2]),
            "total_weeks": row[3],
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build weekly bars from daily bars")
    parser.add_argument(
        "--source-db",
        type=Path,
        default=Path("outputs/p116_foundation_20260522/p116_foundation.duckdb"),
        help="Source daily bars DuckDB",
    )
    parser.add_argument(
        "--output-db",
        type=Path,
        default=Path("outputs/weekly_bars/weekly_bars.duckdb"),
        help="Output weekly bars DuckDB",
    )
    args = parser.parse_args()

    result = build_weekly_bars(args.source_db, args.output_db)
    print(f"✅ Weekly bars built: {result['total_weeks']:,} weeks, {result['tickers']:,} tickers")
    print(f"   Range: {result['min_week']} ~ {result['max_week']}")
    print(f"   Output: {result['output_db']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
