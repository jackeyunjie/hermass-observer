#!/usr/bin/env python3
"""ATR出场 + 分阶段出场回测（近3年）"""
import duckdb
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DB = str(ROOT / "outputs" / "p116_foundation_20260602" / "p116_foundation.duckdb")
con = duckdb.connect(DB, read_only=True)

DF = "AND state_date >= '2023-06-03' AND state_date <= '2026-06-03'"

print("ATR吊灯出场 + 多阶段出场 (近3年)")
print(f"范围: 2023-06-03 → 2026-06-03")
print("=" * 70)

# ====== 1) ATR不同倍率 ======
print(f"\n{'不同ATR倍率 被止损比例 (近3年)':^50s}")
print(f"  {'倍率':>5s}  {'被止损%':>8s}  {'均止损日':>8s}")
print(f"  {'-'*5}  {'-'*8}  {'-'*8}")

for mult in [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]:
    r = con.execute(f"""
    WITH e AS (
        SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex, d1_atr_ratio_pct,
            LAG(d1_state_hex) OVER w AS prev
        FROM d1_perspective_state WHERE d1_close>0 {DF}
        WINDOW w AS (PARTITION BY stock_code ORDER BY state_date)
    ),
    en AS (
        SELECT stock_code, state_date AS ed, d1_close AS ep, d1_atr_ratio_pct
        FROM e WHERE d1_state_hex IN('E','F') AND prev IN('-E','-F') AND mn1_state_hex NOT IN('E','F')
    ),
    p AS (
        SELECT en.stock_code, en.ed, en.ep, en.d1_atr_ratio_pct, s.d1_close,
            ROW_NUMBER() OVER(PARTITION BY en.stock_code, en.ed ORDER BY s.state_date) AS dn
        FROM en JOIN d1_perspective_state s ON en.stock_code=s.stock_code
            AND s.state_date>en.ed AND s.state_date<=DATE_ADD(en.ed,INTERVAL'20'DAY)
    ),
    cm AS (
        SELECT *, MAX(d1_close) OVER(PARTITION BY stock_code, ed ORDER BY dn) AS rh FROM p
    ),
    st AS (
        SELECT stock_code, ed, ep, d1_close,
            rh-{mult}*(ep*d1_atr_ratio_pct/100.0) AS sp, dn
        FROM cm
    ),
    tr AS (
        SELECT stock_code, ed,
            MIN(CASE WHEN d1_close<=sp THEN dn END) AS sd,
            MAX(dn) AS md
        FROM st GROUP BY stock_code, ed
    )
    SELECT COUNT(*) n, SUM(CASE WHEN sd IS NOT NULL THEN 1 ELSE 0 END) s, ROUND(AVG(sd),1) a FROM tr
    """).fetchone()
    pct = r[1]/r[0]*100 if r[0]>0 else 0
    print(f"  {mult:4.1f}x  {pct:7.1f}%  {str(r[2]) if r[2] else 'N/A':>8s}")

# ====== 2) 分阶段出场: 5d30% + 10d40% + 20MA30% ======
print(f"\n{'='*70}")
print("多阶段出场: 5日30% + 10日40% + 20MA触发出30%")
print("=" * 70)

r = con.execute(f"""
WITH b AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex,
        AVG(d1_close) OVER (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
        LAG(d1_state_hex) OVER w AS prev
    FROM d1_perspective_state WHERE d1_close>0 {DF}
    WINDOW w AS (PARTITION BY stock_code ORDER BY state_date)
),
en AS (
    SELECT stock_code, state_date AS ed, d1_close AS ep, ma20
    FROM b WHERE d1_state_hex IN('E','F') AND prev IN('-E','-F') AND mn1_state_hex NOT IN('E','F')
),
-- 5日和10日收盘价
days AS (
    SELECT en.stock_code, en.ed, en.ep, en.ma20,
        s5.d1_close AS c5, s10.d1_close AS c10
    FROM en
    LEFT JOIN d1_perspective_state s5 ON en.stock_code=s5.stock_code AND s5.state_date=en.ed+5
    LEFT JOIN d1_perspective_state s10 ON en.stock_code=s10.stock_code AND s10.state_date=en.ed+10
),
-- 20MA第一次触碰
touch AS (
    SELECT d.stock_code, d.ed, d.ep, d.ma20, d.c5, d.c10,
        MIN(s.d1_close) AS touch_px, MIN(s.state_date) AS touch_d
    FROM days d
    LEFT JOIN d1_perspective_state s ON d.stock_code=s.stock_code
        AND s.state_date>d.ed AND s.state_date<=d.ed+20 AND s.d1_close<=d.ma20
    GROUP BY d.stock_code, d.ed, d.ep, d.ma20, d.c5, d.c10
),
-- 未触碰 → 20日收盘
final AS (
    SELECT t.*,
        s20.d1_close AS c20,
        COALESCE(t.touch_px, s20.d1_close) AS exit_px,
        CASE WHEN t.touch_px IS NOT NULL THEN '触碰MA20' ELSE '持满20日' END AS reason
    FROM touch t
    LEFT JOIN d1_perspective_state s20 ON t.stock_code=s20.stock_code AND s20.state_date=t.ed+20
)
SELECT
    COUNT(*) n,
    ROUND(AVG(0.3*(c5/ep-1) + 0.4*(c10/ep-1) + 0.3*(exit_px/ep-1))*100,2) AS combo,
    ROUND(AVG(0.3*(c5/ep-1))*100,2) AS r5,
    ROUND(AVG(0.4*(c10/ep-1))*100,2) AS r10,
    ROUND(AVG(0.3*(exit_px/ep-1))*100,2) AS rma,
    SUM(CASE WHEN reason='触碰MA20' THEN 1 ELSE 0 END) AS touch_n,
    ROUND(SUM(CASE WHEN reason='触碰MA20' THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) AS touch_pct
FROM final WHERE exit_px IS NOT NULL
""").fetchone()

