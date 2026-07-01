#!/usr/bin/env python3
"""
chain_debate_runner.py — 产业链 Agent 辩论执行器

对 P0 三条产业链分别调用 IndustryChainAgent 生成判断，
同时模拟 RiskAgent 常驻反驳，输出结构化辩论结果。

Usage:
    source .venv/bin/activate && python3 scripts/chain_debate_runner.py --date 2026-06-05
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hermass_platform.agents.industry_chain_agent import analyze_industry_chain

P0_CHAINS = ["ai_compute", "semiconductor", "nev"]
DEBATE_OUTPUT_DIR = ROOT / "outputs" / "chain_debate"


def _risk_agent_rebuttal(chain_id: str, judgment: dict) -> dict[str, Any]:
    """RiskAgent 常驻反驳"""
    risk_flags = judgment.get("risk_flags", [])
    confidence = judgment.get("confidence", 0.5)
    direction = judgment.get("direction", "neutral")

    rebuttals = []
    downgrade = False

    if confidence > 0.8:
        rebuttals.append("置信度过高，可能忽视尾部风险")
        downgrade = True

    if direction == "bullish" and not any("假突破" in f or "过热" in f for f in risk_flags):
        rebuttals.append("多头判断但未检测到假突破风险，建议观察")
        downgrade = True

    if judgment.get("key_states", {}).get("event_count", 0) == 0:
        rebuttals.append("近期无事件驱动，判断可能基于静态数据")

    if len(risk_flags) == 0:
        rebuttals.append("RiskAgent 未标记任何风险，建议复核数据源")

    # 调整后的置信度
    adjusted_confidence = max(0.1, confidence - 0.15) if downgrade else confidence

    return {
        "agent": "risk_guardian",
        "rebuttals": rebuttals,
        "downgrade": downgrade,
        "original_confidence": confidence,
        "adjusted_confidence": round(adjusted_confidence, 2),
    }


def run_debate(state_date: str) -> list[dict]:
    """对 P0 三条链运行辩论"""
    os.makedirs(DEBATE_OUTPUT_DIR, exist_ok=True)
    results = []

    for chain_id in P0_CHAINS:
        print(f"[chain_debate] 分析 {chain_id} ...")
        judgment = analyze_industry_chain(chain_id, state_date)

        if not judgment.get("ok"):
            print(f"  [WARN] {chain_id} 判断失败: {judgment.get('error')}")
            continue

        rebuttal = _risk_agent_rebuttal(chain_id, judgment)

        result = {
            "chain_id": chain_id,
            "state_date": state_date,
            "judgment": judgment,
            "rebuttal": rebuttal,
            "consensus": {
                "direction": judgment["direction"],
                "confidence": rebuttal["adjusted_confidence"],
                "risk_accepted": not rebuttal["downgrade"],
            },
            "timestamp": datetime.now().isoformat(),
        }
        results.append(result)
        print(f"  {chain_id}: {judgment['direction']} (conf={judgment['confidence']}) -> Risk调整后={rebuttal['adjusted_confidence']}")

    # 写入 JSON
    output_path = DEBATE_OUTPUT_DIR / f"chain_debate_{state_date.replace('-', '')}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "state_date": state_date,
            "chains": P0_CHAINS,
            "results": results,
            "generated_at": datetime.now().isoformat(),
        }, f, ensure_ascii=False, indent=2)
    print(f"[chain_debate] 已写入: {output_path}")

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="产业链 Agent 辩论执行器")
    parser.add_argument("--date", type=str, help="日期 YYYY-MM-DD")
    args = parser.parse_args()

    state_date = args.date or str(date.today())
    print(f"[chain_debate] 日期: {state_date}")

    results = run_debate(state_date)
    print(f"[chain_debate] 完成: {len(results)} 条产业链")
    return 0


if __name__ == "__main__":
    sys.exit(main())
