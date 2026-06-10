#!/usr/bin/env python3
"""SerenityChainAnalyzer — 产业链 Serenity 式瓶颈分析 Agent。

职责：
  1. 读取产业链动态数据（chain_studio 系列表）
  2. 按 Serenity 方法论对产业链节点做稀缺层打分
  3. 运行 serenity scorecard，输出瓶颈排序、证据强度、风险边界
  4. 写入 AgentMemory.duckdb 和 Markdown 报告

用法：
  from hermass_platform.agents.serenity_chain_analyzer import analyze_serenity_chain
  result = analyze_serenity_chain(chain_id="ai_compute", state_date="2026-06-05")
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# Handle both module import and direct script execution
try:
    from .base_agent import find_foundation_db
except ImportError:
    sys.path.insert(0, str(ROOT))
    from hermass_platform.agents.base_agent import find_foundation_db

import duckdb

log = logging.getLogger("serenity_chain_analyzer")

AGENT_ID = "serenity_chain_analyzer"
AGENT_NAME = "产业链瓶颈分析器"

CHAIN_DB = ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"
STATE_CUBE_DB = ROOT / "outputs" / "state_cube" / "state_cube.duckdb"
AGENT_MEMORY_DB = ROOT / "outputs" / "agent_memory" / "AgentMemory.duckdb"
SERENITY_SKILL = ROOT / "config" / "skills" / "serenity-skill"

P0_CHAINS = {"ai_compute", "semiconductor", "nev"}


def _ensure_judgments_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS agent_judgments (
            agent_id         VARCHAR NOT NULL,
            judgment_id      VARCHAR PRIMARY KEY,
            judgment_date    DATE NOT NULL,
            judgment_type    VARCHAR NOT NULL,
            judgment_content JSON,
            confidence       DOUBLE,
            factors_used     JSON,
            context_snapshot JSON
        )
    """)
    # 向后兼容：确保列存在（不同 agent 可能先创建表）
    for col, typ in [
        ("agent_id", "VARCHAR"),
        ("judgment_id", "VARCHAR"),
        ("judgment_date", "DATE"),
        ("judgment_type", "VARCHAR"),
        ("judgment_content", "JSON"),
        ("confidence", "DOUBLE"),
        ("factors_used", "JSON"),
        ("context_snapshot", "JSON"),
    ]:
        try:
            con.execute(f'ALTER TABLE agent_judgments ADD COLUMN IF NOT EXISTS "{col}" {typ}')
        except Exception as exc:
            log.warning(f"ALTER TABLE 补列失败 {col}: {exc}")


def _load_chain_overview(chain_id: str, state_date: str) -> dict[str, Any] | None:
    if not CHAIN_DB.exists():
        return None
    con = duckdb.connect(str(CHAIN_DB), read_only=True)
    row = con.execute("""
        SELECT prosperity_score, regime, event_count, lead_node, lag_node
        FROM chain_studio_overview
        WHERE chain_id = ? AND state_date = ?
    """, [chain_id, state_date]).fetchone()
    con.close()
    if not row:
        return None
    return {
        "prosperity_score": row[0],
        "regime": row[1],
        "event_count": row[2],
        "lead_node": row[3],
        "lag_node": row[4],
    }


def _load_chain_nodes(chain_id: str, state_date: str) -> list[dict[str, Any]]:
    if not CHAIN_DB.exists():
        return []
    con = duckdb.connect(str(CHAIN_DB), read_only=True)
    rows = con.execute("""
        SELECT node_id, node_name, fund_flow_score, position_score, momentum_score, state_hex
        FROM chain_studio_nodes
        WHERE chain_id = ? AND state_date = ?
        ORDER BY node_id
    """, [chain_id, state_date]).fetchall()
    con.close()
    return [
        {
            "node_id": r[0],
            "node_name": r[1],
            "fund_flow_score": r[2] or 0,
            "position_score": r[3] or 0,
            "momentum_score": r[4] or 0,
            "state_hex": r[5] or "",
        }
        for r in rows
    ]


