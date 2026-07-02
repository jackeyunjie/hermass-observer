"""Tests for agently_adapter.tools.state_timeline_reader.

验收重点：
- 直接复用 web.services.state_timeline_observer，不绕 HTTP
- 不写入 AgentMemory / Observation Ledger
- 返回字段结构稳定，包含 State Timeline 核心字段与变化摘要字段
- filters 透传生效
- watchlist 空结果行为正确
"""

from __future__ import annotations

from agently_adapter.tools.state_timeline_reader import (
    load_state_timeline,
    load_stock_timeline,
    load_top50_timeline,
    load_watchlist_timeline,
)


class TestStateTimelineReader:
    """State Timeline Reader 本地只读接口测试。"""

    def test_load_top50_timeline_returns_rows(self) -> None:
        rows = load_top50_timeline(days=1)
        assert isinstance(rows, list)
        assert len(rows) == 50
        first = rows[0]
        assert "stock_code" in first
        assert "state_date" in first
        assert "mn1_is_ef" in first
        assert "ef_pattern" in first

    def test_load_stock_timeline_returns_rows(self) -> None:
        rows = load_stock_timeline("000001.SZ", days=5)
        assert isinstance(rows, list)
        assert len(rows) >= 1
        for row in rows:
            assert row["stock_code"] == "000001.SZ"

    def test_state_change_fields_present(self) -> None:
        rows = load_stock_timeline("000001.SZ", days=10)
        assert len(rows) >= 1
        first = rows[0]
        assert "state_change_flag" in first
        assert "ef_change" in first
        assert "transition_label" in first
        assert isinstance(first["state_change_flag"], bool)
        earliest = rows[-1]
        assert earliest["transition_label"] == "初始状态"
        assert earliest["state_change_flag"] is False

    def test_watchlist_timeline_empty_for_unknown_user(self) -> None:
        rows = load_watchlist_timeline(user_key="__nonexistent_user__", days=5)
        assert rows == []

    def test_load_state_timeline_with_symbol_list(self) -> None:
        rows = load_state_timeline(symbols="000001.SZ,000002.SZ", days=1)
        codes = {row["stock_code"] for row in rows}
        assert codes <= {"000001.SZ", "000002.SZ"}

    def test_load_state_timeline_empty_for_invalid_symbol(self) -> None:
        """无效代码应返回空列表，而不是抛异常或 500。"""
        rows = load_state_timeline(symbols="INVALID_CODE_XYZ", days=1)
        assert rows == []

    def test_load_state_timeline_filters_passthrough(self) -> None:
        """filters 应透传到查询层，d1_is_ef=True 只返回日线 EF 行。"""
        rows = load_state_timeline(
            symbols="000001.SZ,000002.SZ",
            days=5,
            filters={"d1_is_ef": True},
        )
        assert isinstance(rows, list)
        for row in rows:
            assert row["d1_is_ef"] is True

    def test_load_state_timeline_ef_pattern_filter(self) -> None:
        """ef_pattern_any 透传生效。"""
        rows = load_state_timeline(
            symbol_set="top50",
            days=1,
            filters={"ef_pattern_any": ["MN1+W1+D1", "MN1+W1"]},
        )
        assert isinstance(rows, list)
        for row in rows:
            assert row["ef_pattern"] in ("MN1+W1+D1", "MN1+W1")

    def test_load_state_timeline_fetches_more_than_api_page_cap(self) -> None:
        """SDK 不应被 API 的 500 行分页上限静默截断。"""
        rows = load_top50_timeline(days=30)
        assert len(rows) > 500

    def test_return_structure_stable(self) -> None:
        """返回字段必须包含 State Timeline 核心字段与变化摘要字段。"""
        rows = load_stock_timeline("000001.SZ", days=3)
        assert len(rows) >= 1
        required_fields = {
            "stock_code",
            "state_date",
            "mn1_state_hex",
            "w1_state_hex",
            "d1_state_hex",
            "mn1_is_ef",
            "w1_is_ef",
            "d1_is_ef",
            "mn1_is_ab",
            "w1_is_ab",
            "d1_is_ab",
            "mn1_is_zero",
            "w1_is_zero",
            "d1_is_zero",
            "ef_count",
            "ef_pattern",
            "ab_count",
            "ab_pattern",
            "zero_count",
            "zero_pattern",
            "state_change_flag",
            "ef_change",
            "transition_label",
            "display_alias",
            "close",
            "volume",
            "industry_l1",
        }
        first = rows[0]
        missing = required_fields - set(first.keys())
        assert not missing, f"缺少字段: {missing}"
