"""Stop-loss calculation strategies.

基于 Hermass SR 系统的止损位计算。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StopLossResult:
    """止损计算结果."""

    stop_price: float
    method: str
    distance_pct: float   # 止损距离百分比
    risk_amount: float     # 风险金额 (每股)


def sr_support_stop(
    entry_price: float,
    sr_support: float,
    buffer_pct: float = 0.01,
) -> StopLossResult:
    """SR 支撑位止损 (最常用).

    止损位 = SR 支撑 - 缓冲区

    Args:
        entry_price: 入场价格
        sr_support: D1 SR 支撑位
        buffer_pct: 支撑位下方缓冲 (默认 1%)
    """
    stop = sr_support * (1 - buffer_pct)
    # 止损不能高于入场价
    stop = min(stop, entry_price * 0.95)
    # 止损不能太远 (最多 15%)
    stop = max(stop, entry_price * 0.85)

    distance = (entry_price - stop) / entry_price if entry_price > 0 else 0
    return StopLossResult(
        stop_price=round(stop, 3),
        method='sr_support',
        distance_pct=round(distance, 4),
        risk_amount=round(entry_price - stop, 3),
    )


def atr_stop(
    entry_price: float,
    atr: float,
    multiplier: float = 2.0,
) -> StopLossResult:
    """ATR 止损.

    止损位 = 入场价 - ATR * 倍数

    优点: 自适应波动率, 震荡股止损窄, 趋势股止损宽
    """
    stop = entry_price - atr * multiplier
    stop = max(stop, entry_price * 0.85)  # 最多 15%

    distance = (entry_price - stop) / entry_price if entry_price > 0 else 0
    return StopLossResult(
        stop_price=round(stop, 3),
        method='atr',
        distance_pct=round(distance, 4),
        risk_amount=round(atr * multiplier, 3),
    )


def combined_stop(
    entry_price: float,
    sr_support: float,
    atr: float,
    sr_weight: float = 0.6,
) -> StopLossResult:
    """组合止损 (SR + ATR 加权).

    取 SR 支撑止损和 ATR 止损的加权平均，
    兼顾结构支撑和波动率适应性。
    """
    sr = sr_support_stop(entry_price, sr_support)
    at = atr_stop(entry_price, atr)

    stop = sr.stop_price * sr_weight + at.stop_price * (1 - sr_weight)
    stop = max(stop, entry_price * 0.85)

    distance = (entry_price - stop) / entry_price if entry_price > 0 else 0
    return StopLossResult(
        stop_price=round(stop, 3),
        method='combined',
        distance_pct=round(distance, 4),
        risk_amount=round(entry_price - stop, 3),
    )


def trailing_stop_update(
    current_price: float,
    highest_since_entry: float,
    trailing_pct: float = 0.08,
) -> float:
    """跟踪止损更新.

    返回新的止损价 (只升不降).

    Args:
        trailing_pct: 从最高点回撤比例 (默认 8%)
    """
    new_stop = highest_since_entry * (1 - trailing_pct)
    return round(new_stop, 3)
