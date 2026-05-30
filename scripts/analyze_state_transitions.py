#!/usr/bin/env python3
"""State transition analysis: scan all State transition patterns from foundation DB.

Core principles:
    - Data-first: let the database tell us which transitions matter
    - Open-minded: scan all 16x16=256 D1 State transitions + three-period协同跃迁
    - Gradual accumulation: output sample size, excess return, win rate for each transition
    - No binary good/bad judgment; only statistical facts

Outputs:
    outputs/project/state_transition_analysis.json — machine-readable full statistics
    outputs/project/state_transition_analysis.md — human-readable transition matrix + top paths
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "outputs" / "project"

MIN_SAMPLE_SIZE = 30
WINDOWS = [5, 10, 20]


def state_hex(value: int | None) -> str:
    if value is None:
        return "NA"
    if -15 <= value <= 15:
        prefix = "-" if value < 0 else ""
        return prefix + format(abs(value), "X")
    return str(value)


def decode_state(value: int | None) -> dict[str, Any]:
    if value is None:
        return {
            "state": None,
            "hex": "NA",
            "direction": None,
            "base": None,
            "trend": None,
            "position": None,
            "volatility": None,
            "label": "NA",
        }
    magnitude = abs(value)
    base = 8 if magnitude >= 8 else 0
    trend = 4 if magnitude & 4 else 0
    position = 2 if magnitude & 2 else 0
    volatility = 1 if magnitude & 1 else 0
    direction = "空向" if value < 0 else "多向"
    return {
        "state": value,
        "hex": state_hex(value),
        "direction": direction,
        "base": base,
        "trend": trend,
        "position": position,
        "volatility": volatility,
        "label": (
            direction
            + "/"
            + ("扩张" if base else "收缩")
            + "/"
            + ("有趋势" if trend else "无趋势")
            + "/"
            + ("突破" if position else "未突破")
            + "/"
            + ("波动活跃" if volatility else "波动稳定")
        ),
    }


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_metrics(returns: list[float]) -> dict[str, Any]:
    """Compute mean, win_rate, payoff_ratio, std, t_stat for a list of returns."""
    n = len(returns)
    if n == 0:
        return {"n": 0, "mean": None, "win_rate": None, "payoff_ratio": None, "std": None, "t_stat": None}
    mean = statistics.fmean(returns)
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    win_rate = len(wins) / n
    avg_win = statistics.fmean(wins) if wins else 0.0
    avg_loss = statistics.fmean([abs(r) for r in losses]) if losses else 0.0
    payoff_ratio = avg_win / avg_loss if avg_loss > 0 else None
    std = statistics.stdev(returns) if n >= 2 else 0.0
    t_stat = mean / (std / math.sqrt(n)) if std > 0 else 0.0
    return {
        "n": n,
        "mean": round(mean, 6),
        "win_rate": round(win_rate, 4),
        "payoff_ratio": round(payoff_ratio, 4) if payoff_ratio is not None else None,
        "std": round(std, 6),
        "t_stat": round(t_stat, 4),
    }


def build_d1_transition_matrix(db_path: Path) -> dict[str, Any]:
    """Build 256 D1 State transition matrix with forward returns."""
    con = duckdb.connect(str(db_path), read_only=True)

    # Build transition data with forward returns and daily market equal-weight returns
    rows = con.execute(
        """
        WITH transitions AS (
            SELECT 
                stock_code,
                state_date,
                d1_state_score,
                LAG(d1_state_score) OVER (PARTITION BY stock_code ORDER BY state_date) as prev_d1_state,
                d1_close,
                LEAD(d1_close, 5) OVER (PARTITION BY stock_code ORDER BY state_date) as close_5d,
                LEAD(d1_close, 10) OVER (PARTITION BY stock_code ORDER BY state_date) as close_10d,
                LEAD(d1_close, 20) OVER (PARTITION BY stock_code ORDER BY state_date) as close_20d
            FROM d1_perspective_state
        ),
        daily_market AS (
            SELECT 
                state_date,
                AVG(CASE WHEN close_5d IS NOT NULL THEN close_5d/d1_close - 1 END) as mkt_5d,
                AVG(CASE WHEN close_10d IS NOT NULL THEN close_10d/d1_close - 1 END) as mkt_10d,
                AVG(CASE WHEN close_20d IS NOT NULL THEN close_20d/d1_close - 1 END) as mkt_20d
            FROM transitions
            WHERE close_5d IS NOT NULL
            GROUP BY state_date
        )
        SELECT 
            t.prev_d1_state,
            t.d1_state_score,
            t.close_5d/t.d1_close - 1 - m.mkt_5d as excess_5d,
            t.close_10d/t.d1_close - 1 - m.mkt_10d as excess_10d,
            t.close_20d/t.d1_close - 1 - m.mkt_20d as excess_20d
        FROM transitions t
        JOIN daily_market m ON t.state_date = m.state_date
        WHERE t.prev_d1_state IS NOT NULL
          AND t.close_5d IS NOT NULL
          AND t.close_10d IS NOT NULL
          AND t.close_20d IS NOT NULL
        """
    ).fetchall()
    con.close()

    # Group by transition
    by_transition: dict[tuple[int, int], dict[str, list[float]]] = defaultdict(
        lambda: {"excess_5d": [], "excess_10d": [], "excess_20d": []}
    )
    for prev_state, curr_state, e5, e10, e20 in rows:
        key = (int(prev_state), int(curr_state))
        by_transition[key]["excess_5d"].append(float(e5))
        by_transition[key]["excess_10d"].append(float(e10))
        by_transition[key]["excess_20d"].append(float(e20))

    # Compute metrics for each transition
    transition_stats: list[dict[str, Any]] = []
    for (prev, curr), data in by_transition.items():
        stats_5d = compute_metrics(data["excess_5d"])
        stats_10d = compute_metrics(data["excess_10d"])
        stats_20d = compute_metrics(data["excess_20d"])
        transition_stats.append({
            "prev_state": prev,
            "curr_state": curr,
            "prev_hex": state_hex(prev),
            "curr_hex": state_hex(curr),
            "prev_decoded": decode_state(prev),
            "curr_decoded": decode_state(curr),
            "sample_size": stats_5d["n"],
            "sample_adequate": stats_5d["n"] >= MIN_SAMPLE_SIZE,
            "excess_5d": stats_5d,
            "excess_10d": stats_10d,
            "excess_20d": stats_20d,
        })

    # Sort by absolute 20d excess (most interesting first)
    transition_stats.sort(
        key=lambda x: abs(x["excess_20d"]["mean"] or 0.0),
        reverse=True,
    )

    return {
        "total_transitions_observed": len(by_transition),
        "total_transition_events": len(rows),
        "min_sample_threshold": MIN_SAMPLE_SIZE,
        "transitions": transition_stats,
    }


def build_three_period_transitions(db_path: Path) -> dict[str, Any]:
    """Build three-period协同跃迁 statistics."""
    con = duckdb.connect(str(db_path), read_only=True)

    # Scenario definitions as SQL conditions
    scenarios = {
        "any_enter_ef": """
            (ABS(t.prev_mn1) < 14 AND ABS(t.mn1_state_score) >= 14) OR
            (ABS(t.prev_w1) < 14 AND ABS(t.w1_state_score) >= 14) OR
            (ABS(t.prev_d1) < 14 AND ABS(t.d1_state_score) >= 14)
        """,
        "any_exit_ef": """
            (ABS(t.prev_mn1) >= 14 AND ABS(t.mn1_state_score) < 14) OR
            (ABS(t.prev_w1) >= 14 AND ABS(t.w1_state_score) < 14) OR
            (ABS(t.prev_d1) >= 14 AND ABS(t.d1_state_score) < 14)
        """,
        "all_enter_ef": """
            (ABS(t.prev_mn1) < 14 AND ABS(t.mn1_state_score) >= 14) AND
            (ABS(t.prev_w1) < 14 AND ABS(t.w1_state_score) >= 14) AND
            (ABS(t.prev_d1) < 14 AND ABS(t.d1_state_score) >= 14)
        """,
        "all_exit_ef": """
            (ABS(t.prev_mn1) >= 14 AND ABS(t.mn1_state_score) < 14) AND
            (ABS(t.prev_w1) >= 14 AND ABS(t.w1_state_score) < 14) AND
            (ABS(t.prev_d1) >= 14 AND ABS(t.d1_state_score) < 14)
        """,
        "any_enter_breakout": """
            (ABS(t.prev_mn1) NOT IN (10, 11, -10, -11) AND ABS(t.mn1_state_score) IN (10, 11, -10, -11)) OR
            (ABS(t.prev_w1) NOT IN (10, 11, -10, -11) AND ABS(t.w1_state_score) IN (10, 11, -10, -11)) OR
            (ABS(t.prev_d1) NOT IN (10, 11, -10, -11) AND ABS(t.d1_state_score) IN (10, 11, -10, -11))
        """,
        "d1_enter_ef": "ABS(t.prev_d1) < 14 AND ABS(t.d1_state_score) >= 14",
        "d1_exit_ef": "ABS(t.prev_d1) >= 14 AND ABS(t.d1_state_score) < 14",
        "d1_enter_breakout": "ABS(t.prev_d1) NOT IN (10, 11, -10, -11) AND ABS(t.d1_state_score) IN (10, 11, -10, -11)",
        "d1_base_0_to_8": "t.prev_d1_base = 0 AND t.curr_d1_base = 8",
        "d1_base_8_to_0": "t.prev_d1_base = 8 AND t.curr_d1_base = 0",
        "d1_vol_0_to_1": "t.prev_d1_vol = 0 AND t.curr_d1_vol = 1",
        "d1_vol_1_to_0": "t.prev_d1_vol = 1 AND t.curr_d1_vol = 0",
    }

    scenario_results: dict[str, Any] = {}

    for scenario_name, condition in scenarios.items():
        rows = con.execute(
            f"""
            WITH transitions AS (
                SELECT 
                    stock_code,
                    state_date,
                    mn1_state_score, w1_state_score, d1_state_score,
                    LAG(mn1_state_score) OVER (PARTITION BY stock_code ORDER BY state_date) as prev_mn1,
                    LAG(w1_state_score) OVER (PARTITION BY stock_code ORDER BY state_date) as prev_w1,
                    LAG(d1_state_score) OVER (PARTITION BY stock_code ORDER BY state_date) as prev_d1,
                    LAG(mn1_base) OVER (PARTITION BY stock_code ORDER BY state_date) as prev_mn1_base,
                    LAG(w1_base) OVER (PARTITION BY stock_code ORDER BY state_date) as prev_w1_base,
                    LAG(d1_base) OVER (PARTITION BY stock_code ORDER BY state_date) as prev_d1_base,
                    LAG(mn1_volatility_bit) OVER (PARTITION BY stock_code ORDER BY state_date) as prev_mn1_vol,
                    LAG(w1_volatility_bit) OVER (PARTITION BY stock_code ORDER BY state_date) as prev_w1_vol,
                    LAG(d1_volatility_bit) OVER (PARTITION BY stock_code ORDER BY state_date) as prev_d1_vol,
                    mn1_base as curr_mn1_base, w1_base as curr_w1_base, d1_base as curr_d1_base,
                    mn1_volatility_bit as curr_mn1_vol, w1_volatility_bit as curr_w1_vol, d1_volatility_bit as curr_d1_vol,
                    d1_close,
                    LEAD(d1_close, 5) OVER (PARTITION BY stock_code ORDER BY state_date) as close_5d,
                    LEAD(d1_close, 10) OVER (PARTITION BY stock_code ORDER BY state_date) as close_10d,
                    LEAD(d1_close, 20) OVER (PARTITION BY stock_code ORDER BY state_date) as close_20d
                FROM d1_perspective_state
            ),
            daily_market AS (
                SELECT 
                    state_date,
                    AVG(CASE WHEN close_5d IS NOT NULL THEN close_5d/d1_close - 1 END) as mkt_5d,
                    AVG(CASE WHEN close_10d IS NOT NULL THEN close_10d/d1_close - 1 END) as mkt_10d,
                    AVG(CASE WHEN close_20d IS NOT NULL THEN close_20d/d1_close - 1 END) as mkt_20d
                FROM transitions
                WHERE close_5d IS NOT NULL
                GROUP BY state_date
            )
            SELECT 
                t.close_5d/t.d1_close - 1 - m.mkt_5d as excess_5d,
                t.close_10d/t.d1_close - 1 - m.mkt_10d as excess_10d,
                t.close_20d/t.d1_close - 1 - m.mkt_20d as excess_20d
            FROM transitions t
            JOIN daily_market m ON t.state_date = m.state_date
            WHERE t.close_5d IS NOT NULL
              AND t.close_10d IS NOT NULL
              AND t.close_20d IS NOT NULL
              AND ({condition})
            """
        ).fetchall()

        excess_5d = [float(r[0]) for r in rows]
        excess_10d = [float(r[1]) for r in rows]
        excess_20d = [float(r[2]) for r in rows]

        scenario_results[scenario_name] = {
            "sample_size": len(rows),
            "sample_adequate": len(rows) >= MIN_SAMPLE_SIZE,
            "excess_5d": compute_metrics(excess_5d),
            "excess_10d": compute_metrics(excess_10d),
            "excess_20d": compute_metrics(excess_20d),
        }

    con.close()
    return scenario_results


def build_top_transitions_report(d1_matrix: dict[str, Any], top_n: int = 50) -> list[dict[str, Any]]:
    """Extract top N transitions by |excess_20d| for reporting."""
    adequate = [t for t in d1_matrix["transitions"] if t["sample_adequate"]]
    return adequate[:top_n]


def render_markdown(
    d1_matrix: dict[str, Any],
    three_period: dict[str, Any],
    db_path: Path,
    generated_at: str,
) -> str:
    lines = [
        "# State 跃迁统计分析报告",
        "",
        f"- 生成时间: `{generated_at}`",
        f"- Foundation DB: `{db_path}`",
        f"- 最小样本阈值: `{MIN_SAMPLE_SIZE}`",
        f"- D1 跃迁事件总数: `{d1_matrix['total_transition_events']:,}`",
        f"- 观测到的不同跃迁类型: `{d1_matrix['total_transitions_observed']}` / 256 种",
        "",
        "## 核心原则",
        "",
        "1. **数据优先**: 不预设哪些跃迁是'好'的，让数据库告诉我们。",
        "2. **保持开放**: 扫描全部 16×16=256 种 D1 State 跃迁，以及 MN1/W1/D1 三周期协同跃迁。",
        "3. **逐步积累**: 输出每种跃迁的样本量、超额收益、胜率；样本不足的标注'待积累'。",
        "4. **不做二元判定**: 不做'有效/无效'判断，只呈现统计事实。",
        "",
        "---",
        "",
        "## 一、D1 State 跃迁矩阵（Top 50 按 |20日超额| 排序）",
        "",
        "| 排名 | 跃迁 | 样本量 | 5日超额 | 5日胜率 | 10日超额 | 10日胜率 | 20日超额 | 20日胜率 | 盈亏比 | t-stat | 充足? |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---|",
    ]

    top = build_top_transitions_report(d1_matrix, top_n=50)
    for idx, t in enumerate(top, 1):
        e5 = t["excess_5d"]
        e10 = t["excess_10d"]
        e20 = t["excess_20d"]
        adequate = "✅ 充足" if t["sample_adequate"] else "⚠️ 待积累"
        pr_str = f"{e5['payoff_ratio']:.3f}" if e5['payoff_ratio'] is not None else "-"
        lines.append(
            f"| {idx} | `{t['prev_hex']}->{t['curr_hex']}` | {t['sample_size']:,} | "
            f"{e5['mean']:.4f} | {e5['win_rate']:.2%} | "
            f"{e10['mean']:.4f} | {e10['win_rate']:.2%} | "
            f"{e20['mean']:.4f} | {e20['win_rate']:.2%} | "
            f"{pr_str} | {e5['t_stat']:.2f} | {adequate} |"
        )

    lines.extend([
        "",
        "### 样本量矩阵（D1 State 跃迁）",
        "",
        "行=前一日 State，列=当日 State。数值=样本量，空白=无样本。",
        "",
    ])

    # Build sample size matrix
    sample_matrix: dict[int, dict[int, int]] = defaultdict(dict)
    for t in d1_matrix["transitions"]:
        sample_matrix[t["prev_state"]][t["curr_state"]] = t["sample_size"]

    # Get all observed states
    all_states = sorted(set(t["prev_state"] for t in d1_matrix["transitions"]) | set(t["curr_state"] for t in d1_matrix["transitions"]))

    # Header
    header = "| 前\\后 | " + " | ".join(f"{state_hex(s)}" for s in all_states) + " |"
    separator = "|---|" + "|".join("---" for _ in all_states) + "|"
    lines.extend([header, separator])

    for prev in all_states:
        row_cells = [f"**{state_hex(prev)}**"]
        for curr in all_states:
            n = sample_matrix.get(prev, {}).get(curr, 0)
            if n >= MIN_SAMPLE_SIZE:
                row_cells.append(f"{n:,}")
            elif n > 0:
                row_cells.append(f"<span style='color:#999'>{n}</span>")
            else:
                row_cells.append("")
        lines.append("| " + " | ".join(row_cells) + " |")

    lines.extend([
        "",
        "---",
        "",
        "## 二、三周期协同跃迁统计",
        "",
        "| 场景 | 样本量 | 充足? | 5日超额 | 5日胜率 | 10日超额 | 10日胜率 | 20日超额 | 20日胜率 | 盈亏比 |",
        "|---|---:|:---|---:|---:|---:|---:|---:|---:|---:|",
    ])

    scenario_labels = {
        "any_enter_ef": "任意周期进入 E/F",
        "any_exit_ef": "任意周期退出 E/F",
        "all_enter_ef": "三周期同时进入 E/F",
        "all_exit_ef": "三周期同时退出 E/F",
        "any_enter_breakout": "任意周期进入突破态(10/11)",
        "d1_enter_ef": "D1 单独进入 E/F",
        "d1_exit_ef": "D1 单独退出 E/F",
        "d1_enter_breakout": "D1 单独进入突破态",
        "d1_base_0_to_8": "D1 base 0→8 (收缩→扩张)",
        "d1_base_8_to_0": "D1 base 8→0 (扩张→收缩)",
        "d1_vol_0_to_1": "D1 波动稳定→活跃",
        "d1_vol_1_to_0": "D1 波动活跃→稳定",
    }

    for key, label in scenario_labels.items():
        s = three_period.get(key, {})
        e5 = s.get("excess_5d", {})
        e10 = s.get("excess_10d", {})
        e20 = s.get("excess_20d", {})
        adequate = "✅ 充足" if s.get("sample_adequate") else "⚠️ 待积累"
        pr_str = f"{e5.get('payoff_ratio'):.3f}" if e5.get('payoff_ratio') is not None else "-"
        m5 = e5.get('mean', 0) or 0
        wr5 = e5.get('win_rate', 0) or 0
        m10 = e10.get('mean', 0) or 0
        wr10 = e10.get('win_rate', 0) or 0
        m20 = e20.get('mean', 0) or 0
        wr20 = e20.get('win_rate', 0) or 0
        lines.append(
            f"| {label} | {s.get('sample_size', 0):,} | {adequate} | "
            f"{m5:.4f} | {wr5:.2%} | "
            f"{m10:.4f} | {wr10:.2%} | "
            f"{m20:.4f} | {wr20:.2%} | "
            f"{pr_str} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 三、统计边界说明",
        "",
        "1. **超额收益计算**: 个股 forward return 减去当日全市场等权平均 return。",
        "2. **样本充足标准**: ≥30 个样本。低于此阈值的结论仅作为'候选观察'。",
        "3. **t-stat 解读**: |t-stat| > 1.96 表示 95% 置信度下显著不为零。",
        "4. **过拟合警告**: 精确 State 组合存在过拟合风险，需结合模糊 bit 聚合和样本外验证。",
        "5. **数据范围**: 2018-05-15 至 2026-05-22，全市场 A 股。",
        "",
        "---",
        "",
        "*本报告为研究性质，不构成交易建议。所有数字均为历史统计，不代表未来表现。*",
        "",
    ])

    return "\n".join(lines)


def run_analysis(db_path: Path) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    print("Building D1 transition matrix...", file=sys.stderr)
    d1_matrix = build_d1_transition_matrix(db_path)
    print(f"  -> {d1_matrix['total_transitions_observed']} transitions, {d1_matrix['total_transition_events']} events", file=sys.stderr)

    print("Building three-period协同跃迁...", file=sys.stderr)
    three_period = build_three_period_transitions(db_path)
    print(f"  -> {len(three_period)} scenarios computed", file=sys.stderr)

    result = {
        "schema_version": "state_transition_analysis_v1",
        "generated_at": generated_at,
        "research_only": True,
        "foundation_db": str(db_path),
        "min_sample_threshold": MIN_SAMPLE_SIZE,
        "windows": WINDOWS,
        "d1_transition_matrix": d1_matrix,
        "three_period_transitions": three_period,
    }

    # Write JSON
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "state_transition_analysis.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON written: {json_path}", file=sys.stderr)

    # Write Markdown
    md = render_markdown(d1_matrix, three_period, db_path, generated_at)
    md_path = OUT_DIR / "state_transition_analysis.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"Markdown written: {md_path}", file=sys.stderr)

    return {
        "ok": True,
        "json": str(json_path),
        "markdown": str(md_path),
        "d1_transitions": d1_matrix["total_transitions_observed"],
        "d1_events": d1_matrix["total_transition_events"],
        "scenarios": len(three_period),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="State transition analysis from foundation DB.")
    parser.add_argument("--foundation-db", type=Path, help="Path to foundation DuckDB")
    args = parser.parse_args()

    if args.foundation_db:
        db_path = args.foundation_db
    else:
        candidates = sorted(ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"))
        if not candidates:
            print("No foundation DB found", file=sys.stderr)
            return 1
        db_path = candidates[-1]

    result = run_analysis(db_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
