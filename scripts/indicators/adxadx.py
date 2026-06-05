"""Python port of StrategyQuant SqADXADX.

The source indicator in ``data/SqADXADX.mq4`` plots two ADX systems at once:

- ADX / +DI / -DI with period 14 by default
- ADXADX / +DIDI / -DIDI with period 30 by default

The implementation below follows the source loop closely, including Wilder-like
recursive smoothing of TR and directional movement sums.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ADXADXConfig:
    adx_period: int = 14
    adxadx_period: int = 30
    slope_bars: int = 3
    level_active: float = 20.0
    level_closed: float = 13.0
    level_dormant: float = 9.0


def _source_period(value: int, fallback: int = 14) -> int:
    """Match source behavior: invalid periods fall back to 14."""
    try:
        period = int(value)
    except (TypeError, ValueError):
        return fallback
    if period >= 100 or period <= 0:
        return fallback
    return period


def _column(df: pd.DataFrame, name: str) -> pd.Series:
    cols = {str(c).lower(): c for c in df.columns}
    if name not in cols:
        raise ValueError(f"Missing required column: {name}")
    return pd.to_numeric(df[cols[name]], errors="coerce").astype(float)


def _round8(value: float) -> float:
    if np.isnan(value):
        return np.nan
    return round(float(value), 8)


def _adx_for_period(high: pd.Series, low: pd.Series, close: pd.Series, period: int, prefix: str) -> pd.DataFrame:
    n = len(close)
    sum_tr = np.zeros(n, dtype=float)
    sum_dm_plus = np.zeros(n, dtype=float)
    sum_dm_minus = np.zeros(n, dtype=float)
    plus_di = np.zeros(n, dtype=float)
    minus_di = np.zeros(n, dtype=float)
    dx = np.zeros(n, dtype=float)
    adx = np.zeros(n, dtype=float)

    if n == 0:
        return pd.DataFrame(index=close.index)

    h = high.to_numpy(dtype=float)
    l = low.to_numpy(dtype=float)
    c = close.to_numpy(dtype=float)

    sum_tr[0] = _round8(h[0] - l[0])
    for i in range(1, n):
        true_range = h[i] - l[i]
        delta_hh = _round8(h[i] - h[i - 1])
        delta_ll = _round8(l[i - 1] - l[i])
        delta_hc = _round8(h[i] - c[i - 1])
        delta_lc = _round8(l[i] - c[i - 1])

        tr = _round8(max(abs(delta_lc), max(true_range, abs(delta_hc))))
        dm_plus = max(delta_hh, 0.0) if delta_hh > delta_ll else 0.0
        dm_minus = max(delta_ll, 0.0) if delta_ll > delta_hh else 0.0

        if i < period:
            sum_tr[i] = _round8(sum_tr[i - 1] + tr)
            sum_dm_plus[i] = sum_dm_plus[i - 1] + dm_plus
            sum_dm_minus[i] = sum_dm_minus[i - 1] + dm_minus
        else:
            sum_tr[i] = _round8(sum_tr[i - 1] - sum_tr[i - 1] / period + tr)
            sum_dm_plus[i] = sum_dm_plus[i - 1] - sum_dm_plus[i - 1] / period + dm_plus
            sum_dm_minus[i] = sum_dm_minus[i - 1] - sum_dm_minus[i - 1] / period + dm_minus

        if sum_tr[i] == 0 or np.isnan(sum_tr[i]):
            plus_di[i] = 0.0
            minus_di[i] = 0.0
        else:
            plus_di[i] = 100.0 * sum_dm_plus[i] / sum_tr[i]
            minus_di[i] = 100.0 * sum_dm_minus[i] / sum_tr[i]

        diff = abs(plus_di[i] - minus_di[i])
        di_sum = _round8(plus_di[i] + minus_di[i])
        if di_sum == 0 or np.isnan(di_sum):
            dx[i] = 50.0
            adx[i] = 50.0
        else:
            dx[i] = 100.0 * diff / di_sum
            adx[i] = ((period - 1) * adx[i - 1] + dx[i]) / period

    result = pd.DataFrame(index=close.index)
    result[f"{prefix}_sum_tr"] = sum_tr
    result[f"{prefix}_sum_dm_plus"] = sum_dm_plus
    result[f"{prefix}_sum_dm_minus"] = sum_dm_minus
    result[f"{prefix}_plus_di"] = plus_di
    result[f"{prefix}_minus_di"] = minus_di
    result[f"{prefix}_dx"] = dx
    result[f"{prefix}_adx"] = adx
    result[f"{prefix}_ready"] = np.arange(n) >= period * 2
    return result


def _level_name(value: float, config: ADXADXConfig) -> str:
    if pd.isna(value):
        return "insufficient_history"
    if value <= config.level_dormant:
        return "dormant"
    if value <= config.level_closed:
        return "closed"
    if value < config.level_active:
        return "building"
    return "active"


def _di_direction(plus: pd.Series, minus: pd.Series) -> pd.Series:
    return pd.Series(
        np.select(
            [plus > minus, minus > plus],
            ["plus", "minus"],
            default="neutral",
        ),
        index=plus.index,
    )


def compute_adxadx(df: pd.DataFrame, config: ADXADXConfig | None = None) -> pd.DataFrame:
    """Compute SqADXADX buffers for OHLC input ordered oldest to newest."""
    cfg = config or ADXADXConfig()
    adx_period = _source_period(cfg.adx_period)
    adxadx_period = _source_period(cfg.adxadx_period)
    if cfg.slope_bars <= 0:
        raise ValueError("slope_bars must be positive")

    out = df.copy()
    high = _column(out, "high")
    low = _column(out, "low")
    close = _column(out, "close")

    short = _adx_for_period(high, low, close, adx_period, "short")
    long = _adx_for_period(high, low, close, adxadx_period, "long")

    out["adx"] = short["short_adx"]
    out["plus_di"] = short["short_plus_di"]
    out["minus_di"] = short["short_minus_di"]
    out["adx_dx"] = short["short_dx"]
    out["adx_ready"] = short["short_ready"]

    out["adxadx"] = long["long_adx"]
    out["plus_didi"] = long["long_plus_di"]
    out["minus_didi"] = long["long_minus_di"]
    out["adxadx_dx"] = long["long_dx"]
    out["adxadx_ready"] = long["long_ready"]

    out["adx_slope"] = out["adx"] - out["adx"].shift(cfg.slope_bars)
    out["adxadx_slope"] = out["adxadx"] - out["adxadx"].shift(cfg.slope_bars)
    out["adx_spread"] = out["adx"] - out["adxadx"]
    out["adx_spread_slope"] = out["adx_spread"] - out["adx_spread"].shift(cfg.slope_bars)
    out["di_delta"] = out["plus_di"] - out["minus_di"]
    out["didi_delta"] = out["plus_didi"] - out["minus_didi"]
    out["short_di_direction"] = _di_direction(out["plus_di"], out["minus_di"])
    out["long_di_direction"] = _di_direction(out["plus_didi"], out["minus_didi"])

    out["adx_level"] = out["adx"].map(lambda value: _level_name(value, cfg))
    out["adxadx_level"] = out["adxadx"].map(lambda value: _level_name(value, cfg))
    out["adx_above_20"] = out["adx"] >= cfg.level_active
    out["adxadx_above_20"] = out["adxadx"] >= cfg.level_active
    out["adx_below_13"] = out["adx"] <= cfg.level_closed
    out["adxadx_below_13"] = out["adxadx"] <= cfg.level_closed

    prev_adx = out["adx"].shift(1)
    prev_adxadx = out["adxadx"].shift(1)
    out["adx_cross_above_adxadx"] = (prev_adx <= prev_adxadx) & (out["adx"] > out["adxadx"])
    out["adx_cross_below_adxadx"] = (prev_adx >= prev_adxadx) & (out["adx"] < out["adxadx"])

    out["adxadx_phase"] = np.select(
        [
            (out["adx_below_13"]) & (out["adxadx_below_13"]) & (out["adx_slope"] <= 0) & (out["adxadx_slope"] <= 0),
            (out["adx"] >= cfg.level_active) & (out["adx_slope"] > 0) & (out["adxadx"] < cfg.level_active) & (out["short_di_direction"] == "plus"),
            (out["adx"] >= cfg.level_active) & (out["adxadx"] >= cfg.level_active) & (out["adx_slope"] > 0) & (out["adxadx_slope"] > 0) & (out["short_di_direction"] == "plus") & (out["long_di_direction"] == "plus"),
            (out["adx"] >= cfg.level_active) & (out["adxadx"] >= cfg.level_active) & (out["adx_slope"] < 0) & (out["adxadx_slope"] >= 0),
            (out["adx"] >= cfg.level_active) & (out["adx_slope"] > 0) & (out["adxadx"] < cfg.level_active) & (out["short_di_direction"] == "minus"),
            (out["adx"] >= cfg.level_active) & (out["adxadx"] >= cfg.level_active) & (out["adx_slope"] > 0) & (out["adxadx_slope"] > 0) & (out["short_di_direction"] == "minus") & (out["long_di_direction"] == "minus"),
            (out["adx"] < out["adxadx"]) & (out["adx_slope"] < 0) & (out["adxadx_slope"] <= 0),
        ],
        [
            "dual_closed",
            "short_bull_start",
            "dual_bull_trend",
            "trend_decay",
            "short_bear_start",
            "dual_bear_trend",
            "dual_contraction",
        ],
        default="mixed",
    )

    return out


def compute_adxadx_from_csv(
    input_path: str,
    output_path: str | None = None,
    config: ADXADXConfig | None = None,
) -> pd.DataFrame:
    df = pd.read_csv(input_path)
    result = compute_adxadx(df, config)
    if output_path:
        result.to_csv(output_path, index=False)
    return result

