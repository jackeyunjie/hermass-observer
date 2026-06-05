"""Python port of MT4 ATR with dual 14/30 parameters.

The source file ``data/ATR.mq4`` calculates Average True Range with one input
period. This module keeps the same source formula and computes two ATR lines:

- ATR14: short volatility release
- ATR30: slower volatility background

The normalized columns divide ATR by close so different price levels can be
compared in the knowledge base and later empirical scans.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ATR1430Config:
    atr_short_period: int = 14
    atr_long_period: int = 30
    slope_bars: int = 3
    percentile_lookback: int = 100
    low_quantile: float = 0.20
    high_quantile: float = 0.80


def _column(df: pd.DataFrame, name: str) -> pd.Series:
    cols = {str(c).lower(): c for c in df.columns}
    if name not in cols:
        raise ValueError(f"Missing required column: {name}")
    return pd.to_numeric(df[cols[name]], errors="coerce").astype(float)


def true_range(df: pd.DataFrame) -> pd.Series:
    """Return MT4-compatible True Range ordered oldest to newest."""
    high = _column(df, "high")
    low = _column(df, "low")
    close = _column(df, "close")
    prev_close = close.shift(1)
    tr = pd.concat([high, prev_close], axis=1).max(axis=1) - pd.concat([low, prev_close], axis=1).min(axis=1)
    if len(tr):
        tr.iloc[0] = 0.0
    return tr.astype(float)


def mt4_atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Replicate ``data/ATR.mq4`` ATR smoothing.

    MT4's bundled ATR indicator initializes ATR at ``period`` as the average of
    TR[1:period], then updates by adding the newest TR and dropping TR[i-period].
    That is equivalent to a rolling mean after initialization, but this loop
    keeps the source behavior explicit.
    """
    if period <= 0:
        raise ValueError("ATR period must be positive")

    tr = true_range(df).to_numpy(dtype=float)
    atr = np.zeros(len(tr), dtype=float)
    if len(tr) <= period:
        return pd.Series(atr, index=df.index, dtype=float)

    first_value = float(np.nansum(tr[1 : period + 1]) / period)
    atr[period] = first_value
    for i in range(period + 1, len(tr)):
        atr[i] = atr[i - 1] + (tr[i] - tr[i - period]) / period
    return pd.Series(atr, index=df.index, dtype=float)


def _level(values: pd.Series, q_low: pd.Series, q_high: pd.Series) -> pd.Series:
    return pd.Series(
        np.select(
            [values <= q_low, values >= q_high],
            ["low", "high"],
            default="middle",
        ),
        index=values.index,
    ).mask(values.isna() | q_low.isna() | q_high.isna(), "insufficient_history")


def compute_atr1430(df: pd.DataFrame, config: ATR1430Config | None = None) -> pd.DataFrame:
    """Compute ATR14/ATR30 composite columns for OHLC input."""
    cfg = config or ATR1430Config()
    if cfg.atr_short_period <= 0 or cfg.atr_long_period <= 0:
        raise ValueError("ATR periods must be positive")
    if cfg.slope_bars <= 0:
        raise ValueError("slope_bars must be positive")
    if cfg.percentile_lookback <= 1:
        raise ValueError("percentile_lookback must be greater than 1")

    out = df.copy()
    close = _column(out, "close")

    out["tr"] = true_range(out)
    out["atr14"] = mt4_atr(out, cfg.atr_short_period)
    out["atr30"] = mt4_atr(out, cfg.atr_long_period)
    out["atr14_norm"] = out["atr14"] / close.replace(0.0, np.nan)
    out["atr30_norm"] = out["atr30"] / close.replace(0.0, np.nan)

    out["atr14_slope"] = out["atr14"] - out["atr14"].shift(cfg.slope_bars)
    out["atr30_slope"] = out["atr30"] - out["atr30"].shift(cfg.slope_bars)
    out["atr14_norm_slope"] = out["atr14_norm"] - out["atr14_norm"].shift(cfg.slope_bars)
    out["atr30_norm_slope"] = out["atr30_norm"] - out["atr30_norm"].shift(cfg.slope_bars)
    out["atr14_atr30_ratio"] = out["atr14"] / out["atr30"].replace(0.0, np.nan)
    out["atr14_minus_atr30_norm"] = out["atr14_norm"] - out["atr30_norm"]

    min_periods = max(10, min(cfg.percentile_lookback, len(out)))
    out["atr14_norm_q20"] = out["atr14_norm"].rolling(cfg.percentile_lookback, min_periods=min_periods).quantile(cfg.low_quantile)
    out["atr30_norm_q20"] = out["atr30_norm"].rolling(cfg.percentile_lookback, min_periods=min_periods).quantile(cfg.low_quantile)
    out["atr14_norm_q80"] = out["atr14_norm"].rolling(cfg.percentile_lookback, min_periods=min_periods).quantile(cfg.high_quantile)
    out["atr30_norm_q80"] = out["atr30_norm"].rolling(cfg.percentile_lookback, min_periods=min_periods).quantile(cfg.high_quantile)

    out["atr14_level"] = _level(out["atr14_norm"], out["atr14_norm_q20"], out["atr14_norm_q80"])
    out["atr30_level"] = _level(out["atr30_norm"], out["atr30_norm_q20"], out["atr30_norm_q80"])
    out["atr14_low"] = out["atr14_level"] == "low"
    out["atr30_low"] = out["atr30_level"] == "low"
    out["atr14_high"] = out["atr14_level"] == "high"
    out["atr30_high"] = out["atr30_level"] == "high"

    out["atr14_rising_from_low"] = out["atr14_low"].shift(1).fillna(False).astype(bool) & (out["atr14_norm_slope"] > 0)
    out["atr30_rising_from_low"] = out["atr30_low"].shift(1).fillna(False).astype(bool) & (out["atr30_norm_slope"] > 0)
    out["atr_dual_low"] = out["atr14_low"] & out["atr30_low"]
    out["atr_dual_expanding"] = (out["atr14_norm_slope"] > 0) & (out["atr30_norm_slope"] > 0)
    out["atr_short_leads_long"] = (out["atr14_norm_slope"] > 0) & (out["atr30_norm_slope"] <= 0)
    out["atr_release_decay"] = (out["atr14_norm_slope"] < 0) & (out["atr30_norm_slope"] >= 0)

    out["atr1430_phase"] = np.select(
        [
            out["atr_dual_low"],
            out["atr14_rising_from_low"] & out["atr30_low"],
            out["atr_dual_expanding"] & (out["atr14_atr30_ratio"] >= 1.0),
            out["atr_release_decay"],
            out["atr14_high"] & out["atr30_high"],
            out["atr14_norm_slope"] < 0,
        ],
        [
            "dual_low_compression",
            "short_rising_from_low",
            "dual_expansion",
            "release_decay",
            "dual_high_volatility",
            "contraction_after_release",
        ],
        default="mixed",
    )

    return out


def compute_atr1430_from_csv(
    input_path: str,
    output_path: str | None = None,
    config: ATR1430Config | None = None,
) -> pd.DataFrame:
    df = pd.read_csv(input_path)
    result = compute_atr1430(df, config)
    if output_path:
        result.to_csv(output_path, index=False)
    return result
