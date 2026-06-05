#!/usr/bin/env python3
"""右侧交易入场分析：D1从低位转入右侧状态 → 后续表现

右侧入口定义:
- 2,3: 收缩有趋势（蓄力早期）
- 6,7: 蓄力（收缩有趋势，已突破）
- 10(A),11(B): 人和（刚扩张/刚突破）
- 14(E),15(F): 天时（强趋势+突破+扩张）

前序条件: D1前日在逆位/收缩态(-E/-F/-C/-D/-A/-B)，当日转入上述右侧状态

不统计最低点，不统计价格绝对值——只统计 State 从低位转入右侧后的表现。
"""
import duckdb, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DB = str(ROOT / "outputs" / "p116_foundation_20260602" / "p116_foundation.duckdb")
con = duckdb.connect(DB, read_only=True)
res = {}

# 右侧入口：从逆位/收缩态(-E/-F/-C/-D/-A/-B)转入
ENTRY_HEXES = ["2","3","6","7","A","B","E","F"]
ENTRY_NAMES = {"2":"收缩有趋势","3":"收缩有趋势","6":"蓄力","7":"蓄力","A":"人和(刚突破)","B":"人和(刚突破)","E":"天时","F":"天时"}

for h in ENTRY_HEXES:
    for with_mn1_filter in [False, True]:
        key = f"{h}_{'mn1_not_ef' if with_mn1_filter else 'all'}"
        mn1_clause = "AND mn1_state_hex NOT IN ('E','F')" if with_mn1_filter else ""
        
        r = con.execute(f"""
        WITH e AS (
            SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex,
                LAG(d1_state_hex) OVER(PARTITION BY stock_code ORDER BY state_date) AS prev
            FROM d1_perspective_state WHERE d1_close > 0
        ),
        entries AS (
            SELECT stock_code, state_date, d1_close
            FROM e
            WHERE d1_state_hex='{h}' AND prev IN ('-E','-F','-C','-D','-A','-B')
                {mn1_clause}
        ),
        fwd AS (
            SELECT en.stock_code, en.state_date, en.d1_close,
                LEAD(en.d1_close,5)  OVER(PARTITION BY en.stock_code ORDER BY en.state_date)/en.d1_close-1 AS r5,
                LEAD(en.d1_close,10) OVER(PARTITION BY en.stock_code ORDER BY en.state_date)/en.d1_close-1 AS r10,
                LEAD(en.d1_close,20) OVER(PARTITION BY en.stock_code ORDER BY en.state_date)/en.d1_close-1 AS r20,
                LEAD(en.d1_close,60) OVER(PARTITION BY en.stock_code ORDER BY en.state_date)/en.d1_close-1 AS r60,
                LEAD(en.d1_close,120) OVER(PARTITION BY en.stock_code ORDER BY en.state_date)/en.d1_close-1 AS r120,
                LEAD(en.d1_close,250) OVER(PARTITION BY en.stock_code ORDER BY en.state_date)/en.d1_close-1 AS r250
            FROM entries en
        )
        SELECT 
            COUNT(*) n,
            ROUND(AVG(r5)*100,2) a5, ROUND(AVG(r10)*100,2) a10, ROUND(AVG(r20)*100,2) a20,
            ROUND(AVG(r60)*100,2) a60, ROUND(AVG(r120)*100,2) a120, ROUND(AVG(r250)*100,2) a250,
            ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr20,
            ROUND(SUM(CASE WHEN r60>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr60,
            ROUND(SUM(CASE WHEN r120>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr120,
            ROUND(SUM(CASE WHEN r250>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) wr250
        FROM fwd WHERE r20 IS NOT NULL
        """).fetchone()
        
        res[key] = {"n":r[0],"r5":r[1],"r10":r[2],"r20":r[3],"r60":r[4],"r120":r[5],"r250":r[6],
                     "wr20":r[7],"wr60":r[8],"wr120":r[9],"wr250":r[10]}

# 附加: 按入口分组，看后续翻倍比例
print("=" * 80)
print("右侧入场分析: D1从逆位/收缩态转入正向状态后的表现")
print("说明: 前日D1在 -E/-F/-C/-D/-A/-B（逆位/收缩态），当日转入右侧状态")
print("右侧状态: 2/3=收缩有趋势, 6/7=蓄力, A/B=人和, E/F=天时")
print("=" * 80)

