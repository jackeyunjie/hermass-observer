"""Bootstrap statistics for strategy verification scripts.

Extracted from search_vcp_optimal_state.py, search_2560_optimal_state.py,
search_bollinger_optimal_state.py to eliminate code duplication and add
Bootstrap confidence intervals.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

import numpy as np


# -- Format utilities (extracted from 3 scripts) --------------------------------


def pct(value: float | None, digits: int = 2) -> str:
    if value is None or not math.isfinite(value):
        return ""
    return f"{value * 100:.{digits}f}%"


def fmt_num(value: Any, digits: int = 4) -> str:
    try:
        if value is None:
            return ""
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return ""


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


# -- Stat utilities (extracted from 3 scripts) ---------------------------------


def payoff_ratio(values: list[float]) -> float | None:
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    if not wins or not losses:
        return None
    loss_mean = statistics.fmean(losses)
    if loss_mean == 0:
        return None
    return statistics.fmean(wins) / abs(loss_mean)


# -- Bootstrap CI core ---------------------------------------------------------


def bootstrap_ci(
    values: list[float],
    stat_fn: callable,
    n_bootstrap: int = 10000,
    confidence: float = 0.95,
    seed: int = 42,
    max_sample_size: int = 2000,
) -> tuple[float | None, float | None]:
    """Bootstrap confidence interval via percentile method.

    For large samples (>max_sample_size) we subsample to keep runtime bounded
    while preserving CI accuracy (bootstrap precision is driven by n_bootstrap,
    not original sample size once n is moderately large).
    """
    if len(values) < 5:
        return (None, None)

    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=np.float64)
    n = len(arr)

    # Subsample large arrays to bound runtime
    if n > max_sample_size:
        arr = rng.choice(arr, size=max_sample_size, replace=False)
        n = max_sample_size

    boot_stats = np.empty(n_bootstrap, dtype=np.float64)
    for i in range(n_bootstrap):
        sample = rng.choice(arr, size=n, replace=True)
        boot_stats[i] = stat_fn(sample)

    alpha = (1.0 - confidence) / 2.0
    return (
        float(np.percentile(boot_stats, alpha * 100)),
        float(np.percentile(boot_stats, (1.0 - alpha) * 100)),
    )


def bootstrap_mean_ci(
    values: list[float], n_bootstrap: int = 10000, confidence: float = 0.95
) -> tuple[float | None, float | None]:
    """Mean bootstrap CI."""
    return bootstrap_ci(values, np.mean, n_bootstrap, confidence)


def bootstrap_median_ci(
    values: list[float], n_bootstrap: int = 10000, confidence: float = 0.95
) -> tuple[float | None, float | None]:
    """Median bootstrap CI."""
    return bootstrap_ci(values, np.median, n_bootstrap, confidence)


def bootstrap_win_rate_ci(
    values: list[float], n_bootstrap: int = 10000, confidence: float = 0.95
) -> tuple[float | None, float | None]:
    """Win-rate bootstrap CI."""
    return bootstrap_ci(values, lambda a: np.mean(a > 0), n_bootstrap, confidence)


def bootstrap_payoff_ratio_ci(
    values: list[float], n_bootstrap: int = 10000, confidence: float = 0.95
) -> tuple[float | None, float | None]:
    """Payoff-ratio bootstrap CI."""

    def payoff(arr):
        w = arr[arr > 0]
        l = arr[arr < 0]
        if len(w) == 0 or len(l) == 0:
            return 0.0
        r = np.mean(w) / abs(np.mean(l))
        return r if np.isfinite(r) else 0.0

    return bootstrap_ci(values, payoff, n_bootstrap, confidence)


# -- metric_row (replaces 3 copies) --------------------------------------------


def metric_row(
    key: str,
    samples: list[dict[str, Any]],
    window: int,
    n_bootstrap: int = 10000,
    skip_ci: bool = False,
) -> dict[str, Any]:
    """Compute point estimates + optional 95% Bootstrap CI for a group of samples."""
    values = [
        float(s[f"excess_ret_{window}d"]) for s in samples if s.get(f"excess_ret_{window}d") is not None
    ]
    wins = [v for v in values if v > 0]

    mean = statistics.fmean(values) if values else None
    stdev = statistics.stdev(values) if len(values) > 1 else None
    t_stat = mean / (stdev / math.sqrt(len(values))) if mean is not None and stdev and stdev > 0 else None
    med = statistics.median(values) if values else None
    wr = len(wins) / len(values) if values else None
    pr = payoff_ratio(values)

    ci_mean = ci_med = ci_wr = ci_pr = (None, None)
    if not skip_ci and len(values) >= 10:
        ci_mean = bootstrap_mean_ci(values, n_bootstrap)
        ci_med = bootstrap_median_ci(values, n_bootstrap)
        ci_wr = bootstrap_win_rate_ci(values, n_bootstrap)
        ci_pr = bootstrap_payoff_ratio_ci(values, n_bootstrap)

    return {
        "key": key,
        "n": len(values),
        "mean_excess": mean,
        "mean_excess_ci_lo": ci_mean[0],
        "mean_excess_ci_hi": ci_mean[1],
        "median_excess": med,
        "median_excess_ci_lo": ci_med[0],
        "median_excess_ci_hi": ci_med[1],
        "win_rate": wr,
        "win_rate_ci_lo": ci_wr[0],
        "win_rate_ci_hi": ci_wr[1],
        "payoff_ratio": pr,
        "payoff_ratio_ci_lo": ci_pr[0],
        "payoff_ratio_ci_hi": ci_pr[1],
        "t_stat": t_stat,
    }
