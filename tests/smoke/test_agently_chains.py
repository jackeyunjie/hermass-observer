"""冒烟测试：agently_adapter 三条核心编排链

覆盖：
- 正常链：LLM 全通
- judge 失败：market_overview 整链 abort → qa_entry fallback
- 单 Agent 失败：stock_checkup 中间节点降级 → 链继续
- router 失败 → keyword 兜底
- 闲聊路由 → None

用法：python tests/smoke/test_agently_chains.py
"""

from __future__ import annotations

import os
import sys
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agently_adapter.qa_entry import handle


# ── 公共 context 模板 ───────────────────────────────
def base_ctx(
    symbol: str = "000021.SZ",
    market_data: dict[str, Any] | None = None,
    stock_states: dict[str, Any] | None = None,
    industry_name: str = "",
) -> dict[str, Any]:
    return {
        "user_type": "执行型",
        "current_page": "stock",
        "symbol": symbol,
        "mode": "chat",
        "market_data": market_data or {},
        "stock_states": stock_states
        or {"mn1": "E", "w1": "F", "d1": "C", "ef_count": 3},
        "stock_name": "测试股",
        "industry_name": industry_name,
    }


# ── 1. 个股问诊（最大流程长）──────────────────────
def test_stock_checkup_happy() -> None:
    """Happy path: 翻译 → 诊断 → 翻译 → 融合 全通"""
    trans_mock = MagicMock()
    trans_mock.side_effect = [
        {"meaning": "E2 强势", "what_it_says": "趋势确认", "season": "生长季", "how_to_read": "跟踪", "tone": "执行型"},
        {"meaning": "诊断翻译", "what_it_says": "量价配合", "season": "生长季", "how_to_read": "持有", "tone": "执行型"},
    ]
    with patch("agently_adapter.agents.translator.run", trans_mock), \
         patch("agently_adapter.agents.diagnoser.run") as m_d, \
         patch("agently_adapter.agents.fusion.run") as m_f:
        m_d.return_value = {
            "conclusion": "量价配合，趋势良好",
            "cycle_position": "MN1 地利，W1 天时，D1 天时",
            "capital_structure": "资金流入确认",
            "next_step": "标准跟踪，设止损",
            "risk_flag": "none",
        }
        m_f.return_value = {
            "answer": "000021 当前强势，量价配合",
            "why": "ef=3，资金确认",
            "multi_cycle_view": "三周期共振",
            "single_cycle_position": "日线天时",
            "avoid": "勿追高",
            "next_actions": [],
            "sources": [],
            "freshness_note": "",
        }
        r = handle("000021 怎么样", base_ctx())
        assert r is not None
        assert r.get("provider") == "agently_deepseek"
        assert r.get("enhancement_used") is True
        print("PASS stock_checkup happy")


def test_stock_checkup_diagnoser_fails() -> None:
    """诊断 Agent 失败 → 该步降级为默认值 → 链继续"""
    trans_mock = MagicMock()
    trans_mock.side_effect = [
        {"meaning": "E2 强势", "what_it_says": "趋势确认", "season": "生长季", "how_to_read": "跟踪", "tone": "执行型"},
        {"meaning": "降级翻译", "what_it_says": "诊断未获取", "season": "未知", "how_to_read": "观察", "tone": "执行型"},
    ]
    with patch("agently_adapter.agents.translator.run", trans_mock), \
         patch("agently_adapter.agents.diagnoser.run", return_value=None), \
         patch("agently_adapter.agents.fusion.run") as m_f:
        m_f.return_value = {
            "answer": "诊断失败，已降级",
            "why": "诊断 Agent 未返回",
            "multi_cycle_view": "多周期环境正常",
            "single_cycle_position": "单周期位置待确认",
            "avoid": "数据不完整，谨慎决策",
            "next_actions": [],
            "sources": [],
            "freshness_note": "",
        }
        r = handle("000021 怎么样", base_ctx())
        assert r is not None
        assert "链路调用失败" not in r.get("why", "")  # 不应触发全链 fallback
        print("PASS stock_checkup diagnoser_fail -> partial fallback")


