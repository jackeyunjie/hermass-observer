#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    out_dir = ROOT / "public"
    fixtures_dir = ROOT / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    foundation_db = ROOT / "outputs" / "p116_foundation_20260520" / "p116_foundation.duckdb"
    if not foundation_db.exists():
        raise FileNotFoundError(foundation_db)

    conn = duckdb.connect(str(foundation_db), read_only=True)
    rows = (
        conn.execute(
            """
        SELECT
          state_date::VARCHAR AS date,
          d1_close,
          mn1_period_start::VARCHAR AS mn1_period_start,
          mn1_sr_support,
          mn1_sr_resistance,
          mn1_trend,
          mn1_volatility,
          mn1_base,
          mn1_trend_bit,
          mn1_position_bit,
          mn1_volatility_bit,
          mn1_state_score,
          mn1_state_hex,
          w1_sr_support,
          w1_sr_resistance,
          w1_state_hex,
          d1_sr_support,
          d1_sr_resistance,
          d1_state_hex,
          ef_count
        FROM d1_perspective_state
        WHERE stock_code = '688107.SH'
          AND state_date BETWEEN DATE '2026-05-18' AND DATE '2026-05-20'
        ORDER BY state_date DESC
        """
        )
        .fetchdf()
        .to_dict("records")
    )
    conn.close()

    output_rows = []
    for row in rows:
        output_rows.append(
            {
                "stock_code": "688107",
                "stock_name": "安路科技",
                "date": row["date"],
                "d1_close": row["d1_close"],
                "mn1_sr_support": row["mn1_sr_support"],
                "mn1_sr_resistance": row["mn1_sr_resistance"],
                "mn1_sr_period_start": row["mn1_period_start"],
                "mn1_trend": row["mn1_trend"],
                "mn1_volatility": row["mn1_volatility"],
                "old_fixture_mn1": "8",
                "foundation_mn1": row["mn1_state_hex"],
                "foundation_score": row["mn1_state_score"],
                "foundation_calc": (
                    f"{'扩' if row['mn1_base'] == 8 else '缩'}+"
                    f"{'牛' if row['mn1_trend_bit'] else '平'}+"
                    f"{'上突' if row['mn1_position_bit'] == 2 else '中'}+"
                    f"{'波扩' if row['mn1_volatility_bit'] else '稳'}="
                    f"{row['mn1_state_score']}"
                ),
                "w1_sr_support": row["w1_sr_support"],
                "w1_sr_resistance": row["w1_sr_resistance"],
                "w1": row["w1_state_hex"],
                "d1_sr_support": row["d1_sr_support"],
                "d1_sr_resistance": row["d1_sr_resistance"],
                "d1": row["d1_state_hex"],
                "ef_count": row["ef_count"],
            }
        )

    csv_path = fixtures_dir / "audit_688107_mn1_state_20260520.csv"
    fields = list(output_rows[0].keys())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)

    body = "\n".join(
        "<tr>" + "".join(f"<td>{row[field]}</td>" for field in fields) + "</tr>" for row in output_rows
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>688107 MN1 State Audit - 2026-05-20</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; margin: 24px; color: #1f2937; }}
    h1 {{ font-size: 22px; margin: 0 0 12px; }}
    .note {{ background: #fff7ed; border: 1px solid #fed7aa; padding: 12px; border-radius: 6px; margin-bottom: 16px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #d7dde6; padding: 8px; text-align: left; white-space: nowrap; }}
    th {{ background: #eef3f8; position: sticky; top: 0; }}
    td:nth-child(11), td:nth-child(12), td:nth-child(13), td:nth-child(16), td:nth-child(19) {{ font-weight: 700; color: #0f766e; }}
  </style>
</head>
<body>
  <h1>688107 安路科技 MN1 State Foundation 审计</h1>
  <div class="note">
    此页直接读取新的 P116 foundation DuckDB。688107 的 MN1 SR 为 24.66 / 35.50，
    D1 close 高于 MN1 resistance，按 P116 D1 视角天条得到 MN1=E，W1=F，D1=F。
  </div>
  <table>
    <thead><tr>{"".join(f"<th>{field}</th>" for field in fields)}</tr></thead>
    <tbody>{body}</tbody>
  </table>
</body>
</html>
"""
    html_path = out_dir / "audit_688107_mn1_state_20260520.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"CSV: {csv_path}")
    print(f"HTML: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
