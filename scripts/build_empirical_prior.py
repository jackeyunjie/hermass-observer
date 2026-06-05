#!/usr/bin/env python3
"""Build empirical_prior statistics from foundation DB history.

MVP scope: 144/169/200 W1 MA states (SQL-computable from timeframe_bars).
Future indicators (RSIOMA, ADXADX, Kaufman, BB20/BB50, Pivot) require
pre-computing indicator values before state labeling.

Usage:
    python3 scripts/build_empirical_prior.py \
        --indicator 144_169_200 --timeframe W1 \
        --db outputs/p116_foundation_20260602/p116_foundation.duckdb \
        --priors strategy_rules/priors/144_169_200_w1_priors.json \
        --dry-run

    # Apply updates (writes back to priors file)
    python3 scripts/build_empirical_prior.py \
        --indicator 144_169_200 --timeframe W1 \
        --db outputs/p116_foundation_20260602/p116_foundation.duckdb \
        --priors strategy_rules/priors/144_169_200_w1_priors.json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent

# ── SQL state labelers (indicator-specific) ────────────────────────────

MA144_169_200_W1_SQL = """
WITH weekly_ma AS (
    SELECT
        stock_code,
        available_date AS state_date,
        close,
        AVG(close) OVER w144 AS ma144,
        AVG(close) OVER w169 AS ma169,
        AVG(close) OVER w200 AS ma200
    FROM timeframe_bars
    WHERE timeframe = 'W1'
    WINDOW
        w144 AS (PARTITION BY stock_code ORDER BY available_date
                 ROWS BETWEEN 143 PRECEDING AND CURRENT ROW),
        w169 AS (PARTITION BY stock_code ORDER BY available_date
                 ROWS BETWEEN 168 PRECEDING AND CURRENT ROW),
        w200 AS (PARTITION BY stock_code ORDER BY available_date
                 ROWS BETWEEN 199 PRECEDING AND CURRENT ROW)
),
labeled AS (
    SELECT *,
        LAG(ma144) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_ma144,
        LAG(ma169) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_ma169,
        -- State priority: W7 (squeeze) > W8 (cross) > W1-W6 (ordering)
        CASE
            -- W7: three-line squeeze (spacing < 2%)
            WHEN ma169 > 0 AND ma200 > 0
                 AND ABS(ma144 - ma169) / ma169 < 0.02
                 AND ABS(ma169 - ma200) / ma200 < 0.02
                THEN 'W7'
            -- W8: 144/169 crossover (golden/dead cross)
            WHEN prev_ma144 IS NOT NULL AND prev_ma169 IS NOT NULL
                 AND (
                     (ma144 > ma169 AND prev_ma144 <= prev_ma169)
                     OR (ma144 < ma169 AND prev_ma144 >= prev_ma169)
                 )
                THEN 'W8'
            -- W1: bullish alignment
            WHEN ma144 > ma169 AND ma169 > ma200 THEN 'W1'
            -- W2: cautious bullish
            WHEN ma144 > ma200 AND ma200 > ma169 THEN 'W2'
            -- W3: bullish pending
            WHEN ma169 > ma144 AND ma144 > ma200 THEN 'W3'
            -- W4: neutral
            WHEN ma169 > ma200 AND ma200 > ma144 THEN 'W4'
            -- W5: avoid long
            WHEN ma200 > ma144 AND ma144 > ma169 THEN 'W5'
            -- W6: strong avoid long
            WHEN ma200 > ma169 AND ma169 > ma144 THEN 'W6'
            ELSE NULL
        END AS state_id
    FROM weekly_ma
    WHERE ma144 > 0 AND ma169 > 0 AND ma200 > 0
),
outcomes AS (
    SELECT *,
        LEAD(close, 5)
            OVER (PARTITION BY stock_code ORDER BY state_date) / close - 1 AS r5,
        LEAD(close, 20)
            OVER (PARTITION BY stock_code ORDER BY state_date) / close - 1 AS r20
    FROM labeled
    WHERE state_id IS NOT NULL
)
SELECT
    state_id,
    COUNT(*) AS sample_count,
    ROUND(AVG(r5) * 100, 3) AS avg_return_5d_pct,
    ROUND(AVG(r20) * 100, 3) AS avg_return_20d_pct,
    ROUND(SUM(CASE WHEN r5 > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 4) AS win_rate_5d,
    ROUND(SUM(CASE WHEN r20 > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 4) AS win_rate_20d,
    ROUND(AVG(CASE WHEN r20 < 0 THEN -r20 ELSE 0 END) * 100, 3) AS avg_loss_20d_pct,
    ROUND(MIN(r20) * 100, 3) AS worst_r20_pct
FROM outcomes
GROUP BY state_id
ORDER BY state_id
"""

STATE_SQL = {
    ("144_169_200", "W1"): MA144_169_200_W1_SQL,
}


def compute_stats(db_path, indicator, timeframe):
    """Run SQL to compute empirical stats for a given indicator/timeframe."""
    key = (indicator, timeframe)
    if key not in STATE_SQL:
        raise ValueError(f"No SQL state labeler for {indicator}/{timeframe}. "
                         f"Supported: {list(STATE_SQL.keys())}")

    sql = STATE_SQL[key]
    con = duckdb.connect(db_path, read_only=True)
    try:
        df = con.execute(sql).fetchdf()
        return df
    finally:
        con.close()


def confidence_from_n(n):
    """Map sample count to confidence tier."""
    if n >= 1000:
        return "high"
    if n >= 200:
        return "medium"
    return "low"


def update_priors(priors_path, stats_df, dry_run=False):
    """Update prior_probability fields in a priors JSON file."""
    with open(priors_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    updated = 0
    priors = data.get("priors", {})
    meta = data.get("_meta", {})

    for _, row in stats_df.iterrows():
        sid = row["state_id"]
        if sid not in priors:
            print(f"  [WARN] State {sid} not found in priors file, skipping")
            continue

        p = priors[sid]["prior_probability"]
        n = int(row["sample_count"])

        p["evidence_level"] = "empirical_prior"
        p["evidence_source"] = "foundation_db_backtest"
        p["confidence"] = confidence_from_n(n)
        p["sample_count"] = n
        p["win_rate_5d"] = float(row["win_rate_5d"])
        p["win_rate_20d"] = float(row["win_rate_20d"])
        p["avg_return_5d_pct"] = float(row["avg_return_5d_pct"])
        p["avg_return_20d_pct"] = float(row["avg_return_20d_pct"])
        p["false_breakout_rate"] = round(1.0 - float(row["win_rate_20d"]), 4)
        p["max_drawdown_pct"] = float(row["worst_r20_pct"])
        p["promotion_required"] = (
            "empirical_prior → validated_prior (needs cross-validation)"
            if n >= 500 else
            "insufficient_samples (needs n>=500 for promotion)"
        )

        updated += 1

    meta["evidence_level"] = "empirical_prior"
    meta["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    meta["empirical_note"] = (
        f"Backed by foundation DB backtest. "
        f"States updated: {updated}/{len(priors)}. "
        f"Total observations: {int(stats_df['sample_count'].sum())}."
    )

    if dry_run:
        print(f"  [DRY-RUN] Would update {updated}/{len(priors)} states")
        for sid in priors:
            p = priors[sid]["prior_probability"]
            if p.get("evidence_level") == "empirical_prior":
                print(f"    {sid}: n={p['sample_count']}, wr20={p['win_rate_20d']:.1%}, "
                      f"avg_r20={p['avg_return_20d_pct']:.2f}%")
        return

    with open(priors_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Written: {priors_path} ({updated}/{len(priors)} states updated)")


def main():
    parser = argparse.ArgumentParser(
        description="Compute empirical_prior from foundation DB history"
    )
    parser.add_argument("--indicator", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--db", default=str(ROOT / "outputs" / "p116_foundation_20260602" / "p116_foundation.duckdb"))
    parser.add_argument("--priors", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"Computing empirical_prior for {args.indicator}/{args.timeframe}")
    print(f"  DB: {args.db}")

    stats = compute_stats(args.db, args.indicator, args.timeframe)
    print(f"  States found: {len(stats)}")
    print(f"  Total observations: {int(stats['sample_count'].sum())}")
    print()
    print(stats.to_string(index=False))
    print()

    update_priors(args.priors, stats, dry_run=args.dry_run)

    # Summary
    print("\n" + "=" * 60)
    print("Empirical Prior Summary")
    print("=" * 60)
    for _, row in stats.iterrows():
        sid = row["state_id"]
        n = int(row["sample_count"])
        wr20 = float(row["win_rate_20d"])
        avg20 = float(row["avg_return_20d_pct"])
        conf = confidence_from_n(n)
        print(f"  {sid:4s}  n={n:>6,}  wr20={wr20:>6.1%}  avg20={avg20:>7.2f}%  [{conf}]")


if __name__ == "__main__":
    sys.exit(main() or 0)
