#!/usr/bin/env python3
"""Build the State Cube: multi-timeframe, multi-indicator state panorama.

For every (stock_code, date), generates a single row containing:
  - Hermass States (MN1/W1/D1 state_hex)
  - MA States (144/169/200 on W1/D1)
  - BB20/BB50 position & width states
  - ATR/ADX context
  - Future returns (for training/evaluation)

This is the input tensor for the Agent Debate network.

Usage:
    python3 scripts/build_state_cube.py \
        --foundation outputs/p116_foundation_20260602/p116_foundation.duckdb \
        --output outputs/state_cube/state_cube.duckdb \
        --min-date 2020-01-01
"""

import argparse
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent

# ── SQL: W1 state calculations ────────────────────────────────────────

W1_STATES_SQL = """
WITH weekly_bars AS (
    SELECT
        stock_code,
        period_start,
        period_end,
        available_date AS state_date,
        open, high, low, close
    FROM foundation.timeframe_bars
    WHERE timeframe = 'W1'
),
weekly_ma AS (
    SELECT
        stock_code, period_start, period_end, state_date, close,
        AVG(close) OVER w144 AS ma144,
        AVG(close) OVER w169 AS ma169,
        AVG(close) OVER w200 AS ma200
    FROM weekly_bars
    WINDOW
        w144 AS (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 143 PRECEDING AND CURRENT ROW),
        w169 AS (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 168 PRECEDING AND CURRENT ROW),
        w200 AS (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW)
),
weekly_ma_states AS (
    SELECT
        stock_code, period_start, period_end, state_date,
        CASE
            WHEN ma144 > 0 AND ma169 > 0 AND ma200 > 0
                 AND ABS(ma144 - ma169) / ma169 < 0.02
                 AND ABS(ma169 - ma200) / ma200 < 0.02
                THEN 'W7'
            WHEN LAG(ma144) OVER (PARTITION BY stock_code ORDER BY state_date) IS NOT NULL
                 AND LAG(ma169) OVER (PARTITION BY stock_code ORDER BY state_date) IS NOT NULL
                 AND (
                     (ma144 > ma169 AND LAG(ma144) OVER (PARTITION BY stock_code ORDER BY state_date) <= LAG(ma169) OVER (PARTITION BY stock_code ORDER BY state_date))
                     OR (ma144 < ma169 AND LAG(ma144) OVER (PARTITION BY stock_code ORDER BY state_date) >= LAG(ma169) OVER (PARTITION BY stock_code ORDER BY state_date))
                 )
                THEN 'W8'
            WHEN ma144 > ma169 AND ma169 > ma200 THEN 'W1'
            WHEN ma144 > ma200 AND ma200 > ma169 THEN 'W2'
            WHEN ma169 > ma144 AND ma144 > ma200 THEN 'W3'
            WHEN ma169 > ma200 AND ma200 > ma144 THEN 'W4'
            WHEN ma200 > ma144 AND ma144 > ma169 THEN 'W5'
            WHEN ma200 > ma169 AND ma169 > ma144 THEN 'W6'
            ELSE NULL
        END AS ma_state
    FROM weekly_ma
    WHERE ma144 > 0 AND ma169 > 0 AND ma200 > 0
),
weekly_bb50 AS (
    SELECT
        stock_code, period_start, period_end, state_date, close,
        AVG(close) OVER w50 AS bb50_middle,
        STDDEV_SAMP(close) OVER w50 AS bb50_std
    FROM weekly_bars
    WINDOW w50 AS (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW)
),
weekly_bb50_states AS (
    SELECT
        stock_code, period_start, period_end, state_date,
        CASE
            WHEN bb50_std IS NULL OR bb50_middle IS NULL THEN NULL
            WHEN close > bb50_middle + 2 * bb50_std THEN 'above_upper'
            WHEN close < bb50_middle - 2 * bb50_std THEN 'below_lower'
            WHEN close > bb50_middle THEN 'above_middle'
            WHEN close < bb50_middle THEN 'below_middle'
            ELSE 'at_middle'
        END AS bb50_position
    FROM weekly_bb50
),
weekly_indicators AS (
    SELECT
        stock_code, available_date AS state_date,
        bb_middle_20, bb_std_20,
        bb_width_pct, bb_width_expanding, bb_width_squeeze_on,
        atr14, adx14, plus_di_14, minus_di_14,
        close
    FROM foundation.timeframe_indicators
    WHERE timeframe = 'W1'
),
weekly_bb20_states AS (
    SELECT
        stock_code, state_date,
        CASE
            WHEN bb_std_20 IS NULL OR bb_middle_20 IS NULL THEN NULL
            WHEN close > bb_middle_20 + 2 * bb_std_20 THEN 'above_upper'
            WHEN close < bb_middle_20 - 2 * bb_std_20 THEN 'below_lower'
            WHEN close > bb_middle_20 THEN 'above_middle'
            WHEN close < bb_middle_20 THEN 'below_middle'
            ELSE 'at_middle'
        END AS bb20_position,
        CASE
            WHEN bb_width_squeeze_on THEN 'squeeze'
            WHEN bb_width_expanding THEN 'expanding'
            ELSE 'neutral'
        END AS bb20_width
    FROM weekly_indicators
)
SELECT
    b.stock_code,
    b.period_start,
    b.period_end,
    b.state_date,
    b.close AS w1_close,
    m.ma_state AS w1_ma_state,
    bb20.bb20_position AS w1_bb20_position,
    bb20.bb20_width AS w1_bb20_width,
    bb50.bb50_position AS w1_bb50_position,
    i.atr14 AS w1_atr14,
    i.adx14 AS w1_adx14,
    i.plus_di_14 AS w1_plus_di_14,
    i.minus_di_14 AS w1_minus_di_14
FROM weekly_bars b
LEFT JOIN weekly_ma_states m
    ON b.stock_code = m.stock_code AND b.state_date = m.state_date
LEFT JOIN weekly_bb20_states bb20
    ON b.stock_code = bb20.stock_code AND b.state_date = bb20.state_date
LEFT JOIN weekly_bb50_states bb50
    ON b.stock_code = bb50.stock_code AND b.state_date = bb50.state_date
LEFT JOIN weekly_indicators i
    ON b.stock_code = i.stock_code AND b.state_date = i.state_date
"""

