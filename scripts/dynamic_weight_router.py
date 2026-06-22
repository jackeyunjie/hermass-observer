"""Dynamic Weight Router — transforms 6 agent opinions into weighted conclusion.

Phase 2 MOE architecture: reads agent_debate_latest.json, computes:
- Dynamic weights: per-agent weight based on market regime fit
- Conflicts: where agents disagree with >1 color gap
- Resonances: where multiple agents align on same color
- Final verdict: weighted composite with risk adjustment

Rule-based (no LLM), intended to be run after agent_debate_runner.py.
"""
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEBATE_JSON = ROOT / "outputs" / "debate" / "agent_debate_latest.json"


def _verdict_score(verdict_color: str) -> float:
    """Convert color to numeric score: green=1.0, yellow=0.5, red=0.0"""
    return {"green": 1.0, "yellow": 0.5, "red": 0.0}.get(verdict_color, 0.5)


def _verdict_severity(verdict_color: str) -> float:
    """How severe the verdict is — used for conflict weighting"""
    return {"green": 0.7, "yellow": 0.5, "red": 0.3}.get(verdict_color, 0.5)


def compute_weights(opinions: list[dict], market: dict) -> dict[str, float]:
    """Dynamic weight allocation based on market regime.

    Base weights are market-condition aware:
    - In strong trend → trend agent weight ↑
    - In high momentum → momentum agent weight ↑
    - In high volatility → volatility + risk weights ↑
    - In extreme risk → risk agent gets near-veto weight
    """
    base_weights = {
        "市场 Agent": 15,
        "趋势 Agent": 20,
        "动量 Agent": 18,
        "波动率 Agent": 15,
        "边界 Agent": 12,
        "风险 Agent": 20,
    }

    # Trend adjustment
    if market["avg_w1_adx"] >= 35:
        base_weights["趋势 Agent"] += 5
    if market["ef2_count"] >= 500:
        base_weights["趋势 Agent"] += 3

    # Momentum adjustment
    if market["avg_d1_adx"] >= 35 and market["d1_bull_pct"] >= 50:
        base_weights["动量 Agent"] += 5
    if market["strong_momentum"] >= 500:
        base_weights["动量 Agent"] += 3

    # Volatility / risk adjustment
    bb_extreme = market["d1_above_bb"] + market["d1_below_bb"]
    if bb_extreme >= 500:
        base_weights["波动率 Agent"] += 3
        base_weights["风险 Agent"] += 3
    if market["extreme_adx"] >= 100:
        base_weights["风险 Agent"] += 5

    # Normalize to sum 100
    total = sum(base_weights.values())
    return {k: round(v / total * 100, 1) for k, v in base_weights.items()}


def detect_conflicts(opinions: list[dict]) -> list[dict]:
    """Detect pairwise conflicts between agents with >1 color gap."""
    color_order = {"green": 0, "yellow": 1, "red": 2}
    conflicts = []

    for i in range(len(opinions)):
        for j in range(i + 1, len(opinions)):
            a, b = opinions[i], opinions[j]
            gap = abs(color_order.get(a["verdict_color"], 1) -
                      color_order.get(b["verdict_color"], 1))
            if gap >= 2:
                # green vs red — significant conflict
                conflicts.append({
                    "agent_a": a["agent"],
                    "agent_b": b["agent"],
                    "verdict_a": a["verdict"],
                    "verdict_b": b["verdict"],
                    "color_a": a["verdict_color"],
                    "color_b": b["verdict_color"],
                    "severity": "高" if gap == 2 else "中",
                    "description": (
                        f"{a['agent']}（{a['verdict']}）vs "
                        f"{b['agent']}（{b['verdict']}）：方向相反，需要特别注意"
                    ),
                })
    return conflicts


def detect_resonances(opinions: list[dict]) -> list[dict]:
    """Detect where multiple agents align on same verdict color."""
    color_groups: dict[str, list[str]] = {}
    for op in opinions:
        color_groups.setdefault(op["verdict_color"], []).append(op["agent"])

    resonances = []
    for color, agents in color_groups.items():
        if len(agents) >= 2:
            label = {"green": "正向共振", "yellow": "观望共振", "red": "风险共振"}.get(color, "共振")
            resonances.append({
                "color": color,
                "agents": agents,
                "count": len(agents),
                "label": label,
                "description": (
                    f"{len(agents)} 个 Agent 达成{label}：{'、'.join(agents)}"
                ),
            })

    return sorted(resonances, key=lambda r: -r["count"])


