"""Tests for State Timeline Observer runtime materialized switch.

验证：
- materialized=True 强制使用物化表
- materialized=False 强制使用实时 CTE
- 默认行为遵循环境变量
- /api/admin/data-sync-status 暴露物化表状态
"""

from __future__ import annotations

from pathlib import Path

import pytest

import web.services.state_timeline_observer as observer
from scripts.materialize_state_timeline_daily import materialize_state_timeline_daily
from web.main import _parse_tri_state_param


@pytest.fixture(scope="session")
def materialized_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """生成一张当日的 State Timeline 预计算表。"""
    output_dir = tmp_path_factory.mktemp("state_timeline")
    result = materialize_state_timeline_daily(output_dir=output_dir)
    assert result.get("ok"), result.get("error")
    return Path(result["output_path"])


@pytest.fixture
def materialized_dir(monkeypatch: pytest.MonkeyPatch, materialized_db: Path) -> Path:
    """在测试中启用物化表并指向测试产物目录。"""
    monkeypatch.setattr(observer, "STATE_TIMELINE_MATERIALIZED_DIR", materialized_db.parent)
    return materialized_db.parent


class TestTriStateParam:
    """三态参数解析器测试。"""

    def test_parse_true_values(self) -> None:
        for value in ("1", "true", "True", "TRUE", "yes", "on"):
            assert _parse_tri_state_param(value) is True

    def test_parse_false_values(self) -> None:
        for value in ("0", "false", "False", "FALSE", "no", "off"):
            assert _parse_tri_state_param(value) is False

    def test_parse_none_values(self) -> None:
        for value in (None, "", "maybe", "2", "foo"):
            assert _parse_tri_state_param(value) is None


class TestRuntimeSwitch:
    """运行时开关语义测试。"""

    def test_materialized_forces_on_when_env_off(
        self,
        monkeypatch: pytest.MonkeyPatch,
        materialized_dir: Path,
    ) -> None:
        """环境变量关闭时，materialized=True 仍能命中物化表。"""
        monkeypatch.setattr(observer, "USE_STATE_TIMELINE_MATERIALIZED", False)

        result = observer.query_state_timeline(
            symbols="000001.SZ",
            days=1,
            materialized=True,
        )
        assert result["ok"] is True
        assert len(result["rows"]) == 1
        assert result["rows"][0]["stock_code"] == "000001.SZ"
        assert result["meta"]["date_max"] in result["rows"][0]["state_date"]

    def test_materialized_forces_off_when_env_on(
        self,
        monkeypatch: pytest.MonkeyPatch,
        materialized_dir: Path,
    ) -> None:
        """环境变量打开时，materialized=False 强制走实时 CTE。"""
        monkeypatch.setattr(observer, "USE_STATE_TIMELINE_MATERIALIZED", True)

        result = observer.query_state_timeline(
            symbols="000001.SZ",
            days=1,
            materialized=False,
        )
        assert result["ok"] is True
        assert len(result["rows"]) == 1
        assert result["rows"][0]["stock_code"] == "000001.SZ"

    def test_default_uses_env_var_when_off(
        self,
        monkeypatch: pytest.MonkeyPatch,
        materialized_dir: Path,
    ) -> None:
        monkeypatch.setattr(observer, "USE_STATE_TIMELINE_MATERIALIZED", False)

        result = observer.query_state_timeline(
            symbols="000001.SZ",
            days=1,
        )
        assert result["ok"] is True
        assert len(result["rows"]) == 1

    def test_default_uses_env_var_when_on(
        self,
        monkeypatch: pytest.MonkeyPatch,
        materialized_dir: Path,
    ) -> None:
        monkeypatch.setattr(observer, "USE_STATE_TIMELINE_MATERIALIZED", True)

        result = observer.query_state_timeline(
            symbols="000001.SZ",
            days=1,
        )
        assert result["ok"] is True
        assert len(result["rows"]) == 1

    def test_stock_timeline_passes_materialized_flag(
        self,
        monkeypatch: pytest.MonkeyPatch,
        materialized_dir: Path,
    ) -> None:
        """query_stock_timeline 能把 materialized 参数透传下去。"""
        monkeypatch.setattr(observer, "USE_STATE_TIMELINE_MATERIALIZED", False)

        result = observer.query_stock_timeline(
            stock_code="000001.SZ",
            days=1,
            materialized=True,
        )
        assert result["ok"] is True
        assert len(result["rows"]) == 1


class TestDataSyncStatus:
    """data-sync-status 接口扩展测试。"""

    def test_data_sync_status_includes_materialized(
        self,
        monkeypatch: pytest.MonkeyPatch,
        materialized_dir: Path,
        materialized_db: Path,
    ) -> None:
        from web.main import _state_timeline_materialized_status

        date_str = materialized_db.stem.split("_")[-1]
        normalized = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

        status = _state_timeline_materialized_status(normalized)
        assert status["exists"] is True
        assert status["row_count"] > 0
        assert status["date"] == normalized
        assert "use_env_switch" in status

    def test_data_sync_status_missing_materialized(self) -> None:
        from web.main import _state_timeline_materialized_status

        status = _state_timeline_materialized_status("2099-12-31")
        assert status["exists"] is False
        assert status["row_count"] == 0
        assert status["date"] == "2099-12-31"
