#!/usr/bin/env python3
"""长期形态观察系统 — Schema & 初始化。

六张核心表，全部存入 outputs/pattern_lifecycle/pattern_lifecycle.duckdb：

  pattern_observation_daily  — 每日全市场形态快照
  vcp_candidate_pool         — VCP 潜在者池
  ma2560_candidate_pool      — 2560 潜在者池
  pattern_events             — 突破/失效/回踩/二次确认事件
  macro_regime_daily         — 大盘/行业周期状态
  pattern_lifecycle          — 单品种形态完整生命周期

依赖：
  - outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb
"""

from __future__ import annotations

import duckdb
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "pattern_lifecycle_v1"

CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS pattern_observation_daily (
        stock_code       VARCHAR    NOT NULL,
        obs_date         DATE       NOT NULL,
        close            DOUBLE,
        volume           DOUBLE,
        vcp_phase        VARCHAR    DEFAULT 'none',
        vcp_phase_prev   VARCHAR    DEFAULT 'none',
        vcp_contraction_days INTEGER DEFAULT 0,
        vcp_range_ratio  DOUBLE,
        vcp_atr_trend    VARCHAR,
        ma2560_phase     VARCHAR    DEFAULT 'none',
        ma2560_phase_prev VARCHAR   DEFAULT 'none',
        ma25             DOUBLE,
        ma60             DOUBLE,
        ma25_slope       DOUBLE,
        ma60_slope       DOUBLE,
        ef_count         INTEGER,
        in_ef_pool       BOOLEAN    DEFAULT FALSE,
        PRIMARY KEY (stock_code, obs_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vcp_candidate_pool (
        stock_code       VARCHAR    NOT NULL,
        first_detected   DATE       NOT NULL,
        last_updated     DATE       NOT NULL,
        phase            VARCHAR    NOT NULL DEFAULT 'forming',
        quality_tier     VARCHAR    DEFAULT 'watch',
        contraction_count INTEGER   DEFAULT 1,
        lowest_range_ratio DOUBLE,
        lowest_atr       DOUBLE,
        breakout_date    DATE,
        breakout_close   DOUBLE,
        breakout_volume_ratio DOUBLE,
        status           VARCHAR    NOT NULL DEFAULT 'active',
        resolved_date    DATE,
        resolution       VARCHAR,
        notes            VARCHAR,
        PRIMARY KEY (stock_code, first_detected)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ma2560_candidate_pool (
        stock_code       VARCHAR    NOT NULL,
        first_detected   DATE       NOT NULL,
        last_updated     DATE       NOT NULL,
        phase            VARCHAR    NOT NULL DEFAULT 'approaching',
        ma25             DOUBLE,
        ma60             DOUBLE,
        price_vs_ma25    VARCHAR,
        golden_cross_date DATE,
        death_cross_date DATE,
        alignment_days   INTEGER    DEFAULT 0,
        status           VARCHAR    NOT NULL DEFAULT 'active',
        resolved_date    DATE,
        resolution       VARCHAR,
        notes            VARCHAR,
        PRIMARY KEY (stock_code, first_detected)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pattern_events (
        stock_code       VARCHAR    NOT NULL,
        event_date       DATE       NOT NULL,
        pattern_type     VARCHAR    NOT NULL,
        event            VARCHAR    NOT NULL,
        detail           VARCHAR,
        close            DOUBLE,
        volume_ratio     DOUBLE,
        importance       INTEGER    DEFAULT 1,
        PRIMARY KEY (stock_code, event_date, pattern_type, event)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS macro_regime_daily (
        regime_date      DATE       NOT NULL,
        asset_code       VARCHAR    NOT NULL,
        asset_type       VARCHAR    NOT NULL,
        mn1_state_hex    VARCHAR,
        w1_state_hex     VARCHAR,
        d1_state_hex     VARCHAR,
        ef_count         INTEGER,
        breadth_bull_pct DOUBLE,
        PRIMARY KEY (regime_date, asset_code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pattern_lifecycle (
        stock_code       VARCHAR    NOT NULL,
        stock_name       VARCHAR,
        sw_l1            VARCHAR,
        pattern_type     VARCHAR    NOT NULL,
        first_seen       DATE       NOT NULL,
        last_seen        DATE       NOT NULL,
        events           VARCHAR,
        peak_phase       VARCHAR,
        total_days       INTEGER,
        breakout_occurred BOOLEAN DEFAULT FALSE,
        crossed_ef_pool  BOOLEAN DEFAULT FALSE,
        resolution       VARCHAR,
        PRIMARY KEY (stock_code, pattern_type, first_seen)
    )
    """,
]


def get_db_path() -> Path:
    out_dir = ROOT / "outputs" / "pattern_lifecycle"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / "pattern_lifecycle.duckdb"


def init_schema(db_path: Path | None = None) -> Path:
    db_path = db_path or get_db_path()
    con = duckdb.connect(str(db_path))
    for stmt in CREATE_STATEMENTS:
        con.execute(stmt)
    cols = {row[1] for row in con.execute("PRAGMA table_info('vcp_candidate_pool')").fetchall()}
    if "quality_tier" not in cols:
        con.execute("ALTER TABLE vcp_candidate_pool ADD COLUMN quality_tier VARCHAR DEFAULT 'watch'")
    con.execute("CREATE TABLE IF NOT EXISTS schema_info (schema_version VARCHAR, created_at VARCHAR)")
    con.execute("DELETE FROM schema_info")
    con.execute(
        "INSERT INTO schema_info VALUES (?, ?)",
        (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
    )
    con.close()
    return db_path


if __name__ == "__main__":
    p = init_schema()
    print(f"Schema initialized: {p}")
