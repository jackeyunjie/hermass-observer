#!/usr/bin/env python3
"""Weekly State transition analysis based on native W1 State.

Analyzes W1→W1 state transitions, forward returns, and three-period协同转换.
Uses real weekly bars (not D1-close approximations) for both state and returns.

Outputs:
    outputs/project/weekly_state_transition_analysis.json
    outputs/project/weekly_state_transition_analysis.md
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "outputs" / "state_cache"
WEEKLY_DB = ROOT / "outputs" / "weekly_bars" / "weekly_bars.duckdb"
OUT_DIR = ROOT / "outputs" / "project"

MIN_SAMPLE_SIZE = 30
FORWARD_WEEKS = [1, 2, 4, 8]


def state_hex(value: int | None) -> str:
    if value is None:
        return "NA"
    prefix = "-" if value < 0 else ""
    return prefix + format(abs(value), "X")


def decode_state(value: int | None) -> dict[str, Any]:
    if value is None:
        return {"hex": "NA", "direction": None, "base": None, "trend": None, "position": None, "volatility": None}
    magnitude = abs(value)
    base = 8 if magnitude >= 8 else 0
    trend = 1 if magnitude & 4 else 0
    position = 1 if magnitude & 2 else 0
    volatility = 1 if magnitude & 1 else 0
    direction = "空向" if value < 0 else "多向"
    return {
        "hex": state_hex(value),
        "direction": direction,
        "base": base,
        "trend": trend,
        "position": position,
        "volatility": volatility,
        "label": f"{direction}/{'扩张' if base else '收缩'}/{'有趋势' if trend else '无趋势'}/{'突破' if position else '未突破'}/{'波动活跃' if volatility else '波动稳定'}",
    }


def compute_metrics(returns: list[float]) -> dict[str, Any]:
    n = len(returns)
    if n == 0:
        return {"n": 0, "mean": None, "win_rate": None, "payoff_ratio": None, "std": None, "t_stat": None, "sharpe": None}
    mean = statistics.fmean(returns)
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    win_rate = len(wins) / n
    avg_win = statistics.fmean(wins) if wins else 0.0
    avg_loss = statistics.fmean([abs(r) for r in losses]) if losses else 0.0
    payoff_ratio = avg_win / avg_loss if avg_loss > 0 else None
    std = statistics.stdev(returns) if n >= 2 else 0.0
    t_stat = mean / (std / math.sqrt(n)) if std > 0 else 0.0
    sharpe = mean / std if std > 0 else 0.0
    return {
        "n": n,
        "mean": round(mean, 6),
        "win_rate": round(win_rate, 4),
        "payoff_ratio": round(payoff_ratio, 4) if payoff_ratio is not None else None,
        "std": round(std, 6),
        "t_stat": round(t_stat, 4),
        "sharpe": round(sharpe, 4),
    }


def load_weekly_states(cache_dir: Path) -> list[dict[str, Any]]:
    """Load all weekly_state_*.json into flat records."""
    records = []
    for path in sorted(cache_dir.glob("weekly_state_*.json")):
        if "latest" in path.name:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        iso_week = data.get("iso_week") or data.get("week")
        week_start = data.get("week_start_date")
        week_end = data.get("week_end_date")
        stocks = data.get("data") or data.get("stocks", [])
        for s in stocks:
            records.append({
                "iso_week": iso_week,
                "week_start_date": s.get("week_start_date") or week_start,
                "week_end_date": s.get("week_end_date") or week_end,
                "stock_code": s["stock_code"],
                "w1_state_score": s.get("w1_state") if "w1_state" in s else s.get("w1_state_score"),
                "w1_state_hex": s.get("w1_state_hex"),
                "w1_base": s.get("w1_base"),
                "w1_trend_bit": s.get("w1_trend") if isinstance(s.get("w1_trend"), int) else s.get("w1_trend_bit"),
                "w1_position_bit": s.get("w1_position") if isinstance(s.get("w1_position"), int) else s.get("w1_position_bit"),
                "w1_volatility_bit": s.get("w1_volatility") if isinstance(s.get("w1_volatility"), int) else s.get("w1_volatility_bit"),
                "w1_close": s.get("w1_close"),
            })
    return records


def build_w1_transition_matrix(records: list[dict[str, Any]], weekly_db: Path) -> dict[str, Any]:
    """Build W1→W1 transition matrix with forward weekly returns."""
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{str(weekly_db).replace(chr(39), chr(39)+chr(39))}' AS wdb (READ_ONLY)")

    # Write temp JSON and load into DuckDB
    import tempfile
    temp_json = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(records, temp_json, ensure_ascii=False)
    temp_json.close()
    con.execute(f"""
        CREATE TABLE weekly_native AS
        SELECT * FROM (
            SELECT
                iso_week,
                week_start_date::DATE AS week_start_date,
                week_end_date::DATE AS week_end_date,
                stock_code,
                w1_state_score,
                w1_state_hex,
                w1_base,
                w1_trend_bit,
                w1_position_bit,
                w1_volatility_bit,
                w1_close
            FROM read_json_auto('{temp_json.name.replace(chr(39), chr(39)+chr(39))}')
        )
    """)

    # Build transitions with forward returns
    leads = ", ".join([
        f"LEAD(w1_close, {fw}) OVER (PARTITION BY stock_code ORDER BY week_start_date) AS close_{fw}w"
        for fw in FORWARD_WEEKS
    ])

    sql = f"""
        WITH transitions AS (
            SELECT
                stock_code,
                week_start_date,
                week_end_date,
                w1_state_score,
                w1_state_hex,
                w1_base,
                w1_trend_bit,
                w1_position_bit,
                w1_volatility_bit,
                w1_close,
                LAG(w1_state_score) OVER (PARTITION BY stock_code ORDER BY week_start_date) AS prev_w1_state,
                LAG(w1_state_hex) OVER (PARTITION BY stock_code ORDER BY week_start_date) AS prev_w1_hex,
                {leads}
            FROM weekly_native
        ),
        weekly_market AS (
            SELECT
                week_start_date,
                {", ".join([f"AVG(CASE WHEN close_{fw}w IS NOT NULL THEN close_{fw}w / w1_close - 1 END) AS mkt_{fw}w" for fw in FORWARD_WEEKS])}
            FROM transitions
            WHERE close_1w IS NOT NULL
            GROUP BY week_start_date
        )
        SELECT
            t.prev_w1_state,
            t.prev_w1_hex,
            t.w1_state_score,
            t.w1_state_hex,
            {", ".join([f"t.close_{fw}w / t.w1_close - 1 - m.mkt_{fw}w AS excess_{fw}w" for fw in FORWARD_WEEKS])}
        FROM transitions t
        JOIN weekly_market m ON t.week_start_date = m.week_start_date
        WHERE t.prev_w1_state IS NOT NULL
          AND t.close_1w IS NOT NULL
        ORDER BY t.stock_code, t.week_start_date
    """

    rows = con.execute(sql).fetchall()
    con.close()

    by_transition: dict[tuple[int, int], dict[str, list[float]]] = defaultdict(
        lambda: {f"excess_{fw}w": [] for fw in FORWARD_WEEKS}
    )

    for row in rows:
        prev_state, prev_hex, curr_state, curr_hex = row[0], row[1], row[2], row[3]
        key = (int(prev_state), int(curr_state))
        for i, fw in enumerate(FORWARD_WEEKS):
            val = row[4 + i]
            if val is not None:
                by_transition[key][f"excess_{fw}w"].append(float(val))

    transition_stats: list[dict[str, Any]] = []
    for (prev, curr), data in by_transition.items():
        stats = {f"excess_{fw}w": compute_metrics(data[f"excess_{fw}w"]) for fw in FORWARD_WEEKS}
        transition_stats.append({
            "prev_state": prev,
            "curr_state": curr,
            "prev_hex": state_hex(prev),
            "curr_hex": state_hex(curr),
            "prev_decoded": decode_state(prev),
            "curr_decoded": decode_state(curr),
            "sample_size": stats["excess_1w"]["n"],
            "sample_adequate": stats["excess_1w"]["n"] >= MIN_SAMPLE_SIZE,
            **stats,
        })

    transition_stats.sort(key=lambda x: abs(x["excess_4w"]["mean"] or 0.0), reverse=True)

    return {
        "total_transitions_observed": len(by_transition),
        "total_transition_events": len(rows),
        "min_sample_threshold": MIN_SAMPLE_SIZE,
        "transitions": transition_stats,
    }


def build_three_period_transitions(
    records: list[dict[str, Any]],
    foundation_db: Path | None,
    weekly_db: Path,
) -> dict[str, Any]:
    """Build three-period协同转换 using native W1 + D1/MN1 from foundation."""
    if foundation_db is None or not foundation_db.exists():
        return {"error": "Foundation DB not available for three-period analysis"}

    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{str(weekly_db).replace(chr(39), chr(39)+chr(39))}' AS wdb (READ_ONLY)")
    con.execute(f"ATTACH '{str(foundation_db).replace(chr(39), chr(39)+chr(39))}' AS fdb (READ_ONLY)")

    # Write temp JSON and load into DuckDB
    import tempfile
    temp_json = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(records, temp_json, ensure_ascii=False)
    temp_json.close()
    con.execute(f"""
        CREATE TABLE weekly_native AS
        SELECT * FROM (
            SELECT
                iso_week,
                week_start_date::DATE AS week_start_date,
                week_end_date::DATE AS week_end_date,
                stock_code,
                w1_state_score,
                w1_state_hex,
                w1_base,
                w1_trend_bit,
                w1_position_bit,
                w1_volatility_bit,
                w1_close
            FROM read_json_auto('{temp_json.name.replace(chr(39), chr(39)+chr(39))}')
        )
    """)

    scenarios = {
        "w1_enter_ef": "ABS(t.prev_w1) < 14 AND ABS(t.w1_state_score) >= 14",
        "w1_exit_ef": "ABS(t.prev_w1) >= 14 AND ABS(t.w1_state_score) < 14",
        "w1_enter_breakout": "ABS(t.prev_w1) NOT IN (10, 11, -10, -11) AND ABS(t.w1_state_score) IN (10, 11, -10, -11)",
        "w1_base_0_to_8": "t.prev_w1_base = 0 AND t.w1_base = 8",
        "w1_base_8_to_0": "t.prev_w1_base = 8 AND t.w1_base = 0",
        "w1_vol_0_to_1": "t.prev_w1_vol = 0 AND t.w1_volatility_bit = 1",
        "w1_vol_1_to_0": "t.prev_w1_vol = 1 AND t.w1_volatility_bit = 0",
        "all_three_enter_ef": """
            (ABS(t.prev_mn1) < 14 AND ABS(t.mn1_state_score) >= 14) AND
            (ABS(t.prev_w1) < 14 AND ABS(t.w1_state_score) >= 14) AND
            (ABS(t.prev_d1) < 14 AND ABS(t.d1_state_score) >= 14)
        """,
        "all_three_exit_ef": """
            (ABS(t.prev_mn1) >= 14 AND ABS(t.mn1_state_score) < 14) AND
            (ABS(t.prev_w1) >= 14 AND ABS(t.w1_state_score) < 14) AND
            (ABS(t.prev_d1) >= 14 AND ABS(t.d1_state_score) < 14)
        """,
        "w1_d1_sync_enter_ef": """
            (ABS(t.prev_w1) < 14 AND ABS(t.w1_state_score) >= 14) AND
            (ABS(t.prev_d1) < 14 AND ABS(t.d1_state_score) >= 14)
        """,
        "w1_d1_sync_exit_ef": """
            (ABS(t.prev_w1) >= 14 AND ABS(t.w1_state_score) < 14) AND
            (ABS(t.prev_d1) >= 14 AND ABS(t.d1_state_score) < 14)
        """,
        "w1_mn1_sync_enter_ef": """
            (ABS(t.prev_w1) < 14 AND ABS(t.w1_state_score) >= 14) AND
            (ABS(t.prev_mn1) < 14 AND ABS(t.mn1_state_score) >= 14)
        """,
        "w1_mn1_sync_exit_ef": """
            (ABS(t.prev_w1) >= 14 AND ABS(t.w1_state_score) < 14) AND
            (ABS(t.prev_mn1) >= 14 AND ABS(t.mn1_state_score) < 14)
        """,
    }

    scenario_results: dict[str, Any] = {}

    for scenario_name, condition in scenarios.items():
        sql = f"""
            WITH weekly_aligned AS (
                SELECT
                    n.stock_code,
                    n.week_start_date,
                    n.week_end_date,
                    n.w1_state_score,
                    n.w1_base,
                    n.w1_volatility_bit,
                    n.w1_close,
                    d.mn1_state_score,
                    d.d1_state_score,
                    d.d1_close
                FROM weekly_native n
                LEFT JOIN fdb.d1_perspective_state d
                    ON d.stock_code = n.stock_code AND d.state_date = n.week_end_date
            ),
            transitions AS (
                SELECT
                    *,
                    LAG(w1_state_score) OVER (PARTITION BY stock_code ORDER BY week_start_date) AS prev_w1,
                    LAG(w1_base) OVER (PARTITION BY stock_code ORDER BY week_start_date) AS prev_w1_base,
                    LAG(w1_volatility_bit) OVER (PARTITION BY stock_code ORDER BY week_start_date) AS prev_w1_vol,
                    LAG(mn1_state_score) OVER (PARTITION BY stock_code ORDER BY week_start_date) AS prev_mn1,
                    LAG(d1_state_score) OVER (PARTITION BY stock_code ORDER BY week_start_date) AS prev_d1,
                    LEAD(w1_close, 1) OVER (PARTITION BY stock_code ORDER BY week_start_date) AS close_1w,
                    LEAD(w1_close, 2) OVER (PARTITION BY stock_code ORDER BY week_start_date) AS close_2w,
                    LEAD(w1_close, 4) OVER (PARTITION BY stock_code ORDER BY week_start_date) AS close_4w,
                    LEAD(w1_close, 8) OVER (PARTITION BY stock_code ORDER BY week_start_date) AS close_8w
                FROM weekly_aligned
            ),
            weekly_market AS (
                SELECT
                    week_start_date,
                    AVG(CASE WHEN close_1w IS NOT NULL THEN close_1w / w1_close - 1 END) AS mkt_1w,
                    AVG(CASE WHEN close_2w IS NOT NULL THEN close_2w / w1_close - 1 END) AS mkt_2w,
                    AVG(CASE WHEN close_4w IS NOT NULL THEN close_4w / w1_close - 1 END) AS mkt_4w,
                    AVG(CASE WHEN close_8w IS NOT NULL THEN close_8w / w1_close - 1 END) AS mkt_8w
                FROM transitions
                WHERE close_1w IS NOT NULL
                GROUP BY week_start_date
            )
            SELECT
                t.close_1w / t.w1_close - 1 - m.mkt_1w AS excess_1w,
                t.close_2w / t.w1_close - 1 - m.mkt_2w AS excess_2w,
                t.close_4w / t.w1_close - 1 - m.mkt_4w AS excess_4w,
                t.close_8w / t.w1_close - 1 - m.mkt_8w AS excess_8w
            FROM transitions t
            JOIN weekly_market m ON t.week_start_date = m.week_start_date
            WHERE t.close_1w IS NOT NULL
              AND t.w1_close > 0
              AND ({condition})
        """

        rows = con.execute(sql).fetchall()
        returns = {f"excess_{fw}w": [float(r[i]) for r in rows if r[i] is not None] for i, fw in enumerate(FORWARD_WEEKS)}

        scenario_results[scenario_name] = {
            "event_count": len(rows),
            **{f"excess_{fw}w": compute_metrics(returns[f"excess_{fw}w"]) for fw in FORWARD_WEEKS},
        }

    con.close()
    return scenario_results


def build_hotspots(transition_matrix: dict[str, Any]) -> dict[str, Any]:
    """Identify most frequent and highest-return transitions."""
    transitions = transition_matrix["transitions"]

    # Most frequent
    most_frequent = sorted(transitions, key=lambda x: x["sample_size"], reverse=True)[:20]

    # Highest 4-week excess return (with adequate sample)
    adequate = [t for t in transitions if t["sample_adequate"]]
    highest_return = sorted(adequate, key=lambda x: x["excess_4w"]["mean"] or -999, reverse=True)[:20]
    lowest_return = sorted(adequate, key=lambda x: x["excess_4w"]["mean"] or 999)[:20]

    # Best risk-adjusted (Sharpe)
    best_sharpe = sorted(adequate, key=lambda x: x["excess_4w"]["sharpe"] or -999, reverse=True)[:20]

    # By bit component
    base_expansion = [t for t in adequate if t["prev_decoded"]["base"] == 0 and t["curr_decoded"]["base"] == 8]
    base_contraction = [t for t in adequate if t["prev_decoded"]["base"] == 8 and t["curr_decoded"]["base"] == 0]
    trend_on = [t for t in adequate if t["prev_decoded"]["trend"] == 0 and t["curr_decoded"]["trend"] == 1]
    trend_off = [t for t in adequate if t["prev_decoded"]["trend"] == 1 and t["curr_decoded"]["trend"] == 0]
    pos_breakout = [t for t in adequate if t["prev_decoded"]["position"] == 0 and t["curr_decoded"]["position"] == 1]
    pos_retrace = [t for t in adequate if t["prev_decoded"]["position"] == 1 and t["curr_decoded"]["position"] == 0]
    vol_on = [t for t in adequate if t["prev_decoded"]["volatility"] == 0 and t["curr_decoded"]["volatility"] == 1]
    vol_off = [t for t in adequate if t["prev_decoded"]["volatility"] == 1 and t["curr_decoded"]["volatility"] == 0]

    def avg_4w(tlist: list[dict]) -> float:
        if not tlist:
            return 0.0
        return statistics.fmean([t["excess_4w"]["mean"] or 0.0 for t in tlist])

    return {
        "most_frequent": most_frequent,
        "highest_4w_return": highest_return,
        "lowest_4w_return": lowest_return,
        "best_sharpe": best_sharpe,
        "component_summary": {
            "base_expansion": {"count": len(base_expansion), "avg_4w_excess": round(avg_4w(base_expansion), 6)},
            "base_contraction": {"count": len(base_contraction), "avg_4w_excess": round(avg_4w(base_contraction), 6)},
            "trend_on": {"count": len(trend_on), "avg_4w_excess": round(avg_4w(trend_on), 6)},
            "trend_off": {"count": len(trend_off), "avg_4w_excess": round(avg_4w(trend_off), 6)},
            "position_breakout": {"count": len(pos_breakout), "avg_4w_excess": round(avg_4w(pos_breakout), 6)},
            "position_retrace": {"count": len(pos_retrace), "avg_4w_excess": round(avg_4w(pos_retrace), 6)},
            "volatility_on": {"count": len(vol_on), "avg_4w_excess": round(avg_4w(vol_on), 6)},
            "volatility_off": {"count": len(vol_off), "avg_4w_excess": round(avg_4w(vol_off), 6)},
        },
    }


def generate_report(
    transition_matrix: dict[str, Any],
    hotspots: dict[str, Any],
    three_period: dict[str, Any],
    out_path: Path,
) -> None:
    md = f"""# 周线 State 转换分析报告

