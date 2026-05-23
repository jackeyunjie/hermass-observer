"""Backtest performance metrics."""
from __future__ import annotations

import math
from dataclasses import dataclass

from backtest.config import TradeRecord, DailySnapshot


@dataclass
class PerformanceMetrics:
    """回测绩效指标."""

    # 基础
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0

    # 收益
    total_net_pnl: float = 0.0
    total_return_pct: float = 0.0
    avg_return_pct: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    payoff_ratio: float = 0.0  # 盈亏比

    # 风险
    max_drawdown_pct: float = 0.0
    max_drawdown_duration: int = 0  # 最大回撤持续天数
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0

    # 持仓
    avg_hold_days: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0

    # 退出原因分布
    exit_reasons: dict[str, int] = None

    # 年化
    annualized_return: float = 0.0
    annualized_volatility: float = 0.0

    def to_dict(self) -> dict:
        return {
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': round(self.win_rate, 4),
            'total_net_pnl': round(self.total_net_pnl, 2),
            'total_return_pct': round(self.total_return_pct, 4),
            'avg_return_pct': round(self.avg_return_pct, 4),
            'avg_win_pct': round(self.avg_win_pct, 4),
            'avg_loss_pct': round(self.avg_loss_pct, 4),
            'profit_factor': round(self.profit_factor, 2),
            'payoff_ratio': round(self.payoff_ratio, 2),
            'max_drawdown_pct': round(self.max_drawdown_pct, 4),
            'max_drawdown_duration': self.max_drawdown_duration,
            'sharpe_ratio': round(self.sharpe_ratio, 2),
            'sortino_ratio': round(self.sortino_ratio, 2),
            'calmar_ratio': round(self.calmar_ratio, 2),
            'avg_hold_days': round(self.avg_hold_days, 1),
            'max_consecutive_wins': self.max_consecutive_wins,
            'max_consecutive_losses': self.max_consecutive_losses,
            'exit_reasons': self.exit_reasons or {},
            'annualized_return': round(self.annualized_return, 4),
            'annualized_volatility': round(self.annualized_volatility, 4),
        }


def calculate_metrics(
    trades: list[TradeRecord],
    snapshots: list[DailySnapshot],
    initial_capital: float,
    risk_free_rate: float = 0.02,
) -> PerformanceMetrics:
    """从交易记录和每日快照计算完整绩效指标."""
    m = PerformanceMetrics()

    if not trades:
        return m

    # ── 基础统计 ──
    m.total_trades = len(trades)
    returns = [t.return_pct for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    m.winning_trades = len(wins)
    m.losing_trades = len(losses)
    m.win_rate = m.winning_trades / m.total_trades if m.total_trades else 0

    # ── 收益 ──
    m.total_net_pnl = sum(t.net_pnl for t in trades)
    m.total_return_pct = m.total_net_pnl / initial_capital
    m.avg_return_pct = sum(returns) / len(returns) if returns else 0
    m.avg_win_pct = sum(wins) / len(wins) if wins else 0
    m.avg_loss_pct = sum(losses) / len(losses) if losses else 0

    gross_profit = sum(t.net_pnl for t in trades if t.net_pnl > 0)
    gross_loss = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
    m.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    m.payoff_ratio = abs(m.avg_win_pct / m.avg_loss_pct) if m.avg_loss_pct != 0 else float('inf')

    # ── 持仓 ──
    m.avg_hold_days = sum(t.hold_days for t in trades) / len(trades)

    # 连续胜负
    streak_w, streak_l = 0, 0
    max_w, max_l = 0, 0
    for t in trades:
        if t.net_pnl > 0:
            streak_w += 1
            streak_l = 0
        else:
            streak_l += 1
            streak_w = 0
        max_w = max(max_w, streak_w)
        max_l = max(max_l, streak_l)
    m.max_consecutive_wins = max_w
    m.max_consecutive_losses = max_l

    # 退出原因
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    m.exit_reasons = reasons

    # ── 每日快照指标 ──
    if snapshots and len(snapshots) > 1:
        daily_rets = [s.daily_return_pct for s in snapshots if s.daily_return_pct != 0]

        # 最大回撤
        m.max_drawdown_pct = max(s.drawdown_pct for s in snapshots)

        # 最大回撤持续天数
        in_dd = False
        dd_start = 0
        dd_duration = 0
        for i, s in enumerate(snapshots):
            if s.drawdown_pct > 0.001:
                if not in_dd:
                    dd_start = i
                    in_dd = True
                dd_duration = max(dd_duration, i - dd_start)
            else:
                in_dd = False
        m.max_drawdown_duration = dd_duration

        # 夏普比
        if daily_rets and len(daily_rets) > 20:
            mean_ret = sum(daily_rets) / len(daily_rets)
            var = sum((r - mean_ret) ** 2 for r in daily_rets) / (len(daily_rets) - 1)
            std = math.sqrt(var) if var > 0 else 0.0001
            daily_rf = risk_free_rate / 252
            m.sharpe_ratio = (mean_ret - daily_rf) / std * math.sqrt(252)

            # Sortino (只看下行波动)
            downside_rets = [r for r in daily_rets if r < daily_rf]
            if downside_rets:
                down_var = sum((r - daily_rf) ** 2 for r in downside_rets) / len(daily_rets)
                down_std = math.sqrt(down_var) if down_var > 0 else 0.0001
                m.sortino_ratio = (mean_ret - daily_rf) / down_std * math.sqrt(252)

            # 年化
            total_days = len(snapshots)
            final_equity = snapshots[-1].total_equity
            m.annualized_return = (final_equity / initial_capital) ** (252 / max(total_days, 1)) - 1
            m.annualized_volatility = std * math.sqrt(252)

            # Calmar
            m.calmar_ratio = m.annualized_return / m.max_drawdown_pct if m.max_drawdown_pct > 0 else 0

    return m


def compare_to_benchmark(
    snapshots: list[DailySnapshot],
    benchmark_returns: list[float],
) -> dict:
    """与基准对比."""
    if not snapshots or len(snapshots) < 2:
        return {}

    strategy_rets = [s.daily_return_pct for s in snapshots[1:]]

    # 对齐长度
    n = min(len(strategy_rets), len(benchmark_returns))
    strategy_rets = strategy_rets[:n]
    benchmark_returns = benchmark_returns[:n]

    # 超额收益
    excess = [s - b for s, b in zip(strategy_rets, benchmark_returns)]
    cumulative_excess = 1.0
    for e in excess:
        cumulative_excess *= (1 + e)

    # 信息比
    if len(excess) > 20:
        mean_ex = sum(excess) / len(excess)
        var_ex = sum((e - mean_ex) ** 2 for e in excess) / (len(excess) - 1)
        std_ex = math.sqrt(var_ex) if var_ex > 0 else 0.0001
        info_ratio = mean_ex / std_ex * math.sqrt(252)
    else:
        info_ratio = 0.0

    return {
        'cumulative_excess_return': round(cumulative_excess - 1, 4),
        'information_ratio': round(info_ratio, 2),
        'tracking_error': round(math.sqrt(
            sum((e - sum(excess)/len(excess))**2 for e in excess) / max(len(excess)-1, 1)
        ) * math.sqrt(252), 4) if excess else 0,
    }
