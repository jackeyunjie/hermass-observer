"""Tests for turning point probability reader service and API routes."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient

import web.main as main
from web.services import turning_point_probability_reader as tpp_reader


@pytest.fixture
def sample_json(tmp_path: Path) -> dict[str, Any]:
    payload = {
        "meta": {
            "state_date": "2026-07-02",
            "model_version": "tpp_mvp_v0.1",
            "generated_at": "2026-07-02T12:00:00",
            "market_regime": "range",
            "row_count": 4,
            "warnings": [],
        },
        "market_summary": {
            "3D": {"turning_type_counts": {"uncertain": 1}, "avg_confidence": 0.25, "count": 1},
            "3W": {"turning_type_counts": {"turn_up": 1}, "avg_confidence": 0.55, "count": 1},
            "3M": {"turning_type_counts": {"continue": 1}, "avg_confidence": 0.45, "count": 1},
            "6M": {"turning_type_counts": {"turn_down": 1}, "avg_confidence": 0.35, "count": 1},
        },
        "top_by_window": {
            "3D": [
                {
                    "stock_code": "000001.SZ",
                    "stock_name": "平安银行",
                    "state_date": "2026-07-02",
                    "window": "3D",
                    "turning_type": "uncertain",
                    "prob_turn_up": 0.3,
                    "prob_turn_down": 0.2,
                    "prob_continue": 0.45,
                    "prob_false_breakout": 0.05,
                    "confidence": 0.25,
                    "evidence_score": 0.1,
                    "evidence_items": ["D1 强势结构"],
                    "risk_flags": ["低置信"],
                    "source_state_summary": {"d1_state_score": 8},
                    "bucket_sample_size": 10,
                    "prior_weight": 0.1667,
                    "market_regime": "range",
                    "industry_l1": "银行",
                    "model_version": "tpp_mvp_v0.1",
                    "updated_at": "2026-07-02T12:00:00",
                }
            ],
            "3W": [
                {
                    "stock_code": "000001.SZ",
                    "stock_name": "平安银行",
                    "state_date": "2026-07-02",
                    "window": "3W",
                    "turning_type": "turn_up",
                    "prob_turn_up": 0.6,
                    "prob_turn_down": 0.1,
                    "prob_continue": 0.25,
                    "prob_false_breakout": 0.05,
                    "confidence": 0.55,
                    "evidence_score": 0.4,
                    "evidence_items": ["W1 方向偏多"],
                    "risk_flags": [],
                    "source_state_summary": {"w1_state_score": 10},
                    "bucket_sample_size": 100,
                    "prior_weight": 0.6667,
                    "market_regime": "range",
                    "industry_l1": "银行",
                    "model_version": "tpp_mvp_v0.1",
                    "updated_at": "2026-07-02T12:00:00",
                }
            ],
            "3M": [],
            "6M": [],
        },
    }
    return payload


@pytest.fixture
def json_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_json: dict[str, Any]) -> Path:
    """将 reader 指向一个临时 latest JSON。"""
    json_path = tmp_path / "turning_point_probability_latest.json"
    json_path.write_text(json.dumps(sample_json, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(tpp_reader, "LATEST_JSON", json_path)
    # 避免误读到真实 DuckDB
    monkeypatch.setattr(tpp_reader, "OUTPUT_DIR", tmp_path)
    return json_path


@pytest.fixture
def sample_duckdb(tmp_path: Path) -> Path:
    """构造一个最小 DuckDB 产物。"""
    db_path = tmp_path / "turning_point_probability_20260702.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("""
            CREATE TABLE turning_point_probability (
                stock_code VARCHAR,
                stock_name VARCHAR,
                state_date DATE,
                "window" VARCHAR,
                turning_type VARCHAR,
                prob_turn_up DOUBLE,
                prob_turn_down DOUBLE,
                prob_continue DOUBLE,
                prob_false_breakout DOUBLE,
                confidence DOUBLE,
                evidence_score DOUBLE,
                evidence_items VARCHAR,
                risk_flags VARCHAR,
                source_state_summary VARCHAR,
                bucket_sample_size INTEGER,
                prior_weight DOUBLE,
                market_regime VARCHAR,
                industry_l1 VARCHAR,
                future_return_n DOUBLE,
                outcome_label VARCHAR,
                model_version VARCHAR,
                updated_at TIMESTAMP
            )
        """)
        base = {
            "stock_code": "000001.SZ",
            "stock_name": "平安银行",
            "state_date": date(2026, 7, 2),
            "turning_type": "uncertain",
            "prob_turn_up": 0.25,
            "prob_turn_down": 0.25,
            "prob_continue": 0.4,
            "prob_false_breakout": 0.1,
            "confidence": 0.2,
            "evidence_score": 0.05,
            "evidence_items": json.dumps(["D1 强势结构"], ensure_ascii=False),
            "risk_flags": json.dumps(["低置信"], ensure_ascii=False),
            "source_state_summary": json.dumps({"d1_state_score": 8}, ensure_ascii=False),
            "bucket_sample_size": 5,
            "prior_weight": 0.1,
            "market_regime": "range",
            "industry_l1": "银行",
            "future_return_n": None,
            "outcome_label": None,
            "model_version": "tpp_mvp_v0.1",
            "updated_at": "2026-07-02T12:00:00",
        }
        for w in ("3D", "3W", "3M", "6M"):
            rec = dict(base)
            rec["window"] = w
            con.execute(
                """
                INSERT INTO turning_point_probability VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22
                )
                """,
                [
                    rec["stock_code"], rec["stock_name"], rec["state_date"], rec["window"], rec["turning_type"],
                    rec["prob_turn_up"], rec["prob_turn_down"], rec["prob_continue"], rec["prob_false_breakout"],
                    rec["confidence"], rec["evidence_score"], rec["evidence_items"], rec["risk_flags"],
                    rec["source_state_summary"], rec["bucket_sample_size"], rec["prior_weight"], rec["market_regime"],
                    rec["industry_l1"], rec["future_return_n"], rec["outcome_label"], rec["model_version"], rec["updated_at"]
                ],
            )
    finally:
        con.close()
    return db_path


class TestTurningPointProbabilitySummary:
    def test_summary_returns_ok_and_fields(self, json_enabled: Path) -> None:
        client = TestClient(main.app)
        response = client.get("/api/turning-point-probability/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["state_date"] == "2026-07-02"
        assert data["model_version"] == "tpp_mvp_v0.1"
        assert data["row_count"] == 4
        assert data["market_regime"] == "range"
        assert "market_summary" in data
        assert "3W" in data["market_summary"]

    def test_summary_degrades_when_no_json_no_db(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(tpp_reader, "LATEST_JSON", tmp_path / "missing.json")
        monkeypatch.setattr(tpp_reader, "OUTPUT_DIR", tmp_path)
        client = TestClient(main.app)
        response = client.get("/api/turning-point-probability/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["row_count"] == 0
        assert data["market_summary"] == {}
        assert any("尚未生成" in w for w in data["warnings"])


class TestTurningPointProbabilitySignals:
    def test_signals_returns_top_by_window(self, json_enabled: Path) -> None:
        client = TestClient(main.app)
        response = client.get("/api/turning-point-probability/signals?window=3W&limit=5")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["window"] == "3W"
        assert data["count"] == 1
        row = data["signals"][0]
        assert row["stock_code"] == "000001.SZ"
        assert "prob_turn_up" in row
        assert "risk_flags" in row
        assert "bucket_sample_size" in row

    def test_signals_rejects_invalid_window(self, json_enabled: Path) -> None:
        client = TestClient(main.app)
        response = client.get("/api/turning-point-probability/signals?window=1D")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert "window" in data["error"]

    def test_signals_normalizes_window_and_limit(self, json_enabled: Path) -> None:
        client = TestClient(main.app)
        response = client.get("/api/turning-point-probability/signals?window=3w&limit=9999")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["window"] == "3W"
        assert data["limit"] == tpp_reader.MAX_LIMIT

    def test_signals_degrades_to_duckdb(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_duckdb: Path) -> None:
        monkeypatch.setattr(tpp_reader, "LATEST_JSON", tmp_path / "missing.json")
        monkeypatch.setattr(tpp_reader, "OUTPUT_DIR", tmp_path)
        monkeypatch.setattr(tpp_reader, "_latest_duckdb_path", lambda: sample_duckdb)
        client = TestClient(main.app)
        response = client.get("/api/turning-point-probability/signals?window=3D&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["window"] == "3D"
        assert data["count"] == 1
        assert data["signals"][0]["stock_code"] == "000001.SZ"


class TestTurningPointProbabilityStock:
    def test_stock_returns_four_windows(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_duckdb: Path) -> None:
        monkeypatch.setattr(tpp_reader, "LATEST_JSON", tmp_path / "missing.json")
        monkeypatch.setattr(tpp_reader, "OUTPUT_DIR", tmp_path)
        monkeypatch.setattr(tpp_reader, "_latest_duckdb_path", lambda: sample_duckdb)
        client = TestClient(main.app)
        response = client.get("/api/turning-point-probability/stock?stock_code=000001.SZ")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["stock_code"] == "000001.SZ"
        assert data["count"] == 4
        windows = [r["window"] for r in data["rows"]]
        assert windows == ["3D", "3W", "3M", "6M"]

    def test_stock_missing_code(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpp_reader, "OUTPUT_DIR", tmp_path)
        client = TestClient(main.app)
        response = client.get("/api/turning-point-probability/stock")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert "stock_code" in data["error"]

    def test_stock_normalizes_lowercase_code(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_duckdb: Path) -> None:
        monkeypatch.setattr(tpp_reader, "LATEST_JSON", tmp_path / "missing.json")
        monkeypatch.setattr(tpp_reader, "OUTPUT_DIR", tmp_path)
        monkeypatch.setattr(tpp_reader, "_latest_duckdb_path", lambda: sample_duckdb)
        client = TestClient(main.app)
        response = client.get("/api/turning-point-probability/stock?stock_code=000001.sz")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["stock_code"] == "000001.SZ"
        assert data["count"] == 4


class TestResearchOnlyBoundary:
    def test_no_forbidden_words_in_json_response(self, json_enabled: Path) -> None:
        forbidden = {
            "买入", "卖出", "加仓", "减仓", "清仓", "空仓",
            "加杠杆", "止盈", "止损", "目标价", "收益承诺",
            "推荐买", "推荐卖", "适合交易",
        }
        client = TestClient(main.app)
        endpoints = [
            "/api/turning-point-probability/summary",
            "/api/turning-point-probability/signals?window=3W&limit=5",
            "/api/turning-point-probability/stock?stock_code=000001.SZ",
        ]
        for url in endpoints:
            text = json.dumps(client.get(url).json(), ensure_ascii=False)
            found = [w for w in forbidden if w in text]
            assert not found, f"{url} 包含禁用词: {found}"
