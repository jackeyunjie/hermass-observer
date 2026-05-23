"""Backtest engine - main entry point.

Usage:
    python3 -m backtest.engine --date 2026-05-20 --lookback-days 252
    make backtest DATE=2026-05-20
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

from backtest.config import BacktestConfig, TradeRecord, DailySnapshot
from backtest.portfolio import Portfolio
from backtest.strategy import generate_signals, Signal
from backtest.metrics import calculate_metrics, compare_to_benchmark
from backtest.strategy_signals.bollinger_bandit import bollinger_bandit_exit_signal, exit_ma_period


ROOT = Path(__file__).resolve().parents[1]


def load_state_data_from_duckdb(
    foundation_db: Path,
    start_date: str,
    end_date: str,
) -> dict[str, list[dict]]:
    """从 DuckDB 加载每日 state 数据, 返回 {date: [state_dict]}."""
    conn = duckdb.connect(str(foundation_db), read_only=True)
    rows = conn.execute(f"""
        WITH bars_base AS (
            SELECT
                stock_code,
                date,
                open,
                high,
                low,
                close,
                volume,
                avg(close) OVER w20 AS ma20,
                avg(close) OVER w25 AS ma25,
                avg(close) OVER w50 AS ma50,
                avg(close) OVER w60 AS ma60,
                stddev_samp(close) OVER w50 AS std50,
                max(high) OVER w5 AS high_5d,
                min(low) OVER w5 AS low_5d,
                max(high) OVER w20 AS high_20d,
                min(low) OVER w20 AS low_20d,
                max(high) OVER w10prev AS high_10d_prev,
                avg(volume) OVER w50 AS avg_volume_50d,
                lag(close, 1) OVER w AS prev_close,
                lag(close, 30) OVER w AS close_30_ago
            FROM daily_bars
            WINDOW
                w AS (PARTITION BY stock_code ORDER BY date),
                w5 AS (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
                w20 AS (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
                w25 AS (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 24 PRECEDING AND CURRENT ROW),
                w50 AS (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
                w60 AS (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
                w10prev AS (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING)
        ),
        bars AS (
            SELECT
                *,
                ma20 AS bb_mid_20,
                ma20 + 2.0 * stddev_samp(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS bb_upper_20_2,
                ma50 + std50 AS bb_upper_50_1,
                lag(ma25, 1) OVER (PARTITION BY stock_code ORDER BY date) AS ma25_prev,
                lag(ma60, 1) OVER (PARTITION BY stock_code ORDER BY date) AS ma60_prev,
                lag(ma50 + std50, 1) OVER (PARTITION BY stock_code ORDER BY date) AS bb_upper_50_1_prev,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS ma10,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 10 PRECEDING AND CURRENT ROW) AS ma11,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS ma12,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 12 PRECEDING AND CURRENT ROW) AS ma13,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) AS ma14,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 14 PRECEDING AND CURRENT ROW) AS ma15,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 15 PRECEDING AND CURRENT ROW) AS ma16,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 16 PRECEDING AND CURRENT ROW) AS ma17,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 17 PRECEDING AND CURRENT ROW) AS ma18,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 18 PRECEDING AND CURRENT ROW) AS ma19,
                ma20,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) AS ma21,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 21 PRECEDING AND CURRENT ROW) AS ma22,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 22 PRECEDING AND CURRENT ROW) AS ma23,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS ma24,
                ma25,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 25 PRECEDING AND CURRENT ROW) AS ma26,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 26 PRECEDING AND CURRENT ROW) AS ma27,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 27 PRECEDING AND CURRENT ROW) AS ma28,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 28 PRECEDING AND CURRENT ROW) AS ma29,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS ma30,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 30 PRECEDING AND CURRENT ROW) AS ma31,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 31 PRECEDING AND CURRENT ROW) AS ma32,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 32 PRECEDING AND CURRENT ROW) AS ma33,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 33 PRECEDING AND CURRENT ROW) AS ma34,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 34 PRECEDING AND CURRENT ROW) AS ma35,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 35 PRECEDING AND CURRENT ROW) AS ma36,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 36 PRECEDING AND CURRENT ROW) AS ma37,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 37 PRECEDING AND CURRENT ROW) AS ma38,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 38 PRECEDING AND CURRENT ROW) AS ma39,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 39 PRECEDING AND CURRENT ROW) AS ma40,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 40 PRECEDING AND CURRENT ROW) AS ma41,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 41 PRECEDING AND CURRENT ROW) AS ma42,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 42 PRECEDING AND CURRENT ROW) AS ma43,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 43 PRECEDING AND CURRENT ROW) AS ma44,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 44 PRECEDING AND CURRENT ROW) AS ma45,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 45 PRECEDING AND CURRENT ROW) AS ma46,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 46 PRECEDING AND CURRENT ROW) AS ma47,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 47 PRECEDING AND CURRENT ROW) AS ma48,
                avg(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 48 PRECEDING AND CURRENT ROW) AS ma49
            FROM bars_base
        ),
        enriched AS (
            SELECT
                *,
                lag(d1_atr_ratio_pct * d1_close / 100.0, 5) OVER (PARTITION BY stock_code ORDER BY state_date) AS atr14_5d_ago,
                lag(d1_atr_ratio_pct * d1_close / 100.0, 10) OVER (PARTITION BY stock_code ORDER BY state_date) AS atr14_10d_ago
            FROM d1_perspective_state
        )
        SELECT
            s.stock_code,
            s.state_date::VARCHAR AS date,
            s.d1_close AS close,
            s.mn1_state_hex, s.w1_state_hex, s.d1_state_hex,
            s.mn1_state_score, s.w1_state_score, s.d1_state_score,
            s.ef_count,
            s.d1_sr_support, s.d1_sr_resistance, s.d1_sr_ready,
            s.mn1_sr_support, s.mn1_sr_resistance,
            s.w1_sr_support, s.w1_sr_resistance,
            s.d1_atr_ratio_pct,
            s.atr14_5d_ago,
            s.atr14_10d_ago,
            s.mn1_trend_bit, s.w1_trend_bit, s.d1_trend_bit,
            s.mn1_trend, s.w1_trend, s.d1_trend,
            s.mn1_position_bit, s.w1_position_bit, s.d1_position_bit,
            s.mn1_volatility_bit, s.w1_volatility_bit, s.d1_volatility_bit,
            b.open, b.high, b.low, b.volume,
            b.bb_mid_20, b.bb_upper_20_2, b.bb_upper_50_1, b.bb_upper_50_1_prev, b.close_30_ago,
            b.ma25, b.ma60, b.ma25_prev, b.ma60_prev,
            b.high_5d, b.low_5d, b.high_20d, b.low_20d,
            b.high_10d_prev, b.avg_volume_50d, b.prev_close,
            b.ma10, b.ma11, b.ma12, b.ma13, b.ma14, b.ma15, b.ma16, b.ma17, b.ma18, b.ma19,
            b.ma20, b.ma21, b.ma22, b.ma23, b.ma24, b.ma25, b.ma26, b.ma27, b.ma28, b.ma29,
            b.ma30, b.ma31, b.ma32, b.ma33, b.ma34, b.ma35, b.ma36, b.ma37, b.ma38, b.ma39,
            b.ma40, b.ma41, b.ma42, b.ma43, b.ma44, b.ma45, b.ma46, b.ma47, b.ma48, b.ma49,
            b.ma50
        FROM enriched s
        LEFT JOIN bars b ON b.stock_code = s.stock_code AND b.date = s.state_date
        WHERE s.state_date BETWEEN '{start_date}' AND '{end_date}'
        ORDER BY s.state_date, s.ef_count DESC, s.stock_code
    """).fetchdf()
    conn.close()

    # Group by date
    by_date: dict[str, list[dict]] = {}
    for _, row in rows.iterrows():
        d = row['date']
        if d not in by_date:
            by_date[d] = []
        by_date[d].append({
            'stock_code': row['stock_code'],
            'stock_name': '',
            'date': d,
            'close': float(row['close']) if row['close'] else 0,
            'mn1_hex': row['mn1_state_hex'],
            'w1_hex': row['w1_state_hex'],
            'd1_hex': row['d1_state_hex'],
            'mn1_state_score': int(row['mn1_state_score']) if row['mn1_state_score'] else 0,
            'w1_state_score': int(row['w1_state_score']) if row['w1_state_score'] else 0,
            'd1_state_score': int(row['d1_state_score']) if row['d1_state_score'] else 0,
            'ef_count': int(row['ef_count']) if row['ef_count'] else 0,
            'd1_sr_support': float(row['d1_sr_support']) if row['d1_sr_support'] else 0,
            'd1_sr_resistance': float(row['d1_sr_resistance']) if row['d1_sr_resistance'] else 0,
            'd1_atr': float(row['d1_atr_ratio_pct']) * float(row['close']) / 100 if row['d1_atr_ratio_pct'] and row['close'] else 0,
            'atr14_5d_ago': float(row['atr14_5d_ago']) if row['atr14_5d_ago'] else 0,
            'atr14_10d_ago': float(row['atr14_10d_ago']) if row['atr14_10d_ago'] else 0,
            'mn1_trend_bit': int(row['mn1_trend_bit']) if row['mn1_trend_bit'] is not None else 0,
            'w1_trend_bit': int(row['w1_trend_bit']) if row['w1_trend_bit'] is not None else 0,
            'd1_trend_bit': int(row['d1_trend_bit']) if row['d1_trend_bit'] is not None else 0,
            'mn1_trend_label': row['mn1_trend'] or '',
            'w1_trend_label': row['w1_trend'] or '',
            'd1_trend_label': row['d1_trend'] or '',
            'mn1_position_bit': int(row['mn1_position_bit']) if row['mn1_position_bit'] is not None else 0,
            'w1_position_bit': int(row['w1_position_bit']) if row['w1_position_bit'] is not None else 0,
            'd1_position_bit': int(row['d1_position_bit']) if row['d1_position_bit'] is not None else 0,
            'mn1_volatility_bit': int(row['mn1_volatility_bit']) if row['mn1_volatility_bit'] is not None else 0,
            'w1_volatility_bit': int(row['w1_volatility_bit']) if row['w1_volatility_bit'] is not None else 0,
            'd1_volatility_bit': int(row['d1_volatility_bit']) if row['d1_volatility_bit'] is not None else 0,
            'open': float(row['open']) if row['open'] else 0,
            'high': float(row['high']) if row['high'] else 0,
            'low': float(row['low']) if row['low'] else 0,
            'volume': float(row['volume']) if row['volume'] else 0,
            'bb_mid_20': float(row['bb_mid_20']) if row['bb_mid_20'] else 0,
            'bb_upper_20_2': float(row['bb_upper_20_2']) if row['bb_upper_20_2'] else 0,
            'bb_upper_50_1': float(row['bb_upper_50_1']) if row['bb_upper_50_1'] else 0,
            'bb_upper_50_1_prev': float(row['bb_upper_50_1_prev']) if row['bb_upper_50_1_prev'] else 0,
            'close_30_ago': float(row['close_30_ago']) if row['close_30_ago'] else 0,
            'ma25': float(row['ma25']) if row['ma25'] else 0,
            'ma60': float(row['ma60']) if row['ma60'] else 0,
            'ma25_prev': float(row['ma25_prev']) if row['ma25_prev'] else 0,
            'ma60_prev': float(row['ma60_prev']) if row['ma60_prev'] else 0,
            'high_5d': float(row['high_5d']) if row['high_5d'] else 0,
            'low_5d': float(row['low_5d']) if row['low_5d'] else 0,
            'high_20d': float(row['high_20d']) if row['high_20d'] else 0,
            'low_20d': float(row['low_20d']) if row['low_20d'] else 0,
            'high_10d_prev': float(row['high_10d_prev']) if row['high_10d_prev'] else 0,
            'avg_volume_50d': float(row['avg_volume_50d']) if row['avg_volume_50d'] else 0,
            'volume_ma_50': float(row['avg_volume_50d']) if row['avg_volume_50d'] else 0,
            'high_10d': float(row['high_10d_prev']) if row['high_10d_prev'] else 0,
            'prev_close': float(row['prev_close']) if row['prev_close'] else 0,
            'ma_by_period': {
                period: float(row[f'ma{period}']) if row[f'ma{period}'] else 0
                for period in range(10, 51)
            },
        })
    return by_date


def load_daily_prices(
    foundation_db: Path,
    start_date: str,
    end_date: str,
) -> dict[str, dict[str, float]]:
    """加载每日收盘价 {date: {stock_code: close}}."""
    conn = duckdb.connect(str(foundation_db), read_only=True)
    rows = conn.execute(f"""
        SELECT stock_code, date::VARCHAR AS date, close
        FROM daily_bars
        WHERE date BETWEEN '{start_date}' AND '{end_date}'
        ORDER BY stock_code, date
    """).fetchdf()
    conn.close()

    prices: dict[str, dict[str, float]] = {}
    for _, row in rows.iterrows():
        d = row['date']
        if d not in prices:
            prices[d] = {}
        prices[d][row['stock_code']] = float(row['close'])
    return prices


def run_backtest(
    date_str: str,
    config: BacktestConfig | None = None,
    foundation_db: Path | None = None,
) -> dict:
    """运行 E/F 策略回测.

    Returns:
        完整回测结果 dict
    """
    if config is None:
        config = BacktestConfig()
    if foundation_db is None:
        ymd = date_str.replace('-', '')
        foundation_db = ROOT / 'outputs' / f'p116_foundation_{ymd}' / 'p116_foundation.duckdb'

    if not foundation_db.exists():
        raise FileNotFoundError(
            f"Foundation DB not found: {foundation_db}\n"
            f"Run: make foundation DATE={date_str}"
        )

    # 计算回测时间范围
    end_dt = datetime.strptime(date_str, '%Y-%m-%d')
    start_dt = end_dt - timedelta(days=config.lookback_days + config.warmup_days)
    start_str = start_dt.strftime('%Y-%m-%d')

    print(f"Backtest: {start_str} -> {date_str}")
    print(f"Config: min_ef={config.min_ef_count}, max_pos={config.max_positions}, "
          f"capital={config.initial_capital:,.0f}")

    # 加载数据
    state_data = load_state_data_from_duckdb(foundation_db, start_str, date_str)
    daily_prices = load_daily_prices(foundation_db, start_str, date_str)
    all_dates = sorted(state_data.keys())

    print(f"Loaded {len(all_dates)} trading days, {sum(len(v) for v in state_data.values())} state rows")

    # 生成信号
    signals_by_date = generate_signals(state_data, config)
    state_by_date_code = {
        date: {item['stock_code']: item for item in states}
        for date, states in state_data.items()
    }

    # 计算每日市场宽度 (bull vs bear 比例)
    market_breadth: dict[str, float] = {}
    for date, states in state_data.items():
        bull = sum(1 for s in states if s.get('d1_state_score', 0) >= 8)
        bear = sum(1 for s in states if s.get('d1_state_score', 0) < 0)
        total = len(states)
        if total > 0:
            market_breadth[date] = (bull - bear) / total  # -1 to 1

    # 初始化组合
    portfolio = Portfolio(config)

    # ── 主回测循环 ──
    warmup_end_idx = min(config.warmup_days, len(all_dates))

    for i, date in enumerate(all_dates):
        prices = daily_prices.get(date, {})

        # 1. 检查止损 (立即触发, 不受最小持有天数限制)
        all_exits = portfolio.check_stops(prices)
        stop_only = {c: r for c, r in all_exits.items() if r == 'stop_loss'}
        for code, reason in stop_only.items():
            pos = portfolio.positions.get(code)
            if pos:
                hold_days = i - all_dates.index(pos.entry_date) if pos.entry_date in all_dates else 0
                portfolio.close_position(code, date, prices.get(code, pos.entry_price), reason, hold_days)

        # 2. 跟踪止损 (也需要最小持有天数)
        if config.trailing_stop:
            trailing_exits = portfolio.update_trailing_stops(prices)
            min_hold = config.hold_days_range[0]
            for code in trailing_exits:
                if code not in stop_only:
                    pos = portfolio.positions.get(code)
                    if pos:
                        hold_days = i - all_dates.index(pos.entry_date) if pos.entry_date in all_dates else 0
                        if hold_days >= min_hold:
                            portfolio.close_position(code, date, prices.get(code, pos.entry_price), 'trailing_stop', hold_days)

        # 2b. 止盈 (需要最小持有天数, 让利润发展)
        min_hold = config.hold_days_range[0]
        tp_exits = {c: r for c, r in all_exits.items() if r == 'take_profit' and c not in stop_only}
        for code, reason in tp_exits.items():
            pos = portfolio.positions.get(code)
            if pos:
                hold_days = i - all_dates.index(pos.entry_date) if pos.entry_date in all_dates else 0
                if hold_days >= min_hold:
                    portfolio.close_position(code, date, prices.get(code, pos.entry_price), reason, hold_days)

        # 2c. 布林强盗动态递减均线出场
        if config.enable_bollinger_bandit_exit:
            for code, pos in list(portfolio.positions.items()):
                if pos.entry_type != 'bb_bandit_long_entry':
                    continue
                if pos.entry_date not in all_dates:
                    continue
                hold_days = i - all_dates.index(pos.entry_date)
                if hold_days < 1:
                    continue
                state = state_by_date_code.get(date, {}).get(code, {})
                period = exit_ma_period(hold_days)
                exit_ma = state.get('ma_by_period', {}).get(period, 0)
                price = prices.get(code, pos.entry_price)
                if bollinger_bandit_exit_signal(price, exit_ma):
                    portfolio.close_position(code, date, price, f'bb_bandit_ma{period}_exit', hold_days)

        # 3. 最大持有天数平仓
        for code, pos in list(portfolio.positions.items()):
            if pos.entry_date in all_dates:
                entry_idx = all_dates.index(pos.entry_date)
                if i - entry_idx >= config.hold_days_range[1]:
                    portfolio.close_position(code, date, prices.get(code, pos.entry_price), 'max_hold', i - entry_idx)

        # 4. 新信号 (跳过预热期)
        if i >= warmup_end_idx:
            signals = signals_by_date.get(date, [])

            # 市场宽度过滤: 大盘差时只放行最优质信号
            breadth = market_breadth.get(date, 0)
            if breadth < -0.3:
                # 熊市: 只保留 quality_score > 80 的信号
                signals = [s for s in signals if s.quality_score > 80]
            elif breadth < 0:
                # 弱势: 只保留 quality_score > 70 的信号
                signals = [s for s in signals if s.quality_score > 70]

            for sig in signals:
                if not portfolio.can_open():
                    break
                if sig.stock_code in portfolio.positions:
                    continue

                # 基于 SR 简化计算止损
                price = prices.get(sig.stock_code, sig.entry_price)
                if price <= 0:
                    continue

                shares = portfolio.calc_position_size(price)
                if shares <= 0:
                    continue

                portfolio.open_position(
                    stock_code=sig.stock_code,
                    stock_name=sig.stock_name,
                    date=date,
                    price=price,
                    shares=shares,
                    stop_loss=sig.stop_loss,
                    take_profit=sig.take_profit,
                    ef_count=sig.ef_count,
                    mn1_hex=sig.mn1_hex,
                    w1_hex=sig.w1_hex,
                    d1_hex=sig.d1_hex,
                    entry_type=sig.entry_type,
                    strategy_components=sig.strategy_components,
                )

        # 5. 每日快照
        portfolio.snapshot(date, prices)

    # 强制平仓所有剩余持仓
    last_date = all_dates[-1] if all_dates else date_str
    last_prices = daily_prices.get(last_date, {})
    for code in list(portfolio.positions.keys()):
        pos = portfolio.positions[code]
        hold_days = len(all_dates)
        if pos.entry_date in all_dates:
            hold_days = all_dates.index(last_date) - all_dates.index(pos.entry_date)
        portfolio.close_position(code, last_date, last_prices.get(code, pos.entry_price), 'backtest_end', hold_days)

    # 计算绩效
    metrics = calculate_metrics(portfolio.closed_trades, portfolio.daily_snapshots, config.initial_capital)

    result = {
        'backtest_date': date_str,
        'config': {
            'strategy_name': config.strategy_name,
            'min_ef_count': config.min_ef_count,
            'max_positions': config.max_positions,
            'initial_capital': config.initial_capital,
            'commission_rate': config.commission_rate,
            'slippage_pct': config.slippage_pct,
            'stop_loss_atr_mult': config.stop_loss_atr_mult,
            'trailing_stop_pct': config.trailing_stop_pct,
        },
        'metrics': metrics.to_dict(),
        'trades': [t.to_dict() for t in portfolio.closed_trades],
        'equity_curve': [s.to_dict() for s in portfolio.daily_snapshots],
        'total_trading_days': len(all_dates),
        'warmup_days': config.warmup_days,
        'research_only_flag': True,
    }

    print(f"\n{'='*50}")
    print(f"Backtest Results")
    print(f"{'='*50}")
    print(f"Total trades:     {metrics.total_trades}")
    print(f"Win rate:         {metrics.win_rate:.1%}")
    print(f"Avg return:       {metrics.avg_return_pct:.2%}")
    print(f"Profit factor:    {metrics.profit_factor:.2f}")
    print(f"Max drawdown:     {metrics.max_drawdown_pct:.2%}")
    print(f"Sharpe ratio:     {metrics.sharpe_ratio:.2f}")
    print(f"Annual return:    {metrics.annualized_return:.2%}")
    print(f"{'='*50}")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description='E/F Strategy Backtester')
    parser.add_argument('--date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--lookback-days', type=int, default=252)
    parser.add_argument('--foundation-db', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--max-positions', type=int, default=10)
    parser.add_argument('--min-ef', type=int, default=2)
    parser.add_argument('--initial-capital', type=float, default=1_000_000)
    parser.add_argument('--strategy', choices=['ef', 'composite'], default='ef')
    args = parser.parse_args()

    config = BacktestConfig(
        lookback_days=args.lookback_days,
        max_positions=args.max_positions,
        min_ef_count=args.min_ef,
        initial_capital=args.initial_capital,
        strategy_name=args.strategy,
    )

    result = run_backtest(args.date, config, args.foundation_db)

    # 保存结果
    output_dir = args.output_dir or (ROOT / 'outputs' / f"backtest_{args.date.replace('-', '')}")
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / 'backtest_result.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n',
        encoding='utf-8',
    )
    print(f"\nSaved: {output_dir / 'backtest_result.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
