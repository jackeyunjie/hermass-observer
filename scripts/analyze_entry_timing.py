#!/usr/bin/env python3
"""精确出场条件分析：价格>200均线 + D1收缩 + MN1/W1前置状态 → D1反转向上后的表现。

叠加收缩观测指标（BB带宽/ATR比率/ADX）作为入场时机细粒度过滤器。
"""

import duckdb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = str(ROOT / "outputs" / "p116_foundation_20260602" / "p116_foundation.duckdb")
OUT = ROOT / "data" / "research" / "个人量化" / "entry_timing_analysis.md"

con = duckdb.connect(DB, read_only=True)
L = []

L.append("# 精确入场时机分析")
L.append("")
L.append("条件: 价格>200日均线 + D1在收缩态(-E/-F/-C/-D) + MN1≠E/F + D1反转向E/F")
L.append("叠加: 收缩观测指标(BB带宽/ATR比率/ADX)作为细粒度过滤器")
L.append(f"数据: {DB}")
L.append("")

# ══════════════════════════════════════════════════════════
# Step 1: Context - position relative to 200 MA, then filter
# ══════════════════════════════════════════════════════════

# Compute sma200 using window function, then find D1 contraction + entry points
L.append("## 一、全市场条件：价格>200均线 + D1在逆位/收缩态 → D1反转向E/F")
L.append("")

L.append("### 1.1 整体表现（不分组）")
L.append("")

r = con.execute("""
WITH base AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex, w1_state_hex, ef_count,
        d1_atr_ratio_pct, d1_bb_width_q20_20, d1_adx14,
        AVG(d1_close) OVER (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma200
    FROM d1_perspective_state WHERE d1_close > 0
),
entries AS (
    SELECT *, d1_close > sma200 AS above_ma,
        LAG(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_d1
    FROM base
    WHERE sma200 > 0
),
reversals AS (
    SELECT stock_code, state_date, d1_close,
        d1_state_hex, mn1_state_hex, w1_state_hex, ef_count,
        d1_atr_ratio_pct, d1_bb_width_q20_20, d1_adx14,
        prev_d1
    FROM entries
    WHERE d1_state_hex IN ('E','F')
      AND prev_d1 IN ('-E','-F','-C','-D')  -- 前一日D1在收缩态
      AND mn1_state_hex NOT IN ('E','F')     -- MN1不在E/F
      AND above_ma                            -- 价格在200均线之上
),
fwd AS (
    SELECT r.*,
        LEAD(r.d1_close, 5)  OVER (PARTITION BY r.stock_code ORDER BY r.state_date) / r.d1_close - 1 AS r5,
        LEAD(r.d1_close, 10) OVER (PARTITION BY r.stock_code ORDER BY r.state_date) / r.d1_close - 1 AS r10,
        LEAD(r.d1_close, 20) OVER (PARTITION BY r.stock_code ORDER BY r.state_date) / r.d1_close - 1 AS r20
    FROM reversals r
)
SELECT COUNT(*) AS n,
    ROUND(AVG(r5)*100,2) AS avg5, ROUND(AVG(r10)*100,2) AS avg10, ROUND(AVG(r20)*100,2) AS avg20,
    ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) AS wr20
FROM fwd WHERE r20 IS NOT NULL
""").fetchone()

L.append(f"- 样本: **{r[0]:,} 次**")
L.append(f"- 5日超额: **{r[1]}%** | 10日超额: **{r[2]}%** | 20日超额: **{r[3]}%**")
L.append(f"- 20日胜率: **{r[4]}%**")
L.append("")

# ══════════════════════════════════════════════════════════
# Step 2: By MN1/W1 state combo
# ══════════════════════════════════════════════════════════
L.append("### 1.2 按 MN1/W1 前置组合分组（样本≥50）")
L.append("")
L.append("| MN1/W1 | 样本 | 20日超额 | 20日胜率 | 平均ATR% | 平均BB宽 |")
L.append("|---|---:|---:|---:|---:|---:|")