> 基于原生 W1 State（真实周线收盘价计算）  
> 生成时间：{datetime.now(timezone.utc).isoformat()}  
> 样本范围：{len([t for t in transition_matrix['transitions'] if t['sample_adequate']])} 种转换（样本≥{MIN_SAMPLE_SIZE}）

---

## 1. 总体概览

| 指标 | 数值 |
|------|------|
| 观察到的转换类型 | {transition_matrix['total_transitions_observed']:,} |
| 总转换事件 | {transition_matrix['total_transition_events']:,} |
| 样本充足（≥{MIN_SAMPLE_SIZE}）的转换 | {len([t for t in transition_matrix['transitions'] if t['sample_adequate']]):,} |

---

## 2. 转换热点

### 2.1 最频繁的转换（Top 10）

| 排名 | 转换 | 样本量 | 1周超额 | 4周超额 | 胜率 |
|------|------|--------|---------|---------|------|
"""
    for i, t in enumerate(hotspots["most_frequent"][:10], 1):
        md += f"| {i} | {t['prev_hex']} → {t['curr_hex']} | {t['sample_size']:,} | {fmt_pct(t['excess_1w']['mean'])} | {fmt_pct(t['excess_4w']['mean'])} | {fmt_pct(t['excess_4w']['win_rate'])} |\n"

    md += """
