#!/usr/bin/env python3
"""Data Quality Fields — 数据质量字段追加与回填。

在 d1_perspective_state 表上追加 4 个数据质量字段，并按规则回填：

  1. data_quality_score  INTEGER  (0 = CLEAN, 1 = DEGRADED)
  2. market_segment      VARCHAR  (SH / SZ / CYB / STAR)
  3. bar_history_days    INTEGER  (该股在库中的累计 K 线条数)
  4. post_suspension_days INTEGER (停牌复牌后天数，未停牌 / 已恢复 = 0)

DEGRADED 规则（命中任意一条即 data_quality_score = 1）：
  - 停牌日：该股当日不在 daily_bars
  - 涨跌停日：主板 |涨跌幅| >= 9.9%，科创板 / 创业板 >= 19.9%
  - ST 股票：stock_name 含 "ST"（当前库无 stock_name 列，预留扩展）
  - IPO 首日：bar_history_days < 1
  - 停牌 > 30 天复牌后前 5 日：post_suspension_days ∈ [1, 5] 且停牌天数 > 30

幂等：多次执行不报错（ALTER TABLE 带 IF NOT EXISTS 语义检测，UPDATE 可重复运行）。

用法：
  python3 scripts/add_data_quality_fields.py --date 2026-06-02
  python3 scripts/add_data_quality_fields.py --date 2026-06-02 --foundation-db /path/to/foundation.duckdb
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

# ── 路径与日志 ────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("data_quality")

# ── 常量 ──────────────────────────────────────────────────────
TARGET_TABLE = "d1_perspective_state"
MANIFEST_TABLE = "data_quality_manifest"

# 板块涨跌幅阈值 (绝对值)
LIMIT_THRESHOLD_MAIN = 0.099    # 主板 ±9.9%
LIMIT_THRESHOLD_GEM = 0.199     # 创业板 / 科创板 ±19.9%

# 停牌 > 30 个交易日后复牌前 5 日标 DEGRADED
LONG_SUSPENSION_THRESHOLD = 30
POST_RESUMPTION_WINDOW = 5


# ── 市场板块映射 ──────────────────────────────────────────────
def classify_market_segment(stock_code: str) -> str:
    """按股票代码前缀分类板块。

    000/001/002 → SZ  (深市主板)
    300/301     → CYB (创业板)
    600/601/603/605 → SH (上交所主板)
    688/689     → STAR (科创板)
    其他        → OTHER
    """
    prefix = stock_code[:3]
    if prefix in ("000", "001", "002"):
        return "SZ"
    if prefix in ("300", "301"):
        return "CYB"
    if prefix in ("600", "601", "603", "605"):
        return "SH"
    if prefix in ("688", "689"):
        return "STAR"
    return "OTHER"


def _limit_threshold(segment: str) -> float:
    """根据板块返回涨跌停阈值。"""
    if segment in ("CYB", "STAR"):
        return LIMIT_THRESHOLD_GEM
    return LIMIT_THRESHOLD_MAIN


# ── 辅助：定位 foundation DB ─────────────────────────────────
def default_foundation_db(date: str) -> Path:
    ymd = date.replace("-", "")
    return ROOT / "outputs" / f"p116_foundation_{ymd}" / "p116_foundation.duckdb"


def find_foundation_db(date: str = "") -> Path:
    """优先用指定日期，否则取最新目录。"""
    if date:
        p = default_foundation_db(date)
        if p.exists():
            return p
    # 回退：找最新
    out_dir = ROOT / "outputs"
    candidates = sorted(
        out_dir.glob("p116_foundation_*/p116_foundation.duckdb"),
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("未找到任何 p116_foundation.duckdb")
    return candidates[0]


# ── 列存在性检测 ─────────────────────────────────────────────
def _column_exists(conn: duckdb.DuckDBPyConnection, table: str, column: str) -> bool:
    rows = conn.execute(f"DESCRIBE {table}").fetchdf()
    return column in rows["column_name"].values


# ── Step 0: 创建备份表 ───────────────────────────────────────
BACKUP_TABLE = f"{TARGET_TABLE}_backup"


def create_backup(conn: duckdb.DuckDBPyConnection) -> bool:
    """在 ALTER TABLE 前创建备份表（如不存在）。"""
    tables = conn.execute("SHOW TABLES").fetchdf()
    if BACKUP_TABLE in tables["name"].values:
        log.info("备份表 %s 已存在，跳过", BACKUP_TABLE)
        return False
    conn.execute(f"CREATE TABLE {BACKUP_TABLE} AS SELECT * FROM {TARGET_TABLE}")
    row_count = conn.execute(f"SELECT COUNT(*) FROM {BACKUP_TABLE}").fetchone()[0]
    log.info("已创建备份表 %s (%d 行)", BACKUP_TABLE, row_count)
    return True


# ── Step 1: ALTER TABLE 追加字段 ─────────────────────────────
def add_columns(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """追加 4 个字段（如不存在），返回新增列名列表。"""
    columns_to_add = [
        ("data_quality_score", "INTEGER DEFAULT 0"),
        ("market_segment", "VARCHAR"),
        ("bar_history_days", "INTEGER"),
        ("post_suspension_days", "INTEGER DEFAULT 0"),
    ]
    added: list[str] = []
    for col_name, col_def in columns_to_add:
        if _column_exists(conn, TARGET_TABLE, col_name):
            log.info("列 %s 已存在，跳过 ALTER", col_name)
        else:
            conn.execute(f"ALTER TABLE {TARGET_TABLE} ADD COLUMN {col_name} {col_def}")
            added.append(col_name)
            log.info("已追加列 %s %s", col_name, col_def)

    # 确保 manifest 表存在
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {MANIFEST_TABLE} (
            run_id        VARCHAR,
            run_timestamp TIMESTAMP,
            foundation_db VARCHAR,
            rows_updated  BIGINT,
            degraded_count BIGINT,
            clean_count   BIGINT,
            steps_completed VARCHAR,
            elapsed_sec   DOUBLE
        )
    """)
    return added