# ── SQL: M30 state calculations (intraday observation) ────────────────

M30_STATES_SQL = """
WITH m30_bars AS (
    SELECT
        stock_code,
        period_start,
        period_end,
        available_date AS state_date,
        open, high, low, close
    FROM foundation.timeframe_bars
    WHERE timeframe = 'M30'
),
m30_last_bar AS (
    SELECT
        stock_code,
        state_date,
        close AS m30_close,
        ROW_NUMBER() OVER (PARTITION BY stock_code, state_date ORDER BY period_start DESC) AS rn
    FROM m30_bars
),
m30_indicators AS (
    SELECT
        stock_code, available_date AS state_date,
        bb_middle_20, bb_std_20,
        bb_width_pct, bb_width_expanding, bb_width_squeeze_on,
        atr14, adx14, plus_di_14, minus_di_14,
        close,
        ROW_NUMBER() OVER (PARTITION BY stock_code, available_date ORDER BY period_start DESC) AS rn
    FROM foundation.timeframe_indicators
    WHERE timeframe = 'M30'
),
m30_indicators_last AS (
    SELECT * FROM m30_indicators WHERE rn = 1
),
m30_bb20_states AS (
    SELECT
        stock_code, state_date,
        CASE
            WHEN bb_std_20 IS NULL OR bb_middle_20 IS NULL THEN NULL
            WHEN close > bb_middle_20 + 2 * bb_std_20 THEN 'above_upper'
            WHEN close < bb_middle_20 - 2 * bb_std_20 THEN 'below_lower'
            WHEN close > bb_middle_20 THEN 'above_middle'
            WHEN close < bb_middle_20 THEN 'below_middle'
            ELSE 'at_middle'
        END AS bb20_position,
        CASE
            WHEN bb_width_squeeze_on THEN 'squeeze'
            WHEN bb_width_expanding THEN 'expanding'
            ELSE 'neutral'
        END AS bb20_width
    FROM m30_indicators_last
)
SELECT DISTINCT
    lb.stock_code,
    lb.state_date,
    lb.m30_close,
    bb20.bb20_position AS m30_bb20_position,
    bb20.bb20_width AS m30_bb20_width,
    i.atr14 AS m30_atr14,
    i.adx14 AS m30_adx14,
    i.plus_di_14 AS m30_plus_di_14,
    i.minus_di_14 AS m30_minus_di_14,
    -- M30 derived placeholders (computed from raw M30 bars; full calc deferred to Phase 2)
    NULL::FLOAT AS m30_adx_slope_3,
    NULL::VARCHAR AS m30_breakout_signal,
    NULL::BOOLEAN AS m30_price_breakout,
    NULL::BOOLEAN AS m30_ma20_ready,
    NULL::VARCHAR AS m30_close_vs_ma20_flag,
    NULL::FLOAT AS m30_intraday_prev_high
FROM m30_last_bar lb
LEFT JOIN m30_bb20_states bb20
    ON lb.stock_code = bb20.stock_code AND lb.state_date = bb20.state_date
LEFT JOIN m30_indicators_last i
    ON lb.stock_code = i.stock_code AND lb.state_date = i.state_date
WHERE lb.rn = 1
"""

