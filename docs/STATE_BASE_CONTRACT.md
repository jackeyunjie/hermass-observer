# State 底座契约文档

版本：v2.0
日期：2026-05-24
状态：正式契约（不可单方面修改）
关联 Schema：`config/schema_v2.sql`
关联实现：`scripts/build_p116_foundation.py`、`scripts/state_calc/p116_core.py`

> 范围声明：本文档定义的是 A 股生产系统的 State 契约。MT5、美股/US、Alpaca 等内容如有保留，均仅作历史归档参考，不属于当前契约范围。

---

## 第一章：定位与边界

### 1.1 State 底座是什么

State 底座（Layer 2）是 Hermass Observer 系统的**只读地基**。它将原始行情数据转化为标准化的多周期市场状态描述，所有下游模块只能消费 Layer 2 的输出，不写回。

```text
┌─────────────────┐
│   Layer 1 数据层  │  → 黑狼 API / iFinD / AKShare → 行情原始数据
├─────────────────┤
│   Layer 2 State  │  → Foundation DB + State Cache   ← 本文档管辖范围
│   底座（只读）    │     ★ 只读边界，不可逾越
├─────────────────┤
│   Layer 3 策略层  │  → strategy_signal_ledger.py 等（只消费 Layer 2）
├─────────────────┤
│   Layer 4 验证层  │  → forward_observation / calibration
├─────────────────┤
│   Layer 5 展示层  │  → daily_research_brief / strategy_reminder
└─────────────────┘
```

### 1.2 本文档的效力

- 本文档是 State 底座的**宪法级文件**。
- 以下条目标记为「🔒 不可变」，任何修改需团队全票通过并同步更新本文档。
- 以下条目标记为「📐 可扩展但需兼容」，新增字段只能追加，不能删除或重命名已有字段。
- 本文档优于任何代码注释或口头约定。若代码实现与本文档冲突，以本文档为准。

### 1.3 术语总则：使用二维坐标表达 State

自本版本起，项目的抽象层术语统一为：

```text
view_tf      = 视角 Agent 所在周期
structure_tf = 被观察的结构周期
state_hex(view_tf, structure_tf)
```

解释如下：

- 每个周期视角都是一个独立 Agent
- 每个 Agent 内部包含“本周期及以上大周期”的时间戳对齐状态
- 同一 `structure_tf` 在不同 `view_tf` 下可能得到不同 `state_hex`

例如：

```text
state_hex(D1, W1) ≠ state_hex(W1, W1)
state_hex(H1, D1) ≠ state_hex(D1, D1)
```

这是正确行为，不是冲突。

### 1.4 当前契约边界：本文档定义 D1 Agent 主产出

当前 Foundation DB 的权威产出仍是 `D1 Agent`，即：

```text
mn1_state_hex = state_hex(D1, MN1)
w1_state_hex  = state_hex(D1, W1)
d1_state_hex  = state_hex(D1, D1)
```

以上字段名是**历史兼容命名**。它们在抽象层不应再被解释为“某周期原生 State”，而应被解释为 `D1 Agent` 内部的三个结构状态。

---

## 第二章：Foundation DB 完整 Schema

### 2.1 数据库概述

Foundation DB 是 `build_p116_foundation.py --date YYYY-MM-DD` 生成的 DuckDB 文件，每天一份，命名规则：

```text
outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb
```

包含 **12 张表**，分四层：

| 层 | 表名 | 作用 |
|----|------|------|
| 数据层 | `daily_bars` | 日线 K 线 |
| | `weekly_bars` | 周线 K 线（DuckDB `date_trunc('week')` 聚合） |
| | `monthly_bars` | 月线 K 线（DuckDB `date_trunc('month')` 聚合） |
| 统一层 | `timeframe_bars` | D1/W1/MN1 三周期统一视图 |
| 指标层 | `sr_levels` | 支撑/阻力关键位（SqFractal 5→确认 3→前向填充） |
| | `timeframe_indicators` | 三周期技术指标（ADX/DI/BB/ATR 全量） |
| 关联层 | `d1_d_sr` | D1 close ↔ D1 SR（ASOF JOIN） |
| | `d1_w_sr` | D1 close ↔ W1 SR（ASOF JOIN） |
| | `d1_mn1_sr` | D1 close ↔ MN1 SR（ASOF JOIN） |
| | `d1_sr_context` | 三周期 SR 上下文联合表 |
| 产出层 | `d1_perspective_state` | ★ 最终 State 表（下游主数据源） |
| | `foundation_run_log` | 构建运行日志 |

