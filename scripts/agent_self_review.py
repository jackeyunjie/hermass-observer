#!/usr/bin/env python3
"""Hermass AI 自评 — 每 4 小时自动运行的系统健康检查。

检查项：
  1. 服务心跳（/health endpoint）
  2. 数据新鲜度（最新 Foundation DB 是否过期）
  3. Agent 判断积压（AgentMemory 中未回溯的判断数量）

输出：outputs/reviews/self_review_YYYYMMDD_HHMM.json
退出码：0=健康, 1=有警告, 2=有错误

告警：异常时写入 outputs/reviews/.alert_self_review 标记文件 + ERROR 日志。
AgentBus review_needed topic 由独立的 alert_scanner 消费。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MEMORY_DB = ROOT / "outputs" / "agent_memory" / "AgentMemory.duckdb"
REVIEW_DIR = ROOT / "outputs" / "reviews"
ALERT_FILE = REVIEW_DIR / ".alert_self_review"

logging.basicConfig(
    level=logging.WARNING,
    format="[%(asctime)s] %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agent_self_review")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_health() -> dict[str, Any]:
    """检查服务心跳。"""
    import urllib.request
    try:
        resp = urllib.request.urlopen("http://localhost:8020/health", timeout=5)
        status = resp.getcode()
        body = resp.read().decode("utf-8", errors="ignore")[:200]
        return {"ok": status == 200, "status": status, "body": body}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)[:200]}


def check_data_freshness(max_stale_hours: int = 48) -> dict[str, Any]:
    """检查最新 Foundation DB 是否过期。"""
    pattern = "outputs/p116_foundation_*/p116_foundation.duckdb"
    dbs = sorted(
        ROOT.glob(pattern),
        key=lambda path: _foundation_date_key(path),
        reverse=True,
    )
    if not dbs:
        return {"ok": False, "latest_date": None, "error": "no foundation db found"}

    latest = dbs[0]
    size = latest.stat().st_size
    size_mb = size / 1024 / 1024

    # 从路径中提取日期 YYYYMMDD
    stem = latest.parent.name  # p116_foundation_20260601
    ymd = "".join(c for c in stem if c.isdigit())[-8:]
    try:
        db_date = datetime.strptime(ymd, "%Y%m%d")
    except ValueError:
        db_date = None

    stale = False
    if db_date:
        hours_ago = (datetime.now() - db_date).total_seconds() / 3600
        stale = hours_ago > max_stale_hours
    else:
        hours_ago = None

    return {
        "ok": not stale,
        "latest_date": ymd,
        "path": str(latest),
        "size_mb": round(size_mb, 1),
        "stale": stale,
        "hours_ago": round(hours_ago, 1) if hours_ago is not None else None,
        "max_stale_hours": max_stale_hours,
    }


def _foundation_date_key(path: Path) -> str:
    match = re.search(r"p116_foundation_(\d{8})$", path.parent.name)
    return match.group(1) if match else ""


def check_judgment_backlog(max_unreviewed: int = 100) -> dict[str, Any]:
    """检查 AgentMemory 中未回溯判断的积压数量。"""
    import duckdb
    if not MEMORY_DB.exists():
        return {"ok": True, "total_judgments": 0, "unreviewed": 0, "note": "AgentMemory db not yet created"}

    try:
        con = duckdb.connect(str(MEMORY_DB), read_only=True)
        try:
            total = con.execute(
                "SELECT COUNT(*) FROM agent_judgments"
            ).fetchone()[0]

            reviewed = con.execute(
                "SELECT COUNT(DISTINCT judgment_id) FROM judgment_outcomes"
            ).fetchone()[0]

            unreviewed = total - reviewed
            backlogged = unreviewed > max_unreviewed
            return {
                "ok": not backlogged,
                "total_judgments": total,
                "reviewed": reviewed,
                "unreviewed": unreviewed,
                "max_unreviewed": max_unreviewed,
                "backlogged": backlogged,
            }
        finally:
            con.close()
    except Exception as e:
        logger.warning("check_judgment_backlog 查询失败: %s", e)
        return {"ok": True, "total_judgments": 0, "unreviewed": 0, "error": str(e)[:200], "backlogged": False}


def build_report() -> dict[str, Any]:
    health = check_health()
    data = check_data_freshness()
    backlog = check_judgment_backlog()

    issues = []
    if not health["ok"]:
        issues.append(f"服务心跳异常: status={health.get('status')}")
    if not data["ok"]:
        issues.append(f"数据过期: latest={data.get('latest_date')}, hours_ago={data.get('hours_ago')}")
    if backlog.get("backlogged"):
        issues.append(f"判断积压: {backlog.get('unreviewed')} 条未回溯")

    overall = "ok" if not issues else ("warn" if len(issues) <= 1 else "error")

    report = {
        "review_type": "self_review",
        "generated_at": _now(),
        "overall": overall,
        "issues": issues,
        "checks": {
            "health": health,
            "data_freshness": data,
            "judgment_backlog": backlog,
        },
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermass AI 自评健康检查")
    parser.add_argument("--json", action="store_true", default=True, help="输出 JSON 到 stdout")
    args = parser.parse_args()

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    report = build_report()

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = REVIEW_DIR / f"self_review_{ts}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    latest_path = REVIEW_DIR / "self_review_latest.json"
    latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    # ── 告警信号：异常时落标记文件 + ERROR 日志 ──
    if report["overall"] in ("warn", "error"):
        logger.error("自评异常: overall=%s issues=%s", report["overall"], report["issues"])
        alert = {
            "triggered_at": _now(),
            "overall": report["overall"],
            "issues": report["issues"],
            "action": "AgentBus review_needed 应由 alert_scanner 消费此标记文件后广播",
        }
        ALERT_FILE.write_text(json.dumps(alert, ensure_ascii=False, indent=2))

    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)

    if report["overall"] == "error":
        return 2
    elif report["overall"] == "warn":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