r = con.execute("""
WITH base AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex, w1_state_hex,
        d1_atr_ratio_pct, d1_bb_width_q20_20,
        AVG(d1_close) OVER (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma200
    FROM d1_perspective_state WHERE d1_close > 0
),
entries AS (
    SELECT *, d1_close > sma200 AS above_ma,
        LAG(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_d1
    FROM base WHERE sma200 > 0
),
reversals AS (
    SELECT mn1_state_hex||'/'||w1_state_hex AS mn_w1,
        d1_close, d1_atr_ratio_pct, d1_bb_width_q20_20,
        stock_code, state_date
    FROM entries
    WHERE d1_state_hex IN ('E','F') AND prev_d1 IN ('-E','-F','-C','-D')
      AND mn1_state_hex NOT IN ('E','F') AND above_ma
),
fwd AS (
    SELECT r.*,
        LEAD(r.d1_close, 20) OVER (PARTITION BY r.stock_code ORDER BY r.state_date) / r.d1_close - 1 AS r20
    FROM reversals r
),
groups AS (
    SELECT mn_w1, COUNT(*) AS n, ROUND(AVG(r20)*100,2) AS a20,
        ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) AS wr,
        ROUND(AVG(d1_atr_ratio_pct),1) AS atr, ROUND(AVG(d1_bb_width_q20_20),2) AS bb
    FROM fwd WHERE r20 IS NOT NULL
    GROUP BY mn_w1 HAVING COUNT(*) >= 50
)
SELECT * FROM groups ORDER BY a20 DESC
""").fetchall()

for row in r:
    L.append(f"| {row[0]} | {row[1]:,} | {row[2]:+.2f}% | {row[3]}% | {row[5]} | {row[6]} |")

L.append("")
L.append("**解读**: 不同 MN1/W1 组合下，D1从收缩反转进入E/F的20日表现差异显著。ATR和BB宽度反映了当时的波动环境。")
L.append("")

# ══════════════════════════════════════════════════════════
# Step 3: Contraction observer indicators as entry filters
# ══════════════════════════════════════════════════════════
L.append("---")
L.append("## 二、收缩观测指标作为入场过滤器")
L.append("")
L.append("叠加条件: 价格>200均线 + D1=-E/-F/-C/-D + MN1≠E/F + D1反转向E/F")
L.append("")

for metric_name, column, label in [
    ("ATR比率(ATR/60日均)", "d1_atr_ratio_pct", "ATR%"),
    ("BB带宽(20日百分位)", "d1_bb_width_q20_20", "BB宽"),
    ("ADX(14)", "d1_adx14", "ADX"),
]:
    L.append(f"### 2.x {label}")
    L.append("")
    L.append(f"| {label} 区间 | 样本 | 20日超额 | 胜率 |")
    L.append("|---|---:|---:|---:|")

    r = con.execute(f"""
    WITH base AS (
        SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex, {column},
            AVG(d1_close) OVER (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma200
        FROM d1_perspective_state WHERE d1_close > 0
    ),
    entries AS (
        SELECT *, d1_close > sma200 AS above_ma,
            LAG(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_d1
        FROM base WHERE sma200 > 0
    ),
    reversals AS (
        SELECT d1_close, stock_code, state_date, {column} AS val
        FROM entries
        WHERE d1_state_hex IN ('E','F') AND prev_d1 IN ('-E','-F','-C','-D')
          AND mn1_state_hex NOT IN ('E','F') AND above_ma
    ),
    fwd AS (
        SELECT r.val,
            LEAD(r.d1_close,20) OVER (PARTITION BY r.stock_code ORDER BY r.state_date)/r.d1_close-1 AS r20
        FROM reversals r
    ),
    bucketed AS (
        SELECT 
            CASE 
                WHEN val IS NULL THEN 'NULL'
                WHEN val < NTILE_VAL THEN '<Q1'
                WHEN val BETWEEN Q1 AND Q3 THEN 'Q1-Q3'
                ELSE '>Q3'
            END AS bucket,
            r20
        FROM (
            SELECT val, r20,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY val) OVER() AS Q1,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY val) OVER() AS Q3
            FROM fwd WHERE r20 IS NOT NULL AND val IS NOT NULL
        ) t
    )
    SELECT bucket, COUNT(*) AS n, ROUND(AVG(r20)*100,2),
        ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1)
    FROM bucketed GROUP BY bucket ORDER BY bucket
    """).fetchall()

    for row in r:
        L.append(f"| {row[0]} | {row[1]:,} | {row[2]:+.2f}% | {row[3]}% |")
    L.append("")

