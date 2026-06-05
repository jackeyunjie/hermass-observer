#!/usr/bin/env python3
import duckdb
con = duckdb.connect('outputs/p116_foundation_20260602/p116_foundation.duckdb', read_only=True)

r = con.execute("""
WITH b AS (
    SELECT *, AVG(d1_close) OVER w AS ma
    FROM d1_perspective_state WHERE d1_close>0
    WINDOW w AS (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW)
),
e AS (
    SELECT *, LAG(d1_state_hex) OVER w2 AS p, LEAD(d1_state_hex) OVER w2 AS n
    FROM b WHERE ma>0
    WINDOW w2 AS (PARTITION BY stock_code ORDER BY state_date)
)
SELECT 
    SUM(CASE WHEN d1_state_hex IN('-E','-F') AND n IN('E','F') AND d1_close>ma AND mn1_state_hex NOT IN('E','F') THEN 1 ELSE 0 END) AS with_all,
    SUM(CASE WHEN d1_state_hex IN('-E','-F') AND n IN('E','F') AND mn1_state_hex NOT IN('E','F') THEN 1 ELSE 0 END) AS no_ma,
    SUM(CASE WHEN d1_state_hex IN('-E','-F') AND n IN('E','F') AND d1_close>ma THEN 1 ELSE 0 END) AS ma_only
FROM e
""").fetchone()
print(f"with_all(MA+MN1)={r[0]}, no_ma={r[1]}, ma_only={r[2]}")
con.close()
