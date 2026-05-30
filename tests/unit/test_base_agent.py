from pathlib import Path

import pytest
from hermass_platform.agents.base_agent import (
    AgentContext,
    AgentResult,
    find_foundation_db,
    find_signal_db,
)


class TestAgentContext:

    def test_default_fields(self):
        ctx = AgentContext(
            agent_id="test_agent",
            agent_name="测试Agent",
            user_id="user_001",
        )
        assert ctx.agent_id == "test_agent"
        assert ctx.generated_at != ""

    def test_to_dict(self):
        ctx = AgentContext(
            agent_id="test_agent",
            agent_name="测试",
            user_id="user_001",
            session_id="sess_001",
            target_date="2026-05-24",
        )
        d = ctx.to_dict()
        assert d["agent_id"] == "test_agent"
        assert d["user_id"] == "user_001"
        assert d["session_id"] == "sess_001"
        assert "generated_at" in d


class TestAgentResult:

    def test_default_status_ok(self):
        r = AgentResult(
            agent_id="test",
            agent_name="测试",
            status="ok",
        )
        assert r.status == "ok"
        assert r.errors == []
        assert r.generated_at != ""

    def test_error_result(self):
        r = AgentResult(
            agent_id="test",
            agent_name="测试",
            status="error",
            errors=["数据源不可用"],
        )
        assert r.status == "error"
        assert len(r.errors) == 1

    def test_to_dict(self):
        r = AgentResult(
            agent_id="test",
            agent_name="测试",
            status="ok",
            data={"ef2_count": 100},
            summary="测试摘要",
        )
        d = r.to_dict()
        assert d["status"] == "ok"
        assert d["data"]["ef2_count"] == 100


class TestFindFoundationDB:

    def test_foundation_db_exists(self):
        db = find_foundation_db("2026-05-20")
        if db is None:
            pytest.skip("无可用 Foundation DB")
        assert db.exists()
        assert db.suffix == ".duckdb"

    def test_future_date_returns_none(self):
        db = find_foundation_db("2099-12-31")
        assert db is None


class TestFindSignalDB:

    def test_signal_db_exists(self):
        db = find_signal_db()
        if db is None:
            pytest.skip("无可用 signal DB")
        assert db.exists()
