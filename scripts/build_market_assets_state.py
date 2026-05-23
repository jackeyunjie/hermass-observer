#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path

import duckdb

from build_p116_foundation import build as build_foundation


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKET_DB = ROOT / "outputs" / "market_assets" / "market_assets.duckdb"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def default_raw_db(date_str: str) -> Path:
    return ROOT / "outputs" / f"market_assets_raw_{ymd(date_str)}" / "market_assets_raw.duckdb"


def default_out_db(date_str: str) -> Path:
    return ROOT / "outputs" / f"market_assets_state_{ymd(date_str)}" / "market_assets_state.duckdb"


def default_export_dir() -> Path:
    return ROOT / "outputs" / "market_assets_state"


def sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


EXPORT_COLUMNS = [
    "symbol",
    "name",
    "asset_type",
    "sw_l1",
    "state_date",
    "d1_close",
    "mn1_state_hex",
    "w1_state_hex",
    "d1_state_hex",
    "mn1_state_score",
    "w1_state_score",
    "d1_state_score",
    "ef_count",
    "mn1_sr_support",
    "mn1_sr_resistance",
    "w1_sr_support",
    "w1_sr_resistance",
    "d1_sr_support",
    "d1_sr_resistance",
]


def export_latest_state(con: duckdb.DuckDBPyConnection, date_str: str) -> dict:
    rows = con.execute(
        f"""
        SELECT {", ".join(EXPORT_COLUMNS)}
        FROM latest_market_asset_state
        ORDER BY
          CASE asset_type WHEN 'broad_index' THEN 0 ELSE 1 END,
          sw_l1 NULLS LAST,
          symbol
        """
    ).fetchall()
    export_dir = default_export_dir()
    public_dir = ROOT / "public"
    export_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)

    csv_path = export_dir / f"market_assets_state_{ymd(date_str)}.csv"
    json_path = export_dir / f"market_assets_state_{ymd(date_str)}.json"
    html_path = public_dir / f"market_assets_state_{ymd(date_str)}.html"

    records = []
    for row in rows:
        record = {column: value for column, value in zip(EXPORT_COLUMNS, row)}
        records.append(record)

    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(records)

    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    html_rows = []
    for record in records:
        cells = "".join(f"<td>{html.escape('' if record[col] is None else str(record[col]))}</td>" for col in EXPORT_COLUMNS)
        html_rows.append(f"<tr>{cells}</tr>")
    html_head = "".join(f"<th>{html.escape(col)}</th>" for col in EXPORT_COLUMNS)
    strong_count = sum(1 for item in records if (item.get("ef_count") or 0) >= 2)
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>指数与行业ETF三周期State - {html.escape(date_str)}</title>
  <style>
    :root {{
      color-scheme: light;
      --text: #1f2933;
      --muted: #64748b;
      --border: #d7dee8;
      --head: #eef4f1;
      --accent: #087f6d;
      --bg: #ffffff;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
    }}
    main {{
      padding: 24px 32px 40px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 24px;
      line-height: 1.25;
    }}
    .meta {{
      color: var(--muted);
      margin-bottom: 18px;
    }}
    .table-wrap {{
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    table {{
      border-collapse: collapse;
      min-width: 1600px;
      width: 100%;
    }}
    th, td {{
      border-bottom: 1px solid var(--border);
      border-right: 1px solid var(--border);
      padding: 9px 10px;
      white-space: nowrap;
      text-align: left;
    }}
    th {{
      position: sticky;
      top: 0;
      background: var(--head);
      font-weight: 700;
    }}
    tr:nth-child(even) td {{
      background: #fafcfd;
    }}
    td:nth-child(7), td:nth-child(8), td:nth-child(9) {{
      color: var(--accent);
      font-weight: 700;
    }}
  </style>
</head>
<body>
  <main>
    <h1>指数与行业ETF三周期State</h1>
    <div class="meta">日期：{html.escape(date_str)} ｜ 资产数：{len(records)} ｜ 至少两周期E/F：{strong_count}</div>
    <div class="table-wrap">
      <table>
        <thead><tr>{html_head}</tr></thead>
        <tbody>
          {"".join(html_rows)}
        </tbody>
      </table>
    </div>
  </main>
</body>
</html>
"""
    html_path.write_text(page, encoding="utf-8")
    return {
        "csv": str(csv_path),
        "json": str(json_path),
        "html": str(html_path),
        "rows": len(records),
        "ef_count_gte_2": strong_count,
    }


def build_raw_compatible_db(market_db: Path, raw_db: Path, date_str: str) -> dict:
    if not market_db.exists():
        raise FileNotFoundError(market_db)
    raw_db.parent.mkdir(parents=True, exist_ok=True)
    if raw_db.exists():
        raw_db.unlink()
    con = duckdb.connect(str(raw_db))
    con.execute(f"ATTACH '{sql_path(market_db)}' AS marketdb (READ_ONLY)")
    con.execute(
        f"""
        CREATE TABLE blackwolf_ashare_daily_raw AS
        SELECT
          symbol AS stock_code,
          date::DATE AS date,
          open,
          high,
          low,
          close,
          volume,
          amount,
          true AS research_only_flag,
          name,
          asset_type,
          sw_l1,
          benchmark_group
        FROM marketdb.market_asset_daily
        WHERE date <= DATE '{date_str}'
        ORDER BY symbol, date
        """
    )
    con.execute(
        """
        CREATE TABLE asset_metadata AS
        SELECT DISTINCT stock_code AS symbol, name, asset_type, sw_l1, benchmark_group
        FROM blackwolf_ashare_daily_raw
        ORDER BY symbol
        """
    )
    summary = con.execute(
        """
        SELECT
          COUNT(*) AS raw_rows,
          COUNT(DISTINCT stock_code) AS asset_count,
          MIN(date) AS min_date,
          MAX(date) AS max_date
        FROM blackwolf_ashare_daily_raw
        """
    ).fetchdf().to_dict("records")[0]
    con.close()
    return {**summary, "raw_db": str(raw_db)}


def build_market_assets_state(date_str: str, market_db: Path, raw_db: Path, out_db: Path) -> dict:
    raw_summary = build_raw_compatible_db(market_db, raw_db, date_str)
    foundation_summary = build_foundation(raw_db, out_db, date_str)
    con = duckdb.connect(str(out_db))
    con.execute(f"ATTACH '{sql_path(raw_db)}' AS rawcompat (READ_ONLY)")
    con.execute(
        """
        CREATE TABLE asset_metadata AS
        SELECT * FROM rawcompat.asset_metadata
        """
    )
    state_summary = con.execute(
        """
        SELECT
          COUNT(*) AS state_rows,
          COUNT(DISTINCT stock_code) AS asset_count,
          MAX(state_date) AS latest_date
        FROM d1_perspective_state
        """
    ).fetchdf().to_dict("records")[0]
    con.execute(
        """
        CREATE TABLE latest_market_asset_state AS
        SELECT
          s.stock_code AS symbol,
          m.name,
          m.asset_type,
          m.sw_l1,
          m.benchmark_group,
          s.state_date,
          s.d1_close,
          s.mn1_state_hex,
          s.w1_state_hex,
          s.d1_state_hex,
          s.mn1_state_score,
          s.w1_state_score,
          s.d1_state_score,
          s.ef_count,
          s.mn1_sr_support,
          s.mn1_sr_resistance,
          s.w1_sr_support,
          s.w1_sr_resistance,
          s.d1_sr_support,
          s.d1_sr_resistance
        FROM d1_perspective_state s
        LEFT JOIN asset_metadata m ON m.symbol = s.stock_code
        WHERE s.state_date = (SELECT MAX(state_date) FROM d1_perspective_state)
        ORDER BY m.asset_type, m.sw_l1, s.stock_code
        """
    )
    latest_rows = con.execute("SELECT COUNT(*) FROM latest_market_asset_state").fetchone()[0]
    exports = export_latest_state(con, date_str)
    con.close()
    summary = {
        "schema_version": "market_assets_state_v1",
        "date": date_str,
        "source_market_db": str(market_db),
        "raw_db": str(raw_db),
        "out_db": str(out_db),
        "raw_summary": raw_summary,
        "foundation_summary": foundation_summary,
        "state_summary": state_summary,
        "latest_rows": latest_rows,
        "exports": exports,
    }
    summary_path = out_db.parent / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build P116 MN1/W1/D1 state for index and industry ETF assets.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--raw-db", type=Path)
    parser.add_argument("--out-db", type=Path)
    args = parser.parse_args()
    raw_db = args.raw_db or default_raw_db(args.date)
    out_db = args.out_db or default_out_db(args.date)
    print(json.dumps(build_market_assets_state(args.date, args.market_db, raw_db, out_db), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
