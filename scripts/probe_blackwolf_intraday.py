#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from typing import Any


API_BASE = "http://api.fxyz.site"
DEFAULT_PERIODS = ["1m", "5m", "15m", "30m", "60m", "1h", "H1", "240m", "4h", "H4"]


def read_token() -> str:
    token = sys.stdin.read().strip()
    if not token:
        raise RuntimeError("missing token on stdin")
    return token


def request_json(path: str, params: dict[str, str], timeout: int) -> Any:
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "HermassResearch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-JSON response: {text[:240]!r}") from exc


def unwrap_records(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ["data", "rows", "result", "list", "items", "values"]:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        if isinstance(payload.get("data"), dict):
            return unwrap_records(payload["data"])
    return []


def sample_shape(value: Any) -> Any:
    if isinstance(value, dict):
        keys = list(value.keys())
        return {"keys": keys[:24], "sample": {key: value[key] for key in keys[:10]}}
    if isinstance(value, (list, tuple)):
        return list(value[:12])
    return repr(value)[:240]


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Blackwolf intraday periods for one stock.")
    parser.add_argument("--code", default="688107")
    parser.add_argument("--start-date", default="2026-04-15")
    parser.add_argument("--end-date", default="2026-05-19")
    parser.add_argument("--periods", nargs="*", default=DEFAULT_PERIODS)
    parser.add_argument("--timeout", type=int, default=25)
    args = parser.parse_args()

    token = read_token()
    for period in args.periods:
        try:
            payload = request_json(
                "/wolf/time/kline",
                {
                    "symbol": "stock",
                    "code": args.code,
                    "period": period,
                    "cq": "1",
                    "startDate": args.start_date,
                    "endDate": args.end_date,
                    "token": token,
                },
                args.timeout,
            )
            records = unwrap_records(payload)
            sample = sample_shape(records[0] if records else payload)
            print(json.dumps({"period": period, "count": len(records), "sample": sample}, ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({"period": period, "error": f"{type(exc).__name__}: {str(exc)[:220]}"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
