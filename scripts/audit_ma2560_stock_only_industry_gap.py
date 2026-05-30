#!/usr/bin/env python3
"""Audit why ma2560 strong-hold samples remain stock_only."""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FORWARD_DIR = ROOT / "outputs" / "ma2560_market_match_forward"
OUT_DIR = ROOT / "outputs" / "ma2560_market_match_forward"
PUBLIC_DIR = ROOT / "public"
IFIND_DIR = ROOT / "outputs" / "ifind"
INDUSTRY_ASSETS_PATH = ROOT / "config" / "industry_rotation_assets.json"
PROXY_WHITELIST_PATH = ROOT / "config" / "industry_etf_proxy_whitelist.json"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def code6(value: Any) -> str:
    text = str(value or "").upper().strip()
    digits = "".join(ch for ch in text.split(".", 1)[0] if ch.isdigit())
    return digits[-6:] if digits else text


def load_json(path: Path, required: bool = False) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_industry(date_str: str) -> dict[str, dict[str, Any]]:
    path = IFIND_DIR / f"industry_{ymd(date_str)}.json"
    payload = load_json(path)
    out: dict[str, dict[str, Any]] = {}
    for key, row in (payload.get("by_code") or {}).items():
        code = code6(key or row.get("stock_code"))
        if code:
            out[code] = row
    for row in payload.get("rows", []) or []:
        code = code6(row.get("stock_code"))
        if code:
            out[code] = row
    return out


def load_asset_industries() -> set[str]:
    payload = load_json(INDUSTRY_ASSETS_PATH, required=True)
    return {str(row.get("sw_l1") or "").strip() for row in payload.get("industry_etf_assets", []) if row.get("sw_l1")}


def load_proxy_whitelist() -> dict[str, Any]:
    payload = load_json(PROXY_WHITELIST_PATH)
    payload.setdefault("no_etf_coverage", [])
    payload.setdefault("proxy_mappings", {})
    return payload


