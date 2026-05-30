import pytest
from hermass_platform.agents.base_agent import find_foundation_db, find_signal_db
from hermass_platform.agents.strategy_advisor import (
    analyze_strategy_fit,
    explore_top_signals,
)


class TestStrategyAdvisor:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.foundation_db = find_foundation_db("2026-05-20")
        self.signal_db = find_signal_db()

    def test_analyze_strategy_fit(self):
        if self.foundation_db is None:
            pytest.skip("无可用 Foundation DB")
        result = analyze_strategy_fit(
            user_id="test_user",
            foundation_db=str(self.foundation_db),
            signal_db=str(self.signal_db) if self.signal_db else "",
        )
        assert result["status"] == "ok"
        assert "strategies" in result["data"]
        assert "summary" in result

    def test_analyze_specific_strategy(self):
        if self.foundation_db is None:
            pytest.skip("无可用 Foundation DB")
        result = analyze_strategy_fit(
            user_id="test_user",
            foundation_db=str(self.foundation_db),
            signal_db=str(self.signal_db) if self.signal_db else "",
            strategy_id="vcp",
        )
        assert result["status"] == "ok"

    def test_explore_top_signals(self):
        if self.foundation_db is None:
            pytest.skip("无可用 Foundation DB")
        result = explore_top_signals(
            user_id="test_user",
            foundation_db=str(self.foundation_db),
            signal_db=str(self.signal_db) if self.signal_db else "",
            top_n=5,
        )
        assert result["status"] == "ok"
        assert "top_signals" in result["data"]

    def test_explore_by_strategy(self):
        if self.foundation_db is None:
            pytest.skip("无可用 Foundation DB")
        result = explore_top_signals(
            user_id="test_user",
            foundation_db=str(self.foundation_db),
            signal_db=str(self.signal_db) if self.signal_db else "",
            strategy_id="ma2560",
            top_n=3,
        )
        assert result["status"] == "ok"

    def test_no_db_returns_error(self):
        result = analyze_strategy_fit(
            user_id="test_user",
            foundation_db="/nonexistent.duckdb",
        )
        assert result["status"] == "error"

    def test_result_structure(self):
        if self.foundation_db is None:
            pytest.skip("无可用 Foundation DB")
        result = explore_top_signals(
            user_id="test_user",
            foundation_db=str(self.foundation_db),
            signal_db=str(self.signal_db) if self.signal_db else "",
            top_n=3,
        )
        assert "agent_id" in result
        assert result["agent_id"] == "strategy_advisor"
