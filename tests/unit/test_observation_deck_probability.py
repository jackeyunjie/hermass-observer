"""Tests for observation deck probability adapter."""

from __future__ import annotations

from typing import Any

import pytest

from web.services import observation_deck_probability as adapter


class TestObservationDeckProbabilityAdapter:
    def test_build_maps_turning_types(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_summary() -> dict[str, Any]:
            return {"ok": True, "state_date": "2026-07-02"}

        def fake_signals(window: str, limit: int) -> dict[str, Any]:
            return {
                "ok": True,
                "signals": [
                    {
                        "stock_code": "000001.SZ",
                        "stock_name": "平安银行",
                        "window": window,
                        "turning_type": "turn_up",
                        "confidence": 0.55,
                        "evidence_items": ["W1 方向偏多", "ADX 强劲"],
                        "risk_flags": [],
                        "industry_l1": "银行",
                    }
                ],
            }

        monkeypatch.setattr(adapter, "tpp_get_summary", fake_summary)
        monkeypatch.setattr(adapter, "tpp_get_signals", fake_signals)

        result = adapter.build_observation_deck_probability_signals(limit=5)
        assert result["ok"] is True
        assert result["date"] == "2026-07-02"
        assert len(result["items"]) == 2
        labels = {item["label"] for item in result["items"]}
        assert labels == {"结构转强"}
        assert result["items"][0]["tone"] == "strong"
        assert result["items"][0]["evidence_count"] == 2
        assert result["items"][0]["research_url"] == "/research?stock_code=000001.SZ"

    def test_uncertain_becomes_evidence_insufficient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_summary() -> dict[str, Any]:
            return {"ok": True, "state_date": "2026-07-02"}

        def fake_signals(window: str, limit: int) -> dict[str, Any]:
            return {
                "ok": True,
                "signals": [
                    {
                        "stock_code": "688107.SH",
                        "stock_name": "安路科技",
                        "window": "3W",
                        "turning_type": "uncertain",
                        "confidence": 0.25,
                        "evidence_items": [],
                        "risk_flags": [],
                        "industry_l1": "电子",
                    }
                ],
            }

        monkeypatch.setattr(adapter, "tpp_get_summary", fake_summary)
        monkeypatch.setattr(adapter, "tpp_get_signals", fake_signals)

        result = adapter.build_observation_deck_probability_signals(limit=5)
        assert result["items"][0]["label"] == "证据不足"
        assert result["items"][0]["tone"] == "muted"
        assert result["items"][0]["risk_label"] == "低置信"

    def test_risk_label_from_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_summary() -> dict[str, Any]:
            return {"ok": True, "state_date": "2026-07-02"}

        def fake_signals(window: str, limit: int) -> dict[str, Any]:
            return {
                "ok": True,
                "signals": [
                    {
                        "stock_code": "000002.SZ",
                        "stock_name": "万科A",
                        "window": "3W",
                        "turning_type": "false_breakout",
                        "confidence": 0.45,
                        "evidence_items": ["M30 假突破风险"],
                        "risk_flags": ["假突破风险"],
                        "industry_l1": "房地产",
                    }
                ],
            }

        monkeypatch.setattr(adapter, "tpp_get_summary", fake_summary)
        monkeypatch.setattr(adapter, "tpp_get_signals", fake_signals)

        result = adapter.build_observation_deck_probability_signals(limit=5)
        item = result["items"][0]
        assert item["label"] == "假突破风险"
        assert item["tone"] == "risk"
        assert item["risk_label"] == "假突破风险"
        assert item["evidence_count"] == 1

    def test_bad_confidence_degrades_to_low_confidence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_summary() -> dict[str, Any]:
            return {"ok": True, "state_date": "2026-07-02"}

        def fake_signals(window: str, limit: int) -> dict[str, Any]:
            return {
                "ok": True,
                "signals": [
                    {
                        "stock_code": "000001.SZ",
                        "stock_name": "平安银行",
                        "window": "3W",
                        "turning_type": "uncertain",
                        "confidence": "bad-value",
                        "evidence_items": [],
                        "risk_flags": [],
                        "industry_l1": "银行",
                    }
                ],
            }

        monkeypatch.setattr(adapter, "tpp_get_summary", fake_summary)
        monkeypatch.setattr(adapter, "tpp_get_signals", fake_signals)

        result = adapter.build_observation_deck_probability_signals(limit=5)
        assert result["items"][0]["risk_label"] == "低置信"

    def test_empty_when_reader_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_summary() -> dict[str, Any]:
            return {"ok": True, "state_date": "2026-07-02"}

        def fake_signals(window: str, limit: int) -> dict[str, Any]:
            return {"ok": False, "error": "产物缺失"}

        monkeypatch.setattr(adapter, "tpp_get_summary", fake_summary)
        monkeypatch.setattr(adapter, "tpp_get_signals", fake_signals)

        result = adapter.build_observation_deck_probability_signals(limit=5)
        assert result["ok"] is True
        assert result["items"] == []
        assert "产物缺失" in result["warning"]

    def test_respects_limit_and_deduplicates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_summary() -> dict[str, Any]:
            return {"ok": True, "state_date": "2026-07-02"}

        def fake_signals(window: str, limit: int) -> dict[str, Any]:
            # 同一标的出现在两个窗口
            return {
                "ok": True,
                "signals": [
                    {
                        "stock_code": "000001.SZ",
                        "stock_name": "平安银行",
                        "window": window,
                        "turning_type": "continue",
                        "confidence": 0.5,
                        "evidence_items": ["D1 强势结构"],
                        "risk_flags": [],
                        "industry_l1": "银行",
                    }
                ],
            }

        monkeypatch.setattr(adapter, "tpp_get_summary", fake_summary)
        monkeypatch.setattr(adapter, "tpp_get_signals", fake_signals)

        result = adapter.build_observation_deck_probability_signals(limit=5)
        assert len(result["items"]) == 2  # 3W 与 3M 各一条
        assert result["items"][0]["window"] == "3W"
        assert result["items"][1]["window"] == "3M"

        result2 = adapter.build_observation_deck_probability_signals(limit=1)
        assert len(result2["items"]) == 1

    def test_no_forbidden_words(self, monkeypatch: pytest.MonkeyPatch) -> None:
        forbidden = {
            "买入", "卖出", "加仓", "减仓", "清仓", "空仓",
            "加杠杆", "止盈", "止损", "目标价", "收益承诺",
            "推荐买", "推荐卖", "适合交易",
        }

        def fake_summary() -> dict[str, Any]:
            return {"ok": True, "state_date": "2026-07-02"}

        def fake_signals(window: str, limit: int) -> dict[str, Any]:
            return {
                "ok": True,
                "signals": [
                    {
                        "stock_code": "000001.SZ",
                        "stock_name": "平安银行",
                        "window": window,
                        "turning_type": "turn_up",
                        "confidence": 0.55,
                        "evidence_items": ["W1 方向偏多"],
                        "risk_flags": [],
                        "industry_l1": "银行",
                    }
                ],
            }

        monkeypatch.setattr(adapter, "tpp_get_summary", fake_summary)
        monkeypatch.setattr(adapter, "tpp_get_signals", fake_signals)

        result = adapter.build_observation_deck_probability_signals(limit=5)
        text = str(result)
        found = [w for w in forbidden if w in text]
        assert not found, f"包含禁用词: {found}"
