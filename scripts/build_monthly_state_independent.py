#!/usr/bin/env python3
"""Build independent monthly (MN1) State cache from monthly_bars.

Unlike the D1-perspective MN1 state which uses D1 close vs MN1 SR,
this script computes MN1 state independently using monthly close
against monthly SR, monthly trend, and monthly volatility.

Outputs: outputs/state_cache/monthly_state_YYYYMM.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]


def sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def build_monthly_states_sql() -> str:
    """SQL to compute independent MN1 states from monthly_bars.

    Mirrors build_p116_foundation.py indicator and SR logic,
    but position uses monthly close vs monthly SR (not D1 close).
    """
    return """
    WITH
    -- 1. SqFractal 5, confirmed 3 bars later, forward-filled
    ordered AS (
      SELECT
        stock_code,
        month_start_date,
        month_end_date,
        open, high, low, close, volume,
        row_number() OVER (PARTITION BY stock_code ORDER BY month_end_date)::BIGINT AS tf_bar_index,
        lag(high, 1) OVER w AS high_lag_1,
        lag(high, 2) OVER w AS high_lag_2,
        lead(high, 1) OVER w AS high_lead_1,
        lead(high, 2) OVER w AS high_lead_2,
        lag(low, 1) OVER w AS low_lag_1,
        lag(low, 2) OVER w AS low_lag_2,
        lead(low, 1) OVER w AS low_lead_1,
        lead(low, 2) OVER w AS low_lead_2
      FROM monthly_bars
      WINDOW w AS (PARTITION BY stock_code ORDER BY month_end_date)
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
          PARTITION BY stock_code ORDER BY month_end_date
        ) AS fractal_resistance,
        lag(center_fractal_support, 3) OVER (
          PARTITION BY stock_code ORDER BY month_end_date
        ) AS fractal_support
      FROM center_fractal
    ),
    filled AS (
      SELECT
        *,
        last_value(fractal_resistance IGNORE NULLS) OVER (
          PARTITION BY stock_code ORDER BY month_end_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS sr_resistance,
        last_value(fractal_support IGNORE NULLS) OVER (
          PARTITION BY stock_code ORDER BY month_end_date
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
        w AS (PARTITION BY stock_code ORDER BY month_end_date),
        w20 AS (PARTITION BY stock_code ORDER BY month_end_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
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
        PARTITION BY stock_code ORDER BY month_end_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
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
        w14 AS (PARTITION BY stock_code ORDER BY month_end_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),
        w20prev AS (PARTITION BY stock_code ORDER BY month_end_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        w60prev AS (PARTITION BY stock_code ORDER BY month_end_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
    ),
    ranked AS (
      SELECT
        *,
        lag(bb_width_pct) OVER w AS prev_bb_width_pct,
        lag(atr_ratio_pct) OVER w AS prev_atr_ratio_pct,
        lag(adx14) OVER w AS prev_adx14,
        adx14 - lag(adx14, 3) OVER w AS adx_slope_3
      FROM ranked_base
      WINDOW w AS (PARTITION BY stock_code ORDER BY month_end_date)
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
    -- 4. State bits (independent MN1: monthly close vs monthly SR)
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
      month_start_date,
      month_end_date,
      close AS mn1_close,
      sr_support AS mn1_sr_support,
      sr_resistance AS mn1_sr_resistance,
      sr_support IS NOT NULL AND sr_resistance IS NOT NULL AS mn1_sr_ready,
      trend AS mn1_trend,
      volatility AS mn1_volatility,
      compression AS mn1_compression,
      base AS mn1_base,
      trend_bit AS mn1_trend_bit,
      position_bit AS mn1_position_bit,
      volatility_bit AS mn1_volatility_bit,
      bull_context AS mn1_bull_context,
      bear_context AS mn1_bear_context,
      state_magnitude AS mn1_state_magnitude,
      state_score AS mn1_state_score,
      CASE
        WHEN state_score < 0 THEN '-' || to_hex(abs(state_score)::UBIGINT)
        ELSE to_hex(state_score::UBIGINT)
      END AS mn1_state_hex,
      adx14 AS mn1_adx14,
      plus_di_14 AS mn1_plus_di_14,
      minus_di_14 AS mn1_minus_di_14,
      atr_ratio_pct AS mn1_atr_ratio_pct,
      bb_width_pct AS mn1_bb_width_pct,
      tf_bar_index
    FROM scored
    ORDER BY stock_code, month_end_date
    """


def write_monthly_json(
    con: duckdb.DuckDBPyConnection,
    out_dir: Path,
    ym: str,
    month_start: date,
    month_end: date,
) -> Path:
    """Write a single monthly_state_YYYYMM.json file."""
    rows = con.execute(
        """
        SELECT
          stock_code,
          mn1_state_score,
          mn1_state_hex,
          mn1_close,
          mn1_sr_support,
          mn1_sr_resistance,
          mn1_sr_ready,
          mn1_trend,
          mn1_volatility,
          mn1_compression,
          mn1_base,
          mn1_trend_bit,
          mn1_position_bit,
          mn1_volatility_bit,
          mn1_adx14,
          mn1_plus_di_14,
          mn1_minus_di_14,
          mn1_atr_ratio_pct,
          mn1_bb_width_pct
        FROM monthly_state_independent
        WHERE ym = ?
        ORDER BY stock_code
        """,
        (ym,),
    ).fetchall()

    data = []
    for row in rows:
        data.append({
            "stock_code": row[0],
            "mn1_state_score": row[1],
            "mn1_state_hex": row[2],
            "mn1_close": row[3],
            "mn1_sr_support": row[4],
            "mn1_sr_resistance": row[5],
            "mn1_sr_ready": row[6],
            "mn1_trend": row[7],
            "mn1_volatility": row[8],
            "mn1_compression": row[9],
            "mn1_base": row[10],
            "mn1_trend_bit": row[11],
            "mn1_position_bit": row[12],
            "mn1_volatility_bit": row[13],
            "mn1_adx14": row[14],
            "mn1_plus_di_14": row[15],
            "mn1_minus_di_14": row[16],
            "mn1_atr_ratio_pct": row[17],
            "mn1_bb_width_pct": row[18],
        })

    result = {
        "schema_version": "monthly_state_independent_v1",
        "ym": ym,
        "month_start_date": month_start.isoformat(),
        "month_end_date": month_end.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "outputs/monthly_bars/monthly_bars.duckdb",
        "total_stocks": len(data),
        "data": data,
    }

    path = out_dir / f"monthly_state_{ym}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_diff_analysis(
    con: duckdb.DuckDBPyConnection,
    out_dir: Path,
    foundation_db: Path,
) -> Path:
    """Compare independent MN1 state with D1-perspective MN1 state and output report."""
    con.execute(f"ATTACH '{sql_path(foundation_db)}' AS foundation (READ_ONLY)")

    # 1. Month-end diff (closest to independent MN1 because month-end close = monthly close)
    month_end_rows = con.execute(
        """
        SELECT
          i.ym,
          i.mn1_state_hex AS independent_hex,
          i.mn1_state_score AS independent_score,
          f.mn1_state_hex AS d1_perspective_hex,
          f.mn1_state_score AS d1_perspective_score,
          i.stock_code,
          i.mn1_close,
          f.d1_close
        FROM monthly_state_independent i
        LEFT JOIN foundation.d1_perspective_state f
          ON f.stock_code = i.stock_code
          AND f.state_date = i.month_end_date
        WHERE i.ym IN (
          SELECT DISTINCT ym FROM monthly_state_independent
          ORDER BY ym DESC
          LIMIT 48
        )
        ORDER BY i.ym DESC, i.stock_code
        """
    ).fetchall()

    # 2. Mid-month diff (pick ~15th of month or nearest trading day) for position divergence analysis
    mid_month_rows = con.execute(
        """
        WITH mid_dates AS (
          SELECT DISTINCT
            stock_code,
            ym,
            -- pick trading day nearest to 15th
            (SELECT state_date FROM foundation.d1_perspective_state
             WHERE stock_code = i.stock_code
               AND state_date BETWEEN i.month_start_date AND i.month_end_date
             ORDER BY abs(extract('day' FROM state_date) - 15)
             LIMIT 1) AS mid_date
          FROM monthly_state_independent i
          WHERE i.ym IN (
            SELECT DISTINCT ym FROM monthly_state_independent
            ORDER BY ym DESC
            LIMIT 48
          )
        )
        SELECT
          i.ym,
          i.mn1_state_hex AS independent_hex,
          i.mn1_state_score AS independent_score,
          f.mn1_state_hex AS d1_perspective_hex,
          f.mn1_state_score AS d1_perspective_score,
          i.stock_code,
          i.mn1_close,
          f.d1_close,
          f.state_date
        FROM monthly_state_independent i
        JOIN mid_dates md
          ON md.stock_code = i.stock_code AND md.ym = i.ym
        LEFT JOIN foundation.d1_perspective_state f
          ON f.stock_code = i.stock_code
          AND f.state_date = md.mid_date
        ORDER BY i.ym DESC, i.stock_code
        """
    ).fetchall()

    from collections import defaultdict

    def analyze(rows, label):
        stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "total": 0,
            "same_hex": 0,
            "same_score": 0,
            "diff_by_bits": 0,
            "diff_by_sign_only": 0,
            "diff_by_magnitude_only": 0,
            "missing_in_foundation": 0,
            "score_diff_distribution": defaultdict(int),
            "hex_transition_counts": defaultdict(int),
            "position_diff_count": 0,
        })

        for row in rows:
            ym, ind_hex, ind_score, d1_hex, d1_score, stock_code, mn1_close, d1_close = row[:8]
            st = stats[ym]
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
                # Check if position bit specifically differs
                if ind_bits[2] != d1_bits[2]:
                    st["position_diff_count"] += 1
            elif (ind_score or 0) * (d1_score or 0) < 0:
                st["diff_by_sign_only"] += 1
            elif abs(ind_score or 0) != abs(d1_score or 0):
                st["diff_by_magnitude_only"] += 1

            transition = f"{d1_hex or 'NULL'}->{ind_hex}"
            st["hex_transition_counts"][transition] += 1

        for st in stats.values():
            st["score_diff_distribution"] = dict(st["score_diff_distribution"])
            st["hex_transition_counts"] = dict(
                sorted(st["hex_transition_counts"].items(), key=lambda x: -x[1])[:20]
            )
        return stats

    month_end_stats = analyze(month_end_rows, "month_end")
    mid_month_stats = analyze(mid_month_rows, "mid_month")

    report = {
        "schema_version": "monthly_state_diff_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "foundation_db": str(foundation_db),
        "note": "Independent MN1 state vs D1-perspective MN1 state (from d1_perspective_state)",
        "month_end": dict(sorted(month_end_stats.items(), reverse=True)),
        "mid_month": dict(sorted(mid_month_stats.items(), reverse=True)),
    }

    (out_dir / "calibration").mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "calibration" / "MONTHLY_STATE_DIVERGENCE_REPORT.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Human-readable markdown
    lines = [
        "# Monthly State Independent vs D1-Perspective Divergence Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Foundation: {foundation_db}",
        "",
        "## Methodology",
        "",
        "- **Independent MN1**: computed from monthly bars (monthly close vs monthly SR).",
        "- **D1-perspective MN1**: from `d1_perspective_state` (daily close vs monthly SR).",
        "- **Month-end comparison**: uses the last trading day of the month, where daily close ≈ monthly close. This is the fairest comparison.",
        "- **Mid-month comparison**: uses the trading day closest to the 15th of the month, where daily close can deviate significantly from monthly close.",
        "",
        "## Month-End Comparison (Closest to Independent)",
        "",
    ]

    for ym, st in sorted(month_end_stats.items(), reverse=True):
        total = st["total"]
        if total == 0:
            continue
        same_pct = round(st["same_hex"] / total * 100, 2)
        pos_pct = round(st.get("position_diff_count", 0) / total * 100, 2) if st.get("position_diff_count") else 0.0
        lines.append(f"### {ym}")
        lines.append(f"- Total stocks: {total}")
        lines.append(f"- Same hex: {st['same_hex']} ({same_pct}%)")
        lines.append(f"- Same score (incl sign): {st['same_score']}")
        lines.append(f"- Diff by bits: {st['diff_by_bits']}")
        lines.append(f"- Diff by sign only: {st['diff_by_sign_only']}")
        lines.append(f"- Diff by magnitude only: {st['diff_by_magnitude_only']}")
        lines.append(f"- Position-bit diff: {st.get('position_diff_count', 0)} ({pos_pct}%)")
        lines.append(f"- Missing in foundation: {st['missing_in_foundation']}")
        lines.append("")

    lines.append("## Mid-Month Comparison (Position Divergence Expected)")
    lines.append("")

    for ym, st in sorted(mid_month_stats.items(), reverse=True):
        total = st["total"]
        if total == 0:
            continue
        same_pct = round(st["same_hex"] / total * 100, 2)
        pos_pct = round(st.get("position_diff_count", 0) / total * 100, 2) if st.get("position_diff_count") else 0.0
        lines.append(f"### {ym}")
        lines.append(f"- Total stocks: {total}")
        lines.append(f"- Same hex: {st['same_hex']} ({same_pct}%)")
        lines.append(f"- Same score (incl sign): {st['same_score']}")
        lines.append(f"- Diff by bits: {st['diff_by_bits']}")
        lines.append(f"- Diff by sign only: {st['diff_by_sign_only']}")
        lines.append(f"- Position-bit diff: {st.get('position_diff_count', 0)} ({pos_pct}%)")
        lines.append(f"- Missing in foundation: {st['missing_in_foundation']}")
        lines.append("")

    md_path = out_dir / "calibration" / "MONTHLY_STATE_DIVERGENCE_REPORT.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    return md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build independent monthly MN1 state cache")
    parser.add_argument("--monthly-db", type=Path, default=ROOT / "outputs" / "monthly_bars" / "monthly_bars.duckdb")
    parser.add_argument("--foundation-db", type=Path, default=ROOT / "outputs" / "p116_foundation_20260522" / "p116_foundation.duckdb")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "outputs" / "state_cache")
    parser.add_argument("--ym", type=str, default=None, help="YYYYMM like 202605. If omitted, generates all months.")
    parser.add_argument("--skip-diff", action="store_true", help="Skip diff analysis against foundation DB")
    args = parser.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Connecting to {args.monthly_db}")
    con = duckdb.connect(str(args.monthly_db))
    con.execute("SET threads=4")

    print("Computing independent MN1 states...")
    con.execute("DROP TABLE IF EXISTS monthly_state_independent")
    sql = build_monthly_states_sql()
    con.execute(f"CREATE TABLE monthly_state_independent AS {sql}")
    con.execute("ALTER TABLE monthly_state_independent ADD COLUMN ym VARCHAR")
    con.execute("UPDATE monthly_state_independent SET ym = strftime('%Y%m', month_end_date)")

    total_rows = con.execute("SELECT COUNT(*) FROM monthly_state_independent").fetchone()[0]
    print(f"Total independent MN1 state rows: {total_rows}")

    if args.ym:
        months = con.execute(
            "SELECT DISTINCT ym, MIN(month_start_date), MAX(month_end_date) FROM monthly_state_independent WHERE ym = ? GROUP BY ym",
            (args.ym,),
        ).fetchall()
    else:
        months = con.execute(
            "SELECT DISTINCT ym, MIN(month_start_date), MAX(month_end_date) FROM monthly_state_independent GROUP BY ym ORDER BY ym"
        ).fetchall()

    print(f"Generating {len(months)} monthly JSON files...")
    for ym, month_start, month_end in months:
        path = write_monthly_json(con, out_dir, ym, month_start, month_end)
        print(f"  Written {path.name} ({ym})")

    if months:
        latest_ym = months[-1][0]
        latest_src = out_dir / f"monthly_state_{latest_ym}.json"
        latest_dst = out_dir / "monthly_state_latest.json"
        if latest_src.exists():
            import shutil
            shutil.copy(str(latest_src), str(latest_dst))
            print(f"  Copied latest to {latest_dst.name}")

    if not args.skip_diff and args.foundation_db.exists():
        print("Running diff analysis against foundation DB...")
        try:
            report_path = run_diff_analysis(con, out_dir, args.foundation_db)
            print(f"  Written diff report to {report_path}")
        except Exception as e:
            print(f"  Diff analysis failed: {e}")
            import traceback
            traceback.print_exc()

    con.close()
    print("Done.")


if __name__ == "__main__":
    main()