def _load_chain_events(chain_id: str, state_date: str) -> list[dict[str, Any]]:
    if not CHAIN_DB.exists():
        return []
    con = duckdb.connect(str(CHAIN_DB), read_only=True)
    rows = con.execute("""
        SELECT event_type, event_source, impact_score, description
        FROM chain_studio_events
        WHERE chain_id = ? AND state_date = ?
        ORDER BY impact_score DESC
        LIMIT 20
    """, [chain_id, state_date]).fetchall()
    con.close()
    return [
        {"event_type": r[0], "event_source": r[1], "impact_score": r[2] or 0, "description": r[3]}
        for r in rows
    ]


def _load_node_stocks(node_id: str, chain_id: str, state_date: str) -> list[dict[str, Any]]:
    """读取某节点下的成分股状态"""
    # 先从产业链库读取候选股
    stock_codes = []
    if CHAIN_DB.exists():
        con = duckdb.connect(str(CHAIN_DB), read_only=True)
        rows = con.execute("""
            SELECT DISTINCT stock_code
            FROM chain_studio_candidates
            WHERE chain_id = ? AND node_id = ? AND state_date = ?
        """, [chain_id, node_id, state_date]).fetchall()
        con.close()
        stock_codes = [r[0] for r in rows if r[0]]

    if not stock_codes or not STATE_CUBE_DB.exists():
        return []

    # 参数化查询：DuckDB 不支持列表参数，用 unnest 构造临时表
    con = duckdb.connect(str(STATE_CUBE_DB), read_only=True)
    rows = con.execute("""
        SELECT sc.stock_code, sc.d1_state_hex, sc.w1_state_hex, sc.ef_count, sc.future_r5, sc.future_r20
        FROM state_cube AS sc
        INNER JOIN (SELECT UNNEST(?::VARCHAR[]) AS stock_code) AS codes ON sc.stock_code = codes.stock_code
        WHERE sc.state_date = ?
        LIMIT 50
    """, [stock_codes[:50], state_date]).fetchall()
    con.close()
    return [
        {
            "stock_code": r[0],
            "d1_state_hex": r[1],
            "w1_state_hex": r[2],
            "ef_count": r[3] or 0,
            "future_r5": r[4],
            "future_r20": r[5],
        }
        for r in rows
    ]


def _derive_serenity_factors(node: dict[str, Any], events: list[dict], stocks: list[dict]) -> dict[str, float]:
    """从本地数据推导 Serenity scorecard 8 个因子（0-5 分）"""
    ff = node.get("fund_flow_score", 0) or 0
    pos = node.get("position_score", 0) or 0
    mom = node.get("momentum_score", 0) or 0
    state_hex = node.get("state_hex", "")

    # 需求拐点：资金流得分映射
    demand_inflection = min(5.0, max(0.0, ff / 20.0))

    # 架构耦合：位置得分越高越接近瓶颈（耦合强）
    architecture_coupling = min(5.0, max(0.0, pos / 20.0))

    # 卡点严重程度：位置得分 + 状态
    chokepoint_severity = min(5.0, max(0.0, pos / 20.0 + (1.0 if "E" in state_hex or "F" in state_hex else 0)))

    # 供应商集中度：基于成分股数量反向推断（股越少越集中）
    stock_count = len(stocks)
    if stock_count <= 3:
        supplier_concentration = 4.5
    elif stock_count <= 8:
        supplier_concentration = 3.5
    elif stock_count <= 15:
        supplier_concentration = 2.5
    else:
        supplier_concentration = 1.5

    # 扩产难度：基于技术状态（收缩态难扩产）
    expansion_difficulty = 2.5
    if state_hex.startswith("C") or state_hex.startswith("D"):
        expansion_difficulty = 4.0
    elif state_hex.startswith("A") or state_hex.startswith("B"):
        expansion_difficulty = 2.0

    # 证据质量：事件数量和影响分
    ev_count = len(events)
    ev_impact = sum(e.get("impact_score", 0) for e in events) / max(1, ev_count)
    evidence_quality = min(5.0, max(0.0, ev_count / 4.0 + ev_impact / 30.0))

    # 估值偏离：基于 future_r5 / future_r20 的平均（值越大可能偏离越大）
    valid_returns = [s["future_r5"] for s in stocks if s.get("future_r5") is not None]
    if valid_returns:
        avg_r5 = sum(valid_returns) / len(valid_returns)
        valuation_disconnect = min(5.0, max(0.0, abs(avg_r5) / 10.0))
    else:
        valuation_disconnect = 2.5

    # 催化剂时点：动量得分
    catalyst_timing = min(5.0, max(0.0, mom / 20.0))

    return {
        "demand_inflection": round(demand_inflection, 1),
        "architecture_coupling": round(architecture_coupling, 1),
        "chokepoint_severity": round(chokepoint_severity, 1),
        "supplier_concentration": round(supplier_concentration, 1),
        "expansion_difficulty": round(expansion_difficulty, 1),
        "evidence_quality": round(evidence_quality, 1),
        "valuation_disconnect": round(valuation_disconnect, 1),
        "catalyst_timing": round(catalyst_timing, 1),
    }


