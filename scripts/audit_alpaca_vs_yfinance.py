#!/usr/bin/env python3
"""Cross-validate yfinance data against Alpaca Market Data API.

Usage:
    1. Ensure Alpaca credentials are configured:
       cp config/secrets/alpaca_credentials.json.template config/secrets/alpaca_credentials.json
       # Edit and fill in your API key

    2. Run audit:
       python scripts/audit_alpaca_vs_yfinance.py --sample 50 --days 30

Outputs:
    - outputs/us_stock/audit/alpaca_yfinance_audit_YYYYMMDD.json
    - outputs/us_stock/audit/alpaca_yfinance_audit_YYYYMMDD.md
    - public/alpaca_yfinance_audit_YYYYMMDD.html
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

FOUNDATION_DB = ROOT / "outputs" / "us_stock" / "us_foundation.duckdb"
OUT_DIR = ROOT / "outputs" / "us_stock" / "audit"
PUBLIC_DIR = ROOT / "public"


def load_alpaca_credentials() -> dict:
    from alpaca_trading.client import load_credentials
    return load_credentials()


def get_sample_tickers(foundation_db: Path, n: int = 50) -> list[str]:
    """Get a representative sample of tickers from foundation DB."""
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        rows = con.execute(
            f"""
            SELECT DISTINCT stock_code
            FROM daily_bars
            ORDER BY stock_code
            LIMIT {n}
            """
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def get_yfinance_data(foundation_db: Path, ticker: str, start: date, end: date) -> pd.DataFrame:
    """Read historical bars from foundation DB (yfinance source)."""
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


def get_alpaca_data(ticker: str, start: date, end: date, api_key: str, secret_key: str) -> pd.DataFrame:
    """Fetch historical bars from Alpaca Market Data API."""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(api_key, secret_key)
    req = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    bars = client.get_stock_bars(req)
    df = bars.df.reset_index()
    # Alpaca returns MultiIndex (symbol, timestamp); flatten
    if "timestamp" in df.columns:
        df = df.rename(columns={"timestamp": "date"})
    elif "timestamp" in df.index.names:
        df = df.reset_index().rename(columns={"timestamp": "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.set_index("date")
    df = df.rename(columns={
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    })
    return df


def compare_series(yf_df: pd.DataFrame, alp_df: pd.DataFrame, ticker: str) -> dict:
    """Compare two DataFrames and return discrepancy metrics."""
    if yf_df.empty or alp_df.empty:
        return {"ticker": ticker, "error": "missing_data", "yf_rows": len(yf_df), "alp_rows": len(alp_df)}

    # Align by date
    merged = yf_df[["close", "volume"]].join(
        alp_df[["close", "volume"]],
        how="inner",
        lsuffix="_yf",
        rsuffix="_alp",
    )

    if merged.empty:
        return {"ticker": ticker, "error": "no_overlap", "yf_rows": len(yf_df), "alp_rows": len(alp_df)}

    merged["close_diff"] = merged["close_yf"] - merged["close_alp"]
    merged["close_diff_pct"] = (merged["close_diff"] / merged["close_alp"]).abs() * 100
    merged["volume_diff_pct"] = ((merged["volume_yf"] - merged["volume_alp"]).abs() / merged["volume_alp"]) * 100

    return {
        "ticker": ticker,
        "overlap_days": len(merged),
        "yf_rows": len(yf_df),
        "alp_rows": len(alp_df),
        "close_max_diff": round(merged["close_diff"].abs().max(), 4),
        "close_avg_diff_pct": round(merged["close_diff_pct"].mean(), 4),
        "close_max_diff_pct": round(merged["close_diff_pct"].max(), 4),
        "volume_avg_diff_pct": round(merged["volume_diff_pct"].mean(), 2),
        "days_with_diff_gt_1pct": int((merged["close_diff_pct"] > 1.0).sum()),
        "days_with_diff_gt_0_1pct": int((merged["close_diff_pct"] > 0.1).sum()),
    }


def generate_report(results: list[dict], start: date, end: date) -> dict:
    """Generate summary report."""
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
    """Generate HTML report."""
    date_str = report["audit_date"][:10].replace("-", "")
    details = report.get("details", [])
    valid = [d for d in details if "error" not in d]
    errors = [d for d in details if "error" in d]

    rows = ""
    for d in sorted(valid, key=lambda x: x["close_max_diff_pct"], reverse=True):
        color = "#ff6b6b" if d["close_max_diff_pct"] > 1 else "#f9ca24" if d["close_max_diff_pct"] > 0.1 else "#74b9ff"
        rows += f"""
        <tr>
            <td><strong>{d['ticker']}</strong></td>
            <td>{d['overlap_days']}</td>
            <td>{d['yf_rows']}</td>
            <td>{d['alp_rows']}</td>
            <td style="color:{color}">{d['close_max_diff_pct']:.4f}%</td>
            <td>{d['close_avg_diff_pct']:.4f}%</td>
            <td>{d['days_with_diff_gt_0_1pct']}</td>
            <td>{d['days_with_diff_gt_1pct']}</td>
        </tr>
        """

    error_rows = ""
    for e in errors:
        error_rows += f"<tr><td>{e['ticker']}</td><td colspan='7' style='color:#ff6b6b'>{e.get('error', 'unknown')}</td></tr>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>Alpaca vs yfinance Audit - {date_str}</title>
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
<h1>🔍 Alpaca vs yfinance 数据交叉验证报告</h1>
<div class="subtitle">{report['start_date']} ~ {report['end_date']} | 测试 {report['tickers_tested']} 只股票</div>
<div class="stats">
    <div class="stat-card"><div class="num" style="color:#74b9ff">{report['valid_comparisons']}</div><div class="label">有效对比</div></div>
    <div class="stat-card"><div class="num" style="color:#f9ca24">{report['close_avg_diff_pct_mean']:.4f}%</div><div class="label">平均差异</div></div>
    <div class="stat-card"><div class="num" style="color:#ff6b6b">{report['worst_diff_pct']:.4f}%</div><div class="label">最大差异</div></div>
    <div class="stat-card"><div class="num">{report['tickers_with_diff_gt_1pct']}</div><div class="label">差异&gt;1%的股票数</div></div>
</div>
<div class="guardrail"><strong>⚠️ 说明</strong><br>
yfinance 使用 split-adjusted 数据，Alpaca 默认返回 raw + adjustment_factor。差异主要来源于复权方式不同、拆股日期差异、或数据源本身的不一致。差异 &gt; 1% 需要重点排查。
</div>
<table>
<thead><tr><th>代码</th><th>重叠天数</th><th>yfinance行数</th><th>Alpaca行数</th><th>最大差异%</th><th>平均差异%</th><th>&gt;0.1%天数</th><th>&gt;1%天数</th></tr></thead>
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

    # Load credentials
    try:
        creds = load_alpaca_credentials()
        api_key = creds["api_key"]
        secret_key = creds["secret_key"]
        if api_key == "YOUR_ALPACA_API_KEY":
            print("❌ Please configure Alpaca credentials first:")
            print(f"   Edit: config/secrets/alpaca_credentials.json")
            print(f"   Template: config/secrets/alpaca_credentials.json.template")
            return
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return

    # Determine tickers
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        tickers = get_sample_tickers(FOUNDATION_DB, args.sample)

    end = date.today()
    start = end - timedelta(days=args.days)

    print(f"🔍 Cross-validating {len(tickers)} tickers from {start} to {end}")
    print(f"   yfinance source: {FOUNDATION_DB}")
    print(f"   Alpaca source: Market Data API")

    results = []
    for i, ticker in enumerate(tickers):
        print(f"\n[{i+1}/{len(tickers)}] {ticker}...")
        try:
            yf_df = get_yfinance_data(FOUNDATION_DB, ticker, start, end)
            alp_df = get_alpaca_data(ticker, start, end, api_key, secret_key)
            result = compare_series(yf_df, alp_df, ticker)
            results.append(result)
            if "error" in result:
                print(f"   ⚠️ {result['error']}: yf={result['yf_rows']}, alp={result['alp_rows']}")
            else:
                print(f"   ✓ overlap={result['overlap_days']} days, max_diff={result['close_max_diff_pct']:.4f}%, avg_diff={result['close_avg_diff_pct']:.4f}%")
        except Exception as e:
            print(f"   ❌ Error: {e}")
            results.append({"ticker": ticker, "error": str(e)})

    # Generate report
    report = generate_report(results, start, end)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = OUT_DIR / f"alpaca_yfinance_audit_{date_str}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n📄 JSON: {json_path}")

    # Markdown
    md_lines = [
        f"# 🔍 Alpaca vs yfinance 数据交叉验证报告",
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
        f"| 代码 | 重叠天数 | yf行数 | alp行数 | 最大差异% | 平均差异% | >0.1%天数 | >1%天数 |",
        f"|---|---|---|---|---|---|---|---|",
    ]
    for d in sorted([r for r in report.get("details", []) if "error" not in r], key=lambda x: x["close_max_diff_pct"], reverse=True):
        md_lines.append(f"| {d['ticker']} | {d['overlap_days']} | {d['yf_rows']} | {d['alp_rows']} | {d['close_max_diff_pct']:.4f}% | {d['close_avg_diff_pct']:.4f}% | {d['days_with_diff_gt_0_1pct']} | {d['days_with_diff_gt_1pct']} |")
    md_path = OUT_DIR / f"alpaca_yfinance_audit_{date_str}.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"📄 MD:   {md_path}")

    # HTML
    html = generate_html(report)
    html_path = PUBLIC_DIR / f"alpaca_yfinance_audit_{date_str}.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"📄 HTML: {html_path}")

    print(f"\n{'='*60}")
    print(f"✅ Audit complete!")
    print(f"   Valid comparisons: {report['valid_comparisons']}/{report['tickers_tested']}")
    print(f"   Avg diff: {report['close_avg_diff_pct_mean']:.4f}%")
    print(f"   Worst diff: {report['worst_diff_pct']:.4f}% ({report['worst_ticker']})")
    print(f"   Tickers with >1% diff: {report['tickers_with_diff_gt_1pct']}")


if __name__ == "__main__":
    main()
