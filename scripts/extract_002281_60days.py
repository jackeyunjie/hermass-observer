#!/usr/bin/env python3
"""Extract 002281.SZ last 60 days data from P116 v2 database."""

import duckdb
import bisect
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "outputs" / "p116_ashare_d1_native_state_v2_20260518" / "p116_ashare_d1_native_state_v2.duckdb"


def find_latest(date_list, target_date):
    """Find the most recent date in date_list that is <= target_date."""
    idx = bisect.bisect_right(date_list, target_date) - 1
    if idx >= 0:
        return date_list[idx]
    return None


def main():
    conn = duckdb.connect(str(DB_PATH))

    stock_code = "002281.SZ"
    stock_name = "光迅科技"

    # Get all data for 002281.SZ
    result = conn.execute(
        """
        SELECT
            state_date,
            timeframe,
            state_hex,
            close,
            sr_resistance,
            sr_support,
            sr_ready
        FROM ashare_d1_native_state_v2_final
        WHERE stock_code = '002281.SZ'
        ORDER BY state_date, timeframe
        """
    ).fetchall()

    # Organize by date and timeframe
    data_by_date = {}
    for row in result:
        date, tf, hex_val, close, sr_r, sr_s, sr_ready = row
        if date not in data_by_date:
            data_by_date[date] = {}
        data_by_date[date][tf] = {
            "state_hex": hex_val,
            "close": close,
            "sr_resistance": sr_r,
            "sr_support": sr_s,
            "sr_ready": sr_ready,
        }

    # Get all D1 dates (daily dates), sorted descending (newest first)
    d1_dates = sorted(
        [d for d in data_by_date.keys() if "D1" in data_by_date[d]], reverse=True
    )

    # Get W1 and MN1 dates (sorted ascending for bisect)
    w1_dates = sorted([d for d in data_by_date.keys() if "W1" in data_by_date[d]])
    mn1_dates = sorted([d for d in data_by_date.keys() if "MN1" in data_by_date[d]])

    # Take last 60 D1 dates
    recent_60_dates = d1_dates[:60]

    # Print header
    print(f"\n{'='*140}")
    print(
        f"股票: {stock_name} ({stock_code}) - 最近60天 P116 State v2 (SR-based position)"
    )
    print(f"{'='*140}")
    print(
        f"{'日期':<12} {'MN1':<6} {'W1':<6} {'D1':<6} {'收盘价':<10} "
        f"{'MN1_R':<10} {'MN1_S':<10} {'W1_R':<10} {'W1_S':<10} {'D1_R':<10} {'D1_S':<10}"
    )
    print(f"{'-'*140}")

    # Print data (newest first)
    for d in recent_60_dates:
        d1_data = data_by_date[d]["D1"]

        # Find latest W1 and MN1 for this date
        w1_date = find_latest(w1_dates, d)
        mn1_date = find_latest(mn1_dates, d)

        w1_data = (
            data_by_date[w1_date]["W1"]
            if w1_date and w1_date in data_by_date
            else None
        )
        mn1_data = (
            data_by_date[mn1_date]["MN1"]
            if mn1_date and mn1_date in data_by_date
            else None
        )

        mn1_hex = mn1_data["state_hex"] if mn1_data else "N/A"
        w1_hex = w1_data["state_hex"] if w1_data else "N/A"
        d1_hex = d1_data["state_hex"]

        mn1_r = mn1_data["sr_resistance"] if mn1_data else None
        mn1_s = mn1_data["sr_support"] if mn1_data else None
        w1_r = w1_data["sr_resistance"] if w1_data else None
        w1_s = w1_data["sr_support"] if w1_data else None
        d1_r = d1_data["sr_resistance"]
        d1_s = d1_data["sr_support"]
        close = d1_data["close"]

        print(
            f"{str(d):<12} {mn1_hex:<6} {w1_hex:<6} {d1_hex:<6} {close:<10.2f} "
            f"{str(mn1_r):<10} {str(mn1_s):<10} {str(w1_r):<10} {str(w1_s):<10} "
            f"{str(d1_r):<10} {str(d1_s):<10}"
        )

    print(f"{'='*140}")
    print(f"共 {len(recent_60_dates)} 行数据")

    conn.close()


if __name__ == "__main__":
    main()
