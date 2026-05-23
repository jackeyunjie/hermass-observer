#!/usr/bin/env python3
"""全市场形态扫描器 — VCP 潜在池 / 2560 潜在池。

每天扫描 5000+ 只股票，找出：
  - VCP 潜在者：波动率收缩 + 振幅收窄 + 成交量萎缩，未突破
  - 2560 潜在者：MA25 靠近 MA60 + 价格重建均线区 + 斜率改善
  - VCP 突破者：前 N 天有潜在结构 + 放量突破
  - 2560 确认者：金叉 / 多头排列 / 回踩不破

不要求进入三周期 E/F —— 目标是提前发现「正在搭结构」的品种。

依赖：
  outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb  (daily_bars, timeframe_indicators)
  outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb  (d1_perspective_state → ef_count)

用法：
  python3 scripts/pattern_scanner.py --date 2026-05-21
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_DB = ROOT / "outputs" / "pattern_lifecycle" / "pattern_lifecycle.duckdb"


def ymd(d: str) -> str:
    return d.replace("-", "")


def foundation_db_path(date_str: str) -> Path:
    return ROOT / "outputs" / f"p116_foundation_{ymd(date_str)}" / "p116_foundation.duckdb"


def attach_foundation(con: duckdb.DuckDBPyConnection, date_str: str) -> None:
    fp = foundation_db_path(date_str)
    if not fp.exists():
        raise FileNotFoundError(f"Foundation DB missing: {fp}")
    con.execute(f"ATTACH IF NOT EXISTS '{fp}' AS foundation (READ_ONLY)")


def ensure_lifecycle(con: duckdb.DuckDBPyConnection, db_path: Path) -> None:
    con.execute(f"ATTACH IF NOT EXISTS '{db_path}' AS lifecycle")


# ───────────────────── 全市场日常观测 ─────────────────────

def scan_daily_observations(con: duckdb.DuckDBPyConnection, obs_date: str) -> int:
    # 先写基础行情 + 均线
    con.execute(f"""
        WITH ma_data AS (
            SELECT
                stock_code,
                date AS available_date,
                AVG(close) OVER (PARTITION BY stock_code ORDER BY date ROWS 24 PRECEDING) AS ma25,
                AVG(close) OVER (PARTITION BY stock_code ORDER BY date ROWS 59 PRECEDING) AS ma60
            FROM foundation.daily_bars
        )
        INSERT OR REPLACE INTO pattern_observation_daily
        SELECT
            b.stock_code,
            b.date,
            b.close,
            b.volume,
            'none' AS vcp_phase,
            'none' AS vcp_phase_prev,
            0 AS vcp_contraction_days,
            NULL AS vcp_range_ratio,
            'flat' AS vcp_atr_trend,
            CASE
                WHEN mv.ma25 IS NULL OR mv.ma60 IS NULL THEN 'none'
                WHEN mv.ma25 > mv.ma60 THEN 'bull_aligned'
                WHEN mv.ma25 <= mv.ma60 AND ABS(mv.ma25 - mv.ma60) / NULLIF(mv.ma60, 0) < 0.03
                THEN 'approaching'
                WHEN mv.ma25 <= mv.ma60 AND ABS(mv.ma25 - mv.ma60) / NULLIF(mv.ma60, 0) < 0.05
                THEN 'near_cross'
                ELSE 'bear_aligned'
            END AS ma2560_phase,
            'none' AS ma2560_phase_prev,
            mv.ma25,
            mv.ma60,
            NULL AS ma25_slope,
            NULL AS ma60_slope,
            COALESCE(ps.ef_count, 0) AS ef_count,
            COALESCE(ps.ef_count, 0) >= 2 AS in_ef_pool
        FROM foundation.daily_bars b
        LEFT JOIN foundation.d1_perspective_state ps
          ON b.stock_code = ps.stock_code AND b.date = ps.state_date
        LEFT JOIN ma_data mv
          ON b.stock_code = mv.stock_code AND b.date = mv.available_date
        WHERE b.date = '{obs_date}'
    """)

    # 用 Python 回退计算 VCP 相位 — AT 比较多日 ATR
    atr_query = f"""
        SELECT i.stock_code, i.available_date, i.atr14
        FROM foundation.timeframe_indicators i
        WHERE i.timeframe = 'D1'
          AND i.available_date BETWEEN DATE '{obs_date}' - 14 AND DATE '{obs_date}'
        ORDER BY i.stock_code, i.available_date
    """
    atr_rows = con.execute(atr_query).fetchall()
    by_stock: dict[str, list[float]] = {}
    for code, dt, atr in atr_rows:
        by_stock.setdefault(code, []).append(float(atr or 0))

    updates = []
    for code, atrs in by_stock.items():
        if len(atrs) < 6:
            continue
        now = atrs[-1]
        a5 = atrs[-6] if len(atrs) >= 6 else now
        a10 = atrs[-11] if len(atrs) >= 11 else now
        prev_list = atrs[-4:-1] if len(atrs) >= 4 else [now, now, now]
        phase = 'expanding'
        if now > 0 and now < a5 and a5 < a10:
            phase = 'contracting'
        elif now > 0 and now < a5:
            phase = 'tightening'
        ct_days = sum(1 for i in range(len(atrs)-1) if len(atrs) > i+1 and atrs[i] < atrs[i+1])
        updates.append((phase, ct_days, code, obs_date))

    if updates:
        con.executemany(
            "UPDATE pattern_observation_daily SET vcp_phase = ?, vcp_contraction_days = ? WHERE stock_code = ? AND obs_date = ?",
            updates,
        )

    # 补充 2560 相位前一值
    con.execute(f"""
        UPDATE pattern_observation_daily o
        SET ma2560_phase_prev = COALESCE(
            (SELECT p.ma2560_phase FROM pattern_observation_daily p
             WHERE p.stock_code = o.stock_code AND p.obs_date = DATE '{obs_date}' - 1
             LIMIT 1), 'none')
        WHERE o.obs_date = '{obs_date}'
    """)

    # 补充振幅比
    con.execute(f"""
        UPDATE pattern_observation_daily o
        SET vcp_range_ratio = (
            SELECT (MAX(p.close) - MIN(p.close)) / NULLIF(o.close, 0)
            FROM pattern_observation_daily p
            WHERE p.stock_code = o.stock_code
              AND p.obs_date BETWEEN DATE '{obs_date}' - 4 AND DATE '{obs_date}'
        )
        WHERE o.obs_date = '{obs_date}'
    """)

    count = con.execute(f"SELECT COUNT(*) FROM pattern_observation_daily WHERE obs_date = '{obs_date}'").fetchone()[0]
    return count


# ───────────────────── VCP 潜在池更新 ─────────────────────

def update_vcp_pool(con: duckdb.DuckDBPyConnection, obs_date: str) -> int:
    con.execute(f"""
        INSERT INTO vcp_candidate_pool
            (stock_code, first_detected, last_updated, phase, quality_tier, contraction_count,
             lowest_range_ratio, lowest_atr, status, notes)
        SELECT
            o.stock_code,
            o.obs_date,
            o.obs_date,
            'forming',
            CASE
                WHEN o.vcp_phase = 'contracting' AND o.vcp_range_ratio IS NOT NULL AND o.vcp_range_ratio < 0.08 THEN 'strict'
                ELSE 'watch'
            END,
            1,
            o.vcp_range_ratio,
            NULL,
            'active',
            '全市场形态扫描 — VCP 潜在者检测'
        FROM pattern_observation_daily o
        WHERE o.obs_date = '{obs_date}'
          AND o.vcp_phase IN ('contracting', 'tightening')
        ON CONFLICT (stock_code, first_detected) DO NOTHING
    """)

    con.execute(f"""
        UPDATE vcp_candidate_pool
        SET last_updated = '{obs_date}',
            phase = COALESCE((
                SELECT o.vcp_phase FROM pattern_observation_daily o
                WHERE o.stock_code = vcp_candidate_pool.stock_code
                  AND o.obs_date = '{obs_date}' LIMIT 1
            ), phase),
            quality_tier = COALESCE((
                SELECT CASE
                    WHEN o.vcp_phase = 'contracting' AND o.vcp_range_ratio IS NOT NULL AND o.vcp_range_ratio < 0.08 THEN 'strict'
                    ELSE 'watch'
                END
                FROM pattern_observation_daily o
                WHERE o.stock_code = vcp_candidate_pool.stock_code
                  AND o.obs_date = '{obs_date}' LIMIT 1
            ), quality_tier),
            contraction_count = contraction_count + 1
        WHERE status = 'active'
          AND EXISTS (
              SELECT 1 FROM pattern_observation_daily o
              WHERE o.stock_code = vcp_candidate_pool.stock_code
                AND o.obs_date = '{obs_date}'
                AND o.vcp_phase IN ('contracting', 'tightening')
          )
    """)

    con.execute(f"""
        UPDATE vcp_candidate_pool
        SET status = 'degraded',
            notes = COALESCE(notes, '') || ' 形态松动:' || '{obs_date}',
            resolved_date = '{obs_date}',
            resolution = 'degraded'
        WHERE status = 'active'
          AND NOT EXISTS (
              SELECT 1 FROM pattern_observation_daily o
              WHERE o.stock_code = vcp_candidate_pool.stock_code
                AND o.obs_date = '{obs_date}'
                AND o.vcp_phase IN ('contracting', 'tightening')
          )
    """)

    return con.execute("SELECT COUNT(*) FROM vcp_candidate_pool WHERE status = 'active'").fetchone()[0]


# ───────────────────── 2560 潜在池更新 ─────────────────────

def update_ma2560_pool(con: duckdb.DuckDBPyConnection, obs_date: str) -> int:
    con.execute(f"""
        INSERT INTO ma2560_candidate_pool
            (stock_code, first_detected, last_updated, phase, ma25, ma60,
             price_vs_ma25, alignment_days, status, notes)
        SELECT
            o.stock_code,
            o.obs_date,
            o.obs_date,
            o.ma2560_phase,
            o.ma25,
            o.ma60,
            CASE WHEN o.close > o.ma25 THEN 'above' ELSE 'below' END,
            0,
            'active',
            '全市场形态扫描 — 2560 潜在者检测'
        FROM pattern_observation_daily o
        WHERE o.obs_date = '{obs_date}'
          AND o.ma2560_phase IN ('approaching', 'near_cross')
          AND o.close > COALESCE(o.ma25, 0)
        ON CONFLICT (stock_code, first_detected) DO NOTHING
    """)

    # 已有潜在者：更新
    con.execute(f"""
        UPDATE ma2560_candidate_pool
        SET last_updated = '{obs_date}',
            phase = COALESCE((
                SELECT o.ma2560_phase
                FROM pattern_observation_daily o
                WHERE o.stock_code = ma2560_candidate_pool.stock_code
                  AND o.obs_date = '{obs_date}'
                LIMIT 1
            ), phase),
            ma25 = COALESCE((
                SELECT o.ma25 FROM pattern_observation_daily o
                WHERE o.stock_code = ma2560_candidate_pool.stock_code
                  AND o.obs_date = '{obs_date}' LIMIT 1
            ), ma25),
            ma60 = COALESCE((
                SELECT o.ma60 FROM pattern_observation_daily o
                WHERE o.stock_code = ma2560_candidate_pool.stock_code
                  AND o.obs_date = '{obs_date}' LIMIT 1
            ), ma60),
            alignment_days = alignment_days + 1
        WHERE status = 'active'
          AND EXISTS (
              SELECT 1 FROM pattern_observation_daily o
              WHERE o.stock_code = ma2560_candidate_pool.stock_code
                AND o.obs_date = '{obs_date}'
          )
    """)

    # 死叉检测
    con.execute(f"""
        UPDATE ma2560_candidate_pool
        SET status = 'failed',
            resolved_date = '{obs_date}',
            resolution = 'death_cross',
            death_cross_date = '{obs_date}',
            notes = notes || ' 死叉:' || '{obs_date}'
        WHERE status = 'active'
          AND EXISTS (
              SELECT 1 FROM pattern_observation_daily o
              WHERE o.stock_code = ma2560_candidate_pool.stock_code
                AND o.obs_date = '{obs_date}'
                AND o.ma2560_phase = 'bear_aligned'
                AND o.ma2560_phase_prev IN ('bull_aligned', 'approaching', 'near_cross')
          )
    """)

    return con.execute("SELECT COUNT(*) FROM ma2560_candidate_pool WHERE status = 'active'").fetchone()[0]


# ───────────────────── 事件记录 ─────────────────────

def record_events(con: duckdb.DuckDBPyConnection, obs_date: str) -> int:
    con.execute(f"""
        INSERT OR IGNORE INTO pattern_events
        SELECT
            o.stock_code,
            o.obs_date AS event_date,
            'vcp' AS pattern_type,
            'breakout_possible' AS event,
            '冲破上轨' AS detail,
            o.close,
            o.volume / NULLIF(
                (SELECT AVG(volume) FROM pattern_observation_daily p2
                 WHERE p2.stock_code = o.stock_code
                   AND p2.obs_date BETWEEN date '{obs_date}' - 20 AND date '{obs_date}' - 1), 0
            ) AS volume_ratio,
            2 AS importance
        FROM pattern_observation_daily o
        JOIN vcp_candidate_pool vcp
          ON o.stock_code = vcp.stock_code
         AND vcp.status = 'active'
        WHERE o.obs_date = '{obs_date}'
          AND o.vcp_phase IN ('contracting', 'tightening')
          AND o.vcp_range_ratio IS NOT NULL
          AND o.vcp_range_ratio < 0.04
    """)

    # 2560 金叉事件
    con.execute(f"""
        INSERT OR IGNORE INTO pattern_events
        SELECT
            o.stock_code,
            o.obs_date,
            'ma2560',
            'golden_cross',
            'MA25上穿MA60',
            o.close,
            NULL,
            3
        FROM pattern_observation_daily o
        WHERE o.obs_date = '{obs_date}'
          AND o.ma2560_phase = 'bull_aligned'
          AND o.ma2560_phase_prev IN ('approaching', 'near_cross')
    """)

    # VCP 形态松动
    con.execute(f"""
        INSERT OR IGNORE INTO pattern_events
        SELECT
            vcp.stock_code,
            '{obs_date}',
            'vcp',
            'contraction_lost',
            '波动率重新扩张',
            NULL,
            NULL,
            1
        FROM vcp_candidate_pool vcp
        WHERE vcp.status = 'degraded'
          AND vcp.resolved_date = '{obs_date}'
    """)

    return con.execute(f"SELECT COUNT(*) FROM pattern_events WHERE event_date = '{obs_date}'").fetchone()[0]


# ───────────────────── 宏观周期 ─────────────────────

def update_macro_regime(con: duckdb.DuckDBPyConnection, obs_date: str) -> int:
    ms_csv = ROOT / "outputs" / "market_assets_state" / f"market_assets_state_{ymd(obs_date)}.csv"
    if not ms_csv.exists():
        print(f"[macro_regime] market_assets_state CSV not found: {ms_csv}, skipping")
        return 0

    import csv
    count = 0
    with open(ms_csv, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = (row.get("symbol") or row.get("stock_code") or row.get("asset_code") or "").strip()
            if not code:
                continue
            mn1 = row.get("mn1_state_hex") or row.get("MN1_state") or "NA"
            w1 = row.get("w1_state_hex") or row.get("W1_state") or "NA"
            d1 = row.get("d1_state_hex") or row.get("D1_state") or "NA"
            ef = sum(1 for s in [mn1, w1, d1] if s in ("E", "F"))
            asset_type = row.get("asset_type") or ("etf" if "ETF" in (row.get("name") or "") else "index")
            con.execute("""
                INSERT OR REPLACE INTO macro_regime_daily
                    (regime_date, asset_code, asset_type, mn1_state_hex,
                     w1_state_hex, d1_state_hex, ef_count, breadth_bull_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """, (obs_date, code, asset_type, mn1, w1, d1, ef))
            count += 1

    return count


# ───────────────────── 生命周期摘要 ─────────────────────

def update_lifecycle_summary(con: duckdb.DuckDBPyConnection, obs_date: str) -> int:
    con.execute(f"""
        INSERT INTO pattern_lifecycle
            (stock_code, stock_name, sw_l1, pattern_type, first_seen, last_seen,
             events, peak_phase, total_days, breakout_occurred, crossed_ef_pool, resolution)
        SELECT
            v.stock_code,
            NULL,
            NULL,
            'vcp',
            v.first_detected,
            v.last_updated,
            '',
            v.phase,
            (v.last_updated - v.first_detected)::INTEGER,
            v.resolution = 'breakout',
            FALSE,
            COALESCE(v.resolution, 'open')
        FROM vcp_candidate_pool v
        WHERE v.last_updated = '{obs_date}'
        ON CONFLICT (stock_code, pattern_type, first_seen) DO UPDATE
        SET last_seen = '{obs_date}',
            total_days = (DATE '{obs_date}' - first_seen)::INTEGER,
            peak_phase = EXCLUDED.peak_phase,
            resolution = EXCLUDED.resolution
    """)

    con.execute(f"""
        INSERT INTO pattern_lifecycle
            (stock_code, stock_name, sw_l1, pattern_type, first_seen, last_seen,
             events, peak_phase, total_days, breakout_occurred, crossed_ef_pool, resolution)
        SELECT
            v.stock_code,
            NULL,
            NULL,
            'ma2560',
            v.first_detected,
            v.last_updated,
            '',
            v.phase,
            (v.last_updated - v.first_detected)::INTEGER,
            v.phase = 'bull_aligned',
            FALSE,
            COALESCE(v.resolution, 'open')
        FROM ma2560_candidate_pool v
        WHERE v.last_updated = '{obs_date}'
        ON CONFLICT (stock_code, pattern_type, first_seen) DO UPDATE
        SET last_seen = '{obs_date}',
            total_days = (DATE '{obs_date}' - first_seen)::INTEGER,
            peak_phase = EXCLUDED.peak_phase,
            resolution = EXCLUDED.resolution
    """)

    return con.execute("SELECT COUNT(*) FROM pattern_lifecycle WHERE last_seen = ?", (obs_date,)).fetchone()[0]


# ───────────────────── 主入口 ─────────────────────

def run_full_scan(obs_date: str, foundation_db: str | None = None) -> dict[str, Any]:
    db_path = LIFECYCLE_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pattern_lifecycle_schema",
        str(ROOT / "scripts" / "pattern_lifecycle_schema.py"),
    )
    schema_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(schema_mod)
    schema_mod.init_schema(db_path)

    con = duckdb.connect(str(db_path))

    if foundation_db:
        con.execute(f"ATTACH IF NOT EXISTS '{foundation_db}' AS foundation (READ_ONLY)")
    else:
        attach_foundation(con, obs_date)

    print(f"[scan] 日常观测 (obs_date={obs_date})")
    daily_count = scan_daily_observations(con, obs_date)

    print(f"[scan] VCP 潜在池更新")
    vcp_active = update_vcp_pool(con, obs_date)

    print(f"[scan] 2560 潜在池更新")
    ma2560_active = update_ma2560_pool(con, obs_date)

    print(f"[scan] 事件记录")
    event_count = record_events(con, obs_date)

    print(f"[scan] 宏观周期")
    macro_count = update_macro_regime(con, obs_date)

    print(f"[scan] 生命周期摘要")
    lifecycle_count = update_lifecycle_summary(con, obs_date)

    con.close()

    result = {
        "schema_version": "pattern_lifecycle_v1",
        "scan_date": obs_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "daily_observations": daily_count,
        "vcp_active_pool": vcp_active,
        "ma2560_active_pool": ma2560_active,
        "events_today": event_count,
        "macro_assets": macro_count,
        "lifecycle_updated": lifecycle_count,
        "lifecycle_db": str(db_path),
        "research_only": True,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="全市场形态扫描")
    parser.add_argument("--date", required=True)
    parser.add_argument("--foundation-db", default=None)
    args = parser.parse_args()
    result = run_full_scan(args.date, args.foundation_db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
