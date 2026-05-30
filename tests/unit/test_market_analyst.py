import pytest
from hermass_platform.agents.base_agent import find_foundation_db
from hermass_platform.agents.market_analyst import (
    analyze_market_environment,
    analyze_industry_heat,
)


class TestMarketAnalyst:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.db = find_foundation_db("2026-05-20")

    def test_analyze_market_environment(self):
        if self.db is None:
            pytest.skip("无可用 Foundation DB")
        result = analyze_market_environment(
            user_id="test_user",
            foundation_db=str(self.db),
            target_date="2026-05-20",
        )
        assert result["status"] == "ok"
        assert "data" in result
        assert "summary" in result
        data = result["data"]
        assert data["total_stocks"] > 0
        assert "ef_distribution" in data
        assert data["stock_count"] > 0

    def test_analyze_market_environment_no_db(self):
        result = analyze_market_environment(
            user_id="test_user",
            foundation_db="/nonexistent.duckdb",
        )
        assert result["status"] == "error"

    def test_analyze_industry_heat_electronics(self):
        if self.db is None:
            pytest.skip("无可用 Foundation DB")
        result = analyze_industry_heat(
            user_id="test_user",
            foundation_db=str(self.db),
            target_date="2026-05-20",
            sw_l1_name="电子",
        )
        assert result["status"] == "ok"
        assert result["data"]["sw_l1"] == "电子"

    def test_analyze_industry_heat_nonexistent(self):
        if self.db is None:
            pytest.skip("无可用 Foundation DB")
        result = analyze_industry_heat(
            user_id="test_user",
            foundation_db=str(self.db),
            target_date="2026-05-20",
            sw_l1_name="不存在行业XYZ",
        )
        assert result["status"] == "ok"
        assert result["data"]["total_in_industry"] == 0

    def test_result_structure(self):
        if self.db is None:
            pytest.skip("无可用 Foundation DB")
        result = analyze_market_environment(
            user_id="test_user",
            foundation_db=str(self.db),
        )
        assert "agent_id" in result
        assert "agent_name" in result
        assert result["agent_id"] == "market_analyst"
