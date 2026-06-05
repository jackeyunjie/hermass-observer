#!/usr/bin/env python3
"""多维收缩观察：高度/宽度/深度/广度 — SR距离+相对位置+时间压缩+周期共振

高度: 价格在SR区间的相对位置 (0=支撑, 1=阻力)
宽度: SR区间的宽度 (阻力-支撑)/价格 → 宽度收缩率
深度: 连续收缩天数 (宽度持续减少的天数)
广度: 三周期SR是否同步收缩 (D1+W1+MN1)

核心假设: 价格在支撑位附近 + SR区间持续收缩 + 三周期同步 → 高质量突破前兆
"""
import duckdb, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DB = str(ROOT / "outputs" / "p116_foundation_20260602" / "p116_foundation.duckdb")
con = duckdb.connect(DB, read_only=True)
res = {}

# ══════════════════════════════════════════════════════════
# 1. SR区间宽度和价格位置的分布（全市场 vs D1=-E/-F）
# ══════════════════════════════════════════════════════════
r = con.execute("""
WITH stats AS (
    SELECT 
        CASE WHEN d1_state_hex IN('-E','-F') THEN 'D1=-E/-F' ELSE '全市场' END AS grp,
        d1_close, d1_sr_support, d1_sr_resistance,
        (d1_sr_resistance - d1_sr_support) / NULLIF(d1_close,0) AS sr_width,
        (d1_close - d1_sr_support) / NULLIF(d1_sr_resistance - d1_sr_support, 0) AS sr_position
    FROM d1_perspective_state 
    WHERE d1_close > 0 AND d1_sr_support > 0 AND d1_sr_resistance > 0
        AND d1_sr_support < d1_sr_resistance
        AND (d1_close - d1_sr_support) / NULLIF(d1_sr_resistance - d1_sr_support, 0) BETWEEN-0.5 AND 1.5
)
SELECT grp, COUNT(*) n,
    ROUND(AVG(sr_width)*100,2) avg_width_pct,
    ROUND(MEDIAN(sr_width)*100,2) med_width_pct,
    ROUND(AVG(sr_position)*100,1) avg_pos,
    ROUND(MEDIAN(sr_position)*100,1) med_pos
FROM stats GROUP BY grp
""").fetchall()
res["sr_stats"] = [{"grp":r[0],"n":r[1],"avg_width":r[2],"med_width":r[3],"avg_pos":r[4],"med_pos":r[5]} for r in r]

# ══════════════════════════════════════════════════════════
# 2. SR收缩: 宽度连续缩小的天数 → 后续反转收益
# ══════════════════════════════════════════════════════════
r = con.execute("""
WITH base AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex,
        d1_sr_support, d1_sr_resistance,
        (d1_sr_resistance - d1_sr_support)/NULLIF(d1_close,0) AS sr_w,
        LAG(d1_state_hex) OVER(PARTITION BY stock_code ORDER BY state_date) AS prev
    FROM d1_perspective_state WHERE d1_close>0 AND d1_sr_support>0 AND d1_sr_resistance>0
),
-- 宽度是否在缩小
compress AS (
    SELECT *, sr_w < LAG(sr_w) OVER(PARTITION BY stock_code ORDER BY state_date) AS narrowing,
        LAG(sr_w) OVER(PARTITION BY stock_code ORDER BY state_date) AS prev_w,
        LAG(sr_w,3) OVER(PARTITION BY stock_code ORDER BY state_date) AS w3_ago,
        LAG(sr_w,5) OVER(PARTITION BY stock_code ORDER BY state_date) AS w5_ago
    FROM base
),
-- 连续缩窄天数，从反转日往前看
streaks AS (
    SELECT *,
        SUM(CASE WHEN narrowing THEN 1 ELSE 0 END) OVER(PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 9 PRECEDING AND 1 PRECEDING) AS narrow_days,
        CASE WHEN sr_w < prev_w AND prev_w < LAG(sr_w,2) OVER(PARTITION BY stock_code ORDER BY state_date) 
             AND LAG(sr_w,2) OVER(PARTITION BY stock_code ORDER BY state_date) < LAG(sr_w,3) OVER(PARTITION BY stock_code ORDER BY state_date)
             THEN 1 ELSE 0 END AS streak3
    FROM compress
),
fwd AS (
    SELECT s.*,
        LEAD(s.d1_close,20) OVER(PARTITION BY s.stock_code ORDER BY s.state_date)/s.d1_close-1 AS r20
    FROM streaks s
    WHERE s.d1_state_hex IN('E','F') AND s.prev IN('-E','-F') 
        AND s.mn1_state_hex NOT IN('E','F')
)
SELECT 
    CASE WHEN narrow_days<=1 THEN '0-1天' WHEN narrow_days<=3 THEN '2-3天' 
         WHEN narrow_days<=5 THEN '4-5天' ELSE '6-10天' END g,
    COUNT(*) n, ROUND(AVG(r20)*100,2) a20,
    ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr
FROM fwd WHERE r20 IS NOT NULL
GROUP BY g ORDER BY AVG(narrow_days)
""").fetchall()
res["sr_compression_vs_return"] = [{"g":r[0],"n":r[1],"r20":r[2],"wr":r[3]} for r in r]

