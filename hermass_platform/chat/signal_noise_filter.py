"""MN1×W1 dual-dimension noise filter for strategy signals.

Uses MN1×W1 cross-calibration from strategy_evaluation optimal-state search data
(2025-06 to 2026-05, 3 strategies × 30 hex combos each).

Key findings (dual-dimension):
  VCP:     MN1=C/D + W1=8-B → +5.97% excess (optimal—"震荡蓄力" hypothesis confirmed)
  MA2560:  MN1=E/F + W1=C/D → +3.94% excess (trend background + W1 consolidation = best entry)
  MA2560:  MN1<0 or W1<0  → auto-downgrade to noise (t-stat≈0.75)
"""

from dataclasses import dataclass

HEX_TO_SCORE: dict[str, int] = {
    "0": 0,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "A": 10,
    "B": 11,
    "C": 12,
    "D": 13,
    "E": 14,
    "F": 15,
    "-1": -1,
    "-2": -2,
    "-3": -3,
    "-C": -12,
    "-E": -14,
    "-F": -15,
}


def _regime(score: int | None) -> str:
    if score is None:
        return "未知"
    if score < 0:
        return "破位"
    if score in (14, 15):
        return "牛市(E/F)"
    if score >= 12:
        return "震荡偏强(C/D)"
    if score >= 8:
        return "扩张未突破(8-B)"
    return "收缩(0-7)"


DUAL_GRID = {
    "vcp": {
        ("震荡偏强(C/D)", "扩张未突破(8-B)"): {
            "score": 95,
            "level": "最优",
            "n": 340,
            "reason": "VCP 震荡蓄力策略。MN1=C/D（大盘稳定）+ W1=8-B（个股蓄力未突破）= 弹簧压缩的完美土壤，超额 +5.97%",
        },
        ("牛市(E/F)", "牛市(E/F)"): {
            "score": 80,
            "level": "高",
            "n": 313,
            "reason": "VCP 全牛环境下超额 +3.86%，但次于震荡蓄力环境",
        },
        ("牛市(E/F)", "震荡偏强(C/D)"): {
            "score": 78,
            "level": "高",
            "n": 352,
            "reason": "VCP 在牛市月线+震荡周线下超额 +3.34%",
        },
        ("扩张未突破(8-B)", "牛市(E/F)"): {
            "score": 72,
            "level": "高",
            "n": 558,
            "reason": "VCP 在月线扩张未突破+周线牛市中，超额 +3.56%",
        },
        ("扩张未突破(8-B)", "震荡偏强(C/D)"): {
            "score": 70,
            "level": "中高",
            "n": 126,
            "reason": "VCP 双扩张阶段超额 +4.41%，样本偏少但方向正面",
        },
        ("震荡偏强(C/D)", "收缩(0-7)"): {
            "score": 65,
            "level": "中",
            "n": 464,
            "reason": "VCP 月线震荡+周线收缩，超额 +3.23%，胜率 51.3% 为所有组合最高",
        },
    },
    "ma2560": {
        ("牛市(E/F)", "震荡偏强(C/D)"): {
            "score": 85,
            "level": "最优",
            "n": 475,
            "reason": "MA2560 趋势策略。MN1=E/F（趋势背景）+ W1=C/D（周线整理）= 金叉最佳触发窗口，超额 +3.94%",
        },
        ("牛市(E/F)", "牛市(E/F)"): {
            "score": 78,
            "level": "高",
            "n": 0,
            "reason": "MA2560 全牛环境：历史组合中该格样本不足（< 100），按 MN1=E/F 单维评分",
        },
        ("扩张未突破(8-B)", "扩张未突破(8-B)"): {
            "score": 60,
            "level": "中",
            "n": 151,
            "reason": "MA2560 双扩张阶段超额 +3.17%，样本 151 个",
        },
        ("震荡偏强(C/D)", "牛市(E/F)"): {
            "score": 55,
            "level": "中",
            "n": 307,
            "reason": "MA2560 月线震荡+周线牛市，超额仅 +2.29%",
        },
        ("震荡偏强(C/D)", "震荡偏强(C/D)"): {
            "score": 45,
            "level": "中低",
            "n": 969,
            "reason": "MA2560 双震荡环境下信号多但超额仅 +1.09%，性价比低",
        },
        ("震荡偏强(C/D)", "扩张未突破(8-B)"): {
            "score": 40,
            "level": "中低",
            "n": 259,
            "reason": "MA2560 在月线震荡+周线扩张未突破阶段超额 +1.41%",
        },
        ("震荡偏强(C/D)", "破位"): {
            "score": 15,
            "level": "噪声",
            "n": 111,
            "reason": "MA2560 月线震荡+周线破位：超额仅 +1.7%，胜率 37.8%",
        },
    },
    "bollinger_bandit": {
        ("牛市(E/F)", "震荡偏强(C/D)"): {
            "score": 80,
            "level": "高",
            "n": 549,
            "reason": "布林强盗在月线牛市+周线震荡中超额 +3.10%，样本最充足",
        },
        ("震荡偏强(C/D)", "震荡偏强(C/D)"): {
            "score": 65,
            "level": "中",
            "n": 172,
            "reason": "布林强盗双震荡环境超额 +3.05%",
        },
        ("震荡偏强(C/D)", "收缩(0-7)"): {
            "score": 60,
            "level": "中",
            "n": 127,
            "reason": "布林强盗在月线震荡+周线收缩中超额 +3.92%但样本仅 127",
        },
        ("震荡偏强(C/D)", "牛市(E/F)"): {
            "score": 55,
            "level": "中",
            "n": 107,
            "reason": "布林强盗月线震荡+周线牛市中超额 +2.31%",
        },
    },
}

