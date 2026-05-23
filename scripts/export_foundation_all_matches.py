#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path

import duckdb

from export_foundation_d1_view import load_names


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")


FIELDS = [
    "rank",
    "stock_code",
    "stock_name",
    "date",
    "ef_count",
    "mn1_state",
    "w1_state",
    "d1_state",
    "d1_close",
    "mn1_sr_support",
    "mn1_sr_resistance",
    "w1_sr_support",
    "w1_sr_resistance",
    "d1_sr_support",
    "d1_sr_resistance",
]


def main() -> int:
    db_path = ROOT / "outputs" / "p116_foundation_20260520" / "p116_foundation.duckdb"
    names = load_names(RESEARCH_ROOT / "data" / "symbol_name_mapping.csv")
    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute(
        """
        SELECT
          row_number() OVER (ORDER BY ef_count DESC, stock_code ASC) AS rank,
          stock_code,
          state_date::VARCHAR AS date,
          ef_count,
          mn1_state_hex AS mn1_state,
          w1_state_hex AS w1_state,
          d1_state_hex AS d1_state,
          d1_close,
          mn1_sr_support,
          mn1_sr_resistance,
          w1_sr_support,
          w1_sr_resistance,
          d1_sr_support,
          d1_sr_resistance
        FROM d1_perspective_state
        WHERE state_date = DATE '2026-05-20'
          AND ef_count >= 2
        ORDER BY ef_count DESC, stock_code ASC
        """
    ).fetchdf().to_dict("records")
    con.close()

    output_rows = []
    for row in rows:
        symbol = row["stock_code"]
        output_rows.append(
            {
                "rank": row["rank"],
                "stock_code": symbol.split(".")[0],
                "stock_name": names.get(symbol, ""),
                "date": row["date"],
                "ef_count": row["ef_count"],
                "mn1_state": row["mn1_state"],
                "w1_state": row["w1_state"],
                "d1_state": row["d1_state"],
                "d1_close": row["d1_close"],
                "mn1_sr_support": row["mn1_sr_support"],
                "mn1_sr_resistance": row["mn1_sr_resistance"],
                "w1_sr_support": row["w1_sr_support"],
                "w1_sr_resistance": row["w1_sr_resistance"],
                "d1_sr_support": row["d1_sr_support"],
                "d1_sr_resistance": row["d1_sr_resistance"],
            }
        )

    public_dir = ROOT / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    csv_path = public_dir / "observation_pool_foundation_all_matches_20260520.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(output_rows)

    body = "\n".join(
        "<tr>" + "".join(f"<td>{row[field]}</td>" for field in FIELDS) + "</tr>"
        for row in output_rows
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>P116 Foundation 全部匹配 - 2026-05-20</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; margin: 24px; color: #1f2937; }}
    h1 {{ font-size: 22px; margin: 0 0 12px; }}
    .note {{ background: #eef7f2; border: 1px solid #c9e7d7; padding: 12px; border-radius: 6px; margin-bottom: 16px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
    th, td {{ border: 1px solid #d7dde6; padding: 7px; text-align: left; white-space: nowrap; }}
    th {{ background: #eef3f8; position: sticky; top: 0; }}
    td:nth-child(6), td:nth-child(7), td:nth-child(8) {{ font-weight: 700; color: #0f766e; }}
  </style>
</head>
<body>
  <h1>P116 Foundation 全部匹配 - 2026-05-20</h1>
  <div class="note">筛选：至少 2 周期 E/F。共 {len(output_rows)} 只。Top100 页面只展示前 100；本页展示全部匹配，688107 当前排名第 881。</div>
  <table>
    <thead><tr>{''.join(f'<th>{field}</th>' for field in FIELDS)}</tr></thead>
    <tbody>{body}</tbody>
  </table>
</body>
</html>
"""
    html_path = public_dir / "observation_pool_foundation_all_matches_20260520.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"CSV: {csv_path}")
    print(f"HTML: {html_path}")
    print(f"rows: {len(output_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