### 2.2 各表字段定义

完整 DDL 见 `config/schema_v2.sql`。以下仅说明各表的主键和关键字段。

#### 2.2.1 `daily_bars`

| 字段 | 类型 | 说明 |
|------|------|------|
| stock_code | VARCHAR | 股票代码（6 位，如 '000001'） |
| date | DATE | 交易日 |
| open / high / low / close | DOUBLE | OHLC |
| volume | DOUBLE | 成交量 |
| amount | DOUBLE | 成交额 |

🔒 `(stock_code, date)` 为唯一约束。

#### 2.2.2 `weekly_bars` / `monthly_bars`

| 字段 | 类型 | 说明 |
|------|------|------|
| stock_code | VARCHAR | 股票代码 |
| period_start | DATE | 周期起始日（`date_trunc` 结果） |
| period_end | DATE | 周期最后交易日 |
| available_date | DATE | 可用日（用于 ASOF JOIN 的锚定日） |
| source_bar_count | BIGINT | 本周期包含的日线 bar 数 |

聚合规则：
- `open` = `arg_min(open, date)` — 周期第一个交易日开盘价
- `high` = `max(high)`
- `low` = `min(low)`
- `close` = `arg_max(close, date)` — 周期最后一个交易日收盘价
- `volume` = `sum(volume)`
- `amount` = `sum(amount)`

🔒 聚合公式不可变。

#### 2.2.3 `timeframe_bars`

`daily_bars` + `weekly_bars` + `monthly_bars` 的 `UNION ALL`，增加 `timeframe` 字段区分周期。

| timeframe 取值 | 含义 |
|---------------|------|
| 'D1' | 日线（`period_start = date`，`source_bar_count = 1`） |
| 'W1' | 周线 |
| 'MN1' | 月线 |

#### 2.2.4 `sr_levels`

🔒 关键位计算算法（不可变）：

```text
Step 1: SqFractal 5
  - 分形高点：high 大于前后各 2 根 bar 的 high → center_fractal_resistance
  - 分形低点：low 小于前后各 2 根 bar 的 low → center_fractal_support

Step 2: 确认延迟 3 根 bar
  - lag(center_fractal_resistance, 3) → fractal_resistance
  - lag(center_fractal_support, 3) → fractal_support

Step 3: 前向填充
  - last_value(fractal_resistance IGNORE NULLS) → sr_resistance
  - last_value(fractal_support IGNORE NULLS) → sr_support
  - sr_ready = (sr_resistance IS NOT NULL AND sr_support IS NOT NULL)
```

| 参数 | 值 | 状态 |
|------|-----|------|
| fractal_period | 5 | 🔒 不可变 |
| confirm_lag_bars | 3 | 🔒 不可变 |

#### 2.2.5 `timeframe_indicators`

包含每个 (stock_code, timeframe, period_start) 的全量技术指标。

🔒 窗口参数（不可变）：

| 参数 | 值 | 用途 |
|------|-----|------|
| BB 滚动窗口 | 20 bar | 布林中轨/标准差 |
| BB 分位窗口 | 前 20 bar（不含当前） | Q20/Q50/Q80 |
| ATR 窗口 | 14 bar | ATR14 |
| ATR 分位窗口 | 前 60 bar（不含当前） | Q75/均值 |
| ADX 斜率 | 当前 adx14 - 3 bar 前 adx14 | ADX 方向 |

🔒 趋势分类规则（不可变）：

| trend 值 | 判定条件 |
|----------|----------|
| `insufficient_history` | ADX or DI 为 NULL |
| `closed` | ADX ≤ 13 AND adx_slope < 0 |
| `bull_trend` | ADX ≥ 25 AND adx_slope > 0 AND +DI > -DI |
| `bear_trend` | ADX ≥ 25 AND adx_slope > 0 AND -DI > +DI |
| `bull_start` | ADX > 20 AND +DI > -DI |
| `bear_start` | ADX > 20 AND -DI > +DI |
| `neutral` | 其他 |

