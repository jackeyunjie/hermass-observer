"""Classic strategy sentinel: read-only signal observer.

This module is intentionally isolated from the Hermass State system:
- It only reads from outputs/strategy_signals/strategy_signal_daily_latest.json
  or the strategy_signals.duckdb produced by strategy_signal_ledger.py.
- It does not compute signals, write State Cube, or participate in Agent debate.
- It returns neutral, research-only labels on the overview API; original rule
  terminology is only exposed on the detail page behind a disclaimer.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

log = logging.getLogger("hermass.web.classic_strategy_sentinel")

ROOT = Path(__file__).resolve().parents[2]
SIGNAL_DIR = ROOT / "outputs" / "strategy_signals"
LATEST_JSON = SIGNAL_DIR / "strategy_signal_daily_latest.json"
DUCKDB_PATH = SIGNAL_DIR / "strategy_signals.duckdb"

# Phase 1 allowed strategies. ATR chandelier is explicitly excluded.
ALLOWED_STRATEGIES = frozenset({"vcp", "ma2560", "bollinger_bandit"})

# Map (strategy_id, signal_type) to a neutral homepage label.
# These labels deliberately avoid "买入/卖出/入场/止损/止盈/仓位".
OVERVIEW_LABELS: dict[tuple[str, str], str] = {
    ("vcp", "entry"): "VCP 规则信号",
    ("vcp", "exit"): "VCP 失效信号",
    ("ma2560", "entry"): "2560 规则信号",
    ("ma2560", "exit"): "2560 风险信号",
    ("ma2560", "risk"): "2560 风险信号",
    ("bollinger_bandit", "entry"): "布林规则信号",
    ("bollinger_bandit", "exit"): "布林规则风险",
    ("bollinger_bandit", "risk"): "布林规则风险",
}

# Display names used inside the sentinel pages.
STRATEGY_DISPLAY_NAMES: dict[str, str] = {
    "vcp": "VCP 收缩释放",
    "ma2560": "2560 趋势推进",
    "bollinger_bandit": "布林强盗",
}

# Canonical signal-type order for mutual-exclusion tie-breaking.
_SIGNAL_PRIORITY = {"entry": 0, "exit": 1, "risk": 2, "structure": 3}

# Minimum confidence for a signal to be surfaced by the sentinel.
MIN_CONFIDENCE = 0.0

# Disclaimer that must accompany any detail page/API exposing original rules.
RESEARCH_ONLY_DISCLAIMER = (
    "以下为经典策略原始规则触发说明，仅作研究观察，不构成交易建议。"
)


@dataclass(frozen=True)
class _SignalKey:
    stock_code: str
    strategy_id: str


def _load_latest_json(date_str: str) -> list[dict[str, Any]] | None:
    """Load rows from the latest JSON if its date matches the requested date."""
    if not LATEST_JSON.exists():
        return None
    try:
        data = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Failed to parse %s: %s", LATEST_JSON, exc)
        return None
    if not isinstance(data, dict):
        return None
    if str(data.get("date")) != date_str:
        return None
    rows = data.get("rows")
    if not isinstance(rows, list):
        return None
    return rows


def _load_duckdb_rows(date_str: str) -> list[dict[str, Any]]:
    """Load matching rows from strategy_signals.duckdb as a fallback."""
    if not DUCKDB_PATH.exists():
        return []
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        result = con.execute(
            """
            SELECT
                signal_date AS signal_date,
                stock_code,
                stock_name,
                strategy_id,
                signal_type,
                signal_name,
                signal_strength,
                params_json,
                raw_signal,
                source_module,
                research_only,
                reminder_eligible,
                display_scope,
                lifecycle_stage,
                strategy_environment_fit,
                fit_reasons,
                env_category,
                w1_mn1_label,
                env_category_factor,
                vcp_entry_confirmation,
                vcp_stop_prices,
                ma2560_entry_confirmation,
                bollinger_entry_confirmation,
                atr_chandelier_entry_confirmation,
                ma2560_local_combo_pass,
                ma2560_p116_state_match,
                ma2560_market_match_level,
                ma2560_state_combo,
                matched_pattern,
                pattern_boost,
                conviction_level
            FROM strategy_signal_daily
            WHERE signal_date = CAST(? AS DATE)
              AND strategy_id IN ('vcp', 'ma2560', 'bollinger_bandit')
            ORDER BY strategy_id, signal_type, signal_strength DESC
            """,
            [date_str],
        )
        cols = [desc[0] for desc in result.description]
        return [dict(zip(cols, row)) for row in result.fetchall()]
    except Exception as exc:
        log.warning("Failed to query %s: %s", DUCKDB_PATH, exc)
        return []
    finally:
        con.close()


def _load_rows(date_str: str) -> list[dict[str, Any]]:
    """Load rows for a given date, preferring the latest JSON."""
    rows = _load_latest_json(date_str)
    if rows is not None:
        return [
            row
            for row in rows
            if row.get("strategy_id") in ALLOWED_STRATEGIES
        ]
    return _load_duckdb_rows(date_str)


def _row_confidence(row: dict[str, Any]) -> float:
    """Return numeric confidence for a row."""
    value = row.get("signal_strength")
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _normalize_date(date_str: str) -> str:
    """Normalize YYYY-MM-DD or YYYYMMDD to YYYY-MM-DD."""
    s = date_str.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def _neutral_overview_label(strategy_id: str, signal_type: str) -> str:
    """Return the neutral homepage label for a strategy + signal_type."""
    return OVERVIEW_LABELS.get(
        (strategy_id, signal_type),
        f"{STRATEGY_DISPLAY_NAMES.get(strategy_id, strategy_id)} 规则信号",
    )


def _mutually_exclusive_signals(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """For each (stock, strategy), keep the highest-priority signal only.

    Priority: entry > exit > risk > structure. Within the same type the highest
    confidence wins.
    """
    best: dict[_SignalKey, dict[str, Any]] = {}
    for row in rows:
        key = _SignalKey(
            stock_code=str(row.get("stock_code") or ""),
            strategy_id=str(row.get("strategy_id") or ""),
        )
        if not key.stock_code or key.strategy_id not in ALLOWED_STRATEGIES:
            continue
        stype = str(row.get("signal_type") or "")
        priority = _SIGNAL_PRIORITY.get(stype, 99)
        confidence = _row_confidence(row)
        existing = best.get(key)
        if existing is None:
            best[key] = row
            continue
        existing_type = str(existing.get("signal_type") or "")
        existing_priority = _SIGNAL_PRIORITY.get(existing_type, 99)
        if priority < existing_priority:
            best[key] = row
        elif priority == existing_priority and confidence > _row_confidence(existing):
            best[key] = row
    return list(best.values())


def _evidence_for(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a research-only evidence checklist for the detail view.

    The checklist is intentionally conservative: it marks items as met based on
    the raw_signal value and avoids inventing prices or technical values.
    """
    raw = str(row.get("raw_signal") or "")
    stype = str(row.get("signal_type") or "")
    strategy = str(row.get("strategy_id") or "")
    items: list[dict[str, Any]] = []

    if strategy == "vcp":
        items = [
            {"condition": "波幅收缩：近期波动率逐步收窄", "met": "contraction" in raw},
            {"condition": "量能枯竭：收缩区间成交量递减", "met": "contraction" in raw and raw != "vcp_breakout_no_vol"},
            {"condition": "突破确认：收盘价突破收缩区间上沿", "met": "breakout" in raw},
            {"condition": "量能确认：成交量 ≥ 1.5×20日均量", "met": raw == "vcp_breakout"},
            {"condition": "基底站上 MA50", "met": raw == "vcp_breakout"},
        ]
    elif strategy == "ma2560":
        items = [
            {"condition": "均线排列：MA25 向上倾斜，MA25 > MA60", "met": "golden_cross" in raw or "strong" in raw or "aligned" in raw},
            {"condition": "价格位置：收盘价在 MA25 ±2% 区间内或上方", "met": "golden_cross" in raw or "strong" in raw},
            {"condition": "量能确认：VOL5/VOL60 ≥ 0.9 且未过热", "met": "golden_cross" in raw or "strong" in raw},
            {"condition": "回踩次数：60日内回踩 MA25 次数 < 3", "met": "golden_cross" in raw or "strong_hold" in raw},
            {"condition": "趋势强度过滤：ADX 支撑趋势方向", "met": "golden_cross" in raw and "weak_adx" not in raw},
        ]
    elif strategy == "bollinger_bandit":
        items = [
            {"condition": "突破上轨：收盘价突破布林带上轨", "met": "long_entry" in raw},
            {"condition": "动量确认：上影线 < 实体×2", "met": "long_entry" in raw},
            {"condition": "量能分级：成交量 ≥ 1.2×20日均量", "met": "long_entry" in raw},
            {"condition": "带宽状态：波动扩张初期", "met": "long_entry" in raw},
        ]

    # For exit/risk signals, keep the checklist but mark all entry-oriented
    # conditions conservatively; highlight that the signal itself is a rule
    # trigger rather than a recommendation.
    if stype in ("exit", "risk"):
        for item in items:
            item["met"] = False
        items.append({"condition": "规则触发：当前价格/结构满足该策略退出/风险条件", "met": True})

    return items