# ── 2. 市场全景 ────────────────────────────────────
def test_market_overview_happy() -> None:
    """Happy path: 判官 → 翻译 → 融合 全通"""
    with patch("agently_adapter.agents.judge.run") as m_j, \
         patch("agently_adapter.agents.translator.run") as m_t, \
         patch("agently_adapter.agents.fusion.run") as m_f:
        m_j.return_value = {
            "environment": "震荡选择环境，ef2=11.2%",
            "key_signals": ["逆位占比 72%", "电力设备资金流入"],
            "suggested_action": "等待，仅跟踪电力设备突破个股",
            "risk_level": "normal",
            "trap_warning": "",
            "alert_level": "none",
        }
        m_t.return_value = {"meaning": "当前偏暖", "what_it_says": "可持仓", "season": "生长季", "how_to_read": "跟踪", "tone": "方向型"}
        m_f.return_value = {
            "answer": "大盘偏暖，可持仓",
            "why": "ef2=11.2%，结构 intact",
            "multi_cycle_view": "震荡选择",
            "single_cycle_position": "日线偏多",
            "avoid": "勿追高",
            "next_actions": [],
            "sources": [],
            "freshness_note": "",
        }
        r = handle("大盘怎么样", base_ctx(symbol=""))
        assert r is not None
        assert r.get("provider") == "agently_deepseek"
        print("PASS market_overview happy")


def test_market_overview_judge_fails() -> None:
    """判官失败 → 整链 abort → qa_entry fallback_response"""
    with patch("agently_adapter.agents.judge.run", return_value=None), \
         patch("agently_adapter.agents.translator.run") as m_t, \
         patch("agently_adapter.agents.fusion.run") as m_f:
        r = handle("大盘怎么样", base_ctx(symbol=""))
        assert r is not None
        assert "链路调用失败" in r.get("why", "")  # fallback 标记
        assert r.get("enhancement_used") is False
        print("PASS market_overview judge_fail -> qa_entry fallback")


# ── 3. 行业扫描 ────────────────────────────────────
def test_industry_scan_happy() -> None:
    with patch("agently_adapter.agents.judge.run") as m_j, \
         patch("agently_adapter.agents.industry.run") as m_i, \
         patch("agently_adapter.agents.translator.run") as m_t, \
         patch("agently_adapter.agents.fusion.run") as m_f:
        m_j.return_value = {"environment": "偏暖", "key_signals": [], "suggested_action": "跟踪电子", "risk_level": "normal", "trap_warning": "", "alert_level": "none"}
        m_i.return_value = {"industry_state": "电子景气上行", "component_scan": "23% 强势", "supply_chain": "上游缺货", "rotation_position": "加速", "data_gaps": []}
        m_t.return_value = {"meaning": "电子板块景气", "what_it_says": "资金流入", "season": "生长季", "how_to_read": "跟踪", "tone": "研究型"}
        m_f.return_value = {
            "answer": "电子行业景气上行",
            "why": "23% 成分股强势",
            "multi_cycle_view": "行业共振",
            "single_cycle_position": "启动-加速过渡",
            "avoid": "龙头已进入后期",
            "next_actions": [],
            "sources": [],
            "freshness_note": "",
        }
        r = handle("电子行业怎么样", base_ctx(industry_name="电子"))
        assert r is not None
        print("PASS industry_scan happy")


# ── 4. 路由 + keyword fallback ─────────────────────
def test_keyword_fallback_when_router_down() -> None:
    """LLM 路由返回 None → keyword 兜底命中 watch_command"""
    with patch("agently_adapter.agents.router.run", return_value=None):
        r = handle("帮忙盯着 000021", base_ctx())
        assert r is not None
        assert r.get("mode_used") == "chat"
        print("PASS keyword fallback -> watch_command")


# ── 5. 闲聊路由 ────────────────────────────────────
def test_chitchat_returns_none() -> None:
    """闲聊 → qa_entry 返回 None，让 web 层走规则回答"""
    with patch("agently_adapter.agents.router.run", return_value={"scenario": "chitchat"}):
        r = handle("你好啊", base_ctx())
        assert r is None
        print("PASS chitchat -> None (web-routed)")


if __name__ == "__main__":
    test_stock_checkup_happy()
    test_stock_checkup_diagnoser_fails()
    test_market_overview_happy()
    test_market_overview_judge_fails()
    test_industry_scan_happy()
    test_keyword_fallback_when_router_down()
    test_chitchat_returns_none()
    print("\n7 / 7 PASS — 冒烟完成")
