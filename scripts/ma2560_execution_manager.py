#!/usr/bin/env python3
"""2560 strategy execution manager: entry confirmation, volume qualification,
pullback counting, exit rules, and trade simulation.

Implements the complete 2560 execution logic per:
  docs/STRATEGY_EXECUTION_2560_BOLLINGER_DETAIL.md
  docs/STRATEGY_EXECUTION_SPEC.md

A-share constraints: T+1, limit-up/down ±9.8%, min lot 100 shares.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MA2560ExitResult:
    exit_reason: str
    exit_type: str
    pnl_pct: float
    exit_pct: float = 1.0  # 1.0=full, 0.5=half


# ── helpers ──────────────────────────────────────────────────────────


def _is_limit_up(row: dict[str, Any]) -> bool:
    close = row.get("close", 0)
    prev_close = row.get("prev_close", 0) or row.get("open", 0)
    if prev_close <= 0:
        return False
    return (close - prev_close) / prev_close >= 0.098


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


# ── volume confirmation ──────────────────────────────────────────────


def ma2560_volume_confirmation(row: dict[str, Any], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Volume state classification for 2560 entry.

    Returns:
        vol_state: "冲量" / "做量" / "缩量" / "异常"
        vol_grade: "S" / "A" / "B" / "C"
        vol5_vol60_ratio: float
        rejection_reason: str
    """
    lookup = ctx if ctx is not None else row
    vol5 = _safe_float(lookup.get("volume_ma5"), 0.0)
    vol60 = _safe_float(lookup.get("volume_ma60"), 0.0)
    vol20 = _safe_float(lookup.get("volume_ma20"), 0.0)
    vol_today = _safe_float(row.get("volume"), 0.0)
    days_since_cross = _safe_float(lookup.get("vol5_cross_vol60_days"), -1.0)
    above_streak = int(_safe_float(lookup.get("vol5_above_vol60_streak"), 0.0))

    ratio = vol5 / vol60 if vol60 > 0 else 0.0
    vol_today_ratio = vol_today / vol20 if vol20 > 0 else 0.0

    # State classification
    if days_since_cross >= 0 and days_since_cross <= 3:
        vol_state = "冲量"
        if ratio > 2.5:
            vol_grade = "C"
            rejection_reason = "冲量过热，VOL5/VOL60 > 2.5，需观察"
        else:
            vol_grade = "B"
            rejection_reason = ""
    elif days_since_cross > 3 and ratio >= 0.9:
        if above_streak >= 5:
            vol_state = "做量"
            vol_grade = "A"
            rejection_reason = ""
        else:
            vol_state = "做量(初期)"
            vol_grade = "B"
            rejection_reason = ""
    elif ratio >= 1.0 and vol_today_ratio < 0.4:
        vol_state = "缩量"
        open_p = _safe_float(row.get("open"), 0.0)
        close_p = _safe_float(row.get("close"), 0.0)
        is_doji = open_p > 0 and abs(close_p - open_p) / open_p < 0.005
        is_pit = bool(lookup.get("is_pit_volume", False))
        if is_doji or is_pit:
            vol_grade = "S"
            rejection_reason = ""
        else:
            vol_grade = "A"
            rejection_reason = ""
    else:
        vol_state = "异常"
        vol_grade = "C"
        rejection_reason = "VOL5 低于 VOL60，量能结构不支持"

    return {
        "vol_state": vol_state,
        "vol_grade": vol_grade,
        "vol5_vol60_ratio": round(ratio, 2),
        "rejection_reason": rejection_reason,
    }


# ── pullback counting ────────────────────────────────────────────────


def count_pullbacks(
    price_series: list[tuple[str, float, float, float]],
    ma25_series: list[tuple[str, float]],
    zone_pct: float = 0.02,
) -> int:
    """Count pullback events to MA25 within a 60-day window.

    Args:
        price_series: [(date, open, high, low, close), ...] sorted ascending.
        ma25_series: [(date, ma25), ...] sorted ascending.
        zone_pct: MA25 ±zone_pct defines the pullback zone (default 2%).

    Returns:
        Number of valid pullback events (>=3 means abandon entry).
    """
    if not price_series or not ma25_series:
        return 0

    # Build date -> ma25 map
    ma25_by_date = {d: v for d, v in ma25_series}

    pullback_count = 0
    is_above_ma25 = False
    last_pullback_date = ""

    for date_str, open_p, high_p, low_p, close_p in price_series:
        ma25 = ma25_by_date.get(date_str)
        if ma25 is None or ma25 <= 0:
            continue

        ma25_upper = ma25 * (1 + zone_pct)
        ma25_lower = ma25 * (1 - zone_pct)

        was_above = is_above_ma25
        is_above = close_p > ma25 * (1 + zone_pct)
        is_in_zone = ma25_lower <= low_p <= ma25_upper
        is_breakdown = close_p < ma25_lower

        if is_breakdown:
            # Valid breakdown resets counter
            pullback_count = 0
            is_above_ma25 = False
            last_pullback_date = ""
        elif was_above and is_in_zone and not is_above:
            # New pullback event (must have re-broken out after last pullback)
            if last_pullback_date == "" or True:  # simplified: count all valid touches
                pullback_count += 1
                last_pullback_date = date_str
            is_above_ma25 = False
        elif not was_above and is_above:
            # Re-breakout above MA25
            is_above_ma25 = True

    return pullback_count


