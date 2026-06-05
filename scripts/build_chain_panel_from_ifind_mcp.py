#!/usr/bin/env python3
"""build_chain_panel_from_ifind_mcp.py — 通过 iFinD MCP 接口自动拉取产业链成分股。

利用 iFinD MCP 的 search_stocks 工具（支持按行业板块/主题概念/主营业务选股），
自动拉取 config/chain_node_rules.json 中定义的产业链节点成分股，写入 ifind_chain_panel 表。

用法：
    export IFIND_MCP_API_KEY="你的API_KEY"
    source .venv/bin/activate
    python3 scripts/build_chain_panel_from_ifind_mcp.py --date 2026-06-04
    python3 scripts/build_chain_panel_from_ifind_mcp.py --date 2026-06-04 --chains ai_compute,nev

环境变量：
    IFIND_MCP_API_KEY — iFinD MCP API Key（必须）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
CHAIN_DB = ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"
RULES_PATH = ROOT / "config" / "chain_node_rules.json"
QUERY_CONFIG_PATH = ROOT / "config" / "ifind_mcp_chain_queries.json"
MCP_URL = "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-stock-mcp"

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
    source_type       VARCHAR    NOT NULL DEFAULT 'ifind_mcp',
    evidence_level    VARCHAR    NOT NULL DEFAULT 'medium',
    confidence        DOUBLE     NOT NULL DEFAULT 0.85,
    node_match_method VARCHAR,
    manual_verified   BOOLEAN    NOT NULL DEFAULT false,
    raw_source_ref    VARCHAR,
    as_of_date        VARCHAR    NOT NULL,
    updated_at        VARCHAR    NOT NULL,
    PRIMARY KEY (chain_id, node_id, stock_code, as_of_date)
);
"""


def call_search_stocks(api_key: str, query: str) -> dict[str, Any] | None:
    """调用 MCP search_stocks 工具。"""
    headers = {"Content-Type": "application/json", "Authorization": api_key}
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "search_stocks", "arguments": {"query": query}},
        "id": 1,
    }).encode()
    try:
        req = urllib.request.Request(MCP_URL, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            content = data.get("result", {}).get("content", [{}])
            if content:
                text = content[0].get("text", "")
                parsed = json.loads(text)
                return parsed.get("data", {})
    except Exception as e:
        print(f"  [warn] MCP call failed: {e}", file=sys.stderr)
    return None


def parse_search_result(result_text: str) -> list[dict[str, str]]:
    """解析 search_stocks 返回的 Markdown 表格。"""
    stocks: list[dict[str, str]] = []
    lines = [l.strip() for l in result_text.split("\n") if l.strip().startswith("|")]
    for line in lines:
        # Skip header and separator lines
        if "股票代码" in line or "---" in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        parts = [p for p in parts if p]
        if len(parts) >= 2:
            code = parts[0]
            name = parts[1]
            if code and name and not code.startswith("-"):
                stocks.append({"stock_code": code, "stock_name": name})
    return stocks


def normalize_code(raw: str) -> str | None:
    """标准化股票代码。"""
    raw = str(raw).strip().replace("\u3000", " ")
    parts = raw.split()
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    if "." in raw:
        return raw
    return None


def build_query_from_node(node: dict[str, Any]) -> str:
    """从节点规则生成 search_stocks 查询语句。"""
    node_name = node.get("node_name", "")
    product_keywords = node.get("match_rules", {}).get("product_keyword", [])
    business_keywords = node.get("match_rules", {}).get("business_keyword", [])

    # 优先用 product_keyword 生成查询
    if product_keywords:
        kw = product_keywords[0]
        return f"{kw}行业的A股股票"
    if business_keywords:
        kw = business_keywords[0]
        return f"{kw}行业的A股股票"
    return f"{node_name}行业的A股股票"


def load_query_config(path: Path | None) -> dict[str, list[str]]:
    if not path or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): [str(q) for q in v] for k, v in data.get("queries", {}).items()}


def build_queries_for_node(chain_id: str, node: dict[str, Any], query_config: dict[str, list[str]]) -> list[str]:
    key = f"{chain_id}/{node['node_id']}"
    queries = list(query_config.get(key, []))
    queries.append(build_query_from_node(node))
    deduped = []
    seen = set()
    for query in queries:
        if query and query not in seen:
            deduped.append(query)
            seen.add(query)
    return deduped