#### 2.2.6 `d1_d_sr` / `d1_w_sr` / `d1_mn1_sr`

ASOF LEFT JOIN 的三张中间表，将 `daily_bars` 的每天与对应周期的 `sr_levels` 按 `available_date` 对齐。

🔒 关联逻辑（不可变）：

```sql
daily_bars ASOF LEFT JOIN sr_levels(timeframe='X')
  ON stock_code = stock_code AND date >= available_date
```

#### 2.2.7 `d1_sr_context`

三张 ASOF 表的 LEFT JOIN 合成。

#### 2.2.8 `d1_perspective_state` ★ 核心表

这是 State 底座的唯一权威产出，所有下游模块读取 State 数据时必须以本表为准。

每行 = 一只股票在一个交易日的三周期 State。

状态编码（🔒 不可变）：

```text
score = base + trend_bit × 4 + position_bit + volatility_bit
```

符号裁决（🔒 不可变）：

```text
伪代码：
  IF d1_close < mn1_sr_support → 负号
  ELSE IF d1_close > mn1_sr_resistance → 正号
  ELSE IF mn1_bear_context AND NOT mn1_bull_context → 负号
  ELSE → 正号
```

| bit | 值 | 含义 |
|-----|-----|------|
| base | 8 | 扩张（有趋势） |
| base | 0 | 收缩（无趋势 / closed） |
| trend_bit | 1 | 牛 / 熊 |
| trend_bit | 0 | 平 |
| position_bit | 2 | 上突（close > resistance）/ 下突（close < support） |
| position_bit | 0 | 区间内 |
| volatility_bit | 1 | 波扩（ATR 扩张） |
| volatility_bit | 0 | 稳 |

E/F 定义（🔒 不可变）：

```text
E = state_score = 14
F = state_score = 15
```

E/F 状态永远是正值。`ef_count` 为 MN1/W1/D1 三周期中 E/F 的计数（0-3）。

#### 2.2.9 `foundation_run_log`

| 字段 | 说明 |
|------|------|
| schema_version | `'p116_foundation_v2_0'`（🔒 本次升级后锁定） |
| generated_at | 构建时间（ISO 8601 UTC） |
| source_raw_db | 上游数据源路径 |
| latest_date | 数据截止日期 |
| research_only_flag | `true`（🔒 永远为 true） |

---

## 第三章：State 计算公式不可变契约

### 3.1 4-bit 编码公式

🔒 该公式不可修改。

```text
state_magnitude = base + (trend_bit × 4) + position_bit + volatility_bit
state_score     = sign × state_magnitude

取值范围：
  正号:  0 ~ 15
  负号: -15 ~ -1
  E: 14 (正)
  F: 15 (正)
```

### 3.2 D1 Agent 天条

🔒 不可修改。

```text
对当前 Foundation DB 所定义的 `D1 Agent` 而言，所有结构周期的 position 计算都使用 D1 收盘价（`d1_close`）比较各自周期的 SR 关键位：

MN1 position = D1 close vs MN1 SR（月线支撑/阻力）
W1  position = D1 close vs W1  SR（周线支撑/阻力）
D1  position = D1 close vs D1  SR（日线支撑/阻力）

但 trend、base、volatility 使用各自周期的数据：
- trend:      各自周期的 ADX/DI
- base:       各自周期的 compression（布林带宽分位）
- volatility: 各自周期的 ATR% 比较
```

📐 该规则可泛化为：

```text
在任意 Agent 中：
  position(view_tf, structure_tf) = close(view_tf) vs SR(structure_tf)
```

但当前 Foundation DB 只把 `view_tf = D1` 的版本正式落库。

### 3.3 位置优先符号裁决

🔒 不可修改。

```text
优先级 1: 当前 Agent 的 perspective_close 与 SR 的关系（最高优先）
  - close < sr_support → 负
  - close > sr_resistance → 正

优先级 2: bull/bear context（仅当 close 在 SR 区间内时生效）
  - bear_context AND NOT bull_context → 负
  - 其余 → 正
```

