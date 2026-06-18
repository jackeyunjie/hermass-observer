import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from hermass_platform.chat.conversation_store import ConversationStore


@dataclass
class Turn:
    role: str
    message: str
    intent: str = ""
    agent: str = ""
    timestamp: str = ""


@dataclass
class Session:
    session_id: str
    user_id: str
    created_at: str
    last_active: str
    turns: list[Turn] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    max_turns: int = 20
    ttl_seconds: int = 86400

    def add_turn(self, role: str, message: str, intent: str = "", agent: str = ""):
        now = datetime.now(timezone.utc).isoformat()
        self.turns.append(
            Turn(
                role=role,
                message=message,
                intent=intent,
                agent=agent,
                timestamp=now,
            )
        )
        self.last_active = now

        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns :]

        for key, value in self._extract_context(message, role, intent):
            self.context[key] = value

    @staticmethod
    def _extract_stock_code(value: str) -> str:
        if (
            "000" in value
            or "600" in value
            or "688" in value
            or "002" in value
        ):
            import re as _re_extract

            codes = _re_extract.findall(r"(?<!\d)\d{6}(?!\d)", value)
            if codes:
                return codes[0]
        return ""

    def _extract_context(self, message: str, role: str, intent: str):
        items: list[tuple[str, str]] = []

        code = self._extract_stock_code(message)
        if code:
            items.append(("stock_code", code))
        elif role == "assistant":
            try:
                from web.main import _chat_stock_code as _chat_stock
            except Exception:
                _chat_stock = None
            if _chat_stock is not None:
                try:
                    code = _chat_stock(
                        type("_FakeQuery", (), {
                            "message": message,
                            "stock_code": None,
                            "session_context": {},
                        })()
                    )
                except Exception:
                    code = ""
                if code:
                    items.append(("stock_code", code))

        if intent:
            items.append(("last_intent", intent))

        return items

    def get_context_for_prompt(self) -> dict:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "turn_count": len(self.turns),
            "last_intent": self.context.get("last_intent", ""),
            "last_stock_code": self.context.get("stock_code", ""),
            "recent_turns": [{"role": t.role, "message": t.message[:200]} for t in self.turns[-5:]],
        }

    def is_expired(self) -> bool:
        try:
            last = datetime.fromisoformat(self.last_active)
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            return elapsed > self.ttl_seconds
        except (ValueError, TypeError):
            return True


class ConversationManager:
    def __init__(self, ttl_seconds: int = 86400):
        self._sessions: dict[str, Session] = {}
        self._ttl_seconds = ttl_seconds
        self._store = ConversationStore()

    def create_session(self, user_id: str) -> Session:
        session_id = f"conv_{user_id}_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        session = Session(
            session_id=session_id,
            user_id=user_id,
            created_at=now,
            last_active=now,
            ttl_seconds=self._ttl_seconds,
        )
        self._sessions[session_id] = session
        self._store.save_session(session.session_id, session.user_id, session.created_at, session.last_active)
        self._gc()
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        session = self._sessions.get(session_id)
        if session is not None:
            if session.is_expired():
                del self._sessions[session_id]
                self._store.delete_session(session_id)
                return None
            return session

        data = self._store.load_session(session_id)
        if data is None:
            return None

        session = Session(
            session_id=data["session_id"],
            user_id=data["user_id"],
            created_at=data["created_at"],
            last_active=data["last_active"],
            ttl_seconds=self._ttl_seconds,
        )
        for t in data["turns"]:
            session.turns.append(Turn(**t))
            for key, value in session._extract_context(t["message"], t["role"], t["intent"]):
                session.context[key] = value

        if session.is_expired():
            self._store.delete_session(session_id)
            return None

        self._sessions[session_id] = session
        return session

    def get_recent_session_id(self, user_id: str) -> str | None:
        for session_id, session in self._sessions.items():
            if session.user_id == user_id and not session.is_expired():
                return session_id
        try:
            data = self._store.load_recent_session(user_id)
            if data:
                return data.get("session_id")
        except Exception:
            pass
        return None

    def get_or_create(self, user_id: str, session_id: str | None = None) -> Session:
        if not session_id:
            session_id = self.get_recent_session_id(user_id)
        if session_id:
            session = self.get_session(session_id)
            if session and session.user_id == user_id:
                return session
        return self.create_session(user_id)

    def add_message(
        self,
        session_id: str,
        role: str,
        message: str,
        intent: str = "",
        agent: str = "",
    ):
        session = self.get_session(session_id)
        if session is None:
            return
        session.add_turn(role, message, intent, agent)
        self._store.add_turn(session_id, role, message, intent, agent)

    def get_context(self, session_id: str) -> dict:
        session = self.get_session(session_id)
        if session is None:
            return {}
        return session.get_context_for_prompt()

    def update_context(self, session_id: str, context: dict):
        """Merge new keys into session context for cross-turn memory persistence."""
        session = self.get_session(session_id)
        if session is None:
            return
        for k, v in context.items():
            if v not in (None, '', [], {}):
                session.context[k] = v

    def end_session(self, session_id: str):
        self._sessions.pop(session_id, None)
        self._store.delete_session(session_id)

    def _gc(self):
        if len(self._sessions) > 100:
            sorted_sessions = sorted(self._sessions.items(), key=lambda item: item[1].last_active)
            to_evict = len(self._sessions) - 100
            for sid, _ in sorted_sessions[:to_evict]:
                del self._sessions[sid]

    @property
    def active_sessions(self) -> int:
        self._gc()
        return len(self._sessions)


_default_conversation_manager = ConversationManager()


def get_conversation_manager() -> ConversationManager:
    return _default_conversation_manager