def _detail_rules(strategy_id: str) -> dict[str, list[dict[str, str]]]:
    """Return the original rule text for the detail page.

    These terms are intentionally only rendered on the detail page behind the
    research-only disclaimer.
    """
    if strategy_id == "vcp":
        return {
            "stop_rules": [
                {"rule": "硬止损", "detail": "入场价 -6%"},
                {"rule": "技术止损", "detail": "最近收缩低点 × 0.99"},
                {"rule": "ATR 止损", "detail": "入场价 - 2×ATR"},
            ],
            "exit_rules": [
                {"rule": "假突破", "detail": "3日内收盘 < 突破点，立即离场"},
                {"rule": "时间退出", "detail": "持仓 > 20 日且盈利 < 5%"},
                {"rule": "移动止损", "detail": "最高价 ≥ 入场价 +5% 后，回吐至成本价离场"},
            ],
            "position_rule_text": "单笔风险 2%，ATR 调整仓位，100股起",
            "external_validation": "Mark Minervini 72.4% 的交易选择一致",
        }
    if strategy_id == "ma2560":
        return {
            "stop_rules": [
                {"rule": "MA25 止损", "detail": "收盘价跌破 MA25，全仓离场"},
                {"rule": "MA60 清仓", "detail": "收盘价跌破 MA60，强制清仓"},
                {"rule": "MA25 走平", "detail": "MA25 不再向上，视为趋势减弱信号"},
            ],
            "exit_rules": [
                {"rule": "第一止盈", "detail": "盈利 5-10%，减仓 50%"},
                {"rule": "第二止盈", "detail": "盈利 ≥ 10%，全部清仓"},
                {"rule": "均线跟踪", "detail": "持仓期间 MA25/MA60 持续作为动态止损线"},
            ],
            "position_rule_text": "趋势确认后建仓，跌破均线逐级退出",
            "external_validation": "Darvas 79.3% 的环境选择一致",
        }
    if strategy_id == "bollinger_bandit":
        return {
            "stop_rules": [
                {"rule": "递减均线", "detail": "Day1: MA50 → Day2: MA49 → ... → Day41+: MA10"},
                {"rule": "中轨跌破", "detail": "收盘价 < 50日SMA（布林带中轨），趋势反转清仓"},
                {"rule": "波动率异常", "detail": "当前 ATR > 2×入场ATR，减仓 50%"},
            ],
            "exit_rules": [
                {"rule": "假突破", "detail": "T+1 收盘 < 信号日最低，或涨停次日低开 >3%"},
                {"rule": "上轨回落", "detail": "曾突破上轨后回落至下轨下方，减仓 50%"},
                {"rule": "时间退出", "detail": "持仓 > 10 日且盈利 < 5%"},
            ],
            "position_rule_text": "波动扩张初期建仓，按递减均线跟踪",
            "external_validation": "Bollinger 73.5% 的环境选择一致",
        }
    return {
        "stop_rules": [],
        "exit_rules": [],
        "position_rule_text": "",
        "external_validation": "",
    }