def run(
    date_str: str,
    target_chains: list[str] | None = None,
    target_nodes: set[str] | None = None,
    dry_run: bool = False,
    query_config_path: Path | None = QUERY_CONFIG_PATH,
    max_per_node: int = 50,
) -> dict[str, Any]:
    api_key = os.environ.get("IFIND_MCP_API_KEY")
    if not api_key and not dry_run:
        return {"ok": False, "error": "IFIND_MCP_API_KEY environment variable not set"}

    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    query_config = load_query_config(query_config_path)
    chains = rules.get("chains", [])
    if target_chains:
        chains = [c for c in chains if c["chain_id"] in target_chains]

    updated_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    stats = {"chains": 0, "nodes": 0, "queries": 0, "stocks_found": 0, "by_chain": {}}

    for chain in chains:
        chain_id = chain["chain_id"]
        chain_name = chain["chain_name"]
        stats["chains"] += 1
        stats["by_chain"][chain_id] = {"nodes": 0, "stocks": 0}

        for node in chain.get("nodes", []):
            node_id = node["node_id"]
            node_key = f"{chain_id}/{node_id}"
            if target_nodes and node_key not in target_nodes and node_id not in target_nodes:
                continue
            node_name = node.get("node_name", "")
            node_position = node.get("position", "")
            role_rules = node.get("role_rules", {})
            stats["nodes"] += 1
            stats["by_chain"][chain_id]["nodes"] += 1

            queries = build_queries_for_node(chain_id, node, query_config)
            node_stocks: dict[str, dict[str, str]] = {}
            query_previews = []
            for query in queries:
                print(f"[MCP] Querying: {chain_id}/{node_id} -> '{query}'")
                stats["queries"] += 1
                if dry_run:
                    query_previews.append({"query": query, "dry_run": True, "stocks": 0})
                    continue

                result = call_search_stocks(api_key or "", query)
                if not result:
                    time.sleep(1)
                    continue

                result_text = result.get("result", "")
                stocks = parse_search_result(result_text)
                query_previews.append({"query": query, "stocks": len(stocks), "preview": result_text[:300]})
                print(f"  -> Found {len(stocks)} stocks")
                for s in stocks:
                    code = normalize_code(s["stock_code"])
                    if code and code not in node_stocks:
                        node_stocks[code] = s
                time.sleep(1.5)

            for s in list(node_stocks.values())[:max_per_node]:
                code = normalize_code(s["stock_code"])
                if not code:
                    continue
                name = s["stock_name"]
                # Derive role from name keyword matching
                leaders = role_rules.get("leader_names", [])
                role = "龙头" if name and any(l in name for l in leaders) else role_rules.get("default", "配套")

                raw_ref = json.dumps({
                    "queries": queries,
                    "source": "ifind_mcp_search_stocks",
                    "mcp_result_preview": query_previews[:5],
                }, ensure_ascii=False)

                records.append({
                    "chain_id": chain_id,
                    "chain_name": chain_name,
                    "node_id": node_id,
                    "node_name": node_name,
                    "node_position": node_position,
                    "stock_code": code,
                    "stock_name": name,
                    "role": role,
                    "source_type": "ifind_mcp",
                    "evidence_level": "medium",
                    "confidence": 0.85,
                    "node_match_method": "mcp_search_stocks",
                    "manual_verified": False,
                    "raw_source_ref": raw_ref,
                    "as_of_date": date_str,
                    "updated_at": updated_at,
                })

            stats["stocks_found"] += len(node_stocks)
            stats["by_chain"][chain_id]["stocks"] += len(node_stocks)

    # Write to DB
    if not dry_run and records:
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
                    (
                        rec["chain_id"],
                        rec["node_id"],
                        rec["stock_code"],
                        rec["as_of_date"],
                    ),
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
        "dry_run": dry_run,
        "records": len(records),
        "stats": stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build chain panel from iFinD MCP search_stocks.")
    parser.add_argument("--date", required=True, help="as_of_date YYYY-MM-DD")
    parser.add_argument("--chains", help="comma-separated chain_ids")
    parser.add_argument("--nodes", help="comma-separated node ids or chain_id/node_id values")
    parser.add_argument("--query-config", default=str(QUERY_CONFIG_PATH), help="Path to MCP fallback query config JSON")
    parser.add_argument("--max-per-node", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true", help="Compute only, do not write DB")
    args = parser.parse_args()

    target_chains = [c.strip() for c in args.chains.split(",")] if args.chains else None
    target_nodes = {n.strip() for n in args.nodes.split(",") if n.strip()} if args.nodes else None
    result = run(
        args.date,
        target_chains=target_chains,
        target_nodes=target_nodes,
        dry_run=args.dry_run,
        query_config_path=Path(args.query_config) if args.query_config else None,
        max_per_node=args.max_per_node,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
