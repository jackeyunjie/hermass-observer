#!/usr/bin/env python3
"""build_chain_panel_rule_fallback.py — MCP 不可用时按 rule 兜底生成产业链 panel。

读取 config/chain_node_rules.json，用 name_keyword 在 A 股名称中做规则匹配，
把结果写入 outputs/industry_chain/industry_chain_evidence.duckdb 的 ifind_chain_panel 表。

用法：
    source .venv/bin/activate
    python scripts/build_chain_panel_rule_fallback.py --date 2026-06-18
    python scripts/build_chain_panel_rule_fallback.py --date 2026-06-18 --chains optical_communication,memory_chips

规则优先级（与 chain_node_rules.json 一致）：
    name_keyword > product_keyword > business_keyword > sw_l3_exact > sw_l3_contains
本兜底脚本优先使用 name_keyword；当 name_keyword 为空时，降级使用 product_keyword。
所有兜底记录：
    source_type = 'rule_inference'
    manual_verified = false
    evidence_level 按匹配类型取 global_settings.evidence_level
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
CHAIN_DB = ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"
RULES_PATH = ROOT / "config" / "chain_node_rules.json"

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
    evidence_level    VARCHAR    NOT NULL DEFAULT 'medium',
    confidence        DOUBLE     NOT NULL DEFAULT 0.60,
    node_match_method VARCHAR,
    manual_verified   BOOLEAN    NOT NULL DEFAULT false,
    raw_source_ref    VARCHAR,
    as_of_date        VARCHAR    NOT NULL,
    updated_at        VARCHAR    NOT NULL,
    PRIMARY KEY (chain_id, node_id, stock_code, as_of_date)
);
"""


def load_stock_universe() -> dict[str, str]:
    """从 akshare 拉取 A 股代码-名称映射并标准化为 exchange.code 格式。"""
    try:
        import akshare as ak
    except ImportError as e:
        raise RuntimeError("需要安装 akshare: pip install akshare") from e

    df = ak.stock_info_a_code_name()
    mapping: dict[str, str] = {}
    for _, row in df.iterrows():
        raw_code = str(row["code"]).strip()
        name = str(row["name"]).strip().replace(" ", "")
        if len(raw_code) == 6 and raw_code.isdigit():
            prefix = "SH" if raw_code.startswith(("60", "68", "90", "11")) else "SZ"
            mapping[f"{raw_code}.{prefix}"] = name
    return mapping


