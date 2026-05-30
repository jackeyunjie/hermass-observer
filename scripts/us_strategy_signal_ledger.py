#!/usr/bin/env python3
"""US stock strategy signal ledger.

Builds a normalized signal ledger for US stocks, equivalent to
scripts/strategy_signal_ledger.py for A-shares.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from us_strategy_signals import compute_us_signals_for_date, SIGNAL_META
from bootstrap_stats import safe_float

US_LEDGER_DB = ROOT / "outputs" / "us_stock" / "us_strategy_signals.duckdb"
US_FOUNDATION_DB = ROOT / "outputs" / "us_stock" / "us_foundation.duckdb"
OUT_DIR = ROOT / "outputs" / "us_stock" / "strategy_signals"


def ymd(d: str) -> str:
    return d.replace("-", "")


def create_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS us_strategy_signal_daily (
            signal_date DATE NOT NULL,
            stock_code VARCHAR NOT NULL,
            strategy_id VARCHAR NOT NULL,
            signal_type VARCHAR NOT NULL,
            signal_name VARCHAR NOT NULL,
            signal_strength DOUBLE NOT NULL,
            raw_signal VARCHAR NOT NULL,
            source_module VARCHAR NOT NULL,
            ef_count INTEGER,
            mn1_state_hex VARCHAR,
            w1_state_hex VARCHAR,
            d1_state_hex VARCHAR,
            mn1_state_score INTEGER,
            w1_state_score INTEGER,
            d1_state_score INTEGER,
            lifecycle_stage VARCHAR DEFAULT 'unknown',
            strategy_environment_fit VARCHAR DEFAULT 'pending',
            fit_reasons VARCHAR DEFAULT '',
            market_phase VARCHAR DEFAULT 'undetermined',
            research_only BOOLEAN NOT NULL DEFAULT true,
            created_at VARCHAR NOT NULL,
            PRIMARY KEY (signal_date, stock_code, strategy_id, raw_signal)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS us_signal_manifest (
            signal_date DATE PRIMARY KEY,
            generated_at VARCHAR NOT NULL,
            foundation_db VARCHAR NOT NULL,
            signal_count BIGINT NOT NULL,
            strategy_counts_json VARCHAR NOT NULL,
            research_only BOOLEAN NOT NULL DEFAULT true
        )
        """
    )


def compute_lifecycle_stage(row: dict[str, Any]) -> tuple[str, list[str]]:
    """Compute lifecycle stage for US stocks (simplified, no duration data)."""
    reasons = []
    d1 = row.get("d1_state_hex", "")
    w1 = row.get("w1_state_hex", "")
    mn1 = row.get("mn1_state_hex", "")
    ef_count = row.get("ef_count", 0) or 0
    d1_vol_bit = row.get("d1_volatility_bit", 0) or 0

    # Extract base from state score
    d1_score = abs(row.get("d1_state_score") or 0)
    d1_is_expansion = d1_score >= 8
    d1_has_trend = (d1_score >> 2) & 1 == 1

    if not d1_is_expansion:
        reasons.append("D1 in contraction")
        return "unknown", reasons

    if d1_vol_bit == 1:
        reasons.append("D1 volatility active")

    if ef_count >= 3:
        reasons.append("Three-period E/F resonance")
        if d1_vol_bit == 0:
            return "progression", reasons
        return "extension", reasons

    if ef_count >= 2:
        if d1_vol_bit == 0:
            reasons.append("Volatility stable")
            return "progression", reasons
        return "extension", reasons

    if d1_is_expansion and d1_has_trend:
        return "progression", reasons

    return "unknown", reasons


def compute_environment_fit(
    strategy_id: str,
    lifecycle_stage: str,
    reasons: list[str],
) -> tuple[str, str]:
    """Compute environment fit for US stocks."""
    best_stage = {
        "vcp": "progression",  # VCP best at emergence but we lack duration data
        "ma2560": "progression",
        "bollinger_bandit": "extension",
    }.get(strategy_id)

    if lifecycle_stage == "unknown" or not best_stage:
        return "pending", "；".join(reasons + [f"{strategy_id} pending"])

    if lifecycle_stage == best_stage:
        fit = "best_fit"
    elif strategy_id == "ma2560" and lifecycle_stage in ("progression",):
        fit = "fit"
    elif strategy_id == "bollinger_bandit" and lifecycle_stage == "progression":
        fit = "fit"
    else:
        fit = "weak_fit"

    return fit, "；".join(reasons + [f"{strategy_id} {fit}"])