# ── SQL: D1 state calculations ────────────────────────────────────────

D1_STATES_SQL = """
WITH daily_bars AS (
    SELECT
        stock_code,
        period_start,
        period_end,
        available_date AS state_date,
        open, high, low, close
    FROM foundation.timeframe_bars
    WHERE timeframe = 'D1'
),
daily_ma AS (
    SELECT
        stock_code, period_start, period_end, state_date, close,
        AVG(close) OVER w144 AS ma144,
        AVG(close) OVER w169 AS ma169,
        AVG(close) OVER w200 AS ma200
    FROM daily_bars
    WINDOW
        w144 AS (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 143 PRECEDING AND CURRENT ROW),
        w169 AS (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 168 PRECEDING AND CURRENT ROW),
        w200 AS (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW)
),
daily_ma_states AS (
    SELECT
        stock_code, period_start, period_end, state_date,
        CASE
            WHEN ma144 > 0 AND ma169 > 0 AND ma200 > 0
                 AND ABS(ma144 - ma169) / ma169 < 0.02
                 AND ABS(ma169 - ma200) / ma200 < 0.02
                THEN 'D7'
            WHEN LAG(ma144) OVER (PARTITION BY stock_code ORDER BY state_date) IS NOT NULL
                 AND LAG(ma169) OVER (PARTITION BY stock_code ORDER BY state_date) IS NOT NULL
                 AND (
                     (ma144 > ma169 AND LAG(ma144) OVER (PARTITION BY stock_code ORDER BY state_date) <= LAG(ma169) OVER (PARTITION BY stock_code ORDER BY state_date))
                     OR (ma144 < ma169 AND LAG(ma144) OVER (PARTITION BY stock_code ORDER BY state_date) >= LAG(ma169) OVER (PARTITION BY stock_code ORDER BY state_date))
                 )
                THEN 'D8'
            WHEN ma144 > ma169 AND ma169 > ma200 THEN 'D1'
            WHEN ma144 > ma200 AND ma200 > ma169 THEN 'D2'
            WHEN ma169 > ma144 AND ma144 > ma200 THEN 'D3'
            WHEN ma169 > ma200 AND ma200 > ma144 THEN 'D4'
            WHEN ma200 > ma144 AND ma144 > ma169 THEN 'D5'
            WHEN ma200 > ma169 AND ma169 > ma144 THEN 'D6'
            ELSE NULL
        END AS ma_state
    FROM daily_ma
    WHERE ma144 > 0 AND ma169 > 0 AND ma200 > 0
),
daily_bb50 AS (
    SELECT
        stock_code, period_start, period_end, state_date, close,
        AVG(close) OVER w50 AS bb50_middle,
        STDDEV_SAMP(close) OVER w50 AS bb50_std
    FROM daily_bars
    WINDOW w50 AS (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW)
),
daily_bb50_states AS (
    SELECT
        stock_code, period_start, period_end, state_date,
        CASE
            WHEN bb50_std IS NULL OR bb50_middle IS NULL THEN NULL
            WHEN close > bb50_middle + 2 * bb50_std THEN 'above_upper'
            WHEN close < bb50_middle - 2 * bb50_std THEN 'below_lower'
            WHEN close > bb50_middle THEN 'above_middle'
            WHEN close < bb50_middle THEN 'below_middle'
            ELSE 'at_middle'
        END AS bb50_position
    FROM daily_bb50
),
daily_indicators AS (
    SELECT
        stock_code, available_date AS state_date,
        bb_middle_20, bb_std_20,
        bb_width_pct, bb_width_expanding, bb_width_squeeze_on,
        atr14, adx14, plus_di_14, minus_di_14,
        close
    FROM foundation.timeframe_indicators
    WHERE timeframe = 'D1'
),
daily_bb20_states AS (
    SELECT
        stock_code, state_date,
        CASE
            WHEN bb_std_20 IS NULL OR bb_middle_20 IS NULL THEN NULL
            WHEN close > bb_middle_20 + 2 * bb_std_20 THEN 'above_upper'
            WHEN close < bb_middle_20 - 2 * bb_std_20 THEN 'below_lower'
            WHEN close > bb_middle_20 THEN 'above_middle'
            WHEN close < bb_middle_20 THEN 'below_middle'
            ELSE 'at_middle'
        END AS bb20_position,
        CASE
            WHEN bb_width_squeeze_on THEN 'squeeze'
            WHEN bb_width_expanding THEN 'expanding'
            ELSE 'neutral'
        END AS bb20_width
    FROM daily_indicators
),
daily_returns AS (
    SELECT
        stock_code, state_date, close,
        LEAD(close, 5) OVER (PARTITION BY stock_code ORDER BY state_date) / close - 1 AS r5,
        LEAD(close, 20) OVER (PARTITION BY stock_code ORDER BY state_date) / close - 1 AS r20
    FROM daily_bars
)
SELECT
    b.stock_code,
    b.period_start,
    b.period_end,
    b.state_date,
    b.close AS d1_close,
    m.ma_state AS d1_ma_state,
    bb20.bb20_position AS d1_bb20_position,
    bb20.bb20_width AS d1_bb20_width,
    bb50.bb50_position AS d1_bb50_position,
    i.atr14 AS d1_atr14,
    i.adx14 AS d1_adx14,
    i.plus_di_14 AS d1_plus_di_14,
    i.minus_di_14 AS d1_minus_di_14,
    r.r5 AS future_r5,
    r.r20 AS future_r20
FROM daily_bars b
LEFT JOIN daily_ma_states m
    ON b.stock_code = m.stock_code AND b.state_date = m.state_date
LEFT JOIN daily_bb20_states bb20
    ON b.stock_code = bb20.stock_code AND b.state_date = bb20.state_date
LEFT JOIN daily_bb50_states bb50
    ON b.stock_code = bb50.stock_code AND b.state_date = bb50.state_date
LEFT JOIN daily_indicators i
    ON b.stock_code = i.stock_code AND b.state_date = i.state_date
LEFT JOIN daily_returns r
    ON b.stock_code = r.stock_code AND b.state_date = r.state_date
"""


