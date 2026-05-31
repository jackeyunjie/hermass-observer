from __future__ import annotations

from unittest.mock import MagicMock, patch

from agently_adapter.deepseek import call


def test_call_returns_parsed_dict_when_agent_returns_dict() -> None:
    fake_agent = MagicMock()
    fake_agent.start.return_value = {"answer": "ok", "why": "ok"}
    with patch("agently_adapter.deepseek.Agently", create_agent=MagicMock(return_value=fake_agent)), \
         patch("agently_adapter.deepseek._ensure_settings", return_value=True):
        result = call({"stock_code": "000021.SZ"}, system_prompt="sys", instruct="do this")
    assert result == {"answer": "ok", "why": "ok"}


def test_call_returns_parsed_dict_when_agent_returns_json_string() -> None:
    fake_agent = MagicMock()
    fake_agent.start.return_value = '{"answer": "ok", "why": "ok"}'
    with patch("agently_adapter.deepseek.Agently", create_agent=MagicMock(return_value=fake_agent)), \
         patch("agently_adapter.deepseek._ensure_settings", return_value=True):
        result = call({"stock_code": "000021.SZ"}, system_prompt="sys", instruct="do this")
    assert result == {"answer": "ok", "why": "ok"}


def test_call_returns_none_when_settings_fail() -> None:
    with patch("agently_adapter.deepseek._ensure_settings", return_value=False):
        result = call({"stock_code": "000021.SZ"}, system_prompt="sys", instruct="do this")
    assert result is None
