"""Observation Deck 转折概率首页适配层。

把 `turning_point_probability_reader` 的原始概率信号转换成 Research-Only
的结构标签，供首页模板直接展示。不返回裸概率百分比。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from urllib.parse import quote

from web.services.turning_point_probability_reader import (
    get_signals as tpp_get_signals,
    get_summary as tpp_get_summary,
)

log = logging.getLogger("hermass.web.observation_deck_probability")

WINDOWS_FOR_DECK = ["3W", "3M"]

TURNING_TYPE_LABEL = {
    "turn_up": "结构转强",
    "turn_down": "结构转弱",
    "continue": "持续结构",
    "false_breakout": "假突破风险",
    "uncertain": "证据不足",
}

TURNING_TYPE_TONE = {
    "turn_up": "strong",
    "turn_down": "risk",
    "continue": "muted",
    "false_breakout": "risk",
    "uncertain": "muted",
}


def _safe_first(seq: list[Any]) -> Any:
    return seq[0] if seq else None


def _risk_label(row: dict[str, Any]) -> str:
    """基于 risk_flags 和 confidence 生成一个风险标签。"""
    flags = row.get("risk_flags") or []
    if isinstance(flags, str):
        flags = [flags]
    first = _safe_first(flags)
    if first:
        return str(first)
    confidence = row.get("confidence")
    if confidence is not None:
        try:
            if float(confidence) < 0.4:
                return "低置信"
        except (TypeError, ValueError):
            return "低置信"
    return ""


def _evidence_count(row: dict[str, Any]) -> int:
    items = row.get("evidence_items") or []
    if isinstance(items, str):
        # 防御：理论上 reader 已解析为列表
        return 1 if items else 0
    return len(items)


def _build_item(row: dict[str, Any]) -> dict[str, Any] | None:
    stock_code = str(row.get("stock_code") or "").strip().upper()
    if not stock_code:
        return None
    turning_type = str(row.get("turning_type") or "uncertain").strip().lower()
    label = TURNING_TYPE_LABEL.get(turning_type, "证据不足")
    tone = TURNING_TYPE_TONE.get(turning_type, "muted")
    return {
        "stock_code": stock_code,
        "stock_name": str(row.get("stock_name") or stock_code),
        "window": str(row.get("window") or "").upper(),
        "label": label,
        "tone": tone,
        "evidence_count": _evidence_count(row),
        "risk_label": _risk_label(row),
        "industry_l1": row.get("industry_l1") or "",
        "research_url": f"/research?stock_code={quote(stock_code, safe='')}",
    }


def build_observation_deck_probability_signals(limit: int = 5) -> dict[str, Any]:
    """构建首页概率信号面板数据。

    返回字段：
        ok, date, warning, items
    """
    warnings: list[str] = []

    summary = tpp_get_summary()
    state_date = summary.get("state_date") or str(date.today())

    candidates: list[dict[str, Any]] = []
    for window in WINDOWS_FOR_DECK:
        try:
            result = tpp_get_signals(window=window, limit=limit)
        except Exception as exc:
            log.warning("读取 %s 概率信号失败: %s", window, exc)
            warnings.append(f"读取 {window} 信号失败")
            continue
        if not result.get("ok"):
            warnings.append(result.get("warning") or result.get("error") or f"{window} 信号不可用")
            continue
        for row in result.get("signals", []) or []:
            item = _build_item(row)
            if item:
                candidates.append(item)

    if not candidates:
        return {
            "ok": True,
            "date": state_date,
            "warning": "; ".join(warnings) if warnings else "暂无转折概率信号",
            "items": [],
        }

    # 去重：同一标的同一窗口只保留一条；按出现顺序
    seen: set[tuple[str, str]] = set()
    items: list[dict[str, Any]] = []
    for item in candidates:
        key = (item["stock_code"], item["window"])
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
        if len(items) >= limit:
            break

    return {
        "ok": True,
        "date": state_date,
        "warning": "; ".join(warnings) if warnings else "",
        "items": items,
    }
