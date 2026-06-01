#!/usr/bin/env python3
"""US stock forward observation ledger.

Records strategy signals with future return labels using SPY as benchmark.
Equivalent to scripts/forward_observation_ledger.py for A-shares.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
US_FOUNDATION_DB = ROOT / "outputs" / "us_stock" / "us_foundation.duckdb"
US_SIGNAL_DIR = ROOT / "outputs" / "us_stock" / "strategy_signals"
OUT_DIR = ROOT / "outputs" / "us_stock" / "forward_observation"


def ymd(d: str) -> str:
    return d.replace("-", "")


def load_signal_payload(date_str: str) -> dict[str, Any]:
    path = US_SIGNAL_DIR / f"us_signal_daily_{ymd(date_str)}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def load_price_data(
    foundation_db: Path,
    stock_codes: list[str],
    start_date: str,
    end_date: str,
) -> dict[str, list[tuple[str, float]]]:
    """Load price data for forward return calculation."""
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        codes_str = ",".join(f"'{c}'" for c in stock_codes)
        rows = con.execute(
            f"""
            SELECT stock_code, CAST(date AS VARCHAR), close
            FROM daily_bars
            WHERE stock_code IN ({codes_str})
              AND date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
            ORDER BY stock_code, date
            """,
            (start_date, end_date),
        ).fetchall()

        by_code: dict[str, list[tuple[str, float]]] = {}
        for code, d, close in rows:
            by_code.setdefault(code, []).append((str(d), float(close)))
        return by_code
    finally:
        con.close()


def compute_forward_return(
    price_series: list[tuple[str, float]],
    signal_date: str,
    window: int,
) -> tuple[float | None, str | None, float | None]:
    """Compute forward return for a given window."""
    dates = [p[0] for p in price_series]
    try:
        idx = dates.index(signal_date)
    except ValueError:
        return None, None, None

    if idx + window >= len(price_series):
        return None, None, None

    target_date, target_close = price_series[idx + window]
    _, entry_close = price_series[idx]
    if entry_close <= 0:
        return None, None, None

    ret = (target_close - entry_close) / entry_close
    return ret, target_date, target_close


def build_observations(
    date_str: str,
    foundation_db: Path,
    windows: list[int] = [5, 10, 20],
) -> dict[str, Any]:
    """Build forward observation records for a given date."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    payload = load_signal_payload(date_str)
    rows = payload.get("rows", [])
    if not rows:
        return {"date": date_str, "total": 0, "labeled": 0, "pending": len(rows)}

    # Load price data for all stocks + SPY
    stock_codes = list(set(r["stock_code"] for r in rows))
    if "SPY" not in stock_codes:
        stock_codes.append("SPY")

    max_window = max(windows)
    end_date_dt = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=max_window * 3 + 30)
    price_data = load_price_data(foundation_db, stock_codes, date_str, end_date_dt.strftime("%Y-%m-%d"))

    spy_prices = price_data.get("SPY", [])

    observations = []
    for row in rows:
        code = row["stock_code"]
        prices = price_data.get(code, [])

        obs = {
            "date": date_str,
            "stock_code": code,
            "strategy_id": row["strategy_id"],
            "signal_type": row["signal_type"],
            "signal_name": row["signal_name"],
            "signal_strength": row.get("signal_strength"),
            "lifecycle_stage": row.get("lifecycle_stage"),
            "strategy_environment_fit": row.get("strategy_environment_fit"),
            "fit_reasons": row.get("fit_reasons", ""),
            "ef_count": row.get("ef_count"),
            "mn1_state": row.get("mn1_state_hex"),
            "w1_state": row.get("w1_state_hex"),
            "d1_state": row.get("d1_state_hex"),
            "reference_close": prices[0][1] if prices else None,
        }

        missing = False
        for w in windows:
            ret, target_date, target_close = compute_forward_return(prices, date_str, w)
            spy_ret, _, _ = compute_forward_return(spy_prices, date_str, w)
            obs[f"target_date_{w}d"] = target_date
            obs[f"target_close_{w}d"] = target_close
            obs[f"forward_return_{w}d"] = ret
            obs[f"spy_return_{w}d"] = spy_ret
            obs[f"forward_excess_return_{w}d"] = (
                ret - spy_ret if ret is not None and spy_ret is not None else None
            )
            if ret is None or spy_ret is None:
                missing = True

        obs["label_status"] = "pending_future_data" if missing else "labeled"
        observations.append(obs)

    labeled = sum(1 for o in observations if o["label_status"] == "labeled")

    # Write output
    out_json = OUT_DIR / f"us_forward_obs_{ymd(date_str)}.json"
    out_latest = OUT_DIR / "us_forward_obs_latest.json"
    result = {
        "schema_version": "us_forward_obs_v1",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "foundation_db": str(foundation_db),
        "windows": windows,
        "benchmark": "SPY",
        "total": len(observations),
        "labeled": labeled,
        "pending": len(observations) - labeled,
        "rows": observations,
        "research_only": True,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    out_json.write_text(text, encoding="utf-8")
    out_latest.write_text(text, encoding="utf-8")

    return {
        "date": date_str,
        "total": len(observations),
        "labeled": labeled,
        "pending": len(observations) - labeled,
        "json": str(out_json),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--db", default=str(US_FOUNDATION_DB))
    parser.add_argument("--windows", default="5,10,20")
    args = parser.parse_args()

    windows = [int(w) for w in args.windows.split(",")]
    result = build_observations(args.date, Path(args.db), windows)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
