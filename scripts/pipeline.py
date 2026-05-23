#!/usr/bin/env python3
"""P116 Observer Pipeline - Main entry point.

Usage:
    python3 scripts/pipeline.py --date 2026-05-20
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

# Import our modules
import sys
sys.path.insert(0, str(Path(__file__).parent))

from state_calc.p116_core import decode_state_hex
from filter.ef_screener import screen_stocks, count_ef_states
from output.csv_gen import generate_csv
from output.html_gen import generate_html


def _state_to_dict(prefix: str, state_hex: str) -> dict:
    state = decode_state_hex(state_hex)
    return {
        f'{prefix}_hex': state.hex,
        f'{prefix}_score': state.score,
        f'{prefix}_base': state.base,
        f'{prefix}_trend_bit': state.trend_bit,
        f'{prefix}_position_bit': state.position_bit,
        f'{prefix}_volatility_bit': state.volatility_bit,
        f'{prefix}_comp_label': state.comp_label,
        f'{prefix}_trend_label': state.trend_label,
        f'{prefix}_position_label': state.position_label,
        f'{prefix}_volatility_label': state.volatility_label,
    }


def load_existing_d1_view_states(date_str: str) -> tuple[list[dict], int]:
    """Load already computed D1-view rows and adapt them to the output pipeline.

    This keeps the executable pipeline from overwriting deliverables with empty
    placeholder data. Full MT4+SR recomputation should feed the same state dict
    shape when that data path is wired in.
    """
    root = Path(__file__).parent.parent
    ymd = date_str.replace('-', '')
    input_json = root / 'fixtures' / f'all_products_d1_view_6_rows_{ymd}.json'
    if not input_json.exists():
        raise FileNotFoundError(
            f"missing D1 view fixture: {input_json}; full MT4 recomputation is not wired into pipeline.py yet"
        )

    data = json.loads(input_json.read_text(encoding='utf-8'))
    all_states = []
    seen_latest_symbols = set()

    for row in data.get('rows', []):
        symbol = row['品种']
        parts = symbol.split(' ', 1)
        code = parts[0]
        name = parts[1] if len(parts) > 1 else ''
        state = {
            'stock_code': code,
            'stock_name': name,
            'date': row['时间'][:10],
        }
        state.update(_state_to_dict('MN1', row.get('MN1state') or '0'))
        state.update(_state_to_dict('W1', row.get('W1state') or '0'))
        state.update(_state_to_dict('D1', row.get('D1state') or '0'))
        all_states.append(state)
        seen_latest_symbols.add(code)

    return all_states, len(seen_latest_symbols)


def run_pipeline(date_str: str, data_source: str = 'fixture'):
    """Run the full P116 pipeline.
    
    Args:
        date_str: Date in format YYYY-MM-DD
        data_source: 'file' or 'api'
    """
    print(f"【Research-Only】本结果仅为技术状态观察，不构成任何投资建议")
    print(f"\n{'='*60}")
    print(f"P116 Observer Pipeline - {date_str}")
    print(f"{'='*60}")
    
    # 1. Load data
    print("\n[1/4] Loading data...")
    
    if data_source == 'fixture':
        all_states, symbol_count = load_existing_d1_view_states(date_str)
        print(f"  Loaded {symbol_count} symbols from D1-view fixture")
    else:
        raise NotImplementedError("full MT4+SR recomputation is not wired into pipeline.py yet")
    
    # 2. Calculate states
    print("\n[2/4] Calculating D1 perspective states...")
    print("  Using precomputed fixture states; full MT4 recomputation pending")
    
    # 3. Screen stocks
    print("\n[3/4] Screening for E/F conditions...")
    all_screened = screen_stocks(all_states, min_ef=2, max_results=10_000)
    screened = all_screened[:100]
    print(f"  Found {len(all_screened)} matching stocks")
    
    # Count signal strengths
    ultra = sum(1 for r in screened if r.ef_count == 3)
    strong = sum(1 for r in screened if r.ef_count == 2)
    print(f"  Ultra-strong (3/3): {ultra}")
    print(f"  Strong (2/3): {strong}")
    
    # 4. Generate outputs
    print("\n[4/4] Generating outputs...")
    
    # CSV
    csv_path = Path(__file__).parent.parent / 'fixtures' / f'observation_pool_{date_str.replace("-", "")}.csv'
    csv_path.parent.mkdir(exist_ok=True)
    generate_csv(screened, csv_path)
    print(f"  CSV: {csv_path}")
    
    # HTML
    html_path = Path(__file__).parent.parent / 'public' / f'observation_pool_{date_str.replace("-", "")}.html'
    html_path.parent.mkdir(exist_ok=True)
    generate_html(screened, html_path, date_str, len(all_screened))
    print(f"  HTML: {html_path}")
    
    # JSON
    json_path = Path(__file__).parent.parent / 'fixtures' / f'observation_pool_{date_str.replace("-", "")}.json'
    output_data = {
        'date': date_str,
        'generated_at': datetime.now().isoformat(),
        'total_matches': len(all_screened),
        'ultra_strong': ultra,
        'strong': strong,
        'stocks': [
            {
                'code': r.stock_code,
                'name': r.stock_name,
                'ef_count': r.ef_count,
                'states': r.states
            }
            for r in screened
        ]
    }
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"  JSON: {json_path}")
    
    print(f"\n{'='*60}")
    print("Pipeline complete!")
    print(f"{'='*60}")
    
    return {
        'csv': csv_path,
        'html': html_path,
        'json': json_path,
        'screened': screened
    }


def main():
    parser = argparse.ArgumentParser(description='P116 Observer Pipeline')
    parser.add_argument('--date', required=True, help='Date in YYYY-MM-DD format')
    parser.add_argument('--source', choices=['fixture', 'recompute'], default='fixture',
                       help='Data source: fixture or recompute')
    args = parser.parse_args()
    
    run_pipeline(args.date, args.source)


if __name__ == '__main__':
    main()
