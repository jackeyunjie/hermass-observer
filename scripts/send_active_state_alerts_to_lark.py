#!/usr/bin/env python3
"""Send minimal active state alerts to Lark for recently watched stocks.

Phase 1 rules:
- Only look at stocks mentioned in recent cognitive behavior ledgers.
- Trigger on:
  1. D1 state dropping out of E/F
  2. D1 score weakening 3 consecutive trading days
  3. Sector resonance on the stock's industry
- Deduplicate by trade_date + stock_code + alert_type + bucket
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermass_platform.agents.base_agent import find_foundation_db
from hermass_platform.slice.industry_slice import detect_sector_resonance, list_industries

COGNITIVE_DIR = ROOT / "outputs" / "cognitive"
FUNDAMENTAL_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
LARK_CONFIG = ROOT / "config" / "platform" / "lark_app.yaml"
ALERT_LEDGER = ROOT / "outputs" / "alerts" / "active_state_alerts_sent.json"


def _ensure_alert_dir() -> None:
    ALERT_LEDGER.parent.mkdir(parents=True, exist_ok=True)


def _load_alert_ledger() -> dict[str, Any]:
    _ensure_alert_dir()
    if not ALERT_LEDGER.exists():
        return {"version": "1.0.0", "sent_keys": []}
    try:
        return json.loads(ALERT_LEDGER.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "1.0.0", "sent_keys": []}


def _save_alert_ledger(data: dict[str, Any]) -> None:
    ALERT_LEDGER.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _canonical_stock_code(stock_code: str) -> str:
    digits = "".join(ch for ch in stock_code if ch.isdigit())
    if len(digits) != 6:
        return stock_code.upper()
    if digits.startswith(("6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("8", "4")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def _load_recent_watchlist(days: int = 7) -> set[str]:
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
            message = str(event_payload.get("message") or "")
            for token in message.split():
                digits = "".join(ch for ch in token if ch.isdigit())
                if len(digits) == 6:
                    watchlist.add(_canonical_stock_code(digits))
    return watchlist


def _load_recent_industry_focus(days: int = 7) -> set[str]:
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
    return focus


def _load_watchlist_from_all_recent_events(days: int = 30) -> set[str]:
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
    return watchlist


def _industry_map() -> dict[str, str]:
    if not FUNDAMENTAL_DB.exists():
        return {}
    con = duckdb.connect(str(FUNDAMENTAL_DB), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT DISTINCT stock_code, sw_l1
            FROM ifind_industry_chain_profile
            WHERE stock_code IS NOT NULL AND sw_l1 IS NOT NULL AND sw_l1 != ''
            """
        ).fetchall()
        return {str(code).upper(): str(sw_l1) for code, sw_l1 in rows}
    finally:
        con.close()


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


def _load_state_rows(foundation_db: str, stock_code: str, target_date: str) -> list[tuple]:
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        return con.execute(
            """
            SELECT state_date, d1_state_hex, d1_state_score, w1_state_hex, mn1_state_hex
            FROM d1_perspective_state
            WHERE stock_code = ?
              AND state_date <= CAST(? AS DATE)
            ORDER BY state_date DESC
            LIMIT 5
            """,
            [stock_code, target_date],
        ).fetchall()
    finally:
        con.close()


def _d1_drop_alert(stock_code: str, rows: list[tuple]) -> dict[str, str] | None:
    if len(rows) < 2:
        return None
    latest_state = str(rows[0][1] or "")
    prev_state = str(rows[1][1] or "")
    if prev_state in {"E", "F"} and latest_state not in {"E", "F"}:
        return {
            "alert_type": "state_drop",
            "bucket": latest_state or "unknown",
            "title": f"{stock_code} State 提醒：D1 从 {prev_state} 回落到 {latest_state or '-'}。",
            "reason": "原因：短周期已从最强状态转入确认，原有共振需要重新观察。",
        }
    return None


def _d1_weakening_alert(stock_code: str, rows: list[tuple]) -> dict[str, str] | None:
    if len(rows) < 3:
        return None
    s0 = rows[0][2]
    s1 = rows[1][2]
    s2 = rows[2][2]
    if None in (s0, s1, s2):
        return None
    if int(s0) < int(s1) < int(s2):
        return {
            "alert_type": "d1_weakening_3d",
            "bucket": str(s0),
            "title": f"{stock_code} State 提醒：D1 已连续 3 个交易日走弱。",
            "reason": "原因：短周期强度持续回落，说明推进节奏正在降温。",
        }
    return None


