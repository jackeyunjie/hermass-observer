"""Unit tests for the classic strategy sentinel.

Covers the research-only boundary and isolation from the Hermass State system.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import web.main as main
from web.services import classic_strategy_sentinel as sentinel


# Forbidden trading-action words that must not appear in overview API output.
FORBIDDEN_OVERVIEW_WORDS = {
    "买入",
    "卖出",
    "加仓",
    "减仓",
    "清仓",
    "空仓",
    "加杠杆",
    "止盈",
    "止损",
    "目标价",
    "收益承诺",
    "适合交易",
    "推荐买",
    "推荐卖",
    "入场",
    "出场",
    "买点",
    "卖点",
    "仓位",
}

# Forbidden State-system mixing words.
FORBIDDEN_STATE_MIX_WORDS = {
    "同向",
    "冲突",
    "领先",
    "证据不足",
    "转折概率",
}


def _sample_rows() -> list[dict]:
    """Return a diverse set of rows that exercises all allowed strategies."""
    return [
        {
            "signal_date": "2026-07-02",
            "stock_code": "000001.SZ",
            "stock_name": "平安银行",
            "strategy_id": "vcp",
            "signal_type": "entry",
            "signal_name": "VCP突破确认",
            "signal_strength": 0.85,
            "raw_signal": "vcp_breakout",
            "strategy_environment_fit": "最佳适配",
        },
        {
            "signal_date": "2026-07-02",
            "stock_code": "000002.SZ",
            "stock_name": "万科A",
            "strategy_id": "vcp",
            "signal_type": "structure",
            "signal_name": "VCP收缩结构",
            "signal_strength": 0.65,
            "raw_signal": "vcp_contraction",
            "strategy_environment_fit": "弱适配",
        },
        {
            "signal_date": "2026-07-02",
            "stock_code": "600519.SH",
            "stock_name": "贵州茅台",
            "strategy_id": "ma2560",
            "signal_type": "entry",
            "signal_name": "2560金叉",
            "signal_strength": 0.80,
            "raw_signal": "ma2560_golden_cross",
            "strategy_environment_fit": "最佳适配",
        },
        {
            "signal_date": "2026-07-02",
            "stock_code": "600519.SH",
            "stock_name": "贵州茅台",
            "strategy_id": "ma2560",
            "signal_type": "exit",
            "signal_name": "2560死叉风险",
            "signal_strength": 0.90,
            "raw_signal": "ma2560_death_cross_exit",
            "strategy_environment_fit": "弱适配",
        },
        {
            "signal_date": "2026-07-02",
            "stock_code": "300750.SZ",
            "stock_name": "宁德时代",
            "strategy_id": "bollinger_bandit",
            "signal_type": "entry",
            "signal_name": "布林强盗多头触发",
            "signal_strength": 0.75,
            "raw_signal": "bb_bandit_long_entry",
            "strategy_environment_fit": "最佳适配",
        },
        {
            "signal_date": "2026-07-02",
            "stock_code": "000063.SZ",
            "stock_name": "中兴通讯",
            "strategy_id": "atr_chandelier",
            "signal_type": "entry",
            "signal_name": "ATR吊灯多头触发",
            "signal_strength": 0.70,
            "raw_signal": "atr_long_entry",
            "strategy_environment_fit": "待观察",
        },
    ]


@pytest.fixture
def sample_rows():
    return _sample_rows()


@pytest.fixture(autouse=True)
def _patch_load_rows(monkeypatch, sample_rows):
    """All tests in this module use the in-memory sample rows."""
    captured: list[str] = []

    def _fake_load(date_str: str):
        captured.append(date_str)
        return [dict(row) for row in sample_rows]

    monkeypatch.setattr(sentinel, "_load_rows", _fake_load)


class TestOverview:
    def test_returns_allowed_strategy_aggregations(self):
        overview = sentinel.get_overview("2026-07-02")
        assert overview["ok"] is True
        strategies = overview["strategies"]
        names = [s["strategy_name"] for s in strategies]
        assert "vcp" in names
        assert "ma2560" in names
        assert "bollinger_bandit" in names

    def test_only_allowed_strategies_in_output(self):
        overview = sentinel.get_overview("2026-07-02")
        for s in overview["strategies"]:
            assert s["strategy_name"] in sentinel.ALLOWED_STRATEGIES

    def test_atr_chandelier_excluded(self):
        overview = sentinel.get_overview("2026-07-02")
        names = [s["strategy_name"] for s in overview["strategies"]]
        assert "atr_chandelier" not in names

    def test_structure_signals_not_in_overview(self):
        overview = sentinel.get_overview("2026-07-02")
        for s in overview["strategies"]:
            assert s["signal_type"] != "structure"

    def test_mutual_exclusion_per_stock_and_strategy(self):
        # 600519 has both entry and exit for ma2560; only entry should count
        # for the overview aggregation, and total_stocks should reflect that.
        overview = sentinel.get_overview("2026-07-02")
        ma2560_entry = next(
            (s for s in overview["strategies"]
             if s["strategy_name"] == "ma2560" and s["signal_type"] == "entry"),
            None,
        )
        assert ma2560_entry is not None
        assert ma2560_entry["signal_count"] == 1
        assert ma2560_entry["signals"][0]["stock_code"] == "600519.SH"

    def test_overview_neutral_labels_no_action_words(self):
        overview = sentinel.get_overview("2026-07-02")
        text = str(overview)
        for word in FORBIDDEN_OVERVIEW_WORDS:
            assert word not in text, f"Overview leaked forbidden word: {word}"

    def test_overview_no_state_mixing(self):
        overview = sentinel.get_overview("2026-07-02")
        text = str(overview)
        for word in FORBIDDEN_STATE_MIX_WORDS:
            assert word not in text, f"Overview leaked State mixing word: {word}"

    def test_missing_data_returns_ok_and_empty(self, monkeypatch):
        monkeypatch.setattr(sentinel, "_load_rows", lambda _date: [])
        overview = sentinel.get_overview("2026-07-02")
        assert overview["ok"] is True
        assert overview["strategies"] == []
        assert overview["total_stocks"] == 0
        assert overview["warning"] is not None


class TestSignals:
    def test_signals_returns_only_requested_strategy(self):
        data = sentinel.get_signals("vcp", "2026-07-02")
        assert data["ok"] is True
        assert data["strategy"] == "vcp"
        for sig in data["signals"]:
            assert sig.get("signal_name") in {
                "vcp_breakout",
                "vcp_contraction",
            }

    def test_signals_rejects_unsupported_strategy(self):
        data = sentinel.get_signals("atr_chandelier", "2026-07-02")
        assert data["ok"] is False
        assert "error" in data

    def test_signals_no_state_mixing(self):
        data = sentinel.get_signals("ma2560", "2026-07-02")
        text = str(data)
        for word in FORBIDDEN_STATE_MIX_WORDS:
            assert word not in text


class TestDetail:
    def test_detail_contains_disclaimer(self):
        detail = sentinel.get_detail("vcp", "000001.SZ", "2026-07-02")
        assert detail["ok"] is True
        assert detail["disclaimer"] == sentinel.RESEARCH_ONLY_DISCLAIMER
        assert "仅作研究观察" in detail["disclaimer"]

    def test_detail_includes_original_rule_text(self):
        detail = sentinel.get_detail("vcp", "000001.SZ", "2026-07-02")
        assert detail["found"] is True
        assert len(detail["stop_rules"]) > 0
        assert len(detail["exit_rules"]) > 0
        assert detail["position_rule_text"]

    def test_detail_evidence_items_present(self):
        detail = sentinel.get_detail("vcp", "000001.SZ", "2026-07-02")
        assert detail["evidence_items"]
        for item in detail["evidence_items"]:
            assert "condition" in item
            assert "met" in item

    def test_detail_not_found_returns_ok_with_warning(self):
        detail = sentinel.get_detail("vcp", "999999.SZ", "2026-07-02")
        assert detail["ok"] is True
        assert detail["found"] is False
        assert detail["warning"] is not None

    def test_detail_rejects_unsupported_strategy(self):
        detail = sentinel.get_detail("atr_chandelier", "000001.SZ", "2026-07-02")
        assert detail["ok"] is False

    def test_detail_requires_stock_code(self):
        detail = sentinel.get_detail("vcp", "", "2026-07-02")
        assert detail["ok"] is False


class TestBoundary:
    def test_service_constants_match_requirements(self):
        assert sentinel.ALLOWED_STRATEGIES == {"vcp", "ma2560", "bollinger_bandit"}
        assert "atr_chandelier" not in sentinel.ALLOWED_STRATEGIES

    def test_overview_labels_are_neutral(self):
        labels = {
            sentinel.OVERVIEW_LABELS[(s, t)]
            for s, t in sentinel.OVERVIEW_LABELS
        }
        for word in FORBIDDEN_OVERVIEW_WORDS:
            for label in labels:
                assert word not in label, f"Label '{label}' contains {word}"

    def test_no_state_fields_in_any_api_response(self):
        overview = sentinel.get_overview("2026-07-02")
        signals = sentinel.get_signals("vcp", "2026-07-02")
        detail = sentinel.get_detail("vcp", "000001.SZ", "2026-07-02")
        for payload in (overview, signals, detail):
            for key in payload:
                assert "state_" not in str(key).lower() or key in (
                    "strategy_environment_fit",
                )


class TestRoutes:
    def test_api_sentinel_overview(self, monkeypatch, sample_rows):
        monkeypatch.setattr(sentinel, "_load_rows", lambda _date: [dict(r) for r in sample_rows])
        client = TestClient(main.app)
        response = client.get("/api/sentinel/overview?date=2026-07-02")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert any(s["strategy_name"] == "vcp" for s in data["strategies"])

    def test_api_sentinel_signals(self, monkeypatch, sample_rows):
        monkeypatch.setattr(sentinel, "_load_rows", lambda _date: [dict(r) for r in sample_rows])
        client = TestClient(main.app)
        response = client.get("/api/sentinel/signals?strategy=vcp&date=2026-07-02")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["strategy"] == "vcp"

    def test_api_sentinel_detail(self, monkeypatch, sample_rows):
        monkeypatch.setattr(sentinel, "_load_rows", lambda _date: [dict(r) for r in sample_rows])
        client = TestClient(main.app)
        response = client.get("/api/sentinel/detail?strategy=vcp&stock_code=000001.SZ&date=2026-07-02")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["found"] is True
        assert "仅作研究观察" in data["disclaimer"]

    def test_page_sentinel_overview(self, monkeypatch, sample_rows):
        monkeypatch.setattr(sentinel, "_load_rows", lambda _date: [dict(r) for r in sample_rows])
        client = TestClient(main.app)
        response = client.get("/sentinel?date=2026-07-02")
        assert response.status_code == 200
        assert "经典策略哨兵" in response.text
        assert sentinel.RESEARCH_ONLY_DISCLAIMER in response.text

    def test_page_sentinel_detail(self, monkeypatch, sample_rows):
        monkeypatch.setattr(sentinel, "_load_rows", lambda _date: [dict(r) for r in sample_rows])
        client = TestClient(main.app)
        response = client.get("/sentinel/detail?strategy=vcp&stock_code=000001.SZ&date=2026-07-02")
        assert response.status_code == 200
        assert "VCP 收缩释放" in response.text
        assert "止损规则" in response.text
        assert "退出规则" in response.text
        assert sentinel.RESEARCH_ONLY_DISCLAIMER in response.text

    def test_route_rejects_atr_chandelier(self, monkeypatch, sample_rows):
        monkeypatch.setattr(sentinel, "_load_rows", lambda _date: [dict(r) for r in sample_rows])
        client = TestClient(main.app)
        response = client.get("/api/sentinel/signals?strategy=atr_chandelier&date=2026-07-02")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