# ══════════════════════════════════════════════════════════
# Step 4: Combined - best scenario
# ══════════════════════════════════════════════════════════
L.append("---")
L.append("## 三、最优组合：多重过滤叠加")
L.append("")
L.append("价格>200均线 + D1=-E/-F + MN1≠E/F + ATR收缩(<中位数) + BB带宽低位(<中位数)")
L.append("")

r = con.execute("""
WITH base AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex, w1_state_hex,
        d1_atr_ratio_pct, d1_bb_width_q20_20,
        AVG(d1_close) OVER (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma200
    FROM d1_perspective_state WHERE d1_close > 0
),
entries AS (
    SELECT *, d1_close > sma200 AS above_ma,
        LAG(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_d1
    FROM base WHERE sma200 > 0
),
reversals AS (
    SELECT d1_close, d1_atr_ratio_pct, d1_bb_width_q20_20,
        stock_code, state_date
    FROM entries
    WHERE d1_state_hex IN ('E','F') AND prev_d1 IN ('-E','-F')
      AND mn1_state_hex NOT IN ('E','F') AND above_ma
),
stats AS (
    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY d1_atr_ratio_pct) OVER() AS atr_med,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY d1_bb_width_q20_20) OVER() AS bb_med
    FROM reversals LIMIT 1
),
filtered AS (
    SELECT r.* FROM reversals r, stats s
    WHERE r.d1_atr_ratio_pct < s.atr_med AND r.d1_bb_width_q20_20 < s.bb_med
),
fwd AS (
    SELECT r.*,
        LEAD(r.d1_close,20) OVER (PARTITION BY r.stock_code ORDER BY r.state_date)/r.d1_close-1 AS r20
    FROM filtered r
)
SELECT COUNT(*) AS n,
    ROUND(AVG(r20)*100,2) AS a20,
    ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) AS wr
FROM fwd WHERE r20 IS NOT NULL
""").fetchone()

L.append(f"- 样本: **{r[0]:,}**")
L.append(f"- 20日超额: **{r[1]}%**")
L.append(f"- 20日胜率: **{r[2]}%**")
L.append("")

# ══════════════════════════════════════════════════════════
# Step 5: D1 reversal indicator - what ADX/ATR/BB values mark the best entry
# ══════════════════════════════════════════════════════════
L.append("---")
L.append("## 四、D1反转日的指标特征：什么样的反转信号最好")
L.append("")
L.append("条件: 价格>200均线 + D1=-E/-F + MN1≠E/F → D1进入E/F")
L.append("按反转日的 ADX/ATR/BB 值三分位分组，看20日超额收益。")
L.append("")

