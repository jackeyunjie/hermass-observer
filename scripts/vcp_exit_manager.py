#!/usr/bin/env python3
"""VCP strategy entry confirmation, exit rules, and position sizing.

Implements the complete VCP execution logic per docs/STRATEGY_EXECUTION_SPEC.md:
  • Entry confirmation (limit-up rejection, volume grading A/B/C, 3-day timeout)
  • Position sizing (2% risk budget, ATR-adjusted, 100-share lot)
  • Exit simulation (false breakout, hard stop, ATR stop, technical stop,
                    time exit, trailing stop)

A-share constraints: T+1 (entry signal executes next open), limit-up/down ±9.8%,
min lot 100 shares.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class VCPPositionConfig:
    risk_per_trade: float = 0.02
    atr_period: int = 20
    atr_position_scale: float = 2.0


@dataclass
class VCPExitResult:
    exit_reason: str
    exit_type: str
    pnl_pct: float


# ── helpers ──────────────────────────────────────────────────────────


def _is_limit_up(row: dict[str, Any]) -> bool:
    close = row.get("close", 0)
    prev_close = row.get("prev_close", 0) or row.get("open", 0)
    if prev_close <= 0:
        return False
    return (close - prev_close) / prev_close >= 0.098


def _is_limit_down(row: dict[str, Any]) -> bool:
    close = row.get("close", 0)
    prev_close = row.get("prev_close", 0) or row.get("open", 0)
    if prev_close <= 0:
        return False
    return (close - prev_close) / prev_close <= -0.098


# ── entry confirmation ───────────────────────────────────────────────


def vcp_entry_confirmation(row: dict[str, Any], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Confirm a VCP entry signal after vcp_signal() fires.

    Returns dict with keys:
        confirmed: bool
        signal_grade: "A" | "B" | "C"
        rejection_reason: str
        volume_ratio: float
        is_limit_up: bool
    """
    close = row.get("close", 0)
    vol = row.get("volume", 0)
    lookup = ctx if ctx is not None else row
    vol_ma20 = lookup.get("volume_ma20", 0) or lookup.get("avg_volume_20d", 0) or 1
    vol_ratio = vol / vol_ma20 if vol_ma20 > 0 else 0.0

    is_limit_up = _is_limit_up(row)
    if is_limit_up:
        return {
            "confirmed": False,
            "signal_grade": "C",
            "rejection_reason": "涨停突破，无法买入",
            "volume_ratio": round(vol_ratio, 2),
            "is_limit_up": True,
        }

    vol_pass = vol_ratio >= 1.5
    vol_weak = 0.8 <= vol_ratio < 1.5

    if vol_pass and not is_limit_up:
        grade = "A"
    elif vol_weak:
        grade = "B"
    else:
        grade = "C"

    confirmed = grade in ("A", "B")
    return {
        "confirmed": confirmed,
        "signal_grade": grade,
        "rejection_reason": "" if confirmed else "无量突破，降级为C",
        "volume_ratio": round(vol_ratio, 2),
        "is_limit_up": False,
    }