### 2.2 后续收益最高的转换（4周超额，Top 10）

| 排名 | 转换 | 样本量 | 4周超额 | 胜率 | t-stat | Sharpe |
|------|------|--------|---------|------|--------|--------|
"""
    for i, t in enumerate(hotspots["highest_4w_return"][:10], 1):
        md += f"| {i} | {t['prev_hex']} → {t['curr_hex']} | {t['sample_size']:,} | {fmt_pct(t['excess_4w']['mean'])} | {fmt_pct(t['excess_4w']['win_rate'])} | {t['excess_4w']['t_stat'] or '-'} | {t['excess_4w']['sharpe'] or '-'} |\n"

    md += """
### 2.3 后续收益最低的转换（4周超额，Bottom 10）

| 排名 | 转换 | 样本量 | 4周超额 | 胜率 | t-stat | Sharpe |
|------|------|--------|---------|------|--------|--------|
"""
    for i, t in enumerate(hotspots["lowest_4w_return"][:10], 1):
        md += f"| {i} | {t['prev_hex']} → {t['curr_hex']} | {t['sample_size']:,} | {fmt_pct(t['excess_4w']['mean'])} | {fmt_pct(t['excess_4w']['win_rate'])} | {t['excess_4w']['t_stat'] or '-'} | {t['excess_4w']['sharpe'] or '-'} |\n"

    md += """
