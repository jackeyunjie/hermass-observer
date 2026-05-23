"""2560 均线系统策略。

中国交易圈经典趋势跟随系统：
- 金叉（MA25 上穿 MA60）：买入信号
- 死叉（MA25 下穿 MA60）：卖出信号
- 多头排列（价格 > MA25 > MA60）：最强持有状态
- 两者斜率同时向上：趋势加速

依赖：
    ma25, ma60, ma25_prev, ma60_prev, close
"""

from __future__ import annotations

from typing import Any


def ma2560_signal(
    row: dict[str, Any],
    ctx: dict[str, Any],
) -> tuple[str, float] | None:

    ma25 = ctx.get("ma25")
    ma60 = ctx.get("ma60")
    ma25_prev = ctx.get("ma25_prev")
    ma60_prev = ctx.get("ma60_prev")
    close = row.get("close", 0)

    if ma25 is None or ma60 is None or close <= 0:
        return None

    aligned = ma25 > ma60
    aligned_prev = (ma25_prev or 0) > (ma60_prev or 0)

    # 金叉
    if aligned and not aligned_prev:
        return ("ma2560_golden_cross", 0.85)

    # 死叉 — 无条件出场
    if not aligned and aligned_prev:
        return ("ma2560_death_cross_exit", 0.90)

    # 均线多头排列 + 价格在 MA25 上方 = 最强持有
    if close > ma25 > ma60:
        return ("ma2560_strong_hold", 0.65)

    # 仅均线多头排列
    if aligned:
        return ("ma2560_aligned", 0.50)

    # 空头排列
    if ma25 < ma60:
        return ("ma2560_bearish", 0.20)

    return None
