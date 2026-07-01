#!/usr/bin/env python3
"""
chain_propagation_analyzer.py — 产业链传导分析

计算上中下游节点间的传导强度、时滞和方向，
识别利润/资金/动量在产业链内部的迁移路径。

执行:
    source .venv/bin/activate && python3 scripts/chain_propagation_analyzer.py --date 2026-06-05
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

P0_CHAINS = {"ai_compute", "semiconductor", "nev"}
PROPAGATION_PATHS = [
    ("上游", "中游"),
    ("中游", "下游"),
    ("上游", "下游"),
    ("上游-配套", "中游"),
    ("中游-配套", "下游"),
]


def _resolve_date(args_date: str | None) -> date:
    if args_date:
        return date.fromisoformat(args_date)
    con = duckdb.connect(str(STATE_CUBE_DB), read_only=True)
    row = con.execute("SELECT MAX(state_date) FROM state_cube").fetchone()
    con.close()
    return row[0] if row and row[0] else date.today()


def _get_node_scores(as_of_date: date) -> dict[str, dict[str, dict[str, float]]]:
    """读取 chain_studio_nodes 的各节点评分"""
    con = duckdb.connect(str(CHAIN_DB), read_only=True)
    rows = con.execute(f"""
        SELECT chain_id, node_id, fund_flow_score, momentum_score, position_score, state_hex
        FROM chain_studio_nodes
        WHERE state_date = '{as_of_date}'
    """).fetchall()
    con.close()

    result: dict[str, dict[str, dict[str, float]]] = {}
    for r in rows:
        cid, nid, ff, mom, pos, state_hex = r
        if cid not in P0_CHAINS:
            continue
        result.setdefault(cid, {})[nid] = {
            "fund_flow_score": ff or 0,
            "momentum_score": mom or 0,
            "position_score": pos or 0,
            "state_hex": state_hex or "--",
        }
    return result


def _get_historical_node_returns(chain_id: str, node_id: str, end_date: date, days: int = 20) -> list[float] | None:
    """从 state_cube 读取某节点历史收益率（用节点内所有股的平均）"""
    # 先读取该节点对应的股票列表
    con = duckdb.connect(str(CHAIN_DB), read_only=True)
    stock_rows = con.execute(f"""
        SELECT DISTINCT stock_code FROM ifind_chain_panel
        WHERE chain_id = '{chain_id}'
          AND node_position = '{node_id}'
    """).fetchall()
    con.close()

    stocks = [r[0] for r in stock_rows if r[0]]
    if not stocks:
        return None

    start_date = end_date - timedelta(days=days * 2 + 10)
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

    if len(rows) < 5:
        return None

    closes = [r[1] for r in rows]
    returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] and closes[i - 1] != 0:
            returns.append((closes[i] - closes[i - 1]) / closes[i - 1])
        else:
            returns.append(0.0)
    return returns


def _calc_correlation_and_lag(src_returns: list[float], tgt_returns: list[float], max_lag: int = 5) -> tuple[float, int]:
    """计算最优时滞和相关性"""
    if len(src_returns) < max_lag * 2 or len(tgt_returns) < max_lag * 2:
        return 0.0, 0

    min_len = min(len(src_returns), len(tgt_returns))
    src = src_returns[-min_len:]
    tgt = tgt_returns[-min_len:]

    best_corr = -999
    best_lag = 0

    for lag in range(0, max_lag + 1):
        if len(src) <= lag:
            continue
        s = src[:-lag] if lag > 0 else src
        t = tgt[lag:]
        min_l = min(len(s), len(t))
        if min_l < 3:
            continue
        s = s[:min_l]
        t = t[:min_l]

        mean_s = sum(s) / len(s)
        mean_t = sum(t) / len(t)

        num = sum((a - mean_s) * (b - mean_t) for a, b in zip(s, t))
        den_s = sum((a - mean_s) ** 2 for a in s) ** 0.5
        den_t = sum((b - mean_t) ** 2 for b in t) ** 0.5

        if den_s == 0 or den_t == 0:
            corr = 0.0
        else:
            corr = num / (den_s * den_t)

        if corr > best_corr:
            best_corr = corr
            best_lag = lag

    return round(best_corr, 3), best_lag


def calculate_propagation(as_of_date: date) -> list[dict]:
    """计算产业链传导路径"""
    node_scores = _get_node_scores(as_of_date)
    results = []

    for cid, nodes in node_scores.items():
        for src_node, tgt_node in PROPAGATION_PATHS:
            if src_node not in nodes or tgt_node not in nodes:
                continue

            src_scores = nodes[src_node]
            tgt_scores = nodes[tgt_node]

            # 计算历史收益率相关性及时滞
            src_returns = _get_historical_node_returns(cid, src_node, as_of_date)
            tgt_returns = _get_historical_node_returns(cid, tgt_node, as_of_date)

            if src_returns and tgt_returns:
                corr, lag = _calc_correlation_and_lag(src_returns, tgt_returns)
            else:
                corr, lag = 0.0, 0

            # 传导强度：综合相关性 + 动量差 + 资金流差
            momentum_diff = tgt_scores["momentum_score"] - src_scores["momentum_score"]
            fund_flow_diff = tgt_scores["fund_flow_score"] - src_scores["fund_flow_score"]

            # 简化强度公式
            strength = max(0, min(100,
                abs(corr) * 40 +
                max(-20, min(20, momentum_diff)) * 1.5 +
                max(-20, min(20, fund_flow_diff)) * 0.5 +
                30
            ))

            # 传导方向判断
            if corr > 0.3 and lag > 0:
                direction = f"{src_node} → {tgt_node}"
                status = "active"
            elif corr > 0.1:
                direction = f"{src_node} → {tgt_node}（弱）"
                status = "weak"
            else:
                direction = f"{src_node} → {tgt_node}（中断）"
                status = "stalled"

            results.append({
                "chain_id": cid,
                "source_node": src_node,
                "target_node": tgt_node,
                "state_date": as_of_date,
                "strength": round(strength, 2),
                "correlation": corr,
                "lag_days": lag,
                "direction": direction,
                "status": status,
                "momentum_diff": round(momentum_diff, 2),
                "fund_flow_diff": round(fund_flow_diff, 2),
                "updated_at": datetime.now(),
            })

    return results


def write_propagation(records: list[dict]) -> None:
    os.makedirs(CHAIN_DB.parent, exist_ok=True)
    con = duckdb.connect(str(CHAIN_DB))

    con.execute("DROP TABLE IF EXISTS chain_propagation")
    con.execute("""
        CREATE TABLE chain_propagation (
            chain_id VARCHAR,
            source_node VARCHAR,
            target_node VARCHAR,
            state_date DATE,
            strength DOUBLE,
            correlation DOUBLE,
            lag_days INTEGER,
            direction VARCHAR,
            status VARCHAR,
            momentum_diff DOUBLE,
            fund_flow_diff DOUBLE,
            updated_at TIMESTAMP,
            PRIMARY KEY (chain_id, source_node, target_node, state_date)
        )
    """)
    con.execute("CREATE INDEX idx_prop_chain ON chain_propagation(chain_id)")
    con.execute("CREATE INDEX idx_prop_date ON chain_propagation(state_date)")
    con.execute("CREATE INDEX idx_prop_status ON chain_propagation(status)")

    if records:
        con.executemany("""
            INSERT INTO chain_propagation
            (chain_id, source_node, target_node, state_date, strength, correlation,
             lag_days, direction, status, momentum_diff, fund_flow_diff, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (chain_id, source_node, target_node, state_date)
            DO UPDATE SET
                strength = EXCLUDED.strength,
                correlation = EXCLUDED.correlation,
                lag_days = EXCLUDED.lag_days,
                direction = EXCLUDED.direction,
                status = EXCLUDED.status,
                momentum_diff = EXCLUDED.momentum_diff,
                fund_flow_diff = EXCLUDED.fund_flow_diff,
                updated_at = EXCLUDED.updated_at
        """, [
            (r["chain_id"], r["source_node"], r["target_node"], r["state_date"],
             r["strength"], r["correlation"], r["lag_days"], r["direction"],
             r["status"], r["momentum_diff"], r["fund_flow_diff"], r["updated_at"])
            for r in records
        ])

    con.commit()
    con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="产业链传导分析")
    parser.add_argument("--date", type=str, help="计算日期 YYYY-MM-DD")
    args = parser.parse_args()

    as_of_date = _resolve_date(args.date)
    print(f"[chain_propagation] 计算日期: {as_of_date}")

    records = calculate_propagation(as_of_date)
    print(f"[chain_propagation] 计算完成: {len(records)} 条")

    for r in records:
        print(f"  {r['chain_id']}: {r['source_node']} → {r['target_node']} | "
              f"strength={r['strength']}, corr={r['correlation']}, lag={r['lag_days']}d, status={r['status']}")

    write_propagation(records)
    print(f"[chain_propagation] 已写入: {CHAIN_DB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
