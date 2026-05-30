import pytest
from pathlib import Path

from hermass_platform.agents.base_agent import find_foundation_db
from hermass_platform.agents.cognitive_detective import (
    get_user_profile,
    record_user_behavior,
    get_user_summary,
)
from hermass_platform.agents.risk_guardian import (
    assess_portfolio_risk,
    get_stop_loss_reference,
)


class TestCognitiveDetectiveAgent:

    def test_get_user_profile(self):
        result = get_user_profile("profile_test_user")
        assert result["agent_id"] == "cognitive_detective"
        assert result["status"] == "ok"
        assert "data" in result

    def test_record_behavior(self):
        result = record_user_behavior("behavior_test", "market_query", {"intent": "market_phase"})
        assert result["status"] == "ok"
        assert result["data"]["recorded"]

    def test_record_invalid_behavior(self):
        result = record_user_behavior("behavior_test", "invalid_event")
        assert result["status"] == "error"

    def test_get_user_summary(self):
        record_user_behavior("sum_user", "learn_query")
        result = get_user_summary("sum_user")
        assert result["status"] == "ok"
        assert result["data"]["total_events"] >= 1

    def test_agent_result_structure(self):
        result = get_user_profile("struct_test")
        assert "agent_id" in result
        assert "agent_name" in result
        assert "status" in result
        assert "summary" in result


class TestRiskGuardian:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.db = find_foundation_db("2026-05-20")

    def test_assess_portfolio_risk(self):
        if self.db is None:
            pytest.skip("无可用 Foundation DB")
        result = assess_portfolio_risk(
            user_id="test_user",
            foundation_db=str(self.db),
            stock_codes=["000001.SZ"],
        )
        assert result["status"] == "ok"
        assert "data" in result
        assert "holdings" in result["data"]

    def test_assess_all_stocks(self):
        if self.db is None:
            pytest.skip("无可用 Foundation DB")
        result = assess_portfolio_risk(
            user_id="test_user",
            foundation_db=str(self.db),
        )
        assert result["status"] == "ok"
        assert result["data"]["total_holdings"] > 0

    def test_risk_summary_has_levels(self):
        if self.db is None:
            pytest.skip("无可用 Foundation DB")
        result = assess_portfolio_risk(
            user_id="test_user",
            foundation_db=str(self.db),
        )
        risk_sum = result["data"]["risk_summary"]
        assert "high_risk_count" in risk_sum
        assert "low_risk_count" in risk_sum

    def test_stop_loss_reference(self):
        if self.db is None:
            pytest.skip("无可用 Foundation DB")
        result = get_stop_loss_reference(
            user_id="test_user",
            stock_code="000001.SZ",
            foundation_db=str(self.db),
        )
        assert result["status"] == "ok"
        assert result["data"]["stock_code"] == "000001.SZ"

    def test_stop_loss_nonexistent(self):
        if self.db is None:
            pytest.skip("无可用 Foundation DB")
        result = get_stop_loss_reference(
            user_id="test_user",
            stock_code="999999",
            foundation_db=str(self.db),
        )
        assert result["status"] == "error"

    def test_no_db_returns_error(self):
        result = assess_portfolio_risk(
            user_id="test",
            foundation_db="/nonexistent.duckdb",
        )
        assert result["status"] == "error"
