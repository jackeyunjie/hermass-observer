#!/usr/bin/env python3
"""筛选三周期都是E/F的股票，生成推荐表单."""

import json
import csv
from pathlib import Path
from datetime import datetime


def decode_state(state_hex):
    """Decode state hex to components."""
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


def filter_3of3_ef(input_json, date_str):
    """Filter stocks where all 3 periods are E/F."""
    
    with open(input_json, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    rows = data['rows']
    row_limit = data.get('row_limit_per_symbol', 6)
    
    # Group by symbol
    symbol_rows = {}
    for row in rows:
        sym = row['品种']
        symbol_rows.setdefault(sym, []).append(row)
    
    # Filter: ALL 3 periods must be E/F
    filtered = []
    for sym, sym_rows in symbol_rows.items():
        if len(sym_rows) != row_limit:
            continue
        
        latest = sym_rows[0]
        mn1 = latest['MN1state']
        w1 = latest['W1state']
        d1 = latest['D1state']
        
        # Strict: all 3 must be E or F
        if mn1 in ('E', 'F') and w1 in ('E', 'F') and d1 in ('E', 'F'):
            parts = sym.split(' ', 1)
            filtered.append({
                'code': parts[0],
                'name': parts[1] if len(parts) > 1 else '',
                'mn1': mn1,
                'w1': w1,
                'd1': d1,
                'rows': sym_rows[:3]  # Last 3 days
            })
    
    # Sort by code
    filtered.sort(key=lambda x: x['code'])
    
    return filtered


def generate_csv_3of3(stocks, output_csv, date_str):
    """Generate CSV for 3/3 EF stocks."""
    
    FIXED_COLUMNS = [
        '股票代码', '股票简称', '日期', 'MN1_state_hex', 'MN1_state_score',
        'W1_state_hex', 'W1_state_score', 'D1_state_hex', 'D1_state_score',
        'MN1_base', 'MN1_trend_bit', 'MN1_position_bit', 'MN1_volatility_bit',
        'MN1_comp_label', 'MN1_trend_label', 'MN1_position_label', 'MN1_volatility_label',
        'W1_base', 'W1_trend_bit', 'W1_position_bit', 'W1_volatility_bit',
        'W1_comp_label', 'W1_trend_label', 'W1_position_label', 'W1_volatility_label',
        'D1_base', 'D1_trend_bit', 'D1_position_bit', 'D1_volatility_bit',
        'D1_comp_label', 'D1_trend_label', 'D1_position_label', 'D1_volatility_label'
    ]
    
    csv_rows = []
    for item in stocks:
        for row in item['rows']:
            date = row['时间'][:10]
            mn1 = decode_state(row['MN1state'])
            w1 = decode_state(row['W1state'])
            d1 = decode_state(row['D1state'])
            
            csv_rows.append({
                '股票代码': item['code'],
                '股票简称': item['name'],
                '日期': date,
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
    
    with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=FIXED_COLUMNS)
        writer.writeheader()
        writer.writerows(csv_rows)
    
    return len(csv_rows)


def generate_html_3of3(stocks, output_html, date_str):
    """Generate HTML for 3/3 EF stocks."""
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>P116 三周期E/F推荐 - {date_str}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; background: #f5f5f5; }}
  h1 {{ color: #333; font-size: 20px; margin-bottom: 10px; }}
  .summary {{ background: #fff; padding: 15px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  .summary span {{ margin-right: 20px; color: #666; }}
  .summary .num {{ color: #cf1322; font-weight: bold; font-size: 24px; }}
  .warning {{ background: #fff7e6; border: 1px solid #ffd591; padding: 15px; border-radius: 8px; margin-bottom: 20px; color: #d46b08; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; font-size: 12px; }}
  th {{ padding: 8px 6px; text-align: center; font-size: 11px; white-space: nowrap; position: sticky; top: 0; border-right: 1px solid rgba(255,255,255,0.2); }}
  td {{ padding: 6px; border-bottom: 1px solid #eee; border-right: 1px solid #f0f0f0; text-align: center; }}
  tr:hover {{ background: #f0f7ff; }}
  .code {{ font-family: monospace; font-weight: bold; color: #333; font-size: 13px; }}
  .name {{ color: #666; }}
  .date {{ font-family: monospace; color: #999; font-size: 11px; }}
  .state-ef {{ color: #52c41a; font-weight: bold; font-size: 14px; }}
  .score {{ font-family: monospace; font-size: 11px; color: #666; }}
  .label {{ display: inline-block; padding: 1px 4px; border-radius: 2px; font-size: 10px; margin-right: 1px; }}
  .label-niu {{ background: #fff1f0; color: #cf1322; }}
  .label-tu {{ background: #e6f7ff; color: #096dd9; }}
  .col-core {{ background: #1890ff; color: white; }}
  .col-mn1 {{ background: #722ed1; color: white; }}
  .col-w1 {{ background: #13c2c2; color: white; }}
  .col-d1 {{ background: #fa8c16; color: white; }}
  .col-detail {{ background: #8c8c8c; color: white; }}
</style>
</head>
<body>
<h1>P116 三周期E/F推荐名单 - {date_str}</h1>
<div class="summary">
  <span>筛选条件: <b>MN1=E/F AND W1=E/F AND D1=E/F</b></span>
  <span>匹配数量: <span class="num">{len(stocks)}</span></span>
  <span>展示: <span class="num">{len(stocks)}</span>只 × 3天</span>
</div>
'''
    
    if len(stocks) == 0:
        html += '''
<div class="warning">
  <b>⚠️ 无匹配股票</b><br>
  5月20日没有三周期同时达到E/F状态的股票。<br>
  这是正常现象，因为月线(MN1)达到E/F的条件非常苛刻。<br><br>
  <b>建议：</b>使用「至少2周期E/F」的筛选条件，可获得更多观察标的。
</div>
'''
    else:
        html += '''
<table>
<thead>
<tr>
<th class="col-core">股票代码</th>
<th class="col-core">股票简称</th>
<th class="col-core">日期</th>
<th class="col-mn1">MN1_hex</th>
<th class="col-mn1">MN1_score</th>
<th class="col-w1">W1_hex</th>
<th class="col-w1">W1_score</th>
<th class="col-d1">D1_hex</th>
<th class="col-d1">D1_score</th>
<th class="col-detail">MN1_base</th>
<th class="col-detail">MN1_trend</th>
<th class="col-detail">MN1_pos</th>
<th class="col-detail">MN1_vol</th>
<th class="col-detail">W1_base</th>
<th class="col-detail">W1_trend</th>
<th class="col-detail">W1_pos</th>
<th class="col-detail">W1_vol</th>
<th class="col-detail">D1_base</th>
<th class="col-detail">D1_trend</th>
<th class="col-detail">D1_pos</th>
<th class="col-detail">D1_vol</th>
</tr>
</thead>
<tbody>
'''
        
        for item in stocks:
            for row in item['rows']:
                date = row['时间'][:10]
                mn1 = decode_state(row['MN1state'])
                w1 = decode_state(row['W1state'])
                d1 = decode_state(row['D1state'])
                
                html += f'''
<tr>
<td class="code">{item['code']}</td>
<td class="name">{item['name']}</td>
<td class="date">{date}</td>
<td class="state-ef">{mn1['state_hex']}</td>
<td class="score">{mn1['state_score']}</td>
<td class="state-ef">{w1['state_hex']}</td>
<td class="score">{w1['state_score']}</td>
<td class="state-ef">{d1['state_hex']}</td>
<td class="score">{d1['state_score']}</td>
<td>{mn1['comp_label']}</td>
<td><span class="label {'label-niu' if mn1['trend_label'] == '牛' else ''}">{mn1['trend_label']}</span></td>
<td><span class="label {'label-tu' if mn1['position_label'] == '上突' else ''}">{mn1['position_label']}</span></td>
<td>{mn1['volatility_label']}</td>
<td>{w1['comp_label']}</td>
<td><span class="label {'label-niu' if w1['trend_label'] == '牛' else ''}">{w1['trend_label']}</span></td>
<td><span class="label {'label-tu' if w1['position_label'] == '上突' else ''}">{w1['position_label']}</span></td>
<td>{w1['volatility_label']}</td>
<td>{d1['comp_label']}</td>
<td><span class="label {'label-niu' if d1['trend_label'] == '牛' else ''}">{d1['trend_label']}</span></td>
<td><span class="label {'label-tu' if d1['position_label'] == '上突' else ''}">{d1['position_label']}</span></td>
<td>{d1['volatility_label']}</td>
</tr>
'''
        
        html += '</tbody>\n</table>\n'
    
    html += '''
</body>
</html>'''
    
    with open(output_html, 'w', encoding='utf-8') as f:
        f.write(html)


def main():
    date_str = "2026-05-20"
    input_json = f"fixtures/all_products_d1_view_6_rows_{date_str.replace('-', '')}.json"
    output_csv = f"fixtures/observation_pool_3of3_{date_str.replace('-', '')}.csv"
    output_html = f"public/observation_pool_3of3_{date_str.replace('-', '')}.html"
    
    print("=" * 60)
    print(f"P116 三周期E/F筛选 - {date_str}")
    print("=" * 60)
    
    # Filter
    stocks = filter_3of3_ef(input_json, date_str)
    
    print(f"\n筛选条件: MN1=E/F AND W1=E/F AND D1=E/F")
    print(f"匹配数量: {len(stocks)} 只")
    
    if len(stocks) == 0:
        print("\n⚠️  没有三周期同时达到E/F的股票")
        print("    这是正常现象，月线(MN1)达到E/F条件非常苛刻")
    else:
        print(f"\n前10只:")
        for item in stocks[:10]:
            print(f"  {item['code']} {item['name']}: MN1={item['mn1']} W1={item['w1']} D1={item['d1']}")
    
    # Generate outputs
    print(f"\n生成CSV: {output_csv}")
    rows = generate_csv_3of3(stocks, output_csv, date_str)
    print(f"  行数: {rows}")
    
    print(f"\n生成HTML: {output_html}")
    generate_html_3of3(stocks, output_html, date_str)
    
    print("\n" + "=" * 60)
    print("完成!")
    print("=" * 60)
    
    if len(stocks) == 0:
        print("\n建议: 使用「至少2周期E/F」条件可获得更多观察标的")
        print("  python3 scripts/generate_observation_pool.py --date 2026-05-20")


if __name__ == '__main__':
    main()