### 3.4 bit 位语义

🔒 不可修改。

```text
position_bit = 2:
  含义：价格突破了支撑位或阻力位（无论方向）
  条件：d1_close > sr_resistance（上突）或 d1_close < sr_support（下突）
  
position_bit = 0:
  含义：价格在 SR 支撑与阻力之间运行

trend_bit = 1:
  含义：存在方向性趋势（ADX 确认的牛/熊）
  条件：trend LIKE 'bull%' OR trend LIKE 'bear%'
  
trend_bit = 0:
  含义：无明确方向性趋势

base = 8:
  含义：布林带宽处于扩张状态
  条件：compression != 'closed' AND trend != 'closed'
  
base = 0:
  含义：市场压缩（closed/contracting）

volatility_bit = 1:
  含义：ATR 扩张
  条件：volatility = 'atr_expanding'
  
volatility_bit = 0:
  含义：ATR 稳定或收缩
```

### 3.5 十六进制编码

🔒 不可修改。

```text
state_score >= 0 → to_hex(state_score)
state_score < 0  → '-' + to_hex(abs(state_score))

示例：
  14 → 'E'     15 → 'F'     0 → '0'     8 → '8'
  -12 → '-C'    -15 → '-F'   -1 → '-1'
```

---

## 第四章：下游消费者接口规范

### 4.1 核心原则

**所有下游模块只能读取 Foundation DB，不能写入。**

### 4.2 允许读取的表和字段

| 表 | 允许操作 | 主要消费者 |
|----|----------|-----------|
| `d1_perspective_state` | SELECT（全字段） | 所有下游模块 |
| `d1_sr_context` | SELECT（全字段） | strategy_signal_ledger（通过 backtest/engine.py） |
| `weekly_bars` | SELECT（全字段） | 独立周线 State 系统 |
| `monthly_bars` | SELECT（全字段） | 独立月线 State 系统 |
| `foundation_run_log` | SELECT | 验证脚本 |

### 4.3 禁止操作

| 禁止操作 | 说明 |
|----------|------|
| INSERT / UPDATE / DELETE / DROP | 任何对 Foundation DB 的写入 |
| ALTER TABLE | 任何 Schema 变更 |
| 修改 `state_score` / `state_hex` / `ef_count` | 不允许下游重新计算或覆写 State |
| 修改 `d1_close` | 不允许下游修改 D1 收盘价 |
| 修改 SR 值 | 不允许下游改写支撑/阻力位 |

### 4.4 接入方式

📐 可扩展。

当前已有两种接入方式：

**方式 A：直接 DuckDB 读取**

```python
con = duckdb.connect(foundation_db, read_only=True)
rows = con.execute("SELECT ... FROM d1_perspective_state WHERE state_date = ?", [date]).fetchall()
```

**方式 B：通过 State Cache 间接消费**

```python
# state_cache_builder.py 将 Foundation DB 转为 JSON 缓存
# 下游读取 state_cache/state_ef_YYYYMMDD.json
```

### 4.5 Schema 版本检查

📐 可扩展。

建议所有消费者在启动时校验：

```python
def check_schema_version(db: Path) -> bool:
    con = duckdb.connect(str(db), read_only=True)
    version = con.execute(
        "SELECT schema_version FROM foundation_run_log LIMIT 1"
    ).fetchone()[0]
    con.close()
    if version != 'p116_foundation_v2_0':
        raise RuntimeError(
            f"Foundation DB schema version mismatch: "
            f"expected p116_foundation_v2_0, got {version}"
        )
    return True
```

### 4.6 State Cache 输出接口

State Cache 是 Foundation DB 的 JSON 衍生品，供轻量消费者使用。

| 缓存文件 | 来源 | 消费者 |
|----------|------|--------|
| `state_ef_{date}.json` | `d1_perspective_state` 中 `ef_count >= 2` 的行 | brief / reminder |
| `state_distribution_{date}.json` | State Score 全量统计 | market_phase |
| `state_transition_{date}.json` | State 历史转换路径 | calibration |
| `sr_boundary_{date}.json` | SR 边界数据 | signal_ledger |

