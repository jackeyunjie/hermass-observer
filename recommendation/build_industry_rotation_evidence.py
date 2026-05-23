#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
MARKET_DB = ROOT / "outputs" / "market_assets" / "market_assets.duckdb"
MONEYFLOW_EVIDENCE_DIR = ROOT / "outputs" / "moneyflow_evidence"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_moneyflow(date_str: str) -> dict[str, dict[str, Any]]:
    path = MONEYFLOW_EVIDENCE_DIR / f"moneyflow_evidence_{ymd(date_str)}.csv"
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = str(row.get("stock_code") or "")
            out[code] = row
            out[code.split(".")[0]] = row
    return out


def market_asset_metrics(date_str: str, db_path: Path) -> dict[str, dict[str, Any]]:
    if not db_path.exists():
        return {}
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            """
            WITH latest AS (
              SELECT *
              FROM market_asset_daily
              WHERE date <= CAST(? AS DATE)
            ),
            ranked AS (
              SELECT
                *,
                ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn_latest,
                LAG(close, 5) OVER (PARTITION BY symbol ORDER BY date) AS close_5d_ago,
                LAG(close, 20) OVER (PARTITION BY symbol ORDER BY date) AS close_20d_ago
              FROM latest
            )
            SELECT
              symbol, name, asset_type, sw_l1, benchmark_group,
              CAST(date AS VARCHAR), close, close_5d_ago, close_20d_ago
            FROM ranked
            WHERE rn_latest = 1
            ORDER BY asset_type, sw_l1, symbol
            """,
            [date_str],
        ).fetchall()
    finally:
        con.close()
    out: dict[str, dict[str, Any]] = {}
    for symbol, name, asset_type, sw_l1, benchmark_group, row_date, close, close_5d, close_20d in rows:
        ret_5d = (close / close_5d - 1.0) if close and close_5d else None
        ret_20d = (close / close_20d - 1.0) if close and close_20d else None
        key = sw_l1 or symbol
        out[key] = {
            "etf_symbol": symbol,
            "etf_name": name,
            "asset_type": asset_type,
            "benchmark_group": benchmark_group,
            "market_asset_date": row_date,
            "etf_close": close,
            "etf_return_5d": round(ret_5d, 6) if ret_5d is not None else "",
            "etf_return_20d": round(ret_20d, 6) if ret_20d is not None else "",
        }
    return out