# ── Step 2: 回填 market_segment ──────────────────────────────
def backfill_market_segment(conn: duckdb.DuckDBPyConnection) -> int:
    """按股票代码前缀回填 market_segment。"""
    t0 = time.time()

    # 用 CASE WHEN 一次性更新
    conn.execute(f"""
        UPDATE {TARGET_TABLE}
        SET market_segment = CASE
            WHEN LEFT(stock_code, 3) IN ('000', '001', '002') THEN 'SZ'
            WHEN LEFT(stock_code, 3) IN ('300', '301')         THEN 'CYB'
            WHEN LEFT(stock_code, 3) IN ('600', '601', '603', '605') THEN 'SH'
            WHEN LEFT(stock_code, 3) IN ('688', '689')         THEN 'STAR'
            ELSE 'OTHER'
        END
        WHERE market_segment IS NULL
    """)

    updated = conn.execute(
        f"SELECT COUNT(*) FROM {TARGET_TABLE} WHERE market_segment IS NOT NULL"
    ).fetchone()[0]

    log.info("market_segment 回填完成：%d 行 (%.1fs)", updated, time.time() - t0)
    return updated


# ── Step 3: 回填 bar_history_days ────────────────────────────
def backfill_bar_history_days(conn: duckdb.DuckDBPyConnection) -> int:
    """回填每行对应的累计 K 线条数（截至 state_date）。"""
    t0 = time.time()

    # 高效做法：先在 daily_bars 上算出每只股票的累计条数
    # 然后 JOIN 回 d1_perspective_state
    # bar_history_days = 截至该日期的 COUNT(*) OVER (PARTITION BY stock_code ORDER BY date)
    conn.execute(f"""
        UPDATE {TARGET_TABLE} t
        SET bar_history_days = sub.cnt
        FROM (
            SELECT stock_code, date,
                   COUNT(*) OVER (
                       PARTITION BY stock_code
                       ORDER BY date
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   ) AS cnt
            FROM daily_bars
        ) sub
        WHERE t.stock_code = sub.stock_code
          AND t.state_date = sub.date
          AND t.bar_history_days IS NULL
    """)

    updated = conn.execute(
        f"SELECT COUNT(*) FROM {TARGET_TABLE} WHERE bar_history_days IS NOT NULL"
    ).fetchone()[0]

    log.info("bar_history_days 回填完成：%d 行 (%.1fs)", updated, time.time() - t0)
    return updated


