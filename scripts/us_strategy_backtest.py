#!/usr/bin/env python3
"""US stock three-strategy full backtest with leverage support.

Runs VCP/2560/Bollinger signals with State environment matching,
proper entry/exit rules, leverage mechanics, and SPY benchmark comparison.

Leverage model (margin account):
  - buying_power = equity * leverage
  - cash can go negative (borrowed)
  - daily interest on max(0, -cash) * borrow_rate / 252
  - margin_call when equity < initial_capital * margin_call_threshold
  - on margin_call: liquidate ALL positions, stop trading
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from us_strategy_signals import compute_us_signals_for_date, compute_enriched_us_signals_for_date, SIGNAL_META

US_FOUNDATION_DB = ROOT / "outputs" / "us_stock" / "us_foundation.duckdb"
OUT_DIR = ROOT / "outputs" / "us_stock" / "backtest"


@dataclass
class Position:
    stock_code: str
    strategy_id: str
    entry_date: str
    entry_price: float
    shares: int
    signal_name: str
    ef_count: int = 0
    highest_price: float = 0.0
    hold_days: int = 0
    entry_atr: float = 0.0


@dataclass
class Trade:
    stock_code: str
    strategy_id: str
    signal_name: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    exit_reason: str
    pnl_pct: float
    hold_days: int
    ef_count: int


def load_all_dates(foundation_db: Path) -> list[str]:
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT CAST(date AS VARCHAR) FROM daily_bars ORDER BY date"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def load_prices_for_date(foundation_db: Path, trade_date: str) -> dict[str, dict]:
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT stock_code, open, high, low, close, volume
            FROM daily_bars WHERE date = CAST(? AS DATE)
            """,
            (trade_date,),
        ).fetchall()
        return {
            r[0]: {"open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
            for r in rows if r[4] and r[4] > 0
        }
    finally:
        con.close()


def load_ma_values(foundation_db: Path, stock_code: str, trade_date: str) -> dict:
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT close FROM daily_bars
            WHERE stock_code = ? AND date <= CAST(? AS DATE)
            ORDER BY date DESC LIMIT 60
            """,
            (stock_code, trade_date),
        ).fetchall()
        if len(rows) < 25:
            return {}
        closes = [r[0] for r in reversed(rows)]
        return {
            "ma25": sum(closes[-25:]) / 25,
            "ma60": sum(closes[-60:]) / 60 if len(closes) >= 60 else sum(closes) / len(closes),
            "close": closes[-1],
        }
    finally:
        con.close()


def check_exit(
    pos: Position,
    current_price: float,
    ma_data: dict,
    hold_days: int,
) -> str | None:
    """Check exit conditions for a position."""
    pnl_pct = (current_price - pos.entry_price) / pos.entry_price

    # Hard stop loss: -8%
    if pnl_pct <= -0.08:
        return "hard_stop"

    # Strategy-specific exits
    if pos.strategy_id == "ma2560":
        ma25 = ma_data.get("ma25", 0)
        ma60 = ma_data.get("ma60", 0)
        if ma60 > 0 and current_price < ma60:
            return "ma60_break"
        if ma25 > 0 and current_price < ma25:
            return "ma25_break"
        if pnl_pct >= 0.10:
            return "profit_10pct"
        if pnl_pct >= 0.05:
            return "profit_5pct"

    elif pos.strategy_id == "vcp":
        # Trailing stop: if price drops below entry after being up 5%+
        if pos.highest_price >= pos.entry_price * 1.05 and current_price <= pos.entry_price:
            return "trailing_stop"
        if hold_days > 20 and pnl_pct < 0.05:
            return "time_exit"

    elif pos.strategy_id == "bollinger_bandit":
        # Degrading MA exit
        exit_ma_period = max(10, 50 - hold_days)
        # Simplified: use MA25 as proxy
        ma25 = ma_data.get("ma25", 0)
        if ma25 > 0 and current_price < ma25:
            return "degrading_ma_exit"
        if hold_days > 10 and pnl_pct < 0.05:
            return "time_exit"

    # Max hold: 60 days
    if hold_days >= 60:
        return "max_hold"

    return None


def run_backtest(
    foundation_db: Path,
    start_date: str,
    end_date: str,
    initial_capital: float = 1_000_000,
    max_positions: int = 10,
    risk_per_trade: float = 0.02,
    min_ef: int = 2,
    strategy_filter: str = "all",
    leverage: float = 1.0,
    borrow_rate: float = 0.05,
    margin_call_threshold: float = 0.25,
) -> dict[str, Any]:
    """Run full three-strategy backtest on US stocks with leverage support."""
    all_dates = load_all_dates(foundation_db)
    trade_dates = [d for d in all_dates if start_date <= d <= end_date]

    if not trade_dates:
        return {"error": "No trading dates in range"}

    cash = initial_capital
    positions: dict[str, Position] = {}
    trades: list[Trade] = []
    daily_nav: list[dict] = []
    spy_start = None
    margin_called = False
    margin_call_date = ""
    total_borrow_cost = 0.0
    max_borrowed = 0.0

    print(f"Running backtest: {start_date} to {end_date} ({len(trade_dates)} days)")
    print(f"Initial capital: ${initial_capital:,.0f}, Max positions: {max_positions}")
    print(f"Strategy: {strategy_filter}, Leverage: {leverage}x, Borrow rate: {borrow_rate:.1%}")
    print(f"Margin call threshold: {margin_call_threshold:.0%}")

    for i, trade_date in enumerate(trade_dates):
        if margin_called:
            # After margin call, track flat NAV
            daily_nav.append({
                "date": trade_date,
                "nav": round(cash, 2),
                "positions": 0,
                "spy_return": round(daily_nav[-1]["spy_return"], 4) if daily_nav else 0,
            })
            continue

        prices = load_prices_for_date(foundation_db, trade_date)

        # ── 1. Update existing positions & check exits ──
        exited = []
        for code, pos in positions.items():
            px = prices.get(code)
            if not px:
                continue
            current = px["close"]
            pos.hold_days += 1
            pos.highest_price = max(pos.highest_price, current)

            ma_data = load_ma_values(foundation_db, code, trade_date)
            exit_reason = check_exit(pos, current, ma_data, pos.hold_days)

            if exit_reason:
                pnl_pct = (current - pos.entry_price) / pos.entry_price
                cash += pos.shares * current
                trades.append(Trade(
                    stock_code=code,
                    strategy_id=pos.strategy_id,
                    signal_name=pos.signal_name,
                    entry_date=pos.entry_date,
                    entry_price=pos.entry_price,
                    exit_date=trade_date,
                    exit_price=current,
                    exit_reason=exit_reason,
                    pnl_pct=pnl_pct,
                    hold_days=pos.hold_days,
                    ef_count=pos.ef_count,
                ))
                exited.append(code)

        for code in exited:
            del positions[code]

        # ── 2. Calculate current equity & margin status ──
        position_value = sum(
            prices.get(code, {}).get("close", pos.entry_price) * pos.shares
            for code, pos in positions.items()
        )
        equity = cash + position_value
        nav = equity

        # Daily borrowing cost on negative cash
        borrowed = max(0.0, -cash)
        if borrowed > 0:
            daily_interest = borrowed * borrow_rate / 252
            cash -= daily_interest
            total_borrow_cost += daily_interest
            equity = cash + position_value
            nav = equity
            max_borrowed = max(max_borrowed, borrowed)

        # Margin call check
        if equity < initial_capital * margin_call_threshold:
            margin_called = True
            margin_call_date = trade_date
            # Liquidate all positions at today's close
            for code, pos in list(positions.items()):
                px = prices.get(code)
                if px:
                    cash += pos.shares * px["close"]
                    pnl_pct = (px["close"] - pos.entry_price) / pos.entry_price
                    trades.append(Trade(
                        stock_code=code,
                        strategy_id=pos.strategy_id,
                        signal_name=pos.signal_name,
                        entry_date=pos.entry_date,
                        entry_price=pos.entry_price,
                        exit_date=trade_date,
                        exit_price=px["close"],
                        exit_reason="margin_call_liquidation",
                        pnl_pct=pnl_pct,
                        hold_days=pos.hold_days,
                        ef_count=pos.ef_count,
                    ))
            positions.clear()
            nav = cash
            print(f"  ⚠ MARGIN CALL on {trade_date}: equity=${equity:,.0f} < threshold=${initial_capital*margin_call_threshold:,.0f}")

        # ── 3. Generate signals & enter new positions ──
        if not margin_called and len(positions) < max_positions:
            signals = compute_enriched_us_signals_for_date(foundation_db, trade_date, min_ef)
            entry_signals = [s for s in signals if s["signal_type"] == "entry"]

            # Filter by strategy if specified
            if strategy_filter != "all":
                entry_signals = [s for s in entry_signals if s.get("strategy_id") == strategy_filter]

            # ── P0: 核心模块过滤 ──
            filtered_signals = []
            for s in entry_signals:
                # 1. strategy_environment_fit: 拒绝弱适配
                fit_level = s.get("fit_level", "")
                if fit_level == "弱适配":
                    continue

                # 2. market_phase: 收缩期/风险释放期不开仓
                phase = s.get("market_phase", "")
                if phase in ("risk_release", "contraction"):
                    continue

                # 3. 空间评估: RR < 1.0 跳过
                rr = s.get("rr_ratio")
                if rr is not None and rr < 1.0:
                    continue

                filtered_signals.append(s)

            entry_signals = filtered_signals

            # Sort by ef_count desc, then signal_strength desc
            entry_signals.sort(key=lambda s: (-(s.get("ef_count") or 0), -(s.get("signal_strength") or 0)))

            slots = max_positions - len(positions)
            for sig in entry_signals[:slots]:
                code = sig["stock_code"]
                if code in positions:
                    continue
                px = prices.get(code)
                if not px or px["close"] <= 0:
                    continue

                entry_price = px["close"]

                # Leverage-aware position sizing
                buying_power = equity * leverage
                allocated_cap = buying_power * risk_per_trade / 0.08
                shares = max(1, int(allocated_cap / entry_price))
                cost = shares * entry_price

                # Max 20% of buying power per position
                max_cost = buying_power * 0.2
                if cost > max_cost:
                    shares = max(1, int(max_cost / entry_price))
                    cost = shares * entry_price

                # Check if we have enough buying power
                if cost > buying_power:
                    continue

                cash -= cost
                positions[code] = Position(
                    stock_code=code,
                    strategy_id=sig["strategy_id"],
                    entry_date=trade_date,
                    entry_price=entry_price,
                    shares=shares,
                    signal_name=sig["signal_name"],
                    ef_count=sig.get("ef_count", 0),
                    highest_price=entry_price,
                    entry_atr=0,
                )

        # ── 4. Track SPY benchmark & daily NAV ──
        spy_px = prices.get("SPY")
        if spy_px and spy_start is None:
            spy_start = spy_px["close"]

        position_value = sum(
            prices.get(code, {}).get("close", pos.entry_price) * pos.shares
            for code, pos in positions.items()
        )
        equity = cash + position_value
        nav = equity
        spy_ret = (spy_px["close"] / spy_start - 1) if spy_px and spy_start else 0

        daily_nav.append({
            "date": trade_date,
            "nav": round(nav, 2),
            "cash": round(cash, 2),
            "position_value": round(position_value, 2),
            "equity": round(equity, 2),
            "borrowed": round(max(0.0, -cash), 2),
            "positions": len(positions),
            "spy_return": round(spy_ret, 4),
        })

        if (i + 1) % 50 == 0:
            print(f"  Day {i+1}/{len(trade_dates)}: NAV=${nav:,.0f}, Equity=${equity:,.0f}, Cash=${cash:,.0f}, Pos={len(positions)}, Trades={len(trades)}")

    # ── 5. Final liquidation ──
    final_date = trade_dates[-1]
    final_prices = load_prices_for_date(foundation_db, final_date)
    for code, pos in list(positions.items()):
        px = final_prices.get(code)
        if px:
            pnl_pct = (px["close"] - pos.entry_price) / pos.entry_price
            cash += pos.shares * px["close"]
            trades.append(Trade(
                stock_code=code, strategy_id=pos.strategy_id,
                signal_name=pos.signal_name, entry_date=pos.entry_date,
                entry_price=pos.entry_price, exit_date=final_date,
                exit_price=px["close"], exit_reason="end_of_backtest",
                pnl_pct=pnl_pct, hold_days=pos.hold_days, ef_count=pos.ef_count,
            ))
    positions.clear()

    # ── 6. Compute statistics ──
    winning = [t for t in trades if t.pnl_pct > 0]
    losing = [t for t in trades if t.pnl_pct <= 0]
    pnl_list = [t.pnl_pct for t in trades]

    final_nav = daily_nav[-1]["nav"] if daily_nav else initial_capital
    total_return = (final_nav - initial_capital) / initial_capital
    spy_final = daily_nav[-1]["spy_return"] if daily_nav else 0

    # Max drawdown
    peak = initial_capital
    max_dd = 0.0
    max_dd_start = ""
    peak_date = ""
    for nav_row in daily_nav:
        if nav_row["nav"] > peak:
            peak = nav_row["nav"]
            peak_date = nav_row["date"]
        dd = (peak - nav_row["nav"]) / peak
        if dd > max_dd:
            max_dd = dd
            max_dd_start = peak_date

    # Sharpe (simplified, using daily returns)
    if len(daily_nav) > 1:
        daily_returns = []
        for i in range(1, len(daily_nav)):
            r = (daily_nav[i]["nav"] - daily_nav[i-1]["nav"]) / daily_nav[i-1]["nav"]
            daily_returns.append(r)
        avg_r = statistics.mean(daily_returns)
        std_r = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 1
        sharpe = (avg_r / std_r * (252 ** 0.5)) if std_r > 0 else 0
    else:
        sharpe = 0

    # Calmar = annualized return / max drawdown
    trading_days = len(trade_dates)
    annualized_return = ((1 + total_return) ** (252 / trading_days) - 1) if trading_days > 0 else 0
    calmar = annualized_return / max_dd if max_dd > 0 else 0

    # By strategy
    by_strategy = {}
    for sid in set(t.strategy_id for t in trades):
        st = [t for t in trades if t.strategy_id == sid]
        sw = [t for t in st if t.pnl_pct > 0]
        by_strategy[sid] = {
            "trades": len(st),
            "win_rate": round(len(sw) / len(st), 4) if st else 0,
            "avg_pnl": round(statistics.mean([t.pnl_pct for t in st]), 4) if st else 0,
            "avg_hold_days": round(statistics.mean([t.hold_days for t in st]), 1) if st else 0,
        }

    result = {
        "schema_version": "us_backtest_v2_leverage",
        "start_date": start_date,
        "end_date": end_date,
        "trading_days": trading_days,
        "initial_capital": initial_capital,
        "final_nav": round(final_nav, 2),
        "total_return": round(total_return, 4),
        "annualized_return": round(annualized_return, 4),
        "spy_return": round(spy_final, 4),
        "excess_return": round(total_return - spy_final, 4),
        "max_drawdown": round(max_dd, 4),
        "sharpe_ratio": round(sharpe, 3),
        "calmar_ratio": round(calmar, 3),
        "total_trades": len(trades),
        "win_rate": round(len(winning) / len(trades), 4) if trades else 0,
        "avg_pnl_pct": round(statistics.mean(pnl_list), 4) if pnl_list else 0,
        "avg_hold_days": round(statistics.mean([t.hold_days for t in trades]), 1) if trades else 0,
        "by_strategy": by_strategy,
        "exit_reasons": dict(sorted(
            Counter(t.exit_reason for t in trades).items(),
            key=lambda x: -x[1],
        )),
        "leverage": leverage,
        "borrow_rate": borrow_rate,
        "margin_call_threshold": margin_call_threshold,
        "margin_called": margin_called,
        "margin_call_date": margin_call_date,
        "total_borrow_cost": round(total_borrow_cost, 2),
        "max_borrowed": round(max_borrowed, 2),
        "strategy_filter": strategy_filter,
        "trades": [
            {
                "stock_code": t.stock_code,
                "strategy_id": t.strategy_id,
                "entry_date": t.entry_date,
                "entry_price": round(t.entry_price, 2),
                "exit_date": t.exit_date,
                "exit_price": round(t.exit_price, 2),
                "exit_reason": t.exit_reason,
                "pnl_pct": round(t.pnl_pct, 4),
                "hold_days": t.hold_days,
            }
            for t in trades
        ],
        "daily_nav": daily_nav,
        "research_only": True,
    }

    # Write output
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    strat_tag = strategy_filter if strategy_filter != "all" else "all"
    lev_tag = f"{leverage:.0f}x"
    out_json = OUT_DIR / f"us_backtest_{strat_tag}_lev{lev_tag}_{ymd(start_date)}_{ymd(end_date)}.json"
    text = json.dumps(result, ensure_ascii=False, indent=2)
    out_json.write_text(text, encoding="utf-8")

    return result


def ymd(d: str) -> str:
    return d.replace("-", "")


def main() -> int:
    parser = argparse.ArgumentParser(description="US stock strategy backtest with leverage support")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--db", default=str(US_FOUNDATION_DB))
    parser.add_argument("--capital", type=float, default=1_000_000)
    parser.add_argument("--max-positions", type=int, default=10)
    parser.add_argument("--min-ef", type=int, default=2)
    parser.add_argument("--strategy", default="all", choices=["all", "vcp", "ma2560", "bollinger_bandit"],
                        help="Filter to a single strategy")
    parser.add_argument("--leverage", type=float, default=1.0, help="Leverage multiplier (1.0, 2.0, 3.0)")
    parser.add_argument("--borrow-rate", type=float, default=0.05, help="Annual borrow rate (default 5%%)")
    parser.add_argument("--margin-call-threshold", type=float, default=0.25,
                        help="Equity / initial_capital threshold for margin call (default 0.25)")
    args = parser.parse_args()

    result = run_backtest(
        Path(args.db), args.start_date, args.end_date,
        initial_capital=args.capital,
        max_positions=args.max_positions,
        min_ef=args.min_ef,
        strategy_filter=args.strategy,
        leverage=args.leverage,
        borrow_rate=args.borrow_rate,
        margin_call_threshold=args.margin_call_threshold,
    )

    # Print summary
    print("\n" + "=" * 60)
    print("US STOCK BACKTEST SUMMARY")
    print("=" * 60)
    print(f"Period: {result['start_date']} to {result['end_date']}")
    print(f"Strategy: {result['strategy_filter']} | Leverage: {result['leverage']}x")
    print(f"Trading Days: {result['trading_days']}")
    print(f"Total Return: {result['total_return']:.2%}")
    print(f"Annualized Return: {result.get('annualized_return', 0):.2%}")
    print(f"SPY Return: {result['spy_return']:.2%}")
    print(f"Excess Return: {result['excess_return']:.2%}")
    print(f"Max Drawdown: {result['max_drawdown']:.2%}")
    print(f"Sharpe Ratio: {result['sharpe_ratio']:.3f}")
    print(f"Calmar Ratio: {result.get('calmar_ratio', 0):.3f}")
    print(f"Total Trades: {result['total_trades']}")
    print(f"Win Rate: {result['win_rate']:.2%}")
    print(f"Avg Hold Days: {result['avg_hold_days']}")
    print(f"Total Borrow Cost: ${result.get('total_borrow_cost', 0):,.2f}")
    print(f"Max Borrowed: ${result.get('max_borrowed', 0):,.2f}")
    if result.get("margin_called"):
        print(f"⚠ MARGIN CALLED on {result['margin_call_date']}")
    print("\nBy Strategy:")
    for sid, stats in result.get("by_strategy", {}).items():
        print(f"  {sid}: {stats['trades']} trades, WR={stats['win_rate']:.2%}, Avg PnL={stats['avg_pnl']:.2%}")
    print("\nExit Reasons:")
    for reason, count in result.get("exit_reasons", {}).items():
        print(f"  {reason}: {count}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
