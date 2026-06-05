#!/usr/bin/env python3
"""Qoder P3 v2: 收缩统计 — 去掉200MA过滤，直接统计"""
import duckdb, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DB = str(ROOT / "outputs" / "p116_foundation_20260602" / "p116_foundation.duckdb")
con = duckdb.connect(DB, read_only=True)
res = {}

# D1=-E/-F 收缩深度 (no MA filter)
r = con.execute("""
SELECT 
    CASE WHEN d1_state_hex='-E' THEN 'D1=-E' WHEN d1_state_hex='-F' THEN 'D1=-F' END AS g,
    COUNT(*) n, ROUND(AVG(d1_atr_ratio_pct),1) a, ROUND(MEDIAN(d1_atr_ratio_pct),1) am,
    ROUND(AVG(d1_bb_width_q20_20),2) b, ROUND(MEDIAN(d1_bb_width_q20_20),2) bm,
    ROUND(AVG(d1_adx14),1) d, ROUND(MEDIAN(d1_adx14),1) dm
FROM d1_perspective_state WHERE d1_state_hex IN ('-E','-F') AND d1_atr_ratio_pct IS NOT NULL
GROUP BY g
UNION ALL
SELECT '全市场', COUNT(*), ROUND(AVG(d1_atr_ratio_pct),1), ROUND(MEDIAN(d1_atr_ratio_pct),1),
    ROUND(AVG(d1_bb_width_q20_20),2), ROUND(MEDIAN(d1_bb_width_q20_20),2),
    ROUND(AVG(d1_adx14),1), ROUND(MEDIAN(d1_adx14),1)
FROM d1_perspective_state WHERE d1_atr_ratio_pct IS NOT NULL
""").fetchall()
res["q1_contraction_levels"] = [{"g":r[0],"n":r[1],"atr_mean":r[2],"atr_med":r[3],"bb_mean":r[4],"bb_med":r[5],"adx_mean":r[6],"adx_med":r[7]} for r in r]

# Q2: D1=-E/-F 时 ATR+BB收缩程度 → 次日反转收益 (no MA, no MN1 filter)
r = con.execute("""
WITH e AS (
    SELECT *, LAG(d1_state_hex) OVER w AS p, LEAD(d1_state_hex) OVER w AS n, LEAD(d1_close,20) OVER w / d1_close - 1 AS r20
    FROM d1_perspective_state WHERE d1_close > 0 AND d1_atr_ratio_pct IS NOT NULL AND d1_bb_width_q20_20 IS NOT NULL
    WINDOW w AS (PARTITION BY stock_code ORDER BY state_date)
),
contr AS (
    SELECT d1_atr_ratio_pct AS atr, d1_bb_width_q20_20 AS bb, r20 FROM e
    WHERE d1_state_hex IN ('-E','-F') AND n IN ('E','F') AND mn1_state_hex NOT IN ('E','F') AND r20 IS NOT NULL
),
m AS (SELECT MEDIAN(atr) am, MEDIAN(bb) bm FROM contr)
SELECT 
    CASE WHEN atr<am AND bb<bm THEN '双重收缩(ATR+BB均<中位)'
         WHEN atr<am THEN '仅ATR收缩'
         WHEN bb<bm THEN '仅BB收缩'
         ELSE '无收缩(ATR+BB均>中位)' END AS g,
    COUNT(*) n, ROUND(AVG(r20)*100,2) a20, ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr,
    ROUND(AVG(atr),1) a, ROUND(AVG(bb),2) b
FROM contr, m WHERE r20 IS NOT NULL GROUP BY g ORDER BY n DESC
""").fetchall()
res["q2_contraction_depth_vs_return"] = [{"g":r[0],"n":r[1],"r20":r[2],"wr":r[3],"atr":r[4],"bb":r[5]} for r in r]

# Q3: 立即反转(D1=-E/-F→次日E/F) vs 3-5天后反转
r = con.execute("""
WITH e AS (
    SELECT *, LAG(d1_state_hex) OVER w AS p, LEAD(d1_state_hex,1) OVER w AS n1, LEAD(d1_state_hex,3) OVER w AS n3,
        LEAD(d1_state_hex,5) OVER w AS n5, LEAD(d1_close,20) OVER w / d1_close - 1 AS r20
    FROM d1_perspective_state WHERE d1_close>0
    WINDOW w AS (PARTITION BY stock_code ORDER BY state_date)
)
SELECT '次日立即反转' AS g, COUNT(*) n, ROUND(AVG(r20)*100,2) a20, ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr
FROM e WHERE d1_state_hex IN('-E','-F') AND n1 IN('E','F') AND mn1_state_hex NOT IN('E','F') AND r20 IS NOT NULL
UNION ALL
SELECT '3-5天后反转', COUNT(*), ROUND(AVG(r20)*100,2), ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1)
FROM e WHERE d1_state_hex IN('-E','-F') AND n3 NOT IN('E','F') AND n5 IN('E','F') AND mn1_state_hex NOT IN('E','F') AND r20 IS NOT NULL
""").fetchall()
res["q3_reversal_timing"] = [{"g":r[0],"n":r[1],"r20":r[2],"wr":r[3]} for r in r]

# Q4: 深度收缩持续时间 — deep标志在反转日前计算，用LAG取前日的deep
r = con.execute("""
WITH meds AS (
    SELECT MEDIAN(d1_atr_ratio_pct) am, MEDIAN(d1_bb_width_q20_20) bm
    FROM d1_perspective_state WHERE d1_state_hex IN('-E','-F') AND d1_atr_ratio_pct IS NOT NULL AND d1_bb_width_q20_20 IS NOT NULL
),
scored AS (
    SELECT t.*, m.am, m.bm,
        CASE WHEN t.d1_state_hex IN('-E','-F') AND t.d1_atr_ratio_pct < m.am AND t.d1_bb_width_q20_20 < m.bm THEN 1 ELSE 0 END AS deep,
        LAG(t.d1_state_hex) OVER (PARTITION BY t.stock_code ORDER BY t.state_date) AS p,
        LAG(CASE WHEN t.d1_state_hex IN('-E','-F') AND t.d1_atr_ratio_pct < m.am AND t.d1_bb_width_q20_20 < m.bm THEN 1 ELSE 0 END) OVER (PARTITION BY t.stock_code ORDER BY t.state_date) AS prev_deep,
        LEAD(t.d1_close,20) OVER (PARTITION BY t.stock_code ORDER BY t.state_date)/t.d1_close-1 AS r20
    FROM d1_perspective_state t, meds m WHERE d1_close>0 AND d1_atr_ratio_pct IS NOT NULL AND d1_bb_width_q20_20 IS NOT NULL
),
streaks AS (
    SELECT *,
        SUM(deep) OVER (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 9 PRECEDING AND 1 PRECEDING) AS hist_contr
    FROM scored
)
SELECT CASE WHEN hist_contr<=1 THEN '<2天' WHEN hist_contr<=3 THEN '2-4天' WHEN hist_contr<=6 THEN '5-7天' ELSE '8-10天' END AS g,
    COUNT(*) n, ROUND(AVG(r20)*100,2) a20, ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr
FROM streaks
WHERE d1_state_hex IN('E','F') AND p IN('-E','-F') AND mn1_state_hex NOT IN('E','F') AND r20 IS NOT NULL AND prev_deep>0
GROUP BY g ORDER BY n DESC
""").fetchall()
res["q4_deep_contraction_duration"] = [{"g":r[0],"n":r[1],"r20":r[2],"wr":r[3]} for r in r]

con.close()
print(json.dumps(res, indent=2, ensure_ascii=False))
