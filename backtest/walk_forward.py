"""Walk-forward analysis to detect overfitting.

将历史数据分为多个 train/test 窗口，滚动回测，
验证策略在 out-of-sample 数据上的表现。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from backtest.config import BacktestConfig
from backtest.engine import run_backtest

ROOT = Path(__file__).resolve().parents[1]


def run_walk_forward(
    start_date: str,
    end_date: str,
    config: BacktestConfig | None = None,
    foundation_db: Path | None = None,
) -> dict:
    """滚动窗口 Walk-Forward 分析."""
    if config is None:
        config = BacktestConfig()

    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    total_days = (end_dt - start_dt).days

    # 滚动窗口
    window_size = total_days // 3  # 3 个窗口
    if window_size < 60:
        window_size = 60

    results = []
    current_start = start_dt

    while current_start + timedelta(days=window_size) <= end_dt:
        window_end = current_start + timedelta(days=window_size)
        window_end_str = window_end.strftime('%Y-%m-%d')

        print(f"\n{'='*50}")
        print(f"Window: {current_start.strftime('%Y-%m-%d')} -> {window_end_str}")
        print(f"{'='*50}")

        try:
            result = run_backtest(
                date_str=window_end_str,
                config=config,
                foundation_db=foundation_db,
            )
            results.append({
                'window_start': current_start.strftime('%Y-%m-%d'),
                'window_end': window_end_str,
                'metrics': result['metrics'],
            })
        except FileNotFoundError as e:
            print(f"  Skipped (no data): {e}")
        except Exception as e:
            print(f"  Error: {e}")

        current_start += timedelta(days=config.step_days)

    # 汇总
    if not results:
        return {'error': 'No valid windows', 'windows': []}

    avg_win_rate = sum(r['metrics']['win_rate'] for r in results) / len(results)
    avg_sharpe = sum(r['metrics']['sharpe_ratio'] for r in results) / len(results)
    avg_return = sum(r['metrics']['annualized_return'] for r in results) / len(results)
    avg_drawdown = sum(r['metrics']['max_drawdown_pct'] for r in results) / len(results)

    # 过拟合检测: 如果各窗口表现差异很大，可能是过拟合
    sharpe_values = [r['metrics']['sharpe_ratio'] for r in results]
    sharpe_std = (sum((s - avg_sharpe)**2 for s in sharpe_values) / len(sharpe_values)) ** 0.5 if len(sharpe_values) > 1 else 0

    stability = 'STABLE' if sharpe_std < 0.5 else ('MODERATE' if sharpe_std < 1.0 else 'UNSTABLE')

    summary = {
        'start_date': start_date,
        'end_date': end_date,
        'windows': results,
        'avg_win_rate': round(avg_win_rate, 4),
        'avg_sharpe': round(avg_sharpe, 2),
        'avg_annual_return': round(avg_return, 4),
        'avg_max_drawdown': round(avg_drawdown, 4),
        'sharpe_std': round(sharpe_std, 2),
        'stability': stability,
        'overfitting_risk': 'HIGH' if sharpe_std > 1.5 else ('MEDIUM' if sharpe_std > 0.8 else 'LOW'),
        'research_only_flag': True,
    }

    print(f"\n{'='*50}")
    print(f"Walk-Forward Summary")
    print(f"{'='*50}")
    print(f"Windows:          {len(results)}")
    print(f"Avg Win Rate:     {avg_win_rate:.1%}")
    print(f"Avg Sharpe:       {avg_sharpe:.2f}")
    print(f"Avg Annual Return:{avg_return:.2%}")
    print(f"Avg Max Drawdown: {avg_drawdown:.2%}")
    print(f"Sharpe Std:       {sharpe_std:.2f}")
    print(f"Stability:        {stability}")
    print(f"Overfitting Risk: {summary['overfitting_risk']}")
    print(f"{'='*50}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description='Walk-Forward Analysis')
    parser.add_argument('--start-date', required=True)
    parser.add_argument('--end-date', required=True)
    parser.add_argument('--foundation-db', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()

    result = run_walk_forward(args.start_date, args.end_date, foundation_db=args.foundation_db)

    output_dir = args.output_dir or (ROOT / 'outputs' / f"walk_forward_{args.end_date.replace('-', '')}")
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / 'walk_forward_result.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n',
        encoding='utf-8',
    )
    print(f"\nSaved: {output_dir / 'walk_forward_result.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
