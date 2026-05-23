#!/usr/bin/env python3
"""HTML Generator for observation pool."""

from pathlib import Path
from typing import List, Any


def generate_html(
    screen_results: List[Any],
    output_path: Path,
    date_str: str,
    total_matches: int
) -> Path:
    """Generate HTML observation pool page.
    
    Args:
        screen_results: List of ScreenResult objects
        output_path: Output HTML path
        date_str: Date string for title
        total_matches: Total matching stocks
    
    Returns:
        Path to generated HTML
    """
    
    # Count signal strengths
    ultra_count = sum(1 for r in screen_results if r.ef_count == 3)
    strong_count = sum(1 for r in screen_results if r.ef_count == 2)
    
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
  .col-core {{ background: #1890ff; color: white; }}
  .col-mn1 {{ background: #722ed1; color: white; }}
  .col-w1 {{ background: #13c2c2; color: white; }}
  .col-d1 {{ background: #fa8c16; color: white; }}
  .col-detail {{ background: #8c8c8c; color: white; }}
</style>
</head>
<body>
<h1>P116 State 每日观察池 - {date_str}</h1>
<div class="summary">
  <span>筛选: <b>至少2周期E/F</b></span>
  <span>总匹配: <span class="num">{total_matches}</span></span>
  <span>超强(3/3): <span class="num">{ultra_count}</span></span>
  <span>强势(2/3): <span class="num">{strong_count}</span></span>
  <span>展示: <span class="num">{len(screen_results)}</span>只×3天</span>
</div>
<table>
<thead>
<tr>
'''

    # Headers with color coding
    header_colors = {
        'stock_code': 'col-core', 'stock_name': 'col-core', 'date': 'col-core', 'ef_count': 'col-core',
        'MN1_state_hex': 'col-mn1', 'MN1_state_score': 'col-mn1',
        'W1_state_hex': 'col-w1', 'W1_state_score': 'col-w1',
        'D1_state_hex': 'col-d1', 'D1_state_score': 'col-d1'
    }
    
    from .csv_gen import FIXED_COLUMNS, CHINESE_HEADERS
    
    for col in FIXED_COLUMNS:
        color_class = header_colors.get(col, 'col-detail')
        display = col.replace('_state_hex', '').replace('_state_score', '_score').replace('_label', '').replace('_bit', '').replace('volatility', 'vol')
        html += f'<th class="{color_class}">{display}</th>\n'
    
    html += '</tr>\n</thead>\n<tbody>\n'
    
    # Data rows
    for result in screen_results:
        for state in result.states:
            row_class = 'ef3' if result.ef_count == 3 else 'ef2'
            html += f'<tr class="{row_class}">\n'
            
            for col in FIXED_COLUMNS:
                val = _get_value(state, result, col)
                
                if col == 'stock_code':
                    html += f'<td class="code">{val}</td>\n'
                elif col == 'stock_name':
                    html += f'<td class="name">{val}</td>\n'
                elif col == 'date':
                    html += f'<td class="date">{val}</td>\n'
                elif col in ('MN1_state_hex', 'W1_state_hex', 'D1_state_hex'):
                    if val in ('E', 'F'):
                        html += f'<td class="state-ef">{val}</td>\n'
                    else:
                        html += f'<td class="state-other">{val}</td>\n'
                elif col in ('MN1_state_score', 'W1_state_score', 'D1_state_score'):
                    html += f'<td class="score">{val}</td>\n'
                elif 'label' in col:
                    label_class = _get_label_class(val)
                    html += f'<td><span class="label {label_class}">{val}</span></td>\n'
                else:
                    html += f'<td>{val}</td>\n'
            
            html += '</tr>\n'
    
    html += '''</tbody>
</table>
</body>
</html>'''
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    return output_path


def _get_value(state: dict, result: Any, col: str) -> str:
    """Get value for a column."""
    if col == 'stock_code':
        return result.stock_code
    elif col == 'stock_name':
        return result.stock_name
    elif col == 'ef_count':
        return str(result.ef_count)
    else:
        return str(state.get(col, ''))


def _get_label_class(val: str) -> str:
    """Get CSS class for label."""
    if val == '牛':
        return 'label-niu'
    elif val == '熊':
        return 'label-xiong'
    elif val == '平':
        return 'label-ping'
    elif val in ('上突', '下突'):
        return 'label-tu'
    elif val == '中':
        return 'label-zhong'
    return ''
