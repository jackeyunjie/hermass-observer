#!/usr/bin/env python3
"""合并所有每日 blackwolf_m30_*.duckdb 到统一 merged DB（增量去重）。

用法:
    python3 scripts/merge_m30_db.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT_DB = DATA_DIR / "blackwolf_m30_merged.duckdb"


def _get_cols(con: duckdb.DuckDBPyConnection, db_path: str, table: str = "m30_bars") -> list[str]:
    """Get column names from an attached (or current) database."""
    try:
        # Try querying main database first, then check attached
        rows = con.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}'").fetchall()
        cols = [r[0] for r in rows]
        if cols:
            return cols
    except Exception:
        pass
    # Fallback: describe from the source DB directly
    src_con = duckdb.connect(db_path, read_only=True)
    cols = [r[1] for r in src_con.execute(f"PRAGMA table_info('{table}')").fetchall()]
    src_con.close()
    return cols


def main() -> int:
    daily_dbs = sorted(DATA_DIR.glob("blackwolf_m30_*/blackwolf_m30.duckdb"))
    if not daily_dbs:
        print("未找到每日 M30 DB", file=sys.stderr)
        return 1

    print(f"发现 {len(daily_dbs)} 个每日 M30 DB")

    con = duckdb.connect(str(OUT_DB))

    # Create merged table if not exists
    existing = con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name='m30_bars'").fetchone()[0]
    if not existing:
        first_path = str(daily_dbs[0])
        first_cols = _get_cols(con, first_path)
        col_defs = []
        for c in first_cols:
            c_lower = c.lower()
            if c_lower in ("open", "high", "low", "close", "volume", "amount"):
                col_defs.append(f"{c} DOUBLE")
            elif c_lower in ("stock_code",):
                col_defs.append(f"{c} VARCHAR")
            elif c_lower in ("period_start",):
                col_defs.append(f"{c} TIMESTAMP")
            elif c_lower in ("bar_date", "available_date"):
                col_defs.append(f"{c} DATE")
            else:
                col_defs.append(f"{c} VARCHAR")
        con.execute(f"CREATE TABLE m30_bars ({', '.join(col_defs)})")

    count_before = con.execute("SELECT COUNT(*) FROM m30_bars").fetchone()[0]
    print(f"合并前记录数: {count_before:,}")

    # Get merged table columns
    merged_cols = _get_cols(con, str(OUT_DB))
    # Check which date column we use
    has_avail = "available_date" in merged_cols or "available_date" in [c.lower() for c in merged_cols]
    has_bar = "bar_date" in merged_cols or "bar_date" in [c.lower() for c in merged_cols]

    # Insert from each daily DB via ATTACH
    for db_path in daily_dbs:
        src_cols = _get_cols(con, str(db_path))
        has_src_bar = "bar_date" in src_cols or "bar_date" in [c.lower() for c in src_cols]

        # Build insert: select from attached DB matching merged columns
        con.execute(f"ATTACH '{db_path}' AS src_db (READ_ONLY)")

        # Build column mapping
        src_select = []
        for mc in merged_cols:
            mc_lower = mc.lower()
            if mc_lower == "available_date":
                if has_src_bar:
                    src_select.append("bar_date")
                else:
                    src_select.append("NULL::DATE")
            elif mc in src_cols:
                src_select.append(mc)
            elif mc_lower in {c.lower(): c for c in src_cols}:
                src_select.append({c.lower(): c for c in src_cols}[mc_lower])
            else:
                src_select.append("NULL")

        col_str = ", ".join(src_select)
        try:
            con.execute(f"INSERT INTO m30_bars SELECT {col_str} FROM src_db.m30_bars")
        except Exception as e:
            print(f"  跳过 {db_path.name}: {e}")
        con.execute("DETACH src_db")

    # Dedup all at once
    count_raw = con.execute("SELECT COUNT(*) FROM m30_bars").fetchone()[0]
    print(f"原始行数: {count_raw:,}")
    con.execute("CREATE TABLE m30_bars_dedup AS SELECT DISTINCT * FROM m30_bars")
    con.execute("DROP TABLE m30_bars")
    con.execute("ALTER TABLE m30_bars_dedup RENAME TO m30_bars")
    count_after = con.execute("SELECT COUNT(*) FROM m30_bars").fetchone()[0]
    added = count_after - count_before

    # Summary
    date_col = "bar_date" if has_bar and not has_avail else "available_date"
    try:
        r = con.execute(f"""
            SELECT MIN({date_col}), MAX({date_col}),
                   COUNT(DISTINCT {date_col}), COUNT(DISTINCT stock_code)
            FROM m30_bars
        """).fetchone()
        print(f"合并后: {count_after:,} 行 (+{added:,})")
        print(f"日期: {r[0]} ~ {r[1]}, {r[2]} 天, {r[3]} 只股票")
    except Exception:
        print(f"合并后: {count_after:,} 行 (+{added:,})")

    con.close()
    print(json.dumps({"ok": True, "before": count_before, "after": count_after, "added": added}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
