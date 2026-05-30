import pytest
from hermass_platform.chat.compliance_filter import (
    check_compliance,
    apply_disclaimer,
    get_system_prompt,
    ComplianceResult,
    FORBIDDEN_PATTERNS,
    COMPLIANCE_REPLACEMENTS,
)


class TestCheckCompliance:

    def test_clean_text_passes(self):
        result = check_compliance("当前市场处于趋势行进阶段，2560策略处于最佳适配状态。")
        assert result.passed

    def test_forbidden_buy_recommendation(self):
        result = check_compliance("建议买入这只股票，信号很好")
        assert not result.passed
        assert any("建议买入" in v for v in result.violations)

    def test_forbidden_sell_recommendation(self):
        result = check_compliance("建议卖出，市场要跌了")
        assert not result.passed
        assert any("建议卖出" in v for v in result.violations)

    def test_forbidden_price_prediction(self):
        result = check_compliance("预计涨到100元")
        assert not result.passed
        assert any("价格预测" in v for v in result.violations)

    def test_forbidden_target_price(self):
        result = check_compliance("目标价50元，上涨空间很大")
        assert not result.passed
        assert any("目标价" in v for v in result.violations)

    def test_forbidden_guaranteed_return(self):
        result = check_compliance("这只股票必涨，稳赚不赔")
        assert not result.passed
        assert any("稳赚" in v for v in result.violations)

    def test_forbidden_order_instruction(self):
        result = check_compliance("现在就买，明天开盘买")
        assert not result.passed
        assert any("现在就买" in v for v in result.violations)

    def test_forbidden_position_instruction(self):
        result = check_compliance("建议满仓操作")
        assert not result.passed
        assert any("满仓" in v for v in result.violations)

    def test_trade_related_detection(self):
        result = check_compliance("当前市场阶段为趋势行进，2560策略信号良好")
        assert result.is_trade_related

    def test_non_trade_text(self):
        result = check_compliance("你好，今天天气不错")
        assert not result.is_trade_related

    def test_compliance_result_dataclass(self):
        cr = ComplianceResult(passed=True)
        assert cr.passed
        assert len(cr.violations) == 0
        assert not cr.needs_disclaimer()

    def test_needs_disclaimer_when_trade_related(self):
        cr = ComplianceResult(passed=True, is_trade_related=True)
        assert cr.needs_disclaimer()

    def test_multiple_forbidden_words(self):
        result = check_compliance("这只股票必涨，建议买入，预计涨到100元")
        assert not result.passed
        assert len(result.violations) >= 3


class TestApplyDisclaimer:

    def test_disclaimer_appended(self):
        text = "当前市场处于趋势行进阶段。"
        result = apply_disclaimer(text)
        assert "不构成投资建议" in result
        assert result.startswith(text)

    def test_disclaimer_with_source(self):
        text = "当前信号处于最佳适配状态。"
        result = apply_disclaimer(text, source_path="outputs/strategy_signals/strategy_signals.duckdb")
        assert "不构成投资建议" in result
        assert "strategy_signals.duckdb" in result


class TestSystemPrompt:

    def test_system_prompt_not_empty(self):
        prompt = get_system_prompt()
        assert len(prompt) > 100
        assert "Hermass Observer" in prompt or "hermass" in prompt.lower()

    def test_system_prompt_contains_compliance_rules(self):
        prompt = get_system_prompt()
        assert "合规约束" in prompt
        assert "建议买入" in prompt or "不可违反" in prompt

    def test_system_prompt_contains_response_structure(self):
        prompt = get_system_prompt()
        assert "应答结构" in prompt or "事实层" in prompt


class TestForbiddenPatterns:

    def test_all_patterns_compilable(self):
        for pattern, category in FORBIDDEN_PATTERNS:
            assert pattern.pattern
            assert category


class TestComplianceReplacements:

    def test_all_replacements_compilable(self):
        for pattern, replacement in COMPLIANCE_REPLACEMENTS:
            assert pattern.pattern
            assert replacement