### 2.4 最佳风险调整收益（Sharpe，Top 10）

| 排名 | 转换 | 样本量 | 4周超额 | Sharpe | t-stat |
|------|------|--------|---------|--------|--------|
"""
    for i, t in enumerate(hotspots["best_sharpe"][:10], 1):
        md += f"| {i} | {t['prev_hex']} → {t['curr_hex']} | {t['sample_size']:,} | {fmt_pct(t['excess_4w']['mean'])} | {t['excess_4w']['sharpe'] or '-'} | {t['excess_4w']['t_stat'] or '-'} |\n"

    md += """
---

## 3. 分组件转换分析

### 3.1 各组件切换的平均4周超额收益

| 组件切换 | 转换次数 | 平均4周超额 | 解读 |
|----------|----------|-------------|------|
"""
    comp = hotspots["component_summary"]
    md += f"| Base: 收缩→扩张 | {comp['base_expansion']['count']:,} | {fmt_pct(comp['base_expansion']['avg_4w_excess'])} | 从收缩进入扩张的平均表现 |\n"
    md += f"| Base: 扩张→收缩 | {comp['base_contraction']['count']:,} | {fmt_pct(comp['base_contraction']['avg_4w_excess'])} | 从扩张退回收缩的平均表现 |\n"
    md += f"| Trend: 无→有 | {comp['trend_on']['count']:,} | {fmt_pct(comp['trend_on']['avg_4w_excess'])} | 趋势从无到有的平均表现 |\n"
    md += f"| Trend: 有→无 | {comp['trend_off']['count']:,} | {fmt_pct(comp['trend_off']['avg_4w_excess'])} | 趋势消失的平均表现 |\n"
    md += f"| Position: 未突破→突破 | {comp['position_breakout']['count']:,} | {fmt_pct(comp['position_breakout']['avg_4w_excess'])} | 突破SR的平均表现 |\n"
    md += f"| Position: 突破→未突破 | {comp['position_retrace']['count']:,} | {fmt_pct(comp['position_retrace']['avg_4w_excess'])} | 退回SR区间的平均表现 |\n"
    md += f"| Volatility: 稳定→活跃 | {comp['volatility_on']['count']:,} | {fmt_pct(comp['volatility_on']['avg_4w_excess'])} | 波动率上升的平均表现 |\n"
    md += f"| Volatility: 活跃→稳定 | {comp['volatility_off']['count']:,} | {fmt_pct(comp['volatility_off']['avg_4w_excess'])} | 波动率下降的平均表现 |\n"

    md += """