def match_stocks_for_node(
    node: dict[str, Any],
    stock_universe: dict[str, str],
    conf_map: dict[str, float],
    evidence_map: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """按优先级匹配单个节点的股票。"""
    matched: dict[str, dict[str, Any]] = {}
    rules = node.get("match_rules", {})

    priority = [
        ("name_keyword", rules.get("name_keyword", [])),
        ("product_keyword", rules.get("product_keyword", [])),
        ("business_keyword", rules.get("business_keyword", [])),
    ]

    for match_type, keywords in priority:
        if not keywords:
            continue
        for kw in keywords:
            for code, name in stock_universe.items():
                if code in matched:
                    continue
                if kw in name:
                    matched[code] = {
                        "stock_code": code,
                        "stock_name": name,
                        "confidence": conf_map.get(match_type, 0.60),
                        "evidence_level": evidence_map.get(match_type, "weak"),
                        "match_method": match_type,
                        "matched_keyword": kw,
                    }
        # 一旦 name_keyword 匹配到股票，就不再降级（保持高置信）
        if matched and match_type == "name_keyword":
            break

    return matched


def run(
    date_str: str,
    target_chains: list[str] | None = None,
    max_per_node: int = 50,
) -> dict[str, Any]:
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    conf_map = rules.get("global_settings", {}).get("confidence", {})
    evidence_map = rules.get("global_settings", {}).get("evidence_level", {})
    chains = rules.get("chains", [])
    if target_chains:
        chains = [c for c in chains if c["chain_id"] in target_chains]

    print("[fallback] 加载 A 股名称库...", file=sys.stderr)
    stock_universe = load_stock_universe()
    print(f"[fallback] 共 {len(stock_universe)} 只股票", file=sys.stderr)

    updated_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    stats = {"chains": 0, "nodes": 0, "stocks_found": 0, "by_chain": {}}

    for chain in chains:
        chain_id = chain["chain_id"]
        chain_name = chain["chain_name"]
        stats["chains"] += 1
        stats["by_chain"][chain_id] = {"nodes": 0, "stocks": 0}

        for node in chain.get("nodes", []):
            node_id = node["node_id"]
            node_name = node.get("node_name", "")
            node_position = node.get("position", "")
            role_rules = node.get("role_rules", {})
            stats["nodes"] += 1
            stats["by_chain"][chain_id]["nodes"] += 1

            matched = match_stocks_for_node(node, stock_universe, conf_map, evidence_map)
            limited = list(matched.values())[:max_per_node]

            for m in limited:
                name = m["stock_name"]
                leaders = role_rules.get("leader_names", [])
                role = "龙头" if name and any(l in name for l in leaders) else role_rules.get("default", "配套")

                raw_ref = json.dumps({
                    "match_method": m["match_method"],
                    "matched_keyword": m["matched_keyword"],
                    "source": "rule_inference_fallback",
                    "note": "MCP unavailable; matched by name/product keyword",
                }, ensure_ascii=False)

                records.append({
                    "chain_id": chain_id,
                    "chain_name": chain_name,
                    "node_id": node_id,
                    "node_name": node_name,
                    "node_position": node_position,
                    "stock_code": m["stock_code"],
                    "stock_name": name,
                    "role": role,
                    "source_type": "rule_inference",
                    "evidence_level": m["evidence_level"],
                    "confidence": m["confidence"],
                    "node_match_method": m["match_method"],
                    "manual_verified": False,
                    "raw_source_ref": raw_ref,
                    "as_of_date": date_str,
                    "updated_at": updated_at,
                })

            stats["stocks_found"] += len(limited)
            stats["by_chain"][chain_id]["stocks"] += len(limited)
            print(
                f"[fallback] {chain_id}/{node_id}: {len(limited)} stocks "
                f"(method={limited[0]['match_method'] if limited else 'none'})",
                file=sys.stderr,
            )

    # Write to DB
    if records:
        CHAIN_DB.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(CHAIN_DB))
        try:
            con.execute(CREATE_IFIND_CHAIN_PANEL)
            for rec in records:
                existing_manual_verified = con.execute(
                    """
                    SELECT manual_verified
                    FROM ifind_chain_panel
                    WHERE chain_id = ?
                      AND node_id = ?
                      AND stock_code = ?
                      AND as_of_date = ?
                    """,
                    (rec["chain_id"], rec["node_id"], rec["stock_code"], rec["as_of_date"]),
                ).fetchone()
                manual_verified = (
                    bool(existing_manual_verified[0])
                    if existing_manual_verified is not None
                    else bool(rec["manual_verified"])
                )
                con.execute(
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
                        rec["node_match_method"], manual_verified, rec["raw_source_ref"],
                        rec["as_of_date"], rec["updated_at"],
                    ),
                )
        finally:
            con.close()

    return {
        "ok": True,
        "date": date_str,
        "records": len(records),
        "stats": stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build chain panel from rule fallback when MCP unavailable.")
    parser.add_argument("--date", required=True, help="as_of_date YYYY-MM-DD")
    parser.add_argument("--chains", help="comma-separated chain_ids")
    parser.add_argument("--max-per-node", type=int, default=50)
    args = parser.parse_args()

    target_chains = [c.strip() for c in args.chains.split(",")] if args.chains else None
    result = run(args.date, target_chains=target_chains, max_per_node=args.max_per_node)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
