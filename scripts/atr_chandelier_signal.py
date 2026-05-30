#!/usr/bin/env python3
"""ATR Chandelier 策略入场信号。

入场条件（State 过滤）：
- MN1 ∈ {E,F,2,3,6,7,10,11}  → mn1_state_score ∈ {0,1,2,3,6,7,10,11}
- W1  ∈ {E,F,2,3,6,7,10,11}  → w1_state_score ∈ {0,1,2,3,6,7,10,11}
- D1  ∈ {2,3,4,5,6,7,10,11,12,13,14,15} → d1_state_score ∈ {2,3,4,5,6,7,10,11,12,13,14,15}

当三个周期 State 同时满足条件时，产生 atr_chandelier_entry 信号。
该策略不依赖传统技术指标（VCP 收缩、MA 金叉、布林带），
仅依赖多周期 State 共振 + ATR 吊灯跟踪止损出场。
"""

from __future__ import annotations

from typing import Any


# 允许的 State score 集合
_ALLOWED_MN1 = {0, 1, 2, 3, 6, 7, 10, 11}
_ALLOWED_W1 = {0, 1, 2, 3, 6, 7, 10, 11}
_ALLOWED_D1 = {2, 3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 15}


def check_atr_chandelier_entry(
    mn1_state: int | None,
    w1_state: int | None,
    d1_state: int | None,
) -> bool:
    """检查 ATR 吊灯策略的 State 入场条件。

    Args:
        mn1_state: 月线 State score (0-15)
        w1_state: 周线 State score (0-15)
        d1_state: 日线 State score (0-15)

    Returns:
        True 当且仅当三个周期的 State 同时满足允许集合。
    """
    if mn1_state is None or w1_state is None or d1_state is None:
        return False
    return (
        mn1_state in _ALLOWED_MN1
        and w1_state in _ALLOWED_W1
        and d1_state in _ALLOWED_D1
    )


def atr_chandelier_signal(
    row: dict[str, Any],
    ctx: dict[str, Any],
) -> tuple[str, float] | None:
    """ATR Chandelier 策略信号生成函数。

    从 row / ctx 中读取 mn1_state_score, w1_state_score, d1_state_score，
    当三个周期 State 同时满足条件时返回 entry 信号。

    兼容 strategy_signal_ledger.py 的 signal_rows_for_state 调用签名。
    """
    mn1_score = row.get("mn1_state_score")
    w1_score = row.get("w1_state_score")
    d1_score = row.get("d1_state_score")

    # 尝试从 ctx 回退（兼容不同数据源）
    if mn1_score is None:
        mn1_score = ctx.get("mn1_state_score")
    if w1_score is None:
        w1_score = ctx.get("w1_state_score")
    if d1_score is None:
        d1_score = ctx.get("d1_state_score")

    if check_atr_chandelier_entry(mn1_score, w1_score, d1_score):
        return ("atr_chandelier_entry", 0.75)
    return None
