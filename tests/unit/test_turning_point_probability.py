"""Tests for build_turning_point_probability MVP script."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from scripts.build_turning_point_probability import (
    WINDOW_CONFIG,
    build_turning_point_probability,
)


@pytest.fixture
def synthetic_state_cube(tmp_path: Path) -> Path:
    """构造一个最小可用的 state_cube DuckDB 用于测试。"""
    db_path = tmp_path / "state_cube.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("""
            CREATE TABLE state_cube (
                stock_code VARCHAR,
                state_date DATE,
                mn1_state_hex VARCHAR,
                w1_state_hex VARCHAR,
                d1_state_hex VARCHAR,
                mn1_state_score INTEGER,
                w1_state_score INTEGER,
                d1_state_score INTEGER,
                ef_count INTEGER,
                d1_adx14 DOUBLE,
                d1_bb20_width DOUBLE,
                d1_close DOUBLE,
                w1_close DOUBLE,
                m30_close DOUBLE,
                m30_breakout_signal VARCHAR,
                m30_price_breakout DOUBLE,
                w1_bb20_position DOUBLE,
                d1_bb20_position DOUBLE
            )
        """)

        start = date(2026, 1, 1)
        current = date(2026, 7, 2)
        rows: list[tuple] = []
        price_a = 100.0
        price_b = 100.0
        d = start
        while d <= current:
            # 股票 A：持续上涨，用于产生 turn_up 历史样本
            rows.append((
                "A000001.SZ", d, "8", "5", "8",
                2, 5, 8, 1,
                25.0, 0.03, price_a, price_a, price_a,
                None, None, 0.5, 0.5,
            ))
            price_a *= 1.01

            # 股票 B：持续下跌，用于产生 turn_down 历史样本
            rows.append((
                "B000002.SZ", d, "-5", "-3", "-6",
                -2, -3, -6, 0,
                18.0, 0.04, price_b, price_b, price_b,
                None, None, -0.3, -0.3,
            ))
            price_b *= 0.995
            d += timedelta(days=1)

        con.executemany(
            """
            INSERT INTO state_cube VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15, $16, $17, $18
            )
            """,
            rows,
        )

        # 额外插入一只仅在当前日期出现、历史样本极少的标的 C
        con.execute(
            """
            INSERT INTO state_cube VALUES (
                'C000003.SZ', '2026-07-02', 'C', 'B', 'E',
                14, 10, 14, 2,
                12.0, 0.01, 50.0, 50.0, 50.0,
                'false_up', 1.5, 0.8, 0.8
            )
            """
        )
    finally:
        con.close()
    return db_path


def _query_records(db_path: Path) -> list[dict[str, Any]]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        columns = [d[0] for d in con.execute("DESCRIBE turning_point_probability").fetchall()]
        rows = con.execute("SELECT * FROM turning_point_probability").fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        con.close()


class TestTurningPointProbabilityScript:
    def test_generates_duckdb_and_json(self, synthetic_state_cube: Path, tmp_path: Path) -> None:
        result = build_turning_point_probability(
            target_date=date(2026, 7, 2),
            state_cube_path=synthetic_state_cube,
            output_dir=tmp_path,
        )
        assert result["ok"]
        assert Path(result["duckdb_path"]).exists()
        assert Path(result["json_path"]).exists()
        assert result["row_count"] > 0

    def test_four_windows_present(self, synthetic_state_cube: Path, tmp_path: Path) -> None:
        result = build_turning_point_probability(
            target_date=date(2026, 7, 2),
            state_cube_path=synthetic_state_cube,
            output_dir=tmp_path,
        )
        records = _query_records(Path(result["duckdb_path"]))
        windows = {r["window"] for r in records}
        assert windows == set(WINDOW_CONFIG)
        # A、B、C 三只标的 × 4 个窗口 = 12 行
        assert len(records) == 12

    def test_probability_fields_in_range(self, synthetic_state_cube: Path, tmp_path: Path) -> None:
        result = build_turning_point_probability(
            target_date=date(2026, 7, 2),
            state_cube_path=synthetic_state_cube,
            output_dir=tmp_path,
        )
        records = _query_records(Path(result["duckdb_path"]))
        for r in records:
            for field in ("prob_turn_up", "prob_turn_down", "prob_continue", "prob_false_breakout", "confidence"):
                assert 0.0 <= r[field] <= 1.0, f"{field}={r[field]} out of range"

    def test_probabilities_sum_to_one(self, synthetic_state_cube: Path, tmp_path: Path) -> None:
        result = build_turning_point_probability(
            target_date=date(2026, 7, 2),
            state_cube_path=synthetic_state_cube,
            output_dir=tmp_path,
        )
        records = _query_records(Path(result["duckdb_path"]))
        for r in records:
            s = r["prob_turn_up"] + r["prob_turn_down"] + r["prob_continue"] + r["prob_false_breakout"]
            assert abs(s - 1.0) < 0.01, f"probabilities sum to {s}"

    def test_confidence_capped_when_low_sample(self, synthetic_state_cube: Path, tmp_path: Path) -> None:
        result = build_turning_point_probability(
            target_date=date(2026, 7, 2),
            state_cube_path=synthetic_state_cube,
            output_dir=tmp_path,
        )
        records = _query_records(Path(result["duckdb_path"]))
        low_sample_records = [r for r in records if r["bucket_sample_size"] < 30]
        assert low_sample_records, "expected at least one low-sample record (stock C)"
        for r in low_sample_records:
            assert r["confidence"] <= 0.5, f"low-sample confidence {r['confidence']} exceeds 0.5"

    def test_json_does_not_expose_forbidden_words(self, synthetic_state_cube: Path, tmp_path: Path) -> None:
        result = build_turning_point_probability(
            target_date=date(2026, 7, 2),
            state_cube_path=synthetic_state_cube,
            output_dir=tmp_path,
        )
        text = Path(result["json_path"]).read_text(encoding="utf-8")
        forbidden = {
            "买入", "卖出", "加仓", "减仓", "清仓", "空仓",
            "加杠杆", "止盈", "止损", "目标价", "收益承诺",
        }
        found = [w for w in forbidden if w in text]
        assert not found, f"JSON 包含禁用词: {found}"
        # 回填字段 future_return_n / outcome_label 不应出现在默认 JSON
        assert "future_return_n" not in text
        assert "outcome_label" not in text

    def test_fundamental_missing_does_not_fail(self, synthetic_state_cube: Path, tmp_path: Path) -> None:
        result = build_turning_point_probability(
            target_date=date(2026, 7, 2),
            state_cube_path=synthetic_state_cube,
            output_dir=tmp_path,
        )
        assert result["ok"]
        records = _query_records(Path(result["duckdb_path"]))
        assert records

    def test_empty_output_when_state_cube_and_foundation_missing(self, tmp_path: Path) -> None:
        result = build_turning_point_probability(
            target_date=date(2026, 7, 2),
            state_cube_path=tmp_path / "nonexistent_state_cube.duckdb",
            foundation_path=tmp_path / "nonexistent_foundation.duckdb",
            output_dir=tmp_path,
        )
        assert result["ok"]
        assert result["row_count"] == 0
        assert Path(result["duckdb_path"]).exists()

    def test_meta_in_latest_json(self, synthetic_state_cube: Path, tmp_path: Path) -> None:
        result = build_turning_point_probability(
            target_date=date(2026, 7, 2),
            state_cube_path=synthetic_state_cube,
            output_dir=tmp_path,
        )
        payload = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
        assert payload["meta"]["state_date"] == "2026-07-02"
        assert payload["meta"]["model_version"].startswith("tpp_mvp")
        assert set(payload["market_summary"]) == set(WINDOW_CONFIG)
        for w in WINDOW_CONFIG:
            assert w in payload["top_by_window"]
