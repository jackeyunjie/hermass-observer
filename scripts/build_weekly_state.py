#!/usr/bin/env python3
"""Build native W1 State from real weekly bars.

This script computes W1 State independently from weekly K-line data,
using W1 close (not D1 close) for position evaluation.

Input:  outputs/weekly_bars/weekly_bars.duckdb
Output: outputs/state_cache/weekly_state_YYYYWww.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
WEEKLY_DB = ROOT / "outputs" / "weekly_bars" / "weekly_bars.duckdb"
CACHE_DIR = ROOT / "outputs" / "state_cache"


def iso_week_key(d: date) -> str:
    """Return ISO week key like '2026W20'."""
    iso = d.isocalendar()
    return f"{iso.year}W{iso.week:02d}"


def build_native_w1_state(
    weekly_db: Path = WEEKLY_DB,
    out_dir: Path = CACHE_DIR,
    week_key: str | None = None,
) -> list[Path]:
    """Compute native W1 State for all weeks (or a specific week) and write JSON."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Use in-memory DuckDB and attach weekly bars read-only
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{str(weekly_db).replace(chr(39), chr(39)+chr(39))}' AS wdb (READ_ONLY)")

    # 1. Compute SR levels from weekly bars (same fractal logic as foundation)
    con.execute("""
        CREATE OR REPLACE TABLE sr_levels AS
        WITH ordered AS (
          SELECT
            *,
            row_number() OVER (PARTITION BY stock_code ORDER BY week_start_date)::BIGINT AS bar_index,
            lag(high, 1) OVER w AS high_lag_1,
            lag(high, 2) OVER w AS high_lag_2,
            lead(high, 1) OVER w AS high_lead_1,
            lead(high, 2) OVER w AS high_lead_2,
            lag(low, 1) OVER w AS low_lag_1,
            lag(low, 2) OVER w AS low_lag_2,
            lead(low, 1) OVER w AS low_lead_1,
            lead(low, 2) OVER w AS low_lead_2
          FROM wdb.weekly_bars
          WINDOW w AS (PARTITION BY stock_code ORDER BY week_start_date)
        ),
        center_fractal AS (
          SELECT
            *,
            CASE
              WHEN high_lag_2 < high AND high_lag_1 < high AND high_lead_1 < high AND high_lead_2 < high
              THEN high ELSE NULL
            END AS center_fractal_resistance,
            CASE
              WHEN low_lag_2 > low AND low_lag_1 > low AND low_lead_1 > low AND low_lead_2 > low
              THEN low ELSE NULL
            END AS center_fractal_support
          FROM ordered
        ),
        confirmed AS (
          SELECT
            *,
            lag(center_fractal_resistance, 3) OVER (
              PARTITION BY stock_code ORDER BY week_start_date
            ) AS fractal_resistance,
            lag(center_fractal_support, 3) OVER (
              PARTITION BY stock_code ORDER BY week_start_date
            ) AS fractal_support
          FROM center_fractal
        ),
        filled AS (
          SELECT
            *,
            last_value(fractal_resistance IGNORE NULLS) OVER (
              PARTITION BY stock_code ORDER BY week_start_date
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS sr_resistance,
            last_value(fractal_support IGNORE NULLS) OVER (
              PARTITION BY stock_code ORDER BY week_start_date
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS sr_support
          FROM confirmed
        )
        SELECT
          stock_code,
          week_start_date,
          week_end_date,
          open, high, low, close, volume,
          sr_resistance,
          sr_support,
          (sr_resistance IS NOT NULL AND sr_support IS NOT NULL) AS sr_ready
        FROM filled
        ORDER BY stock_code, week_start_date
    """)

    # 2. Compute weekly indicators (ADX, DI, ATR, BB width)
    con.execute("""
        CREATE OR REPLACE TABLE indicators AS
        WITH ordered AS (
          SELECT
            stock_code, week_start_date, week_end_date, close, high, low,
            lag(close) OVER w AS prev_close,
            lag(high) OVER w AS prev_high,
            lag(low) OVER w AS prev_low,
            avg(close) OVER w20 AS bb_middle_20,
            stddev_samp(close) OVER w20 AS bb_std_20
          FROM wdb.weekly_bars
          WINDOW
            w AS (PARTITION BY stock_code ORDER BY week_start_date),
            w20 AS (PARTITION BY stock_code ORDER BY week_start_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
        ),
        directional AS (
          SELECT
            *,
            greatest(high - low, abs(high - coalesce(prev_close, close)), abs(low - coalesce(prev_close, close))) AS true_range,
            CASE
              WHEN prev_high IS NULL THEN NULL
              WHEN (high - prev_high) > (prev_low - low) AND (high - prev_high) > 0 THEN high - prev_high
              ELSE 0
            END AS plus_dm,
            CASE
              WHEN prev_low IS NULL THEN NULL
              WHEN (prev_low - low) > (high - prev_high) AND (prev_low - low) > 0 THEN prev_low - low
              ELSE 0
            END AS minus_dm,
            CASE
              WHEN bb_middle_20 IS NOT NULL AND bb_middle_20 <> 0 AND bb_std_20 IS NOT NULL
              THEN (4.0 * bb_std_20) / bb_middle_20
              ELSE NULL
            END AS bb_width_pct
          FROM ordered
        ),
        smoothed AS (
          SELECT
            *,
            avg(true_range) OVER w14 AS atr14,
            avg(plus_dm) OVER w14 AS plus_dm14,
            avg(minus_dm) OVER w14 AS minus_dm14
          FROM directional
          WINDOW w14 AS (
            PARTITION BY stock_code ORDER BY week_start_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
          )
        ),
        di AS (
          SELECT
            *,
            CASE WHEN atr14 IS NOT NULL AND atr14 <> 0 THEN 100.0 * plus_dm14 / atr14 ELSE NULL END AS plus_di_14,
            CASE WHEN atr14 IS NOT NULL AND atr14 <> 0 THEN 100.0 * minus_dm14 / atr14 ELSE NULL END AS minus_di_14,
            CASE WHEN close IS NOT NULL AND close <> 0 AND atr14 IS NOT NULL THEN 100.0 * atr14 / close ELSE NULL END AS atr_ratio_pct
          FROM smoothed
        ),
        dx AS (
          SELECT
            *,
            CASE
              WHEN plus_di_14 IS NOT NULL AND minus_di_14 IS NOT NULL AND (plus_di_14 + minus_di_14) <> 0
              THEN 100.0 * abs(plus_di_14 - minus_di_14) / (plus_di_14 + minus_di_14)
              ELSE NULL
            END AS dx14
          FROM di
        ),
        ranked_base AS (
          SELECT
            *,
            avg(dx14) OVER w14 AS adx14,
            quantile_cont(bb_width_pct, 0.20) OVER w20prev AS bb_width_q20_20,
            quantile_cont(bb_width_pct, 0.50) OVER w20prev AS bb_width_median_20,
            quantile_cont(bb_width_pct, 0.80) OVER w20prev AS bb_width_q80_20,
            quantile_cont(atr_ratio_pct, 0.75) OVER w60prev AS atr_ratio_q75_60,
            avg(atr_ratio_pct) OVER w60prev AS atr_ratio_avg60
          FROM dx
          WINDOW
            w14 AS (PARTITION BY stock_code ORDER BY week_start_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),
            w20prev AS (PARTITION BY stock_code ORDER BY week_start_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
            w60prev AS (PARTITION BY stock_code ORDER BY week_start_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
        ),
        ranked AS (
          SELECT
            *,
            lag(bb_width_pct) OVER w AS prev_bb_width_pct,
            lag(atr_ratio_pct) OVER w AS prev_atr_ratio_pct,
            lag(adx14) OVER w AS prev_adx14,
            adx14 - lag(adx14, 3) OVER w AS adx_slope_3
          FROM ranked_base
          WINDOW w AS (PARTITION BY stock_code ORDER BY week_start_date)
        )
        SELECT
          stock_code, week_start_date, week_end_date, close,
          atr14, atr_ratio_pct, atr_ratio_avg60, atr_ratio_q75_60,
          plus_di_14, minus_di_14, adx14, adx_slope_3,
          bb_width_pct, bb_width_q20_20, bb_width_q80_20, prev_bb_width_pct,
          CASE
            WHEN adx14 IS NULL OR plus_di_14 IS NULL OR minus_di_14 IS NULL THEN 'insufficient_history'
            WHEN adx14 <= 13 AND adx_slope_3 < 0 THEN 'closed'
            WHEN adx14 >= 25 AND adx_slope_3 > 0 AND plus_di_14 > minus_di_14 THEN 'bull_trend'
            WHEN adx14 >= 25 AND adx_slope_3 > 0 AND minus_di_14 > plus_di_14 THEN 'bear_trend'
            WHEN adx14 > 20 AND plus_di_14 > minus_di_14 THEN 'bull_start'
            WHEN adx14 > 20 AND minus_di_14 > plus_di_14 THEN 'bear_start'
            ELSE 'neutral'
          END AS trend,
          CASE
            WHEN atr_ratio_pct IS NULL OR atr_ratio_avg60 IS NULL THEN 'insufficient_history'
            WHEN atr_ratio_pct >= atr_ratio_avg60 * 1.25 OR atr_ratio_pct >= atr_ratio_q75_60 THEN 'atr_expanding'
            WHEN atr_ratio_pct <= atr_ratio_avg60 * 0.75 THEN 'atr_contracting'
            ELSE 'neutral'
          END AS volatility,
          CASE
            WHEN bb_width_pct IS NULL OR bb_width_q20_20 IS NULL THEN 'insufficient_history'
            WHEN adx14 <= 13 AND adx_slope_3 < 0 AND bb_width_pct <= bb_width_q20_20 THEN 'closed'
            WHEN bb_width_pct <= bb_width_q20_20 THEN 'contracting'
            WHEN bb_width_pct >= bb_width_q80_20
             AND prev_bb_width_pct IS NOT NULL
             AND bb_width_pct > prev_bb_width_pct * 1.05 THEN 'strong_expansion'
            WHEN prev_bb_width_pct IS NOT NULL AND bb_width_pct > prev_bb_width_pct * 1.05 THEN 'expansion_start'
            ELSE 'neutral'
          END AS compression
        FROM ranked
        ORDER BY stock_code, week_start_date
    """)

    # 3. Compute native W1 State
    con.execute("""
        CREATE OR REPLACE TABLE native_w1_state AS
        SELECT
          i.stock_code,
          i.week_start_date,
          i.week_end_date,
          i.close AS w1_close,
          s.sr_support AS w1_sr_support,
          s.sr_resistance AS w1_sr_resistance,
          s.sr_ready AS w1_sr_ready,
          i.trend AS w1_trend_label,
          i.volatility AS w1_volatility_label,
          i.compression AS w1_compression_label,
          i.adx14 AS w1_adx14,
          i.bb_width_pct AS w1_bb_width_pct,
          i.atr_ratio_pct AS w1_atr_ratio_pct,
          -- Bits (same logic as D1-perspective)
          CASE WHEN i.trend LIKE 'bull%' OR i.trend LIKE 'bear%' THEN 1 ELSE 0 END AS trend_bit,
          CASE WHEN i.volatility = 'atr_expanding' THEN 1 ELSE 0 END AS volatility_bit,
          CASE WHEN i.compression = 'closed' OR i.trend = 'closed' THEN 0 ELSE 8 END AS base,
          -- Position bit using W1 close (native perspective)
          -- When SR not ready, default to 0 (same as D1-perspective behavior)
          CASE
            WHEN s.sr_ready = false OR s.sr_support IS NULL OR s.sr_resistance IS NULL THEN 0
            WHEN i.close > s.sr_resistance THEN 2
            WHEN i.close < s.sr_support THEN 2
            ELSE 0
          END AS position_bit,
          -- Bull/bear context for sign arbitration
          (i.trend LIKE 'bull%' OR i.close > s.sr_resistance) AS bull_context,
          (i.trend LIKE 'bear%' OR i.close < s.sr_support) AS bear_context
        FROM indicators i
        LEFT JOIN sr_levels s
          ON s.stock_code = i.stock_code AND s.week_start_date = i.week_start_date
        ORDER BY i.stock_code, i.week_start_date
    """)

    # 4. Compute final state score and hex
    rows = con.execute("""
        SELECT
          stock_code,
          week_start_date,
          week_end_date,
          w1_close,
          w1_sr_support,
          w1_sr_resistance,
          w1_sr_ready,
          base,
          trend_bit,
          position_bit,
          volatility_bit,
          bull_context,
          bear_context
        FROM native_w1_state
        WHERE week_start_date IS NOT NULL
        ORDER BY week_start_date, stock_code
    """).fetchall()

    con.close()

    # Group by week and compute state in Python
    weeks: dict[str, dict[str, Any]] = {}

    for row in rows:
        (
            stock_code, week_start, week_end, w1_close,
            sr_support, sr_resistance, sr_ready,
            base, trend_bit, position_bit, volatility_bit,
            bull_context, bear_context,
        ) = row

        wk = iso_week_key(week_start)
        if wk not in weeks:
            weeks[wk] = {
                "schema_version": "weekly_state_v1",
                "week": wk,
                "week_start_date": week_start.isoformat(),
                "week_end_date": week_end.isoformat() if week_end else None,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_stocks": 0,
                "stocks": [],
            }

        # Compute state score even when SR not ready (position_bit defaults to 0)
        # This matches D1-perspective behavior in foundation DB
        magnitude = base + trend_bit * 4 + position_bit + volatility_bit

        # Sign arbitration (position priority, same as D1 perspective)
        if sr_ready and sr_support is not None and w1_close < sr_support:
            state_score = -magnitude
        elif sr_ready and sr_resistance is not None and w1_close > sr_resistance:
            state_score = magnitude
        elif bear_context and not bull_context:
            state_score = -magnitude
        else:
            state_score = magnitude

        if state_score < 0:
            state_hex = f"-{abs(state_score):X}"
        else:
            state_hex = f"{state_score:X}"

        weeks[wk]["stocks"].append({
            "stock_code": stock_code,
            "week_start_date": week_start.isoformat(),
            "week_end_date": week_end.isoformat() if week_end else None,
            "w1_state": state_score,
            "w1_state_hex": state_hex,
            "w1_base": base,
            "w1_trend": trend_bit,
            "w1_position": position_bit,
            "w1_volatility": volatility_bit,
            "w1_close": round(w1_close, 4) if w1_close else None,
            "w1_sr_support": round(sr_support, 4) if sr_support else None,
            "w1_sr_resistance": round(sr_resistance, 4) if sr_resistance else None,
            "w1_sr_ready": bool(sr_ready) if sr_ready is not None else False,
        })
        weeks[wk]["total_stocks"] += 1

    # Write JSON files
    written: list[Path] = []
    for wk, data in sorted(weeks.items()):
        if week_key is not None and wk != week_key:
            continue
        path = out_dir / f"weekly_state_{wk}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)

    # Write latest symlink copy
    if written:
        latest = out_dir / "weekly_state_latest.json"
        latest_week = max(weeks.keys()) if week_key is None else week_key
        latest.write_text(
            json.dumps(weeks[latest_week], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Build native W1 State from weekly bars")
    parser.add_argument("--weekly-db", type=Path, default=WEEKLY_DB, help="Path to weekly_bars.duckdb")
    parser.add_argument("--out-dir", type=Path, default=CACHE_DIR, help="Output directory")
    parser.add_argument("--week", type=str, default=None, help="Specific ISO week to build, e.g. 2026W20")
    args = parser.parse_args()

    paths = build_native_w1_state(
        weekly_db=args.weekly_db,
        out_dir=args.out_dir,
        week_key=args.week,
    )

    if paths:
        print(f"Wrote {len(paths)} weekly state file(s):")
        for p in paths:
            size = p.stat().st_size
            print(f"  {p.name} ({size:,} bytes)")
    else:
        print("No files written.")


if __name__ == "__main__":
    main()
