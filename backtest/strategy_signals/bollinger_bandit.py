"""John Hill style Bollinger Bandit timing rules.

Rules implemented for the long-only A-share backtest:
- Channel basis: 50-period SMA with 1 standard deviation.
- Momentum filter: current close must be above the close 30 periods ago.
- Long entry: close crosses above the upper channel while the momentum filter is true.
- Exit: dynamic degrading MA, 50 on the first bar after entry, then 49, ... down to 10.

The short side from the original system is intentionally not enabled because the
current A-share portfolio engine is long-only.
"""
from __future__ import annotations

from typing import Any


def bollinger_bandit_signal(
    row: dict[str, Any],
    ctx: dict[str, Any],
) -> tuple[str, float] | None:
    """Return Bollinger Bandit long-entry signal when the approved rules pass."""
    close = row.get("close", 0) or 0
    prev_close = ctx.get("prev_close") or 0
    close_30_ago = ctx.get("close_30_ago") or 0
    upper = ctx.get("bb_upper_50_1") or 0
    prev_upper = ctx.get("bb_upper_50_1_prev") or upper

    if min(close, prev_close, close_30_ago, upper, prev_upper) <= 0:
        return None

    momentum_up = close > close_30_ago
    crossed_upper = close > upper and prev_close <= prev_upper
    if momentum_up and crossed_upper:
        return ("bb_bandit_long_entry", 0.80)
    return None


def exit_ma_period(hold_bars: int, start_period: int = 50, floor_period: int = 10) -> int:
    """Return the degrading exit MA period for an open position.

    hold_bars=1 uses MA50, hold_bars=2 uses MA49, and the period never drops
    below MA10.
    """
    return max(floor_period, start_period - max(hold_bars - 1, 0))


def bollinger_bandit_exit_signal(
    close: float,
    exit_ma_value: float,
) -> tuple[str, float] | None:
    """Return exit signal when close violates the dynamic degrading MA."""
    if close <= 0 or exit_ma_value <= 0:
        return None
    if close < exit_ma_value:
        return ("bb_bandit_dynamic_ma_exit", 0.95)
    return None

