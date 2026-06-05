#!/usr/bin/env python3
"""Agent Debate Runner — 多 Agent 辩论编排器。

Phase 2 核心组件。对 State Cube 中的候选股票，召集多个 Agent 输出结构化意见：
  - contraction_observer: 收缩突破观测
  - m30_observer: M30 盘中精细观察（只做观察，不拍板）
  - risk_guardian: 风险反驳（常驻）
  - market_analyst: 市场环境判断

输出：多 Agent 意见、冲突、共振、权重建议。

Usage:
    python3 scripts/agent_debate_runner.py --date 2026-06-02 --top-n 50
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hermass_platform.agents.contraction_observer import observe_contraction
from hermass_platform.agents.m30_observer import observe_m30_intraday
from hermass_platform.agents.risk_guardian import assess_portfolio_risk
from hermass_platform.agents.base_agent import find_foundation_db


def run_debate(
    target_date: str,
    foundation_db: str = "",
    top_n: int = 50,
    user_id: str = "system",
) -> dict:
    """运行多 Agent 辩论。

    Returns:
        dict: 包含各 Agent 意见、冲突矩阵、共振列表、权重建议
    """
    if not foundation_db:
        db_path = find_foundation_db(target_date)
        foundation_db = str(db_path) if db_path else ""

    if not foundation_db:
        return {"status": "error", "errors": ["无可用 Foundation DB"]}

    print(f"=== Agent Debate: {target_date} ===\n")

    # ── 1. 获取候选池（三周期 E/F 优先） ──
    import duckdb
    con = duckdb.connect(foundation_db, read_only=True)
    candidates = con.execute(f"""
        SELECT stock_code, d1_state_hex, w1_state_hex, mn1_state_hex, ef_count, d1_close
        FROM d1_perspective_state
        WHERE state_date = DATE '{target_date}'
          AND ef_count >= 2
        ORDER BY ef_count DESC, stock_code
        LIMIT {top_n}
    """).fetchdf()
    con.close()

    stock_codes = candidates["stock_code"].tolist() if not candidates.empty else []
    print(f"候选池: {len(stock_codes)} 只 (ef_count >= 2)\n")

    # ── 2. 并行调用各 Agent ──
    results = {}

    # Contraction Observer
    print("[1/4] Contraction Observer 扫描中...")
    try:
        co_result = observe_contraction(
            user_id=user_id, target_date=target_date, foundation_db=foundation_db
        )
        results["contraction_observer"] = co_result
        print(f"  -> 收缩检测完成")
    except Exception as e:
        results["contraction_observer"] = {"status": "error", "errors": [str(e)]}
        print(f"  -> 错误: {e}")

    # M30 Observer（只做观察，不拍板）
    print("[2/4] M30 Observer 精细观察中...")
    try:
        m30_result = observe_m30_intraday(
            user_id=user_id,
            target_date=target_date,
            foundation_db=foundation_db,
            stock_codes=stock_codes,
        )
        results["m30_observer"] = m30_result
        m30_data = m30_result.get("data", {})
        print(f"  -> 突破候选: {m30_data.get('breakout_count', 0)}, 风险: {m30_data.get('risk_count', 0)}")
    except Exception as e:
        results["m30_observer"] = {"status": "error", "errors": [str(e)]}
        print(f"  -> 错误: {e}")

    # Risk Guardian（常驻反驳）
    print("[3/4] Risk Guardian 风险评估中...")
    try:
        rg_result = assess_portfolio_risk(
            user_id=user_id,
            target_date=target_date,
            foundation_db=foundation_db,
            stock_codes=stock_codes,
        )
        results["risk_guardian"] = rg_result
        print(f"  -> 风险评估完成")
    except Exception as e:
        results["risk_guardian"] = {"status": "error", "errors": [str(e)]}
        print(f"  -> 错误: {e}")

    # ── 3. 冲突检测与共振分析 ──
    print("[4/4] 冲突/共振分析中...")
    debate_summary = _analyze_debate(results, stock_codes)
    print(f"  -> 共振: {len(debate_summary['resonance'])}, 冲突: {len(debate_summary['conflicts'])}")

    output = {
        "status": "ok",
        "target_date": target_date,
        "candidate_count": len(stock_codes),
        "agent_results": results,
        "debate_summary": debate_summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    return output


def _analyze_debate(results: dict, stock_codes: list) -> dict:
    """分析 Agent 间的冲突与共振。"""
    resonance = []
    conflicts = []
    neutral = []

    # 提取各 Agent 对每只股票的看法
    m30_data = results.get("m30_observer", {}).get("data", {})
    m30_obs = {o["stock_code"]: o for o in m30_data.get("m30_observations", [])}

    co_data = results.get("contraction_observer", {}).get("data", {})
    co_obs = {o["stock_code"]: o for o in co_data.get("observations", [])}

    for code in stock_codes:
        m30 = m30_obs.get(code, {})
        co = co_obs.get(code, {})

        # 共振：收缩 + M30 突破确认
        if co.get("is_contraction") and m30.get("m30_breakout_confirmed"):
            resonance.append({
                "stock_code": code,
                "type": "contraction_breakout",
                "m30_score": m30.get("score", 0),
                "ef_count": m30.get("ef_count", 0),
                "agents": ["contraction_observer", "m30_observer"],
            })
        # 冲突：收缩但 M30 风险
        elif co.get("is_contraction") and m30.get("m30_risk_flag"):
            conflicts.append({
                "stock_code": code,
                "type": "contraction_vs_risk",
                "m30_score": m30.get("score", 0),
                "ef_count": m30.get("ef_count", 0),
                "agents": ["contraction_observer", "m30_observer"],
            })
        else:
            neutral.append({
                "stock_code": code,
                "m30_score": m30.get("score", 0),
                "ef_count": m30.get("ef_count", 0),
            })

    # 按 M30 score 排序
    resonance.sort(key=lambda x: x["m30_score"], reverse=True)
    conflicts.sort(key=lambda x: x["m30_score"], reverse=True)

    return {
        "resonance": resonance,
        "conflicts": conflicts,
        "neutral": neutral,
        "resonance_count": len(resonance),
        "conflict_count": len(conflicts),
    }


def main():
    parser = argparse.ArgumentParser(description="Agent Debate Runner")
    parser.add_argument("--date", required=True, help="目标日期 YYYY-MM-DD")
    parser.add_argument("--foundation", default="", help="Foundation DB 路径")
    parser.add_argument("--top-n", type=int, default=50, help="候选池大小")
    parser.add_argument("--user-id", default="system", help="用户 ID")
    parser.add_argument("--output", default="", help="输出 JSON 路径")
    args = parser.parse_args()

    result = run_debate(
        target_date=args.date,
        foundation_db=args.foundation,
        top_n=args.top_n,
        user_id=args.user_id,
    )

    print(f"\n{'='*60}")
    print(json.dumps(result["debate_summary"], ensure_ascii=False, indent=2))

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n已写入: {args.output}")


if __name__ == "__main__":
    main()
