#!/usr/bin/env python3
"""本地数据上传到服务器（替代 SSH rsync）。

用法：
  python3 scripts/upload_output_to_server.py --date 20260601 --type foundation
  python3 scripts/upload_output_to_server.py --date 20260601 --type snapshot

需要：服务器已部署 /api/admin/upload-data 端点
"""

from __future__ import annotations

import argparse
import gzip
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://console.supertrader.world/api/admin/upload-data"
AUTH = ("hermass-test", "Hermass2026!Lab")


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
        timeout=300,
    )
    data = resp.json()
    if data.get("ok"):
        print(f"[OK] 上传成功: {data.get('path')} ({data.get('size') / 1024 / 1024:.0f} MB)")
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
        timeout=60,
    )
    data = resp.json()
    if data.get("ok"):
        print(f"[OK] 上传成功: {data.get('path')}")
    else:
        print(f"[ERROR] 上传失败: {data.get('error')}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="上传数据到 Hermass 服务器")
    parser.add_argument("--date", required=True)
    parser.add_argument("--type", required=True, choices=["foundation", "snapshot"])
    args = parser.parse_args()

    if args.type == "foundation":
        upload_foundation(args.date)
    elif args.type == "snapshot":
        upload_snapshot()


if __name__ == "__main__":
    main()
