#!/usr/bin/env python3
"""Build an industry-chain fund manager assistant observation pool.

This script does not create trading advice. It ranks chain-node-stock mappings
for research review by combining:
  - ifind_chain_panel mapping evidence
  - fundamental quality data
  - State Cube technical context
  - chain dynamics and event evidence

Unverified mappings remain research-only and are surfaced as manual-review
priorities instead of production holdings.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHAIN_DB = ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"
DEFAULT_FUND_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
DEFAULT_STATE_DB = ROOT / "outputs" / "state_cube" / "state_cube.duckdb"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "industry_chain"

SOURCE_WEIGHTS = {
    "manual_override": 98.0,
    "ifind_terminal_excel": 92.0,
    "ifind_mcp": 82.0,
    "agent_debate": 80.0,
    "rule_inference": 65.0,
}
EVIDENCE_WEIGHTS = {
    "strong": 95.0,
    "manual_export": 90.0,
    "medium": 75.0,
    "weak": 55.0,
    "none": 0.0,
}

CANDIDATE_COLUMNS: list[tuple[str, str]] = [
    ("run_as_of_date", "VARCHAR"),
    ("state_date", "VARCHAR"),
    ("panel_latest_date", "VARCHAR"),
    ("stock_code", "VARCHAR"),
    ("stock_name", "VARCHAR"),
    ("chain_id", "VARCHAR"),
    ("chain_name", "VARCHAR"),
    ("node_id", "VARCHAR"),
    ("node_name", "VARCHAR"),
    ("node_position", "VARCHAR"),
    ("roles", "VARCHAR"),
    ("source_types", "VARCHAR"),
    ("evidence_levels", "VARCHAR"),
    ("node_match_methods", "VARCHAR"),
    ("manual_verified_any", "BOOLEAN"),
    ("review_gate", "VARCHAR"),
    ("candidate_bucket", "VARCHAR"),
    ("assistant_score", "DOUBLE"),
    ("evidence_score", "DOUBLE"),
    ("fundamental_score", "DOUBLE"),
    ("technical_score", "DOUBLE"),
    ("dynamic_score", "DOUBLE"),
    ("risk_penalty", "DOUBLE"),
    ("risk_flags_json", "VARCHAR"),
    ("chain_dynamic_summary_json", "VARCHAR"),
    ("event_summary_json", "VARCHAR"),
    ("panel_records", "INTEGER"),
    ("source_type_count", "INTEGER"),
    ("confidence_max", "DOUBLE"),
    ("confidence_avg", "DOUBLE"),
    ("sw_l1", "VARCHAR"),
    ("sw_l2", "VARCHAR"),
    ("sw_l3", "VARCHAR"),
    ("main_business", "VARCHAR"),
    ("main_product_types", "VARCHAR"),
    ("main_product_names", "VARCHAR"),
    ("quality_score", "DOUBLE"),
    ("final_fundamental_score", "DOUBLE"),
    ("core_business_purity", "DOUBLE"),
    ("cash_quality", "DOUBLE"),
    ("earnings_quality", "DOUBLE"),
    ("asset_safety_ratio", "DOUBLE"),
    ("roe", "DOUBLE"),
    ("gross_margin", "DOUBLE"),
    ("revenue_yoy", "DOUBLE"),
    ("net_profit_yoy", "DOUBLE"),
    ("pe_ttm", "DOUBLE"),
    ("pb", "DOUBLE"),
    ("debt_ratio", "DOUBLE"),
    ("mn1_state_hex", "VARCHAR"),
    ("w1_state_hex", "VARCHAR"),
    ("d1_state_hex", "VARCHAR"),
    ("w1_ma_state", "VARCHAR"),
    ("d1_ma_state", "VARCHAR"),
    ("w1_bb20_position", "VARCHAR"),
    ("w1_bb20_width", "VARCHAR"),
    ("d1_bb20_position", "VARCHAR"),
    ("d1_bb20_width", "VARCHAR"),
    ("w1_bb50_position", "VARCHAR"),
    ("d1_bb50_position", "VARCHAR"),
    ("w1_adx14", "DOUBLE"),
    ("d1_adx14", "DOUBLE"),
    ("w1_plus_di_14", "DOUBLE"),
    ("d1_plus_di_14", "DOUBLE"),
    ("w1_minus_di_14", "DOUBLE"),
    ("d1_minus_di_14", "DOUBLE"),
    ("d1_close", "DOUBLE"),
    ("w1_close", "DOUBLE"),
    ("raw_source_refs", "VARCHAR"),
]


def _escape_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    text = str(value)
    return text if text else None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _split_csv(value: Any) -> list[str]:
    if value is None:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _score_from_values(values: list[str], weights: dict[str, float], default: float) -> float:
    if not values:
        return default
    return max(weights.get(value, default) for value in values)


def resolve_cutoff_date(con: duckdb.DuckDBPyConnection, requested_date: str | None) -> str:
    if requested_date:
        return requested_date
    value = con.execute("SELECT MAX(as_of_date) FROM ifind_chain_panel").fetchone()[0]
    if value is None:
        raise RuntimeError("ifind_chain_panel has no records")
    return str(value)


def resolve_state_date(con: duckdb.DuckDBPyConnection, cutoff_date: str, requested_state_date: str | None) -> str | None:
    if requested_state_date:
        value = con.execute(
            "SELECT MAX(state_date) FROM state.state_cube WHERE state_date <= CAST(? AS DATE)",
            (requested_state_date,),
        ).fetchone()[0]
    else:
        value = con.execute(
            "SELECT MAX(state_date) FROM state.state_cube WHERE state_date <= CAST(? AS DATE)",
            (cutoff_date,),
        ).fetchone()[0]
    return str(value) if value is not None else None


def fetch_candidate_rows(
    chain_db: Path,
    fund_db: Path,
    state_db: Path,
    cutoff_date: str,
    state_date: str | None,
    chains: list[str] | None,
    require_manual_verified: bool,
) -> list[dict[str, Any]]:
    con = duckdb.connect(str(chain_db))
    try:
        if fund_db.exists():
            con.execute(f"ATTACH '{_escape_path(fund_db)}' AS fund (READ_ONLY)")
        if state_db.exists():
            con.execute(f"ATTACH '{_escape_path(state_db)}' AS state (READ_ONLY)")

        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        where = ["p.as_of_date <= ?"]
        panel_params: list[Any] = [cutoff_date]
        if chains:
            where.append(f"p.chain_id IN ({', '.join(['?'] * len(chains))})")
            panel_params.extend(chains)
        if require_manual_verified:
            where.append("p.manual_verified = true")
        if "chain_panel_review_mapping_decisions" in tables:
            where.append(
                """
                NOT EXISTS (
                    SELECT 1
                    FROM chain_panel_review_mapping_decisions d
                    WHERE d.chain_id = p.chain_id
                      AND d.node_id = p.node_id
                      AND d.stock_code = p.stock_code
                      AND d.review_status = 'rejected'
                )
                """
            )
        elif "chain_panel_review_decisions" in tables:
            where.append(
                """
                NOT EXISTS (
                    SELECT 1
                    FROM chain_panel_review_decisions d
                    WHERE d.chain_id = p.chain_id
                      AND d.node_id = p.node_id
                      AND d.stock_code = p.stock_code
                      AND d.as_of_date = p.as_of_date
                      AND d.review_status = 'rejected'
                )
                """
            )
        where_sql = "WHERE " + " AND ".join(where)
        state_params: list[Any] = []

        state_join = ""
        state_cols = """
            NULL AS state_date,
            NULL AS mn1_state_hex,
            NULL AS w1_state_hex,
            NULL AS d1_state_hex,
            NULL AS w1_ma_state,
            NULL AS d1_ma_state,
            NULL AS w1_bb20_position,
            NULL AS w1_bb20_width,
            NULL AS d1_bb20_position,
            NULL AS d1_bb20_width,
            NULL AS w1_bb50_position,
            NULL AS d1_bb50_position,
            NULL AS w1_adx14,
            NULL AS d1_adx14,
            NULL AS w1_plus_di_14,
            NULL AS d1_plus_di_14,
            NULL AS w1_minus_di_14,
            NULL AS d1_minus_di_14,
            NULL AS d1_close,
            NULL AS w1_close,
        """
        if state_db.exists() and state_date:
            state_join = "LEFT JOIN state.state_cube s ON a.stock_code = s.stock_code AND s.state_date = CAST(? AS DATE)"
            state_params.append(state_date)
            state_cols = """
                CAST(s.state_date AS VARCHAR) AS state_date,
                s.mn1_state_hex,
                s.w1_state_hex,
                s.d1_state_hex,
                s.w1_ma_state,
                s.d1_ma_state,
                s.w1_bb20_position,
                s.w1_bb20_width,
                s.d1_bb20_position,
                s.d1_bb20_width,
                s.w1_bb50_position,
                s.d1_bb50_position,
                s.w1_adx14,
                s.d1_adx14,
                s.w1_plus_di_14,
                s.d1_plus_di_14,
                s.w1_minus_di_14,
                s.d1_minus_di_14,
                s.d1_close,
                s.w1_close,
            """

        sql = f"""
            WITH panel_current AS (
                SELECT *
                FROM (
                    SELECT
                        p.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY chain_id, node_id, stock_code, source_type
                            ORDER BY as_of_date DESC, updated_at DESC
                        ) AS rn
                    FROM ifind_chain_panel p
                    {where_sql}
                )
                WHERE rn = 1
            ),
            panel_agg AS (
                SELECT
                    chain_id,
                    MAX(chain_name) AS chain_name,
                    node_id,
                    MAX(node_name) AS node_name,
                    MAX(node_position) AS node_position,
                    stock_code,
                    MAX(stock_name) AS stock_name,
                    string_agg(DISTINCT role, ',') AS roles,
                    string_agg(DISTINCT source_type, ',') AS source_types,
                    string_agg(DISTINCT evidence_level, ',') AS evidence_levels,
                    string_agg(DISTINCT node_match_method, ',') AS node_match_methods,
                    COUNT(*) AS panel_records,
                    COUNT(DISTINCT source_type) AS source_type_count,
                    MAX(confidence) AS confidence_max,
                    AVG(confidence) AS confidence_avg,
                    MAX(CASE WHEN manual_verified THEN 1 ELSE 0 END) AS manual_verified_any,
                    MAX(as_of_date) AS panel_latest_date,
                    string_agg(DISTINCT substr(COALESCE(raw_source_ref, ''), 1, 500), ' || ') AS raw_source_refs
                FROM panel_current
                GROUP BY chain_id, node_id, stock_code
            ),
            profile_latest AS (
                SELECT *
                FROM (
                    SELECT
                        stock_code,
                        as_of_date AS profile_as_of_date,
                        sw_l1,
                        sw_l2,
                        sw_l3,
                        main_business,
                        main_product_types,
                        main_product_names,
                        ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY as_of_date DESC) AS rn
                    FROM fund.ifind_industry_chain_profile
                    WHERE as_of_date <= ?
                )
                WHERE rn = 1
            ),
            quality_latest AS (
                SELECT *
                FROM (
                    SELECT
                        stock_code,
                        as_of_date AS quality_as_of_date,
                        quality_score,
                        final_fundamental_score,
                        core_business_purity,
                        cash_quality,
                        earnings_quality,
                        asset_safety_ratio,
                        ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY as_of_date DESC, computed_at DESC) AS rn
                    FROM fund.fundamental_quality_score
                    WHERE as_of_date <= ?
                )
                WHERE rn = 1
            ),
            financial_latest AS (
                SELECT *
                FROM (
                    SELECT
                        stock_code,
                        roe,
                        gross_margin,
                        revenue_yoy,
                        net_profit_yoy,
                        pe_ttm,
                        pb,
                        debt_ratio,
                        ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY collected_at DESC) AS rn
                    FROM fund.ifind_financial_metrics
                )
                WHERE rn = 1
            ),
            event_latest AS (
                SELECT *
                FROM (
                    SELECT
                        stock_code,
                        ef_count,
                        chain_events,
                        latest_chain_event,
                        chain_catalyst,
                        event_date,
                        as_of_date AS event_as_of_date,
                        ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY as_of_date DESC, event_date DESC) AS rn
                    FROM chain_event_cross
                    WHERE as_of_date <= ?
                )
                WHERE rn = 1
            )
            SELECT
                a.*,
                p.sw_l1,
                p.sw_l2,
                p.sw_l3,
                p.main_business,
                p.main_product_types,
                p.main_product_names,
                q.quality_score,
                q.final_fundamental_score,
                q.core_business_purity,
                q.cash_quality,
                q.earnings_quality,
                q.asset_safety_ratio,
                f.roe,
                f.gross_margin,
                f.revenue_yoy,
                f.net_profit_yoy,
                f.pe_ttm,
                f.pb,
                f.debt_ratio,
                e.ef_count,
                e.chain_events,
                e.latest_chain_event,
                e.chain_catalyst,
                CAST(e.event_date AS VARCHAR) AS event_date,
                CAST(e.event_as_of_date AS VARCHAR) AS event_as_of_date,
                {state_cols}
                NULL AS _end_marker
            FROM panel_agg a
            LEFT JOIN profile_latest p ON a.stock_code = p.stock_code
            LEFT JOIN quality_latest q ON a.stock_code = q.stock_code
            LEFT JOIN financial_latest f ON a.stock_code = f.stock_code
            LEFT JOIN event_latest e ON a.stock_code = e.stock_code
            {state_join}
        """
        full_params = panel_params + [cutoff_date, cutoff_date, cutoff_date] + state_params
        cur = con.execute(sql, full_params)
        cols = [desc[0] for desc in cur.description]
        rows = []
        for row in cur.fetchall():
            item = dict(zip(cols, row))
            item.pop("_end_marker", None)
            rows.append(item)
        return rows
    finally:
        con.close()


def fetch_node_source_map(chain_db: Path, cutoff_date: str) -> dict[tuple[str, str], set[str]]:
    con = duckdb.connect(str(chain_db), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT chain_id, node_id, source_type
            FROM ifind_chain_panel
            WHERE as_of_date <= ?
            GROUP BY chain_id, node_id, source_type
            """,
            (cutoff_date,),
        ).fetchall()
    finally:
        con.close()

    result: dict[tuple[str, str], set[str]] = defaultdict(set)
    for chain_id, node_id, source_type in rows:
        result[(str(chain_id), str(node_id))].add(str(source_type))
    return result