print(f"\n方案B 分阶段 (n={r[0]:,}):")
print(f"  组合收益: {r[1]}%")
print(f"  5日部分 (30%): {r[2]}%")
print(f"  10日部分 (40%): {r[3]}%")
print(f"  20MA部分 (30%): {r[4]}%")
print(f"  触碰20MA比例: {r[5]:,} ({r[6]}%)")

# ====== 3) 对各方案对比 ======
# A: 纯持有20日
ra = con.execute(f"""
WITH b AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex,
        LAG(d1_state_hex) OVER w AS prev
    FROM d1_perspective_state WHERE d1_close>0 {DF}
    WINDOW w AS (PARTITION BY stock_code ORDER BY state_date)
),
en AS (
    SELECT stock_code, state_date AS ed, d1_close AS ep
    FROM b WHERE d1_state_hex IN('E','F') AND prev IN('-E','-F') AND mn1_state_hex NOT IN('E','F')
)
SELECT COUNT(*) n, ROUND(AVG((s.d1_close/en.ep-1))*100,2) a,
    ROUND(SUM(CASE WHEN s.d1_close>en.ep THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) w
FROM en JOIN d1_perspective_state s ON en.stock_code=s.stock_code AND s.state_date=en.ed+20
""").fetchone()

# C: 5日全出场
rc = con.execute(f"""
WITH b AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex,
        LAG(d1_state_hex) OVER w AS prev
    FROM d1_perspective_state WHERE d1_close>0 {DF}
    WINDOW w AS (PARTITION BY stock_code ORDER BY state_date)
),
en AS (
    SELECT stock_code, state_date AS ed, d1_close AS ep
    FROM b WHERE d1_state_hex IN('E','F') AND prev IN('-E','-F') AND mn1_state_hex NOT IN('E','F')
)
SELECT COUNT(*) n, ROUND(AVG((s.d1_close/en.ep-1))*100,2) a,
    ROUND(SUM(CASE WHEN s.d1_close>en.ep THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) w
FROM en JOIN d1_perspective_state s ON en.stock_code=s.stock_code AND s.state_date=en.ed+5
""").fetchone()

# D: 10日全出场
rd = con.execute(f"""
WITH b AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex,
        LAG(d1_state_hex) OVER w AS prev
    FROM d1_perspective_state WHERE d1_close>0 {DF}
    WINDOW w AS (PARTITION BY stock_code ORDER BY state_date)
),
en AS (
    SELECT stock_code, state_date AS ed, d1_close AS ep
    FROM b WHERE d1_state_hex IN('E','F') AND prev IN('-E','-F') AND mn1_state_hex NOT IN('E','F')
)
SELECT COUNT(*) n, ROUND(AVG((s.d1_close/en.ep-1))*100,2) a,
    ROUND(SUM(CASE WHEN s.d1_close>en.ep THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) w
FROM en JOIN d1_perspective_state s ON en.stock_code=s.stock_code AND s.state_date=en.ed+10
""").fetchone()

print(f"\n{'='*70}")
print("出场方案对比 (近3年)")
print("=" * 70)
print(f"  {'方案':<20s}  {'样本':>6s}  {'收益':>7s}  {'胜率':>6s}")
print(f"  {'-'*20}  {'-'*6}  {'-'*7}  {'-'*6}")
print(f"  {'A 纯持有20日':<20s}  {ra[0]:>6,}  {ra[1]:>+6.2f}%  {ra[2]:>5.1f}%")
print(f"  {'B 分阶段(5/10/MA20)':<20s}  {r[0]:>6,}  {r[1]:>+6.2f}%  {'—':>6}")
print(f"  {'C 纯5日出':<20s}  {rc[0]:>6,}  {rc[1]:>+6.2f}%  {rc[2]:>5.1f}%")
print(f"  {'D 纯10日出':<20s}  {rd[0]:>6,}  {rd[1]:>+6.2f}%  {rd[2]:>5.1f}%")

# ====== 4) ATR+分阶段组合 ======
# 2.5x被止损的比例vs没被止损的差额
r2 = con.execute(f"""
WITH e AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex, d1_atr_ratio_pct,
        LAG(d1_state_hex) OVER w AS prev
    FROM d1_perspective_state WHERE d1_close>0 {DF}
    WINDOW w AS (PARTITION BY stock_code ORDER BY state_date)
)
SELECT
    ROUND(AVG(CASE WHEN d1_atr_ratio_pct < 3.0 THEN 1.0 ELSE 0.0 END)*100,1) AS low_atr_pct,
    ROUND(AVG(CASE WHEN d1_atr_ratio_pct >= 4.5 THEN 1.0 ELSE 0.0 END)*100,1) AS high_atr_pct
FROM e WHERE d1_state_hex IN('E','F') AND prev IN('-E','-F') AND mn1_state_hex NOT IN('E','F')
""").fetchone()

print(f"\n{'='*70}")
print("结论")
print("=" * 70)
print(f"  入场时ATR<3.0占 {r2[0]}%, ATR≥4.5占 {r2[1]}%")

con.close()
