#!/usr/bin/env python3
"""
chain_review_backfill.py — 产业链判断 5/20 日复盘回填

读取 agent_judgments 中 industry_chain 类型的判断，
计算 state_date + 5 日和 +20 日的实际收益，回填到 judgment_outcomes。

Usage:
    source .venv/bin/activate && python3 scripts/chain_review_backfill.py --date 2026-06-05 --horizon 5
    source .venv/bin/activate && python3 scripts/chain_review_backfill.py --date 2026-06-05 --horizon 20
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parent.parent
AGENT_MEMORY_DB = ROOT / "outputs" / "agent_memory" / "AgentMemory.duckdb"
STATE_CUBE_DB = ROOT / "outputs" / "state_cube" / "state_cube.duckdb"


def _ensure_outcomes_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS judgment_outcomes (
            judgment_id      VARCHAR NOT NULL,
            actual_date      DATE NOT NULL,
            actual_value     DOUBLE,
            direction_correct BOOLEAN,
            strength_deviation DOUBLE,
            scenario_label   VARCHAR,
            PRIMARY KEY (judgment_id, actual_date)
        )
    """)


def _load_pending_judgments(state_date: str, horizon: int) -> list[dict]:
    """读取待回填的判断"""
    if not AGENT_MEMORY_DB.exists():
        return []
    con = duckdb.connect(str(AGENT_MEMORY_DB), read_only=True)
    rows = con.execute("""
        SELECT judgment_id, judgment_content, confidence, judgment_date
        FROM agent_judgments
        WHERE judgment_type = 'industry_chain'
          AND judgment_date = ?
    """, [state_date]).fetchall()
    con.close()

    results = []
    for row in rows:
        content = row[1]
        if isinstance(content, str):
            content = json.loads(content)
        results.append({
            "judgment_id": row[0],
            "content": content,
            "confidence": row[2],
            "judgment_date": row[3],
        })
    return results


def _calc_chain_return(chain_id: str, start_date: str, horizon: int) -> float | None:
    """计算产业链在 N 日后的收益率"""
    if not STATE_CUBE_DB.exists():
        return None

    end_date = (date.fromisoformat(start_date) + timedelta(days=horizon + 5)).isoformat()

    # 读取成分股
    chain_json = ROOT / "outputs" / "industry_chain" / "chain_fund_manager_assistant_latest.json"
    stock_codes = []
    try:
        with open(chain_json, "r", encoding="utf-8") as f:
            payload = json.load(f)
        stock_codes = [
            r["stock_code"] for r in payload.get("rows", [])
            if r.get("chain_id") == chain_id and r.get("stock_code")
        ]
    except Exception:
        pass

    if not stock_codes:
        return None

    placeholders = ",".join([f"'{s}'" for s in stock_codes[:30]])
    con = duckdb.connect(str(STATE_CUBE_DB), read_only=True)

    # 读取 start_date 和 end_date 附近的收盘价
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

    if len(rows) < 2:
        return None

    start_close = rows[0][1]
    # 找第 horizon 个交易日（或最近的）
    target_idx = min(horizon, len(rows) - 1)
    end_close = rows[target_idx][1]

    if start_close and start_close != 0:
        return round((end_close - start_close) / start_close, 4)
    return None


def backfill(state_date: str, horizon: int) -> list[dict]:
    """回填指定日期的判断"""
    judgments = _load_pending_judgments(state_date, horizon)
    print(f"[backfill] {state_date} 待回填: {len(judgments)} 条，horizon={horizon}")

    con = duckdb.connect(str(AGENT_MEMORY_DB))
    _ensure_outcomes_table(con)

    results = []
    for j in judgments:
        jid = j["judgment_id"]
        content = j["content"]
        chain_id = content.get("chain_id", "unknown")
        direction = content.get("direction", "neutral")
        confidence = j["confidence"]

        actual_return = _calc_chain_return(chain_id, state_date, horizon)
        if actual_return is None:
            print(f"  [SKIP] {chain_id}: 无法计算收益")
            continue

        # 判断方向是否正确
        if direction == "bullish":
            direction_correct = actual_return > 0
        elif direction == "bearish":
            direction_correct = actual_return < 0
        else:
            direction_correct = abs(actual_return) < 0.02

        # 强度偏差
        expected_return = confidence * 0.1 if direction == "bullish" else -confidence * 0.1 if direction == "bearish" else 0
        strength_deviation = round(actual_return - expected_return, 4)

        # 场景标签
        if direction_correct and abs(actual_return) > 0.05:
            scenario_label = "strong_win"
        elif direction_correct:
            scenario_label = "win"
        elif abs(actual_return) < 0.02:
            scenario_label = "draw"
        else:
            scenario_label = "loss"

        actual_date = (date.fromisoformat(state_date) + timedelta(days=horizon)).isoformat()

        con.execute("""
            INSERT INTO judgment_outcomes
            (judgment_id, actual_date, actual_value, direction_correct, strength_deviation, scenario_label)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (judgment_id, actual_date)
            DO UPDATE SET
                actual_value = EXCLUDED.actual_value,
                direction_correct = EXCLUDED.direction_correct,
                strength_deviation = EXCLUDED.strength_deviation,
                scenario_label = EXCLUDED.scenario_label
        """, (jid, actual_date, actual_return, direction_correct, strength_deviation, scenario_label))

        results.append({
            "judgment_id": jid,
            "chain_id": chain_id,
            "direction": direction,
            "actual_return": actual_return,
            "direction_correct": direction_correct,
            "scenario_label": scenario_label,
        })
        print(f"  {chain_id}: {direction} -> 实际收益 {actual_return:.2%} ({scenario_label})")

    con.commit()
    con.close()
    print(f"[backfill] 回填完成: {len(results)} 条")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="产业链判断复盘回填")
    parser.add_argument("--date", type=str, required=True, help="判断日期 YYYY-MM-DD")
    parser.add_argument("--horizon", type=int, choices=[5, 20], default=5, help="回填 horizon")
    args = parser.parse_args()

    backfill(args.date, args.horizon)
    return 0


if __name__ == "__main__":
    sys.exit(main())