---

## 4. 三周期协同转换

> 注：W1 使用原生周线 State，D1/MN1 使用 Foundation DB 中 D1 视角的 State（按周最后交易日对齐）

"""

    for scenario_name, result in sorted(three_period.items()):
        if "error" in result:
            md += f"\n**{scenario_name}**: {result['error']}\n"
            continue
        md += f"""\n### {scenario_name}

| 窗口 | 事件数 | 平均超额 | 胜率 | t-stat | Sharpe |
|------|--------|----------|------|--------|--------|
"""
        for fw in FORWARD_WEEKS:
            s = result[f"excess_{fw}w"]
            md += f"| {fw}周 | {s['n']:,} | {fmt_pct(s['mean'])} | {fmt_pct(s['win_rate'])} | {s['t_stat'] or '-'} | {s['sharpe'] or '-'} |\n"

    md += """
---

## 5. 关键发现

"""
    # Auto-generate insights
    insights = []

    # Best single transition
    best = hotspots["highest_4w_return"][0] if hotspots["highest_4w_return"] else None
    if best and best["excess_4w"]["mean"] and best["excess_4w"]["mean"] > 0.05:
        insights.append(f"1. **最强转换**：`{best['prev_hex']} → {best['curr_hex']}`，4周平均超额收益 {best['excess_4w']['mean']*100:.2f}%，胜率 {best['excess_4w']['win_rate']*100:.1f}%，样本 {best['sample_size']:,} 个。")

    worst = hotspots["lowest_4w_return"][0] if hotspots["lowest_4w_return"] else None
    if worst and worst["excess_4w"]["mean"] and worst["excess_4w"]["mean"] < -0.05:
        insights.append(f"2. **最弱转换**：`{worst['prev_hex']} → {worst['curr_hex']}`，4周平均超额收益 {worst['excess_4w']['mean']*100:.2f}%，胜率 {worst['excess_4w']['win_rate']*100:.1f}%，样本 {worst['sample_size']:,} 个。")

    # Component insights
    be = comp["base_expansion"]["avg_4w_excess"]
    bc = comp["base_contraction"]["avg_4w_excess"]
    if be > bc:
        insights.append(f"3. **Base切换**：收缩→扩张的平均4周超额（{be*100:.2f}%）优于扩张→收缩（{bc*100:.2f}%），说明收缩后释放通常带来正向收益。")
    else:
        insights.append(f"3. **Base切换**：扩张→收缩的平均4周超额（{bc*100:.2f}%）优于收缩→扩张（{be*100:.2f}%），说明趋势延续更重要。")

    po = comp["position_breakout"]["avg_4w_excess"]
    pr = comp["position_retrace"]["avg_4w_excess"]
    if po > pr:
        insights.append(f"4. **Position切换**：突破SR的平均4周超额（{po*100:.2f}%）优于退回区间（{pr*100:.2f}%），确认突破有正向动量。")
    else:
        insights.append(f"4. **Position切换**：退回SR区间的平均4周超额（{pr*100:.2f}%）优于突破（{po*100:.2f}%），说明假突破风险较高。")

    # Three period insights
    all_enter = three_period.get("all_three_enter_ef")
    if all_enter and all_enter.get("excess_4w", {}).get("mean"):
        v = all_enter["excess_4w"]["mean"]
        insights.append(f"5. **三周期EF共振**：当 MN1/W1/D1 同时进入 E/F 时，4周平均超额收益为 {v*100:.2f}%（事件数 {all_enter['excess_4w']['n']:,}）。")

    all_exit = three_period.get("all_three_exit_ef")
    if all_exit and all_exit.get("excess_4w", {}).get("mean"):
        v = all_exit["excess_4w"]["mean"]
        insights.append(f"6. **三周期EF退出**：当 MN1/W1/D1 同时退出 E/F 时，4周平均超额收益为 {v*100:.2f}%（事件数 {all_exit['excess_4w']['n']:,}）。")

    for insight in insights:
        md += insight + "\n\n"

    md += """---

