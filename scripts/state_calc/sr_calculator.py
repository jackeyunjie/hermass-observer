#!/usr/bin/env python3
"""SR (Support/Resistance) Calculator.

Implements MT4-style SR calculation using fractals and price action.
"""

import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class SRLevels:
    """Support and Resistance levels."""
    support: float
    resistance: float
    ready: bool
    
    def __post_init__(self):
        if self.support is None or self.resistance is None:
            self.ready = False


def find_fractal_highs(highs: List[float], period: int = 5) -> List[int]:
    """Find fractal high indices.
    
    A fractal high is a bar where the high is higher than 
    period bars on both sides.
    """
    indices = []
    half = period // 2
    
    for i in range(half, len(highs) - half):
        is_fractal = True
        for j in range(1, half + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_fractal = False
                break
        if is_fractal:
            indices.append(i)
    
    return indices


def find_fractal_lows(lows: List[float], period: int = 5) -> List[int]:
    """Find fractal low indices."""
    indices = []
    half = period // 2
    
    for i in range(half, len(lows) - half):
        is_fractal = True
        for j in range(1, half + 1):
            if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                is_fractal = False
                break
        if is_fractal:
            indices.append(i)
    
    return indices


def calculate_sr(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    lookback: int = 120,
    min_fractals: int = 3
) -> SRLevels:
    """Calculate SR levels from price data.
    
    Args:
        highs: List of high prices
        lows: List of low prices
        closes: List of close prices
        lookback: Number of bars to look back
        min_fractals: Minimum fractals needed for valid SR
    
    Returns:
        SRLevels with support, resistance, and ready flag
    """
    if len(closes) < lookback:
        return SRLevels(support=None, resistance=None, ready=False)
    
    # Use last lookback bars
    h = highs[-lookback:]
    l = lows[-lookback:]
    
    # Find fractals
    high_indices = find_fractal_highs(h)
    low_indices = find_fractal_lows(l)
    
    if len(high_indices) < min_fractals or len(low_indices) < min_fractals:
        # Fallback: use recent high/low
        resistance = max(h[-20:]) if len(h) >= 20 else max(h)
        support = min(l[-20:]) if len(l) >= 20 else min(l)
        return SRLevels(support=support, resistance=resistance, ready=True)
    
    # Get fractal values
    fractal_highs = [h[i] for i in high_indices]
    fractal_lows = [l[i] for i in low_indices]
    
    # Use most recent significant levels
    # Resistance: highest recent fractal high
    resistance = max(fractal_highs[-5:]) if len(fractal_highs) >= 5 else max(fractal_highs)
    
    # Support: lowest recent fractal low
    support = min(fractal_lows[-5:]) if len(fractal_lows) >= 5 else min(fractal_lows)
    
    # Validate: support should be below resistance
    if support >= resistance:
        # Use percentile-based fallback
        support = np.percentile(l, 10)
        resistance = np.percentile(h, 90)
    
    return SRLevels(support=float(support), resistance=float(resistance), ready=True)


def calculate_ma(prices: List[float], period: int) -> Optional[float]:
    """Calculate simple moving average."""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def calculate_atr(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14
) -> Tuple[float, float]:
    """Calculate ATR (Average True Range).
    
    Returns:
        Tuple of (current_atr, previous_atr)
    """
    if len(closes) < period + 1:
        return 0.0, 0.0
    
    true_ranges = []
    for i in range(1, len(closes)):
        high_low = highs[i] - lows[i]
        high_close = abs(highs[i] - closes[i-1])
        low_close = abs(lows[i] - closes[i-1])
        true_ranges.append(max(high_low, high_close, low_close))
    
    if len(true_ranges) < period:
        return 0.0, 0.0
    
    # Current ATR
    current_atr = sum(true_ranges[-period:]) / period
    
    # Previous ATR
    if len(true_ranges) >= period + 1:
        previous_atr = sum(true_ranges[-(period+1):-1]) / period
    else:
        previous_atr = current_atr
    
    return current_atr, previous_atr