metric_list = [
    ("ATR比率(收缩=小值更好)", "d1_atr_ratio_pct"),
    ("BB带宽百分位(收缩=小值更好)", "d1_bb_width_q20_20"),
    ("ADX(趋势强度)", "d1_adx14"),
]
for label, col in metric_list:
    r = con.execute(f"""
    WITH base AS (
        SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex, {col},
            AVG(d1_close) OVER (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma200
        FROM d1_perspective_state WHERE d1_close > 0
    ),
    entries AS (
        SELECT *, d1_close > sma200 AS above_ma,
            LAG(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_d1
        FROM base WHERE sma200 > 0
    ),
    reversals AS (
        SELECT d1_close, stock_code, state_date, {col} AS v
        FROM entries
        WHERE d1_state_hex IN ('E','F') AND prev_d1 IN ('-E','-F')
          AND mn1_state_hex NOT IN ('E','F') AND above_ma AND {col} IS NOT NULL
    ),
    with_q AS (
        SELECT v, d1_close, stock_code, state_date,
            NTILE(3) OVER (ORDER BY v) AS tercile
        FROM reversals
    ),
    fwd AS (
        SELECT v, tercile,
            LEAD(d1_close,20) OVER (PARTITION BY stock_code ORDER BY state_date)/d1_close-1 AS r20
        FROM with_q
    )
    SELECT 
        CASE tercile 
            WHEN 1 THEN '下三分位(最小)'
            WHEN 2 THEN '中三分位'
            WHEN 3 THEN '上三分位(最大)'
        END AS grp,
        COUNT(*) AS n, ROUND(AVG(r20)*100,2), ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1),
        ROUND(MIN(v),1)||'~'||ROUND(MAX(v),1) AS range_val
    FROM fwd WHERE r20 IS NOT NULL
    GROUP BY tercile ORDER BY tercile
    """).fetchall()
    
    L.append(f"### {label}")
    L.append("| 区间 | 样本 | 20日超额 | 胜率 | 数值范围 |")
    L.append("|---|---:|---:|---:|---:|")
    for row in r:
        L.append(f"| {row[0]} | {row[1]:,} | {row[2]:+.2f}% | {row[3]}% | {row[4]} |")
    L.append("")

# ══════════════════════════════════════════════════════════
# Step 6: D1 consecutive contraction days before reversal
# ══════════════════════════════════════════════════════════
L.append("---")
L.append("## 五、D1连续收缩天数对反转质量的影响")
L.append("")
L.append("条件: 价格>200均线 + MN1≠E/F + D1从连续N天收缩(-E/-F/-C/-D)后反转向E/F")
L.append("")

r = con.execute("""
WITH base AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex,
        AVG(d1_close) OVER (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma200,
        CASE WHEN d1_state_hex IN ('-E','-F','-C','-D') THEN 1 ELSE 0 END AS is_contr
    FROM d1_perspective_state WHERE d1_close > 0
),
with_streak AS (
    SELECT *, d1_close > sma200 AS above_ma,
        LAG(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_d1,
        SUM(is_contr) OVER (PARTITION BY stock_code ORDER BY state_date 
            ROWS BETWEEN 19 PRECEDING AND 1 PRECEDING) AS contr_days_20
    FROM base WHERE sma200 > 0
),
reversals AS (
    SELECT d1_close, stock_code, state_date,
        CASE WHEN contr_days_20 <= 2 THEN '≤2天'
             WHEN contr_days_20 <= 5 THEN '3-5天'
             WHEN contr_days_20 <= 10 THEN '6-10天'
             ELSE '>10天' END AS streak_grp
    FROM with_streak
    WHERE d1_state_hex IN ('E','F') AND prev_d1 IN ('-E','-F')
      AND mn1_state_hex NOT IN ('E','F') AND above_ma
),
fwd AS (
    SELECT streak_grp,
        LEAD(d1_close,20) OVER (PARTITION BY stock_code ORDER BY state_date)/d1_close-1 AS r20
    FROM reversals
)
SELECT streak_grp, COUNT(*) AS n, ROUND(AVG(r20)*100,2),
    ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1)
FROM fwd WHERE r20 IS NOT NULL
GROUP BY streak_grp ORDER BY n DESC
""").fetchall()

L.append("| 收缩天数 | 样本 | 20日超额 | 胜率 |")
L.append("|---|---:|---:|---:|")
for row in r:
    L.append(f"| {row[0]} | {row[1]:,} | {row[2]:+.2f}% | {row[3]}% |")

