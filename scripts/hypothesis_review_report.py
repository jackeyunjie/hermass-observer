#!/usr/bin/env python3
"""
hypothesis_review_report.py — 假设验证复盘报告生成器

从 decision_observation.duckdb 读取数据，生成 Markdown 复盘报告。

Usage:
    .venv/bin/python scripts/hypothesis_review_report.py --hypothesis D1_CONTRACTION_BREAKOUT_OBSERVATION --from 2026-05-01 --to 2026-06-05
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DECISION_OBSERVATION_DB = PROJECT_ROOT / "outputs" / "decision_observation" / "decision_observation.duckdb"
REPORT_DIR = PROJECT_ROOT / "outputs" / "hypothesis_reviews"


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"{v * 100:.2f}%"


def _fmt_float(v: float | None, decimals: int = 4) -> str:
    if v is None:
        return "N/A"
    return f"{v:.{decimals}f}"


def generate_report(hypothesis_id: str, from_date: date, to_date: date) -> str:
    if not DECISION_OBSERVATION_DB.exists():
        return f"# 假设复盘报告\n\n**错误**: 数据库不存在: {DECISION_OBSERVATION_DB}\n"

    con = duckdb.connect(str(DECISION_OBSERVATION_DB), read_only=True)

    # Basic stats
    total_row = con.execute(
        "SELECT COUNT(*) FROM decision_observation WHERE hypothesis_id = ? AND state_date BETWEEN ? AND ?",
        [hypothesis_id, from_date, to_date],
    ).fetchone()
    total = total_row[0] if total_row else 0

    if total < 5:
        con.close()
        return (
            f"# 假设复盘报告\n\n"
            f"- **假设 ID**: {hypothesis_id}\n"
            f"- **日期范围**: {from_date} ~ {to_date}\n"
            f"- **样本数量**: {total}\n\n"
            f"> 数据不足（样本 < 5），无法生成有意义的统计量。\n\n"
            f"> 本报告仅为假设验证的观察复盘，不构成投资建议。\n"
        )

    # Label distribution
    label_rows = con.execute(
        "SELECT final_label, COUNT(*) FROM decision_observation WHERE hypothesis_id = ? AND state_date BETWEEN ? AND ? GROUP BY final_label",
        [hypothesis_id, from_date, to_date],
    ).fetchall()
    label_dist: dict[str, int] = {row[0] or "unknown": row[1] for row in label_rows}

    # Return stats by label
    return_rows = con.execute(
        """
        SELECT final_label,
               AVG(future_r5),
               AVG(future_r20),
               COUNT(*)
        FROM decision_observation
        WHERE hypothesis_id = ? AND state_date BETWEEN ? AND ?
          AND future_r5 IS NOT NULL
        GROUP BY final_label
        """,
        [hypothesis_id, from_date, to_date],
    ).fetchall()
    return_stats: dict[str, dict[str, Any]] = {}
    for row in return_rows:
        label = row[0] or "unknown"
        return_stats[label] = {
            "avg_r5": row[1],
            "avg_r20": row[2],
            "count": row[3],
        }

    # Precision@10: top 10 observe candidates by future_r5
    precision_rows = con.execute(
        """
        SELECT stock_code, state_date, future_r5
        FROM decision_observation
        WHERE hypothesis_id = ? AND state_date BETWEEN ? AND ?
          AND final_label = 'observe'
          AND future_r5 IS NOT NULL
        ORDER BY future_r5 DESC
        LIMIT 10
        """,
        [hypothesis_id, from_date, to_date],
    ).fetchall()
    precision_avg = None
    if precision_rows:
        precision_avg = sum(r[2] for r in precision_rows) / len(precision_rows)

    # RiskAgent Veto analysis
    veto_rows = con.execute(
        """
        SELECT risk_veto, AVG(future_r5), COUNT(*)
        FROM decision_observation
        WHERE hypothesis_id = ? AND state_date BETWEEN ? AND ?
          AND future_r5 IS NOT NULL
        GROUP BY risk_veto
        """,
        [hypothesis_id, from_date, to_date],
    ).fetchall()
    veto_stats: dict[bool, dict[str, Any]] = {}
    for row in veto_rows:
        veto_val = bool(row[0])
        veto_stats[veto_val] = {"avg_r5": row[1], "count": row[2]}

    # Conflict vs Resonance: need to parse router_json
    # DuckDB can extract JSON fields
    conflict_rows = con.execute(
        """
        SELECT
            AVG(future_r5) FILTER (WHERE CAST(json_extract_string(router_json, '$.conflict_score') AS DOUBLE) > 0.5),
            COUNT(*) FILTER (WHERE CAST(json_extract_string(router_json, '$.conflict_score') AS DOUBLE) > 0.5),
            AVG(future_r5) FILTER (WHERE CAST(json_extract_string(router_json, '$.resonance_score') AS DOUBLE) > 0.5),
            COUNT(*) FILTER (WHERE CAST(json_extract_string(router_json, '$.resonance_score') AS DOUBLE) > 0.5)
        FROM decision_observation
        WHERE hypothesis_id = ? AND state_date BETWEEN ? AND ?
          AND future_r5 IS NOT NULL
        """,
        [hypothesis_id, from_date, to_date],
    ).fetchone()
    high_conflict_avg = conflict_rows[0]
    high_conflict_count = conflict_rows[1]
    high_resonance_avg = conflict_rows[2]
    high_resonance_count = conflict_rows[3]

    # Typical hits: future_r5 > 0.10 and final_label = observe
    hit_rows = con.execute(
        """
        SELECT stock_code, state_date, future_r5, final_score
        FROM decision_observation
        WHERE hypothesis_id = ? AND state_date BETWEEN ? AND ?
          AND final_label = 'observe'
          AND future_r5 > 0.10
        ORDER BY future_r5 DESC
        LIMIT 3
        """,
        [hypothesis_id, from_date, to_date],
    ).fetchall()

    # Typical misses: future_r5 < -0.10 and final_label = observe
    miss_rows = con.execute(
        """
        SELECT stock_code, state_date, future_r5, final_score
        FROM decision_observation
        WHERE hypothesis_id = ? AND state_date BETWEEN ? AND ?
          AND final_label = 'observe'
          AND future_r5 < -0.10
        ORDER BY future_r5 ASC
        LIMIT 3
        """,
        [hypothesis_id, from_date, to_date],
    ).fetchall()

    # Overall observe stats for recommendation
    observe_r5_rows = con.execute(
        """
        SELECT AVG(future_r5), COUNT(*)
        FROM decision_observation
        WHERE hypothesis_id = ? AND state_date BETWEEN ? AND ?
          AND final_label = 'observe'
          AND future_r5 IS NOT NULL
        """,
        [hypothesis_id, from_date, to_date],
    ).fetchone()
    observe_avg_r5 = observe_r5_rows[0]
    observe_count = observe_r5_rows[1]

    con.close()

    # Build report
    lines: list[str] = []
    lines.append(f"# 假设复盘报告: {hypothesis_id}")
    lines.append("")
    lines.append(f"- **日期范围**: {from_date} ~ {to_date}")
    lines.append(f"- **样本数量**: {total}")
    lines.append("")
    lines.append("> 本报告仅为假设验证的观察复盘，不构成投资建议。")
    lines.append("")

    # 1. 假设概述
    lines.append("## 假设概述")
    lines.append("")
    lines.append(f"假设 `{hypothesis_id}` 在 {from_date} 至 {to_date} 期间共产生 **{total}** 条观察记录。")
    lines.append("")

    # 2. 标签分布
    lines.append("## 标签分布")
    lines.append("")
    for label in ("observe", "watch", "reject", "unknown"):
        count = label_dist.get(label, 0)
        pct = count / total * 100 if total > 0 else 0
        lines.append(f"- **{label}**: {count} 只 ({pct:.1f}%)")
    lines.append("")

    # 3. 收益统计
    lines.append("## 收益统计")
    lines.append("")
    lines.append("| 标签 | 样本数 | avg future_r5 | avg future_r20 |")
    lines.append("|------|--------|---------------|----------------|")
    for label in ("observe", "watch", "reject", "unknown"):
        stats = return_stats.get(label, {})
        count = stats.get("count", 0)
        avg_r5 = _fmt_pct(stats.get("avg_r5"))
        avg_r20 = _fmt_pct(stats.get("avg_r20"))
        lines.append(f"| {label} | {count} | {avg_r5} | {avg_r20} |")
    lines.append("")

    # 4. Precision@10
    lines.append("## Precision@10")
    lines.append("")
    if precision_avg is not None:
        lines.append(f"在 `final_label=observe` 的候选中，future_r5 最高的前 10 只平均收益为 **{_fmt_pct(precision_avg)}**。")
        lines.append("")
        lines.append("| 排名 | 股票代码 | 日期 | future_r5 |")
        lines.append("|------|----------|------|-----------|")
        for i, (stock_code, state_date, future_r5) in enumerate(precision_rows, 1):
            lines.append(f"| {i} | {stock_code} | {state_date} | {_fmt_pct(future_r5)} |")
    else:
        lines.append("`final_label=observe` 且 future_r5 有值的候选不足，无法计算 Precision@10。")
    lines.append("")

    # 5. RiskAgent Veto 分析
    lines.append("## RiskAgent Veto 分析")
    lines.append("")
    veto_true = veto_stats.get(True, {})
    veto_false = veto_stats.get(False, {})
    lines.append(f"- **veto=true**: {veto_true.get('count', 0)} 只，avg future_r5 = {_fmt_pct(veto_true.get('avg_r5'))}")
    lines.append(f"- **veto=false**: {veto_false.get('count', 0)} 只，avg future_r5 = {_fmt_pct(veto_false.get('avg_r5'))}")
    lines.append("")

    # 6. 冲突 vs 共振
    lines.append("## 冲突 vs 共振")
    lines.append("")
    lines.append(f"- **高冲突** (conflict_score > 0.5): {high_conflict_count or 0} 只，avg future_r5 = {_fmt_pct(high_conflict_avg)}")
    lines.append(f"- **高共振** (resonance_score > 0.5): {high_resonance_count or 0} 只，avg future_r5 = {_fmt_pct(high_resonance_avg)}")
    lines.append("")

    # 7. 典型命中案例
    lines.append("## 典型命中案例")
    lines.append("")
    if hit_rows:
        lines.append("future_r5 > 10% 且 final_label=observe 的候选：")
        lines.append("")
        lines.append("| 股票代码 | 日期 | future_r5 | final_score |")
        lines.append("|----------|------|-----------|-------------|")
        for stock_code, state_date, future_r5, final_score in hit_rows:
            lines.append(f"| {stock_code} | {state_date} | {_fmt_pct(future_r5)} | {_fmt_float(final_score)} |")
    else:
        lines.append("本周期内无 future_r5 > 10% 的命中案例。")
    lines.append("")

    # 8. 典型误判案例
    lines.append("## 典型误判案例")
    lines.append("")
    if miss_rows:
        lines.append("future_r5 < -10% 但 final_label=observe 的候选（误判）：")
        lines.append("")
        lines.append("| 股票代码 | 日期 | future_r5 | final_score |")
        lines.append("|----------|------|-----------|-------------|")
        for stock_code, state_date, future_r5, final_score in miss_rows:
            lines.append(f"| {stock_code} | {state_date} | {_fmt_pct(future_r5)} | {_fmt_float(final_score)} |")
    else:
        lines.append("本周期内无 future_r5 < -10% 的误判案例。")
    lines.append("")

    # 9. 假设修正建议
    lines.append("## 假设修正建议")
    lines.append("")
    suggestions: list[str] = []

    if observe_avg_r5 is not None:
        if observe_avg_r5 < 0:
            suggestions.append(f"`observe` 标签整体平均 future_r5 为 {_fmt_pct(observe_avg_r5)}，呈负收益，说明当前筛选条件可能过于宽松或方向性判断有误。")
        elif observe_avg_r5 < 0.02:
            suggestions.append(f"`observe` 标签整体平均 future_r5 为 {_fmt_pct(observe_avg_r5)}，收益微弱，建议收紧筛选条件或增加确认因子。")
        else:
            suggestions.append(f"`observe` 标签整体平均 future_r5 为 {_fmt_pct(observe_avg_r5)}，方向为正，可继续保持观察。")

    if high_resonance_avg is not None and high_conflict_avg is not None:
        if high_resonance_avg > high_conflict_avg:
            suggestions.append("高共振候选表现优于高冲突候选，建议下一轮提高 resonance_score 的权重门槛。")
        else:
            suggestions.append("高冲突候选反而表现更好，说明当前 Agent 共识可能存在'集体误判'，建议引入更多独立 Agent 或降低共振权重。")

    if veto_true and veto_false:
        vt_r5 = veto_true.get("avg_r5")
        vf_r5 = veto_false.get("avg_r5")
        if vt_r5 is not None and vf_r5 is not None:
            if vt_r5 > vf_r5:
                suggestions.append("RiskAgent veto=true 的候选反而收益更高，说明当前 RiskAgent 的 veto 逻辑可能过于保守，建议校准风险阈值。")
            else:
                suggestions.append("RiskAgent veto=false 的候选收益更高，veto 机制基本有效，可继续保持。")

    if precision_avg is not None and precision_avg < 0:
        suggestions.append("Precision@10 为负，说明 top 10 观察候选的短期表现不佳，建议增加动量或成交量确认因子。")

    if not suggestions:
        suggestions.append("当前数据量有限，建议积累更多样本后再做系统性修正。")

    for s in suggestions:
        lines.append(f"- {s}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="假设验证复盘报告生成器")
    parser.add_argument("--hypothesis", type=str, required=True, help="假设 ID")
    parser.add_argument("--from", dest="from_date", type=str, required=True, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--to", type=str, required=True, help="结束日期 YYYY-MM-DD")
    args = parser.parse_args()

    from_date = _parse_date(args.from_date)
    to_date = _parse_date(args.to)
    hypothesis_id = args.hypothesis

    print(f"[report] 生成报告: hypothesis={hypothesis_id} {from_date} ~ {to_date}")

    report_md = generate_report(hypothesis_id, from_date, to_date)

    os.makedirs(REPORT_DIR, exist_ok=True)
    report_path = REPORT_DIR / f"{hypothesis_id}_{from_date}_{to_date}_review.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"[report] 已写入: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