def count_pullbacks_from_series(
    close_series: list[tuple[str, float]],
    low_series: list[tuple[str, float]],
    ma25_series: list[tuple[str, float]],
    zone_pct: float = 0.02,
) -> int:
    """Simplified pullback count using separate close/low series."""
    price_series = []
    close_map = {d: c for d, c in close_series}
    for date_str, low_p in low_series:
        close_p = close_map.get(date_str, low_p)
        price_series.append((date_str, 0.0, 0.0, low_p, close_p))
    return count_pullbacks(price_series, ma25_series, zone_pct)


# ── full entry check ─────────────────────────────────────────────────


def ma2560_full_entry_check(
    row: dict[str, Any],
    ctx: dict[str, Any] | None = None,
    pullback_count: int = 0,
) -> dict[str, Any]:
    """6-item 2560 entry confirmation check.

    Checks:
        1. MA25 upward slope (均线排列)
        2. Price position relative to MA25 (价格位置)
        3. Volume qualification (量能)
        4. Pullback count < 3 (回踩次数)
        5. Not limit-up (涨停)
        6. State match (optional, checked externally)

    Returns:
        confirmed: bool
        rejection_reason: str
        checks: dict of individual check results
        vol_confirmation: dict from ma2560_volume_confirmation
        pullback_count: int
    """
    lookup = ctx if ctx is not None else row
    checks: dict[str, Any] = {}

    # 1. MA25 upward slope
    ma25 = _safe_float(lookup.get("ma25"), 0.0)
    ma25_prev = _safe_float(lookup.get("ma25_prev"), 0.0)
    ma25_upward = ma25 > ma25_prev if ma25_prev > 0 else True
    checks["ma25_upward"] = ma25_upward

    # 2. Price position: close within MA25 ±2% or above
    close_p = _safe_float(row.get("close"), 0.0)
    low_p = _safe_float(row.get("low"), 0.0)
    ma25_zone = ma25 > 0 and (ma25 * 0.98 <= close_p <= ma25 * 1.02 or close_p >= ma25 * 0.98)
    checks["price_in_ma25_zone"] = ma25_zone

    # 3. Volume qualification
    vol_conf = ma2560_volume_confirmation(row, lookup)
    checks["volume_grade"] = vol_conf["vol_grade"]
    checks["volume_state"] = vol_conf["vol_state"]

    # 4. Pullback count
    checks["pullback_count"] = pullback_count
    checks["pullback_ok"] = pullback_count < 3

    # 5. Limit-up check
    is_limit = _is_limit_up(row)
    checks["not_limit_up"] = not is_limit

    # Determine overall confirmation
    confirmed = (
        ma25_upward
        and ma25_zone
        and vol_conf["vol_grade"] in ("S", "A", "B")
        and pullback_count < 3
        and not is_limit
    )

    # Build rejection reason
    reasons: list[str] = []
    if not ma25_upward:
        reasons.append("MA25未向上")
    if not ma25_zone:
        reasons.append("价格未在MA25区间")
    if vol_conf["vol_grade"] == "C":
        reasons.append(f"量能不足({vol_conf['vol_state']})")
    if pullback_count >= 3:
        reasons.append(f"多次回踩({pullback_count}次)")
    if is_limit:
        reasons.append("涨停无法买入")

    return {
        "confirmed": confirmed,
        "rejection_reason": "；".join(reasons) if reasons else "",
        "checks": checks,
        "vol_confirmation": vol_conf,
        "pullback_count": pullback_count,
    }


# ── exit check ───────────────────────────────────────────────────────


