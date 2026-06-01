#!/usr/bin/env python3
"""D1 Perspective State Calculator.

Calculates MN1/W1/D1 states using D1 close price against each timeframe's SR.
Handles multi-timeframe data alignment via forward-fill.
"""

import bisect
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, date

from .p116_core import calculate_state, StateComponents
from .sr_calculator import calculate_sr, calculate_ma, calculate_atr


@dataclass
class TimeframeData:
    """OHLCV data for a single timeframe."""

    dates: List[date]
    opens: List[float]
    highs: List[float]
    lows: List[float]
    closes: List[float]
    volumes: List[float]


@dataclass
class AlignedState:
    """State for a single day with all timeframes aligned."""

    date: date
    stock_code: str
    stock_name: str
    d1_close: float

    # States
    mn1_state: StateComponents
    w1_state: StateComponents
    d1_state: StateComponents

    # SR levels (for reference)
    mn1_sr_support: float
    mn1_sr_resistance: float
    w1_sr_support: float
    w1_sr_resistance: float
    d1_sr_support: float
    d1_sr_resistance: float


def align_timeframes(
    d1_data: TimeframeData, w1_data: TimeframeData, mn1_data: TimeframeData
) -> List[Dict[str, Any]]:
    """Align W1/MN1 data to D1 dates using forward-fill.

    For each D1 date, find the most recent W1 and MN1 bar.
    """
    aligned = []

    # W1/MN1 dates sorted for bisect
    w1_dates = sorted(w1_data.dates)
    mn1_dates = sorted(mn1_data.dates)

    for i, d1_date in enumerate(d1_data.dates):
        # Find latest W1 <= D1 date
        w1_idx = bisect.bisect_right(w1_dates, d1_date) - 1

        # Find latest MN1 <= D1 date
        mn1_idx = bisect.bisect_right(mn1_dates, d1_date) - 1

        if w1_idx < 0 or mn1_idx < 0:
            continue

        aligned.append({"date": d1_date, "d1_idx": i, "w1_idx": w1_idx, "mn1_idx": mn1_idx})

    return aligned


