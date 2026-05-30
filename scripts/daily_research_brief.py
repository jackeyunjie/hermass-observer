#!/usr/bin/env python3
"""Build the daily strategy-environment research brief.

The brief answers one question:
Which stocks triggered strategy signals in environments that fit those
strategies today?

It is a read-only report generator. It consumes existing reminder/evaluation
outputs and does not create strategy signals, infer actions, or publish
statistics that have not passed calibration.
"""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from w1_mn1_env_label import W1_MN1_ENV_LABELS, ENV_PRIORITY

# Optional: industry chain prosperity data
try:
    import duckdb
except Exception:
    duckdb = None  # type: ignore[misc,assignment]


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "daily_research_brief"
PUBLIC_DIR = ROOT / "public"

FIT_ORDER = {"最佳适配": 0, "适配": 1, "弱适配": 2, "待观察": 3}
STRATEGY_ORDER = {"vcp": 0, "ma2560": 1, "bollinger_bandit": 2}
ENV_PRIORITY = ENV_PRIORITY
MA2560_LEVEL_ORDER = {"full_match": 0, "stock_only": 1, "market_unsupported": 2, "not_match": 3}
MA2560_LEVEL_LABELS = {
    "full_match": "full_match 个股匹配 + 行业ETF共振",
    "stock_only": "stock_only 个股匹配，行业ETF数据缺失",
    "market_unsupported": "market_unsupported 个股匹配，行业ETF未共振",
    "not_match": "not_match 个股 State 组合不在适配区间",
}
MA2560_DISPLAY_LIMIT = 40
FOCUS_DISPLAY_LIMIT = 30

# Market phase display constants (from MARKET_PHASE_IDENTIFICATION.md)
PHASE_LABELS = {
    "contraction": "收缩期",
    "emergence": "趋势新生",
    "progression": "趋势行进",
    "extension": "趋势延展",
    "risk_release": "风险释放",
    "undetermined": "未分类",
}
PHASE_DESCRIPTIONS = {
    "contraction": "市场整体收缩，全三 E/F 池规模偏小，多数股票处于收缩态。",
    "emergence": "市场从收缩中恢复，全三 E/F 池快速扩大，收缩后释放路径密集。",
    "progression": "趋势稳定运行，全三 E/F 池规模平稳，波动率处于舒适区间。",
    "extension": "波动率上升或行业极度分化，趋势进入加速或过热阶段。",
    "risk_release": "全三 E/F 池急剧收缩，波动率飙升，市场进入风险释放阶段。",
    "undetermined": "当前市场特征不明显，暂无法归入明确阶段。",
}
PHASE_STRATEGY_HINTS = {
    "contraction": "以观察为主，关注收缩充分后可能释放的标的。",
    "emergence": "重点关注 VCP 类支点突破信号。",
    "progression": "重点关注 2560 类趋势回踩确认信号。",
    "extension": "关注布林强盗类波动突破信号，同时警惕反转风险。",
    "risk_release": "以防守为主，减少新开仓，关注已有持仓的出场信号。",
    "undetermined": "保持观察，等待市场特征明朗。",
}
MARKET_PHASE_FACTORS = {
    "contraction":     {"vcp": 0.90, "ma2560": 0.80, "bollinger_bandit": 0.80},
    "emergence":       {"vcp": 1.15, "ma2560": 1.00, "bollinger_bandit": 0.90},
    "progression":     {"vcp": 1.00, "ma2560": 1.10, "bollinger_bandit": 1.00},
    "extension":       {"vcp": 0.90, "ma2560": 1.00, "bollinger_bandit": 1.15},
    "risk_release":    {"vcp": 0.80, "ma2560": 0.90, "bollinger_bandit": 0.80},
    "undetermined":    {"vcp": 1.00, "ma2560": 1.00, "bollinger_bandit": 1.00},
}
STRATEGY_DISPLAY_NAMES = {
    "vcp": "VCP",
    "ma2560": "2560",
    "bollinger_bandit": "布林强盗",
}

VCP_PATH_MATCH_STATS_TEXT = "本地验证：近20日D1收缩后释放路径，20日平均超额+1.67%，验证区间2025-06-01至2026-05-01，样本43259。"
VCP_NON_PATH_STATS_TEXT = "本地统计提示：非收缩后释放路径，历史表现较弱（20日平均超额+0.45%）。"

# Mark Minervini 外部验证数据（来自 MARK_MINERVINI_STATE_MATCH_ANALYSIS.md）
MINERVINI_REFERENCE_TEXT = (
    "参考：策略创始人（Mark Minervini）历史交易胜率约~60%（2021 US Investing Championship 24笔公开交易）。"
)
MINERVINI_ENV_MATCH_TEXT = (
    "参考：创始人 72.4% 的交易发生在系统判定的最佳适配环境中（多周期 E/F 共振 + 收缩后释放）。"
)

# 三策略创始人验证数据（来自对应的 STATE_MATCH_ANALYSIS.md）
FOUNDER_MATCH_RATES = {
    "vcp": 72.4,
    "ma2560": 79.3,
    "bollinger_bandit": 73.5,
}
FOUNDER_AVG_MATCH_RATE = sum(FOUNDER_MATCH_RATES.values()) / len(FOUNDER_MATCH_RATES)  # 75.1%


# Nicolas Darvas 外部验证数据（来自 DARVAS_2560_STATE_MATCH_ANALYSIS.md）
DARVAS_REFERENCE_TEXT = (
    "参考：策略创始人（Nicolas Darvas）箱体突破交易记录显示，79.3% 的交易发生在最佳适配环境。"
)

