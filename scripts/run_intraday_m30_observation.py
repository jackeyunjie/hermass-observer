#!/usr/bin/env python3
"""
run_intraday_m30_observation.py
M30 准实时观察调度器。

在 A 股交易时段内，每 30 分钟执行一次 M30 观察流水线：
  09:30-11:30, 13:00-15:00 (北京时间)

用法：
  .venv/bin/python scripts/run_intraday_m30_observation.py --date YYYY-MM-DD
  .venv/bin/python scripts/run_intraday_m30_observation.py --date YYYY-MM-DD --once 09:30
"""
import argparse
import subprocess
import sys
import json
import os
from datetime import datetime, date, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv/bin/python"
BUILD_SCRIPT = ROOT / "scripts/build_m30_observation_state.py"
LOG_DIR = ROOT / "outputs/logs"
OUT_DIR = ROOT / "outputs/m30_observation"

# A 股交易时段（北京时间）
MORNING_START = time(9, 30)
MORNING_END = time(11, 30)
AFTERNOON_START = time(13, 0)
AFTERNOON_END = time(15, 0)
INTERVAL_MINUTES = 30


def is_trading_time(t: time) -> bool:
    return (
        (MORNING_START <= t <= MORNING_END)
        or (AFTERNOON_START <= t <= AFTERNOON_END)
    )


def next_trading_slot(after: time) -> time:
    """返回 after 之后的下一个 30 分钟整点交易时间。"""
    candidates = []
    # 上午
    m = 30
    while True:
        cand = time(9, m)
        if cand > MORNING_END:
            break
        candidates.append(cand)
        m += INTERVAL_MINUTES
    # 下午
    m = 0
    while True:
        cand = time(13, m)
        if cand > AFTERNOON_END:
            break
        candidates.append(cand)
        m += INTERVAL_MINUTES
    for c in candidates:
        if c > after:
            return c
    return None


def run_build(date_str: str, time_str: str, log_file: Path) -> dict:
    cmd = [
        str(PYTHON), str(BUILD_SCRIPT),
        "--date", date_str,
        "--time", time_str,
    ]
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as lf:
        lf.write(f"\n--- {datetime.now().isoformat()} snapshot {time_str} ---\n")
        lf.flush()
        result = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=str(ROOT))
        status = "ok" if result.returncode == 0 else "error"
        lf.write(f"exit_code={result.returncode} status={status}\n")
    return {"time": time_str, "status": status, "exit_code": result.returncode}


def run_loop(date_str: str, dry_run: bool = False):
    log_file = LOG_DIR / f"m30_observation_{date_str.replace('-','')}.log"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    # 生成当天所有 30 分钟交易时间点
    slots = []
    base = datetime.combine(date.today(), time(9, 0))
    for offset in (30, 60, 90, 120):
        t = (base + timedelta(minutes=offset)).time()
        if t <= MORNING_END:
            slots.append(t)
    base = datetime.combine(date.today(), time(13, 0))
    for offset in (0, 30, 60, 90, 120):
        t = (base + timedelta(minutes=offset)).time()
        if t <= AFTERNOON_END:
            slots.append(t)

    for t in slots:
        ts = t.strftime("%H:%M")
        now = datetime.now().time()
        if not dry_run:
            # 如果当前时间还没到该 slot，等待
            slot_dt = datetime.combine(date.today(), t)
            now_dt = datetime.now()
            if slot_dt > now_dt:
                wait_sec = (slot_dt - now_dt).total_seconds()
                print(f"[WAIT] Next slot {ts} in {int(wait_sec)}s")
                import time as _time
                _time.sleep(wait_sec)
        print(f"[RUN] Slot {ts}")
        if dry_run:
            results.append({"time": ts, "status": "dry_run", "exit_code": 0})
        else:
            r = run_build(date_str, ts, log_file)
            results.append(r)
    return results


def main():
    parser = argparse.ArgumentParser(description="Intraday M30 Observation Runner")
    parser.add_argument("--date", required=True, help="Trade date YYYY-MM-DD")
    parser.add_argument("--once", help="Run single snapshot HH:MM and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print slots without running")
    args = parser.parse_args()

    log_file = LOG_DIR / f"m30_observation_{args.date.replace('-','')}.log"
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if args.once:
        t = datetime.strptime(args.once, "%H:%M").time()
        if not is_trading_time(t):
            print(f"[ERROR] {args.once} is not in trading hours")
            sys.exit(1)
        r = run_build(args.date, args.once, log_file)
        print(json.dumps(r, ensure_ascii=False))
        sys.exit(0 if r["status"] == "ok" else 1)

    results = run_loop(args.date, dry_run=args.dry_run)
    summary = {
        "date": args.date,
        "slots": len(results),
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "error": sum(1 for r in results if r["status"] == "error"),
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