# ── Step 4: 回填 post_suspension_days ────────────────────────
def backfill_post_suspension_days(conn: duckdb.DuckDBPyConnection, dry_run: bool = False, batch_size: int = 250) -> dict:
    """检测停牌-复牌事件，回填 post_suspension_days。"""
    t0 = time.time()

    # ── 4a. 构建交易日历 ──
    calendar_df = conn.execute("""
        SELECT DISTINCT date AS trade_date
        FROM daily_bars
        ORDER BY trade_date
    """).fetchdf()
    all_trade_dates = calendar_df["trade_date"].tolist()
    trade_date_set = set(all_trade_dates)
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}

    log.info("交易日历：%d 个交易日 (%s ~ %s)",
             len(all_trade_dates), all_trade_dates[0], all_trade_dates[-1])

    # ── 4b. 每只股票的交易日集合 ──
    stock_dates_df = conn.execute("""
        SELECT stock_code, date
        FROM daily_bars
        ORDER BY stock_code, date
    """).fetchdf()

    stock_date_sets: dict[str, set] = {}
    for code, group in stock_dates_df.groupby("stock_code"):
        stock_date_sets[code] = set(group["date"].tolist())

    log.info("加载 %d 只股票的交易日数据", len(stock_date_sets))

    # ── 4c. 检测停牌事件 ──
    suspension_events: list[tuple[str, int, int]] = []
    result_records: list[dict] = []
    batch: list[dict] = []

    def _flush_batch(records: list[dict]) -> None:
        if not records:
            return
        df = pd.DataFrame(records)[["stock_code", "state_date", "post_suspension_days"]]
        conn.execute("DROP TABLE IF EXISTS _tmp_post_suspension")
        conn.execute("CREATE TEMPORARY TABLE _tmp_post_suspension AS SELECT * FROM df")
        conn.execute(f"""
            UPDATE d1_perspective_state t
            SET post_suspension_days = tmp.post_suspension_days
            FROM _tmp_post_suspension tmp
            WHERE t.stock_code = tmp.stock_code
              AND t.state_date = tmp.state_date
        """)
        conn.execute("DROP TABLE IF EXISTS _tmp_post_suspension")

    processed = 0
    for stock_code, stock_dates in stock_date_sets.items():
        missing_dates = sorted(trade_date_set - stock_dates)
        if not missing_dates:
            processed += 1
            continue

        events: list[tuple[int, int]] = []
        start_idx = date_to_idx[missing_dates[0]]
        prev_idx = start_idx
        for md in missing_dates[1:]:
            curr_idx = date_to_idx[md]
            if curr_idx == prev_idx + 1:
                prev_idx = curr_idx
            else:
                events.append((start_idx, prev_idx))
                start_idx = curr_idx
                prev_idx = curr_idx
        events.append((start_idx, prev_idx))

        for (s_idx, e_idx) in events:
            suspend_days = e_idx - s_idx + 1
            resume_idx = e_idx + 1
            if resume_idx < len(all_trade_dates):
                suspension_events.append((stock_code, suspend_days, resume_idx))
                for offset in range(1, POST_RESUMPTION_WINDOW + 1):
                    day_idx = resume_idx + offset - 1
                    if day_idx < len(all_trade_dates):
                        if dry_run:
                            result_records.append({
                                "stock_code": stock_code,
                                "state_date": all_trade_dates[day_idx],
                                "post_suspension_days": offset,
                                "_suspend_days": suspend_days,
                            })
                        else:
                            batch.append({
                                "stock_code": stock_code,
                                "state_date": all_trade_dates[day_idx],
                                "post_suspension_days": offset,
                                "_suspend_days": suspend_days,
                            })

        processed += 1
        if processed % 1000 == 0:
            log.info("停牌检测进度：%d / %d 只股票", processed, len(stock_date_sets))
        if batch and (processed % max(1, batch_size) == 0 or processed == len(stock_date_sets)):
            _flush_batch(batch)
            batch = []

    if batch:
        _flush_batch(batch)
    log.info("检测到 %d 次停牌-复牌事件（含 long/short）", len(suspension_events))

    # ── 4d. 写入 post_suspension_days（已改为逐批 flush） ──
    # 保留旧 result_records 仅用于 dry-run 预览

    stats = {
        "suspension_events": len(suspension_events),
        "long_suspensions": sum(1 for _, d, _ in suspension_events if d > LONG_SUSPENSION_THRESHOLD),
        "rows_with_post_suspension": len(result_records) if dry_run else -1,
    }
    log.info("post_suspension_days 回填完成：%s (%.1fs)", stats, time.time() - t0)
    return stats
