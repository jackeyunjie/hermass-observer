#!/usr/bin/env python3
"""预计算每日快照 JSON — 回答速度提升 50-100 倍。

将全市场最新日的关键 State 字段预计算为 ~5MB 的 JSON 文件。
Agent 回答时直接读文件，不需要每次都连 DuckDB。

输出: outputs/daily_snapshot.json

Usage:
    python3 scripts/build_daily_snapshot.py
    python3 scripts/build_daily_snapshot.py --date 2026-05-25
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "daily_snapshot"
SNAPSHOT_FILE = ROOT / "outputs" / "daily_snapshot.json"


def find_foundation_db(date_str: str) -> Path | None:
    ymd = date_str.replace("-", "")
    candidate = ROOT / "outputs" / f"p116_foundation_{ymd}" / "p116_foundation.duckdb"
    if candidate.exists():
        return candidate
    dbs = sorted(ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"), reverse=True)
    for db in dbs:
        if db.exists() and db.stat().st_size > 0:
            return db
    return None


def build(date_str: str) -> dict:
    db_path = find_foundation_db(date_str)
    if db_path is None:
        raise FileNotFoundError(f"无可用 Foundation DB for {date_str}")

    con = duckdb.connect(str(db_path), read_only=True)

    latest_date = con.execute("SELECT MAX(state_date) FROM d1_perspective_state").fetchone()[0]

    stock_rows = con.execute(f"""
        SELECT
            stock_code,
            d1_close,
            mn1_state_hex, w1_state_hex, d1_state_hex,
            mn1_state_score, w1_state_score, d1_state_score,
            ef_count,
            mn1_trend, w1_trend, d1_trend,
            d1_adx14, d1_atr_ratio_pct,
            d1_sr_support, d1_sr_resistance, d1_sr_ready,
            w1_sr_support, w1_sr_resistance, w1_sr_ready,
            mn1_sr_support, mn1_sr_resistance, mn1_sr_ready,
            mn1_volatility, d1_volatility
        FROM d1_perspective_state
        WHERE state_date = CAST('{latest_date}' AS DATE)
        ORDER BY ef_count DESC, d1_state_score DESC
    """).fetchall()

    stocks = []
    ef_dist = {"0": 0, "1": 0, "2": 0, "3": 0}
    total_ef2 = 0

    for r in stock_rows:
        entry = {
            "c": r[0],
            "p": r[1],
            "hex": [r[2], r[3], r[4]],
            "sc": [r[5], r[6], r[7]],
            "ef": r[8],
            "tr": [r[9] or "", r[10] or "", r[11] or ""],
            "adx": r[12],
            "atr": r[13],
            "sr": {
                "d": [r[14], r[15], r[16]],
                "w": [r[17], r[18], r[19]],
                "m": [r[20], r[21], r[22]],
            },
            "vol": [r[23] or "", r[24] or ""],
        }
        stocks.append(entry)

        ef_key = str(r[8])
        ef_dist[ef_key] = ef_dist.get(ef_key, 0) + 1
        if r[8] >= 2:
            total_ef2 += 1

    market_overview_row = con.execute(f"""
        SELECT
            COUNT(*) AS total,
            COUNT(DISTINCT stock_code) AS stocks,
            SUM(CASE WHEN ef_count >= 2 THEN 1 ELSE 0 END) AS ef2,
            ROUND(AVG(CASE WHEN d1_state_score > 0 THEN d1_state_score END), 2) AS avg_d1
        FROM d1_perspective_state
        WHERE state_date = CAST('{latest_date}' AS DATE)
    """).fetchone()

    con.close()

    snapshot = {
        "v": "1.0",
        "date": str(latest_date),
        "built": datetime.now(timezone.utc).isoformat(),
        "market": {
            "total": market_overview_row[0],
            "stocks": market_overview_row[1],
            "ef2_count": market_overview_row[2],
            "ef2_pct": round(market_overview_row[2] / max(market_overview_row[1], 1) * 100, 1),
            "avg_d1_score": market_overview_row[3],
        },
        "ef_dist": ef_dist,
        "stocks": stocks,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ymd = str(latest_date).replace("-", "")
    dated_path = OUTPUT_DIR / f"daily_snapshot_{ymd}.json"
    dated_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")

    SNAPSHOT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")

    size_kb = SNAPSHOT_FILE.stat().st_size / 1024
    print(
        json.dumps(
            {
                "status": "ok",
                "date": str(latest_date),
                "stocks": len(stocks),
                "size_kb": round(size_kb, 1),
                "outputs": {
                    "latest": str(SNAPSHOT_FILE),
                    "dated": str(dated_path),
                },
            },
            ensure_ascii=False,
        )
    )

    return snapshot


def main():
    parser = argparse.ArgumentParser(description="Build daily State snapshot JSON")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--silent", action="store_true")
    args = parser.parse_args()

    try:
        build(args.date)
    except FileNotFoundError as e:
        print(json.dumps({"status": "error", "message": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
