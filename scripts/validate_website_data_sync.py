#!/usr/bin/env python3
"""Validate that website-facing daily data is synced on the server."""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any

import requests


BASE_URL = os.environ.get("HERMASS_SITE_URL", "http://8.130.125.201")
HOST_HEADER = os.environ.get("HERMASS_UPLOAD_HOST", "console.supertrader.world")
AUTH_USER = os.environ.get("HERMASS_UPLOAD_USER", "hermass-test")
AUTH_PASS = os.environ.get("HERMASS_UPLOAD_PASS", "Hermass2026!Lab")


def normalize_date(date_str: str) -> str:
    if re.fullmatch(r"\d{8}", date_str or ""):
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return date_str


def compact_date(date_str: str) -> str:
    return normalize_date(date_str).replace("-", "")


def auth() -> tuple[str, str] | None:
    return (AUTH_USER, AUTH_PASS) if AUTH_USER and AUTH_PASS else None


def headers() -> dict[str, str]:
    return {"Host": HOST_HEADER} if HOST_HEADER else {}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)
    print(f"[FAIL] {message}")


def ok(message: str) -> None:
    print(f"[OK] {message}")


def get_json(path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    resp = requests.get(
        f"{BASE_URL.rstrip('/')}{path}",
        params=params,
        headers=headers(),
        auth=auth(),
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def get_text(path: str) -> str:
    resp = requests.get(
        f"{BASE_URL.rstrip('/')}{path}",
        headers=headers(),
        auth=auth(),
        timeout=60,
    )
    resp.raise_for_status()
    return resp.text


def validate_status(status: dict[str, Any], expected_date: str) -> list[str]:
    errors: list[str] = []

    def require_fresh_file(label: str, item: dict[str, Any], *, min_rows: int = 1, exact_date: bool = True) -> None:
        item_date = str(item.get("date") or "")
        row_count = int(item.get("row_count") or 0)
        date_ok = item_date == expected_date if exact_date else item_date >= expected_date
        if item.get("exists") and date_ok and row_count >= min_rows:
            ok(f"{label} date={item_date} rows={row_count}")
        else:
            fail(errors, f"{label} stale/missing: {item}")

    daily = status.get("daily_snapshot") or {}
    if daily.get("exists") and daily.get("date") == expected_date:
        ok(f"daily_snapshot date={daily.get('date')}")
    else:
        fail(errors, f"daily_snapshot stale/missing: {daily}")

    signal = status.get("strategy_signal_daily") or {}
    if signal.get("exists") and signal.get("date") == expected_date and int(signal.get("signal_count") or 0) > 0:
        ok(f"strategy_signal_daily date={signal.get('date')} signal_count={signal.get('signal_count')}")
    else:
        fail(errors, f"strategy_signal_daily stale/missing: {signal}")

    latest_signal = status.get("strategy_signal_latest") or {}
    if latest_signal.get("exists") and latest_signal.get("date") == expected_date:
        ok(f"strategy_signal_latest date={latest_signal.get('date')}")
    else:
        fail(errors, f"strategy_signal_latest stale/missing: {latest_signal}")

    state_cache = status.get("state_cache") or {}
    require_fresh_file("state_cache.state_ef", state_cache.get("state_ef") or {})
    require_fresh_file("state_cache.state_duration", state_cache.get("state_duration") or {})
    require_fresh_file("state_cache.sr_boundary", state_cache.get("sr_boundary") or {})
    require_fresh_file("market_phase", status.get("market_phase") or {}, min_rows=0)
    require_fresh_file("market_assets_state", status.get("market_assets_state") or {})
    require_fresh_file("unified_view", status.get("unified_view") or {})
    require_fresh_file("forward_observation", status.get("forward_observation") or {}, min_rows=0)

    macro = status.get("macro_chain_prior") or {}
    if macro.get("exists") and macro.get("date"):
        ok(f"macro_chain_prior date={macro.get('date')} rows={macro.get('row_count')}")
    else:
        fail(errors, f"macro_chain_prior missing: {macro}")

    delta = status.get("foundation_delta") or {}
    if delta.get("exists") and int(delta.get("size") or 0) > 0:
        ok(f"foundation_delta exists size={delta.get('size')}")
    else:
        fail(errors, f"foundation_delta missing: {delta}")

    foundation = status.get("foundation_db") or {}
    if (
        foundation.get("exists")
        and foundation.get("latest_date") >= expected_date
        and int(foundation.get("daily_rows") or 0) > 0
        and int(foundation.get("state_rows") or 0) > 0
    ):
        ok(
            "foundation_db "
            f"latest_date={foundation.get('latest_date')} "
            f"daily_rows={foundation.get('daily_rows')} "
            f"state_rows={foundation.get('state_rows')}"
        )
    else:
        fail(errors, f"foundation_db stale/missing rows: {foundation}")

    return errors


def validate_industry_page(html: str, expected_date: str, signal_count: int) -> list[str]:
    errors: list[str] = []
    if f"数据 {expected_date}" in html:
        ok(f"industry header data date={expected_date}")
    else:
        fail(errors, f"industry header missing data date={expected_date}")

    if expected_date in html:
        ok(f"industry page contains date={expected_date}")
    else:
        fail(errors, f"industry page missing expected date={expected_date}")

    if str(signal_count) in html:
        ok(f"industry page contains signal_count={signal_count}")
    else:
        fail(errors, f"industry page missing signal_count={signal_count}")

    return errors


def validate_market_page(html: str, expected_date: str) -> list[str]:
    errors: list[str] = []
    if f"数据 {expected_date}" in html:
        ok(f"market header data date={expected_date}")
    else:
        fail(errors, f"market header missing data date={expected_date}")
    if (
        f"当前数据日期：{expected_date}" in html
        or f"数据截至 {expected_date}" in html
        or f"数据截至&nbsp;{expected_date}" in html
    ):
        ok(f"market hero data date={expected_date}")
    else:
        fail(errors, f"market hero missing data date={expected_date}")
    if "未知阶段" in html.split("</section>", 1)[0]:
        fail(errors, "market first screen still leads with unknown phase")
    else:
        ok("market first screen does not lead with unknown phase")
    return errors


def validate_state_observer_page(html: str) -> list[str]:
    """State Timeline Observer 页面最小验收：页面可打开且包含核心文案。"""
    errors: list[str] = []
    required_phrases = [
        "State Timeline Observer",
        "State 观察工作台",
        "不是交易指令面板",
        "MN1",
        "W1",
        "D1",
    ]
    for phrase in required_phrases:
        if phrase in html:
            ok(f"state-observer page contains '{phrase}'")
        else:
            fail(errors, f"state-observer page missing '{phrase}'")
    return errors


def validate_state_observer_api(expected_date: str) -> list[str]:
    """State Timeline Observer API 最小验收：能返回当天数据且字段完整。"""
    errors: list[str] = []
    try:
        data = get_json("/api/state-observer", {"symbol_set": "top50", "days": "1", "page": "1", "page_size": "5"})
        if not data.get("ok"):
            fail(errors, f"state-observer API returned ok=false: {data.get('error')}")
            return errors
        rows = data.get("rows", [])
        meta = data.get("meta", {})
        if meta.get("date_max") == expected_date:
            ok(f"state-observer API date_max={expected_date}")
        else:
            fail(errors, f"state-observer API date_max={meta.get('date_max')} != {expected_date}")
        if rows:
            first = rows[0]
            required_fields = [
                "stock_code", "stock_name", "state_date",
                "mn1_state_hex", "w1_state_hex", "d1_state_hex",
                "mn1_is_ef", "w1_is_ef", "d1_is_ef",
                "mn1_is_ab", "w1_is_ab", "d1_is_ab",
                "mn1_is_zero", "w1_is_zero", "d1_is_zero",
                "ef_pattern", "ab_pattern", "zero_pattern",
                "state_change_flag", "ef_change", "transition_label",
            ]
            missing = [f for f in required_fields if f not in first]
            if not missing:
                ok(f"state-observer API row fields complete")
            else:
                fail(errors, f"state-observer API missing fields: {missing}")
        else:
            fail(errors, "state-observer API returned no rows for top50")
    except Exception as exc:
        fail(errors, f"state-observer API request failed: {exc}")
    return errors


def validate_state_observer_watchlist(expected_date: str) -> list[str]:
    """State Timeline Observer watchlist 路径验收：有任务返回真实数据，无任务返回空结果且不报错。"""
    errors: list[str] = []
    try:
        data = get_json("/api/state-observer", {"symbol_set": "watchlist", "days": "5"})
        if not data.get("ok"):
            fail(errors, f"state-observer watchlist returned ok=false: {data.get('error')}")
            return errors
        rows = data.get("rows", [])
        meta = data.get("meta", {})
        if not isinstance(rows, list):
            fail(errors, "state-observer watchlist rows is not a list")
            return errors
        if meta.get("date_max") == expected_date:
            ok(f"state-observer watchlist date_max={expected_date}")
        else:
            fail(errors, f"state-observer watchlist date_max={meta.get('date_max')} != {expected_date}")
        ok(f"state-observer watchlist returned ok=true rows={len(rows)}")
        if rows:
            first = rows[0]
            if all(f in first for f in ("stock_code", "state_date", "state_change_flag", "ef_change", "transition_label")):
                ok("state-observer watchlist row fields complete")
            else:
                missing = [f for f in ("stock_code", "state_date", "state_change_flag", "ef_change", "transition_label") if f not in first]
                fail(errors, f"state-observer watchlist missing fields: {missing}")
    except Exception as exc:
        fail(errors, f"state-observer watchlist request failed: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Hermass website daily data sync.")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD or YYYYMMDD")
    args = parser.parse_args()

    expected_date = normalize_date(args.date)
    print(f"[CHECK] website data sync date={expected_date}")

    errors: list[str] = []
    try:
        status = get_json("/api/admin/data-sync-status", {"date": compact_date(expected_date)})
    except Exception as exc:
        print(f"[FAIL] data-sync-status request failed: {exc}")
        return 1

    errors.extend(validate_status(status, expected_date))

    signal_count = int((status.get("strategy_signal_daily") or {}).get("signal_count") or 0)
    try:
        industry_html = get_text("/industry")
        errors.extend(validate_industry_page(industry_html, expected_date, signal_count))
    except Exception as exc:
        fail(errors, f"industry page request failed: {exc}")

    try:
        market_html = get_text("/market")
        errors.extend(validate_market_page(market_html, expected_date))
    except Exception as exc:
        fail(errors, f"market page request failed: {exc}")

    try:
        state_observer_html = get_text("/state-observer")
        errors.extend(validate_state_observer_page(state_observer_html))
    except Exception as exc:
        fail(errors, f"state-observer page request failed: {exc}")

    errors.extend(validate_state_observer_api(expected_date))
    errors.extend(validate_state_observer_watchlist(expected_date))

    if errors:
        print(f"[SUMMARY] failed={len(errors)}")
        return 1
    print("[SUMMARY] all website data sync checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
