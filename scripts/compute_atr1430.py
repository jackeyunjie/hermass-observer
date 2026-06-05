#!/usr/bin/env python3
"""Compute ATR14/ATR30 composite indicator from CSV or Foundation DB bars."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.indicators.atr1430 import ATR1430Config, compute_atr1430  # noqa: E402


def read_foundation_bars(db_path: Path, stock_code: str, timeframe: str, limit: int | None) -> pd.DataFrame:
    import duckdb

    timeframe_value = timeframe.upper()
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        if timeframe_value == "D1":
            sql = """
                SELECT stock_code, date AS period_start, date AS period_end,
                       open, high, low, close, volume, amount
                FROM daily_bars
                WHERE stock_code = ?
                ORDER BY date
            """
            params = [stock_code]
        else:
            sql = """
                SELECT stock_code, timeframe, period_start, period_end,
                       open, high, low, close, volume, amount
                FROM timeframe_bars
                WHERE stock_code = ? AND upper(timeframe) = ?
                ORDER BY period_start
            """
            params = [stock_code, timeframe_value]
        if limit:
            sql = f"SELECT * FROM ({sql}) t ORDER BY period_start DESC LIMIT ?"
            params.append(limit)
            df = con.execute(sql, params).fetchdf().sort_values("period_start")
        else:
            df = con.execute(sql, params).fetchdf()
    finally:
        con.close()
    return df.reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute ATR14/ATR30 buffers.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="CSV input with OHLC columns.")
    source.add_argument("--foundation-db", help="Foundation DuckDB path.")
    parser.add_argument("--stock-code", help="Stock code when using --foundation-db.")
    parser.add_argument("--timeframe", default="D1", help="D1/W1/M30 etc when using --foundation-db.")
    parser.add_argument("--limit", type=int, help="Optional latest bar limit for --foundation-db.")
    parser.add_argument("--output", help="Output CSV path. If omitted, prints tail rows.")
    parser.add_argument("--json-tail", type=int, default=0, help="Print latest N rows as JSON records.")

    parser.add_argument("--atr-short-period", type=int, default=14)
    parser.add_argument("--atr-long-period", type=int, default=30)
    parser.add_argument("--slope-bars", type=int, default=3)
    parser.add_argument("--percentile-lookback", type=int, default=100)
    parser.add_argument("--low-quantile", type=float, default=0.20)
    parser.add_argument("--high-quantile", type=float, default=0.80)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = ATR1430Config(
        atr_short_period=args.atr_short_period,
        atr_long_period=args.atr_long_period,
        slope_bars=args.slope_bars,
        percentile_lookback=args.percentile_lookback,
        low_quantile=args.low_quantile,
        high_quantile=args.high_quantile,
    )

    if args.foundation_db:
        if not args.stock_code:
            raise SystemExit("--stock-code is required with --foundation-db")
        df = read_foundation_bars(Path(args.foundation_db), args.stock_code, args.timeframe, args.limit)
    else:
        df = pd.read_csv(args.input)

    result = compute_atr1430(df, config)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(output, index=False)
        print(f"Wrote {len(result)} rows to {output}")

    tail_count = args.json_tail or (0 if args.output else 5)
    if tail_count:
        tail = result.tail(tail_count).astype(object)
        records = tail.where(pd.notna(tail), None).to_dict(orient="records")
        print(json.dumps(records, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