# ══════════════════════════════════════════════════════════
# 3. 价格位置 × SR宽度：四象限
# ══════════════════════════════════════════════════════════
r = con.execute("""
WITH base AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex,
        d1_sr_support, d1_sr_resistance,
        (d1_sr_resistance-d1_sr_support)/NULLIF(d1_close,0) AS sr_w,
        (d1_close-d1_sr_support)/NULLIF(d1_sr_resistance-d1_sr_support,0) AS sr_p,
        LAG(d1_state_hex) OVER(PARTITION BY stock_code ORDER BY state_date) AS prev
    FROM d1_perspective_state WHERE d1_close>0 AND d1_sr_support>0 AND d1_sr_resistance>0
        AND d1_sr_support < d1_sr_resistance
),
meds AS (SELECT MEDIAN(sr_w) mw, MEDIAN(sr_p) mp FROM base),
rev AS (
    SELECT b.*, m.mw, m.mp,
        CASE WHEN b.sr_p < m.mp AND b.sr_w < m.mw THEN '低位+窄幅(挤压)'
             WHEN b.sr_p < m.mp THEN '低位+宽幅'
             WHEN b.sr_w < m.mw THEN '高位+窄幅'
             ELSE '高位+宽幅' END AS quadrant,
        LEAD(b.d1_close,20) OVER(PARTITION BY b.stock_code ORDER BY b.state_date)/b.d1_close-1 AS r20
    FROM base b, meds m
    WHERE b.d1_state_hex IN('E','F') AND b.prev IN('-E','-F')
        AND b.mn1_state_hex NOT IN('E','F') AND b.sr_p BETWEEN 0 AND 1
)
SELECT quadrant, COUNT(*) n, ROUND(AVG(r20)*100,2) a20,
    ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr,
    ROUND(AVG(sr_p)*100,1) avg_pos, ROUND(AVG(sr_w)*100,2) avg_w
FROM rev WHERE r20 IS NOT NULL
GROUP BY quadrant ORDER BY n DESC
""").fetchall()
res["sr_quadrant"] = [{"q":r[0],"n":r[1],"r20":r[2],"wr":r[3],"avg_pos":r[4],"avg_width":r[5]} for r in r]