def _derive_penalties(node: dict[str, Any], stocks: list[dict]) -> dict[str, float]:
    """从本地数据推导惩罚项（0-5 分）"""
    state_hex = node.get("state_hex", "")

    # 炒作风险：动量极高但状态收缩
    mom = node.get("momentum_score", 0) or 0
    hype_risk = 0.0
    if mom > 80 and ("C" in state_hex or "D" in state_hex):
        hype_risk = 3.0
    elif mom > 60:
        hype_risk = 1.5

    # 周期性：状态频繁变化暗示高周期
    cyclicality = 1.5

    # 替代设计风险：无明显信号，默认中等
    alternative_design_risk = 2.0

    return {
        "dilution_financing": 0.0,
        "governance": 0.0,
        "geopolitics": 1.0,  # 科技产业链默认低 geopolitics 风险
        "liquidity": 0.0,
        "hype_risk": round(hype_risk, 1),
        "accounting_quality": 0.0,
        "cyclicality": round(cyclicality, 1),
        "alternative_design_risk": round(alternative_design_risk, 1),
    }


def _run_scorecard(factors: dict[str, float], penalties: dict[str, float], meta: dict[str, Any]) -> dict[str, Any]:
    """调用本地 serenity scorecard 脚本计算"""
    import subprocess

    payload = {
        "ticker": meta.get("node_id", "NODE"),
        "company": meta.get("node_name", "Unknown"),
        "market": "A-share",
        "factors": factors,
        "penalties": penalties,
        "evidence": meta.get("evidence", []),
        "what_could_weaken_view": meta.get("kill_switches", []),
    }

    scorecard_script = SERENITY_SKILL / "scripts" / "serenity_scorecard.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(scorecard_script), "-", "--format", "json"],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=10,
        )
        result = json.loads(proc.stdout)
    except Exception as exc:
        log.warning(f"Scorecard 计算失败: {exc}; 使用本地 fallback")
        result = _local_score_fallback(factors, penalties, meta)

    return result


