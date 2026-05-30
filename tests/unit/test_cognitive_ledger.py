import json
import tempfile
from pathlib import Path

import pytest
from hermass_platform.cognitive.cognitive_ledger import (
    BehaviorEvent,
    record_event,
    load_events,
    get_event_summary,
    LEDGER_DIR,
    _ledger_path,
)


class TestBehaviorEvent:

    def test_create_valid_event(self):
        e = BehaviorEvent(user_id="user_001", event_type="market_query")
        assert e.is_valid()
        assert e.user_id == "user_001"
        assert e.timestamp != ""

    def test_invalid_event_type(self):
        e = BehaviorEvent(user_id="user_001", event_type="invalid_type")
        assert not e.is_valid()

    def test_all_valid_types(self):
        for t in BehaviorEvent.VALID_TYPES:
            e = BehaviorEvent(user_id="u", event_type=t)
            assert e.is_valid()

    def test_payload_preserved(self):
        e = BehaviorEvent(
            user_id="user_001",
            event_type="market_query",
            payload={"intent": "market_phase", "message": "市场怎么样"},
        )
        d = e.__class__.__dataclass_fields__
        assert e.payload["intent"] == "market_phase"


class TestCognitiveLedger:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        import hermass_platform.cognitive.cognitive_ledger as cl
        self.orig_ledger_dir = cl.LEDGER_DIR
        cl.LEDGER_DIR = Path(self.tmpdir.name) / "cognitive"
        cl.LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        yield
        cl.LEDGER_DIR = self.orig_ledger_dir
        self.tmpdir.cleanup()

    def test_record_and_load(self):
        ok = record_event(BehaviorEvent(user_id="test_u", event_type="market_query"))
        assert ok

        events = load_events("test_u")
        assert len(events) >= 1
        assert events[0].event_type == "market_query"

    def test_record_invalid_rejected(self):
        ok = record_event(BehaviorEvent(user_id="test_u", event_type="bad_type"))
        assert not ok

    def test_multiple_events(self):
        record_event(BehaviorEvent(user_id="u2", event_type="strategy_query"))
        record_event(BehaviorEvent(user_id="u2", event_type="risk_query"))
        record_event(BehaviorEvent(user_id="u2", event_type="learn_query"))

        events = load_events("u2")
        assert len(events) == 3

    def test_limit_events(self):
        record_event(BehaviorEvent(user_id="u3", event_type="market_query"))
        record_event(BehaviorEvent(user_id="u3", event_type="strategy_query"))
        record_event(BehaviorEvent(user_id="u3", event_type="risk_query"))

        events = load_events("u3", limit=2)
        assert len(events) == 2

    def test_nonexistent_user(self):
        events = load_events("no_such_user")
        assert events == []

    def test_event_summary(self):
        for _ in range(5):
            record_event(BehaviorEvent(user_id="u4", event_type="market_query"))
        for _ in range(3):
            record_event(BehaviorEvent(user_id="u4", event_type="risk_query"))
        for _ in range(2):
            record_event(BehaviorEvent(user_id="u4", event_type="learn_query"))

        summary = get_event_summary("u4")
        assert summary["total_events"] == 10
        assert summary["event_distribution"]["market_query"] == 5
        assert summary["event_distribution"]["risk_query"] == 3
        assert summary["event_distribution"]["learn_query"] == 2

    def test_summary_empty_user(self):
        summary = get_event_summary("no_one")
        assert summary["total_events"] == 0

    def test_event_truncation_500(self):
        for i in range(600):
            record_event(BehaviorEvent(user_id="u5", event_type="learn_query"))
        events = load_events("u5", limit=600)
        assert len(events) <= 500

    def test_ledger_path_deterministic(self):
        p1 = _ledger_path("same_user")
        p2 = _ledger_path("same_user")
        assert p1 == p2

    def test_ledger_path_different_users(self):
        p1 = _ledger_path("user_a")
        p2 = _ledger_path("user_b")
        assert p1 != p2
