"""E/F signal strategy - converts state observations into trade decisions."""
from __future__ import annotations

from dataclasses import dataclass

from backtest.config import BacktestConfig


@dataclass
class Signal:
    """交易信号."""

    stock_code: str
    stock_name: str
    date: str
    ef_count: int
    mn1_hex: str
    w1_hex: str
    d1_hex: str
    entry_price: float
    stop_loss: float
    take_profit: float
    quality_score: float = 0.0
    entry_type: str = 'ef'
    strategy_components: tuple[str, ...] = ()


def compute_stop_loss(
    entry_price: float,
    sr_support: float,
    atr: float,
    config: BacktestConfig,
) -> float:
    """基于 SR 支撑位和 ATR 计算止损价."""
    atr_stop = entry_price - config.stop_loss_atr_mult * atr
    sr_stop = sr_support * 0.99  # SR 支撑下方 1%
    # 取两者中较高的 (更保守)
    stop = max(atr_stop, sr_stop)
    # 止损不超过 15%
    max_stop = entry_price * 0.85
    return max(stop, max_stop)


def compute_take_profit(
    entry_price: float,
    sr_resistance: float,
    atr: float,
    config: BacktestConfig,
) -> float:
    """基于 SR 阻力位和 ATR 计算止盈价.

    取 max(ATR目标, SR阻力) 而非 min, 给趋势留更多空间。
    最低保盈 5% (避免交易成本吃掉利润)。
    """
    atr_target = entry_price + config.take_profit_atr_mult * atr
    sr_target = sr_resistance * 0.98
    # 取两者中较高的 (让利润跑)
    target = max(atr_target, sr_target)
    # 最低保盈 5% (佣金+印花税+滑点 ~= 0.4%, 需要足够 buffer)
    min_target = entry_price * 1.05
    return max(target, min_target)


def generate_signals(
    states_by_date: dict[str, list[dict]],
    config: BacktestConfig,
) -> dict[str, list[Signal]]:
    """从每日 state 数据生成交易信号.

    Args:
        states_by_date: {date_str: [state_dict, ...]}
        config: 回测配置

    Returns:
        {date_str: [Signal, ...]} 按 quality_score 降序排列
    """
    all_signals: dict[str, list[Signal]] = {}

    for date_str, states in states_by_date.items():
        signals = []
        for s in states:
            ef_count = s.get('ef_count', 0)
            if ef_count < config.min_ef_count:
                continue

            entry_price = s.get('close', 0.0)
            if entry_price <= 0:
                continue

            sr_support = s.get('d1_sr_support', entry_price * 0.9)
            sr_resistance = s.get('d1_sr_resistance', entry_price * 1.1)
            atr = s.get('d1_atr', entry_price * 0.02)

            stop = compute_stop_loss(entry_price, sr_support, atr, config)
            target = compute_take_profit(entry_price, sr_resistance, atr, config)

            # 兼容旧 signal 包与当前 signal_module 包命名。
            try:
                from signal_module.quality_score import calc_quality_score
            except ImportError:
                from signal.quality_score import calc_quality_score
            q = calc_quality_score(s)
            score = q.total

            entry_type = 'ef'
            strategy_components: tuple[str, ...] = ()
            if config.strategy_name == 'composite':
                from backtest.strategy_signals.composite import composite_signal as _cs
                result = _cs(s, s, position_ctx=None, mode="classic")
                if result is None:
                    continue
                strategy_components = tuple(
                    k for k, v in result.get("details", {}).items()
                    if v.get("signal")
                )
                if result.get("exit_type"):
                    continue
                entry_type = result.get("entry_type") or "composite_entry"
                score = result.get("composite_confidence", 0) * 100
                if score < config.composite_score_floor:
                    continue

            # 盈亏比过滤: RR < 1.5 的信号降权
            risk = entry_price - stop
            reward = target - entry_price
            rr = reward / risk if risk > 0 else 0
            if rr < 1.0:
                score *= 0.3  # RR 太差, 大幅降权
            elif rr < 1.5:
                score *= 0.7

            # 最低质量分门槛: 低于此分数不参与
            if score < 60:
                continue

            signals.append(Signal(
                stock_code=s['stock_code'],
                stock_name=s.get('stock_name', ''),
                date=date_str,
                ef_count=ef_count,
                mn1_hex=s.get('mn1_state_hex', s.get('mn1_hex', '0')),
                w1_hex=s.get('w1_state_hex', s.get('w1_hex', '0')),
                d1_hex=s.get('d1_state_hex', s.get('d1_hex', '0')),
                entry_price=entry_price,
                stop_loss=stop,
                take_profit=target,
                quality_score=score,
                entry_type=entry_type,
                strategy_components=strategy_components,
            ))

        # 按质量分排序
        signals.sort(key=lambda x: x.quality_score, reverse=True)
        all_signals[date_str] = signals

    return all_signals


def filter_signals_by_market(
    signals: list[Signal],
    market_trend: str,
) -> list[Signal]:
    """根据大盘趋势过滤信号.

    market_trend: 'bull', 'bear', 'neutral'
    """
    if market_trend == 'bear':
        # 熊市只保留 E/F 3/3 的超强信号
        return [s for s in signals if s.ef_count >= 3]
    return signals