def get_overview(date_str: str) -> dict[str, Any]:
    """Return the daily overview for the classic strategy sentinel.

    Result contains one bucket per allowed strategy + signal_type that has a
    neutral homepage label. Structure signals are intentionally excluded from
    the overview to avoid noise on the home page.
    """
    date_str = _normalize_date(date_str)
    rows = _load_rows(date_str)
    if rows is None:
        rows = []

    # Filter to allowed strategies and non-structure types for the overview.
    filtered = [
        row
        for row in rows
        if row.get("strategy_id") in ALLOWED_STRATEGIES
        and row.get("signal_type") != "structure"
        and _row_confidence(row) >= MIN_CONFIDENCE
    ]

    # Apply mutual exclusion so each (stock, strategy) counts once.
    exclusive = _mutually_exclusive_signals(filtered)

    # Group by (strategy_id, signal_type).
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in exclusive:
        key = (str(row.get("strategy_id")), str(row.get("signal_type")))
        groups.setdefault(key, []).append(row)

    strategies = []
    for strategy_id in ("vcp", "ma2560", "bollinger_bandit"):
        for signal_type in ("entry", "exit", "risk"):
            group = groups.get((strategy_id, signal_type), [])
            if not group:
                continue
            label = _neutral_overview_label(strategy_id, signal_type)
            strategies.append({
                "strategy_name": strategy_id,
                "display_name": STRATEGY_DISPLAY_NAMES.get(strategy_id, strategy_id),
                "signal_type": signal_type,
                "label": label,
                "signal_count": len(group),
                "signals": [
                    {
                        "stock_code": row.get("stock_code"),
                        "stock_name": row.get("stock_name") or "",
                        "signal_name": row.get("raw_signal"),
                        "signal_display_text": row.get("signal_name") or "",
                        "confidence": round(_row_confidence(row), 4),
                    }
                    for row in sorted(
                        group,
                        key=lambda r: _row_confidence(r),
                        reverse=True,
                    )
                ],
            })

    warning = None
    if not rows:
        warning = f"未找到 {date_str} 的策略信号数据。"

    return {
        "ok": True,
        "date": date_str,
        "strategies": strategies,
        "total_stocks": len({r.get("stock_code") for r in exclusive}),
        "warning": warning,
        "disclaimer": RESEARCH_ONLY_DISCLAIMER,
    }