def _local_score_fallback(factors: dict[str, float], penalties: dict[str, float], meta: dict[str, Any]) -> dict[str, Any]:
    """当 serenity_scorecard.py 不可用时本地计算"""
    WEIGHTS = {
        "demand_inflection": 15,
        "architecture_coupling": 10,
        "chokepoint_severity": 15,
        "supplier_concentration": 12,
        "expansion_difficulty": 12,
        "evidence_quality": 15,
        "valuation_disconnect": 11,
        "catalyst_timing": 10,
    }
    PENALTY_MULTIPLIER = 2.0

    total = sum((factors.get(k, 0) / 5.0 * w) for k, w in WEIGHTS.items())
    penalty_total = sum((penalties.get(k, 0) * PENALTY_MULTIPLIER) for k in penalties)
    final_score = max(0.0, min(100.0, total - penalty_total))

    if final_score >= 85:
        verdict = "Top research priority"
    elif final_score >= 70:
        verdict = "High research priority"
    elif final_score >= 55:
        verdict = "Worth tracking"
    else:
        verdict = "Early lead or low priority"

    return {
        "ticker": meta.get("node_id", "NODE"),
        "company": meta.get("node_name", "Unknown"),
        "market": "A-share",
        "raw_factor_points": round(total, 2),
        "penalty_points": round(penalty_total, 2),
        "final_score": round(final_score, 2),
        "verdict": verdict,
        "factor_details": {k: {"rating": factors.get(k, 0), "weight": WEIGHTS[k], "points": round(factors.get(k, 0) / 5.0 * WEIGHTS[k], 2)} for k in WEIGHTS},
        "penalty_details": {k: {"rating": penalties.get(k, 0), "points": round(penalties.get(k, 0) * PENALTY_MULTIPLIER, 2)} for k in penalties},
        "kill_switches": meta.get("kill_switches", []),
        "evidence": meta.get("evidence", []),
    }


