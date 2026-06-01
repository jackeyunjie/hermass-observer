#!/usr/bin/env python3
"""Build P116 A-share D1-native state v2 - Position based on SR key levels.

This version replaces the 120-day high/low position calculation with SR key level
based position calculation:
- break_up: close > sr_resistance → position_bit = +2
- break_down: close < sr_support → position_bit = -2
- neutral: sr_support <= close <= sr_resistance → position_bit = 0
- Error if sr_ready = False

Usage:
    cd /Users/lv111101/Documents/hongrun-chaos-trading-system
    .venv/bin/python scripts/build_p116_ashare_d1_native_state_v2.py
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


REPO_ROOT = Path(__file__).resolve().parents[1]
# Research repo root (parent of product repo)
RESEARCH_ROOT = REPO_ROOT.parent / "hongrun-chaos-trading-system"

DEFAULT_RAW_DB = (
    RESEARCH_ROOT
    / "outputs"
    / "p108_blackwolf_ashare_daily_raw_20260518"
    / "p108_blackwolf_ashare_daily_raw.duckdb"
)
DEFAULT_SR_DB = (
    RESEARCH_ROOT
    / "outputs"
    / "p116b_ashare_d1_official_sr_key_positions_20260518"
    / "p116b_ashare_d1_official_sr_key_positions.duckdb"
)
DEFAULT_OUT_DB = (
    REPO_ROOT
    / "outputs"
    / "p116_ashare_d1_native_state_v2_20260518"
    / "p116_ashare_d1_native_state_v2.duckdb"
)

SCHEMA_VERSION = "p116_ashare_d1_native_state_v2_0"
DATA_LEVEL = "L2_STATE_SMOKE_CANDIDATE"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_state_v2(raw_db: Path, sr_db: Path, out_db: Path) -> dict[str, Any]:
    """Build P116 state v2 with SR-based position calculation.

    D1视角原则：所有周期的position都用D1收盘价与各周期SR关键位比较。
    """

    out_db.parent.mkdir(parents=True, exist_ok=True)

    # Connect to P116 original DB and SR DB
    p116_db_path = (
        RESEARCH_ROOT
        / "outputs"
        / "p116_ashare_d1_native_state_20260518"
        / "p116_ashare_d1_native_state.duckdb"
    )

    conn = duckdb.connect(str(out_db))
    conn.execute(f"ATTACH '{p116_db_path}' AS p116_db (READ_ONLY)")
    conn.execute(f"ATTACH '{sr_db}' AS sr_db (READ_ONLY)")

    # Create state table with SR-based position (D1视角)
    conn.execute("""
        CREATE OR REPLACE TABLE ashare_d1_native_state_v2 AS
        WITH 
        -- Get SR key levels from p116b
        sr_levels AS (
            SELECT
                stock_code,
                base_date,
                MN1_sr_resistance,
                MN1_sr_support,
                MN1_sr_ready,
                W_sr_resistance,
                W_sr_support,
                W_sr_ready,
                D_sr_resistance,
                D_sr_support,
                D_sr_ready
            FROM sr_db.ashare_d1_official_sr_key_positions_postclose
        ),
        -- Get D1 data as base (D1视角，以D1为基准)
        d1_base AS (
            SELECT
                stock_code,
                state_date,
                close AS d1_close,
                open,
                high,
                low,
                volume,
                amount,
                compression,
                trend,
                volatility
            FROM p116_db.ashare_d1_state_timeframe
            WHERE timeframe = 'D1'
        ),
        -- Calculate position for each timeframe using D1 close vs respective SR levels
        state_with_sr AS (
            SELECT
                d.stock_code,
                d.state_date,
                -- D1 timeframe
                'D1' AS timeframe,
                d.d1_close AS close,
                d.open,
                d.high,
                d.low,
                d.volume,
                d.amount,
                sr.D_sr_resistance AS sr_resistance,
                sr.D_sr_support AS sr_support,
                sr.D_sr_ready AS sr_ready,
                CASE
                    WHEN NOT sr.D_sr_ready THEN 'sr_not_ready'
                    WHEN d.d1_close > sr.D_sr_resistance THEN 'break_up'
                    WHEN d.d1_close < sr.D_sr_support THEN 'break_down'
                    ELSE 'neutral'
                END AS position,
                d.compression,
                d.trend,
                d.volatility
            FROM d1_base d
            LEFT JOIN sr_levels sr 
                ON d.stock_code = sr.stock_code 
                AND d.state_date = sr.base_date
            
            UNION ALL
            
            -- W1 timeframe (using D1 close vs W1 SR levels)
            SELECT
                d.stock_code,
                d.state_date,
                'W1' AS timeframe,
                d.d1_close AS close,
                d.open,
                d.high,
                d.low,
                d.volume,
                d.amount,
                sr.W_sr_resistance AS sr_resistance,
                sr.W_sr_support AS sr_support,
                sr.W_sr_ready AS sr_ready,
                CASE
                    WHEN NOT sr.W_sr_ready THEN 'sr_not_ready'
                    WHEN d.d1_close > sr.W_sr_resistance THEN 'break_up'
                    WHEN d.d1_close < sr.W_sr_support THEN 'break_down'
                    ELSE 'neutral'
                END AS position,
                d.compression,
                d.trend,
                d.volatility
            FROM d1_base d
            LEFT JOIN sr_levels sr 
                ON d.stock_code = sr.stock_code 
                AND d.state_date = sr.base_date
            
            UNION ALL
            
            -- MN1 timeframe (using D1 close vs MN1 SR levels)
            SELECT
                d.stock_code,
                d.state_date,
                'MN1' AS timeframe,
                d.d1_close AS close,
                d.open,
                d.high,
                d.low,
                d.volume,
                d.amount,
                sr.MN1_sr_resistance AS sr_resistance,
                sr.MN1_sr_support AS sr_support,
                sr.MN1_sr_ready AS sr_ready,
                CASE
                    WHEN NOT sr.MN1_sr_ready THEN 'sr_not_ready'
                    WHEN d.d1_close > sr.MN1_sr_resistance THEN 'break_up'
                    WHEN d.d1_close < sr.MN1_sr_support THEN 'break_down'
                    ELSE 'neutral'
                END AS position,
                d.compression,
                d.trend,
                d.volatility
            FROM d1_base d
            LEFT JOIN sr_levels sr 
                ON d.stock_code = sr.stock_code 
                AND d.state_date = sr.base_date
        )
        SELECT
            *,
            -- Component bits
            CASE WHEN compression IN ('closed', 'contracting') THEN 0 ELSE 8 END AS base_component,
            CASE WHEN volatility IN ('atr_expanding', 'range_expanded') THEN 1 ELSE 0 END AS volatility_bit,
            -- Position bit with sign based on direction
            CASE 
                WHEN position = 'break_up' THEN 2
                WHEN position = 'break_down' THEN -2
                WHEN position = 'sr_not_ready' THEN NULL
                ELSE 0
            END AS position_bit,
            CASE WHEN trend LIKE 'bull%' OR trend LIKE 'bear%' THEN 4 ELSE 0 END AS trend_bit,
            -- Context
            (trend LIKE 'bull%' OR position = 'break_up') AS bull_context,
            (trend LIKE 'bear%' OR position = 'break_down') AS bear_context
        FROM state_with_sr
    """)

    # Calculate state_score and state_hex
    conn.execute("""
        CREATE OR REPLACE TABLE ashare_d1_native_state_v2_final AS
        SELECT
            stock_code,
            state_date,
            timeframe,
            close,
            open,
            high,
            low,
            volume,
            amount,
            sr_resistance,
            sr_support,
            sr_ready,
            position,
            compression,
            trend,
            volatility,
            base_component,
            volatility_bit,
            position_bit,
            trend_bit,
            bull_context,
            bear_context,
            -- State score calculation
            CASE
                WHEN position_bit IS NULL THEN NULL
                WHEN bear_context AND NOT bull_context
                    THEN -(base_component + volatility_bit + position_bit + trend_bit)
                ELSE (base_component + volatility_bit + position_bit + trend_bit)
            END AS state_score,
            -- Hex encoding
            CASE
                WHEN position_bit IS NULL THEN 'SR_NOT_READY'
                WHEN state_score < 0 THEN '-' || to_hex(abs(state_score)::UBIGINT)
                ELSE to_hex(state_score::UBIGINT)
            END AS state_hex
        FROM ashare_d1_native_state_v2
    """)

    # Get summary stats
    summary = conn.execute("""
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT stock_code) AS total_stocks,
            COUNT(DISTINCT state_date) AS total_dates,
            COUNT(CASE WHEN position_bit IS NULL THEN 1 END) AS sr_not_ready_count,
            COUNT(CASE WHEN position = 'break_up' THEN 1 END) AS break_up_count,
            COUNT(CASE WHEN position = 'break_down' THEN 1 END) AS break_down_count,
            COUNT(CASE WHEN position = 'neutral' THEN 1 END) AS neutral_count
        FROM ashare_d1_native_state_v2_final
    """).fetchone()

    conn.close()

    return {
        "schema_version": SCHEMA_VERSION,
        "data_level": DATA_LEVEL,
        "generated_at": now_iso(),
        "total_rows": summary[0],
        "total_stocks": summary[1],
        "total_dates": summary[2],
        "sr_not_ready_count": summary[3],
        "break_up_count": summary[4],
        "break_down_count": summary[5],
        "neutral_count": summary[6],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build P116 state v2 with SR-based position")
    parser.add_argument("--raw-db", type=Path, default=DEFAULT_RAW_DB)
    parser.add_argument("--sr-db", type=Path, default=DEFAULT_SR_DB)
    parser.add_argument("--out-db", type=Path, default=DEFAULT_OUT_DB)
    args = parser.parse_args()

    print("Building P116 state v2 with SR-based position...")
    print(f"Raw DB: {args.raw_db}")
    print(f"SR DB: {args.sr_db}")
    print(f"Output: {args.out_db}")

    summary = build_state_v2(args.raw_db, args.sr_db, args.out_db)

    print("\nBuild complete!")
    print(f"Total rows: {summary['total_rows']}")
    print(f"Total stocks: {summary['total_stocks']}")
    print(f"SR not ready: {summary['sr_not_ready_count']}")
    print(f"Break up: {summary['break_up_count']}")
    print(f"Break down: {summary['break_down_count']}")
    print(f"Neutral: {summary['neutral_count']}")


if __name__ == "__main__":
    main()
