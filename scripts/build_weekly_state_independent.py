#!/usr/bin/env python3
"""Build independent weekly (W1) State cache from weekly_bars.

Unlike the D1-perspective W1 state which uses D1 close vs W1 SR,
this script computes W1 state independently using weekly close
against weekly SR, weekly trend, and weekly volatility.

Outputs: outputs/state_cache/weekly_state_YYYYWww.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]


def iso_week_str(d: date) -> str:
    """Return ISO week string like '2026W21'."""
    iso = d.isocalendar()
    return f"{iso.year}W{iso.week:02d}"


def sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def build_weekly_states_sql() -> str:
    """SQL to compute independent W1 states from weekly_bars.

    Mirrors build_p116_foundation.py indicator and SR logic,
    but position uses weekly close vs weekly SR (not D1 close).
    """
    return """
    WITH
    -- 1. SqFractal 5, confirmed 3 bars later, forward-filled
    ordered AS (
      SELECT
        stock_code,
        week_start_date,
        week_end_date,
        open, high, low, close, volume,
        row_number() OVER (PARTITION BY stock_code ORDER BY week_end_date)::BIGINT AS tf_bar_index,
        lag(high, 1) OVER w AS high_lag_1,
        lag(high, 2) OVER w AS high_lag_2,
        lead(high, 1) OVER w AS high_lead_1,
        lead(high, 2) OVER w AS high_lead_2,
        lag(low, 1) OVER w AS low_lag_1,
        lag(low, 2) OVER w AS low_lag_2,
        lead(low, 1) OVER w AS low_lead_1,
        lead(low, 2) OVER w AS low_lead_2
      FROM weekly_bars
      WINDOW w AS (PARTITION BY stock_code ORDER BY week_end_date)
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
          PARTITION BY stock_code ORDER BY week_end_date
        ) AS fractal_resistance,
        lag(center_fractal_support, 3) OVER (
          PARTITION BY stock_code ORDER BY week_end_date
        ) AS fractal_support
      FROM center_fractal
    ),
    filled AS (
      SELECT
        *,
        last_value(fractal_resistance IGNORE NULLS) OVER (
          PARTITION BY stock_code ORDER BY week_end_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS sr_resistance,
        last_value(fractal_support IGNORE NULLS) OVER (
          PARTITION BY stock_code ORDER BY week_end_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS sr_support
      FROM confirmed
    ),
    -- 2. Indicators (ADX, DI, BB, ATR) — same logic as foundation
    indicators_base AS (
      SELECT
        *,
        lag(close) OVER w AS prev_close,
        lag(high) OVER w AS prev_high,
        lag(low) OVER w AS prev_low,
        avg(close) OVER w20 AS bb_middle_20,
        stddev_samp(close) OVER w20 AS bb_std_20
      FROM filled
      WINDOW
        w AS (PARTITION BY stock_code ORDER BY week_end_date),
        w20 AS (PARTITION BY stock_code ORDER BY week_end_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
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
      FROM indicators_base
    ),
    smoothed AS (
      SELECT
        *,
        avg(true_range) OVER w14 AS atr14,
        avg(plus_dm) OVER w14 AS plus_dm14,
        avg(minus_dm) OVER w14 AS minus_dm14
      FROM directional
      WINDOW w14 AS (
        PARTITION BY stock_code ORDER BY week_end_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
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
          WHEN plus_di_14 IS NOT NULL
           AND minus_di_14 IS NOT NULL
           AND (plus_di_14 + minus_di_14) <> 0
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
        w14 AS (PARTITION BY stock_code ORDER BY week_end_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),
        w20prev AS (PARTITION BY stock_code ORDER BY week_end_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        w60prev AS (PARTITION BY stock_code ORDER BY week_end_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
    ),
    ranked AS (
      SELECT
        *,
        lag(bb_width_pct) OVER w AS prev_bb_width_pct,
        lag(atr_ratio_pct) OVER w AS prev_atr_ratio_pct,
        lag(adx14) OVER w AS prev_adx14,
        adx14 - lag(adx14, 3) OVER w AS adx_slope_3
      FROM ranked_base
      WINDOW w AS (PARTITION BY stock_code ORDER BY week_end_date)
    ),
    -- 3. Trend / Volatility / Compression classification
    indicator_states AS (
      SELECT
        *,
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
    ),
    -- 4. State bits (independent W1: weekly close vs weekly SR)
    bits AS (
      SELECT
        *,
        CASE WHEN close > sr_resistance THEN 2 WHEN close < sr_support THEN 2 ELSE 0 END AS position_bit,
        CASE WHEN trend LIKE 'bull%' OR trend LIKE 'bear%' THEN 1 ELSE 0 END AS trend_bit,
        CASE WHEN volatility = 'atr_expanding' THEN 1 ELSE 0 END AS volatility_bit,
        CASE WHEN compression = 'closed' OR trend = 'closed' THEN 0 ELSE 8 END AS base,
        (trend LIKE 'bull%' OR close > sr_resistance) AS bull_context,
        (trend LIKE 'bear%' OR close < sr_support) AS bear_context
      FROM indicator_states
    ),
    -- 5. Magnitude and signed score (position-priority sign arbitration)
    magnitudes AS (
      SELECT *, (base + trend_bit * 4 + position_bit + volatility_bit)::INTEGER AS state_magnitude
      FROM bits
    ),
    scored AS (
      SELECT
        *,
        CASE
          WHEN close < sr_support THEN -state_magnitude
          WHEN close > sr_resistance THEN state_magnitude
          WHEN bear_context AND NOT bull_context THEN -state_magnitude
          ELSE state_magnitude
        END AS state_score
      FROM magnitudes
    )
    SELECT
      stock_code,
      week_start_date,
      week_end_date,
      close AS w1_close,
      sr_support AS w1_sr_support,
      sr_resistance AS w1_sr_resistance,
      sr_support IS NOT NULL AND sr_resistance IS NOT NULL AS w1_sr_ready,
      trend AS w1_trend,
      volatility AS w1_volatility,
      compression AS w1_compression,
      base AS w1_base,
      trend_bit AS w1_trend_bit,
      position_bit AS w1_position_bit,
      volatility_bit AS w1_volatility_bit,
      bull_context AS w1_bull_context,
      bear_context AS w1_bear_context,
      state_magnitude AS w1_state_magnitude,
      state_score AS w1_state_score,
      CASE
        WHEN state_score < 0 THEN '-' || to_hex(abs(state_score)::UBIGINT)
        ELSE to_hex(state_score::UBIGINT)
      END AS w1_state_hex,
      adx14 AS w1_adx14,
      plus_di_14 AS w1_plus_di_14,
      minus_di_14 AS w1_minus_di_14,
      atr_ratio_pct AS w1_atr_ratio_pct,
      bb_width_pct AS w1_bb_width_pct,
      tf_bar_index
    FROM scored
    ORDER BY stock_code, week_end_date
    """


def write_weekly_json(
    con: duckdb.DuckDBPyConnection,
    out_dir: Path,
    iso_week: str,
    week_start: date,
    week_end: date,
) -> Path:
    """Write a single weekly_state_YYYYWww.json file."""
    rows = con.execute(
        """
        SELECT
          stock_code,
          w1_state_score,
          w1_state_hex,
          w1_close,
          w1_sr_support,
          w1_sr_resistance,
          w1_sr_ready,
          w1_trend,
          w1_volatility,
          w1_compression,
          w1_base,
          w1_trend_bit,
          w1_position_bit,
          w1_volatility_bit,
          w1_adx14,
          w1_plus_di_14,
          w1_minus_di_14,
          w1_atr_ratio_pct,
          w1_bb_width_pct
        FROM weekly_state_independent
        WHERE iso_week = ?
        ORDER BY stock_code
        """,
        (iso_week,),
    ).fetchall()

    data = []
    for row in rows:
        data.append(
            {
                "stock_code": row[0],
                "w1_state_score": row[1],
                "w1_state_hex": row[2],
                "w1_close": row[3],
                "w1_sr_support": row[4],
                "w1_sr_resistance": row[5],
                "w1_sr_ready": row[6],
                "w1_trend": row[7],
                "w1_volatility": row[8],
                "w1_compression": row[9],
                "w1_base": row[10],
                "w1_trend_bit": row[11],
                "w1_position_bit": row[12],
                "w1_volatility_bit": row[13],
                "w1_adx14": row[14],
                "w1_plus_di_14": row[15],
                "w1_minus_di_14": row[16],
                "w1_atr_ratio_pct": row[17],
                "w1_bb_width_pct": row[18],
            }
        )

    result = {
        "schema_version": "weekly_state_independent_v1",
        "iso_week": iso_week,
        "week_start_date": week_start.isoformat(),
        "week_end_date": week_end.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "outputs/weekly_bars/weekly_bars.duckdb",
        "total_stocks": len(data),
        "data": data,
    }

    path = out_dir / f"weekly_state_{iso_week}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_diff_analysis(
    con: duckdb.DuckDBPyConnection,
    out_dir: Path,
    foundation_db: Path,
) -> Path:
    """Compare independent W1 state with D1-perspective W1 state and output report."""
    con.execute(f"ATTACH '{sql_path(foundation_db)}' AS foundation (READ_ONLY)")

    diff_rows = con.execute(
        """
        SELECT
          i.iso_week,
          i.w1_state_hex AS independent_hex,
          i.w1_state_score AS independent_score,
          f.w1_state_hex AS d1_perspective_hex,
          f.w1_state_score AS d1_perspective_score,
          i.stock_code,
          i.w1_close,
          f.d1_close
        FROM weekly_state_independent i
        LEFT JOIN foundation.d1_perspective_state f
          ON f.stock_code = i.stock_code
          AND f.state_date = i.week_end_date
        WHERE i.iso_week IN (
          SELECT DISTINCT iso_week FROM weekly_state_independent
          ORDER BY iso_week DESC
          LIMIT 52
        )
        ORDER BY i.iso_week DESC, i.stock_code
        """
    ).fetchall()

    # Aggregate diff distribution per week
    from collections import defaultdict

    week_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "total": 0,
            "same_hex": 0,
            "same_score": 0,
            "diff_by_sign": 0,
            "diff_by_magnitude": 0,
            "diff_by_bits": 0,
            "missing_in_foundation": 0,
            "score_diff_distribution": defaultdict(int),
            "hex_transition_counts": defaultdict(int),
        }
    )

    for row in diff_rows:
        iso_week, ind_hex, ind_score, d1_hex, d1_score, stock_code, w1_close, d1_close = row
        st = week_stats[iso_week]
        st["total"] += 1

        if d1_hex is None:
            st["missing_in_foundation"] += 1
            continue

        if ind_hex == d1_hex:
            st["same_hex"] += 1
            st["same_score"] += 1
        elif ind_score == d1_score:
            st["same_score"] += 1

        score_diff = (ind_score or 0) - (d1_score or 0)
        st["score_diff_distribution"][score_diff] += 1

        # Decode bits for deeper analysis
        def decode(score: int | None) -> tuple:
            if score is None:
                return (None, None, None, None)
            s = abs(score)
            base = 0 if s < 8 else 8
            rem = s - base
            tb = 1 if rem >= 4 else 0
            rem -= tb * 4
            pb = 1 if rem >= 2 else 0
            rem -= pb * 2
            vb = rem
            return (base, tb, pb, vb)

        ind_bits = decode(ind_score)
        d1_bits = decode(d1_score)

        if ind_bits != d1_bits:
            st["diff_by_bits"] += 1
        elif (ind_score or 0) * (d1_score or 0) < 0:
            st["diff_by_sign"] += 1
        elif abs(ind_score or 0) != abs(d1_score or 0):
            st["diff_by_magnitude"] += 1

        transition = f"{d1_hex or 'NULL'}->{ind_hex}"
        st["hex_transition_counts"][transition] += 1

    # Convert defaultdicts to regular dicts for JSON serialization
    for st in week_stats.values():
        st["score_diff_distribution"] = dict(st["score_diff_distribution"])
        st["hex_transition_counts"] = dict(
            sorted(st["hex_transition_counts"].items(), key=lambda x: -x[1])[:20]
        )

    report = {
        "schema_version": "weekly_state_diff_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "foundation_db": str(foundation_db),
        "note": "Independent W1 state vs D1-perspective W1 state (from d1_perspective_state)",
        "weeks": dict(sorted(week_stats.items(), reverse=True)),
    }

    path = out_dir / "weekly_state_diff_analysis.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Also write a human-readable summary
    summary_lines = [
        "# Weekly State Independent vs D1-Perspective Diff Analysis",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Foundation: {foundation_db}",
        "",
    ]

    for wk, st in sorted(week_stats.items(), reverse=True):
        total = st["total"]
        if total == 0:
            continue
        same_pct = round(st["same_hex"] / total * 100, 2)
        summary_lines.append(f"## Week {wk}")
        summary_lines.append(f"- Total stocks: {total}")
        summary_lines.append(f"- Same hex: {st['same_hex']} ({same_pct}%)")
        summary_lines.append(f"- Same score (incl sign): {st['same_score']}")
        summary_lines.append(f"- Diff by bits: {st['diff_by_bits']}")
        summary_lines.append(f"- Diff by sign only: {st['diff_by_sign']}")
        summary_lines.append(f"- Diff by magnitude only: {st['diff_by_magnitude']}")
        summary_lines.append(f"- Missing in foundation: {st['missing_in_foundation']}")
        summary_lines.append("")

    summary_path = out_dir / "weekly_state_diff_analysis.md"
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build independent weekly W1 state cache")
    parser.add_argument(
        "--weekly-db", type=Path, default=ROOT / "outputs" / "weekly_bars" / "weekly_bars.duckdb"
    )
    parser.add_argument(
        "--foundation-db",
        type=Path,
        default=ROOT / "outputs" / "p116_foundation_20260522" / "p116_foundation.duckdb",
    )
    parser.add_argument("--out-dir", type=Path, default=ROOT / "outputs" / "state_cache")
    parser.add_argument(
        "--week", type=str, default=None, help="ISO week like 2026W21. If omitted, generates all weeks."
    )
    parser.add_argument("--skip-diff", action="store_true", help="Skip diff analysis against foundation DB")
    args = parser.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Connecting to {args.weekly_db}")
    con = duckdb.connect(str(args.weekly_db))
    con.execute("SET threads=4")

    # Build independent states as a temporary table
    print("Computing independent W1 states...")
    con.execute("DROP TABLE IF EXISTS weekly_state_independent")
    sql = build_weekly_states_sql()
    con.execute(f"CREATE TABLE weekly_state_independent AS {sql}")
    con.execute("ALTER TABLE weekly_state_independent ADD COLUMN iso_week VARCHAR")
    con.execute("UPDATE weekly_state_independent SET iso_week = strftime('%GW%V', week_end_date)")

    total_rows = con.execute("SELECT COUNT(*) FROM weekly_state_independent").fetchone()[0]
    print(f"Total independent W1 state rows: {total_rows}")

    # Determine weeks to output
    if args.week:
        weeks = con.execute(
            "SELECT DISTINCT iso_week, MIN(week_start_date), MAX(week_end_date) FROM weekly_state_independent WHERE iso_week = ? GROUP BY iso_week",
            (args.week,),
        ).fetchall()
    else:
        weeks = con.execute(
            "SELECT DISTINCT iso_week, MIN(week_start_date), MAX(week_end_date) FROM weekly_state_independent GROUP BY iso_week ORDER BY iso_week"
        ).fetchall()

    print(f"Generating {len(weeks)} weekly JSON files...")
    for iso_week, week_start, week_end in weeks:
        path = write_weekly_json(con, out_dir, iso_week, week_start, week_end)
        print(f"  Written {path.name} ({iso_week})")

    # Write latest symlink / copy
    if weeks:
        latest_week = weeks[-1][0]
        latest_src = out_dir / f"weekly_state_{latest_week}.json"
        latest_dst = out_dir / "weekly_state_latest.json"
        if latest_src.exists():
            import shutil

            shutil.copy(str(latest_src), str(latest_dst))
            print(f"  Copied latest to {latest_dst.name}")

    # Diff analysis
    if not args.skip_diff and args.foundation_db.exists():
        print("Running diff analysis against foundation DB...")
        try:
            report_path = run_diff_analysis(con, out_dir, args.foundation_db)
            print(f"  Written diff report to {report_path.name}")
        except Exception as e:
            print(f"  Diff analysis failed: {e}")

    con.close()
    print("Done.")


if __name__ == "__main__":
    main()