def fetch_chain_dynamics(chain_db: Path, cutoff_date: str) -> dict[str, list[dict[str, Any]]]:
    con = duckdb.connect(str(chain_db), read_only=True)
    try:
        rows = con.execute(
            """
            WITH latest AS (
                SELECT
                    chain_id,
                    chain_node,
                    indicator_name,
                    indicator_unit,
                    latest_value,
                    trend,
                    percentile_1y,
                    percentile_3y,
                    as_of_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY chain_id, chain_node, indicator_name
                        ORDER BY as_of_date DESC
                    ) AS rn
                FROM chain_dynamics
                WHERE as_of_date <= ?
            )
            SELECT *
            FROM latest
            WHERE rn = 1
            ORDER BY chain_id, chain_node, indicator_name
            """,
            (cutoff_date,),
        ).fetchall()
        cols = [desc[0] for desc in con.description]
    finally:
        con.close()

    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        item = dict(zip(cols, row))
        item.pop("rn", None)
        chain_id = str(item["chain_id"])
        result[chain_id].append({k: _as_str(v) if isinstance(v, (date, datetime)) else v for k, v in item.items()})

    if "solar" in result and "solar_storage" not in result:
        result["solar_storage"] = result["solar"]
    return result


def compute_evidence_score(row: dict[str, Any]) -> float:
    source_types = _split_csv(row.get("source_types"))
    evidence_levels = _split_csv(row.get("evidence_levels"))
    confidence = (_as_float(row.get("confidence_max")) or 0.0) * 100.0
    source_score = _score_from_values(source_types, SOURCE_WEIGHTS, 50.0)
    level_score = _score_from_values(evidence_levels, EVIDENCE_WEIGHTS, 45.0)
    score = level_score * 0.45 + source_score * 0.35 + confidence * 0.20
    if int(row.get("source_type_count") or 0) >= 2:
        score += 7.0
    if bool(row.get("manual_verified_any")):
        score += 10.0
    return round(max(0.0, min(score, 100.0)), 2)