# ══════════════════════════════════════════════════════════
# 4. 跨周期同步收缩: D1+W1+MN1 三个SR区间是否同时压缩
# ══════════════════════════════════════════════════════════
r = con.execute("""
WITH base AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex,
        (d1_sr_resistance-d1_sr_support)/NULLIF(d1_close,0) AS d1w,
        (w1_sr_resistance-w1_sr_support)/NULLIF(d1_close,0) AS w1w,
        (mn1_sr_resistance-mn1_sr_support)/NULLIF(d1_close,0) AS mn1w,
        LAG(d1_state_hex) OVER(PARTITION BY stock_code ORDER BY state_date) AS prev,
        d1_bb_width_q20_20, w1_bb_width_q20_20, mn1_bb_width_q20_20
    FROM d1_perspective_state WHERE d1_close>0 
        AND d1_sr_support>0 AND w1_sr_support>0 AND mn1_sr_support>0
),
meds AS (
    SELECT MEDIAN(d1w) d1m, MEDIAN(w1w) w1m, MEDIAN(mn1w) m1m FROM base
),
scored AS (
    SELECT b.*, m.d1m, m.w1m, m.m1m,
        CASE WHEN b.d1w < m.d1m AND b.w1w < m.w1m AND b.mn1w < m.m1m THEN '三周同步压缩'
             WHEN b.d1w < m.d1m AND b.w1w < m.w1m THEN 'D1+W1压缩'
             WHEN b.d1w < m.d1m THEN '仅D1压缩'
             ELSE '无压缩' END AS sync_level
    FROM base b, meds m
),
fwd AS (
    SELECT sync_level,
        LEAD(d1_close,20) OVER(PARTITION BY stock_code ORDER BY state_date)/d1_close-1 AS r20
    FROM scored
    WHERE d1_state_hex IN('E','F') AND prev IN('-E','-F') AND mn1_state_hex NOT IN('E','F')
)
SELECT sync_level, COUNT(*) n, ROUND(AVG(r20)*100,2) a20,
    ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr
FROM fwd WHERE r20 IS NOT NULL
GROUP BY sync_level ORDER BY n DESC
""").fetchall()
res["cross_period_sync"] = [{"level":r[0],"n":r[1],"r20":r[2],"wr":r[3]} for r in r]

# ══════════════════════════════════════════════════════════
# 5. 多维因子组合: SR位置 + SR压缩 + BB + ATR 四维联合
# ══════════════════════════════════════════════════════════
r = con.execute("""
WITH base AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex,
        (d1_sr_resistance-d1_sr_support)/NULLIF(d1_close,0) AS sr_w,
        (d1_close-d1_sr_support)/NULLIF(d1_sr_resistance-d1_sr_support,0) AS sr_p,
        d1_bb_width_q20_20 AS bb_pct, d1_atr_ratio_pct AS atr_pct,
        LAG(d1_state_hex) OVER(PARTITION BY stock_code ORDER BY state_date) AS prev
    FROM d1_perspective_state WHERE d1_close>0 AND d1_sr_support>0 AND d1_sr_resistance>0
),
meds AS (SELECT MEDIAN(sr_w) mw, MEDIAN(sr_p) mp, MEDIAN(bb_pct) mb, MEDIAN(atr_pct) ma FROM base),
fwd AS (
    SELECT b.*, m.*,
        CASE WHEN b.sr_p < m.mp AND b.sr_w < m.mw AND b.bb_pct < m.mb AND b.atr_pct < m.ma THEN '四维压缩'
             WHEN b.sr_p < m.mp AND b.sr_w < m.mw AND b.bb_pct < m.mb THEN 'SR+BB压缩'
             WHEN b.sr_p < m.mp AND b.sr_w < m.mw THEN 'SR压缩'
             ELSE '无压缩' END AS level,
        LEAD(b.d1_close,20) OVER(PARTITION BY b.stock_code ORDER BY b.state_date)/b.d1_close-1 AS r20
    FROM base b, meds m
    WHERE b.d1_state_hex IN('E','F') AND b.prev IN('-E','-F') AND b.mn1_state_hex NOT IN('E','F')
)
SELECT level, COUNT(*) n, ROUND(AVG(r20)*100,2) a20,
    ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr
FROM fwd WHERE r20 IS NOT NULL
GROUP BY level ORDER BY n DESC
""").fetchall()
res["four_dim"] = [{"level":r[0],"n":r[1],"r20":r[2],"wr":r[3]} for r in r]

con.close()
print(json.dumps(res, indent=2, ensure_ascii=False))