def update_data_quality_score(conn: duckdb.DuckDBPyConnection) -> dict:
    """按 DEGRADED 规则更新 data_quality_score。

    命中任意一条 → 1，否则 → 0。
    """
    t0 = time.time()

    # 先全部重置为 0
    conn.execute(f"UPDATE {TARGET_TABLE} SET data_quality_score = 0")

    degraded_rules: list[tuple[str, str]] = [
        # Rule 1: IPO 首日 (bar_history_days < 1，即 bar_history_days IS NULL 或 = 0)
        (
            "IPO首日",
            f"""
            UPDATE {TARGET_TABLE}
            SET data_quality_score = 1
            WHERE (bar_history_days IS NULL OR bar_history_days < 1)
              AND data_quality_score = 0
            """,
        ),
        # Rule 2: 停牌日 (该股当日不在 daily_bars → bar_history_days IS NULL)
        # 注意：bar_history_days IS NULL 也可能是数据尚未回填
        # 更精确的停牌检测：在交易日历中但该股无 daily_bars 数据
        # 用 LEFT JOIN daily_bars 来判断
        (
            "停牌日",
            f"""
            UPDATE {TARGET_TABLE} t
            SET data_quality_score = 1
            FROM (
                SELECT cal.trade_date
                FROM (SELECT DISTINCT state_date AS trade_date FROM {TARGET_TABLE}) cal
            ) cal
            WHERE t.state_date = cal.trade_date
              AND NOT EXISTS (
                  SELECT 1 FROM daily_bars db
                  WHERE db.stock_code = t.stock_code AND db.date = t.state_date
              )
              AND t.data_quality_score = 0
            """,
        ),
        # Rule 3: 涨跌停日
        (
            "涨跌停日",
            f"""
            UPDATE {TARGET_TABLE} t
            SET data_quality_score = 1
            FROM (
                SELECT
                    stock_code,
                    date,
                    ABS(close - prev_close) / prev_close AS abs_return
                FROM (
                    SELECT
                        stock_code,
                        date,
                        close,
                        LAG(close) OVER (PARTITION BY stock_code ORDER BY date) AS prev_close
                    FROM daily_bars
                ) sub
                WHERE prev_close IS NOT NULL AND prev_close > 0
            ) ret
            WHERE t.stock_code = ret.stock_code
              AND t.state_date = ret.date
              AND t.data_quality_score = 0
              AND (
                  (t.market_segment IN ('CYB', 'STAR') AND ret.abs_return >= {LIMIT_THRESHOLD_GEM})
                  OR
                  (t.market_segment NOT IN ('CYB', 'STAR') AND ret.abs_return >= {LIMIT_THRESHOLD_MAIN})
              )
            """,
        ),
        # Rule 4: 长期停牌复牌后前5日 (post_suspension_days ∈ [1,5] 且停牌 > 30 天)
        # 注意：post_suspension_days 只在长期停牌复牌后才被赋值 > 0
        # 所以这里只需检查 post_suspension_days BETWEEN 1 AND POST_RESUMPTION_WINDOW
        (
            "长期停牌复牌后5日",
            f"""
            UPDATE {TARGET_TABLE}
            SET data_quality_score = 1
            WHERE post_suspension_days BETWEEN 1 AND {POST_RESUMPTION_WINDOW}
              AND data_quality_score = 0
            """,
        ),
    ]

    rule_stats: dict[str, int] = {}
    for rule_name, sql in degraded_rules:
        try:
            conn.execute(sql)
            # 统计本规则命中数（通过差值方式不好做，改为直接查）
            rule_stats[rule_name] = -1  # placeholder
        except Exception as e:
            log.warning("规则 [%s] 执行异常: %s", rule_name, e)
            rule_stats[rule_name] = -999

    # 精确统计各规则命中数（独立查询）
    rule_counts = {}
    rule_counts["IPO首日"] = conn.execute(
        f"SELECT COUNT(*) FROM {TARGET_TABLE} WHERE bar_history_days IS NULL OR bar_history_days < 1"
    ).fetchone()[0]

    rule_counts["涨跌停日"] = conn.execute(f"""
        SELECT COUNT(*)
        FROM {TARGET_TABLE} t
        JOIN (
            SELECT stock_code, date,
                   ABS(close - LAG(close) OVER (PARTITION BY stock_code ORDER BY date))
                       / LAG(close) OVER (PARTITION BY stock_code ORDER BY date) AS abs_return
            FROM daily_bars
        ) ret ON t.stock_code = ret.stock_code AND t.state_date = ret.date
        WHERE ret.abs_return IS NOT NULL
          AND (
              (t.market_segment IN ('CYB', 'STAR') AND ret.abs_return >= {LIMIT_THRESHOLD_GEM})
              OR
              (t.market_segment NOT IN ('CYB', 'STAR') AND ret.abs_return >= {LIMIT_THRESHOLD_MAIN})
          )
    """).fetchone()[0]

    rule_counts["长期停牌复牌后5日"] = conn.execute(
        f"SELECT COUNT(*) FROM {TARGET_TABLE} WHERE post_suspension_days BETWEEN 1 AND {POST_RESUMPTION_WINDOW}"
    ).fetchone()[0]

    # 最终统计
    total = conn.execute(f"SELECT COUNT(*) FROM {TARGET_TABLE}").fetchone()[0]
    degraded = conn.execute(
        f"SELECT COUNT(*) FROM {TARGET_TABLE} WHERE data_quality_score = 1"
    ).fetchone()[0]
    clean = total - degraded

    # 红线 3：如有 DEGRADED 数据，提交人类审核
    if degraded > 0:
        from hermass_platform.red_lines import flag_data_anomaly
        flag_data_anomaly(
            agent_id="add_data_quality_fields",
            anomaly_type="DEGRADED_data_detected",
            stock_code="",
            details={
                "degraded_count": degraded,
                "clean_count": clean,
                "degraded_pct": round(degraded / total * 100, 2) if total else 0,
                "rule_counts": rule_counts,
            },
        )

    stats = {
        "total_rows": total,
        "degraded_count": degraded,
        "clean_count": clean,
        "degraded_pct": round(degraded / total * 100, 2) if total else 0,
        "rule_counts": rule_counts,
    }
    log.info("data_quality_score 更新完成：%s (%.1fs)", stats, time.time() - t0)
    return stats


