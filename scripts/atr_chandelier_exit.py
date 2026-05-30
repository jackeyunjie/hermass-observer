#!/usr/bin/env python3
"""ATR Chandelier 策略出场管理。

出场规则：
1. 初始跟踪止损：3 × ATR(20) 从入场后最高价回撤
2. 盈利达到 4R 后收紧：1.6 × ATR(20) 从入场后最高价回撤
3. R = entry ATR(20)（入场时的 ATR 值）

策略隔离：不使用 VCP 3层止损、MA2560 MA25/MA60、Bollinger 退化 MA。
仅使用 ATR 吊灯跟踪止损。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ATRChandelierPositionState:
    """ATR Chandelier 持仓状态（用于回测引擎中的 pos.bb_state 替代）。"""
    entry_price: float
    entry_date: str
    entry_atr: float
    highest_since_entry: float = 0.0
    tightened: bool = False

    def __post_init__(self):
        if self.highest_since_entry <= 0:
            self.highest_since_entry = self.entry_price


@dataclass
class ATRChandelierExitResult:
    exit_reason: str
    exit_type: str
    pnl_pct: float
    exit_pct: float = 1.0  # 默认全部清仓


def compute_atr_from_ohlc(ohlc: list[tuple[float, float, float, float]], period: int = 20) -> float:
    """从 OHLC 序列计算 ATR(period)。

    ohlc: [(open, high, low, close), ...] 按时间升序排列。
    返回最新 ATR 值。
    """
    if len(ohlc) < 2:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(ohlc)):
        _, high, low, close = ohlc[i]
        _, _, _, prev_close = ohlc[i - 1]
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        trs.append(max(tr1, tr2, tr3))
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    return sum(trs[-period:]) / period


def compute_atr_from_closes(closes: list[float], period: int = 20) -> float:
    """从收盘价序列简化计算 ATR（用连续收盘价差的均值近似）。"""
    if len(closes) < 2:
        return 0.0
    trs = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    return sum(trs[-period:]) / period


def chandelier_exit_check(
    entry_price: float,
    entry_atr: float,
    current_close: float,
    highest_since_entry: float,
    hold_days: int,
) -> ATRChandelierExitResult | None:
    """检查 ATR 吊灯出场条件。

    Args:
        entry_price: 入场价格
        entry_atr: 入场时的 ATR(20) 值（即 R）
        current_close: 当前收盘价
        highest_since_entry: 入场后最高价
        hold_days: 持仓天数

    Returns:
        ATRChandelierExitResult 如果触发出场，否则 None。
    """
    if entry_price <= 0 or entry_atr <= 0:
        return None

    pnl_pct = (current_close - entry_price) / entry_price
    r_units = pnl_pct / (entry_atr / entry_price) if entry_atr > 0 else 0.0

    # 盈利达到 4R 后收紧止损倍数
    if r_units >= 4.0:
        atr_multiplier = 1.6
        reason_suffix = "(4R后收紧)"
    else:
        atr_multiplier = 3.0
        reason_suffix = ""

    stop_price = highest_since_entry - atr_multiplier * entry_atr

    if current_close < stop_price:
        return ATRChandelierExitResult(
            exit_reason=f"ATR吊灯止损({atr_multiplier}x){reason_suffix}",
            exit_type="trailing",
            pnl_pct=pnl_pct,
            exit_pct=1.0,
        )

    return None


def simulate_atr_chandelier_trade(
    entry_data: dict[str, Any],
    price_series: list[tuple[str, float]],
    atr_series: list[tuple[str, float]] | None = None,
    capital: float = 1_000_000,
) -> dict[str, Any]:
    """模拟 ATR Chandelier 交易从入场到出场。

    Args:
        entry_data: 必须包含 date, entry_price, entry_atr
        price_series: [(date_str, close), ...] 按时间升序
        atr_series: 可选 [(date_str, atr), ...]，用于每日更新 ATR
        capital: 账户资金（用于计算仓位）

    Returns:
        dict 包含 status, entry_date, entry_price, exit_date, exit_price,
        hold_days, exit_reason, exit_type, pnl_pct, pnl_amount
    """
    entry_date = entry_data.get("date") or entry_data.get("entry_date", "")
    entry_price = float(entry_data.get("entry_price", 0))
    entry_atr = float(entry_data.get("entry_atr", 0))

    if entry_price <= 0:
        return {"status": "invalid_entry", "entry_price": entry_price}

    # 简化仓位计算：2% 风险预算
    risk_amount = capital * 0.02
    stop_distance = 3.0 * entry_atr
    shares = int((risk_amount / stop_distance) / 100) * 100 if stop_distance > 0 else 0
    position_value = shares * entry_price

    entry_idx = next((i for i, (d, _) in enumerate(price_series) if d >= entry_date), None)
    if entry_idx is None:
        return {
            "status": "no_price_data",
            "entry_date": entry_date,
            "entry_price": entry_price,
            "shares": shares,
            "position_value": position_value,
        }

    highest_since_entry = entry_price

    for i in range(entry_idx + 1, len(price_series)):
        obs_date, close = price_series[i]
        hold_days = i - entry_idx
        highest_since_entry = max(highest_since_entry, close)

        result = chandelier_exit_check(
            entry_price=entry_price,
            entry_atr=entry_atr,
            current_close=close,
            highest_since_entry=highest_since_entry,
            hold_days=hold_days,
        )

        if result:
            pnl_amount = shares * (close - entry_price)
            return {
                "status": "exited",
                "entry_date": entry_date,
                "entry_price": entry_price,
                "exit_date": obs_date,
                "exit_price": close,
                "hold_days": hold_days,
                "exit_reason": result.exit_reason,
                "exit_type": result.exit_type,
                "pnl_pct": round(result.pnl_pct, 4),
                "pnl_amount": round(pnl_amount, 2),
                "shares": shares,
                "position_value": position_value,
            }

    last_date, last_close = price_series[-1]
    hold_days = len(price_series) - 1 - entry_idx
    pnl_pct = (last_close - entry_price) / entry_price if entry_price > 0 else 0
    return {
        "status": "holding",
        "entry_date": entry_date,
        "entry_price": entry_price,
        "last_date": last_date,
        "last_price": last_close,
        "hold_days": hold_days,
        "pnl_pct": round(pnl_pct, 4),
        "shares": shares,
        "position_value": position_value,
    }
