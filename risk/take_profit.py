"""Take-profit strategies.

基于 SR 阻力位和 ATR 的止盈策略。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TakeProfitResult:
    """止盈计算结果."""

    target_price: float
    method: str
    reward_pct: float   # 盈利百分比
    rr_ratio: float     # 盈亏比 (reward / risk)


def sr_resistance_target(
    entry_price: float,
    sr_resistance: float,
    approach_pct: float = 0.98,
) -> TakeProfitResult:
    """SR 阻力位止盈.

    目标位 = SR 阻力 * approach_pct (提前一点出场)
    """
    target = sr_resistance * approach_pct
    # 目标至少在入场价之上
    target = max(target, entry_price * 1.02)

    reward = (target - entry_price) / entry_price if entry_price > 0 else 0
    return TakeProfitResult(
        target_price=round(target, 3),
        method='sr_resistance',
        reward_pct=round(reward, 4),
        rr_ratio=0.0,  # 需要配合止损计算
    )


def atr_target(
    entry_price: float,
    atr: float,
    multiplier: float = 3.0,
) -> TakeProfitResult:
    """ATR 止盈.

    目标位 = 入场价 + ATR * 倍数
    """
    target = entry_price + atr * multiplier

    reward = (target - entry_price) / entry_price if entry_price > 0 else 0
    return TakeProfitResult(
        target_price=round(target, 3),
        method='atr',
        reward_pct=round(reward, 4),
        rr_ratio=0.0,
    )


def tiered_targets(
    entry_price: float,
    sr_resistance: float,
    atr: float,
) -> list[TakeProfitResult]:
    """分批止盈 (三级目标).

    Level 1: 1/3 仓位在 SR 阻力位附近平仓
    Level 2: 1/3 仓位在 SR 阻力 * 1.05 平仓
    Level 3: 1/3 仓位跟踪止损
    """
    t1 = sr_resistance_target(entry_price, sr_resistance, approach_pct=0.98)
    t1.method = 'tier_1'

    t2_price = sr_resistance * 1.05
    t2_reward = (t2_price - entry_price) / entry_price if entry_price > 0 else 0
    t2 = TakeProfitResult(
        target_price=round(t2_price, 3),
        method='tier_2',
        reward_pct=round(t2_reward, 4),
        rr_ratio=0.0,
    )

    t3_price = sr_resistance * 1.10
    t3_reward = (t3_price - entry_price) / entry_price if entry_price > 0 else 0
    t3 = TakeProfitResult(
        target_price=round(t3_price, 3),
        method='tier_3',
        reward_pct=round(t3_reward, 4),
        rr_ratio=0.0,
    )

    return [t1, t2, t3]


def calc_rr_ratio(reward_pct: float, risk_pct: float) -> float:
    """计算盈亏比."""
    if risk_pct <= 0:
        return 0.0
    return round(reward_pct / risk_pct, 2)