def classify_gap(row: dict[str, Any], industry: dict[str, Any], mapped_industries: set[str], proxy_whitelist: dict[str, Any]) -> str:
    sw_l1 = str(industry.get("sw_l1") or "").strip()
    if not sw_l1:
        return "missing_industry_profile"
    if sw_l1 in {str(item).strip() for item in proxy_whitelist.get("no_etf_coverage", [])}:
        return "no_etf_coverage"
    if sw_l1 not in mapped_industries:
        proxy_row = (proxy_whitelist.get("proxy_mappings") or {}).get(sw_l1) or {}
        status = str(proxy_row.get("status") or "").strip()
        if status == "approved":
            return "approved_proxy_pending_market_asset_state"
        if status:
            return f"proxy_{status}"
        return "industry_without_configured_etf"
    return "market_asset_state_missing"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def render_html(payload: dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    summary_rows = "".join(
        f"<tr><td>{esc(reason)}</td><td class='num'>{count}</td></tr>"
        for reason, count in payload["gap_counts"].items()
    )
    industry_rows = "".join(
        f"<tr><td>{esc(industry)}</td><td class='num'>{count}</td></tr>"
        for industry, count in payload["industry_counts"].items()
    )
    detail_rows = "".join(
        f"""
        <tr>
          <td><strong>{esc(row.get('stock_code'))}</strong><br><span>{esc(row.get('stock_name'))}</span></td>
          <td>{esc(row.get('sw_l1'))}<br><span>{esc(row.get('sw_l2'))}</span></td>
          <td>{esc(row.get('gap_reason'))}</td>
          <td>{esc(row.get('ma2560_state_combo'))}</td>
          <td>{esc(row.get('strategy_environment_fit'))}</td>
        </tr>
        """
        for row in payload["rows"]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>2560 stock_only 行业缺口审计 {esc(payload['date'])}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f8fb; color: #172033; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 26px; }}
    h2 {{ margin: 22px 0 10px; font-size: 18px; }}
    .meta {{ color: #5d6b82; margin: 0 0 18px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e1e6ef; margin-bottom: 18px; }}
    th, td {{ text-align: left; vertical-align: top; padding: 10px 12px; border-bottom: 1px solid #edf1f7; font-size: 13px; }}
    th {{ background: #f0f3f8; color: #344054; font-weight: 650; }}
    td span {{ color: #667085; font-size: 12px; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  </style>
</head>
<body>
  <main>
    <h1>2560 stock_only 行业缺口审计</h1>
    <p class="meta">日期 {esc(payload['date'])} | stock_only {esc(payload['total'])} 条 | 生成 {esc(payload['generated_at'])}</p>
    <h2>缺口原因</h2>
    <table><thead><tr><th>原因</th><th>数量</th></tr></thead><tbody>{summary_rows}</tbody></table>
    <h2>行业分布</h2>
    <table><thead><tr><th>行业</th><th>数量</th></tr></thead><tbody>{industry_rows}</tbody></table>
    <h2>明细</h2>
    <table><thead><tr><th>股票</th><th>行业</th><th>缺口原因</th><th>State组合</th><th>环境适配</th></tr></thead><tbody>{detail_rows}</tbody></table>
  </main>
</body>
</html>
"""


def build_audit(date_str: str) -> dict[str, Any]:
    forward = load_json(FORWARD_DIR / f"ma2560_market_match_forward_{ymd(date_str)}.json", required=True)
    industry_map = load_industry(date_str)
    mapped_industries = load_asset_industries()
    proxy_whitelist = load_proxy_whitelist()
    rows: list[dict[str, Any]] = []
    for row in forward.get("rows", []) or []:
        if row.get("ma2560_market_match_level") != "stock_only":
            continue
        industry = industry_map.get(code6(row.get("stock_code"))) or {}
        rows.append(
            {
                "date": date_str,
                "stock_code": row.get("stock_code"),
                "stock_code_6": code6(row.get("stock_code")),
                "stock_name": row.get("stock_name") or industry.get("stock_name"),
                "sw_l1": industry.get("sw_l1") or "",
                "sw_l2": industry.get("sw_l2") or "",
                "sw_l3": industry.get("sw_l3") or "",
                "gap_reason": classify_gap(row, industry, mapped_industries, proxy_whitelist),
                "ma2560_state_combo": row.get("ma2560_state_combo"),
                "strategy_environment_fit": row.get("strategy_environment_fit"),
                "fit_reasons": row.get("fit_reasons"),
            }
        )
    gap_counts = dict(Counter(row["gap_reason"] for row in rows).most_common())
    industry_counts = dict(Counter(row["sw_l1"] or "未分类" for row in rows).most_common())
    payload = {
        "schema_version": "ma2560_stock_only_gap_audit_v1",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(rows),
        "gap_counts": gap_counts,
        "industry_counts": industry_counts,
        "rows": rows,
        "research_only": True,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"ma2560_stock_only_gap_audit_{ymd(date_str)}"
    json_path = OUT_DIR / f"{stem}.json"
    csv_path = OUT_DIR / f"{stem}.csv"
    html_path = PUBLIC_DIR / f"{stem}.html"
    latest_json = OUT_DIR / "ma2560_stock_only_gap_audit_latest.json"
    latest_csv = OUT_DIR / "ma2560_stock_only_gap_audit_latest.csv"
    latest_html = PUBLIC_DIR / "ma2560_stock_only_gap_audit_latest.html"

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    html_text = render_html(payload)
    json_path.write_text(text, encoding="utf-8")
    latest_json.write_text(text, encoding="utf-8")
    write_csv(csv_path, rows)
    write_csv(latest_csv, rows)
    html_path.write_text(html_text, encoding="utf-8")
    latest_html.write_text(html_text, encoding="utf-8")
    return {
        "ok": True,
        "date": date_str,
        "total": len(rows),
        "gap_counts": gap_counts,
        "industry_counts": industry_counts,
        "json": str(json_path),
        "csv": str(csv_path),
        "html": str(html_path),
        "latest_json": str(latest_json),
        "latest_csv": str(latest_csv),
        "latest_html": str(latest_html),
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit ma2560 stock_only industry data gaps.")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    print(json.dumps(build_audit(args.date), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
