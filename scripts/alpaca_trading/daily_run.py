#!/usr/bin/env python3
"""Daily run: generate State Scan brief → filter signals → plan orders → (optionally) execute.

This is the main entry point for the US stock trading workflow.

Usage:
    # Generate brief + trading plan (dry run)
    python scripts/alpaca_trading/daily_run.py --dry-run

    # Generate brief + submit orders to Alpaca paper trading
    python scripts/alpaca_trading/daily_run.py --live

Prerequisites:
    1. Alpaca account: https://app.alpaca.markets/signup
    2. API keys saved to config/secrets/alpaca_credentials.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from build_us_daily_brief import build_brief, US_CACHE_DB, US_FOUNDATION_DB, OUT_DIR, PUBLIC_DIR
from alpaca_trading.client import AlpacaClient, load_credentials
from alpaca_trading.rules import (
    filter_signals,
    plan_orders,
    print_plan_table,
    execute_plans,
    save_trade_log,
)

TRADE_LOG_DIR = ROOT / "outputs" / "us_stock" / "trades"


def run(
    dry_run: bool = True,
    min_grade: str = "B",
    max_position_pct: float = 0.05,
    stop_loss_pct: float = 0.08,
) -> dict:
    """Run the full daily workflow."""
    print("=" * 70)
    print("🚀 US Stock Daily Trading Workflow")
    print("=" * 70)

    # Step 1: Generate State Scan brief
    print("\n📊 Step 1: Generating State Scan brief...")
    brief = build_brief(US_CACHE_DB, US_FOUNDATION_DB)
    date_str = brief["date"].replace("-", "")
    print(f"   Date: {brief['date']}")
    print(f"   Signals: {brief['stats']['total']} total | A:{brief['stats']['grade_A']} B:{brief['stats']['grade_B']} C:{brief['stats']['grade_C']} D:{brief['stats']['grade_D']}")

    # Step 2: Filter signals
    print(f"\n🔍 Step 2: Filtering signals (min grade: {min_grade})...")
    signals = filter_signals(brief, min_grade=min_grade)
    print(f"   Actionable signals: {len(signals)}")

    if not signals:
        print("\n✅ No actionable signals today. Done.")
        return {"ok": True, "date": brief["date"], "signals": 0, "orders": 0}

    # Step 3: Connect to Alpaca and plan orders
    print("\n💰 Step 3: Planning orders...")
    try:
        creds = load_credentials()
        has_credentials = creds.get("api_key") != "YOUR_ALPACA_API_KEY"
    except FileNotFoundError:
        has_credentials = False

    if not has_credentials:
        print("   ⚠️  Alpaca credentials not configured. Skipping order planning.")
        print("   Create: config/secrets/alpaca_credentials.json")
        print("   Template: config/secrets/alpaca_credentials.json.template")
        return {
            "ok": True,
            "date": brief["date"],
            "signals": len(signals),
            "orders": 0,
            "note": "credentials_not_configured",
        }

    client = AlpacaClient()
    account = client.get_account()
    equity = account["equity"]
    positions = client.get_positions()
    print(f"   Account: ${equity:,.2f} equity, {len(positions)} open positions")

    plans = plan_orders(
        signals,
        equity=equity,
        existing_positions=positions,
        max_position_pct=max_position_pct,
        stop_loss_pct=stop_loss_pct,
    )
    print_plan_table(plans)

    # Step 4: Execute (or dry run)
    print(f"\n📤 Step 4: {'Executing orders' if not dry_run else 'DRY RUN — simulating orders'}...")
    if plans:
        results = execute_plans(plans, client, dry_run=dry_run)
        TRADE_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = TRADE_LOG_DIR / "trade_log.json"
        save_trade_log(results, log_path)
        print(f"   Trade log: {log_path}")
    else:
        results = []
        print("   No orders to submit.")

    summary = {
        "ok": True,
        "date": brief["date"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "signals": len(signals),
        "orders_planned": len(plans),
        "orders_executed": len([r for r in results if r.get("status") not in ("dry_run", "error")]),
        "account": {"equity": equity, "positions": len(positions)},
    }

    # Save daily summary
    summary_path = TRADE_LOG_DIR / f"daily_summary_{date_str}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Daily workflow complete: {summary_path}")

    return summary


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="US Stock Daily Trading Workflow")
    parser.add_argument("--live", action="store_true", help="Submit real orders to Alpaca")
    parser.add_argument("--min-grade", default="B", choices=["A", "B", "C"])
    parser.add_argument("--max-position-pct", type=float, default=0.05)
    parser.add_argument("--stop-loss-pct", type=float, default=0.08)
    args = parser.parse_args()

    dry_run = not args.live
    if args.live:
        print("\n" + "!" * 70)
        print("⚠️  LIVE MODE: Orders will be submitted to Alpaca!")
        print("!" * 70 + "\n")

    result = run(
        dry_run=dry_run,
        min_grade=args.min_grade,
        max_position_pct=args.max_position_pct,
        stop_loss_pct=args.stop_loss_pct,
    )
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
