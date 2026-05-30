"""VCP 策略 - Volatility Contraction Pattern.

Mark Minervini 核心模式：
- 阶段 1：波动率逐步收缩（ATR 连续下降）
- 阶段 2：价格振幅收窄（5日振幅 < 20日振幅 × 60%）
- 突破确认：收盘 > 10日最高 + 成交量 > 50日均量 × 1.5

依赖：
    atr14, atr14_5d_ago, atr14_10d_ago
    high_5d, low_5d, high_20d, low_20d, high_10d
    volume, volume_ma_50
    close, open
"""

from __future__ import annotations

from typing import Any


def vcp_signal(
    row: dict[str, Any],
    ctx: dict[str, Any],
) -> tuple[str, float] | None:

    atr_now = ctx.get("atr14")
    atr_5d = ctx.get("atr14_5d_ago")
    atr_10d = ctx.get("atr14_10d_ago")
    high_5d = ctx.get("high_5d")
    low_5d = ctx.get("low_5d")
    high_20d = ctx.get("high_20d")
    low_20d = ctx.get("low_20d")
    high_10d = ctx.get("high_10d")
    vol = ctx.get("volume")
    vol_ma50 = ctx.get("volume_ma_50")
    close = row.get("close", 0)

    if close <= 0:
        return None

    contraction_score = 0

    # 1. ATR 连续收缩（3 段下降）
    if atr_now and atr_5d and atr_10d:
        if atr_now < atr_5d < atr_10d:
            contraction_score += 1

    # 2. 价格振幅收缩
    range_20 = 0
    if all([high_5d, low_5d, high_20d, low_20d]):
        range_5 = (high_5d - low_5d) / close if close else 0
        range_20 = (high_20d - low_20d) / close if close else 1
        if range_20 > 0 and range_5 < range_20 * 0.6:
            contraction_score += 1

    # 3. 日线低波动（振幅 < 近 20 日均振幅 × 0.5）
    open_p = row.get("open", close)
    day_range = abs(close - open_p) / close if close else 0
    if range_20 > 0 and day_range < range_20 * 0.5:
        contraction_score += 1

    # VCP 收缩阶段标记（未突破时预告）
    if contraction_score >= 2:
        if high_10d and close > high_10d:
            # 突破确认：量能放大
            if vol and vol_ma50 and vol > vol_ma50 * 1.5:
                return ("vcp_breakout", 0.95)
            if vol and vol_ma50 and vol > vol_ma50 * 1.2:
                return ("vcp_breakout_weak_vol", 0.70)
            return ("vcp_breakout_no_vol", 0.55)
        # 收缩完成但未突破
        return ("vcp_contraction", 0.40)

    if contraction_score == 1:
        return ("vcp_early_contraction", 0.20)

    return None
