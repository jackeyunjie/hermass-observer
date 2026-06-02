#!/usr/bin/env python3
"""本地数据上传到服务器（替代 SSH rsync）。

用法：
  python3 scripts/upload_output_to_server.py --date 20260601 --type foundation
  python3 scripts/upload_output_to_server.py --date 20260601 --type snapshot
  python3 scripts/upload_output_to_server.py --date 20260601 --type state_ef

需要：服务器已部署 /api/admin/upload-data 端点
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("HERMASS_UPLOAD_URL", "http://console.supertrader.world/api/admin/upload-data")
AUTH_USER = os.environ.get("HERMASS_UPLOAD_USER", "hermass-test")
AUTH_PASS = os.environ.get("HERMASS_UPLOAD_PASS", "Hermass2026!Lab")
AUTH = (AUTH_USER, AUTH_PASS) if AUTH_USER and AUTH_PASS else None

CHUNK_SIZE = 50 * 1024 * 1024  # 50MB 分块


def normalize_date(date: str) -> str:
    return f"{date[:4]}-{date[4:6]}-{date[6:]}" if len(date) == 8 and date.isdigit() else date


def compact_date(date: str) -> str:
    return normalize_date(date).replace("-", "")


def _check_response(resp: requests.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        print(f"[ERROR] 非 JSON 响应: HTTP {resp.status_code}")
        print(resp.text[:500])
        sys.exit(1)


def _post_files(files, data, timeout=300):
    resp = requests.post(BASE_URL, files=files, data=data, auth=AUTH, timeout=timeout)
    return _check_response(resp)


def upload_foundation(date: str) -> None:
    db_path = ROOT / "outputs" / f"p116_foundation_{date}" / "p116_foundation.duckdb"
    if not db_path.exists():
        print(f"[ERROR] {db_path} 不存在")
        sys.exit(1)

    size_mb = db_path.stat().st_size / 1024 / 1024
    print(f"分块上传 Foundation DB ({size_mb:.0f} MB)...")

    # 压缩到临时文件
    gz_path = db_path.with_suffix(".duckdb.gz")
    if not gz_path.exists() or gz_path.stat().st_mtime < db_path.stat().st_mtime:
        print("  压缩中...")
        with open(db_path, "rb") as src, open(gz_path, "wb") as dst:
            dst.write(gzip.compress(src.read(), compresslevel=6))

    gz_size = gz_path.stat().st_size
    gz_size_mb = gz_size / 1024 / 1024
    print(f"  压缩后 {gz_size_mb:.0f} MB")

    total_chunks = math.ceil(gz_size / CHUNK_SIZE)
    print(f"  总分块: {total_chunks}")

    upload_id = hashlib.sha256(f"{date}_{gz_size}".encode()).hexdigest()[:16]

    for i in range(total_chunks):
        offset = i * CHUNK_SIZE
        end = min(offset + CHUNK_SIZE, gz_size)
        chunk_len = end - offset

        with open(gz_path, "rb") as f:
            f.seek(offset)
            chunk_data = f.read(chunk_len)

        resp = _post_files(
            files={"file": (f"p116_foundation.duckdb.gz.chunk{i}", chunk_data, "application/octet-stream")},
            data={
                "type": "foundation_chunk",
                "date": date,
                "upload_id": upload_id,
                "chunk_index": str(i),
                "total_chunks": str(total_chunks),
                "chunk_hash": hashlib.sha256(chunk_data).hexdigest(),
            },
            timeout=120,
        )
        if not resp.get("ok"):
            print(f"[ERROR] 分块 {i+1}/{total_chunks} 上传失败: {resp.get('error')}")
            sys.exit(1)
        print(f"  分块 {i+1}/{total_chunks} OK")

    # 通知服务器重组
    resp = requests.post(
        BASE_URL,
        data={
            "type": "foundation_merge",
            "date": date,
            "upload_id": upload_id,
            "total_chunks": str(total_chunks),
        },
        auth=AUTH,
        timeout=300,
    )
    data = _check_response(resp)
    if data.get("ok"):
        print(f"[OK] 上传并合并成功: {data.get('path')} ({data.get('size') / 1024 / 1024:.0f} MB)")
    else:
        print(f"[ERROR] 合并失败: {data.get('error')}")
        sys.exit(1)


def upload_snapshot() -> None:
    path = ROOT / "outputs" / "daily_snapshot.json"
    if not path.exists():
        print(f"[ERROR] {path} 不存在")
        sys.exit(1)

    print(f"上传 snapshot ({path.stat().st_size / 1024:.0f} KB)...")
    data = _post_files(
        files={"file": ("daily_snapshot.json", path.read_bytes(), "application/json")},
        data={"type": "snapshot"},
        timeout=60,
    )
    if data.get("ok"):
        print(f"[OK] 上传成功: {data.get('path')}")
    else:
        print(f"[ERROR] 上传失败: {data.get('error')}")
        sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="上传数据到 Hermass 服务器")
    parser.add_argument("--date", required=True)
    parser.add_argument("--type", required=True, choices=["foundation", "snapshot"])
    args = parser.parse_args()

    if args.type == "foundation":
        upload_foundation(args.date)
    elif args.type == "snapshot":
        upload_snapshot()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
