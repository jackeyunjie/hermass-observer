#!/usr/bin/env python3
"""Q4 fix + segment + trend 简化版"""
import duckdb, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DB = str(ROOT / "outputs" / "p116_foundation_20260602" / "p116_foundation.duckdb")
con = duckdb.connect(DB, read_only=True)
res = {}

# Precompute medians
am, bm = con.execute("""
    SELECT MEDIAN(d1_atr_ratio_pct), MEDIAN(d1_bb_width_q20_20)
    FROM d1_perspective_state WHERE d1_state_hex IN('-E','-F')
        AND d1_atr_ratio_pct IS NOT NULL AND d1_bb_width_q20_20 IS NOT NULL
""").fetchone()

print(f"Medians: ATR={am:.1f}% BB={bm:.3f}", flush=True)

AM = am
BM = bm

# Q4: Fix with simple step-by-step
r = con.execute("""
WITH src AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex,
        d1_atr_ratio_pct, d1_bb_width_q20_20,
        LAG(d1_state_hex) OVER(PARTITION BY stock_code ORDER BY state_date) AS prev
    FROM d1_perspective_state WHERE d1_close > 0 AND d1_atr_ratio_pct IS NOT NULL
),
tagged AS (
    SELECT *,
        CASE WHEN d1_state_hex IN('-E','-F') AND d1_atr_ratio_pct < """ + str(AM) + """ AND d1_bb_width_q20_20 < """ + str(BM) + """ THEN 1 ELSE 0 END AS dp
    FROM src
),
hist AS (
    SELECT *,
        SUM(dp) OVER(PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 9 PRECEDING AND 1 PRECEDING) AS hc
    FROM tagged
),
rev AS (
    SELECT hc,
        LEAD(d1_close,20) OVER(PARTITION BY stock_code ORDER BY state_date)/d1_close-1 AS r20
    FROM hist
    WHERE d1_state_hex IN('E','F') AND prev IN('-E','-F') AND mn1_state_hex NOT IN('E','F')
),
valid AS (
    SELECT * FROM rev WHERE r20 IS NOT NULL
)
SELECT 
    CASE WHEN hc=0 THEN '0d' WHEN hc<=2 THEN '1-2d' WHEN hc<=4 THEN '3-4d' WHEN hc<=7 THEN '5-7d' ELSE '8-10d' END g,
    COUNT(*) n, ROUND(AVG(r20)*100,2) a20, ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr
FROM valid
GROUP BY g ORDER BY AVG(hc)
""").fetchall()
res["q4"] = [{"g":r[0],"n":r[1],"r20":r[2],"wr":r[3]} for r in r]
print(f"Q4: {len(res['q4'])} groups", flush=True)

# Market segment
r = con.execute("""
SELECT 
    CASE WHEN s.stock_code BETWEEN '000000' AND '002999' THEN '主板中小'
         WHEN s.stock_code BETWEEN '300000' AND '301999' THEN '创业板'
         WHEN s.stock_code BETWEEN '688000' AND '689999' THEN '科创板'
         WHEN s.stock_code BETWEEN '600000' AND '605999' THEN '沪主板' ELSE '其他' END seg,
    COUNT(*) n,
    ROUND(AVG((L.d1_close/s.d1_close-1))*100,2) a20,
    ROUND(SUM(CASE WHEN L.d1_close>s.d1_close THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr
FROM d1_perspective_state s
JOIN d1_perspective_state L ON s.stock_code=L.stock_code AND s.state_date+20=L.state_date
JOIN d1_perspective_state s2 ON s.stock_code=s2.stock_code AND s.state_date=s2.state_date-1
WHERE s.d1_state_hex IN('E','F') AND s2.d1_state_hex IN('-E','-F') AND s.mn1_state_hex NOT IN('E','F')
GROUP BY seg ORDER BY n DESC
""").fetchall()
res["segment"] = [{"seg":r[0],"n":r[1],"r20":r[2],"wr":r[3]} for r in r]
print(f"Segment: {len(res['segment'])} groups", flush=True)

# Trend filter
r = con.execute("""
SELECT 
    CASE WHEN s.mn1_state_hex IN('8','9','A','B','C','D') AND s.w1_state_hex IN('8','9','A','B','C','D') THEN 'MN1+W1双扩张'
         WHEN s.mn1_state_hex IN('8','9','A','B','C','D') THEN '仅MN1扩张(高位)'
         WHEN s.w1_state_hex IN('8','9','A','B','C','D') THEN '仅W1扩张'
         ELSE 'MN1+W1双收缩(低位)' END trend,
    COUNT(*) n,
    ROUND(AVG((L.d1_close/s.d1_close-1))*100,2) a20,
    ROUND(SUM(CASE WHEN L.d1_close>s.d1_close THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr
FROM d1_perspective_state s
JOIN d1_perspective_state L ON s.stock_code=L.stock_code AND s.state_date+20=L.state_date
JOIN d1_perspective_state s2 ON s.stock_code=s2.stock_code AND s.state_date=s2.state_date-1
WHERE s.d1_state_hex IN('E','F') AND s2.d1_state_hex IN('-E','-F') AND s.mn1_state_hex NOT IN('E','F')
GROUP BY trend ORDER BY n DESC
""").fetchall()
res["trend"] = [{"trend":r[0],"n":r[1],"r20":r[2],"wr":r[3]} for r in r]
print(f"Trend: {len(res['trend'])} groups", flush=True)

con.close()
print(json.dumps(res, indent=2, ensure_ascii=False))
