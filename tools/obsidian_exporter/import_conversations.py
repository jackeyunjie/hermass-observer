#!/usr/bin/env python3
"""从 conversations.db 导出对话到 Obsidian vault。

适配 Hermass 实际 schema：sessions + turns 表。
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from tools.obsidian_exporter.exporter import ObsidianExporter


def export_conversations(config: dict[str, Any]) -> dict[str, Any]:
    exporter = ObsidianExporter(config)
    db_path = Path(config["source_db"])
    if not db_path.exists():
        return {"ok": True, "exported_files": [], "note": f"db not found: {db_path}"}

    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            """
            SELECT t.role, t.message, t.intent, t.agent, t.timestamp,
                   s.user_id, t.session_id
            FROM turns t
            JOIN sessions s ON t.session_id = s.session_id
            WHERE date(t.timestamp) = ?
            ORDER BY t.timestamp
            """,
            [str(date.today())],
        ).fetchall()
    finally:
        con.close()

    if not rows:
        return {"ok": True, "exported_files": [], "note": f"no conversations today {date.today()}"}

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

    today_str = str(date.today())
    lines = [
        f"# 对话日志 — {today_str}",
        "",
        f"标签: #daily #conversation",
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
            icon = "🧑" if t["role"] == "user" else "🤖"
            intent_tag = f" `{t['intent']}`" if t["intent"] else ""
            lines.append(f"{icon} **{t['role']}**{intent_tag}")
            lines.append(f"> {t['message']}")
            lines.append("")
        lines.append("---")
        lines.append("")

    content = "\n".join(lines)
    out_path = exporter.daily_dir / f"{today_str}.md"
    exporter.write_markdown(out_path, content)

    return {"ok": True, "exported_files": [str(out_path)], "sessions": len(sessions), "turns": len(rows)}
