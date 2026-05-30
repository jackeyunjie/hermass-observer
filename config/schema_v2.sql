-- ============================================================================
-- Hermass Observer Foundation DB Schema v2.0
-- 契约版本：2.0
-- 创建日期：2026-05-24
-- 关联文档：docs/STATE_BASE_CONTRACT.md
-- ============================================================================
-- 
-- 此文件是 State 底座的权威 Schema 定义。
-- Foundation DB 由 scripts/build_p116_foundation.py 生成。
-- 所有下游模块只能读取 Foundation DB，不能写入。
-- 
-- 版本演进规则：
--   - v2.0 → v2.x：仅允许 ADD COLUMN，禁止 DROP COLUMN、RENAME、类型变更
--   - v2.x → v3.0：需同步更新 STATE_BASE_CONTRACT.md 并通知所有下游消费者
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. daily_bars —— 日线 K 线数据
-- ============================================================================
-- 来源：黑狼 API → rawdb.blackwolf_ashare_daily_raw → 过滤 research_only_flag = true
-- 唯一约束：(stock_code, date)
-- ============================================================================
CREATE TABLE IF NOT EXISTS daily_bars (
    stock_code  VARCHAR    NOT NULL,
    date        DATE       NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      DOUBLE,
    amount      DOUBLE,
    PRIMARY KEY (stock_code, date)
);

-- ============================================================================
-- 2. weekly_bars —— 周线 K 线数据
-- ============================================================================
-- 来源：daily_bars 按 date_trunc('week', date) 聚合
-- 聚合规则：open = 周首日开盘价, high = 周最高, low = 周最低, close = 周末日收盘价
-- 唯一约束：(stock_code, period_start)
-- ============================================================================
CREATE TABLE IF NOT EXISTS weekly_bars (
    stock_code       VARCHAR    NOT NULL,
    period_start     DATE       NOT NULL,
    period_end       DATE,
    available_date   DATE,
    open             DOUBLE,
    high             DOUBLE,
    low              DOUBLE,
    close            DOUBLE,
    volume           DOUBLE,
    amount           DOUBLE,
    source_bar_count BIGINT,
    PRIMARY KEY (stock_code, period_start)
);

-- ============================================================================
-- 3. monthly_bars —— 月线 K 线数据
-- ============================================================================
-- 来源：daily_bars 按 date_trunc('month', date) 聚合
-- 聚合规则：同 weekly_bars
-- 唯一约束：(stock_code, period_start)
-- ============================================================================
CREATE TABLE IF NOT EXISTS monthly_bars (
    stock_code       VARCHAR    NOT NULL,
    period_start     DATE       NOT NULL,
    period_end       DATE,
    available_date   DATE,
    open             DOUBLE,
    high             DOUBLE,
    low              DOUBLE,
    close            DOUBLE,
    volume           DOUBLE,
    amount           DOUBLE,
    source_bar_count BIGINT,
    PRIMARY KEY (stock_code, period_start)
);

-- ============================================================================
-- 4. timeframe_bars —— 三周期统一 K 线视图
-- ============================================================================
-- 来源：daily_bars + weekly_bars + monthly_bars UNION ALL
-- timeframe 取值：'D1' | 'W1' | 'MN1'
-- 唯一约束：(stock_code, timeframe, period_start)
-- ============================================================================
CREATE TABLE IF NOT EXISTS timeframe_bars (
    stock_code       VARCHAR    NOT NULL,
    timeframe        VARCHAR    NOT NULL,   -- 'D1' / 'W1' / 'MN1'
    period_start     DATE       NOT NULL,
    period_end       DATE,
    available_date   DATE,
    open             DOUBLE,
    high             DOUBLE,
    low              DOUBLE,
    close            DOUBLE,
    volume           DOUBLE,
    amount           DOUBLE,
    source_bar_count BIGINT,
    PRIMARY KEY (stock_code, timeframe, period_start)
);

