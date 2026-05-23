"""Shared DeepSeek prompt context for Hermass Observer scripts."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTEXT_PATH = ROOT / "config" / "deepseek_context.md"


def load_deepseek_context(path: Path = DEFAULT_CONTEXT_PATH) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def with_deepseek_context(system_prompt: str) -> str:
    context = load_deepseek_context()
    if not context:
        return system_prompt
    return f"{context}\n\n---\n\n{system_prompt.strip()}"
