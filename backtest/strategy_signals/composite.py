"""Classic strategy orchestration for P116 stock-pool research.

There are two separate uses:
1. Selection evidence: VCP and 2560 are observation/entry-quality factors for
   stocks already in the P116 E/F pool.
2. Classic strategy options: complete systems such as Bollinger Bandit and
   ATR Chandelier are preserved for backtest/advisory modes, including exits.

Do not collapse Bollinger Bandit into a generic Bollinger breakout. Its entry
and dynamic degrading-MA exit live in ``bollinger_bandit.py``.
"""
from __future__ import annotations

from typing import Any

from backtest.strategy_signals.bollinger_bandit import bollinger_bandit_signal
from backtest.strategy_signals.chandelier_exit import chandelier_exit_signal
from backtest.strategy_signals.ma2560 import ma2560_signal
from backtest.strategy_signals.vcp import vcp_signal


SELECTION_ENTRY_SIGNALS = {
    "ma2560_golden_cross",
    "vcp_breakout",
    "vcp_breakout_weak_vol",
    "vcp_breakout_no_vol",
}

SELECTION_STRUCTURE_SIGNALS = {
    "ma2560_strong_hold",
    "ma2560_aligned",
    "vcp_contraction",
    "vcp_early_contraction",
}

CLASSIC_ENTRY_SIGNALS = {
    *SELECTION_ENTRY_SIGNALS,
    "bb_bandit_long_entry",
}

CLASSIC_EXIT_SIGNALS = {
    "ma2560_death_cross_exit",
    "bb_bandit_dynamic_ma_exit",
    "chandelier_exit_tight",
    "chandelier_exit",
}

SIGNAL_WEIGHTS = {
    "ma2560_golden_cross": 0.85,
    "ma2560_strong_hold": 0.65,
    "ma2560_aligned": 0.50,
    "ma2560_death_cross_exit": 1.00,
    "ma2560_bearish": 0.00,
    "bb_bandit_long_entry": 0.80,
    "bb_bandit_dynamic_ma_exit": 1.00,
    "vcp_breakout": 0.95,
    "vcp_breakout_weak_vol": 0.70,
    "vcp_breakout_no_vol": 0.55,
    "vcp_contraction": 0.40,
    "vcp_early_contraction": 0.20,
    "chandelier_exit_tight": 1.00,
    "chandelier_exit": 0.90,
    "chandelier_rising": 0.00,
}


def _ctx(row: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    merged = dict(row)
    merged.update(ctx)
    return merged


def strategy_details(
    row: dict[str, Any],
    ctx: dict[str, Any],
    position_ctx: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return all classic strategy signals for the current bar."""
    merged = _ctx(row, ctx)
    bb = bollinger_bandit_signal(row, merged)
    st = ma2560_signal(row, merged)
    vc = vcp_signal(row, merged)
    ch = chandelier_exit_signal(row, merged, position_ctx)
    return {
        "bollinger_bandit": {"signal": bb[0] if bb else None, "confidence": bb[1] if bb else 0},
        "ma2560": {"signal": st[0] if st else None, "confidence": st[1] if st else 0},
        "vcp": {"signal": vc[0] if vc else None, "confidence": vc[1] if vc else 0},
        "chandelier_exit": {"signal": ch[0] if ch else None, "confidence": ch[1] if ch else 0},
    }


def selection_evidence_signal(row: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any] | None:
    """VCP/2560 evidence for ranking candidates inside the P116 E/F pool."""
    merged = _ctx(row, ctx)
    ef_count = merged.get("ef_count", 0)
    if ef_count < 2:
        return None

    details = strategy_details(row, merged, position_ctx=None)
    labels = [
        item["signal"]
        for name, item in details.items()
        if name in {"ma2560", "vcp"} and item.get("signal")
    ]
    entry_labels = [label for label in labels if label in SELECTION_ENTRY_SIGNALS]
    structure_labels = [label for label in labels if label in SELECTION_STRUCTURE_SIGNALS]
    if not entry_labels and not structure_labels:
        return None

    best_label = max(entry_labels or structure_labels, key=lambda label: SIGNAL_WEIGHTS.get(label, 0))
    return {
        "entry_type": best_label if best_label in SELECTION_ENTRY_SIGNALS else "selection_structure_only",
        "exit_type": None,
        "composite_confidence": SIGNAL_WEIGHTS.get(best_label, 0),
        "details": details,
        "strategy_role": "selection_evidence",
    }


def classic_strategy_signal(
    row: dict[str, Any],
    ctx: dict[str, Any],
    position_ctx: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Complete classic strategy option for backtests and advisory modes."""
    merged = _ctx(row, ctx)
    details = strategy_details(row, merged, position_ctx)

    for name in ("chandelier_exit", "ma2560", "bollinger_bandit"):
        sig = details[name].get("signal")
        if sig in CLASSIC_EXIT_SIGNALS:
            return {
                "entry_type": None,
                "exit_type": sig,
                "composite_confidence": details[name]["confidence"],
                "details": details,
                "strategy_role": "classic_strategy",
            }

    if merged.get("ef_count", 0) < 2:
        return None

    best_name = None
    best_signal = None
    best_confidence = 0.0
    for name in ("vcp", "ma2560", "bollinger_bandit"):
        sig = details[name].get("signal")
        confidence = details[name].get("confidence", 0)
        if sig in CLASSIC_ENTRY_SIGNALS and confidence > best_confidence:
            best_name = name
            best_signal = sig
            best_confidence = confidence

    if not best_signal:
        return None

    return {
        "entry_type": best_signal,
        "exit_type": None,
        "composite_confidence": best_confidence,
        "details": details,
        "strategy_role": f"classic_strategy:{best_name}",
    }


def composite_signal(
    row: dict[str, Any],
    ctx: dict[str, Any],
    position_ctx: dict[str, Any] | None = None,
    *,
    mode: str = "classic",
) -> dict[str, Any] | None:
    """Backward-compatible entry point.

    mode='selection' keeps Bollinger Bandit/Chandelier out of candidate ranking.
    mode='classic' preserves the complete classic strategy option for backtests.
    """
    if mode == "selection":
        return selection_evidence_signal(row, ctx)
    return classic_strategy_signal(row, ctx, position_ctx)