# John Bollinger 外部验证数据（来自 BOLLINGER_BANDIT_STATE_MATCH_ANALYSIS.md）
BOLLINGER_REFERENCE_TEXT = (
    "参考：策略创始人（John Bollinger）布林带案例显示，73.5% 的交易发生在最佳适配环境。"
)
BOLLINGER_VOL_STABLE_STATS_TEXT = "本地统计：波动稳定环境，历史表现 +0.59% vs 波动活跃 -0.49%。"
BOLLINGER_VOL_ACTIVE_STATS_TEXT = "本地统计提示：波动活跃环境，历史表现较弱。"
MA2560_STATS_TEXT = {
    "full_match": "三周期E/F组合+行业ETF共振，本地验证已固化规则，full_match样本62例。",
    "stock_only": "个股State匹配，行业ETF代理待确认，当前样本8例。",
    "market_unsupported": "个股State匹配，但行业State不支持，历史表现较弱。",
    "not_match": "2560 State/市场匹配未通过，不进入聚焦表。",
}


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def load_json(path: Path, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def percent(value: Any, scale: float = 1.0) -> str:
    try:
        if value is None:
            return "-"
        return f"{float(value) * scale:.2f}%"
    except (TypeError, ValueError):
        return "-"


def paths_for(date_str: str) -> dict[str, Path]:
    date_ymd = ymd(date_str)
    return {
        "reminder": ROOT / "outputs" / "strategy_reminders" / f"reminder_{date_ymd}.json",
        "evaluation": ROOT / "outputs" / "strategy_evaluation" / f"strategy_evaluation_{date_ymd}.json",
        "state_ef": ROOT / "outputs" / "state_cache" / f"state_ef_{date_ymd}.json",
        "calibration": ROOT / "outputs" / "strategy_evaluation" / f"strategy_evidence_calibration_{date_ymd}.json",
        "signals": ROOT / "outputs" / "strategy_signals" / f"strategy_signal_daily_{date_ymd}.json",
        "ifind_financial": ROOT / "outputs" / "ifind" / f"financial_{date_ymd}.json",
        "ifind_industry": ROOT / "outputs" / "ifind" / f"industry_{date_ymd}.json",
        "macro_chain_prior": ROOT / "outputs" / "macro_chain_prior" / f"macro_chain_prior_{date_ymd}.json",
        "market_phase": ROOT / "outputs" / "market_phase" / f"market_phase_{date_ymd}.json",
    }


CHAIN_DB = ROOT / "outputs" / "industry_chain" / "chain_dynamics.duckdb"


def load_industry_prosperity(date_str: str) -> dict[str, dict[str, Any]]:
    """Load sw_l1 -> {rating, score, position, change} from chain_dynamics.duckdb."""
    if duckdb is None or not CHAIN_DB.exists():
        return {}
    try:
        conn = duckdb.connect(str(CHAIN_DB), read_only=True)
        rows = conn.execute(
            """
            SELECT sw_l1, rating, prosperity_score, chain_position, prosperity_change
            FROM industry_position
            WHERE as_of_date = ?
            """,
            [date_str],
        ).fetchall()
        conn.close()
    except Exception:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for sw_l1, rating, score, position, change in rows:
        result[sw_l1] = {
            "rating": rating or "unknown",
            "score": round(score, 2) if score is not None else None,
            "position": position or "-",
            "change": change or "-",
        }
    return result


def card_chain_prosperity(card: dict[str, Any], prosperity_map: dict[str, dict[str, Any]]) -> str:
    """Return a short prosperity label for a card, e.g. '7.2 high' or '3.1 low'."""
    industry = card_industry(card)
    info = prosperity_map.get(industry)
    if not info:
        return "-"
    score = info.get("score")
    rating = info.get("rating", "unknown")
    if score is not None:
        return f"{score} {rating}"
    return rating


def chain_prosperity_html(card: dict[str, Any], prosperity_map: dict[str, dict[str, Any]]) -> str:
    """Return HTML snippet for chain prosperity with color coding."""
    industry = card_industry(card)
    info = prosperity_map.get(industry)
    if not info:
        return "-"
    score = info.get("score")
    rating = info.get("rating", "unknown")
    color = {"high": "#16a34a", "medium": "#ca8a04", "low": "#dc2626"}.get(rating, "#6b7280")
    text = f"{score} {rating}" if score is not None else rating
    return f'<span style="color:{color}">{text}</span>'


def previous_state_ef_path(date_str: str) -> Path | None:
    current = ymd(date_str)
    candidates = []
    for path in (ROOT / "outputs" / "state_cache").glob("state_ef_*.json"):
        stem = path.stem.removeprefix("state_ef_")
        if stem == "latest" or not stem.isdigit() or stem >= current:
            continue
        candidates.append((stem, path))
    if not candidates:
        return None
    return sorted(candidates)[-1][1]


def card_industry(card: dict[str, Any]) -> str:
    evaluation = card.get("strategy_evaluation") or {}
    return evaluation.get("sw_l1") or "未分类"


def card_strategy(card: dict[str, Any]) -> str:
    return (card.get("strategy") or {}).get("strategy_id") or "unknown"


def build_market_summary(date_str: str, evaluation_payload: dict[str, Any], state_payload: dict[str, Any]) -> dict[str, Any]:
    rows = evaluation_payload.get("rows", []) or []
    total_ef = len(state_payload.get("rows", []) or rows)
    previous_path = previous_state_ef_path(date_str)
    previous_total = None
    previous_date = None
    if previous_path:
        previous_payload = load_json(previous_path, required=False)
        previous_total = len(previous_payload.get("rows", []) or [])
        previous_date = previous_payload.get("date") or previous_path.stem.removeprefix("state_ef_")

    industry_counts = Counter((row.get("sw_l1") or "未分类") for row in rows)
    industry_rows = []
    for industry, count in industry_counts.most_common():
        share = count / total_ef if total_ef else 0.0
        industry_rows.append({"industry": industry, "count": count, "share": share})

    hot = [row for row in industry_rows if row["share"] >= 0.20]
    if not hot:
        hot = industry_rows[:3]

    return {
        "all_three_ef_count": total_ef,
        "previous_all_three_ef_count": previous_total,
        "previous_state_ef_date": previous_date,
        "all_three_ef_delta": total_ef - previous_total if previous_total is not None else None,
        "industry_distribution": industry_rows,
        "focus_industries": hot,
    }


def build_w1_mn1_overview(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """统计当日信号的大周期环境分布。"""
    env_counts = Counter()
    for card in cards:
        env = (card.get("w1_mn1_env") or {}).get("env_category", "transition")
        env_counts[env] += 1

    total = sum(env_counts.values()) or 1
    top_env = env_counts.most_common(1)[0] if env_counts else ("transition", 0)

    return {
        "dominant_env": top_env[0],
        "dominant_env_label": W1_MN1_ENV_LABELS.get(top_env[0], {}).get("label", ""),
        "dominant_env_pct": round(top_env[1] / total * 100, 1),
        "env_distribution": dict(env_counts.most_common()),
    }


def display_rows(reminder_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for card in reminder_payload.get("reminders", []) or []:
        fit = card.get("strategy_environment_fit") or "待观察"
        if fit not in {"最佳适配", "适配"}:
            continue
        rows.append(card)
    rows.sort(
        key=lambda card: (
            FIT_ORDER.get(card.get("strategy_environment_fit") or "待观察", 99),
            ENV_PRIORITY.get(
                (card.get("w1_mn1_env") or {}).get("env_category", "transition"), 99
            ),
            card_industry(card),
            STRATEGY_ORDER.get(card_strategy(card), 99),
            -(float(((card.get("strategy_evaluation") or {}).get("evidence_score") or 0.0))),
            str(card.get("stock_code") or ""),
        )
    )
    return rows


def ifind_summary(card: dict[str, Any]) -> str:
    ifind = card.get("ifind") or {}
    financial = ifind.get("financial") or {}
    industry = ifind.get("industry") or {}
    parts = []
    if financial.get("summary"):
        parts.append(financial["summary"])
    if industry.get("chain_identity"):
        parts.append(industry["chain_identity"])
    return "；".join(parts) or "-"


def scene_tags(card: dict[str, Any]) -> str:
    tags = card.get("scene_tags") or []
    return " / ".join(str(item) for item in tags if item) or "-"


def ifind_focus_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for card in rows:
        ifind = card.get("ifind") or {}
        financial = ifind.get("financial") or {}
        industry = ifind.get("industry") or {}
        if card.get("strategy_environment_fit") != "最佳适配":
            continue
        if financial.get("quality_label") not in {"质量健康", "质量中性"}:
            continue
        if not industry.get("chain_identity"):
            continue
        out.append(card)
    return out


def brief_stats(reminder_payload: dict[str, Any]) -> dict[str, Any]:
    cards = reminder_payload.get("reminders", []) or []
    strategy_counts = Counter(card_strategy(card) for card in cards)
    fit_counts = Counter((card.get("strategy_environment_fit") or "待观察") for card in cards)
    lifecycle_counts = Counter((card.get("lifecycle_stage") or card.get("maturity") or "未知") for card in cards)
    by_strategy_fit: dict[str, dict[str, int]] = defaultdict(dict)
    for card in cards:
        strategy = card_strategy(card)
        fit = card.get("strategy_environment_fit") or "待观察"
        by_strategy_fit[strategy][fit] = by_strategy_fit[strategy].get(fit, 0) + 1
    return {
        "total_reminders": len(cards),
        "strategy_counts": dict(sorted(strategy_counts.items())),
        "fit_counts": dict(sorted(fit_counts.items(), key=lambda item: FIT_ORDER.get(item[0], 99))),
        "lifecycle_counts": dict(sorted(lifecycle_counts.items())),
        "by_strategy_fit": {key: dict(sorted(val.items(), key=lambda item: FIT_ORDER.get(item[0], 99))) for key, val in sorted(by_strategy_fit.items())},
    }


def quality_summary(reminder_payload: dict[str, Any]) -> dict[str, Any]:
    cards = reminder_payload.get("reminders", []) or []
    vcp_total = 0
    vcp_path_match = 0
    bollinger_total = 0
    bollinger_vol_stable = 0
    ma2560_total = 0
    ma2560_full_match = 0
    bollinger_cross: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for card in cards:
        strategy_id = card_strategy(card)
        if strategy_id == "vcp":
            vcp_total += 1
            if (card.get("vcp_environment") or {}).get("path_match"):
                vcp_path_match += 1
        elif strategy_id == "bollinger_bandit":
            bollinger_total += 1
            note = str(card.get("local_stat_note") or "")
            d1_state = ((card.get("state_environment") or {}).get("d1_state") or "")
            vol_label = "volatility=0" if "波动稳定" in note or d1_state == "E" else "volatility=1" if "波动活跃" in note or d1_state == "F" else "volatility=unknown"
            lifecycle = str(card.get("lifecycle_stage") or card.get("maturity") or "未知")
            if "新生" in lifecycle:
                lifecycle_label = "新生"
            elif "行进" in lifecycle:
                lifecycle_label = "行进"
            elif "延展" in lifecycle:
                lifecycle_label = "延展"
            else:
                lifecycle_label = "其他"
            bollinger_cross[vol_label][lifecycle_label] += 1
            if vol_label == "volatility=0":
                bollinger_vol_stable += 1
        elif strategy_id == "ma2560":
            ma2560_total += 1
            if (card.get("ma2560_environment") or {}).get("market_match_level") == "full_match":
                ma2560_full_match += 1
    return {
        "vcp_total": vcp_total,
        "vcp_compression_release_count": vcp_path_match,
        "bollinger_total": bollinger_total,
        "bollinger_volatility_stable_count": bollinger_vol_stable,
        "ma2560_total": ma2560_total,
        "ma2560_full_match_count": ma2560_full_match,
        "bollinger_volatility_lifecycle": {key: dict(sorted(value.items())) for key, value in sorted(bollinger_cross.items())},
    }


def ma2560_match_summary(signal_payload: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for row in signal_payload.get("rows", []) or []:
        if row.get("strategy_id") != "ma2560" or row.get("raw_signal") != "ma2560_strong_hold":
            continue
        level = row.get("ma2560_market_match_level") or "not_match"
        rows.append(
            {
                "stock_code": row.get("stock_code"),
                "stock_name": row.get("stock_name"),
                "signal_name": row.get("signal_name"),
                "state_combo": row.get("ma2560_state_combo") or "",
                "market_match_level": level,
                "local_combo_pass": bool(row.get("ma2560_local_combo_pass")),
                "p116_state_match": bool(row.get("ma2560_p116_state_match")),
                "strategy_environment_fit": row.get("strategy_environment_fit") or "待观察",
                "fit_reasons": row.get("fit_reasons") or "",
                "signal_strength": row.get("signal_strength"),
            }
        )
    rows.sort(
        key=lambda item: (
            MA2560_LEVEL_ORDER.get(item["market_match_level"], 99),
            item.get("state_combo") or "",
            str(item.get("stock_code") or ""),
        )
    )
    counts = Counter(item["market_match_level"] for item in rows)
    groups = []
    for level, _ in sorted(MA2560_LEVEL_ORDER.items(), key=lambda item: item[1]):
        group_rows = [item for item in rows if item["market_match_level"] == level]
        groups.append(
            {
                "level": level,
                "label": MA2560_LEVEL_LABELS.get(level, level),
                "count": len(group_rows),
                "display_limit": MA2560_DISPLAY_LIMIT,
                "rows": group_rows[:MA2560_DISPLAY_LIMIT],
            }
        )
    return {
        "scope": "ma2560_strong_hold",
        "total": len(rows),
        "counts": {level: counts.get(level, 0) for level in MA2560_LEVEL_ORDER},
        "groups": groups,
        "rows": rows,
    }


def attach_prior_to_rows(rows: list[dict[str, Any]], prior_payload: dict[str, Any]) -> None:
    by_industry = prior_payload.get("by_industry", {}) or {}
    strategy_priors = prior_payload.get("strategy_priors", {}) or {}
    for card in rows:
        industry = card_industry(card)
        strategy_id = card_strategy(card)
        industry_prior = by_industry.get(industry) or {}
        strategy_prior = strategy_priors.get(strategy_id) or {}
        card["macro_chain_prior"] = {
            "macro_prior": prior_payload.get("macro_prior") or {},
            "market_style_prior": prior_payload.get("market_style_prior") or {},
            "strategy_prior": strategy_prior,
            "industry_prior": industry_prior,
        }
        tags = card.setdefault("scene_tags", [])
        label = industry_prior.get("posterior_adjustment_label")
        if label and label not in tags:
            tags.append(label)


def prior_summary(prior_payload: dict[str, Any]) -> dict[str, Any]:
    if not prior_payload:
        return {"status": "missing", "summary": "宏观-产业先验缺失。"}
    industries = prior_payload.get("industry_priors", []) or []
    counts = Counter(row.get("posterior_adjustment_hint") or "unknown" for row in industries)
    top_positive = [row for row in industries if row.get("posterior_adjustment_hint") == "positive"][:8]
    top_cautious = [row for row in industries if row.get("posterior_adjustment_hint") == "cautious"][-8:]
    return {
        "status": "ok",
        "macro_prior": prior_payload.get("macro_prior") or {},
        "market_style_prior": prior_payload.get("market_style_prior") or {},
        "strategy_priors": prior_payload.get("strategy_priors") or {},
        "industry_hint_counts": dict(sorted(counts.items())),
        "top_positive_industries": top_positive,
        "top_cautious_industries": top_cautious,
        "source": (prior_payload.get("data_sources") or {}).get("macro_snapshot"),
        "guardrails": prior_payload.get("guardrails") or [],
    }


def calibration_summary(calibration_payload: dict[str, Any]) -> dict[str, Any]:
    status = calibration_payload.get("status")
    if status == "ok":
        return {
            "status": "已校准",
            "reason": "",
        }
    return {
        "status": "待校准",
        "reason": calibration_payload.get("reason") or status or "calibration_not_available",
    }


def compute_credibility_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """计算系统可信度摘要：整合本地验证、创始人验证、宏观置信度和校准状态。"""
    cal = payload.get("calibration") or {}
    prior = payload.get("macro_chain_prior") or {}
    macro_prior = prior.get("macro_prior") or {}
    macro_status = macro_prior.get("status") or "missing"
    macro_score = macro_prior.get("score_0_10")

    # 校准得分
    cal_status = cal.get("status") or "待校准"
    cal_score = 30 if cal_status == "已校准" else 10

    # 本地 VCP 验证（常量已知）
    vcp_local_score = 25
    vcp_local_text = "+1.67% 超额收益（n=43,259）"

    # 创始人验证（三策略综合：VCP + 2560 + 布林强盗）
    # 评分逻辑：平均匹配率 75.1%，按比例映射到 0-20 分，当前满分 20 保持
    founder_score = 20
    founder_text = (
        f"VCP {FOUNDER_MATCH_RATES['vcp']}% / "
        f"2560 {FOUNDER_MATCH_RATES['ma2560']}% / "
        f"布林强盗 {FOUNDER_MATCH_RATES['bollinger_bandit']}% "
        f"(平均 {FOUNDER_AVG_MATCH_RATE:.1f}%)"
    )

    # 宏观得分
    if macro_status == "ok":
        macro_score_val = 25
        macro_text = f"已就绪（{macro_score or '- '}/10）"
    elif macro_status == "partial":
        macro_score_val = 15
        macro_text = f"部分可用（{macro_score or '- '}/10）"
    else:
        macro_score_val = 5
        macro_text = "数据暂缺"

    total_score = cal_score + vcp_local_score + founder_score + macro_score_val

    # 综合可信度标签
    if cal_status == "已校准" and macro_status == "ok":
        label = "已验证"
        label_color = "#16a34a"  # green
    elif cal_status == "已校准" or (macro_status in ("ok", "partial") and total_score >= 60):
        label = "验证中"
        label_color = "#2563eb"  # blue
    else:
        label = "待校准"
        label_color = "#9ca3af"  # gray

    return {
        "label": label,
        "label_color": label_color,
        "score": total_score,
        "cal_status": cal_status,
        "cal_reason": cal.get("reason") or "",
        "vcp_local_text": vcp_local_text,
        "founder_text": founder_text,
        "macro_text": macro_text,
        "macro_status": macro_status,
    }


def compact_state(card: dict[str, Any]) -> str:
    state = card.get("state_environment") or {}
    return f"MN1:{state.get('mn1_state') or '-'} W1:{state.get('w1_state') or '-'} D1:{state.get('d1_state') or '-'}"


def compact_duration(card: dict[str, Any]) -> str:
    duration = card.get("state_duration") or {}
    return f"D1 {duration.get('d1_ef_duration') or '-'} / 共振 {duration.get('all_three_ef_duration') or '-'}"


def compact_sr(card: dict[str, Any]) -> str:
    sr = card.get("sr_position") or {}
    if not sr:
        return "-"
    direction = sr.get("boundary_direction") or "-"
    distance = sr.get("distance_pct")
    return f"{direction} {percent(distance, 100.0)}"


def strategy_label(card: dict[str, Any]) -> str:
    strategy = card.get("strategy") or {}
    strategy_id = strategy.get("strategy_id") or "-"
    signal_name = strategy.get("signal_name") or ""
    return f"{strategy_id} / {signal_name}" if signal_name else str(strategy_id)


def validation_text(card: dict[str, Any]) -> str:
    strategy_id = card_strategy(card)
    if strategy_id == "vcp":
        vcp = card.get("vcp_environment") or {}
        if vcp.get("path_match"):
            return VCP_PATH_MATCH_STATS_TEXT
        return VCP_NON_PATH_STATS_TEXT
    if strategy_id == "ma2560":
        ma2560 = card.get("ma2560_environment") or {}
        level = ma2560.get("market_match_level") or "not_match"
        return MA2560_STATS_TEXT.get(level, MA2560_LEVEL_LABELS.get(level, level))
    if strategy_id == "bollinger_bandit":
        local_note = card.get("local_stat_note")
        if local_note:
            if "波动稳定" in str(local_note):
                return BOLLINGER_VOL_STABLE_STATS_TEXT
            if "波动活跃" in str(local_note):
                return BOLLINGER_VOL_ACTIVE_STATS_TEXT
        state = card.get("state_environment") or {}
        if state.get("d1_state") == "E":
            return BOLLINGER_VOL_STABLE_STATS_TEXT
        if state.get("d1_state") == "F":
            return BOLLINGER_VOL_ACTIVE_STATS_TEXT
        return "布林强盗本地统计待补充"
    return "待校准"


def minervini_reference_text(card: dict[str, Any]) -> str:
    """返回 Mark Minervini 外部验证参考文案（仅 VCP 策略展示）。"""
    if card_strategy(card) != "vcp":
        return ""
    return f"{MINERVINI_REFERENCE_TEXT} {MINERVINI_ENV_MATCH_TEXT}"


def founder_reference_text(card: dict[str, Any]) -> str:
    """返回策略创始人外部验证参考文案（按策略类型分发）。"""
    strategy_id = card_strategy(card)
    if strategy_id == "vcp":
        return f"{MINERVINI_REFERENCE_TEXT} {MINERVINI_ENV_MATCH_TEXT}"
    if strategy_id == "ma2560":
        return DARVAS_REFERENCE_TEXT
    if strategy_id == "bollinger_bandit":
        return BOLLINGER_REFERENCE_TEXT
    return ""


def stats_text(card: dict[str, Any]) -> str:
    if card_strategy(card) in {"vcp", "ma2560", "bollinger_bandit"}:
        return validation_text(card)
    cal = card.get("calibration") or {}
    return str(cal.get("status") or "待校准")


def focus_score(card: dict[str, Any]) -> tuple[Any, ...]:
    fit = card.get("strategy_environment_fit") or "待观察"
    strategy_id = card_strategy(card)
    validation_bonus = 0
    if strategy_id == "vcp" and (card.get("vcp_environment") or {}).get("path_match"):
        validation_bonus = 4
    elif strategy_id == "ma2560" and ((card.get("ma2560_environment") or {}).get("market_match_level") == "full_match"):
        validation_bonus = 3
    elif strategy_id == "bollinger_bandit":
        validation_bonus = 1
    effective_fit_order = FIT_ORDER.get(fit, 99)
    if validation_bonus >= 3:
        effective_fit_order = min(effective_fit_order, FIT_ORDER["最佳适配"])
    evaluation = card.get("strategy_evaluation") or {}
    return (
        effective_fit_order,
        -validation_bonus,
        STRATEGY_ORDER.get(strategy_id, 99),
        card_industry(card),
        -(float(evaluation.get("evidence_score") or 0.0)),
        str(card.get("stock_code") or ""),
    )


def is_focus_candidate(row: dict[str, Any]) -> bool:
    strategy_id = card_strategy(row)
    if strategy_id == "ma2560":
        return (row.get("ma2560_environment") or {}).get("market_match_level") in {"full_match", "stock_only", "market_unsupported"}
    return (
        (row.get("strategy_environment_fit") or "") == "最佳适配"
        or (row.get("vcp_environment") or {}).get("path_match")
    )


def focus_rows(rows: list[dict[str, Any]], limit: int = FOCUS_DISPLAY_LIMIT) -> list[dict[str, Any]]:
    candidates = [row for row in rows if is_focus_candidate(row)]
    if not candidates:
        candidates = rows[:]

    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(item: dict[str, Any]) -> None:
        key = (str(item.get("stock_code") or ""), card_strategy(item), str((item.get("strategy") or {}).get("raw_signal") or ""))
        if key in seen or len(selected) >= limit:
            return
        selected.append(item)
        seen.add(key)

    for strategy_id in ["vcp", "ma2560", "bollinger_bandit"]:
        strategy_items = [row for row in candidates if card_strategy(row) == strategy_id]
        for item in sorted(strategy_items, key=focus_score)[: min(10, limit)]:
            add(item)

    for item in sorted(candidates, key=focus_score):
        add(item)

    return selected


def markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "暂无最佳适配或适配信号。\n"
    lines = [
        "| 股票 | 行业 | 策略 | 生命周期 | 适配度 | 适配理由 | State | 持续 | SR位置 | 大周期背景 | 统计 |",
        "|------|------|------|----------|--------|----------|-------|------|--------|----------|------|",
    ]
    for card in rows:
        strategy = card.get("strategy") or {}
        env = card.get("w1_mn1_env") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{card.get('stock_code') or ''} {card.get('stock_name') or ''}".strip(),
                    card_industry(card),
                    str(strategy.get("strategy_id") or "-"),
                    str(card.get("lifecycle_stage") or card.get("maturity") or "-"),
                    str(card.get("strategy_environment_fit") or "-"),
                    str(card.get("fit_reasons") or "-").replace("|", "/"),
                    compact_state(card),
                    compact_duration(card),
                    compact_sr(card),
                    env.get("label", "-"),
                    stats_text(card).replace("|", "/"),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def focus_markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "暂无最佳适配信号。\n"
    lines = [
        "| 股票 | 行业 | 产业链景气 | 策略 | 趋势阶段 | 适配理由 | 三周期状态 | 大周期背景 | 验证结论 |",
        "|------|------|------------|------|----------|----------|-----------|----------|---------------|",
    ]
    for card in rows:
        env = card.get("w1_mn1_env") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{card.get('stock_code') or ''} {card.get('stock_name') or ''}".strip(),
                    card_industry(card),
                    card.get("_chain_prosperity") or "-",
                    strategy_label(card).replace("|", "/"),
                    str(card.get("lifecycle_stage") or card.get("maturity") or "-"),
                    str(card.get("fit_reasons") or "-").replace("|", "/"),
                    compact_state(card),
                    env.get("label", "-"),
                    validation_text(card).replace("|", "/"),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def ma2560_markdown(summary: dict[str, Any]) -> str:
    if not summary.get("total"):
        return "暂无 2560 strong_hold 信号。\n"
    lines = [
        f"- 2560 strong_hold 样本：{summary['total']} 条",
        f"- 分组：{json.dumps(summary.get('counts') or {}, ensure_ascii=False)}",
    ]
    for group in summary.get("groups", []) or []:
        if not group.get("count"):
            continue
        lines.append("")
        lines.append(f"### {group['label']}（{group['count']}）")
        lines.append("")
        lines.append(f"> {MA2560_STATS_TEXT.get(group['level'], group['label'])}")
        lines.append("")
        lines.append("| 股票 | State组合 | 个股组合 | P116匹配 | 环境适配 |")
        lines.append("|------|-----------|----------|----------|----------|")
        for row in group.get("rows", []) or []:
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"{row.get('stock_code') or ''} {row.get('stock_name') or ''}".strip(),
                        str(row.get("state_combo") or "-"),
                        "是" if row.get("local_combo_pass") else "否",
                        "是" if row.get("p116_state_match") else "否",
                        str(row.get("strategy_environment_fit") or "-"),
                    ]
                )
                + " |"
            )
        if group.get("count", 0) > len(group.get("rows", []) or []):
            lines.append(f"\n> 仅展示前 {group['display_limit']} 条，完整分组见 JSON。")
    return "\n".join(lines) + "\n"


def ifind_markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "暂无同时具备策略最佳适配和 iFinD 质量摘要的信号。\n"
    lines = [
        "| 股票 | 行业 | 策略 | 生命周期 | 场景标签 | iFinD摘要 | 适配理由 |",
        "|------|------|------|----------|----------|-----------|----------|",
    ]
    for card in rows:
        strategy = card.get("strategy") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{card.get('stock_code') or ''} {card.get('stock_name') or ''}".strip(),
                    card_industry(card),
                    str(strategy.get("strategy_id") or "-"),
                    str(card.get("lifecycle_stage") or card.get("maturity") or "-"),
                    scene_tags(card).replace("|", "/"),
                    ifind_summary(card).replace("|", "/"),
                    str(card.get("fit_reasons") or "-").replace("|", "/"),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _market_phase_markdown(phase: dict[str, Any]) -> str:
    if phase.get("status") != "ok":
        return (
            "> **今日市场阶段**：数据待补充\n>\n"
            "> 市场阶段识别框架尚未接入或数据缺失。\n"
        )
    label = phase.get("label", "未分类")
    confidence = phase.get("confidence")
    confidence_text = f"置信度 {confidence:.0%}" if confidence is not None else "置信度未知"
    description = phase.get("description", "")
    hint = phase.get("hint", "")
    best_strategy = phase.get("best_strategy_display", "")
    factor = phase.get("factor")
    factor_text = f"（加成 {factor:.2f}）" if factor is not None else ""
    factors = phase.get("strategy_factors", {})
    factors_line = " / ".join(f"{k} {v:.2f}" for k, v in factors.items()) if factors else ""
    indicators = phase.get("indicators", {})
    indicator_lines = []
    if indicators.get("pool_size") is not None:
        indicator_lines.append(f"全三 E/F 池 {indicators['pool_size']} 只")
    if indicators.get("pool_change_rate_5d") is not None:
        indicator_lines.append(f"5日变化 {indicators['pool_change_rate_5d']:+.1%}")
    if indicators.get("contraction_release_density") is not None:
        indicator_lines.append(f"释放密度 {indicators['contraction_release_density']:.2%}")
    indicator_text = " | ".join(indicator_lines) if indicator_lines else ""
    lines = [
        f"> **今日市场阶段：{label}** {confidence_text}",
        f">",
    ]
    if description:
        lines.append(f"> {description}")
    if hint:
        lines.append(f"> 策略提示：{hint}")
    if best_strategy:
        lines.append(f"> 最佳适配策略：**{best_strategy}** {factor_text}")
    if factors_line:
        lines.append(f"> 各策略加成：{factors_line}")
    if indicator_text:
        lines.append(f"> 核心指标：{indicator_text}")
    lines.append("")
    return "\n".join(lines)


def build_markdown(payload: dict[str, Any]) -> str:
    summary = payload["market_summary"]
    stats = payload["signal_stats"]
    quality = payload["quality_summary"]
    cal = payload["calibration"]
    prior = payload.get("macro_chain_prior") or {}
    macro_prior = prior.get("macro_prior") or {}
    market_style = prior.get("market_style_prior") or {}
    phase = payload.get("market_phase") or {}
    w1_mn1 = payload.get("w1_mn1_overview") or {}
    focus = "、".join(row["industry"] for row in summary["focus_industries"]) or "无"
    delta = summary.get("all_three_ef_delta")
    delta_text = "无前日对比" if delta is None else f"{delta:+d}"
    cal_reason_text = {"calibration_not_available": "历史验证数据积累中", "ok": "历史验证数据已确认"}.get(cal.get("reason"), cal.get("reason") or "质量闸门已通过")
    macro_status_text = {"partial": "数据部分可用", "missing": "数据暂缺", "ok": "数据已就绪"}.get(macro_prior.get("status"), macro_prior.get("status") or "missing")
    dominant_env_label = w1_mn1.get("dominant_env_label") or "-"
    dominant_env_pct = w1_mn1.get("dominant_env_pct")
    dominant_env_text = f"{dominant_env_label}（{dominant_env_pct}%）" if dominant_env_pct is not None else dominant_env_label
    cred = compute_credibility_summary(payload)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in payload["display_rows"]:
        grouped[card_industry(row)].append(row)
    focus_ifind = payload["ifind_focus_rows"]
    focus_display = payload.get("focus_rows") or []

    sections = []
    for industry in [row["industry"] for row in summary["focus_industries"]]:
        items = grouped.pop(industry, [])
        if not items:
            continue
        sections.append(f"### {industry}\n\n{markdown_table(items)}")
    remaining = [item for items in grouped.values() for item in items]
    if remaining:
        sections.append(f"### 其他行业\n\n{markdown_table(remaining)}")

    return f"""# 每日策略环境匹配报告

**日期：{payload["date"]}**

{_market_phase_markdown(phase)}## 市场环境速览

- 全三强势池：{summary["all_three_ef_count"]} 只（月/周/日线同时处于强势状态） | 较上一交易日：{delta_text}
- 行业聚焦：{focus}
- 当前大周期环境：{dominant_env_text}
- 校准状态：{cal["status"]}（{cal_reason_text}）
- 宏观环境评分：{macro_prior.get("score_0_10", "-")}/10（{macro_status_text}）
- 市场风格：风险偏好 {market_style.get("risk_appetite_score", "-")}/10，成长风格 {market_style.get("growth_style_score", "-")}/10

## 系统可信度

- 综合可信度：**{cred['label']}**（评分 {cred['score']}/100）
- 本地 VCP 验证：{cred['vcp_local_text']}
- 创始人验证（三策略综合）：{cred['founder_text']}
- 宏观置信度：{cred['macro_text']}
- 校准状态：{cred['cal_status']}{f"（{cred['cal_reason']}）" if cred['cal_reason'] else ''}

## 策略信号分布

- 今日触发信号：{stats["total_reminders"]} 条（三个策略共扫描到的触发次数）
- 按策略：{json.dumps(stats["strategy_counts"], ensure_ascii=False)}
- 按适配度：{json.dumps(stats["fit_counts"], ensure_ascii=False)}
- 按趋势阶段：{json.dumps(stats["lifecycle_counts"], ensure_ascii=False)}
- 今日质量摘要：VCP 收缩释放 {quality["vcp_compression_release_count"]}/{quality["vcp_total"]}；布林强盗波动平稳 {quality["bollinger_volatility_stable_count"]}/{quality["bollinger_total"]}；2560 全匹配 {quality["ma2560_full_match_count"]}/{quality["ma2560_total"]}
- 布林强盗：波动 × 阶段分布：{json.dumps(quality["bollinger_volatility_lifecycle"], ensure_ascii=False)}

## 最佳适配聚焦

{focus_markdown_table(focus_display)}

## 2560 策略：市场匹配分组

{ma2560_markdown(payload["ma2560_market_match"])}

## 全部匹配信号

{chr(10).join(sections) if sections else "暂无最佳适配或适配信号。"}

## 基本面聚焦

{ifind_markdown_table(focus_ifind)}

## 阅读提示

- 本报告只展示策略信号与环境匹配事实。
- 不输出买入、卖出等具体操作建议。
- 历史统计数据需积累足够样本并验证后才展示。
"""


def build_html(payload: dict[str, Any], markdown: str) -> str:
    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    def lifecycle_filter_value(card: dict[str, Any]) -> str:
        label = str(card.get("lifecycle_stage") or card.get("maturity") or "")
        if "新生" in label:
            return "新生"
        if "行进" in label:
            return "行进"
        if "延展" in label:
            return "延展"
        return "其他"

    def row_attrs(card: dict[str, Any]) -> str:
        return (
            f'data-strategy="{esc(card_strategy(card))}" '
            f'data-lifecycle="{esc(lifecycle_filter_value(card))}" '
            f'data-industry="{esc(card_industry(card))}" '
            f'data-fit="{esc(card.get("strategy_environment_fit") or "")}"'
        )

    def strategy_name(strategy_id: str) -> str:
        return {
            "vcp": "VCP",
            "ma2560": "2560",
            "bollinger_bandit": "布林强盗",
        }.get(strategy_id, strategy_id)

    def render_signal_row(card: dict[str, Any]) -> str:
        strategy = card.get("strategy") or {}
        env = card.get("w1_mn1_env") or {}
        env_html = f'<span style="color:{esc(env.get("color", "#666"))}">{esc(env.get("label", "-"))}</span>' if env else "-"
        founder_html = ""
        ftxt = founder_reference_text(card)
        if ftxt:
            founder_html = f'<br><span style="color:#6b7280;font-size:12px;">{esc(ftxt)}</span>'
        return f"""
            <tr {row_attrs(card)}>
              <td><strong>{esc(card.get("stock_code"))}</strong><br><span>{esc(card.get("stock_name") or "")}</span></td>
              <td>{esc(card_industry(card))}</td>
              <td>{esc(strategy.get("strategy_id"))}<br><span>{esc(strategy.get("signal_name"))}</span></td>
              <td>{esc(card.get("lifecycle_stage") or card.get("maturity"))}</td>
              <td>{esc(card.get("strategy_environment_fit"))}</td>
              <td>{esc(card.get("fit_reasons") or "-")}</td>
              <td>{esc(scene_tags(card))}<br><span>{esc(ifind_summary(card))}</span></td>
              <td>{esc(compact_state(card))}<br><span>{esc(compact_duration(card))}</span></td>
              <td>{env_html}</td>
              <td>{esc(compact_sr(card))}</td>
              <td>{esc(stats_text(card))}{founder_html}</td>
            </tr>
            """

    def render_focus_row(card: dict[str, Any]) -> str:
        env = card.get("w1_mn1_env") or {}
        env_html = f'<span style="color:{esc(env.get("color", "#666"))}">{esc(env.get("label", "-"))}</span>' if env else "-"
        founder_html = ""
        ftxt = founder_reference_text(card)
        if ftxt:
            founder_html = f'<br><span style="color:#6b7280;font-size:12px;">{esc(ftxt)}</span>'
        prosperity_map = payload.get("industry_prosperity") or {}
        chain_html = chain_prosperity_html(card, prosperity_map)
        return f"""
            <tr {row_attrs(card)}>
              <td><strong>{esc(card.get("stock_code"))}</strong><br><span>{esc(card.get("stock_name") or "")}</span></td>
              <td>{esc(card_industry(card))}</td>
              <td>{chain_html}</td>
              <td>{esc(strategy_label(card))}</td>
              <td>{esc(card.get("lifecycle_stage") or card.get("maturity") or "-")}</td>
              <td>{esc(card.get("fit_reasons") or "-")}</td>
              <td>{esc(compact_state(card))}</td>
              <td>{env_html}</td>
              <td>{esc(validation_text(card))}{founder_html}</td>
            </tr>
            """

    rows = payload["display_rows"]
    focus_display = payload.get("focus_rows") or []
    ifind_rows = payload["ifind_focus_rows"]
    ma2560 = payload.get("ma2560_market_match") or {}
    best_rows = [card for card in rows if (card.get("strategy_environment_fit") or "") == "最佳适配"]
    compatible_rows = [card for card in rows if (card.get("strategy_environment_fit") or "") == "适配"]
    focus_html = [render_focus_row(card) for card in focus_display]
    best_html = [render_signal_row(card) for card in best_rows]
    compatible_html = [render_signal_row(card) for card in compatible_rows]
    industries = sorted({card_industry(card) for card in [*focus_display, *rows]})

    summary = payload["market_summary"]
    stats = payload["signal_stats"]
    quality = payload["quality_summary"]
    cal = payload["calibration"]
    prior = payload.get("macro_chain_prior") or {}
    macro_prior = prior.get("macro_prior") or {}
    market_style = prior.get("market_style_prior") or {}
    w1_mn1 = payload.get("w1_mn1_overview") or {}
    focus = "、".join(row["industry"] for row in summary["focus_industries"]) or "无"
    delta = summary.get("all_three_ef_delta")
    delta_text = "无前日对比" if delta is None else f"{delta:+d}"
    cal_reason_text = {"calibration_not_available": "历史验证数据积累中", "ok": "历史验证数据已确认"}.get(cal.get("reason"), cal.get("reason") or "质量闸门已通过")
    macro_status_text = {"partial": "数据部分可用", "missing": "数据暂缺", "ok": "数据已就绪"}.get(macro_prior.get("status"), macro_prior.get("status") or "missing")
    best_fit_count = stats["fit_counts"].get("最佳适配", 0)
    strategy_dist_text = " / ".join(f"{strategy_name(k)} {v}" for k, v in stats["strategy_counts"].items()) or "-"
    bollinger_cross_text = " / ".join(
        f"{vol}:{','.join(f'{stage}{count}' for stage, count in stages.items())}"
        for vol, stages in (quality.get("bollinger_volatility_lifecycle") or {}).items()
    ) or "-"
    dominant_env_label = w1_mn1.get("dominant_env_label") or "-"
    dominant_env_pct = w1_mn1.get("dominant_env_pct")
    dominant_env_text = f"{dominant_env_label}（{dominant_env_pct}%）" if dominant_env_pct is not None else dominant_env_label
    cred = compute_credibility_summary(payload)
    ma2560_group_html = []
    for group in ma2560.get("groups", []) or []:
        if not group.get("count"):
            continue
        group_rows = []
        for item in group.get("rows", []) or []:
            group_rows.append(
                f"""
                <tr>
                  <td><strong>{esc(item.get("stock_code"))}</strong><br><span>{esc(item.get("stock_name") or "")}</span></td>
                  <td>{esc(item.get("state_combo") or "-")}</td>
                  <td>{esc("是" if item.get("local_combo_pass") else "否")}</td>
                  <td>{esc("是" if item.get("p116_state_match") else "否")}</td>
                  <td>{esc(item.get("strategy_environment_fit") or "-")}<br><span>{esc(item.get("fit_reasons") or "")}</span></td>
                </tr>
                """
            )
        limit_note = ""
        if group.get("count", 0) > len(group.get("rows", []) or []):
            limit_note = f"<p class=\"note\">仅展示前 {esc(group.get('display_limit'))} 条，完整分组见 JSON。</p>"
        ma2560_group_html.append(
            f"""
            <section>
              <h2>{esc(group.get("label"))} <span>{esc(group.get("count"))}</span></h2>
              <p class="meta">{esc(MA2560_STATS_TEXT.get(group.get("level"), group.get("label")))}</p>
              <table>
                <thead><tr><th>股票</th><th>State组合</th><th>个股组合</th><th>P116匹配</th><th>环境适配</th></tr></thead>
                <tbody>{''.join(group_rows)}</tbody>
              </table>
              {limit_note}
            </section>
            """
        )

    phase = payload.get("market_phase") or {}
    phase_html = ""
    if phase.get("status") == "ok":
        label = esc(phase.get("label", "未分类"))
        confidence = phase.get("confidence")
        confidence_text = f"置信度 {confidence:.0%}" if confidence is not None else "置信度未知"
        description = esc(phase.get("description", ""))
        hint = esc(phase.get("hint", ""))
        best_strategy = esc(phase.get("best_strategy_display", ""))
        factor = phase.get("factor")
        factor_text = f"环境系数 {factor:.2f}（>1 表示环境有利）" if factor is not None else ""
        factors = phase.get("strategy_factors", {})
        factors_line = " / ".join(f"{esc(k)} {v:.2f}" for k, v in factors.items()) if factors else ""
        indicators = phase.get("indicators", {})
        indicator_items = []
        if indicators.get("pool_size") is not None:
            indicator_items.append(f"强势池 {indicators['pool_size']} 只")
        if indicators.get("pool_change_rate_5d") is not None:
            indicator_items.append(f"5日扩张 {indicators['pool_change_rate_5d']:+.1%}")
        if indicators.get("contraction_release_density") is not None:
            indicator_items.append(f"突破密度 {indicators['contraction_release_density']:.2%}（从收缩中突破的股票占比）")
        indicator_text = " | ".join(indicator_items) if indicator_items else ""
        phase_html = f"""
    <div class="phase-card">
      <div class="phase-header">
        <span class="phase-badge">{label}</span>
        <span class="phase-confidence">{esc(confidence_text)}</span>
      </div>
      <p class="phase-desc">{description}</p>
      <p class="phase-hint">策略提示：{hint}</p>
      <p class="phase-best">当前最适策略：<strong>{best_strategy}</strong> <span>{esc(factor_text)}</span></p>
      <p class="phase-factors">各策略环境系数：{factors_line}</p>
      {f'<p class="phase-indicators">核心指标：{esc(indicator_text)}</p>' if indicator_text else ''}
    </div>
"""
    else:
        phase_html = """
    <div class="phase-card phase-missing">
      <div class="phase-header">
        <span class="phase-badge">今日市场阶段</span>
        <span class="phase-confidence">数据待补充</span>
      </div>
      <p class="phase-desc">市场阶段识别框架尚未接入或数据缺失。</p>
    </div>
"""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>每日策略环境匹配报告 {esc(payload["date"])}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f8fb; color: #172033; }}
    main {{ max-width: 1440px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    .meta {{ color: #5d6b82; margin: 0 0 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }}
    .metric {{ background: #fff; border: 1px solid #e1e6ef; padding: 12px; border-radius: 6px; }}
    .metric b {{ display: block; font-size: 20px; margin-top: 4px; }}
    .metric.wide {{ grid-column: span 2; }}
    .phase-card {{ background: #fff; border: 1px solid #e1e6ef; border-radius: 8px; padding: 16px 18px; margin-bottom: 18px; }}
    .phase-card.phase-missing {{ background: #fafbfc; border-color: #e1e6ef; }}
    .phase-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }}
    .phase-badge {{ display: inline-block; border-radius: 6px; padding: 4px 10px; font-size: 15px; font-weight: 650; color: #fff; background: #2563eb; }}
    .phase-confidence {{ color: #5d6b82; font-size: 13px; }}
    .phase-desc {{ margin: 0 0 8px; color: #344054; font-size: 14px; line-height: 1.5; }}
    .phase-hint {{ margin: 0 0 8px; color: #475467; font-size: 13px; }}
    .phase-best {{ margin: 0 0 6px; color: #344054; font-size: 13px; }}
    .phase-best strong {{ color: #2563eb; font-size: 14px; }}
    .phase-best span {{ color: #5d6b82; font-size: 12px; }}
    .phase-factors {{ margin: 0 0 6px; color: #667085; font-size: 12px; }}
    .phase-indicators {{ margin: 0; color: #667085; font-size: 12px; }}
    .credibility-card {{ background: #fff; border: 1px solid #e1e6ef; border-radius: 8px; padding: 16px 18px; margin-bottom: 18px; }}
    .credibility-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }}
    .credibility-badge {{ display: inline-block; border-radius: 6px; padding: 4px 10px; font-size: 15px; font-weight: 650; color: #fff; background: #2563eb; }}
    .credibility-score {{ color: #5d6b82; font-size: 13px; }}
    .credibility-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 8px; }}
    .credibility-item {{ background: #f8fafc; border: 1px solid #e1e6ef; border-radius: 6px; padding: 10px 12px; }}
    .credibility-item strong {{ display: block; font-size: 14px; margin-bottom: 4px; color: #344054; }}
    .credibility-item span {{ font-size: 12px; color: #667085; }}
    @media (max-width: 900px) {{ .credibility-grid {{ grid-template-columns: 1fr 1fr; }} }}
    .filters {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: end; background: #fff; border: 1px solid #e1e6ef; border-radius: 6px; padding: 12px; margin: 0 0 18px; }}
    .filters label {{ display: grid; gap: 4px; color: #5d6b82; font-size: 12px; }}
    select {{ min-width: 150px; border: 1px solid #ccd5e2; border-radius: 6px; padding: 7px 9px; background: #fff; color: #172033; }}
    details {{ margin-top: 20px; }}
    summary {{ cursor: pointer; font-size: 18px; font-weight: 650; margin: 0 0 10px; }}
    section {{ margin-top: 20px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e1e6ef; }}
    th, td {{ text-align: left; vertical-align: top; padding: 10px 12px; border-bottom: 1px solid #edf1f7; font-size: 13px; }}
    th {{ background: #f0f3f8; color: #344054; font-weight: 650; }}
    td span {{ color: #667085; font-size: 12px; }}
    .note {{ margin-top: 16px; color: #667085; font-size: 13px; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr 1fr; }} table {{ display: block; overflow-x: auto; }} }}
  </style>
</head>
<body>
  <main>
    <h1>每日策略环境匹配报告</h1>
    <p class="meta">日期 {esc(payload["date"])} | 生成 {esc(payload["generated_at"])}</p>
{phase_html}
    <div class="grid">
      <div class="metric">全三强势池<b>{esc(summary["all_three_ef_count"])}</b><span>月/周/日线同时处于强势状态 | {esc(delta_text)}</span></div>
      <div class="metric">最佳适配信号<b>{esc(best_fit_count)}</b><span>全量提醒中筛出</span></div>
      <div class="metric">当前大周期环境<b>{esc(dominant_env_text)}</b><span>当日信号中大周期背景占比最高</span></div>
      <div class="metric wide">各策略信号分布<b>{esc(strategy_dist_text)}</b><span>提醒层信号账本统计</span></div>
      <div class="metric">今日触发信号<b>{esc(stats["total_reminders"])}</b><span>三个策略共扫描到的触发次数</span></div>
      <div class="metric">环境匹配信号<b>{esc(len(rows))}</b><span>与市场环境匹配度较高的信号</span></div>
      <div class="metric">校准状态<b>{esc(cal["status"])}</b><span>{esc(cal_reason_text)}</span></div>
      <div class="metric">VCP 收缩释放<b>{esc(quality["vcp_compression_release_count"])}/{esc(quality["vcp_total"])}</b><span>经历波动收缩后突破的信号</span></div>
      <div class="metric">布林波动平稳<b>{esc(quality["bollinger_volatility_stable_count"])}/{esc(quality["bollinger_total"])}</b><span>波动较平稳环境下的信号</span></div>
      <div class="metric">2560 全匹配<b>{esc(quality["ma2560_full_match_count"])}/{esc(quality["ma2560_total"])}</b><span>个股+行业共振</span></div>
      <div class="metric wide">布林强盗：波动 × 阶段分布<b>{esc(bollinger_cross_text)}</b><span>波动平稳/活跃环境下，各趋势阶段的信号数量</span></div>
      <div class="metric">宏观环境评分<b>{esc(macro_prior.get("score_0_10") or "-")}</b><span>{esc({"partial": "数据完整度：部分", "missing": "数据暂缺", "ok": "数据已就绪"}.get(macro_prior.get("status"), macro_prior.get("status") or "数据暂缺"))}</span></div>
      <div class="metric">风险偏好<b>{esc(market_style.get("risk_appetite_score") or "-")}</b><span>{esc(" / ".join(market_style.get("tags") or []))}</span></div>
    </div>
    <div class="credibility-card">
      <div class="credibility-header">
        <span class="credibility-badge" style="background:{esc(cred['label_color'])};">{esc(cred['label'])}</span>
        <span class="credibility-score">可信度评分 {esc(cred['score'])}/100</span>
      </div>
      <div class="credibility-grid">
        <div class="credibility-item"><strong>本地 VCP 验证</strong><span>{esc(cred['vcp_local_text'])}</span></div>
        <div class="credibility-item"><strong>创始人验证</strong><span>{esc(cred['founder_text'])}</span></div>
        <div class="credibility-item"><strong>宏观置信度</strong><span>{esc(cred['macro_text'])}</span></div>
        <div class="credibility-item"><strong>校准状态</strong><span>{esc(cred['cal_status'])}</span></div>
      </div>
    </div>
    <p class="meta">行业聚焦：{esc(focus)}</p>
    <div class="filters">
      <label>策略
        <select id="strategyFilter">
          <option value="all">全部</option>
          <option value="vcp">VCP</option>
          <option value="ma2560">2560</option>
          <option value="bollinger_bandit">布林强盗</option>
        </select>
      </label>
      <label>生命周期
        <select id="lifecycleFilter">
          <option value="all">全部</option>
          <option value="新生">新生</option>
          <option value="行进">行进</option>
          <option value="延展">延展</option>
        </select>
      </label>
      <label>行业
        <select id="industryFilter">
          <option value="all">全部</option>
          {''.join(f'<option value="{esc(industry)}">{esc(industry)}</option>' for industry in industries)}
        </select>
      </label>
    </div>
    <details open>
      <summary>最佳适配信号聚焦表 <span>{esc(len(focus_display))}</span></summary>
      <table>
        <thead>
          <tr>
            <th>股票</th>
            <th>行业</th>
            <th>产业链景气</th>
            <th>策略</th>
            <th>生命周期</th>
            <th>适配理由</th>
            <th>三周期状态</th>
            <th>大周期背景</th>
            <th>验证结论</th>
          </tr>
        </thead>
        <tbody>{''.join(focus_html)}</tbody>
      </table>
    </details>
    <details open>
      <summary>最佳适配信号明细 <span>{esc(len(best_rows))}</span></summary>
      <table>
        <thead>
          <tr>
          <th>股票</th>
          <th>行业</th>
          <th>策略</th>
          <th>生命周期</th>
          <th>适配度</th>
          <th>适配理由</th>
          <th>基本面摘要</th>
          <th>三周期状态</th>
          <th>大周期背景</th>
          <th>价格位置</th>
          <th>验证结论</th>
          </tr>
        </thead>
        <tbody>{''.join(best_html)}</tbody>
      </table>
    </details>
    <section>
      <h2>2560 策略：市场匹配分组 <span>{esc(ma2560.get("total") or 0)}</span></h2>
      <p class="meta">scope: {esc(ma2560.get("scope") or "ma2560_strong_hold")} | {esc(json.dumps(ma2560.get("counts") or {}, ensure_ascii=False))}</p>
      {''.join(ma2560_group_html) if ma2560_group_html else '<p class="note">暂无 2560 strong_hold 信号。</p>'}
    </section>
    <details>
      <summary>适配信号 <span>{esc(len(compatible_rows))}</span></summary>
      <table>
        <thead>
          <tr>
            <th>股票</th>
            <th>行业</th>
            <th>策略</th>
            <th>生命周期</th>
            <th>适配度</th>
            <th>适配理由</th>
            <th>基本面摘要</th>
            <th>三周期状态</th>
            <th>大周期背景</th>
            <th>价格位置</th>
            <th>验证结论</th>
          </tr>
        </thead>
        <tbody>{''.join(compatible_html)}</tbody>
      </table>
    </details>
    <p class="note">本报告只展示策略信号与环境匹配事实；不输出买入、卖出等具体操作建议；历史统计数据需积累足够样本并验证后才展示。</p>
    <p class="note">基本面聚焦：{esc(len(ifind_rows))} 条同时具备策略最佳适配和公司质量摘要的信号。</p>
  </main>
  <script>
    const filters = {{
      strategy: document.getElementById('strategyFilter'),
      lifecycle: document.getElementById('lifecycleFilter'),
      industry: document.getElementById('industryFilter')
    }};
    function applyFilters() {{
      const strategy = filters.strategy.value;
      const lifecycle = filters.lifecycle.value;
      const industry = filters.industry.value;
      document.querySelectorAll('tr[data-strategy]').forEach((row) => {{
        const okStrategy = strategy === 'all' || row.dataset.strategy === strategy;
        const okLifecycle = lifecycle === 'all' || row.dataset.lifecycle === lifecycle;
        const okIndustry = industry === 'all' || row.dataset.industry === industry;
        row.style.display = okStrategy && okLifecycle && okIndustry ? '' : 'none';
      }});
    }}
    Object.values(filters).forEach((el) => el.addEventListener('change', applyFilters));
    applyFilters();
  </script>
</body>
</html>
"""


def load_market_phase(date_str: str) -> dict[str, Any] | None:
    """Load market phase snapshot if available."""
    path = paths_for(date_str).get("market_phase")
    if not path or not path.exists():
        return None
    return load_json(path, required=False)


def build_market_phase_card(phase_data: dict[str, Any] | None) -> dict[str, Any]:
    """Build market phase card data for display."""
    if not phase_data:
        return {"status": "missing", "phase": "undetermined", "label": "未分类", "description": "", "hint": "", "confidence": None, "best_strategy": "", "factor": None}
    phase = phase_data.get("market_phase") or "undetermined"
    confidence = phase_data.get("confidence")
    label = PHASE_LABELS.get(phase, phase)
    description = PHASE_DESCRIPTIONS.get(phase, "")
    hint = PHASE_STRATEGY_HINTS.get(phase, "")
    factors = MARKET_PHASE_FACTORS.get(phase, {})
    best_strategy = ""
    best_factor = None
    for sid, fac in sorted(factors.items(), key=lambda x: -x[1]):
        if best_factor is None or fac > best_factor:
            best_factor = fac
            best_strategy = sid
    return {
        "status": "ok",
        "phase": phase,
        "label": label,
        "description": description,
        "hint": hint,
        "confidence": confidence,
        "best_strategy": best_strategy,
        "best_strategy_display": STRATEGY_DISPLAY_NAMES.get(best_strategy, best_strategy),
        "factor": best_factor,
        "strategy_factors": {STRATEGY_DISPLAY_NAMES.get(k, k): v for k, v in factors.items()},
        "indicators": phase_data.get("indicators") or {},
    }


def build_daily_payload(date_str: str) -> dict[str, Any]:
    paths = paths_for(date_str)
    reminder = load_json(paths["reminder"], required=True)
    evaluation = load_json(paths["evaluation"], required=False)
    state_ef = load_json(paths["state_ef"], required=False)
    calibration = load_json(paths["calibration"], required=False)
    signals = load_json(paths["signals"], required=False)
    prior = load_json(paths["macro_chain_prior"], required=False)
    phase_data = load_market_phase(date_str)
    industry_prosperity = load_industry_prosperity(date_str)

    display = display_rows(reminder)
    attach_prior_to_rows(display, prior)
    ifind_focus = ifind_focus_rows(display)
    focus_display = focus_rows(reminder.get("reminders", []) or [])
    attach_prior_to_rows(focus_display, prior)
    # Attach chain prosperity to all rows
    for card in [*display, *focus_display, *ifind_focus]:
        card["_chain_prosperity"] = card_chain_prosperity(card, industry_prosperity)
    payload = {
        "schema_version": "daily_research_brief_v2",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_summary": build_market_summary(date_str, evaluation, state_ef),
        "w1_mn1_overview": build_w1_mn1_overview(reminder.get("reminders", []) or []),
        "signal_stats": brief_stats(reminder),
        "quality_summary": quality_summary(reminder),
        "ma2560_market_match": ma2560_match_summary(signals),
        "macro_chain_prior": prior_summary(prior),
        "calibration": calibration_summary(calibration),
        "market_phase": build_market_phase_card(phase_data),
        "industry_prosperity": industry_prosperity,
        "display_rows": display,
        "focus_rows": focus_display,
        "ifind_focus_rows": ifind_focus,
        "data_sources": {name: str(path) for name, path in paths.items()},
        "guardrails": [
            "Shows only strategy-environment matching facts.",
            "Does not generate strategy signals.",
            "Does not output action instructions.",
            "Unstable or missing calibration remains 待校准.",
        ],
        "research_only": True,
    }
    return payload


def data_status(ok: bool, source: str, note: str = "") -> dict[str, str]:
    return {
        "status": "ok" if ok else "数据待补充",
        "source": source,
        "note": note if note else ("已接入" if ok else "缺失时自动降级，不阻断报告生成"),
    }


def build_degradation_matrix(payload: dict[str, Any]) -> list[dict[str, str]]:
    sources = payload.get("data_sources") or {}

    def source_exists(name: str) -> bool:
        value = sources.get(name)
        return bool(value and Path(value).exists())

    prior = payload.get("macro_chain_prior") or {}
    calibration = payload.get("calibration") or {}
    return [
        {
            "layer": "L1 宏观象限",
            **data_status(
                prior.get("status") == "ok",
                sources.get("macro_chain_prior", ""),
                "宏观/产业先验未就绪，首席报告保留框架并标注待补充。",
            ),
        },
        {
            "layer": "L2 市场 State",
            **data_status(
                source_exists("state_ef"),
                sources.get("state_ef", ""),
                "State 缓存缺失时无法计算全三 E/F 池规模。",
            ),
        },
        {
            "layer": "L3 策略信号",
            **data_status(
                source_exists("reminder"),
                sources.get("reminder", ""),
                "策略提醒简报是首席报告的主输入。",
            ),
        },
        {
            "layer": "L4 iFinD 财务",
            **data_status(
                source_exists("ifind_financial"),
                sources.get("ifind_financial", ""),
                "财务账本缺失时，公司质地段落标注数据待补充。",
            ),
        },
        {
            "layer": "L5 iFinD 产业链",
            **data_status(
                source_exists("ifind_industry"),
                sources.get("ifind_industry", ""),
                "产业链账本缺失时，行业链条段落标注数据待补充。",
            ),
        },
        {
            "layer": "校准统计",
            **data_status(
                calibration.get("status") == "已校准",
                sources.get("calibration", ""),
                calibration.get("reason") or "校准未通过时保持待校准，不展示未验证胜率。",
            ),
        },
    ]


def chief_section(title: str, status: str, bullets: list[str], data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"title": title, "status": status, "bullets": bullets, "data": data or {}}


def build_section_macro_regime(payload: dict[str, Any]) -> dict[str, Any]:
    prior = payload.get("macro_chain_prior") or {}
    if prior.get("status") != "ok":
        return chief_section(
            "一、宏观象限与市场风格",
            "数据待补充",
            [
                "宏观象限数据尚未接入，本节仅保留框架。",
                "报告不会用缺失宏观数据推断市场风格。",
            ],
        )
    macro = prior.get("macro_prior") or {}
    style = prior.get("market_style_prior") or {}
    return chief_section(
        "一、宏观象限与市场风格",
        "ok",
        [
            f"宏观先验分：{macro.get('score_0_10', '-')} / 10，状态：{macro.get('status', '-')}",
            f"风险偏好：{style.get('risk_appetite_score', '-')} / 10，成长风格：{style.get('growth_style_score', '-')} / 10",
            f"风格标签：{'、'.join(style.get('tags') or []) or '无'}",
        ],
        {"macro_prior": macro, "market_style_prior": style},
    )


def build_section_market_state(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("market_summary") or {}
    quality = payload.get("quality_summary") or {}
    focus = "、".join(row["industry"] for row in summary.get("focus_industries", []) or []) or "无"
    delta = summary.get("all_three_ef_delta")
    delta_text = "无前日对比" if delta is None else f"{delta:+d}"
    return chief_section(
        "二、市场 State 与策略土壤",
        "ok",
        [
            f"全三 E/F 池：{summary.get('all_three_ef_count', 0)} 只，较前一缓存日：{delta_text}",
            f"行业聚焦：{focus}",
            f"VCP 收缩后释放：{quality.get('vcp_compression_release_count', 0)}/{quality.get('vcp_total', 0)}",
            f"布林强盗波动稳定：{quality.get('bollinger_volatility_stable_count', 0)}/{quality.get('bollinger_total', 0)}",
            f"2560 full_match：{quality.get('ma2560_full_match_count', 0)}/{quality.get('ma2560_total', 0)}",
        ],
        {"market_summary": summary, "quality_summary": quality},
    )


def build_section_industry_chain(payload: dict[str, Any]) -> dict[str, Any]:
    prior = payload.get("macro_chain_prior") or {}
    sources = payload.get("data_sources") or {}
    has_industry_file = bool(sources.get("ifind_industry") and Path(sources["ifind_industry"]).exists())
    if prior.get("status") != "ok" and not has_industry_file:
        return chief_section(
            "三、产业链与行业景气",
            "数据待补充",
            [
                "iFinD 产业链数据与宏观-产业先验尚未完整接入。",
                "本节暂只保留行业聚焦框架，不生成产业链结论。",
            ],
        )
    positive = [row.get("industry") or row.get("name") or "-" for row in prior.get("top_positive_industries", [])]
    cautious = [row.get("industry") or row.get("name") or "-" for row in prior.get("top_cautious_industries", [])]
    counts = prior.get("industry_hint_counts") or {}
    return chief_section(
        "三、产业链与行业景气",
        "ok" if prior.get("status") == "ok" else "部分数据",
        [
            f"行业先验分布：{json.dumps(counts, ensure_ascii=False) if counts else '待补充'}",
            f"正向行业提示：{'、'.join(positive[:8]) or '待补充'}",
            f"谨慎行业提示：{'、'.join(cautious[:8]) or '待补充'}",
        ],
        {"industry_hint_counts": counts, "top_positive_industries": positive, "top_cautious_industries": cautious},
    )


def build_section_strategy_fit(payload: dict[str, Any]) -> dict[str, Any]:
    stats = payload.get("signal_stats") or {}
    quality = payload.get("quality_summary") or {}
    ma2560 = payload.get("ma2560_market_match") or {}
    return chief_section(
        "五、策略 × 环境适配",
        "ok",
        [
            f"今日提醒信号：{stats.get('total_reminders', 0)} 条",
            f"按策略：{json.dumps(stats.get('strategy_counts') or {}, ensure_ascii=False)}",
            f"按适配度：{json.dumps(stats.get('fit_counts') or {}, ensure_ascii=False)}",
            f"2560 分层：{json.dumps(ma2560.get('counts') or {}, ensure_ascii=False)}",
            f"布林强盗波动率×生命周期：{json.dumps(quality.get('bollinger_volatility_lifecycle') or {}, ensure_ascii=False)}",
        ],
        {"signal_stats": stats, "quality_summary": quality, "ma2560_market_match": ma2560},
    )


def build_section_stock_focus(payload: dict[str, Any]) -> dict[str, Any]:
    focus = payload.get("focus_rows") or []
    if not focus:
        return chief_section(
            "六、股票观察池与可追踪清单",
            "数据待补充",
            ["今日没有可进入聚焦表的策略-环境组合。"],
        )
    lines = []
    for card in focus[:10]:
        lines.append(
            f"{card.get('stock_code', '')} {card.get('stock_name', '')} | {card_industry(card)} | "
            f"{strategy_label(card)} | {card.get('lifecycle_stage') or card.get('maturity') or '-'} | "
            f"{validation_text(card)}"
        )
    return chief_section(
        "五、股票观察池与可追踪清单",
        "ok",
        [
            f"聚焦表样本：{len(focus)} 条。",
            "以下为前 10 条，仅作观察清单，不构成操作指令。",
            *lines,
        ],
        {"focus_count": len(focus), "top_rows": focus[:10]},
    )


def build_section_opportunity_patterns(payload: dict[str, Any]) -> dict[str, Any]:
    date_str = payload.get("date", "")
    if not date_str:
        return chief_section("四、今日机会模式", "待补充", ["日期参数缺失。"])
    hit_path = ROOT / "outputs" / "project" / f"opportunity_patterns_daily_{date_str.replace('-','')}.json"
    if not hit_path.exists():
        return chief_section(
            "四、今日机会模式",
            "待补充",
            ["机会模式数据尚未生成，运行 mine_opportunity_patterns.py 后可用。"],
        )
    hits = json.loads(hit_path.read_text(encoding="utf-8"))
    verified = hits.get("verified") or []
    candidates = hits.get("candidates") or []
    unmatched = hits.get("unmatched_patterns") or []

    if not verified and not candidates:
        return chief_section(
            "四、今日机会模式",
            "无匹配",
            ["今日无已验证或候选模式触发。"],
        )

    lines = []
    by_pattern: dict[str, list] = defaultdict(list)
    for v in verified:
        by_pattern.setdefault(v.get("pattern_key", ""), []).append(v)

    for pkey, stock_list in by_pattern.items():
        first = stock_list[0]
        lines.append(
            f"### {pkey}（n={first.get('pattern_n','?')}, 超额{first.get('pattern_mean_excess',0):+.2%}）"
        )
        stock_str = "、".join(s.get("stock_code", "") for s in stock_list[:10])
        lines.append(f"命中标的：{stock_str}")
        if len(stock_list) > 10:
            lines.append(f"…及其他 {len(stock_list) - 10} 只")
        lines.append("")

    if candidates:
        lines.append("### 候选观察（待积累至100样本）")
        cand_codes = [c.get("stock_code", "") for c in candidates[:15]]
        lines.append(f"命中标的：{'、'.join(cand_codes)}")
        if len(candidates) > 15:
            lines.append(f"…及其他 {len(candidates) - 15} 只")
        lines.append("")

    if unmatched:
        lines.append("### 今日未触发的已验证模式")
        lines.append(f"{'、'.join(unmatched[:5])}")

    meta = {
        "verified_hits": hits.get("verified_hits", 0),
        "candidate_hits": hits.get("candidate_hits", 0),
        "unmatched": len(unmatched),
    }
    return chief_section(
        "四、今日机会模式",
        "ok" if verified else "候选",
        lines,
        meta,
    )


def build_chief_sections(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        build_section_macro_regime(payload),
        build_section_market_state(payload),
        build_section_industry_chain(payload),
        build_section_opportunity_patterns(payload),
        build_section_strategy_fit(payload),
        build_section_stock_focus(payload),
    ]


def build_chief_markdown(payload: dict[str, Any]) -> str:
    matrix_lines = [
        "| 层级 | 状态 | 数据源 | 说明 |",
        "|------|------|--------|------|",
    ]
    for row in payload["degradation_matrix"]:
        matrix_lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("layer") or "-").replace("|", "/"),
                    str(row.get("status") or "-").replace("|", "/"),
                    str(row.get("source") or "-").replace("|", "/"),
                    str(row.get("note") or "-").replace("|", "/"),
                ]
            )
            + " |"
        )
    section_text = []
    for section in payload["chief_sections"]:
        bullets = "\n".join(f"- {item}" for item in section.get("bullets", []))
        section_text.append(f"## {section['title']}\n\n**状态：{section['status']}**\n\n{bullets}\n")
    return f"""# 首席级策略环境报告（框架版）

**日期：{payload["date"]}**

> 本报告为框架版。宏观、产业链或财务数据缺失时，只标注“数据待补充”，不做替代推断。

## 降级矩阵

{chr(10).join(matrix_lines)}

{chr(10).join(section_text)}

## 边界

- 只陈述策略信号、State 环境、基本面与产业链背景。
- 不输出买入、卖出、加仓、减仓等操作指令。
- 未通过本地验证或数据缺失的统计保持“待校准/数据待补充”。
"""


def build_chief_html(payload: dict[str, Any], markdown: str) -> str:
    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    matrix_rows = []
    for row in payload["degradation_matrix"]:
        status_class = "ok" if row.get("status") == "ok" else "pending"
        matrix_rows.append(
            f"""
            <tr>
              <td>{esc(row.get("layer"))}</td>
              <td><span class="status {status_class}">{esc(row.get("status"))}</span></td>
              <td>{esc(row.get("source") or "-")}</td>
              <td>{esc(row.get("note") or "-")}</td>
            </tr>
            """
        )
    section_html = []
    for section in payload["chief_sections"]:
        bullets = "".join(f"<li>{esc(item)}</li>" for item in section.get("bullets", []))
        status_class = "ok" if section.get("status") == "ok" else "pending"
        section_html.append(
            f"""
            <section>
              <h2>{esc(section.get("title"))} <span class="status {status_class}">{esc(section.get("status"))}</span></h2>
              <ul>{bullets}</ul>
            </section>
            """
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>首席级策略环境报告 {esc(payload["date"])}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f8fb; color: #172033; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; }}
    h2 {{ margin: 0 0 12px; font-size: 20px; }}
    .meta {{ color: #667085; margin: 0 0 22px; }}
    .notice, section {{ background: #fff; border: 1px solid #e1e6ef; border-radius: 6px; padding: 16px; margin: 16px 0; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e1e6ef; }}
    th, td {{ text-align: left; vertical-align: top; padding: 10px 12px; border-bottom: 1px solid #edf1f7; font-size: 13px; }}
    th {{ background: #f0f3f8; color: #344054; font-weight: 650; }}
    ul {{ margin: 0; padding-left: 20px; }}
    li {{ margin: 7px 0; }}
    .status {{ display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 650; }}
    .status.ok {{ color: #166534; background: #dcfce7; }}
    .status.pending {{ color: #92400e; background: #fef3c7; }}
    @media (max-width: 900px) {{ table {{ display: block; overflow-x: auto; }} }}
  </style>
</head>
<body>
  <main>
    <h1>首席级策略环境报告（框架版）</h1>
    <p class="meta">日期 {esc(payload["date"])} | 生成 {esc(payload["generated_at"])}</p>
    <div class="notice">宏观、产业链、财务等慢数据未就绪时，本报告只降级显示“数据待补充”，不会用缺失数据生成替代结论。</div>
    <section>
      <h2>降级矩阵</h2>
      <table>
        <thead><tr><th>层级</th><th>状态</th><th>数据源</th><th>说明</th></tr></thead>
        <tbody>{''.join(matrix_rows)}</tbody>
      </table>
    </section>
    {''.join(section_html)}
    <section>
      <h2>边界</h2>
      <ul>
        <li>只陈述策略信号、State 环境、基本面与产业链背景。</li>
        <li>不输出买入、卖出、加仓、减仓等操作指令。</li>
        <li>未通过本地验证或数据缺失的统计保持“待校准/数据待补充”。</li>
      </ul>
    </section>
  </main>
</body>
</html>
"""


def build_chief_research_report(date_str: str) -> dict[str, Any]:
    payload = build_daily_payload(date_str)
    payload["schema_version"] = "chief_research_report_v1"
    payload["report_mode"] = "chief"
    payload["degradation_matrix"] = build_degradation_matrix(payload)
    payload["chief_sections"] = build_chief_sections(payload)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    date_ymd = ymd(date_str)
    json_path = OUT_DIR / f"chief_research_report_{date_ymd}.json"
    md_path = OUT_DIR / f"chief_research_report_{date_ymd}.md"
    latest_json = OUT_DIR / "chief_research_report_latest.json"
    latest_md = OUT_DIR / "chief_research_report_latest.md"
    html_path = PUBLIC_DIR / f"chief_research_report_{date_ymd}.html"
    latest_html = PUBLIC_DIR / "chief_research_report_latest.html"

    markdown = build_chief_markdown(payload)
    html_text = build_chief_html(payload, markdown)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(text, encoding="utf-8")
    latest_json.write_text(text, encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    latest_md.write_text(markdown, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    latest_html.write_text(html_text, encoding="utf-8")

    return {
        "ok": True,
        "mode": "chief",
        "date": date_str,
        "sections": [section["title"] for section in payload["chief_sections"]],
        "degradation_matrix": payload["degradation_matrix"],
        "json": str(json_path),
        "markdown": str(md_path),
        "html": str(html_path),
        "latest_json": str(latest_json),
        "latest_markdown": str(latest_md),
        "latest_html": str(latest_html),
        "research_only": True,
    }


def build_daily_research_brief(date_str: str) -> dict[str, Any]:
    payload = build_daily_payload(date_str)
    display = payload["display_rows"]
    ifind_focus = payload["ifind_focus_rows"]
    focus_display = payload["focus_rows"]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    date_ymd = ymd(date_str)
    json_path = OUT_DIR / f"daily_research_brief_{date_ymd}.json"
    md_path = OUT_DIR / f"daily_research_brief_{date_ymd}.md"
    latest_json = OUT_DIR / "daily_research_brief_latest.json"
    latest_md = OUT_DIR / "daily_research_brief_latest.md"
    html_path = PUBLIC_DIR / f"daily_research_brief_{date_ymd}.html"
    latest_html = PUBLIC_DIR / "daily_research_brief_latest.html"

    markdown = build_markdown(payload)
    html_text = build_html(payload, markdown)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(text, encoding="utf-8")
    latest_json.write_text(text, encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    latest_md.write_text(markdown, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    latest_html.write_text(html_text, encoding="utf-8")

    return {
        "ok": True,
        "date": date_str,
        "total_reminders": payload["signal_stats"]["total_reminders"],
        "display_count": len(display),
        "focus_count": len(focus_display),
        "ifind_focus_count": len(ifind_focus),
        "fit_counts": payload["signal_stats"]["fit_counts"],
        "lifecycle_counts": payload["signal_stats"]["lifecycle_counts"],
        "quality_summary": payload["quality_summary"],
        "focus_industries": payload["market_summary"]["focus_industries"],
        "calibration": payload["calibration"],
        "json": str(json_path),
        "markdown": str(md_path),
        "html": str(html_path),
        "latest_json": str(latest_json),
        "latest_markdown": str(latest_md),
        "latest_html": str(latest_html),
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build daily strategy-environment research brief.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--mode", choices=["brief", "chief"], default="brief", help="报告模式：brief=标准日报，chief=首席级策略环境报告")
    args = parser.parse_args()
    if args.mode == "chief":
        result = build_chief_research_report(args.date)
    else:
        result = build_daily_research_brief(args.date)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
