#!/usr/bin/env python3
"""EF 前驱组合分析：D1 进入 E/F 前是什么 State 组合，后续表现如何。"""
import duckdb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = str(ROOT / "outputs" / "p116_foundation_20260602" / "p116_foundation.duckdb")
OUT = ROOT / "data" / "research" / "个人量化" / "ef_precursor_analysis.md"

con = duckdb.connect(DB, read_only=True)
L = []

L.append("# EF 前驱组合分析报告")
L.append("")
L.append(f"数据库: {DB}")
L.append("")
L.append("---")
L.append("")
L.append("## Q1: D1 进入 E/F 前的三周期 State 组合分布 (Top 20)")
L.append("")
L.append("| 前驱 (MN1/W1/D1) | 次数 | 占比 |")
L.append("|---|---:|--:|")

r = con.execute("""
WITH e AS (
    SELECT stock_code, d1_state_hex,
        LAG(mn1_state_hex) OVER w AS pm,
        LAG(w1_state_hex)  OVER w AS pw,
        LAG(d1_state_hex)  OVER w AS pd
    FROM d1_perspective_state
    WHERE d1_state_hex IS NOT NULL AND mn1_state_hex IS NOT NULL AND w1_state_hex IS NOT NULL
    WINDOW w AS (PARTITION BY stock_code ORDER BY state_date)
)
SELECT pm||'/'||pw||'/'||pd AS t, COUNT(*) AS n, ROUND(COUNT(*)*100.0/SUM(COUNT(*))OVER(),1) AS p
FROM e WHERE d1_state_hex IN ('E','F') AND pd NOT IN ('E','F')
GROUP BY t ORDER BY n DESC LIMIT 20
""").fetchall()
for row in r:
    L.append(f"| {row[0]} | {row[1]:,} | {row[2]}% |")

# Q2
L.append("")
L.append("---")
L.append("")
L.append("## Q2: 前驱组合 → 后续 20 日超额收益（样本≥100，按20日降序）")
L.append("")
L.append("| 前驱 (MN1/W1/D1) | 样本 | 20日超额 | 胜率 |")
L.append("|---|---:|---:|---:|")

r = con.execute("""
WITH e AS (
    SELECT stock_code, state_date, d1_state_hex, d1_close,
        LAG(mn1_state_hex) OVER w AS pm,
        LAG(w1_state_hex)  OVER w AS pw,
        LAG(d1_state_hex)  OVER w AS pd
    FROM d1_perspective_state
    WINDOW w AS (PARTITION BY stock_code ORDER BY state_date)
),
entries AS (
    SELECT stock_code, state_date, pm||'/'||pw||'/'||pd AS pre, d1_close
    FROM e WHERE d1_state_hex IN ('E','F') AND pd NOT IN ('E','F')
),
prec AS (
    SELECT pre, COUNT(*) AS n FROM entries GROUP BY pre HAVING COUNT(*)>=100
),
fwd AS (
    SELECT e.pre,
        LEAD(e.d1_close,20) OVER (PARTITION BY e.stock_code ORDER BY e.state_date)/e.d1_close-1 AS r20
    FROM entries e JOIN prec p ON e.pre=p.pre
)
SELECT pre, COUNT(*) AS n, ROUND(AVG(r20)*100,2),
    ROUND(SUM(CASE WHEN r20>0 THEN 1. ELSE 0 END)/COUNT(*)*100,1)
FROM fwd WHERE r20 IS NOT NULL
GROUP BY pre ORDER BY AVG(r20) DESC
""").fetchall()

for row in r:
    L.append(f"| {row[0]} | {row[1]:,} | {row[2]:+.2f}% | {row[3]}% |")

L.append("")
L.append("### Bottom 10")
L.append("")
L.append("| 前驱 | 样本 | 20日超额 | 胜率 |")
L.append("|---|---:|---:|---:|")
for row in sorted(r, key=lambda x: x[2])[:10]:
    L.append(f"| {row[0]} | {row[1]:,} | {row[2]:+.2f}% | {row[3]}% |")

# Q3: MN1=E/F vs not
L.append("")
L.append("---")
L.append("")
L.append("## Q3: MN1=E/F vs MN1≠E/F，D1首次进入E/F的表现")
L.append("")
L.append("| 条件 | 样本 | 20日超额 | 胜率 |")
L.append("|---|---:|---:|---:|")

r = con.execute("""
WITH e AS (
    SELECT stock_code, state_date, d1_state_hex, mn1_state_hex, d1_close,
        LAG(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS pd
    FROM d1_perspective_state
),
entries AS (
    SELECT mn1_state_hex IN ('E','F') AS m_ef, d1_close, stock_code, state_date
    FROM e WHERE d1_state_hex IN ('E','F') AND pd NOT IN ('E','F')
),
fwd AS (
    SELECT m_ef,
        LEAD(d1_close,20) OVER (PARTITION BY stock_code ORDER BY state_date)/d1_close-1 AS r20
    FROM entries
)
SELECT CASE WHEN m_ef THEN 'MN1=E/F' ELSE 'MN1≠E/F' END AS g, COUNT(*) AS n,
    ROUND(AVG(r20)*100,2), ROUND(SUM(CASE WHEN r20>0 THEN 1. ELSE 0 END)/COUNT(*)*100,1)
FROM fwd WHERE r20 IS NOT NULL
GROUP BY m_ef
""").fetchall()

