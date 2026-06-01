"""SQLite-backed persistent store for conversation sessions.

Uses Python stdlib sqlite3. No ORM, no external dependencies.
"""

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / "outputs" / "conversations.db"


class ConversationStore:
    """Persistent conversation storage with SQLite backend."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_active TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                intent TEXT DEFAULT '',
                agent TEXT DEFAULT '',
                metadata TEXT DEFAULT '',
                timestamp TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)
        try:
            conn.execute("ALTER TABLE turns ADD COLUMN metadata TEXT DEFAULT ''")
        except Exception:
            pass
        conn.commit()

    def save_session(self, session_id: str, user_id: str, created_at: str, last_active: str) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, user_id, created_at, last_active) VALUES (?, ?, ?, ?)",
            (session_id, user_id, created_at, last_active),
        )
        conn.commit()

    def load_session(self, session_id: str, max_turns: int = 20) -> Optional[dict]:
        """Load session from SQLite. Returns a plain dict with turns list."""
        conn = self._conn()
        row = conn.execute(
            "SELECT session_id, user_id, created_at, last_active FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None

        turn_rows = conn.execute(
            "SELECT role, message, intent, agent, timestamp FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, max_turns),
        ).fetchall()

        turns = [
            {"role": t[0], "message": t[1], "intent": t[2], "agent": t[3], "timestamp": t[4]}
            for t in reversed(turn_rows)
        ]

        return {
            "session_id": row[0],
            "user_id": row[1],
            "created_at": row[2],
            "last_active": row[3],
            "turns": turns,
        }

    def add_turn(self, session_id: str, role: str, message: str, intent: str, agent: str) -> None:
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO turns (session_id, role, message, intent, agent, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, role, message, intent, agent, now),
        )
        conn.execute(
            "UPDATE sessions SET last_active = ? WHERE session_id = ?",
            (now, session_id),
        )
        conn.commit()

    def delete_session(self, session_id: str) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
