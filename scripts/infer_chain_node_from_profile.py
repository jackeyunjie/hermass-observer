#!/usr/bin/env python3
"""infer_chain_node_from_profile.py — 基于 ifind_industry_chain_profile 自动推断产业链节点。

基于 config/chain_node_rules.json 中的匹配规则，将现有 fundamental_evidence.duckdb 中的
个股身份数据映射到产业链节点，生成 ifind_chain_panel 表记录。

用法：
    source .venv/bin/activate
    python3 scripts/infer_chain_node_from_profile.py --date 2026-05-21
    python3 scripts/infer_chain_node_from_profile.py --date 2026-05-21 --dry-run
    python3 scripts/infer_chain_node_from_profile.py --date 2026-05-21 --chains ai_compute,nev

输出：
    outputs/industry_chain/industry_chain_evidence.duckdb → ifind_chain_panel

字段规范（按 Codex 要求）：
    chain_id, chain_name, node_id, node_name, node_position,
    stock_code, stock_name, role,
    source_type, evidence_level, confidence, node_match_method,
    manual_verified, raw_source_ref,
    as_of_date, updated_at
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
FUND_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
CHAIN_DB = ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"
RULES_PATH = ROOT / "config" / "chain_node_rules.json"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

CREATE_IFIND_CHAIN_PANEL = """
CREATE TABLE IF NOT EXISTS ifind_chain_panel (
    chain_id          VARCHAR    NOT NULL,
    chain_name        VARCHAR    NOT NULL,
    node_id           VARCHAR    NOT NULL,
    node_name         VARCHAR    NOT NULL,
    node_position     VARCHAR,
    stock_code        VARCHAR    NOT NULL,
    stock_name        VARCHAR,
    role              VARCHAR,
    source_type       VARCHAR    NOT NULL DEFAULT 'rule_inference',
    evidence_level    VARCHAR    NOT NULL DEFAULT 'weak',
    confidence        DOUBLE     NOT NULL DEFAULT 0.0,
    node_match_method VARCHAR,
    manual_verified   BOOLEAN    NOT NULL DEFAULT false,
    raw_source_ref    VARCHAR,
    as_of_date        VARCHAR    NOT NULL,
    updated_at        VARCHAR    NOT NULL,
    PRIMARY KEY (chain_id, node_id, stock_code, as_of_date)
);
"""

# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------


def load_rules(path: Path = RULES_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"chain_node_rules.json not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Profile loading
# ---------------------------------------------------------------------------


def load_profiles(con: duckdb.DuckDBPyConnection, date_str: str) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT stock_code, stock_name, sw_l1, sw_l2, sw_l3,
               main_business, main_product_types, main_product_names
        FROM ifind_industry_chain_profile
        WHERE as_of_date = ?
        """,
        (date_str,),
    ).fetchdf().to_dict("records")
    return rows


def load_segments(con: duckdb.DuckDBPyConnection, date_str: str) -> dict[str, list[dict]]:
    """按 stock_code 分组加载营收构成数据。"""
    rows = con.execute(
        """
        SELECT stock_code, metric_name, metric_value, report_period, segment_basis
        FROM ifind_business_segment_facts
        WHERE as_of_date = ?
          AND segment_basis IN ('按产品', '按业务')
        ORDER BY stock_code, report_period DESC
        """,
        (date_str,),
    ).fetchdf().to_dict("records")
    result: dict[str, list[dict]] = {}
    for r in rows:
        result.setdefault(r["stock_code"], []).append(r)
    return result


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------


def _match_name_keyword(stock_name: str, keywords: list[str]) -> bool:
    if not stock_name or not keywords:
        return False
    return any(kw in stock_name for kw in keywords)


def _match_product_keyword(product_types: str | None, product_names: str | None, keywords: list[str]) -> bool:
    text = " ".join(filter(None, [product_types or "", product_names or ""]))
    if not text or not keywords:
        return False
    return any(kw in text for kw in keywords)


def _match_business_keyword(business: str | None, keywords: list[str]) -> bool:
    if not business or not keywords:
        return False
    return any(kw in business for kw in keywords)


def _match_sw_l3_exact(sw_l3: str | None, values: list[str]) -> bool:
    if not sw_l3 or not values:
        return False
    return sw_l3 in values


def _match_sw_l3_contains(sw_l3: str | None, values: list[str]) -> bool:
    if not sw_l3 or not values:
        return False
    return any(v in sw_l3 for v in values)


def match_stock_to_node(profile: dict[str, Any], node: dict[str, Any], global_settings: dict[str, Any]) -> tuple[str | None, float, str]:
    """返回 (match_method, confidence, evidence_level) 或 (None, 0, 'none')。"""
    rules = node.get("match_rules", {})
    conf = global_settings.get("confidence", {})
    ev_levels = global_settings.get("evidence_level", {})
    priority = global_settings.get("match_priority", [])

    stock_name = profile.get("stock_name") or ""
    product_types = profile.get("main_product_types") or ""
    product_names = profile.get("main_product_names") or ""
    business = profile.get("main_business") or ""
    sw_l3 = profile.get("sw_l3") or ""

    # 按优先级顺序匹配
    for method in priority:
        if method == "name_keyword":
            kws = rules.get("name_keyword", [])
            if _match_name_keyword(stock_name, kws):
                return "name_keyword", conf.get("name_keyword_match", 0.95), ev_levels.get("name_keyword_match", "strong")
        elif method == "product_keyword":
            kws = rules.get("product_keyword", [])
            if _match_product_keyword(product_types, product_names, kws):
                return "product_keyword", conf.get("product_keyword_match", 0.85), ev_levels.get("product_keyword_match", "medium")
        elif method == "business_keyword":
            kws = rules.get("business_keyword", [])
            if _match_business_keyword(business, kws):
                return "business_keyword", conf.get("business_keyword_match", 0.80), ev_levels.get("business_keyword_match", "medium")
        elif method == "sw_l3_exact":
            vals = rules.get("sw_l3_exact", [])
            if _match_sw_l3_exact(sw_l3, vals):
                return "sw_l3_exact", conf.get("sw_l3_exact_match", 0.75), ev_levels.get("sw_l3_exact_match", "weak")
        elif method == "sw_l3_contains":
            vals = rules.get("sw_l3_contains", [])
            if _match_sw_l3_contains(sw_l3, vals):
                return "sw_l3_contains", conf.get("sw_l3_contains_match", 0.60), ev_levels.get("sw_l3_contains_match", "weak")

    return None, 0.0, "none"


