#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
import sys
from collections import defaultdict
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

import duckdb

import build_anlu_intraday_h4_h1_views as core
from hermass_five_cycle_agently_contract import 计算视角状态审计, 通用规则


ROOT = Path(__file__).resolve().parents[1]
HERMASS = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")
RAW_DB = HERMASS / "outputs/p108_blackwolf_ashare_daily_raw_20260519/p108_blackwolf_ashare_daily_raw.duckdb"
STOCK_LIST = HERMASS / "data/blackwolf_stock_list_flag0.csv"
MONEYFLOW_CSV = HERMASS / "data/blackwolf_ashare_moneyflow_20260519_20260519.csv"
OUT_JSON = ROOT / "fixtures/all_products_d1_view_6_rows_20260519.json"
OUT_HTML = ROOT / "public/all_products_d1_view_6_rows_20260519.html"

ROW_LIMIT = 6
VIEW_START = "2018-05-15"
END = "2026-05-19"
COLUMNS = ["品种", "时间", "MN1state", "W1state", "D1state"]
COLUMN_CN = {
    "品种": "品种",
    "时间": "时间",
    "MN1state": "月线状态",
    "W1state": "周线状态",
    "D1state": "日线状态",
}


def load_names() -> dict[str, str]:
    out = {}
    with STOCK_LIST.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            out[row["stock_code"]] = row.get("name") or ""
    return out


def load_moneyflow() -> dict[tuple[str, str], dict[str, Any]]:
    if not MONEYFLOW_CSV.exists():
        return {}
    out = {}
    with MONEYFLOW_CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            out[(row["stock_code"], row["date"])] = row
    return out


def load_daily_rows() -> dict[str, list[dict[str, Any]]]:
    con = duckdb.connect(str(RAW_DB), read_only=True)
    try:
        rows = con.execute(
            """
            WITH latest_symbols AS (
              SELECT DISTINCT stock_code
              FROM blackwolf_ashare_daily_raw
              WHERE date = DATE '2026-05-19'
            ),
            recent_dates AS (
              SELECT DISTINCT date
              FROM blackwolf_ashare_daily_raw
              WHERE date <= DATE '2026-05-19'
              ORDER BY date DESC
              LIMIT 160
            )
            SELECT stock_code, date, open, high, low, close, volume, amount
            FROM blackwolf_ashare_daily_raw
            WHERE stock_code IN (SELECT stock_code FROM latest_symbols)
              AND date IN (SELECT date FROM recent_dates)
            ORDER BY stock_code, date
            """,
        ).fetchall()
    finally:
        con.close()
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stock_code, d, o, h, l, c, v, a in rows:
        by_symbol[stock_code].append(
            {
                "stock_code": stock_code,
                "date": core.parse_date(d),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(v),
                "amount": float(a),
            }
        )
    return by_symbol


def latest_level_index(levels: list[dict[str, Any]], asof: datetime) -> int | None:
    latest = None
    for idx, row in enumerate(levels):
        if row["available_at"] <= asof:
            latest = idx
        else:
            break
    return latest


def label(stock_code: str, names: dict[str, str]) -> str:
    name = names.get(stock_code) or "名称未提供"
    return f"{stock_code.split('.')[0]} {name}"


