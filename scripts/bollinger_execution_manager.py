#!/usr/bin/env python3
"""Bollinger Bandit strategy entry confirmation, exit rules, and trade simulation.

Implements the complete Bollinger Bandit execution logic per:
  • docs/STRATEGY_EXECUTION_SPEC.md (section 1.4, 3.4)
  • docs/STRATEGY_EXECUTION_2560_BOLLINGER_DETAIL.md (section 2)

Key features:
  • Entry confirmation (spike filter, limit-up rejection, volume grading S/A/B)
  • Fake-breakout detection (next-day close < signal-day low, spike + pullback,
    limit-up followed by >3% gap-down)
  • Degrading MA exit (MA50 → MA10, hold_days based)
  • 5-level daily exit priority (ATR anomaly → middle-band breakdown →
    degrading-MA stop → upper-band pullback half-exit → time exit)
  • Full trade simulation with position sizing

A-share constraints: T+1, limit-up/down ±9.8%, min lot 100 shares.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scripts.vcp_exit_manager import calculate_position_size


@dataclass
class BollingerPositionState:
    entry_price: float
    entry_date: str
    entry_atr: float
    half_exited: bool = False
    prev_above_upper: bool = False


# ── helpers ──────────────────────────────────────────────────────────


def _is_limit_up(row: dict[str, Any]) -> bool:
    close = row.get("close", 0)
    prev_close = row.get("prev_close", 0) or row.get("open", 0)
    if prev_close <= 0:
        return False
    return (close - prev_close) / prev_close >= 0.098


def _rolling_mean(values: list[float], window: int) -> float:
    if not values:
        return 0.0
    w = min(window, len(values))
    return sum(values[-w:]) / w


def _rolling_std(values: list[float], window: int) -> float:
    if not values:
        return 0.0
    w = min(window, len(values))
    mean = sum(values[-w:]) / w
    variance = sum((v - mean) ** 2 for v in values[-w:]) / w
    return variance ** 0.5


def _atr_from_ohlc(ohlc: list[tuple[float, float, float, float]], period: int = 14) -> float:
    """Compute ATR from OHLC tuples [(open, high, low, close), ...]."""
    trs: list[float] = []
    for i, (o, h, l, c) in enumerate(ohlc):
        if i == 0:
            trs.append(h - l)
        else:
            prev_c = ohlc[i - 1][3]
            trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    if not trs:
        return 0.0
    w = min(period, len(trs))
    return sum(trs[-w:]) / w


def _compute_bollinger(closes: list[float], period: int = 50, num_std: float = 1.0) -> tuple[float, float]:
    """Return (upper_band, middle_band) from close series."""
    if not closes:
        return 0.0, 0.0
    w = min(period, len(closes))
    window = closes[-w:]
    mean = sum(window) / w
    variance = sum((c - mean) ** 2 for c in window) / w
    std = variance ** 0.5
    return mean + num_std * std, mean


# ── entry confirmation ───────────────────────────────────────────────


def bb_entry_confirmation(row: dict[str, Any], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bollinger Bandit entry confirmation after bollinger_bandit_signal() fires.

    Returns dict with keys:
        confirmed: bool
        signal_grade: "S" | "A" | "B"
        rejection_reason: str
        volume_ratio: float
        is_limit_up: bool
    """
    o = row.get("open", 0)
    h = row.get("high", 0)
    l = row.get("low", 0)
    c = row.get("close", 0)
    body = abs(c - o)
    upper_shadow = h - max(o, c)

    lookup = ctx if ctx is not None else row
    vol_ma20 = lookup.get("volume_ma20", 0) or lookup.get("avg_volume_20d", 0) or 1
    vol_ratio = row.get("volume", 0) / vol_ma20 if vol_ma20 > 0 else 0.0

    # 1. Upper-shadow spike filter
    if round(body, 4) > 0 and round(upper_shadow, 4) > round(body, 4) * 2.0:
        return {
            "confirmed": False,
            "signal_grade": "B",
            "rejection_reason": "上影线过长(>实体2倍)，毛刺行情",
            "volume_ratio": round(vol_ratio, 2),
            "is_limit_up": False,
        }

    # 2. Limit-up rejection
    is_limit_up = _is_limit_up(row)
    if is_limit_up:
        return {
            "confirmed": False,
            "signal_grade": "B",
            "rejection_reason": "涨停突破，无法买入",
            "volume_ratio": round(vol_ratio, 2),
            "is_limit_up": True,
        }

    # 3. Volume grading
    if vol_ratio >= 2.0:
        grade = "S"
    elif vol_ratio >= 1.2:
        grade = "A"
    else:
        grade = "B"

    confirmed = grade in ("S", "A")
    return {
        "confirmed": confirmed,
        "signal_grade": grade,
        "rejection_reason": "" if confirmed else "量能不足",
        "volume_ratio": round(vol_ratio, 2),
        "is_limit_up": False,
    }


