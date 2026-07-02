"""Tests for State Timeline Observer async export worker."""

from __future__ import annotations

import json
import multiprocessing
import time
from pathlib import Path

import web.services.state_timeline_export_worker as export_worker
from web.services.state_timeline_export_worker import (
    ASYNC_ROW_THRESHOLD,
    EXPORT_DIR,
    ROOT,
    _advance_task_record,
    _append_task_record,
    _build_sync_url,
    _is_valid_transition,
    _read_latest_record,
    clean_old_exports,
    create_export_task,
    get_output_path,
    get_task_status,
    mark_task_expired,
    should_export_async,
)


def _write_test_record(tmp_path: Path, task_id: str, status: str = "queued") -> None:
    """写入一条测试任务记录。"""
    log = tmp_path / "task_log.jsonl"
    record = {
        "task_id": task_id,
        "status": status,
        "format": "csv",
        "query": {"symbol_set": "watchlist", "days": 5, "filters": {}},
        "estimated_rows": 100,
        "output_path": str(Path("outputs") / "state_timeline_exports" / f"{task_id}.csv"),
        "row_count": 0,
        "error": "",
        "owner_key": "visitor_test",
        "owner_scope": "guest",
        "created_at": "2026-07-01T00:00:00+00:00",
        "finished_at": "",
    }
    log.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")


def _append_test_record_worker(args: tuple[Path, int]) -> int:
    """多进程并发测试用：向指定 TASK_LOG 追加一条记录。"""
    log_path, index = args
    # 在子进程中重新注入 monkeypatch 后的 TASK_LOG
    export_worker.TASK_LOG = log_path
    _append_task_record({
        "task_id": f"test_task_{index:04d}",
        "status": "queued",
        "seq": index,
    })
    return index


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

    def test_build_sync_url_preserves_materialized_choice(self) -> None:
        url = _build_sync_url({"symbols": "000001.SZ", "format": "csv", "materialized": False})
        assert "materialized=0" in url

    def test_create_export_task_passes_materialized_to_row_estimate(self, monkeypatch) -> None:
        seen: list[dict] = []

        def fake_query_state_timeline(**kwargs):
            seen.append(kwargs)
            return {"ok": True, "meta": {"row_count": 1}}

        monkeypatch.setattr(export_worker, "query_state_timeline", fake_query_state_timeline)
        result = create_export_task(
            {"symbols": "000001.SZ", "days": 1, "format": "csv", "materialized": True}
        )

        assert result["status"] == "sync"
        assert seen
        assert seen[0]["materialized"] is True


class TestTaskLogConcurrency:
    """任务日志并发安全测试。"""

    def test_concurrent_appends_do_not_corrupt_jsonl(self, tmp_path, monkeypatch):
        """多进程并发追加不应损坏 JSONL。"""
        log_path = tmp_path / "task_log.jsonl"
        monkeypatch.setattr(export_worker, "TASK_LOG", log_path)

        count = 20
        # 必须在 if __name__ == "__main__" 保护的模块中运行多进程
        with multiprocessing.Pool(processes=4) as pool:
            pool.map(_append_test_record_worker, [(log_path, i) for i in range(count)])

        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        # 去除可能的空行
        lines = [line for line in lines if line.strip()]
        assert len(lines) == count

        seen_seq = set()
        for line in lines:
            record = json.loads(line)
            assert record["status"] == "queued"
            seen_seq.add(record["seq"])
        assert seen_seq == set(range(count))


class TestStateMachine:
    """任务状态机测试。"""

    def test_valid_transitions(self) -> None:
        assert _is_valid_transition("queued", "running") is True
        assert _is_valid_transition("queued", "failed") is True
        assert _is_valid_transition("running", "completed") is True
        assert _is_valid_transition("running", "failed") is True
        assert _is_valid_transition("completed", "expired") is True

    def test_invalid_transitions(self) -> None:
        assert _is_valid_transition("queued", "completed") is False
        assert _is_valid_transition("completed", "failed") is False
        assert _is_valid_transition("failed", "completed") is False
        assert _is_valid_transition("expired", "completed") is False

    def test_advance_task_record_advances_state(self, tmp_path, monkeypatch):
        task_id = "test_advance_001"
        _write_test_record(tmp_path, task_id, "queued")
        monkeypatch.setattr(export_worker, "TASK_LOG", tmp_path / "task_log.jsonl")

        result = _advance_task_record(task_id, "running")
        assert result is not None
        assert result["status"] == "running"

        latest = _read_latest_record(task_id)
        assert latest["status"] == "running"

    def test_advance_task_record_rejects_invalid_transition(self, tmp_path, monkeypatch):
        task_id = "test_advance_002"
        _write_test_record(tmp_path, task_id, "failed")
        monkeypatch.setattr(export_worker, "TASK_LOG", tmp_path / "task_log.jsonl")

        result = _advance_task_record(task_id, "completed")
        assert result is None


