#!/usr/bin/env python3
"""Phase 1: 产业链动态指标填充 —— AKShare 期货价格数据

根据 docs/CHAIN_DATA_POPULATION_PLAN.md 的 Phase 1 方案，拉取 4 个期货品种
（碳酸锂 LC、工业硅 SI、多晶硅 PS、铜 CU）的日线数据，转换为 chain_dynamics
表记录并写入 DuckDB，同时生成数据覆盖报告。

执行:
    source .venv/bin/activate && python3 scripts/build_chain_dynamics_phase1.py --date 2026-05-23
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"
REPORT_DIR = ROOT / "outputs" / "industry_chain"

# ---------------------------------------------------------------------------
# 品种映射配置
# ---------------------------------------------------------------------------
FUTURES_CONFIG: list[dict[str, str]] = [
    {
        "symbol": "LC0",
        "name": "碳酸锂主力",
        "chain_id": "nev",
        "chain_node": "上游-锂矿",
        "indicator_name": "锂盐均价（期货代理）",
        "indicator_unit": "元/吨",
        "exchange": "广期所",
    },
    {
        "symbol": "SI0",
        "name": "工业硅主力",
        "chain_id": "solar",
        "chain_node": "上游-硅料",
        "indicator_name": "工业硅均价（期货代理）",
        "indicator_unit": "元/吨",
        "exchange": "广期所",
    },
    {
        "symbol": "PS0",
        "name": "多晶硅主力",
        "chain_id": "solar",
        "chain_node": "上游-硅料",
        "indicator_name": "多晶硅均价（期货代理）",
        "indicator_unit": "元/吨",
        "exchange": "广期所",
    },
    {
        "symbol": "CU0",
        "name": "铜主力",
        "chain_id": "semiconductor",
        "chain_node": "配套-材料",
        "indicator_name": "铜价（成本代理）",
        "indicator_unit": "元/吨",
        "exchange": "上期所",
    },
    {
        "symbol": "CU0",
        "name": "铜主力",
        "chain_id": "ai_compute",
        "chain_node": "配套-材料",
        "indicator_name": "铜价（成本代理）",
        "indicator_unit": "元/吨",
        "exchange": "上期所",
    },
]


# ---------------------------------------------------------------------------
# 数据拉取
# ---------------------------------------------------------------------------

def fetch_futures_daily(symbol: str, start_date: str, end_date: str, max_retries: int = 3) -> list[dict[str, Any]]:
    """从 AKShare 拉取期货日线数据（含重试）。

    参数:
        symbol: 期货品种代码（如 "LC0" 碳酸锂主力合约）
        start_date: 起始日期 YYYY-MM-DD
        end_date: 截止日期 YYYY-MM-DD
        max_retries: 最大重试次数

    返回:
        [{"date": "2026-05-22", "close": 85000.0, "volume": 12345, ...}, ...]
    """
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("akshare is not installed.  Run: source .venv/bin/activate && pip install akshare") from exc

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            df = ak.futures_zh_daily_sina(symbol=symbol)
            if df is None or df.empty:
                return []
            break
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            else:
                raise last_exc
    else:
        return []

    # 标准化列名
    df.columns = [str(c).strip().lower() for c in df.columns]
    # 日期过滤
    df["_date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df[(df["_date"] >= start_date) & (df["_date"] <= end_date)]
    df = df.sort_values("_date").reset_index(drop=True)

    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        records.append({
            "date": str(row["_date"]),
            "open": _to_float(row.get("open")),
            "high": _to_float(row.get("high")),
            "low": _to_float(row.get("low")),
            "close": _to_float(row.get("close")),
            "volume": _to_float(row.get("volume")),
            "hold": _to_float(row.get("hold")),
            "settle": _to_float(row.get("settle")),
        })
    return records


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text in {"--", "-", "NA", "N/A", "nan", "None", "null", ""}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------

def compute_trend(daily_closes: list[float]) -> str:
    """基于近 5 日收盘价判定趋势。"""
    closes = [c for c in daily_closes if c is not None]
    if len(closes) < 5:
        return "flat"

    recent_5 = closes[-5:]
    delta_1 = recent_5[-1] - recent_5[-2]
    delta_2 = recent_5[-2] - recent_5[-3]
    delta_3 = recent_5[-3] - recent_5[-4]

    # 连续上行后首次下行
    if delta_3 > 0 and delta_2 > 0 and delta_1 < 0:
        return "turning_down"
    # 连续下行后首次上行
    if delta_3 < 0 and delta_2 < 0 and delta_1 > 0:
        return "turning_up"
    # 整体上行
    if recent_5[-1] > recent_5[0]:
        return "up"
    # 整体下行
    if recent_5[-1] < recent_5[0]:
        return "down"
    return "flat"


def compute_percentile(current: float, history: list[float]) -> float | None:
    """计算当前值在历史序列中的百分位（0-100）。"""
    valid = [h for h in history if h is not None]
    if not valid:
        return None
    below = sum(1 for v in valid if v < current)
    return round(below / len(valid) * 100, 1)


def compute_chain_dynamics_from_futures(
    futures_data: list[dict[str, Any]],
    chain_id: str,
    chain_node: str,
    indicator_name: str,
    indicator_unit: str,
    source_query: str,
    lookback_percentile: int = 252,
) -> list[dict[str, Any]]:
    """将期货数据转换为 chain_dynamics 表的记录列表。

    对 futures_data 中的每一条日线记录，计算：
        - latest_value: 当日收盘价
        - prev_value: 前一日收盘价
        - trend: 基于近 5 日方向判定
        - percentile_1y: 当前价格在近 lookback_percentile 个交易日的百分位
        - percentile_3y: 当前价格在近 756 个交易日的百分位（如有足够数据）
    """
    if not futures_data:
        return []

    records: list[dict[str, Any]] = []
    closes = [d["close"] for d in futures_data if d.get("close") is not None]

    for i, day in enumerate(futures_data):
        close = day.get("close")
        if close is None:
            continue

        prev_close = None
        if i > 0:
            for j in range(i - 1, -1, -1):
                if futures_data[j].get("close") is not None:
                    prev_close = futures_data[j]["close"]
                    break

        # 趋势：基于当天及之前共 5 个有效收盘价
        closes_up_to_i = [d["close"] for d in futures_data[: i + 1] if d.get("close") is not None]
        trend = compute_trend(closes_up_to_i)

        # 百分位
        hist_1y = closes[max(0, i - lookback_percentile) : i]
        percentile_1y = compute_percentile(close, hist_1y) if len(hist_1y) >= 60 else None

        hist_3y = closes[max(0, i - 756) : i]
        percentile_3y = compute_percentile(close, hist_3y) if len(hist_3y) >= 36 else None

        records.append({
            "chain_id": chain_id,
            "chain_node": chain_node,
            "indicator_name": indicator_name,
            "indicator_unit": indicator_unit,
            "latest_value": close,
            "prev_value": prev_close,
            "trend": trend,
            "percentile_1y": percentile_1y,
            "percentile_3y": percentile_3y,
            "data_frequency": "daily",
            "source_period": day["date"][:7] if day.get("date") else None,
            "source_vendor": "AKShare",
            "source_query": source_query,
            "confidence": 1.0,
            "as_of_date": day["date"],
            "collected_at": datetime.now(timezone.utc).isoformat(),
        })

    return records


# ---------------------------------------------------------------------------
# 数据库操作
# ---------------------------------------------------------------------------

CHAIN_DYNAMICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS chain_dynamics (
    chain_id         VARCHAR    NOT NULL,
    chain_node       VARCHAR    NOT NULL,
    indicator_name   VARCHAR    NOT NULL,
    indicator_unit   VARCHAR,
    latest_value     DOUBLE,
    prev_value       DOUBLE,
    trend            VARCHAR,
    percentile_1y    DOUBLE,
    percentile_3y    DOUBLE,
    data_frequency   VARCHAR,
    source_period    VARCHAR,
    source_vendor    VARCHAR    DEFAULT 'AKShare',
    source_query     VARCHAR,
    confidence       DOUBLE    DEFAULT 1.0,
    as_of_date       VARCHAR    NOT NULL,
    collected_at     VARCHAR    NOT NULL,
    PRIMARY KEY (chain_id, chain_node, indicator_name, as_of_date)
);
"""