def compute_final_verdict(opinions: list[dict], weights: dict[str, float],
                          conflicts: list[dict], resonances: list[dict],
                          market: dict | None = None) -> dict:
    """Weighted composite conclusion with direct market scoring.

    Blends agent-weighted score (40%) with direct market momentum score (60%)
    to produce more discriminative ratings. The direct score uses raw market
    aggregates (not agent opinions) to avoid the "all agents agree = narrow band" problem.
    """
    # Agent-weighted score
    weighted_score = 0.0
    total_weight = 0.0
    for op in opinions:
        w = weights.get(op["agent"], 15)
        s = _verdict_score(op["verdict_color"])
        weighted_score += w * s
        total_weight += w

    agent_score = round(weighted_score / total_weight, 2) if total_weight > 0 else 0.5

    # Collect risk signals from all agents
    all_risks = [op["risk"] for op in opinions if op["verdict_color"] == "red"]

    # Adjust for conflicts and resonances
    conflict_penalty = len([c for c in conflicts if c["severity"] == "高"]) * 0.05
    resonance_bonus = sum(
        0.03 for r in resonances if r["color"] == "green"
    ) - sum(
        0.03 for r in resonances if r["color"] == "red"
    )

    agent_adjusted = max(0.05, min(0.95, agent_score - conflict_penalty + resonance_bonus))

    # Direct market score from raw aggregates (0-1 scale)
    direct_score = 0.5
    if market:
        total_stocks = max(market.get("total_stocks", 1), 1)
        ef2_pct = market.get("ef2_count", 0) / total_stocks
        bull_pct = market.get("d1_bull_pct", 50) / 100
        adx_norm = min(market.get("avg_d1_adx", 20) / 50, 1.0)  # 0-1, ADX 50 = max
        bb_ratio = 1.0 - min((market.get("d1_above_bb", 0) + market.get("d1_below_bb", 0)) / max(total_stocks, 1), 0.5)

        # Strong momentum + high EF coverage = bullish
        momentum = (bull_pct * 0.5 + adx_norm * 0.3 + ef2_pct * 15 * 0.2)
        # Extreme BB positions = cautious
        extreme_penalty = (market.get("d1_above_bb", 0) + market.get("d1_below_bb", 0)) / max(total_stocks, 1) * 0.3
        # Risk signals
        risk_deduction = 0.0
        if market.get("extreme_adx", 0) >= 5: risk_deduction += 0.05
        if market.get("fake_breakout", 0) >= 5: risk_deduction += 0.05
        if market.get("mn1_weak_ef2", 0) >= 20: risk_deduction += 0.03

        direct_score = max(0.05, min(0.95, momentum - extreme_penalty - risk_deduction))

    # Blend: 60% direct market score + 40% agent consensus
    blended_score = round(direct_score * 0.6 + agent_adjusted * 0.4, 2)

    # Thresholds calibrated against 54-day market observation ledger:
    # - ≥0.50: 56.5% 5-day win rate, avg +0.80% (23 samples)
    # - <0.30: historically contrarian during down markets
    if blended_score >= 0.50:
        final_verdict = "偏多操作"
        final_color = "green"
    elif blended_score >= 0.30:
        final_verdict = "谨慎中性"
        final_color = "yellow"
    else:
        final_verdict = "观望/防御"
        final_color = "red"

    # Build summary
    summary_parts = [f"加权评分 {blended_score:.2f}（Agent {agent_adjusted:.2f} / 市场 {direct_score:.2f}）"]
    if conflicts:
        summary_parts.append(f"{len(conflicts)} 组 Agent 冲突")
    if resonances:
        summary_parts.append(f"{len(resonances)} 组共振")
    if all_risks:
        summary_parts.append(f"{len(all_risks)} 个风险警告")

    return {
        "raw_score": agent_score,
        "adjusted_score": blended_score,
        "agent_score": agent_adjusted,
        "market_direct_score": direct_score,
        "conflict_penalty": round(conflict_penalty, 2),
        "resonance_adjustment": round(resonance_bonus, 2),
        "final_verdict": final_verdict,
        "final_color": final_color,
        "summary": " · ".join(summary_parts),
        "decision": (
            "6个Agent加权综合评分偏多，可维持现有观察仓位"
            if final_color == "green"
            else (
                "信号分歧较大，建议降低仓位等待共振信号出现"
                if final_color == "red"
                else "当前市场方向不明，建议小仓位试探或观望"
            )
        ),
        "top_risks": all_risks[:2] if all_risks else ["无系统性风险信号"],
    }


def main(debate_data: dict = None) -> dict:
    if debate_data is None:
        if not DEBATE_JSON.exists():
            return {"error": "agent_debate_latest.json 不存在，请先运行 agent_debate_runner.py"}
        debate = json.loads(DEBATE_JSON.read_text(encoding="utf-8"))
    else:
        debate = debate_data

    opinions = debate.get("opinions", [])
    market = debate.get("market_summary", {})

    weights = compute_weights(opinions, market)
    conflicts = detect_conflicts(opinions)
    resonances = detect_resonances(opinions)
    verdict = compute_final_verdict(opinions, weights, conflicts, resonances, market=market)

    result = {
        "generated_at": date.today().isoformat(),
        "weights": weights,
        "conflicts": conflicts,
        "resonances": resonances,
        "verdict": verdict,
    }

    print(f"[OK] Router — {len(conflicts)} conflicts, {len(resonances)} resonances, "
          f"verdict={verdict['final_verdict']} (score={verdict['adjusted_score']:.2f})")
    return result


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))
