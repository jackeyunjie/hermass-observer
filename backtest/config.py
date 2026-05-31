"""Backtest configuration."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BacktestConfig:
    """回测参数配置."""

    # 信号参数
    min_ef_count: int = 2            # 最低 E/F 周期数
    max_positions: int = 20          # 最大同时持仓数
    days_per_stock: int = 3          # 每只股票展示天数

    # 资金管理
    initial_capital: float = 1_000_000.0   # 初始资金
    max_single_pct: float = 0.05     # 单只最大仓位 5% (降低集中度)
    max_sector_pct: float = 0.30     # 同行业最大仓位 30%
    commission_rate: float = 0.0003  # 佣金费率 (万三)
    stamp_tax_rate: float = 0.0005   # 印花税 (卖出千分之五)
    slippage_pct: float = 0.001      # 滑点 0.1%

    # 止损止盈
    stop_loss_atr_mult: float = 2.0  # 止损 = SR支撑 - 2*ATR
    take_profit_atr_mult: float = 4.0  # 止盈 = 入场 + 4*ATR (更宽)
    trailing_stop: bool = True       # 是否启用跟踪止损
    trailing_stop_pct: float = 0.10  # 跟踪止损回撤 10% (更宽松)

    # 持仓周期
    hold_days_range: tuple[int, int] = (5, 30)  # 最少持有5天, 最多30天

    # 信号过滤
    require_volume_confirm: bool = True   # 突破需要放量确认
    volume_ratio_threshold: float = 1.5   # 量比阈值
    require_trend_align: bool = False     # 是否要求大盘趋势一致
    strategy_name: str = "ef"             # ef | vcp | ma2560 | bollinger_bandit | composite
    composite_score_floor: float = 60.0   # 复合策略最低原始质量分
    enable_bollinger_bandit_exit: bool = True

    # 回测时间
    lookback_days: int = 252         # 回测历史天数 (一年)
    warmup_days: int = 60            # 预热期 (不交易)

    # Walk-forward
    train_ratio: float = 0.7         # 训练集比例
    step_days: int = 21              # 滚动步长 (月度)


@dataclass
class TradeRecord:
    """单笔交易记录."""

    stock_code: str
    stock_name: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    direction: str  # 'long' only for A-share

    # 信号信息
    ef_count: int = 0
    mn1_hex: str = ''
    w1_hex: str = ''
    d1_hex: str = ''
    entry_type: str = ''
    strategy_components: tuple[str, ...] = field(default_factory=tuple)

    # 风控
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    exit_reason: str = ''  # 'signal_exit', 'stop_loss', 'take_profit', 'max_hold', 'trailing_stop'

    # 成果
    gross_pnl: float = 0.0
    commission: float = 0.0
    stamp_tax: float = 0.0
    net_pnl: float = 0.0
    return_pct: float = 0.0
    hold_days: int = 0

    def to_dict(self) -> dict:
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'entry_date': self.entry_date,
            'exit_date': self.exit_date,
            'entry_price': round(self.entry_price, 3),
            'exit_price': round(self.exit_price, 3),
            'shares': self.shares,
            'stop_loss_price': round(self.stop_loss_price, 3),
            'take_profit_price': round(self.take_profit_price, 3),
            'exit_reason': self.exit_reason,
            'ef_count': self.ef_count,
            'mn1_hex': self.mn1_hex,
            'w1_hex': self.w1_hex,
            'd1_hex': self.d1_hex,
            'entry_type': self.entry_type,
            'strategy_components': list(self.strategy_components),
            'gross_pnl': round(self.gross_pnl, 2),
            'commission': round(self.commission, 2),
            'stamp_tax': round(self.stamp_tax, 2),
            'net_pnl': round(self.net_pnl, 2),
            'return_pct': round(self.return_pct, 4),
            'hold_days': self.hold_days,
        }


@dataclass
class DailySnapshot:
    """每日账户快照."""

    date: str
    cash: float
    market_value: float
    total_equity: float
    positions_count: int
    drawdown_pct: float = 0.0
    daily_return_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            'date': self.date,
            'cash': round(self.cash, 2),
            'market_value': round(self.market_value, 2),
            'total_equity': round(self.total_equity, 2),
            'positions_count': self.positions_count,
            'drawdown_pct': round(self.drawdown_pct, 4),
            'daily_return_pct': round(self.daily_return_pct, 4),
        }