print(f"\n{'入口':>6s} {'MN1≠EF':>8s} {'样本':>7s} {'5日':>7s} {'10日':>7s} {'20日':>7s} {'60日':>7s} {'120日':>7s} {'250日':>8s} {'20胜率':>7s} {'250胜率':>7s}")
print(f"{'─'*6} {'─'*8} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*8} {'─'*7} {'─'*7}")

for h in ENTRY_HEXES:
    for mn1_label, mn1_key in [("不限制","all"), ("MN1≠EF", "mn1_not_ef")]:
        key = f"{h}_{mn1_key}"
        r = res[key]
        if r["n"] > 0:
            def v(x): return x if x else 0
            print(f"  {h}({ENTRY_NAMES[h]:<8s}) {mn1_label:>6s}  {r['n']:>6,}  {v(r['r5']):>+6.2f}% {v(r['r10']):>+6.2f}% {v(r['r20']):>+6.2f}% {v(r['r60']):>+6.2f}% {v(r['r120']):>+6.2f}% {v(r['r250']):>+7.2f}%  {v(r['wr20']):>5.1f}%  {v(r['wr250']):>5.1f}%")

# 翻倍比例: 各入口后续涨幅≥100%的比例
print(f"\n{'='*80}")
print("各入口的翻倍/三倍比例 (250日内)")
print("=" * 80)
print(f"  {'入口':>6s}  {'样本':>7s}  {'≥1倍%':>7s}  {'≥3倍%':>7s}  {'≥5倍%':>7s}")
print(f"  {'─'*6}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*7}")

for h in ENTRY_HEXES:
    r = con.execute(f"""
    WITH e AS (
        SELECT stock_code, state_date, d1_close, d1_state_hex,
            LAG(d1_state_hex) OVER(PARTITION BY stock_code ORDER BY state_date) AS prev
        FROM d1_perspective_state WHERE d1_close > 0
    ),
    entries AS (
        SELECT stock_code, state_date, d1_close
        FROM e WHERE d1_state_hex='{h}' AND prev IN ('-E','-F','-C','-D','-A','-B')
    ),
    fwd AS (
        SELECT LEAD(d1_close,250) OVER(PARTITION BY stock_code ORDER BY state_date)/d1_close-1 AS r250
        FROM entries
    )
    SELECT COUNT(*) n,
        ROUND(SUM(CASE WHEN r250>=1.0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) p1x,
        ROUND(SUM(CASE WHEN r250>=3.0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) p3x,
        ROUND(SUM(CASE WHEN r250>=5.0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) p5x
    FROM fwd WHERE r250 IS NOT NULL
    """).fetchone()
    if r[0] > 0:
        print(f"  {h}({ENTRY_NAMES[h]})  {r[0]:>6,}  {r[1]:>6.1f}%  {r[2]:>6.1f}%  {r[3]:>6.1f}%")

# 对比: 如果是最高点(已经E/F)再入场(追顶)
print(f"\n{'='*80}")
print("对照: 在D1已经是E/F时才入场（没有前序低位要求）")
print("=" * 80)
r = con.execute("""
WITH e AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex,
        LAG(d1_state_hex) OVER(PARTITION BY stock_code ORDER BY state_date) AS prev
    FROM d1_perspective_state WHERE d1_close > 0
),
entries AS (
    SELECT stock_code, state_date, d1_close
    FROM e WHERE d1_state_hex IN('E','F') AND prev IN('E','F')
),
fwd AS (
    SELECT LEAD(d1_close,250) OVER(PARTITION BY stock_code ORDER BY state_date)/d1_close-1 AS r250 FROM entries
)
SELECT COUNT(*) n, ROUND(AVG(r250)*100,2) a250,
    ROUND(SUM(CASE WHEN r250>=1.0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) p1x,
    ROUND(SUM(CASE WHEN r250>=3.0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) p3x
FROM fwd WHERE r250 IS NOT NULL
""").fetchone()
print(f"  连续在E/F中入场: n={r[0]:,}  250日收益={r[1]}%  翻倍率={r[2]}%  三倍率={r[3]}%")
print("  → 这是追顶，不是右侧交易")

con.close()
