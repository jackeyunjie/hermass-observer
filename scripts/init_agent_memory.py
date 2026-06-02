#!/usr/bin/env python3
"""AgentMemory 数据库建表脚本。

创建 outputs/agent_memory/AgentMemory.duckdb，包含 5 张表：

  1. agent_judgments      — Agent 判断记录
  2. judgment_outcomes    — 判断结果追踪
  3. agent_scenario_library — 场景库
  4. factor_weights_history — 因子权重变更历史
  5. agent_evolution_log  — Agent 进化日志

幂等：多次执行不报错（CREATE TABLE IF NOT EXISTS + DROP/CREATE INDEX）。

用法：
  python3 scripts/init_agent_memory.py
  python3 scripts/init_agent_memory.py --output /path/to/AgentMemory.duckdb
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("init_agent_memory")

DEFAULT_OUTPUT = ROOT / "outputs" / "agent_memory" / "AgentMemory.duckdb"

# ── DDL ──────────────────────────────────────────────────────

DDL_STATEMENTS = [
    # ────────────────────────────────────────────────────────
    # 1. agent_judgments: Agent 每次判断的完整快照
    # ────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS agent_judgments (
        agent_id         VARCHAR   NOT NULL,
        judgment_id      VARCHAR   NOT NULL PRIMARY KEY,
        judgment_date    DATE      NOT NULL,
        judgment_type    VARCHAR   NOT NULL,
        judgment_content JSON,
        confidence       DOUBLE,
        factors_used     JSON,
        context_snapshot JSON
    )
    """,

    # ────────────────────────────────────────────────────────
    # 2. judgment_outcomes: 判断的事后验证结果
    # ────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS judgment_outcomes (
        judgment_id        VARCHAR   NOT NULL,
        actual_date        DATE      NOT NULL,
        actual_value       DOUBLE,
        direction_correct  BOOLEAN,
        strength_deviation DOUBLE,
        scenario_label     VARCHAR,
        FOREIGN KEY (judgment_id) REFERENCES agent_judgments(judgment_id)
    )
    """,

    # ────────────────────────────────────────────────────────
    # 3. agent_scenario_library: 从历史判断中提炼的场景库
    # ────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS agent_scenario_library (
        scenario_id        VARCHAR   NOT NULL PRIMARY KEY,
        scenario_name      VARCHAR   NOT NULL,
        features           JSON,
        sample_count       INTEGER   DEFAULT 0,
        true_breakout_rate DOUBLE,
        avg_excess_return  DOUBLE,
        last_updated       DATE
    )
    """,

    # ────────────────────────────────────────────────────────
    # 4. factor_weights_history: 因子权重的每次调整记录
    # ────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS factor_weights_history (
        factor_name        VARCHAR   NOT NULL,
        date               DATE      NOT NULL,
        old_weight         DOUBLE,
        new_weight         DOUBLE,
        actual_contribution DOUBLE,
        reason             VARCHAR,
        PRIMARY KEY (factor_name, date)
    )
    """,

    # ────────────────────────────────────────────────────────
    # 5. agent_evolution_log: Agent 每日进化状态快照
    # ────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS agent_evolution_log (
        agent_id              VARCHAR   NOT NULL,
        date                  DATE      NOT NULL,
        direction_accuracy_20d DOUBLE,
        avg_deviation_20d     DOUBLE,
        scenarios_discovered  INTEGER   DEFAULT 0,
        evolution_stage       VARCHAR,
        PRIMARY KEY (agent_id, date)
    )
    """,
]

# ── INDEX ────────────────────────────────────────────────────

INDEX_STATEMENTS = [
    # agent_judgments: 按日期 + agent 快速检索
    "CREATE INDEX IF NOT EXISTS idx_judgments_date ON agent_judgments(judgment_date)",
    "CREATE INDEX IF NOT EXISTS idx_judgments_agent_date ON agent_judgments(agent_id, judgment_date)",
    "CREATE INDEX IF NOT EXISTS idx_judgments_type ON agent_judgments(judgment_type)",

    # judgment_outcomes: 按 judgment_id JOIN + 按日期范围查询
    "CREATE INDEX IF NOT EXISTS idx_outcomes_judgment_id ON judgment_outcomes(judgment_id)",
    "CREATE INDEX IF NOT EXISTS idx_outcomes_actual_date ON judgment_outcomes(actual_date)",
    "CREATE INDEX IF NOT EXISTS idx_outcomes_scenario ON judgment_outcomes(scenario_label)",

    # agent_scenario_library: 按名称搜索
    "CREATE INDEX IF NOT EXISTS idx_scenario_name ON agent_scenario_library(scenario_name)",

    # factor_weights_history: 按日期范围查询
    "CREATE INDEX IF NOT EXISTS idx_factor_weights_date ON factor_weights_history(date)",

    # agent_evolution_log: 按日期范围查询
    "CREATE INDEX IF NOT EXISTS idx_evolution_date ON agent_evolution_log(date)",
]


def init_database(db_path: Path) -> dict:
    """创建数据库并执行所有 DDL。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("创建 AgentMemory 数据库: %s", db_path)
    conn = duckdb.connect(str(db_path))

    created_tables: list[str] = []
    created_indexes: list[str] = []

    # 执行建表
    for ddl in DDL_STATEMENTS:
        table_name = ddl.split("IF NOT EXISTS")[1].strip().split("(")[0].strip()
        conn.execute(ddl)
        created_tables.append(table_name)
        log.info("  表: %s", table_name)

    # 执行索引
    for idx_sql in INDEX_STATEMENTS:
        conn.execute(idx_sql)
        idx_name = idx_sql.split("IF NOT EXISTS")[1].strip().split(" ")[0].strip()
        created_indexes.append(idx_name)
        log.info("  索引: %s", idx_name)

    # 验证
    tables = conn.execute("SHOW TABLES").fetchdf()
    log.info("数据库表列表: %s", tables["name"].tolist())

    # 检查外键
    fk_check = conn.execute("""
        SELECT *
        FROM duckdb_constraints()
        WHERE constraint_type = 'FOREIGN KEY'
          AND table_name = 'judgment_outcomes'
    """).fetchdf()
    log.info("外键约束: %d 条", len(fk_check))

    conn.close()

    result = {
        "db_path": str(db_path),
        "tables": created_tables,
        "indexes": created_indexes,
        "total_tables": len(created_tables),
        "total_indexes": len(created_indexes),
    }
    log.info("AgentMemory 初始化完成: %d 张表, %d 个索引", len(created_tables), len(created_indexes))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="初始化 AgentMemory 数据库（5 张表 + 索引 + 外键）"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="输出路径，默认 outputs/agent_memory/AgentMemory.duckdb",
    )
    args = parser.parse_args()

    db_path = Path(args.output) if args.output else DEFAULT_OUTPUT
    result = init_database(db_path)

    import json
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
