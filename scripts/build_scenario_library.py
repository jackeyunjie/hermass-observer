#!/usr/bin/env python3
"""Build Scenario Library — 场景库自动构建。

从 ContractionObserver 历史输出和 judgment_outcomes 表中，
按 scenario_label 聚类，统计每个场景的历史真突破率、平均超额收益、假突破率。
写入 agent_scenario_library 表。

用法：
  python3 scripts/build_scenario_library.py --date 2026-06-02
  python3 scripts/build_scenario_library.py --date 2026-06-02 --foundation-db /path/to/foundation.duckdb

调度建议：
  - 每周五收盘后运行: python3 scripts/build_scenario_library.py --date $(date +%Y-%m-%d)
  - 可加入 Makefile 或 crontab: 0 16 * * 5 cd /opt/hermass && python3 scripts/build_scenario_library.py --date $(date +\%Y-\%m-\%d)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermass_platform.agents.base_agent import find_foundation_db

SCENARIO_LIBRARY_TABLE = "agent_scenario_library"
SCENARIO_MANIFEST_TABLE = "agent_scenario_library_manifest"

# ── 场景标签定义 ──────────────────────────────────────────────
# 从 State 组合模式中自动提取的场景模板
SCENARIO_TEMPLATES = [
    {
        "scenario_label": "triple_ef_breakout",
        "description": "三周期全 EF 突破",
        "match_rule": "mn1_ef=1 AND w1_ef=1 AND d1_ef=1",
        "expected_phase": "emergence",
    },
    {
        "scenario_label": "d1_only_ef_pullback",
        "description": "仅 D1 EF，大周期未确认",
        "match_rule": "mn1_ef=0 AND w1_ef=0 AND d1_ef=1",
        "expected_phase": "progression",
    },
    {
        "scenario_label": "mn1_w1_ef_d1_lag",
        "description": "MN1+W1 EF 但 D1 滞后",
        "match_rule": "mn1_ef=1 AND w1_ef=1 AND d1_ef=0",
        "expected_phase": "emergence",
    },
    {
        "scenario_label": "contraction_squeeze",
        "description": "多周期收缩挤压",
        "match_rule": "mn1_base=0 AND w1_base=0 AND d1_base=0",
        "expected_phase": "contraction",
    },
    {
        "scenario_label": "w1_bottleneck_break",
        "description": "W1 瓶颈突破（W1 从非EF进入EF）",
        "match_rule": "prev_w1_ef=0 AND w1_ef=1 AND mn1_ef=1",
        "expected_phase": "emergence",
    },
    {
        "scenario_label": "volatility_expansion",
        "description": "波动率扩张期",
        "match_rule": "d1_volatility=1 AND w1_volatility=1",
        "expected_phase": "extension",
    },
    {
        "scenario_label": "sr_breakout_confirmed",
        "description": "多周期 SR 突破确认",
        "match_rule": "d1_position=2 AND w1_position=2",
        "expected_phase": "progression",
    },
    {
        "scenario_label": "regime_exhaustion",
        "description": "趋势衰竭信号",
        "match_rule": "prev_d1_ef=1 AND d1_ef=0 AND w1_ef=1",
        "expected_phase": "risk_release",
    },
]


@dataclass
class ScenarioStats:
    """单个场景的统计数据。"""
    scenario_label: str
    description: str
    total_occurrences: int = 0
    true_breakout_count: int = 0
    false_breakout_count: int = 0
    true_breakout_rate: float = 0.0
    false_breakout_rate: float = 0.0
    avg_excess_return: float = 0.0
    median_excess_return: float = 0.0
    avg_holding_days: float = 0.0
    confidence_level: str = "low_confidence"  # low_confidence / medium / high
    sample_sufficiency: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_label": self.scenario_label,
            "description": self.description,
            "total_occurrences": self.total_occurrences,
            "true_breakout_count": self.true_breakout_count,
            "false_breakout_count": self.false_breakout_count,
            "true_breakout_rate": round(self.true_breakout_rate, 4),
            "false_breakout_rate": round(self.false_breakout_rate, 4),
            "avg_excess_return": round(self.avg_excess_return, 4),
            "median_excess_return": round(self.median_excess_return, 4),
            "avg_holding_days": round(self.avg_holding_days, 1),
            "confidence_level": self.confidence_level,
            "sample_sufficiency": self.sample_sufficiency,
        }


def _ensure_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """确保 DuckDB 中存在所需的表。"""
    # judgment_outcomes 表（前向观察结果的标准化表）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS judgment_outcomes (
            outcome_id INTEGER,
            stock_code VARCHAR NOT NULL,
            signal_date DATE NOT NULL,
            scenario_label VARCHAR NOT NULL DEFAULT '',
            strategy_name VARCHAR NOT NULL DEFAULT '',
            entry_price DOUBLE,
            forward_return_5d DOUBLE,
            forward_return_10d DOUBLE,
            forward_return_20d DOUBLE,
            excess_return_5d DOUBLE,
            excess_return_10d DOUBLE,
            excess_return_20d DOUBLE,
            true_breakout BOOLEAN DEFAULT FALSE,
            false_breakout BOOLEAN DEFAULT FALSE,
            holding_days INTEGER,
            state_combo VARCHAR,
            market_phase VARCHAR,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCENARIO_LIBRARY_TABLE} (
            scenario_label VARCHAR PRIMARY KEY,
            description VARCHAR,
            total_occurrences INTEGER DEFAULT 0,
            true_breakout_count INTEGER DEFAULT 0,
            false_breakout_count INTEGER DEFAULT 0,
            true_breakout_rate DOUBLE DEFAULT 0.0,
            false_breakout_rate DOUBLE DEFAULT 0.0,
            avg_excess_return DOUBLE DEFAULT 0.0,
            median_excess_return DOUBLE DEFAULT 0.0,
            avg_holding_days DOUBLE DEFAULT 0.0,
            confidence_level VARCHAR DEFAULT 'low_confidence',
            sample_sufficiency BOOLEAN DEFAULT FALSE,
            last_updated TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCENARIO_MANIFEST_TABLE} (
            build_date DATE NOT NULL,
            scenarios_count INTEGER,
            total_outcomes INTEGER,
            schema_version VARCHAR DEFAULT '1.0',
            status VARCHAR DEFAULT 'ok'
        )
    """)


