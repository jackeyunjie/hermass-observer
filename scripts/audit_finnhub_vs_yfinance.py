#!/usr/bin/env python3
"""Cross-validate yfinance data against Finnhub API.

Usage:
    1. Get free API key from https://finnhub.io/register
    2. Save to config/secrets/finnhub_credentials.json:
       {"api_key": "YOUR_FINNHUB_API_KEY"}
    3. Run: python scripts/audit_finnhub_vs_yfinance.py --sample 50 --days 30

Outputs:
    - outputs/us_stock/audit/finnhub_yfinance_audit_YYYYMMDD.json
    - outputs/us_stock/audit/finnhub_yfinance_audit_YYYYMMDD.md
    - public/finnhub_yfinance_audit_YYYYMMDD.html
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys_path_inserted = False

FOUNDATION_DB = ROOT / "outputs" / "us_stock" / "us_foundation.duckdb"
OUT_DIR = ROOT / "outputs" / "us_stock" / "audit"
PUBLIC_DIR = ROOT / "public"
CREDENTIALS_PATH = ROOT / "config" / "secrets" / "finnhub_credentials.json"

FINNHUB_BASE = "https://finnhub.io/api/v1"


def load_credentials() -> dict:
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"Finnhub credentials not found at {CREDENTIALS_PATH}\n"
            "Please create this file with:\n"
            '{"api_key": "YOUR_FINNHUB_API_KEY"}\n'
            "Get your free API key at https://finnhub.io/register"
        )
    return json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))


def get_sample_tickers(foundation_db: Path, n: int = 50) -> list[str]:
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        rows = con.execute(
            f"SELECT DISTINCT stock_code FROM daily_bars ORDER BY stock_code LIMIT {n}"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def get_yfinance_data(foundation_db: Path, ticker: str, start: date, end: date) -> pd.DataFrame:
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        df = con.execute(
            """
            SELECT date, open, high, low, close, volume
            FROM daily_bars
            WHERE stock_code = ? AND date >= ? AND date <= ?
            ORDER BY date
            """,
            (ticker, start, end),
        ).df()
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        return df
    finally:
        con.close()


def get_finnhub_data(ticker: str, start: date, end: date, api_key: str) -> pd.DataFrame:
    """Fetch daily bars from Finnhub."""
    start_ts = int(datetime.combine(start, datetime.min.time()).timestamp())
    end_ts = int(datetime.combine(end, datetime.min.time()).timestamp())

    url = f"{FINNHUB_BASE}/stock/candle"
    params = {
        "symbol": ticker,
        "resolution": "D",
        "from": start_ts,
        "to": end_ts,
        "token": api_key,
    }

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("s") != "ok":
        raise RuntimeError(f"Finnhub error: {data.get('s', 'unknown')}")

    df = pd.DataFrame(
        {
            "date": pd.to_datetime(data["t"], unit="s"),
            "open": data["o"],
            "high": data["h"],
            "low": data["l"],
            "close": data["c"],
            "volume": data["v"],
        }
    )
    df = df.set_index("date")
    return df


def compare_series(yf_df: pd.DataFrame, fh_df: pd.DataFrame, ticker: str) -> dict:
    if yf_df.empty or fh_df.empty:
        return {"ticker": ticker, "error": "missing_data", "yf_rows": len(yf_df), "fh_rows": len(fh_df)}

    merged = yf_df[["close", "volume"]].join(
        fh_df[["close", "volume"]],
        how="inner",
        lsuffix="_yf",
        rsuffix="_fh",
    )

    if merged.empty:
        return {"ticker": ticker, "error": "no_overlap", "yf_rows": len(yf_df), "fh_rows": len(fh_df)}

    merged["close_diff"] = merged["close_yf"] - merged["close_fh"]
    merged["close_diff_pct"] = (merged["close_diff"].abs() / merged["close_fh"]) * 100
    merged["volume_diff_pct"] = (
        (merged["volume_yf"] - merged["volume_fh"]).abs() / merged["volume_fh"]
    ) * 100

    return {
        "ticker": ticker,
        "overlap_days": len(merged),
        "yf_rows": len(yf_df),
        "fh_rows": len(fh_df),
        "close_max_diff": round(merged["close_diff"].abs().max(), 4),
        "close_avg_diff_pct": round(merged["close_diff_pct"].mean(), 4),
        "close_max_diff_pct": round(merged["close_diff_pct"].max(), 4),
        "volume_avg_diff_pct": round(merged["volume_diff_pct"].mean(), 2),
        "days_with_diff_gt_1pct": int((merged["close_diff_pct"] > 1.0).sum()),
        "days_with_diff_gt_0_1pct": int((merged["close_diff_pct"] > 0.1).sum()),
    }


def generate_report(results: list[dict], start: date, end: date) -> dict:
    valid = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]

    if not valid:
        return {"error": "no_valid_comparisons", "details": errors}

    return {
        "audit_date": datetime.now(timezone.utc).isoformat(),
        "start_date": str(start),
        "end_date": str(end),
        "tickers_tested": len(results),
        "valid_comparisons": len(valid),
        "errors": len(errors),
        "close_avg_diff_pct_mean": round(sum(r["close_avg_diff_pct"] for r in valid) / len(valid), 4),
        "close_max_diff_pct_mean": round(sum(r["close_max_diff_pct"] for r in valid) / len(valid), 4),
        "tickers_with_diff_gt_1pct": sum(1 for r in valid if r["days_with_diff_gt_1pct"] > 0),
        "tickers_with_diff_gt_0_1pct": sum(1 for r in valid if r["days_with_diff_gt_0_1pct"] > 0),
        "worst_ticker": max(valid, key=lambda r: r["close_max_diff_pct"])["ticker"] if valid else None,
        "worst_diff_pct": round(max(r["close_max_diff_pct"] for r in valid), 4) if valid else None,
        "details": results,
    }


def generate_html(report: dict) -> str:
    date_str = report["audit_date"][:10].replace("-", "")
    details = report.get("details", [])
    valid = [d for d in details if "error" not in d]
    errors = [d for d in details if "error" in d]

    rows = ""
    for d in sorted(valid, key=lambda x: x["close_max_diff_pct"], reverse=True):
        color = (
            "#ff6b6b"
            if d["close_max_diff_pct"] > 1
            else "#f9ca24"
            if d["close_max_diff_pct"] > 0.1
            else "#74b9ff"
        )
        rows += f"""
        <tr>
            <td><strong>{d["ticker"]}</strong></td>
            <td>{d["overlap_days"]}</td>
            <td>{d["yf_rows"]}</td>
            <td>{d["fh_rows"]}</td>
            <td style="color:{color}">{d["close_max_diff_pct"]:.4f}%</td>
            <td>{d["close_avg_diff_pct"]:.4f}%</td>
            <td>{d["days_with_diff_gt_0_1pct"]}</td>
            <td>{d["days_with_diff_gt_1pct"]}</td>
        </tr>
        """

    error_rows = ""
    for e in errors:
        error_rows += f"<tr><td>{e['ticker']}</td><td colspan='7' style='color:#ff6b6b'>{e.get('error', 'unknown')}</td></tr>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>Finnhub vs yfinance Audit - {date_str}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#0f0f23; color:#e0e0e0; margin:0; padding:20px; }}
h1 {{ color:#fff; }} .subtitle {{ color:#888; font-size:14px; margin-bottom:20px; }}
.stats {{ display:flex; gap:15px; margin-bottom:20px; flex-wrap:wrap; }}
.stat-card {{ background:#1a1a2e; border-radius:8px; padding:15px 20px; min-width:120px; text-align:center; }}
.stat-card .num {{ font-size:24px; font-weight:bold; color:#fff; }}
.stat-card .label {{ font-size:12px; color:#888; margin-top:5px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#1a1a2e; color:#888; padding:10px; text-align:left; position:sticky; top:0; }}
td {{ padding:10px; border-bottom:1px solid #222; }}
tr:hover {{ background:#1a1a2e; }}
.guardrail {{ background:#1a1a2e; border-left:3px solid #e74c3c; padding:15px; margin:20px 0; border-radius:4px; font-size:13px; color:#ccc; }}
</style></head><body>
<h1>🔍 Finnhub vs yfinance 数据交叉验证报告</h1>
<div class="subtitle">{report["start_date"]} ~ {report["end_date"]} | 测试 {report["tickers_tested"]} 只股票</div>
<div class="stats">
    <div class="stat-card"><div class="num" style="color:#74b9ff">{report["valid_comparisons"]}</div><div class="label">有效对比</div></div>
    <div class="stat-card"><div class="num" style="color:#f9ca24">{report["close_avg_diff_pct_mean"]:.4f}%</div><div class="label">平均差异</div></div>
    <div class="stat-card"><div class="num" style="color:#ff6b6b">{report["worst_diff_pct"]:.4f}%</div><div class="label">最大差异</div></div>
    <div class="stat-card"><div class="num">{report["tickers_with_diff_gt_1pct"]}</div><div class="label">差异&gt;1%的股票数</div></div>
</div>
<div class="guardrail"><strong>⚠️ 说明</strong><br>
yfinance 使用 split-adjusted 数据，Finnhub 返回 adjusted 数据。差异主要来源于复权方式不同、拆股日期差异、或数据源本身的不一致。差异 &gt; 1% 需要重点排查。
</div>
<table>
<thead><tr><th>代码</th><th>重叠天数</th><th>yfinance行数</th><th>Finnhub行数</th><th>最大差异%</th><th>平均差异%</th><th>&gt;0.1%天数</th><th>&gt;1%天数</th></tr></thead>
<tbody>{rows}{error_rows}</tbody>
</table>
</body></html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=50, help="Number of tickers to sample")
    parser.add_argument("--days", type=int, default=30, help="Days of history to compare")
    parser.add_argument("--tickers", default=None, help="Comma-separated tickers (overrides sample)")
    args = parser.parse_args()

    if not FOUNDATION_DB.exists():
        print(f"Foundation DB not found: {FOUNDATION_DB}")
        return

    try:
        creds = load_credentials()
        api_key = creds["api_key"]
        if api_key == "YOUR_FINNHUB_API_KEY":
            print("❌ Please configure Finnhub credentials first:")
            print(f"   Edit: {CREDENTIALS_PATH}")
            return
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        tickers = get_sample_tickers(FOUNDATION_DB, args.sample)

    end = date.today()
    start = end - timedelta(days=args.days)

    print(f"🔍 Cross-validating {len(tickers)} tickers from {start} to {end}")
    print(f"   yfinance source: {FOUNDATION_DB}")
    print(f"   Finnhub source:  API (free tier, 60 calls/min)")

    results = []
    for i, ticker in enumerate(tickers):
        print(f"\n[{i + 1}/{len(tickers)}] {ticker}...")
        try:
            yf_df = get_yfinance_data(FOUNDATION_DB, ticker, start, end)
            fh_df = get_finnhub_data(ticker, start, end, api_key)
            result = compare_series(yf_df, fh_df, ticker)
            results.append(result)
            if "error" in result:
                print(f"   ⚠️ {result['error']}: yf={result['yf_rows']}, fh={result['fh_rows']}")
            else:
                print(
                    f"   ✓ overlap={result['overlap_days']} days, max_diff={result['close_max_diff_pct']:.4f}%, avg_diff={result['close_avg_diff_pct']:.4f}%"
                )
        except Exception as e:
            print(f"   ❌ Error: {e}")
            results.append({"ticker": ticker, "error": str(e)})

        # Rate limit: 60 calls/min = 1 call/sec
        time.sleep(1)

    # Generate report
    report = generate_report(results, start, end)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUT_DIR / f"finnhub_yfinance_audit_{date_str}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n📄 JSON: {json_path}")

    md_lines = [
        f"# 🔍 Finnhub vs yfinance 数据交叉验证报告",
        f"",
        f"**日期范围**: {start} ~ {end}",
        f"**测试股票**: {report['tickers_tested']} 只",
        f"**有效对比**: {report['valid_comparisons']} 只",
        f"",
        f"## 汇总",
        f"",
        f"| 指标 | 数值 |",
        f"|---|---|",
        f"| 平均差异% | {report['close_avg_diff_pct_mean']:.4f}% |",
        f"| 最大差异% | {report['worst_diff_pct']:.4f}% |",
        f"| 差异>1%的股票数 | {report['tickers_with_diff_gt_1pct']} |",
        f"| 差异>0.1%的股票数 | {report['tickers_with_diff_gt_0_1pct']} |",
        f"| 最差股票 | {report['worst_ticker']} |",
        f"",
        f"## 详细对比",
        f"",
        f"| 代码 | 重叠天数 | yf行数 | fh行数 | 最大差异% | 平均差异% | >0.1%天数 | >1%天数 |",
        f"|---|---|---|---|---|---|---|---|",
    ]
    for d in sorted(
        [r for r in report.get("details", []) if "error" not in r],
        key=lambda x: x["close_max_diff_pct"],
        reverse=True,
    ):
        md_lines.append(
            f"| {d['ticker']} | {d['overlap_days']} | {d['yf_rows']} | {d['fh_rows']} | {d['close_max_diff_pct']:.4f}% | {d['close_avg_diff_pct']:.4f}% | {d['days_with_diff_gt_0_1pct']} | {d['days_with_diff_gt_1pct']} |"
        )
    md_path = OUT_DIR / f"finnhub_yfinance_audit_{date_str}.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"📄 MD:   {md_path}")

    html = generate_html(report)
    html_path = PUBLIC_DIR / f"finnhub_yfinance_audit_{date_str}.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"📄 HTML: {html_path}")

    print(f"\n{'=' * 60}")
    print(f"✅ Audit complete!")
    print(f"   Valid comparisons: {report['valid_comparisons']}/{report['tickers_tested']}")
    print(f"   Avg diff: {report['close_avg_diff_pct_mean']:.4f}%")
    print(f"   Worst diff: {report['worst_diff_pct']:.4f}% ({report['worst_ticker']})")
    print(f"   Tickers with >1% diff: {report['tickers_with_diff_gt_1pct']}")


if __name__ == "__main__":
    main()
