#!/usr/bin/env python3
"""Dynamic Weight Router — 动态权重路由器。

基于 State Cube 多周期状态全景 + 多 Agent 辩论结果，分配权重、识别冲突/共振、
输出最终观察结论。

核心规则（来自 AGENTS.MD）：
  - Router 权重必须来自同一时刻状态全景、冲突/共振、周期层级和历史 outcome
  - 不要写死 ef_count_min 作为入口
  - M30 Agent 只做盘中观察和精确位置判断，不单独拍板
  - Risk Agent 必须作为常驻反驳者

权重分配逻辑：
  1. 周期层级权重：MN1 > W1 > D1 > M30（M30 权重最低，只做精细确认）
  2. Agent 共识权重：多 Agent 共振加分，冲突减分
  3. 历史 outcome 权重：同类状态历史胜率高的加分
  4. M30 特殊规则：仅在 D1/W1 收缩期提供权重微调，不单独触发

Usage:
    python3 scripts/dynamic_weight_router.py --date 2026-06-02 --debate-json outputs/debate/...
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import duckdb

from hermass_platform.agents.base_agent import find_foundation_db


# ── 周期层级基础权重 ──
TIMEFRAME_BASE_WEIGHTS = {
    "MN1": 0.35,
    "W1": 0.30,
    "D1": 0.25,
    "M30": 0.10,  # M30 权重最低，只做精细确认
}

# ── Agent 类型权重 ──
AGENT_TYPE_WEIGHTS = {
    "contraction_observer": 0.30,
    "m30_observer": 0.15,        # M30 权重低，不单独拍板
    "risk_guardian": 0.25,       # Risk 常驻反驳，权重高
    "market_analyst": 0.15,
    "strategy_advisor": 0.15,
}

# ── 共振/冲突调整系数 ──
RESONANCE_BONUS = 0.20
CONFLICT_PENALTY = -0.15

# ── AgentMemory 路径 ──
DEFAULT_AGENT_MEMORY = ROOT / "outputs" / "agent_memory" / "AgentMemory.duckdb"


def _load_historical_outcome(
    state_hex_key: str,
    agent_memory_db: str = "",
) -> float:
    """查询同类状态的历史 outcome 胜率，返回 [-0.1, 0.1] 的权重调整。

    从 AgentMemory.judgment_outcomes 中，按 scenario_label 匹配 state_hex_key，
    统计 direction_correct 率。无数据时返回 0。
    """
    mem_path = agent_memory_db or str(DEFAULT_AGENT_MEMORY)
    if not Path(mem_path).exists():
        return 0.0

    try:
        con = duckdb.connect(mem_path, read_only=True)
        # 检查表是否存在
        tables = con.execute("SHOW TABLES").fetchdf()
        if "judgment_outcomes" not in tables["name"].values:
            con.close()
            return 0.0

        # 按 scenario_label 匹配（state_hex_key 如 "E-D1-F"）
        row = con.execute(f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN direction_correct THEN 1 ELSE 0 END) AS correct
            FROM judgment_outcomes
            WHERE scenario_label = '{state_hex_key}'
        """).fetchone()
        con.close()

        total = row[0] if row and row[0] else 0
        correct = row[1] if row and row[1] else 0

        if total < 5:
            # 样本不足，不调整
            return 0.0

        win_rate = correct / total
        # 胜率 > 0.6 加分，< 0.4 减分，映射到 [-0.1, 0.1]
        if win_rate > 0.6:
            return min(0.1, (win_rate - 0.6) * 0.5)
        elif win_rate < 0.4:
            return max(-0.1, (win_rate - 0.4) * 0.5)
        return 0.0

    except Exception:
        return 0.0