# ══════════════════════════════════════════════════════════
# Step 7: Summary rules
# ══════════════════════════════════════════════════════════
L.append("")
L.append("---")
L.append("## 六、精确入场规则总结")
L.append("")
# Get the best combo numbers
summary = con.execute("""
WITH base AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex,
        d1_atr_ratio_pct, d1_bb_width_q20_20, d1_adx14,
        AVG(d1_close) OVER (PARTITION BY stock_code ORDER BY state_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma200
    FROM d1_perspective_state WHERE d1_close > 0
),
entries AS (
    SELECT *, d1_close > sma200 AS above_ma,
        LAG(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_d1
    FROM base WHERE sma200 > 0
),
reversals AS (
    SELECT d1_close, d1_atr_ratio_pct, d1_bb_width_q20_20, d1_adx14,
        stock_code, state_date
    FROM entries
    WHERE d1_state_hex IN ('E','F') AND prev_d1 IN ('-E','-F')
      AND mn1_state_hex NOT IN ('E','F') AND above_ma
),
stats AS (
    SELECT 
        PERCENTILE_CONT(0.33) WITHIN GROUP (ORDER BY d1_atr_ratio_pct) OVER() AS atr_low,
        PERCENTILE_CONT(0.33) WITHIN GROUP (ORDER BY d1_bb_width_q20_20) OVER() AS bb_low,
        PERCENTILE_CONT(0.33) WITHIN GROUP (ORDER BY d1_adx14) OVER() AS adx_low
    FROM reversals LIMIT 1
),
fwd AS (
    SELECT r.*, s.atr_low, s.bb_low, s.adx_low,
        LEAD(r.d1_close,20) OVER (PARTITION BY r.stock_code ORDER BY r.state_date)/r.d1_close-1 AS r20
    FROM reversals r, stats s
),
best AS (
    SELECT * FROM fwd WHERE d1_atr_ratio_pct < atr_low AND d1_bb_width_q20_20 < bb_low
)
SELECT COUNT(*), ROUND(AVG(r20)*100,2), ROUND(SUM(CASE WHEN r20>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1),
    ROUND(AVG(atr_low),1), ROUND(AVG(bb_low),2), ROUND(AVG(adx_low),1)
FROM best WHERE r20 IS NOT NULL
""").fetchone()

L.append(f"**核心组合**（所有条件叠加）: 价格>200均线 + D1=-E/-F + MN1≠E/F + ATR<{summary[3]}% + BB宽<{summary[4]}")
L.append("")
L.append(f"- 样本: **{summary[0]:,}** | 20日超额: **{summary[1]}%** | 胜率: **{summary[2]}%**")
L.append("")
L.append("### 入场规则")
L.append("")
L.append("1. **价格必须 > 200日均线** — 不在均线以下接飞刀")
L.append("2. **D1 前两天在 -E/-F** — 日线极度收缩/恐慌")
L.append("3. **MN1 ≠ E/F** — 大方向还没被引爆，上方有空间")
L.append("4. **D1 当天进入 E/F** — 反转信号确认")
L.append(f"5. **ATR比率 < {summary[3]}%** — 波动率收缩到位（不是大波动中追）")
L.append(f"6. **BB带宽百分位 < {summary[4]}** — 布林带挤压到位（不是已经跑出去再追）")
L.append("")
L.append("### 收缩观测指标的使用方法")
L.append("")
L.append("- **ATR比率**: D1 真实波幅 / 60日平均波幅。低于中位数 = 波动率正在收缩，突破更有力。太高 = 已在趋势中，追高风险大。")
L.append("- **BB带宽百分位**: 20日布林带(bollinger-band)宽度在历史中的位置。低位 = 布林带挤压，突破即将发生。高位 = 已扩张。")  
L.append("- **ADX**: 趋势强度。ADX在低位(<中位)时反转后的趋势更持久；ADX过高说明趋势已经过度延伸。")

con.close()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(L), encoding="utf-8")
print(f"Done → {OUT}")
