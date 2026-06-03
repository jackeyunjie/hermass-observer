#!/usr/bin/env python3
"""通用 Obsidian 导出核心：对话/文档 -> vault。"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


class ObsidianExporter:
    def __init__(self, config: dict[str, Any]) -> None:
        self.vault = Path(config["vault"]).resolve()
        self.daily_dir = self.vault / config.get("daily_subdir", "daily")
        self.archive_dir = self.vault / config.get("archive_subdir", "archive")
        self.preserve_links = bool(config.get("preserve_links", True))
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def write_markdown(self, path: Path, content: str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def archive(self, src: Path, name: str) -> Path | None:
        if not src.exists():
            return None
        dest = self.archive_dir / f"{name}"
        shutil.move(str(src), str(dest))
        return dest