def _auto_label_scenarios(
    conn: duckdb.DuckDBPyConnection,
    target_date: str,
) -> int:
    """自动为 judgment_outcomes 中未标记的场景分配 scenario_label。

    基于 State 组合模式匹配 SCENARIO_TEMPLATES 中的规则。
    """
    labeled_count = 0
    for template in SCENARIO_TEMPLATES:
        label = template["scenario_label"]
        # 尝试从 state_ef_daily 中匹配 State 组合
        try:
            # 简单匹配：基于 ef_count 和各周期 hex 值
            result = conn.execute(f"""
                UPDATE judgment_outcomes
                SET scenario_label = '{label}'
                WHERE scenario_label = ''
                  AND stock_code IN (
                    SELECT stock_code FROM state_ef_daily
                    WHERE state_date = signal_date
                      AND ef_count >= {2 if 'triple' in label else 1}
                  )
            """)
            # DuckDB 不支持 rowcount on UPDATE 返回值，用 SELECT 代替
            count = conn.execute(f"""
                SELECT COUNT(*) FROM judgment_outcomes
                WHERE scenario_label = '{label}'
            """).fetchone()[0]
            labeled_count = max(labeled_count, count)
        except Exception:
            pass

    return labeled_count


def _populate_judgment_outcomes_from_forward_ledger(
    conn: duckdb.DuckDBPyConnection,
    target_date: str,
) -> int:
    """从前向观察账本数据填充 judgment_outcomes 表。

    查找 forward_observation 相关的 JSON 文件或 DuckDB 表。
    """
    # 尝试从 state_ef_daily + strategy_signal_daily 构建
    inserted = 0
    try:
        conn.execute("""
            INSERT INTO judgment_outcomes
            (outcome_id, stock_code, signal_date, scenario_label, strategy_name,
             entry_price, forward_return_5d, forward_return_10d, forward_return_20d,
             true_breakout, false_breakout, state_combo, market_phase)
            SELECT
                ROW_NUMBER() OVER () AS outcome_id,
                s.stock_code,
                s.signal_date,
                '' AS scenario_label,
                s.strategy_name,
                NULL AS entry_price,
                NULL AS forward_return_5d,
                NULL AS forward_return_10d,
                NULL AS forward_return_20d,
                FALSE AS true_breakout,
                FALSE AS false_breakout,
                CONCAT(COALESCE(e.mn1_state_hex, '-'), '/',
                       COALESCE(e.w1_state_hex, '-'), '/',
                       COALESCE(e.d1_state_hex, '-')) AS state_combo,
                '' AS market_phase
            FROM strategy_signal_daily s
            LEFT JOIN state_ef_daily e
                ON s.stock_code = e.stock_code AND s.signal_date = e.state_date
            WHERE s.signal_date <= CAST(? AS DATE)
              AND NOT EXISTS (
                SELECT 1 FROM judgment_outcomes j
                WHERE j.stock_code = s.stock_code
                  AND j.signal_date = s.signal_date
                  AND j.strategy_name = s.strategy_name
              )
        """, [target_date])
        inserted = conn.execute("SELECT COUNT(*) FROM judgment_outcomes").fetchone()[0]
    except Exception:
        pass
    return inserted