def compute_fundamental_score(row: dict[str, Any]) -> float:
    final_score = _as_float(row.get("final_fundamental_score"))
    if final_score is not None:
        return round(max(0.0, min(final_score, 100.0)), 2)

    parts: list[float] = []
    gross_margin = _as_float(row.get("gross_margin"))
    roe = _as_float(row.get("roe"))
    revenue_yoy = _as_float(row.get("revenue_yoy"))
    net_profit_yoy = _as_float(row.get("net_profit_yoy"))
    debt_ratio = _as_float(row.get("debt_ratio"))
    if gross_margin is not None:
        parts.append(max(0.0, min(gross_margin, 60.0)) / 60.0 * 100.0)
    if roe is not None:
        parts.append(max(0.0, min(roe, 25.0)) / 25.0 * 100.0)
    if revenue_yoy is not None:
        parts.append(max(0.0, min(revenue_yoy, 80.0)) / 80.0 * 100.0)
    if net_profit_yoy is not None:
        parts.append(max(0.0, min(net_profit_yoy, 100.0)) / 100.0 * 100.0)
    if debt_ratio is not None:
        parts.append(max(0.0, min(100.0 - debt_ratio, 100.0)))
    if not parts:
        return 50.0
    return round(sum(parts) / len(parts), 2)


