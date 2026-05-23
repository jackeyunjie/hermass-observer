"""ATR 吊灯出场策略 - Chandelier Exit.

Le Beau & Lucas 经典出场管理：
- 吊灯止损 = 入场以来最高价 - 3 × ATR(14)
- 跌破吊灯位置 → 离场
- ATR 自适应：波动大的股票给更大空间

依赖：
    atr14, highest_since_entry, close, high
"""

from __future__ import annotations

from typing import Any


def chandelier_exit_signal(
    row: dict[str, Any],
    ctx: dict[str, Any],
    position_ctx: dict[str, Any] | None = None,
) -> tuple[str, float] | None:
    """检查是否触发吊灯止损出场。

    Args:
        row: 当前 Bar 数据
        ctx: 当前指标上下文
        position_ctx: 持仓上下文 {"highest_since_entry": float, "entry_price": float}

    Returns:
        (signal_type, confidence) 或 None
    """
    atr14 = ctx.get("atr14")
    if atr14 is None or atr14 <= 0:
        return None

    close = row.get("close", 0)
    high = row.get("high", close)
    if close <= 0:
        return None

    if position_ctx is None:
        return None

    highest = max(position_ctx.get("highest_since_entry", high), high)
    entry_price = position_ctx.get("entry_price", close)

    atr_mult = position_ctx.get("atr_mult", 3.0)
    chandelier_stop = highest - atr_mult * atr14

    waterfall_stop = highest - 2.0 * atr14

    profit_from_entry = (close - entry_price) / entry_price if entry_price else 0

    # 盈利超过 15% 时收紧吊灯乘数
    if profit_from_entry > 0.15:
        chandelier_stop = highest - 2.0 * atr14
        waterfall_stop = highest - 1.5 * atr14

    if close < waterfall_stop:
        return ("chandelier_exit_tight", 0.95)

    if close < chandelier_stop:
        return ("chandelier_exit", 0.80)

    # 吊灯在抬高：正常持有
    if chandelier_stop > (ctx.get("chandelier_stop_prev") or 0):
        return ("chandelier_rising", 0.30)

    return None
