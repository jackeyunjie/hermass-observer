"""State Timeline Observer 异步导出任务工作线程。

提供后台 CSV/Parquet 导出能力：
- 任务日志落地到 outputs/state_timeline_exports/task_log.jsonl
- 产物保存到 outputs/state_timeline_exports/
- 不引入 Celery/Redis，使用 threading 后台线程
- 小查询仍走同步（由调用方决定）
- task_log.jsonl 使用文件锁（fcntl）+ threading.Lock，单机多进程安全

使用方式：
    from web.services.state_timeline_export_worker import create_export_task
    result = create_export_task({"symbol_set": "all", "days": 60, "format": "csv"})
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from web.services.state_timeline_observer import query_state_timeline

log = logging.getLogger("hermass.web.state_timeline_export_worker")

ROOT = Path(__file__).resolve().parents[2]
EXPORT_DIR = ROOT / "outputs" / "state_timeline_exports"
TASK_LOG = EXPORT_DIR / "task_log.jsonl"

# 异步触发阈值
ASYNC_ROW_THRESHOLD = 10000

# 默认产物保留天数
DEFAULT_RETENTION_DAYS = 7

# 状态机：允许的状态转移
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "failed"},
    "running": {"completed", "failed"},
    "completed": {"expired"},
    "failed": set(),
    "expired": set(),
}

# 进程内线程锁（防止同进程多线程竞争）
_task_log_lock = threading.Lock()

# 跨进程文件锁：优先 fcntl，不可用时降级为线程锁（仅同进程有效）
try:
    import fcntl

    _HAS_FCNTL = True
except Exception:  # pragma: no cover - Windows 等无 fcntl 环境
    fcntl = None  # type: ignore[assignment]
    _HAS_FCNTL = False


@contextmanager
def _task_log_file_lock(exclusive: bool = True) -> Iterator[Any]:
    """对 task_log.jsonl 加跨进程文件锁。

    写操作使用独占锁，读操作使用共享锁。fcntl 不可用时回退到 threading.Lock。
    """
    if not _HAS_FCNTL:
        # 降级：仅能保证同进程内线程安全
        with _task_log_lock:
            yield None
        return

    _ensure_dirs()
    # 共享锁用读模式打开；独占锁用追加模式打开（不存在则创建）
    mode = "a" if exclusive else "r"
    f = TASK_LOG.open(mode, encoding="utf-8")
    try:
        op = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH  # type: ignore[attr-defined]
        fcntl.flock(f.fileno(), op)  # type: ignore[attr-defined]
        yield f
    finally:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
        f.close()


def _ensure_dirs() -> None:
    """确保导出目录存在。"""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    """返回当前 ISO 8601 时间字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _generate_task_id() -> str:
    """生成任务 ID。"""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = uuid.uuid4().hex[:8]
    return f"state_timeline_export_{today}_{suffix}"


def _normalize_query(query: dict[str, Any]) -> dict[str, Any]:
    """规范化查询参数，移除空值和格式参数。"""
    normalized: dict[str, Any] = {}
    for key in ("symbols", "symbol_set", "date_from", "date_to", "days", "filters", "user_key", "async", "materialized"):
        if key in query:
            normalized[key] = query[key]
    # days 默认 20
    if "days" not in normalized:
        normalized["days"] = 20
    # filters 默认空字典
    if "filters" not in normalized or normalized["filters"] is None:
        normalized["filters"] = {}
    return normalized


def _is_valid_transition(from_status: str, to_status: str) -> bool:
    """校验状态转移是否合法。"""
    return to_status in _VALID_TRANSITIONS.get(from_status, set())


