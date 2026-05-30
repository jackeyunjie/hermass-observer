#!/usr/bin/env python3
"""US stock strategy signal adapter.

Adapts A-share strategy signal modules (backtest/strategy_signals/) to work
with US stock data from us_foundation.duckdb. Reuses all strategy logic;
only data format mapping differs.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from backtest.strategy_signals.vcp import vcp_signal
from backtest.strategy_signals.ma2560 import ma2560_signal
from backtest.strategy_signals.bollinger_bandit import bollinger_bandit_signal
from strategy_signal_ledger import compute_environment_fit

US_FOUNDATION_DB = ROOT / "outputs" / "us_stock" / "us_foundation.duckdb"

SIGNAL_META = {
    "vcp_breakout": ("vcp", "entry", "VCP Breakout"),
    "vcp_breakout_weak_vol": ("vcp", "entry", "VCP Weak Volume Breakout"),
    "vcp_breakout_no_vol": ("vcp", "entry", "VCP No Volume Breakout"),
    "vcp_contraction": ("vcp", "structure", "VCP Contraction"),
    "vcp_early_contraction": ("vcp", "structure", "VCP Early Contraction"),
    "ma2560_golden_cross": ("ma2560", "entry", "2560 Golden Cross"),
    "ma2560_strong_hold": ("ma2560", "structure", "2560 Strong Hold"),
    "ma2560_aligned": ("ma2560", "structure", "2560 Aligned"),
    "ma2560_death_cross_exit": ("ma2560", "exit", "2560 Death Cross"),
    "ma2560_bearish": ("ma2560", "risk", "2560 Bearish"),
    "bb_bandit_long_entry": ("bollinger_bandit", "entry", "Bollinger Bandit Long"),
}


def load_us_daily_with_indicators(
    foundation_db: Path,
    target_date: str,
) -> list[dict[str, Any]]:
    """Load US stock daily data with all indicators for a given date.

    Returns rows in the format expected by backtest/strategy_signals/ functions.
    """
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        rows = con.execute(
            """
            WITH daily AS (
                SELECT stock_code, date, open, high, low, close, volume
                FROM daily_bars
                WHERE date = CAST(? AS DATE)
            ),
            state AS (
                SELECT stock_code, state_date,
                       mn1_state_hex, w1_state_hex, d1_state_hex,
                       mn1_state_score, w1_state_score, d1_state_score,
                       ef_count,
                       d1_trend, d1_base, d1_trend_bit, d1_position_bit, d1_volatility_bit,
                       w1_base, w1_trend_bit, w1_position_bit, w1_volatility_bit,
                       mn1_base, mn1_trend_bit, mn1_position_bit, mn1_volatility_bit,
                       d1_adx14, d1_plus_di_14, d1_minus_di_14,
                       d1_bb_width_pct, d1_atr_ratio_pct
                FROM d1_perspective_state
                WHERE state_date = CAST(? AS DATE)
            )
            SELECT d.stock_code, d.date, d.open, d.high, d.low, d.close, d.volume,
                   s.mn1_state_hex, s.w1_state_hex, s.d1_state_hex,
                   s.mn1_state_score, s.w1_state_score, s.d1_state_score,
                   s.ef_count,
                   s.d1_trend, s.d1_base, s.d1_trend_bit, s.d1_position_bit, s.d1_volatility_bit,
                   s.d1_adx14, s.d1_plus_di_14, s.d1_minus_di_14,
                   s.d1_bb_width_pct, s.d1_atr_ratio_pct
            FROM daily d
            JOIN state s ON d.stock_code = s.stock_code
            WHERE d.close > 0 AND d.volume > 0
            ORDER BY d.stock_code
            """,
            (target_date, target_date),
        ).fetchall()

        cols = [desc[0] for desc in con.execute("SELECT 1").description]
        # Get column names from the actual query
        cur = con.execute(
            """
            WITH daily AS (
                SELECT stock_code, date, open, high, low, close, volume
                FROM daily_bars WHERE date = CAST(? AS DATE)
            ),
            state AS (
                SELECT * FROM d1_perspective_state WHERE state_date = CAST(? AS DATE)
            )
            SELECT d.stock_code, d.date, d.open, d.high, d.low, d.close, d.volume,
                   s.mn1_state_hex, s.w1_state_hex, s.d1_state_hex,
                   s.mn1_state_score, s.w1_state_score, s.d1_state_score,
                   s.ef_count,
                   s.d1_trend, s.d1_base, s.d1_trend_bit, s.d1_position_bit, s.d1_volatility_bit,
                   s.d1_adx14, s.d1_plus_di_14, s.d1_minus_di_14,
                   s.d1_bb_width_pct, s.d1_atr_ratio_pct
            FROM daily d
            JOIN state s ON d.stock_code = s.stock_code
            WHERE 1=0
            """,
            (target_date, target_date),
        )
        col_names = [desc[0] for desc in cur.description]

        result = []
        for row in rows:
            d = dict(zip(col_names, row))
            result.append(d)
        return result
    finally:
        con.close()


def build_indicator_context(
    foundation_db: Path,
    stock_code: str,
    target_date: str,
) -> dict[str, Any]:
    """Build the indicator context needed by strategy signal functions.

    Loads MA25, MA50, MA60, BB upper, ATR, volume MAs, etc.
    """
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        # Get recent daily bars for MA calculation
        bars = con.execute(
            """
            SELECT date, open, high, low, close, volume
            FROM daily_bars
            WHERE stock_code = ? AND date <= CAST(? AS DATE)
            ORDER BY date DESC
            LIMIT 120
            """,
            (stock_code, target_date),
        ).fetchall()

        if len(bars) < 60:
            return {}

        bars = list(reversed(bars))  # oldest first
        closes = [b[4] for b in bars]
        volumes = [b[5] for b in bars]

        # Simple MA calculation
        def ma(series, period):
            if len(series) < period:
                return None
            return sum(series[-period:]) / period

        # BB calculation
        def bb_upper(closes, period=50, std_mult=1.0):
            if len(closes) < period:
                return None
            recent = closes[-period:]
            mean = sum(recent) / period
            variance = sum((x - mean) ** 2 for x in recent) / period
            std = variance ** 0.5
            return mean + std_mult * std

        # ATR calculation (simplified)
        def atr(bars, period=20):
            if len(bars) < period + 1:
                return None
            trs = []
            for i in range(-period, 0):
                h = bars[i][2]
                l = bars[i][3]
                pc = bars[i-1][4]
                tr = max(h - l, abs(h - pc), abs(l - pc))
                trs.append(tr)
            return sum(trs) / len(trs)

        ma25 = ma(closes, 25)
        ma50 = ma(closes, 50)
        ma60 = ma(closes, 60)

        # Previous values
        closes_prev = closes[:-1]
        ma25_prev = ma(closes_prev, 25)
        ma60_prev = ma(closes_prev, 60)

        bb_up = bb_upper(closes, 50, 1.0)
        bb_up_prev = bb_upper(closes_prev, 50, 1.0)

        vol_ma5 = ma(volumes, 5)
        vol_ma20 = ma(volumes, 20)
        vol_ma60 = ma(volumes, 60)

        current_atr = atr(bars, 20)

        # VCP-specific indicators
        def atr_for_bars(bars_slice, period=14):
            if len(bars_slice) < period + 1:
                return None
            trs = []
            for i in range(-period, 0):
                h = bars_slice[i][2]
                l = bars_slice[i][3]
                pc = bars_slice[i-1][4]
                tr = max(h - l, abs(h - pc), abs(l - pc))
                trs.append(tr)
            return sum(trs) / len(trs)

        atr14_now = atr_for_bars(bars, 14)
        atr14_5d = atr_for_bars(bars[:-5], 14) if len(bars) > 5 else None
        atr14_10d = atr_for_bars(bars[:-10], 14) if len(bars) > 10 else None

        def high_low_range(bars_slice, days):
            if len(bars_slice) < days:
                return None, None
            recent = bars_slice[-days:]
            return max(b[2] for b in recent), min(b[3] for b in recent)

        high_5d, low_5d = high_low_range(bars[:-1], 5) if len(bars) > 1 else (None, None)
        high_20d, low_20d = high_low_range(bars[:-1], 20) if len(bars) > 1 else (None, None)
        high_10d, _ = high_low_range(bars[:-1], 10) if len(bars) > 1 else (None, None)

        vol_ma50 = ma(volumes, 50)

        # State info
        state = con.execute(
            """
            SELECT * FROM d1_perspective_state
            WHERE stock_code = ? AND state_date = CAST(? AS DATE)
            """,
            (stock_code, target_date),
        ).fetchone()

        state_dict = {}
        if state:
            state_cols = [desc[0] for desc in con.execute(
                "SELECT * FROM d1_perspective_state WHERE 1=0"
            ).description]
            state_dict = dict(zip(state_cols, state))

        # Close 30 days ago (for BB momentum filter)
        close_30_ago = closes[-31] if len(closes) >= 31 else closes[0]

        # Previous close
        prev_close = closes[-2] if len(closes) >= 2 else closes[-1]

        return {
            "close": closes[-1],
            "prev_close": prev_close,
            "close_30_ago": close_30_ago,
            "open": bars[-1][1],
            "high": bars[-1][2],
            "low": bars[-1][3],
            "volume": bars[-1][5],
            "ma25": ma25,
            "ma60": ma60,
            "ma25_prev": ma25_prev,
            "ma60_prev": ma60_prev,
            "bb_upper_50_1": bb_up,
            "bb_upper_50_1_prev": bb_up_prev,
            "volume_ma5": vol_ma5,
            "volume_ma20": vol_ma20,
            "volume_ma60": vol_ma60,
            "volume_ma_50": vol_ma50,
            "atr": current_atr,
            "atr14": atr14_now,
            "atr14_5d_ago": atr14_5d,
            "atr14_10d_ago": atr14_10d,
            "high_5d": high_5d,
            "low_5d": low_5d,
            "high_20d": high_20d,
            "low_20d": low_20d,
            "high_10d": high_10d,
            **state_dict,
        }
    finally:
        con.close()


def compute_us_signals_for_date(
    foundation_db: Path,
    target_date: str,
    min_ef_count: int = 2,
) -> list[dict[str, Any]]:
    """Compute all strategy signals for US stocks on a given date.

    Returns rows compatible with strategy_signal_daily schema.
    """
    daily_rows = load_us_daily_with_indicators(foundation_db, target_date)
    signals = []

    for row in daily_rows:
        ef = row.get("ef_count", 0) or 0
        if ef < min_ef_count:
            continue

        stock_code = row["stock_code"]
        ctx = build_indicator_context(foundation_db, stock_code, target_date)
        if not ctx:
            continue

        # Merge row data into ctx for strategy functions
        ctx["date"] = target_date
        ctx["stock_code"] = stock_code

        # Run each strategy
        for source_module, fn in [
            ("backtest.strategy_signals.vcp", vcp_signal),
            ("backtest.strategy_signals.ma2560", ma2560_signal),
            ("backtest.strategy_signals.bollinger_bandit", bollinger_bandit_signal),
        ]:
            result = fn(ctx, ctx)
            if not result:
                continue
            raw_signal, strength = result
            meta = SIGNAL_META.get(raw_signal)
            if not meta:
                continue
            strategy_id, signal_type, signal_name = meta

            signals.append({
                "signal_date": target_date,
                "stock_code": stock_code,
                "strategy_id": strategy_id,
                "signal_type": signal_type,
                "signal_name": signal_name,
                "signal_strength": float(strength or 0),
                "raw_signal": raw_signal,
                "source_module": source_module,
                "ef_count": ef,
                "mn1_state_hex": row.get("mn1_state_hex"),
                "w1_state_hex": row.get("w1_state_hex"),
                "d1_state_hex": row.get("d1_state_hex"),
                "mn1_state_score": row.get("mn1_state_score"),
                "w1_state_score": row.get("w1_state_score"),
                "d1_state_score": row.get("d1_state_score"),
            })

    return signals


# ---------------------------------------------------------------------------
# 核心模块过滤 — 生命周期推断 + Environment Fit + 空间评估
# ---------------------------------------------------------------------------

def compute_us_lifecycle_stage(state_row: dict[str, Any]) -> tuple[str, list[str]]:
    """基于美股 d1_perspective_state 现有字段推断生命周期阶段。

    美股 DB 没有 duration 字段（d1_days_since_contraction_exit 等），
    因此基于 d1_trend + d1_volatility_bit + ef_count 做近似推断。
    """
    reasons: list[str] = []
    d1_trend = state_row.get("d1_trend", "")
    d1_volatility_bit = state_row.get("d1_volatility_bit", 0) or 0
    ef_count = state_row.get("ef_count", 0) or 0

    # 新生：趋势启动且波动不活跃
    if d1_trend == "bull_start":
        reasons.append(f"D1趋势启动({d1_trend})")
        if d1_volatility_bit != 1:
            reasons.append("波动不活跃")
            return "新生", reasons

    # 延展：趋势上行且波动活跃，或 ef_count 高但波动放大
    if d1_trend == "bull_trend" and d1_volatility_bit == 1:
        reasons.append("D1趋势上行, 波动活跃")
        return "延展", reasons

    # 行进：趋势上行且波动稳定，ef_count >= 2
    if d1_trend == "bull_trend" and d1_volatility_bit == 0 and ef_count >= 2:
        reasons.append(f"D1趋势上行, 波动稳定, ef_count={ef_count}")
        return "行进", reasons

    if d1_trend:
        reasons.append(f"D1趋势={d1_trend}")
    if ef_count:
        reasons.append(f"ef_count={ef_count}")
    return "未知", reasons


def compute_us_market_phase(state_row: dict[str, Any]) -> str:
    """基于 d1_trend 推断市场阶段，用于收缩期/风险释放期过滤。"""
    d1_trend = state_row.get("d1_trend", "")
    d1_base = state_row.get("d1_base", 0) or 0

    if d1_trend in ("bear_trend", "bear_start"):
        return "risk_release"
    if d1_trend in ("closed", "insufficient_history"):
        return "contraction"
    if d1_trend == "neutral" and d1_base == 0:
        return "contraction"
    if d1_trend == "bull_trend":
        return "progression"
    if d1_trend == "bull_start":
        return "emergence"
    return "undetermined"


def compute_us_rr(
    foundation_db: Path,
    stock_code: str,
    target_date: str,
    close: float,
    signal_name: str,
    strategy_id: str = "",
) -> dict[str, Any]:
    """使用 SR 数据 + 策略目标收益法计算 RR。

    修正逻辑：阻力位不是天花板，而是第一关。
    Entry 信号的 upside 基于策略目标收益，而非最近阻力位。
    """
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        row = con.execute(
            """
            SELECT d1_sr_support, d1_sr_resistance, d1_sr_ready
            FROM d1_sr_context
            WHERE stock_code = ? AND state_date = CAST(? AS DATE)
            """,
            (stock_code, target_date),
        ).fetchone()
    finally:
        con.close()

    # ── Downside: 止损空间 ──
    downside_pct = 0.06  # 默认 6% 止损
    support = None
    if row and row[2] and row[0] and close > 0:
        support = float(row[0])
        if support < close:
            downside_pct = (close - support) / close
            # 止损空间不小于 3%、不大于 10%
            downside_pct = max(0.03, min(0.10, downside_pct))

    # ── Upside: 策略目标收益（核心修正）──
    # 阻力位不是用来当天花板的——它是用来被突破的。
    # 策略目标收益反映的是突破后的潜在空间。
    if strategy_id == "vcp":
        upside_pct = 0.15
    elif strategy_id == "ma2560":
        upside_pct = 0.10
    elif strategy_id == "bollinger_bandit":
        upside_pct = 0.12
    else:
        upside_pct = 0.10

    # 如果有 SR 数据，取策略目标收益和阻力空间的较大值
    resistance = None
    if row and row[2] and row[1] and close > 0:
        resistance = float(row[1])
        if resistance > close * 1.001:
            sr_upside = (resistance - close) / close
            # Breakout mode: 阻力已突破或非常接近，看下一个结构位
            is_breakout = "breakout" in signal_name.lower()
            if is_breakout and close > resistance * 0.995:
                # 突破后空间 = channel width (resistance - support)
                if support and support < close:
                    channel_upside = (resistance - support) / close
                    upside_pct = max(upside_pct, channel_upside)
                else:
                    upside_pct = max(upside_pct, sr_upside * 1.5)
            else:
                upside_pct = max(upside_pct, sr_upside)

    rr = upside_pct / downside_pct if downside_pct > 0 else None

    return {
        "rr_ratio": rr,
        "upside_pct": upside_pct,
        "downside_pct": downside_pct,
        "rr_ready": bool(row and row[2]),
        "support": support,
        "resistance": resistance,
        "method": "strategy_target_with_sr",
    }


def compute_enriched_us_signals_for_date(
    foundation_db: Path,
    target_date: str,
    min_ef_count: int = 2,
) -> list[dict[str, Any]]:
    """Compute enriched signals with lifecycle_stage, fit_level, market_phase, rr_ratio."""
    daily_rows = load_us_daily_with_indicators(foundation_db, target_date)
    signals = []

    for row in daily_rows:
        ef = row.get("ef_count", 0) or 0
        if ef < min_ef_count:
            continue

        stock_code = row["stock_code"]
        ctx = build_indicator_context(foundation_db, stock_code, target_date)
        if not ctx:
            continue

        # Merge row data into ctx for strategy functions
        ctx["date"] = target_date
        ctx["stock_code"] = stock_code

        # ── 生命周期推断 + Environment Fit ──
        lifecycle_stage, lifecycle_reasons = compute_us_lifecycle_stage(row)

        # ── 市场阶段推断 ──
        market_phase = compute_us_market_phase(row)

        # ── 空间评估 ──
        close = row.get("close", 0)
        rr_data = compute_us_rr(foundation_db, stock_code, target_date, close, "")

        # Run each strategy
        for source_module, fn in [
            ("backtest.strategy_signals.vcp", vcp_signal),
            ("backtest.strategy_signals.ma2560", ma2560_signal),
            ("backtest.strategy_signals.bollinger_bandit", bollinger_bandit_signal),
        ]:
            result = fn(ctx, ctx)
            if not result:
                continue
            raw_signal, strength = result
            meta = SIGNAL_META.get(raw_signal)
            if not meta:
                continue
            strategy_id, signal_type, signal_name = meta

            # Compute fit_level for this strategy
            fit_level, fit_reasons = compute_environment_fit(
                strategy_id, lifecycle_stage, list(lifecycle_reasons)
            )

            # Compute RR with breakout-aware logic per strategy
            rr_data_strategy = compute_us_rr(
                foundation_db, stock_code, target_date, close, signal_name, strategy_id
            )

            signals.append({
                "signal_date": target_date,
                "stock_code": stock_code,
                "strategy_id": strategy_id,
                "signal_type": signal_type,
                "signal_name": signal_name,
                "signal_strength": float(strength or 0),
                "raw_signal": raw_signal,
                "source_module": source_module,
                "ef_count": ef,
                "mn1_state_hex": row.get("mn1_state_hex"),
                "w1_state_hex": row.get("w1_state_hex"),
                "d1_state_hex": row.get("d1_state_hex"),
                "mn1_state_score": row.get("mn1_state_score"),
                "w1_state_score": row.get("w1_state_score"),
                "d1_state_score": row.get("d1_state_score"),
                # ── 新增核心字段 ──
                "lifecycle_stage": lifecycle_stage,
                "lifecycle_reasons": ";".join(lifecycle_reasons),
                "fit_level": fit_level,
                "fit_reasons": fit_reasons,
                "market_phase": market_phase,
                "rr_ratio": rr_data_strategy.get("rr_ratio"),
                "rr_upside_pct": rr_data_strategy.get("upside_pct"),
                "rr_downside_pct": rr_data_strategy.get("downside_pct"),
                "rr_ready": rr_data_strategy.get("rr_ready"),
            })

    return signals


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--db", default=str(US_FOUNDATION_DB))
    parser.add_argument("--min-ef", type=int, default=2)
    parser.add_argument("--enriched", action="store_true", help="Output enriched signals with fit/phase/rr")
    args = parser.parse_args()

    if args.enriched:
        sigs = compute_enriched_us_signals_for_date(Path(args.db), args.date, args.min_ef)
    else:
        sigs = compute_us_signals_for_date(Path(args.db), args.date, args.min_ef)

    import json
    out = {
        "date": args.date,
        "signal_count": len(sigs),
        "by_strategy": {
            sid: sum(1 for s in sigs if s["strategy_id"] == sid)
            for sid in sorted(set(s["strategy_id"] for s in sigs))
        },
        "by_fit": {},
        "by_phase": {},
        "sample": sigs[:3],
    }
    if sigs and "fit_level" in sigs[0]:
        out["by_fit"] = {
            fl: sum(1 for s in sigs if s.get("fit_level") == fl)
            for fl in sorted(set(s.get("fit_level", "") for s in sigs))
        }
        out["by_phase"] = {
            ph: sum(1 for s in sigs if s.get("market_phase") == ph)
            for ph in sorted(set(s.get("market_phase", "") for s in sigs))
        }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