-- ============================================================================
-- 5. sr_levels —— 支撑/阻力关键位
-- ============================================================================
-- 算法：SqFractal 5（前后各 2 根 bar 确认分形高点/低点）
--       确认延迟 3 根 bar（向后看 3 根确认分形有效）
--       前向填充（last_value IGNORE NULLS）直至下一个分形出现
-- fractal_period = 5（固定），confirm_lag_bars = 3（固定）
-- 唯一约束：(stock_code, timeframe, period_start)
-- ============================================================================
CREATE TABLE IF NOT EXISTS sr_levels (
    stock_code       VARCHAR    NOT NULL,
    timeframe        VARCHAR    NOT NULL,
    period_start     DATE       NOT NULL,
    period_end       DATE,
    available_date   DATE,
    open             DOUBLE,
    high             DOUBLE,
    low              DOUBLE,
    close            DOUBLE,
    volume           DOUBLE,
    amount           DOUBLE,
    source_bar_count BIGINT,
    tf_bar_index     BIGINT,
    fractal_resistance DOUBLE,            -- 确认后的分形阻力（NULL until confirmed）
    fractal_support    DOUBLE,            -- 确认后的分形支撑（NULL until confirmed）
    sr_resistance      DOUBLE,            -- 前向填充后的有效阻力位
    sr_support         DOUBLE,            -- 前向填充后的有效支撑位
    sr_ready           BOOLEAN,            -- 支撑和阻力均已就绪
    fractal_period     INTEGER   NOT NULL DEFAULT 5,
    confirm_lag_bars   INTEGER   NOT NULL DEFAULT 3,
    PRIMARY KEY (stock_code, timeframe, period_start)
);

-- ============================================================================
-- 6. timeframe_indicators —— 三周期技术指标
-- ============================================================================
-- 包含每根 bar 的 trend、volatility、compression 分类及其底层指标值
-- 窗口参数（固定，不可变）：
--   - BB 中轨/标准差：20 bar 滚动窗口
--   - ATR：14 bar 滚动窗口
--   - BB 分位: Q20/Q50/Q80，基于前 20 bar（不含当前）
--   - ATR 分位: Q75/均值，基于前 60 bar（不含当前）
--   - ADX slope: 当前 - 3 bar 前
-- ============================================================================
CREATE TABLE IF NOT EXISTS timeframe_indicators (
    stock_code       VARCHAR    NOT NULL,
    timeframe        VARCHAR    NOT NULL,
    period_start     DATE       NOT NULL,
    period_end       DATE,
    available_date   DATE,
    open             DOUBLE,
    high             DOUBLE,
    low              DOUBLE,
    close            DOUBLE,
    volume           DOUBLE,
    amount           DOUBLE,
    source_bar_count BIGINT,
    prev_close       DOUBLE,
    prev_high        DOUBLE,
    prev_low         DOUBLE,
    bb_middle_20     DOUBLE,
    bb_std_20        DOUBLE,
    true_range       DOUBLE,
    plus_dm          DOUBLE,
    minus_dm         DOUBLE,
    bb_width_pct     DOUBLE,            -- (4 × bb_std) / bb_middle
    atr14            DOUBLE,
    plus_dm14        DOUBLE,
    minus_dm14       DOUBLE,
    plus_di_14       DOUBLE,
    minus_di_14      DOUBLE,
    atr_ratio_pct    DOUBLE,            -- (ATR14 / close) × 100
    dx14             DOUBLE,
    adx14            DOUBLE,
    bb_width_q20_20  DOUBLE,            -- BB宽度 20% 分位（前20bar不含当前）
    bb_width_median_20 DOUBLE,          -- BB宽度 50% 分位
    bb_width_q80_20  DOUBLE,            -- BB宽度 80% 分位
    atr_ratio_q75_60 DOUBLE,            -- ATR比率 75% 分位（前60bar不含当前）
    atr_ratio_avg60  DOUBLE,            -- ATR比率 均值（前60bar不含当前）
    prev_bb_width_pct DOUBLE,
    prev_atr_ratio_pct DOUBLE,
    prev_adx14       DOUBLE,
    adx_slope_3      DOUBLE,            -- ADX 3bar 斜率
    trend            VARCHAR,            -- 'closed'/'bull_trend'/'bear_trend'/'bull_start'/'bear_start'/'neutral'/'insufficient_history'
    volatility       VARCHAR,            -- 'atr_expanding'/'atr_contracting'/'neutral'/'insufficient_history'
    compression      VARCHAR,            -- 'closed'/'contracting'/'strong_expansion'/'expansion_start'/'neutral'/'insufficient_history'
    adx_trend_on     BOOLEAN,            -- ADX >= 25 AND ADX斜率 > 0
    adx_squeeze_on   BOOLEAN,            -- ADX <= 13 AND ADX斜率 < 0
    bb_width_squeeze_on BOOLEAN,         -- BB宽度 <= Q20
    bb_width_expanding  BOOLEAN,         -- BB宽度 > 前值 × 1.05
    PRIMARY KEY (stock_code, timeframe, period_start)
);

