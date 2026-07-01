#!/usr/bin/env python3
"""
chain_rrg_calculator.py — 产业链 RRG 轮动计算

计算各节点相对产业链整体的 RS-Ratio（相对强度）和 RS-Momentum（动量），
输出四象限分类：leading / improving / lagging / weakening

执行:
    source .venv/bin/activate && python3 scripts/chain_rrg_calculator.py --date 2026-06-05
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHAIN_DB = PROJECT_ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"
STATE_CUBE_DB = PROJECT_ROOT / "outputs" / "state_cube" / "state_cube.duckdb"
CHAIN_JSON = PROJECT_ROOT / "outputs" / "industry_chain" / "chain_fund_manager_assistant_latest.json"

P0_CHAINS = {"ai_compute", "semiconductor", "nev"}
WINDOW_DAYS = 10


def _load_chain_json() -> dict[str, Any]:
    with open(CHAIN_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_date(args_date: str | None) -> date:
    if args_date:
        return date.fromisoformat(args_date)
    con = duckdb.connect(str(STATE_CUBE_DB), read_only=True)
    row = con.execute("SELECT MAX(state_date) FROM state_cube").fetchone()
    con.close()
    return row[0] if row and row[0] else date.today()


def _get_node_stocks(payload: dict) -> dict[str, dict[str, list[str]]]:
    """返回 {chain_id: {node_id: [stock_codes]}}"""
    rows = payload.get("rows", [])
    result: dict[str, dict[str, list[str]]] = {}
    for r in rows:
        cid = r.get("chain_id")
        if cid not in P0_CHAINS:
            continue
        pos = r.get("node_position", "unknown")
        code = r.get("stock_code")
        if not code:
            continue
        result.setdefault(cid, {}).setdefault(pos, []).append(code)
    return result


def _calc_node_returns(stocks: list[str], end_date: date, days: int) -> list[float] | None:
    """计算节点近 N 日收益率序列"""
    start_date = end_date - timedelta(days=days * 2 + 5)  # 留足交易日
    placeholders = ",".join([f"'{s}'" for s in stocks])

    con = duckdb.connect(str(STATE_CUBE_DB), read_only=True)
    sql = f"""
        SELECT state_date, AVG(d1_close) as avg_close
        FROM state_cube
        WHERE stock_code IN ({placeholders})
          AND state_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY state_date
        ORDER BY state_date
    """
    rows = con.execute(sql).fetchall()
    con.close()

    if len(rows) < days + 1:
        return None

    closes = [r[1] for r in rows]
    returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] and closes[i - 1] != 0:
            returns.append((closes[i] - closes[i - 1]) / closes[i - 1])
        else:
            returns.append(0.0)

    return returns[-days:] if len(returns) >= days else returns


def _calc_rrg(node_returns: list[float], chain_returns: list[float]) -> dict[str, float]:
    """计算 RRG 指标"""
    if not node_returns or not chain_returns or len(node_returns) != len(chain_returns):
        return {"rs_ratio": 100.0, "rs_momentum": 0.0}

    # RS-Ratio: 节点累计收益 / 链条累计收益 * 100
    node_cum = 1.0
    for r in node_returns:
        node_cum *= (1 + r)
    chain_cum = 1.0
    for r in chain_returns:
        chain_cum *= (1 + r)

    if chain_cum <= 0:
        rs_ratio = 100.0
    else:
        rs_ratio = (node_cum / chain_cum) * 100.0

    # RS-Momentum: RS-Ratio 的 N 日变化率（简化版：近 5 日 vs 前 5 日）
    half = len(node_returns) // 2
    if half > 0:
        node_recent = sum(node_returns[-half:]) / half
        node_prior = sum(node_returns[:half]) / half
        chain_recent = sum(chain_returns[-half:]) / half
        chain_prior = sum(chain_returns[:half]) / half

        rs_recent = (1 + node_recent) / (1 + chain_recent) if (1 + chain_recent) != 0 else 1.0
        rs_prior = (1 + node_prior) / (1 + chain_prior) if (1 + chain_prior) != 0 else 1.0
        rs_momentum = (rs_recent - rs_prior) * 100
    else:
        rs_momentum = 0.0

    return {"rs_ratio": round(rs_ratio, 2), "rs_momentum": round(rs_momentum, 2)}


def _quadrant(rs_ratio: float, rs_momentum: float) -> str:
    if rs_ratio >= 100 and rs_momentum >= 0:
        return "leading"
    elif rs_ratio < 100 and rs_momentum >= 0:
        return "improving"
    elif rs_ratio < 100 and rs_momentum < 0:
        return "lagging"
    else:
        return "weakening"


def calculate_rrg(as_of_date: date) -> list[dict]:
    payload = _load_chain_json()
    node_stocks = _get_node_stocks(payload)

    results = []
    for cid, nodes in node_stocks.items():
        # 先计算整条链的收益率（所有节点平均）
        all_stocks = []
        for stocks in nodes.values():
            all_stocks.extend(stocks)
        chain_returns = _calc_node_returns(all_stocks, as_of_date, WINDOW_DAYS)
        if chain_returns is None:
            continue

        for node_id, stocks in nodes.items():
            node_returns = _calc_node_returns(stocks, as_of_date, WINDOW_DAYS)
            if node_returns is None:
                continue

            rrg = _calc_rrg(node_returns, chain_returns)
            quadrant = _quadrant(rrg["rs_ratio"], rrg["rs_momentum"])

            results.append({
                "chain_id": cid,
                "node_id": node_id,
                "state_date": as_of_date,
                "rs_ratio": rrg["rs_ratio"],
                "rs_momentum": rrg["rs_momentum"],
                "quadrant": quadrant,
                "node_return_pct": round((sum(node_returns) / len(node_returns)) * 100, 2) if node_returns else 0,
                "chain_return_pct": round((sum(chain_returns) / len(chain_returns)) * 100, 2) if chain_returns else 0,
                "updated_at": datetime.now(),
            })

    return results


def write_rrg(records: list[dict]) -> None:
    os.makedirs(CHAIN_DB.parent, exist_ok=True)
    con = duckdb.connect(str(CHAIN_DB))

    con.execute("DROP TABLE IF EXISTS chain_rrg")
    con.execute("""
        CREATE TABLE chain_rrg (
            chain_id VARCHAR,
            node_id VARCHAR,
            state_date DATE,
            rs_ratio DOUBLE,
            rs_momentum DOUBLE,
            quadrant VARCHAR,
            node_return_pct DOUBLE,
            chain_return_pct DOUBLE,
            updated_at TIMESTAMP,
            PRIMARY KEY (chain_id, node_id, state_date)
        )
    """)
    con.execute("CREATE INDEX idx_rrg_chain ON chain_rrg(chain_id)")
    con.execute("CREATE INDEX idx_rrg_date ON chain_rrg(state_date)")
    con.execute("CREATE INDEX idx_rrg_quad ON chain_rrg(quadrant)")

    if records:
        con.executemany("""
            INSERT INTO chain_rrg
            (chain_id, node_id, state_date, rs_ratio, rs_momentum, quadrant,
             node_return_pct, chain_return_pct, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (chain_id, node_id, state_date)
            DO UPDATE SET
                rs_ratio = EXCLUDED.rs_ratio,
                rs_momentum = EXCLUDED.rs_momentum,
                quadrant = EXCLUDED.quadrant,
                node_return_pct = EXCLUDED.node_return_pct,
                chain_return_pct = EXCLUDED.chain_return_pct,
                updated_at = EXCLUDED.updated_at
        """, [
            (r["chain_id"], r["node_id"], r["state_date"], r["rs_ratio"],
             r["rs_momentum"], r["quadrant"], r["node_return_pct"],
             r["chain_return_pct"], r["updated_at"])
            for r in records
        ])

    con.commit()
    con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="产业链 RRG 轮动计算")
    parser.add_argument("--date", type=str, help="计算日期 YYYY-MM-DD")
    args = parser.parse_args()

    as_of_date = _resolve_date(args.date)
    print(f"[chain_rrg] 计算日期: {as_of_date}")

    records = calculate_rrg(as_of_date)
    print(f"[chain_rrg] 计算完成: {len(records)} 条")

    for r in records:
        print(f"  {r['chain_id']}/{r['node_id']}: RS={r['rs_ratio']}, Mom={r['rs_momentum']}, {r['quadrant']}")

    write_rrg(records)
    print(f"[chain_rrg] 已写入: {CHAIN_DB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