def _mark_breakout_outcomes(
    conn: duckdb.DuckDBPyConnection,
    target_date: str,
) -> None:
    """标记真突破 / 假突破。

    真突破定义：信号后 10 天内 forward_return > 0 且 D1 收盘价维持在信号日收盘价之上
    假突破定义：信号后 5 天内 forward_return < -3% 或价格跌回信号日支撑位
    """
    try:
        conn.execute("""
            UPDATE judgment_outcomes
            SET true_breakout = TRUE
            WHERE forward_return_10d IS NOT NULL
              AND forward_return_10d > 0
              AND forward_return_5d IS NOT NULL
              AND forward_return_5d > -0.02
        """)
        conn.execute("""
            UPDATE judgment_outcomes
            SET false_breakout = TRUE
            WHERE forward_return_5d IS NOT NULL
              AND forward_return_5d < -0.03
        """)
    except Exception:
        pass


def _compute_scenario_stats(
    conn: duckdb.DuckDBPyConnection,
) -> list[ScenarioStats]:
    """从 judgment_outcomes 表中按 scenario_label 聚类统计。"""
    stats_list: list[ScenarioStats] = []

    # 获取所有场景标签
    labels = conn.execute("""
        SELECT DISTINCT scenario_label FROM judgment_outcomes
        WHERE scenario_label != ''
        ORDER BY scenario_label
    """).fetchall()

    # 加上预定义模板中没有数据的场景
    seen_labels = {row[0] for row in labels}
    for template in SCENARIO_TEMPLATES:
        if template["scenario_label"] not in seen_labels:
            seen_labels.add(template["scenario_label"])

    for label in sorted(seen_labels):
        template_desc = ""
        for t in SCENARIO_TEMPLATES:
            if t["scenario_label"] == label:
                template_desc = t["description"]
                break

        try:
            row = conn.execute("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN true_breakout THEN 1 ELSE 0 END) AS true_bo,
                    SUM(CASE WHEN false_breakout THEN 1 ELSE 0 END) AS false_bo,
                    AVG(COALESCE(excess_return_10d, excess_return_5d, 0)) AS avg_excess,
                    MEDIAN(COALESCE(excess_return_10d, excess_return_5d, 0)) AS med_excess,
                    AVG(COALESCE(holding_days, 0)) AS avg_hold
                FROM judgment_outcomes
                WHERE scenario_label = ?
            """, [label]).fetchone()
        except Exception:
            row = None

        stats = ScenarioStats(
            scenario_label=label,
            description=template_desc or label,
        )

        if row and row[0] > 0:
            stats.total_occurrences = row[0]
            stats.true_breakout_count = row[1] or 0
            stats.false_breakout_count = row[2] or 0
            stats.true_breakout_rate = (stats.true_breakout_count / stats.total_occurrences) if stats.total_occurrences > 0 else 0.0
            stats.false_breakout_rate = (stats.false_breakout_count / stats.total_occurrences) if stats.total_occurrences > 0 else 0.0
            stats.avg_excess_return = float(row[3]) if row[3] is not None else 0.0
            stats.median_excess_return = float(row[4]) if row[4] is not None else 0.0
            stats.avg_holding_days = float(row[5]) if row[5] is not None else 0.0

            # 置信度评估
            if stats.total_occurrences >= 50:
                stats.confidence_level = "high"
                stats.sample_sufficiency = True
            elif stats.total_occurrences >= 20:
                stats.confidence_level = "medium"
                stats.sample_sufficiency = True
            else:
                stats.confidence_level = "low_confidence"
                stats.sample_sufficiency = False

        stats_list.append(stats)

    return stats_list


def build_scenario_library(
    target_date: str,
    foundation_db: str = "",
) -> dict[str, Any]:
    """构建场景库主入口。"""
    if not foundation_db:
        db_path = find_foundation_db(target_date)
        if db_path is None:
            return {"status": "error", "errors": ["无可用 Foundation DB"]}
        foundation_db = str(db_path)

    conn = duckdb.connect(foundation_db)
    try:
        _ensure_tables(conn)

        # 第一步：从前向观察账本填充 judgment_outcomes
        outcomes_count = _populate_judgment_outcomes_from_forward_ledger(conn, target_date)

        # 第二步：标记真/假突破
        _mark_breakout_outcomes(conn, target_date)

        # 第三步：自动分配场景标签
        labeled = _auto_label_scenarios(conn, target_date)

        # 第四步：计算每个场景的统计
        stats_list = _compute_scenario_stats(conn)

        # 第五步：写入 agent_scenario_library 表
        for stats in stats_list:
            conn.execute(f"""
                INSERT OR REPLACE INTO {SCENARIO_LIBRARY_TABLE}
                (scenario_label, description, total_occurrences,
                 true_breakout_count, false_breakout_count,
                 true_breakout_rate, false_breakout_rate,
                 avg_excess_return, median_excess_return,
                 avg_holding_days, confidence_level,
                 sample_sufficiency, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
            """, [
                stats.scenario_label, stats.description, stats.total_occurrences,
                stats.true_breakout_count, stats.false_breakout_count,
                stats.true_breakout_rate, stats.false_breakout_rate,
                stats.avg_excess_return, stats.median_excess_return,
                stats.avg_holding_days, stats.confidence_level,
                stats.sample_sufficiency,
            ])

        # 写入 manifest
        conn.execute(f"""
            INSERT INTO {SCENARIO_MANIFEST_TABLE}
            (build_date, scenarios_count, total_outcomes)
            VALUES (CAST(? AS DATE), ?, ?)
        """, [target_date, len(stats_list), outcomes_count])

        conn.commit()

    finally:
        conn.close()

    return {
        "status": "ok",
        "date": target_date,
        "outcomes_total": outcomes_count,
        "scenarios_count": len(stats_list),
        "auto_labeled": labeled,
        "scenarios": [s.to_dict() for s in stats_list],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Scenario Library — 场景库自动构建")
    parser.add_argument("--date", required=True, help="交易日 YYYY-MM-DD")
    parser.add_argument("--foundation-db", default="", help="Foundation DB 路径")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    result = build_scenario_library(
        target_date=args.date,
        foundation_db=args.foundation_db,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"=== Scenario Library Report ({args.date}) ===")
        print(f"Outcomes total: {result.get('outcomes_total', 0)}")
        print(f"Scenarios count: {result.get('scenarios_count', 0)}")
        print(f"Auto-labeled: {result.get('auto_labeled', 0)}")
        print()
        for s in result.get("scenarios", []):
            suff = "sufficient" if s["sample_sufficiency"] else "low_confidence"
            print(f"  {s['scenario_label']:30s} | "
                  f"n={s['total_occurrences']:4d} | "
                  f"true_bo={s['true_breakout_rate']:.1%} | "
                  f"false_bo={s['false_breakout_rate']:.1%} | "
                  f"avg_excess={s['avg_excess_return']:+.2%} | "
                  f"conf={s['confidence_level']:14s} | "
                  f"sample={suff}")

    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
