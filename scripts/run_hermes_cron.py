#!/usr/bin/env python3
"""Run Hermass cron tasks from config/hermes_cron.json.

This is the concrete local runner behind the project cron config. It supports:

- daemon mode: check schedules periodically and execute due tasks
- run-once mode: execute one named task immediately for verification
- dry-run mode: show due tasks without executing commands

The runner stores execution state in outputs/hermes_cron/state.json and appends
run records to outputs/hermes_cron/run_log.jsonl.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "hermes_cron.json"
STATE_DIR = ROOT / "outputs" / "hermes_cron"
STATE_PATH = STATE_DIR / "state.json"
RUN_LOG_PATH = STATE_DIR / "run_log.jsonl"
LOG_PATH = ROOT / "logs" / "hermes_cron.log"
ALERT_SCANNER = ROOT / "scripts" / "alert_scanner.py"

REVIEW_COMMAND_MARKERS = (
    "scripts/agent_self_review.py",
    "scripts/agent_cross_review.py",
)


@dataclass(frozen=True)
class CronTask:
    name: str
    schedule: str
    command: str
    description: str = ""
    delivery: str = "terminal"


def setup_logging(verbose: bool = False) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


log = logging.getLogger("hermes_cron")


def load_config(path: Path = DEFAULT_CONFIG) -> list[CronTask]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tasks = []
    for item in payload.get("tasks", []):
        if item.get("enabled") is False:
            continue
        tasks.append(
            CronTask(
                name=str(item["name"]),
                schedule=str(item["schedule"]),
                command=str(item["command"]),
                description=str(item.get("description", "")),
                delivery=str(item.get("delivery", "terminal")),
            )
        )
    return tasks


def parse_field(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue

        if "/" in part:
            base, step_text = part.split("/", 1)
            step = int(step_text)
        else:
            base, step = part, 1

        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(base)

        if step <= 0:
            raise ValueError(f"invalid cron step: {field}")
        if start < minimum or end > maximum or start > end:
            raise ValueError(f"cron field out of range: {field} ({minimum}-{maximum})")
        values.update(range(start, end + 1, step))
    return values


def cron_dow(now: datetime) -> int:
    """Return POSIX cron day-of-week: Sunday=0, Monday=1, ..., Saturday=6."""
    return (now.weekday() + 1) % 7


def cron_matches(schedule: str, now: datetime) -> bool:
    fields = schedule.split()
    if len(fields) != 5:
        raise ValueError(f"unsupported cron schedule: {schedule!r}")

    minute_s, hour_s, dom_s, month_s, dow_s = fields
    minutes = parse_field(minute_s, 0, 59)
    hours = parse_field(hour_s, 0, 23)
    doms = parse_field(dom_s, 1, 31)
    months = parse_field(month_s, 1, 12)
    dows = parse_field(dow_s.replace("7", "0"), 0, 6)

    return (
        now.minute in minutes
        and now.hour in hours
        and now.day in doms
        and now.month in months
        and cron_dow(now) in dows
    )


def minute_key(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M")


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"last_run": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"last_run": {}}


def save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STATE_PATH)


def append_run_log(record: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with RUN_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def is_review_task(task: CronTask) -> bool:
    return any(marker in task.command for marker in REVIEW_COMMAND_MARKERS)


def run_shell(command: str, timeout: int) -> dict[str, Any]:
    started_at = datetime.now().isoformat(timespec="seconds")
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(ROOT),
            executable="/bin/bash",
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return {
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-4000:],
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "returncode": 124,
            "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
            "timed_out": True,
        }


def run_alert_scanner(timeout: int = 120) -> dict[str, Any]:
    if not ALERT_SCANNER.exists():
        return {
            "skipped": True,
            "reason": f"missing {ALERT_SCANNER}",
        }
    command = f"cd {shell_quote(str(ROOT))} && .venv/bin/python scripts/alert_scanner.py"
    result = run_shell(command, timeout=timeout)
    result["skipped"] = False
    return result


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def run_task(task: CronTask, *, timeout: int, dry_run: bool = False) -> dict[str, Any]:
    log.info("执行任务: %s", task.name)
    record: dict[str, Any] = {
        "task": task.name,
        "schedule": task.schedule,
        "command": task.command,
        "description": task.description,
        "delivery": task.delivery,
        "triggered_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": dry_run,
    }

    if dry_run:
        record["result"] = {"returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}
        append_run_log(record)
        return record

    result = run_shell(task.command, timeout=timeout)
    record["result"] = result
    log.info("任务完成: %s returncode=%s", task.name, result["returncode"])

    if is_review_task(task):
        scanner_result = run_alert_scanner(timeout=120)
        record["alert_scanner"] = scanner_result
        log.info(
            "review 后 alert_scanner 完成: %s returncode=%s skipped=%s",
            task.name,
            scanner_result.get("returncode"),
            scanner_result.get("skipped"),
        )

    append_run_log(record)
    return record


def due_tasks(tasks: list[CronTask], now: datetime, state: dict[str, Any]) -> list[CronTask]:
    current_key = minute_key(now)
    last_run = state.setdefault("last_run", {})
    due = []
    for task in tasks:
        if not cron_matches(task.schedule, now):
            continue
        if last_run.get(task.name) == current_key:
            continue
        due.append(task)
    return due


def mark_ran(task: CronTask, now: datetime, state: dict[str, Any]) -> None:
    state.setdefault("last_run", {})[task.name] = minute_key(now)
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)


def select_tasks(tasks: list[CronTask], pattern: str) -> list[CronTask]:
    return [
        task for task in tasks
        if fnmatch.fnmatch(task.name, pattern) or pattern in task.name
    ]


def run_once(args: argparse.Namespace) -> int:
    tasks = load_config(args.config)
    matches = select_tasks(tasks, args.task)
    if not matches:
        print(f"[ERROR] 未找到任务: {args.task}", file=sys.stderr)
        return 2

    status = 0
    for task in matches:
        record = run_task(task, timeout=args.timeout, dry_run=args.dry_run)
        result = record.get("result") or {}
        rc = int(result.get("returncode") or 0)
        if rc != 0:
            status = 1
        print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return status


def list_tasks(args: argparse.Namespace) -> int:
    tasks = load_config(args.config)
    now = datetime.now()
    state = load_state()
    due_names = {task.name for task in due_tasks(tasks, now, state)}
    for task in tasks:
        marker = "*" if task.name in due_names else " "
        print(f"{marker} {task.schedule:14s} {task.name} :: {task.command}")
    return 0


def daemon(args: argparse.Namespace) -> int:
    tasks = load_config(args.config)
    stop = False

    def _handle_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    log.info("Hermass cron daemon started: tasks=%d interval=%ss", len(tasks), args.interval)
    while not stop:
        now = datetime.now()
        state = load_state()
        for task in due_tasks(tasks, now, state):
            record = run_task(task, timeout=args.timeout, dry_run=args.dry_run)
            mark_ran(task, now, state)
            rc = (record.get("result") or {}).get("returncode")
            if rc:
                log.warning("任务非零退出: %s returncode=%s", task.name, rc)
        time.sleep(args.interval)

    log.info("Hermass cron daemon stopped")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermass cron runner")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--dry-run", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出任务，并标记当前分钟应运行的任务")

    once = sub.add_parser("run-once", help="立即执行一个任务")
    once.add_argument("--task", required=True, help="任务名、子串或 shell wildcard")

    daemon_parser = sub.add_parser("daemon", help="启动常驻调度器")
    daemon_parser.add_argument("--interval", type=int, default=60, help="检查间隔秒数")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    if args.command == "list":
        return list_tasks(args)
    if args.command == "run-once":
        return run_once(args)
    if args.command == "daemon":
        return daemon(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