def _di_bias(plus_di: float | None, minus_di: float | None, adx: float | None) -> float:
    if plus_di is None or minus_di is None:
        return 0.0
    if plus_di > minus_di:
        return 7.0 + (5.0 if adx is not None and adx >= 25 else 0.0)
    if minus_di > plus_di:
        return -7.0 - (5.0 if adx is not None and adx >= 25 else 0.0)
    return 0.0


def compute_technical_score(row: dict[str, Any]) -> float:
    if not row.get("state_date"):
        return 45.0

    score = 50.0
    score += _di_bias(_as_float(row.get("w1_plus_di_14")), _as_float(row.get("w1_minus_di_14")), _as_float(row.get("w1_adx14")))
    score += _di_bias(_as_float(row.get("d1_plus_di_14")), _as_float(row.get("d1_minus_di_14")), _as_float(row.get("d1_adx14")))

    d1_pos = row.get("d1_bb20_position")
    w1_pos = row.get("w1_bb20_position")
    pos_score = {
        "above_middle": 6.0,
        "above_upper": 3.0,
        "at_middle": 1.0,
        "below_middle": -5.0,
        "below_lower": -12.0,
    }
    score += pos_score.get(str(d1_pos), 0.0)
    score += pos_score.get(str(w1_pos), 0.0) * 0.6

    d1_width = row.get("d1_bb20_width")
    plus_di = _as_float(row.get("d1_plus_di_14"))
    minus_di = _as_float(row.get("d1_minus_di_14"))
    if d1_width == "squeeze":
        score += 5.0
    elif d1_width == "expanding" and plus_di is not None and minus_di is not None:
        score += 4.0 if plus_di > minus_di else -4.0

    if row.get("w1_ma_state") and plus_di is not None and minus_di is not None and plus_di > minus_di:
        score += 3.0
    if row.get("d1_ma_state") and plus_di is not None and minus_di is not None and plus_di > minus_di:
        score += 3.0
    return round(max(0.0, min(score, 100.0)), 2)