def _append_task_record(record: dict[str, Any]) -> None:
    """追加一条任务记录到 JSONL。

    使用进程内锁 + 跨进程文件锁，保证多线程/多进程并发追加不损坏 JSONL。
    """
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _task_log_lock:
        with _task_log_file_lock(exclusive=True) as f:
            if f is not None:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            else:
                # fcntl 不可用的降级路径
                _ensure_dirs()
                with TASK_LOG.open("a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())


def _read_latest_record(task_id: str) -> dict[str, Any] | None:
    """读取某个任务 ID 的最新记录。"""
    if not TASK_LOG.exists():
        return None
    latest: dict[str, Any] | None = None
    with _task_log_lock:
        with _task_log_file_lock(exclusive=False) as _f:
            with TASK_LOG.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    if record.get("task_id") == task_id:
                        latest = record
    return latest


def _advance_task_record(
    task_id: str,
    new_status: str,
    **updates: Any,
) -> dict[str, Any] | None:
    """按状态机推进任务记录，并追加到日志。

    返回最新记录；若任务不存在或状态转移非法则返回 None。
    """
    record = _read_latest_record(task_id)
    if record is None:
        return None
    current_status = record.get("status", "queued")
    if not _is_valid_transition(current_status, new_status):
        return None
    new_record = {**record, "status": new_status, **updates}
    _append_task_record(new_record)
    return new_record


def _estimate_rows(query: dict[str, Any]) -> int:
    """估算结果行数。

    复用 query_state_timeline 的全结果统计，只取 meta.row_count。
    """
    result = query_state_timeline(
        symbols=query.get("symbols"),
        symbol_set=query.get("symbol_set"),
        date_from=query.get("date_from"),
        date_to=query.get("date_to"),
        days=query.get("days"),
        filters=query.get("filters"),
        page=1,
        page_size=1,
        format="json",
        user_key=query.get("user_key"),
        materialized=query.get("materialized"),
    )
    if not result.get("ok"):
        raise RuntimeError(f"估算行数失败: {result.get('error')}")
    return int(result.get("meta", {}).get("row_count", 0))


def should_export_async(query: dict[str, Any], estimated_rows: int) -> bool:
    """判断是否需要走异步导出。"""
    symbols = str(query.get("symbols") or "").strip().lower()
    fmt = str(query.get("format") or "csv").strip().lower()
    force_async = bool(query.get("async"))

    if force_async:
        return True
    if symbols == "all" and fmt == "csv":
        return True
    if estimated_rows > ASYNC_ROW_THRESHOLD:
        return True
    return False


def _build_sync_url(query: dict[str, Any]) -> str:
    """为同步导出构建 GET URL。"""
    from urllib.parse import urlencode

    params: dict[str, Any] = {}
    if query.get("symbols"):
        params["symbols"] = query["symbols"]
    elif query.get("symbol_set"):
        params["symbol_set"] = query["symbol_set"]
    if query.get("date_from"):
        params["date_from"] = query["date_from"]
    if query.get("date_to"):
        params["date_to"] = query["date_to"]
    if query.get("days") is not None:
        params["days"] = query["days"]
    filters = query.get("filters") or {}
    for k, v in filters.items():
        params[k] = v
    if query.get("materialized") is not None:
        params["materialized"] = "1" if query.get("materialized") else "0"
    params["format"] = query.get("format", "csv")
    return "/api/state-observer?" + urlencode(params)


def create_export_task(
    query: dict[str, Any],
    owner_key: str = "",
    owner_scope: str = "guest",
) -> dict[str, Any]:
    """创建导出任务。

    流程：
    1. 估算行数
    2. 判断是否需要异步
    3. 异步则创建任务、启动后台线程
    4. 同步则返回 sync 标记，前端复用现有 /api/state-observer?format=csv

    参数：
      owner_key: 创建者标识（username 或 visitor_id）
      owner_scope: "user" 或 "guest"

    返回：
      异步：{ok, task_id, status, format, estimated_rows, download_path}
      同步：{ok, task_id: "", status: "sync", format, estimated_rows, download_path: ""}
    """
    _ensure_dirs()

    normalized = _normalize_query(query)
    fmt = str(query.get("format") or "csv").strip().lower()
    normalized["format"] = fmt

    estimated_rows = _estimate_rows(normalized)

    if not should_export_async(normalized, estimated_rows):
        return {
            "ok": True,
            "task_id": "",
            "status": "sync",
            "format": fmt,
            "estimated_rows": estimated_rows,
            "download_path": "",
        }

    task_id = _generate_task_id()
    output_path = EXPORT_DIR / f"{task_id}.{fmt}"

    record = {
        "task_id": task_id,
        "status": "queued",
        "format": fmt,
        "query": normalized,
        "estimated_rows": estimated_rows,
        "output_path": str(output_path.relative_to(ROOT)),
        "row_count": 0,
        "error": "",
        "owner_key": owner_key,
        "owner_scope": owner_scope,
        "created_at": _now_iso(),
        "finished_at": "",
    }
    _append_task_record(record)

    # 启动后台线程
    thread = threading.Thread(target=run_export_task, args=(task_id,), daemon=True)
    thread.start()

    download_path = f"/api/state-observer/export/{task_id}/download"
    return {
        "ok": True,
        "task_id": task_id,
        "status": "queued",
        "format": fmt,
        "estimated_rows": estimated_rows,
        "download_path": download_path,
    }


def run_export_task(task_id: str) -> dict[str, Any]:
    """实际执行导出任务。"""
    record = _read_latest_record(task_id)
    if record is None:
        raise RuntimeError(f"任务 {task_id} 不存在")

    # 更新为 running（带状态机校验）
    if _advance_task_record(task_id, "running") is None:
        raise RuntimeError(f"任务 {task_id} 状态转移非法")

    query = record["query"]
    fmt = record["format"]
    output_path = ROOT / record["output_path"]

    try:
        result = query_state_timeline(
            symbols=query.get("symbols"),
            symbol_set=query.get("symbol_set"),
            date_from=query.get("date_from"),
            date_to=query.get("date_to"),
            days=query.get("days"),
            filters=query.get("filters"),
            page=1,
            page_size=10000,
            format=fmt,
            user_key=query.get("user_key"),
            materialized=query.get("materialized"),
        )
        if not result.get("ok"):
            raise RuntimeError(f"查询失败: {result.get('error')}")

        if fmt == "csv":
            content = result["csv"]
        else:
            # 未来支持 parquet 等格式
            raise RuntimeError(f"暂不支持的导出格式: {fmt}")

        _ensure_dirs()
        output_path.write_text(content, encoding="utf-8")

        row_count = result.get("meta", {}).get("row_count", 0)
        completed_record = _advance_task_record(
            task_id,
            "completed",
            row_count=row_count,
            finished_at=_now_iso(),
        )
        if completed_record is None:
            raise RuntimeError(f"任务 {task_id} 无法标记为完成")
        return {"ok": True, "task_id": task_id, "status": "completed", "row_count": row_count}

    except Exception as exc:
        log.exception("导出任务 %s 失败", task_id)
        _advance_task_record(
            task_id,
            "failed",
            error=str(exc),
            finished_at=_now_iso(),
        )
        return {"ok": False, "task_id": task_id, "status": "failed", "error": str(exc)}


def get_task_owner(task_id: str) -> dict[str, Any] | None:
    """获取任务 owner 信息。"""
    record = _read_latest_record(task_id)
    if record is None:
        return None
    return {
        "owner_key": record.get("owner_key", ""),
        "owner_scope": record.get("owner_scope", "guest"),
    }


def get_task_status(task_id: str) -> dict[str, Any] | None:
    """获取任务状态。

    若任务已完成但产物文件已被清理，则状态显示为 expired 并标记 file_present=False。
    """
    record = _read_latest_record(task_id)
    if record is None:
        return None

    status = record.get("status", "queued")
    output_path = ROOT / record["output_path"] if record.get("output_path") else None
    file_present = bool(output_path is not None and output_path.exists())

    if status == "completed" and not file_present:
        status = "expired"

    download_path = ""
    if status == "completed" and file_present:
        download_path = f"/api/state-observer/export/{task_id}/download"

    return {
        "ok": True,
        "task_id": record["task_id"],
        "status": status,
        "format": record["format"],
        "estimated_rows": record["estimated_rows"],
        "row_count": record.get("row_count", 0),
        "file_present": file_present,
        "download_path": download_path,
        "error": record.get("error", ""),
        "created_at": record.get("created_at", ""),
        "finished_at": record.get("finished_at", ""),
        "expired_at": record.get("expired_at", ""),
    }


def get_output_path(task_id: str) -> Path | None:
    """获取任务产物路径。"""
    record = _read_latest_record(task_id)
    if record is None:
        return None
    return ROOT / record["output_path"]


def mark_task_expired(task_id: str, reason: str = "cleaned") -> dict[str, Any]:
    """将已完成任务标记为 expired。

    用于产物清理后保持任务日志可读。
    """
    record = _read_latest_record(task_id)
    if record is None:
        return {"ok": False, "error": "task_not_found"}
    current_status = record.get("status", "queued")
    if current_status == "expired":
        return {"ok": True, "task": record}
    if not _is_valid_transition(current_status, "expired"):
        return {"ok": False, "error": "invalid_state_transition", "current_status": current_status}
    expired_record = {
        **record,
        "status": "expired",
        "expired_at": _now_iso(),
        "expired_reason": reason,
    }
    _append_task_record(expired_record)
    return {"ok": True, "task": expired_record}


def clean_old_exports(retention_days: int = DEFAULT_RETENTION_DAYS) -> dict[str, Any]:
    """清理保留期之前的导出产物，并将对应任务标记为 expired。

    返回被删除的文件列表与被标记 expired 的任务列表。
    """
    _ensure_dirs()
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted: list[str] = []
    expired_tasks: list[str] = []

    for path in EXPORT_DIR.glob("state_timeline_export_*.csv"):
        if not path.is_file():
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if mtime >= cutoff:
            continue

        task_id = path.stem
        record = _read_latest_record(task_id)
        # 只清理已完成或已过期任务；正在运行的任务文件不删除
        if record is not None and record.get("status") not in ("completed", "expired"):
            continue

        try:
            path.unlink()
            deleted.append(path.name)
        except Exception as exc:
            log.warning("删除导出产物失败 %s: %s", path, exc)
            continue

        if record is not None and record.get("status") != "expired":
            mark_result = mark_task_expired(task_id, reason=f"retention_{retention_days}d")
            if mark_result.get("ok"):
                expired_tasks.append(task_id)

    return {"deleted": deleted, "expired_tasks": expired_tasks}
