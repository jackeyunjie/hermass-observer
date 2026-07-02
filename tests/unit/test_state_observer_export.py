"""Tests for State Timeline Observer async export worker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from web.services.state_timeline_export_worker import (
    ASYNC_ROW_THRESHOLD,
    ROOT,
    create_export_task,
    get_output_path,
    get_task_status,
    should_export_async,
)

EXPORT_DIR = ROOT / "outputs" / "state_timeline_exports"


class TestStateObserverExport:
    """State Timeline 异步导出单元测试。"""

    def test_should_export_async_all_market_csv(self) -> None:
        query = {"symbols": "all", "format": "csv"}
        assert should_export_async(query, 100) is True

    def test_should_export_async_large_rows(self) -> None:
        query = {"symbols": "000001.SZ", "format": "csv"}
        assert should_export_async(query, ASYNC_ROW_THRESHOLD + 1) is True

    def test_should_export_async_force_async(self) -> None:
        query = {"symbols": "000001.SZ", "format": "csv", "async": 1}
        assert should_export_async(query, 1) is True

    def test_should_export_sync_small_query(self) -> None:
        query = {"symbols": "000001.SZ", "format": "csv"}
        assert should_export_async(query, 10) is False

    def test_create_export_task_sync_response(self) -> None:
        result = create_export_task({"symbols": "000001.SZ", "days": 1, "format": "csv"})
        assert result["ok"] is True
        assert result["status"] == "sync"
        assert result["task_id"] == ""
        assert result["download_path"] == ""
        assert result["estimated_rows"] >= 0

    def test_create_export_task_async_response(self) -> None:
        # 全市场 120 天一定走异步
        result = create_export_task({"symbols": "all", "days": 120, "format": "csv"})
        assert result["ok"] is True
        assert result["status"] == "queued"
        assert result["task_id"].startswith("state_timeline_export_")
        assert "/api/state-observer/export/" in result["download_path"]
        assert result["estimated_rows"] > ASYNC_ROW_THRESHOLD

    def test_task_status_roundtrip(self) -> None:
        result = create_export_task({"symbols": "all", "days": 120, "format": "csv"})
        task_id = result["task_id"]

        status = get_task_status(task_id)
        assert status is not None
        assert status["task_id"] == task_id
        assert status["status"] in ("queued", "running", "completed")
        assert status["format"] == "csv"

    def test_output_path_exists_after_create(self) -> None:
        result = create_export_task({"symbols": "all", "days": 120, "format": "csv"})
        task_id = result["task_id"]
        path = get_output_path(task_id)
        assert path is not None
        assert path.name == f"{task_id}.csv"

    def test_task_log_jsonl_appended(self) -> None:
        task_log = EXPORT_DIR / "task_log.jsonl"
        before = task_log.read_text(encoding="utf-8").count("\n") if task_log.exists() else 0
        create_export_task({"symbols": "all", "days": 120, "format": "csv"})
        after = task_log.read_text(encoding="utf-8").count("\n")
        assert after > before