def compute_dynamic_score(dynamics: list[dict[str, Any]]) -> float:
    if not dynamics:
        return 50.0
    score = 50.0
    trend_points = {
        "turning_up": 4.0,
        "up": 3.0,
        "flat": 0.0,
        "down": -2.0,
        "turning_down": -3.0,
    }
    for item in dynamics:
        score += trend_points.get(str(item.get("trend")), 0.0)
    return round(max(0.0, min(score, 100.0)), 2)


def build_risk_flags(
    row: dict[str, Any],
    evidence_score: float,
    fundamental_score: float,
    node_source_map: dict[tuple[str, str], set[str]],
    dynamics: list[dict[str, Any]],
) -> tuple[list[str], float]:
    flags: list[str] = []
    penalty = 0.0
    if not bool(row.get("manual_verified_any")):
        flags.append("manual_not_verified")
        penalty += 8.0
    if evidence_score < 60:
        flags.append("weak_mapping_evidence")
        penalty += 10.0
    source_types = set(_split_csv(row.get("source_types")))
    if source_types == {"rule_inference"}:
        flags.append("single_source_rule_inference")
        penalty += 5.0
    node_sources = node_source_map.get((str(row.get("chain_id")), str(row.get("node_id"))), set())
    if "ifind_mcp" not in node_sources:
        flags.append("mcp_not_covered_for_node")
        penalty += 3.0
    if not row.get("state_date"):
        flags.append("state_cube_missing")
        penalty += 8.0
    d1_adx = _as_float(row.get("d1_adx14"))
    d1_plus = _as_float(row.get("d1_plus_di_14"))
    d1_minus = _as_float(row.get("d1_minus_di_14"))
    if row.get("d1_bb20_position") == "above_upper" and d1_adx is not None and d1_adx >= 35:
        flags.append("d1_overheated")
        penalty += 6.0
    if d1_plus is not None and d1_minus is not None and d1_minus > d1_plus and d1_adx is not None and d1_adx >= 20:
        flags.append("d1_bearish_di")
        penalty += 8.0
    if fundamental_score < 55:
        flags.append("low_fundamental_score")
        penalty += 7.0
    if all(row.get(k) is None for k in ["roe", "gross_margin", "revenue_yoy", "net_profit_yoy"]):
        if row.get("quality_score") is None and row.get("final_fundamental_score") is None:
            flags.append("financial_metrics_missing")
            penalty += 5.0
        else:
            flags.append("ifind_ttm_metrics_missing")
            penalty += 1.0
    if not dynamics:
        flags.append("chain_dynamic_missing")
        penalty += 3.0
    return flags, penalty