def build_us_ledger(
    date_str: str,
    foundation_db: Path = US_FOUNDATION_DB,
    ledger_db: Path = US_LEDGER_DB,
    min_ef: int = 2,
) -> dict[str, Any]:
    """Build US stock strategy signal ledger for a given date."""
    ledger_db.parent.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(ledger_db))
    create_tables(con)

    # Clear existing data for this date
    con.execute("DELETE FROM us_strategy_signal_daily WHERE signal_date = CAST(? AS DATE)", (date_str,))
    con.execute("DELETE FROM us_signal_manifest WHERE signal_date = CAST(? AS DATE)", (date_str,))

    # Compute signals
    raw_signals = compute_us_signals_for_date(foundation_db, date_str, min_ef)

    # Enrich with lifecycle and fit
    rows = []
    for sig in raw_signals:
        lifecycle, lifecycle_reasons = compute_lifecycle_stage(sig)
        fit, fit_reasons = compute_environment_fit(sig["strategy_id"], lifecycle, lifecycle_reasons)

        rows.append({
            **sig,
            "lifecycle_stage": lifecycle,
            "strategy_environment_fit": fit,
            "fit_reasons": fit_reasons,
        })

    created_at = datetime.now(timezone.utc).isoformat()

    if rows:
        con.executemany(
            """
            INSERT OR REPLACE INTO us_strategy_signal_daily
            (signal_date, stock_code, strategy_id, signal_type, signal_name,
             signal_strength, raw_signal, source_module, ef_count,
             mn1_state_hex, w1_state_hex, d1_state_hex,
             mn1_state_score, w1_state_score, d1_state_score,
             lifecycle_stage, strategy_environment_fit, fit_reasons,
             research_only, created_at)
            VALUES (CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, true, ?)
            """,
            [
                (
                    r["signal_date"], r["stock_code"], r["strategy_id"],
                    r["signal_type"], r["signal_name"], r["signal_strength"],
                    r["raw_signal"], r["source_module"], r["ef_count"],
                    r.get("mn1_state_hex"), r.get("w1_state_hex"), r.get("d1_state_hex"),
                    r.get("mn1_state_score"), r.get("w1_state_score"), r.get("d1_state_score"),
                    r["lifecycle_stage"], r["strategy_environment_fit"], r["fit_reasons"],
                    created_at,
                )
                for r in rows
            ],
        )

    strategy_counts = {
        f"{sid}:{stype}": n
        for sid, stype, n in con.execute(
            """
            SELECT strategy_id, signal_type, COUNT(*)
            FROM us_strategy_signal_daily
            WHERE signal_date = CAST(? AS DATE)
            GROUP BY 1, 2 ORDER BY 1, 2
            """,
            (date_str,),
        ).fetchall()
    }

    con.execute(
        """
        INSERT OR REPLACE INTO us_signal_manifest
        VALUES (CAST(? AS DATE), ?, ?, ?, ?, true)
        """,
        (date_str, created_at, str(foundation_db), len(rows),
         json.dumps(strategy_counts, ensure_ascii=False, sort_keys=True)),
    )

    con.close()

    # Write JSON output
    out_json = OUT_DIR / f"us_signal_daily_{ymd(date_str)}.json"
    out_latest = OUT_DIR / "us_signal_daily_latest.json"
    payload = {
        "schema_version": "us_signal_daily_v1",
        "date": date_str,
        "generated_at": created_at,
        "foundation_db": str(foundation_db),
        "signal_count": len(rows),
        "strategy_counts": strategy_counts,
        "rows": rows,
        "research_only": True,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    out_json.write_text(text, encoding="utf-8")
    out_latest.write_text(text, encoding="utf-8")

    return {
        "ok": True,
        "date": date_str,
        "signal_count": len(rows),
        "strategy_counts": strategy_counts,
        "json": str(out_json),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--db", default=str(US_FOUNDATION_DB))
    parser.add_argument("--min-ef", type=int, default=2)
    args = parser.parse_args()
    result = build_us_ledger(args.date, Path(args.db), min_ef=args.min_ef)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
