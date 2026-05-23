"""Build recommended portfolio from E/F signals.

将观察池的 E/F 筛选结果, 经过信号增强和风控过滤,
输出带止损止盈的推荐组合。

Usage:
    python3 -m recommend.build_portfolio --date 2026-05-20
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import duckdb

from signal.quality_score import rank_by_quality, calc_quality_score
from signal.sector_filter import deduplicate_sectors
from risk.stop_loss import sr_support_stop, combined_stop
from risk.take_profit import sr_resistance_target, calc_rr_ratio
from risk.position_sizer import atr_based
from risk.drawdown_guard import evaluate_drawdown, GuardAction

ROOT = Path(__file__).resolve().parents[1]


def load_candidates(foundation_db: Path, date_str: str) -> list[dict]:
    """从 DuckDB 加载 E/F 候选."""
    conn = duckdb.connect(str(foundation_db), read_only=True)
    rows = conn.execute(f"""
        SELECT
            stock_code, state_date::VARCHAR AS date,
            d1_close AS close,
            mn1_state_hex, w1_state_hex, d1_state_hex,
            mn1_state_score, w1_state_score, d1_state_score,
            ef_count,
            mn1_sr_support, mn1_sr_resistance,
            w1_sr_support, w1_sr_resistance,
            d1_sr_support, d1_sr_resistance,
            d1_atr_ratio_pct,
            mn1_base, mn1_trend_bit, mn1_position_bit, mn1_volatility_bit,
            w1_base, w1_trend_bit, w1_position_bit, w1_volatility_bit,
            d1_base, d1_trend_bit, d1_position_bit, d1_volatility_bit
        FROM d1_perspective_state
        WHERE state_date = '{date_str}'
          AND ef_count >= 2
        ORDER BY ef_count DESC, d1_state_score DESC
        LIMIT 200
    """).fetchdf()
    conn.close()

    candidates = []
    for _, r in rows.iterrows():
        close = float(r['close']) if r['close'] else 0
        atr_val = float(r['d1_atr_ratio_pct']) * close / 100 if r['d1_atr_ratio_pct'] and close else close * 0.02

        candidates.append({
            'stock_code': r['stock_code'],
            'stock_name': '',
            'date': r['date'],
            'close': close,
            'ef_count': int(r['ef_count']),
            'mn1_hex': r['mn1_state_hex'],
            'w1_hex': r['w1_state_hex'],
            'd1_hex': r['d1_state_hex'],
            'mn1_state_score': int(r['mn1_state_score']),
            'w1_state_score': int(r['w1_state_score']),
            'd1_state_score': int(r['d1_state_score']),
            'mn1_trend_bit': int(r['mn1_trend_bit']),
            'w1_trend_bit': int(r['w1_trend_bit']),
            'd1_trend_bit': int(r['d1_trend_bit']),
            'mn1_position_bit': int(r['mn1_position_bit']),
            'w1_position_bit': int(r['w1_position_bit']),
            'd1_position_bit': int(r['d1_position_bit']),
            'mn1_volatility_bit': int(r['mn1_volatility_bit']),
            'w1_volatility_bit': int(r['w1_volatility_bit']),
            'd1_volatility_bit': int(r['d1_volatility_bit']),
            'mn1_sr_support': float(r['mn1_sr_support']) if r['mn1_sr_support'] else 0,
            'mn1_sr_resistance': float(r['mn1_sr_resistance']) if r['mn1_sr_resistance'] else 0,
            'w1_sr_support': float(r['w1_sr_support']) if r['w1_sr_support'] else 0,
            'w1_sr_resistance': float(r['w1_sr_resistance']) if r['w1_sr_resistance'] else 0,
            'd1_sr_support': float(r['d1_sr_support']) if r['d1_sr_support'] else 0,
            'd1_sr_resistance': float(r['d1_sr_resistance']) if r['d1_sr_resistance'] else 0,
            'atr': atr_val,
            'sector': '',
            'volume_ratio': 1.0,
        })
    return candidates


def build_portfolio(
    date_str: str,
    foundation_db: Path | None = None,
    equity: float = 1_000_000,
    max_positions: int = 10,
    recent_drawdown: float = 0.0,
) -> dict:
    """构建推荐组合."""
    if foundation_db is None:
        ymd = date_str.replace('-', '')
        foundation_db = ROOT / 'outputs' / f'p116_foundation_{ymd}' / 'p116_foundation.duckdb'

    if not foundation_db.exists():
        raise FileNotFoundError(f"Foundation DB not found: {foundation_db}")

    # 1. 加载候选
    candidates = load_candidates(foundation_db, date_str)
    print(f"Loaded {len(candidates)} E/F candidates for {date_str}")

    if not candidates:
        return {'date': date_str, 'positions': [], 'skipped': True, 'reason': 'no candidates'}

    # 2. 回撤保护
    dd_state = evaluate_drawdown(equity, equity / (1 - recent_drawdown) if recent_drawdown < 1 else equity)
    if dd_state.action == GuardAction.PAUSE:
        return {
            'date': date_str, 'positions': [], 'skipped': True,
            'reason': dd_state.message, 'drawdown_state': dd_state.current_drawdown,
        }

    # 3. 质量评分
    ranked = rank_by_quality(candidates)

    # 4. 行业去重
    deduped = deduplicate_sectors(ranked, max_per_sector=3)

    # 5. 构建组合
    positions = []
    for s in deduped[:max_positions]:
        close = s['close']
        sr_support = s.get('d1_sr_support', close * 0.9)
        sr_resistance = s.get('d1_sr_resistance', close * 1.1)
        atr_val = s.get('atr', close * 0.02)

        # 止损
        sl = combined_stop(close, sr_support, atr_val)
        # 止盈
        tp = sr_resistance_target(close, sr_resistance)
        # 盈亏比
        rr = calc_rr_ratio(tp.reward_pct, sl.distance_pct)

        # 仓位
        position_size = atr_based(equity * dd_state.position_scale, close, atr_val)

        positions.append({
            'stock_code': s['stock_code'],
            'stock_name': s.get('stock_name', ''),
            'entry_price': round(close, 3),
            'shares': position_size.shares,
            'amount': round(position_size.amount, 2),
            'position_pct': round(position_size.risk_pct, 4),
            'stop_loss': sl.stop_price,
            'stop_loss_method': sl.method,
            'stop_loss_distance': sl.distance_pct,
            'take_profit': tp.target_price,
            'take_profit_method': tp.method,
            'reward_pct': tp.reward_pct,
            'rr_ratio': rr,
            'ef_count': s['ef_count'],
            'mn1_hex': s['mn1_hex'],
            'w1_hex': s['w1_hex'],
            'd1_hex': s['d1_hex'],
            'quality_score': s.get('quality_score', 0),
            'quality_grade': s.get('quality_grade', ''),
            'quality_breakdown': s.get('quality_breakdown', {}),
        })

    total_amount = sum(p['amount'] for p in positions)

    portfolio = {
        'date': date_str,
        'generated_at': datetime.now().isoformat(),
        'total_equity': equity,
        'total_invested': round(total_amount, 2),
        'cash_remaining': round(equity - total_amount, 2),
        'positions_count': len(positions),
        'positions': positions,
        'drawdown_state': {
            'current_drawdown': round(dd_state.current_drawdown, 4),
            'action': dd_state.action.value,
            'position_scale': dd_state.position_scale,
            'message': dd_state.message,
        },
        'research_only_flag': True,
    }

    print(f"\nRecommended portfolio: {len(positions)} positions")
    print(f"Invested: {total_amount:,.0f} / {equity:,.0f}")
    for p in positions:
        print(f"  {p['stock_code']:>8s}  EF={p['ef_count']}  Q={p['quality_score']:.0f} "
              f"  SL={p['stop_loss']:.2f}  TP={p['take_profit']:.2f}  RR={p['rr_ratio']:.1f}")

    return portfolio


def main() -> int:
    parser = argparse.ArgumentParser(description='Build Recommended Portfolio')
    parser.add_argument('--date', required=True)
    parser.add_argument('--foundation-db', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--equity', type=float, default=1_000_000)
    parser.add_argument('--max-positions', type=int, default=10)
    args = parser.parse_args()

    portfolio = build_portfolio(
        date_str=args.date,
        foundation_db=args.foundation_db,
        equity=args.equity,
        max_positions=args.max_positions,
    )

    output_dir = args.output_dir or (ROOT / 'outputs' / f"recommend_{args.date.replace('-', '')}")
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / 'portfolio.json'
    out_path.write_text(json.dumps(portfolio, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
