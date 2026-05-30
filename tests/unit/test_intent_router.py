import pytest
from hermass_platform.chat.intent_router import (
    classify_intent,
    get_agent_for_intent,
    list_all_intents,
    INTENT_DEFINITIONS,
)


class TestIntentClassification:

    def test_market_phase_intent(self):
        r = classify_intent("现在市场什么阶段")
        assert r.intent == "market_phase"
        assert r.agent == "market_analyst"
        assert r.confidence > 0.5

    def test_market_environment(self):
        r = classify_intent("大盘怎么样")
        assert r.intent == "market_phase"
        assert r.agent == "market_analyst"

    def test_my_profile_intent(self):
        r = classify_intent("我的交易风格是什么")
        assert r.intent == "my_profile"
        assert r.agent == "cognitive_detective"

    def test_my_fit_intent(self):
        r = classify_intent("当前环境适合我吗")
        assert r.intent == "my_fit"
        assert r.agent == "strategy_advisor"

    def test_signal_explore_intent(self):
        r = classify_intent("今天有什么好信号")
        assert r.intent == "signal_explore"
        assert r.agent == "strategy_advisor"

    def test_strategy_fit_intent(self):
        r = classify_intent("VCP策略现在表现怎么样")
        assert r.intent == "strategy_fit"
        assert r.agent == "strategy_advisor"

    def test_sector_heat_intent(self):
        r = classify_intent("电子行业最近怎么样")
        assert r.intent == "sector_heat"
        assert r.agent == "market_analyst"

    def test_macro_outlook_intent(self):
        r = classify_intent("现在的GDP和CPI怎么样")
        assert r.intent == "macro_outlook"
        assert r.agent == "market_analyst"

    def test_my_risk_intent(self):
        r = classify_intent("我持仓有什么风险")
        assert r.intent == "my_risk"
        assert r.agent == "risk_guardian"

    def test_exit_rule_intent(self):
        r = classify_intent("什么时候应该止损")
        assert r.intent == "exit_rule"
        assert r.agent == "risk_guardian"

    def test_learn_topic_intent(self):
        r = classify_intent("什么是VCP形态")
        assert r.intent == "learn_topic"
        assert r.agent == "coach"

    def test_practice_intent(self):
        r = classify_intent("给我出一道测试题")
        assert r.intent == "practice"
        assert r.agent == "coach"

    def test_subscription_intent(self):
        r = classify_intent("怎么升级会员")
        assert r.intent == "subscription"
        assert r.agent == "monetization_butler"

    def test_benefits_intent(self):
        r = classify_intent("高级版有什么功能")
        assert r.intent == "benefits"
        assert r.agent == "monetization_butler"

    def test_greeting_fallback(self):
        r = classify_intent("你好")
        assert r.intent in INTENT_DEFINITIONS
        assert r.confidence > 0.1

    def test_unknown_fallback(self):
        r = classify_intent("今天天气不错")
        assert r.intent in INTENT_DEFINITIONS
        assert r.confidence <= 0.3

    def test_confidence_in_range(self):
        for msg in ["市场怎么样", "我的画像", "有什么信号", "怎么订阅"]:
            r = classify_intent(msg)
            assert 0.0 <= r.confidence <= 1.0

    def test_multi_keyword_match(self):
        r = classify_intent("我对电子行业和半导体行业的持仓风险怎么样")
        assert r.intent in ("sector_heat", "my_risk")
        assert len(r.matched_keywords) > 0


class TestGetAgentForIntent:

    def test_valid_intents(self):
        assert get_agent_for_intent("market_phase") == "market_analyst"
        assert get_agent_for_intent("my_profile") == "cognitive_detective"
        assert get_agent_for_intent("learn_topic") == "coach"
        assert get_agent_for_intent("subscription") == "monetization_butler"

    def test_unknown_intent(self):
        assert get_agent_for_intent("nonexistent") == "market_analyst"


class TestListAllIntents:

    def test_all_intents_listed(self):
        intents = list_all_intents()
        assert len(intents) == len(INTENT_DEFINITIONS)
        for item in intents:
            assert "intent" in item
            assert "agent" in item
            assert "description" in item
            assert item["intent"] in INTENT_DEFINITIONS
