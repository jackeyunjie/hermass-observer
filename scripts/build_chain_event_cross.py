#!/usr/bin/env python3
"""
build_chain_event_cross.py — 产业链跨链事件填充

从 chain_fund_manager_assistant_latest.json 中提取事件数据，
识别价格趋势变化、资金流信号、状态变化三类事件，
写入 industry_chain_evidence.duckdb 的 chain_studio_events 表。

执行:
    source .venv/bin/activate && python3 scripts/build_chain_event_cross.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHAIN_DB = PROJECT_ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"
CHAIN_JSON = PROJECT_ROOT / "outputs" / "industry_chain" / "chain_fund_manager_assistant_latest.json"
STATE_CUBE_DB = PROJECT_ROOT / "outputs" / "state_cube" / "state_cube.duckdb"

P0_CHAINS = {"ai_compute", "semiconductor", "nev"}


def _load_chain_json() -> dict[str, Any]:
    with open(CHAIN_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_state_date() -> date:
    con = duckdb.connect(str(STATE_CUBE_DB), read_only=True)
    row = con.execute("SELECT MAX(state_date) FROM state_cube").fetchone()
    con.close()
    return row[0] if row and row[0] else date.today()


def build_events(payload: dict, state_date: date) -> list[dict]:
    """构建 chain_studio_events 数据"""
    rows = payload.get("rows", [])
    p0_rows = [r for r in rows if r.get("chain_id") in P0_CHAINS]

    events = []
    seen = set()

    for r in p0_rows:
        cid = r.get("chain_id")
        stock = r.get("stock_code", "-")

        # 1. 价格趋势事件
        dyn_json = r.get("chain_dynamic_summary_json")
        if dyn_json:
            try:
                dyn = json.loads(dyn_json) if isinstance(dyn_json, str) else dyn_json
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

        # 2. 资金流事件
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

        # 3. 状态变化事件
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

    # 去重保留 impact 最高
    best = {}
    for e in events:
        key = (e["chain_id"], e["event_type"], e["event_source"], e["state_date"])
        if key not in best or e["impact_score"] > best[key]["impact_score"]:
            best[key] = e

    return list(best.values())


def write_events(events: list[dict]) -> None:
    os.makedirs(CHAIN_DB.parent, exist_ok=True)
    con = duckdb.connect(str(CHAIN_DB))

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
            (e["chain_id"], e["event_type"], e["event_source"], e["event_target"],
             e["state_date"], e["impact_score"], e["description"], e["updated_at"])
            for e in events
        ])

    con.commit()
    con.close()


def main() -> int:
    print("[build_chain_event_cross] 启动")

    if not CHAIN_JSON.exists():
        print(f"ERROR: 产业链 JSON 不存在: {CHAIN_JSON}", file=sys.stderr)
        return 1

    payload = _load_chain_json()
    state_date = _resolve_state_date()
    print(f"[build_chain_event_cross] 使用 state_date: {state_date}")

    events = build_events(payload, state_date)
    print(f"[build_chain_event_cross] 事件数: {len(events)}")

    write_events(events)
    print(f"[build_chain_event_cross] 已写入: {CHAIN_DB}")

    con = duckdb.connect(str(CHAIN_DB), read_only=True)
    cnt = con.execute("SELECT COUNT(*) FROM chain_studio_events").fetchone()[0]
    print(f"  chain_studio_events: {cnt} 行")
    con.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
