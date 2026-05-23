#!/usr/bin/env python3
"""EF Screener - Filter stocks by E/F state conditions.

筛选至少2个周期为E或F状态的股票。
"""

from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class ScreenResult:
    """Screening result for a stock."""
    stock_code: str
    stock_name: str
    ef_count: int
    mn1_hex: str
    w1_hex: str
    d1_hex: str
    states: List[Dict[str, Any]]  # Recent days data


def count_ef_states(mn1_hex: str, w1_hex: str, d1_hex: str) -> int:
    """Count how many timeframes are in E or F state."""
    ef_states = {'E', 'F'}
    count = 0
    for h in [mn1_hex, w1_hex, d1_hex]:
        if h in ef_states:
            count += 1
    return count


def screen_stocks(
    all_states: List[Dict[str, Any]],
    min_ef: int = 2,
    max_results: int = 100,
    days_per_stock: int = 3
) -> List[ScreenResult]:
    """Screen stocks by EF conditions.
    
    Args:
        all_states: List of state dicts with keys: stock_code, stock_name, 
                    date, MN1_hex, W1_hex, D1_hex
        min_ef: Minimum EF count (default 2)
        max_results: Maximum stocks to return
        days_per_stock: Days of history per stock
    
    Returns:
        List of ScreenResult, sorted by ef_count desc
    """
    # Group by stock
    stock_groups = {}
    for state in all_states:
        code = state['stock_code']
        if code not in stock_groups:
            stock_groups[code] = []
        stock_groups[code].append(state)
    
    results = []
    
    for code, states in stock_groups.items():
        # Sort by date descending
        states = sorted(states, key=lambda x: x['date'], reverse=True)
        
        # Check latest state
        latest = states[0]
        ef_count = count_ef_states(
            latest['MN1_hex'],
            latest['W1_hex'],
            latest['D1_hex']
        )
        
        if ef_count >= min_ef:
            results.append(ScreenResult(
                stock_code=code,
                stock_name=latest['stock_name'],
                ef_count=ef_count,
                mn1_hex=latest['MN1_hex'],
                w1_hex=latest['W1_hex'],
                d1_hex=latest['D1_hex'],
                states=states[:days_per_stock]
            ))
    
    # Sort by ef_count desc, then code asc
    results.sort(key=lambda x: (-x.ef_count, x.stock_code))
    
    return results[:max_results]


def classify_signal_strength(ef_count: int) -> str:
    """Classify signal strength."""
    if ef_count == 3:
        return "超强(3/3)"
    elif ef_count == 2:
        return "强势(2/3)"
    else:
        return "一般"