---

## 第五章：边界条件清单

### 5.1 NULL 值处理

| 场景 | NULL 来源 | 处理规则 | 位置 |
|------|----------|----------|------|
| SR 未就绪 | 历史数据不足 3 个分形确认 | `sr_ready = false`；`sr_support` / `sr_resistance` 为 NULL | `sr_levels` |
| ASOF 未匹配 | `date < available_date`（最早交易日） | LEFT JOIN 产生 NULL；`d1_perspective_state` 中对应 `_sr_ready` 为 NULL/False | `d1_d_sr` 等 |
| 指标数据不足 | 周期 bar 数少于窗口大小（14/20/60） | 指标字段为 NULL；trend/volatility/compression = `'insufficient_history'` | `timeframe_indicators` |
| ADX/DI 计算除零 | `plus_di_14 + minus_di_14 = 0` | `dx14` = NULL；`adx14` = NULL | `timeframe_indicators` |
| BB 宽度除零 | `bb_middle_20 = 0` | `bb_width_pct` = NULL | `timeframe_indicators` |
| ATR% 除零 | `close = 0` | `atr_ratio_pct` = NULL | `timeframe_indicators` |

### 5.2 负值 State 处理

负值 State（如 `-C`、`-F`）是有效状态，表示在 bear context 下的价格行为。

```text
规则：
- 负值 State 的 state_hex 以 '-' 开头
- 负值 State 的 state_score < 0
- E/F 永远是正值：只有当 state_score ∈ {14, 15} 时才算 E/F
- ef_count 只统计正值 E/F，负值不计入
```

### 5.3 数据缺失兜底

| 缺失场景 | 兜底策略 |
|----------|----------|
| 某只股票某日无数据 | 该日不出现在 `d1_perspective_state` 中（由 `daily_bars` 驱动） |
| 黑狼 API 不可用 | 使用前一日 Foundation DB（跳过当天），或切换 yfinance/AKShare 备用源 |
| 节假日/非交易日 | `daily_bars` 无该日数据，整个流水线无产出 |
| 新上市股票数据不足 | SR/指标为 NULL，State 不计算，不出现在 `d1_perspective_state` 中 |

### 5.4 状态转换边界

```text
State = 0（缩/平/中/稳）→ State = E（扩/牛/上突/波扩）
  含义：从完全收缩到完全扩张
  出现条件：同时满足 4 个条件（base=8, trend=1, position=2, vol=1）
  频率：罕见，通常是重大事件驱动
  
State = E → State = F
  含义：从 E（14）到 F（15）仅差 volatility 的翻转
  F = E 的 volatility_bit 从 0 翻到 1

State = E → State < E
  含义：趋势强度减弱或位置回落
  通常先丢失 volatility（E→C），再丢失 position（C→8 或 C→0）
```

---

## 第六章：Agent 视角体系

### 6.1 设计原则

系统采用多 Agent 视角体系。核心原则：

- **每个周期视角是一个独立 Agent**
- **视角决定基准价**（view_tf 的 close）
- **各结构周期的 trend/base/volatility 独立**

详细架构设计参见 `docs/AGENT_PERSPECTIVE_ARCHITECTURE.md`。

### 6.2 视角矩阵

系统采用 `view_tf × structure_tf` 二维坐标：

| view_tf \\ structure_tf | MN1 | W1 | D1 | H4 | H1 |
|------------------------|-----|-----|-----|-----|-----|
| **MN1** | MN1@MN1 | — | — | — | — |
| **W1** | MN1@W1 | W1@W1 | — | — | — |
| **D1** | MN1@D1 | W1@D1 | D1@D1 | — | — |
| **H4** | MN1@H4 | W1@H4 | D1@H4 | H4@H4 | — |
| **H1** | MN1@H1 | W1@H1 | D1@H1 | H4@H1 | H1@H1 |

每个单元格 = 一个 `(view_tf, structure_tf)` 状态对。

### 6.3 各 Agent 定义

#### 6.3.1 D1 Agent（日频，当前主系统）

