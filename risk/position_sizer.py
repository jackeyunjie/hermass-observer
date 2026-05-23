"""Position sizing strategies.

三种仓位计算方法:
1. Fixed Fraction: 固定比例法 (每只占总资金 N%)
2. Kelly Criterion: 凯利公式 (基于历史胜率和盈亏比)
3. ATR-Based: 基于 ATR 的波动率标准化仓位
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionSize:
    """仓位计算结果."""

    amount: float       # 买入金额
    shares: int         # 股数 (100 整数倍)
    risk_per_share: float  # 每股风险 (入场价-止损价)
    total_risk: float   # 总风险金额
    risk_pct: float     # 占总资金比例


def fixed_fraction(
    equity: float,
    price: float,
    fraction: float = 0.10,
    min_lot: int = 100,
) -> PositionSize:
    """固定比例法.

    Args:
        equity: 总权益
        price: 入场价格
        fraction: 每只占比 (默认 10%)
        min_lot: 最小交易单位 (A股 100 股)
    """
    amount = equity * fraction
    shares = int(amount / price / min_lot) * min_lot
    actual_amount = shares * price
    return PositionSize(
        amount=actual_amount,
        shares=shares,
        risk_per_share=0.0,
        total_risk=0.0,
        risk_pct=actual_amount / equity if equity > 0 else 0,
    )


def kelly_criterion(
    equity: float,
    price: float,
    stop_loss: float,
    win_rate: float,
    payoff_ratio: float,
    kelly_fraction: float = 0.5,  # Half-Kelly (更保守)
    max_pct: float = 0.15,
    min_lot: int = 100,
) -> PositionSize:
    """凯利公式仓位.

    kelly% = (p * b - q) / b
    其中: p=胜率, q=败率, b=盈亏比

    Args:
        win_rate: 历史胜率 (0-1)
        payoff_ratio: 盈亏比 (平均盈利/平均亏损)
        kelly_fraction: Kelly 缩放因子 (0.5 = Half-Kelly)
    """
    risk_per_share = max(price - stop_loss, price * 0.01)
    b = payoff_ratio if payoff_ratio > 0 else 1.0
    p = min(max(win_rate, 0.01), 0.99)
    q = 1 - p

    kelly_pct = (p * b - q) / b * kelly_fraction
    kelly_pct = max(kelly_pct, 0.02)  # 最少 2%
    kelly_pct = min(kelly_pct, max_pct)  # 最多 max_pct

    amount = equity * kelly_pct
    shares = int(amount / price / min_lot) * min_lot
    actual_amount = shares * price
    total_risk = shares * risk_per_share

    return PositionSize(
        amount=actual_amount,
        shares=shares,
        risk_per_share=risk_per_share,
        total_risk=total_risk,
        risk_pct=actual_amount / equity if equity > 0 else 0,
    )


def atr_based(
    equity: float,
    price: float,
    atr: float,
    risk_budget_pct: float = 0.01,  # 每笔交易最大亏损 = 总资金 1%
    atr_mult: float = 2.0,
    max_pct: float = 0.15,
    min_lot: int = 100,
) -> PositionSize:
    """ATR 波动率标准化.

    每只股票的风险金额 = 总资金 * risk_budget_pct
    止损距离 = ATR * atr_mult
    股数 = 风险金额 / 止损距离

    优点: 波动大的股票自动买少, 波动小的自动买多
    """
    risk_per_share = atr * atr_mult
    if risk_per_share <= 0:
        risk_per_share = price * 0.03  # fallback 3%

    risk_budget = equity * risk_budget_pct
    shares = int(risk_budget / risk_per_share / min_lot) * min_lot
    actual_amount = shares * price

    # 不超过最大比例
    if actual_amount > equity * max_pct:
        shares = int(equity * max_pct / price / min_lot) * min_lot
        actual_amount = shares * price

    total_risk = shares * risk_per_share

    return PositionSize(
        amount=actual_amount,
        shares=shares,
        risk_per_share=risk_per_share,
        total_risk=total_risk,
        risk_pct=actual_amount / equity if equity > 0 else 0,
    )


def calc_optimal_position(
    equity: float,
    price: float,
    stop_loss: float,
    atr: float,
    win_rate: float = 0.5,
    payoff_ratio: float = 1.5,
    method: str = 'atr',
) -> PositionSize:
    """自动选择最优仓位方法.

    method: 'fixed', 'kelly', 'atr'
    """
    if method == 'kelly':
        return kelly_criterion(equity, price, stop_loss, win_rate, payoff_ratio)
    elif method == 'atr':
        return atr_based(equity, price, atr)
    else:
        return fixed_fraction(equity, price)
