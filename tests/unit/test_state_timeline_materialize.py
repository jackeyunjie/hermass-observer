"""Tests for State Timeline Observer materialized table and query switching.

本测试不依赖 HTTP 服务，直接调用 web.services.state_timeline_observer 和
scripts/materialize_state_timeline_daily。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

import web.services.state_timeline_observer as observer
from scripts.materialize_state_timeline_daily import materialize_state_timeline_daily


@pytest.fixture(scope="session")
def materialized_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """生成一张当日的 State Timeline 预计算表，供整个测试会话复用。"""
    output_dir = tmp_path_factory.mktemp("state_timeline")
    result = materialize_state_timeline_daily(output_dir=output_dir)
    assert result.get("ok"), result.get("error")
    return Path(result["output_path"])


@pytest.fixture
def materialized_enabled(monkeypatch: pytest.MonkeyPatch, materialized_db: Path) -> Path:
    """在单个测试中开启物化表开关，并指向测试产物目录。"""
    monkeypatch.setattr(observer, "USE_STATE_TIMELINE_MATERIALIZED", True)
    monkeypatch.setattr(observer, "STATE_TIMELINE_MATERIALIZED_DIR", materialized_db.parent)
    return materialized_db


class TestMaterializeScript:
    """物化脚本本身的功能测试。"""

    def test_materialize_creates_duckdb(self, materialized_db: Path) -> None:
        assert materialized_db.exists()
        assert materialized_db.stat().st_size > 0

    def test_materialized_schema_matches_core_query(self, materialized_db: Path) -> None:
        """物化表字段与 _build_core_query SELECT 输出保持一致。"""
        import duckdb

        con = duckdb.connect(str(materialized_db), read_only=True)
        try:
            columns = {row[0] for row in con.execute("DESCRIBE state_timeline_daily").fetchall()}
        finally:
            con.close()

        required = {
            "stock_code", "stock_name", "industry_l1", "state_date",
            "mn1_state_hex", "w1_state_hex", "d1_state_hex",
            "mn1_state_score", "w1_state_score", "d1_state_score",
            "mn1_is_ef", "w1_is_ef", "d1_is_ef",
            "mn1_is_ab", "w1_is_ab", "d1_is_ab",
            "mn1_is_zero", "w1_is_zero", "d1_is_zero",
            "ef_count", "ef_pattern",
            "ab_count", "ab_pattern",
            "zero_count", "zero_pattern",
            "state_triplet",
            "state_change_flag", "ef_change", "transition_label",
            "close", "volume", "as_of_date", "display_alias",
        }
        missing = required - columns
        assert not missing, f"物化表缺少字段: {missing}"

    def test_materialized_has_indexes(self, materialized_db: Path) -> None:
        import duckdb

        con = duckdb.connect(str(materialized_db), read_only=True)
        try:
            indexes = {row[0] for row in con.execute("SELECT index_name FROM duckdb_indexes()").fetchall()}
        finally:
            con.close()

        required = {
            "idx_stock_date", "idx_state_date", "idx_industry",
            "idx_ef_pattern", "idx_ab_pattern", "idx_zero_pattern",
        }
        missing = required - indexes
        assert not missing, f"物化表缺少索引: {missing}"


class TestMaterializedQuerySwitch:
    """查询服务在物化表与实时 CTE 之间切换的行为测试。"""

    def test_query_uses_materialized_when_switch_on(self, materialized_enabled: Path) -> None:
        result = observer.query_state_timeline(symbols="all", days=1, page_size=5)
        assert result["ok"] is True
        assert len(result["rows"]) == 5
        assert result["meta"]["row_count"] > 0
        first = result["rows"][0]
        assert "display_alias" in first
        assert "state_change_flag" in first

    def test_materialized_filters_work(self, materialized_enabled: Path) -> None:
        result = observer.query_state_timeline(
            symbols="all",
            days=1,
            filters={"d1_is_ef": True},
            page_size=100,
        )
        assert result["ok"] is True
        assert len(result["rows"]) > 0
        for row in result["rows"]:
            assert row["d1_is_ef"] is True

    def test_materialized_explicit_symbols(self, materialized_enabled: Path) -> None:
        result = observer.query_state_timeline(
            symbols="000001.SZ",
            days=1,
        )
        assert result["ok"] is True
        assert len(result["rows"]) == 1
        assert result["rows"][0]["stock_code"] == "000001.SZ"

    def test_materialized_csv_format(self, materialized_enabled: Path) -> None:
        result = observer.query_state_timeline(
            symbols="000001.SZ",
            days=1,
            format="csv",
        )
        assert result["ok"] is True
        assert "csv" in result
        assert "stock_code" in result["csv"]
        assert "display_alias" in result["csv"]

    def test_query_falls_back_for_multi_day_range(self, monkeypatch: pytest.MonkeyPatch, materialized_enabled: Path) -> None:
        """物化表只有单日数据，跨天查询应 fallback 到实时 CTE。"""
        result = observer.query_state_timeline(symbols="all", days=3, page_size=5)
        assert result["ok"] is True
        assert result["meta"]["row_count"] > len(result["rows"])

    def test_query_falls_back_when_no_materialized_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """开关打开但产物目录为空时，应 fallback 到实时 CTE 且不报错。"""
        monkeypatch.setattr(observer, "USE_STATE_TIMELINE_MATERIALIZED", True)
        empty_dir = Path(__file__).resolve().parents[2] / "outputs" / "state_timeline_nonexistent"
        monkeypatch.setattr(observer, "STATE_TIMELINE_MATERIALIZED_DIR", empty_dir)

        result = observer.query_state_timeline(symbols="all", days=1, page_size=5)
        assert result["ok"] is True
        assert len(result["rows"]) == 5

    def test_materialized_watchlist_empty_does_not_fall_back_to_all_market(
        self,
        monkeypatch: pytest.MonkeyPatch,
        materialized_enabled: Path,
    ) -> None:
        monkeypatch.setattr(observer, "_resolve_watchlist_codes", lambda user_key: [])

        result = observer.query_state_timeline(
            symbol_set="watchlist",
            days=1,
            user_key="visitor_without_watchlist",
            page_size=5,
        )
        assert result["ok"] is True
        assert result["meta"]["row_count"] == 0
        assert result["meta"]["symbol_count"] == 0
        assert result["rows"] == []


class TestSwitchDefault:
    """验证默认启用策略与回退行为。"""

    def test_default_switch_is_on(self) -> None:
        # Phase 2D 后默认启用智能 auto（未设置环境变量时默认为 True）
        assert observer.USE_STATE_TIMELINE_MATERIALIZED is True

    def test_default_query_auto_fallback_when_no_materialized_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 默认启用但本地无对应物化文件时，应自动回退实时 CTE 并给出原因
        monkeypatch.setattr(observer, "STATE_TIMELINE_MATERIALIZED_DIR", Path("/nonexistent_state_timeline"))
        result = observer.query_state_timeline(symbols="all", days=1, page_size=5)
        assert result["ok"] is True
        assert len(result["rows"]) == 5
        assert result["meta"]["materialized_used"] is False
        assert result["meta"]["materialized_reason"] == "auto_fallback_missing_file"
        assert result["meta"]["materialized_requested"] is None