def bb_spike_filter(row: dict[str, Any]) -> tuple[bool, str]:
    """Stricter spike filter: upper shadow > 2× body AND amplitude > 8%.

    Returns (is_spike, reason).
    """
    o = row.get("open", 0)
    h = row.get("high", 0)
    l = row.get("low", 0)
    c = row.get("close", 0)
    if o <= 0:
        return False, ""

    body = abs(c - o)
    upper_shadow = h - max(o, c)
    amplitude = (h - l) / o

    if round(body, 4) > 0 and round(upper_shadow, 4) > round(body, 4) * 2.0 and amplitude > 0.08:
        return True, f"上影线>{upper_shadow:.2f}>实体{body:.2f}×2且振幅{amplitude:.1%}>8%"
    return False, ""


# ── fake-breakout detection ──────────────────────────────────────────


def bb_detect_fake_breakout(
    signal_day: dict[str, Any],
    next_day: dict[str, Any],
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Detect false breakout on T+1.

    Types:
        1. Next-day close < signal-day low
        2. Upper shadow > 2× body (already caught at entry, but re-checked here)
        3. Limit-up signal day + next-day gap-down > 3%

    Returns dict with keys:
        is_false_breakout: bool
        false_breakout_type: str
        action: str
        reason: str
    """
    if next_day is None:
        return {
            "is_false_breakout": False,
            "false_breakout_type": "",
            "action": "等待次日数据",
            "reason": "次日数据尚未到达",
        }

    signal_close = signal_day.get("close", 0)
    signal_low = signal_day.get("low", 0)
    next_close = next_day.get("close", 0)
    next_open = next_day.get("open", 0)

    # Type 1: next-day close < signal-day low
    if next_close < signal_low:
        return {
            "is_false_breakout": True,
            "false_breakout_type": "次日回落",
            "action": "立即离场",
            "reason": f"次日收盘({next_close}) < 信号日最低({signal_low})，假突破确认",
        }

    # Type 2: upper-shadow spike (redundant with entry check, but kept for completeness)
    signal_open = signal_day.get("open", 0)
    signal_high = signal_day.get("high", 0)
    body = abs(signal_close - signal_open)
    upper_shadow = signal_high - max(signal_open, signal_close)
    if round(body, 4) > 0 and round(upper_shadow, 4) > round(body, 4) * 2.0:
        return {
            "is_false_breakout": True,
            "false_breakout_type": "上影线毛刺",
            "action": "立即离场",
            "reason": f"上影线({upper_shadow:.2f}) > 实体({body:.2f})×2，毛刺假突破",
        }

    # Type 3: limit-up followed by gap-down > 3%
    if _is_limit_up(signal_day) and signal_close > 0:
        gap = (next_open - signal_close) / signal_close
        if gap < -0.03:
            return {
                "is_false_breakout": True,
                "false_breakout_type": "涨停次日低开",
                "action": "立即离场",
                "reason": f"涨停后次日低开{gap:.1%} > 3%，假突破",
            }

    return {
        "is_false_breakout": False,
        "false_breakout_type": "",
        "action": "正常持有",
        "reason": "未触发假突破条件",
    }


# ── degrading MA ─────────────────────────────────────────────────────


def compute_degrading_ma(hold_days: int, closes: list[float]) -> tuple[int, float]:
    """Compute the degrading exit MA for Bollinger Bandit.

    Day 1 (hold_days=1) → MA50
    Day 2 (hold_days=2) → MA49
    ...
    Day 41+ (hold_days>=41) → MA10 (floor)
    """
    period = max(10, 51 - hold_days)
    return period, _rolling_mean(closes, period)


# ── daily exit check ─────────────────────────────────────────────────


def bb_full_exit_check(
    state: BollingerPositionState,
    current_day: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any] | None:
    """Daily exit check for Bollinger Bandit.

    Priority: ATR anomaly → middle-band breakdown → degrading-MA stop
              → upper-band pullback half-exit → time exit.

    Returns None if no exit triggered, or a dict with exit details.
    """
    current = current_day.get("close", 0)
    hold_days = ctx.get("hold_days", 0)
    entry_atr = state.entry_atr
    current_atr = ctx.get("atr", 0)
    bb_upper = ctx.get("bb_upper", 0)
    bb_middle = ctx.get("bb_middle", 0)
    exit_ma = ctx.get("exit_ma", bb_middle)

    if state.entry_price <= 0:
        return None
    pnl_pct = (current - state.entry_price) / state.entry_price

    # 1. ATR anomaly: current ATR > 2× entry ATR → half exit
    if entry_atr > 0 and current_atr > entry_atr * 2:
        return {
            "exit_reason": "波动率异常(ATR>2x入场时)",
            "exit_type": "risk",
            "exit_pct": 0.5,
            "trigger_price": current,
        }

    # 2. Middle-band breakdown: close < 50-day SMA → full exit
    if current < bb_middle:
        return {
            "exit_reason": "中轨跌破(50日SMA)，趋势反转",
            "exit_type": "stop",
            "exit_pct": 1.0,
            "trigger_price": current,
        }

    # 3. Degrading-MA stop
    if current < exit_ma:
        # Constraint: when hold_days < 20, exit_ma may still be above upper band;
        # defer exit until exit_ma drops below upper band.
        if hold_days >= 20 or exit_ma < bb_upper:
            return {
                "exit_reason": f"递减均线止损(MA{ctx.get('exit_ma_period', 0)})",
                "exit_type": "stop",
                "exit_pct": 1.0,
                "trigger_price": current,
            }

    # 4. Upper-band pullback half-exit
    if state.prev_above_upper and current < bb_upper and not state.half_exited:
        state.half_exited = True
        return {
            "exit_reason": "上轨回落减仓(跌破布林上轨)",
            "exit_type": "profit",
            "exit_pct": 0.5,
            "trigger_price": current,
        }

    # 5. Time exit: hold > 10 days and profit < 5%
    if hold_days > 10 and pnl_pct < 0.05:
        return {
            "exit_reason": "时间退出(10日未达5%盈利)",
            "exit_type": "time",
            "exit_pct": 1.0,
            "trigger_price": current,
        }

    # Update state for next day
    state.prev_above_upper = current > bb_upper

    return None


# ── full trade simulation ────────────────────────────────────────────


def simulate_bollinger_trade(
    entry_data: dict[str, Any],
    price_series: list[dict[str, Any]],
    capital: float = 1_000_000,
) -> dict[str, Any]:
    """Simulate a Bollinger Bandit trade from entry to exit.

    entry_data must contain:
        date: str
        entry_price: float
        entry_atr: float   # optional; computed from series if missing

    price_series: list of dicts with keys:
        date, close, open, high, low, volume
        Sorted ascending by date.

    Returns dict with:
        status: "exited" | "holding" | "no_price_data"
        entry_date, entry_price
        exit_date, exit_price, hold_days, exit_reason, exit_type, pnl_pct
        position: {shares, risk_amount, position_value, position_pct, ...}
    """
    entry_date = entry_data.get("date") or entry_data.get("entry_date", "")
    entry_price = float(entry_data.get("entry_price", 0))
    entry_atr = float(entry_data.get("entry_atr", 0))

    if entry_price <= 0:
        return {"status": "invalid_entry", "entry_date": entry_date, "entry_price": entry_price}

    # Find entry index
    entry_idx = next((i for i, d in enumerate(price_series) if d.get("date", "") >= entry_date), None)
    if entry_idx is None:
        return {"status": "no_price_data", "entry_date": entry_date, "entry_price": entry_price}

    # Compute entry ATR from series if not provided
    if entry_atr <= 0 and entry_idx >= 0:
        ohlc_so_far = [
            (d["open"], d["high"], d["low"], d["close"])
            for d in price_series[: entry_idx + 1]
        ]
        entry_atr = _atr_from_ohlc(ohlc_so_far)

    # Position sizing: use entry - 2×ATR as reference stop for sizing only.
    # This stop_price is NOT an exit rule; actual exits are governed by
    # bb_full_exit_check (degrading-MA / middle-band / upper-band / time).
    stop_price = entry_price - 2 * entry_atr if entry_atr > 0 else entry_price * 0.80
    position = calculate_position_size(capital, entry_price, stop_price, entry_atr)

    state = BollingerPositionState(entry_price, entry_date, entry_atr)

    for i in range(entry_idx + 1, len(price_series)):
        day = price_series[i]
        hold_days = i - entry_idx

        # Build indicator context from price history up to current day
        closes_so_far = [d["close"] for d in price_series[: i + 1]]
        ohlc_so_far = [
            (d["open"], d["high"], d["low"], d["close"])
            for d in price_series[: i + 1]
        ]

        bb_upper, bb_middle = _compute_bollinger(closes_so_far, period=50, num_std=1.0)
        exit_ma_period, exit_ma = compute_degrading_ma(hold_days, closes_so_far)
        current_atr = _atr_from_ohlc(ohlc_so_far)

        ctx = {
            "hold_days": hold_days,
            "atr": current_atr,
            "bb_upper": bb_upper,
            "bb_middle": bb_middle,
            "exit_ma_period": exit_ma_period,
            "exit_ma": exit_ma,
        }

        # T+1 fake-breakout check (highest priority)
        if hold_days == 1:
            fake = bb_detect_fake_breakout(price_series[entry_idx], day)
            if fake.get("is_false_breakout"):
                pnl_pct = (day["close"] - entry_price) / entry_price
                shares = position["shares"]
                pnl_amount = shares * (day["close"] - entry_price)
                return {
                    "status": "exited",
                    "entry_date": entry_date,
                    "entry_price": entry_price,
                    "exit_date": day["date"],
                    "exit_price": day["close"],
                    "hold_days": hold_days,
                    "exit_reason": f"假突破({fake['false_breakout_type']})",
                    "exit_type": "stop",
                    "pnl_pct": round(pnl_pct, 4),
                    "pnl_amount": round(pnl_amount, 2),
                    "position": position,
                }

        # Regular exit rules
        result = bb_full_exit_check(state, day, ctx)
        if result:
            pnl_pct = (day["close"] - entry_price) / entry_price
            shares = position["shares"]
            pnl_amount = shares * (day["close"] - entry_price)
            return {
                "status": "exited",
                "entry_date": entry_date,
                "entry_price": entry_price,
                "exit_date": day["date"],
                "exit_price": day["close"],
                "hold_days": hold_days,
                "exit_reason": result["exit_reason"],
                "exit_type": result["exit_type"],
                "pnl_pct": round(pnl_pct, 4),
                "pnl_amount": round(pnl_amount, 2),
                "position": position,
            }

    # Still holding — use last available price
    last_day = price_series[-1]
    hold_days = len(price_series) - 1 - entry_idx
    pnl_pct = (last_day["close"] - entry_price) / entry_price if entry_price > 0 else 0
    return {
        "status": "holding",
        "entry_date": entry_date,
        "entry_price": entry_price,
        "last_date": last_day["date"],
        "last_price": last_day["close"],
        "hold_days": hold_days,
        "pnl_pct": round(pnl_pct, 4),
        "position": position,
    }
