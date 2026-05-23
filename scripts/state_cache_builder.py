#!/usr/bin/env python3
"""Build daily materialized cache outputs for Hermass/P116 state scans.

The foundation DB remains the read-only source of truth. This script creates a
separate cache DB plus JSON files for expensive full-market scans used by UI,
Agents, and backtests.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def default_foundation_db(date_str: str) -> Path:
    return ROOT / "outputs" / f"p116_foundation_{ymd(date_str)}" / "p116_foundation.duckdb"


def default_cache_db() -> Path:
    return ROOT / "outputs" / "state_cache" / "state_cache.duckdb"


def sql_quote_path(path: Path) -> str:
    return str(path).replace("'", "''")


def json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def fetch_dicts(con: duckdb.DuckDBPyConnection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur = con.execute(sql, params)
    cols = [item[0] for item in cur.description]
    return [{col: json_safe(value) for col, value in zip(cols, row)} for row in cur.fetchall()]


def ensure_column(con: duckdb.DuckDBPyConnection, table: str, column: str, definition: str) -> None:
    exists = con.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = 'main'
          AND table_name = ?
          AND column_name = ?
        """,
        (table, column),
    ).fetchone()[0]
    if not exists:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


class StateCacheBuilder:
    def __init__(self, date_str: str, foundation_db: Path, cache_db: Path, boundary_pct: float = 0.03) -> None:
        self.date_str = date_str
        self.date_ymd = ymd(date_str)
        self.foundation_db = foundation_db
        self.cache_db = cache_db
        self.boundary_pct = boundary_pct
        self.out_dir = cache_db.parent

    def connect(self) -> duckdb.DuckDBPyConnection:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(self.cache_db))
        con.execute(f"ATTACH '{sql_quote_path(self.foundation_db)}' AS foundation (READ_ONLY)")
        return con

    def create_tables(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS state_ef_daily (
                obs_date DATE,
                stock_code VARCHAR,
                d1_close DOUBLE,
                mn1_state_hex VARCHAR,
                w1_state_hex VARCHAR,
                d1_state_hex VARCHAR,
                mn1_state_score INTEGER,
                w1_state_score INTEGER,
                d1_state_score INTEGER,
                score_sum INTEGER,
                ef_count INTEGER,
                cache_scope VARCHAR
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS state_distribution_daily (
                obs_date DATE,
                period VARCHAR,
                state_hex VARCHAR,
                cnt BIGINT,
                avg_score DOUBLE,
                min_score INTEGER,
                max_score INTEGER
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS state_transition_daily (
                obs_date DATE,
                stock_code VARCHAR,
                period VARCHAR,
                from_state VARCHAR,
                to_state VARCHAR,
                from_score INTEGER,
                to_score INTEGER,
                d1_close DOUBLE,
                ef_count INTEGER
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS sr_boundary_daily (
                obs_date DATE,
                stock_code VARCHAR,
                boundary_period VARCHAR,
                boundary_type VARCHAR,
                distance_pct DOUBLE,
                d1_close DOUBLE,
                boundary_price DOUBLE,
                state_hex VARCHAR,
                state_score INTEGER,
                ef_count INTEGER,
                boundary_direction VARCHAR,
                close_vs_boundary DOUBLE,
                above_resistance BOOLEAN,
                below_support BOOLEAN
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS state_duration_daily (
                obs_date DATE,
                stock_code VARCHAR,
                d1_close DOUBLE,
                mn1_state_hex VARCHAR,
                w1_state_hex VARCHAR,
                d1_state_hex VARCHAR,
                mn1_ef_duration INTEGER,
                w1_ef_duration INTEGER,
                d1_ef_duration INTEGER,
                all_three_ef_duration INTEGER,
                mn1_contraction_duration INTEGER,
                w1_contraction_duration INTEGER,
                d1_contraction_duration INTEGER,
                mn1_days_since_contraction_exit INTEGER,
                w1_days_since_contraction_exit INTEGER,
                d1_days_since_contraction_exit INTEGER,
                mn1_prev_contraction_duration INTEGER,
                w1_prev_contraction_duration INTEGER,
                d1_prev_contraction_duration INTEGER,
                ef_count INTEGER
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS state_cache_manifest (
                obs_date DATE PRIMARY KEY,
                generated_at VARCHAR,
                foundation_db VARCHAR,
                boundary_pct DOUBLE,
                all_three_ef_count BIGINT,
                distribution_rows BIGINT,
                transition_rows BIGINT,
                sr_boundary_rows BIGINT,
                duration_rows BIGINT,
                research_only BOOLEAN
            )
            """
        )
        ensure_column(con, "sr_boundary_daily", "boundary_direction", "VARCHAR")
        ensure_column(con, "sr_boundary_daily", "close_vs_boundary", "DOUBLE")
        ensure_column(con, "sr_boundary_daily", "above_resistance", "BOOLEAN")
        ensure_column(con, "sr_boundary_daily", "below_support", "BOOLEAN")
        ensure_column(con, "state_cache_manifest", "duration_rows", "BIGINT")
        ensure_column(con, "state_duration_daily", "mn1_contraction_duration", "INTEGER")
        ensure_column(con, "state_duration_daily", "w1_contraction_duration", "INTEGER")
        ensure_column(con, "state_duration_daily", "d1_contraction_duration", "INTEGER")
        ensure_column(con, "state_duration_daily", "mn1_days_since_contraction_exit", "INTEGER")
        ensure_column(con, "state_duration_daily", "w1_days_since_contraction_exit", "INTEGER")
        ensure_column(con, "state_duration_daily", "d1_days_since_contraction_exit", "INTEGER")
        ensure_column(con, "state_duration_daily", "mn1_prev_contraction_duration", "INTEGER")
        ensure_column(con, "state_duration_daily", "w1_prev_contraction_duration", "INTEGER")
        ensure_column(con, "state_duration_daily", "d1_prev_contraction_duration", "INTEGER")

    def clear_date(self, con: duckdb.DuckDBPyConnection) -> None:
        for table in [
            "state_ef_daily",
            "state_distribution_daily",
            "state_transition_daily",
            "sr_boundary_daily",
            "state_duration_daily",
            "state_cache_manifest",
        ]:
            con.execute(f"DELETE FROM {table} WHERE obs_date = CAST(? AS DATE)", (self.date_str,))

    def build_all_three_ef(self, con: duckdb.DuckDBPyConnection) -> int:
        con.execute(
            """
            INSERT INTO state_ef_daily
            SELECT
                state_date AS obs_date,
                stock_code,
                d1_close,
                mn1_state_hex,
                w1_state_hex,
                d1_state_hex,
                mn1_state_score,
                w1_state_score,
                d1_state_score,
                mn1_state_score + w1_state_score + d1_state_score AS score_sum,
                ef_count,
                'all_three_ef_raw' AS cache_scope
            FROM foundation.d1_perspective_state
            WHERE state_date = CAST(? AS DATE)
              AND mn1_state_hex IN ('E', 'F')
              AND w1_state_hex IN ('E', 'F')
              AND d1_state_hex IN ('E', 'F')
            """,
            (self.date_str,),
        )
        return con.execute(
            "SELECT COUNT(*) FROM state_ef_daily WHERE obs_date = CAST(? AS DATE)",
            (self.date_str,),
        ).fetchone()[0]

    def build_distribution(self, con: duckdb.DuckDBPyConnection) -> int:
        con.execute(
            """
            INSERT INTO state_distribution_daily
            WITH expanded AS (
                SELECT state_date AS obs_date, 'mn1' AS period, mn1_state_hex AS state_hex, mn1_state_score AS state_score
                FROM foundation.d1_perspective_state
                WHERE state_date = CAST(? AS DATE)
                UNION ALL
                SELECT state_date AS obs_date, 'w1' AS period, w1_state_hex AS state_hex, w1_state_score AS state_score
                FROM foundation.d1_perspective_state
                WHERE state_date = CAST(? AS DATE)
                UNION ALL
                SELECT state_date AS obs_date, 'd1' AS period, d1_state_hex AS state_hex, d1_state_score AS state_score
                FROM foundation.d1_perspective_state
                WHERE state_date = CAST(? AS DATE)
                UNION ALL
                SELECT state_date AS obs_date, 'combo' AS period,
                       mn1_state_hex || '/' || w1_state_hex || '/' || d1_state_hex AS state_hex,
                       mn1_state_score + w1_state_score + d1_state_score AS state_score
                FROM foundation.d1_perspective_state
                WHERE state_date = CAST(? AS DATE)
            )
            SELECT obs_date, period, state_hex,
                   COUNT(*) AS cnt,
                   AVG(state_score) AS avg_score,
                   MIN(state_score) AS min_score,
                   MAX(state_score) AS max_score
            FROM expanded
            GROUP BY 1, 2, 3
            """,
            (self.date_str, self.date_str, self.date_str, self.date_str),
        )
        return con.execute(
            "SELECT COUNT(*) FROM state_distribution_daily WHERE obs_date = CAST(? AS DATE)",
            (self.date_str,),
        ).fetchone()[0]

    def build_transitions(self, con: duckdb.DuckDBPyConnection) -> int:
        con.execute(
            """
            INSERT INTO state_transition_daily
            WITH base AS (
                SELECT
                    stock_code,
                    state_date,
                    d1_close,
                    ef_count,
                    mn1_state_hex,
                    w1_state_hex,
                    d1_state_hex,
                    mn1_state_score,
                    w1_state_score,
                    d1_state_score,
                    lag(mn1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_mn1_state,
                    lag(w1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_w1_state,
                    lag(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_d1_state,
                    lag(mn1_state_score) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_mn1_score,
                    lag(w1_state_score) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_w1_score,
                    lag(d1_state_score) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_d1_score
                FROM foundation.d1_perspective_state
                WHERE state_date BETWEEN CAST(? AS DATE) - INTERVAL 10 DAY AND CAST(? AS DATE)
            ),
            expanded AS (
                SELECT state_date AS obs_date, stock_code, 'mn1' AS period,
                       prev_mn1_state AS from_state, mn1_state_hex AS to_state,
                       prev_mn1_score AS from_score, mn1_state_score AS to_score,
                       d1_close, ef_count
                FROM base
                WHERE state_date = CAST(? AS DATE)
                UNION ALL
                SELECT state_date AS obs_date, stock_code, 'w1' AS period,
                       prev_w1_state AS from_state, w1_state_hex AS to_state,
                       prev_w1_score AS from_score, w1_state_score AS to_score,
                       d1_close, ef_count
                FROM base
                WHERE state_date = CAST(? AS DATE)
                UNION ALL
                SELECT state_date AS obs_date, stock_code, 'd1' AS period,
                       prev_d1_state AS from_state, d1_state_hex AS to_state,
                       prev_d1_score AS from_score, d1_state_score AS to_score,
                       d1_close, ef_count
                FROM base
                WHERE state_date = CAST(? AS DATE)
            )
            SELECT *
            FROM expanded
            WHERE from_state IS NOT NULL
              AND from_state != to_state
            """,
            (self.date_str, self.date_str, self.date_str, self.date_str, self.date_str),
        )
        return con.execute(
            "SELECT COUNT(*) FROM state_transition_daily WHERE obs_date = CAST(? AS DATE)",
            (self.date_str,),
        ).fetchone()[0]

    def build_sr_boundary(self, con: duckdb.DuckDBPyConnection) -> int:
        con.execute(
            """
            INSERT INTO sr_boundary_daily
            WITH source AS (
                SELECT
                    state_date,
                    stock_code,
                    d1_close,
                    ef_count,
                    d1_state_hex,
                    w1_state_hex,
                    mn1_state_hex,
                    d1_state_score,
                    w1_state_score,
                    mn1_state_score,
                    d1_sr_ready,
                    w1_sr_ready,
                    mn1_sr_ready,
                    d1_sr_support,
                    d1_sr_resistance,
                    w1_sr_support,
                    w1_sr_resistance,
                    mn1_sr_support,
                    mn1_sr_resistance
                FROM foundation.d1_perspective_state
                WHERE state_date = CAST(? AS DATE)
                  AND d1_close > 0
            ),
            expanded AS (
                SELECT state_date AS obs_date, stock_code, 'd1' AS boundary_period,
                       'support' AS boundary_type,
                       ABS(d1_close / d1_sr_support - 1) AS distance_pct,
                       d1_close / d1_sr_support - 1 AS close_vs_boundary,
                       d1_close, d1_sr_support AS boundary_price,
                       d1_state_hex AS state_hex, d1_state_score AS state_score, ef_count,
                       CASE
                           WHEN d1_close > d1_sr_resistance THEN 'above_resistance'
                           WHEN d1_close < d1_sr_support THEN 'below_support'
                           ELSE 'inside_range'
                       END AS boundary_direction,
                       d1_close > d1_sr_resistance AS above_resistance,
                       d1_close < d1_sr_support AS below_support
                FROM source
                WHERE d1_sr_ready = true AND d1_sr_support > 0
                UNION ALL
                SELECT state_date AS obs_date, stock_code, 'd1' AS boundary_period,
                       'resistance' AS boundary_type,
                       ABS(d1_close / d1_sr_resistance - 1) AS distance_pct,
                       d1_close / d1_sr_resistance - 1 AS close_vs_boundary,
                       d1_close, d1_sr_resistance AS boundary_price,
                       d1_state_hex AS state_hex, d1_state_score AS state_score, ef_count,
                       CASE
                           WHEN d1_close > d1_sr_resistance THEN 'above_resistance'
                           WHEN d1_close < d1_sr_support THEN 'below_support'
                           ELSE 'inside_range'
                       END AS boundary_direction,
                       d1_close > d1_sr_resistance AS above_resistance,
                       d1_close < d1_sr_support AS below_support
                FROM source
                WHERE d1_sr_ready = true AND d1_sr_resistance > 0
                UNION ALL
                SELECT state_date AS obs_date, stock_code, 'w1' AS boundary_period,
                       'support' AS boundary_type,
                       ABS(d1_close / w1_sr_support - 1) AS distance_pct,
                       d1_close / w1_sr_support - 1 AS close_vs_boundary,
                       d1_close, w1_sr_support AS boundary_price,
                       w1_state_hex AS state_hex, w1_state_score AS state_score, ef_count,
                       CASE
                           WHEN d1_close > w1_sr_resistance THEN 'above_resistance'
                           WHEN d1_close < w1_sr_support THEN 'below_support'
                           ELSE 'inside_range'
                       END AS boundary_direction,
                       d1_close > w1_sr_resistance AS above_resistance,
                       d1_close < w1_sr_support AS below_support
                FROM source
                WHERE w1_sr_ready = true AND w1_sr_support > 0
                UNION ALL
                SELECT state_date AS obs_date, stock_code, 'w1' AS boundary_period,
                       'resistance' AS boundary_type,
                       ABS(d1_close / w1_sr_resistance - 1) AS distance_pct,
                       d1_close / w1_sr_resistance - 1 AS close_vs_boundary,
                       d1_close, w1_sr_resistance AS boundary_price,
                       w1_state_hex AS state_hex, w1_state_score AS state_score, ef_count,
                       CASE
                           WHEN d1_close > w1_sr_resistance THEN 'above_resistance'
                           WHEN d1_close < w1_sr_support THEN 'below_support'
                           ELSE 'inside_range'
                       END AS boundary_direction,
                       d1_close > w1_sr_resistance AS above_resistance,
                       d1_close < w1_sr_support AS below_support
                FROM source
                WHERE w1_sr_ready = true AND w1_sr_resistance > 0
                UNION ALL
                SELECT state_date AS obs_date, stock_code, 'mn1' AS boundary_period,
                       'support' AS boundary_type,
                       ABS(d1_close / mn1_sr_support - 1) AS distance_pct,
                       d1_close / mn1_sr_support - 1 AS close_vs_boundary,
                       d1_close, mn1_sr_support AS boundary_price,
                       mn1_state_hex AS state_hex, mn1_state_score AS state_score, ef_count,
                       CASE
                           WHEN d1_close > mn1_sr_resistance THEN 'above_resistance'
                           WHEN d1_close < mn1_sr_support THEN 'below_support'
                           ELSE 'inside_range'
                       END AS boundary_direction,
                       d1_close > mn1_sr_resistance AS above_resistance,
                       d1_close < mn1_sr_support AS below_support
                FROM source
                WHERE mn1_sr_ready = true AND mn1_sr_support > 0
                UNION ALL
                SELECT state_date AS obs_date, stock_code, 'mn1' AS boundary_period,
                       'resistance' AS boundary_type,
                       ABS(d1_close / mn1_sr_resistance - 1) AS distance_pct,
                       d1_close / mn1_sr_resistance - 1 AS close_vs_boundary,
                       d1_close, mn1_sr_resistance AS boundary_price,
                       mn1_state_hex AS state_hex, mn1_state_score AS state_score, ef_count,
                       CASE
                           WHEN d1_close > mn1_sr_resistance THEN 'above_resistance'
                           WHEN d1_close < mn1_sr_support THEN 'below_support'
                           ELSE 'inside_range'
                       END AS boundary_direction,
                       d1_close > mn1_sr_resistance AS above_resistance,
                       d1_close < mn1_sr_support AS below_support
                FROM source
                WHERE mn1_sr_ready = true AND mn1_sr_resistance > 0
            )
            SELECT
                obs_date,
                stock_code,
                boundary_period,
                boundary_type,
                distance_pct,
                d1_close,
                boundary_price,
                state_hex,
                state_score,
                ef_count,
                boundary_direction,
                close_vs_boundary,
                above_resistance,
                below_support
            FROM expanded
            WHERE distance_pct <= ?
            """,
            (
                self.date_str,
                self.boundary_pct,
            ),
        )
        return con.execute(
            "SELECT COUNT(*) FROM sr_boundary_daily WHERE obs_date = CAST(? AS DATE)",
            (self.date_str,),
        ).fetchone()[0]

    def build_durations(self, con: duckdb.DuckDBPyConnection) -> int:
        con.execute(
            """
            INSERT INTO state_duration_daily (
                obs_date,
                stock_code,
                d1_close,
                mn1_state_hex,
                w1_state_hex,
                d1_state_hex,
                mn1_ef_duration,
                w1_ef_duration,
                d1_ef_duration,
                all_three_ef_duration,
                mn1_contraction_duration,
                w1_contraction_duration,
                d1_contraction_duration,
                mn1_days_since_contraction_exit,
                w1_days_since_contraction_exit,
                d1_days_since_contraction_exit,
                mn1_prev_contraction_duration,
                w1_prev_contraction_duration,
                d1_prev_contraction_duration,
                ef_count
            )
            WITH hist AS (
                SELECT
                    state_date,
                    stock_code,
                    d1_close,
                    mn1_state_hex,
                    w1_state_hex,
                    d1_state_hex,
                    mn1_state_score,
                    w1_state_score,
                    d1_state_score,
                    ef_count,
                    mn1_state_hex IN ('E', 'F') AS mn1_ef,
                    w1_state_hex IN ('E', 'F') AS w1_ef,
                    d1_state_hex IN ('E', 'F') AS d1_ef,
                    mn1_state_hex IN ('E', 'F')
                        AND w1_state_hex IN ('E', 'F')
                        AND d1_state_hex IN ('E', 'F') AS all_three_ef,
                    mn1_state_score < 8 AS mn1_contraction,
                    w1_state_score < 8 AS w1_contraction,
                    d1_state_score < 8 AS d1_contraction
                FROM foundation.d1_perspective_state
                WHERE state_date <= CAST(? AS DATE)
            ),
            groups AS (
                SELECT
                    *,
                    SUM(CASE WHEN NOT mn1_ef THEN 1 ELSE 0 END)
                        OVER (PARTITION BY stock_code ORDER BY state_date) AS mn1_grp,
                    SUM(CASE WHEN NOT w1_ef THEN 1 ELSE 0 END)
                        OVER (PARTITION BY stock_code ORDER BY state_date) AS w1_grp,
                    SUM(CASE WHEN NOT d1_ef THEN 1 ELSE 0 END)
                        OVER (PARTITION BY stock_code ORDER BY state_date) AS d1_grp,
                    SUM(CASE WHEN NOT all_three_ef THEN 1 ELSE 0 END)
                        OVER (PARTITION BY stock_code ORDER BY state_date) AS all_three_grp,
                    SUM(CASE WHEN NOT mn1_contraction THEN 1 ELSE 0 END)
                        OVER (PARTITION BY stock_code ORDER BY state_date) AS mn1_contraction_grp,
                    SUM(CASE WHEN NOT w1_contraction THEN 1 ELSE 0 END)
                        OVER (PARTITION BY stock_code ORDER BY state_date) AS w1_contraction_grp,
                    SUM(CASE WHEN NOT d1_contraction THEN 1 ELSE 0 END)
                        OVER (PARTITION BY stock_code ORDER BY state_date) AS d1_contraction_grp,
                    SUM(CASE WHEN mn1_contraction THEN 1 ELSE 0 END)
                        OVER (PARTITION BY stock_code ORDER BY state_date) AS mn1_expansion_grp,
                    SUM(CASE WHEN w1_contraction THEN 1 ELSE 0 END)
                        OVER (PARTITION BY stock_code ORDER BY state_date) AS w1_expansion_grp,
                    SUM(CASE WHEN d1_contraction THEN 1 ELSE 0 END)
                        OVER (PARTITION BY stock_code ORDER BY state_date) AS d1_expansion_grp
                FROM hist
            ),
            durations AS (
                SELECT
                    *,
                    CASE
                        WHEN mn1_ef THEN COUNT(*) OVER (
                            PARTITION BY stock_code, mn1_grp
                            ORDER BY state_date
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        )
                        ELSE 0
                    END AS mn1_ef_duration,
                    CASE
                        WHEN w1_ef THEN COUNT(*) OVER (
                            PARTITION BY stock_code, w1_grp
                            ORDER BY state_date
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        )
                        ELSE 0
                    END AS w1_ef_duration,
                    CASE
                        WHEN d1_ef THEN COUNT(*) OVER (
                            PARTITION BY stock_code, d1_grp
                            ORDER BY state_date
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        )
                        ELSE 0
                    END AS d1_ef_duration,
                    CASE
                        WHEN all_three_ef THEN COUNT(*) OVER (
                            PARTITION BY stock_code, all_three_grp
                            ORDER BY state_date
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        )
                        ELSE 0
                    END AS all_three_ef_duration
                FROM groups
            ),
            lifecycle AS (
                SELECT
                    *,
                    CASE
                        WHEN mn1_contraction THEN COUNT(*) OVER (
                            PARTITION BY stock_code, mn1_contraction_grp
                            ORDER BY state_date
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        )
                        ELSE 0
                    END AS mn1_contraction_duration,
                    CASE
                        WHEN w1_contraction THEN COUNT(*) OVER (
                            PARTITION BY stock_code, w1_contraction_grp
                            ORDER BY state_date
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        )
                        ELSE 0
                    END AS w1_contraction_duration,
                    CASE
                        WHEN d1_contraction THEN COUNT(*) OVER (
                            PARTITION BY stock_code, d1_contraction_grp
                            ORDER BY state_date
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        )
                        ELSE 0
                    END AS d1_contraction_duration,
                    CASE
                        WHEN NOT mn1_contraction THEN COUNT(*) OVER (
                            PARTITION BY stock_code, mn1_expansion_grp
                            ORDER BY state_date
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        )
                        ELSE 0
                    END AS mn1_days_since_contraction_exit,
                    CASE
                        WHEN NOT w1_contraction THEN COUNT(*) OVER (
                            PARTITION BY stock_code, w1_expansion_grp
                            ORDER BY state_date
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        )
                        ELSE 0
                    END AS w1_days_since_contraction_exit,
                    CASE
                        WHEN NOT d1_contraction THEN COUNT(*) OVER (
                            PARTITION BY stock_code, d1_expansion_grp
                            ORDER BY state_date
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        )
                        ELSE 0
                    END AS d1_days_since_contraction_exit
                FROM durations
            ),
            with_prev AS (
                SELECT
                    *,
                    CASE
                        WHEN NOT mn1_contraction THEN MAX(mn1_contraction_duration) OVER (PARTITION BY stock_code, mn1_expansion_grp)
                        ELSE 0
                    END AS mn1_prev_contraction_duration,
                    CASE
                        WHEN NOT w1_contraction THEN MAX(w1_contraction_duration) OVER (PARTITION BY stock_code, w1_expansion_grp)
                        ELSE 0
                    END AS w1_prev_contraction_duration,
                    CASE
                        WHEN NOT d1_contraction THEN MAX(d1_contraction_duration) OVER (PARTITION BY stock_code, d1_expansion_grp)
                        ELSE 0
                    END AS d1_prev_contraction_duration
                FROM lifecycle
            )
            SELECT
                state_date AS obs_date,
                stock_code,
                d1_close,
                mn1_state_hex,
                w1_state_hex,
                d1_state_hex,
                CAST(mn1_ef_duration AS INTEGER) AS mn1_ef_duration,
                CAST(w1_ef_duration AS INTEGER) AS w1_ef_duration,
                CAST(d1_ef_duration AS INTEGER) AS d1_ef_duration,
                CAST(all_three_ef_duration AS INTEGER) AS all_three_ef_duration,
                CAST(mn1_contraction_duration AS INTEGER) AS mn1_contraction_duration,
                CAST(w1_contraction_duration AS INTEGER) AS w1_contraction_duration,
                CAST(d1_contraction_duration AS INTEGER) AS d1_contraction_duration,
                CAST(mn1_days_since_contraction_exit AS INTEGER) AS mn1_days_since_contraction_exit,
                CAST(w1_days_since_contraction_exit AS INTEGER) AS w1_days_since_contraction_exit,
                CAST(d1_days_since_contraction_exit AS INTEGER) AS d1_days_since_contraction_exit,
                CAST(mn1_prev_contraction_duration AS INTEGER) AS mn1_prev_contraction_duration,
                CAST(w1_prev_contraction_duration AS INTEGER) AS w1_prev_contraction_duration,
                CAST(d1_prev_contraction_duration AS INTEGER) AS d1_prev_contraction_duration,
                ef_count
            FROM with_prev
            WHERE state_date = CAST(? AS DATE)
            """,
            (self.date_str, self.date_str),
        )
        return con.execute(
            "SELECT COUNT(*) FROM state_duration_daily WHERE obs_date = CAST(? AS DATE)",
            (self.date_str,),
        ).fetchone()[0]

    def write_json_outputs(self, con: duckdb.DuckDBPyConnection, counts: dict[str, int]) -> dict[str, str]:
        ef_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM state_ef_daily
            WHERE obs_date = CAST(? AS DATE)
            ORDER BY score_sum DESC, stock_code
            """,
            (self.date_str,),
        )
        distribution_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM state_distribution_daily
            WHERE obs_date = CAST(? AS DATE)
            ORDER BY period, cnt DESC, state_hex
            """,
            (self.date_str,),
        )
        transition_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM state_transition_daily
            WHERE obs_date = CAST(? AS DATE)
            ORDER BY period, stock_code
            """,
            (self.date_str,),
        )
        boundary_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM sr_boundary_daily
            WHERE obs_date = CAST(? AS DATE)
            ORDER BY distance_pct ASC, boundary_period, boundary_type, stock_code
            """,
            (self.date_str,),
        )
        duration_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM state_duration_daily
            WHERE obs_date = CAST(? AS DATE)
            ORDER BY all_three_ef_duration DESC, d1_ef_duration DESC, stock_code
            """,
            (self.date_str,),
        )

        base = {
            "date": self.date_str,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "foundation_db": str(self.foundation_db),
            "cache_db": str(self.cache_db),
            "research_only": True,
        }
        payloads = {
            "state_ef": {
                **base,
                "schema_version": "state_ef_cache_v1",
                "cache_scope": "all_three_ef_raw",
                "total": len(ef_rows),
                "rows": ef_rows,
            },
            "state_distribution": {
                **base,
                "schema_version": "state_distribution_cache_v1",
                "total": len(distribution_rows),
                "rows": distribution_rows,
            },
            "state_transition": {
                **base,
                "schema_version": "state_transition_cache_v1",
                "lookback_days": 10,
                "total": len(transition_rows),
                "rows": transition_rows,
            },
            "sr_boundary": {
                **base,
                "schema_version": "sr_boundary_cache_v2",
                "boundary_pct": self.boundary_pct,
                "total": len(boundary_rows),
                "rows": boundary_rows,
            },
            "state_duration": {
                **base,
                "schema_version": "state_duration_cache_v2",
                "total": len(duration_rows),
                "rows": duration_rows,
            },
        }
        outputs: dict[str, str] = {}
        for name, payload in payloads.items():
            path = self.out_dir / f"{name}_{self.date_ymd}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            latest = self.out_dir / f"{name}_latest.json"
            latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            outputs[name] = str(path)
            outputs[f"{name}_latest"] = str(latest)

        manifest = {
            **base,
            "schema_version": "state_cache_manifest_v1",
            "counts": counts,
            "outputs": outputs,
        }
        manifest_path = self.out_dir / f"state_cache_manifest_{self.date_ymd}.json"
        manifest_latest = self.out_dir / "state_cache_manifest_latest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest_latest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        outputs["manifest"] = str(manifest_path)
        outputs["manifest_latest"] = str(manifest_latest)
        return outputs

    def validate(self, con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
        raw_count = con.execute(
            """
            SELECT COUNT(*)
            FROM foundation.d1_perspective_state
            WHERE state_date = CAST(? AS DATE)
              AND mn1_state_hex IN ('E', 'F')
              AND w1_state_hex IN ('E', 'F')
              AND d1_state_hex IN ('E', 'F')
            """,
            (self.date_str,),
        ).fetchone()[0]
        cache_count = con.execute(
            "SELECT COUNT(*) FROM state_ef_daily WHERE obs_date = CAST(? AS DATE)",
            (self.date_str,),
        ).fetchone()[0]
        return {
            "all_three_ef_raw_count": raw_count,
            "state_ef_cache_count": cache_count,
            "all_three_ef_count_match": raw_count == cache_count,
        }

    def build(self) -> dict[str, Any]:
        if not self.foundation_db.exists():
            raise FileNotFoundError(f"foundation DB not found: {self.foundation_db}")
        con = self.connect()
        try:
            self.create_tables(con)
            self.clear_date(con)
            counts = {
                "all_three_ef_count": self.build_all_three_ef(con),
                "distribution_rows": self.build_distribution(con),
                "transition_rows": self.build_transitions(con),
                "sr_boundary_rows": self.build_sr_boundary(con),
                "duration_rows": self.build_durations(con),
            }
            validation = self.validate(con)
            if not validation["all_three_ef_count_match"]:
                raise RuntimeError(f"state EF cache validation failed: {validation}")
            generated_at = datetime.now(timezone.utc).isoformat()
            con.execute(
                """
                INSERT INTO state_cache_manifest
                (
                    obs_date,
                    generated_at,
                    foundation_db,
                    boundary_pct,
                    all_three_ef_count,
                    distribution_rows,
                    transition_rows,
                    sr_boundary_rows,
                    duration_rows,
                    research_only
                )
                VALUES (CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, ?, true)
                """,
                (
                    self.date_str,
                    generated_at,
                    str(self.foundation_db),
                    self.boundary_pct,
                    counts["all_three_ef_count"],
                    counts["distribution_rows"],
                    counts["transition_rows"],
                    counts["sr_boundary_rows"],
                    counts["duration_rows"],
                ),
            )
            outputs = self.write_json_outputs(con, counts)
            return {
                "schema_version": "state_cache_build_result_v1",
                "ok": True,
                "date": self.date_str,
                "generated_at": generated_at,
                "foundation_db": str(self.foundation_db),
                "cache_db": str(self.cache_db),
                "boundary_pct": self.boundary_pct,
                "counts": counts,
                "validation": validation,
                "outputs": outputs,
                "research_only": True,
            }
        finally:
            con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build daily state cache tables and JSON outputs.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--foundation-db", type=Path)
    parser.add_argument("--cache-db", type=Path, default=default_cache_db())
    parser.add_argument("--boundary-pct", type=float, default=0.03)
    args = parser.parse_args()

    builder = StateCacheBuilder(
        date_str=args.date,
        foundation_db=args.foundation_db or default_foundation_db(args.date),
        cache_db=args.cache_db,
        boundary_pct=args.boundary_pct,
    )
    result = builder.build()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