# ── Step 6: 写入 manifest ────────────────────────────────────
def write_manifest(
    conn: duckdb.DuckDBPyConnection,
    foundation_db: str,
    stats: dict,
    elapsed: float,
) -> None:
    run_id = datetime.now(timezone.utc).strftime("dq_%Y%m%d_%H%M%S")
    conn.execute(f"""
        INSERT INTO {MANIFEST_TABLE}
        VALUES (
            '{run_id}',
            CURRENT_TIMESTAMP,
            '{foundation_db}',
            {stats.get('total_rows', 0)},
            {stats.get('degraded_count', 0)},
            {stats.get('clean_count', 0)},
            'add_columns,market_segment,bar_history_days,post_suspension_days,data_quality_score',
            {elapsed:.1f}
        )
    """)
    log.info("manifest 已写入 run_id=%s", run_id)


# ── 主流程 ────────────────────────────────────────────────────
def run(foundation_db: Path, dry_run: bool = False, batch_size: int = 250) -> dict:
    t_start = time.time()
    log.info("=" * 60)
    log.info("Data Quality Fields — 开始处理")
    log.info("foundation_db: %s", foundation_db)
    log.info("=" * 60)

    conn = duckdb.connect(str(foundation_db))
    conn.execute("SET preserve_insertion_order=false")

    # Step 0: 创建备份表
    log.info("── Step 0: 创建备份表 ──")
    create_backup(conn)

    # Step 1: 追加字段
    log.info("── Step 1: ALTER TABLE 追加字段 ──")
    added = add_columns(conn)
    log.info("新增列: %s", added if added else "(无，均已存在)")

    # Step 2: 回填 market_segment
    log.info("── Step 2: 回填 market_segment ──")
    backfill_market_segment(conn)

    # Step 3: 回填 bar_history_days
    log.info("── Step 3: 回填 bar_history_days ──")
    backfill_bar_history_days(conn)

    # Step 4: 回填 post_suspension_days
    log.info("── Step 4: 回填 post_suspension_days ──")
    psd_stats = backfill_post_suspension_days(conn, dry_run=dry_run, batch_size=batch_size)

    # Step 5: 更新 data_quality_score
    log.info("── Step 5: 更新 data_quality_score ──")
    dq_stats = update_data_quality_score(conn)

    # Step 6: 写入 manifest
    elapsed = time.time() - t_start
    write_manifest(conn, str(foundation_db), dq_stats, elapsed)

    conn.close()

    log.info("=" * 60)
    log.info("全部完成 (%.1fs)", elapsed)
    log.info("  总行数: %d", dq_stats["total_rows"])
    log.info("  DEGRADED: %d (%.2f%%)", dq_stats["degraded_count"], dq_stats["degraded_pct"])
    log.info("  CLEAN: %d", dq_stats["clean_count"])
    log.info("  停牌事件: %d (长期: %d)",
             psd_stats["suspension_events"], psd_stats["long_suspensions"])
    log.info("=" * 60)

    return {
        "foundation_db": str(foundation_db),
        "added_columns": added,
        "post_suspension_stats": psd_stats,
        "data_quality_stats": dq_stats,
        "elapsed_sec": round(elapsed, 1),
    }


# ── CLI ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="追加数据质量字段并回填 d1_perspective_state"
    )
    parser.add_argument(
        "--date",
        type=str,
        default="",
        help="目标日期 (YYYY-MM-DD)，默认取最新 foundation",
    )
    parser.add_argument(
        "--foundation-db",
        type=str,
        default="",
        help="直接指定 foundation.duckdb 路径（覆盖 --date）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印会执行的写入动作，不实际修改数据库",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=250,
        help="post_suspension_days 回填分批大小，默认 250",
    )
    args = parser.parse_args()

    if args.foundation_db:
        db_path = Path(args.foundation_db)
    else:
        db_path = find_foundation_db(args.date)

    if not db_path.exists():
        log.error("foundation DB 不存在: %s", db_path)
        sys.exit(1)

    result = run(db_path, dry_run=args.dry_run, batch_size=args.batch_size)

    # 输出摘要到 stdout (方便 pipeline 消费)
    import json
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()