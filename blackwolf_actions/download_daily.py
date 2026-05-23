#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from token_provider import read_token


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def run_daily_download(date_str: str, base_date: str | None = None, test: bool = False) -> dict:
    token = read_token()
    base_ymd = ymd(base_date or previous_base_date(date_str))
    date_ymd = ymd(date_str)
    script = RESEARCH_ROOT / "scripts" / "download_blackwolf_ashare_daily_api.py"
    base_zip = RESEARCH_ROOT / "data" / f"blackwolf_ashare_daily_mac_format_20180515_{base_ymd}.zip"
    out_zip_name = f"blackwolf_ashare_daily_mac_format_20180515_{date_ymd}{'_test' if test else ''}.zip"
    out_zip = RESEARCH_ROOT / "data" / out_zip_name
    summary = ROOT / "reports" / "blackwolf_actions" / f"daily_download_{date_ymd}{'_test' if test else ''}.json"
    if not script.exists():
        raise FileNotFoundError(script)
    if not base_zip.exists():
        raise FileNotFoundError(base_zip)

    env = dict(os.environ)
    env["BLACKWOLF_TOKEN"] = token
    cmd = [
        sys.executable,
        str(script),
        "--date",
        date_str,
        "--base-zip",
        str(base_zip),
        "--out-zip",
        str(out_zip),
        "--summary",
        str(summary),
    ]
    result = subprocess.run(cmd, cwd=RESEARCH_ROOT, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(sanitize_output(result.stderr or result.stdout))
    payload = json.loads(result.stdout)
    payload["token_source"] = "local_secure_provider"
    payload["token_written_to_logs"] = False
    return payload


def previous_base_date(date_str: str) -> str:
    # Production calls should pass --base-date. The default supports current 2026-05-21 testing.
    if date_str == "2026-05-21":
        return "2026-05-20"
    raise RuntimeError("missing --base-date")


def sanitize_output(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if "token" not in line.lower())[:2000]


def main() -> int:
    parser = argparse.ArgumentParser(description="Blackwolf daily download action.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--base-date")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    result = run_daily_download(args.date, args.base_date, args.test)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
