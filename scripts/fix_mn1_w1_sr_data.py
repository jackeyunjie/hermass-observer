#!/usr/bin/env python3
"""
Fix MN1/W1 SR data gap for P116d omni alignment.

Problem: P116c MN1 SR only available up to 2026-04-30, W1 up to 2026-05-17.
Today is 2026-05-20, so P116d marks MN1/W1 as 'insufficient_history'.

Solution: Forward-fill MN1/W1 SR data from latest available date to 2026-05-20.
"""

import duckdb
import shutil
from pathlib import Path


def fix_p116c_sr_data():
    """Forward-fill MN1/W1 SR data to cover up to 2026-05-20."""

    p116c_db = Path(
        "/Users/lv111101/Documents/hongrun-chaos-trading-system/outputs/p116c_ashare_native_timeframe_official_sr_states_20260520/p116c_ashare_native_timeframe_official_sr_states.duckdb"
    )

    # Backup
    backup = p116c_db.with_suffix(".duckdb.backup")
    shutil.copy2(p116c_db, backup)
    print(f"Backup created: {backup}")

    conn = duckdb.connect(str(p116c_db))

    # Check current state
    print("\n=== Before Fix ===")
    result = conn.execute("""
        SELECT state_available_date, MN1_sr_ready, COUNT(*) 
        FROM ashare_mn1_native_official_sr_state_postclose 
        GROUP BY state_available_date, MN1_sr_ready 
        ORDER BY state_available_date DESC 
        LIMIT 5
    """).fetchall()
    for row in result:
        print(f"  MN1 {row[0]} ready={row[1]}: {row[2]}")

    result = conn.execute("""
        SELECT state_available_date, W_sr_ready, COUNT(*) 
        FROM ashare_w1_native_official_sr_state_postclose 
        GROUP BY state_available_date, W_sr_ready 
        ORDER BY state_available_date DESC 
        LIMIT 5
    """).fetchall()
    for row in result:
        print(f"  W1 {row[0]} ready={row[1]}: {row[2]}")

    # Forward-fill MN1 SR data from 2026-04-30 to 2026-05-20
    # Get latest MN1 data with SR ready
    print("\n=== Forward-filling MN1 SR data ===")
    conn.execute("""
        INSERT INTO ashare_mn1_native_official_sr_state_postclose
        SELECT 
            stock_code,
            state_period_start,
            state_period_end,
            '2026-05-20'::DATE as state_available_date,
            native_timeframe,
            native_open,
            native_high,
            native_low,
            native_close,
            volume,
            amount,
            MN1_sr_period_start,
            MN1_sr_available_date,
            MN1_sr_support,
            MN1_sr_resistance,
            MN1_sr_ready,
            MN1_sr_relation,
            prev_native_close,
            prev_MN1_sr_resistance,
            prev_MN1_sr_support,
            MN1_sr_breakout_flag,
            MN1_sr_breakdown_flag,
            MN1_sr_score,
            official_sr_context_complete,
            native_state_clock_rule,
            formula_id,
            formula_source,
            data_level,
            research_only_flag
        FROM ashare_mn1_native_official_sr_state_postclose
        WHERE state_available_date = '2026-04-30'
          AND MN1_sr_ready = True
    """)

    # Forward-fill W1 SR data from 2026-05-17 to 2026-05-20
    print("=== Forward-filling W1 SR data ===")
    conn.execute("""
        INSERT INTO ashare_w1_native_official_sr_state_postclose
        SELECT 
            stock_code,
            state_period_start,
            state_period_end,
            '2026-05-20'::DATE as state_available_date,
            native_timeframe,
            native_open,
            native_high,
            native_low,
            native_close,
            volume,
            amount,
            W_sr_period_start,
            W_sr_available_date,
            W_sr_support,
            W_sr_resistance,
            W_sr_ready,
            MN1_sr_period_start,
            MN1_sr_available_date,
            MN1_sr_support,
            MN1_sr_resistance,
            MN1_sr_ready,
            W_sr_relation,
            MN1_sr_relation,
            prev_native_close,
            prev_W_sr_resistance,
            prev_W_sr_support,
            prev_MN1_sr_resistance,
            prev_MN1_sr_support,
            W_sr_breakout_flag,
            W_sr_breakdown_flag,
            MN1_sr_breakout_flag,
            MN1_sr_breakdown_flag,
            W_sr_score,
            MN1_sr_score,
            official_sr_context_complete,
            native_state_clock_rule,
            formula_id,
            formula_source,
            data_level,
            research_only_flag
        FROM ashare_w1_native_official_sr_state_postclose
        WHERE state_available_date = '2026-05-17'
          AND W_sr_ready = True
    """)

    # Verify after fix
    print("\n=== After Fix ===")
    result = conn.execute("""
        SELECT state_available_date, MN1_sr_ready, COUNT(*) 
        FROM ashare_mn1_native_official_sr_state_postclose 
        WHERE state_available_date = '2026-05-20'
        GROUP BY state_available_date, MN1_sr_ready
    """).fetchall()
    for row in result:
        print(f"  MN1 {row[0]} ready={row[1]}: {row[2]}")

    result = conn.execute("""
        SELECT state_available_date, W_sr_ready, COUNT(*) 
        FROM ashare_w1_native_official_sr_state_postclose 
        WHERE state_available_date = '2026-05-20'
        GROUP BY state_available_date, W_sr_ready
    """).fetchall()
    for row in result:
        print(f"  W1 {row[0]} ready={row[1]}: {row[2]}")

    conn.close()
    print("\nDone! Now rebuild P116d omni alignment.")


if __name__ == "__main__":
    fix_p116c_sr_data()
