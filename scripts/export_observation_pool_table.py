#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path


STATE_LABELS = {
    "0": "闭+中+稳=0",
    "1": "闭+中+波扩=1",
    "2": "闭+触发+稳=2",
    "3": "闭+触发+波扩=3",
    "4": "闭+趋势+稳=4",
    "5": "闭+趋势+波扩=5",
    "6": "闭+趋势+触发+稳=6",
    "7": "闭+趋势+触发+波扩=7",
    "8": "扩+中+稳=8",
    "9": "扩+中+波扩=9",
    "A": "扩+触发+稳=10",
    "B": "扩+触发+波扩=11",
    "C": "扩+牛+中+稳=12",
    "D": "扩+牛+中+波扩=13",
    "E": "扩+牛+上突+稳=14",
    "F": "扩+牛+上突+波扩=15",
    "-1": "闭+中+波扩=-1",
    "-2": "闭+触发+稳=-2",
    "-3": "闭+触发+波扩=-3",
    "-4": "闭+趋势+稳=-4",
    "-5": "闭+趋势+波扩=-5",
    "-6": "闭+趋势+触发+稳=-6",
    "-7": "闭+趋势+触发+波扩=-7",
    "-8": "扩+中+稳=-8",
    "-9": "扩+中+波扩=-9",
    "-A": "扩+触发+稳=-10",
    "-B": "扩+触发+波扩=-11",
    "-C": "扩+熊+中+稳=-12",
    "-D": "扩+熊+中+波扩=-13",
    "-E": "扩+熊+下破+稳=-14",
    "-F": "扩+熊+下破+波扩=-15",
}


def state_label(value: object) -> str:
    text = str(value).strip().upper()
    return STATE_LABELS.get(text, text)


def flatten_rows(data: dict) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for stock_index, stock in enumerate(data.get("stocks", []), start=1):
        signal = "超强信号" if int(stock.get("ef_count", 0)) >= 3 else "强势信号"
        for day_index, row in enumerate(stock.get("rows", []), start=1):
            rows.append(
                {
                    "序号": str(stock_index),
                    "品种": str(row.get("品种", stock.get("symbol", ""))),
                    "日期": str(row.get("时间", ""))[:10],
                    "MN1state": str(row.get("MN1state", "")),
                    "W1state": str(row.get("W1state", "")),
                    "D1state": str(row.get("D1state", "")),
                    "MN1计算": state_label(row.get("MN1state", "")),
                    "W1计算": state_label(row.get("W1state", "")),
                    "D1计算": state_label(row.get("D1state", "")),
                    "信号": signal,
                    "EF周期数": str(stock.get("ef_count", "")),
                    "品种内行": str(day_index),
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "序号",
        "品种",
        "日期",
        "MN1state",
        "W1state",
        "D1state",
        "MN1计算",
        "W1计算",
        "D1计算",
        "信号",
        "EF周期数",
        "品种内行",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_html(path: Path, data: dict, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    title = "P116 State 每日观察池 - 2026-05-20"
    stat_items = [
        ("总匹配", data.get("total_matches", "")),
        ("展示品种", data.get("displayed", "")),
        ("每品种天数", data.get("days_per_stock", "")),
        ("超强信号", data.get("ultra_strong_count", "")),
        ("强势信号", data.get("strong_count", "")),
        ("筛选条件", data.get("filter_criteria", "")),
    ]
    body_rows = []
    current_symbol = None
    for row in rows:
        symbol = row["品种"]
        cls = "group-start" if symbol != current_symbol else ""
        current_symbol = symbol
        body_rows.append(
            "<tr class=\"{}\">{}</tr>".format(
                cls,
                "".join(
                    f"<td>{html.escape(row[col])}</td>"
                    for col in [
                        "序号",
                        "品种",
                        "日期",
                        "MN1state",
                        "W1state",
                        "D1state",
                        "MN1计算",
                        "W1计算",
                        "D1计算",
                        "信号",
                    ]
                ),
            )
        )
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --text: #1f2937;
      --muted: #667085;
      --line: #d7dde6;
      --soft: #f6f8fb;
      --head: #eef3f8;
      --accent: #0f766e;
    }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      color: var(--text);
      background: #ffffff;
    }}
    main {{
      max-width: 1500px;
      margin: 0 auto;
      padding: 24px;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(6, minmax(120px, 1fr));
      gap: 8px;
      margin: 12px 0 18px;
    }}
    .stat {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      background: var(--soft);
    }}
    .label {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.3;
    }}
    .value {{
      margin-top: 2px;
      font-size: 16px;
      font-weight: 650;
      line-height: 1.3;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 13px;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 7px 8px;
      text-align: left;
      vertical-align: middle;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    th {{
      position: sticky;
      top: 0;
      background: var(--head);
      z-index: 1;
      font-weight: 700;
    }}
    tbody tr:nth-child(even) td {{
      background: #fbfcfd;
    }}
    tbody tr.group-start td {{
      border-top: 2px solid var(--accent);
    }}
    .col-index {{ width: 52px; }}
    .col-symbol {{ width: 170px; }}
    .col-date {{ width: 104px; }}
    .col-state {{ width: 74px; text-align: center; }}
    .col-calc {{ width: 180px; }}
    .col-signal {{ width: 86px; }}
    @media (max-width: 900px) {{
      main {{ padding: 16px; }}
      .meta {{ grid-template-columns: repeat(2, minmax(120px, 1fr)); }}
      table {{ min-width: 1180px; }}
      .table-wrap {{ overflow-x: auto; }}
    }}
  </style>
</head>
<body>
<main>
  <h1>{html.escape(title)}</h1>
  <div class="meta">
    {''.join(f'<div class="stat"><div class="label">{html.escape(k)}</div><div class="value">{html.escape(str(v))}</div></div>' for k, v in stat_items)}
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th class="col-index">序号</th>
          <th class="col-symbol">品种</th>
          <th class="col-date">日期</th>
          <th class="col-state">MN1</th>
          <th class="col-state">W1</th>
          <th class="col-state">D1</th>
          <th class="col-calc">MN1计算</th>
          <th class="col-calc">W1计算</th>
          <th class="col-calc">D1计算</th>
          <th class="col-signal">信号</th>
        </tr>
      </thead>
      <tbody>
        {''.join(body_rows)}
      </tbody>
    </table>
  </div>
</main>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    rows = flatten_rows(data)
    csv_path = args.out_dir / f"observation_pool_{args.date}.csv"
    html_path = args.out_dir / f"observation_pool_{args.date}.html"
    write_csv(csv_path, rows)
    write_html(html_path, data, rows)
    print(json.dumps({"csv": str(csv_path), "html": str(html_path), "rows": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
