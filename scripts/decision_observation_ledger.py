#!/usr/bin/env python3
"""
decision_observation_ledger.py — 决策观察账本

读取 dynamic_weight_router 的输出，将观察结论写入：
- AgentMemory.duckdb (agent_judgments 表)
- outputs/observation_ledger/ 本地 JSON 备份
- outputs/decision_observation/decision_observation.duckdb (hypothesis 验证闭环)

Usage:
    source .venv/bin/activate && python3 scripts/decision_observation_ledger.py --date 2026-06-05
    source .venv/bin/activate && python3 scripts/decision_observation_ledger.py write --date 2026-06-05 --hypothesis D1_CONTRACTION_BREAKOUT_OBSERVATION
    source .venv/bin/activate && python3 scripts/decision_observation_ledger.py backfill --as-of 2026-06-05 --hypothesis D1_CONTRACTION_BREAKOUT_OBSERVATION
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_MEMORY_DB = PROJECT_ROOT / "outputs" / "agent_memory" / "AgentMemory.duckdb"
ROUTER_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "router"
DEBATE_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "debate"
LEDGER_DIR = PROJECT_ROOT / "outputs" / "observation_ledger"
DECISION_OBSERVATION_DB = PROJECT_ROOT / "outputs" / "decision_observation" / "decision_observation.duckdb"
STATE_CUBE_DB = PROJECT_ROOT / "outputs" / "state_cube" / "state_cube.duckdb"


def _resolve_date(args_date: str | None) -> date:
    if args_date:
        return date.fromisoformat(args_date)
    return date.today()


def _router_candidate_paths(as_of_date: date, hypothesis_id: str = "") -> list[Path]:
    ymd = as_of_date.strftime("%Y%m%d")
    # New format first (hypothesis-specific)
    if hypothesis_id:
        exact = [
            ROUTER_OUTPUT_DIR / f"{hypothesis_id}_{ymd}_router.json",
            ROUTER_OUTPUT_DIR / f"router_{hypothesis_id}_{ymd}.json",
        ]
    else:
        exact = []
    # Legacy fallback
    exact.extend([
        ROUTER_OUTPUT_DIR / f"router_decisions_{ymd}.json",
        ROUTER_OUTPUT_DIR / f"router_{ymd}.json",
        PROJECT_ROOT / "outputs" / "debate" / f"router_{ymd}.json",
    ])
    dated = list(ROUTER_OUTPUT_DIR.glob(f"router*{ymd}*.json"))
    dated.extend((PROJECT_ROOT / "outputs" / "debate").glob(f"router*{ymd}*.json"))
    if hypothesis_id:
        dated.extend(ROUTER_OUTPUT_DIR.glob(f"{hypothesis_id}*{ymd}*.json"))
        dated.extend(DEBATE_OUTPUT_DIR.glob(f"{hypothesis_id}*{ymd}*.json"))

    seen: set[Path] = set()
    paths: list[Path] = []
    for path in exact + sorted(dated, key=lambda p: p.stat().st_mtime, reverse=True):
        if path.exists() and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def _debate_candidate_paths(as_of_date: date, hypothesis_id: str = "") -> list[Path]:
    ymd = as_of_date.strftime("%Y%m%d")
    if hypothesis_id:
        exact = [
            DEBATE_OUTPUT_DIR / f"{hypothesis_id}_{ymd}_debate.json",
            DEBATE_OUTPUT_DIR / f"debate_{hypothesis_id}_{ymd}.json",
        ]
    else:
        exact = []
    exact.extend([
        DEBATE_OUTPUT_DIR / f"debate_{ymd}.json",
        DEBATE_OUTPUT_DIR / f"router_{ymd}.json",
    ])
    dated = list(DEBATE_OUTPUT_DIR.glob(f"debate*{ymd}*.json"))
    if hypothesis_id:
        dated.extend(DEBATE_OUTPUT_DIR.glob(f"{hypothesis_id}*{ymd}*.json"))

    seen: set[Path] = set()
    paths: list[Path] = []
    for path in exact + sorted(dated, key=lambda p: p.stat().st_mtime, reverse=True):
        if path.exists() and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def _load_router_output(as_of_date: date, stock_code: str = "", hypothesis_id: str = "") -> Any | None:
    """读取 Router 当天的 JSON 输出"""
    for candidate in _router_candidate_paths(as_of_date, hypothesis_id=hypothesis_id):
        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not stock_code:
                return data
            records = normalize_router_records(data, as_of_date)
            if any(r.get("stock_code") == stock_code for r in records):
                return data

    # fallback: 最新文件
    files = sorted(ROUTER_OUTPUT_DIR.glob("router*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if files:
        with open(files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
        if not stock_code:
            return data
        records = normalize_router_records(data, as_of_date)
        if any(r.get("stock_code") == stock_code for r in records):
            return data
    return None


def _load_debate_output(as_of_date: date, hypothesis_id: str = "") -> Any | None:
    """读取 Debate 当天的 JSON 输出"""
    for candidate in _debate_candidate_paths(as_of_date, hypothesis_id=hypothesis_id):
        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as f:
                return json.load(f)
    return None


def _ensure_agent_memory_schema(con: duckdb.DuckDBPyConnection) -> None:
    """确保 agent_judgments 表存在（复用现有 Hermass Schema）"""
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
    con.execute("CREATE INDEX IF NOT EXISTS idx_aj_agent ON agent_judgments(agent_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_aj_date ON agent_judgments(judgment_date)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_aj_type ON agent_judgments(judgment_type)")


def _ensure_decision_observation_schema(con: duckdb.DuckDBPyConnection) -> None:
    """确保 decision_observation 表存在"""
    con.execute("""
        CREATE TABLE IF NOT EXISTS decision_observation (
            observation_id VARCHAR PRIMARY KEY,
            hypothesis_id VARCHAR NOT NULL,
            stock_code VARCHAR NOT NULL,
            state_date DATE NOT NULL,
            agent_debate_json JSON,
            router_json JSON,
            final_label VARCHAR,
            final_score DOUBLE,
            risk_veto BOOLEAN,
            future_r5 DOUBLE,
            future_r20 DOUBLE,
            outcome_label VARCHAR,
            review_status VARCHAR DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_do_hypothesis ON decision_observation(hypothesis_id, state_date)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_do_stock ON decision_observation(stock_code, state_date)")


def _risk_flags_from_route(route: dict[str, Any]) -> list[str]:
    flags = route.get("risk_flags", [])
    if isinstance(flags, dict):
        return [str(k) for k, v in flags.items() if v]
    if isinstance(flags, list):
        return [str(v) for v in flags if v]
    return [str(flags)] if flags else []


def _route_rationale(route: dict[str, Any]) -> str:
    action = route.get("action") or route.get("direction") or "观察"
    final_weight = route.get("final_weight")
    consensus = route.get("agent_consensus", {}) if isinstance(route.get("agent_consensus"), dict) else {}
    support = ",".join(consensus.get("support_agents", []) or [])
    oppose = ",".join(consensus.get("oppose_agents", []) or [])
    parts = [str(action)]
    if final_weight is not None:
        parts.append(f"final_weight={final_weight}")
    if support:
        parts.append(f"support={support}")
    if oppose:
        parts.append(f"oppose={oppose}")
    return "；".join(parts)


def _normalize_route_record(route: dict[str, Any], as_of_date: date) -> dict[str, Any]:
    stock_code = route.get("stock_code")
    chain_id = route.get("chain_id") or (route.get("context", {}) or {}).get("chain_id")
    conclusion = route.get("conclusion") or route.get("direction") or route.get("final_label") or "neutral"
    confidence = route.get("final_weight", route.get("confidence", 0.5))
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except Exception:
        confidence = 0.5

    judgment_type = route.get("judgment_type")
    if not judgment_type:
        judgment_type = "industry_chain" if chain_id and not stock_code else "decision_observation"

    return {
        "agent": route.get("agent") or route.get("agent_id") or "DynamicWeightRouter",
        "judgment_type": judgment_type,
        "stock_code": stock_code,
        "chain_id": chain_id,
        "state_date": str(route.get("state_date") or as_of_date),
        "direction": conclusion,
        "confidence": confidence,
        "rationale": route.get("rationale") or _route_rationale(route),
        "risk_flags": _risk_flags_from_route(route),
        "risk_veto": route.get("risk_veto", False),
        "key_states": route.get("key_states") or route.get("state_hex") or {},
        "context": {
            "source_route": route,
            "route_calculation": {
                "base_weight": route.get("base_weight"),
                "consensus_adjust": route.get("consensus_adjust"),
                "m30_fine_tune": route.get("m30_fine_tune"),
                "history_adjust": route.get("history_adjust"),
                "final_weight": route.get("final_weight"),
            },
            "agent_consensus": route.get("agent_consensus", {}),
            "m30_input": route.get("m30_input", {}),
            "contraction_input": route.get("contraction_input", {}),
            "data_quality_note": route.get("data_quality_note", ""),
        },
    }


def normalize_router_records(router_output: Any, as_of_date: date) -> list[dict[str, Any]]:
    """把 Router 的 dict/list 输出统一成 observation ledger records。"""
    if router_output is None:
        return []

    routes: list[Any]
    if isinstance(router_output, list):
        routes = router_output
    elif isinstance(router_output, dict):
        if isinstance(router_output.get("all_routed"), list):
            routes = router_output["all_routed"]
        elif isinstance(router_output.get("records"), list):
            routes = router_output["records"]
        elif isinstance(router_output.get("per_stock_routes"), list):
            routes = router_output["per_stock_routes"]
        else:
            combined = []
            for key in ("top_candidates", "risk_candidates"):
                value = router_output.get(key)
                if isinstance(value, list):
                    combined.extend(value)
            routes = combined if combined else ([router_output] if router_output.get("stock_code") or router_output.get("chain_id") else [])
    else:
        routes = []

    records = [
        _normalize_route_record(route, as_of_date)
        for route in routes
        if isinstance(route, dict)
    ]

    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        key = (
            str(record.get("stock_code") or ""),
            str(record.get("chain_id") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _extract_per_stock_debate(debate_output: dict[str, Any], stock_code: str) -> dict[str, Any]:
    """从 debate 输出中提取单只股票的 debate 数据"""
    if not isinstance(debate_output, dict):
        return {}

    # New format: per_stock_debates dict
    per_stock = debate_output.get("per_stock_debates", {})
    if isinstance(per_stock, dict) and stock_code in per_stock:
        return per_stock[stock_code]

    # Legacy format: build from agent_results
    agent_results = debate_output.get("agent_results", {})
    stock_debate: dict[str, Any] = {"stock_code": stock_code, "agents": {}}

    for agent_id, agent_data in agent_results.items():
        if not isinstance(agent_data, dict):
            continue
        agent_data_section = agent_data.get("data", {})
        # Try to find stock-specific data in observations or holdings
        observations = agent_data_section.get("observations", [])
        holdings = agent_data_section.get("holdings", [])
        for item in observations + holdings:
            if isinstance(item, dict) and item.get("stock_code") == stock_code:
                stock_debate["agents"][agent_id] = {
                    "agent_id": agent_id,
                    "agent_name": agent_data.get("agent_name", agent_id),
                    "status": agent_data.get("status", "ok"),
                    "data": item,
                }
                break
        else:
            # Include agent summary even if no stock-specific data
            stock_debate["agents"][agent_id] = {
                "agent_id": agent_id,
                "agent_name": agent_data.get("agent_name", agent_id),
                "status": agent_data.get("status", "ok"),
                "summary": agent_data.get("summary", ""),
            }

    # Add debate summary classification for this stock
    debate_summary = debate_output.get("debate_summary", {})
    for category in ("resonance", "conflicts", "neutral"):
        items = debate_summary.get(category, [])
        for item in items:
            if isinstance(item, dict) and item.get("stock_code") == stock_code:
                stock_debate["classification"] = category
                stock_debate["summary"] = item
                break

    return stock_debate


def _map_conclusion_to_label(conclusion: str) -> str:
    """将 router conclusion 映射为 final_label"""
    c = str(conclusion).lower()
    if "strong" in c or "observe" in c or "偏多" in c or "操作" in conclusion:
        return "observe"
    if "moderate" in c or "watch" in c or "中性" in c or "谨慎" in conclusion:
        return "watch"
    if "reject" in c or "avoid" in c or "pass" in c or "防御" in c or "观望" in conclusion:
        return "reject"
    return "watch"


def _compute_outcome_label(future_r5: float | None) -> str | None:
    if future_r5 is None:
        return None
    if future_r5 > 0.05:
        return "positive"
    if future_r5 < -0.05:
        return "negative"
    return "neutral"


def _get_state_cube_futures(stock_code: str, state_date: date) -> tuple[float | None, float | None]:
    """从 state_cube 读取 future_r5 和 future_r20"""
    if not STATE_CUBE_DB.exists():
        return None, None
    try:
        con = duckdb.connect(str(STATE_CUBE_DB), read_only=True)
        row = con.execute(
            "SELECT future_r5, future_r20 FROM state_cube WHERE stock_code = ? AND state_date = ?",
            [stock_code, state_date],
        ).fetchone()
        con.close()
        if row:
            return row[0], row[1]
    except Exception as e:
        print(f"[ledger] state_cube 读取失败: {e}")
    return None, None


def _get_market_average_futures(state_date: date) -> tuple[float | None, float | None]:
    """从 state_cube 读取当日全市场平均 future_r5 / future_r20"""
    if not STATE_CUBE_DB.exists():
        return None, None
    try:
        con = duckdb.connect(str(STATE_CUBE_DB), read_only=True)
        row = con.execute(
            """
            SELECT AVG(future_r5), AVG(future_r20)
            FROM state_cube
            WHERE state_date = ? AND d1_close > 0
            """,
            [state_date],
        ).fetchone()
        con.close()
        if row:
            return row[0], row[1]
    except Exception as e:
        print(f"[ledger] state_cube 市场均值读取失败: {e}")
    return None, None


def write_ledger(records: list[dict], as_of_date: date, replace_date: bool = False) -> dict[str, Any]:
    """写入 AgentMemory.duckdb 和本地 JSON 备份"""
    os.makedirs(AGENT_MEMORY_DB.parent, exist_ok=True)
    os.makedirs(LEDGER_DIR, exist_ok=True)

    con = duckdb.connect(str(AGENT_MEMORY_DB))
    _ensure_agent_memory_schema(con)

    if replace_date:
        con.execute(
            """
            DELETE FROM agent_judgments
            WHERE judgment_date = ?
              AND judgment_type = 'decision_observation'
              AND agent_id = 'DynamicWeightRouter'
            """,
            [as_of_date],
        )

    written = 0
    for r in records:
        stock_code = r.get("stock_code") or ""
        chain_id = r.get("chain_id") or ""
        judgment_type = r.get("judgment_type", "decision_observation")
        agent_id = r.get("agent", "DynamicWeightRouter")
        judgment_id = str(uuid5(NAMESPACE_URL, f"{judgment_type}:{agent_id}:{as_of_date}:{stock_code}:{chain_id}"))
        direction = r.get("direction", "neutral")
        confidence = r.get("confidence", 0.5)

        judgment_content = json.dumps({
            "direction": direction,
            "rationale": r.get("rationale", ""),
            "risk_flags": r.get("risk_flags", []),
            "key_states": r.get("key_states", {}),
            "chain_id": chain_id,
            "stock_code": stock_code,
        }, ensure_ascii=False, default=str)

        factors_used = json.dumps({
            "source": "dynamic_weight_router",
            "version": "1.0",
        }, ensure_ascii=False)

        context_snapshot = json.dumps({
            "state_date": str(as_of_date),
            "chain_id": chain_id,
            "stock_code": stock_code,
            "ledger_version": "phase2_decision_observation_v1",
            "router_context": r.get("context", {}),
        }, ensure_ascii=False, default=str)

        con.execute("""
            DELETE FROM agent_judgments WHERE judgment_id = ?
        """, [judgment_id])
        con.execute("""
            INSERT INTO agent_judgments
            (agent_id, judgment_id, judgment_date, judgment_type,
             judgment_content, confidence, factors_used, context_snapshot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            agent_id, judgment_id, as_of_date, judgment_type,
            judgment_content, confidence, factors_used, context_snapshot
        ))
        written += 1

    con.commit()
    con.close()

    # JSON 备份
    backup_path = LEDGER_DIR / f"observation_ledger_{as_of_date.strftime('%Y%m%d')}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump({
            "state_date": str(as_of_date),
            "record_count": written,
            "records": records,
            "written_at": datetime.now().isoformat(),
        }, f, ensure_ascii=False, indent=2, default=str)

    print(f"[ledger] 写入 {written} 条到 AgentMemory，备份: {backup_path}")
    return {
        "record_count": written,
        "backup_path": str(backup_path),
        "agent_memory_db": str(AGENT_MEMORY_DB),
    }


def write_hypothesis_ledger(
    as_of_date: date,
    hypothesis_id: str,
    replace_date: bool = False,
) -> dict[str, Any]:
    """读取 Router + Debate 输出，写入 decision_observation.duckdb"""
    os.makedirs(DECISION_OBSERVATION_DB.parent, exist_ok=True)

    router_output = _load_router_output(as_of_date, hypothesis_id=hypothesis_id)
    debate_output = _load_debate_output(as_of_date, hypothesis_id=hypothesis_id)

    if router_output is None:
        return {"ok": False, "error": f"未找到 Router 输出: {as_of_date}", "record_count": 0}

    # Normalize router records
    records = normalize_router_records(router_output, as_of_date)
    if not records:
        return {"ok": False, "error": "Router 输出无有效记录", "record_count": 0}

    con = duckdb.connect(str(DECISION_OBSERVATION_DB))
    _ensure_decision_observation_schema(con)

    written = 0
    for r in records:
        stock_code = r.get("stock_code")
        if not stock_code:
            continue

        observation_id = str(uuid5(NAMESPACE_URL, f"{hypothesis_id}:{stock_code}:{as_of_date}"))

        # Extract from normalized router record
        route_context = r.get("context", {})
        source_route = route_context.get("source_route", {})

        final_label = _map_conclusion_to_label(r.get("direction", ""))
        final_score = r.get("confidence", 0.5)

        # Risk veto: prefer explicit risk_veto field, fallback to risk_flags check
        risk_veto = r.get("risk_veto", False)
        if not risk_veto:
            risk_flags = r.get("risk_flags", [])
            risk_veto = any("veto" in str(f).lower() for f in risk_flags)

        # Build router_json
        router_json = json.dumps({
            "stock_code": stock_code,
            "final_label": final_label,
            "final_score": final_score,
            "risk_veto": risk_veto,
            "risk_flags": risk_flags,
            "agent_weights": source_route.get("tf_weights", {}),
            "conflict_score": 1.0 if source_route.get("conflict") else 0.0,
            "resonance_score": 1.0 if source_route.get("resonance") else 0.0,
            "risk_penalty": 0.0,
            "router_reason": source_route.get("action") or source_route.get("rationale") or r.get("rationale", ""),
            "support_agents": source_route.get("support_agents", []),
            "oppose_agents": source_route.get("oppose_agents", []),
        }, ensure_ascii=False, default=str)

        # Build agent_debate_json
        per_stock_debate = _extract_per_stock_debate(debate_output or {}, stock_code)
        agent_debate_json = json.dumps(per_stock_debate, ensure_ascii=False, default=str) if per_stock_debate else None

        # Read future_r5/future_r20 from state_cube (may be NULL)
        future_r5, future_r20 = _get_state_cube_futures(stock_code, as_of_date)

        # outcome_label is NOT computed during write (only during backfill)
        outcome_label = None

        # Check existing review_status to preserve it
        existing = con.execute(
            "SELECT review_status FROM decision_observation WHERE observation_id = ?",
            [observation_id],
        ).fetchone()
        review_status = existing[0] if existing else "pending"

        # UPSERT: insert or replace, but preserve review_status
        con.execute("""
            INSERT OR REPLACE INTO decision_observation (
                observation_id, hypothesis_id, stock_code, state_date,
                agent_debate_json, router_json, final_label, final_score,
                risk_veto, future_r5, future_r20, outcome_label,
                review_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                (SELECT created_at FROM decision_observation WHERE observation_id = ?),
                CURRENT_TIMESTAMP
            ), CURRENT_TIMESTAMP)
        """, (
            observation_id, hypothesis_id, stock_code, as_of_date,
            agent_debate_json, router_json, final_label, final_score,
            risk_veto, future_r5, future_r20, outcome_label,
            review_status, observation_id,
        ))
        written += 1

    con.commit()
    con.close()

    print(f"[ledger] hypothesis={hypothesis_id} date={as_of_date} 写入 {written} 条到 decision_observation")
    return {
        "ok": True,
        "record_count": written,
        "db_path": str(DECISION_OBSERVATION_DB),
    }


def _build_market_observation_record(
    as_of_date: date,
    debate_data: dict[str, Any],
    router_data: dict[str, Any],
) -> dict[str, Any]:
    """构造单条市场级观察记录（不写入 DB）。"""
    verdict = router_data.get("verdict", {})
    final_verdict = verdict.get("final_verdict", "谨慎中性")
    final_label = _map_conclusion_to_label(final_verdict)
    final_score = float(verdict.get("adjusted_score", 0.5))

    router_json = json.dumps({
        "generated_at": router_data.get("generated_at"),
        "weights": router_data.get("weights", {}),
        "conflicts_count": len(router_data.get("conflicts", [])),
        "resonances_count": len(router_data.get("resonances", [])),
        "verdict": verdict,
    }, ensure_ascii=False, default=str)

    debate_summary = {
        "generated_at": debate_data.get("generated_at"),
        "state_date": debate_data.get("state_date"),
        "cube_stocks": debate_data.get("cube_stocks"),
        "opinions": debate_data.get("opinions", []),
        "market_summary": debate_data.get("market_summary", {}),
    }
    agent_debate_json = json.dumps(debate_summary, ensure_ascii=False, default=str)

    future_r5, future_r20 = _get_market_average_futures(as_of_date)
    outcome_label = _compute_outcome_label(future_r5)
    risk_veto = final_label == "reject"
    observation_id = str(uuid5(NAMESPACE_URL, f"MARKET_DAILY_OBSERVATION:__MARKET__:{as_of_date}"))

    return {
        "observation_id": observation_id,
        "hypothesis_id": "MARKET_DAILY_OBSERVATION",
        "stock_code": "__MARKET__",
        "state_date": as_of_date,
        "agent_debate_json": agent_debate_json,
        "router_json": router_json,
        "final_label": final_label,
        "final_score": final_score,
        "risk_veto": risk_veto,
        "future_r5": future_r5,
        "future_r20": future_r20,
        "outcome_label": outcome_label,
    }


def write_market_observation_ledger(
    as_of_date: date,
    debate_data: dict[str, Any],
    router_data: dict[str, Any],
    replace_date: bool = False,
) -> dict[str, Any]:
    """写入市场级观察记录（MOE 当前管线产出为市场级别 verdict）。

    该记录把每日 6-Agent 辩论 + Router 综合判断固化为可复盘的市场择时信号，
    stock_code 使用 __MARKET__ 占位，方便后续统一回填与归因。
    """
    os.makedirs(DECISION_OBSERVATION_DB.parent, exist_ok=True)

    con = duckdb.connect(str(DECISION_OBSERVATION_DB))
    _ensure_decision_observation_schema(con)

    if replace_date:
        con.execute(
            """
            DELETE FROM decision_observation
            WHERE hypothesis_id = 'MARKET_DAILY_OBSERVATION' AND state_date = ?
            """,
            [as_of_date],
        )

    record = _build_market_observation_record(as_of_date, debate_data, router_data)

    con.execute("""
        INSERT OR REPLACE INTO decision_observation (
            observation_id, hypothesis_id, stock_code, state_date,
            agent_debate_json, router_json, final_label, final_score,
            risk_veto, future_r5, future_r20, outcome_label,
            review_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (
        record["observation_id"], record["hypothesis_id"], record["stock_code"], record["state_date"],
        record["agent_debate_json"], record["router_json"], record["final_label"], record["final_score"],
        record["risk_veto"], record["future_r5"], record["future_r20"], record["outcome_label"],
        "pending",
    ))

    con.commit()
    con.close()

    print(f"[ledger] 市场级观察记录 date={as_of_date} label={record['final_label']} score={record['final_score']:.2f}")
    return {
        "ok": True,
        "record_count": 1,
        "observation_id": record["observation_id"],
        "db_path": str(DECISION_OBSERVATION_DB),
    }


def batch_write_market_observations(
    records: list[dict[str, Any]],
    replace_hypothesis: bool = True,
) -> dict[str, Any]:
    """批量写入市场级观察记录，使用单一 DB 连接避免并发锁。"""
    if not records:
        return {"ok": True, "record_count": 0}

    os.makedirs(DECISION_OBSERVATION_DB.parent, exist_ok=True)
    con = duckdb.connect(str(DECISION_OBSERVATION_DB))
    _ensure_decision_observation_schema(con)

    if replace_hypothesis:
        con.execute(
            "DELETE FROM decision_observation WHERE hypothesis_id = 'MARKET_DAILY_OBSERVATION'"
        )

    for record in records:
        con.execute("""
            INSERT OR REPLACE INTO decision_observation (
                observation_id, hypothesis_id, stock_code, state_date,
                agent_debate_json, router_json, final_label, final_score,
                risk_veto, future_r5, future_r20, outcome_label,
                review_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (
            record["observation_id"], record["hypothesis_id"], record["stock_code"], record["state_date"],
            record["agent_debate_json"], record["router_json"], record["final_label"], record["final_score"],
            record["risk_veto"], record["future_r5"], record["future_r20"], record["outcome_label"],
            "pending",
        ))

    con.commit()
    con.close()

    print(f"[ledger] 批量写入 {len(records)} 条市场级观察记录")
    return {"ok": True, "record_count": len(records)}


def generate_market_observation_report() -> dict[str, Any]:
    """生成市场级观察信号的历史复盘报告，供前端展示。"""
    if not DECISION_OBSERVATION_DB.exists():
        return {"ok": False, "error": "decision_observation.duckdb 不存在", "records": []}

    con = duckdb.connect(str(DECISION_OBSERVATION_DB), read_only=True)
    rows = con.execute(
        """
        SELECT state_date, final_label, final_score, future_r5, future_r20, outcome_label, risk_veto
        FROM decision_observation
        WHERE hypothesis_id = 'MARKET_DAILY_OBSERVATION'
        ORDER BY state_date DESC
        """
    ).fetchall()
    con.close()

    records = []
    for state_date, final_label, final_score, future_r5, future_r20, outcome_label, risk_veto in rows:
        records.append({
            "state_date": str(state_date),
            "final_label": final_label,
            "final_score": round(final_score, 2) if final_score is not None else None,
            "future_r5": round(future_r5, 4) if future_r5 is not None else None,
            "future_r20": round(future_r20, 4) if future_r20 is not None else None,
            "outcome_label": outcome_label,
            "risk_veto": bool(risk_veto),
        })

    # 胜率统计：按 final_label 分组
    label_stats: dict[str, dict[str, Any]] = {}
    total_hit = total_seen = 0
    for r in records:
        label = r["final_label"] or "unknown"
        if label not in label_stats:
            label_stats[label] = {"count": 0, "hit": 0, "r5_list": [], "r20_list": []}
        label_stats[label]["count"] += 1
        if r["future_r5"] is not None:
            label_stats[label]["r5_list"].append(r["future_r5"])
        if r["future_r20"] is not None:
            label_stats[label]["r20_list"].append(r["future_r20"])
        if r["outcome_label"]:
            total_seen += 1
            # 看涨信号（observe）命中 positive，看跌信号（reject）命中 negative，均为正确
            if label == "observe" and r["outcome_label"] == "positive":
                label_stats[label]["hit"] += 1
                total_hit += 1
            elif label == "reject" and r["outcome_label"] == "negative":
                label_stats[label]["hit"] += 1
                total_hit += 1
            elif label == "watch":
                # watch 信号不纳入方向胜率，但记录中性命中
                pass

    for label, s in label_stats.items():
        s["avg_r5"] = round(sum(s["r5_list"]) / len(s["r5_list"]), 4) if s["r5_list"] else None
        s["avg_r20"] = round(sum(s["r20_list"]) / len(s["r20_list"]), 4) if s["r20_list"] else None
        s["positive_pct"] = round(sum(1 for v in s["r5_list"] if v > 0) / len(s["r5_list"]), 4) if s["r5_list"] else 0
        s["positive_pct_r20"] = round(sum(1 for v in s["r20_list"] if v > 0) / len(s["r20_list"]), 4) if s["r20_list"] else 0
        s["hit_rate"] = round(s["hit"] / s["count"], 4) if s["count"] else 0
        s.pop("r5_list", None)
        s.pop("r20_list", None)

    overall_hit_rate = round(total_hit / total_seen, 4) if total_seen else 0

    # 按 score 分三档统计未来收益（即使官方 label 都是 watch，也能给出趋势强度）
    score_bins = {
        "high": {"r5": [], "r20": []},
        "mid": {"r5": [], "r20": []},
        "low": {"r5": [], "r20": []},
    }
    for r in records:
        s = r["final_score"] or 0.5
        bin_key = "high" if s >= 0.50 else ("mid" if s >= 0.30 else "low")
        if r["future_r5"] is not None:
            score_bins[bin_key]["r5"].append(r["future_r5"])
        if r["future_r20"] is not None:
            score_bins[bin_key]["r20"].append(r["future_r20"])

    score_bin_stats = {}
    for key, bins in score_bins.items():
        score_bin_stats[key] = {
            "count": len(bins["r5"]),
            "avg_future_r5": round(sum(bins["r5"]) / len(bins["r5"]), 4) if bins["r5"] else None,
            "positive_pct": round(sum(1 for v in bins["r5"] if v > 0) / len(bins["r5"]), 4) if bins["r5"] else None,
            "avg_future_r20": round(sum(bins["r20"]) / len(bins["r20"]), 4) if bins["r20"] else None,
            "positive_pct_r20": round(sum(1 for v in bins["r20"] if v > 0) / len(bins["r20"]), 4) if bins["r20"] else None,
        }

    return {
        "ok": True,
        "record_count": len(records),
        "latest": records[0] if records else None,
        "records": records,
        "label_stats": label_stats,
        "score_bin_stats": score_bin_stats,
        "overall_hit_rate": overall_hit_rate,
        "evaluated_count": total_seen,
    }


def backfill_hypothesis_ledger(as_of_date: date, hypothesis_id: str) -> dict[str, Any]:
    """回填指定日期及之前的所有记录的 future_r5/future_r20 和 outcome_label"""
    if not DECISION_OBSERVATION_DB.exists():
        return {"ok": False, "error": "decision_observation.duckdb 不存在", "record_count": 0}

    con = duckdb.connect(str(DECISION_OBSERVATION_DB))
    _ensure_decision_observation_schema(con)

    # Find all records for this hypothesis with state_date <= as_of_date
    rows = con.execute(
        "SELECT observation_id, stock_code, state_date FROM decision_observation WHERE hypothesis_id = ? AND state_date <= ?",
        [hypothesis_id, as_of_date],
    ).fetchall()

    updated = 0
    for observation_id, stock_code, state_date in rows:
        future_r5, future_r20 = _get_state_cube_futures(stock_code, state_date)
        outcome_label = _compute_outcome_label(future_r5)

        con.execute("""
            UPDATE decision_observation
            SET future_r5 = ?, future_r20 = ?, outcome_label = ?, review_status = 'backfilled', updated_at = CURRENT_TIMESTAMP
            WHERE observation_id = ?
        """, [future_r5, future_r20, outcome_label, observation_id])
        updated += 1

    con.commit()
    con.close()

    print(f"[ledger] hypothesis={hypothesis_id} backfill 截至 {as_of_date} 更新 {updated} 条")
    return {
        "ok": True,
        "record_count": updated,
        "db_path": str(DECISION_OBSERVATION_DB),
    }


def generate_minimal_ledger(as_of_date: date) -> list[dict]:
    """当 Router 输出不存在时，生成最小骨架记录"""
    return [{
        "agent": "DynamicWeightRouter",
        "judgment_type": "decision_observation",
        "stock_code": "",
        "state_date": str(as_of_date),
        "direction": "neutral",
        "confidence": 0.5,
        "rationale": "Router 输出缺失，生成占位记录以验证账本通路",
        "risk_flags": ["router_output_missing"],
        "key_states": {"regime": "unknown", "lead_node": "-"},
    }]


def write_current_router_ledger(
    as_of_date: date,
    stock_code: str = "",
    *,
    replace_date: bool = False,
) -> dict[str, Any]:
    """读取当前 Router 输出并写入观察账本（原有功能）。"""
    router_output = _load_router_output(as_of_date, stock_code=stock_code)
    source = "router"
    if router_output is None:
        records = generate_minimal_ledger(as_of_date)
        source = "minimal"
    else:
        records = normalize_router_records(router_output, as_of_date)

    if stock_code:
        records = [r for r in records if r.get("stock_code") == stock_code]
    if not records:
        return {"ok": False, "error": "未找到该标的 Router 结果", "record_count": 0}

    result = write_ledger(records, as_of_date, replace_date=replace_date)
    return {"ok": True, "source": source, **result}


def write_per_stock_observation_ledger(
    as_of_date: date,
    debate_data: dict[str, Any],
    replace_date: bool = False,
) -> dict[str, Any]:
    """将 per-stock 决策记录写入 decision_observation.duckdb。

    从 debate 输出的 per_stock_records 中读取每只标的的评分和标签，
    写入 decision_observation 表，支持个股历史时序复盘。
    """
    per_stock = debate_data.get("per_stock_records", [])
    if not per_stock:
        return {"ok": False, "error": "debate 输出无 per_stock_records", "record_count": 0}

    os.makedirs(DECISION_OBSERVATION_DB.parent, exist_ok=True)
    con = duckdb.connect(str(DECISION_OBSERVATION_DB))
    _ensure_decision_observation_schema(con)

    if replace_date:
        con.execute(
            """
            DELETE FROM decision_observation
            WHERE hypothesis_id = 'PER_STOCK_OBSERVATION' AND state_date = ?
            """,
            [as_of_date],
        )

    written = 0
    for rec in per_stock:
        stock_code = rec.get("stock_code", "")
        if not stock_code:
            continue

        observation_id = str(uuid5(NAMESPACE_URL, f"PER_STOCK_OBSERVATION:{stock_code}:{as_of_date}"))
        final_label = rec.get("label", "watch")
        final_score = float(rec.get("composite_score", 0.5))
        risk_veto = final_label == "reject" and final_score < 0.3

        # Build router_json from per-stock scores
        dim_scores = rec.get("dimension_scores", {})
        router_json = json.dumps({
            "stock_code": stock_code,
            "final_label": final_label,
            "final_score": final_score,
            "risk_veto": risk_veto,
            "dimension_scores": dim_scores,
            "bullish_signals": rec.get("bullish_signals", 0),
            "bearish_signals": rec.get("bearish_signals", 0),
            "verdict": rec.get("verdict", "中性"),
        }, ensure_ascii=False, default=str)

        # Build agent_debate_json from key_states
        agent_debate_json = json.dumps(rec.get("key_states", {}), ensure_ascii=False, default=str)

        # Read future_r5/future_r20 from state_cube
        future_r5, future_r20 = _get_state_cube_futures(stock_code, as_of_date)
        outcome_label = _compute_outcome_label(future_r5)

        # Preserve existing review_status
        existing = con.execute(
            "SELECT review_status FROM decision_observation WHERE observation_id = ?",
            [observation_id],
        ).fetchone()
        review_status = existing[0] if existing else "pending"

        con.execute("""
            INSERT OR REPLACE INTO decision_observation (
                observation_id, hypothesis_id, stock_code, state_date,
                agent_debate_json, router_json, final_label, final_score,
                risk_veto, future_r5, future_r20, outcome_label,
                review_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                (SELECT created_at FROM decision_observation WHERE observation_id = ?),
                CURRENT_TIMESTAMP
            ), CURRENT_TIMESTAMP)
        """, (
            observation_id, "PER_STOCK_OBSERVATION", stock_code, as_of_date,
            agent_debate_json, router_json, final_label, final_score,
            risk_veto, future_r5, future_r20, outcome_label,
            review_status, observation_id,
        ))
        written += 1

    con.commit()
    con.close()

    observe_count = sum(1 for r in per_stock if r.get("label") == "observe")
    reject_count = sum(1 for r in per_stock if r.get("label") == "reject")
    print(f"[ledger] per-stock date={as_of_date} 写入 {written} 条 "
          f"(observe={observe_count}, watch={written - observe_count - reject_count}, reject={reject_count})")
    return {
        "ok": True,
        "record_count": written,
        "observe_count": observe_count,
        "reject_count": reject_count,
        "db_path": str(DECISION_OBSERVATION_DB),
    }


def _build_per_stock_observation_record(
    rec: dict[str, Any],
    as_of_date: date,
    future_r5: float | None,
    future_r20: float | None,
) -> dict[str, Any]:
    """构造单条 per-stock 观察记录（不写入 DB）。"""
    stock_code = rec.get("stock_code", "")
    final_label = rec.get("label", "watch")
    final_score = float(rec.get("composite_score", 0.5))
    risk_veto = final_label == "reject" and final_score < 0.3
    observation_id = str(uuid5(NAMESPACE_URL, f"PER_STOCK_OBSERVATION:{stock_code}:{as_of_date}"))

    dim_scores = rec.get("dimension_scores", {})
    router_json = json.dumps({
        "stock_code": stock_code,
        "final_label": final_label,
        "final_score": final_score,
        "risk_veto": risk_veto,
        "dimension_scores": dim_scores,
        "bullish_signals": rec.get("bullish_signals", 0),
        "bearish_signals": rec.get("bearish_signals", 0),
        "verdict": rec.get("verdict", "中性"),
    }, ensure_ascii=False, default=str)

    agent_debate_json = json.dumps(rec.get("key_states", {}), ensure_ascii=False, default=str)
    outcome_label = _compute_outcome_label(future_r5)

    return {
        "observation_id": observation_id,
        "hypothesis_id": "PER_STOCK_OBSERVATION",
        "stock_code": stock_code,
        "state_date": as_of_date,
        "agent_debate_json": agent_debate_json,
        "router_json": router_json,
        "final_label": final_label,
        "final_score": final_score,
        "risk_veto": risk_veto,
        "future_r5": future_r5,
        "future_r20": future_r20,
        "outcome_label": outcome_label,
    }


def batch_write_per_stock_observations(
    records: list[dict[str, Any]],
    replace_hypothesis: bool = True,
) -> dict[str, Any]:
    """批量写入 per-stock 观察记录，使用单一 DB 连接避免并发锁。"""
    if not records:
        return {"ok": True, "record_count": 0}

    os.makedirs(DECISION_OBSERVATION_DB.parent, exist_ok=True)
    con = duckdb.connect(str(DECISION_OBSERVATION_DB))
    _ensure_decision_observation_schema(con)

    if replace_hypothesis:
        con.execute(
            "DELETE FROM decision_observation WHERE hypothesis_id = 'PER_STOCK_OBSERVATION'"
        )

    for record in records:
        con.execute("""
            INSERT OR REPLACE INTO decision_observation (
                observation_id, hypothesis_id, stock_code, state_date,
                agent_debate_json, router_json, final_label, final_score,
                risk_veto, future_r5, future_r20, outcome_label,
                review_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (
            record["observation_id"], record["hypothesis_id"], record["stock_code"], record["state_date"],
            record["agent_debate_json"], record["router_json"], record["final_label"], record["final_score"],
            record["risk_veto"], record["future_r5"], record["future_r20"], record["outcome_label"],
            "pending",
        ))

    con.commit()
    con.close()

    print(f"[ledger] 批量写入 {len(records)} 条 per-stock 观察记录")
    return {"ok": True, "record_count": len(records)}


def generate_per_stock_observation_report(
    stock_code: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """生成 per-stock 观察记录报告，支持单只标的时序复盘。

    如果指定 stock_code，返回该标的的历史信号和结果；
    如果不指定，返回今日所有标的的快照。
    """
    if not DECISION_OBSERVATION_DB.exists():
        return {"ok": False, "error": "decision_observation.duckdb 不存在", "records": []}

    con = duckdb.connect(str(DECISION_OBSERVATION_DB), read_only=True)

    if stock_code:
        rows = con.execute(
            """
            SELECT stock_code, state_date, final_label, final_score,
                   future_r5, future_r20, outcome_label, risk_veto
            FROM decision_observation
            WHERE hypothesis_id = 'PER_STOCK_OBSERVATION' AND stock_code = ?
            ORDER BY state_date DESC
            LIMIT ?
            """,
            [stock_code, limit],
        ).fetchall()
    else:
        # Return today's snapshot (latest state_date)
        latest = con.execute(
            "SELECT MAX(state_date) FROM decision_observation WHERE hypothesis_id = 'PER_STOCK_OBSERVATION'"
        ).fetchone()
        if not latest or not latest[0]:
            con.close()
            return {"ok": False, "error": "无 per-stock 记录", "records": []}
        latest_date = latest[0]
        rows = con.execute(
            """
            SELECT stock_code, state_date, final_label, final_score,
                   future_r5, future_r20, outcome_label, risk_veto
            FROM decision_observation
            WHERE hypothesis_id = 'PER_STOCK_OBSERVATION' AND state_date = ?
            ORDER BY final_score DESC
            """,
            [latest_date],
        ).fetchall()

    con.close()

    records = []
    for stock_code_val, state_date, final_label, final_score, future_r5, future_r20, outcome_label, risk_veto in rows:
        records.append({
            "stock_code": stock_code_val,
            "state_date": str(state_date),
            "final_label": final_label,
            "final_score": round(final_score, 2) if final_score is not None else None,
            "future_r5": round(future_r5, 4) if future_r5 is not None else None,
            "future_r20": round(future_r20, 4) if future_r20 is not None else None,
            "outcome_label": outcome_label,
            "risk_veto": bool(risk_veto),
        })

    # Category stats
    observe_count = sum(1 for r in records if r["final_label"] == "observe")
    reject_count = sum(1 for r in records if r["final_label"] == "reject")
    watch_count = len(records) - observe_count - reject_count

    result: dict[str, Any] = {
        "ok": True,
        "record_count": len(records),
        "observe_count": observe_count,
        "watch_count": watch_count,
        "reject_count": reject_count,
        "records": records,
    }

    # Historical aggregate stats (only when no specific stock_code)
    if not stock_code:
        result["history"] = _compute_per_stock_history_stats()

    return result


def _compute_per_stock_history_stats() -> dict[str, Any]:
    """计算 per-stock 历史复盘统计（所有有 future_r5 的记录）。"""
    if not DECISION_OBSERVATION_DB.exists():
        return {"ok": False, "error": "decision_observation.duckdb 不存在"}

    con = duckdb.connect(str(DECISION_OBSERVATION_DB), read_only=True)
    rows = con.execute(
        """
        SELECT final_label, final_score, future_r5, future_r20, outcome_label
        FROM decision_observation
        WHERE hypothesis_id = 'PER_STOCK_OBSERVATION' AND future_r5 IS NOT NULL
        """
    ).fetchall()
    con.close()

    label_stats: dict[str, dict[str, Any]] = {}
    total_hit = total_seen = 0
    score_bins = {
        "high": {"r5": [], "r20": []},
        "mid": {"r5": [], "r20": []},
        "low": {"r5": [], "r20": []},
    }

    for final_label, final_score, future_r5, future_r20, outcome_label in rows:
        label = final_label or "unknown"
        if label not in label_stats:
            label_stats[label] = {"count": 0, "hit": 0, "r5_list": [], "r20_list": []}
        label_stats[label]["count"] += 1
        if future_r5 is not None:
            label_stats[label]["r5_list"].append(future_r5)
        if future_r20 is not None:
            label_stats[label]["r20_list"].append(future_r20)
        if outcome_label:
            total_seen += 1
            if label == "observe" and outcome_label == "positive":
                label_stats[label]["hit"] += 1
                total_hit += 1
            elif label == "reject" and outcome_label == "negative":
                label_stats[label]["hit"] += 1
                total_hit += 1

        s = final_score or 0.5
        bin_key = "high" if s >= 0.7 else ("mid" if s >= 0.4 else "low")
        if future_r5 is not None:
            score_bins[bin_key]["r5"].append(future_r5)
        if future_r20 is not None:
            score_bins[bin_key]["r20"].append(future_r20)

    for label, s in label_stats.items():
        s["avg_r5"] = round(sum(s["r5_list"]) / len(s["r5_list"]), 4) if s["r5_list"] else None
        s["avg_r20"] = round(sum(s["r20_list"]) / len(s["r20_list"]), 4) if s["r20_list"] else None
        s["positive_pct"] = round(sum(1 for v in s["r5_list"] if v > 0) / len(s["r5_list"]), 4) if s["r5_list"] else 0
        s["positive_pct_r20"] = round(sum(1 for v in s["r20_list"] if v > 0) / len(s["r20_list"]), 4) if s["r20_list"] else 0
        s["hit_rate"] = round(s["hit"] / s["count"], 4) if s["count"] else 0
        s.pop("r5_list", None)
        s.pop("r20_list", None)

    score_bin_stats = {}
    for key, bins in score_bins.items():
        score_bin_stats[key] = {
            "count": len(bins["r5"]),
            "avg_future_r5": round(sum(bins["r5"]) / len(bins["r5"]), 4) if bins["r5"] else None,
            "positive_pct": round(sum(1 for v in bins["r5"] if v > 0) / len(bins["r5"]), 4) if bins["r5"] else None,
            "avg_future_r20": round(sum(bins["r20"]) / len(bins["r20"]), 4) if bins["r20"] else None,
            "positive_pct_r20": round(sum(1 for v in bins["r20"] if v > 0) / len(bins["r20"]), 4) if bins["r20"] else None,
        }

    return {
        "ok": True,
        "total_evaluated": total_seen,
        "overall_hit_rate": round(total_hit / total_seen, 4) if total_seen else 0,
        "label_stats": label_stats,
        "score_bin_stats": score_bin_stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="决策观察账本写入")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # Legacy/default: just --date
    parser.add_argument("--date", type=str, help="日期 YYYY-MM-DD")

    # write subcommand
    write_parser = subparsers.add_parser("write", help="写入 hypothesis 观察记录")
    write_parser.add_argument("--date", type=str, required=True, help="日期 YYYY-MM-DD")
    write_parser.add_argument("--hypothesis", type=str, required=True, help="假设 ID")

    # backfill subcommand
    backfill_parser = subparsers.add_parser("backfill", help="回填 outcome_label")
    backfill_parser.add_argument("--as-of", type=str, required=True, help="截止日期 YYYY-MM-DD")
    backfill_parser.add_argument("--hypothesis", type=str, required=True, help="假设 ID")

    args = parser.parse_args()

    if args.command == "write":
        as_of_date = _resolve_date(args.date)
        print(f"[ledger] write hypothesis={args.hypothesis} date={as_of_date}")
        result = write_hypothesis_ledger(as_of_date, args.hypothesis, replace_date=True)
        if not result.get("ok"):
            print(f"[ledger] 失败: {result.get('error')}")
            return 1
        return 0

    if args.command == "backfill":
        as_of_date = _resolve_date(args.as_of)
        print(f"[ledger] backfill hypothesis={args.hypothesis} as-of={as_of_date}")
        result = backfill_hypothesis_ledger(as_of_date, args.hypothesis)
        if not result.get("ok"):
            print(f"[ledger] 失败: {result.get('error')}")
            return 1
        return 0

    # Legacy behavior: no subcommand, just --date
    as_of_date = _resolve_date(args.date)
    print(f"[ledger] 处理日期: {as_of_date}")

    router_output = _load_router_output(as_of_date)
    if router_output is None:
        print("[ledger] 未找到 Router 输出，生成最小骨架记录")
        result = write_current_router_ledger(as_of_date, replace_date=True)
    else:
        records = normalize_router_records(router_output, as_of_date)
        print(f"[ledger] 标准化 Router 输出: {len(records)} 条")
        result = write_ledger(records, as_of_date, replace_date=True)

    if not result.get("ok", True):
        print(f"[ledger] 失败: {result.get('error')}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
