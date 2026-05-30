#!/usr/bin/env python3
"""仓位动态管理模型 — 可复用函数模块。

基于市场阶段和策略加成系数，动态计算建议仓位比例和单笔风险预算。

被 generate_daily_trading_sop.py 调用，也可独立测试。

设计文档：docs/POSITION_SIZING_MODEL.md

使用示例：
    from position_sizing import calculate_dynamic_position

    result = calculate_dynamic_position(
        market_phase="progression",
        strategy_boost=1.15,
        macro_quadrant="复苏",
        fit_level="最佳适配",
    )
    print(result["total_allocation_pct"], result["per_trade_risk_pct"])
"""

from __future__ import annotations

from typing import Any


BASE_ALLOCATION = 0.50  # 基础仓位：总资金的 50%（可配置）

PHASE_FACTORS: dict[str, float] = {
    "contraction": 0.3,
    "emergence": 1.0,
    "progression": 1.2,
    "extension": 0.7,
    "risk_release": 0.0,
    "undetermined": 0.5,
}

MACRO_FACTORS: dict[str, float] = {
    "衰退": 0.8,
    "复苏": 1.0,
    "过热": 0.9,
    "滞胀": 0.5,
}

RISK_TABLE: dict[tuple[str, str], float] = {
    ("emergence", "最佳适配"): 2.5,
    ("emergence", "适配"): 2.0,
    ("emergence", "弱适配"): 1.0,
    ("emergence", "待观察"): 0.5,
    ("progression", "最佳适配"): 2.0,
    ("progression", "适配"): 1.5,
    ("progression", "弱适配"): 1.0,
    ("progression", "待观察"): 0.5,
    ("extension", "最佳适配"): 1.5,
    ("extension", "适配"): 1.0,
    ("extension", "弱适配"): 0.5,
    ("extension", "待观察"): 0.3,
    ("contraction", "最佳适配"): 1.0,
    ("contraction", "适配"): 0.5,
    ("contraction", "弱适配"): 0.0,
    ("contraction", "待观察"): 0.0,
    ("risk_release", "最佳适配"): 0.0,
    ("risk_release", "适配"): 0.0,
    ("risk_release", "弱适配"): 0.0,
    ("risk_release", "待观察"): 0.0,
    ("undetermined", "最佳适配"): 1.5,
    ("undetermined", "适配"): 1.0,
    ("undetermined", "弱适配"): 0.5,
    ("undetermined", "待观察"): 0.3,
}

MAX_POSITIONS_TABLE: dict[str, int] = {
    "contraction": 2,
    "emergence": 8,
    "progression": 10,
    "extension": 5,
    "risk_release": 0,
    "undetermined": 4,
}


def compute_macro_coeff_from_mn1(mn1_state_score: int | None) -> float:
    """沪深300月线 MN1 State → 宏观环境系数。

    规则来自 docs/MACRO_ENVIRONMENT_FILTER_RULES.md 第 2.1 节。

    E/F=1.0, C/D=0.8, A/B=0.6, 8/9=0.5, 4-7=0.3, 0-3=0.0, 负值=0.0
    """
    if mn1_state_score is None:
        return 0.5
    if mn1_state_score < 0:
        return 0.0
    score = abs(mn1_state_score)
    if score >= 14:
        return 1.0
    if score >= 12:
        return 0.8
    if score >= 10:
        return 0.6
    if score >= 8:
        return 0.5
    if score >= 4:
        return 0.3
    return 0.0


def compute_industry_coeff_from_mn1(mn1_state_score: int | None) -> float:
    """行业 ETF 月线 MN1 State → 行业系数。

    规则来自 docs/MACRO_ENVIRONMENT_FILTER_RULES.md 第 1.2 节。

    E/F=1.0, 8-D=0.7, 4-7=0.3, 0-3=0.0, 负值=0.0
    """
    if mn1_state_score is None:
        return 0.5
    if mn1_state_score < 0:
        return 0.0
    score = abs(mn1_state_score)
    if score >= 14:
        return 1.0
    if score >= 8:
        return 0.7
    if score >= 4:
        return 0.3
    return 0.0


