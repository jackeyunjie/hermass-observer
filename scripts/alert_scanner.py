#!/usr/bin/env python3
"""Hermass Alert Scanner — 消费复盘标记文件，广播 AgentBus review_needed。

扫描 outputs/reviews/ 下的 .alert_self_review 和 .alert_cross_review 标记文件：
  - 发现标记后读取对应 review 报告
  - 调用 hermass_platform.bus.agent_bus.publish_review_needed(...) 广播
  - 归档标记文件，避免重复广播

用法:
    python3 scripts/alert_scanner.py

退出码:
    0 = 无告警或全部处理成功
    1 = 部分处理失败
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 路径 ──────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "outputs" / "reviews"
ARCHIVE_DIR = REVIEW_DIR / "archived"
LOG_FILE = ROOT / "logs" / "alert_scanner.log"

import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── 日志 ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("alert_scanner")

# ── 标记文件配置 ──────────────────────────────────────────────
MARKER_CONFIG: dict[str, dict[str, Any]] = {
    ".alert_self_review": {
        "review_file": "self_review_latest.json",
        "from_agent": "alert_scanner",
        "subject_template": "自评告警: overall={overall}",
    },
    ".alert_cross_review": {
        "review_file": "cross_review_latest.json",
        "from_agent": "alert_scanner",
        "subject_template": "互评告警: overall={overall}",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("读取 JSON 失败: %s — %s", path, exc)
        return None


def _archive_marker(marker_path: Path) -> Path:
    """将标记文件归档，避免重复广播。"""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archived_name = f"{marker_path.name}_{timestamp}"
    archived_path = ARCHIVE_DIR / archived_name
    try:
        marker_path.rename(archived_path)
        logger.info("标记文件已归档: %s -> %s", marker_path.name, archived_path.name)
        return archived_path
    except OSError as exc:
        logger.error("归档标记文件失败: %s — %s", marker_path, exc)
        raise


def _process_marker(marker_name: str) -> bool:
    """处理单个标记文件，返回是否成功。"""
    config = MARKER_CONFIG[marker_name]
    marker_path = REVIEW_DIR / marker_name

    marker = _load_json(marker_path)
    if marker is None:
        logger.warning("标记文件存在但无法读取: %s", marker_path)
        return False

    overall = marker.get("overall", "unknown")
    triggered_at = marker.get("triggered_at", "unknown")

    # 读取对应 review 报告
    review_path = REVIEW_DIR / config["review_file"]
    review = _load_json(review_path)
    if review is None:
        logger.warning("Review 文件不存在，仅使用标记内容广播: %s", review_path)
        review = {}

    # 构造 subject
    subject = config["subject_template"].format(overall=overall)

    # 构造 details — 合并 marker + review 关键字段
    details: dict[str, Any] = {
        "triggered_at": triggered_at,
        "overall": overall,
        "marker_source": marker_name,
    }

    if marker_name == ".alert_self_review":
        issues = marker.get("issues", [])
        details["issues"] = issues
        details["review_summary"] = {
            "review_type": review.get("review_type", "self_review"),
            "generated_at": review.get("generated_at"),
            "checks": review.get("checks", {}),
        }
        if issues:
            subject += f", issues={len(issues)}"

    elif marker_name == ".alert_cross_review":
        inconsistent = marker.get("inconsistent_details", [])
        details["consistent_pairs"] = marker.get("consistent_pairs", 0)
        details["total_pairs"] = marker.get("total_pairs", 0)
        details["inconsistent_details"] = inconsistent
        details["review_summary"] = {
            "review_type": review.get("review_type", "cross_review"),
            "generated_at": review.get("generated_at"),
            "inconsistent_pairs": review.get("inconsistent_pairs", 0),
        }
        if inconsistent:
            subject += f", 不一致对={len(inconsistent)}"

    # 广播 AgentBus review_needed
    try:
        from hermass_platform.bus.agent_bus import AgentBus, publish_review_needed

        bus = AgentBus()
        result = publish_review_needed(
            bus=bus,
            from_agent=config["from_agent"],
            subject=subject,
            details=details,
        )
        logger.info(
            "review_needed 广播成功 — topic=%s from=%s subject=%s msg_id=%s",
            result.get("topic"),
            result.get("from_agent"),
            subject,
            result.get("message_id"),
        )
    except Exception as exc:
        logger.error("review_needed 广播失败 — subject=%s: %s", subject, exc)
        return False

    # 归档标记文件
    try:
        _archive_marker(marker_path)
    except OSError:
        return False

    return True


def main() -> int:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    any_failed = False
    any_processed = False

    for marker_name in MARKER_CONFIG:
        marker_path = REVIEW_DIR / marker_name
        if not marker_path.exists():
            logger.debug("无标记文件: %s", marker_path)
            continue

        any_processed = True
        logger.info("发现标记文件: %s", marker_path)
        ok = _process_marker(marker_name)
        if not ok:
            any_failed = True

    if not any_processed:
        logger.info("本次扫描未发现告警标记，无需广播。")

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
