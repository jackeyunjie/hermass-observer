#!/usr/bin/env python3
"""W1×MN1 大周期环境标签计算模块。

根据 MN1/W1 State score 计算大周期背景分类，用于策略信号的环境标注
和适配度调节。
"""

from __future__ import annotations

from typing import Any

# ── 语义桶定义 ────────────────────────────────────────────────────────────────

W1_MN1_ENV_LABELS: dict[str, dict[str, Any]] = {
    "strong_resonance": {
        "label": "大周期共振",
        "description": "月线+周线均扩张有趋势",
        "color": "#22c55e",  # 绿色
        "priority": 1,
    },
    "trend_gestation": {
        "label": "趋势孕育",
        "description": "周线有趋势但月线收缩",
        "color": "#3b82f6",  # 蓝色
        "priority": 2,
    },
    "week_strong_month_weak": {
        "label": "周强月弱",
        "description": "周线趋势确认但月线未跟上",
        "color": "#f59e0b",  # 黄色
        "priority": 3,
    },
    "month_strong_week_weak": {
        "label": "月强周弱",
        "description": "月线趋势但周线回调中",
        "color": "#f59e0b",  # 黄色
        "priority": 4,
    },
    "transition": {
        "label": "大周期过渡",
        "description": "无明确方向",
        "color": "#6b7280",  # 灰色
        "priority": 5,
    },
    "double_contraction": {
        "label": "双重收缩",
        "description": "大小周期均收缩",
        "color": "#ef4444",  # 红色
        "priority": 6,
    },
}

ENV_PRIORITY: dict[str, int] = {
    "strong_resonance": 0,
    "trend_gestation": 1,
    "week_strong_month_weak": 2,
    "month_strong_week_weak": 3,
    "transition": 4,
    "double_contraction": 5,
}

ENV_CATEGORY_FACTOR: dict[str, dict[str, float]] = {
    "strong_resonance": {"vcp": 1.10, "ma2560": 1.12, "bollinger_bandit": 1.10},
    "trend_gestation": {"vcp": 1.08, "ma2560": 0.98, "bollinger_bandit": 0.95},
    "week_strong_month_weak": {"vcp": 1.00, "ma2560": 1.02, "bollinger_bandit": 1.00},
    "month_strong_week_weak": {"vcp": 0.95, "ma2560": 1.05, "bollinger_bandit": 0.98},
    "double_contraction": {"vcp": 0.92, "ma2560": 0.88, "bollinger_bandit": 0.90},
    "transition": {"vcp": 1.00, "ma2560": 1.00, "bollinger_bandit": 1.00},
}


# ── 内部辅助 ──────────────────────────────────────────────────────────────────


def _is_expansion(score: int | None) -> bool:
    """base=8 判断。"""
    if score is None:
        return False
    return abs(score) >= 8


def _is_trending(score: int | None) -> bool:
    """trend_bit=1 判断。"""
    if score is None:
        return False
    return (abs(score) >> 2) & 1 == 1


# ── 核心函数 ──────────────────────────────────────────────────────────────────


def compute_w1_mn1_env_category(
    mn1_state_score: int | None,
    w1_state_score: int | None,
) -> str:
    """根据 MN1 和 W1 的 state_score 计算 6 类环境分类。

    返回 env_category 字符串（6 选 1）。
    """
    w1_exp = _is_expansion(w1_state_score)
    w1_trend = _is_trending(w1_state_score)
    mn1_exp = _is_expansion(mn1_state_score)
    mn1_trend = _is_trending(mn1_state_score)

    # 强共振：双扩张+有趋势
    if w1_exp and w1_trend and mn1_exp and mn1_trend:
        return "strong_resonance"

    # 趋势孕育：W1 有趋势但收缩，MN1 收缩或扩张初期
    if (not w1_exp and w1_trend) and (not mn1_exp or not mn1_trend):
        return "trend_gestation"

    # 周强月弱：W1 扩张有趋势，MN1 收缩或无趋势
    if w1_exp and w1_trend and (not mn1_exp or not mn1_trend):
        return "week_strong_month_weak"

    # 月强周弱：MN1 扩张有趋势，W1 收缩或无趋势
    if mn1_exp and mn1_trend and (not w1_exp or not w1_trend):
        return "month_strong_week_weak"

    # 双重收缩
    if not w1_exp and not mn1_exp:
        return "double_contraction"

    return "transition"


def compute_w1_mn1_env_label(
    mn1_state_score: int | None,
    w1_state_score: int | None,
) -> dict[str, Any]:
    """完整标签计算。

    返回包含 env_category、label、description、color、priority 的字典。
    """
    category = compute_w1_mn1_env_category(mn1_state_score, w1_state_score)
    meta = W1_MN1_ENV_LABELS[category]
    return {
        "env_category": category,
        "label": meta["label"],
        "description": meta["description"],
        "color": meta["color"],
        "priority": meta["priority"],
    }


def compute_env_category_factor(env_category: str, strategy_id: str) -> float:
    """大周期环境对策略的调节系数。"""
    return ENV_CATEGORY_FACTOR.get(env_category, {}).get(strategy_id, 1.0)
