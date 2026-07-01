#!/usr/bin/env python3
"""一键创建 Hermass 决策观察账本 Base 表，并把 table_id 写回配置。

Usage:
    .venv/bin/python scripts/setup_lark_base_digest_table.py --base-token bas_xxx
    .venv/bin/python scripts/setup_lark_base_digest_table.py --base-token bas_xxx --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
LARK_DIGEST_CONFIG = ROOT / "config" / "platform" / "lark_digest.yaml"

FIELDS = [
    {"type": "datetime", "name": "日期", "style": {"format": "yyyy-MM-dd"}},
    {"type": "text", "name": "标的", "style": {"type": "plain"}},
    {
        "type": "select",
        "name": "类型",
        "multiple": False,
        "options": [
            {"name": "市场", "hue": "Blue", "lightness": "Light"},
            {"name": "个股", "hue": "Green", "lightness": "Light"},
        ],
    },
    {"type": "text", "name": "Hypothesis", "style": {"type": "plain"}},
    {
        "type": "select",
        "name": "Router结论",
        "multiple": False,
        "options": [
            {"name": "observe", "hue": "Green", "lightness": "Light"},
            {"name": "watch", "hue": "Yellow", "lightness": "Light"},
            {"name": "reject", "hue": "Red", "lightness": "Light"},
        ],
    },
    {"type": "number", "name": "Router评分", "style": {"type": "plain", "precision": 4}},
    {"type": "checkbox", "name": "风险否决"},
    {
        "type": "select",
        "name": "风险标签",
        "multiple": True,
        "options": [
            {"name": "过热", "hue": "Red", "lightness": "Lighter"},
            {"name": "假突破", "hue": "Orange", "lightness": "Lighter"},
            {"name": "数据异常", "hue": "Gray", "lightness": "Lighter"},
            {"name": "ADX过高", "hue": "Carmine", "lightness": "Lighter"},
            {"name": "趋势背离", "hue": "Purple", "lightness": "Lighter"},
        ],
    },
    {"type": "number", "name": "Agent支持数", "style": {"type": "plain", "precision": 0}},
    {"type": "number", "name": "Agent反对数", "style": {"type": "plain", "precision": 0}},
    {"type": "number", "name": "future_r5", "style": {"type": "plain", "precision": 4}},
    {"type": "number", "name": "future_r20", "style": {"type": "plain", "precision": 4}},
    {"type": "text", "name": "后验结果", "style": {"type": "plain"}},
    {
        "type": "select",
        "name": "复核状态",
        "multiple": False,
        "options": [
            {"name": "pending", "hue": "Gray", "lightness": "Lighter"},
            {"name": "confirmed", "hue": "Green", "lightness": "Light"},
            {"name": "invalid", "hue": "Red", "lightness": "Light"},
        ],
    },
    {"type": "text", "name": "详情链接", "style": {"type": "url"}},
    {"type": "text", "name": "备注", "style": {"type": "plain"}},
]


def _lark_cli(args: list[str], timeout: int = 60) -> dict[str, Any]:
    result = subprocess.run(["lark-cli", *args], capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(result.stdout)
    except Exception:
        return {
            "ok": False,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }


def _load_config() -> dict[str, Any]:
    if not LARK_DIGEST_CONFIG.exists():
        return {"digest": {"enabled": False, "base_token": "", "table_id": "", "table_name": "Hermass 决策观察账本", "max_stocks_per_day": 50}}
    with open(LARK_DIGEST_CONFIG, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_config(data: dict[str, Any]) -> None:
    LARK_DIGEST_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with open(LARK_DIGEST_CONFIG, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Hermass Base digest table")
    parser.add_argument("--base-token", required=True, help="Base token (from /base/xxx URL)")
    parser.add_argument("--table-name", help="Table name override")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    cfg = _load_config()
    table_name = args.table_name or cfg.get("digest", {}).get("table_name", "Hermass 决策观察账本")

    # 1. create empty table
    create_args = ["base", "+table-create", "--base-token", args.base_token, "--name", table_name]
    if args.dry_run:
        create_args.append("--dry-run")
    resp = _lark_cli(create_args)
    print(json.dumps({"table_create": resp}, ensure_ascii=False, indent=2))
    if not resp.get("ok"):
        print("ERROR: failed to create table", file=sys.stderr)
        return 1

    table_id = resp.get("table", {}).get("table_id") or resp.get("table", {}).get("id")
    if not table_id:
        print("ERROR: no table_id in response", file=sys.stderr)
        return 1

    # 2. create fields
    for field in FIELDS:
        field_args = [
            "base", "+field-create",
            "--base-token", args.base_token,
            "--table-id", table_id,
            "--json", json.dumps(field, ensure_ascii=False),
        ]
        if args.dry_run:
            field_args.append("--dry-run")
        field_resp = _lark_cli(field_args)
        print(json.dumps({"field_create": {"name": field["name"], "response": field_resp}}, ensure_ascii=False, indent=2))
        if not field_resp.get("ok"):
            print(f"WARNING: field create failed for {field['name']}", file=sys.stderr)

    # 3. update config
    if not args.dry_run:
        cfg.setdefault("digest", {})
        cfg["digest"]["enabled"] = True
        cfg["digest"]["base_token"] = args.base_token
        cfg["digest"]["table_id"] = table_id
        cfg["digest"]["table_name"] = table_name
        _save_config(cfg)
        print(f"\n✅ 配置已更新：{LARK_DIGEST_CONFIG}")
        print(f"   base_token: {args.base_token}")
        print(f"   table_id:   {table_id}")
    else:
        print(f"\nDry-run: would write table_id={table_id} to {LARK_DIGEST_CONFIG}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
