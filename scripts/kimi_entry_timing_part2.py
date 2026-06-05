#!/usr/bin/env python3
"""Kimi任务 Part2: 精确入场时机 — 收缩观测指标细粒度过滤"""
import duckdb, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DB = str(ROOT / "outputs" / "p116_foundation_20260602" / "p116_foundation.duckdb")
con = duckdb.connect(DB, read_only=True)
results = {}

BASE_SQL = """
WITH base AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex,
        d1_atr_ratio_pct, d1_bb_width_q20_20, d1_adx14,
        AVG(d1_close) OVER (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma200
    FROM d1_perspective_state WHERE d1_close > 0
),
ent AS (
    SELECT *, d1_close > sma200 AS above_ma,
        LAG(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev,
        LEAD(d1_close,20) OVER(PARTITION BY stock_code ORDER BY state_date)/d1_close-1 AS r20
    FROM base WHERE sma200 > 0
),
rev AS (
    SELECT d1_close, d1_atr_ratio_pct AS atr, d1_bb_width_q20_20 AS bb, d1_adx14 AS adx,
        stock_code, state_date, r20
    FROM ent
    WHERE d1_state_hex IN ('E','F') AND prev IN ('-E','-F') AND mn1_state_hex NOT IN ('E','F') AND above_ma
)
"""

# ATR 三分位
r = con.execute(BASE_SQL + """
, with_q AS (
    SELECT atr, d1_close, stock_code, state_date, r20, NTILE(3) OVER(ORDER BY atr) AS t FROM rev WHERE atr IS NOT NULL
),
fwd AS (
    SELECT t, atr, r20 FROM with_q WHERE r20 IS NOT NULL
)
SELECT t, COUNT(*) AS n, ROUND(AVG(r20)*100,2) AS a20, ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) AS wr,
    ROUND(MIN(atr),1)||'~'||ROUND(MAX(atr),1) AS rng
FROM fwd GROUP BY t ORDER BY t
""").fetchall()
results["atr_tercile"] = [{"t": r[0], "n": r[1], "r20": r[2], "wr": r[3], "range": r[4]} for r in r]

# BB 三分位
r = con.execute(BASE_SQL + """
, with_q AS (
    SELECT bb, d1_close, stock_code, state_date, r20, NTILE(3) OVER(ORDER BY bb) AS t FROM rev WHERE bb IS NOT NULL
),
fwd AS (
    SELECT t, bb, r20 FROM with_q WHERE r20 IS NOT NULL
)
SELECT t, COUNT(*) AS n, ROUND(AVG(r20)*100,2) AS a20, ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) AS wr,
    ROUND(MIN(bb),2)||'~'||ROUND(MAX(bb),2) AS rng
FROM fwd GROUP BY t ORDER BY t
""").fetchall()
results["bb_tercile"] = [{"t": r[0], "n": r[1], "r20": r[2], "wr": r[3], "range": r[4]} for r in r]

# ADX 三分位
r = con.execute(BASE_SQL + """
, with_q AS (
    SELECT adx, d1_close, stock_code, state_date, r20, NTILE(3) OVER(ORDER BY adx) AS t FROM rev WHERE adx IS NOT NULL
),
fwd AS (
    SELECT t, adx, r20 FROM with_q WHERE r20 IS NOT NULL
)
SELECT t, COUNT(*) AS n, ROUND(AVG(r20)*100,2) AS a20, ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) AS wr,
    ROUND(MIN(adx),1)||'~'||ROUND(MAX(adx),1) AS rng
FROM fwd GROUP BY t ORDER BY t
""").fetchall()
results["adx_tercile"] = [{"t": r[0], "n": r[1], "r20": r[2], "wr": r[3], "range": r[4]} for r in r]

# 叠加: ATR<下三分位 AND BB<下三分位
r = con.execute(BASE_SQL + """
, stats AS (
    SELECT (SELECT atr FROM rev ORDER BY atr LIMIT 1 OFFSET (SELECT COUNT(*)/3 FROM rev)) AS a33,
           (SELECT bb FROM rev ORDER BY bb LIMIT 1 OFFSET (SELECT COUNT(*)/3 FROM rev)) AS b33
),
flt AS (
    SELECT r.* FROM rev r, stats s WHERE r.atr < s.a33 AND r.bb < s.b33
)
SELECT COUNT(*) AS n, ROUND(AVG(r20)*100,2) AS a20, ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) AS wr
FROM flt WHERE r20 IS NOT NULL
""").fetchone()
results["best_combo"] = {"n": r[0], "r20": r[1], "wr": r[2]}

con.close()
print(json.dumps(results, indent=2, ensure_ascii=False))
