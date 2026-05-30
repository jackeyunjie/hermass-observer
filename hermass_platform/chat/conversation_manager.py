import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


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
    ttl_seconds: int = 1800

    def add_turn(self, role: str, message: str, intent: str = "", agent: str = ""):
        now = datetime.now(timezone.utc).isoformat()
        self.turns.append(Turn(
            role=role,
            message=message,
            intent=intent,
            agent=agent,
            timestamp=now,
        ))
        self.last_active = now

        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

        for key, value in self._extract_context(message, role, intent):
            self.context[key] = value

    def _extract_context(self, message: str, role: str, intent: str):
        items: list[tuple[str, str]] = []

        if "000" in message or "600" in message or "688" in message or "002" in message:
            import re
            codes = re.findall(r'(?<!\d)\d{6}(?!\d)', message)
            if codes:
                items.append(("last_stock_code", codes[0]))

        if intent:
            items.append(("last_intent", intent))

        return items

    def get_context_for_prompt(self) -> dict:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "turn_count": len(self.turns),
            "last_intent": self.context.get("last_intent", ""),
            "last_stock_code": self.context.get("last_stock_code", ""),
            "recent_turns": [
                {"role": t.role, "message": t.message[:200]}
                for t in self.turns[-5:]
            ],
        }

    def is_expired(self) -> bool:
        try:
            last = datetime.fromisoformat(self.last_active)
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            return elapsed > self.ttl_seconds
        except (ValueError, TypeError):
            return True


class ConversationManager:
    def __init__(self, ttl_seconds: int = 1800):
        self._sessions: dict[str, Session] = {}
        self._ttl_seconds = ttl_seconds

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
        self._gc()
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired():
            del self._sessions[session_id]
            return None
        return session

    def get_or_create(self, user_id: str, session_id: str | None = None) -> Session:
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

    def get_context(self, session_id: str) -> dict:
        session = self.get_session(session_id)
        if session is None:
            return {}
        return session.get_context_for_prompt()

    def end_session(self, session_id: str):
        self._sessions.pop(session_id, None)

    def _gc(self):
        if len(self._sessions) > 1000:
            expired = [
                sid for sid, s in self._sessions.items()
                if s.is_expired()
            ]
            for sid in expired:
                del self._sessions[sid]

    @property
    def active_sessions(self) -> int:
        self._gc()
        return len(self._sessions)


_default_conversation_manager = ConversationManager()


def get_conversation_manager() -> ConversationManager:
    return _default_conversation_manager
