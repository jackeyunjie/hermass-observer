from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class AgentContext:
    agent_id: str
    agent_name: str
    user_id: str
    session_id: str = ""
    target_date: str = ""
    foundation_db: str = ""
    signal_db: str = ""
    generated_at: str = ""

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "target_date": self.target_date,
            "generated_at": self.generated_at,
        }


@dataclass
class AgentResult:
    agent_id: str
    agent_name: str
    status: str
    data: dict = field(default_factory=dict)
    summary: str = ""
    errors: list[str] = field(default_factory=list)
    generated_at: str = ""

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "status": self.status,
            "data": self.data,
            "summary": self.summary,
            "errors": self.errors,
            "generated_at": self.generated_at,
        }


def find_foundation_db(target_date: str = "") -> Optional[Path]:
    candidates = sorted(
        ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"),
        reverse=True,
    )
    if not target_date:
        for c in candidates:
            if c.exists() and c.stat().st_size > 0:
                return c
        return None

    import duckdb

    best_path: Optional[Path] = None
    best_date = ""
    fallback_path: Optional[Path] = None
    fallback_date = ""

    for c in candidates:
        if not c.exists() or c.stat().st_size <= 0:
            continue
        try:
            con = duckdb.connect(str(c), read_only=True)
            latest = con.execute(
                "SELECT MAX(state_date) FROM d1_perspective_state"
            ).fetchone()[0]
        except Exception:
            latest = None
        finally:
            try:
                con.close()
            except Exception:
                pass
        if not latest:
            continue
        latest_str = str(latest)
        if latest_str <= target_date and latest_str > best_date:
            best_date = latest_str
            best_path = c
        if latest_str > fallback_date:
            fallback_date = latest_str
            fallback_path = c

    if best_path:
        return best_path
    if fallback_path:
        return fallback_path
    return None


def find_signal_db() -> Optional[Path]:
    candidates = sorted(
        ROOT.glob("outputs/strategy_signals/strategy_signals.duckdb"),
    )
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            return c
    return None
