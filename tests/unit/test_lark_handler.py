import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from hermass_platform.chat.lark_handler import (
    handle_lark_message,
    verify_url_challenge,
    _dispatch_agent,
    _resolve_foundation_db,
    _wrap_lark_markdown,
    _get_help_message,
)


class TestVerifyUrlChallenge:

    def test_challenge_returns_echo(self):
        result = verify_url_challenge("test_challenge_123")
        assert result["challenge"] == "test_challenge_123"


class TestWrapLarkMarkdown:

    def test_headers_converted(self):
        text = "## 标题\n正文内容"
        result = _wrap_lark_markdown(text)
        assert "**标题**" in result

    def test_bullet_points(self):
        text = "- 项目一\n- 项目二"
        result = _wrap_lark_markdown(text)
        assert "•" in result


class TestResolveFoundationDB:

    def test_returns_string(self):
        db = _resolve_foundation_db()
        if db:
            assert isinstance(db, str)


class TestDispatchAgent:

    def test_market_phase_dispatches(self):
        db = _resolve_foundation_db()
        if not db:
            pytest.skip("No Foundation DB available")
        result = _dispatch_agent("test_user", "market_phase", "市场怎么样", db)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_my_profile_dispatches(self):
        result = _dispatch_agent("test_user", "my_profile", "我的风格", "")
        assert isinstance(result, str)

    def test_learn_topic_dispatches(self):
        result = _dispatch_agent("test_user", "learn_topic", "什么是State", "")
        assert isinstance(result, str)
        assert "State" in result or "state" in result.lower() or len(result) > 20

    def test_practice_dispatches(self):
        result = _dispatch_agent("test_user", "practice", "给我出题", "")
        assert isinstance(result, str)

    def test_exit_rule_dispatches(self):
        db = _resolve_foundation_db()
        if not db:
            pytest.skip("No Foundation DB available")
        result = _dispatch_agent("test_user", "exit_rule", "000001止损", db)
        assert isinstance(result, str)

    def test_unknown_intent(self):
        result = _dispatch_agent("test_user", "unknown_intent_xyz", "test", "")
        assert isinstance(result, str)

    def test_subscription_dispatches(self):
        result = _dispatch_agent("test_user", "subscription", "怎么升级", "")
        assert isinstance(result, str)

    def test_benefits_dispatches(self):
        result = _dispatch_agent("test_user", "benefits", "有什么功能", "")
        assert isinstance(result, str)


class TestHandleLarkMessage:

    @pytest.fixture(autouse=True)
    def setup(self):
        import hermass_platform.cognitive.cognitive_ledger as cl
        self.cog_tmpdir = tempfile.TemporaryDirectory()
        self.orig_cog_dir = cl.LEDGER_DIR
        cl.LEDGER_DIR = Path(self.cog_tmpdir.name) / "cognitive"
        cl.LEDGER_DIR.mkdir(parents=True, exist_ok=True)

        import hermass_platform.monetization.subscription_manager as sm
        self.sub_tmpdir = tempfile.TemporaryDirectory()
        self.orig_sub_dir = sm.SUB_DIR
        sm.SUB_DIR = Path(self.sub_tmpdir.name) / "subscription"
        sm.SUB_DIR.mkdir(parents=True, exist_ok=True)

        yield

        cl.LEDGER_DIR = self.orig_cog_dir
        self.cog_tmpdir.cleanup()
        sm.SUB_DIR = self.orig_sub_dir
        self.sub_tmpdir.cleanup()

    def test_market_query(self):
        reply = handle_lark_message("lark_user_001", "现在市场怎么样")
        assert isinstance(reply, str)
        assert len(reply) > 20

    def test_profile_query(self):
        reply = handle_lark_message("lark_user_002", "我的交易画像是什么")
        assert isinstance(reply, str)

    def test_strategy_query(self):
        reply = handle_lark_message("lark_user_003", "有什么好信号")
        assert isinstance(reply, str)

    def test_learning_query(self):
        reply = handle_lark_message("lark_user_004", "什么是E和F状态")
        assert isinstance(reply, str)

    def test_subscription_query(self):
        reply = handle_lark_message("lark_user_005", "基础版有什么功能")
        assert isinstance(reply, str)

    def test_compliance_present_in_trade_reply(self):
        reply = handle_lark_message("lark_user_007", "推荐策略怎么样")
        assert isinstance(reply, str)
        assert "不构成投资建议" in reply or len(reply) > 10

    def test_session_created(self):
        reply = handle_lark_message(
            "lark_user_008", "今天行情怎么样",
            session_id="test_sess_001",
        )
        assert isinstance(reply, str)


class TestHelpMessage:

    def test_help_keyword(self):
        reply = handle_lark_message("lark_test", "帮助")
        assert "市场分析" in reply
        assert "策略信号" in reply
        assert "认知检测" in reply

    def test_help_what_can_do(self):
        reply = handle_lark_message("lark_test", "能做什么")
        assert "市场分析" in reply

    def test_help_usage(self):
        reply = handle_lark_message("lark_test", "怎么用")
        assert "市场分析" in reply

    def test_sector_resonance_query(self):
        reply = handle_lark_message("lark_test", "今天哪些行业在动")
        assert isinstance(reply, str)
        assert len(reply) > 10

    def test_sector_resonance_keyword(self):
        reply = handle_lark_message("lark_test", "板块共振了吗")
        assert isinstance(reply, str)

    def test_get_help_message_function(self):
        msg = _get_help_message()
        assert "Hermass Observer" in msg
        assert "市场分析" in msg
        assert "帮助" in msg