- **构成**：MN1@D1, W1@D1, D1@D1
- **更新**：每个交易日
- **用途**：策略信号触发、适配度计算、前向观察
- **实现**：`scripts/state_calc/p116_core.py` → `d1_perspective_state` 表
- **基准价**：D1 close

#### 6.3.2 W1 Agent（周频，辅助系统）

- **构成**：MN1@W1, W1@W1
- **更新**：每周末（周五收盘后）
- **用途**：周线趋势判断、周度报告、跨期稳定性验证
- **实现**：`scripts/build_weekly_state_independent.py`
- **基准价**：W1 close

#### 6.3.3 H1 Agent（小时频，盘中监控参考）

- **构成**：MN1@H1, W1@H1, D1@H1, H4@H1, H1@H1
- **更新**：每小时
- **用途**：盘中实时监控参考
- **实现**：待实现（参见 `docs/H1_AGENT_FEASIBILITY_ANALYSIS.md`）
- **基准价**：H1 close
- **A 股限制**：T+1 制度下仅用于监控，不用于交易信号
- **状态**：暂不实现（参见 H1 可行性分析报告）

#### 6.3.4 MN1 Agent（月频，长期参考）

- **构成**：MN1@MN1
- **更新**：每月末
- **用途**：月度宏观判断、长期配置
- **实现**：待实现
- **基准价**：MN1 close

### 6.4 Agent 间差异

#### 6.4.1 差异是设计特性

同一标的同一天，不同 Agent 可能给出不同 State。**这是正确行为，不是 bug**。

```text
示例：
  周三，某股票 D1 close = 50.0，W1 close（上周五）= 48.0，W1 SR 阻力 = 49.0

  D1 Agent W1 State：D1 close(50) > W1 阻力(49) → position = 突破
  W1 Agent W1 State：W1 close(48) < W1 阻力(49) → position = 未突破

  → 两者都是对的，回答的问题不同
```

#### 6.4.2 差异率数据

实测 D1 Agent vs W1 Agent 的差异率（参见 `docs/W1_STATE_DUAL_PERSPECTIVE_CALIBRATION.md`）：

| 日期类型 | position 差异率 | 完全 State 差异率 |
|----------|----------------|-------------------|
| 周一 | 15-25% | 10-15% |
| 周三 | 20-30% | 15-20% |
| 周五 | 5-10% | 3-5% |
| **平均** | **15-20%** | **10-15%** |

### 6.5 使用规则

| 分析场景 | 推荐 Agent | 禁止行为 |
|----------|-----------|----------|
| 日频信号触发 | D1 Agent | 不可用 W1/H1 Agent 的 State 触发日频信号 |
| 周频趋势判断 | W1 Agent | 不可用 D1 Agent 的 W1 State 判断周线趋势 |
| 盘中监控 | H1 Agent | H1 State 不可直接用于 A 股 T+1 交易 |
| 月度宏观 | MN1 Agent | — |
| 回测收益计算 | 与信号同一 Agent | 禁止混用不同 Agent 的 State |

**核心规则**：不可混用不同 Agent 的 State。信号触发和回测收益必须使用同一 Agent。

### 6.6 与现有系统的映射

| Agent | 当前实现 | 状态 |
|-------|---------|------|
| D1 Agent | `scripts/state_calc/p116_core.py` | 已固化，主系统 |
| W1 Agent | `scripts/build_weekly_state_independent.py` | 脚本存在，未接入信号链路 |
| H1 Agent | — | 待实现（P1，参见可行性分析） |
| MN1 Agent | — | 待实现（P2） |

---

## 第七章：版本演进规则

### 7.1 Schema 版本号

| 版本 | 状态 | 说明 |
|------|------|------|
| `p116_foundation_v0_2_mt4like` | 旧版 | v1.0 之前的历史版本 |
| `p116_foundation_v2_0` | **当前** | 本文档定义的版本 |

### 7.2 变更规则

