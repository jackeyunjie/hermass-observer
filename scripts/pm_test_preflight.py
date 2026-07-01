#!/usr/bin/env python3
"""Run a read-only PM test preflight for the public Hermass site."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://console.supertrader.world"
AUTH_USER = "hermass-test"
AUTH_PASSWORD = "Hermass2026!Lab"

FORBIDDEN_TERMS = [
    "买入",
    "卖出",
    "加仓",
    "减仓",
    "止盈",
    "止损",
    "荐股",
    "收益承诺",
    "目标价",
]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def http_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    auth: bool = False,
    timeout: int = 15,
) -> tuple[int, str]:
    data = None
    headers = {"User-Agent": "Hermass-PM-Preflight/1.0"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if auth:
        token = base64.b64encode(f"{AUTH_USER}:{AUTH_PASSWORD}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def run_command(name: str, args: list[str]) -> CheckResult:
    proc = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = proc.stdout.strip().splitlines()
    detail = output[-1] if output else f"exit={proc.returncode}"
    return CheckResult(name, proc.returncode == 0, detail)


def check_public_pages() -> list[CheckResult]:
    pages = [
        ("home", "/"),
        ("market", "/market"),
        ("recommend", "/recommend"),
        ("research", "/research?stock_code=000021.SZ"),
        ("watchlist", "/watchlist"),
        ("playbook", "/playbook"),
        ("feedback", "/feedback"),
    ]
    results: list[CheckResult] = []
    for name, path in pages:
        status, _ = http_request("GET", f"{BASE_URL}{path}")
        results.append(CheckResult(f"public page {name}", status == 200, f"HTTP {status} {path}"))
    return results


def check_auth_boundaries() -> list[CheckResult]:
    public_payload = {"message": "ping"}
    public_status, _ = http_request(
        "POST",
        f"{BASE_URL}/api/chat/public-query",
        payload=public_payload,
    )
    anon_status, _ = http_request(
        "POST",
        f"{BASE_URL}/api/chat/query",
        payload={"message": "ping", "mode": "chat", "use_llm": False},
    )
    auth_status, _ = http_request(
        "POST",
        f"{BASE_URL}/api/chat/query",
        payload={"message": "ping", "mode": "chat", "use_llm": False},
        auth=True,
    )
    favicon_status, _ = http_request("GET", f"{BASE_URL}/favicon.ico")
    return [
        CheckResult("public Guanxiang", public_status == 200, f"HTTP {public_status}"),
        CheckResult("chat requires auth", anon_status == 401, f"HTTP {anon_status}"),
        CheckResult("chat auth smoke", auth_status == 200, f"HTTP {auth_status}"),
        CheckResult("favicon", favicon_status not in {0, 404}, f"HTTP {favicon_status}"),
    ]


def check_data_status(expected_date: str) -> list[CheckResult]:
    compact_date = expected_date.replace("-", "")
    status, body = http_request("GET", f"{BASE_URL}/api/admin/data-sync-status?date={compact_date}")
    if status != 200:
        return [CheckResult("data sync status", False, f"HTTP {status}")]
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        return [CheckResult("data sync status JSON", False, str(exc))]

    expected = data.get("expected_date")
    daily = data.get("daily_snapshot") or {}
    market_assets = data.get("market_assets_state") or {}
    ok = expected == expected_date and daily.get("date") == expected_date
    detail = f"expected={expected}, daily={daily.get('date')}, market_assets={market_assets.get('date')}"
    return [CheckResult("data date", ok, detail)]


def check_daily_brief(expected_date: str) -> list[CheckResult]:
    status, body = http_request("GET", f"{BASE_URL}/api/daily-observation-brief")
    if status != 200:
        return [CheckResult("daily observation brief", False, f"HTTP {status}")]
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        return [CheckResult("daily observation brief JSON", False, str(exc))]
    date_value = str(data.get("date") or "")
    candidates = data.get("watch_candidates") or []
    ok = date_value == expected_date and isinstance(candidates, list)
    return [CheckResult("daily brief date", ok, f"date={date_value}, candidates={len(candidates)}")]


def check_guanxiang_response() -> list[CheckResult]:
    status, body = http_request(
        "POST",
        f"{BASE_URL}/api/chat/query",
        payload={
            "message": "000021 怎么样",
            "mode": "chat",
            "use_llm": True,
            "page": "stock",
            "stock_code": "000021.SZ",
        },
        auth=True,
    )
    if status != 200:
        return [CheckResult("Guanxiang stock question", False, f"HTTP {status}")]
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        return [CheckResult("Guanxiang stock question JSON", False, str(exc))]
    provider = data.get("provider")
    answer = str(data.get("answer") or "")
    forbidden = [term for term in FORBIDDEN_TERMS if term in body]
    results = [
        CheckResult("Guanxiang stock question", bool(answer), f"provider={provider}, answer_len={len(answer)}"),
        CheckResult("Guanxiang forbidden terms", not forbidden, f"terms={','.join(forbidden) or '-'}"),
    ]
    return results


def print_results(results: list[CheckResult]) -> int:
    failed = 0
    for result in results:
        marker = "OK" if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {result.detail}")
        if not result.ok:
            failed += 1
    print(f"[SUMMARY] total={len(results)} failed={failed}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only PM test preflight.")
    parser.add_argument("--date", required=True, help="Expected data date in YYYY-MM-DD format.")
    parser.add_argument("--skip-local", action="store_true", help="Skip local py_compile and release checks.")
    args = parser.parse_args()

    results: list[CheckResult] = []
    if not args.skip_local:
        results.append(run_command("py_compile web/main.py", [".venv/bin/python", "-m", "py_compile", "web/main.py"]))
        results.append(run_command("verify_release", [".venv/bin/python", "scripts/verify_release.py"]))
    results.extend(check_public_pages())
    results.extend(check_auth_boundaries())
    results.extend(check_data_status(args.date))
    results.extend(check_daily_brief(args.date))
    results.extend(check_guanxiang_response())
    return print_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
