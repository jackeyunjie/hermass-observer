#!/usr/bin/env python3
"""Generate P116 daily observation pool with FIXED column order.

Usage:
    python3 scripts/generate_observation_pool.py --date 2026-05-20
"""

import argparse
import csv
import json
from pathlib import Path

# FIXED column order - never change this
FIXED_COLUMNS = [
    # Core info
    '股票代码', '股票简称', '日期', 'EF周期数',
    # Core states (left side, easy to see)
    'MN1_state_hex', 'MN1_state_score',
    'W1_state_hex', 'W1_state_score',
    'D1_state_hex', 'D1_state_score',
    # Detail fields
    'MN1_base', 'MN1_trend_bit', 'MN1_position_bit', 'MN1_volatility_bit',
    'MN1_comp_label', 'MN1_trend_label', 'MN1_position_label', 'MN1_volatility_label',
    'W1_base', 'W1_trend_bit', 'W1_position_bit', 'W1_volatility_bit',
    'W1_comp_label', 'W1_trend_label', 'W1_position_label', 'W1_volatility_label',
    'D1_base', 'D1_trend_bit', 'D1_position_bit', 'D1_volatility_bit',
    'D1_comp_label', 'D1_trend_label', 'D1_position_label', 'D1_volatility_label'
]


def decode_state(state_hex: str) -> dict:
    """Decode state hex to components."""
    if state_hex is None or state_hex == '':
        return {
            'state_hex': '',
            'state_score': '',
            'base': '',
            'trend_bit': '',
            'position_bit': '',
            'volatility_bit': '',
            'comp_label': '',
            'trend_label': '',
            'position_label': '',
            'volatility_label': ''
        }
    if state_hex.startswith('-'):
        score = -int(state_hex[1:], 16)
    else:
        score = int(state_hex, 16)
    
    abs_score = abs(score)
    base = 0 if abs_score < 8 else 8
    rem = abs_score - base
    trend_bit = 1 if rem >= 4 else 0
    rem -= trend_bit * 4
    pos_bit = 2 if rem >= 2 else 0
    rem -= pos_bit
    vol_bit = rem
    
    return {
        'state_hex': state_hex,
        'state_score': score,
        'base': base,
        'trend_bit': trend_bit,
        'position_bit': pos_bit,
        'volatility_bit': vol_bit,
        'comp_label': '缩' if base == 0 else '扩',
        'trend_label': '牛' if trend_bit and score > 0 else ('熊' if trend_bit else '平'),
        'position_label': '上突' if pos_bit and score > 0 else ('下突' if pos_bit and score < 0 else '中'),
        'volatility_label': '波扩' if vol_bit else '稳'
    }


def generate_observation_pool(
    input_json: str,
    output_csv: str,
    output_html: str,
    date_str: str,
    require_mn1_ef: bool = False,
):
    """Generate observation pool with fixed column order."""
    
    with open(input_json, 'r', encoding='utf-8') as f:
        data = json.load(f)

    rows = data['rows']
    row_limit = data.get('row_limit_per_symbol', 6)

    # Group by symbol
    symbol_rows = {}
    for row in rows:
        sym = row['品种']
        symbol_rows.setdefault(sym, []).append(row)

    # Filter and rank - at least 2 E/F
    filtered = []
    for sym, sym_rows in symbol_rows.items():
        if len(sym_rows) != row_limit:
            continue
        
        latest = sym_rows[0]
        mn1_state = latest['MN1state']
        ef_count = sum(1 for s in [latest['W1state'], mn1_state, latest['D1state']] if s in ('E', 'F'))
        
        if ef_count >= 2 and (not require_mn1_ef or mn1_state in ('E', 'F')):
            parts = sym.split(' ', 1)
            filtered.append({
                'code': parts[0],
                'name': parts[1] if len(parts) > 1 else '',
                'ef_count': ef_count,
                'rows': sym_rows[:3]
            })

    filtered.sort(key=lambda x: (-x['ef_count'], x['code']))
    top100 = filtered[:100]

    # Build CSV rows
    csv_rows = []
    for item in top100:
        for row in item['rows']:
            date = row['时间'][:10]
            mn1 = decode_state(row['MN1state'])
            w1 = decode_state(row['W1state'])
            d1 = decode_state(row['D1state'])
            
            csv_rows.append({
                '股票代码': item['code'],
                '股票简称': item['name'],
                '日期': date,
                'EF周期数': item['ef_count'],
                'MN1_state_hex': mn1['state_hex'],
                'MN1_state_score': mn1['state_score'],
                'W1_state_hex': w1['state_hex'],
                'W1_state_score': w1['state_score'],
                'D1_state_hex': d1['state_hex'],
                'D1_state_score': d1['state_score'],
                'MN1_base': mn1['base'],
                'MN1_trend_bit': mn1['trend_bit'],
                'MN1_position_bit': mn1['position_bit'],
                'MN1_volatility_bit': mn1['volatility_bit'],
                'MN1_comp_label': mn1['comp_label'],
                'MN1_trend_label': mn1['trend_label'],
                'MN1_position_label': mn1['position_label'],
                'MN1_volatility_label': mn1['volatility_label'],
                'W1_base': w1['base'],
                'W1_trend_bit': w1['trend_bit'],
                'W1_position_bit': w1['position_bit'],
                'W1_volatility_bit': w1['volatility_bit'],
                'W1_comp_label': w1['comp_label'],
                'W1_trend_label': w1['trend_label'],
                'W1_position_label': w1['position_label'],
                'W1_volatility_label': w1['volatility_label'],
                'D1_base': d1['base'],
                'D1_trend_bit': d1['trend_bit'],
                'D1_position_bit': d1['position_bit'],
                'D1_volatility_bit': d1['volatility_bit'],
                'D1_comp_label': d1['comp_label'],
                'D1_trend_label': d1['trend_label'],
                'D1_position_label': d1['position_label'],
                'D1_volatility_label': d1['volatility_label']
            })

    # Save CSV with fixed column order
    with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=FIXED_COLUMNS)
        writer.writeheader()
        writer.writerows(csv_rows)

    # Generate HTML
    html = generate_html(csv_rows, date_str, len(filtered), require_mn1_ef)
    with open(output_html, 'w', encoding='utf-8') as f:
        f.write(html)

    return len(csv_rows), len(top100), len(filtered)