def ensure_chain_dynamics_table(con: duckdb.DuckDBPyConnection) -> None:
    """确保 chain_dynamics 表存在且 Schema 正确。"""
    # 检查旧表是否存在（有 dynamic_id 列的是旧 Schema）
    try:
        cols = con.execute("PRAGMA table_info(chain_dynamics)").fetchall()
        col_names = {c[1] for c in cols}
        if "dynamic_id" in col_names:
            # 旧表，且有数据吗？
            cnt = con.execute("SELECT COUNT(*) FROM chain_dynamics").fetchone()[0]
            if cnt == 0:
                con.execute("DROP TABLE chain_dynamics")
            else:
                # 重命名旧表，保留数据供后续迁移
                con.execute("ALTER TABLE chain_dynamics RENAME TO chain_dynamics_legacy")
    except Exception:
        pass

    con.execute(CHAIN_DYNAMICS_SCHEMA)


def write_to_chain_dynamics(con: duckdb.DuckDBPyConnection, records: list[dict[str, Any]]) -> int:
    """写入 chain_dynamics 表。"""
    if not records:
        return 0

    ensure_chain_dynamics_table(con)

    inserted = 0
    for r in records:
        con.execute(
            """
            INSERT OR REPLACE INTO chain_dynamics
            (chain_id, chain_node, indicator_name, indicator_unit,
             latest_value, prev_value, trend, percentile_1y, percentile_3y,
             data_frequency, source_period, source_vendor, source_query,
             confidence, as_of_date, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r["chain_id"],
                r["chain_node"],
                r["indicator_name"],
                r["indicator_unit"],
                r["latest_value"],
                r["prev_value"],
                r["trend"],
                r["percentile_1y"],
                r["percentile_3y"],
                r["data_frequency"],
                r["source_period"],
                r["source_vendor"],
                r["source_query"],
                r["confidence"],
                r["as_of_date"],
                r["collected_at"],
            ),
        )
        inserted += 1
    return inserted


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------

def generate_report(
    results: list[dict[str, Any]],
    date_str: str,
    db_path: Path,
    lookback_days: int,
) -> str:
    """生成 Markdown 报告。"""
    lines: list[str] = [
        "# 产业链 Phase 1 数据填充报告",
        "",
        f"**生成时间**: {datetime.now(timezone.utc).isoformat()}",
        f"**基准日期**: {date_str}",
        f"**数据库**: {db_path}",
        f"**回看天数**: {lookback_days}",
        "",
        "## 执行摘要",
        "",
    ]

    total_rows = sum(r.get("inserted_rows", 0) for r in results)
    lines.append(f"- 共拉取 **{len(FUTURES_CONFIG)}** 个期货品种映射")
    lines.append(f"- 共写入 **{total_rows}** 条 chain_dynamics 记录")
    lines.append("")

    for r in results:
        cfg = r["config"]
        lines.append(f"### {cfg['name']} ({cfg['symbol']})")
        lines.append("")
        lines.append(f"- **产业链**: {cfg['chain_id']} / {cfg['chain_node']}")
        lines.append(f"- **指标**: {cfg['indicator_name']}")
        lines.append(f"- **交易所**: {cfg['exchange']}")
        lines.append(f"- **数据状态**: {r.get('status', 'unknown')}")
        if r.get("error"):
            lines.append(f"- **错误**: {r['error']}")
        else:
            lines.append(f"- **数据条数**: {r.get('data_rows', 0)}")
            lines.append(f"- **日期范围**: {r.get('date_range', 'N/A')}")
            if r.get("latest"):
                latest = r["latest"]
                lines.append(f"- **最新收盘价**: {latest.get('latest_value', 'N/A'):,.2f} {cfg['indicator_unit']}")
                lines.append(f"- **趋势**: `{latest.get('trend', 'N/A')}`")
                lines.append(f"- **1年分位**: {latest.get('percentile_1y', 'N/A')}")
                lines.append(f"- **3年分位**: {latest.get('percentile_3y', 'N/A')}")
        lines.append("")

    # 数据库统计
    lines.append("## 数据库统计")
    lines.append("")
    try:
        con = duckdb.connect(str(db_path))
        cnt = con.execute("SELECT COUNT(*) FROM chain_dynamics").fetchone()[0]
        lines.append(f"- chain_dynamics 总记录数: **{cnt}**")

        for chain_id in sorted({c["chain_id"] for c in FUTURES_CONFIG}):
            c = con.execute(
                "SELECT COUNT(*) FROM chain_dynamics WHERE chain_id = ?", (chain_id,)
            ).fetchone()[0]
            lines.append(f"  - {chain_id}: {c} 条")

        # 最新值摘要表
        lines.append("")
        lines.append("## 最新指标快照")
        lines.append("")
        lines.append("| 产业链 | 环节 | 指标 | 最新值 | 单位 | 趋势 | 1年分位 | 3年分位 | 日期 |")
        lines.append("|--------|------|------|--------|------|------|---------|---------|------|")

        latest_rows = con.execute(
            """
            SELECT chain_id, chain_node, indicator_name, latest_value, indicator_unit,
                   trend, percentile_1y, percentile_3y, as_of_date
            FROM chain_dynamics
            WHERE (chain_id, chain_node, indicator_name, as_of_date) IN (
                SELECT chain_id, chain_node, indicator_name, MAX(as_of_date)
                FROM chain_dynamics
                GROUP BY chain_id, chain_node, indicator_name
            )
            ORDER BY chain_id, indicator_name
            """
        ).fetchall()
        for row in latest_rows:
            chain_id, chain_node, indicator_name, latest_value, unit, trend, p1y, p3y, as_of = row
            val_str = f"{latest_value:,.2f}" if latest_value is not None else "N/A"
            lines.append(
                f"| {chain_id} | {chain_node} | {indicator_name} | "
                f"{val_str} | {unit or ''} | "
                f"{trend or ''} | {p1y if p1y is not None else 'N/A'} | "
                f"{p3y if p3y is not None else 'N/A'} | {as_of or ''} |"
            )
        con.close()
    except Exception as exc:
        lines.append(f"统计时出错: {exc}")

    lines.append("")
    lines.append("---")
    lines.append("*报告由 scripts/build_chain_dynamics_phase1.py 自动生成*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 1: Fill chain_dynamics with AKShare futures data.")
    parser.add_argument("--date", default="2026-05-23", help="基准日期 YYYY-MM-DD")
    parser.add_argument("--lookback-days", type=int, default=252, help="回看交易日数")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB 路径")
    parser.add_argument("--dry-run", action="store_true", help="仅检查不写入数据库")
    parser.add_argument("--report-only", action="store_true", help="仅生成报告，不拉取数据")
    args = parser.parse_args()

    date_str = args.date
    lookback = args.lookback_days
    db_path = Path(args.db)
    report_dir = REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)

    # 计算起始日期（简单处理：减去 lookback_days 个自然日，AKShare 会自行过滤）
    from datetime import timedelta
    start_dt = datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=lookback + 30)
    start_date = start_dt.strftime("%Y-%m-%d")

    results: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []

    if not args.report_only:
        for cfg in FUTURES_CONFIG:
            symbol = cfg["symbol"]
            result: dict[str, Any] = {"config": cfg, "status": "ok", "inserted_rows": 0}

            try:
                print(f"[Phase1] Fetching {symbol} ({cfg['name']}) for {cfg['chain_id']} ...")
                futures_data = fetch_futures_daily(symbol, start_date, date_str)
                result["data_rows"] = len(futures_data)

                if futures_data:
                    result["date_range"] = f"{futures_data[0]['date']} ~ {futures_data[-1]['date']}"
                    source_query = json.dumps({
                        "symbol": symbol,
                        "function": "futures_zh_daily_sina",
                        "exchange": cfg["exchange"],
                    }, ensure_ascii=False)

                    records = compute_chain_dynamics_from_futures(
                        futures_data=futures_data,
                        chain_id=cfg["chain_id"],
                        chain_node=cfg["chain_node"],
                        indicator_name=cfg["indicator_name"],
                        indicator_unit=cfg["indicator_unit"],
                        source_query=source_query,
                        lookback_percentile=lookback,
                    )
                    result["inserted_rows"] = len(records)
                    if records:
                        result["latest"] = records[-1]
                    all_records.extend(records)
                else:
                    result["status"] = "no_data"

            except Exception as exc:
                result["status"] = "error"
                result["error"] = str(exc)
                print(f"  ERROR: {exc}")

            results.append(result)
            time.sleep(0.5)  # 轻量防封

        # 写入数据库
        if not args.dry_run and all_records:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            con = duckdb.connect(str(db_path))
            try:
                inserted = write_to_chain_dynamics(con, all_records)
                print(f"[Phase1] Wrote {inserted} rows into {db_path}")
            finally:
                con.close()
        elif args.dry_run:
            print(f"[Phase1] Dry-run: would write {len(all_records)} rows")

    # 生成报告
    report_md = generate_report(results, date_str, db_path, lookback)
    report_path = report_dir / "chain_dynamics_phase1_report.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"[Phase1] Report written to {report_path}")

    # 输出 JSON 摘要
    summary = {
        "ok": True,
        "date": date_str,
        "lookback_days": lookback,
        "db_path": str(db_path),
        "report_path": str(report_path),
        "dry_run": args.dry_run,
        "total_records": len(all_records) if not args.report_only else None,
        "results": results,
    }
    summary_path = report_dir / f"chain_dynamics_phase1_summary_{date_str.replace('-', '')}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[Phase1] Summary written to {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