def get_signals(strategy: str, date_str: str, signal_type: str = "") -> dict[str, Any]:
    """Return signals for a single strategy on a given date."""
    date_str = _normalize_date(date_str)
    if strategy not in ALLOWED_STRATEGIES:
        return {
            "ok": False,
            "error": f"不支持的策略：{strategy}。当前仅支持 vcp、ma2560、bollinger_bandit。",
        }

    rows = _load_rows(date_str)
    if rows is None:
        rows = []

    filtered = [
        row
        for row in rows
        if row.get("strategy_id") == strategy
        and _row_confidence(row) >= MIN_CONFIDENCE
        and (not signal_type or row.get("signal_type") == signal_type)
    ]

    # Apply mutual exclusion per (stock, strategy) when no signal_type is given.
    if not signal_type:
        filtered = _mutually_exclusive_signals(filtered)

    filtered.sort(key=lambda r: (_SIGNAL_PRIORITY.get(str(r.get("signal_type")), 99), -_row_confidence(r)))

    signals = []
    for row in filtered:
        signals.append({
            "stock_code": row.get("stock_code"),
            "stock_name": row.get("stock_name") or "",
            "signal_name": row.get("raw_signal"),
            "signal_display_text": row.get("signal_name") or "",
            "signal_type": row.get("signal_type"),
            "confidence": round(_row_confidence(row), 4),
            "strategy_environment_fit": row.get("strategy_environment_fit") or "",
            "env_category": row.get("env_category") or "",
        })

    rules = _detail_rules(strategy)
    return {
        "ok": True,
        "date": date_str,
        "strategy": strategy,
        "display_name": STRATEGY_DISPLAY_NAMES.get(strategy, strategy),
        "signals": signals,
        "signal_count": len(signals),
        "env_match": {
            "text": rules.get("external_validation", ""),
            "source": "strategy_reminder_brief.py 环境匹配统计",
        },
        "disclaimer": RESEARCH_ONLY_DISCLAIMER,
        "warning": None if rows else f"未找到 {date_str} 的策略信号数据。",
    }


def get_detail(strategy: str, stock_code: str, date_str: str) -> dict[str, Any]:
    """Return detail for a single (strategy, stock, date) signal."""
    date_str = _normalize_date(date_str)
    stock_code = (stock_code or "").strip()
    if strategy not in ALLOWED_STRATEGIES:
        return {
            "ok": False,
            "error": f"不支持的策略：{strategy}。当前仅支持 vcp、ma2560、bollinger_bandit。",
        }
    if not stock_code:
        return {"ok": False, "error": "缺少 stock_code 参数。"}

    rows = _load_rows(date_str)
    if rows is None:
        rows = []

    matches = [
        row
        for row in rows
        if row.get("strategy_id") == strategy
        and str(row.get("stock_code") or "").strip() == stock_code
    ]

    if not matches:
        return {
            "ok": True,
            "date": date_str,
            "strategy": strategy,
            "stock_code": stock_code,
            "found": False,
            "disclaimer": RESEARCH_ONLY_DISCLAIMER,
            "warning": f"未找到 {stock_code} 在 {date_str} 的 {strategy} 信号记录。",
        }

    # Pick the highest-priority / highest-confidence match.
    matches.sort(key=lambda r: (_SIGNAL_PRIORITY.get(str(r.get("signal_type")), 99), -_row_confidence(r)))
    row = matches[0]
    rules = _detail_rules(strategy)

    return {
        "ok": True,
        "date": date_str,
        "strategy": strategy,
        "display_name": STRATEGY_DISPLAY_NAMES.get(strategy, strategy),
        "stock_code": row.get("stock_code"),
        "stock_name": row.get("stock_name") or "",
        "signal_name": row.get("raw_signal"),
        "signal_display_text": row.get("signal_name") or "",
        "signal_type": row.get("signal_type"),
        "confidence": round(_row_confidence(row), 4),
        "evidence_items": _evidence_for(row),
        "stop_rules": rules.get("stop_rules", []),
        "exit_rules": rules.get("exit_rules", []),
        "position_rule_text": rules.get("position_rule_text", ""),
        "external_validation": rules.get("external_validation", ""),
        "strategy_environment_fit": row.get("strategy_environment_fit") or "",
        "disclaimer": RESEARCH_ONLY_DISCLAIMER,
        "found": True,
    }
