#!/usr/bin/env python3
"""Phase 2 Agent 准确率回填 — 基于 state_cube 历史数据对 6 个 Agent 的方向判断评分。

方法：
1. 对 state_cube 中每个历史日期，运行与 agent_debate_runner 相同的规则逻辑
2. 产生每个 Agent 的 verdict_color (green/yellow/red)
3. 用该日期 state_cube 中所有标的的 avg(future_r5) 作为「市场实际走向」
4. 评分标准：
   - green 命中: avg_future_r5 > 0
   - red 命中: avg_future_r5 < 0
   - yellow 命中: |avg_future_r5| < 2%（市场确实横盘）

输出：outputs/agent_accuracy/accuracy_report.json
"""
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
STATE_CUBE = ROOT / "outputs" / "state_cube" / "state_cube.duckdb"
OUTPUT = ROOT / "outputs" / "debate" / "agent_accuracy_report.json"


def _market_aggregates_for_date(con, dt: str) -> dict:
    """为指定日期计算与 agent_debate_runner._market_aggregates 相同的聚合。"""
    row = con.execute(f"""
        SELECT
            COUNT(*) AS total,
            ROUND(AVG(d1_adx14), 1) AS avg_d1_adx,
            ROUND(AVG(w1_adx14), 1) AS avg_w1_adx,
            ROUND(AVG(CASE WHEN d1_plus_di_14 > d1_minus_di_14 THEN 1.0 ELSE 0.0 END) * 100, 1) AS d1_bull_pct,
            ROUND(AVG(CASE WHEN w1_plus_di_14 > w1_minus_di_14 THEN 1.0 ELSE 0.0 END) * 100, 1) AS w1_bull_pct,
            COUNT(CASE WHEN ef_count >= 2 THEN 1 END) AS ef2_count,
            COUNT(CASE WHEN ef_count >= 3 THEN 1 END) AS ef3_count,
            COUNT(CASE WHEN d1_bb20_position = 'above_upper' THEN 1 END) AS above_bb,
            COUNT(CASE WHEN d1_bb20_position = 'below_lower' THEN 1 END) AS below_bb,
            ROUND(AVG(d1_atr14 / NULLIF(d1_close, 0)) * 100, 1) AS avg_atr_pct,
            COUNT(CASE WHEN d1_adx14 >= 40 AND d1_plus_di_14 > d1_minus_di_14 THEN 1 END) AS strong_momentum,
            COUNT(CASE WHEN d1_adx14 >= 70 THEN 1 END) AS extreme_adx,
            COUNT(CASE WHEN d1_adx14 >= 30 AND d1_minus_di_14 > d1_plus_di_14 THEN 1 END) AS bearish_div,
            COUNT(CASE WHEN d1_bb20_position = 'above_upper' AND d1_adx14 < w1_adx14 THEN 1 END) AS fake_breakout,
            COUNT(CASE WHEN mn1_state_hex NOT IN ('E', 'F') AND ef_count >= 2 THEN 1 END) AS mn1_weak_ef2,
            ROUND(AVG(future_r5) * 100, 2) AS avg_future_r5_pct
        FROM state_cube
        WHERE state_date = '{dt}' AND d1_close > 0
    """).fetchone()
    return {
        "total_stocks": row[0], "avg_d1_adx": row[1], "avg_w1_adx": row[2],
        "d1_bull_pct": row[3], "w1_bull_pct": row[4],
        "ef2_count": row[5], "ef3_count": row[6],
        "d1_above_bb": row[7], "d1_below_bb": row[8],
        "avg_atr_pct": row[9],
        "strong_momentum": row[10], "extreme_adx": row[11],
        "bearish_div": row[12], "fake_breakout": row[13],
        "mn1_weak_ef2": row[14],
        "avg_future_r5_pct": row[15] or 0,
    }


def _agent_verdicts(market: dict) -> list[dict]:
    """对给定 market_aggregates 运行与 agent_debate_runner 相同的规则逻辑。
    返回 [{agent, verdict_color, verdict}] 列表。
    """
    opinions = []

    # 市场 Agent
    bull_pct = market["d1_bull_pct"]
    ef2_count = market["ef2_count"]
    phase = "强势多头" if bull_pct >= 55 and ef2_count >= 500 else (
        "温和偏多" if bull_pct >= 45 else "震荡整理"
    )
    opinions.append({
        "agent": "市场 Agent",
        "verdict_color": "green" if "多头" in phase else "yellow",
        "verdict": phase,
    })

    # 趋势 Agent
    pct_ef2 = ef2_count / max(market["total_stocks"], 1) * 100
    opinions.append({
        "agent": "趋势 Agent",
        "verdict_color": "green" if pct_ef2 >= 10 else "yellow",
        "verdict": "偏多" if pct_ef2 >= 8 else "中性",
    })

    # 动量 Agent
    opinions.append({
        "agent": "动量 Agent",
        "verdict_color": "green" if bull_pct >= 60 else ("yellow" if bull_pct >= 40 else "red"),
        "verdict": "偏多" if bull_pct >= 50 else "中性",
    })

    # 波动率 Agent
    extreme = market["d1_above_bb"] + market["d1_below_bb"]
    opinions.append({
        "agent": "波动率 Agent",
        "verdict_color": "yellow" if extreme > 300 else "green",
        "verdict": "观察" if extreme > 300 else "正常",
    })

    # 边界 Agent
    opinions.append({
        "agent": "边界 Agent",
        "verdict_color": "yellow" if market["d1_above_bb"] > 50 else "green",
        "verdict": "谨慎" if market["d1_above_bb"] > 50 else "正常",
    })

    # 风险 Agent
    risks = 0
    if market["extreme_adx"] >= 5:
        risks += 1
    if market["bearish_div"] >= 10:
        risks += 1
    if market["fake_breakout"] >= 5:
        risks += 1
    if market["mn1_weak_ef2"] >= 20:
        risks += 1
    opinions.append({
        "agent": "风险 Agent",
        "verdict_color": "red" if risks >= 2 else ("yellow" if risks else "green"),
        "verdict": "有风险" if risks >= 2 else ("观察" if risks else "安全"),
    })

    return opinions


