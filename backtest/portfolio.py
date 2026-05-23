"""Virtual portfolio for backtesting."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from backtest.config import BacktestConfig, TradeRecord, DailySnapshot


@dataclass
class Position:
    """单个持仓."""

    stock_code: str
    stock_name: str
    entry_date: str
    entry_price: float
    shares: int
    stop_loss: float
    take_profit: float
    highest_since_entry: float = 0.0

    # 信号信息
    ef_count: int = 0
    mn1_hex: str = ''
    w1_hex: str = ''
    d1_hex: str = ''
    entry_type: str = ''
    strategy_components: tuple[str, ...] = ()

    @property
    def cost(self) -> float:
        return self.entry_price * self.shares

    def market_value(self, current_price: float) -> float:
        return current_price * self.shares

    def unrealized_pnl(self, current_price: float) -> float:
        return (current_price - self.entry_price) * self.shares

    def return_pct(self, current_price: float) -> float:
        if self.entry_price == 0:
            return 0.0
        return (current_price - self.entry_price) / self.entry_price


class Portfolio:
    """虚拟投资组合管理."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.cash = config.initial_capital
        self.positions: dict[str, Position] = {}
        self.closed_trades: list[TradeRecord] = []
        self.daily_snapshots: list[DailySnapshot] = []
        self.peak_equity = config.initial_capital

    @property
    def position_count(self) -> int:
        return len(self.positions)

    def market_value(self, prices: dict[str, float]) -> float:
        total = 0.0
        for code, pos in self.positions.items():
            price = prices.get(code, pos.entry_price)
            total += pos.market_value(price)
        return total

    def total_equity(self, prices: dict[str, float]) -> float:
        return self.cash + self.market_value(prices)

    def can_open(self) -> bool:
        return self.position_count < self.config.max_positions

    def calc_position_size(self, price: float, atr: float = 0.0) -> int:
        """计算可买股数 (A股100股整数倍)."""
        max_amount = self.cash * self.config.max_single_pct
        # 至少留够佣金
        max_amount *= 0.995
        shares = int(max_amount / price / 100) * 100
        return max(shares, 0)

    def open_position(
        self,
        stock_code: str,
        stock_name: str,
        date: str,
        price: float,
        shares: int,
        stop_loss: float,
        take_profit: float,
        ef_count: int = 0,
        mn1_hex: str = '',
        w1_hex: str = '',
        d1_hex: str = '',
        entry_type: str = '',
        strategy_components: tuple[str, ...] = (),
    ) -> Optional[Position]:
        """开仓."""
        if not self.can_open():
            return None
        if stock_code in self.positions:
            return None
        if shares <= 0:
            return None

        # 加滑点
        actual_price = price * (1 + self.config.slippage_pct)
        cost = actual_price * shares
        commission = max(cost * self.config.commission_rate, 5.0)

        total_cost = cost + commission
        if total_cost > self.cash:
            # 减少股数
            shares = int((self.cash - 5) / actual_price / 100) * 100
            if shares <= 0:
                return None
            cost = actual_price * shares
            commission = max(cost * self.config.commission_rate, 5.0)
            total_cost = cost + commission

        self.cash -= total_cost

        pos = Position(
            stock_code=stock_code,
            stock_name=stock_name,
            entry_date=date,
            entry_price=actual_price,
            shares=shares,
            stop_loss=stop_loss,
            take_profit=take_profit,
            highest_since_entry=actual_price,
            ef_count=ef_count,
            mn1_hex=mn1_hex,
            w1_hex=w1_hex,
            d1_hex=d1_hex,
            entry_type=entry_type,
            strategy_components=strategy_components,
        )
        self.positions[stock_code] = pos
        return pos

    def close_position(
        self,
        stock_code: str,
        date: str,
        exit_price: float,
        exit_reason: str = 'signal_exit',
        hold_days: int = 0,
    ) -> Optional[TradeRecord]:
        """平仓."""
        pos = self.positions.pop(stock_code, None)
        if pos is None:
            return None

        # 卖出滑点
        actual_price = exit_price * (1 - self.config.slippage_pct)
        proceeds = actual_price * pos.shares
        commission = max(proceeds * self.config.commission_rate, 5.0)
        stamp_tax = proceeds * self.config.stamp_tax_rate

        net_proceeds = proceeds - commission - stamp_tax
        self.cash += net_proceeds

        gross_pnl = (actual_price - pos.entry_price) * pos.shares
        net_pnl = gross_pnl - commission - stamp_tax - max(pos.cost * self.config.commission_rate, 5.0)
        return_pct = (actual_price / pos.entry_price - 1) if pos.entry_price > 0 else 0.0

        trade = TradeRecord(
            stock_code=stock_code,
            stock_name=pos.stock_name,
            entry_date=pos.entry_date,
            exit_date=date,
            entry_price=pos.entry_price,
            exit_price=actual_price,
            shares=pos.shares,
            direction='long',
            ef_count=pos.ef_count,
            mn1_hex=pos.mn1_hex,
            w1_hex=pos.w1_hex,
            d1_hex=pos.d1_hex,
            entry_type=pos.entry_type,
            strategy_components=pos.strategy_components,
            stop_loss_price=pos.stop_loss,
            take_profit_price=pos.take_profit,
            exit_reason=exit_reason,
            gross_pnl=gross_pnl,
            commission=commission + max(pos.cost * self.config.commission_rate, 5.0),
            stamp_tax=stamp_tax,
            net_pnl=net_pnl,
            return_pct=return_pct,
            hold_days=hold_days,
        )
        self.closed_trades.append(trade)
        return trade

    def snapshot(self, date: str, prices: dict[str, float]) -> DailySnapshot:
        """生成每日快照."""
        mv = self.market_value(prices)
        equity = self.cash + mv
        if equity > self.peak_equity:
            self.peak_equity = equity
        dd = (self.peak_equity - equity) / self.peak_equity if self.peak_equity > 0 else 0.0

        daily_ret = 0.0
        if self.daily_snapshots:
            prev = self.daily_snapshots[-1]
            if prev.total_equity > 0:
                daily_ret = (equity - prev.total_equity) / prev.total_equity

        snap = DailySnapshot(
            date=date,
            cash=self.cash,
            market_value=mv,
            total_equity=equity,
            positions_count=self.position_count,
            drawdown_pct=dd,
            daily_return_pct=daily_ret,
        )
        self.daily_snapshots.append(snap)
        return snap

    def update_trailing_stops(self, prices: dict[str, float]) -> list[str]:
        """更新跟踪止损, 返回触发止损的股票代码列表."""
        triggered = []
        for code, pos in list(self.positions.items()):
            price = prices.get(code, pos.entry_price)
            if price > pos.highest_since_entry:
                pos.highest_since_entry = price
            # 跟踪止损: 从最高点回撤超过阈值
            if pos.highest_since_entry > pos.entry_price:
                trailing_stop = pos.highest_since_entry * (1 - self.config.trailing_stop_pct)
                if trailing_stop > pos.stop_loss:
                    pos.stop_loss = trailing_stop
            if price <= pos.stop_loss:
                triggered.append(code)
        return triggered

    def check_stops(self, prices: dict[str, float]) -> dict[str, str]:
        """检查止损止盈, 返回 {stock_code: exit_reason}."""
        exits = {}
        for code, pos in self.positions.items():
            price = prices.get(code, pos.entry_price)
            if price <= pos.stop_loss:
                exits[code] = 'stop_loss'
            elif price >= pos.take_profit:
                exits[code] = 'take_profit'
        return exits
