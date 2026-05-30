#!/usr/bin/env python3
"""US Stock State Backtest.

Simple backtest: buy when a stock enters B-grade (2+ E/F cycles), sell when it exits.
Compare against SPY buy-and-hold benchmark.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION_DB = ROOT / "outputs" / "us_stock" / "us_foundation.duckdb"
OUT_DIR = ROOT / "outputs" / "us_stock" / "backtest"
PUBLIC_DIR = ROOT / "public"


def _ef_count(mn1: str, w1: str, d1: str) -> int:
    return sum(1 for s in (mn1, w1, d1) if s in ("E", "F"))


@dataclass
class Trade:
    ticker: str
    entry_date: date
    entry_price: float
    exit_date: date | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    pnl: float | None = None
    pnl_pct: float | None = None
    max_drawdown_pct: float = 0.0
    holding_days: int = 0


def load_state_data(foundation_db: Path, start_date: date | None = None, end_date: date | None = None) -> pd.DataFrame:
    """Load state data from foundation DB."""
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        where_clause = ""
        params = []
        if start_date:
            where_clause += " AND state_date >= ?"
            params.append(start_date)
        if end_date:
            where_clause += " AND state_date <= ?"
            params.append(end_date)

        df = con.execute(
            f"""
            SELECT
                stock_code,
                state_date AS date,
                d1_close AS close,
                mn1_state_hex,
                w1_state_hex,
                d1_state_hex
            FROM d1_perspective_state
            WHERE 1=1 {where_clause}
            ORDER BY stock_code, state_date
            """,
            params,
        ).df()
        df["date"] = pd.to_datetime(df["date"])
        df["ef_count"] = df.apply(lambda r: _ef_count(r["mn1_state_hex"], r["w1_state_hex"], r["d1_state_hex"]), axis=1)
        return df
    finally:
        con.close()


def run_backtest(
    df: pd.DataFrame,
    initial_capital: float = 100_000,
    max_positions: int = 10,
    entry_threshold: int = 2,  # ef_count >= 2 (B-grade)
    exit_threshold: int = 2,   # ef_count < 2
    max_holding_days: int = 20,
    stop_loss_pct: float = 0.08,
    commission_pct: float = 0.001,  # 0.1% commission
) -> dict:
    """Run state-based backtest."""

    dates = sorted(df["date"].unique())
    tickers = df["stock_code"].unique()

    # Build lookup: {ticker: {date: row}}
    data_map: dict[str, dict[date, dict]] = {}
    for _, row in df.iterrows():
        ticker = row["stock_code"]
        d = row["date"]
        if ticker not in data_map:
            data_map[ticker] = {}
        data_map[ticker][d] = {
            "close": row["close"],
            "ef_count": row["ef_count"],
            "mn1": row["mn1_state_hex"],
            "w1": row["w1_state_hex"],
            "d1": row["d1_state_hex"],
        }

    # Get SPY data for benchmark
    spy_data = data_map.get("SPY", {})
    if not spy_data:
        # Try to load SPY separately
        print("Warning: SPY not in data, benchmark will be skipped")

    trades: list[Trade] = []
    daily_nav: list[dict] = []

    capital = initial_capital
    positions: dict[str, dict] = {}  # ticker -> {entry_date, entry_price, shares, max_dd}

    for i, current_date in enumerate(dates):
        # Update existing positions (check exit conditions)
        exited = []
        for ticker, pos in positions.items():
            ticker_data = data_map.get(ticker, {})
            row = ticker_data.get(current_date)
            if not row:
                continue

            price = row["close"]
            holding_days = (current_date - pos["entry_date"]).days
            pnl_pct = (price - pos["entry_price"]) / pos["entry_price"]
            pos["max_dd"] = min(pos["max_dd"], pnl_pct)

            exit_reason = None
            if row["ef_count"] < exit_threshold:
                exit_reason = "state_exit"
            elif holding_days >= max_holding_days:
                exit_reason = "max_hold"
            elif pnl_pct <= -stop_loss_pct:
                exit_reason = "stop_loss"

            if exit_reason:
                # Calculate P&L
                shares = pos["shares"]
                gross_pnl = shares * (price - pos["entry_price"])
                commission = shares * (pos["entry_price"] + price) * commission_pct
                net_pnl = gross_pnl - commission
                capital += shares * price - commission

                trades.append(Trade(
                    ticker=ticker,
                    entry_date=pos["entry_date"],
                    entry_price=pos["entry_price"],
                    exit_date=current_date,
                    exit_price=price,
                    exit_reason=exit_reason,
                    pnl=net_pnl,
                    pnl_pct=(price - pos["entry_price"]) / pos["entry_price"] - 2 * commission_pct,
                    max_drawdown_pct=pos["max_dd"],
                    holding_days=holding_days,
                ))
                exited.append(ticker)

        for t in exited:
            del positions[t]

        # Check new entries
        if len(positions) < max_positions:
            # Score all potential entries
            candidates = []
            for ticker in tickers:
                if ticker in positions or ticker == "SPY":
                    continue
                ticker_data = data_map.get(ticker, {})
                prev_row = ticker_data.get(dates[i - 1]) if i > 0 else None
                curr_row = ticker_data.get(current_date)
                if not curr_row or not prev_row:
                    continue

                # Entry: ef_count crosses from < threshold to >= threshold
                if prev_row["ef_count"] < entry_threshold and curr_row["ef_count"] >= entry_threshold:
                    # Score by state strength
                    score = curr_row["ef_count"] * 10 + (1 if curr_row["d1"] in ("E", "F") else 0)
                    candidates.append((ticker, curr_row["close"], score, curr_row))

            # Sort by score, take top slots
            candidates.sort(key=lambda x: -x[2])
            slots = max_positions - len(positions)

            for ticker, price, score, state in candidates[:slots]:
                if capital <= 0:
                    break
                # Equal weight allocation
                allocation = capital / (slots + 1)  # Conservative
                shares = int(allocation / price)
                if shares < 1:
                    continue
                cost = shares * price * (1 + commission_pct)
                if cost > capital:
                    continue

                capital -= cost
                positions[ticker] = {
                    "entry_date": current_date,
                    "entry_price": price,
                    "shares": shares,
                    "max_dd": 0.0,
                    "state": state,
                }

        # Calculate NAV
        portfolio_value = capital
        for ticker, pos in positions.items():
            ticker_data = data_map.get(ticker, {})
            row = ticker_data.get(current_date)
            if row:
                portfolio_value += pos["shares"] * row["close"]

        spy_close = spy_data.get(current_date, {}).get("close")
        daily_nav.append({
            "date": current_date,
            "nav": portfolio_value,
            "cash": capital,
            "positions": len(positions),
            "spy_close": spy_close,
        })

    # Calculate metrics
    closed_trades = [t for t in trades if t.exit_date is not None]
    winning_trades = [t for t in closed_trades if (t.pnl or 0) > 0]
    losing_trades = [t for t in closed_trades if (t.pnl or 0) <= 0]

    total_pnl = sum(t.pnl for t in closed_trades if t.pnl is not None)
    win_rate = len(winning_trades) / len(closed_trades) * 100 if closed_trades else 0
    avg_win = sum(t.pnl_pct for t in winning_trades) / len(winning_trades) if winning_trades else 0
    avg_loss = sum(t.pnl_pct for t in losing_trades) / len(losing_trades) if losing_trades else 0
    profit_factor = abs(sum(t.pnl for t in winning_trades) / sum(t.pnl for t in losing_trades)) if losing_trades and sum(t.pnl for t in losing_trades) != 0 else float('inf')

    # Calculate max drawdown from NAV curve
    nav_df = pd.DataFrame(daily_nav)
    nav_df["peak"] = nav_df["nav"].cummax()
    nav_df["drawdown"] = (nav_df["nav"] - nav_df["peak"]) / nav_df["peak"]
    max_dd = nav_df["drawdown"].min()

    # Benchmark comparison
    if spy_close and spy_data:
        first_spy = next(iter(spy_data.values()))["close"]
        last_spy = spy_close
        spy_return = (last_spy - first_spy) / first_spy
    else:
        spy_return = None

    strategy_return = (nav_df["nav"].iloc[-1] - initial_capital) / initial_capital if len(nav_df) > 0 else 0

    return {
        "initial_capital": initial_capital,
        "final_nav": round(nav_df["nav"].iloc[-1], 2) if len(nav_df) > 0 else initial_capital,
        "total_return_pct": round(strategy_return * 100, 2),
        "spy_return_pct": round(spy_return * 100, 2) if spy_return else None,
        "total_trades": len(closed_trades),
        "win_rate": round(win_rate, 2),
        "avg_win_pct": round(avg_win * 100, 2),
        "avg_loss_pct": round(avg_loss * 100, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "avg_holding_days": round(sum(t.holding_days for t in closed_trades) / len(closed_trades), 1) if closed_trades else 0,
        "trades": [
            {
                "ticker": t.ticker,
                "entry_date": str(t.entry_date),
                "entry_price": round(t.entry_price, 2),
                "exit_date": str(t.exit_date),
                "exit_price": round(t.exit_price, 2) if t.exit_price else None,
                "exit_reason": t.exit_reason,
                "pnl": round(t.pnl, 2) if t.pnl else None,
                "pnl_pct": round(t.pnl_pct * 100, 2) if t.pnl_pct else None,
                "holding_days": t.holding_days,
                "max_dd_pct": round(t.max_drawdown_pct * 100, 2),
            }
            for t in closed_trades
        ],
        "daily_nav": [
            {"date": str(r["date"]), "nav": round(r["nav"], 2), "cash": round(r["cash"], 2), "positions": r["positions"]}
            for r in daily_nav
        ],
    }


def generate_html(report: dict, params: dict) -> str:
    """Generate HTML backtest report."""
    trades = report["trades"]
    nav = report["daily_nav"]

    # NAV chart data
    nav_dates = [n["date"] for n in nav]
    nav_values = [n["nav"] for n in nav]
    nav_json = json.dumps({"dates": nav_dates, "values": nav_values})

    # Trade table
    rows = ""
    for t in sorted(trades, key=lambda x: x["pnl_pct"] if x["pnl_pct"] is not None else 0, reverse=True):
        color = "#27ae60" if (t["pnl"] or 0) > 0 else "#e74c3c"
        rows += f"""
        <tr>
            <td><strong>{t['ticker']}</strong></td>
            <td>{t['entry_date']}</td>
            <td>${t['entry_price']}</td>
            <td>{t['exit_date']}</td>
            <td>${t['exit_price']}</td>
            <td style="color:{color}">{t['pnl_pct']:+.2f}%</td>
            <td>{t['holding_days']}</td>
            <td>{t['exit_reason']}</td>
        </tr>
        """

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>US State Backtest Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#0f0f23; color:#e0e0e0; margin:0; padding:20px; }}
h1 {{ color:#fff; }} .subtitle {{ color:#888; font-size:14px; margin-bottom:20px; }}
.stats {{ display:flex; gap:15px; margin-bottom:20px; flex-wrap:wrap; }}
.stat-card {{ background:#1a1a2e; border-radius:8px; padding:15px 20px; min-width:120px; text-align:center; }}
.stat-card .num {{ font-size:24px; font-weight:bold; }}
.stat-card .label {{ font-size:12px; color:#888; margin-top:5px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#1a1a2e; color:#888; padding:10px; text-align:left; position:sticky; top:0; }}
td {{ padding:10px; border-bottom:1px solid #222; }}
tr:hover {{ background:#1a1a2e; }}
.chart-container {{ background:#1a1a2e; border-radius:8px; padding:20px; margin:20px 0; height:400px; }}
.guardrail {{ background:#1a1a2e; border-left:3px solid #e74c3c; padding:15px; margin:20px 0; border-radius:4px; font-size:13px; color:#ccc; }}
</style></head><body>
<h1>📈 US State Backtest Report</h1>
<div class="subtitle">Strategy: Buy on B-grade entry (≥2 E/F), Sell on state exit / {params['max_holding_days']} days / -{params['stop_loss_pct']*100:.0f}% stop | Max positions: {params['max_positions']}</div>

<div class="stats">
    <div class="stat-card"><div class="num" style="color:#3498db">${report['final_nav']:,.0f}</div><div class="label">Final NAV</div></div>
    <div class="stat-card"><div class="num" style="color:#{'27ae60' if report['total_return_pct'] > 0 else 'e74c3c'}">{report['total_return_pct']:+.2f}%</div><div class="label">Strategy Return</div></div>
    <div class="stat-card"><div class="num" style="color:#f39c12">{report['win_rate']:.1f}%</div><div class="label">Win Rate</div></div>
    <div class="stat-card"><div class="num" style="color:#e74c3c">{report['max_drawdown_pct']:.2f}%</div><div class="label">Max Drawdown</div></div>
    <div class="stat-card"><div class="num">{report['total_trades']}</div><div class="label">Total Trades</div></div>
    <div class="stat-card"><div class="num">{report['profit_factor']:.2f}</div><div class="label">Profit Factor</div></div>
</div>

<div class="chart-container">
    <canvas id="navChart"></canvas>
</div>

<div class="guardrail">
    <strong>⚠️ 研究用途声明</strong><br>
    本回测为简化模拟，未考虑滑点、流动性、市场冲击等因素。State 信号 ≠ 实盘交易信号，仅供研究参考。
</div>

<h2>Trade Log (Top 50 by P&L)</h2>
<table>
<thead><tr><th>代码</th><th>入场日</th><th>入场价</th><th>出场日</th><th>出场价</th><th>P&L</th><th>持有天数</th><th>出场原因</th></tr></thead>
<tbody>{rows}</tbody>
</table>

<script>
const navData = {nav_json};
new Chart(document.getElementById('navChart'), {{
    type: 'line',
    data: {{
        labels: navData.dates,
        datasets: [{{
            label: 'Portfolio NAV',
            data: navData.values,
            borderColor: '#3498db',
            backgroundColor: 'rgba(52, 152, 219, 0.1)',
            fill: true,
            tension: 0.1
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ ticks: {{ color: '#888', maxTicksLimit: 10 }} }},
            y: {{ ticks: {{ color: '#888' }} }}
        }}
    }}
}});
</script>
</body></html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-02", help="Backtest start date")
    parser.add_argument("--end", default="2025-12-30", help="Backtest end date")
    parser.add_argument("--capital", type=float, default=100_000, help="Initial capital")
    parser.add_argument("--max-positions", type=int, default=10, help="Max concurrent positions")
    parser.add_argument("--entry-threshold", type=int, default=2, help="Min ef_count to enter")
    parser.add_argument("--max-holding-days", type=int, default=20, help="Max holding period")
    parser.add_argument("--stop-loss", type=float, default=0.08, help="Stop loss percentage")
    parser.add_argument("--foundation-db", type=Path, default=FOUNDATION_DB)
    args = parser.parse_args()

    print("=" * 60)
    print("📈 US State Backtest")
    print("=" * 60)
    print(f"Period: {args.start} ~ {args.end}")
    print(f"Capital: ${args.capital:,.0f}")
    print(f"Max positions: {args.max_positions}")
    print(f"Entry: ef_count >= {args.entry_threshold}")
    print(f"Exit: state_exit / {args.max_holding_days} days / -{args.stop_loss*100:.0f}% stop")
    print()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    print("Loading state data...")
    df = load_state_data(args.foundation_db, start, end)
    print(f"  Loaded: {len(df)} rows, {df['stock_code'].nunique()} tickers, {df['date'].nunique()} days")

    print("\nRunning backtest...")
    report = run_backtest(
        df,
        initial_capital=args.capital,
        max_positions=args.max_positions,
        entry_threshold=args.entry_threshold,
        max_holding_days=args.max_holding_days,
        stop_loss_pct=args.stop_loss,
    )

    # Print summary
    print(f"\n{'='*60}")
    print(f"📊 RESULTS")
    print(f"{'='*60}")
    print(f"Final NAV:       ${report['final_nav']:,.2f}")
    print(f"Total Return:    {report['total_return_pct']:+.2f}%")
    if report['spy_return_pct'] is not None:
        print(f"SPY Return:      {report['spy_return_pct']:+.2f}%")
        print(f"Alpha:           {report['total_return_pct'] - report['spy_return_pct']:+.2f}%")
    print(f"Total Trades:    {report['total_trades']}")
    print(f"Win Rate:        {report['win_rate']:.1f}%")
    print(f"Avg Win:         {report['avg_win_pct']:+.2f}%")
    print(f"Avg Loss:        {report['avg_loss_pct']:+.2f}%")
    print(f"Profit Factor:   {report['profit_factor']:.2f}")
    print(f"Max Drawdown:    {report['max_drawdown_pct']:.2f}%")
    print(f"Avg Hold Days:   {report['avg_holding_days']}")

    # Exit reason breakdown
    from collections import Counter
    reasons = Counter(t["exit_reason"] for t in report["trades"])
    print(f"\nExit Reasons:")
    for reason, count in reasons.most_common():
        print(f"  {reason}: {count}")

    # Save outputs
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    json_path = OUT_DIR / f"us_state_backtest_{date_str}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n📄 JSON: {json_path}")

    params = {
        "max_positions": args.max_positions,
        "max_holding_days": args.max_holding_days,
        "stop_loss_pct": args.stop_loss,
    }
    html = generate_html(report, params)
    html_path = PUBLIC_DIR / f"us_state_backtest_{date_str}.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"📄 HTML: {html_path}")

    print(f"\n✅ Backtest complete!")


if __name__ == "__main__":
    main()