def calculate_dynamic_position(
    market_phase: str,
    strategy_boost: float,
    macro_quadrant: str = "复苏",
    fit_level: str = "适配",
    macro_mn1_coeff: float | None = None,
    industry_mn1_coeff: float | None = None,
) -> dict[str, Any]:
    """计算动态仓位。

    公式：
        建议仓位 = 基础仓位 × 阶段系数 × 策略加成系数 × 宏观系数
                  × 大盘月线系数 × 行业月线系数

    参数：
        market_phase：市场阶段（contraction/emergence/progression/extension/risk_release/undetermined）
        strategy_boost：策略加成系数（范围 0.80-1.15）
        macro_quadrant：宏观象限（衰退/复苏/过热/滞胀）
        fit_level：策略-环境适配度（最佳适配/适配/弱适配/待观察）
        macro_mn1_coeff：大盘月线 MN1 系数（可选，优先于 macro_quadrant）
        industry_mn1_coeff：行业月线 MN1 系数（可选）

    返回：dict with total_allocation_pct, per_trade_risk_pct, etc.
    """
    phase_factor = PHASE_FACTORS.get(market_phase, 0.5)

    # 宏观系数：优先用月线 MN1 系数的精确值
    if macro_mn1_coeff is not None:
        macro_factor = macro_mn1_coeff
        macro_source = f"沪深300月线MN1系数={macro_mn1_coeff:.2f}"
    else:
        macro_factor = MACRO_FACTORS.get(macro_quadrant, 1.0)
        macro_source = f"宏观={macro_quadrant}(×{macro_factor})"

    # 行业系数
    industry_factor = industry_mn1_coeff if industry_mn1_coeff is not None else 1.0

    # 核心公式：三层过滤
    raw_allocation = (BASE_ALLOCATION * phase_factor * strategy_boost
                      * macro_factor * industry_factor)

    # 安全钳：上限 100%，下限 0%
    total_allocation = max(0.0, min(1.0, raw_allocation))

    # 单笔风险：查表
    per_trade_risk = RISK_TABLE.get(
        (market_phase, fit_level),
        RISK_TABLE.get(("undetermined", fit_level), 0.5),
    )

    # 最大持仓数：查表
    max_positions = MAX_POSITIONS_TABLE.get(market_phase, 4)

    # 是否允许开新仓
    allow_new = total_allocation > 0 and per_trade_risk > 0

    # 原因说明
    reasons: list[str] = []
    if phase_factor != 1.0:
        label = {"contraction": "收缩期防御", "emergence": "趋势新生",
                 "progression": "趋势行进+20%", "extension": "趋势延展-30%",
                 "risk_release": "风险释放禁开新仓"}.get(market_phase, f"阶段系数={phase_factor}")
        reasons.append(label)
    if strategy_boost != 1.0:
        reasons.append(f"策略加成={strategy_boost:.2f}")
    if macro_mn1_coeff is not None:
        reasons.append(macro_source)
    elif macro_factor != 1.0:
        reasons.append(f"宏观={macro_quadrant}(×{macro_factor})")
    if industry_mn1_coeff is not None and industry_mn1_coeff != 1.0:
        reasons.append(f"行业月线系数={industry_mn1_coeff:.2f}")
    if per_trade_risk == 0:
        reasons.append("当前环境不建议开新仓")

    return {
        "total_allocation_pct": round(total_allocation, 4),
        "per_trade_risk_pct": per_trade_risk,
        "max_positions": max_positions,
        "phase_factor": phase_factor,
        "strategy_boost": strategy_boost,
        "macro_factor": macro_factor,
        "macro_mn1_coeff": macro_mn1_coeff,
        "industry_mn1_coeff": industry_mn1_coeff,
        "base_allocation_pct": BASE_ALLOCATION,
        "allow_new_positions": allow_new,
        "reason": " × ".join(reasons) if reasons else "标准环境",
    }


def render_quick_reference_table() -> str:
    """生成仓位管理速查表（Markdown）。"""
    phases = ["emergence", "progression", "extension", "contraction", "risk_release", "undetermined"]
    fit_levels = ["最佳适配", "适配", "弱适配", "待观察"]
    phase_labels = {
        "emergence": "趋势新生", "progression": "趋势行进",
        "extension": "趋势延展", "contraction": "收缩期",
        "risk_release": "风险释放", "undetermined": "未分类",
    }

    lines = [
        "## 仓位管理速查表",
        "",
        "| 市场阶段 | 适配度 | 建议仓位 | 单笔风险% | 最大持仓 | 是否开仓 |",
        "|----------|--------|----------|-----------|----------|----------|",
    ]

    for phase in phases:
        for fit in fit_levels:
            result = calculate_dynamic_position(
                phase, 1.0, "复苏", fit,
            )
            risk = result["per_trade_risk_pct"]
            alloc = f"{result['total_allocation_pct']:.0%}"
            allow = "✅" if result["allow_new_positions"] else "❌"
            lines.append(
                f"| {phase_labels[phase]} | {fit} | {alloc} | {risk:.1f}% | "
                f"{result['max_positions']} | {allow} |"
            )

    return "\n".join(lines)


if __name__ == "__main__":
    print(render_quick_reference_table())
