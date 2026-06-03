#!/usr/bin/env python3
"""conversations.db → Obsidian Markdown 导出

将 outputs/conversations.db 中的 turns 表导出为 Markdown 日记文件，
按日期分组，每条对话为一级段落，包含 timestamp 和 session_id。

产出：data/research/conversations/daily/YYYY-MM-DD.md
      data/research/conversations/daily/_index.md（总索引）

用法：
  python3 scripts/export_conversations_to_md.py
  python3 scripts/export_conversations_to_md.py --date 2026-06-01
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "outputs" / "conversations.db"
OUT_DIR = ROOT / "data" / "research" / "conversations" / "daily"


def export_date(db_path: Path, target_date: str) -> str:
    """导出指定日期的对话到 Markdown 文件。返回生成的文件路径。"""
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            """
            SELECT t.role, t.message, t.intent, t.agent, t.timestamp, s.user_id, t.session_id
            FROM turns t
            JOIN sessions s ON t.session_id = s.session_id
            WHERE date(t.timestamp) = ?
            ORDER BY t.timestamp
            """,
            [target_date],
        ).fetchall()
    finally:
        con.close()

    if not rows:
        return ""

    # 按 session 分组
    sessions: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        sessions[r[6]].append({
            "role": r[0],
            "message": r[1][:500],
            "intent": r[2],
            "agent": r[3],
            "timestamp": r[4],
            "user_id": r[5],
        })

    lines = [
        f"# 对话日志 — {target_date}",
        "",
        f"类型: #daily #conversation",
        f"日期: [[{target_date}]]",
        "",
        "---",
        "",
    ]

    for sid, turns in sessions.items():
        user = turns[0]["user_id"] if turns else "unknown"
        start_time = turns[0]["timestamp"][:19] if turns else ""
        lines.append(f"## 会话 {sid[:12]}…")
        lines.append(f"用户: {user} · 开始: {start_time} · 轮数: {len(turns)}")
        lines.append("")

        for t in turns:
            role_icon = "🧑" if t["role"] == "user" else "🤖"
            intent_tag = f" `{t['intent']}`" if t["intent"] else ""
            lines.append(f"{role_icon} **{t['role']}**{intent_tag}")
            lines.append(f"> {t['message']}")
            lines.append("")

        lines.append("---")
        lines.append("")

    content = "\n".join(lines)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{target_date}.md"
    out_path.write_text(content, encoding="utf-8")

    return str(out_path)


def build_index(dates: list[str]) -> None:
    """生成 daily/ 目录的时间索引导航。"""
    lines = [
        "# 对话日志索引",
        "",
        f"共 {len(dates)} 天有对话记录",
        "",
        "| 日期 | 文件 |",
        "|------|------|",
    ]
    for d in sorted(dates, reverse=True):
        lines.append(f"| {d} | [[daily/{d}]] |")

    lines.extend([
        "",
        "---",
        "",
        f"> 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 源: `outputs/conversations.db`",
        f"> 脚本: `scripts/export_conversations_to_md.py`",
    ])

    index_path = OUT_DIR / "_index.md"
    index_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 conversation.db → Obsidian Markdown")
    parser.add_argument("--date", help="指定日期（YYYY-MM-DD），不指定则导出全部")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"[SKIP] {DB_PATH} 不存在，跳过导出")
        return 0

    if args.date:
        path = export_date(DB_PATH, args.date)
        if path:
            print(f"[OK] {path}")
        else:
            print(f"[SKIP] {args.date} 无对话记录")
        return 0

    # 导出全部
    con = sqlite3.connect(str(DB_PATH))
    try:
        rows = con.execute(
            "SELECT DISTINCT date(timestamp) FROM turns ORDER BY date(timestamp)"
        ).fetchall()
    finally:
        con.close()

    dates = [r[0] for r in rows]
    if not dates:
        print("[SKIP] 无对话记录")
        return 0

    for d in dates:
        path = export_date(DB_PATH, d)
        if path:
            print(f"[OK] {path}")

    build_index(dates)
    print(f"[OK] daily/_index.md（{len(dates)} 天）")

    # 在 00-README.md 中不写入链接引用——避免与 git 管理冲突
    # Obsidian 会自动识别 daily/ 目录下的 Markdown 文件

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