def analyze_serenity_chain(chain_id: str, state_date: str | None = None) -> dict[str, Any]:
    """对单条产业链运行 Serenity 式瓶颈分析"""
    if chain_id not in P0_CHAINS:
        return {"ok": False, "error": f"不支持的产业链: {chain_id}"}

    if state_date is None:
        state_date = str(date.today())

    overview = _load_chain_overview(chain_id, state_date)
    if not overview:
        return {"ok": False, "error": f"未找到 {chain_id} 在 {state_date} 的数据"}

    nodes = _load_chain_nodes(chain_id, state_date)
    events = _load_chain_events(chain_id, state_date)

    node_scores = []
    for node in nodes:
        node_id = node["node_id"]
        node_name = node["node_name"]
        stocks = _load_node_stocks(node_id, chain_id, state_date)
        node_events = [e for e in events if node_name in (e.get("description") or "")]

        factors = _derive_serenity_factors(node, node_events, stocks)
        penalties = _derive_penalties(node, stocks)

        meta = {
            "node_id": node_id,
            "node_name": node_name,
            "evidence": [
                {"claim": e.get("description", ""), "source": e.get("event_source", ""), "strength": "primary" if e.get("impact_score", 0) >= 50 else "media"}
                for e in node_events[:3]
            ],
            "kill_switches": [
                "需求不及预期",
                "扩产速度超预期缓解瓶颈",
                "技术路线变更导致节点贬值",
            ],
        }

        score_result = _run_scorecard(factors, penalties, meta)
        node_scores.append({
            "node_id": node_id,
            "node_name": node_name,
            "score": score_result["final_score"],
            "verdict": score_result["verdict"],
            "factors": factors,
            "penalties": penalties,
            "detail": score_result,
            "stock_count": len(stocks),
        })

    # 按 score 降序排列
    node_scores.sort(key=lambda x: x["score"], reverse=True)

    # 稀缺层判断
    scarce_layers = [n["node_name"] for n in node_scores if n["score"] >= 70]
    popular_downgrades = [n["node_name"] for n in node_scores if n["score"] < 55 and n["node_name"] in (overview.get("lead_node", ""), overview.get("lag_node", ""))]

    report = {
        "ok": True,
        "agent": AGENT_ID,
        "chain_id": chain_id,
        "state_date": state_date,
        "overview": overview,
        "scarce_layers": scarce_layers,
        "popular_downgrades": popular_downgrades,
        "node_ranking": node_scores,
        "risk_boundary": {
            "max_hype_node": max(node_scores, key=lambda x: x["penalties"].get("hype_risk", 0))["node_name"] if node_scores else "-",
            "min_evidence_node": min(node_scores, key=lambda x: x["factors"].get("evidence_quality", 0))["node_name"] if node_scores else "-",
        },
        "timestamp": datetime.now().isoformat(),
    }

    # 写入 AgentMemory
    try:
        con = duckdb.connect(str(AGENT_MEMORY_DB))
        _ensure_judgments_table(con)
        judgment_id = str(uuid.uuid4())
        con.execute("""
            INSERT INTO agent_judgments
            (agent_id, judgment_id, judgment_date, judgment_type,
             judgment_content, confidence, factors_used, context_snapshot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            AGENT_ID, judgment_id, state_date, "serenity_chain",
            json.dumps(report, ensure_ascii=False),
            round(max((n["score"] for n in node_scores), default=0) / 100, 2),
            json.dumps({"data_sources": ["chain_studio", "state_cube", "serenity_scorecard"], "version": "1.0"}, ensure_ascii=False),
            json.dumps({"chain_id": chain_id, "state_date": state_date}, ensure_ascii=False),
        ))
        con.commit()
        con.close()
        report["judgment_id"] = judgment_id
        report["written_to_memory"] = True
    except Exception as exc:
        log.warning(f"写入 AgentMemory 失败: {exc}")
        report["written_to_memory"] = False

    # 写 Markdown 报告
    try:
        report_dir = ROOT / "outputs" / "industry_chain" / "serenity_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        md_path = report_dir / f"serenity_{chain_id}_{state_date}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(_to_markdown_report(report))
        report["report_path"] = str(md_path)
    except Exception as exc:
        log.warning(f"写 Markdown 报告失败: {exc}")

    return report


def _to_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        f"# Serenity 产业链瓶颈分析：{report['chain_id']}（{report['state_date']}）",
        "",
        f"> Agent: {report['agent']} | 生成时间: {report['timestamp']}",
        "",
        "## 稀缺层排序（Score >= 70）",
    ]
    if report.get("scarce_layers"):
        for layer in report["scarce_layers"]:
            lines.append(f"- **{layer}**")
    else:
        lines.append("- 暂无明确稀缺层")

    lines.extend(["", "## 节点瓶颈打分排名"])
    lines.append("| 排名 | 节点 | Score | Verdict | 股数 | 需求拐点 | 卡点严重 | 扩产难度 | 证据质量 | 催化剂 |")
    lines.append("|-----:|------|------:|---------|------:|---------:|---------:|---------:|---------:|---------:|")
    for idx, node in enumerate(report.get("node_ranking", []), 1):
        f = node["factors"]
        lines.append(
            f"| {idx} | {node['node_name']} | {node['score']} | {node['verdict']} | {node['stock_count']} | "
            f"{f['demand_inflection']} | {f['chokepoint_severity']} | {f['expansion_difficulty']} | "
            f"{f['evidence_quality']} | {f['catalyst_timing']} |"
        )

    lines.extend(["", "## 风险提示"])
    rb = report.get("risk_boundary", {})
    lines.append(f"- 炒作风险最高节点：**{rb.get('max_hype_node', '-')}**")
    lines.append(f"- 证据最薄弱节点：**{rb.get('min_evidence_node', '-')}**")

    if report.get("popular_downgrades"):
        lines.extend(["", "## 热门方向降级观察"])
        for name in report["popular_downgrades"]:
            lines.append(f"- {name}：市场关注度高，但瓶颈打分偏低，需更多证据支撑。")

    lines.extend(["", "## 下一步检查建议"])
    lines.append("1. 核查稀缺层节点的最新财报中关键业务收入与毛利率变化。")
    lines.append("2. 核查高炒作风险节点的订单/产能/客户认证公告。")
    lines.append("3. 核查证据薄弱节点的行业招投标、环评/能评、专利进展。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Serenity 产业链瓶颈分析 Agent")
    parser.add_argument("--chain", type=str, required=True, help="产业链 ID")
    parser.add_argument("--date", type=str, help="日期 YYYY-MM-DD")
    args = parser.parse_args()

    result = analyze_serenity_chain(args.chain, args.date)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