STRATEGY_REMAP = {
    "ma2560": "ma2560",
    "vcp": "vcp",
    "bollinger_bandit": "bollinger_bandit",
    "atr_chandelier": "bollinger_bandit",
}

REGIME_DEFAULT = {
    "score": 50,
    "level": "中",
    "n": 0,
    "reason": "该 MN1×W1 组合尚无足够历史校准数据，保守评估",
}


@dataclass
class SignalQuality:
    score: int
    level: str
    reason: str
    should_downgrade: bool


def _hex_to_score(hex_val: str) -> int:
    cleaned = hex_val.strip().replace("\u2212", "-")
    if cleaned.startswith("-"):
        positive = cleaned[1:]
        return -HEX_TO_SCORE.get(positive, 0)
    return HEX_TO_SCORE.get(cleaned, 0)


def evaluate_signal(
    strategy_id: str,
    mn1_state_hex: str,
    w1_state_hex: str = "",
    ef_count: int = -1,
) -> SignalQuality:
    sid = STRATEGY_REMAP.get(strategy_id, "vcp")

    mn1 = _regime(_hex_to_score(mn1_state_hex))
    w1 = _regime(_hex_to_score(w1_state_hex)) if w1_state_hex else "未知"

    grid = DUAL_GRID.get(sid, DUAL_GRID["vcp"])

    key = (mn1, w1)
    info = grid.get(key)

    if info is None and (mn1 == "破位" or w1 == "破位"):
        if mn1 == "破位" and w1 == "破位":
            return SignalQuality(
                score=5,
                level="噪声",
                reason=f"MN1={mn1_state_hex}, W1={w1_state_hex}：双周期破位，所有策略信号建议排除",
                should_downgrade=True,
            )
        if sid == "ma2560":
            return SignalQuality(
                score=10,
                level="噪声",
                reason=f"MA2560 在 MN1={mn1_state_hex}/W1={w1_state_hex} 环境下 t-stat<1.0，信号不显著",
                should_downgrade=True,
            )
        return SignalQuality(
            score=30,
            level="低",
            reason=f"MN1={mn1_state_hex} 或 W1={w1_state_hex} 处于破位区域，信号可靠性下降",
            should_downgrade=True,
        )

    if info is None:
        info = REGIME_DEFAULT

    should_downgrade = info["level"] in ("噪声", "低") or info["score"] < 35

    return SignalQuality(
        score=info["score"],
        level=info["level"],
        reason=info["reason"],
        should_downgrade=should_downgrade,
    )


def get_noise_filter_context(strategy_id: str, mn1_state_hex: str, w1_state_hex: str = "") -> str:
    sq = evaluate_signal(strategy_id, mn1_state_hex, w1_state_hex)

    if sq.level == "噪声":
        return (
            f"\n\n**⚠️ 智能降噪（MN1×W1 双维）**\n{sq.reason}。\n系统建议：该信号环境置信度极低，已自动排除。"
        )
    elif sq.level == "低":
        return f"\n\n**⚠️ 信号风险提示**\n{sq.reason}。"
    elif sq.level == "最优":
        return f"\n\n**🏆 最优环境匹配**\n{sq.reason}。"
    elif sq.level == "高":
        return f"\n\n**✅ 信号质量（MN1×W1 双维验证）**\n{sq.reason}。"

    return ""