for row in r:
    L.append(f"| {row[0]} | {row[1]:,} | {row[2]:+.2f}% | {row[3]}% |")

# Q3b: MN1=E/F + W1 expansion detail
L.append("")
L.append("### MN1=E/F 时，W1 状态的影响")
L.append("")
L.append("| W1 | 样本 | 20日超额 | 胜率 |")
L.append("|---|---:|---:|---:|")

r = con.execute("""
WITH e AS (
    SELECT stock_code, state_date, d1_state_hex, mn1_state_hex, w1_state_hex, d1_close,
        LAG(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS pd
    FROM d1_perspective_state
),
entries AS (
    SELECT CASE WHEN w1_state_hex IN ('8','9','A','B','C','D','E','F') THEN 'W1扩张' ELSE 'W1收缩' END AS wg,
        d1_close, stock_code, state_date
    FROM e WHERE mn1_state_hex IN ('E','F') AND d1_state_hex IN ('E','F') AND pd NOT IN ('E','F')
),
fwd AS (
    SELECT wg,
        LEAD(d1_close,20) OVER (PARTITION BY stock_code ORDER BY state_date)/d1_close-1 AS r20
    FROM entries
)
SELECT wg, COUNT(*), ROUND(AVG(r20)*100,2),
    ROUND(SUM(CASE WHEN r20>0 THEN 1. ELSE 0 END)/COUNT(*)*100,1)
FROM fwd WHERE r20 IS NOT NULL
GROUP BY wg
""").fetchall()

for row in r:
    L.append(f"| {row[0]} | {row[1]:,} | {row[2]:+.2f}% | {row[3]}% |")

# Q4: D1 own hex precursor
L.append("")
L.append("---")
L.append("")
L.append("## Q4: D1 进入 E/F 前自身的 Hex（样本≥200）")
L.append("")
L.append("| 前序 D1 | 样本 | 20日超额 | 胜率 |")
L.append("|---|---:|---:|---:|")

r = con.execute("""
WITH e AS (
    SELECT stock_code, state_date, d1_state_hex, d1_close,
        LAG(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS pd
    FROM d1_perspective_state
),
entries AS (
    SELECT pd, d1_close, stock_code, state_date
    FROM e WHERE d1_state_hex IN ('E','F') AND pd NOT IN ('E','F')
),
prec AS (SELECT pd, COUNT(*) AS n FROM entries GROUP BY pd HAVING COUNT(*)>=200),
fwd AS (
    SELECT e.pd,
        LEAD(e.d1_close,20) OVER (PARTITION BY e.stock_code ORDER BY e.state_date)/e.d1_close-1 AS r20
    FROM entries e JOIN prec p ON e.pd=p.pd
)
SELECT pd, COUNT(*), ROUND(AVG(r20)*100,2),
    ROUND(SUM(CASE WHEN r20>0 THEN 1. ELSE 0 END)/COUNT(*)*100,1)
FROM fwd WHERE r20 IS NOT NULL
GROUP BY pd ORDER BY AVG(r20) DESC
""").fetchall()

for row in r:
    L.append(f"| {row[0]} | {row[1]:,} | {row[2]:+.2f}% | {row[3]}% |")

# Q5: Three-period all entering EF
L.append("")
L.append("---")
L.append("")
L.append("## Q5: 三周期同时进入 E/F 的前置 MN1/W1 分布（样本≥30）")
L.append("")
L.append("| 前日 (MN1/W1) | 样本 | 20日超额 | 胜率 |")
L.append("|---|---:|---:|---:|")

r = con.execute("""
WITH e AS (
    SELECT stock_code, state_date, d1_state_hex, mn1_state_hex, w1_state_hex, d1_close,
        LAG(d1_state_hex)  OVER w AS pd,
        LAG(mn1_state_hex) OVER w AS pm,
        LAG(w1_state_hex)  OVER w AS pw
    FROM d1_perspective_state
    WINDOW w AS (PARTITION BY stock_code ORDER BY state_date)
),
entries AS (
    SELECT pm||'/'||pw AS pp, d1_close, stock_code, state_date
    FROM e WHERE d1_state_hex IN ('E','F') AND mn1_state_hex IN ('E','F') AND w1_state_hex IN ('E','F')
        AND pd NOT IN ('E','F') AND pm IS NOT NULL AND pw IS NOT NULL
),
prec AS (SELECT pp, COUNT(*) AS n FROM entries GROUP BY pp HAVING COUNT(*)>=30),
fwd AS (
    SELECT e.pp,
        LEAD(e.d1_close,20) OVER (PARTITION BY e.stock_code ORDER BY e.state_date)/e.d1_close-1 AS r20
    FROM entries e JOIN prec p ON e.pp=p.pp
)
SELECT pp, COUNT(*), ROUND(AVG(r20)*100,2),
    ROUND(SUM(CASE WHEN r20>0 THEN 1. ELSE 0 END)/COUNT(*)*100,1)
FROM fwd WHERE r20 IS NOT NULL
GROUP BY pp ORDER BY AVG(r20) DESC
""").fetchall()

for row in r:
    L.append(f"| {row[0]} | {row[1]:,} | {row[2]:+.2f}% | {row[3]}% |")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(L), encoding="utf-8")
con.close()
print(f"Done → {OUT}")
