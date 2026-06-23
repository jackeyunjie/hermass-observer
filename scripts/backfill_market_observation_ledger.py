#!/usr/bin/env python3
"""Backfill market-level decision observations for historical state dates.

Uses state_cube future_r5/future_r20 to evaluate the daily market call.
This produces a track record for the debate_dashboard market-timing card.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import decision_observation_ledger as ledger
from scripts.agent_debate_runner import (
    _boundary_opinion,
    _market_aggregates,
    _market_opinion,
    _momentum_opinion,
    _query_cube,
    _risk_opinion,
    _trend_opinion,
    _volatility_opinion,
)
from scripts.dynamic_weight_router import (
    compute_final_verdict,
    compute_weights,
    detect_conflicts,
    detect_resonances,
)


def build_debate_for_date(state_date: str) -> dict:
    """Rebuild the market-level debate output for a specific state_date."""
    market = _market_aggregates(state_date)
    top_stocks = _query_cube(
        state_date, where="ef_count >= 2 AND d1_close > 5", limit=50
    )
    opinions = [
        _market_opinion(market),
        _trend_opinion(top_stocks, market),
        _momentum_opinion(top_stocks, market),
        _volatility_opinion(top_stocks, market),
        _boundary_opinion(top_stocks, market),
        _risk_opinion(top_stocks, market),
    ]
    return {
        "generated_at": state_date,
        "state_date": state_date,
        "cube_stocks": market["total_stocks"],
        "market_summary": market,
        "sample_stocks": len(top_stocks),
        "opinions": opinions,
    }


def build_router_for_date(debate: dict) -> dict:
    """Rebuild the router verdict for a specific debate output."""
    opinions = debate.get("opinions", [])
    market = debate.get("market_summary", {})
    weights = compute_weights(opinions, market)
    conflicts = detect_conflicts(opinions)
    resonances = detect_resonances(opinions)
    verdict = compute_final_verdict(opinions, weights, conflicts, resonances, market=market)
    return {
        "generated_at": debate["state_date"],
        "weights": weights,
        "conflicts": conflicts,
        "resonances": resonances,
        "verdict": verdict,
    }


def backfill(start_date: str | None = None, end_date: str | None = None) -> dict:
    """Backfill market observations across dates with available future returns."""
    import duckdb

    state_cube = ROOT / "outputs" / "state_cube" / "state_cube.duckdb"
    con = duckdb.connect(str(state_cube), read_only=True)
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
    print(f"[backfill] {len(dates)} dates to process: {dates[0]} .. {dates[-1]}")

    records: list[dict] = []
    for state_date in dates:
        try:
            debate = build_debate_for_date(state_date)
            router = build_router_for_date(debate)
            as_of = date.fromisoformat(state_date)
            record = ledger._build_market_observation_record(as_of, debate, router)
            records.append(record)
        except Exception as exc:
            print(f"[backfill] failed for {state_date}: {exc}")

    result = ledger.batch_write_market_observations(records, replace_hypothesis=True)
    written = result.get("record_count", 0)
    print(f"[backfill] wrote {written} market observations")
    report = ledger.generate_market_observation_report()
    print(
        f"[backfill] total records={report['record_count']} "
        f"overall_hit_rate={report.get('overall_hit_rate', 0):.2%} "
        f"evaluated={report.get('evaluated_count', 0)}"
    )
    return report


def main() -> int:
    from argparse import ArgumentParser
    from datetime import timedelta

    parser = ArgumentParser(description="Backfill market observation ledger")
    parser.add_argument("--start", type=str, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", type=str, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--recent-days", type=int, default=90, help="默认回填最近 N 个自然日")
    args = parser.parse_args()

    start = args.start
    end = args.end
    if not start and not end:
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=args.recent_days)).isoformat()

    backfill(start_date=start, end_date=end)
    return 0


if __name__ == "__main__":
    sys.exit(main())