def generate_html(rows, date_str, total_matches, require_mn1_ef=False):
    """Generate HTML with fixed column order."""
    stock_count = len({(row['股票代码'], row['股票简称']) for row in rows})
    ultra_count = len({
        (row['股票代码'], row['股票简称'])
        for row in rows
        if str(row.get('EF周期数')) == '3'
    })
    strong_count = len({
        (row['股票代码'], row['股票简称'])
        for row in rows
        if str(row.get('EF周期数')) == '2'
    })
    filter_text = '至少2周期E/F，且MN1必须E/F' if require_mn1_ef else '至少2周期E/F'
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>P116 每日观察池 - {date_str}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; background: #f5f5f5; }}
  h1 {{ color: #333; font-size: 20px; margin-bottom: 10px; }}
  .summary {{ background: #fff; padding: 15px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  .summary span {{ margin-right: 20px; color: #666; }}
  .summary .num {{ color: #1890ff; font-weight: bold; font-size: 18px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; font-size: 12px; }}
  th {{ padding: 8px 6px; text-align: center; font-size: 11px; white-space: nowrap; position: sticky; top: 0; border-right: 1px solid rgba(255,255,255,0.2); }}
  td {{ padding: 6px; border-bottom: 1px solid #eee; border-right: 1px solid #f0f0f0; text-align: center; }}
  tr:hover {{ background: #f0f7ff; }}
  .code {{ font-family: monospace; font-weight: bold; color: #333; font-size: 13px; }}
  .name {{ color: #666; }}
  .date {{ font-family: monospace; color: #999; font-size: 11px; }}
  .ef3 {{ background: #fff7e6; }}
  .ef2 {{ background: #f6ffed; }}
  .state-ef {{ color: #52c41a; font-weight: bold; font-size: 14px; }}
  .state-other {{ color: #999; }}
  .score {{ font-family: monospace; font-size: 11px; color: #666; }}
  .label {{ display: inline-block; padding: 1px 4px; border-radius: 2px; font-size: 10px; margin-right: 1px; }}
  .label-niu {{ background: #fff1f0; color: #cf1322; }}
  .label-xiong {{ background: #f6ffed; color: #389e0d; }}
  .label-ping {{ background: #f5f5f5; color: #666; }}
  .label-tu {{ background: #e6f7ff; color: #096dd9; }}
  .label-zhong {{ background: #fff7e6; color: #d46b08; }}
  .col-core {{ background: #1890ff; }}
  .col-mn1 {{ background: #722ed1; }}
  .col-w1 {{ background: #13c2c2; }}
  .col-d1 {{ background: #fa8c16; }}
  .col-detail {{ background: #8c8c8c; }}
</style>
</head>
<body>
<h1>P116 State 每日观察池 - {date_str}</h1>
<div class="summary">
  <span>筛选: <b>{filter_text}</b></span>
  <span>总匹配: <span class="num">{total_matches}</span></span>
  <span>超强(3/3): <span class="num">{ultra_count}</span></span>
  <span>强势(2/3): <span class="num">{strong_count}</span></span>
  <span>展示: <span class="num">{stock_count}</span>只×3天</span>
</div>
<table>
<thead>
<tr>
'''

    header_colors = {
        '股票代码': 'col-core', '股票简称': 'col-core', '日期': 'col-core', 'EF周期数': 'col-core',
        'MN1_state_hex': 'col-mn1', 'MN1_state_score': 'col-mn1',
        'W1_state_hex': 'col-w1', 'W1_state_score': 'col-w1',
        'D1_state_hex': 'col-d1', 'D1_state_score': 'col-d1'
    }

    for col in FIXED_COLUMNS:
        color_class = header_colors.get(col, 'col-detail')
        display = col.replace('_state_hex', '').replace('_state_score', '_score').replace('_label', '').replace('_bit', '').replace('volatility', 'vol')
        html += f'<th class="{color_class}">{display}</th>\n'

    html += '</tr>\n</thead>\n<tbody>\n'

    if not rows:
        html += f'<tr><td colspan="{len(FIXED_COLUMNS)}" style="padding: 24px; text-align: left; color: #666;">无匹配品种：当前筛选条件为 {filter_text}。</td></tr>\n'

    for row in rows:
        ef = int(row.get('EF周期数', 0))
        row_class = 'ef3' if ef == 3 else 'ef2'
        html += f'<tr class="{row_class}">\n'
        
        for col in FIXED_COLUMNS:
            val = str(row.get(col, ''))
            
            if col == '股票代码':
                html += f'<td class="code">{val}</td>\n'
            elif col == '股票简称':
                html += f'<td class="name">{val}</td>\n'
            elif col == '日期':
                html += f'<td class="date">{val}</td>\n'
            elif col in ('MN1_state_hex', 'W1_state_hex', 'D1_state_hex'):
                if val in ('E', 'F'):
                    html += f'<td class="state-ef">{val}</td>\n'
                else:
                    html += f'<td class="state-other">{val}</td>\n'
            elif col in ('MN1_state_score', 'W1_state_score', 'D1_state_score'):
                html += f'<td class="score">{val}</td>\n'
            elif 'label' in col:
                label_class = ''
                if val == '牛':
                    label_class = 'label-niu'
                elif val == '熊':
                    label_class = 'label-xiong'
                elif val == '平':
                    label_class = 'label-ping'
                elif val in ('上突', '下突'):
                    label_class = 'label-tu'
                elif val == '中':
                    label_class = 'label-zhong'
                html += f'<td><span class="label {label_class}">{val}</span></td>\n'
            else:
                html += f'<td>{val}</td>\n'
        
        html += '</tr>\n'

    html += '''</tbody>
</table>
</body>
</html>'''
    
    return html


def main():
    parser = argparse.ArgumentParser(description='Generate P116 observation pool')
    parser.add_argument('--date', required=True, help='Date string like 2026-05-20')
    parser.add_argument('--input', help='Input JSON path')
    parser.add_argument('--output-csv', help='Output CSV path')
    parser.add_argument('--output-html', help='Output HTML path')
    parser.add_argument('--require-mn1-ef', action='store_true', help='Require latest MN1 state to be E/F')
    args = parser.parse_args()
    
    date_str = args.date
    input_json = args.input or f'fixtures/all_products_d1_view_6_rows_{date_str.replace("-", "")}.json'
    output_csv = args.output_csv or f'fixtures/observation_pool_{date_str.replace("-", "")}.csv'
    output_html = args.output_html or f'public/observation_pool_{date_str.replace("-", "")}.html'
    
    rows, stocks, total_matches = generate_observation_pool(
        input_json,
        output_csv,
        output_html,
        date_str,
        require_mn1_ef=args.require_mn1_ef,
    )
    
    print(f'已生成:')
    print(f'  CSV: {output_csv}')
    print(f'  HTML: {output_html}')
    print(f'  总匹配: {total_matches}只')
    print(f'  数据: {stocks}只 × 3天 = {rows}行')
    print(f'  字段顺序: 已固定（股票代码/简称/日期 → MN1 hex/score → W1 hex/score → D1 hex/score → 详细字段）')


if __name__ == '__main__':
    main()
