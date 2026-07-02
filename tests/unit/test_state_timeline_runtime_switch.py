"""Tests for State Timeline Observer runtime materialized switch and default policy.

验证：
- 默认 auto 策略：单日 + 物化文件存在 -> 物化表；否则回退 CTE
- 显式 materialized=True 强制使用物化表，不可用时报错（不回退）
- 显式 materialized=False 强制使用实时 CTE
- 返回结果包含 materialized_requested / used / reason
- /api/admin/data-sync-status 暴露完整物化表状态
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

import web.services.state_timeline_observer as observer
from scripts.materialize_state_timeline_daily import materialize_state_timeline_daily
from web.main import _parse_tri_state_param, _state_timeline_materialized_status
import web.main as web_main


@pytest.fixture(scope="session")
def materialized_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """生成一张当日的 State Timeline 预计算表。"""
    output_dir = tmp_path_factory.mktemp("state_timeline")
    result = materialize_state_timeline_daily(output_dir=output_dir)
    assert result.get("ok"), result.get("error")
    return Path(result["output_path"])


@pytest.fixture
def materialized_dir(monkeypatch: pytest.MonkeyPatch, materialized_db: Path) -> Path:
    """在测试中指向测试产物目录。"""
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


class TestDefaultPolicy:
    """默认启用策略（materialized=None）测试。"""

    def test_default_uses_materialized_for_single_day(
        self,
        monkeypatch: pytest.MonkeyPatch,
        materialized_dir: Path,
    ) -> None:
        """默认策略：单日 + 文件存在 -> 使用物化表。"""
        monkeypatch.setattr(observer, "USE_STATE_TIMELINE_MATERIALIZED", True)

        result = observer.query_state_timeline(symbols="000001.SZ", days=1)
        assert result["ok"] is True
        assert result["meta"]["materialized_used"] is True
        assert result["meta"]["materialized_reason"] == "auto_single_day_hit"
        assert result["meta"]["materialized_requested"] is None

    def test_default_fallback_for_multi_day(
        self,
        monkeypatch: pytest.MonkeyPatch,
        materialized_dir: Path,
    ) -> None:
        """默认策略：跨天查询 -> 自动回退实时 CTE。"""
        monkeypatch.setattr(observer, "USE_STATE_TIMELINE_MATERIALIZED", True)

        result = observer.query_state_timeline(symbols="000001.SZ", days=3, page_size=5)
        assert result["ok"] is True
        assert result["meta"]["materialized_used"] is False
        assert result["meta"]["materialized_reason"] == "auto_fallback_multi_day"

    def test_default_disabled_by_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        materialized_dir: Path,
    ) -> None:
        """环境变量关闭时，默认策略不使用物化表。"""
        monkeypatch.setattr(observer, "USE_STATE_TIMELINE_MATERIALIZED", False)

        result = observer.query_state_timeline(symbols="000001.SZ", days=1)
        assert result["ok"] is True
        assert result["meta"]["materialized_used"] is False
        assert result["meta"]["materialized_reason"] == "auto_env_disabled"

    def test_default_fallback_when_file_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """物化文件缺失时，默认策略回退实时 CTE。"""
        monkeypatch.setattr(observer, "USE_STATE_TIMELINE_MATERIALIZED", True)
        monkeypatch.setattr(observer, "STATE_TIMELINE_MATERIALIZED_DIR", Path("/nonexistent"))

        result = observer.query_state_timeline(symbols="000001.SZ", days=1)
        assert result["ok"] is True
        assert result["meta"]["materialized_used"] is False
        assert result["meta"]["materialized_reason"] == "auto_fallback_missing_file"


class TestExplicitForce:
    """显式强制开关测试。"""

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
        assert result["meta"]["materialized_used"] is True
        assert result["meta"]["materialized_reason"] == "force_on_hit"
        assert result["meta"]["materialized_requested"] is True

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
        assert result["meta"]["materialized_used"] is False
        assert result["meta"]["materialized_reason"] == "force_off"
        assert result["meta"]["materialized_requested"] is False

    def test_explicit_true_errors_on_multi_day(
        self,
        monkeypatch: pytest.MonkeyPatch,
        materialized_dir: Path,
    ) -> None:
        """materialized=True 跨天查询应报错，不回退。"""
        monkeypatch.setattr(observer, "USE_STATE_TIMELINE_MATERIALIZED", True)

        result = observer.query_state_timeline(
            symbols="000001.SZ",
            days=3,
            materialized=True,
        )
        assert result["ok"] is False
        assert "materialized=True 仅支持单日查询" in result["error"]

    def test_explicit_true_errors_when_file_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """materialized=True 但文件缺失时应报错，不回退。"""
        monkeypatch.setattr(observer, "USE_STATE_TIMELINE_MATERIALIZED", True)
        monkeypatch.setattr(observer, "STATE_TIMELINE_MATERIALIZED_DIR", Path("/nonexistent"))

        result = observer.query_state_timeline(
            symbols="000001.SZ",
            days=1,
            materialized=True,
        )
        assert result["ok"] is False
        assert "物化文件不存在" in result["error"]

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
        assert result["meta"]["materialized_used"] is True


class TestDataSyncStatus:
    """data-sync-status 接口扩展测试。"""

    def test_data_sync_status_includes_materialized(
        self,
        monkeypatch: pytest.MonkeyPatch,
        materialized_dir: Path,
        materialized_db: Path,
    ) -> None:
        monkeypatch.setattr(observer, "USE_STATE_TIMELINE_MATERIALIZED", True)

        date_str = materialized_db.stem.split("_")[-1]
        normalized = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

        status = _state_timeline_materialized_status(normalized)
        assert status["exists"] is True
        assert status["row_count"] > 0
        assert status["healthy"] is True
        assert status["date"] == normalized
        assert status["enabled_by_default"] is True
        assert status["auto_would_use"] is True

    def test_data_sync_status_when_env_disabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
        materialized_dir: Path,
        materialized_db: Path,
    ) -> None:
        monkeypatch.setattr(web_main, "USE_STATE_TIMELINE_MATERIALIZED", False)

        date_str = materialized_db.stem.split("_")[-1]
        normalized = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

        status = _state_timeline_materialized_status(normalized)
        assert status["exists"] is True
        assert status["enabled_by_default"] is False
        assert status["auto_would_use"] is False

    def test_data_sync_status_missing_materialized(self) -> None:
        status = _state_timeline_materialized_status("2099-12-31")
        assert status["exists"] is False
        assert status["row_count"] == 0
        assert status["healthy"] is False
        assert status["date"] == "2099-12-31"
        assert status["auto_would_use"] is False
