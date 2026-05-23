"""VCP post-trigger management observations.

This module converts the local VCP guide into deterministic observation rules
for reports. It does not generate VCP entries; entries remain owned by
``vcp_signal``. The rules here only classify what happened after an approved
VCP trigger.
"""

from __future__ import annotations

from typing import Any


def initial_risk_price(
    entry_price: float,
    risk_pct: float = 0.08,
) -> float:
    """Return the guide-style initial defensive reference price.

    The guide describes a 4%-8% pivot risk band. The implementation uses the
    conservative 8% band because the current signal ledger does not yet store
    the last tight-contraction low.
    """
    if entry_price <= 0:
        return 0.0
    return entry_price * (1.0 - risk_pct)


def vcp_management_observation(
    entry_price: float,
    state_series: list[dict[str, Any]],
    risk_pct: float = 0.08,
    time_stop_bars: int = 5,
) -> dict[str, Any]:
    """Classify VCP post-trigger status using the guide rules.

    Status values:
    - ``rule_exit_observed``: initial defensive boundary was violated.
    - ``time_stop_observed``: after five bars, price still failed to advance.
    - ``profit_protection_zone``: reached at least +2R, guide would move risk to
      breakeven and track the remainder.
    - ``still_active_by_rule``: no management event observed.

    The partial-profit and moving-average stages are deliberately reported as
    management zones instead of simulated order fills, because the system has no
    position-size context yet.
    """
    if entry_price <= 0:
        return {
            "exit_rule_status": "not_available",
            "exit_rule_note": "VCP 管理观察缺少有效参考价。",
        }

    risk_price = initial_risk_price(entry_price, risk_pct=risk_pct)
    risk_per_share = entry_price - risk_price
    high_since_entry = entry_price

    for hold_bars, row in enumerate(state_series[1:], start=1):
        close = float(row.get("close") or 0)
        high = float(row.get("high") or close or 0)
        if close <= 0:
            continue
        high_since_entry = max(high_since_entry, high)

        if close <= risk_price:
            return {
                "exit_rule_status": "rule_exit_observed",
                "exit_date": row.get("date"),
                "exit_price": close,
                "exit_rule_note": "VCP指南版初始防守边界被触发。",
                "vcp_management": {
                    "entry_price": entry_price,
                    "risk_price": risk_price,
                    "risk_pct": risk_pct,
                    "hold_bars": hold_bars,
                    "max_r_multiple": (high_since_entry - entry_price) / risk_per_share if risk_per_share > 0 else None,
                },
            }

        r_multiple = (high_since_entry - entry_price) / risk_per_share if risk_per_share > 0 else 0.0
        if r_multiple >= 2.0:
            return {
                "exit_rule_status": "profit_protection_zone",
                "exit_date": row.get("date"),
                "exit_price": close,
                "exit_rule_note": "VCP达到约2R利润保护区，指南建议进入保本与均线跟踪阶段。",
                "vcp_management": {
                    "entry_price": entry_price,
                    "risk_price": risk_price,
                    "risk_pct": risk_pct,
                    "hold_bars": hold_bars,
                    "max_r_multiple": r_multiple,
                },
            }

        if hold_bars >= time_stop_bars and close <= entry_price:
            return {
                "exit_rule_status": "time_stop_observed",
                "exit_date": row.get("date"),
                "exit_price": close,
                "exit_rule_note": "VCP指南版时间过滤触发：5个交易日后仍未有效推进。",
                "vcp_management": {
                    "entry_price": entry_price,
                    "risk_price": risk_price,
                    "risk_pct": risk_pct,
                    "hold_bars": hold_bars,
                    "max_r_multiple": r_multiple,
                },
            }

    return {
        "exit_rule_status": "still_active_by_rule",
        "exit_rule_note": "截至观察日，VCP指南版初始防守/时间过滤未触发。",
        "vcp_management": {
            "entry_price": entry_price,
            "risk_price": risk_price,
            "risk_pct": risk_pct,
            "max_r_multiple": (high_since_entry - entry_price) / risk_per_share if risk_per_share > 0 else None,
        },
    }
