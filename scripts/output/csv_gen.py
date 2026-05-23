#!/usr/bin/env python3
"""CSV Generator with fixed column order."""

import csv
from pathlib import Path
from typing import List, Dict, Any


# FIXED column order - NEVER CHANGE
FIXED_COLUMNS = [
    'stock_code', 'stock_name', 'date', 'ef_count',
    'MN1_state_hex', 'MN1_state_score',
    'W1_state_hex', 'W1_state_score',
    'D1_state_hex', 'D1_state_score',
    'MN1_base', 'MN1_trend_bit', 'MN1_position_bit', 'MN1_volatility_bit',
    'MN1_comp_label', 'MN1_trend_label', 'MN1_position_label', 'MN1_volatility_label',
    'W1_base', 'W1_trend_bit', 'W1_position_bit', 'W1_volatility_bit',
    'W1_comp_label', 'W1_trend_label', 'W1_position_label', 'W1_volatility_label',
    'D1_base', 'D1_trend_bit', 'D1_position_bit', 'D1_volatility_bit',
    'D1_comp_label', 'D1_trend_label', 'D1_position_label', 'D1_volatility_label'
]

# Chinese headers
CHINESE_HEADERS = {
    'stock_code': '股票代码',
    'stock_name': '股票简称',
    'date': '日期',
    'ef_count': 'EF周期数',
    'MN1_state_hex': 'MN1_state_hex',
    'MN1_state_score': 'MN1_state_score',
    'W1_state_hex': 'W1_state_hex',
    'W1_state_score': 'W1_state_score',
    'D1_state_hex': 'D1_state_hex',
    'D1_state_score': 'D1_state_score',
    'MN1_base': 'MN1_base',
    'MN1_trend_bit': 'MN1_trend_bit',
    'MN1_position_bit': 'MN1_position_bit',
    'MN1_volatility_bit': 'MN1_volatility_bit',
    'MN1_comp_label': 'MN1_comp_label',
    'MN1_trend_label': 'MN1_trend_label',
    'MN1_position_label': 'MN1_position_label',
    'MN1_volatility_label': 'MN1_volatility_label',
    'W1_base': 'W1_base',
    'W1_trend_bit': 'W1_trend_bit',
    'W1_position_bit': 'W1_position_bit',
    'W1_volatility_bit': 'W1_volatility_bit',
    'W1_comp_label': 'W1_comp_label',
    'W1_trend_label': 'W1_trend_label',
    'W1_position_label': 'W1_position_label',
    'W1_volatility_label': 'W1_volatility_label',
    'D1_base': 'D1_base',
    'D1_trend_bit': 'D1_trend_bit',
    'D1_position_bit': 'D1_position_bit',
    'D1_volatility_bit': 'D1_volatility_bit',
    'D1_comp_label': 'D1_comp_label',
    'D1_trend_label': 'D1_trend_label',
    'D1_position_label': 'D1_position_label',
    'D1_volatility_label': 'D1_volatility_label'
}


def generate_csv(
    screen_results: List[Any],
    output_path: Path,
    days_per_stock: int = 3
) -> Path:
    """Generate CSV with fixed column order.
    
    Args:
        screen_results: List of ScreenResult objects
        output_path: Output CSV path
        days_per_stock: Days per stock
    
    Returns:
        Path to generated CSV
    """
    rows = []
    
    for result in screen_results:
        for state in result.states:
            row = {
                'stock_code': result.stock_code,
                'stock_name': result.stock_name,
                'date': state['date'],
                'ef_count': result.ef_count,
                'MN1_state_hex': state['MN1_hex'],
                'MN1_state_score': state['MN1_score'],
                'W1_state_hex': state['W1_hex'],
                'W1_state_score': state['W1_score'],
                'D1_state_hex': state['D1_hex'],
                'D1_state_score': state['D1_score'],
                'MN1_base': state['MN1_base'],
                'MN1_trend_bit': state['MN1_trend_bit'],
                'MN1_position_bit': state['MN1_position_bit'],
                'MN1_volatility_bit': state['MN1_volatility_bit'],
                'MN1_comp_label': state['MN1_comp_label'],
                'MN1_trend_label': state['MN1_trend_label'],
                'MN1_position_label': state['MN1_position_label'],
                'MN1_volatility_label': state['MN1_volatility_label'],
                'W1_base': state['W1_base'],
                'W1_trend_bit': state['W1_trend_bit'],
                'W1_position_bit': state['W1_position_bit'],
                'W1_volatility_bit': state['W1_volatility_bit'],
                'W1_comp_label': state['W1_comp_label'],
                'W1_trend_label': state['W1_trend_label'],
                'W1_position_label': state['W1_position_label'],
                'W1_volatility_label': state['W1_volatility_label'],
                'D1_base': state['D1_base'],
                'D1_trend_bit': state['D1_trend_bit'],
                'D1_position_bit': state['D1_position_bit'],
                'D1_volatility_bit': state['D1_volatility_bit'],
                'D1_comp_label': state['D1_comp_label'],
                'D1_trend_label': state['D1_trend_label'],
                'D1_position_label': state['D1_position_label'],
                'D1_volatility_label': state['D1_volatility_label']
            }
            rows.append(row)
    
    # Write CSV with Chinese headers
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=FIXED_COLUMNS)
        
        # Write Chinese header
        header = {col: CHINESE_HEADERS.get(col, col) for col in FIXED_COLUMNS}
        writer.writerow(header)
        
        # Write data
        writer.writerows(rows)
    
    return output_path
