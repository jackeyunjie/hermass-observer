#!/usr/bin/env python3
"""Trading rules: map State Scan signals to Alpaca orders.

Risk management:
- Max position size per trade (default 5% of equity)
- Stop loss as percentage below entry (default -8%)
- Only trade A/B grade signals
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alpaca_trading.client import AlpacaClient


def calculate_position_size(
    equity: float,
    price: float,
    max_position_pct: float = 0.05,
    min_qty: int = 1,
) -> int:
    """Calculate number of shares to buy given equity and constraints."""
    max_dollar = equity * max_position_pct
    qty = int(max_dollar // price)
    return max(qty, min_qty)


def calculate_stop_price(entry_price: float, stop_loss_pct: float = 0.08) -> float:
    """Calculate stop loss price (below entry for long)."""
    return round(entry_price * (1 - stop_loss_pct), 2)


def filter_signals(
    brief_json: dict[str, Any],
    min_grade: str = "B",
    exclude_tickers: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter brief entries down to actionable signals."""
    grade_order = {"A": 0, "B": 1, "C": 2, "D": 3}
    min_grade_val = grade_order.get(min_grade, 1)
    exclude = exclude_tickers or set()

    signals = []
    for entry in brief_json.get("entries", []):
        ticker = entry["ticker"]
        grade = entry.get("grade", "D")
        if grade_order.get(grade, 99) > min_grade_val:
            continue
        if ticker in exclude:
            continue
        # Skip ETFs for stock signals (optional)
        if ticker in ("SPY", "QQQ", "VOO", "IVV", "GLD", "USO", "SH", "FAS"):
            continue
        signals.append(entry)
    return signals


def plan_orders(
    signals: list[dict[str, Any]],
    equity: float,
    existing_positions: list[dict[str, Any]],
    max_position_pct: float = 0.05,
    stop_loss_pct: float = 0.08,
) -> list[dict[str, Any]]:
    """Generate order plans from signals."""
    existing_symbols = {p["symbol"] for p in existing_positions}
    plans = []

    for sig in signals:
        ticker = sig["ticker"]
        if ticker in existing_symbols:
            continue  # Already holding

        price = sig.get("close", 0)
        if price <= 0:
            continue

        qty = calculate_position_size(equity, price, max_position_pct)
        stop_price = calculate_stop_price(price, stop_loss_pct)
        notional = round(qty * price, 2)
        risk = round(notional * stop_loss_pct, 2)

        plans.append({
            "symbol": ticker,
            "grade": sig.get("grade", "D"),
            "qty": qty,
            "entry_price": price,
            "notional": notional,
            "stop_price": stop_price,
            "stop_loss_pct": stop_loss_pct,
            "risk_amount": risk,
            "mn1": sig.get("mn1", "-"),
            "w1": sig.get("w1", "-"),
            "d1": sig.get("d1", "-"),
            "ef_count": sig.get("ef_count", 0),
            "d1_adx14": sig.get("d1_adx14"),
            "d1_trend": sig.get("d1_trend", "-"),
            "sr_direction": sig.get("sr_direction", "-"),
            "sr_distance_pct": sig.get("sr_distance_pct"),
        })

    return plans


def print_plan_table(plans: list[dict[str, Any]]) -> None:
    """Print order plans in a readable table."""
    if not plans:
        print("No actionable signals.")
        return

    print(f"\n{'='*100}")
    print(f"{'Symbol':<8} {'Grade':<6} {'Qty':>6} {'Entry':>10} {'Notional':>12} {'Stop':>10} {'Risk':>10} {'State':<15}")
    print(f"{'-'*100}")
    total_notional = 0
    total_risk = 0
    for p in plans:
        state_str = f"{p['mn1']}/{p['w1']}/{p['d1']}"
        print(
            f"{p['symbol']:<8} {p['grade']:<6} {p['qty']:>6} "
            f"${p['entry_price']:>8.2f} ${p['notional']:>10.2f} "
            f"${p['stop_price']:>8.2f} ${p['risk_amount']:>8.2f} {state_str:<15}"
        )
        total_notional += p["notional"]
        total_risk += p["risk_amount"]
    print(f"{'-'*100}")
    print(f"{'TOTAL':<8} {'':<6} {'':>6} {'':>10} ${total_notional:>10.2f} {'':>10} ${total_risk:>8.2f}")
    print(f"{'='*100}")


def execute_plans(
    plans: list[dict[str, Any]],
    client: AlpacaClient,
    dry_run: bool = True,
) -> list[dict[str, Any]]:
    """Submit orders to Alpaca (or simulate if dry_run)."""
    results = []
    for p in plans:
        if dry_run:
            print(f"[DRY RUN] Would buy {p['qty']} shares of {p['symbol']} @ ${p['entry_price']:.2f}")
            results.append({**p, "order_id": None, "status": "dry_run"})
        else:
            try:
                order = client.submit_market_order(
                    symbol=p["symbol"],
                    qty=p["qty"],
                    side="buy",
                )
                print(f"[LIVE] Submitted order {order['id']} for {p['symbol']}: {p['qty']} shares")
                results.append({**p, "order_id": order["id"], "status": order["status"]})
            except Exception as e:
                print(f"[ERROR] Failed to submit order for {p['symbol']}: {e}")
                results.append({**p, "order_id": None, "status": "error", "error": str(e)})
    return results


def save_trade_log(results: list[dict[str, Any]], out_path: Path) -> None:
    """Append trade results to a JSON log."""
    log: list[dict] = []
    if out_path.exists():
        log = json.loads(out_path.read_text(encoding="utf-8"))
    log.extend(results)
    out_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Generate trading plans from State Scan brief")
    parser.add_argument("--brief", type=Path, required=True, help="Path to us_state_scan_YYYYMMDD.json")
    parser.add_argument("--min-grade", default="B", choices=["A", "B", "C"], help="Minimum signal grade")
    parser.add_argument("--max-position-pct", type=float, default=0.05, help="Max position size as % of equity")
    parser.add_argument("--stop-loss-pct", type=float, default=0.08, help="Stop loss % below entry")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Simulate orders without submitting")
    parser.add_argument("--live", action="store_true", help="Actually submit orders (requires --dry-run to be False)")
    args = parser.parse_args()

    # Load brief
    brief = json.loads(args.brief.read_text(encoding="utf-8"))
    signals = filter_signals(brief, min_grade=args.min_grade)
    print(f"Signals from brief ({brief['date']}): {len(brief.get('entries', []))} total, {len(signals)} actionable (grade ≥ {args.min_grade})")

    # Connect to Alpaca
    client = AlpacaClient()
    account = client.get_account()
    equity = account["equity"]
    positions = client.get_positions()
    print(f"\nAccount: ${equity:,.2f} equity, {len(positions)} positions")

    # Plan orders
    plans = plan_orders(
        signals,
        equity=equity,
        existing_positions=positions,
        max_position_pct=args.max_position_pct,
        stop_loss_pct=args.stop_loss_pct,
    )
    print_plan_table(plans)

    # Execute
    dry_run = not args.live
    if args.live and dry_run:
        print("\n⚠️  Use --live to submit real orders. Running in dry-run mode.")

    if plans:
        results = execute_plans(plans, client, dry_run=dry_run)
        # Save log
        out_dir = Path("outputs/us_stock/trades")
        out_dir.mkdir(parents=True, exist_ok=True)
        log_path = out_dir / "trade_log.json"
        save_trade_log(results, log_path)
        print(f"\nTrade log saved: {log_path}")
    else:
        print("\nNo orders to submit.")


if __name__ == "__main__":
    main()