def classify_candidate(
    assistant_score: float,
    evidence_score: float,
    fundamental_score: float,
    technical_score: float,
    manual_verified: bool,
) -> tuple[str, str]:
    if manual_verified:
        review_gate = "production_eligible_after_human_review"
        if assistant_score >= 78 and evidence_score >= 80 and fundamental_score >= 70:
            return review_gate, "核心观察池"
        if assistant_score >= 68 and technical_score >= 50:
            return review_gate, "重点观察池"
        return review_gate, "研究备选池"

    review_gate = "research_only_unverified"
    if assistant_score >= 76 and evidence_score >= 76 and fundamental_score >= 65:
        return review_gate, "优先人工核验"
    if assistant_score >= 66:
        return review_gate, "观察池_待核验"
    if evidence_score >= 58:
        return review_gate, "研究备选_待核验"
    return review_gate, "低优先级_待核验"


def enrich_rows(
    rows: list[dict[str, Any]],
    cutoff_date: str,
    node_source_map: dict[tuple[str, str], set[str]],
    dynamics_by_chain: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        chain_id = str(row.get("chain_id"))
        dynamics = dynamics_by_chain.get(chain_id, [])
        evidence_score = compute_evidence_score(row)
        fundamental_score = compute_fundamental_score(row)
        technical_score = compute_technical_score(row)
        dynamic_score = compute_dynamic_score(dynamics)
        flags, risk_penalty = build_risk_flags(row, evidence_score, fundamental_score, node_source_map, dynamics)
        assistant_score = round(
            evidence_score * 0.30
            + fundamental_score * 0.30
            + technical_score * 0.25
            + dynamic_score * 0.15
            - risk_penalty,
            2,
        )
        assistant_score = max(0.0, min(assistant_score, 100.0))
        manual_verified = bool(row.get("manual_verified_any"))
        review_gate, candidate_bucket = classify_candidate(
            assistant_score,
            evidence_score,
            fundamental_score,
            technical_score,
            manual_verified,
        )
        event_summary = {
            "ef_count": row.get("ef_count"),
            "chain_events": row.get("chain_events"),
            "latest_chain_event": row.get("latest_chain_event"),
            "chain_catalyst": row.get("chain_catalyst"),
            "event_date": _as_str(row.get("event_date")),
            "event_as_of_date": _as_str(row.get("event_as_of_date")),
        }

        item = dict(row)
        item.update(
            {
                "run_as_of_date": cutoff_date,
                "state_date": _as_str(row.get("state_date")),
                "panel_latest_date": _as_str(row.get("panel_latest_date")),
                "manual_verified_any": manual_verified,
                "review_gate": review_gate,
                "candidate_bucket": candidate_bucket,
                "assistant_score": assistant_score,
                "evidence_score": evidence_score,
                "fundamental_score": fundamental_score,
                "technical_score": technical_score,
                "dynamic_score": dynamic_score,
                "risk_penalty": round(risk_penalty, 2),
                "risk_flags_json": json.dumps(flags, ensure_ascii=False),
                "chain_dynamic_summary_json": json.dumps(dynamics, ensure_ascii=False, default=str),
                "event_summary_json": json.dumps(event_summary, ensure_ascii=False, default=str),
            }
        )
        for key in ["chain_events", "latest_chain_event", "chain_catalyst", "event_date", "event_as_of_date", "ef_count"]:
            item.pop(key, None)
        enriched.append(item)
    return enriched


def select_rows(rows: list[dict[str, Any]], top_per_node: int, top_total: int | None, include_all: bool) -> list[dict[str, Any]]:
    rows = sorted(rows, key=lambda r: (_as_float(r.get("assistant_score")) or 0.0), reverse=True)
    if include_all:
        return rows

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("chain_id")), str(row.get("node_id")))].append(row)

    selected: list[dict[str, Any]] = []
    for key in sorted(grouped):
        selected.extend(grouped[key][:top_per_node])
    selected = sorted(selected, key=lambda r: (_as_float(r.get("assistant_score")) or 0.0), reverse=True)
    if top_total is not None:
        selected = selected[:top_total]
    return selected