def _sector_resonance_alert(
    stock_code: str,
    industry_map: dict[str, str],
    resonance_by_industry: dict[str, dict[str, Any]],
) -> dict[str, str] | None:
    industry = industry_map.get(stock_code)
    if not industry:
        return None
    item = resonance_by_industry.get(industry)
    if not item:
        return None
    return {
        "alert_type": "sector_resonance",
        "bucket": str(item.get("resonance_count") or "0"),
        "title": f"{stock_code} 行业提醒：{industry} 今日出现板块共振。",
        "reason": f"原因：同日共振确认 {item.get('resonance_count')} 只，行业同步强化值得一起观察。",
    }


def _focused_industry_resonance_alert(
    industry: str,
    resonance_by_industry: dict[str, dict[str, Any]],
) -> dict[str, str] | None:
    item = resonance_by_industry.get(industry)
    if not item:
        return None
    return {
        "alert_type": "focused_industry_resonance",
        "bucket": str(item.get("resonance_count") or "0"),
        "title": f"{industry} 行业提醒：今日出现板块共振。",
        "reason": f"原因：这是最近问过的行业，同日共振确认 {item.get('resonance_count')} 只。",
    }


def _load_chat_target() -> tuple[str, str]:
    if not LARK_CONFIG.exists():
        return "", ""
    text = LARK_CONFIG.read_text(encoding="utf-8")
    chat_id = ""
    webhook_url = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("chat_id:"):
            chat_id = stripped.split(":", 1)[1].strip().strip('"').strip("'")
        elif stripped.startswith("webhook_url:"):
            webhook_url = stripped.split(":", 1)[1].strip().strip('"').strip("'")
    return chat_id, webhook_url


def _push_to_lark(message: str, chat_id: str, webhook_url: str) -> bool:
    try:
        if webhook_url:
            cmd = ["lark-cli", "im", "+send", "--webhook", webhook_url, "--text", message]
        elif chat_id:
            cmd = ["lark-cli", "im", "+send", "--chat-id", chat_id, "--text", message]
        else:
            return False
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Send active state alerts to Lark.")
    parser.add_argument("--date", default=str(date.today()))
    parser.add_argument("--watch-days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    foundation_db = find_foundation_db(args.date)
    if not foundation_db:
        print("no foundation db")
        return 1

    watchlist = sorted(_load_recent_watchlist(days=args.watch_days))
    industry_focus = sorted(_load_recent_industry_focus(days=args.watch_days))
    if not watchlist:
        watchlist = sorted(_load_watchlist_from_all_recent_events(days=30))
    if not watchlist and not industry_focus:
        print("no recent watchlist")
        return 0

    industry_map = _industry_map()
    stock_name_map = _stock_name_map()
    resonance = detect_sector_resonance(str(foundation_db), target_date=args.date)
    resonance_by_industry = {item["sw_l1"]: item for item in resonance}
    ledger = _load_alert_ledger()
    sent_keys = set(ledger.get("sent_keys") or [])
    new_keys: list[str] = []
    messages: list[str] = []

    for stock_code in watchlist:
        rows = _load_state_rows(str(foundation_db), stock_code, args.date)
        alerts = [
            _d1_drop_alert(stock_code, rows),
            _d1_weakening_alert(stock_code, rows),
            _sector_resonance_alert(stock_code, industry_map, resonance_by_industry),
        ]
        for alert in alerts:
            if not alert:
                continue
            key = f"{args.date}:{stock_code}:{alert['alert_type']}:{alert['bucket']}"
            if key in sent_keys:
                continue
            display_code = stock_code.split(".")[0]
            stock_name = stock_name_map.get(stock_code, "")
            title = alert["title"].replace(stock_code, f"{display_code}{(' ' + stock_name) if stock_name else ''}")
            message = f"{title}\n{alert['reason']}"
            messages.append(message)
            new_keys.append(key)

    for industry in industry_focus:
        alert = _focused_industry_resonance_alert(industry, resonance_by_industry)
        if not alert:
            continue
        key = f"{args.date}:industry:{industry}:{alert['alert_type']}:{alert['bucket']}"
        if key in sent_keys:
            continue
        messages.append(f"{alert['title']}\n{alert['reason']}")
        new_keys.append(key)

    if not messages:
        print("no new alerts")
        return 0

    chat_id, webhook_url = _load_chat_target()
    if args.dry_run:
        print(json.dumps({"watchlist": watchlist, "industry_focus": industry_focus, "alerts": messages}, ensure_ascii=False, indent=2))
        return 0
    if not chat_id and not webhook_url:
        print("no lark target configured")
        return 1

    pushed = 0
    for message in messages:
        if _push_to_lark(message, chat_id, webhook_url):
            pushed += 1

    if pushed:
        sent_keys.update(new_keys[:pushed])
        ledger["sent_keys"] = sorted(sent_keys)[-1000:]
        _save_alert_ledger(ledger)

    print(json.dumps({"watchlist_count": len(watchlist), "alerts": len(messages), "pushed": pushed}, ensure_ascii=False))
    return 0 if pushed == len(messages) else 1


if __name__ == "__main__":
    raise SystemExit(main())