def vcp_entry_timeout(row: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """Return True if the VCP entry has timed out (>3 days below pivot)."""
    days_since_signal = ctx.get("days_since_entry_signal", 0)
    return days_since_signal > 3 and row.get("close", 0) < ctx.get("pivot_point", 0)


# ── stop-price / position helpers ────────────────────────────────────


def compute_vcp_stop_prices(entry_price: float, ctx: dict[str, Any]) -> dict[str, Any]:
    """Compute all VCP stop candidates and select the most conservative.

    Returns dict with keys:
        hard_stop, atr_stop, tech_stop, conservative_stop,
        pivot_point, contraction_low, entry_atr, stop_name
    """
    lookup = ctx if ctx is not None else {}
    atr = lookup.get("atr14", 0) or lookup.get("d1_atr", 0) or 0
    contraction_low = lookup.get("low_20d", 0) or lookup.get("contraction_low", 0)
    if contraction_low <= 0:
        contraction_low = entry_price * 0.94
    pivot_point = lookup.get("high_10d", 0) or lookup.get("high_10d_prev", 0) or entry_price

    hard_stop = entry_price * 0.94
    atr_stop = entry_price - 2 * atr
    tech_stop = contraction_low * 0.99

    # Most conservative = highest stop price (closest to entry)
    candidates = [
        ("hard_stop", hard_stop),
        ("atr_stop", atr_stop),
        ("tech_stop", tech_stop),
    ]
    valid = [(n, p) for n, p in candidates if p > 0]
    stop_name, conservative_stop = max(valid, key=lambda x: x[1]) if valid else ("hard_stop", hard_stop)

    return {
        "hard_stop": round(hard_stop, 4),
        "atr_stop": round(atr_stop, 4),
        "tech_stop": round(tech_stop, 4),
        "conservative_stop": round(conservative_stop, 4),
        "pivot_point": round(pivot_point, 4),
        "contraction_low": round(contraction_low, 4),
        "entry_atr": round(atr, 4),
        "stop_name": stop_name,
    }


def calculate_position_size(
    capital: float,
    entry_price: float,
    stop_price: float,
    atr: float,
    config: VCPPositionConfig | None = None,
) -> dict[str, Any]:
    """Calculate ATR-adjusted position size (A-share 100-share lots)."""
    cfg = config or VCPPositionConfig()
    risk_amount = capital * cfg.risk_per_trade
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0 or entry_price <= 0 or capital <= 0:
        return {
            "shares": 0,
            "risk_amount": 0,
            "position_value": 0,
            "position_pct": 0.0,
            "stop_distance": 0.0,
            "atr_factor": 0.0,
        }

    raw_shares = risk_amount / stop_distance
    atr_pct = atr / entry_price * 100
    atr_factor = min(2.0, cfg.atr_position_scale / max(atr_pct, 0.5))
    adjusted_shares = raw_shares * atr_factor
    shares = int(adjusted_shares / 100) * 100

    position_value = shares * entry_price
    position_pct = position_value / capital

    return {
        "shares": shares,
        "risk_amount": round(risk_amount, 2),
        "position_value": round(position_value, 2),
        "position_pct": round(position_pct, 4),
        "stop_distance": round(stop_distance, 4),
        "atr_factor": round(atr_factor, 4),
    }


# ── exit check ───────────────────────────────────────────────────────


def vcp_exit_check(
    entry_price: float,
    pivot_point: float,
    contraction_low: float,
    entry_atr: float,
    current_close: float,
    hold_days: int,
    highest_since_entry: float,
) -> VCPExitResult | None:
    """Check whether any VCP exit rule is triggered.

    Priority: false breakout → hard stop → ATR stop → technical stop
              → time exit → trailing stop.
    """
    if entry_price <= 0:
        return None
    pnl_pct = (current_close - entry_price) / entry_price

    # 1. False breakout
    if hold_days <= 3 and current_close < pivot_point:
        return VCPExitResult("假突破离场", "stop", pnl_pct)

    # 2. Hard stop
    if pnl_pct <= -0.06:
        return VCPExitResult("硬止损(-6%)", "stop", pnl_pct)

    # 3. ATR stop
    atr_stop = entry_price - 2 * entry_atr
    if current_close < atr_stop:
        return VCPExitResult("ATR止损(2x)", "stop", pnl_pct)

    # 4. Technical stop
    tech_stop = contraction_low * 0.99
    if current_close < tech_stop:
        return VCPExitResult("技术止损(收缩低点)", "stop", pnl_pct)

    # 5. Time exit
    if hold_days > 20 and pnl_pct < 0.05:
        return VCPExitResult("时间退出(20日未达5%)", "time", pnl_pct)

    # 6. Trailing stop (breakeven after +5%)
    if highest_since_entry >= entry_price * 1.05 and current_close <= entry_price:
        return VCPExitResult("移动止损(盈利回吐)", "trailing", pnl_pct)

    return None


# ── full trade simulation ────────────────────────────────────────────


def simulate_vcp_trade(
    entry_data: dict[str, Any],
    price_series: list[tuple[str, float]],
    capital: float = 1_000_000,
) -> dict[str, Any]:
    """Simulate a VCP trade from entry to exit using real exit rules.

    entry_data must contain:
        date: str              # entry signal date
        entry_price: float
        pivot_point: float     # optional; defaults to entry_price
        contraction_low: float # optional; defaults to entry_price * 0.94
        entry_atr: float       # optional; defaults to 0

    price_series: [(date_str, close), ...] sorted ascending by date.

    Returns dict with:
        status: "exited" | "holding" | "no_price_data"
        entry_date, entry_price
        exit_date, exit_price, hold_days, exit_reason, exit_type, pnl_pct
        position: {shares, risk_amount, position_value, position_pct, ...}
        stop_prices: {hard_stop, atr_stop, tech_stop, conservative_stop, ...}
    """
    entry_date = entry_data.get("date") or entry_data.get("entry_date", "")
    entry_price = float(entry_data.get("entry_price", 0))
    pivot_point = float(entry_data.get("pivot_point", entry_price))
    contraction_low = float(entry_data.get("contraction_low", entry_price * 0.94))
    entry_atr = float(entry_data.get("entry_atr", 0))

    stops = compute_vcp_stop_prices(entry_price, {
        "atr14": entry_atr,
        "low_20d": contraction_low,
        "high_10d": pivot_point,
    })

    position = calculate_position_size(
        capital, entry_price, stops["conservative_stop"], entry_atr
    )

    # Find entry index (first date >= entry_date)
    entry_idx = next((i for i, (d, _) in enumerate(price_series) if d >= entry_date), None)
    if entry_idx is None:
        return {
            "status": "no_price_data",
            "entry_date": entry_date,
            "entry_price": entry_price,
            "position": position,
            "stop_prices": stops,
        }

    highest_since_entry = entry_price

    # T+1 execution: start checking from the day AFTER entry
    for i in range(entry_idx + 1, len(price_series)):
        obs_date, close = price_series[i]
        hold_days = i - entry_idx
        highest_since_entry = max(highest_since_entry, close)

        result = vcp_exit_check(
            entry_price, pivot_point, contraction_low, entry_atr,
            close, hold_days, highest_since_entry,
        )

        if result:
            shares = position["shares"]
            pnl_amount = shares * (close - entry_price)
            return {
                "status": "exited",
                "entry_date": entry_date,
                "entry_price": entry_price,
                "exit_date": obs_date,
                "exit_price": close,
                "hold_days": hold_days,
                "exit_reason": result.exit_reason,
                "exit_type": result.exit_type,
                "pnl_pct": round(result.pnl_pct, 4),
                "pnl_amount": round(pnl_amount, 2),
                "position": position,
                "stop_prices": stops,
            }

    # Still holding — use last available price
    last_date, last_close = price_series[-1]
    hold_days = len(price_series) - 1 - entry_idx
    pnl_pct = (last_close - entry_price) / entry_price if entry_price > 0 else 0
    return {
        "status": "holding",
        "entry_date": entry_date,
        "entry_price": entry_price,
        "last_date": last_date,
        "last_price": last_close,
        "hold_days": hold_days,
        "pnl_pct": round(pnl_pct, 4),
        "position": position,
        "stop_prices": stops,
    }
