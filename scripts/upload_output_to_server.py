#!/usr/bin/env python3
"""本地数据上传到服务器（替代 SSH rsync）。

用法：
  python3 scripts/upload_output_to_server.py --date 20260601 --type foundation
  python3 scripts/upload_output_to_server.py --date 20260601 --type foundation_delta
  python3 scripts/upload_output_to_server.py --date 20260601 --type strategy_signal_daily
  python3 scripts/upload_output_to_server.py --date 20260601 --type snapshot

需要：服务器已部署 /api/admin/upload-data 端点
"""

from __future__ import annotations

import argparse
import gzip
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("HERMASS_UPLOAD_URL", "http://8.130.125.201/api/admin/upload-data")
HOST_HEADER = os.environ.get("HERMASS_UPLOAD_HOST", "console.supertrader.world")
AUTH_USER = os.environ.get("HERMASS_UPLOAD_USER", "hermass-test")
AUTH_PASS = os.environ.get("HERMASS_UPLOAD_PASS", "Hermass2026!Lab")
AUTH = (AUTH_USER, AUTH_PASS) if AUTH_USER and AUTH_PASS else None
HEADERS = {"Host": HOST_HEADER} if HOST_HEADER else None


def upload_foundation(date: str) -> None:
    db_path = ROOT / "outputs" / f"p116_foundation_{date}" / "p116_foundation.duckdb"
    if not db_path.exists():
        print(f"[ERROR] {db_path} 不存在")
        sys.exit(1)

    size_mb = db_path.stat().st_size / 1024 / 1024
    print(f"压缩上传 Foundation DB ({size_mb:.0f} MB)...")

    compressed = gzip.compress(db_path.read_bytes(), compresslevel=6)
    comp_mb = len(compressed) / 1024 / 1024
    print(f"压缩后 {comp_mb:.0f} MB ({comp_mb / size_mb * 100:.0f}%)")

    resp = requests.post(
        BASE_URL,
        files={"file": ("p116_foundation.duckdb.gz", compressed, "application/gzip")},
        data={"type": "foundation", "date": date},
        auth=AUTH,
        headers=HEADERS,
        timeout=300,
    )
    try:
        data = resp.json()
    except Exception:
        print(f"[ERROR] 非 JSON 响应: HTTP {resp.status_code}")
        print(resp.text[:500])
        sys.exit(1)
    if data.get("ok"):
        print(f"[OK] 上传成功: {data.get('path')} ({data.get('size') / 1024 / 1024:.0f} MB)")
    else:
        print(f"[ERROR] 上传失败: {data.get('error')}")
        sys.exit(1)


def upload_foundation_delta(date: str) -> None:
    db_path = ROOT / "outputs" / f"foundation_delta_{date}" / "foundation_delta.duckdb"
    if not db_path.exists():
        print(f"[ERROR] {db_path} 不存在")
        sys.exit(1)

    size_mb = db_path.stat().st_size / 1024 / 1024
    print(f"压缩上传 Foundation 增量包 ({size_mb:.1f} MB)...")

    compressed = gzip.compress(db_path.read_bytes(), compresslevel=6)
    comp_mb = len(compressed) / 1024 / 1024
    print(f"压缩后 {comp_mb:.1f} MB ({comp_mb / size_mb * 100:.0f}%)")

    resp = requests.post(
        BASE_URL,
        files={"file": ("foundation_delta.duckdb.gz", compressed, "application/gzip")},
        data={"type": "foundation_delta", "date": date},
        auth=AUTH,
        headers=HEADERS,
        timeout=300,
    )
    try:
        data = resp.json()
    except Exception:
        print(f"[ERROR] 非 JSON 响应: HTTP {resp.status_code}")
        print(resp.text[:500])
        sys.exit(1)
    if data.get("ok"):
        merged = data.get("merged") or {}
        tables = merged.get("tables") or {}
        print(f"[OK] 上传并合并成功: {data.get('path')} ({len(tables)} tables)")
    else:
        print(f"[ERROR] 上传失败: {data.get('error')}")
        sys.exit(1)


def upload_snapshot() -> None:
    path = ROOT / "outputs" / "daily_snapshot.json"
    if not path.exists():
        print(f"[ERROR] {path} 不存在")
        sys.exit(1)

    print(f"上传 snapshot ({path.stat().st_size / 1024:.0f} KB)...")
    resp = requests.post(
        BASE_URL,
        files={"file": ("daily_snapshot.json", path.read_bytes(), "application/json")},
        data={"type": "snapshot"},
        auth=AUTH,
        headers=HEADERS,
        timeout=60,
    )
    try:
        data = resp.json()
    except Exception:
        print(f"[ERROR] 非 JSON 响应: HTTP {resp.status_code}")
        print(resp.text[:500])
        sys.exit(1)
    if data.get("ok"):
        print(f"[OK] 上传成功: {data.get('path')}")
    else:
        print(f"[ERROR] 上传失败: {data.get('error')}")
        sys.exit(1)


def upload_strategy_signal_daily(date: str) -> None:
    path = ROOT / "outputs" / "strategy_signals" / f"strategy_signal_daily_{date}.json"
    if not path.exists():
        print(f"[ERROR] {path} 不存在")
        sys.exit(1)

    print(f"上传 strategy_signal_daily ({path.stat().st_size / 1024:.0f} KB)...")
    resp = requests.post(
        BASE_URL,
        files={"file": (path.name, path.read_bytes(), "application/json")},
        data={"type": "strategy_signal_daily", "date": date},
        auth=AUTH,
        headers=HEADERS,
        timeout=60,
    )
    try:
        data = resp.json()
    except Exception:
        print(f"[ERROR] 非 JSON 响应: HTTP {resp.status_code}")
        print(resp.text[:500])
        sys.exit(1)
    if data.get("ok"):
        print(f"[OK] 上传成功: {data.get('path')}")
    else:
        print(f"[ERROR] 上传失败: {data.get('error')}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="上传数据到 Hermass 服务器")
    parser.add_argument("--date", required=True)
    parser.add_argument(
        "--type",
        required=True,
        choices=["foundation", "foundation_delta", "strategy_signal_daily", "snapshot"],
    )
    args = parser.parse_args()

    if args.type == "foundation":
        upload_foundation(args.date)
    elif args.type == "foundation_delta":
        upload_foundation_delta(args.date)
    elif args.type == "strategy_signal_daily":
        upload_strategy_signal_daily(args.date)
    elif args.type == "snapshot":
        upload_snapshot()


if __name__ == "__main__":
    main()
