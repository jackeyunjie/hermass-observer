#!/usr/bin/env python3
"""项目文档增量同步到 Obsidian vault。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.obsidian_exporter.exporter import ObsidianExporter

# 项目根目录（tools/obsidian_exporter 的上两级）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def sync_markdown_docs(config: dict[str, Any]) -> dict[str, Any]:
    exporter = ObsidianExporter(config)
    pattern = config.get("markdown_glob", "*.md")
    imported = []

    for path in _PROJECT_ROOT.glob(pattern):
        if path.is_file() and path.suffix.lower() == ".md":
            # 跳过 vault 自身目录和隐藏目录
            vault_dir = Path(config["vault"]).resolve()
            if vault_dir in path.resolve().parents or path.resolve() == vault_dir:
                continue
            if ".git" in path.parts:
                continue

            dest = exporter.daily_dir / f"{path.stem}.md"
            exporter.write_markdown(dest, path.read_text(encoding="utf-8"))
            imported.append(str(dest))

    return {"ok": True, "imported_files": imported, "count": len(imported)}
