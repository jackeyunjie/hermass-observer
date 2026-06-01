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
    if expected_date in html:
        ok(f"industry page contains date={expected_date}")
    else:
        fail(errors, f"industry page missing expected date={expected_date}")

    if str(signal_count) in html:
        ok(f"industry page contains signal_count={signal_count}")
    else:
        fail(errors, f"industry page missing signal_count={signal_count}")

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

    if errors:
        print(f"[SUMMARY] failed={len(errors)}")
        return 1
    print("[SUMMARY] all website data sync checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