-- ============================================================================
-- 7. d1_d_sr —— D1 日线与 D1 SR 的 ASOF 关联
-- ============================================================================
-- 对每个 (stock_code, date)，ASOF LEFT JOIN 到 sr_levels(timeframe='D1')
-- 确保 D1 close 与 D1 SR 在同一行可比较
-- ============================================================================
CREATE TABLE IF NOT EXISTS d1_d_sr (
    stock_code        VARCHAR    NOT NULL,
    state_date        DATE       NOT NULL,    -- = daily_bars.date
    d1_close          DOUBLE,
    d1_period_start   DATE,
    d1_sr_support     DOUBLE,
    d1_sr_resistance  DOUBLE,
    d1_sr_ready       BOOLEAN,
    PRIMARY KEY (stock_code, state_date)
);

-- ============================================================================
-- 8. d1_w_sr —— D1 日线与 W1 SR 的 ASOF 关联
-- ============================================================================
CREATE TABLE IF NOT EXISTS d1_w_sr (
    stock_code        VARCHAR    NOT NULL,
    state_date        DATE       NOT NULL,
    w1_period_start   DATE,
    w1_sr_support     DOUBLE,
    w1_sr_resistance  DOUBLE,
    w1_sr_ready       BOOLEAN,
    PRIMARY KEY (stock_code, state_date)
);

-- ============================================================================
-- 9. d1_mn1_sr —— D1 日线与 MN1 SR 的 ASOF 关联
-- ============================================================================
CREATE TABLE IF NOT EXISTS d1_mn1_sr (
    stock_code        VARCHAR    NOT NULL,
    state_date        DATE       NOT NULL,
    mn1_period_start  DATE,
    mn1_sr_support    DOUBLE,
    mn1_sr_resistance DOUBLE,
    mn1_sr_ready      BOOLEAN,
    PRIMARY KEY (stock_code, state_date)
);

-- ============================================================================
-- 10. d1_sr_context —— D1 视角三周期 SR 上下文
-- ============================================================================
-- 由 d1_d_sr + d1_w_sr + d1_mn1_sr LEFT JOIN 合成
-- 每个 (stock_code, state_date) 包含 D1 close 及三周期的 SR
-- ============================================================================
CREATE TABLE IF NOT EXISTS d1_sr_context (
    stock_code         VARCHAR    NOT NULL,
    state_date         DATE       NOT NULL,
    d1_close           DOUBLE,
    d1_period_start    DATE,
    d1_sr_support      DOUBLE,
    d1_sr_resistance   DOUBLE,
    d1_sr_ready        BOOLEAN,
    w1_period_start    DATE,
    w1_sr_support      DOUBLE,
    w1_sr_resistance   DOUBLE,
    w1_sr_ready        BOOLEAN,
    mn1_period_start   DATE,
    mn1_sr_support     DOUBLE,
    mn1_sr_resistance  DOUBLE,
    mn1_sr_ready       BOOLEAN,
    PRIMARY KEY (stock_code, state_date)
);