## 附录：方法论

- **State来源**：原生 W1 State（基于真实周线K线计算，非D1收盘价近似）
- **收益计算**：周线收盘价 → 未来N周收盘价，扣除同期等权市场收益
- **样本阈值**：仅报告样本量 ≥ 30 的转换统计
- **三周期对齐**：D1/MN1 State取每周最后一个交易日的值，与原生W1 State周对齐

> ⚠️ 免责声明：本报告仅为历史统计分析，不构成交易建议或投资推荐。
"""

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")


def fmt_pct(val: float | None) -> str:
    if val is None:
        return "-"
    return f"{val*100:+.2f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly State transition analysis")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--weekly-db", type=Path, default=WEEKLY_DB)
    parser.add_argument("--foundation-db", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    # Try to find foundation DB automatically
    foundation_db = args.foundation_db
    if foundation_db is None:
        candidates = sorted(ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"))
        if candidates:
            foundation_db = candidates[-1]
            print(f"Auto-selected foundation DB: {foundation_db}")

    print("Loading weekly states...")
    records = load_weekly_states(args.cache_dir)
    print(f"Loaded {len(records):,} records")

    print("Building W1 transition matrix...")
    transition_matrix = build_w1_transition_matrix(records, args.weekly_db)
    print(f"Observed {transition_matrix['total_transitions_observed']} transition types, {transition_matrix['total_transition_events']:,} events")

    print("Analyzing hotspots...")
    hotspots = build_hotspots(transition_matrix)

    print("Building three-period transitions...")
    three_period = build_three_period_transitions(records, foundation_db, args.weekly_db)

    # Write JSON
    json_path = args.out_dir / "weekly_state_transition_analysis.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "transition_matrix": transition_matrix,
        "hotspots": hotspots,
        "three_period": three_period,
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"JSON written to: {json_path}")

    # Write MD
    md_path = args.out_dir / "weekly_state_transition_analysis.md"
    generate_report(transition_matrix, hotspots, three_period, md_path)
    print(f"Report written to: {md_path}")


if __name__ == "__main__":
    main()
