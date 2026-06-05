"""Python port of the MT4 RSIOMA v2HHLSX indicator.

The original MQ4 indicator first smooths price with a moving average, then
computes RSI on that smoothed series, then overlays a moving average of the
RSIOMA line. The output columns keep the original buffer semantics so the
Python result can be compared with MT4/MT5 exports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


MAMode = Literal["sma", "ema", "smma", "lwma"]
PriceField = Literal["close", "open", "high", "low", "median", "typical", "weighted"]

MODE_SMA = 0
MODE_EMA = 1
MODE_SMMA = 2
MODE_LWMA = 3

PRICE_CLOSE = 0
PRICE_OPEN = 1
PRICE_HIGH = 2
PRICE_LOW = 3
PRICE_MEDIAN = 4
PRICE_TYPICAL = 5
PRICE_WEIGHTED = 6

MA_MODE_NAMES = {
    MODE_SMA: "sma",
    MODE_EMA: "ema",
    MODE_SMMA: "smma",
    MODE_LWMA: "lwma",
    "sma": "sma",
    "ema": "ema",
    "smma": "smma",
    "lwma": "lwma",
}

PRICE_FIELD_NAMES = {
    PRICE_CLOSE: "close",
    PRICE_OPEN: "open",
    PRICE_HIGH: "high",
    PRICE_LOW: "low",
    PRICE_MEDIAN: "median",
    PRICE_TYPICAL: "typical",
    PRICE_WEIGHTED: "weighted",
    "close": "close",
    "open": "open",
    "high": "high",
    "low": "low",
    "median": "median",
    "typical": "typical",
    "weighted": "weighted",
}


@dataclass(frozen=True)
class RSIOMAConfig:
    rsioma_period: int = 14
    rsioma_mode: MAMode | int = "ema"
    rsioma_price: PriceField | int = "close"
    ma_rsioma_period: int = 21
    ma_rsioma_mode: MAMode | int = "ema"
    buy_trigger: float = 80.0
    sell_trigger: float = 20.0
    main_trend_long: float = 70.0
    main_trend_short: float = 30.0
    major_trend: float = 50.0


def normalize_ma_mode(mode: MAMode | int) -> MAMode:
    try:
        return MA_MODE_NAMES[mode]  # type: ignore[index, return-value]
    except KeyError as exc:
        raise ValueError(f"Unsupported MA mode: {mode!r}") from exc


def normalize_price_field(field: PriceField | int) -> PriceField:
    try:
        return PRICE_FIELD_NAMES[field]  # type: ignore[index, return-value]
    except KeyError as exc:
        raise ValueError(f"Unsupported price field: {field!r}") from exc


def price_series(df: pd.DataFrame, field: PriceField | int = "close") -> pd.Series:
    name = normalize_price_field(field)
    cols = {c.lower(): c for c in df.columns}

    def col(column: str) -> pd.Series:
        if column not in cols:
            raise ValueError(f"Missing required column: {column}")
        return pd.to_numeric(df[cols[column]], errors="coerce")

    if name in {"close", "open", "high", "low"}:
        return col(name)
    high = col("high")
    low = col("low")
    close = col("close")
    if name == "median":
        return (high + low) / 2.0
    if name == "typical":
        return (high + low + close) / 3.0
    if name == "weighted":
        return (high + low + 2.0 * close) / 4.0
    raise ValueError(f"Unsupported price field: {name}")


def moving_average(values: pd.Series, period: int, mode: MAMode | int = "ema") -> pd.Series:
    if period <= 0:
        raise ValueError("MA period must be positive")
    mode_name = normalize_ma_mode(mode)
    series = pd.to_numeric(values, errors="coerce").astype(float)
    if mode_name == "sma":
        return series.rolling(period, min_periods=period).mean()
    if mode_name == "ema":
        return series.ewm(span=period, adjust=False, min_periods=period).mean()
    if mode_name == "smma":
        return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    if mode_name == "lwma":
        weights = np.arange(1, period + 1, dtype=float)
        denominator = float(weights.sum())
        return series.rolling(period, min_periods=period).apply(
            lambda window: float(np.dot(window, weights) / denominator),
            raw=True,
        )
    raise ValueError(f"Unsupported MA mode: {mode_name}")


def rsi_on_array(values: pd.Series, period: int) -> pd.Series:
    """Compute MT4-style RSI on an arbitrary input series using Wilder smoothing."""
    if period <= 0:
        raise ValueError("RSI period must be positive")

    series = pd.to_numeric(values, errors="coerce").astype(float)
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    both_zero = (avg_gain == 0.0) & (avg_loss == 0.0)
    only_loss_zero = (avg_gain > 0.0) & (avg_loss == 0.0)
    rsi = rsi.mask(both_zero, 50.0)
    rsi = rsi.mask(only_loss_zero, 100.0)
    return rsi


def compute_rsioma(df: pd.DataFrame, config: RSIOMAConfig | None = None) -> pd.DataFrame:
    """Return RSIOMA buffers for OHLC input ordered oldest to newest.

    Required columns depend on ``rsioma_price``. The default only requires
    ``close``. Output keeps one row per input bar and appends indicator columns.
    """
    cfg = config or RSIOMAConfig()
    if cfg.rsioma_period <= 0 or cfg.ma_rsioma_period <= 0:
        raise ValueError("RSIOMA periods must be positive")

    out = df.copy()
    price = price_series(out, cfg.rsioma_price)
    price_ma = moving_average(price, cfg.rsioma_period, cfg.rsioma_mode)
    rsioma = rsi_on_array(price_ma, cfg.rsioma_period)
    ma_rsioma = moving_average(rsioma, cfg.ma_rsioma_period, cfg.ma_rsioma_mode)
    prev_rsioma = rsioma.shift(1)
    prev_ma_rsioma = ma_rsioma.shift(1)

    trend_up = pd.Series(np.nan, index=out.index, dtype=float)
    trend_down = pd.Series(np.nan, index=out.index, dtype=float)
    signal_up = pd.Series(np.nan, index=out.index, dtype=float)
    signal_down = pd.Series(np.nan, index=out.index, dtype=float)
    ma_cross_signal = pd.Series(np.nan, index=out.index, dtype=float)

    trend_up = trend_up.mask(rsioma > cfg.major_trend, 6.0)
    trend_down = trend_down.mask(rsioma < cfg.major_trend, -6.0)
    trend_up = trend_up.mask(rsioma > cfg.main_trend_long, 12.0)
    trend_down = trend_down.mask(rsioma < cfg.main_trend_short, -12.0)

    signal_up = signal_up.mask((rsioma < cfg.sell_trigger) & (rsioma > prev_rsioma), -3.0)
    signal_down = signal_down.mask((rsioma > cfg.buy_trigger) & (rsioma < prev_rsioma), 4.0)
    signal_up = signal_up.mask((rsioma > cfg.sell_trigger) & (prev_rsioma <= cfg.sell_trigger), 5.0)
    signal_down = signal_down.mask((prev_rsioma >= cfg.buy_trigger) & (rsioma < cfg.buy_trigger), -5.0)
    signal_up = signal_up.mask((prev_rsioma <= cfg.main_trend_short) & (rsioma > cfg.main_trend_short), 12.0)
    signal_down = signal_down.mask((rsioma < cfg.main_trend_long) & (prev_rsioma >= cfg.main_trend_long), -12.0)

    ma_cross_signal = ma_cross_signal.mask(
        (prev_rsioma <= prev_ma_rsioma) & (rsioma > ma_rsioma),
        -8.0,
    )
    ma_cross_signal = ma_cross_signal.mask(
        (prev_rsioma >= prev_ma_rsioma) & (rsioma < ma_rsioma),
        8.0,
    )

    out["rsioma_price"] = price
    out["rsioma_price_ma"] = price_ma
    out["rsioma"] = rsioma
    out["ma_rsioma"] = ma_rsioma
    out["trend_up_hist"] = trend_up
    out["trend_down_hist"] = trend_down
    out["signal_up_hist"] = signal_up
    out["signal_down_hist"] = signal_down
    out["ma_cross_signal"] = ma_cross_signal
    out["rsioma_above_50"] = rsioma > cfg.major_trend
    out["rsioma_above_70"] = rsioma > cfg.main_trend_long
    out["rsioma_below_30"] = rsioma < cfg.main_trend_short
    out["rsioma_above_80"] = rsioma > cfg.buy_trigger
    out["rsioma_below_20"] = rsioma < cfg.sell_trigger
    out["rsioma_slope"] = rsioma - prev_rsioma
    out["rsioma_ma_spread"] = rsioma - ma_rsioma
    out["rsioma_ma_cross"] = np.select(
        [
            ma_cross_signal == -8.0,
            ma_cross_signal == 8.0,
        ],
        [
            "cross_up",
            "cross_down",
        ],
        default="none",
    )
    return out


def compute_rsioma_from_csv(
    input_path: str,
    output_path: str | None = None,
    config: RSIOMAConfig | None = None,
) -> pd.DataFrame:
    df = pd.read_csv(input_path)
    result = compute_rsioma(df, config)
    if output_path:
        result.to_csv(output_path, index=False)
    return result

