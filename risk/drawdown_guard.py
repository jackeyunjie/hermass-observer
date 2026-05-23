"""Drawdown guard - 回撤保护机制.

当组合回撤超过阈值时自动降仓或暂停交易。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GuardAction(Enum):
    NORMAL = 'normal'
    REDUCE = 'reduce'       # 降低仓位
    PAUSE = 'pause'         # 暂停新开仓
    LIQUIDATE = 'liquidate'  # 强制减仓


@dataclass
class DrawdownState:
    """回撤保护状态."""

    current_drawdown: float    # 当前回撤 %
    peak_equity: float
    current_equity: float
    action: GuardAction
    position_scale: float      # 仓位缩放因子 (0-1)
    message: str


def evaluate_drawdown(
    current_equity: float,
    peak_equity: float,
    daily_snapshots: list[dict] | None = None,
) -> DrawdownState:
    """评估当前回撤并决定保护动作.

    阈值:
    - < 5%:  正常交易
    - 5-10%: 仓位降至 85%
    - 10-15%: 仓位降至 60%, 警告
    - 15-20%: 暂停新开仓, 只允许平仓
    - > 20%:  强制减仓至 30%
    """
    if peak_equity <= 0:
        peak_equity = current_equity

    dd = (peak_equity - current_equity) / peak_equity

    if dd < 0.05:
        action = GuardAction.NORMAL
        scale = 1.0
        msg = f"回撤 {dd:.1%}, 正常交易"
    elif dd < 0.10:
        action = GuardAction.REDUCE
        scale = 0.85
        msg = f"回撤 {dd:.1%}, 仓位降至 85%"
    elif dd < 0.15:
        action = GuardAction.REDUCE
        scale = 0.60
        msg = f"回撤 {dd:.1%}, 仓位降至 60%, 请检查策略"
    elif dd < 0.20:
        action = GuardAction.PAUSE
        scale = 0.0
        msg = f"回撤 {dd:.1%}, 暂停新开仓!"
    else:
        action = GuardAction.LIQUIDATE
        scale = 0.0
        msg = f"回撤 {dd:.1%}, 强制减仓!"

    return DrawdownState(
        current_drawdown=dd,
        peak_equity=peak_equity,
        current_equity=current_equity,
        action=action,
        position_scale=scale,
        message=msg,
    )


def check_streak_guard(
    recent_trades: list[dict],
    max_consecutive_losses: int = 5,
) -> tuple[bool, str]:
    """连续亏损保护.

    如果连续亏损超过阈值, 暂停交易。
    """
    if len(recent_trades) < max_consecutive_losses:
        return True, ''

    # 检查最近 N 笔
    recent = recent_trades[-max_consecutive_losses:]
    all_loss = all(t.get('net_pnl', 0) <= 0 for t in recent)

    if all_loss:
        total_loss = sum(t.get('net_pnl', 0) for t in recent)
        return False, f"连续 {max_consecutive_losses} 笔亏损, 总计 {total_loss:,.0f}, 建议暂停交易"

    return True, ''


def check_daily_loss_limit(
    daily_pnl: float,
    equity: float,
    max_daily_loss_pct: float = 0.03,
) -> tuple[bool, str]:
    """单日亏损限制.

    如果单日亏损超过总资金的 N%, 停止当日交易。
    """
    daily_loss_pct = abs(min(daily_pnl, 0)) / equity if equity > 0 else 0
    if daily_loss_pct >= max_daily_loss_pct:
        return False, f"单日亏损 {daily_loss_pct:.1%} 达到限制 {max_daily_loss_pct:.0%}"
    return True, ''