```text
兼容变更（可执行，小版本号升级）：
  - ALTER TABLE ADD COLUMN（新增字段，必须有默认值或允许 NULL）
  - 新增中间表（不影响 d1_perspective_state 的列结构）
  - state_cache JSON 新增字段

不兼容变更（禁止单独执行，需全团队评审 + 大版本号升级）：
  - DROP COLUMN
  - RENAME COLUMN
  - 修改已有字段的类型
  - 修改 State 计算公式（4-bit 编码 / E/F 定义 / 符号裁决）
  - 修改 D1 Agent 天条
  - 修改 SR 算法参数（fractal_period / confirm_lag_bars）
  - 修改指标窗口参数（20/14/60 等）
```

---

## 第八章：附录

### 8.1 State Score 全量枚举

| Score | Hex | base | trend | pos | vol | 典型含义 |
|-------|-----|------|-------|-----|-----|----------|
| 0 | 0 | 缩 | 平 | 中 | 稳 | 完全静止 |
| 1 | 1 | 缩 | 平 | 中 | 波扩 | 波动上升，无方向 |
| 2 | 2 | 缩 | 平 | 突破 | 稳 | 安静突破 |
| 3 | 3 | 缩 | 平 | 突破 | 波扩 | 波动突破 |
| 4 | 4 | 缩 | 趋势 | 中 | 稳 | 趋势刚启动，位置未突破 |
| 5 | 5 | 缩 | 趋势 | 中 | 波扩 | 趋势启动 + 波动上升 |
| 6 | 6 | 缩 | 趋势 | 突破 | 稳 | 趋势 + 位置突破 |
| 7 | 7 | 缩 | 趋势 | 突破 | 波扩 | 趋势 + 突破 + 波动 |
| 8 | 8 | 扩 | 平 | 中 | 稳 | 扩张但无方向 |
| 9 | 9 | 扩 | 平 | 中 | 波扩 | 扩张 + 波动 |
| 10 | A | 扩 | 平 | 突破 | 稳 | 扩张 + 突破 |
| 11 | B | 扩 | 平 | 突破 | 波扩 | 扩张 + 突破 + 波动 |
| 12 | C | 扩 | 趋势 | 中 | 稳 | 趋势 + 扩张，位置未确认 |
| 13 | D | 扩 | 趋势 | 中 | 波扩 | 趋势 + 扩张 + 波动 |
| **14** | **E** | 扩 | 趋势 | 突破 | **稳** | ★ 最优状态 |
| **15** | **F** | 扩 | 趋势 | 突破 | **波扩** | ★ 最强状态 |

### 8.2 相关文件索引

| 文件 | 作用 |
|------|------|
| `config/schema_v2.sql` | Foundation DB DDL 文件 |
| `scripts/build_p116_foundation.py` | Foundation DB 构建器（权威实现） |
| `scripts/state_calc/p116_core.py` | State 4-bit 编码核心模块 |
| `scripts/state_calc/sr_calculator.py` | SR 支撑/阻力计算 |
| `scripts/state_calc/d1_perspective.py` | D1 Agent 对齐与 State 批量计算 |
| `scripts/state_cache_builder.py` | State Cache JSON 构建 |
| `scripts/strategy_signal_ledger.py` | 策略信号账本（主要下游消费者） |
| `scripts/forward_observation_ledger.py` | 前向观察账本（下游消费者） |
| `scripts/daily_research_brief.py` | 每日总报（下游消费者） |
| `scripts/strategy_reminder_brief.py` | 策略提醒（下游消费者） |
| `scripts/build_monthly_state_independent.py` | 独立月线 State 系统 |
| `scripts/build_weekly_state_independent.py` | 独立周线 State 系统 |
| `scripts/validate_weekly_state.py` | D1 Agent / W1 Agent 差异验证 |
| `docs/W1_STATE_DUAL_PERSPECTIVE_CALIBRATION.md` | D1 Agent / W1 Agent 详细分析 |
| `docs/AGENT_PERSPECTIVE_ARCHITECTURE.md` | Agent 视角体系正式定义 |

### 8.3 当前已知数据覆盖

| 指标 | 值 |
|------|-----|
| A 股数量 | 约 5,000 只 |
| 历史交易日 | 2025-06-01 至今（约 230 个交易日） |
| Foundation DB 大小 | 约 3.8 GB（单日） |
| d1_perspective_state 行数 | 约 8500 万行 |
| E/F 全三池规模 | 约 100-250 只（日频波动） |
