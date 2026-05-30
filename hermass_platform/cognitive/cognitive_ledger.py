import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = ROOT / "outputs" / "cognitive"
LEDGER_DIR.mkdir(parents=True, exist_ok=True)

BEHAVIOR_EVENT_VERSION = "1.0.0"


@dataclass
class BehaviorEvent:
    user_id: str
    event_type: str
    timestamp: str = ""
    payload: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    VALID_TYPES = {
        "market_query",
        "strategy_query",
        "signal_explore",
        "risk_query",
        "learn_query",
        "practice_request",
        "profile_query",
        "subscription_query",
        "stock_lookup",
        "industry_query",
    }

    def is_valid(self) -> bool:
        return self.event_type in self.VALID_TYPES


def _ledger_path(user_id: str) -> Path:
    safe_id = hashlib.sha256(user_id.encode()).hexdigest()[:16]
    return LEDGER_DIR / f"behavior_{safe_id}.json"


def record_event(event: BehaviorEvent) -> bool:
    if not event.is_valid():
        return False

    path = _ledger_path(event.user_id)

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            data = {"user_id": event.user_id, "events": [], "version": BEHAVIOR_EVENT_VERSION}
    else:
        data = {"user_id": event.user_id, "events": [], "version": BEHAVIOR_EVENT_VERSION}

    data["events"].append(asdict(event))

    if len(data["events"]) > 500:
        data["events"] = data["events"][-500:]

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def load_events(user_id: str, limit: int = 200) -> list[BehaviorEvent]:
    path = _ledger_path(user_id)
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []

    raw_events = data.get("events", [])[-limit:]
    events = []
    for e in raw_events:
        try:
            event = BehaviorEvent(
                user_id=e.get("user_id", user_id),
                event_type=e.get("event_type", ""),
                timestamp=e.get("timestamp", ""),
                payload=e.get("payload", {}),
            )
            events.append(event)
        except Exception:
            pass
    return events


def get_event_summary(user_id: str) -> dict:
    events = load_events(user_id, limit=500)
    if not events:
        return {
            "user_id": user_id,
            "total_events": 0,
            "first_event_at": "",
            "last_event_at": "",
            "event_distribution": {},
            "active_days": 0,
        }

    event_types: dict[str, int] = {}
    timestamps = []
    for e in events:
        event_types[e.event_type] = event_types.get(e.event_type, 0) + 1
        timestamps.append(e.timestamp)

    timestamps.sort()
    unique_days = len(set(ts[:10] for ts in timestamps if ts))

    return {
        "user_id": user_id,
        "total_events": len(events),
        "first_event_at": timestamps[0] if timestamps else "",
        "last_event_at": timestamps[-1] if timestamps else "",
        "event_distribution": event_types,
        "active_days": unique_days,
    }
