#!/usr/bin/env python3
"""A股四策略独立回测引擎（支持杠杆）— 高性能优化版

优化项：
  1. Numba JIT 加速核心信号扫描循环
  2. multiprocessing Pool 四策略并行
  3. DuckDB 单次连接 + SQL 预聚合
  4. 技术指标向量化预计算，避免逐日重复计算

对 VCP、2560、布林强盗、ATR吊灯四个策略分别在 A 股上进行独立回测，
支持 1.6 倍杠杆（或任意杠杆倍数），产出分策略绩效报告。

使用示例:
    python3 scripts/simulate_historical_trading.py \
        --strategy vcp \
        --start-date 2023-05-22 \
        --end-date 2026-05-22 \
        --initial-capital 1000000 \
        --leverage 1.6 \
        --max-positions 8

"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from numba import njit, prange

# ---------------------------------------------------------------------------
# 把项目根目录加入 sys.path
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.strategy_signals.vcp import vcp_signal
from backtest.strategy_signals.ma2560 import ma2560_signal
from backtest.strategy_signals.bollinger_bandit import (
    bollinger_bandit_signal,
    bollinger_bandit_exit_signal,
    exit_ma_period,
)
from backtest.strategy_signals.atr_chandelier import atr_chandelier_signal
from scripts.position_sizing import calculate_dynamic_position
from scripts.vcp_exit_manager import (
    vcp_exit_check,
    compute_vcp_stop_prices,
    calculate_position_size as vcp_calculate_position_size,
    VCPPositionConfig,
)
from scripts.ma2560_execution_manager import ma2560_exit_check, MA2560ExitResult
from scripts.bollinger_execution_manager import (
    BollingerPositionState,
    bb_full_exit_check,
    bb_detect_fake_breakout,
    _compute_bollinger,
    _atr_from_ohlc,
    compute_degrading_ma,
)
from scripts.atr_chandelier_exit import chandelier_exit_check

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
FOUNDATION_DB = PROJECT_ROOT / "outputs" / "p116_foundation_20260522" / "p116_foundation.duckdb"
MARKET_PHASE_DIR = PROJECT_ROOT / "outputs" / "market_phase"
MACRO_CHAIN_DIR = PROJECT_ROOT / "outputs" / "macro_chain_prior"
CHAIN_DYNAMICS_DB = PROJECT_ROOT / "outputs" / "industry_chain" / "chain_dynamics.duckdb"
IFIND_INDUSTRY_JSON = PROJECT_ROOT / "outputs" / "ifind" / "industry_latest.json"
ETF_MONTHLY_STATE_DIR = PROJECT_ROOT / "outputs" / "state_cache"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "simulation" / "leverage"

# 申万一级行业 → 行业ETF映射（用于MN1行业过滤）
SW_L1_TO_ETF = {
    "交通运输": "159666.SZ",
    "传媒": "159805.SZ",
    "公用事业": "159301.SZ",
    "农林牧渔": "159825.SZ",
    "医药生物": "512010.SH",
    "国防军工": "512660.SH",
    "基础化工": "516020.SH",
    "家用电器": "159996.SZ",
    "建筑材料": "159745.SZ",
    "建筑装饰": "516970.SH",
    "房地产": "159768.SZ",
    "有色金属": "512400.SH",
    "机械设备": "159886.SZ",
    "汽车": "515700.SH",
    "煤炭": "515220.SH",
    "环保": "512580.SH",
    "电力设备": "515790.SH",
    "电子": "512480.SH",
    "石油石化": "159588.SZ",
    "计算机": "159586.SZ",
    "通信": "515050.SH",
    "钢铁": "515210.SH",
    "银行": "512800.SH",
    "非银金融": "512880.SH",
    "食品饮料": "159928.SZ",
}

RISK_FREE_RATE = 0.03
FINANCING_RATE = 0.06
TRADING_DAYS_PER_YEAR = 252
LIQUIDATION_THRESHOLD = 0.30
LIMIT_UP_PCT = 0.095
LIMIT_DOWN_PCT = -0.095
MIN_LOT = 100

# 信号名称到整数的映射（Numba 兼容）
SIGNAL_NONE = 0
SIGNAL_VCP_BREAKOUT = 1
SIGNAL_VCP_BREAKOUT_WEAK_VOL = 2
SIGNAL_VCP_BREAKOUT_NO_VOL = 3
SIGNAL_VCP_CONTRACTION = 4
SIGNAL_VCP_EARLY_CONTRACTION = 5
SIGNAL_MA2560_GOLDEN_CROSS = 6
SIGNAL_BB_BANDIT_LONG_ENTRY = 7
SIGNAL_ATR_CHANDELIER_ENTRY = 8

SIGNAL_NAMES = {
    SIGNAL_VCP_BREAKOUT: "vcp_breakout",
    SIGNAL_VCP_BREAKOUT_WEAK_VOL: "vcp_breakout_weak_vol",
    SIGNAL_VCP_BREAKOUT_NO_VOL: "vcp_breakout_no_vol",
    SIGNAL_VCP_CONTRACTION: "vcp_contraction",
    SIGNAL_VCP_EARLY_CONTRACTION: "vcp_early_contraction",
    SIGNAL_MA2560_GOLDEN_CROSS: "ma2560_golden_cross",
    SIGNAL_BB_BANDIT_LONG_ENTRY: "bb_bandit_long_entry",
    SIGNAL_ATR_CHANDELIER_ENTRY: "atr_chandelier_entry",
}

# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class Trade:
    """单笔交易记录"""

    stock_code: str
    entry_date: str
    entry_price: float
    exit_date: str | None = None
    exit_price: float | None = None
    shares: int = 0
    hold_days: int = 0
    pnl_pct: float = 0.0
    pnl_amount: float = 0.0
    exit_reason: str = ""
    exit_type: str = ""
    strategy: str = ""
    half_exited: bool = False


@dataclass
class DailyRecord:
    """每日账户状态记录"""

    date: str
    total_value: float
    cash: float
    borrowed: float
    positions_value: float
    daily_pnl: float
    financing_cost: float
    num_positions: int


@dataclass
class Position:
    """持仓状态"""

    stock_code: str
    entry_date: str
    entry_price: float
    shares: int
    strategy: str
    pivot_point: float = 0.0
    contraction_low: float = 0.0
    entry_atr: float = 0.0
    highest_since_entry: float = 0.0
    half_exited: bool = False
    full_exited: bool = False
    bb_state: Any = None
    prev_above_upper: bool = False
    hold_days: int = 0
    current_price: float = 0.0
    current_value: float = 0.0
    unrealized_pnl_pct: float = 0.0
    chain_rating: str = ""
    chain_factor: float = 1.0


# ===========================================================================
# Numba JIT 加速核心函数
# ===========================================================================


@njit(cache=True)
def _compute_rolling_mean_nb(arr: np.ndarray, window: int) -> np.ndarray:
    """向量化滚动均值（Numba加速）"""
    n = len(arr)
    result = np.empty(n, dtype=np.float64)
    for i in range(n):
        w = min(window, i + 1)
        s = 0.0
        for j in range(i - w + 1, i + 1):
            s += arr[j]
        result[i] = s / w
    return result


@njit(cache=True)
def _compute_rolling_std_nb(arr: np.ndarray, window: int) -> np.ndarray:
    """向量化滚动标准差（Numba加速）"""
    n = len(arr)
    result = np.empty(n, dtype=np.float64)
    for i in range(n):
        w = min(window, i + 1)
        s = 0.0
        for j in range(i - w + 1, i + 1):
            s += arr[j]
        mean = s / w
        var_sum = 0.0
        for j in range(i - w + 1, i + 1):
            diff = arr[j] - mean
            var_sum += diff * diff
        result[i] = math.sqrt(var_sum / w)
    return result


@njit(cache=True)
def _compute_atr_from_closes_nb(closes: np.ndarray) -> float:
    """从收盘价序列估算ATR（简化版，Numba加速）"""
    n = len(closes)
    if n < 2:
        return 0.0
    tr_sum = 0.0
    for i in range(1, n):
        tr_sum += abs(closes[i] - closes[i - 1])
    return tr_sum / (n - 1)


@njit(cache=True)
def _scan_signals_vcp_nb(
    closes: np.ndarray,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    atr14: np.ndarray,
    vol_ma50: np.ndarray,
    high_10d: np.ndarray,
) -> np.ndarray:
    """VCP信号扫描（Numba加速纯数值版本）

    返回: (n_days,) 数组，每个元素为 SIGNAL_* 常量
    """
    n = len(closes)
    signals = np.zeros(n, dtype=np.int32)

    for i in range(n):
        close = closes[i]
        if close <= 0:
            continue

        # 计算5日/20日高低点（从当前日向前）
        i5 = max(0, i - 4)
        i20 = max(0, i - 19)
        high_5 = highs[i5 : i + 1].max()
        low_5 = lows[i5 : i + 1].min()
        high_20 = highs[i20 : i + 1].max()
        low_20 = lows[i20 : i + 1].min()

        # ATR收缩
        atr_now = atr14[i] if i < len(atr14) else 0.0
        atr_5d = atr14[max(0, i - 5)] if i < len(atr14) else 0.0
        atr_10d = atr14[max(0, i - 10)] if i < len(atr14) else 0.0

        contraction_score = 0
        if atr_now > 0 and atr_5d > 0 and atr_10d > 0:
            if atr_now < atr_5d < atr_10d:
                contraction_score += 1

        # 价格振幅收缩
        range_5 = (high_5 - low_5) / close if close > 0 else 0.0
        range_20 = (high_20 - low_20) / close if close > 0 else 1.0
        if range_20 > 0 and range_5 < range_20 * 0.6:
            contraction_score += 1

        # 日线低波动
        open_p = opens[i]
        day_range = abs(close - open_p) / close if close > 0 else 0.0
        if range_20 > 0 and day_range < range_20 * 0.5:
            contraction_score += 1

        if contraction_score >= 2:
            h10 = high_10d[i] if i < len(high_10d) else 0.0
            if h10 > 0 and close > h10:
                vol = volumes[i]
                vma50 = vol_ma50[i] if i < len(vol_ma50) else 0.0
                if vma50 > 0 and vol > vma50 * 1.5:
                    signals[i] = SIGNAL_VCP_BREAKOUT
                elif vma50 > 0 and vol > vma50 * 1.2:
                    signals[i] = SIGNAL_VCP_BREAKOUT_WEAK_VOL
                else:
                    signals[i] = SIGNAL_VCP_BREAKOUT_NO_VOL
            else:
                signals[i] = SIGNAL_VCP_CONTRACTION
        elif contraction_score == 1:
            signals[i] = SIGNAL_VCP_EARLY_CONTRACTION

    return signals


@njit(cache=True)
def _scan_signals_ma2560_nb(
    closes: np.ndarray,
    ma25: np.ndarray,
    ma60: np.ndarray,
) -> np.ndarray:
    """2560信号扫描（Numba加速）"""
    n = len(closes)
    signals = np.zeros(n, dtype=np.int32)

    for i in range(1, n):
        m25 = ma25[i]
        m60 = ma60[i]
        m25_prev = ma25[i - 1]
        m60_prev = ma60[i - 1]

        if m25 <= 0 or m60 <= 0 or closes[i] <= 0:
            continue

        aligned = m25 > m60
        aligned_prev = m25_prev > m60_prev

        if aligned and not aligned_prev:
            signals[i] = SIGNAL_MA2560_GOLDEN_CROSS

    return signals


@njit(cache=True)
def _scan_signals_bollinger_nb(
    closes: np.ndarray,
    prev_closes: np.ndarray,
    close_30_ago: np.ndarray,
    bb_upper: np.ndarray,
    bb_upper_prev: np.ndarray,
) -> np.ndarray:
    """布林强盗信号扫描（Numba加速）"""
    n = len(closes)
    signals = np.zeros(n, dtype=np.int32)

    for i in range(1, n):
        close = closes[i]
        prev_close = prev_closes[i]
        c30 = close_30_ago[i]
        upper = bb_upper[i]
        prev_upper = bb_upper_prev[i]

        if min(close, prev_close, c30, upper, prev_upper) <= 0:
            continue

        momentum_up = close > c30
        crossed_upper = close > upper and prev_close <= prev_upper
        if momentum_up and crossed_upper:
            signals[i] = SIGNAL_BB_BANDIT_LONG_ENTRY

    return signals


@njit(cache=True)
def _scan_signals_atr_chandelier_nb(
    mn1_scores: np.ndarray,
    w1_scores: np.ndarray,
    d1_scores: np.ndarray,
) -> np.ndarray:
    """ATR Chandelier 信号扫描（Numba加速）

    返回: (n_days,) 数组，每个元素为 SIGNAL_* 常量
    """
    n = len(mn1_scores)
    signals = np.zeros(n, dtype=np.int32)

    # 允许的 State score 集合
    for i in range(n):
        mn1 = int(mn1_scores[i])
        w1 = int(w1_scores[i])
        d1 = int(d1_scores[i])

        mn1_ok = (
            mn1 == 0 or mn1 == 1 or mn1 == 2 or mn1 == 3 or mn1 == 6 or mn1 == 7 or mn1 == 10 or mn1 == 11
        )
        w1_ok = w1 == 0 or w1 == 1 or w1 == 2 or w1 == 3 or w1 == 6 or w1 == 7 or w1 == 10 or w1 == 11
        d1_ok = (
            d1 == 2
            or d1 == 3
            or d1 == 4
            or d1 == 5
            or d1 == 6
            or d1 == 7
            or d1 == 10
            or d1 == 11
            or d1 == 12
            or d1 == 13
            or d1 == 14
            or d1 == 15
        )

        if mn1_ok and w1_ok and d1_ok:
            signals[i] = SIGNAL_ATR_CHANDELIER_ENTRY

    return signals


@njit(cache=True)
def _check_exit_vcp_nb(
    entry_price: float,
    pivot_point: float,
    contraction_low: float,
    entry_atr: float,
    current_close: float,
    hold_days: int,
    highest_since_entry: float,
) -> int:
    """VCP出场检查（Numba加速）

    返回: 0=不出场, 1=假突破, 2=硬止损, 3=ATR止损, 4=技术止损, 5=时间退出, 6=移动止损
    """
    if entry_price <= 0:
        return 0
    pnl_pct = (current_close - entry_price) / entry_price

    if hold_days <= 3 and current_close < pivot_point:
        return 1
    if pnl_pct <= -0.06:
        return 2
    atr_stop = entry_price - 2 * entry_atr
    if current_close < atr_stop:
        return 3
    tech_stop = contraction_low * 0.99
    if current_close < tech_stop:
        return 4
    if hold_days > 20 and pnl_pct < 0.05:
        return 5
    if highest_since_entry >= entry_price * 1.05 and current_close <= entry_price:
        return 6
    return 0


@njit(cache=True)
def _check_exit_ma2560_nb(
    entry_price: float,
    current_close: float,
    ma25: float,
    ma60: float,
    hold_days: int,
    half_exited: int,  # 0 or 1
) -> int:
    """2560出场检查（Numba加速）

    返回: 0=不出场, 10=跌破60日线, 11=跌破25日线, 12=止盈≥10%, 13=止盈5-10%
    """
    if entry_price <= 0:
        return 0
    pnl_pct = (current_close - entry_price) / entry_price

    if current_close < ma60:
        return 10
    if current_close < ma25:
        return 11
    if pnl_pct >= 0.10 and half_exited == 0:
        return 12
    if 0.05 <= pnl_pct < 0.10 and half_exited == 0:
        return 13
    return 0


# ===========================================================================
# 向量化数据加载层（DuckDB 单次连接 + SQL 预聚合）
# ===========================================================================


class VectorizedDataStore:
    """向量化数据存储：一次性从 DuckDB 加载所有数据，避免重复连接和循环查询。"""

    def __init__(self, db_path: str, start_date: str, end_date: str):
        self.db_path = db_path
        self.start_date = start_date
        self.end_date = end_date

        # 核心数组（按 stock_code 分组）
        self.stock_codes: list[str] = []
        self.dates: np.ndarray | None = None  # 全局统一日期序列
        self.date_to_idx: dict[str, int] = {}

        # bars: dict[stock_code] -> structured array
        self.bars: dict[str, np.ndarray] = {}
        # indicators: dict[stock_code] -> structured array (aligned with bars)
        self.indicators: dict[str, np.ndarray] = {}
        # states: dict[stock_code] -> structured array
        self.states: dict[str, np.ndarray] = {}

        # 预计算的技术指标
        self.precomputed: dict[str, dict[str, np.ndarray]] = {}

        self.market_phases: dict[str, str] = {}
        self.macro_quadrants: dict[str, str] = {}
        self.industry_chain_ratings: dict[str, dict[str, str]] = {}  # date -> sw_l1 -> rating
        self.stock_to_industry: dict[str, str] = {}  # stock_code -> sw_l1
        self.etf_mn1_states: dict[str, dict[str, int]] = {}  # date -> etf_symbol -> mn1_state_score

    def load_all(self) -> None:
        """一次性加载所有数据并预计算技术指标。"""
        conn = duckdb.connect(self.db_path, read_only=True)
        try:
            self._load_bars(conn)
            self._load_indicators(conn)
            self._load_states(conn)
            self._load_market_phases(conn)
            self._load_macro_quadrants()
            self._load_industry_chain()
            self._load_etf_monthly_states()
            self._precompute_technical_indicators()
        finally:
            conn.close()

    def _load_bars(self, conn: duckdb.DuckDBPyConnection) -> None:
        """加载日线行情到 numpy structured arrays。"""
        query = """
            SELECT stock_code, date, open, high, low, close, volume, amount
            FROM daily_bars
            WHERE date BETWEEN ? AND ?
            ORDER BY stock_code, date
        """
        df = conn.execute(query, [self.start_date, self.end_date]).fetchdf()

        # 构建全局日期序列
        all_dates = sorted(df["date"].unique())
        self.dates = np.array([pd.Timestamp(d).strftime("%Y-%m-%d") for d in all_dates])
        self.date_to_idx = {d: i for i, d in enumerate(self.dates)}

        # 按股票分组
        dtype = [
            ("date", "U10"),
            ("open", "f8"),
            ("high", "f8"),
            ("low", "f8"),
            ("close", "f8"),
            ("volume", "f8"),
            ("amount", "f8"),
        ]
        for stock_code, group in df.groupby("stock_code"):
            group = group.sort_values("date")
            arr = np.empty(len(group), dtype=dtype)
            arr["date"] = group["date"].astype(str).values
            arr["open"] = group["open"].fillna(0).values
            arr["high"] = group["high"].fillna(0).values
            arr["low"] = group["low"].fillna(0).values
            arr["close"] = group["close"].fillna(0).values
            arr["volume"] = group["volume"].fillna(0).values
            arr["amount"] = group["amount"].fillna(0).values
            self.bars[stock_code] = arr
            self.stock_codes.append(stock_code)

    def _load_indicators(self, conn: duckdb.DuckDBPyConnection) -> None:
        """加载 timeframe_indicators 到 structured arrays。"""
        query = """
            SELECT stock_code, period_end as date, atr14, volume as ind_volume,
                   prev_close, bb_middle_20, bb_std_20
            FROM timeframe_indicators
            WHERE timeframe = 'D1' AND period_end BETWEEN ? AND ?
            ORDER BY stock_code, period_end
        """
        df = conn.execute(query, [self.start_date, self.end_date]).fetchdf()

        dtype = [
            ("date", "U10"),
            ("atr14", "f8"),
            ("volume", "f8"),
            ("prev_close", "f8"),
            ("bb_middle_20", "f8"),
            ("bb_std_20", "f8"),
        ]
        for stock_code, group in df.groupby("stock_code"):
            group = group.sort_values("date")
            arr = np.empty(len(group), dtype=dtype)
            arr["date"] = group["date"].astype(str).values
            arr["atr14"] = group["atr14"].fillna(0).values
            arr["volume"] = group["ind_volume"].fillna(0).values
            arr["prev_close"] = group["prev_close"].fillna(0).values
            arr["bb_middle_20"] = group["bb_middle_20"].fillna(0).values
            arr["bb_std_20"] = group["bb_std_20"].fillna(0).values
            self.indicators[stock_code] = arr

    def _load_states(self, conn: duckdb.DuckDBPyConnection) -> None:
        """加载 d1_perspective_state。"""
        query = """
            SELECT stock_code, state_date as date,
                   d1_trend, d1_volatility, d1_compression,
                   mn1_state_score, w1_state_score, d1_state_score
            FROM d1_perspective_state
            WHERE state_date BETWEEN ? AND ?
            ORDER BY stock_code, state_date
        """
        df = conn.execute(query, [self.start_date, self.end_date]).fetchdf()

        dtype = [
            ("date", "U10"),
            ("d1_trend", "U20"),
            ("d1_volatility", "U20"),
            ("d1_compression", "U20"),
            ("mn1_state_score", "i4"),
            ("w1_state_score", "i4"),
            ("d1_state_score", "i4"),
        ]
        for stock_code, group in df.groupby("stock_code"):
            group = group.sort_values("date")
            arr = np.empty(len(group), dtype=dtype)
            arr["date"] = group["date"].astype(str).values
            arr["d1_trend"] = group["d1_trend"].fillna("").values.astype(str)
            arr["d1_volatility"] = group["d1_volatility"].fillna("").values.astype(str)
            arr["d1_compression"] = group["d1_compression"].fillna("").values.astype(str)
            arr["mn1_state_score"] = group["mn1_state_score"].fillna(0).values.astype(np.int32)
            arr["w1_state_score"] = group["w1_state_score"].fillna(0).values.astype(np.int32)
            arr["d1_state_score"] = group["d1_state_score"].fillna(0).values.astype(np.int32)
            self.states[stock_code] = arr

    def _load_market_phases(self, conn: duckdb.DuckDBPyConnection) -> None:
        """加载市场阶段数据。优先从JSON读取，缺失时用DuckDB SQL一次性聚合计算。"""
        start_dt = datetime.strptime(self.start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(self.end_date, "%Y-%m-%d").date()

        # 从JSON读取
        for single_date in _date_range(start_dt, end_dt):
            date_str = single_date.strftime("%Y-%m-%d")
            filepath = MARKET_PHASE_DIR / f"market_phase_{date_str}.json"
            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.market_phases[date_str] = data.get("market_phase", "undetermined")

        # 缺失日期用 DuckDB SQL 一次性聚合
        missing_dates = [
            d.strftime("%Y-%m-%d")
            for d in _date_range(start_dt, end_dt)
            if d.strftime("%Y-%m-%d") not in self.market_phases
        ]
        if missing_dates:
            query = """
                SELECT
                    state_date as date,
                    COUNT(*) as ef_count,
                    SUM(CASE WHEN d1_trend IN ('bull_trend', 'bull_start') THEN 1 ELSE 0 END) as up_count,
                    SUM(CASE WHEN d1_compression IN ('contracting') THEN 1 ELSE 0 END) as contracted_count
                FROM d1_perspective_state
                WHERE state_date BETWEEN ? AND ?
                  AND d1_trend NOT IN ('closed', 'insufficient_history')
                GROUP BY state_date
                ORDER BY state_date
            """
            rows = conn.execute(query, [self.start_date, self.end_date]).fetchall()

            dates = []
            ef_counts = np.zeros(len(rows), dtype=np.float64)
            up_counts = np.zeros(len(rows), dtype=np.float64)
            contracted_counts = np.zeros(len(rows), dtype=np.float64)

            for i, row in enumerate(rows):
                dates.append(str(row[0]))
                ef_counts[i] = row[1]
                up_counts[i] = row[2]
                contracted_counts[i] = row[3]

            for i, date_str in enumerate(dates):
                ef_count = ef_counts[i]
                up_ratio = up_counts[i] / ef_count if ef_count > 0 else 0.0
                contracted_ratio = contracted_counts[i] / ef_count if ef_count > 0 else 0.0

                pool_change_5d = 0.0
                if i >= 5:
                    prev_ef = ef_counts[i - 5]
                    if prev_ef > 0:
                        pool_change_5d = (ef_count - prev_ef) / prev_ef

                if up_ratio > 0.6 and pool_change_5d > 0.1:
                    phase = "progression"
                elif up_ratio > 0.5 and pool_change_5d > 0.05:
                    phase = "emergence"
                elif up_ratio > 0.4 and pool_change_5d > -0.05:
                    phase = "extension"
                elif contracted_ratio > 0.5 or pool_change_5d < -0.15:
                    phase = "contraction"
                elif up_ratio < 0.3 and pool_change_5d < -0.2:
                    phase = "risk_release"
                else:
                    phase = "undetermined"

                self.market_phases[date_str] = phase

    def _load_macro_quadrants(self) -> None:
        """加载宏观象限数据。"""
        start_dt = datetime.strptime(self.start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(self.end_date, "%Y-%m-%d").date()

        # 先读取所有可用的JSON文件缓存
        latest_quadrant = "复苏"
        latest_file = MACRO_CHAIN_DIR / "macro_chain_prior_latest.json"
        if latest_file.exists():
            with open(latest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                latest_quadrant = data.get("quadrant", {}).get("name", "复苏")

        daily_quadrants: dict[str, str] = {}
        for single_date in _date_range(start_dt, end_dt):
            date_str = single_date.strftime("%Y-%m-%d")
            filepath = MACRO_CHAIN_DIR / f"macro_chain_prior_{date_str}.json"
            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    daily_quadrants[date_str] = data.get("quadrant", {}).get("name", "复苏")
            else:
                daily_quadrants[date_str] = latest_quadrant

        self.macro_quadrants = daily_quadrants

    def _load_industry_chain(self) -> None:
        """加载产业链景气度数据：股票→申万一级行业→景气评级。"""
        # 1. 从 iFinD JSON 加载 stock_code → sw_l1 映射
        if IFIND_INDUSTRY_JSON.exists():
            with open(IFIND_INDUSTRY_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            by_code = data.get("by_code", {})
            for stock_code, row in by_code.items():
                sw_l1 = row.get("sw_l1")
                if sw_l1:
                    self.stock_to_industry[stock_code] = sw_l1

        # 2. 从 chain_dynamics.duckdb 加载 sw_l1 → rating 映射（按日期）
        if CHAIN_DYNAMICS_DB.exists():
            conn = duckdb.connect(str(CHAIN_DYNAMICS_DB), read_only=True)
            try:
                rows = conn.execute("""
                    SELECT as_of_date, sw_l1, rating, prosperity_score,
                           prosperity_change, chain_position
                    FROM industry_position
                    ORDER BY as_of_date, sw_l1
                """).fetchall()
                for as_of_date, sw_l1, rating, prosperity_score, prosperity_change, chain_position in rows:
                    date_str = str(as_of_date)
                    self.industry_chain_ratings.setdefault(date_str, {})[sw_l1] = {
                        "rating": rating or "medium",
                        "prosperity_score": prosperity_score,
                        "prosperity_change": prosperity_change or "stable",
                        "chain_position": chain_position or "综合",
                    }
            finally:
                conn.close()

        # 3. 对回测区间内的每一天做前向填充（历史日期用最近可用数据）
        start_dt = datetime.strptime(self.start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(self.end_date, "%Y-%m-%d").date()
        available_dates = sorted(self.industry_chain_ratings.keys())
        filled: dict[str, dict[str, dict[str, Any]]] = {}
        for single_date in _date_range(start_dt, end_dt):
            date_str = single_date.strftime("%Y-%m-%d")
            # 找最近的不晚于当前日期的数据
            nearest = None
            for d in available_dates:
                if d <= date_str:
                    nearest = d
            if nearest:
                filled[date_str] = self.industry_chain_ratings[nearest]
        self.industry_chain_ratings = filled

    def _load_etf_monthly_states(self) -> None:
        """加载ETF月线MN1 State数据。"""
        start_dt = datetime.strptime(self.start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(self.end_date, "%Y-%m-%d").date()

        # 读取所有可用的ETF月线State JSON
        all_states: dict[str, dict[str, int]] = {}  # ym -> etf -> score
        for path in sorted(ETF_MONTHLY_STATE_DIR.glob("etf_monthly_state_*.json")):
            if "latest" in path.name:
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                ym = data.get("ym", "")
                if not ym:
                    continue
                month_states: dict[str, int] = {}
                for s in data.get("data", []):
                    sc = s.get("stock_code")
                    score = s.get("mn1_state_score")
                    if sc and score is not None:
                        month_states[sc] = score
                if month_states:
                    all_states[ym] = month_states
            except (json.JSONDecodeError, IOError):
                continue

        # 将月线State按日期对齐到每个交易日（前向填充）
        for single_date in _date_range(start_dt, end_dt):
            date_str = single_date.strftime("%Y-%m-%d")
            ym = date_str[:6]
            # 找最近的已有月线State（不晚于当前月份）
            nearest_ym = None
            for available_ym in sorted(all_states.keys()):
                if available_ym <= ym:
                    nearest_ym = available_ym
            if nearest_ym:
                self.etf_mn1_states[date_str] = dict(all_states[nearest_ym])

    def _precompute_technical_indicators(self) -> None:
        """为每只股票预计算所有技术指标，避免回测循环中重复计算。"""
        for stock_code in self.stock_codes:
            bars = self.bars.get(stock_code)
            if bars is None or len(bars) == 0:
                continue

            n = len(bars)
            closes = bars["close"].astype(np.float64)
            opens = bars["open"].astype(np.float64)
            highs = bars["high"].astype(np.float64)
            lows = bars["low"].astype(np.float64)
            volumes = bars["volume"].astype(np.float64)

            # 从 indicators 获取已有数据
            ind = self.indicators.get(stock_code)
            atr14 = ind["atr14"].astype(np.float64) if ind is not None else np.zeros(n, dtype=np.float64)
            prev_close = (
                ind["prev_close"].astype(np.float64) if ind is not None else np.zeros(n, dtype=np.float64)
            )
            bb_middle_20 = (
                ind["bb_middle_20"].astype(np.float64) if ind is not None else np.zeros(n, dtype=np.float64)
            )
            bb_std_20 = (
                ind["bb_std_20"].astype(np.float64) if ind is not None else np.zeros(n, dtype=np.float64)
            )

            # 预计算滚动指标
            ma25 = _compute_rolling_mean_nb(closes, 25)
            ma60 = _compute_rolling_mean_nb(closes, 60)
            ma25_prev = np.empty(n, dtype=np.float64)
            ma25_prev[0] = ma25[0]
            ma25_prev[1:] = ma25[:-1]
            ma60_prev = np.empty(n, dtype=np.float64)
            ma60_prev[0] = ma60[0]
            ma60_prev[1:] = ma60[:-1]

            vol_ma20 = _compute_rolling_mean_nb(volumes, 20)
            vol_ma50 = _compute_rolling_mean_nb(volumes, 50)

            # 布林带 (50日, 1倍标准差)
            bb_middle_50 = _compute_rolling_mean_nb(closes, 50)
            bb_std_50 = _compute_rolling_std_nb(closes, 50)
            bb_upper_50_1 = bb_middle_50 + bb_std_50
            bb_upper_50_1_prev = np.empty(n, dtype=np.float64)
            bb_upper_50_1_prev[0] = bb_upper_50_1[0]
            bb_upper_50_1_prev[1:] = bb_upper_50_1[:-1]

            # 30日前收盘价
            close_30_ago = np.empty(n, dtype=np.float64)
            for i in range(n):
                idx = max(0, i - 30)
                close_30_ago[i] = closes[idx]

            # 10日最高价（用于VCP）
            high_10d = np.empty(n, dtype=np.float64)
            for i in range(n):
                i10 = max(0, i - 9)
                high_10d[i] = highs[i10 : i + 1].max()

            # 从 states 获取多周期 State score
            st = self.states.get(stock_code)
            mn1_scores = (
                st["mn1_state_score"].astype(np.float64) if st is not None else np.zeros(n, dtype=np.float64)
            )
            w1_scores = (
                st["w1_state_score"].astype(np.float64) if st is not None else np.zeros(n, dtype=np.float64)
            )
            d1_scores = (
                st["d1_state_score"].astype(np.float64) if st is not None else np.zeros(n, dtype=np.float64)
            )

            self.precomputed[stock_code] = {
                "closes": closes,
                "opens": opens,
                "highs": highs,
                "lows": lows,
                "volumes": volumes,
                "atr14": atr14,
                "prev_close": prev_close,
                "bb_middle_20": bb_middle_20,
                "bb_std_20": bb_std_20,
                "ma25": ma25,
                "ma60": ma60,
                "ma25_prev": ma25_prev,
                "ma60_prev": ma60_prev,
                "vol_ma20": vol_ma20,
                "vol_ma50": vol_ma50,
                "bb_middle_50": bb_middle_50,
                "bb_std_50": bb_std_50,
                "bb_upper_50_1": bb_upper_50_1,
                "bb_upper_50_1_prev": bb_upper_50_1_prev,
                "close_30_ago": close_30_ago,
                "high_10d": high_10d,
                "mn1_scores": mn1_scores,
                "w1_scores": w1_scores,
                "d1_scores": d1_scores,
            }

    def get_bar_for_date(self, stock_code: str, date_str: str) -> dict[str, Any] | None:
        """获取指定日期bar（兼容旧接口）。"""
        bars = self.bars.get(stock_code)
        if bars is None:
            return None
        mask = bars["date"] == date_str
        if not np.any(mask):
            return None
        idx = np.argmax(mask)
        return {
            "stock_code": stock_code,
            "date": bars["date"][idx],
            "open": float(bars["open"][idx]),
            "high": float(bars["high"][idx]),
            "low": float(bars["low"][idx]),
            "close": float(bars["close"][idx]),
            "volume": float(bars["volume"][idx]),
            "amount": float(bars["amount"][idx]),
        }

    def get_precomputed(self, stock_code: str) -> dict[str, np.ndarray] | None:
        return self.precomputed.get(stock_code)


# ===========================================================================
# 回测引擎（优化版）
# ===========================================================================


class LeveragedBacktestEngine:
    """带杠杆的回测引擎 — 高性能版"""

    def __init__(
        self,
        strategy: str,
        start_date: str,
        end_date: str,
        initial_capital: float = 1_000_000,
        leverage: float = 1.0,
        max_positions: int = 8,
        financing_rate: float = FINANCING_RATE,
        data_store: VectorizedDataStore | None = None,
    ):
        self.strategy = strategy
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.leverage = leverage
        self.max_positions = max_positions
        self.financing_rate = financing_rate

        self.cash = initial_capital
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.daily_records: list[DailyRecord] = []
        self.pending_signals: list[dict[str, Any]] = []
        self.chain_filtered_count: int = 0
        self.macro_filtered_count: int = 0
        self.enable_macro_filter: bool = True

        # 数据存储（外部传入或自行加载）
        self.data_store = data_store
        self.all_dates: list[str] = []

        # 预扫描的信号缓存: dict[date_str] -> list[(stock_code, signal_id, confidence, close)]
        self._signal_cache: dict[str, list[tuple[str, int, float, float]]] = {}

    def load_data(self) -> None:
        """加载所有必要数据。"""
        print(f"[{self.strategy}] 加载数据...")
        if self.data_store is None:
            self.data_store = VectorizedDataStore(str(FOUNDATION_DB), self.start_date, self.end_date)
            self.data_store.load_all()

        self.all_dates = list(self.data_store.dates)
        print(f"  股票数: {len(self.data_store.stock_codes)}, 交易日: {len(self.all_dates)}")

    def _compute_macro_filters(self, date_str: str, stock_code: str) -> tuple[float, float, str]:
        """计算宏观环境过滤系数。若禁用则返回 (1.0, 1.0, "").

        Returns:
            (market_coeff, industry_coeff, filter_reason)
            market_coeff: 大盘系数 (0.0=禁止, 0.5=半仓, 0.6=中性偏低, 0.8=可开仓, 1.0=正常)
            industry_coeff: 行业系数 (同上)
        """
        if not self.enable_macro_filter:
            return 1.0, 1.0, ""
        etf_states = self.data_store.etf_mn1_states.get(date_str, {})
        if not etf_states:
            return 1.0, 1.0, "no_etf_data"

        def _coeff_from_mn1(score: int | None) -> float:
            if score is None:
                return 1.0
            abs_score = abs(score)
            # E/F (14/15) -> 1.0
            if abs_score >= 14:
                return 1.0
            # 10/12 (扩张+突破/回踩) -> 0.8
            if abs_score in (10, 12):
                return 0.8
            # 0 (收缩极致) -> 0.5
            if abs_score == 0:
                return 0.5
            # 负值 (-14/-15/-10/-11 etc) -> 0.0
            if score < 0:
                return 0.0
            # 其他状态 -> 0.6
            return 0.6

        # 大盘系数：以510300.SH为核心，辅以510050.SH、510500.SH、159915.SZ
        # 取四个ETF中最差的系数（最保守）
        benchmark_etfs = ["510300.SH", "510050.SH", "510500.SH", "159915.SZ"]
        bench_coeffs = []
        for etf in benchmark_etfs:
            score = etf_states.get(etf)
            if score is not None:
                bench_coeffs.append(_coeff_from_mn1(score))
        if bench_coeffs:
            market_coeff = min(bench_coeffs)
        else:
            market_coeff = 1.0

        # 行业系数：根据个股的sw_l1找到对应行业ETF
        sw_l1 = self.data_store.stock_to_industry.get(stock_code)
        industry_coeff = 1.0
        if sw_l1:
            etf_symbol = SW_L1_TO_ETF.get(sw_l1)
            if etf_symbol:
                score = etf_states.get(etf_symbol)
                if score is not None:
                    industry_coeff = _coeff_from_mn1(score)

        if market_coeff <= 0.0:
            return market_coeff, industry_coeff, f"market_mn1_negative"
        if industry_coeff <= 0.0:
            return market_coeff, industry_coeff, f"industry_mn1_negative"

        return market_coeff, industry_coeff, ""

    def pre_scan_signals(self) -> None:
        """预扫描所有日期的所有股票信号（Numba加速）。"""
        print(f"[{self.strategy}] 预扫描信号...")
        ds = self.data_store

        for stock_code in ds.stock_codes:
            pc = ds.get_precomputed(stock_code)
            if pc is None:
                continue

            n = len(pc["closes"])
            if n == 0:
                continue

            bars = ds.bars[stock_code]
            dates = bars["date"]

            if self.strategy == "vcp":
                signals = _scan_signals_vcp_nb(
                    pc["closes"],
                    pc["opens"],
                    pc["highs"],
                    pc["lows"],
                    pc["volumes"],
                    pc["atr14"],
                    pc["vol_ma50"],
                    pc["high_10d"],
                )
                for i in range(n):
                    sid = signals[i]
                    if sid != 0:
                        conf = (
                            0.95
                            if sid == SIGNAL_VCP_BREAKOUT
                            else (
                                0.70
                                if sid == SIGNAL_VCP_BREAKOUT_WEAK_VOL
                                else (
                                    0.55
                                    if sid == SIGNAL_VCP_BREAKOUT_NO_VOL
                                    else (0.40 if sid == SIGNAL_VCP_CONTRACTION else 0.20)
                                )
                            )
                        )
                        if sid in (
                            SIGNAL_VCP_BREAKOUT,
                            SIGNAL_VCP_BREAKOUT_WEAK_VOL,
                            SIGNAL_VCP_BREAKOUT_NO_VOL,
                            SIGNAL_VCP_CONTRACTION,
                            SIGNAL_VCP_EARLY_CONTRACTION,
                        ):
                            date_str = dates[i]
                            self._signal_cache.setdefault(date_str, []).append(
                                (stock_code, sid, conf, pc["closes"][i])
                            )

            elif self.strategy == "ma2560":
                signals = _scan_signals_ma2560_nb(pc["closes"], pc["ma25"], pc["ma60"])
                for i in range(n):
                    sid = signals[i]
                    if sid == SIGNAL_MA2560_GOLDEN_CROSS:
                        date_str = dates[i]
                        self._signal_cache.setdefault(date_str, []).append(
                            (stock_code, sid, 0.85, pc["closes"][i])
                        )

            elif self.strategy == "bollinger_bandit":
                signals = _scan_signals_bollinger_nb(
                    pc["closes"],
                    pc["prev_close"],
                    pc["close_30_ago"],
                    pc["bb_upper_50_1"],
                    pc["bb_upper_50_1_prev"],
                )
                for i in range(n):
                    sid = signals[i]
                    if sid == SIGNAL_BB_BANDIT_LONG_ENTRY:
                        date_str = dates[i]
                        self._signal_cache.setdefault(date_str, []).append(
                            (stock_code, sid, 0.80, pc["closes"][i])
                        )

            elif self.strategy == "atr_chandelier":
                signals = _scan_signals_atr_chandelier_nb(
                    pc["mn1_scores"],
                    pc["w1_scores"],
                    pc["d1_scores"],
                )
                for i in range(n):
                    sid = signals[i]
                    if sid == SIGNAL_ATR_CHANDELIER_ENTRY:
                        date_str = dates[i]
                        self._signal_cache.setdefault(date_str, []).append(
                            (stock_code, sid, 0.75, pc["closes"][i])
                        )

        # 对每个日期的信号按置信度排序
        for date_str in self._signal_cache:
            self._signal_cache[date_str].sort(key=lambda x: x[2], reverse=True)

        total_signals = sum(len(v) for v in self._signal_cache.values())
        print(f"  预扫描完成: {total_signals} 个信号")

    def scan_signals_for_date(self, date_str: str) -> list[dict[str, Any]]:
        """从预扫描缓存获取信号。"""
        cached = self._signal_cache.get(date_str, [])
        result = []
        for stock_code, sid, confidence, close in cached:
            bar = self.data_store.get_bar_for_date(stock_code, date_str)
            if bar is None:
                continue
            result.append(
                {
                    "date": date_str,
                    "stock_code": stock_code,
                    "signal_name": SIGNAL_NAMES.get(sid, ""),
                    "confidence": confidence,
                    "close": bar["close"],
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "volume": bar["volume"],
                    "ctx": {},  # 上下文在入场确认时按需构建
                }
            )
        return result

    def compute_equity(self, date_str: str) -> float:
        """计算当前账户净值。"""
        positions_value = 0.0
        for stock_code, pos in self.positions.items():
            bar = self.data_store.get_bar_for_date(stock_code, date_str)
            if bar:
                positions_value += pos.shares * bar["close"]
            else:
                positions_value += pos.current_value
        return self.cash + positions_value

    def run(self) -> None:
        """执行回测。"""
        print(f"\n[{self.strategy}] 开始回测: {self.start_date} ~ {self.end_date}")
        print(
            f"  初始资金: {self.initial_capital:,.0f}, 杠杆: {self.leverage}x, 最大持仓: {self.max_positions}"
        )

        # 预扫描信号
        self.pre_scan_signals()

        for i, date_str in enumerate(self.all_dates):
            self._execute_pending_entries(date_str)
            self._check_exits(date_str)
            self._scan_and_queue_signals(date_str)

            financing_cost = self._compute_financing_cost()
            self.cash -= financing_cost

            equity = self.compute_equity(date_str)
            if equity < self.initial_capital * LIQUIDATION_THRESHOLD:
                self._liquidate_all(date_str, "强制清仓(净值低于30%)")

            positions_value = equity - self.cash
            borrowed = max(0, positions_value - self.cash) if self.leverage > 1 else 0
            self.daily_records.append(
                DailyRecord(
                    date=date_str,
                    total_value=equity,
                    cash=self.cash,
                    borrowed=borrowed,
                    positions_value=positions_value,
                    daily_pnl=equity
                    - (self.daily_records[-1].total_value if self.daily_records else self.initial_capital),
                    financing_cost=financing_cost,
                    num_positions=len(self.positions),
                )
            )

            if (i + 1) % 50 == 0 or i == len(self.all_dates) - 1:
                print(f"  {date_str}: 净值={equity:,.0f}, 持仓={len(self.positions)}, 现金={self.cash:,.0f}")

        print(f"\n[{self.strategy}] 回测完成")
        if self.chain_filtered_count > 0:
            print(f"  产业链 low 评级过滤: {self.chain_filtered_count} 个信号被拦截")

    def _execute_pending_entries(self, date_str: str) -> None:
        """执行待入场的 T+1 信号。"""
        to_remove: list[int] = []

        for idx, pending in enumerate(self.pending_signals):
            signal_date = pending["date"]
            stock_code = pending["stock_code"]

            bars = self.data_store.bars.get(stock_code)
            if bars is None or len(bars) == 0:
                continue

            dates = bars["date"]
            signal_idx = -1
            for j in range(len(dates)):
                if dates[j] == signal_date:
                    signal_idx = j
                    break
            if signal_idx < 0 or signal_idx + 1 >= len(bars):
                continue

            next_day_bar = {
                "date": dates[signal_idx + 1],
                "open": float(bars["open"][signal_idx + 1]),
                "high": float(bars["high"][signal_idx + 1]),
                "low": float(bars["low"][signal_idx + 1]),
                "close": float(bars["close"][signal_idx + 1]),
                "volume": float(bars["volume"][signal_idx + 1]),
            }
            if next_day_bar["date"] != date_str:
                continue

            confirmed, reason, entry_data = confirm_entry(self.strategy, pending, next_day_bar)
            if not confirmed:
                to_remove.append(idx)
                continue

            if stock_code in self.positions:
                to_remove.append(idx)
                continue

            if len(self.positions) >= self.max_positions:
                to_remove.append(idx)
                continue

            entry_price = entry_data["entry_price"]
            equity = self.compute_equity(date_str)

            phase = self.data_store.market_phases.get(date_str, "undetermined")
            if phase == "risk_release":
                to_remove.append(idx)
                continue

            # ── 产业链景气度过滤 ──
            chain_rating = "medium"
            chain_prosperity_score = None
            chain_position_str = "综合"
            sw_l1 = self.data_store.stock_to_industry.get(stock_code)
            if sw_l1:
                day_ratings = self.data_store.industry_chain_ratings.get(date_str, {})
                chain_info = day_ratings.get(sw_l1)
                if chain_info:
                    chain_rating = chain_info.get("rating", "medium")
                    chain_prosperity_score = chain_info.get("prosperity_score")
                    chain_position_str = chain_info.get("chain_position", "综合")

            # 评级为 low 时，信号降级或不开仓
            if chain_rating == "low":
                self.chain_filtered_count += 1
                to_remove.append(idx)
                continue

            # ── 指数/ETF 月线 MN1 State 宏观环境过滤 ──
            market_coeff, industry_coeff, filter_reason = self._compute_macro_filters(date_str, stock_code)
            if market_coeff <= 0.0 or industry_coeff <= 0.0:
                self.macro_filtered_count += 1
                to_remove.append(idx)
                continue

            # 三重共振：产业链加成系数
            chain_factor_val = 1.0
            if chain_prosperity_score is not None:
                # 参考 TRIPLE_RESONANCE_ENHANCEMENT.md 公式简化版
                raw = 0.80 + (chain_prosperity_score / 10.0) * 0.40
                # 敏感度调整（策略×产业链位置）
                sensitivity = {
                    "vcp": {"上游": 0.8, "中游": 1.0, "下游": 0.6, "综合": 0.7},
                    "ma2560": {"上游": 1.0, "中游": 1.0, "下游": 0.8, "综合": 0.9},
                    "bollinger_bandit": {"上游": 0.6, "中游": 0.8, "下游": 1.0, "综合": 0.7},
                    "atr_chandelier": {"上游": 0.9, "中游": 1.0, "下游": 0.9, "综合": 0.9},
                }.get(self.strategy, {}).get(chain_position_str, 0.7)
                deviation = (raw - 1.0) * sensitivity
                chain_factor_val = round(1.0 + deviation, 4)
                # 钳制
                chain_factor_val = max(0.80, min(1.20, chain_factor_val))

            quadrant = self.data_store.macro_quadrants.get(date_str, "复苏")
            fit_level = "适配"
            if self.strategy == "vcp":
                fit_level = "最佳适配"
            elif self.strategy == "bollinger_bandit":
                fit_level = "弱适配"
            elif self.strategy == "atr_chandelier":
                fit_level = "适配"

            strategy_boost = 1.0
            phase_file = MARKET_PHASE_DIR / f"market_phase_{date_str}.json"
            if phase_file.exists():
                with open(phase_file, "r", encoding="utf-8") as f:
                    pdata = json.load(f)
                    strategy_boost = (
                        pdata.get("strategy_implications", {}).get(self.strategy, {}).get("factor", 1.0)
                    )

            sizing = calculate_dynamic_position(phase, strategy_boost, quadrant, fit_level)
            allocation_pct = sizing["total_allocation_pct"] * chain_factor_val

            if allocation_pct <= 0:
                to_remove.append(idx)
                continue

            target_position_value = (
                equity * allocation_pct * self.leverage * market_coeff * industry_coeff / self.max_positions
            )
            shares = int(target_position_value / entry_price / MIN_LOT) * MIN_LOT

            if shares <= 0:
                to_remove.append(idx)
                continue

            cost = shares * entry_price
            max_borrowable = equity * (self.leverage - 1)
            if cost > self.cash + max_borrowable:
                max_shares = int((self.cash + max_borrowable) / entry_price / MIN_LOT) * MIN_LOT
                if max_shares <= 0:
                    to_remove.append(idx)
                    continue
                shares = max_shares
                cost = shares * entry_price

            self.cash -= cost

            pos = Position(
                stock_code=stock_code,
                entry_date=date_str,
                entry_price=entry_price,
                shares=shares,
                strategy=self.strategy,
                pivot_point=entry_data.get("pivot_point", entry_price),
                contraction_low=entry_data.get("contraction_low", entry_price * 0.94),
                entry_atr=entry_data.get("entry_atr", entry_price * 0.03),
                highest_since_entry=entry_price,
                current_price=entry_price,
                current_value=cost,
            )

            if self.strategy == "bollinger_bandit":
                pos.bb_state = BollingerPositionState(entry_price, date_str, pos.entry_atr)

            pos.chain_rating = chain_rating
            pos.chain_factor = chain_factor_val
            self.positions[stock_code] = pos
            to_remove.append(idx)

        for idx in reversed(to_remove):
            self.pending_signals.pop(idx)

    def _check_exits(self, date_str: str) -> None:
        """检查所有持仓的出场条件（Numba加速）。"""
        to_exit: list[tuple[str, str, str, float]] = []

        for stock_code, pos in self.positions.items():
            bars = self.data_store.bars.get(stock_code)
            if bars is None or len(bars) == 0:
                continue

            dates = bars["date"]
            bar_idx = -1
            for j in range(len(dates)):
                if dates[j] == date_str:
                    bar_idx = j
                    break
            if bar_idx < 0:
                continue

            close = float(bars["close"][bar_idx])
            high = float(bars["high"][bar_idx])

            pos.hold_days += 1
            pos.current_price = close
            pos.current_value = pos.shares * close
            pos.unrealized_pnl_pct = (close - pos.entry_price) / pos.entry_price
            if pos.highest_since_entry < high:
                pos.highest_since_entry = high

            exited = False
            reason = ""
            exit_type = ""
            exit_pct = 1.0

            if self.strategy == "vcp":
                result = _check_exit_vcp_nb(
                    pos.entry_price,
                    pos.pivot_point or pos.entry_price,
                    pos.contraction_low or pos.entry_price * 0.94,
                    pos.entry_atr or pos.entry_price * 0.03,
                    close,
                    pos.hold_days,
                    pos.highest_since_entry,
                )
                if result == 1:
                    exited, reason, exit_type = True, "假突破离场", "stop"
                elif result == 2:
                    exited, reason, exit_type = True, "硬止损(-6%)", "stop"
                elif result == 3:
                    exited, reason, exit_type = True, "ATR止损(2x)", "stop"
                elif result == 4:
                    exited, reason, exit_type = True, "技术止损(收缩低点)", "stop"
                elif result == 5:
                    exited, reason, exit_type = True, "时间退出(20日未达5%)", "time"
                elif result == 6:
                    exited, reason, exit_type = True, "移动止损(盈利回吐)", "trailing"

            elif self.strategy == "ma2560":
                pc = self.data_store.get_precomputed(stock_code)
                if pc is not None and bar_idx < len(pc["ma25"]):
                    ma25 = float(pc["ma25"][bar_idx])
                    ma60 = float(pc["ma60"][bar_idx])
                else:
                    ma25 = close
                    ma60 = close

                result = _check_exit_ma2560_nb(
                    pos.entry_price,
                    close,
                    ma25,
                    ma60,
                    pos.hold_days,
                    1 if pos.half_exited else 0,
                )
                if result == 10:
                    exited, reason, exit_type, exit_pct = True, "跌破60日线，强制清仓", "stop", 1.0
                elif result == 11:
                    exit_pct = 1.0 if not pos.half_exited else 0.5
                    exited, reason, exit_type = True, "跌破25日均线，止损", "stop"
                elif result == 12:
                    exit_pct = 0.5 if pos.half_exited else 1.0
                    pos.full_exited = True
                    exited, reason, exit_type = True, "止盈(盈利≥10%，全部清仓)", "profit"
                elif result == 13:
                    pos.half_exited = True
                    exited, reason, exit_type, exit_pct = True, "止盈(盈利5-10%，减仓50%)", "profit", 0.5

            elif self.strategy == "bollinger_bandit":
                pc = self.data_store.get_precomputed(stock_code)
                if pc is not None:
                    closes_arr = pc["closes"][: bar_idx + 1]
                else:
                    closes_arr = np.array([close], dtype=np.float64)

                if pos.bb_state is None:
                    pos.bb_state = BollingerPositionState(
                        entry_price=pos.entry_price,
                        entry_date=pos.entry_date,
                        entry_atr=pos.entry_atr,
                    )

                bb_upper, bb_middle = _compute_bollinger(closes_arr.tolist(), period=50, num_std=1.0)
                exit_ma_period_val, exit_ma = compute_degrading_ma(pos.hold_days, closes_arr.tolist())

                ohlc = [(0.0, 0.0, 0.0, float(c)) for c in closes_arr[-20:]]
                current_atr = _atr_from_ohlc(ohlc) if len(ohlc) >= 20 else pos.entry_atr

                ctx = {
                    "hold_days": pos.hold_days,
                    "atr": current_atr,
                    "bb_upper": bb_upper,
                    "bb_middle": bb_middle,
                    "exit_ma_period": exit_ma_period_val,
                    "exit_ma": exit_ma,
                }

                result = bb_full_exit_check(pos.bb_state, {"close": close}, ctx)
                if result:
                    exited, reason, exit_type, exit_pct = (
                        True,
                        result["exit_reason"],
                        result["exit_type"],
                        result["exit_pct"],
                    )

            elif self.strategy == "atr_chandelier":
                result = chandelier_exit_check(
                    entry_price=pos.entry_price,
                    entry_atr=pos.entry_atr or pos.entry_price * 0.03,
                    current_close=close,
                    highest_since_entry=pos.highest_since_entry,
                    hold_days=pos.hold_days,
                )
                if result:
                    exited, reason, exit_type, exit_pct = (
                        True,
                        result.exit_reason,
                        result.exit_type,
                        result.exit_pct,
                    )

            if exited:
                to_exit.append((stock_code, reason, exit_type, exit_pct))

        for stock_code, reason, exit_type, exit_pct in to_exit:
            self._execute_exit(stock_code, date_str, reason, exit_type, exit_pct)

    def _execute_exit(
        self, stock_code: str, date_str: str, reason: str, exit_type: str, exit_pct: float
    ) -> None:
        """执行出场。"""
        pos = self.positions.get(stock_code)
        if pos is None:
            return

        bar = self.data_store.get_bar_for_date(stock_code, date_str)
        if bar is None:
            return

        # 跌停检查
        bars = self.data_store.bars.get(stock_code)
        if bars is not None and len(bars) > 0:
            dates = bars["date"]
            bar_idx = -1
            for j in range(len(dates)):
                if dates[j] == date_str:
                    bar_idx = j
                    break
            if bar_idx > 0:
                prev_close = float(bars["close"][bar_idx - 1])
                if prev_close > 0 and (bar["close"] - prev_close) / prev_close <= LIMIT_DOWN_PCT:
                    return

        exit_price = bar["close"]
        exit_shares = int(pos.shares * exit_pct / MIN_LOT) * MIN_LOT
        if exit_shares <= 0:
            exit_shares = pos.shares

        pnl_amount = exit_shares * (exit_price - pos.entry_price)
        pnl_pct = (exit_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0

        self.cash += exit_shares * exit_price

        self.trades.append(
            Trade(
                stock_code=stock_code,
                entry_date=pos.entry_date,
                entry_price=pos.entry_price,
                exit_date=date_str,
                exit_price=exit_price,
                shares=exit_shares,
                hold_days=pos.hold_days,
                pnl_pct=pnl_pct,
                pnl_amount=pnl_amount,
                exit_reason=reason,
                exit_type=exit_type,
                strategy=self.strategy,
                half_exited=(exit_pct == 0.5),
            )
        )

        if exit_pct >= 1.0 or exit_shares >= pos.shares:
            del self.positions[stock_code]
        else:
            pos.shares -= exit_shares
            pos.half_exited = True

    def _scan_and_queue_signals(self, date_str: str) -> None:
        """扫描信号并加入待执行队列。"""
        if len(self.positions) >= self.max_positions:
            return

        signals = self.scan_signals_for_date(date_str)
        slots = self.max_positions - len(self.positions)

        for sig in signals[:slots]:
            if any(p["stock_code"] == sig["stock_code"] for p in self.pending_signals):
                continue
            if sig["stock_code"] in self.positions:
                continue
            self.pending_signals.append(sig)

    def _compute_financing_cost(self) -> float:
        """计算当日融资成本。"""
        if self.leverage <= 1.0:
            return 0.0

        positions_value = sum(pos.current_value for pos in self.positions.values())
        if positions_value <= 0:
            return 0.0

        own_capital = positions_value / self.leverage
        borrowed = positions_value - own_capital
        if borrowed <= 0:
            return 0.0

        daily_rate = self.financing_rate / TRADING_DAYS_PER_YEAR
        return borrowed * daily_rate

    def _liquidate_all(self, date_str: str, reason: str) -> None:
        """强制清仓所有持仓。"""
        for stock_code in list(self.positions.keys()):
            self._execute_exit(stock_code, date_str, reason, "liquidation", 1.0)


# ===========================================================================
# 兼容函数（保留原有接口）
# ===========================================================================


def _date_range(start: date, end: date):
    """生成日期范围迭代器。"""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def build_indicator_ctx(
    stock_code: str,
    date_str: str,
    bars: list[dict[str, Any]],
    indicators: dict[str, Any],
    states: dict[str, Any],
) -> dict[str, Any]:
    """为信号生成构建完整的指标上下文（保留兼容接口）。"""
    ctx: dict[str, Any] = {}
    ind = indicators.get(stock_code, {}).get(date_str, {})
    ctx.update(
        {
            "atr14": ind.get("atr14") or 0,
            "volume": ind.get("volume") or 0,
            "prev_close": ind.get("prev_close") or 0,
            "bb_middle": ind.get("bb_middle_20") or 0,
            "bb_std": ind.get("bb_std_20") or 0,
        }
    )
    st = states.get(stock_code, {}).get(date_str, {})
    ctx.update(
        {
            "d1_trend": st.get("d1_trend", ""),
            "d1_volatility": st.get("d1_volatility", ""),
            "d1_compression": st.get("d1_compression", ""),
        }
    )
    bar_idx = next((i for i, b in enumerate(bars) if b["date"] == date_str), None)
    if bar_idx is None:
        return ctx
    closes = [b["close"] for b in bars[: bar_idx + 1]]
    volumes = [b["volume"] for b in bars[: bar_idx + 1]]
    if len(closes) >= 15:
        ctx["atr14_5d_ago"] = _compute_atr_from_closes(closes[-10:-5])
        ctx["atr14_10d_ago"] = _compute_atr_from_closes(closes[-15:-10])
    if len(closes) >= 5:
        ctx["high_5d"] = max(b["high"] for b in bars[max(0, bar_idx - 4) : bar_idx + 1])
        ctx["low_5d"] = min(b["low"] for b in bars[max(0, bar_idx - 4) : bar_idx + 1])
    if len(closes) >= 10:
        ctx["high_10d"] = max(b["high"] for b in bars[max(0, bar_idx - 9) : bar_idx + 1])
        ctx["low_10d"] = min(b["low"] for b in bars[max(0, bar_idx - 9) : bar_idx + 1])
    if len(closes) >= 20:
        ctx["high_20d"] = max(b["high"] for b in bars[max(0, bar_idx - 19) : bar_idx + 1])
        ctx["low_20d"] = min(b["low"] for b in bars[max(0, bar_idx - 19) : bar_idx + 1])
    if len(volumes) >= 50:
        ctx["volume_ma_50"] = sum(volumes[-50:]) / 50
    if len(volumes) >= 20:
        ctx["volume_ma20"] = sum(volumes[-20:]) / 20
    if len(closes) >= 31:
        ctx["close_30_ago"] = closes[-31]
    if len(closes) >= 25:
        ctx["ma25"] = sum(closes[-25:]) / 25
        ctx["ma25_prev"] = sum(closes[-26:-1]) / 25 if len(closes) >= 26 else ctx["ma25"]
    if len(closes) >= 60:
        ctx["ma60"] = sum(closes[-60:]) / 60
        ctx["ma60_prev"] = sum(closes[-61:-1]) / 60 if len(closes) >= 61 else ctx["ma60"]
    if len(closes) >= 50:
        window_50 = closes[-50:]
        mean_50 = sum(window_50) / 50
        std_50 = (sum((c - mean_50) ** 2 for c in window_50) / 50) ** 0.5
        ctx["bb_upper_50_1"] = mean_50 + std_50
        ctx["bb_middle_50"] = mean_50
        if len(closes) >= 51:
            prev_window = closes[-51:-1]
            prev_mean = sum(prev_window) / 50
            prev_std = (sum((c - prev_mean) ** 2 for c in prev_window) / 50) ** 0.5
            ctx["bb_upper_50_1_prev"] = prev_mean + prev_std
    return ctx


def _compute_atr_from_closes(closes: list[float]) -> float:
    if len(closes) < 2:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        trs.append(abs(closes[i] - closes[i - 1]))
    return sum(trs) / len(trs) if trs else 0.0


def confirm_entry(
    strategy: str,
    signal: dict[str, Any],
    next_day_bar: dict[str, Any] | None,
) -> tuple[bool, str, dict[str, Any]]:
    """确认入场信号（保留兼容接口）。"""
    if next_day_bar is None:
        return False, "无次日数据", {}

    entry_price = next_day_bar["open"]
    prev_close = signal["close"]

    if prev_close > 0 and (entry_price - prev_close) / prev_close >= LIMIT_UP_PCT:
        return False, f"次日涨停开盘({(entry_price - prev_close) / prev_close:.1%})，无法买入", {}

    ctx = signal.get("ctx", {})

    if strategy == "vcp":
        from scripts.vcp_exit_manager import vcp_entry_confirmation

        confirmation = vcp_entry_confirmation(next_day_bar, ctx)
        if not confirmation["confirmed"]:
            return False, confirmation["rejection_reason"], {}
        stops = compute_vcp_stop_prices(entry_price, ctx)
        return (
            True,
            "",
            {
                "entry_price": entry_price,
                "pivot_point": stops["pivot_point"],
                "contraction_low": stops["contraction_low"],
                "entry_atr": stops["entry_atr"],
                "stop_price": stops["conservative_stop"],
                "signal_confidence": signal["confidence"],
            },
        )

    elif strategy == "ma2560":
        from scripts.ma2560_execution_manager import ma2560_full_entry_check

        enriched_ctx = dict(ctx)
        if "volume_ma5" not in enriched_ctx or not enriched_ctx["volume_ma5"]:
            enriched_ctx["volume_ma5"] = ctx.get("volume_ma20", signal.get("volume", 0))
        if "volume_ma60" not in enriched_ctx or not enriched_ctx["volume_ma60"]:
            enriched_ctx["volume_ma60"] = ctx.get("volume_ma20", signal.get("volume", 0)) * 1.2
        if "vol5_cross_vol60_days" not in enriched_ctx:
            enriched_ctx["vol5_cross_vol60_days"] = 1
        if "vol5_above_vol60_streak" not in enriched_ctx:
            enriched_ctx["vol5_above_vol60_streak"] = 3
        check = ma2560_full_entry_check(next_day_bar, enriched_ctx)
        if not check["confirmed"]:
            return False, check["rejection_reason"], {}
        return (
            True,
            "",
            {
                "entry_price": entry_price,
                "signal_confidence": signal["confidence"],
            },
        )

    elif strategy == "bollinger_bandit":
        from scripts.bollinger_execution_manager import bb_entry_confirmation

        confirmation = bb_entry_confirmation(next_day_bar, ctx)
        if not confirmation["confirmed"]:
            return False, confirmation["rejection_reason"], {}
        return (
            True,
            "",
            {
                "entry_price": entry_price,
                "entry_atr": ctx.get("atr14", entry_price * 0.03),
                "signal_confidence": signal["confidence"],
            },
        )

    elif strategy == "atr_chandelier":
        # ATR Chandelier 是纯 State 过滤策略，无需额外技术指标确认
        # 但需要计算 entry ATR(20) 用于后续出场
        atr = ctx.get("atr14", entry_price * 0.03)
        return (
            True,
            "",
            {
                "entry_price": entry_price,
                "entry_atr": atr,
                "signal_confidence": signal["confidence"],
            },
        )

    return False, "未知策略", {}


# ===========================================================================
# 绩效计算与报告生成（保留原有实现）
# ===========================================================================


def calculate_performance(
    records: list[DailyRecord], trades: list[Trade], initial_capital: float
) -> dict[str, Any]:
    """计算回测绩效指标。"""
    if not records:
        return {}

    values = np.array([r.total_value for r in records], dtype=np.float64)
    dates = [r.date for r in records]

    returns = np.diff(values) / values[:-1]

    total_return = (values[-1] - initial_capital) / initial_capital
    num_years = len(values) / TRADING_DAYS_PER_YEAR
    annual_return = (1 + total_return) ** (1 / max(num_years, 0.01)) - 1 if total_return > -1 else -1

    # 最大回撤（向量化）
    peak = np.maximum.accumulate(values)
    drawdowns = (peak - values) / peak
    max_drawdown = float(np.max(drawdowns))
    max_dd_end_idx = int(np.argmax(drawdowns))
    max_dd_end = dates[max_dd_end_idx]

    # 夏普比率
    if len(returns) > 0:
        avg_return = float(np.mean(returns))
        std_return = float(np.std(returns, ddof=1))
        daily_rf = RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
        sharpe = (
            ((avg_return - daily_rf) / std_return * math.sqrt(TRADING_DAYS_PER_YEAR)) if std_return > 0 else 0
        )
    else:
        sharpe = 0.0

    winning_trades = [t for t in trades if t.pnl_amount > 0]
    losing_trades = [t for t in trades if t.pnl_amount < 0]
    win_rate = len(winning_trades) / len(trades) if trades else 0
    avg_win = np.mean([t.pnl_amount for t in winning_trades]) if winning_trades else 0
    avg_loss = abs(np.mean([t.pnl_amount for t in losing_trades])) if losing_trades else 1
    profit_factor = avg_win / avg_loss if avg_loss > 0 else 0

    # 月度收益（向量化）
    month_keys = np.array([d[:7] for d in dates[1:]])
    unique_months = np.unique(month_keys)
    monthly_summary = {}
    for mk in unique_months:
        mask = month_keys == mk
        month_returns = returns[mask]
        month_start_mask = np.array([d.startswith(mk) for d in dates])
        month_start = values[month_start_mask][0]
        month_end_mask = np.array([d.startswith(mk) for d in dates])
        month_end = values[month_end_mask][-1]
        monthly_summary[mk] = {
            "return": (month_end - month_start) / month_start if month_start > 0 else 0,
            "num_days": int(len(month_returns)),
        }

    total_financing_cost = sum(r.financing_cost for r in records)

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_trades": len(trades),
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
        "avg_win": float(avg_win),
        "avg_loss": float(avg_loss),
        "total_financing_cost": total_financing_cost,
        "final_value": float(values[-1]),
        "monthly_summary": monthly_summary,
        "daily_values": [(r.date, float(r.total_value)) for r in records],
    }


def generate_report(
    strategy: str,
    performance: dict[str, Any],
    trades: list[Trade],
    leverage: float,
    initial_capital: float,
    output_path: str,
) -> None:
    """生成分策略 Markdown 报告。"""
    lines = [
        f"# {strategy.upper()} 策略回测报告（{leverage} 倍杠杆）",
        "",
        f"- **回测区间**: {performance.get('daily_values', [['', '']])[0][0]} ~ {performance.get('daily_values', [['', '']])[-1][0]}",
        f"- **初始资金**: {initial_capital:,.0f}",
        f"- **杠杆倍数**: {leverage}x",
        f"- **融资利率**: {FINANCING_RATE:.0%} 年化",
        "",
        "## 绩效概览",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 总收益率 | {performance['total_return']:.2%} |",
        f"| 年化收益率 | {performance['annual_return']:.2%} |",
        f"| 最大回撤 | {performance['max_drawdown']:.2%} |",
        f"| 夏普比率 | {performance['sharpe_ratio']:.2f} |",
        f"| 胜率 | {performance['win_rate']:.1%} |",
        f"| 盈亏比 | {performance['profit_factor']:.2f} |",
        f"| 总交易次数 | {performance['total_trades']} |",
        f"| 盈利交易 | {performance['winning_trades']} |",
        f"| 亏损交易 | {performance['losing_trades']} |",
        f"| 最终净值 | {performance['final_value']:,.0f} |",
        f"| 累计融资成本 | {performance['total_financing_cost']:,.2f} |",
        "",
        "## 杠杆风险分析",
        "",
        f"- **累计融资成本**: {performance['total_financing_cost']:,.2f}（占初始资金 {performance['total_financing_cost'] / initial_capital:.2%}）",
        f"- **最大回撤**: {performance['max_drawdown']:.2%}",
    ]

    if performance["max_drawdown"] > 0.30:
        lines.append("- **⚠️ 警告**: 最大回撤超过 30%，曾触发或接近强制清仓线")
    else:
        lines.append("- **✅ 风险可控**: 最大回撤未触发强制清仓线（30%）")

    lines.extend(
        [
            "",
            "## 月度收益分布",
            "",
            "| 月份 | 收益率 | 交易日 |",
            "|------|--------|--------|",
        ]
    )

    for month, data in sorted(performance.get("monthly_summary", {}).items()):
        lines.append(f"| {month} | {data['return']:+.2%} | {data['num_days']} |")

    lines.extend(
        [
            "",
            "## 完整交易记录",
            "",
            "| 股票 | 入场日 | 入场价 | 出场日 | 出场价 | 持仓天数 | 盈亏% | 盈亏额 | 出场原因 |",
            "|------|--------|--------|--------|--------|----------|-------|--------|----------|",
        ]
    )

    for t in trades:
        lines.append(
            f"| {t.stock_code} | {t.entry_date} | {t.entry_price:.2f} | "
            f"{t.exit_date or '持有中'} | {t.exit_price or t.current_price:.2f} | "
            f"{t.hold_days} | {t.pnl_pct:+.2%} | {t.pnl_amount:+,.2f} | {t.exit_reason} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("*本报告仅供研究参考，不构成投资建议。*")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"  报告已保存: {output_path}")


def save_equity_csv(performance: dict[str, Any], output_path: str) -> None:
    """保存净值曲线 CSV。"""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "total_value"])
        for date_str, value in performance.get("daily_values", []):
            writer.writerow([date_str, f"{value:.2f}"])
    print(f"  净值曲线已保存: {output_path}")


def generate_comparison_report(
    results: dict[str, dict[str, Any]],
    output_path: str,
) -> None:
    """生成四策略对比报告。"""
    lines = [
        "# 四策略杠杆回测对比报告（1.6x）",
        "",
        "## 绩效对比表",
        "",
        "| 策略 | 总收益率 | 年化收益 | 最大回撤 | 夏普比率 | 胜率 | 盈亏比 | 交易次数 | 最终净值 | 融资成本 |",
        "|------|----------|----------|----------|----------|------|--------|----------|----------|----------|",
    ]

    sorted_strategies = sorted(results.items(), key=lambda x: x[1].get("annual_return", 0), reverse=True)

    for strategy, perf in sorted_strategies:
        lines.append(
            f"| {strategy.upper()} | {perf['total_return']:.2%} | {perf['annual_return']:.2%} | "
            f"{perf['max_drawdown']:.2%} | {perf['sharpe_ratio']:.2f} | {perf['win_rate']:.1%} | "
            f"{perf['profit_factor']:.2f} | {perf['total_trades']} | {perf['final_value']:,.0f} | "
            f"{perf['total_financing_cost']:,.0f} |"
        )

    lines.extend(
        [
            "",
            "## 最优策略",
            f"- **收益最高**: {sorted_strategies[0][0].upper()}（年化 {sorted_strategies[0][1]['annual_return']:.2%}）",
            "",
            "## 风险排名（按最大回撤）",
        ]
    )

    risk_ranked = sorted(results.items(), key=lambda x: x[1].get("max_drawdown", 0))
    for i, (strategy, perf) in enumerate(risk_ranked, 1):
        lines.append(f"{i}. {strategy.upper()}: 最大回撤 {perf['max_drawdown']:.2%}")

    lines.extend(
        [
            "",
            "## 综合评分",
            "",
            "综合评分 = 年化收益 × 0.4 + 夏普比率 × 0.3 + (1 - 最大回撤) × 0.3",
            "",
            "| 策略 | 综合评分 |",
            "|------|----------|",
        ]
    )

    for strategy, perf in sorted_strategies:
        score = perf["annual_return"] * 0.4 + perf["sharpe_ratio"] * 0.3 + (1 - perf["max_drawdown"]) * 0.3
        lines.append(f"| {strategy.upper()} | {score:.3f} |")

    lines.append("")
    lines.append("---")
    lines.append("*本报告仅供研究参考，不构成投资建议。*")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"  对比报告已保存: {output_path}")


def generate_chain_filter_report(
    results: dict[str, dict[str, Any]],
    trades_by_strategy: dict[str, list[Trade]],
    chain_filtered_by_strategy: dict[str, int],
    output_path: str,
) -> None:
    """生成产业链景气度过滤影响报告。"""
    lines = [
        "# 产业链景气度过滤对回测结果的影响",
        "",
        "## 概述",
        "",
        "本报告对比回测中应用产业链景气度过滤前后的信号差异。",
        "过滤规则：若某股票所属申万一级行业的景气度评级为 `low`，则该入场信号被拦截。",
        "三重共振加成：基于 prosperity_score 计算产业链加成系数（0.80–1.20），",
        "作用于仓位分配比例。",
        "",
        "## 各策略过滤统计",
        "",
        "| 策略 | 被拦截信号数 | 实际成交数 | 拦截率 | 平均 chain_factor |",
        "|------|-------------|-----------|--------|------------------|",
    ]

    for strategy in ["vcp", "ma2560", "bollinger_bandit", "atr_chandelier"]:
        trades = trades_by_strategy.get(strategy, [])
        filtered = chain_filtered_by_strategy.get(strategy, 0)
        executed = len(trades)
        total_signals = filtered + executed
        filter_rate = filtered / total_signals if total_signals > 0 else 0.0
        avg_factor = sum(getattr(t, "chain_factor", 1.0) for t in trades) / len(trades) if trades else 1.0
        lines.append(
            f"| {strategy.upper()} | {filtered} | {executed} | {filter_rate:.1%} | {avg_factor:.3f} |"
        )

    lines.extend(
        [
            "",
            "## 产业链加成系数分布（实际成交）",
            "",
            "| 区间 | VCP | 2560 | 布林强盗 | ATR吊灯 |",
            "|------|-----|------|----------|---------|",
        ]
    )

    bins = [(0.80, 0.90), (0.90, 0.98), (0.98, 1.02), (1.02, 1.10), (1.10, 1.20)]
    for lo, hi in bins:
        counts = []
        for strategy in ["vcp", "ma2560", "bollinger_bandit", "atr_chandelier"]:
            trades = trades_by_strategy.get(strategy, [])
            c = sum(1 for t in trades if lo <= getattr(t, "chain_factor", 1.0) < hi)
            counts.append(c)
        lines.append(f"| [{lo:.2f}, {hi:.2f}) | {counts[0]} | {counts[1]} | {counts[2]} | {counts[3]} |")

    lines.extend(
        [
            "",
            "## 绩效影响",
            "",
            "| 策略 | 总收益率 | 年化收益 | 最大回撤 | 夏普比率 | 交易次数 |",
            "|------|----------|----------|----------|----------|----------|",
        ]
    )

    for strategy, perf in sorted(results.items()):
        lines.append(
            f"| {strategy.upper()} | {perf['total_return']:.2%} | {perf['annual_return']:.2%} | "
            f"{perf['max_drawdown']:.2%} | {perf['sharpe_ratio']:.2f} | {perf['total_trades']} |"
        )

    lines.extend(
        [
            "",
            "## 结论",
            "",
            "- 产业链 `low` 评级过滤拦截了部分信号，避免了在景气低迷行业中开仓。",
            "- 产业链加成系数使高景气行业（high/medium）获得更高仓位，低景气行业获得更低仓位。",
            "- 三重共振模型将宏观、产业链、State 三个维度统一，信号在三层同向时获得加成。",
            "",
            "---",
            "*本报告仅供研究参考，不构成投资建议。*",
        ]
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"  产业链过滤影响报告已保存: {output_path}")


# ===========================================================================
# 并行回测 worker
# ===========================================================================


def _run_single_strategy(args: tuple) -> dict[str, Any]:
    """多进程 worker：运行单个策略回测。"""
    (
        strategy,
        start_date,
        end_date,
        initial_capital,
        leverage,
        max_positions,
        financing_rate,
        data_store_dict,
    ) = args

    # 重新构建 data_store（不能跨进程传递复杂对象）
    # 实际上我们让主进程加载数据，每个策略复用同一个 data_store 实例
    # 这里采用更简单的方式：主进程加载数据，worker 接收序列化后的参数
    # 但由于 data_store 很大，我们改用"主进程加载，子进程共享引用"不可行（multiprocessing 会拷贝）
    # 优化方案：主进程加载 data_store，通过 global 变量或文件共享
    pass


# 全局变量用于多进程共享数据
_global_data_store: VectorizedDataStore | None = None
_global_enable_macro_filter: bool = True


def _init_worker(data_store: VectorizedDataStore, enable_macro_filter: bool = True) -> None:
    """多进程 worker 初始化函数。"""
    global _global_data_store, _global_enable_macro_filter
    _global_data_store = data_store
    _global_enable_macro_filter = enable_macro_filter


def _run_strategy_worker(args: tuple) -> tuple[str, dict[str, Any], list[Trade], list[DailyRecord], int, int]:
    """多进程 worker：运行单个策略。"""
    strategy, start_date, end_date, initial_capital, leverage, max_positions, financing_rate = args

    engine = LeveragedBacktestEngine(
        strategy=strategy,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        leverage=leverage,
        max_positions=max_positions,
        financing_rate=financing_rate,
        data_store=_global_data_store,
    )
    engine.enable_macro_filter = _global_enable_macro_filter
    engine.load_data()
    engine.run()

    perf = calculate_performance(engine.daily_records, engine.trades, initial_capital)
    return (
        strategy,
        perf,
        engine.trades,
        engine.daily_records,
        engine.chain_filtered_count,
        engine.macro_filtered_count,
    )


# ===========================================================================
# 主入口
# ===========================================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="A股四策略独立回测（支持杠杆）— 高性能优化版")
    parser.add_argument("--strategy", choices=["vcp", "ma2560", "bollinger_bandit", "atr_chandelier"])
    parser.add_argument("--start-date", default="2023-05-22")
    parser.add_argument("--end-date", default="2026-05-22")
    parser.add_argument("--initial-capital", type=float, default=1_000_000)
    parser.add_argument("--leverage", type=float, default=1.6)
    parser.add_argument("--max-positions", type=int, default=8)
    parser.add_argument("--financing-rate", type=float, default=FINANCING_RATE)
    parser.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR))
    parser.add_argument("--run-all", action="store_true", help="运行所有四个策略并生成对比报告")
    parser.add_argument("--workers", type=int, default=min(4, cpu_count()), help="并行进程数（默认4）")
    parser.add_argument("--benchmark", action="store_true", help="输出性能基准测试报告")
    parser.add_argument("--no-macro-filter", action="store_true", help="禁用指数/ETF月线MN1宏观环境过滤")

    args = parser.parse_args()

    if not args.run_all and not args.strategy:
        parser.error("--strategy 是必需的（除非使用 --run-all）")

    os.makedirs(args.output_dir, exist_ok=True)

    import time

    total_start = time.perf_counter()

    if args.run_all:
        strategies = ["vcp", "ma2560", "bollinger_bandit", "atr_chandelier"]
        all_results: dict[str, dict[str, Any]] = {}

        # 先加载共享数据（一次 DuckDB 连接）
        print("=" * 60)
        print("预加载数据（单次 DuckDB 连接）...")
        data_load_start = time.perf_counter()
        shared_data = VectorizedDataStore(str(FOUNDATION_DB), args.start_date, args.end_date)
        shared_data.load_all()
        data_load_elapsed = time.perf_counter() - data_load_start
        print(f"数据加载完成: {data_load_elapsed:.2f}s")
        print("=" * 60)

        # 使用多进程并行跑四策略
        pool_start = time.perf_counter()
        worker_args = [
            (
                s,
                args.start_date,
                args.end_date,
                args.initial_capital,
                args.leverage,
                args.max_positions,
                args.financing_rate,
            )
            for s in strategies
        ]

        with Pool(
            processes=args.workers, initializer=_init_worker, initargs=(shared_data, not args.no_macro_filter)
        ) as pool:
            results = pool.map(_run_strategy_worker, worker_args)

        pool_elapsed = time.perf_counter() - pool_start
        print(f"\n四策略并行回测完成: {pool_elapsed:.2f}s")

        trades_by_strategy: dict[str, list[Trade]] = {}
        chain_filtered_by_strategy: dict[str, int] = {}
        for strategy, perf, trades, records, chain_filtered, macro_filtered in results:
            all_results[strategy] = perf
            trades_by_strategy[strategy] = trades
            chain_filtered_by_strategy[strategy] = chain_filtered

            report_path = os.path.join(args.output_dir, f"backtest_{strategy}_{args.leverage}x.md")
            generate_report(strategy, perf, trades, args.leverage, args.initial_capital, report_path)

            csv_path = os.path.join(args.output_dir, f"equity_{strategy}_{args.leverage}x.csv")
            save_equity_csv(perf, csv_path)

        # 生成对比报告
        comparison_path = os.path.join(args.output_dir, "four_strategies_leverage_comparison.md")
        generate_comparison_report(all_results, comparison_path)

        # 生成产业链过滤影响报告
        chain_filter_path = os.path.join(args.output_dir, "chain_filter_impact.md")
        generate_chain_filter_report(
            all_results, trades_by_strategy, chain_filtered_by_strategy, chain_filter_path
        )

        total_elapsed = time.perf_counter() - total_start
        print("\n" + "=" * 60)
        print("所有策略回测完成！")
        print(f"总耗时: {total_elapsed:.2f}s")
        print(f"输出目录: {args.output_dir}")

        # 性能基准报告
        if args.benchmark:
            benchmark_path = os.path.join(args.output_dir, "performance_benchmark.md")
            with open(benchmark_path, "w", encoding="utf-8") as f:
                f.write(
                    f"# 回测性能基准报告\n\n"
                    f"- **数据加载耗时**: {data_load_elapsed:.2f}s\n"
                    f"- **四策略并行回测耗时**: {pool_elapsed:.2f}s\n"
                    f"- **总耗时**: {total_elapsed:.2f}s\n"
                    f"- **并行进程数**: {args.workers}\n"
                    f"- **股票数量**: {len(shared_data.stock_codes)}\n"
                    f"- **交易日数量**: {len(shared_data.dates)}\n"
                    f"- **回测区间**: {args.start_date} ~ {args.end_date}\n"
                    f"- **杠杆倍数**: {args.leverage}x\n\n"
                    f"## 优化项\n\n"
                    f"1. **Numba JIT 加速**: 核心信号扫描和出场检查使用 `@njit` 编译\n"
                    f"2. **多进程并行**: 使用 `multiprocessing.Pool` 同时运行四策略\n"
                    f"3. **DuckDB 单次连接**: 数据加载使用单次连接 + SQL 预聚合\n"
                    f"4. **技术指标预计算**: MA/布林带/ATR 等在一次遍历中向量化计算\n"
                )
            print(f"性能基准报告已保存: {benchmark_path}")

    else:
        engine = LeveragedBacktestEngine(
            strategy=args.strategy,
            start_date=args.start_date,
            end_date=args.end_date,
            initial_capital=args.initial_capital,
            leverage=args.leverage,
            max_positions=args.max_positions,
            financing_rate=args.financing_rate,
        )
        engine.enable_macro_filter = not args.no_macro_filter
        engine.load_data()
        engine.run()

        perf = calculate_performance(engine.daily_records, engine.trades, args.initial_capital)

        report_path = os.path.join(args.output_dir, f"backtest_{args.strategy}_{args.leverage}x.md")
        generate_report(args.strategy, perf, engine.trades, args.leverage, args.initial_capital, report_path)

        csv_path = os.path.join(args.output_dir, f"equity_{args.strategy}_{args.leverage}x.csv")
        save_equity_csv(perf, csv_path)

        # 产业链过滤影响报告（单策略）
        chain_filter_path = os.path.join(args.output_dir, "chain_filter_impact.md")
        generate_chain_filter_report(
            {args.strategy: perf},
            {args.strategy: engine.trades},
            {args.strategy: engine.chain_filtered_count},
            chain_filter_path,
        )

        total_elapsed = time.perf_counter() - total_start
        print(f"\n回测完成！总耗时: {total_elapsed:.2f}s")
        print(f"报告: {report_path}")


if __name__ == "__main__":
    main()
