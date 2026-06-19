#!/usr/bin/env python3
"""
build_chain_studio.py — 产业链工作台（新）数据底座构建
Phase 1 MVP：为 /chain-studio 提供 P0 三条链的最小可展示数据

三张目标表（写入 industry_chain_evidence.duckdb）：
- chain_studio_overview   : 产业链动态总览
- chain_studio_nodes      : 产业链节点仓位/状态
- chain_studio_events     : 跨链事件（MVP 留空骨架）

数据源：
- chain_fund_manager_assistant_latest.json  (产业链映射与评分)
- state_cube.duckdb                          (个股技术状态)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

# ── 路径常量 ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHAIN_DB = PROJECT_ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"
STATE_CUBE_DB = PROJECT_ROOT / "outputs" / "state_cube" / "state_cube.duckdb"
CHAIN_JSON = PROJECT_ROOT / "outputs" / "industry_chain" / "chain_fund_manager_assistant_latest.json"

# P0 产业链（逐步扩展）
P0_CHAINS = {
    "ai_compute",
    "semiconductor",
    "nev",
    # 2026-06-18 新增产业链（数据待入库）
    "optical_communication",  # 光通信/光模块
    "memory_chips",           # 存储芯片
    "dc_transformer",         # 直流变压器
    "power_equipment",        # 电力设备
}


def _load_chain_json() -> dict[str, Any]:
    with open(CHAIN_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_state_date(cube_db: Path) -> date:
    """从 state_cube 读取最新 state_date"""
    con = duckdb.connect(str(cube_db), read_only=True)
    row = con.execute("SELECT MAX(state_date) FROM state_cube").fetchone()
    con.close()
    return row[0] if row and row[0] else date.today()


def _build_overview(payload: dict, state_date: date) -> list[dict]:
    """构建 chain_studio_overview 数据"""
    rows = payload.get("rows", [])
    p0_rows = [r for r in rows if r.get("chain_id") in P0_CHAINS]

    # 按 chain_id 聚合
    chains: dict[str, dict] = {}
    for r in p0_rows:
        cid = r["chain_id"]
        if cid not in chains:
            chains[cid] = {
                "chain_id": cid,
                "chain_name": r.get("chain_name", cid),
                "stocks": [],
                "node_positions": {},
            }
        chains[cid]["stocks"].append(r)
        pos = r.get("node_position", "unknown")
        chains[cid]["node_positions"][pos] = chains[cid]["node_positions"].get(pos, 0) + 1

    # 从 state_cube 读取最新技术指标
    con = duckdb.connect(str(STATE_CUBE_DB), read_only=True)
    overview_rows = []
    for cid, info in chains.items():
        stock_codes = [s["stock_code"] for s in info["stocks"] if s.get("stock_code")]
        if not stock_codes:
            continue

        placeholders = ",".join([f"'{s}'" for s in stock_codes])
        sql = f"""
            SELECT
                COUNT(*) AS cnt,
                AVG(CASE WHEN ef_count > 0 THEN 1 ELSE 0 END) AS ef_rate,
                AVG(future_r5) AS avg_r5,
                AVG(future_r20) AS avg_r20,
                AVG(d1_close) AS avg_close,
                MAX(ef_count) AS max_ef
            FROM state_cube
            WHERE stock_code IN ({placeholders})
              AND state_date = '{state_date}'
        """
        stats = con.execute(sql).fetchone()
        cnt, ef_rate, avg_r5, avg_r20, avg_close, max_ef = stats if stats else (0, 0, 0, 0, 0, 0)

        # 计算 prosperity_score (0-100)
        # 基于：ef_rate(40%) + future_r5 正向比例(30%) + 价格动量(30%)
        ef_score = (ef_rate or 0) * 40
        r5_score = max(0, min(1, (avg_r5 or 0) * 10 + 0.5)) * 30 if avg_r5 is not None else 15
        momentum_score = 30 if (avg_r5 or 0) > 0 else 15
        prosperity = min(100, ef_score + r5_score + momentum_score)

        # regime 分段
        if prosperity >= 70:
            regime = "expansion"
        elif prosperity >= 50:
            regime = "recovery"
        elif prosperity >= 30:
            regime = "contraction"
        else:
            regime = "depression"

        # lead_node / lag_node：按 node_position 的 future_r5 均值排序
        pos_scores: dict[str, list[float]] = {}
        for s in info["stocks"]:
            pos = s.get("node_position", "unknown")
            fr5 = s.get("future_r5")
            if fr5 is not None:
                pos_scores.setdefault(pos, []).append(float(fr5))

        pos_avg = {p: sum(v) / len(v) for p, v in pos_scores.items() if v}
        lead_node = max(pos_avg, key=pos_avg.get) if pos_avg else "-"
        lag_node = min(pos_avg, key=pos_avg.get) if pos_avg else "-"

        # event_count：从旧表读取或硬编码 MVP
        event_count = int(max_ef or 0)

        overview_rows.append({
            "chain_id": cid,
            "state_date": state_date,
            "prosperity_score": round(prosperity, 2),
            "regime": regime,
            "event_count": event_count,
            "lead_node": lead_node,
            "lag_node": lag_node,
            "updated_at": datetime.now(),
        })

    con.close()
    return overview_rows


def _build_nodes(payload: dict, state_date: date) -> list[dict]:
    """构建 chain_studio_nodes 数据（上中下游节点粒度）"""
    rows = payload.get("rows", [])
    p0_rows = [r for r in rows if r.get("chain_id") in P0_CHAINS]

    # 按 (chain_id, node_position) 聚合
    nodes: dict[tuple[str, str], dict] = {}
    for r in p0_rows:
        cid = r["chain_id"]
        pos = r.get("node_position", "unknown")
        key = (cid, pos)
        if key not in nodes:
            nodes[key] = {
                "chain_id": cid,
                "node_id": pos,
                "node_name": r.get("node_name", pos),
                "stocks": [],
            }
        nodes[key]["stocks"].append(r)

    con = duckdb.connect(str(STATE_CUBE_DB), read_only=True)
    node_rows = []
    for (cid, pos), info in nodes.items():
        stock_codes = [s["stock_code"] for s in info["stocks"] if s.get("stock_code")]
        if not stock_codes:
            continue

        placeholders = ",".join([f"'{s}'" for s in stock_codes])
        sql = f"""
            SELECT
                AVG(CASE WHEN ef_count > 0 THEN 1 ELSE 0 END) AS ef_rate,
                AVG(future_r5) AS avg_r5,
                AVG(d1_close) AS avg_close,
                MODE(d1_state_hex) AS mode_d1_state,
                MODE(w1_state_hex) AS mode_w1_state
            FROM state_cube
            WHERE stock_code IN ({placeholders})
              AND state_date = '{state_date}'
        """
        stats = con.execute(sql).fetchone()
        ef_rate, avg_r5, avg_close, mode_d1, mode_w1 = stats if stats else (0, 0, 0, None, None)

        # fund_flow_score: 基于 ef_rate (0-100)
        fund_flow_score = round((ef_rate or 0) * 100, 2)

        # position_score: 基于 d1_close 与 w1_close 的关系（简化版）
        position_score = 50.0  # MVP 默认中值

        # momentum_score: 基于 future_r5
        momentum = avg_r5 or 0
        momentum_score = round(max(0, min(100, (momentum * 20 + 50))), 2)

        # state_hex: 取众数
        state_hex = mode_d1 or mode_w1 or "--"

        node_rows.append({
            "chain_id": cid,
            "node_id": pos,
            "node_name": info["node_name"],
            "state_date": state_date,
            "fund_flow_score": fund_flow_score,
            "position_score": position_score,
            "momentum_score": momentum_score,
            "state_hex": str(state_hex),
            "updated_at": datetime.now(),
        })

    con.close()
    return node_rows


def _build_events(payload: dict, state_date: date) -> list[dict]:
    """构建 chain_studio_events 数据
    从 chain_dynamic_summary_json 和 ef_count 变化中合成事件
    """
    rows = payload.get("rows", [])
    p0_rows = [r for r in rows if r.get("chain_id") in P0_CHAINS]

    events = []
    seen = set()

    for r in p0_rows:
        cid = r.get("chain_id")
        stock = r.get("stock_code", "-")

        # 1. 从 chain_dynamic_summary_json 提取价格趋势事件
        dyn_json = r.get("chain_dynamic_summary_json")
        if dyn_json:
            try:
                if isinstance(dyn_json, str):
                    dyn = json.loads(dyn_json)
                else:
                    dyn = dyn_json
                for item in dyn if isinstance(dyn, list) else [dyn]:
                    if not isinstance(item, dict):
                        continue
                    trend = item.get("trend", "")
                    indicator = item.get("indicator_name", "指标")
                    node = item.get("chain_node", "未知环节")

                    if trend in ("turning_up", "turning_down"):
                        impact = 70
                        desc = f"{indicator} 趋势转向{trend.replace('turning_', '')}"
                    elif trend in ("up", "down"):
                        impact = 50
                        desc = f"{indicator} 持续{trend}"
                    elif trend == "flat":
                        impact = 30
                        desc = f"{indicator} 价格持平"
                    else:
                        continue

                    key = (cid, "price_move", node, str(state_date))
                    if key not in seen:
                        seen.add(key)
                        events.append({
                            "chain_id": cid,
                            "event_type": "price_move",
                            "event_source": node,
                            "event_target": stock,
                            "state_date": state_date,
                            "impact_score": impact,
                            "description": desc,
                            "updated_at": datetime.now(),
                        })
            except Exception:
                pass

        # 2. ef_count > 0 生成资金流事件
        ef = r.get("ef_count")
        if ef and ef > 0:
            key = (cid, "fund_flow", stock, str(state_date))
            if key not in seen:
                seen.add(key)
                events.append({
                    "chain_id": cid,
                    "event_type": "fund_flow",
                    "event_source": stock,
                    "event_target": cid,
                    "state_date": state_date,
                    "impact_score": min(80, 40 + ef * 10),
                    "description": f"{stock} 出现 {ef} 个扩张信号",
                    "updated_at": datetime.now(),
                })

        # 3. 状态变化事件（基于 d1_state_hex 变化）
        d1_state = r.get("d1_state_hex", "")
        if d1_state and d1_state.startswith("E"):
            key = (cid, "state_change", stock, str(state_date))
            if key not in seen:
                seen.add(key)
                events.append({
                    "chain_id": cid,
                    "event_type": "state_change",
                    "event_source": stock,
                    "event_target": cid,
                    "state_date": state_date,
                    "impact_score": 60,
                    "description": f"{stock} 日线进入强势状态 {d1_state}",
                    "updated_at": datetime.now(),
                })

    # 去重：同一 chain + type + source + date 只保留 impact 最高的一条
    best = {}
    for e in events:
        key = (e["chain_id"], e["event_type"], e["event_source"], e["state_date"])
        if key not in best or e["impact_score"] > best[key]["impact_score"]:
            best[key] = e

    return list(best.values())


def _write_tables(overview: list[dict], nodes: list[dict], events: list[dict]) -> None:
    """写入 DuckDB，表不存在则创建"""
    os.makedirs(CHAIN_DB.parent, exist_ok=True)
    con = duckdb.connect(str(CHAIN_DB))

    # ── chain_studio_overview ──
    con.execute("DROP TABLE IF EXISTS chain_studio_overview")
    con.execute("""
        CREATE TABLE chain_studio_overview (
            chain_id VARCHAR,
            state_date DATE,
            prosperity_score DOUBLE,
            regime VARCHAR,
            event_count INTEGER,
            lead_node VARCHAR,
            lag_node VARCHAR,
            updated_at TIMESTAMP,
            PRIMARY KEY (chain_id, state_date)
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_cso_chain ON chain_studio_overview(chain_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_cso_date ON chain_studio_overview(state_date)")
    con.execute("DELETE FROM chain_studio_overview")
    if overview:
        con.executemany("""
            INSERT INTO chain_studio_overview
            (chain_id, state_date, prosperity_score, regime, event_count, lead_node, lag_node, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (r["chain_id"], r["state_date"], r["prosperity_score"], r["regime"],
             r["event_count"], r["lead_node"], r["lag_node"], r["updated_at"])
            for r in overview
        ])

    # ── chain_studio_nodes ──
    # 如果旧表有 id 列，先删除重建
    con.execute("DROP TABLE IF EXISTS chain_studio_nodes")
    con.execute("""
        CREATE TABLE chain_studio_nodes (
            chain_id VARCHAR,
            node_id VARCHAR,
            node_name VARCHAR,
            state_date DATE,
            fund_flow_score DOUBLE,
            position_score DOUBLE,
            momentum_score DOUBLE,
            state_hex VARCHAR,
            updated_at TIMESTAMP,
            PRIMARY KEY (chain_id, node_id, state_date)
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_csn_chain ON chain_studio_nodes(chain_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_csn_date ON chain_studio_nodes(state_date)")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_csn_unique ON chain_studio_nodes(chain_id, node_id, state_date)")
    con.execute("DELETE FROM chain_studio_nodes")
    if nodes:
        con.executemany("""
            INSERT INTO chain_studio_nodes
            (chain_id, node_id, node_name, state_date, fund_flow_score, position_score, momentum_score, state_hex, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (chain_id, node_id, state_date)
            DO UPDATE SET
                node_name = EXCLUDED.node_name,
                fund_flow_score = EXCLUDED.fund_flow_score,
                position_score = EXCLUDED.position_score,
                momentum_score = EXCLUDED.momentum_score,
                state_hex = EXCLUDED.state_hex,
                updated_at = EXCLUDED.updated_at
        """, [
            (r["chain_id"], r["node_id"], r["node_name"], r["state_date"],
             r["fund_flow_score"], r["position_score"], r["momentum_score"],
             r["state_hex"], r["updated_at"])
            for r in nodes
        ])

    # ── chain_studio_events ──
    con.execute("DROP TABLE IF EXISTS chain_studio_events")
    con.execute("""
        CREATE TABLE chain_studio_events (
            chain_id VARCHAR,
            event_type VARCHAR,
            event_source VARCHAR,
            event_target VARCHAR,
            state_date DATE,
            impact_score DOUBLE,
            description TEXT,
            updated_at TIMESTAMP,
            PRIMARY KEY (chain_id, event_type, event_source, state_date)
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_cse_chain ON chain_studio_events(chain_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_cse_date ON chain_studio_events(state_date)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_cse_type ON chain_studio_events(event_type)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_cse_date_impact ON chain_studio_events(state_date DESC, impact_score DESC)")
    con.execute("DELETE FROM chain_studio_events")
    if events:
        con.executemany("""
            INSERT INTO chain_studio_events
            (chain_id, event_type, event_source, event_target, state_date, impact_score, description, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (chain_id, event_type, event_source, state_date)
            DO UPDATE SET
                event_target = EXCLUDED.event_target,
                impact_score = EXCLUDED.impact_score,
                description = EXCLUDED.description,
                updated_at = EXCLUDED.updated_at
        """, [
            (r["chain_id"], r["event_type"], r["event_source"], r["event_target"],
             r["state_date"], r["impact_score"], r["description"], r["updated_at"])
            for r in events
        ])

    # ── chain_node_stocks ──
    con.execute("DROP TABLE IF EXISTS chain_node_stocks")
    con.execute("""
        CREATE TABLE chain_node_stocks (
            stock_code VARCHAR,
            stock_name VARCHAR,
            chain_id VARCHAR,
            node_id VARCHAR,
            node_name VARCHAR,
            state_date DATE,
            updated_at TIMESTAMP,
            PRIMARY KEY (stock_code, chain_id, node_id, state_date)
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_cns_chain ON chain_node_stocks(chain_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_cns_node ON chain_node_stocks(node_id)")

    # 从 JSON 填充
    payload = _load_chain_json()
    stock_records = []
    for r in payload.get("rows", []):
        cid = r.get("chain_id")
        if cid not in P0_CHAINS:
            continue
        code = r.get("stock_code")
        if not code:
            continue
        stock_records.append((
            code, r.get("stock_name", ""), cid,
            r.get("node_position", "unknown"), r.get("node_name", ""),
            overview[0]["state_date"] if overview else date.today(),
            datetime.now()
        ))
    if stock_records:
        con.executemany("""
            INSERT INTO chain_node_stocks
            (stock_code, stock_name, chain_id, node_id, node_name, state_date, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (stock_code, chain_id, node_id, state_date)
            DO UPDATE SET
                stock_name = EXCLUDED.stock_name,
                node_name = EXCLUDED.node_name,
                updated_at = EXCLUDED.updated_at
        """, stock_records)

    # ── chain_studio_candidates ──
    con.execute("DROP TABLE IF EXISTS chain_studio_candidates")
    con.execute("""
        CREATE TABLE chain_studio_candidates (
            stock_code VARCHAR,
            stock_name VARCHAR,
            chain_id VARCHAR,
            chain_name VARCHAR,
            node_id VARCHAR,
            node_name VARCHAR,
            assistant_score DOUBLE,
            state_hex VARCHAR,
            ef_count INTEGER,
            review_gate VARCHAR,
            state_date DATE,
            updated_at TIMESTAMP,
            PRIMARY KEY (stock_code, chain_id, state_date)
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_csc_chain ON chain_studio_candidates(chain_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_csc_score ON chain_studio_candidates(assistant_score DESC)")

    candidate_records = []
    for r in payload.get("rows", []):
        cid = r.get("chain_id")
        if cid not in P0_CHAINS:
            continue
        code = r.get("stock_code")
        if not code:
            continue
        candidate_records.append((
            code, r.get("stock_name", ""), cid, r.get("chain_name", ""),
            r.get("node_position", "unknown"), r.get("node_name", ""),
            r.get("assistant_score"), r.get("d1_state_hex") or r.get("w1_state_hex"),
            r.get("ef_count"), r.get("review_gate", ""),
            overview[0]["state_date"] if overview else date.today(),
            datetime.now()
        ))
    if candidate_records:
        con.executemany("""
            INSERT INTO chain_studio_candidates
            (stock_code, stock_name, chain_id, chain_name, node_id, node_name,
             assistant_score, state_hex, ef_count, review_gate, state_date, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (stock_code, chain_id, state_date)
            DO UPDATE SET
                stock_name = EXCLUDED.stock_name,
                chain_name = EXCLUDED.chain_name,
                node_id = EXCLUDED.node_id,
                node_name = EXCLUDED.node_name,
                assistant_score = EXCLUDED.assistant_score,
                state_hex = EXCLUDED.state_hex,
                ef_count = EXCLUDED.ef_count,
                review_gate = EXCLUDED.review_gate,
                updated_at = EXCLUDED.updated_at
        """, candidate_records)

    con.commit()
    con.close()


def main() -> int:
    print("[build_chain_studio] Phase 1 MVP 启动")

    if not CHAIN_JSON.exists():
        print(f"ERROR: 产业链 JSON 不存在: {CHAIN_JSON}", file=sys.stderr)
        return 1
    if not STATE_CUBE_DB.exists():
        print(f"ERROR: State Cube DB 不存在: {STATE_CUBE_DB}", file=sys.stderr)
        return 1

    payload = _load_chain_json()
    state_date = _resolve_state_date(STATE_CUBE_DB)
    print(f"[build_chain_studio] 使用 state_date: {state_date}")

    overview = _build_overview(payload, state_date)
    print(f"[build_chain_studio] overview 行数: {len(overview)}")

    nodes = _build_nodes(payload, state_date)
    print(f"[build_chain_studio] nodes 行数: {len(nodes)}")

    events = _build_events(payload, state_date)
    print(f"[build_chain_studio] events 行数: {len(events)}")

    _write_tables(overview, nodes, events)
    print(f"[build_chain_studio] 已写入: {CHAIN_DB}")

    # 快速验证
    con = duckdb.connect(str(CHAIN_DB), read_only=True)
    for t in ("chain_studio_overview", "chain_studio_nodes", "chain_studio_events"):
        cnt = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {cnt} 行")
    con.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
