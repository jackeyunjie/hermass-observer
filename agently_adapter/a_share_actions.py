#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from agently_adapter import a_share_core


def preflight(date_str: str, previous_date: str, timeout: float | None = None) -> dict[str, Any]:
    del timeout
    return a_share_core.preflight(date_str, previous_date)


def build_foundation(date_str: str, foundation_db: str, timeout: float | None = None) -> dict[str, Any]:
    del timeout
    return a_share_core.build_foundation(date_str, foundation_db=foundation_db)


def build_state_cache(
    date_str: str,
    foundation_db: str,
    boundary_pct: float = 0.03,
    timeout: float | None = None,
) -> dict[str, Any]:
    del timeout
    return a_share_core.build_state_cache(
        date_str,
        foundation_db=foundation_db,
        boundary_pct=boundary_pct,
    )


def build_strategy_evidence(
    date_str: str,
    foundation_db: str,
    lookback_days: int = 20,
    timeout: float | None = None,
) -> dict[str, Any]:
    del timeout
    return a_share_core.build_strategy_evidence(
        date_str,
        foundation_db=foundation_db,
        lookback_days=lookback_days,
    )


def build_strategy_signal_ledger(
    date_str: str,
    foundation_db: str,
    min_ef: int = 2,
    timeout: float | None = None,
) -> dict[str, Any]:
    del timeout
    return a_share_core.build_strategy_signal_ledger(
        date_str,
        foundation_db=foundation_db,
        min_ef=min_ef,
    )


def build_forward_observation(
    date_str: str,
    foundation_db: str,
    windows: str = "5,10,20",
    timeout: float | None = None,
) -> dict[str, Any]:
    del timeout
    return a_share_core.build_forward_observation(
        date_str,
        foundation_db=foundation_db,
        windows=windows,
    )


def build_daily_brief(date_str: str, timeout: float | None = None) -> dict[str, Any]:
    del timeout
    return a_share_core.build_daily_brief(date_str)


def verify_core_outputs(date_str: str, foundation_db: str | None = None, timeout: float | None = None) -> dict[str, Any]:
    del timeout
    return a_share_core.verify_core_outputs(date_str, foundation_db=foundation_db)