def _score_verdict(verdict_color: str, avg_future_r5_pct: float) -> bool:
    """判断单个 Agent 的判断是否命中市场实际走向。"""
    if verdict_color == "green":
        return avg_future_r5_pct > 0
    elif verdict_color == "red":
        return avg_future_r5_pct < 0
    else:  # yellow
        return abs(avg_future_r5_pct) < 2.0


def main() -> dict:
    if not STATE_CUBE.exists():
        return {"error": "state_cube.duckdb 不存在"}

    con = duckdb.connect(str(STATE_CUBE), read_only=True)
    dates = [
        str(row[0]) for row in
        con.execute(
            "SELECT DISTINCT state_date FROM state_cube "
            "WHERE future_r5 IS NOT NULL "
            "ORDER BY state_date ASC"
        ).fetchall()
    ]

    # 按 Agent 聚合：{agent_name: {hits: int, total: int, returns: [float], dates: [str]}}
    agent_stats: dict[str, dict] = {}
    daily_records = []

    for dt in dates:
        market = _market_aggregates_for_date(con, dt)
        opinions = _agent_verdicts(market)
        avg_future = market["avg_future_r5_pct"]

        day_record = {
            "date": dt,
            "avg_future_r5_pct": avg_future,
            "total_stocks": market["total_stocks"],
            "ef2_count": market["ef2_count"],
            "d1_bull_pct": market["d1_bull_pct"],
            "agents": [],
        }

        for op in opinions:
            name = op["agent"]
            hit = _score_verdict(op["verdict_color"], avg_future)

            if name not in agent_stats:
                agent_stats[name] = {"hits": 0, "total": 0, "returns": [], "dates_hit": [], "dates_miss": []}

            agent_stats[name]["total"] += 1
            if hit:
                agent_stats[name]["hits"] += 1
                agent_stats[name]["dates_hit"].append(dt)
            else:
                agent_stats[name]["dates_miss"].append(dt)
            agent_stats[name]["returns"].append(avg_future)

            day_record["agents"].append({
                "agent": name,
                "verdict_color": op["verdict_color"],
                "verdict": op["verdict"],
                "hit": hit,
            })

        daily_records.append(day_record)

    con.close()

    # 构建 Agent 级准确率报告
    agents = []
    for name, stats in sorted(agent_stats.items()):
        total = stats["total"]
        hits = stats["hits"]
        hit_rate = round(hits / total * 100, 1) if total > 0 else 0
        avg_return = round(sum(stats["returns"]) / len(stats["returns"]), 2) if stats["returns"] else 0

        # 按方向分组统计
        green_total = 0
        green_hits = 0
        red_total = 0
        red_hits = 0
        yellow_total = 0
        yellow_hits = 0
        for dr in daily_records:
            for a in dr["agents"]:
                if a["agent"] == name:
                    if a["verdict_color"] == "green":
                        green_total += 1
                        if a["hit"]:
                            green_hits += 1
                    elif a["verdict_color"] == "red":
                        red_total += 1
                        if a["hit"]:
                            red_hits += 1
                    else:
                        yellow_total += 1
                        if a["hit"]:
                            yellow_hits += 1

        agents.append({
            "agent": name,
            "total_days": total,
            "hit_count": hits,
            "hit_rate_pct": hit_rate,
            "avg_market_return_pct": avg_return,
            "green_hit_rate": round(green_hits / green_total * 100, 1) if green_total > 0 else None,
            "red_hit_rate": round(red_hits / red_total * 100, 1) if red_total > 0 else None,
            "yellow_hit_rate": round(yellow_hits / yellow_total * 100, 1) if yellow_total > 0 else None,
            "green_count": green_total,
            "red_count": red_total,
            "yellow_count": yellow_total,
            "calibration_note": _calibration_note(hit_rate),
        })

    # 全局统计
    all_hits = sum(a["hit_count"] for a in agents)
    all_total = sum(a["total_days"] for a in agents)
    overall_rate = round(all_hits / all_total * 100, 1) if all_total > 0 else 0

    result = {
        "generated_at": date.today().isoformat(),
        "date_range": f"{dates[0]} ~ {dates[-1]}",
        "total_trading_days": len(dates),
        "data_source": f"state_cube.duckdb future_r5 回填",
        "benchmark": "avg(future_r5) 作为市场实际走向",
        "overall_hit_rate_pct": overall_rate,
        "agents": agents,
        "recent_daily": daily_records[-5:] if len(daily_records) >= 5 else daily_records,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {OUTPUT} — {len(dates)} 天, {len(agents)} agents, 全局命中率 {overall_rate}%")

    return result


def _calibration_note(hit_rate: float) -> str:
    if hit_rate >= 60:
        return "已校准（命中率良好）"
    elif hit_rate >= 50:
        return "可接受（随机水平附近，需跟踪）"
    elif hit_rate >= 40:
        return "需校准（低于随机，规则需调整）"
    else:
        return "未校准（严重偏差，不建议使用该 Agent 权重）"


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))
