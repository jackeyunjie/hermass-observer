#!/usr/bin/env python3
"""Validate native W1 State against D1-perspective W1 State from foundation DB.

Compares weekly_state_YYYYWww.json (native W1) with d1_perspective_state
(D1-perspective W1) for the last trading day of each week.

Outputs a divergence analysis report.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "outputs" / "state_cache"


def iso_week_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}W{iso.week:02d}"


def load_weekly_state(week_key: str, cache_dir: Path = CACHE_DIR) -> dict[str, dict] | None:
    path = cache_dir / f"weekly_state_{week_key}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return {s["stock_code"]: s for s in data.get("stocks", [])}


def validate_all_weeks(
    foundation_db: Path,
    cache_dir: Path = CACHE_DIR,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Run divergence analysis across all overlapping weeks."""

    con = duckdb.connect(str(foundation_db), read_only=True)

    # Get all (week_end_date, stock_code, w1_state_hex) from foundation
    # For each week, we take the LAST trading day (Friday or last day before holiday)
    rows = con.execute("""
        SELECT
            state_date,
            stock_code,
            w1_state_hex,
            w1_state_score,
            w1_base,
            w1_trend_bit,
            w1_position_bit,
            w1_volatility_bit,
            d1_close,
            w1_sr_support,
            w1_sr_resistance
        FROM d1_perspective_state
        WHERE state_date >= '2018-05-14'
        ORDER BY stock_code, state_date
    """).fetchall()
    con.close()

    # Group by ISO week
    d1_view_by_week: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        (
            state_date,
            stock_code,
            w1_hex,
            w1_score,
            w1_base,
            w1_trend,
            w1_pos,
            w1_vol,
            d1_close,
            w1_sup,
            w1_res,
        ) = row
        wk = iso_week_key(state_date)
        # For each week, keep the LAST trading day (max date)
        existing = d1_view_by_week[wk].get(stock_code)
        if existing is None or state_date > date.fromisoformat(existing["state_date"]):
            d1_view_by_week[wk][stock_code] = {
                "state_date": state_date.isoformat(),
                "w1_state_hex": w1_hex,
                "w1_state_score": w1_score,
                "w1_base": w1_base,
                "w1_trend": w1_trend,
                "w1_position": w1_pos,
                "w1_volatility": w1_vol,
                "d1_close": round(d1_close, 4) if d1_close else None,
                "w1_sr_support": round(w1_sup, 4) if w1_sup else None,
                "w1_sr_resistance": round(w1_res, 4) if w1_res else None,
            }

    # Compare week by week
    weekly_stats: dict[str, dict[str, Any]] = {}
    overall = {
        "total_comparisons": 0,
        "full_divergence_count": 0,
        "position_divergence_count": 0,
        "trend_divergence_count": 0,
        "volatility_divergence_count": 0,
        "base_divergence_count": 0,
        "symbol_divergence_count": 0,
        "both_ef_count": 0,
        "both_non_ef_count": 0,
        "ef_flips": 0,
    }

    for wk in sorted(d1_view_by_week.keys()):
        native = load_weekly_state(wk, cache_dir)
        if native is None:
            continue

        d1_week = d1_view_by_week[wk]
        stats = {
            "week": wk,
            "total": 0,
            "matched": 0,
            "full_divergence": 0,
            "position_divergence": 0,
            "trend_divergence": 0,
            "volatility_divergence": 0,
            "base_divergence": 0,
            "symbol_divergence": 0,
            "both_ef": 0,
            "both_non_ef": 0,
            "ef_flips": 0,
            "divergence_examples": [],
        }

        for stock_code, d1_rec in d1_week.items():
            nat_rec = native.get(stock_code)
            if nat_rec is None:
                continue

            stats["total"] += 1
            d1_hex = d1_rec["w1_state_hex"] or ""
            nat_hex = nat_rec.get("w1_state_hex") or ""

            d1_score = d1_rec["w1_state_score"] or 0
            nat_score = nat_rec.get("w1_state") or 0

            # Parse bits from hex
            def decode_bits(score: int) -> tuple[int, int, int, int]:
                abs_score = abs(score)
                base = 0 if abs_score < 8 else 8
                rem = abs_score - base
                t = 1 if rem >= 4 else 0
                rem -= t * 4
                p = 1 if rem >= 2 else 0
                rem -= p * 2
                v = rem
                return base, t, p, v

            d1_base, d1_trend, d1_pos, d1_vol = decode_bits(d1_score)
            nat_base, nat_trend, nat_pos, nat_vol = decode_bits(nat_score)

            # Symbol divergence (sign)
            d1_sym = 1 if d1_score >= 0 else -1
            nat_sym = 1 if nat_score >= 0 else -1

            full_div = d1_hex != nat_hex
            pos_div = d1_pos != nat_pos
            trend_div = d1_trend != nat_trend
            vol_div = d1_vol != nat_vol
            base_div = d1_base != nat_base
            sym_div = d1_sym != nat_sym

            if full_div:
                stats["full_divergence"] += 1
                if len(stats["divergence_examples"]) < 5:
                    stats["divergence_examples"].append(
                        {
                            "stock_code": stock_code,
                            "d1_view": d1_hex,
                            "native": nat_hex,
                            "d1_bits": f"B{d1_base}T{d1_trend}P{d1_pos}V{d1_vol}",
                            "native_bits": f"B{nat_base}T{nat_trend}P{nat_pos}V{nat_vol}",
                            "d1_close": d1_rec["d1_close"],
                            "w1_close": nat_rec.get("w1_close"),
                            "w1_sr_support": d1_rec["w1_sr_support"],
                            "w1_sr_resistance": d1_rec["w1_sr_resistance"],
                        }
                    )
            else:
                stats["matched"] += 1

            if pos_div:
                stats["position_divergence"] += 1
            if trend_div:
                stats["trend_divergence"] += 1
            if vol_div:
                stats["volatility_divergence"] += 1
            if base_div:
                stats["base_divergence"] += 1
            if sym_div:
                stats["symbol_divergence"] += 1

            # E/F analysis
            d1_ef = d1_hex in ("E", "F")
            nat_ef = nat_hex in ("E", "F")
            if d1_ef and nat_ef:
                stats["both_ef"] += 1
            elif not d1_ef and not nat_ef:
                stats["both_non_ef"] += 1
            elif d1_ef != nat_ef:
                stats["ef_flips"] += 1

        # Compute rates
        total = stats["total"]
        if total > 0:
            stats["full_divergence_rate"] = round(stats["full_divergence"] / total, 4)
            stats["position_divergence_rate"] = round(stats["position_divergence"] / total, 4)
            stats["trend_divergence_rate"] = round(stats["trend_divergence"] / total, 4)
            stats["volatility_divergence_rate"] = round(stats["volatility_divergence"] / total, 4)
            stats["base_divergence_rate"] = round(stats["base_divergence"] / total, 4)
            stats["symbol_divergence_rate"] = round(stats["symbol_divergence"] / total, 4)
            stats["ef_flip_rate"] = round(stats["ef_flips"] / total, 4)
        else:
            stats["full_divergence_rate"] = 0.0
            stats["position_divergence_rate"] = 0.0
            stats["trend_divergence_rate"] = 0.0
            stats["volatility_divergence_rate"] = 0.0
            stats["base_divergence_rate"] = 0.0
            stats["symbol_divergence_rate"] = 0.0
            stats["ef_flip_rate"] = 0.0

        weekly_stats[wk] = stats

        # Aggregate overall
        overall["total_comparisons"] += total
        overall["full_divergence_count"] += stats["full_divergence"]
        overall["position_divergence_count"] += stats["position_divergence"]
        overall["trend_divergence_count"] += stats["trend_divergence"]
        overall["volatility_divergence_count"] += stats["volatility_divergence"]
        overall["base_divergence_count"] += stats["base_divergence"]
        overall["symbol_divergence_count"] += stats["symbol_divergence"]
        overall["both_ef_count"] += stats["both_ef"]
        overall["both_non_ef_count"] += stats["both_non_ef"]
        overall["ef_flips"] += stats["ef_flips"]

    # Compute overall rates
    total = overall["total_comparisons"]
    if total > 0:
        overall["full_divergence_rate"] = round(overall["full_divergence_count"] / total, 4)
        overall["position_divergence_rate"] = round(overall["position_divergence_count"] / total, 4)
        overall["trend_divergence_rate"] = round(overall["trend_divergence_count"] / total, 4)
        overall["volatility_divergence_rate"] = round(overall["volatility_divergence_count"] / total, 4)
        overall["base_divergence_rate"] = round(overall["base_divergence_count"] / total, 4)
        overall["symbol_divergence_rate"] = round(overall["symbol_divergence_count"] / total, 4)
        overall["ef_flip_rate"] = round(overall["ef_flips"] / total, 4)

    # Day-of-week analysis: use the weekday of the last trading day in each week
    # (All are Fridays or pre-holiday last days, effectively treat as Friday for weekly comparison)
    by_weekday = defaultdict(lambda: {"total": 0, "full_div": 0, "position_div": 0})
    for wk, stats in weekly_stats.items():
        # Parse week to get approximate Friday date
        year, week_num = int(wk[:4]), int(wk[5:])
        # ISO week starts on Monday; Friday is +4 days from Monday
        # We just label all as "friday" since we're comparing end-of-week
        day_label = "friday"
        by_weekday[day_label]["total"] += stats["total"]
        by_weekday[day_label]["full_div"] += stats["full_divergence"]
        by_weekday[day_label]["position_div"] += stats["position_divergence"]

    for day_label in by_weekday:
        d = by_weekday[day_label]
        if d["total"] > 0:
            d["full_rate"] = round(d["full_div"] / d["total"], 4)
            d["position_rate"] = round(d["position_div"] / d["total"], 4)

    # Build worst weeks
    worst_weeks = sorted(
        [s for s in weekly_stats.values() if s["total"] > 0],
        key=lambda x: x["full_divergence_rate"],
        reverse=True,
    )[:10]

    result = {
        "schema_version": "weekly_state_validation_v1",
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "foundation_db": str(foundation_db),
        "overall": overall,
        "by_weekday": dict(by_weekday),
        "worst_weeks": [
            {
                "week": w["week"],
                "total": w["total"],
                "full_divergence_rate": w["full_divergence_rate"],
                "position_divergence_rate": w["position_divergence_rate"],
                "examples": w["divergence_examples"],
            }
            for w in worst_weeks
        ],
        "weekly_summary": [
            {
                "week": w["week"],
                "total": w["total"],
                "matched": w["matched"],
                "full_divergence_rate": w["full_divergence_rate"],
                "position_divergence_rate": w["position_divergence_rate"],
                "trend_divergence_rate": w["trend_divergence_rate"],
                "volatility_divergence_rate": w["volatility_divergence_rate"],
                "base_divergence_rate": w["base_divergence_rate"],
                "symbol_divergence_rate": w["symbol_divergence_rate"],
                "ef_flip_rate": w["ef_flip_rate"],
            }
            for w in weekly_stats.values()
        ],
    }

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate native W1 State against D1-perspective")
    parser.add_argument("--foundation-db", type=Path, required=True, help="Path to foundation DuckDB")
    parser.add_argument(
        "--cache-dir", type=Path, default=CACHE_DIR, help="Directory with weekly_state_*.json"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "outputs" / "calibration" / "weekly_state_validation.json",
        help="Output report path",
    )
    args = parser.parse_args()

    result = validate_all_weeks(
        foundation_db=args.foundation_db,
        cache_dir=args.cache_dir,
        out_path=args.out,
    )

    o = result["overall"]
    print("=" * 60)
    print("Weekly State Validation Report")
    print("=" * 60)
    print(f"Total comparisons:    {o['total_comparisons']:,}")
    print(f"Full divergence:      {o['full_divergence_count']:,} ({o['full_divergence_rate'] * 100:.2f}%)")
    print(
        f"Position divergence:  {o['position_divergence_count']:,} ({o['position_divergence_rate'] * 100:.2f}%)"
    )
    print(f"Trend divergence:     {o['trend_divergence_count']:,} ({o['trend_divergence_rate'] * 100:.2f}%)")
    print(
        f"Volatility divergence:{o['volatility_divergence_count']:,} ({o['volatility_divergence_rate'] * 100:.2f}%)"
    )
    print(f"Base divergence:      {o['base_divergence_count']:,} ({o['base_divergence_rate'] * 100:.2f}%)")
    print(
        f"Symbol divergence:    {o['symbol_divergence_count']:,} ({o['symbol_divergence_rate'] * 100:.2f}%)"
    )
    print(f"EF flips:             {o['ef_flips']:,} ({o['ef_flip_rate'] * 100:.2f}%)")
    print(f"Both EF:              {o['both_ef_count']:,}")
    print(f"Both non-EF:          {o['both_non_ef_count']:,}")
    print(f"Report written to:    {args.out}")


if __name__ == "__main__":
    main()