def build_cube(foundation_db: Path, output_db: Path, min_date: str):
    """Build state_cube by attaching foundation DB and running join SQL."""
    output_db.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(output_db))
    con.execute(f"ATTACH '{foundation_db}' AS foundation (READ_ONLY)")

    print("Computing W1 states...")
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW w1_states AS
        SELECT * FROM ({W1_STATES_SQL})
    """)

    print("Computing D1 states...")
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW d1_states AS
        SELECT * FROM ({D1_STATES_SQL})
    """)

    print("Computing M30 states...")
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW m30_states AS
        SELECT * FROM ({M30_STATES_SQL})
    """)

    print("Joining into state_cube...")
    con.execute(f"""
        CREATE OR REPLACE TABLE state_cube AS
        SELECT
            h.stock_code,
            h.state_date,

            -- Hermass States
            h.mn1_state_hex,
            h.w1_state_hex,
            h.d1_state_hex,
            h.ef_count,

            -- MA States
            ANY_VALUE(w.w1_ma_state) AS w1_ma_state,
            ANY_VALUE(d1s.d1_ma_state) AS d1_ma_state,

            -- BB20
            ANY_VALUE(w.w1_bb20_position) AS w1_bb20_position,
            ANY_VALUE(w.w1_bb20_width) AS w1_bb20_width,
            ANY_VALUE(d1s.d1_bb20_position) AS d1_bb20_position,
            ANY_VALUE(d1s.d1_bb20_width) AS d1_bb20_width,

            -- BB50
            ANY_VALUE(w.w1_bb50_position) AS w1_bb50_position,
            ANY_VALUE(d1s.d1_bb50_position) AS d1_bb50_position,

            -- ATR/ADX context
            ANY_VALUE(w.w1_atr14) AS w1_atr14,
            ANY_VALUE(d1s.d1_atr14) AS d1_atr14,
            ANY_VALUE(w.w1_adx14) AS w1_adx14,
            ANY_VALUE(d1s.d1_adx14) AS d1_adx14,
            ANY_VALUE(w.w1_plus_di_14) AS w1_plus_di_14,
            ANY_VALUE(d1s.d1_plus_di_14) AS d1_plus_di_14,
            ANY_VALUE(w.w1_minus_di_14) AS w1_minus_di_14,
            ANY_VALUE(d1s.d1_minus_di_14) AS d1_minus_di_14,

            -- Price
            ANY_VALUE(d1s.d1_close) AS d1_close,
            ANY_VALUE(w.w1_close) AS w1_close,

            -- M30 intraday observation (Phase 2) — 严格取自最后一根 bar
            ANY_VALUE(m30.m30_close) AS m30_close,
            ANY_VALUE(m30.m30_bb20_position) AS m30_bb20_position,
            ANY_VALUE(m30.m30_bb20_width) AS m30_bb20_width,
            ANY_VALUE(m30.m30_atr14) AS m30_atr14,
            ANY_VALUE(m30.m30_adx14) AS m30_adx14,
            ANY_VALUE(m30.m30_plus_di_14) AS m30_plus_di_14,
            ANY_VALUE(m30.m30_minus_di_14) AS m30_minus_di_14,
            -- M30 derived (from m30_states view)
            ANY_VALUE(m30.m30_adx_slope_3) AS m30_adx_slope_3,
            ANY_VALUE(m30.m30_breakout_signal) AS m30_breakout_signal,
            ANY_VALUE(m30.m30_price_breakout) AS m30_price_breakout,
            ANY_VALUE(m30.m30_ma20_ready) AS m30_ma20_ready,
            ANY_VALUE(m30.m30_close_vs_ma20_flag) AS m30_close_vs_ma20_flag,
            ANY_VALUE(m30.m30_intraday_prev_high) AS m30_intraday_prev_high,

            -- Future returns
            ANY_VALUE(d1s.future_r5) AS future_r5,
            ANY_VALUE(d1s.future_r20) AS future_r20

        FROM foundation.d1_perspective_state h
        LEFT JOIN w1_states w
            ON h.stock_code = w.stock_code
            AND h.state_date BETWEEN w.period_start AND w.period_end
        LEFT JOIN d1_states d1s
            ON h.stock_code = d1s.stock_code
            AND h.state_date = d1s.state_date
        LEFT JOIN m30_states m30
            ON h.stock_code = m30.stock_code
            AND h.state_date = m30.state_date
        WHERE h.state_date >= '{min_date}'
        GROUP BY h.stock_code, h.state_date,
                 h.mn1_state_hex, h.w1_state_hex, h.d1_state_hex,
                 h.ef_count
    """)

    # Stats
    row_count = con.execute("SELECT COUNT(*) FROM state_cube").fetchone()[0]
    stock_count = con.execute("SELECT COUNT(DISTINCT stock_code) FROM state_cube").fetchone()[0]
    date_range = con.execute("SELECT MIN(state_date), MAX(state_date) FROM state_cube").fetchone()

    print(f"\nState Cube built:")
    print(f"  Rows: {row_count:,}")
    print(f"  Stocks: {stock_count:,}")
    print(f"  Date range: {date_range[0]} ~ {date_range[1]}")

    # Sample
    print(f"\nSample row:")
    sample = con.execute("SELECT * FROM state_cube LIMIT 1").fetchone()
    cols = [desc[0] for desc in con.description]
    for col, val in zip(cols, sample):
        print(f"  {col:25s}: {val}")

    # Index for fast lookup
    con.execute("CREATE UNIQUE INDEX idx_state_cube_pk ON state_cube(stock_code, state_date)")
    con.execute("CREATE INDEX idx_state_cube_date ON state_cube(state_date)")

    con.close()
    print(f"\nWritten: {output_db}")


def main():
    parser = argparse.ArgumentParser(description="Build State Cube")
    parser.add_argument("--foundation", default=str(ROOT / "outputs" / "p116_foundation_20260602" / "p116_foundation.duckdb"))
    parser.add_argument("--output", default=str(ROOT / "outputs" / "state_cube" / "state_cube.duckdb"))
    parser.add_argument("--min-date", default="2020-01-01")
    args = parser.parse_args()

    build_cube(Path(args.foundation), Path(args.output), args.min_date)


if __name__ == "__main__":
    sys.exit(main() or 0)
