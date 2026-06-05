"""Python port of ``data/Kaufman_Bands.mq4``.

The MT4 source plots a Kaufman adaptive moving average plus upper/lower bands:

- KAMA = previous KAMA + (ER * (fastSC - slowSC) + slowSC)^G * (close - previous KAMA)
- Band deviation = sqrt(mean((close - KAMA)^2, BollingerPeriod))
- Upper/Lower = KAMA +/- deviation * K_Bollinger

This module computes two parameter sets by default:

- KB20: 9, 2, 30, 2, 2, 20, 2
- KB50: 14, 7, 50, 2, 2, 50, 2
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class KaufmanBandConfig:
    period_ama: int = 9
    nfast: int = 2
    nslow: int = 30
    g: float = 2.0
    dk: float = 2.0
    bollinger_period: int = 20
    k_bollinger: float = 2.0
    slope_bars: int = 3


KB20_CONFIG = KaufmanBandConfig(9, 2, 30, 2.0, 2.0, 20, 2.0)
KB50_CONFIG = KaufmanBandConfig(14, 7, 50, 2.0, 2.0, 50, 2.0)


def _column(df: pd.DataFrame, name: str) -> pd.Series:
    cols = {str(c).lower(): c for c in df.columns}
    if name not in cols:
        raise ValueError(f"Missing required column: {name}")
    return pd.to_numeric(df[cols[name]], errors="coerce").astype(float)


def _safe_period(value: int, *, fallback: int = 1) -> int:
    try:
        period = int(value)
    except (TypeError, ValueError):
        return fallback
    return period if period > 0 else fallback


def compute_single_kaufman_band(
    df: pd.DataFrame,
    config: KaufmanBandConfig,
    prefix: str,
) -> pd.DataFrame:
    """Compute one Kaufman band parameter set for OHLC rows ordered oldest first."""
    close = _column(df, "close")
    n = len(close)
    period_ama = _safe_period(config.period_ama, fallback=9)
    boll_period = _safe_period(config.bollinger_period, fallback=20)
    slope_bars = _safe_period(config.slope_bars, fallback=3)

    c = close.to_numpy(dtype=float)
    kama = np.full(n, np.nan, dtype=float)
    upper = np.full(n, np.nan, dtype=float)
    lower = np.full(n, np.nan, dtype=float)
    deviation = np.full(n, np.nan, dtype=float)
    up_signal = np.full(n, np.nan, dtype=float)
    down_signal = np.full(n, np.nan, dtype=float)

    if n == 0:
        return pd.DataFrame(index=df.index)

    slow_sc = 2.0 / (config.nslow + 1.0)
    fast_sc = 2.0 / (config.nfast + 1.0)
    start = min(period_ama + 1, n - 1)
    ama0 = c[start]

    for i in range(start, n):
        prev = ama0 if i == start else kama[i - 1]
        if not np.isfinite(prev):
            prev = c[i - 1] if i > 0 else c[i]

        if i >= period_ama:
            signal = abs(c[i] - c[i - period_ama])
            noise = 1e-9
            for j in range(i - period_ama + 1, i + 1):
                noise += abs(c[j] - c[j - 1])
            er = signal / noise
        else:
            er = 0.0

        ssc = er * (fast_sc - slow_sc) + slow_sc
        ama = prev + (ssc**config.g) * (c[i] - prev)
        kama[i] = ama

        if i + 1 >= boll_period:
            close_window = c[i - boll_period + 1 : i + 1]
            kama_window = kama[i - boll_period + 1 : i + 1]
            if np.isfinite(kama_window).all():
                dev = float(np.sqrt(np.mean((close_window - kama_window) ** 2)))
                deviation[i] = dev
                upper[i] = ama + dev * config.k_bollinger
                lower[i] = ama - dev * config.k_bollinger

        delta = ama - prev
        threshold = config.dk * 1e-8
        if abs(delta) > threshold and delta > 0:
            up_signal[i] = ama
        if abs(delta) > threshold and delta < 0:
            down_signal[i] = ama

    out = pd.DataFrame(index=df.index)
    out[f"{prefix}_kama"] = kama
    out[f"{prefix}_upper"] = upper
    out[f"{prefix}_lower"] = lower
    out[f"{prefix}_deviation"] = deviation
    out[f"{prefix}_width"] = upper - lower
    out[f"{prefix}_width_pct"] = out[f"{prefix}_width"] / out[f"{prefix}_kama"].replace(0, np.nan)
    out[f"{prefix}_slope"] = out[f"{prefix}_kama"] - out[f"{prefix}_kama"].shift(slope_bars)
    out[f"{prefix}_width_slope"] = out[f"{prefix}_width"] - out[f"{prefix}_width"].shift(slope_bars)
    out[f"{prefix}_price_position"] = np.select(
        [
            close > out[f"{prefix}_upper"],
            close < out[f"{prefix}_lower"],
            close > out[f"{prefix}_kama"],
            close < out[f"{prefix}_kama"],
        ],
        ["above_upper", "below_lower", "above_mid", "below_mid"],
        default="inside_mid",
    )
    out[f"{prefix}_up_signal"] = up_signal
    out[f"{prefix}_down_signal"] = down_signal
    out[f"{prefix}_ready"] = np.isfinite(out[f"{prefix}_upper"]) & np.isfinite(out[f"{prefix}_lower"])
    return out


def _level_from_quantiles(width: pd.Series) -> pd.Series:
    q20 = width.rolling(100, min_periods=20).quantile(0.2)
    q50 = width.rolling(100, min_periods=20).quantile(0.5)
    level = pd.Series(
        np.select(
            [width <= q20, width <= q50],
            ["narrow", "normal"],
            default="wide",
        ),
        index=width.index,
    )
    return level.where(width.notna() & q20.notna() & q50.notna(), "insufficient_history")


def compute_kaufman_bands(
    df: pd.DataFrame,
    kb20: KaufmanBandConfig | None = None,
    kb50: KaufmanBandConfig | None = None,
) -> pd.DataFrame:
    """Compute KB20 and KB50 Kaufman band systems."""
    out = df.copy()
    close = _column(out, "close")
    part20 = compute_single_kaufman_band(out, kb20 or KB20_CONFIG, "kb20")
    part50 = compute_single_kaufman_band(out, kb50 or KB50_CONFIG, "kb50")
    out = pd.concat([out, part20, part50], axis=1)

    out["kb20_width_level"] = _level_from_quantiles(out["kb20_width"])
    out["kb50_width_level"] = _level_from_quantiles(out["kb50_width"])
    out["kb_width_spread"] = out["kb20_width"] - out["kb50_width"]
    out["kb_width_spread_slope"] = out["kb_width_spread"] - out["kb_width_spread"].shift(3)
    out["price_vs_kb20_upper"] = close - out["kb20_upper"]
    out["price_vs_kb20_lower"] = close - out["kb20_lower"]
    out["price_vs_kb50_upper"] = close - out["kb50_upper"]
    out["price_vs_kb50_lower"] = close - out["kb50_lower"]

    out["kaufman_band_phase"] = np.select(
        [
            (out["kb20_width_level"] == "narrow") & (out["kb50_width_level"] == "narrow"),
            (out["kb20_width_level"] == "narrow") & (out["kb50_width_level"] != "narrow"),
            (out["kb20_width_slope"] > 0) & (out["kb20_slope"] > 0) & (out["kb50_slope"] > 0) & (close > out["kb20_kama"]),
            (out["kb20_width_slope"] > 0) & (out["kb20_slope"] > 0) & (out["kb50_slope"].abs() <= 1e-8),
            (close > out["kb20_upper"]) & (out["kb50_width_slope"] <= 0),
            (out["kb20_width_slope"] > 0) & (out["kb20_slope"] < 0) & (out["kb50_width_slope"] > 0) & (out["kb50_slope"] < 0),
            (close < out["kb20_lower"]) & (out["kb50_slope"] > 0),
            (out["kb20_width_slope"] <= 0) & (out["kb50_slope"] < 0),
            (out["kb20_upper"] < out["kb50_upper"]) & (out["kb20_lower"] > out["kb50_lower"]),
            (out["kb20_width_slope"] > 0) & (out["kb50_width_slope"] < 0),
        ],
        [
            "dual_compression",
            "kb20_narrow_kb50_wide",
            "up_expansion_confirmed",
            "up_expansion_unconfirmed",
            "upper_breakout_without_kb50",
            "down_expansion_confirmed",
            "lower_break_with_kb50_up",
            "kb20_converge_kb50_down",
            "kb20_back_inside_kb50",
            "width_divergence",
        ],
        default="mixed",
    )
    return out


__all__ = [
    "KaufmanBandConfig",
    "KB20_CONFIG",
    "KB50_CONFIG",
    "compute_single_kaufman_band",
    "compute_kaufman_bands",
]
