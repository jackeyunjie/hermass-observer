#!/usr/bin/env python3
"""Build a minimal weekly cognitive recap from behavior ledgers and foundation state.

Phase 1:
- group-level recap
- summarize watched stocks in last 7 days
- compare latest state vs one week ago
- output short text for Feishu push
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermass_platform.agents.base_agent import find_foundation_db
from hermass_platform.slice.industry_slice import detect_sector_resonance, list_industries

COGNITIVE_DIR = ROOT / "outputs" / "cognitive"
FUNDAMENTAL_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"


def _canonical_stock_code(stock_code: str) -> str:
    digits = "".join(ch for ch in stock_code if ch.isdigit())
    if len(digits) != 6:
        return stock_code.upper()
    if digits.startswith(("6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("8", "4")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def _load_recent_stock_focus(days: int = 7) -> list[str]:
    watchlist: set[str] = set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for path in COGNITIVE_DIR.glob("behavior_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for event in payload.get("events", []):
            ts = event.get("timestamp")
            if not ts:
                continue
            try:
                event_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            if event_dt < cutoff:
                continue
            event_payload = event.get("payload") or {}
            stock_code = str(event_payload.get("stock_code") or "").strip()
            if stock_code:
                watchlist.add(_canonical_stock_code(stock_code))
    return sorted(watchlist)


def _load_recent_stock_focus_counts(days: int = 7) -> Counter[str]:
    counts: Counter[str] = Counter()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for path in COGNITIVE_DIR.glob("behavior_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for event in payload.get("events", []):
            ts = event.get("timestamp")
            if not ts:
                continue
            try:
                event_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            if event_dt < cutoff:
                continue
            event_payload = event.get("payload") or {}
            stock_code = str(event_payload.get("stock_code") or "").strip()
            if stock_code:
                counts[_canonical_stock_code(stock_code)] += 1
    return counts


def _load_recent_industry_focus(days: int = 7) -> list[str]:
    focus: set[str] = set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    industries = list_industries()
    for path in COGNITIVE_DIR.glob("behavior_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for event in payload.get("events", []):
            ts = event.get("timestamp")
            if not ts:
                continue
            try:
                event_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            if event_dt < cutoff:
                continue
            message = str((event.get("payload") or {}).get("message") or "")
            for industry in industries:
                if industry in message:
                    focus.add(industry)
    return sorted(focus)


def _load_recent_industry_focus_counts(days: int = 7) -> Counter[str]:
    counts: Counter[str] = Counter()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    industries = list_industries()
    for path in COGNITIVE_DIR.glob("behavior_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for event in payload.get("events", []):
            ts = event.get("timestamp")
            if not ts:
                continue
            try:
                event_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            if event_dt < cutoff:
                continue
            message = str((event.get("payload") or {}).get("message") or "")
            for industry in industries:
                if industry in message:
                    counts[industry] += 1
    return counts


def _stock_name_map() -> dict[str, str]:
    if not FUNDAMENTAL_DB.exists():
        return {}
    con = duckdb.connect(str(FUNDAMENTAL_DB), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT DISTINCT stock_code, stock_name
            FROM ifind_industry_chain_profile
            WHERE stock_code IS NOT NULL AND stock_name IS NOT NULL AND stock_name != ''
            """
        ).fetchall()
        return {str(code).upper(): str(name) for code, name in rows}
    finally:
        con.close()


def _state_combo(con: duckdb.DuckDBPyConnection, stock_code: str, target_date: str) -> tuple[str, str] | None:
    row = con.execute(
        """
        SELECT mn1_state_hex, w1_state_hex, d1_state_hex
        FROM d1_perspective_state
        WHERE stock_code = ?
          AND state_date <= CAST(? AS DATE)
        ORDER BY state_date DESC
        LIMIT 1
        """,
        [stock_code, target_date],
    ).fetchone()
    if not row:
        return None
    combo = "/".join(str(item or "-") for item in row)
    return combo, str(row[0] or "")


def _state_change_text(before: str | None, after: str | None) -> str:
    if not before or not after:
        return "State 数据不足"
    if before == after:
        return f"State 保持 {after}"
    return f"State 从 {before} 变为 {after}"


def build_weekly_recap(target_date: str) -> str:
    watchlist = _load_recent_stock_focus(days=7)
    stock_focus_counts = _load_recent_stock_focus_counts(days=7)
    industry_focus = _load_recent_industry_focus(days=7)
    industry_focus_counts = _load_recent_industry_focus_counts(days=7)
    if not watchlist and not industry_focus:
        return "本周认知复盘：最近 7 天暂未记录到明确的个股或行业研究关注轨迹。"

    foundation_db = find_foundation_db(target_date)
    if not foundation_db:
        return "本周认知复盘：当前缺少 foundation 数据，无法生成结构化回顾。"

    name_map = _stock_name_map()
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        last_week = str((date.fromisoformat(target_date) - timedelta(days=7)).isoformat())
        changes = []
        for stock_code in watchlist[:6]:
            current = _state_combo(con, stock_code, target_date)
            previous = _state_combo(con, stock_code, last_week)
            if not current:
                continue
            changes.append(
                (
                    stock_code,
                    name_map.get(stock_code, ""),
                    _state_change_text(previous[0] if previous else None, current[0]),
                )
            )
    finally:
        con.close()

    resonance_today = {
        item.get("sw_l1"): item for item in detect_sector_resonance(foundation_db, target_date)
    }

    lines = [
        f"本周关注回顾：最近 7 天共重点问了 {len(watchlist)} 只股票，关注了 {len(industry_focus)} 个行业。",
    ]
    if changes:
        snippets = []
        for stock_code, stock_name, summary in changes[:3]:
            display = f"{stock_code.split('.')[0]} {stock_name}".strip()
            snippets.append(f"{display} {summary}")
        lines.append("其中：" + "；".join(snippets) + "。")
    if stock_focus_counts:
        top_stock_snippets = []
        for stock_code, count in stock_focus_counts.most_common(3):
            display = f"{stock_code.split('.')[0]} {name_map.get(stock_code, '')}".strip()
            top_stock_snippets.append(f"{display}（{count} 次）")
        lines.append("高频关注：" + "；".join(top_stock_snippets) + "。")
    if industry_focus:
        industry_snippets = []
        for industry in industry_focus[:3]:
            resonance = resonance_today.get(industry)
            if resonance:
                industry_snippets.append(
                    f"{industry} 在本周收盘观察点出现板块共振（确认 {resonance.get('resonance_count', 0)} 只）"
                )
            else:
                industry_snippets.append(f"{industry} 本周未触发显著板块共振")
        lines.append("行业关注：" + "；".join(industry_snippets) + "。")
    if industry_focus_counts:
        top_industry_snippets = [
            f"{industry}（{count} 次）" for industry, count in industry_focus_counts.most_common(3)
        ]
        lines.append("高频行业：" + "；".join(top_industry_snippets) + "。")
    lines.append("系统观察：本周回顾以结构变化为主，不对买卖结果作评价。")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build weekly cognitive recap.")
    parser.add_argument("--date", default=str(date.today()))
    parser.add_argument("--output")
    args = parser.parse_args()

    recap = build_weekly_recap(args.date)
    if args.output:
        Path(args.output).write_text(recap, encoding="utf-8")
    print(recap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
