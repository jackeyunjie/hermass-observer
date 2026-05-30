import tempfile
from pathlib import Path

import pytest

from hermass_platform.monetization.tier_gate import (
    get_tier_definition,
    get_tier_list,
    get_feature_list,
    get_limits,
    get_upgrade_prompt,
    is_feature_allowed,
    get_additional_products,
    get_beta_default_tier,
)
from hermass_platform.monetization.subscription_manager import (
    get_subscription,
    set_tier,
    check_daily_usage,
    record_usage,
    can_access,
)


class TestTierGate:

    def test_get_tier_definition(self):
        td = get_tier_definition("free")
        assert td["name"] == "免费版"
        assert td["price"] == 0

    def test_basic_tier(self):
        td = get_tier_definition("basic")
        assert td["name"] == "基础会员"
        assert td["price"] == 99

    def test_premium_tier(self):
        td = get_tier_definition("premium")
        assert td["name"] == "高级会员"

    def test_unknown_tier_falls_back_to_free(self):
        td = get_tier_definition("nonexistent")
        assert td["name"] == "免费版"

    def test_tier_list(self):
        tiers = get_tier_list()
        assert len(tiers) == 3
        tier_ids = {t["tier"] for t in tiers}
        assert tier_ids == {"free", "basic", "premium"}

    def test_feature_list(self):
        free_features = get_feature_list("free")
        assert len(free_features) > 0
        basic_features = get_feature_list("basic")
        assert len(basic_features) > len(free_features)

    def test_limits(self):
        free_limits = get_limits("free")
        assert free_limits["daily_queries"] == 3
        basic_limits = get_limits("basic")
        assert basic_limits["daily_queries"] == -1

    def test_feature_allowed(self):
        assert not is_feature_allowed("free", "cognitive_profile")
        assert is_feature_allowed("basic", "cognitive_profile")
        assert is_feature_allowed("premium", "cognitive_profile")

    def test_upgrade_prompt(self):
        prompt = get_upgrade_prompt("free")
        assert "¥99" in prompt or "升级" in prompt or "解锁" in prompt

    def test_additional_products(self):
        products = get_additional_products()
        assert len(products) >= 2

    def test_beta_default_tier(self):
        tier = get_beta_default_tier()
        assert tier == "basic"


class TestSubscriptionManager:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        import hermass_platform.monetization.subscription_manager as sm
        self.orig_sub_dir = sm.SUB_DIR
        sm.SUB_DIR = Path(self.tmpdir.name) / "subscription"
        sm.SUB_DIR.mkdir(parents=True, exist_ok=True)
        yield
        sm.SUB_DIR = self.orig_sub_dir
        self.tmpdir.cleanup()

    def test_new_user_gets_beta_tier(self):
        sub = get_subscription("new_user_001")
        assert sub["tier"] == "basic"
        assert sub["status"] == "active"
        assert sub["source"] == "beta_internal"

    def test_set_tier(self):
        sub = set_tier("user_A", "premium")
        assert sub["tier"] == "premium"
        assert sub["status"] == "active"

    def test_tier_persistence(self):
        set_tier("user_B", "free", source="test")
        sub = get_subscription("user_B")
        assert sub["tier"] == "free"
        assert sub["source"] == "test"

    def test_daily_usage_default(self):
        sub = get_subscription("user_C")
        usage = check_daily_usage(sub)
        assert usage["used"] == 0
        assert usage["can_query"] is True

    def test_daily_usage_free_limit(self):
        sub = {"user_id": "test", "tier": "free", "daily_usage": {}}
        usage = check_daily_usage(sub)
        assert usage["limit"] == 3
        assert usage["remaining"] == 3

    def test_daily_usage_basic_unlimited(self):
        sub = {"user_id": "test", "tier": "basic", "daily_usage": {}}
        usage = check_daily_usage(sub)
        assert usage["limit"] is None
        assert usage["can_query"] is True

    def test_record_usage(self):
        usage = record_usage("user_D", "market_query")
        assert usage["used"] >= 1
        usage2 = record_usage("user_D", "strategy_query")
        assert usage2["used"] >= 2

    def test_free_tier_exhausted(self):
        set_tier("user_E", "free")
        for _ in range(3):
            record_usage("user_E", "query")
        usage = check_daily_usage(get_subscription("user_E"))
        assert not usage["can_query"]
        assert usage["remaining"] == 0

    def test_can_access_free_feature(self):
        ok, msg = can_access("user_F", "market_query")
        assert ok or "不支持" in msg

    def test_can_access_blocked_feature(self):
        set_tier("user_G", "free")
        ok, msg = can_access("user_G", "cognitive_profile")
        assert not ok
        assert "不支持" in msg

    def test_exhausted_after_limit(self):
        set_tier("user_H", "free")
        for _ in range(10):
            record_usage("user_H", "query")
        ok, msg = can_access("user_H", "query")
        assert not ok

    def test_subscription_idempotent(self):
        set_tier("user_I", "basic")
        sub1 = get_subscription("user_I")
        sub2 = get_subscription("user_I")
        assert sub1["tier"] == sub2["tier"]


class TestMonetizationButlerAgent:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        import hermass_platform.monetization.subscription_manager as sm
        self.orig_sub_dir = sm.SUB_DIR
        sm.SUB_DIR = Path(self.tmpdir.name) / "subscription"
        sm.SUB_DIR.mkdir(parents=True, exist_ok=True)
        yield
        sm.SUB_DIR = self.orig_sub_dir
        self.tmpdir.cleanup()

    def test_query_subscription_status(self):
        from hermass_platform.agents.monetization_butler import query_subscription_status
        result = query_subscription_status("mz_user")
        assert result["status"] == "ok"
        assert result["data"]["tier"] == "basic"
        assert "daily_usage" in result["data"]

    def test_query_tier_comparison(self):
        from hermass_platform.agents.monetization_butler import query_tier_comparison
        result = query_tier_comparison()
        assert result["status"] == "ok"
        assert len(result["data"]["tiers"]) == 3

    def test_query_upgrade_free_to_basic(self):
        from hermass_platform.agents.monetization_butler import query_upgrade_recommendation
        set_tier("mz_u2", "free")
        result = query_upgrade_recommendation("mz_u2")
        assert result["status"] == "ok"
        assert result["data"]["next_tier"] == "basic"

    def test_query_upgrade_premium(self):
        from hermass_platform.agents.monetization_butler import query_upgrade_recommendation
        set_tier("mz_u3", "premium")
        result = query_upgrade_recommendation("mz_u3")
        assert result["data"]["already_highest"]

    def test_agent_result_structure(self):
        from hermass_platform.agents.monetization_butler import query_subscription_status
        result = query_subscription_status("mz_u4")
        assert "agent_id" in result
        assert result["agent_id"] == "monetization_butler"
