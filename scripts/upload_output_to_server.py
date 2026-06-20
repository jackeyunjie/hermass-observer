#!/usr/bin/env python3
"""本地数据上传到服务器（替代 SSH rsync）。

用法：
  python3 scripts/upload_output_to_server.py --date 20260601 --type foundation
  python3 scripts/upload_output_to_server.py --date 20260601 --type foundation_delta
  python3 scripts/upload_output_to_server.py --date 20260601 --type snapshot
  python3 scripts/upload_output_to_server.py --date 20260601 --type market_assets_state

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

WEBSITE_UPLOAD_SOURCES = {
    "strategy_signal_daily": (ROOT / "outputs" / "strategy_signals", "strategy_signal_daily_{ymd}.json", "application/json"),
    "state_ef": (ROOT / "outputs" / "state_cache", "state_ef_{ymd}.json", "application/json"),
    "state_duration": (ROOT / "outputs" / "state_cache", "state_duration_{ymd}.json", "application/json"),
    "sr_boundary": (ROOT / "outputs" / "state_cache", "sr_boundary_{ymd}.json", "application/json"),
    "market_phase": (ROOT / "outputs" / "market_phase", "market_phase_{ymd}.json", "application/json"),
    "market_assets_state": (ROOT / "outputs" / "market_assets_state", "market_assets_state_{ymd}.json", "application/json"),
    "unified_view": (ROOT / "outputs" / "unified_view", "unified_daily_snapshot_{date}.csv", "text/csv"),
    "forward_observation": (ROOT / "outputs" / "forward_observation", "forward_observation_{ymd}.json", "application/json"),
    "macro_chain_prior": (ROOT / "outputs" / "macro_chain_prior", "macro_chain_prior_{ymd}.json", "application/json"),
    "industry_rotation": (ROOT / "outputs" / "industry_rotation", "industry_rotation_{ymd}.json", "application/json"),
    "industry_chain": (ROOT / "outputs" / "industry_chain", "industry_chain_evidence.duckdb", "application/octet-stream"),
}


def normalize_date(date: str) -> str:
    if len(date) == 8 and date.isdigit():
        return f"{date[:4]}-{date[4:6]}-{date[6:]}"
    return date


def compact_date(date: str) -> str:
    return normalize_date(date).replace("-", "")


def upload_file(path: Path, upload_type: str, date: str, content_type: str, timeout: int = 60) -> dict:
    if not path.exists():
        print(f"[ERROR] {path} 不存在")
        sys.exit(1)
    print(f"上传 {upload_type} ({path.stat().st_size / 1024:.1f} KB)...")
    resp = requests.post(
        BASE_URL,
        files={"file": (path.name, path.read_bytes(), content_type)},
        data={"type": upload_type, "date": compact_date(date)},
        auth=AUTH,
        headers=HEADERS,
        timeout=timeout,
    )
    try:
        data = resp.json()
    except Exception:
        print(f"[ERROR] 非 JSON 响应: HTTP {resp.status_code}")
        print(resp.text[:500])
        sys.exit(1)
    if not data.get("ok"):
        print(f"[ERROR] 上传失败: {data.get('error')}")
        sys.exit(1)
    print(f"[OK] 上传成功: {data.get('path')}")
    return data


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
    upload_file(path, "snapshot", "", "application/json")


def upload_website_output(date: str, upload_type: str) -> None:
    source = WEBSITE_UPLOAD_SOURCES.get(upload_type)
    if not source:
        print(f"[ERROR] 不支持的网站产物类型: {upload_type}")
        sys.exit(1)
    base_dir, filename_template, content_type = source
    normalized = normalize_date(date)
    ymd = compact_date(date)
    path = base_dir / filename_template.format(date=normalized, ymd=ymd)
    upload_file(path, upload_type, date, content_type)


def main() -> None:
    parser = argparse.ArgumentParser(description="上传数据到 Hermass 服务器")
    parser.add_argument("--date", required=True)
    parser.add_argument(
        "--type",
        required=True,
        choices=["foundation", "foundation_delta", "snapshot", *WEBSITE_UPLOAD_SOURCES.keys()],
    )
    args = parser.parse_args()

    if args.type == "foundation":
        upload_foundation(args.date)
    elif args.type == "foundation_delta":
        upload_foundation_delta(args.date)
    elif args.type == "snapshot":
        upload_snapshot()
    elif args.type in WEBSITE_UPLOAD_SOURCES:
        upload_website_output(args.date, args.type)


if __name__ == "__main__":
    main()