def derive_role(stock_name: str, role_rules: dict[str, Any]) -> str:
    leaders = role_rules.get("leader_names", [])
    if stock_name and any(leader in stock_name for leader in leaders):
        return "龙头"
    return role_rules.get("default", "配套")


# ---------------------------------------------------------------------------
# Main inference
# ---------------------------------------------------------------------------


def infer_chain_nodes(
    date_str: str,
    target_chains: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    rules = load_rules()
    global_settings = rules.get("global_settings", {})
    chains = rules.get("chains", [])

    if target_chains:
        chains = [c for c in chains if c["chain_id"] in target_chains]

    if not chains:
        raise ValueError("No chains to process after filtering.")

    updated_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    stats = {"chains": 0, "nodes": 0, "stocks_scanned": 0, "matches": 0, "by_chain": {}}

    # Load profiles
    fund_con = duckdb.connect(str(FUND_DB), read_only=True)
    try:
        profiles = load_profiles(fund_con, date_str)
    finally:
        fund_con.close()

    stats["stocks_scanned"] = len(profiles)

    for chain in chains:
        chain_id = chain["chain_id"]
        chain_name = chain["chain_name"]
        stats["chains"] += 1
        stats["by_chain"][chain_id] = {"matches": 0, "nodes": 0}

        for node in chain.get("nodes", []):
            node_id = node["node_id"]
            node_name = node["node_name"]
            node_position = node.get("position", "")
            role_rules = node.get("role_rules", {})
            stats["nodes"] += 1
            stats["by_chain"][chain_id]["nodes"] += 1

            for profile in profiles:
                match_method, confidence, evidence_level = match_stock_to_node(profile, node, global_settings)
                if match_method is None:
                    continue

                stock_code = profile.get("stock_code", "")
                stock_name = profile.get("stock_name", "")
                role = derive_role(stock_name, role_rules)

                raw_source_ref = json.dumps(
                    {
                        "match_method": match_method,
                        "sw_l3": profile.get("sw_l3"),
                        "product_types": profile.get("main_product_types"),
                        "business": profile.get("main_business")[:200] if profile.get("main_business") else None,
                    },
                    ensure_ascii=False,
                )

                records.append(
                    {
                        "chain_id": chain_id,
                        "chain_name": chain_name,
                        "node_id": node_id,
                        "node_name": node_name,
                        "node_position": node_position,
                        "stock_code": stock_code,
                        "stock_name": stock_name,
                        "role": role,
                        "source_type": "rule_inference",
                        "evidence_level": evidence_level,
                        "confidence": confidence,
                        "node_match_method": match_method,
                        "manual_verified": False,
                        "raw_source_ref": raw_source_ref,
                        "as_of_date": date_str,
                        "updated_at": updated_at,
                    }
                )
                stats["matches"] += 1
                stats["by_chain"][chain_id]["matches"] += 1

    # Write to DB
    if not dry_run and records:
        CHAIN_DB.parent.mkdir(parents=True, exist_ok=True)
        chain_con = duckdb.connect(str(CHAIN_DB))
        try:
            chain_con.execute(CREATE_IFIND_CHAIN_PANEL)
            for rec in records:
                chain_con.execute(
                    """
                    INSERT OR REPLACE INTO ifind_chain_panel
                    (chain_id, chain_name, node_id, node_name, node_position,
                     stock_code, stock_name, role, source_type, evidence_level,
                     confidence, node_match_method, manual_verified, raw_source_ref,
                     as_of_date, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec["chain_id"], rec["chain_name"], rec["node_id"], rec["node_name"],
                        rec["node_position"], rec["stock_code"], rec["stock_name"], rec["role"],
                        rec["source_type"], rec["evidence_level"], rec["confidence"],
                        rec["node_match_method"], rec["manual_verified"], rec["raw_source_ref"],
                        rec["as_of_date"], rec["updated_at"],
                    ),
                )
        finally:
            chain_con.close()

    return {
        "ok": True,
        "date": date_str,
        "dry_run": dry_run,
        "records": len(records),
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Infer chain nodes from iFinD industry chain profile.")
    parser.add_argument("--date", required=True, help="as_of_date YYYY-MM-DD")
    parser.add_argument("--chains", help="comma-separated chain_ids, e.g. ai_compute,nev")
    parser.add_argument("--dry-run", action="store_true", help="Compute only, do not write DB")
    args = parser.parse_args()

    target_chains = [c.strip() for c in args.chains.split(",")] if args.chains else None

    result = infer_chain_nodes(args.date, target_chains=target_chains, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