def write_files(rows: list[dict[str, Any]], output_dir: Path, label: str, summary: dict[str, Any], write_latest: bool) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"chain_fund_manager_assistant_{label}.csv"
    json_path = output_dir / f"chain_fund_manager_assistant_{label}.json"
    latest_json = output_dir / "chain_fund_manager_assistant_latest.json"

    column_names = [name for name, _ in CANDIDATE_COLUMNS]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=column_names, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    payload = {"summary": summary, "rows": rows}
    json_text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    json_path.write_text(json_text, encoding="utf-8")
    paths = {"csv": str(csv_path), "json": str(json_path)}
    if write_latest:
        latest_json.write_text(json_text, encoding="utf-8")
        paths["latest_json"] = str(latest_json)
    return paths


def write_table(chain_db: Path, rows: list[dict[str, Any]], table_name: str) -> None:
    con = duckdb.connect(str(chain_db))
    try:
        cols_sql = ",\n                ".join(f"{name} {typ}" for name, typ in CANDIDATE_COLUMNS)
        con.execute(f"CREATE OR REPLACE TABLE {table_name} ({cols_sql})")
        if not rows:
            return
        names = [name for name, _ in CANDIDATE_COLUMNS]
        placeholders = ", ".join(["?"] * len(names))
        con.executemany(
            f"INSERT INTO {table_name} ({', '.join(names)}) VALUES ({placeholders})",
            [[row.get(name) for name in names] for row in rows],
        )
    finally:
        con.close()


def build_output_label(cutoff_date: str, chains: list[str] | None, require_manual_verified: bool, include_all: bool) -> str:
    parts = [cutoff_date.replace("-", "")]
    if chains:
        safe_chains = "-".join(c.replace("-", "_") for c in chains)
        parts.append(f"chains-{safe_chains}")
    if require_manual_verified:
        parts.append("verified")
    if include_all:
        parts.append("all")
    return "_".join(parts)


def resolve_output_table(chains: list[str] | None, require_manual_verified: bool) -> str:
    if chains or require_manual_verified:
        return "chain_fund_manager_candidates_preview"
    return "chain_fund_manager_candidates"