def ma2560_exit_check(
    entry_price: float,
    current_close: float,
    ma25: float,
    ma60: float,
    hold_days: int,
    half_exited: bool = False,
    full_exited: bool = False,
) -> MA2560ExitResult | None:
    """4-level 2560 exit priority check.

    Priority: 跌破60日线 > 跌破25日线 > 盈利≥10% > 盈利5-10%减半
    """
    if entry_price <= 0:
        return None

    pnl_pct = (current_close - entry_price) / entry_price

    # 1. 强制清仓：收盘跌破 60 日线
    if current_close < ma60:
        return MA2560ExitResult("跌破60日线，强制清仓", "stop", pnl_pct, 1.0)

    # 2. 止损：收盘跌破 25 日均线
    if current_close < ma25:
        return MA2560ExitResult("跌破25日均线，止损", "stop", pnl_pct, 1.0 if not half_exited else 0.5)

    # 3. 第二止盈点：盈利 >= 10%，全部清仓
    if pnl_pct >= 0.10 and not full_exited:
        return MA2560ExitResult("止盈(盈利≥10%，全部清仓)", "profit", pnl_pct, 0.5 if half_exited else 1.0)

    # 4. 第一止盈点：盈利 5%-10%，减仓 50%
    if 0.05 <= pnl_pct < 0.10 and not half_exited:
        return MA2560ExitResult("止盈(盈利5-10%，减仓50%)", "profit", pnl_pct, 0.5)

    return None


# ── full trade simulation ────────────────────────────────────────────


def simulate_ma2560_trade(
    entry_data: dict[str, Any],
    price_series: list[tuple[str, float]],
    ma25_series: list[tuple[str, float]] | None = None,
    ma60_series: list[tuple[str, float]] | None = None,
    capital: float = 1_000_000,
) -> dict[str, Any]:
    """Simulate a 2560 trade from entry to exit using real exit rules.

    entry_data must contain:
        date: str              # entry signal date
        entry_price: float
        pullback_count: int    # optional; default 0

    price_series: [(date_str, close), ...] sorted ascending by date.
    ma25_series: [(date_str, ma25), ...] sorted ascending; optional.
    ma60_series: [(date_str, ma60), ...] sorted ascending; optional.

    Returns dict with:
        status: "exited" | "holding" | "no_price_data"
        entry_date, entry_price
        exit_date, exit_price, hold_days, exit_reason, exit_type, pnl_pct
        half_exited: bool
        full_exited: bool
    """
    entry_date = entry_data.get("date") or entry_data.get("entry_date", "")
    entry_price = float(entry_data.get("entry_price", 0))
    pullback_count = int(entry_data.get("pullback_count", 0))

    if entry_price <= 0:
        return {"status": "invalid", "entry_date": entry_date, "entry_price": entry_price}

    # Build MA lookup maps
    ma25_map: dict[str, float] = {}
    ma60_map: dict[str, float] = {}
    if ma25_series:
        ma25_map = {d: v for d, v in ma25_series}
    if ma60_series:
        ma60_map = {d: v for d, v in ma60_series}

    # Find entry index
    entry_idx = next((i for i, (d, _) in enumerate(price_series) if d >= entry_date), None)
    if entry_idx is None:
        return {
            "status": "no_price_data",
            "entry_date": entry_date,
            "entry_price": entry_price,
            "pullback_count": pullback_count,
        }

    half_exited = False
    full_exited = False

    # T+1 execution: start checking from the day AFTER entry
    for i in range(entry_idx + 1, len(price_series)):
        obs_date, close = price_series[i]
        hold_days = i - entry_idx

        ma25 = ma25_map.get(obs_date, entry_price * 0.95)
        ma60 = ma60_map.get(obs_date, entry_price * 0.90)

        result = ma2560_exit_check(
            entry_price=entry_price,
            current_close=close,
            ma25=ma25,
            ma60=ma60,
            hold_days=hold_days,
            half_exited=half_exited,
            full_exited=full_exited,
        )

        if result:
            # Update state based on exit type
            if result.exit_reason.startswith("止盈(盈利5-10%"):
                half_exited = True
                # Continue holding remaining position
                continue
            elif result.exit_reason.startswith("止盈(盈利≥10%"):
                full_exited = True
                # If already half-exited, this exits the remaining half
                actual_exit_pct = 0.5 if half_exited else 1.0
            else:
                actual_exit_pct = result.exit_pct
                full_exited = True

            pnl_amount = 0  # simplified; no position sizing in observation ledger
            return {
                "status": "exited",
                "entry_date": entry_date,
                "entry_price": entry_price,
                "exit_date": obs_date,
                "exit_price": close,
                "hold_days": hold_days,
                "exit_reason": result.exit_reason,
                "exit_type": result.exit_type,
                "exit_pct": actual_exit_pct,
                "pnl_pct": round(result.pnl_pct, 4),
                "half_exited": half_exited,
                "full_exited": full_exited,
                "pullback_count": pullback_count,
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
        "half_exited": half_exited,
        "full_exited": full_exited,
        "pullback_count": pullback_count,
    }
