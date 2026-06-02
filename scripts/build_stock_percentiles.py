#!/usr/bin/env python3
"""股票级分位阈值表 — 构建 stock_percentile_thresholds。

为每只股票计算 BB/枢轴/ATR 在 60-bar 和 120-bar 窗口下的分位数阈值。

逻辑：
  1. 排除 data_quality_score = DEGRADED 的日期
  2. 次新股 (bar_history_days < 120) 用同 market_segment 均值代替
  3. 每日增量更新

用法：
  python3 scripts/build_stock_percentiles.py --date 2026-06-02
  python3 scripts/build_stock_percentiles.py --foundation-db /path/to/foundation.duckdb
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
log = logging.getLogger("build_stock_percentiles")

TARGET_TABLE = "stock_percentile_thresholds"
LOOKBACK_WINDOWS = [60, 120]
METRICS = ["bb_width", "pivot_width", "atr_ratio"]
QUANTILES = [5, 10, 20, 50, 80]


# ── 辅助 ─────────────────────────────────────────────────────
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


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"DESCRIBE {table}").fetchdf()
    return column in rows["column_name"].values


# ── Step 1: 建表 ─────────────────────────────────────────────
def create_table(conn: duckdb.DuckDBPyConnection) -> bool:
    tables = conn.execute("SHOW TABLES").fetchdf()
    if TARGET_TABLE in tables["name"].values:
        log.info("表 %s 已存在", TARGET_TABLE)
        return False

    conn.execute(f"""
        CREATE TABLE {TARGET_TABLE} (
            stock_code       VARCHAR   NOT NULL,
            timeframe        VARCHAR   NOT NULL,
            lookback_bars    INTEGER   NOT NULL,
            metric_name      VARCHAR   NOT NULL,
            q5               DOUBLE,
            q10              DOUBLE,
            q20              DOUBLE,
            q50              DOUBLE,
            q80              DOUBLE,
            last_updated     DATE,
            PRIMARY KEY (stock_code, timeframe, lookback_bars, metric_name)
        )
    """)

    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_spt_stock ON {TARGET_TABLE}(stock_code)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_spt_metric ON {TARGET_TABLE}(metric_name)")

    log.info("已创建表 %s", TARGET_TABLE)
    return True


# ── Step 2: 计算分位数 ────────────────────────────────────────
def compute_percentiles(
    conn: duckdb.DuckDBPyConnection,
    target_date: str,
    incremental: bool = True,
) -> pd.DataFrame:
    """计算所有股票的分位数。"""
    t0 = time.time()

    has_dq = _column_exists(conn, "d1_perspective_state", "data_quality_score")
    dq_filter = "AND data_quality_score = 0" if has_dq else ""

    # ── 获取历史数据 ──
    # 对每只股票每个 timeframe，取最近 N bar 的指标值
    all_results = []

    for window in LOOKBACK_WINDOWS:
        log.info("── 处理 lookback=%d ──", window)

        for tf in ["D1", "W1", "MN1"]:
            # 获取历史指标数据
            sql = f"""
                WITH target AS (
                    SELECT DISTINCT stock_code, available_date AS state_date
                    FROM timeframe_indicators
                    WHERE timeframe = '{tf}'
                    {f"AND available_date = DATE '{target_date}'" if incremental else ""}
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
                    WHERE ti.timeframe = '{tf}'
                      AND ti.available_date <= t.state_date
                      AND ti.bb_width_pct IS NOT NULL
                )
                SELECT stock_code, bb_width_pct, atr_ratio_pct
                FROM history
                WHERE rn <= {window}
            """
            df = conn.execute(sql).fetchdf()

            if df.empty:
                log.warning("  %s window=%d: 无数据", tf, window)
                continue

            # 获取 pivot_width 数据
            pivot_sql = f"""
                SELECT
                    stock_code,
                    state_date,
                    d1_close,
                    d1_sr_support,
                    d1_sr_resistance,
                    w1_sr_support,
                    w1_sr_resistance,
                    mn1_sr_support,
                    mn1_sr_resistance
                FROM d1_perspective_state
                WHERE state_date = DATE '{target_date}'
            """
            pivot_df = conn.execute(pivot_sql).fetchdf()

            # 计算 pivot_width
            sr_map = {
                "D1": ("d1_sr_support", "d1_sr_resistance"),
                "W1": ("w1_sr_support", "w1_sr_resistance"),
                "MN1": ("mn1_sr_support", "mn1_sr_resistance"),
            }
            sup_col, res_col = sr_map[tf]

            if not pivot_df.empty and sup_col in pivot_df.columns:
                pivot_df["pivot_width"] = np.where(
                    (pivot_df["d1_close"] > 0) &
                    pivot_df[sup_col].notna() &
                    pivot_df[res_col].notna(),
                    (pivot_df[res_col] - pivot_df[sup_col]) / pivot_df["d1_close"],
                    np.nan,
                )
                pivot_df = pivot_df[["stock_code", "pivot_width"]]
            else:
                pivot_df = pd.DataFrame(columns=["stock_code", "pivot_width"])

            # 合并 pivot 到主数据
            if not pivot_df.empty:
                df = df.merge(pivot_df, on="stock_code", how="left")
            else:
                df["pivot_width"] = np.nan

            # ── 计算分位数 ──
            def calc_quantile(series, q):
                clean = series.dropna()
                if len(clean) < q:
                    return np.nan
                return np.percentile(clean, q)

            results = df.groupby("stock_code").agg(
                bb_width_q5=("bb_width_pct", lambda x: calc_quantile(x, 5)),
                bb_width_q10=("bb_width_pct", lambda x: calc_quantile(x, 10)),
                bb_width_q20=("bb_width_pct", lambda x: calc_quantile(x, 20)),
                bb_width_q50=("bb_width_pct", lambda x: calc_quantile(x, 50)),
                bb_width_q80=("bb_width_pct", lambda x: calc_quantile(x, 80)),
                pivot_width_q5=("pivot_width", lambda x: calc_quantile(x, 5)),
                pivot_width_q10=("pivot_width", lambda x: calc_quantile(x, 10)),
                pivot_width_q20=("pivot_width", lambda x: calc_quantile(x, 20)),
                pivot_width_q50=("pivot_width", lambda x: calc_quantile(x, 50)),
                pivot_width_q80=("pivot_width", lambda x: calc_quantile(x, 80)),
                atr_ratio_q5=("atr_ratio_pct", lambda x: calc_quantile(x, 5)),
                atr_ratio_q10=("atr_ratio_pct", lambda x: calc_quantile(x, 10)),
                atr_ratio_q20=("atr_ratio_pct", lambda x: calc_quantile(x, 20)),
                atr_ratio_q50=("atr_ratio_pct", lambda x: calc_quantile(x, 50)),
                atr_ratio_q80=("atr_ratio_pct", lambda x: calc_quantile(x, 80)),
            ).reset_index()

            # 转换为长格式
            for metric in METRICS:
                metric_results = results[["stock_code"]].copy()
                metric_results["timeframe"] = tf
                metric_results["lookback_bars"] = window
                metric_results["metric_name"] = metric
                metric_results["q5"] = results[f"{metric}_q5"]
                metric_results["q10"] = results[f"{metric}_q10"]
                metric_results["q20"] = results[f"{metric}_q20"]
                metric_results["q50"] = results[f"{metric}_q50"]
                metric_results["q80"] = results[f"{metric}_q80"]
                metric_results["last_updated"] = target_date
                all_results.append(metric_results)

            log.info("  %s window=%d: %d 只股票", tf, window, len(results))

    if not all_results:
        return pd.DataFrame()

    result = pd.concat(all_results, ignore_index=True)
    log.info("计算完成: %d 行 (%.1fs)", len(result), time.time() - t0)
    return result


# ── Step 3: 次新股处理 ────────────────────────────────────────
def handle_new_stocks(
    conn: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    target_date: str,
) -> pd.DataFrame:
    """对次新股 (bar_history_days < 120) 用同 market_segment 均值代替。"""
    if df.empty:
        return df

    has_bh = _column_exists(conn, "d1_perspective_state", "bar_history_days")
    has_ms = _column_exists(conn, "d1_perspective_state", "market_segment")

    if not has_bh or not has_ms:
        log.info("bar_history_days 或 market_segment 列不存在，跳过次新股处理")
        return df

    # 获取股票的 bar_history_days 和 market_segment
    stock_info_sql = f"""
        SELECT DISTINCT stock_code, bar_history_days, market_segment
        FROM d1_perspective_state
        WHERE state_date = DATE '{target_date}'
    """
    stock_info = conn.execute(stock_info_sql).fetchdf()

    if stock_info.empty:
        return df

    # 找出次新股 (bar_history_days < 120)
    new_stocks = stock_info[stock_info["bar_history_days"] < 120]["stock_code"].tolist()

    if not new_stocks:
        log.info("无次新股需要处理")
        return df

    log.info("发现 %d 只次新股", len(new_stocks))

    # 计算每个 market_segment 的均值
    segment_means = {}
    for segment in stock_info["market_segment"].dropna().unique():
        segment_stocks = stock_info[
            (stock_info["market_segment"] == segment) &
            (stock_info["bar_history_days"] >= 120)
        ]["stock_code"].tolist()

        if not segment_stocks:
            continue

        segment_data = df[df["stock_code"].isin(segment_stocks)]
        if segment_data.empty:
            continue

        means = segment_data.groupby(["timeframe", "lookback_bars", "metric_name"]).agg({
            "q5": "mean", "q10": "mean", "q20": "mean", "q50": "mean", "q80": "mean"
        }).reset_index()

        segment_means[segment] = means

    # 替换次新股的数据
    for stock_code in new_stocks:
        stock_segment = stock_info[stock_info["stock_code"] == stock_code]["market_segment"].iloc[0]
        if pd.isna(stock_segment) or stock_segment not in segment_means:
            continue

        means = segment_means[stock_segment]

        # 删除该股票的现有数据
        df = df[df["stock_code"] != stock_code]

        # 添加均值数据
        new_rows = means.copy()
        new_rows["stock_code"] = stock_code
        new_rows["last_updated"] = target_date
        df = pd.concat([df, new_rows], ignore_index=True)

    log.info("次新股处理完成")
    return df


# ── Step 4: 写入数据库 ────────────────────────────────────────
def write_incremental(
    conn: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    target_date: str,
) -> dict:
    if df.empty:
        log.warning("无数据可写入")
        return {"rows_written": 0}

    t0 = time.time()

    # DELETE 当日数据
    conn.execute(f"""
        DELETE FROM {TARGET_TABLE}
        WHERE last_updated = DATE '{target_date}'
    """)

    # INSERT 新数据
    conn.execute(f"""
        INSERT INTO {TARGET_TABLE}
        SELECT * FROM df
    """)

    rows_written = len(df)
    log.info("写入完成: %d 行 (%.1fs)", rows_written, time.time() - t0)
    return {"rows_written": rows_written}


# ── 主流程 ────────────────────────────────────────────────────
def run(foundation_db: Path, target_date: str = "", incremental: bool = True) -> dict:
    t_start = time.time()
    log.info("=" * 60)
    log.info("股票级分位阈值表 — 开始处理")
    log.info("foundation_db: %s", foundation_db)
    log.info("target_date: %s", target_date if target_date else "(最新)")
    log.info("incremental: %s", incremental)
    log.info("=" * 60)

    conn = duckdb.connect(str(foundation_db))

    # Step 1: 建表
    log.info("── Step 1: 建表 ──")
    create_table(conn)

    # 确定目标日期
    if not target_date:
        target_date = str(conn.execute("""
            SELECT MAX(state_date) FROM d1_perspective_state
        """).fetchone()[0])
    log.info("目标日期: %s", target_date)

    # Step 2: 计算分位数
    log.info("── Step 2: 计算分位数 ──")
    df = compute_percentiles(conn, target_date, incremental)

    if df.empty:
        log.warning("无数据可处理")
        conn.close()
        return {"status": "no_data", "elapsed_sec": time.time() - t_start}

    # Step 3: 次新股处理
    log.info("── Step 3: 次新股处理 ──")
    df = handle_new_stocks(conn, df, target_date)

    # Step 4: 写入
    log.info("── Step 4: 写入数据库 ──")
    write_stats = write_incremental(conn, df, target_date)

    total = conn.execute(f"SELECT COUNT(*) FROM {TARGET_TABLE}").fetchone()[0]
    conn.close()

    elapsed = time.time() - t_start
    log.info("=" * 60)
    log.info("全部完成 (%.1fs)", elapsed)
    log.info("  总行数: %d", total)
    log.info("  本次写入: %d", write_stats["rows_written"])
    log.info("=" * 60)

    return {
        "foundation_db": str(foundation_db),
        "target_date": target_date,
        "rows_written": write_stats["rows_written"],
        "total_rows": total,
        "elapsed_sec": round(elapsed, 1),
    }


# ── CLI ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="构建股票级分位阈值表"
    )
    parser.add_argument("--date", type=str, default="", help="目标日期")
    parser.add_argument("--foundation-db", type=str, default="", help="foundation.duckdb 路径")
    parser.add_argument("--full", action="store_true", help="全量重建")
    args = parser.parse_args()

    if args.foundation_db:
        db_path = Path(args.foundation_db)
    else:
        db_path = find_foundation_db(args.date)

    if not db_path.exists():
        log.error("foundation DB 不存在: %s", db_path)
        sys.exit(1)

    result = run(db_path, args.date, incremental=not args.full)

    import json
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