def build_assistant(
    cutoff_date: str | None,
    state_date_arg: str | None,
    chains: list[str] | None,
    require_manual_verified: bool,
    top_per_node: int,
    top_total: int | None,
    include_all: bool,
    chain_db: Path,
    fund_db: Path,
    state_db: Path,
    output_dir: Path,
) -> dict[str, Any]:
    if not chain_db.exists():
        return {"ok": False, "error": f"Chain DB not found: {chain_db}"}
    if not fund_db.exists():
        return {"ok": False, "error": f"Fundamental DB not found: {fund_db}"}

    con = duckdb.connect(str(chain_db), read_only=True)
    try:
        if state_db.exists():
            con.execute(f"ATTACH '{_escape_path(state_db)}' AS state (READ_ONLY)")
        resolved_cutoff = resolve_cutoff_date(con, cutoff_date)
        resolved_state_date = resolve_state_date(con, resolved_cutoff, state_date_arg) if state_db.exists() else None
    finally:
        con.close()

    rows = fetch_candidate_rows(
        chain_db=chain_db,
        fund_db=fund_db,
        state_db=state_db,
        cutoff_date=resolved_cutoff,
        state_date=resolved_state_date,
        chains=chains,
        require_manual_verified=require_manual_verified,
    )
    node_source_map = fetch_node_source_map(chain_db, resolved_cutoff)
    dynamics_by_chain = fetch_chain_dynamics(chain_db, resolved_cutoff)
    enriched = enrich_rows(rows, resolved_cutoff, node_source_map, dynamics_by_chain)
    selected = select_rows(enriched, top_per_node=top_per_node, top_total=top_total, include_all=include_all)

    label = build_output_label(resolved_cutoff, chains, require_manual_verified, include_all)
    table_name = resolve_output_table(chains, require_manual_verified)
    write_latest = not chains and not require_manual_verified
    bucket_dist = Counter(str(row.get("candidate_bucket")) for row in selected)
    chain_dist = Counter(str(row.get("chain_id")) for row in selected)
    review_gate_dist = Counter(str(row.get("review_gate")) for row in selected)
    summary = {
        "ok": True,
        "purpose": "research_observation_only_not_trading_advice",
        "run_as_of_date": resolved_cutoff,
        "state_date": resolved_state_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_input_records": len(rows),
        "selected_records": len(selected),
        "require_manual_verified": require_manual_verified,
        "include_all": include_all,
        "top_per_node": top_per_node,
        "top_total": top_total,
        "bucket_dist": dict(bucket_dist),
        "chain_dist": dict(chain_dist),
        "review_gate_dist": dict(review_gate_dist),
        "manual_verified_selected": sum(1 for row in selected if row.get("manual_verified_any")),
        "risk_flag_top": dict(Counter(flag for row in selected for flag in json.loads(row.get("risk_flags_json") or "[]")).most_common(20)),
    }
    paths = write_files(selected, output_dir, label, summary, write_latest=write_latest)
    write_table(chain_db, selected, table_name=table_name)
    summary["outputs"] = paths
    summary["duckdb_table"] = f"outputs/industry_chain/industry_chain_evidence.duckdb::{table_name}"
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build industry-chain fund manager assistant observation pool.")
    parser.add_argument("--date", help="Panel cutoff date YYYY-MM-DD. Defaults to latest ifind_chain_panel date.")
    parser.add_argument("--state-date", help="State Cube date. Defaults to latest state_date <= --date.")
    parser.add_argument("--chains", help="Comma-separated chain_id list")
    parser.add_argument("--require-manual-verified", action="store_true")
    parser.add_argument("--top-per-node", type=int, default=20)
    parser.add_argument("--top-total", type=int, default=500)
    parser.add_argument("--all", action="store_true", help="Export all ranked rows, ignoring top limits.")
    parser.add_argument("--db", default=str(DEFAULT_CHAIN_DB))
    parser.add_argument("--fund-db", default=str(DEFAULT_FUND_DB))
    parser.add_argument("--state-db", default=str(DEFAULT_STATE_DB))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    chains = [c.strip() for c in args.chains.split(",") if c.strip()] if args.chains else None
    result = build_assistant(
        cutoff_date=args.date,
        state_date_arg=args.state_date,
        chains=chains,
        require_manual_verified=args.require_manual_verified,
        top_per_node=args.top_per_node,
        top_total=None if args.all else args.top_total,
        include_all=args.all,
        chain_db=Path(args.db),
        fund_db=Path(args.fund_db),
        state_db=Path(args.state_db),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
