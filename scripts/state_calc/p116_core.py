#!/usr/bin/env python3
"""P116 State Core Calculation Module.

Implements D1-perspective state calculation for MN1/W1/D1 timeframes.
All timeframes use D1 close price compared against their own SR levels.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class StateComponents:
    """State score components."""
    base: int           # 0=contraction, 8=expansion
    trend_bit: int      # 0=neutral, 1=bull/bear
    position_bit: int   # 0=neutral, 2=SR trigger
    volatility_bit: int # 0=stable, 1=expanding
    
    # Labels
    comp_label: str     # 缩/扩
    trend_label: str    # 牛/熊/平
    position_label: str # 上突/下突/中
    volatility_label: str  # 稳/波扩
    
    # Computed
    score: int
    hex: str


def calculate_state(
    d1_close: float,
    sr_support: float,
    sr_resistance: float,
    trend_ma_fast: float,
    trend_ma_slow: float,
    atr_current: float,
    atr_previous: float
) -> StateComponents:
    """Calculate P116 state from D1 perspective.
    
    D1 视角天条：
    - 无论计算哪个周期（MN1/W1/D1），position 都使用 D1 收盘价比较
    - SR 使用各自周期的关键位（MN1用月线SR，W1用周线SR，D1用日线SR）
    - trend 和 volatility 使用各自周期的数据
    
    Args:
        d1_close: D1 closing price (used for ALL timeframes' position calculation)
        sr_support: Support level for THIS timeframe (MN1/W1/D1各自的支撑)
        sr_resistance: Resistance level for THIS timeframe (MN1/W1/D1各自的阻力)
        trend_ma_fast: Fast MA for trend (各自周期的MA)
        trend_ma_slow: Slow MA for trend (各自周期的MA)
        atr_current: Current ATR (各自周期的ATR)
        atr_previous: Previous ATR (各自周期的ATR)
    
    Returns:
        StateComponents with score and labels
    """
    # Position: D1 close vs THIS timeframe's SR.
    # 天条：所有周期都用 D1 close 比较各自的 SR.
    # State bit semantics: only SR trigger contributes 2; inside range is 0.
    if d1_close > sr_resistance:
        position_bit = 2
        position_label = "上突"
    elif d1_close < sr_support:
        position_bit = 2
        position_label = "下突"
    else:
        position_bit = 0
        position_label = "中"
    
    # Trend: MA comparison
    if trend_ma_fast > trend_ma_slow:
        trend_bit = 1
        trend_label = "牛"
    elif trend_ma_fast < trend_ma_slow:
        trend_bit = 1
        trend_label = "熊"
    else:
        trend_bit = 0
        trend_label = "平"
    
    # Base: expansion if trend exists
    base = 8 if trend_bit == 1 else 0
    comp_label = "扩" if base == 8 else "缩"
    
    # Volatility
    volatility_bit = 1 if atr_current > atr_previous else 0
    volatility_label = "波扩" if volatility_bit else "稳"
    
    # Score
    score = base + (trend_bit * 4) + position_bit + volatility_bit
    
    # Hex encoding
    if score < 0:
        hex_val = f"-{abs(score):X}"
    else:
        hex_val = f"{score:X}"
    
    return StateComponents(
        base=base,
        trend_bit=trend_bit,
        position_bit=position_bit,
        volatility_bit=volatility_bit,
        comp_label=comp_label,
        trend_label=trend_label,
        position_label=position_label,
        volatility_label=volatility_label,
        score=score,
        hex=hex_val
    )


def decode_state_hex(state_hex: str) -> StateComponents:
    """Decode state hex back to components."""
    if state_hex.startswith('-'):
        score = -int(state_hex[1:], 16)
    else:
        score = int(state_hex, 16)
    
    abs_score = abs(score)
    base = 0 if abs_score < 8 else 8
    rem = abs_score - base
    
    trend_bit = 1 if rem >= 4 else 0
    rem -= trend_bit * 4
    
    pos_bit = 1 if rem >= 2 else 0
    rem -= pos_bit * 2
    
    vol_bit = rem
    
    # Labels
    comp = '缩' if base == 0 else '扩'
    trend = '牛' if trend_bit and score > 0 else ('熊' if trend_bit else '平')
    pos = '上突' if pos_bit and score > 0 else ('下突' if pos_bit and score < 0 else '中')
    vol = '波扩' if vol_bit else '稳'
    
    return StateComponents(
        base=base,
        trend_bit=trend_bit,
        position_bit=pos_bit,
        volatility_bit=vol_bit,
        comp_label=comp,
        trend_label=trend,
        position_label=pos,
        volatility_label=vol,
        score=score,
        hex=state_hex
    )


def is_ef_state(state_hex: str) -> bool:
    """Check if state is E (14) or F (15)."""
    try:
        if state_hex.startswith('-'):
            score = -int(state_hex[1:], 16)
        else:
            score = int(state_hex, 16)
        return score in (14, 15)
    except (ValueError, AttributeError):
        return False
