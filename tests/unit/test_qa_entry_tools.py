from __future__ import annotations

from unittest.mock import patch

from agently_adapter.qa_entry import handle


def test_handle_attaches_tool_trace_for_market_scenario():
    with patch("agently_adapter.agents.router.run", return_value={"scenario": "market_overview", "confidence": 0.9}), \
         patch("agently_adapter.qa_entry.run_tool") as m_tool, \
         patch("agently_adapter.agents.judge.run", return_value={"environment": "震荡"}), \
         patch("agently_adapter.agents.translator.run", return_value={"meaning": "震荡"}), \
         patch("agently_adapter.agents.fusion.run", return_value={
             "answer": "市场震荡，先筛选。",
             "why": "宽度未扩张。",
             "multi_cycle_view": "",
             "single_cycle_position": "",
             "avoid": "",
             "next_actions": [],
             "sources": [],
             "freshness_note": "",
         }):
        m_tool.return_value = {
            "ok": True,
            "tool": "get_market_phase",
            "data": {"available": True, "phase_label": "震荡选择"},
            "elapsed_ms": 1,
        }
        result = handle("现在市场能不能做", {"mode": "chat", "username": "tester"})

    assert result is not None
    assert "tool:get_market_phase" in result["sources"]
    assert result["trace"]["tools"] == ["get_market_phase"]
    assert result["trace"]["scenarios"] == ["market_overview"]


def test_handle_prefetches_stock_tools_for_stock_scenario():
    with patch("agently_adapter.agents.router.run", return_value={"scenario": "stock_checkup", "confidence": 0.9}), \
         patch("agently_adapter.qa_entry.run_tool") as m_tool, \
         patch("agently_adapter.agents.translator.run", side_effect=[{"meaning": "强势"}, {"meaning": "可跟踪"}]), \
         patch("agently_adapter.agents.diagnoser.run", return_value={"conclusion": "可跟踪"}), \
         patch("agently_adapter.agents.fusion.run", return_value={
             "answer": "000021 可观察。",
             "why": "多周期状态较好。",
             "multi_cycle_view": "",
             "single_cycle_position": "",
             "avoid": "",
             "next_actions": [],
             "sources": [],
             "freshness_note": "",
         }):
        def fake_tool(name, params, **kwargs):
            if name == "get_stock_state":
                return {
                    "ok": True,
                    "tool": name,
                    "data": {
                        "available": True,
                        "stock_code": "000021.SZ",
                        "stock_name": "深科技",
                        "stock_states": {"mn1": "E", "w1": "F", "d1": "C"},
                        "ef_count": 3,
                    },
                    "elapsed_ms": 1,
                }
            return {
                "ok": True,
                "tool": name,
                "data": {"available": False, "positions": []},
                "elapsed_ms": 1,
            }

        m_tool.side_effect = fake_tool
        result = handle("000021 怎么样", {"mode": "chat", "username": "tester"})

    assert result is not None
    assert "tool:get_stock_state" in result["sources"]
    assert "tool:get_chain_position" in result["sources"]
    assert result["trace"]["tools"] == ["get_stock_state", "get_chain_position"]


def test_value_analysis_passes_tool_declarations_to_deepseek():
    with patch("agently_adapter.deepseek.call") as m_call:
        m_call.return_value = {
            "answer": "价值分析完成。",
            "why": "结合工具证据。",
            "multi_cycle_view": "",
            "single_cycle_position": "",
            "avoid": "",
            "next_actions": [],
            "sources": [],
            "freshness_note": "",
        }

        result = handle(
            "用价值分析看 000021",
            {
                "mode": "chat",
                "username": "tester",
                "value_prompt_pack": True,
                "value_payload": {"stock_code": "000021.SZ"},
            },
        )

    assert result is not None
    assert result["provider"] == "agently_deepseek"
    _, kwargs = m_call.call_args
    assert {tool["function"]["name"] for tool in kwargs["tools"]} == {
        "get_market_phase",
        "get_stock_state",
        "get_chain_position",
    }
    assert kwargs["allowed_tools"] == ["get_market_phase", "get_stock_state", "get_chain_position"]