def moneyflow_summary(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {"资金流覆盖": "未下载"}

    def num(key: str) -> float:
        try:
            return float(row.get(key) or 0)
        except Exception:
            return 0.0

    active_buy = num("buytddcje") + num("buyddcje") + num("buyzdcje") + num("buysdcje")
    active_sell = num("selltddcje") + num("sellddcje") + num("sellzdcje") + num("sellxdcje")
    large_buy = num("buytddcje") + num("buyddcje")
    large_sell = num("selltddcje") + num("sellddcje")
    return {
        "资金流覆盖": "已下载",
        "主买总额": round(active_buy, 4),
        "主卖总额": round(active_sell, 4),
        "主动净额": round(active_buy - active_sell, 4),
        "大额主买": round(large_buy, 4),
        "大额主卖": round(large_sell, 4),
        "大额净额": round(large_buy - large_sell, 4),
        "主买单数": row.get("buynum"),
        "主卖单数": row.get("sellnum"),
    }


def build_symbol(
    stock_code: str,
    rows: list[dict[str, Any]],
    names: dict[str, str],
    moneyflow: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mn1 = core.compute_state_levels(core.aggregate_daily(rows, "MN1"), "MN1")
    w1 = core.compute_state_levels(core.aggregate_daily(rows, "W1"), "W1")
    d1 = core.compute_state_levels(core.aggregate_daily(rows, "D1"), "D1")
    levels = {"MN1": mn1, "W1": w1, "D1": d1}
    selected = [row for row in d1 if row["date"].isoformat() <= END]
    views = []
    audits = []
    for bar in reversed(selected[-ROW_LIMIT:]):
        item = {"品种": label(stock_code, names), "时间": bar["close_at"].isoformat(sep=" ")}
        audit = {
            "品种": item["品种"],
            "时间": item["时间"],
            "states": {},
            "moneyflow": moneyflow_summary(moneyflow.get((stock_code, bar["date"].isoformat()))),
        }
        for tf in ["MN1", "W1", "D1"]:
            idx = latest_level_index(levels[tf], bar["close_at"])
            if idx is None:
                item[f"{tf}state"] = "NA"
                continue
            state_audit = 计算视角状态审计(
                bar, tf, levels[tf], idx, core.ea, core.pd, core.decode_state, core.clean_value
            )
            item[f"{tf}state"] = state_audit["components"]["state_hex"]
            audit["states"][tf] = state_audit
        views.append(item)
        audits.append(audit)
    return views, audits


def render_html(payload: dict[str, Any]) -> str:
    rows = payload["rows"]
    body = []
    for row in rows[:2000]:
        body.append(
            "<tr>" + "".join(f"<td>{html.escape(str(row.get(col, '')))}</td>" for col in COLUMNS) + "</tr>"
        )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>所有产品 D1 视角 6 行</title>
<style>body{{margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f6f8fa;color:#17202a}}main{{max-width:1280px;margin:0 auto}}header,section{{background:white;border:1px solid #dbe3ea;border-radius:8px;padding:18px;margin-bottom:16px}}h1{{margin:0 0 8px}}p{{color:#607080}}.wrap{{overflow:auto;max-height:760px;border:1px solid #dbe3ea;border-radius:8px}}table{{border-collapse:collapse;width:100%;min-width:720px}}th,td{{padding:9px 11px;border-bottom:1px solid #e5ebf0;text-align:left;white-space:nowrap}}th{{background:#f8fafb;position:sticky;top:0}}td:nth-child(n+3){{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:700}}</style>
</head><body><main><header><h1>所有产品 D1 视角 6 行</h1><p>状态使用通用函数计算；资金流为增量证据，不参与 state_hex 主计算。页面先展示前 2000 行，完整数据见 JSON。</p>
<p>产品数 {payload["symbol_count"]}；总行数 {len(rows)}；资金流覆盖日 {payload["moneyflow_dates"]}；生成时间 {html.escape(payload["generated_at"])}</p></header>
<section><div class="wrap"><table><thead><tr>{"".join(f"<th>{html.escape(COLUMN_CN[col])}</th>" for col in COLUMNS)}</tr></thead><tbody>{"".join(body)}</tbody></table></div></section>
</main></body></html>"""


def main() -> int:
    names = load_names()
    moneyflow = load_moneyflow()
    by_symbol = load_daily_rows()
    rows_out = []
    audits_out = {}
    errors = []
    symbols = sorted(set(names) & set(by_symbol))
    for idx, stock_code in enumerate(symbols, start=1):
        try:
            rows, audits = build_symbol(stock_code, by_symbol[stock_code], names, moneyflow)
            if len(rows) == ROW_LIMIT:
                rows_out.extend(rows)
                audits_out[stock_code] = audits
        except Exception as exc:
            errors.append({"stock_code": stock_code, "error": f"{type(exc).__name__}: {str(exc)[:180]}"})
        if idx % 50 == 0:
            print(
                json.dumps(
                    {"progress": idx, "rows": len(rows_out), "errors": len(errors)}, ensure_ascii=False
                ),
                file=sys.stderr,
            )
    payload = {
        "schema_version": "all_products_d1_view_6_rows_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_daily_db": str(RAW_DB),
        "source_stock_list": str(STOCK_LIST),
        "source_moneyflow": str(MONEYFLOW_CSV),
        "state_hex_contract": 通用规则,
        "row_limit_per_symbol": ROW_LIMIT,
        "symbol_count": len(audits_out),
        "rows": rows_out,
        "row_audit_by_symbol": audits_out,
        "errors": errors,
        "moneyflow_dates": sorted({key[1] for key in moneyflow.keys()}),
        "moneyflow_row_count": len(moneyflow),
        "data_boundary": "资金流只作为增量证据，不参与 state_hex 主计算；当前资金流已下载日期按 source_moneyflow 文件决定。",
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS",
                "json": str(OUT_JSON),
                "html": str(OUT_HTML),
                "symbol_count": payload["symbol_count"],
                "row_count": len(rows_out),
                "errors": len(errors),
                "moneyflow_row_count": len(moneyflow),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
