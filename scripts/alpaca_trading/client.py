#!/usr/bin/env python3
"""Alpaca Trading API client wrapper.

Supports both paper and live trading.
Credentials read from config/secrets/alpaca_credentials.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_PATH = ROOT / "config" / "secrets" / "alpaca_credentials.json"


def load_credentials() -> dict[str, str]:
    """Load Alpaca API credentials from secrets file."""
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"Alpaca credentials not found at {CREDENTIALS_PATH}\n"
            "Please create this file with:\n"
            '{"api_key": "YOUR_API_KEY", "secret_key": "YOUR_SECRET_KEY", "paper": true}'
        )
    return json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))


class AlpacaClient:
    """Wrapper around Alpaca TradingClient with convenient methods."""

    def __init__(self, paper: bool | None = None) -> None:
        creds = load_credentials()
        self.api_key = creds["api_key"]
        self.secret_key = creds["secret_key"]
        # paper=None -> use credentials file setting; otherwise override
        if paper is None:
            paper = creds.get("paper", True)
        self.paper = paper
        self.client = TradingClient(self.api_key, self.secret_key, paper=paper)

    def get_account(self) -> dict[str, Any]:
        """Get account summary."""
        acc = self.client.get_account()
        return {
            "id": acc.id,
            "cash": float(acc.cash),
            "buying_power": float(acc.buying_power),
            "equity": float(acc.equity),
            "portfolio_value": float(acc.portfolio_value),
            "status": acc.status,
            "pattern_day_trader": acc.pattern_day_trader,
        }

    def get_positions(self) -> list[dict[str, Any]]:
        """Get all open positions."""
        positions = self.client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "market_value": float(p.market_value),
                "avg_entry_price": float(p.avg_entry_price),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
                "current_price": float(p.current_price),
                "change_today": float(p.change_today),
            }
            for p in positions
        ]

    def get_orders(self, status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
        """Get orders by status (open/closed/all)."""
        req = GetOrdersRequest(status=status, limit=limit)
        orders = self.client.get_orders(filter=req)
        return [
            {
                "id": str(o.id),
                "symbol": o.symbol,
                "side": o.side.value,
                "qty": float(o.qty) if o.qty else None,
                "notional": float(o.notional) if o.notional else None,
                "filled_qty": float(o.filled_qty) if o.filled_qty else 0,
                "type": o.type.value,
                "status": o.status.value,
                "submitted_at": str(o.submitted_at) if o.submitted_at else None,
                "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
            }
            for o in orders
        ]

    def submit_market_order(
        self,
        symbol: str,
        qty: float | None = None,
        notional: float | None = None,
        side: str = "buy",
        time_in_force: str = "day",
    ) -> dict[str, Any]:
        """Submit a market order. Use either qty or notional (dollar amount)."""
        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            notional=notional,
            side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY if time_in_force == "day" else TimeInForce.GTC,
        )
        o = self.client.submit_order(order_data=order_data)
        return {
            "id": str(o.id),
            "symbol": o.symbol,
            "side": o.side.value,
            "qty": float(o.qty) if o.qty else None,
            "notional": float(o.notional) if o.notional else None,
            "status": o.status.value,
            "submitted_at": str(o.submitted_at) if o.submitted_at else None,
        }

    def submit_limit_order(
        self,
        symbol: str,
        limit_price: float,
        qty: float | None = None,
        notional: float | None = None,
        side: str = "buy",
        time_in_force: str = "day",
    ) -> dict[str, Any]:
        """Submit a limit order."""
        order_data = LimitOrderRequest(
            symbol=symbol,
            limit_price=limit_price,
            qty=qty,
            notional=notional,
            side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY if time_in_force == "day" else TimeInForce.GTC,
        )
        o = self.client.submit_order(order_data=order_data)
        return {
            "id": str(o.id),
            "symbol": o.symbol,
            "side": o.side.value,
            "limit_price": limit_price,
            "qty": float(o.qty) if o.qty else None,
            "notional": float(o.notional) if o.notional else None,
            "status": o.status.value,
            "submitted_at": str(o.submitted_at) if o.submitted_at else None,
        }

    def cancel_all_orders(self) -> None:
        """Cancel all open orders."""
        self.client.cancel_orders()

    def close_position(self, symbol: str) -> dict[str, Any]:
        """Close a specific position (market order)."""
        o = self.client.close_position(symbol)
        return {
            "id": str(o.id),
            "symbol": o.symbol,
            "side": o.side.value,
            "qty": float(o.qty) if o.qty else None,
            "status": o.status.value,
        }


def test_connection() -> None:
    """Quick test to verify credentials and connection."""
    client = AlpacaClient()
    print(f"Mode: {'PAPER' if client.paper else 'LIVE'}")
    acc = client.get_account()
    print(f"Account: {acc['id']}")
    print(f"Cash: ${acc['cash']:,.2f}")
    print(f"Buying Power: ${acc['buying_power']:,.2f}")
    print(f"Equity: ${acc['equity']:,.2f}")
    print(f"Status: {acc['status']}")

    positions = client.get_positions()
    print(f"\nOpen Positions: {len(positions)}")
    for p in positions[:5]:
        print(f"  {p['symbol']}: {p['qty']} shares @ ${p['current_price']:.2f} (P&L: ${p['unrealized_pl']:+.2f})")

    orders = client.get_orders(status="open")
    print(f"\nOpen Orders: {len(orders)}")


if __name__ == "__main__":
    test_connection()
