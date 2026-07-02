#!/usr/bin/env python3
"""清理 State Timeline 异步导出产物。

与 config/hermes_cron.json 中 "State Timeline 导出产物清理" 任务对齐：
- 删除超过保留期的 CSV 文件
- 在 task_log.jsonl 中将对应任务追加标记为 expired
- 状态查询仍可读，并说明文件已过期/已清理

用法：
    .venv/bin/python scripts/clean_state_timeline_exports.py --retention-days 7
    .venv/bin/python scripts/clean_state_timeline_exports.py --retention-days 7 --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from web.services.state_timeline_export_worker import clean_old_exports


def main() -> int:
    parser = argparse.ArgumentParser(description="清理 State Timeline 导出产物")
    parser.add_argument(
        "--retention-days",
        type=int,
        default=7,
        help="产物保留天数（默认 7）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要清理的内容，不执行删除",
    )
    args = parser.parse_args()

    if args.dry_run:
        # dry-run：扫描并报告，但不删除、不标记
        from datetime import datetime, timedelta, timezone
        from web.services.state_timeline_export_worker import EXPORT_DIR, _read_latest_record

        cutoff = datetime.now(timezone.utc) - timedelta(days=args.retention_days)
        candidates = []
        for path in EXPORT_DIR.glob("state_timeline_export_*.csv"):
            if not path.is_file():
                continue
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime >= cutoff:
                continue
            task_id = path.stem
            record = _read_latest_record(task_id)
            status = record.get("status") if record else "unknown"
            candidates.append({"file": path.name, "task_id": task_id, "status": status})
        print(json.dumps({"dry_run": True, "retention_days": args.retention_days, "candidates": candidates}, ensure_ascii=False))
        return 0

    result = clean_old_exports(retention_days=args.retention_days)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
