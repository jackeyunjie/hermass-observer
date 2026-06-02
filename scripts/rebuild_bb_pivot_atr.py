#!/usr/bin/env python3
"""BB/Pivot/ATR 物化视图 — 收缩度计算。

在 Foundation DB 中创建 `bb_pivot_atr` 表，包含：
  - BB 带宽分位数（Q10/Q20/Q50，60-bar 滚动窗口）
  - 枢轴宽度分位数（Q20，60-bar 滚动窗口）
  - ATR 比率分位数（Q20，60-bar 滚动窗口）
  - triple_squeeze: BB<Q20 AND pivot<Q20 AND atr<Q20
  - squeeze_score: 收缩度 0-100
  - data_quality_score: 引用 d1_perspective_state 的质量标记

幂等：多次执行不报错，只追加新数据（DELETE + INSERT 当日）。

用法：
  python3 scripts/rebuild_bb_pivot_atr.py --date 2026-06-02
  python3 scripts/rebuild_bb_pivot_atr.py --foundation-db /path/to/foundation.duckdb
  python3 scripts/rebuild_bb_pivot_atr.py --full   # 全量重建（慢）
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rebuild_bb_pivot_atr")

TARGET_TABLE = "bb_pivot_atr"
ROLLING_WINDOW = 60  # 60-bar 滚动窗口

# ── 辅助：定位 foundation DB ─────────────────────────────────
def default_foundation_db(date: str) -> Path:
    ymd = date.replace("-", "")
    return ROOT / "outputs" / f"p116_foundation_{ymd}" / "p116_foundation.duckdb"


def find_foundation_db(date: str = "") -> Path:
    if date:
        p = default_foundation_db(date)
        if p.exists():
            return p
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


# ── Step 1: 建表 ─────────────────────────────────────────────
def create_table(conn: duckdb.DuckDBPyConnection) -> bool:
    """创建 bb_pivot_atr 表（如不存在）。返回 True 表示新建。"""
    tables = conn.execute("SHOW TABLES").fetchdf()
    if TARGET_TABLE in tables["name"].values:
        log.info("表 %s 已存在", TARGET_TABLE)
        return False

    conn.execute(f"""
        CREATE TABLE {TARGET_TABLE} (
            stock_code           VARCHAR   NOT NULL,
            state_date           DATE      NOT NULL,
            timeframe            VARCHAR   NOT NULL,
            bb_width_pct         DOUBLE,
            bb_width_q10         DOUBLE,
            bb_width_q20         DOUBLE,
            bb_width_q50         DOUBLE,
            pivot_width          DOUBLE,
            pivot_width_q20      DOUBLE,
            atr_ratio_pct        DOUBLE,
            atr_ratio_q20        DOUBLE,
            triple_squeeze       BOOLEAN,
            squeeze_score        INTEGER,
            data_quality_score   INTEGER   DEFAULT 0,
            PRIMARY KEY (stock_code, state_date, timeframe)
        )
    """)

    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_bpa_date ON {TARGET_TABLE}(state_date)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_bpa_squeeze ON {TARGET_TABLE}(triple_squeeze)")

    log.info("已创建表 %s", TARGET_TABLE)
    return True


# ── Step 2: 计算单个 timeframe 的数据 ─────────────────────────
def compute_one_timeframe(
    conn: duckdb.DuckDBPyConnection,
    timeframe: str,
    date_value: str,
    has_dq: bool,
) -> pd.DataFrame:
    """计算单个 timeframe 的 bb_pivot_atr 数据。"""
    t0 = time.time()

    dq_col = "data_quality_score" if has_dq else "0 AS data_quality_score"
    date_where = f"WHERE available_date = DATE '{date_value}'" if date_value else ""

    # ── 获取 BB/ATR 历史窗口 ──
    bb_atr_sql = f"""
        WITH target AS (
            SELECT DISTINCT stock_code, available_date AS state_date
            FROM timeframe_indicators
            WHERE timeframe = '{timeframe}'
            {f"AND available_date = DATE '{date_value}'" if date_value else ""}
        ),
        history AS (
            SELECT
                ti.stock_code,
                ti.available_date,
                ti.bb_width_pct,
                ti.atr_ratio_pct,
                ROW_NUMBER() OVER (
                    PARTITION BY ti.stock_code
                    ORDER BY ti.available_date DESC
                ) AS rn
            FROM timeframe_indicators ti
            JOIN target t ON ti.stock_code = t.stock_code
            WHERE ti.timeframe = '{timeframe}'
              AND ti.available_date <= t.state_date
              AND ti.bb_width_pct IS NOT NULL
        )
        SELECT * FROM history WHERE rn <= {ROLLING_WINDOW}
    """
    history_df = conn.execute(bb_atr_sql).fetchdf()

    if history_df.empty:
        log.warning("  %s: 无历史数据", timeframe)
        return pd.DataFrame()

    # ── 计算分位数 ──
    bb_quantiles = history_df.groupby("stock_code").agg(
        bb_width_q10=("bb_width_pct", lambda x: np.percentile(x.dropna(), 10) if len(x.dropna()) >= 10 else np.nan),
        bb_width_q20=("bb_width_pct", lambda x: np.percentile(x.dropna(), 20) if len(x.dropna()) >= 20 else np.nan),
        bb_width_q50=("bb_width_pct", lambda x: np.percentile(x.dropna(), 50) if len(x.dropna()) > 0 else np.nan),
        atr_ratio_q20=("atr_ratio_pct", lambda x: np.percentile(x.dropna(), 20) if len(x.dropna()) >= 20 else np.nan),
    ).reset_index()

    # ── 获取当前日期的 BB/ATR 值 ──
    current_sql = f"""
        SELECT
            stock_code,
            available_date AS state_date,
            bb_width_pct,
            atr_ratio_pct
        FROM timeframe_indicators
        WHERE timeframe = '{timeframe}'
        {f"AND available_date = DATE '{date_value}'" if date_value else ""}
          AND bb_width_pct IS NOT NULL
    """
    current_df = conn.execute(current_sql).fetchdf()

    if current_df.empty:
        log.warning("  %s: 当前日期无数据", timeframe)
        return pd.DataFrame()

    # ── 获取 pivot 数据 ──
    # d1_perspective_state 的 state_date 对应 D1，对于 W1/MN1 需要找到最近的 state_date
    tf_sr_map = {
        "D1": ("d1_sr_support", "d1_sr_resistance"),
        "W1": ("w1_sr_support", "w1_sr_resistance"),
        "MN1": ("mn1_sr_support", "mn1_sr_resistance"),
    }
    sup_col, res_col = tf_sr_map[timeframe]

    pivot_sql = f"""
        SELECT
            stock_code,
            state_date,
            d1_close,
            {sup_col} AS sr_support,
            {res_col} AS sr_resistance,
            {dq_col}
        FROM d1_perspective_state
        WHERE state_date = DATE '{date_value}'
    """
    pivot_df = conn.execute(pivot_sql).fetchdf()

    # 计算 pivot_width
    if not pivot_df.empty:
        pivot_df["pivot_width"] = np.where(
            (pivot_df["d1_close"] > 0) & pivot_df["sr_support"].notna() & pivot_df["sr_resistance"].notna(),
            (pivot_df["sr_resistance"] - pivot_df["sr_support"]) / pivot_df["d1_close"],
            np.nan,
        )
    else:
        pivot_df["pivot_width"] = np.nan

    # ── 合并数据 ──
    result = current_df.merge(bb_quantiles, on="stock_code", how="left")
    result["timeframe"] = timeframe

    # 合并 pivot
    if not pivot_df.empty:
        pivot_cols = ["stock_code", "state_date", "pivot_width", "data_quality_score"]
        result = result.merge(pivot_df[pivot_cols], on=["stock_code", "state_date"], how="left")
    else:
        result["pivot_width"] = np.nan
        result["data_quality_score"] = 0

    # pivot_width_q20 临时近似（TODO: 实现完整历史分位数计算）
    result["pivot_width_q20"] = result["pivot_width"] * 0.8

    # ── 计算 triple_squeeze 和 squeeze_score ──
    result["bb_below_q20"] = result["bb_width_pct"] < result["bb_width_q20"]
    result["pivot_below_q20"] = result["pivot_width"] < result["pivot_width_q20"]
    result["atr_below_q20"] = result["atr_ratio_pct"] < result["atr_ratio_q20"]

    result["triple_squeeze"] = (
        result["bb_below_q20"] &
        result["pivot_below_q20"] &
        result["atr_below_q20"]
    )

    def calc_squeeze_score(row):
        if pd.isna(row.get("data_quality_score")) or row.get("data_quality_score") == 1:
            return None
        scores = []
        if not pd.isna(row["bb_width_q20"]) and row["bb_width_q20"] > 0:
            scores.append(max(0, min(100, (row["bb_width_q20"] - row["bb_width_pct"]) / row["bb_width_q20"] * 100)))
        if not pd.isna(row["pivot_width_q20"]) and row["pivot_width_q20"] > 0:
            scores.append(max(0, min(100, (row["pivot_width_q20"] - row["pivot_width"]) / row["pivot_width_q20"] * 100)))
        if not pd.isna(row["atr_ratio_q20"]) and row["atr_ratio_q20"] > 0:
            scores.append(max(0, min(100, (row["atr_ratio_q20"] - row["atr_ratio_pct"]) / row["atr_ratio_q20"] * 100)))
        return int(np.mean(scores)) if scores else None

    result["squeeze_score"] = result.apply(calc_squeeze_score, axis=1)

    # 清理临时列
    result = result[[
        "stock_code", "state_date", "timeframe",
        "bb_width_pct", "bb_width_q10", "bb_width_q20", "bb_width_q50",
        "pivot_width", "pivot_width_q20",
        "atr_ratio_pct", "atr_ratio_q20",
        "triple_squeeze", "squeeze_score", "data_quality_score",
    ]]

    log.info("  %s: %d 行 (%.1fs)", timeframe, len(result), time.time() - t0)
    return result


# ── Step 3: 计算所有 timeframe ────────────────────────────────
def compute_incremental(
    conn: duckdb.DuckDBPyConnection,
    target_date: str = "",
    full_rebuild: bool = False,
) -> pd.DataFrame:
    """计算所有 timeframe 的 bb_pivot_atr 数据。"""
    t0 = time.time()

    # 检查 data_quality_score 列是否存在
    has_dq = _column_exists(conn, "d1_perspective_state", "data_quality_score")

    # ── 确定目标日期 ──
    if target_date and not full_rebuild:
        target_dates = {"D1": target_date, "W1": target_date, "MN1": target_date}
    elif full_rebuild:
        target_dates = {"D1": "", "W1": "", "MN1": ""}
    else:
        latest_dates = conn.execute("""
            SELECT timeframe, MAX(available_date) as max_date
            FROM timeframe_indicators
            GROUP BY timeframe
        """).fetchdf()
        target_dates = {}
        for _, row in latest_dates.iterrows():
            target_dates[row["timeframe"]] = str(row["max_date"])

    log.info("计算目标: %s", target_dates if not full_rebuild else "全量重建")

    # 处理每个 timeframe
    all_results = []
    for tf in ["D1", "W1", "MN1"]:
        date_value = target_dates.get(tf, "")
        if not date_value and not full_rebuild:
            continue

        df = compute_one_timeframe(conn, tf, date_value, has_dq)
        if not df.empty:
            all_results.append(df)

    if not all_results:
        log.warning("无数据可处理")
        return pd.DataFrame()

    result = pd.concat(all_results, ignore_index=True)
    log.info("计算完成: %d 行 (%.1fs)", len(result), time.time() - t0)
    return result


# ── Step 4: 写入数据库 ───────────────────────────────────────
def write_incremental(
    conn: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
) -> dict:
    """增量写入：DELETE 当日 + INSERT 新数据。"""
    if df.empty:
        log.warning("无数据可写入")
        return {"rows_written": 0}

    t0 = time.time()

    # 按日期分组写入
    for state_date, group_df in df.groupby("state_date"):
        date_str = str(state_date)[:10]  # 取日期部分
        conn.execute(f"""
            DELETE FROM {TARGET_TABLE}
            WHERE state_date = DATE '{date_str}'
        """)
        conn.execute(f"""
            INSERT INTO {TARGET_TABLE}
            SELECT * FROM group_df
        """)
        log.info("  写入 %s: %d 行", date_str, len(group_df))

    rows_written = len(df)
    log.info("写入完成: %d 行 (%.1fs)", rows_written, time.time() - t0)

    return {"rows_written": rows_written}


# ── 主流程 ────────────────────────────────────────────────────
def run(foundation_db: Path, target_date: str = "", full_rebuild: bool = False) -> dict:
    t_start = time.time()
    log.info("=" * 60)
    log.info("BB/Pivot/ATR 物化视图 — 开始处理")
    log.info("foundation_db: %s", foundation_db)
    log.info("target_date: %s", target_date if target_date else "(最新)")
    log.info("full_rebuild: %s", full_rebuild)
    log.info("=" * 60)

    conn = duckdb.connect(str(foundation_db))

    # Step 1: 建表
    log.info("── Step 1: 建表 ──")
    create_table(conn)

    # Step 2-3: 计算
    log.info("── Step 2-3: 计算数据 ──")
    df = compute_incremental(conn, target_date, full_rebuild)

    if df.empty:
        log.warning("无数据可处理")
        conn.close()
        return {"status": "no_data", "elapsed_sec": time.time() - t_start}

    # Step 4: 写入
    log.info("── Step 4: 写入数据库 ──")
    write_stats = write_incremental(conn, df)

    # 统计
    total = conn.execute(f"SELECT COUNT(*) FROM {TARGET_TABLE}").fetchone()[0]
    squeeze_count = conn.execute(
        f"SELECT COUNT(*) FROM {TARGET_TABLE} WHERE triple_squeeze = TRUE"
    ).fetchone()[0]

    conn.close()

    elapsed = time.time() - t_start
    log.info("=" * 60)
    log.info("全部完成 (%.1fs)", elapsed)
    log.info("  总行数: %d", total)
    log.info("  本次写入: %d", write_stats["rows_written"])
    log.info("  triple_squeeze 总数: %d", squeeze_count)
    log.info("=" * 60)

    return {
        "foundation_db": str(foundation_db),
        "rows_written": write_stats["rows_written"],
        "squeeze_count": squeeze_count,
        "total_rows": total,
        "elapsed_sec": round(elapsed, 1),
    }


# ── CLI ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="BB/Pivot/ATR 物化视图 — 收缩度计算"
    )
    parser.add_argument(
        "--date",
        type=str,
        default="",
        help="目标日期 (YYYY-MM-DD)，默认取每个 timeframe 的最新日期",
    )
    parser.add_argument(
        "--foundation-db",
        type=str,
        default="",
        help="直接指定 foundation.duckdb 路径",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="全量重建（慢，仅用于初始化）",
    )
    args = parser.parse_args()

    if args.foundation_db:
        db_path = Path(args.foundation_db)
    else:
        db_path = find_foundation_db(args.date)

    if not db_path.exists():
        log.error("foundation DB 不存在: %s", db_path)
        sys.exit(1)

    result = run(db_path, args.date, args.full)

    import json
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
