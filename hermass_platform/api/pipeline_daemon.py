#!/usr/bin/env python3
"""Hermass 每日数据流水线守护进程。

绕过 macOS crontab/launchd 权限限制，使用 Python sleep 循环。

定时任务:
    08:30 北京时间 — 发送每日邮件报告
    15:15 北京时间 — 执行完整数据流水线

Usage:
    python3 hermass_platform/api/pipeline_daemon.py
"""

import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [pipeline] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("hermass.pipeline")

CHECK_INTERVAL = 30
_last_pipeline_date = ""
_last_report_date = ""


def is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5


def _match_time(now: datetime, hour: int, minute: int) -> bool:
    return now.hour == hour and minute <= now.minute < minute + 5


def _today_key(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def run_pipeline():
    global _last_pipeline_date
    script = ROOT / "scripts" / "run_daily_pipeline.sh"
    if not script.exists():
        logger.error(f"流水线脚本不存在: {script}")
        return

    today = _today_key(datetime.now())
    _last_pipeline_date = today
    logger.info(f"=== 触发每日流水线 ({today}) ===")

    try:
        result = subprocess.run(
            ["bash", str(script)], cwd=str(ROOT),
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode == 0:
            logger.info("流水线执行成功")
        else:
            logger.error(f"流水线退出码: {result.returncode}")
    except subprocess.TimeoutExpired:
        logger.error("流水线超时（10分钟）")
    except Exception as e:
        logger.exception(f"流水线异常: {e}")


def send_report():
    global _last_report_date
    script = ROOT / "scripts" / "send_daily_report.py"
    if not script.exists():
        logger.error("邮件报告脚本不存在")
        return

    today = _today_key(datetime.now())
    _last_report_date = today
    logger.info(f"=== 发送每日邮件报告 ({today}) ===")

    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT),
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            logger.info("邮件报告发送成功")
        else:
            logger.warning(f"邮件报告发送失败: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        logger.error("邮件报告超时")
    except Exception as e:
        logger.exception(f"邮件报告异常: {e}")


def main():
    logger.info("Hermass 流水线守护进程启动")
    logger.info("  08:30 北京时间 → 每日邮件报告")
    logger.info("  15:15 北京时间 → 数据流水线")
    logger.info(f"  检查间隔: {CHECK_INTERVAL}s · 按 Ctrl+C 停止")

    try:
        while True:
            now = datetime.now()
            today = _today_key(now)

            if is_weekday(now) and _match_time(now, 8, 30) and today != _last_report_date:
                send_report()

            if is_weekday(now) and _match_time(now, 15, 15) and today != _last_pipeline_date:
                run_pipeline()

            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        logger.info("守护进程已停止")


if __name__ == "__main__":
    main()