def calculate_all_states(
    stock_code: str,
    stock_name: str,
    d1_data: TimeframeData,
    w1_data: TimeframeData,
    mn1_data: TimeframeData,
    days: int = 60,
) -> List[AlignedState]:
    """Calculate states for all timeframes from D1 perspective.

    Args:
        stock_code: Stock code
        stock_name: Stock name
        d1_data: Daily OHLCV
        w1_data: Weekly OHLCV
        mn1_data: Monthly OHLCV
        days: Number of recent days to calculate

    Returns:
        List of AlignedState, newest first
    """
    # Align timeframes
    aligned = align_timeframes(d1_data, w1_data, mn1_data)

    # Take last N days
    aligned = aligned[-days:]

    results = []

    for item in aligned:
        d1_idx = item["d1_idx"]
        w1_idx = item["w1_idx"]
        mn1_idx = item["mn1_idx"]

        # ============================================================
        # D1 视角天条：所有周期的 position 计算都使用 D1 收盘价
        # ============================================================
        # MN1 position = D1 close vs MN1 SR (月线SR, D1收盘价)
        # W1 position  = D1 close vs W1 SR  (周线SR, D1收盘价)
        # D1 position  = D1 close vs D1 SR  (日线SR, D1收盘价)
        # ============================================================
        d1_close = d1_data.closes[d1_idx]

        # Calculate SR for each timeframe using their own data
        # D1 SR
        d1_sr = calculate_sr(
            d1_data.highs[: d1_idx + 1], d1_data.lows[: d1_idx + 1], d1_data.closes[: d1_idx + 1]
        )

        # W1 SR (using W1 data up to current W1 bar)
        w1_sr = calculate_sr(
            w1_data.highs[: w1_idx + 1], w1_data.lows[: w1_idx + 1], w1_data.closes[: w1_idx + 1]
        )

        # MN1 SR (using MN1 data up to current MN1 bar)
        mn1_sr = calculate_sr(
            mn1_data.highs[: mn1_idx + 1], mn1_data.lows[: mn1_idx + 1], mn1_data.closes[: mn1_idx + 1]
        )

        # Calculate trend MAs for each timeframe
        # D1 trend
        d1_ma_fast = calculate_ma(d1_data.closes[: d1_idx + 1], 8)
        d1_ma_slow = calculate_ma(d1_data.closes[: d1_idx + 1], 21)

        # W1 trend (forward-filled to D1)
        w1_ma_fast = calculate_ma(w1_data.closes[: w1_idx + 1], 8)
        w1_ma_slow = calculate_ma(w1_data.closes[: w1_idx + 1], 21)

        # MN1 trend (forward-filled to D1)
        mn1_ma_fast = calculate_ma(mn1_data.closes[: mn1_idx + 1], 8)
        mn1_ma_slow = calculate_ma(mn1_data.closes[: mn1_idx + 1], 21)

        # Calculate ATR for each timeframe
        d1_atr_curr, d1_atr_prev = calculate_atr(
            d1_data.highs[: d1_idx + 1], d1_data.lows[: d1_idx + 1], d1_data.closes[: d1_idx + 1]
        )

        w1_atr_curr, w1_atr_prev = calculate_atr(
            w1_data.highs[: w1_idx + 1], w1_data.lows[: w1_idx + 1], w1_data.closes[: w1_idx + 1]
        )

        mn1_atr_curr, mn1_atr_prev = calculate_atr(
            mn1_data.highs[: mn1_idx + 1], mn1_data.lows[: mn1_idx + 1], mn1_data.closes[: mn1_idx + 1]
        )

        # ============================================================
        # State 计算 - D1 视角天条严格执行
        # ============================================================
        # 所有周期都使用 d1_close 作为 position 计算的基准价格
        # SR 使用各自周期的关键位（MN1用月线SR，W1用周线SR，D1用日线SR）
        # trend 和 volatility 使用各自周期的数据计算
        # ============================================================

        # D1 State: D1 close vs D1 SR
        d1_state = calculate_state(
            d1_close=d1_close,
            sr_support=d1_sr.support if d1_sr.ready else d1_close * 0.95,
            sr_resistance=d1_sr.resistance if d1_sr.ready else d1_close * 1.05,
            trend_ma_fast=d1_ma_fast or d1_close,
            trend_ma_slow=d1_ma_slow or d1_close,
            atr_current=d1_atr_curr,
            atr_previous=d1_atr_prev,
        )

        # W1 State: D1 close vs W1 SR (D1视角！)
        w1_state = calculate_state(
            d1_close=d1_close,  # 天条：使用D1收盘价！
            sr_support=w1_sr.support if w1_sr.ready else d1_close * 0.95,
            sr_resistance=w1_sr.resistance if w1_sr.ready else d1_close * 1.05,
            trend_ma_fast=w1_ma_fast or d1_close,
            trend_ma_slow=w1_ma_slow or d1_close,
            atr_current=w1_atr_curr,
            atr_previous=w1_atr_prev,
        )

        # MN1 State: D1 close vs MN1 SR (D1视角！)
        mn1_state = calculate_state(
            d1_close=d1_close,  # 天条：使用D1收盘价！
            sr_support=mn1_sr.support if mn1_sr.ready else d1_close * 0.95,
            sr_resistance=mn1_sr.resistance if mn1_sr.ready else d1_close * 1.05,
            trend_ma_fast=mn1_ma_fast or d1_close,
            trend_ma_slow=mn1_ma_slow or d1_close,
            atr_current=mn1_atr_curr,
            atr_previous=mn1_atr_prev,
        )

        results.append(
            AlignedState(
                date=item["date"],
                stock_code=stock_code,
                stock_name=stock_name,
                d1_close=d1_close,
                mn1_state=mn1_state,
                w1_state=w1_state,
                d1_state=d1_state,
                mn1_sr_support=mn1_sr.support or 0,
                mn1_sr_resistance=mn1_sr.resistance or 0,
                w1_sr_support=w1_sr.support or 0,
                w1_sr_resistance=w1_sr.resistance or 0,
                d1_sr_support=d1_sr.support or 0,
                d1_sr_resistance=d1_sr.resistance or 0,
            )
        )

    # Return newest first
    return list(reversed(results))
