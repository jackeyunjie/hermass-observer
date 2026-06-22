#!/usr/bin/env python3
"""Backfill per-stock decision observations for historical state dates.

Uses state_cube future_r5/future_r20 to evaluate each stock's 6-Agent score.
Produces a stock-level track record for the debate_dashboard per-stock card.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb

from scripts import decision_observation_ledger as ledger
from scripts.agent_debate_runner import (
    _market_aggregates,
    _per_stock_score,
    _query_cube,
)


def backfill(start_date: str | None = None, end_date: str | None = None, recent_days: int = 90) -> dict:
    """Backfill per-stock observations across dates with available future returns."""
    state_cube = ROOT / "outputs" / "state_cube" / "state_cube.duckdb"
    con = duckdb.connect(str(state_cube), read_only=True)

    if not start_date and not end_date:
        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=recent_days)).isoformat()

    sql = """
        SELECT DISTINCT state_date
        FROM state_cube
        WHERE future_r5 IS NOT NULL
    """
    params = []
    if start_date:
        sql += " AND state_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND state_date <= ?"
        params.append(end_date)
    sql += " ORDER BY state_date"
    rows = con.execute(sql, params).fetchall()
    con.close()

    dates = [str(r[0]) for r in rows]
    print(f"[backfill] {len(dates)} dates to process: {dates[0] if dates else 'N/A'} .. {dates[-1] if dates else 'N/A'}")

    records: list[dict] = []
    for state_date in dates:
        try:
            market = _market_aggregates(state_date)
            stocks = _query_cube(
                state_date, where="ef_count >= 2 AND d1_close > 5", limit=50
            )
            as_of = date.fromisoformat(state_date)
            for stock in stocks:
                score = _per_stock_score(stock, market)
                record = ledger._build_per_stock_observation_record(
                    score,
                    as_of,
                    stock.get("future_r5"),
                    stock.get("future_r20"),
                )
                records.append(record)
        except Exception as exc:
            print(f"[backfill] failed for {state_date}: {exc}")

    result = ledger.batch_write_per_stock_observations(records, replace_hypothesis=True)
    written = result.get("record_count", 0)
    print(f"[backfill] wrote {written} per-stock observations")

    report = ledger.generate_per_stock_observation_report()
    print(
        f"[backfill] report: records={report.get('record_count')} "
        f"observe={report.get('observe_count')} watch={report.get('watch_count')} reject={report.get('reject_count')}"
    )
    return report


def main() -> int:
    from argparse import ArgumentParser

    parser = ArgumentParser(description="Backfill per-stock observation ledger")
    parser.add_argument("--start", type=str, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", type=str, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--recent-days", type=int, default=90, help="默认回填最近 N 个自然日")
    args = parser.parse_args()

    backfill(start_date=args.start, end_date=args.end, recent_days=args.recent_days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