def build_industry_rotation(date_str: str, market_db: Path = MARKET_DB) -> dict[str, Any]:
    snapshot_path = ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_{ymd(date_str)}.json"
    diff_path = ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_diff_{ymd(date_str)}.json"
    if not snapshot_path.exists():
        raise FileNotFoundError(snapshot_path)
    snapshot = load_json(snapshot_path)
    diff = load_json(diff_path) if diff_path.exists() else {"entered": [], "left": [], "stayed": []}
    moneyflow = load_moneyflow(date_str)
    market_metrics = market_asset_metrics(date_str, market_db)
    entered_codes = {row.get("stock_code") for row in diff.get("entered", [])}
    left_codes = {row.get("stock_code") for row in diff.get("left", [])}

    grouped: dict[str, dict[str, Any]] = {}
    for row in snapshot.get("rows", []):
        industry = row.get("sw_l1") or "未分类"
        item = grouped.setdefault(
            industry,
            {
                "sw_l1": industry,
                "pool_count": 0,
                "entered_count": 0,
                "left_count": 0,
                "state_score_sum_avg": 0.0,
                "ef_strength_avg": 0.0,
                "moneyflow_confirmed_count": 0,
                "moneyflow_divergence_count": 0,
                "active_net_5d": 0.0,
                "big_order_net_5d": 0.0,
                "top_symbols": [],
            },
        )
        mf = moneyflow.get(row.get("symbol")) or moneyflow.get(row.get("stock_code")) or {}
        item["pool_count"] += 1
        item["entered_count"] += int(row.get("stock_code") in entered_codes)
        item["state_score_sum_avg"] += fnum(row.get("state_score_sum"))
        item["ef_strength_avg"] += fnum(row.get("ef_strength"))
        item["moneyflow_confirmed_count"] += int(str(mf.get("moneyflow_status")) == "confirmed")
        item["moneyflow_divergence_count"] += int(str(mf.get("moneyflow_status")) == "divergence")
        item["active_net_5d"] += fnum(mf.get("active_net_5d"))
        item["big_order_net_5d"] += fnum(mf.get("big_order_net_5d"))
        item["top_symbols"].append(f"{row.get('stock_code')} {row.get('stock_name')}")

    for row in diff.get("left", []):
        industry = row.get("sw_l1") or "未分类"
        item = grouped.setdefault(
            industry,
            {
                "sw_l1": industry,
                "pool_count": 0,
                "entered_count": 0,
                "left_count": 0,
                "state_score_sum_avg": 0.0,
                "ef_strength_avg": 0.0,
                "moneyflow_confirmed_count": 0,
                "moneyflow_divergence_count": 0,
                "active_net_5d": 0.0,
                "big_order_net_5d": 0.0,
                "top_symbols": [],
            },
        )
        item["left_count"] += 1

    rows = []
    total_pool = max(1, sum(item["pool_count"] for item in grouped.values()))
    for industry, item in grouped.items():
        pool_count = item["pool_count"]
        if pool_count:
            item["state_score_sum_avg"] = round(item["state_score_sum_avg"] / pool_count, 4)
            item["ef_strength_avg"] = round(item["ef_strength_avg"] / pool_count, 4)
        item["pool_share"] = round(pool_count / total_pool, 4)
        item["moneyflow_confirm_rate"] = round(item["moneyflow_confirmed_count"] / pool_count, 4) if pool_count else 0
        item["active_net_5d"] = round(item["active_net_5d"], 2)
        item["big_order_net_5d"] = round(item["big_order_net_5d"], 2)
        item["top_symbols"] = "；".join(item["top_symbols"][:8])
        item.update(market_metrics.get(industry, {}))
        item["rotation_score"] = round(
            pool_count * 1.0
            + item["entered_count"] * 3.0
            - item["left_count"] * 1.2
            + item["moneyflow_confirmed_count"] * 1.5
            - item["moneyflow_divergence_count"] * 2.0
            + fnum(item.get("etf_return_5d")) * 100.0,
            4,
        )
        rows.append(item)

    rows.sort(key=lambda item: (-fnum(item.get("rotation_score")), item.get("sw_l1") or ""))
    for idx, row in enumerate(rows, 1):
        row["rank"] = idx

    out_dir = ROOT / "outputs" / "industry_rotation"
    out_dir.mkdir(parents=True, exist_ok=True)
    public_dir = ROOT / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"industry_rotation_{ymd(date_str)}.csv"
    json_path = out_dir / f"industry_rotation_{ymd(date_str)}.json"
    html_path = public_dir / f"industry_rotation_{ymd(date_str)}.html"

    fields = [
        "rank",
        "sw_l1",
        "rotation_score",
        "pool_count",
        "pool_share",
        "entered_count",
        "left_count",
        "state_score_sum_avg",
        "ef_strength_avg",
        "moneyflow_confirmed_count",
        "moneyflow_confirm_rate",
        "moneyflow_divergence_count",
        "active_net_5d",
        "big_order_net_5d",
        "etf_symbol",
        "etf_name",
        "etf_return_5d",
        "etf_return_20d",
        "top_symbols",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    payload = {
        "schema_version": "industry_rotation_evidence_v1",
        "date": date_str,
        "source_snapshot": str(snapshot_path),
        "source_moneyflow": str(MONEYFLOW_EVIDENCE_DIR / f"moneyflow_evidence_{ymd(date_str)}.csv"),
        "source_market_db": str(market_db),
        "row_count": len(rows),
        "csv": str(csv_path),
        "html": str(html_path),
        "top_industries": rows[:10],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(render_html(payload, rows), encoding="utf-8")
    (public_dir / "industry_rotation_latest.html").write_text(render_html(payload, rows), encoding="utf-8")
    return {**payload, "json": str(json_path)}


def render_html(payload: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    fields = ["rank", "sw_l1", "rotation_score", "pool_count", "entered_count", "left_count", "moneyflow_confirm_rate", "active_net_5d", "big_order_net_5d", "etf_name", "etf_return_5d", "top_symbols"]
    head = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
    body = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(str(row.get(field, '')))}</td>" for field in fields)
        body.append(f"<tr>{cells}</tr>")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>行业轮动证据 - {html.escape(payload['date'])}</title>
  <style>
    body {{ margin:0; padding:24px; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif; color:#17212b; background:#f6f8f7; }}
    header, section {{ background:#fff; border:1px solid #dce4df; border-radius:8px; padding:18px; margin-bottom:16px; }}
    h1 {{ margin:0 0 8px; font-size:24px; }}
    p {{ color:#526071; line-height:1.55; }}
    .table-wrap {{ overflow:auto; max-height:76vh; border:1px solid #dce4df; }}
    table {{ border-collapse:collapse; width:100%; min-width:1500px; font-size:12px; background:#fff; }}
    th,td {{ border-bottom:1px solid #e3e9e5; border-right:1px solid #e3e9e5; padding:7px 8px; white-space:nowrap; text-align:left; }}
    th {{ position:sticky; top:0; background:#eef4f1; }}
  </style>
</head>
<body>
  <header>
    <h1>行业轮动证据 - {html.escape(payload['date'])}</h1>
    <p>融合三周期 E/F 行业分布、5日资金流行业汇总、行业 ETF/指数相对表现。仅用于研究观察，不构成投资建议。</p>
  </header>
  <section>
    <div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>
  </section>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build industry rotation evidence table.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--market-db", type=Path, default=MARKET_DB)
    args = parser.parse_args()
    print(json.dumps(build_industry_rotation(args.date, args.market_db), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
