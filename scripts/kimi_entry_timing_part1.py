#!/usr/bin/env python3
"""Kimi P1 v2: 精确入场 — 放宽条件加MA对比"""
import duckdb, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DB = str(ROOT / "outputs" / "p116_foundation_20260602" / "p116_foundation.duckdb")
con = duckdb.connect(DB, read_only=True)
res = {}

for use_ma, lab in [(False, "noMA"), (True, "ma200")]:
    mf = "AND d1_close > ma" if use_ma else ""
    r = con.execute("""
    WITH b AS (
        SELECT *, AVG(d1_close) OVER (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS ma
        FROM d1_perspective_state WHERE d1_close > 0
    ),
    e AS (
        SELECT *, LAG(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS p FROM b WHERE ma > 0
    ),
    v AS (
        SELECT d1_close, stock_code, state_date FROM e
        WHERE d1_state_hex IN ('E','F') AND p IN ('-E','-F','-C','-D') AND mn1_state_hex NOT IN ('E','F') """ + mf + """
    ),
    f AS (
        SELECT LEAD(d1_close,20) OVER(PARTITION BY stock_code ORDER BY state_date)/d1_close-1 AS r20 FROM v
    )
    SELECT COUNT(*), ROUND(AVG(r20)*100,2), ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) FROM f WHERE r20 IS NOT NULL
    """).fetchone()
    res[lab] = {"n": r[0], "r20": r[1], "wr": r[2]}

r = con.execute("""
WITH b AS (SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex, w1_state_hex FROM d1_perspective_state WHERE d1_close>0),
e AS (SELECT *, LAG(d1_state_hex) OVER(PARTITION BY stock_code ORDER BY state_date) AS p FROM b),
v AS (SELECT mn1_state_hex||'/'||w1_state_hex AS mw, d1_close, stock_code, state_date FROM e
    WHERE d1_state_hex IN('E','F') AND p IN('-E','-F','-C','-D') AND mn1_state_hex NOT IN('E','F')),
f AS (SELECT mw, LEAD(d1_close,20) OVER(PARTITION BY stock_code ORDER BY state_date)/d1_close-1 AS r20 FROM v),
g AS (SELECT mw, COUNT(*) n, ROUND(AVG(r20)*100,2) a20, ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr FROM f WHERE r20 IS NOT NULL GROUP BY mw HAVING COUNT(*)>=500)
SELECT * FROM g ORDER BY a20 DESC LIMIT 20
""").fetchall()
res["by_mn_w1"] = [{"c": x[0], "n": x[1], "r20": x[2], "wr": x[3]} for x in r]

r = con.execute("""
SELECT CASE WHEN cd<=3 THEN '1-3d' WHEN cd<=6 THEN '4-6d' WHEN cd<=10 THEN '7-10d' ELSE '>10d' END AS g,
    COUNT(*) n, ROUND(AVG(r20)*100,2) a20, ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr
FROM (
    SELECT SUM(CASE WHEN d1_state_hex IN('-E','-F','-C','-D') THEN 1 ELSE 0 END) OVER(PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 19 PRECEDING AND 1 PRECEDING) AS cd,
        LEAD(d1_close,20) OVER(PARTITION BY stock_code ORDER BY state_date)/d1_close-1 AS r20
    FROM (SELECT *, LAG(d1_state_hex) OVER(PARTITION BY stock_code ORDER BY state_date) AS p FROM d1_perspective_state WHERE d1_close>0)
    WHERE d1_state_hex IN('E','F') AND p IN('-E','-F') AND mn1_state_hex NOT IN('E','F')
) WHERE r20 IS NOT NULL GROUP BY g ORDER BY n DESC
""").fetchall()
res["streak"] = [{"g": x[0], "n": x[1], "r20": x[2], "wr": x[3]} for x in r]

con.close()
print(json.dumps(res, indent=2, ensure_ascii=False))
