#!/usr/bin/env python3
"""iFind Event Radar Agent — 事件雷达，消费 iFinD 智能体广场输出。

定位：
  iFinD API     = 原始事实层（财务/基本面）
  iFinD Agent   = 事件摘要/投研解释层 ← 本脚本消费这一层
  DeepSeek      = 证据约束分析层
  Hermass       = 统一评分与观察体系

消费 iFinD Agent 类型：
  - A股上市公司公告整理助手  → 定增/并购/重大事项/停复牌
  - A股业绩预警助手          → 预增/预减/亏损/修正
  - 自选股AI资讯简报         → 当日催化事件
  - 每日热点快讯简报         → 市场热点背景

输出：
  outputs/event_digest/ifind_event_digest.duckdb
    - company_events      公告/业绩/资讯事件
    - event_pool_cross    事件 × P116 E/F 池交叉
    - performance_warnings 业绩预警
    - digest_run_log      运行记录

用法：
  python3 scripts/ifind_event_radar.py --date 2026-05-21
  python3 scripts/ifind_event_radar.py --date 2026-05-21 --import-json /path/to/agent_export.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DIGEST_DB = ROOT / "outputs" / "event_digest" / "ifind_event_digest.duckdb"
SCHEMA_VERSION = "ifind_event_digest_v1"


def ymd(d: str) -> str:
    return d.replace("-", "")


CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS company_events (
        event_id         VARCHAR    PRIMARY KEY,
        stock_code       VARCHAR    NOT NULL,
        event_date       VARCHAR    NOT NULL,
        event_type       VARCHAR    NOT NULL,
        event_subtype    VARCHAR,
        title            VARCHAR,
        summary          VARCHAR,
        impact           VARCHAR,
        source_agent     VARCHAR,
        source_export    VARCHAR,
        raw_json         VARCHAR,
        collected_at     VARCHAR    NOT NULL,
        mapped_to_pool   BOOLEAN    DEFAULT FALSE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS performance_warnings (
        warning_id       VARCHAR    PRIMARY KEY,
        stock_code       VARCHAR    NOT NULL,
        announce_date    VARCHAR    NOT NULL,
        warning_type     VARCHAR    NOT NULL,
        period           VARCHAR,
        expected_change  VARCHAR,
        reason           VARCHAR,
        previous_forecast VARCHAR,
        source_agent     VARCHAR    DEFAULT 'A股业绩预警助手',
        collected_at     VARCHAR    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS news_briefs (
        brief_id         VARCHAR    PRIMARY KEY,
        stock_code       VARCHAR,
        brief_date       VARCHAR    NOT NULL,
        brief_type       VARCHAR    NOT NULL,
        headline         VARCHAR,
        body             VARCHAR,
        tags             VARCHAR,
        source_agent     VARCHAR,
        collected_at     VARCHAR    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS event_pool_cross (
        stock_code       VARCHAR    NOT NULL,
        as_of_date       VARCHAR    NOT NULL,
        ef_count         INTEGER,
        total_events     INTEGER,
        warning_count    INTEGER,
        placement_count  INTEGER,
        merger_count     INTEGER,
        positive_warnings VARCHAR,
        negative_warnings VARCHAR,
        latest_event_summary VARCHAR,
        PRIMARY KEY (stock_code, as_of_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS digest_run_log (
        run_id           VARCHAR    PRIMARY KEY,
        run_date         VARCHAR    NOT NULL,
        events_imported  INTEGER,
        warnings_imported INTEGER,
        briefs_imported   INTEGER,
        pool_cross_count  INTEGER,
        source           VARCHAR,
        error            VARCHAR,
        finished_at      VARCHAR
    )
    """,
]


def init_schema(db_path: Path | None = None) -> Path:
    db_path = db_path or DIGEST_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    for stmt in CREATE_STATEMENTS:
        con.execute(stmt)
    con.execute("CREATE TABLE IF NOT EXISTS schema_info (schema_version VARCHAR, created_at VARCHAR)")
    con.execute("DELETE FROM schema_info")
    con.execute("INSERT INTO schema_info VALUES (?, ?)", (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()))
    con.close()
    return db_path


