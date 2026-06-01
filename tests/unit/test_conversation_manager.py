import pytest
import time
from hermass_platform.chat.conversation_manager import (
    ConversationManager,
    Session,
    Turn,
    get_conversation_manager,
)


class TestSession:

    def test_create_session(self):
        s = Session(
            session_id="test_001",
            user_id="user_001",
            created_at="2026-05-24T00:00:00Z",
            last_active="2026-05-24T00:00:00Z",
            ttl_seconds=60,
        )
        assert s.session_id == "test_001"
        assert s.user_id == "user_001"
        assert len(s.turns) == 0

    def test_add_turn(self):
        s = Session(
            session_id="test_002",
            user_id="user_001",
            created_at="2026-05-24T00:00:00Z",
            last_active="2026-05-24T00:00:00Z",
        )
        s.add_turn("user", "现在市场怎么样", "market_phase", "market_analyst")
        s.add_turn("assistant", "当前市场处于趋势行进阶段", "market_phase", "market_analyst")
        assert len(s.turns) == 2
        assert s.turns[0].role == "user"
        assert s.turns[1].role == "assistant"

    def test_turn_limit(self):
        s = Session(
            session_id="test_003",
            user_id="user_001",
            created_at="2026-05-24T00:00:00Z",
            last_active="2026-05-24T00:00:00Z",
            max_turns=5,
        )
        for i in range(10):
            s.add_turn("user", f"消息{i}", f"intent{i}")
        assert len(s.turns) == 5

    def test_context_extraction_stock_code(self):
        s = Session(
            session_id="test_004",
            user_id="user_001",
            created_at="2026-05-24T00:00:00Z",
            last_active="2026-05-24T00:00:00Z",
        )
        s.add_turn("user", "帮我看看600519最近怎么样", "signal_explore")
        ctx = s.get_context_for_prompt()
        assert ctx["last_stock_code"] == "600519"
        assert ctx["last_intent"] == "signal_explore"

    def test_context_extraction_688_stock(self):
        s = Session(
            session_id="test_005",
            user_id="user_001",
            created_at="2026-05-24T00:00:00Z",
            last_active="2026-05-24T00:00:00Z",
        )
        s.add_turn("user", "688107这支怎么样")
        ctx = s.get_context_for_prompt()
        assert ctx["last_stock_code"] == "688107"

    def test_context_recent_turns(self):
        s = Session(
            session_id="test_006",
            user_id="user_001",
            created_at="2026-05-24T00:00:00Z",
            last_active="2026-05-24T00:00:00Z",
        )
        for i in range(10):
            s.add_turn("user", f"消息{i}")
        ctx = s.get_context_for_prompt()
        assert len(ctx["recent_turns"]) <= 5

    def test_is_expired(self):
        s = Session(
            session_id="test_007",
            user_id="user_001",
            created_at="2026-05-24T00:00:00Z",
            last_active="2020-01-01T00:00:00Z",
            ttl_seconds=1,
        )
        assert s.is_expired()

    def test_not_expired(self):
        s = Session(
            session_id="test_008",
            user_id="user_001",
            created_at="2026-05-24T00:00:00Z",
            last_active="2026-05-24T00:00:00Z",
            ttl_seconds=1800,
        )
        s.add_turn("user", "测试")
        assert not s.is_expired()


