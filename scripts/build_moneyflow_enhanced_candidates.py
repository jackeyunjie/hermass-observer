#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "p116_top10_moneyflow_5d"
RETRY_DIR = ROOT / "data" / "p116_top10_moneyflow_retry"

NAMES = {
    "688069.SH": ("德林海", "环保", "水务及水治理"),
    "601991.SH": ("大唐发电", "公用事业", "火力发电"),
    "300054.SZ": ("鼎龙股份", "电子", "电子化学品"),
    "688112.SH": ("鼎阳科技", "机械设备", "仪器仪表"),
    "600500.SH": ("中化国际", "基础化工", "其他化学制品"),
    "002443.SZ": ("金洲管道", "钢铁", "特钢"),
    "603773.SH": ("沃格光电", "电子", "面板"),
    "001378.SZ": ("德冠新材", "基础化工", "膜材料"),
    "300666.SZ": ("江丰电子", "电子", "半导体材料"),
    "002887.SZ": ("绿茵生态", "环保", "综合环境治理"),
}


def num(row: dict, key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except ValueError:
        return 0.0


def load_rows() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(DATA_DIR.glob("blackwolf_ashare_moneyflow_*.csv")):
        with path.open(encoding="utf-8", newline="") as f:
            rows.extend(csv.DictReader(f))
    retry = RETRY_DIR / "blackwolf_ashare_moneyflow_20260520_20260520.csv"
    if retry.exists():
        with retry.open(encoding="utf-8", newline="") as f:
            rows.extend(csv.DictReader(f))

    dedup: dict[tuple[str, str], dict] = {}
    for row in rows:
        symbol = row.get("stock_code", "")
        date = row.get("date", "")[:10]
        if symbol and date:
            dedup[(symbol, date)] = row
    return list(dedup.values())


def enrich_row(row: dict) -> dict:
    buy_total = num(row, "buytddcje") + num(row, "buyddcje") + num(row, "buyzdcje") + num(row, "buysdcje")
    sell_total = (
        num(row, "selltddcje") + num(row, "sellddcje") + num(row, "sellzdcje") + num(row, "sellxdcje")
    )
    big_net = (num(row, "buytddcje") + num(row, "buyddcje")) - (
        num(row, "selltddcje") + num(row, "sellddcje")
    )
    active_net = buy_total - sell_total
    row = dict(row)
    row["buy_total"] = buy_total
    row["sell_total"] = sell_total
    row["active_net"] = active_net
    row["big_order_net"] = big_net
    row["active_net_ratio"] = active_net / buy_total if buy_total else 0.0
    return row


def main() -> int:
    rows = [enrich_row(row) for row in load_rows()]
    by_symbol: dict[str, list[dict]] = {}
    for row in rows:
        by_symbol.setdefault(row["stock_code"], []).append(row)
    for sym_rows in by_symbol.values():
        sym_rows.sort(key=lambda r: r["date"])

    output = []
    for symbol, sym_rows in by_symbol.items():
        latest = sym_rows[-1]
        active_sum = sum(r["active_net"] for r in sym_rows)
        big_sum = sum(r["big_order_net"] for r in sym_rows)
        positive_days = sum(1 for r in sym_rows if r["active_net"] > 0)
        big_positive_days = sum(1 for r in sym_rows if r["big_order_net"] > 0)
        latest_active = latest["active_net"]
        latest_big = latest["big_order_net"]
        latest_ratio = latest["active_net_ratio"]
        score = (
            positive_days * 2
            + big_positive_days * 2
            + (2 if active_sum > 0 else 0)
            + (2 if big_sum > 0 else 0)
            + (2 if latest_active > 0 else 0)
            + (1 if latest_big > 0 else 0)
        )
        name, industry, subindustry = NAMES.get(symbol, ("", "", ""))
        output.append(
            {
                "rank": 0,
                "stock_code": symbol.split(".")[0],
                "stock_name": name,
                "industry": industry,
                "subindustry": subindustry,
                "coverage_days": len(sym_rows),
                "positive_days": positive_days,
                "big_positive_days": big_positive_days,
                "active_net_5d": active_sum,
                "big_order_net_5d": big_sum,
                "latest_date": latest["date"],
                "latest_active_net": latest_active,
                "latest_big_order_net": latest_big,
                "latest_active_net_ratio": latest_ratio,
                "moneyflow_score": score,
            }
        )

    output.sort(
        key=lambda r: (-r["moneyflow_score"], -r["active_net_5d"], -r["big_order_net_5d"], r["stock_code"])
    )
    for idx, row in enumerate(output, 1):
        row["rank"] = idx

    fields = list(output[0].keys())
    fixtures_dir = ROOT / "fixtures"
    public_dir = ROOT / "public"
    fixtures_dir.mkdir(exist_ok=True)
    public_dir.mkdir(exist_ok=True)
    csv_path = public_dir / "p116_moneyflow_enhanced_top10_20260520.csv"
    json_path = fixtures_dir / "p116_moneyflow_enhanced_top10_20260520.json"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output)
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def money(value: float) -> str:
        return f"{value / 100000000:.2f}亿"

    rows_html = []
    for row in output:
        rows_html.append(
            "<tr>"
            f"<td>{row['rank']}</td>"
            f"<td>{row['stock_code']} {row['stock_name']}</td>"
            f"<td>{row['industry']} / {row['subindustry']}</td>"
            f"<td>{row['coverage_days']}</td>"
            f"<td>{row['positive_days']}</td>"
            f"<td>{row['big_positive_days']}</td>"
            f"<td>{money(row['active_net_5d'])}</td>"
            f"<td>{money(row['big_order_net_5d'])}</td>"
            f"<td>{row['latest_date']}</td>"
            f"<td>{money(row['latest_active_net'])}</td>"
            f"<td>{row['latest_active_net_ratio']:.1%}</td>"
            f"<td>{row['moneyflow_score']}</td>"
            "</tr>"
        )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>P116 资金流增强候选池 - 2026-05-20</title>
  <style>
    body {{ margin: 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; color: #1f2937; }}
    h1 {{ margin: 0 0 10px; font-size: 24px; }}
    .note {{ background: #eef7f2; border: 1px solid #c9e7d7; padding: 12px; border-radius: 6px; margin-bottom: 16px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #e5ebf0; padding: 8px; text-align: left; white-space: nowrap; }}
    th {{ background: #eef3f8; position: sticky; top: 0; }}
    td:nth-child(7), td:nth-child(8), td:nth-child(10), td:nth-child(11), td:nth-child(12) {{ font-weight: 700; }}
  </style>
</head>
<body>
  <h1>P116 资金流增强候选池 - 2026-05-20</h1>
  <div class="note">基础池：上一版 10 只三周期 E/F 候选。资金流口径：最近可用 5 日窗口内主动净额、特大+大单净额、正净流天数和最近日方向。5/14 对本批候选返回 0 行，实际覆盖为 5/15、5/18、5/19、5/20 四个交易日。</div>
  <table>
    <thead><tr>{"".join(f"<th>{field}</th>" for field in ["排名", "股票", "行业", "覆盖天数", "主动净流天数", "大额净流天数", "5日主动净额", "5日大额净额", "最新日", "最新主动净额", "最新主动净额/主买", "资金流分"])}</tr></thead>
    <tbody>{"".join(rows_html)}</tbody>
  </table>
</body>
</html>
"""
    html_path = public_dir / "p116_moneyflow_enhanced_top10_20260520.html"
    html_path.write_text(html, encoding="utf-8")
    print(
        json.dumps(
            {"csv": str(csv_path), "html": str(html_path), "json": str(json_path), "rows": len(output)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