class TestExpiredStatus:
    """产物清理后状态一致性测试。"""

    def test_get_task_status_expired_when_file_missing(self, tmp_path, monkeypatch):
        task_id = "test_expired_001"
        _write_test_record(tmp_path, task_id, "completed")
        monkeypatch.setattr(export_worker, "TASK_LOG", tmp_path / "task_log.jsonl")

        status = get_task_status(task_id)
        assert status is not None
        assert status["status"] == "expired"
        assert status["file_present"] is False
        assert status["download_path"] == ""

    def test_get_task_status_completed_when_file_present(self, tmp_path, monkeypatch):
        task_id = "test_expired_002"
        _write_test_record(tmp_path, task_id, "completed")

        # 将项目根路径 monkeypatch 到 tmp_path，使相对 output_path 解析到 tmp_path 下
        monkeypatch.setattr(export_worker, "ROOT", tmp_path)
        monkeypatch.setattr(export_worker, "EXPORT_DIR", tmp_path / "outputs" / "state_timeline_exports")
        monkeypatch.setattr(export_worker, "TASK_LOG", tmp_path / "task_log.jsonl")

        real_output = tmp_path / "outputs" / "state_timeline_exports" / f"{task_id}.csv"
        real_output.parent.mkdir(parents=True, exist_ok=True)
        real_output.write_text("col\nval\n", encoding="utf-8")

        status = get_task_status(task_id)
        assert status is not None
        assert status["status"] == "completed"
        assert status["file_present"] is True
        assert status["download_path"] != ""

    def test_mark_task_expired(self, tmp_path, monkeypatch):
        task_id = "test_expired_003"
        _write_test_record(tmp_path, task_id, "completed")
        monkeypatch.setattr(export_worker, "TASK_LOG", tmp_path / "task_log.jsonl")

        result = mark_task_expired(task_id, reason="test_cleanup")
        assert result["ok"] is True
        assert result["task"]["status"] == "expired"
        assert result["task"]["expired_reason"] == "test_cleanup"

        latest = _read_latest_record(task_id)
        assert latest["status"] == "expired"

    def test_mark_task_expired_idempotent(self, tmp_path, monkeypatch):
        task_id = "test_expired_004"
        _write_test_record(tmp_path, task_id, "expired")
        monkeypatch.setattr(export_worker, "TASK_LOG", tmp_path / "task_log.jsonl")

        result = mark_task_expired(task_id)
        assert result["ok"] is True
        assert result["task"]["status"] == "expired"


class TestCleanup:
    """产物清理脚本测试。"""

    def test_clean_old_exports_deletes_and_marks_expired(self, tmp_path, monkeypatch):
        task_id = "state_timeline_export_20260601_old0001"
        _write_test_record(tmp_path, task_id, "completed")
        monkeypatch.setattr(export_worker, "TASK_LOG", tmp_path / "task_log.jsonl")

        export_dir = tmp_path / "state_timeline_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(export_worker, "EXPORT_DIR", export_dir)

        output_path = export_dir / f"{task_id}.csv"
        output_path.write_text("col\nval\n", encoding="utf-8")

        # 将文件修改时间改到 10 天前
        old_mtime = time.time() - 10 * 24 * 3600
        output_path.touch()
        import os
        os.utime(output_path, (old_mtime, old_mtime))

        result = clean_old_exports(retention_days=7)
        assert output_path.name in result["deleted"]
        assert task_id in result["expired_tasks"]
        assert not output_path.exists()

        latest = _read_latest_record(task_id)
        assert latest["status"] == "expired"

    def test_clean_old_exports_skips_running_tasks(self, tmp_path, monkeypatch):
        task_id = "state_timeline_export_20260601_run0001"
        _write_test_record(tmp_path, task_id, "running")
        monkeypatch.setattr(export_worker, "TASK_LOG", tmp_path / "task_log.jsonl")

        export_dir = tmp_path / "state_timeline_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(export_worker, "EXPORT_DIR", export_dir)

        output_path = export_dir / f"{task_id}.csv"
        output_path.write_text("col\nval\n", encoding="utf-8")

        old_mtime = time.time() - 10 * 24 * 3600
        output_path.touch()
        import os
        os.utime(output_path, (old_mtime, old_mtime))

        result = clean_old_exports(retention_days=7)
        assert output_path.name not in result["deleted"]
        assert task_id not in result["expired_tasks"]
        assert output_path.exists()

    def test_clean_old_exports_keeps_recent_files(self, tmp_path, monkeypatch):
        task_id = "state_timeline_export_20260701_new0001"
        _write_test_record(tmp_path, task_id, "completed")
        monkeypatch.setattr(export_worker, "TASK_LOG", tmp_path / "task_log.jsonl")

        export_dir = tmp_path / "state_timeline_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(export_worker, "EXPORT_DIR", export_dir)

        output_path = export_dir / f"{task_id}.csv"
        output_path.write_text("col\nval\n", encoding="utf-8")

        result = clean_old_exports(retention_days=7)
        assert output_path.name not in result["deleted"]
        assert task_id not in result["expired_tasks"]
        assert output_path.exists()