def route_weights(
    target_date: str,
    state_cube_db: str = "",
    foundation_db: str = "",
    debate_json: str = "",
    agent_memory_db: str = "",
    user_id: str = "system",
) -> dict:
    """基于 State Cube + Agent Debate 结果分配动态权重。

    Args:
        state_cube_db: State Cube DB 路径（优先使用）
        foundation_db: Foundation DB 路径（回退使用）

    Returns:
        dict: 包含每只股票的路由结果、权重分配、冲突标记、最终观察结论
    """
    # 优先使用 State Cube DB
    db_path = state_cube_db
    if not db_path:
        # 尝试查找默认 State Cube
        default_cube = ROOT / "outputs" / "state_cube" / "state_cube_m30.duckdb"
        if default_cube.exists():
            db_path = str(default_cube)

    # 回退到 Foundation DB
    if not db_path:
        db_path = foundation_db
    if not db_path:
        db_path = find_foundation_db(target_date)
        db_path = str(db_path) if db_path else ""

    if not db_path:
        return {"status": "error", "errors": ["无可用 State Cube 或 Foundation DB"]}

    print(f"=== Dynamic Weight Router: {target_date} ===")
    print(f"DB: {db_path}\n")

    # ── 1. 加载 State Cube 数据 ──
    con = duckdb.connect(db_path, read_only=True)

    # 检查 state_cube 表是否存在
    tables = con.execute("SHOW TABLES").fetchdf()
    has_state_cube = "state_cube" in tables["name"].values

    if has_state_cube:
        cube_df = con.execute(f"""
            SELECT
                stock_code, state_date,
                mn1_state_hex, w1_state_hex, d1_state_hex,
                ef_count, d1_close,
                m30_adx_slope_3, m30_breakout_signal, m30_price_breakout,
                m30_ma20_ready, m30_close_vs_ma20_flag
            FROM state_cube
            WHERE state_date = DATE '{target_date}'
              AND ef_count >= 2
            ORDER BY ef_count DESC, stock_code
            LIMIT 100
        """).fetchdf()
    else:
        # 回退到 d1_perspective_state（Foundation DB）
        cube_df = con.execute(f"""
            SELECT
                stock_code, state_date,
                mn1_state_hex, w1_state_hex, d1_state_hex,
                ef_count, d1_close,
                m30_adx_slope_3, m30_breakout_signal, m30_price_breakout,
                m30_ma20_ready, m30_close_vs_ma20_flag
            FROM d1_perspective_state
            WHERE state_date = DATE '{target_date}'
              AND ef_count >= 2
            ORDER BY ef_count DESC, stock_code
            LIMIT 100
        """).fetchdf()

    con.close()

    if cube_df.empty:
        return {"status": "warning", "summary": f"{target_date} 无候选数据", "routed": []}

    # ── 2. 加载 Debate 结果（如有） ──
    debate_data = {}
    if debate_json and Path(debate_json).exists():
        with open(debate_json, "r", encoding="utf-8") as f:
            debate_data = json.load(f)

    m30_obs_map = {}
    co_obs_map = {}
    if debate_data:
        m30_data = debate_data.get("agent_results", {}).get("m30_observer", {}).get("data", {})
        for o in m30_data.get("m30_observations", []):
            m30_obs_map[o["stock_code"]] = o

        co_data = debate_data.get("agent_results", {}).get("contraction_observer", {}).get("data", {})
        for o in co_data.get("observations", []):
            co_obs_map[o["stock_code"]] = o

    # ── 3. 逐只股票路由 ──
    routed = []

    for _, row in cube_df.iterrows():
        stock_code = row["stock_code"]
        mn1_hex = row.get("mn1_state_hex", "") or ""
        w1_hex = row.get("w1_state_hex", "") or ""
        d1_hex = row.get("d1_state_hex", "") or ""
        ef_count = row.get("ef_count", 0) or 0

        # 周期层级评分
        tf_score = 0
        tf_weights = {}
        for tf, weight in TIMEFRAME_BASE_WEIGHTS.items():
            hex_val = {"MN1": mn1_hex, "W1": w1_hex, "D1": d1_hex}.get(tf, "")
            is_ef = hex_val and hex_val[0] in ("E", "F") if hex_val else False
            tf_weights[tf] = {
                "base_weight": weight,
                "is_ef": is_ef,
                "state_hex": hex_val,
            }
            if is_ef:
                tf_score += weight

        # M30 观察输入
        m30_obs = m30_obs_map.get(stock_code, {})
        m30_breakout = m30_obs.get("m30_breakout_confirmed", False)
        m30_risk = m30_obs.get("m30_risk_flag", False)
        m30_score = m30_obs.get("score", 0)
        m30_resonance = m30_obs.get("m30_resonance", False)

        # Contraction 输入
        co_obs = co_obs_map.get(stock_code, {})
        is_contraction = co_obs.get("is_contraction", False)
        is_extreme = co_obs.get("is_extreme", False)

        # ── 动态权重计算 ──
        # 基础权重 = 周期层级评分
        base_weight = tf_score

        # Agent 共识调整
        consensus_adjust = 0
        if m30_resonance and is_contraction:
            consensus_adjust += RESONANCE_BONUS
        if m30_risk and is_contraction:
            consensus_adjust += CONFLICT_PENALTY
        if m30_breakout and not is_contraction:
            # M30 突破但大周期不收缩 = 假突破风险
            consensus_adjust += CONFLICT_PENALTY * 0.5

        # M30 精细微调（仅在 D1/W1 收缩期生效）
        m30_fine_tune = 0
        if ef_count >= 2 and m30_breakout:
            m30_fine_tune = 0.05  # 小周期突破给大周期加 5%
        elif m30_risk:
            m30_fine_tune = -0.05  # M30 风险信号减 5%

        # 历史 outcome 权重（同类状态历史胜率）
        state_hex_key = f"{mn1_hex}-{w1_hex}-{d1_hex}"
        history_adjust = _load_historical_outcome(state_hex_key, agent_memory_db)

        final_weight = base_weight + consensus_adjust + m30_fine_tune + history_adjust
        final_weight = max(0.0, min(1.0, final_weight))

        # ── 观察结论 ──
        if final_weight >= 0.7 and m30_resonance:
            conclusion = "strong_observation"
            action = "重点观察"
        elif final_weight >= 0.5 and is_contraction:
            conclusion = "moderate_observation"
            action = "适度观察"
        elif m30_risk or (m30_breakout and not is_contraction):
            conclusion = "risk_warning"
            action = "风险提醒"
        else:
            conclusion = "neutral"
            action = "无特别信号"

        routed.append({
            "stock_code": stock_code,
            "ef_count": ef_count,
            "state_hex": {"MN1": mn1_hex, "W1": w1_hex, "D1": d1_hex},
            "tf_weights": tf_weights,
            "m30_input": {
                "breakout": m30_breakout,
                "risk": m30_risk,
                "score": m30_score,
                "resonance": m30_resonance,
            },
            "contraction_input": {
                "is_contraction": is_contraction,
                "is_extreme": is_extreme,
            },
            "base_weight": round(base_weight, 3),
            "consensus_adjust": round(consensus_adjust, 3),
            "m30_fine_tune": round(m30_fine_tune, 3),
            "history_adjust": round(history_adjust, 3),
            "final_weight": round(final_weight, 3),
            "conclusion": conclusion,
            "action": action,
        })

    # 按 final_weight 排序
    routed.sort(key=lambda x: x["final_weight"], reverse=True)

    # 统计
    strong = sum(1 for r in routed if r["conclusion"] == "strong_observation")
    moderate = sum(1 for r in routed if r["conclusion"] == "moderate_observation")
    risk = sum(1 for r in routed if r["conclusion"] == "risk_warning")

    output = {
        "status": "ok",
        "target_date": target_date,
        "total_routed": len(routed),
        "strong_observation": strong,
        "moderate_observation": moderate,
        "risk_warning": risk,
        "top_candidates": [r for r in routed if r["final_weight"] >= 0.5][:20],
        "all_routed": routed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    print(f"路由完成: {len(routed)} 只")
    print(f"  重点观察: {strong}, 适度观察: {moderate}, 风险提醒: {risk}")

    return output


def main():
    parser = argparse.ArgumentParser(description="Dynamic Weight Router")
    parser.add_argument("--date", required=True, help="目标日期 YYYY-MM-DD")
    parser.add_argument("--state-cube", default="", help="State Cube DB 路径（优先）")
    parser.add_argument("--foundation", default="", help="Foundation DB 路径（回退）")
    parser.add_argument("--debate-json", default="", help="Agent Debate 结果 JSON")
    parser.add_argument("--agent-memory", default="", help="AgentMemory.duckdb 路径")
    parser.add_argument("--user-id", default="system", help="用户 ID")
    parser.add_argument("--output", default="", help="输出 JSON 路径")
    args = parser.parse_args()

    result = route_weights(
        target_date=args.date,
        state_cube_db=args.state_cube,
        foundation_db=args.foundation,
        debate_json=args.debate_json,
        agent_memory_db=args.agent_memory,
        user_id=args.user_id,
    )

    print(f"\n{'='*60}")
    print(f"Top 5 候选:")
    for r in result.get("top_candidates", [])[:5]:
        print(f"  {r['stock_code']}: weight={r['final_weight']}, {r['action']}")

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n已写入: {args.output}")


if __name__ == "__main__":
    main()
