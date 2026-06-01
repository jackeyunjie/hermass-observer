#!/usr/bin/env python3
"""Build monthly bars from daily bars via DuckDB aggregation.

A 股月线 K 线聚合规则：
- month_start_date = 该月第一个交易日（1日或节假日后的第一个交易日）
- month_end_date = 该月最后一个交易日
- open = 月第一个交易日的开盘价
- high = 月内最高价
- low = 月内最低价
- close = 月最后一个交易日的收盘价
- volume = 月内成交量之和

Usage:
    python3 scripts/build_monthly_bars.py \
        --source-db outputs/p116_foundation_20260522/p116_foundation.duckdb \
        --output-db outputs/monthly_bars/monthly_bars.duckdb
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb


def build_monthly_bars(source_db: Path, output_db: Path) -> dict:
    """Aggregate daily bars into monthly bars."""

    if not source_db.exists():
        raise FileNotFoundError(f"Source DB not found: {source_db}")

    output_db.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(output_db))
    try:
        con.execute(f"ATTACH '{str(source_db).replace(chr(39), chr(39) + chr(39))}' AS src (READ_ONLY)")

        con.execute("DROP TABLE IF EXISTS monthly_bars")
        con.execute("""
            CREATE TABLE monthly_bars (
                stock_code VARCHAR,
                month_start_date DATE,
                month_end_date DATE,
                available_date DATE,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                amount DOUBLE,
                source_bar_count BIGINT
            )
        """)

        con.execute("""
            INSERT INTO monthly_bars
            WITH month_groups AS (
                SELECT
                    stock_code,
                    date_trunc('month', date)::DATE AS month_start_date,
                    date AS trade_date,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    amount,
                    ROW_NUMBER() OVER (
                        PARTITION BY stock_code, date_trunc('month', date)::DATE
                        ORDER BY date
                    ) AS rn_asc,
                    ROW_NUMBER() OVER (
                        PARTITION BY stock_code, date_trunc('month', date)::DATE
                        ORDER BY date DESC
                    ) AS rn_desc
                FROM src.daily_bars
            )
            SELECT
                stock_code,
                month_start_date,
                MAX(trade_date) AS month_end_date,
                MAX(trade_date) AS available_date,
                MAX(CASE WHEN rn_asc = 1 THEN open END) AS open,
                MAX(high) AS high,
                MIN(low) AS low,
                MAX(CASE WHEN rn_desc = 1 THEN close END) AS close,
                SUM(volume) AS volume,
                SUM(amount) AS amount,
                COUNT(*) AS source_bar_count
            FROM month_groups
            GROUP BY stock_code, month_start_date
            ORDER BY stock_code, month_start_date
        """)

        row = con.execute("""
            SELECT
                COUNT(DISTINCT stock_code),
                MIN(month_start_date),
                MAX(month_end_date),
                COUNT(*)
            FROM monthly_bars
        """).fetchone()

        return {
            "ok": True,
            "source_db": str(source_db),
            "output_db": str(output_db),
            "tickers": row[0],
            "min_month": str(row[1]),
            "max_month": str(row[2]),
            "total_months": row[3],
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build monthly bars from daily bars")
    parser.add_argument(
        "--source-db",
        type=Path,
        default=Path("outputs/p116_foundation_20260522/p116_foundation.duckdb"),
        help="Source daily bars DuckDB",
    )
    parser.add_argument(
        "--output-db",
        type=Path,
        default=Path("outputs/monthly_bars/monthly_bars.duckdb"),
        help="Output monthly bars DuckDB",
    )
    args = parser.parse_args()

    result = build_monthly_bars(args.source_db, args.output_db)
    print(f"✅ Monthly bars built: {result['total_months']:,} months, {result['tickers']:,} tickers")
    print(f"   Range: {result['min_month']} ~ {result['max_month']}")
    print(f"   Output: {result['output_db']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