class TestConversationManager:

    def test_create_and_get_session(self):
        mgr = ConversationManager(ttl_seconds=3600)
        session = mgr.create_session("user_001")
        assert session is not None
        assert session.user_id == "user_001"

        retrieved = mgr.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id

    def test_get_or_create(self):
        mgr = ConversationManager(ttl_seconds=3600)
        s1 = mgr.get_or_create("user_001")
        s2 = mgr.get_or_create("user_001", s1.session_id)
        assert s1.session_id == s2.session_id

    def test_get_or_create_new_user(self):
        mgr = ConversationManager(ttl_seconds=3600)
        s1 = mgr.get_or_create("user_001")
        s2 = mgr.get_or_create("user_002")
        assert s1.session_id != s2.session_id

    def test_add_message(self):
        mgr = ConversationManager(ttl_seconds=3600)
        session = mgr.create_session("user_001")
        mgr.add_message(session.session_id, "user", "你好", "market_phase")
        mgr.add_message(session.session_id, "assistant", "你好，有什么可以帮你")
        s = mgr.get_session(session.session_id)
        assert len(s.turns) == 2

    def test_get_context(self):
        mgr = ConversationManager(ttl_seconds=3600)
        session = mgr.create_session("user_001")
        mgr.add_message(session.session_id, "user", "600519怎么样", "signal_explore")
        ctx = mgr.get_context(session.session_id)
        assert ctx["turn_count"] == 1
        assert ctx["last_stock_code"] == "600519"

    def test_assistant_answer_preserves_recent_stock_code(self):
        mgr = ConversationManager(ttl_seconds=3600)
        session = mgr.create_session("user_001")
        mgr.add_message(session.session_id, "user", "000021 怎么样", "stock_checkup")
        mgr.add_message(
            session.session_id,
            "assistant",
            "000021 当前处于观望阶段。",
            '{"scenario": "stock_checkup"}',
            "market_analyst",
        )
        ctx = mgr.get_context(session.session_id)
        assert ctx["last_stock_code"] == "000021"
        memory = mgr._sessions[session.session_id].context
        assert memory.get("stock_code") == "000021"

    def test_http_chat_followup_uses_previous_stock_code(self):
        from fastapi.testclient import TestClient
        from web.main import app, _build_memory_context

        client = TestClient(app)
        first = client.post(
            "/api/chat/query",
            json={
                "message": "000021 怎么样",
                "stock_code": "000021.SZ",
                "page_context": "stock",
                "mode": "chat",
                "use_llm": False,
            },
        )
        assert first.status_code == 200
        payload = first.json()
        sid = payload["session_id"]
        assert sid

        second = client.post(
            "/api/chat/query",
            json={"message": "它是什么行业", "mode": "chat", "session_id": sid, "use_llm": False},
        )
        assert second.status_code == 200
        followup = second.json()
        assert followup["session_id"] == sid
        assert followup["remembered_stock_code"] == "000021.SZ"

        memory = _build_memory_context(sid)
        assert "000021" in memory["recent_stock_codes"]

    def test_industry_followup_mentions_remembered_stock_industry_when_known(self):
        from pathlib import Path
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from web.main import app

        client = TestClient(app)
        industry_payload = {
            "date": "2026-06-01",
            "industry_count": 8,
            "top_industries": [
                {"industry": "电力设备"},
                {"industry": "传媒"},
            ],
        }

        fake_foundation = {
            "000021.SZ": "电子",
            "600519.SH": "食品饮料",
        }

        def fake_industry(*args, **kwargs):
            return industry_payload

        def fake_foundation_db(*args, **kwargs):
            return Path("fake.duckdb")

        def fake_duck_connect(*args, **kwargs):
            class FakeRow:
                def fetchone(self_inner):
                    return ("电子",)
                def execute(self_inner, *a, **k):
                    return self_inner
                def close(self_inner):
                    return None
            return FakeRow()

        with patch("web.main._industry_rotation_data", fake_industry),              patch("web.main.find_foundation_db", fake_foundation_db),              patch("duckdb.connect", fake_duck_connect):
            first = client.post(
                "/api/chat/query",
                json={
                    "message": "000021 怎么样",
                    "stock_code": "000021.SZ",
                    "page_context": "stock",
                    "mode": "chat",
                    "use_llm": False,
                },
            )
            assert first.status_code == 200
            sid = first.json()["session_id"]

            second = client.post(
                "/api/chat/query",
                json={"message": "它是什么行业", "mode": "chat", "session_id": sid, "use_llm": False},
            )
            assert second.status_code == 200
            payload = second.json()
            assert payload["session_id"] == sid
            assert payload["remembered_stock_code"] == "000021.SZ"
            assert "000021.SZ" in payload["answer"]
            assert "电子" in payload["answer"]

    def test_end_session(self):
        mgr = ConversationManager(ttl_seconds=3600)
        session = mgr.create_session("user_001")
        mgr.end_session(session.session_id)
        assert mgr.get_session(session.session_id) is None

    def test_session_expiry(self):
        mgr = ConversationManager(ttl_seconds=0)
        session = mgr.create_session("user_001")
        import time
        time.sleep(0.1)
        assert mgr.get_session(session.session_id) is None

    def test_active_sessions_count(self):
        mgr = ConversationManager(ttl_seconds=3600)
        assert mgr.active_sessions == 0
        s1 = mgr.create_session("user_001")
        s2 = mgr.create_session("user_002")
        assert mgr.active_sessions == 2
        mgr.end_session(s1.session_id)
        assert mgr.active_sessions == 1
        mgr.end_session(s2.session_id)

    def test_global_manager(self):
        mgr = get_conversation_manager()
        assert isinstance(mgr, ConversationManager)

    def test_add_message_nonexistent_session(self):
        mgr = ConversationManager(ttl_seconds=3600)
        mgr.add_message("no such session", "user", "hello")
