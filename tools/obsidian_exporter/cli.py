#!/usr/bin/env python3
"""通用 Obsidian Vault CLI：支持一次执行、定时执行。"""
from __future__ import annotations

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中，使绝对包导入 from tools.xxx 生效
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import argparse
import json
from typing import Any

from tools.obsidian_exporter.exporter import ObsidianExporter
from tools.obsidian_exporter.import_conversations import export_conversations
from tools.obsidian_exporter.sync_docs import sync_markdown_docs

DEFAULT_CONFIG = {
    "vault": "/Users/lv111101/Documents/hermass-observer-product/data/research/conversations",
    "source_db": "/Users/lv111101/Documents/hermass-observer-product/outputs/conversations.db",
    "daily_subdir": "daily",
    "archive_subdir": "archive",
    "markdown_glob": "**/*.md",
    "frontmatter": True,
    "generate_index": True,
    "incremental": True,
    "preserve_links": True,
}


def load_config(path: str | None) -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if path:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            cfg.update(yaml.safe_load(f) or {})
    return cfg


def cmd_export(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    result = export_conversations(cfg)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_sync_docs(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    result = sync_markdown_docs(cfg)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    ObsidianExporter(cfg)
    print(json.dumps({"ok": True, "vault": cfg["vault"]}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="通用 Obsidian Vault 同步器")
    parser.add_argument("--config", help="YAML 配置路径")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="初始化 vault")
    sub.add_parser("export", help="导出对话到 vault")
    sub.add_parser("sync-docs", help="同步项目文档到 vault")
    args = parser.parse_args()
    if args.command == "init":
        return cmd_init(args)
    if args.command == "export":
        return cmd_export(args)
    if args.command == "sync-docs":
        return cmd_sync_docs(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