-- ============================================================================
-- 11. d1_perspective_state —— 最终 State 表（核心）
-- ============================================================================
-- 这是 State 底座的最终产出，所有下游模块的主数据源。
-- 每行 = 一个交易日的三周期 State。
--
-- D1 视角天条：
--   MN1 position = D1 close vs MN1 SR（月线关键位）
--   W1  position = D1 close vs W1  SR（周线关键位）
--   D1  position = D1 close vs D1  SR（日线关键位）
--
-- State 编码公式（不可变）：
--   score = base + trend_bit × 4 + position_bit + volatility_bit
--   base:        8 = 扩张（有趋势）, 0 = 收缩（无趋势/closed）
--   trend_bit:   1 = 牛/熊, 0 = 平
--   position_bit: 2 = 上突/下突（突破 SR）, 0 = 中（区间内）
--   volatility_bit: 1 = 波扩, 0 = 稳
--
-- 符号裁决（position-priority）：
--   若 D1 close < SR support     → 负号
--   若 D1 close > SR resistance  → 正号
--   否则按 bear_context/bull_context 裁决
--   E/F 始终为正（14/15）
--
-- ef_count = mn1 为 E/F 的计数 + w1 为 E/F 的计数 + d1 为 E/F 的计数
-- ============================================================================
CREATE TABLE IF NOT EXISTS d1_perspective_state (
    stock_code         VARCHAR    NOT NULL,
    state_date         DATE       NOT NULL,
    d1_close           DOUBLE,

    -- MN1 State
    mn1_period_start   DATE,
    mn1_sr_support     DOUBLE,
    mn1_sr_resistance  DOUBLE,
    mn1_sr_ready       BOOLEAN,
    mn1_trend          VARCHAR,
    mn1_volatility     VARCHAR,
    mn1_compression    VARCHAR,
    mn1_adx14          DOUBLE,
    mn1_plus_di_14     DOUBLE,
    mn1_minus_di_14    DOUBLE,
    mn1_adx_slope_3    DOUBLE,
    mn1_bb_width_pct   DOUBLE,
    mn1_bb_width_q20_20 DOUBLE,
    mn1_bb_width_q80_20 DOUBLE,
    mn1_atr_ratio_pct  DOUBLE,
    mn1_atr_ratio_avg60 DOUBLE,
    mn1_base           INTEGER,         -- 8 or 0
    mn1_trend_bit      INTEGER,         -- 1 or 0
    mn1_position_bit   INTEGER,         -- 2 or 0
    mn1_volatility_bit INTEGER,         -- 1 or 0
    mn1_bull_context   BOOLEAN,
    mn1_bear_context   BOOLEAN,
    mn1_state_magnitude INTEGER,
    mn1_state_score    INTEGER,         -- 带符号 State Score（-15 到 +15）
    mn1_state_hex      VARCHAR,         -- 十六进制表示（如 'E', 'F', '-C'）

    -- W1 State
    w1_period_start    DATE,
    w1_sr_support      DOUBLE,
    w1_sr_resistance   DOUBLE,
    w1_sr_ready        BOOLEAN,
    w1_trend           VARCHAR,
    w1_volatility      VARCHAR,
    w1_compression     VARCHAR,
    w1_adx14           DOUBLE,
    w1_plus_di_14      DOUBLE,
    w1_minus_di_14     DOUBLE,
    w1_adx_slope_3     DOUBLE,
    w1_bb_width_pct    DOUBLE,
    w1_bb_width_q20_20 DOUBLE,
    w1_bb_width_q80_20 DOUBLE,
    w1_atr_ratio_pct   DOUBLE,
    w1_atr_ratio_avg60 DOUBLE,
    w1_base            INTEGER,
    w1_trend_bit       INTEGER,
    w1_position_bit    INTEGER,
    w1_volatility_bit  INTEGER,
    w1_bull_context    BOOLEAN,
    w1_bear_context    BOOLEAN,
    w1_state_magnitude INTEGER,
    w1_state_score     INTEGER,
    w1_state_hex       VARCHAR,

    -- D1 State
    d1_period_start    DATE,
    d1_sr_support      DOUBLE,
    d1_sr_resistance   DOUBLE,
    d1_sr_ready        BOOLEAN,
    d1_trend           VARCHAR,
    d1_volatility      VARCHAR,
    d1_compression     VARCHAR,
    d1_adx14           DOUBLE,
    d1_plus_di_14      DOUBLE,
    d1_minus_di_14     DOUBLE,
    d1_adx_slope_3     DOUBLE,
    d1_bb_width_pct    DOUBLE,
    d1_bb_width_q20_20 DOUBLE,
    d1_bb_width_q80_20 DOUBLE,
    d1_atr_ratio_pct   DOUBLE,
    d1_atr_ratio_avg60 DOUBLE,
    d1_base            INTEGER,
    d1_trend_bit       INTEGER,
    d1_position_bit    INTEGER,
    d1_volatility_bit  INTEGER,
    d1_bull_context    BOOLEAN,
    d1_bear_context    BOOLEAN,
    d1_state_magnitude INTEGER,
    d1_state_score     INTEGER,
    d1_state_hex       VARCHAR,

    ef_count           INTEGER,          -- E/F 周期计数（0-3）
    PRIMARY KEY (stock_code, state_date)
);

-- ============================================================================
-- 12. foundation_run_log —— 构建运行日志
-- ============================================================================
CREATE TABLE IF NOT EXISTS foundation_run_log (
    schema_version    VARCHAR   NOT NULL DEFAULT 'p116_foundation_v2_0',
    generated_at      VARCHAR   NOT NULL,
    source_raw_db     VARCHAR   NOT NULL,
    output_duckdb     VARCHAR   NOT NULL,
    daily_rows        BIGINT,
    weekly_rows       BIGINT,
    monthly_rows      BIGINT,
    sr_rows           BIGINT,
    state_rows        BIGINT,
    latest_date       DATE,
    research_only_flag BOOLEAN  NOT NULL DEFAULT true
);

COMMIT;