def import_agent_export(con: duckdb.DuckDBPyConnection, json_path: Path, date_str: str, collected_at: str) -> dict[str, int]:
    if not json_path.exists():
        return {"events": 0, "warnings": 0, "briefs": 0}

    data = json.loads(json_path.read_text(encoding="utf-8"))
    events_count = 0
    warnings_count = 0
    briefs_count = 0

    # 公告整理助手 → company_events
    for item in data.get("announcements", []):
        eid = f"ann_{item.get('stock_code','')}_{item.get('date','')}_{events_count}"
        try:
            con.execute("""
                INSERT OR IGNORE INTO company_events
                (event_id, stock_code, event_date, event_type, event_subtype, title, summary,
                 source_agent, source_export, raw_json, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (eid, item.get("stock_code", ""), item.get("date", date_str),
                  item.get("type", "announcement"), item.get("subtype"),
                  item.get("title", ""), item.get("summary", ""),
                  "A股上市公司公告整理助手", str(json_path),
                  json.dumps(item, ensure_ascii=False)[:3000], collected_at))
            events_count += 1
        except Exception:
            pass

    # 业绩预警助手 → performance_warnings
    for item in data.get("performance_warnings", []):
        wid = f"warn_{item.get('stock_code','')}_{item.get('date','')}_{warnings_count}"
        try:
            con.execute("""
                INSERT OR IGNORE INTO performance_warnings
                (warning_id, stock_code, announce_date, warning_type, period,
                 expected_change, reason, previous_forecast, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (wid, item.get("stock_code", ""), item.get("date", date_str),
                  item.get("type", "unknown"), item.get("period"),
                  item.get("expected", ""), item.get("reason", ""),
                  item.get("previous", ""), collected_at))
            warnings_count += 1
        except Exception:
            pass

    # 资讯简报 → news_briefs
    for item in data.get("news_briefs", []):
        bid = f"brief_{item.get('stock_code','')}_{date_str}_{briefs_count}"
        try:
            tags = ",".join(item.get("tags", []) or [])
            con.execute("""
                INSERT OR IGNORE INTO news_briefs
                (brief_id, stock_code, brief_date, brief_type, headline, body, tags, source_agent, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (bid, item.get("stock_code"), date_str,
                  item.get("type", "market_brief"), item.get("headline", ""),
                  item.get("body", "")[:2000], tags,
                  item.get("source_agent", "自选股AI资讯简报"), collected_at))
            briefs_count += 1
        except Exception:
            pass

    return {"events": events_count, "warnings": warnings_count, "briefs": briefs_count}


def cross_with_pool(con: duckdb.DuckDBPyConnection, date_str: str) -> int:
    """将事件与 P116 E/F 池交叉"""
    y = ymd(date_str)
    pool_path = ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_{y}.json"
    if not pool_path.exists():
        return 0

    pool_data = json.loads(pool_path.read_text(encoding="utf-8"))
    pool_codes = set()
    code_ef = {}
    for row in pool_data.get("rows", []):
        code = row.get("symbol") or row.get("stock_code", "")
        if code and row.get("ef_count", 0) >= 2:
            pool_codes.add(code)
            code_ef[code] = row.get("ef_count", 2)

    count = 0
    for code in pool_codes:
        ef = code_ef.get(code, 0)
        events = con.execute(
            "SELECT COUNT(*) FROM company_events WHERE stock_code = ? AND event_date = ?",
            (code, date_str)
        ).fetchone()[0]
        warnings = con.execute(
            "SELECT COUNT(*) FROM performance_warnings WHERE stock_code = ?",
            (code,)
        ).fetchone()[0]

        pos = con.execute(
            "SELECT expected_change FROM performance_warnings WHERE stock_code = ? AND warning_type = '预增'",
            (code,)
        ).fetchall()
        neg = con.execute(
            "SELECT expected_change FROM performance_warnings WHERE stock_code = ? AND warning_type IN ('预减', '亏损', '修正')",
            (code,)
        ).fetchall()

        latest = con.execute(
            "SELECT title, event_type FROM company_events WHERE stock_code = ? AND event_date = ? ORDER BY event_id LIMIT 1",
            (code, date_str)
        ).fetchone()

        con.execute("""
            INSERT OR REPLACE INTO event_pool_cross
            (stock_code, as_of_date, ef_count, total_events, warning_count,
             placement_count, merger_count, positive_warnings, negative_warnings, latest_event_summary)
            VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
        """, (code, date_str, ef, events, warnings,
              json.dumps([p[0] for p in pos], ensure_ascii=False),
              json.dumps([n[0] for n in neg], ensure_ascii=False),
              f"{latest[1]}: {latest[0]}" if latest else "无"))
        count += 1

    return count


def run(date_str: str, import_json: str | None = None) -> dict:
    collected_at = datetime.now(timezone.utc).isoformat()
    run_id = f"event_radar_{ymd(date_str)}"

    db_path = init_schema()
    con = duckdb.connect(str(db_path))

    ev = warnings = briefs = 0
    if import_json:
        result = import_agent_export(con, Path(import_json), date_str, collected_at)
        ev = result["events"]
        warnings = result["warnings"]
        briefs = result["briefs"]

    pool_cross = cross_with_pool(con, date_str)

    con.execute("""
        INSERT OR REPLACE INTO digest_run_log
        (run_id, run_date, events_imported, warnings_imported, briefs_imported,
         pool_cross_count, source, finished_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (run_id, date_str, ev, warnings, briefs, pool_cross,
          import_json or "no_import", datetime.now(timezone.utc).isoformat()))
    con.close()

    return {
        "schema_version": SCHEMA_VERSION,
        "date": date_str,
        "events_imported": ev,
        "warnings_imported": warnings,
        "briefs_imported": briefs,
        "pool_cross": pool_cross,
        "db": str(db_path),
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="iFind Event Radar Agent")
    parser.add_argument("--date", required=True)
    parser.add_argument("--import-json", help="Path to iFind Agent exported JSON")
    args = parser.parse_args()

    result = run(args.date, args.import_json)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
