# Agent 视角体系架构

版本：v1.0
日期：2026-05-27
状态：正式定义
关联契约：`docs/STATE_BASE_CONTRACT.md`
关联校准：`docs/W1_STATE_DUAL_PERSPECTIVE_CALIBRATION.md`

> 范围声明：本系统专注 A 股市场。MT5 相关文档（`HERMASS_STATE_MT5_PORTING_GUIDE.md` 等）已归档，仅作历史参考，不作为 A 股系统的设计依据。

---

## 第一章：设计原则

### 1.1 为什么需要多 Agent 视角体系

传统多周期分析中，日线、周线、月线各自独立计算支撑阻力位和指标状态。当对跨周期状态进行联合分析时，存在两个核心问题：

1. **口径不一致**：周五日线收盘价与该周周线收盘价可能不同，导致"同一天"不同周期的 position 计算基于不同价格点。
2. **视角单一**：系统只有一个观察基准（D1 close），无法回答"周线自身处于什么状态"或"小时线在日线结构中的位置"等问题。

Agent 视角体系的核心设计目标是：**用多个独立观察器（Agent）覆盖不同时间粒度的分析需求，每个 Agent 内部保持跨周期口径一致，Agent 之间允许差异存在。**

### 1.2 与单一 D1 Agent 主口径的区别

| 维度 | 单一 D1 Agent 主口径（旧体系） | 多 Agent 视角体系（新体系） |
|------|----------------------|--------------------------|
| 观察基准 | 只有 D1 close | D1/W1/H1/MN1 各 Agent 独立 |
| 跨周期一致性 | 所有周期用同一价格点 | 同一 Agent 内用同一价格点 |
| 分析场景覆盖 | 仅日频信号触发 | 日频/周频/小时频/月频全覆盖 |
| 状态差异处理 | 视为口径错误 | 视为设计特性 |
| 系统复杂度 | 简单 | 增加 Agent 管理层 |

### 1.3 核心约束：视角决定基准价

**🔒 不可变原则**：每个 Agent 的所有 position 计算，统一使用该 Agent 周期的收盘价作为基准。

```text
D1 Agent: 所有 position 用 D1 close
W1 Agent: 所有 position 用 W1 close
H1 Agent: 所有 position 用 H1 close
MN1 Agent: 所有 position 用 MN1 close
```

但各结构周期的 trend/base/volatility 始终来自各自周期的指标数据——**只有 position 的基准价随视角变化**。

---

## 第二章：Agent 定义

### 2.1 视角矩阵（view_tf × structure_tf）

系统采用二维坐标命名体系：

| 坐标 | 含义 | 示例 |
|------|------|------|
| `view_tf` | 视角 Agent（观察者所在的时间框架） | H1 |
| `structure_tf` | 被观察结构周期 | D1 |
| `state_hex` | 结构周期在 Agent 下的状态编码 | `state_hex(H1, D1)` |

**关键不等式**：`state_hex(H1, D1) ≠ state_hex(D1, D1)`

### 2.2 各 Agent 的构成

每个 Agent 包含"本周期及以上大周期"的时间戳对齐状态：

```text
MN1 Agent:
  MN1@MN1_view

W1 Agent:
  MN1@W1_view, W1@W1_view

D1 Agent:
  MN1@D1_view, W1@D1_view, D1@D1_view

H4 Agent:
  MN1@H4_view, W1@H4_view, D1@H4_view, H4@H4_view

H1 Agent:
  MN1@H1_view, W1@H1_view, D1@H1_view, H4@H1_view, H1@H1_view
```

未来扩展 M30 / M15：

```text
M30 Agent:
  MN1/W1/D1/H4/H1/M30 @ M30_view

M15 Agent:
  MN1/W1/D1/H4/H1/M30/M15 @ M15_view
```

### 2.3 各 Agent 的更新频率和触发条件

| Agent | 更新频率 | 触发条件 | 数据量（相对 D1） |
|-------|---------|---------|-----------------|
| MN1 Agent | 每月末 | 新月线闭合 | 1/20 |
| W1 Agent | 每周末 | 周五收盘后 | 1/5 |
| D1 Agent | 每个交易日 | 日线收盘后 | 1×（基准） |
| H4 Agent | 每 4 小时 | H4 bar 闭合 | 6× |
| H1 Agent | 每小时 | H1 bar 闭合 | 24× |

### 2.4 Agent 间的层级关系

```text
最粗粒度 ←————————————————→ 最细粒度

MN1 Agent    W1 Agent    D1 Agent    H4 Agent    H1 Agent
  月频         周频        日频        4小时        1小时
    ↑           ↑           ↑           ↑           ↑
  宏观背景    中期节奏    信号触发    盘中结构    实时监控
```

**层级规则**：
- 大周期 Agent 的状态变化慢，但稳定性高
- 小周期 Agent 的状态变化快，但噪音多
- 分析时从大周期 Agent 获取背景，从小周期 Agent 获取触发时机

---

## 第三章：计算规则

### 3.1 position 计算：所有结构周期共用 view_tf 的 close

```text
D1 Agent 示例：
  MN1 position = D1 close vs MN1 SR
  W1  position = D1 close vs W1  SR
  D1  position = D1 close vs D1  SR

H1 Agent 示例：
  MN1 position = H1 close vs MN1 SR
  W1  position = H1 close vs W1  SR
  D1  position = H1 close vs D1  SR
  H4  position = H1 close vs H4  SR
  H1  position = H1 close vs H1  SR
```

### 3.2 trend/base/volatility 计算：各结构周期独立

```text
MN1 的 base/trend/volatility 来自 MN1 周期指标
W1   的 base/trend/volatility 来自 W1  周期指标
D1   的 base/trend/volatility 来自 D1  周期指标
H4   的 base/trend/volatility 来自 H4  周期指标
H1   的 base/trend/volatility 来自 H1  周期指标
```

### 3.3 State 编码公式

🔒 公式不可变，与 `STATE_BASE_CONTRACT.md` 一致：

```text
score = base + trend_bit × 4 + position_bit + volatility_bit
state_score = sign × score
```

### 3.4 ef_count 在各 Agent 中的定义

| Agent | ef_count 统计范围 | 含义 |
|-------|------------------|------|
| D1 Agent | MN1@D1 + W1@D1 + D1@D1 | 三周期 E/F 计数 |
| W1 Agent | MN1@W1 + W1@W1 | 双周期 E/F 计数 |
| H1 Agent | MN1@H1 + W1@H1 + D1@H1 + H4@H1 + H1@H1 | 五周期 E/F 计数 |
| MN1 Agent | MN1@MN1 | 单周期 E/F 计数 |

**注意**：不同 Agent 的 ef_count 不可直接比较。D1 Agent 的 ef_count=3 与 H1 Agent 的 ef_count=3 含义不同。

### 3.5 符号裁决规则（位置优先）

🔒 规则不可变，与 `STATE_BASE_CONTRACT.md` 一致：

```text
优先级 1: view_tf_close 与 SR 的关系
  - close < sr_support → 负号
  - close > sr_resistance → 正号

优先级 2: bull/bear context（仅当 close 在 SR 区间内）
  - bear_context AND NOT bull_context → 负号
  - 其余 → 正号
```

---

## 第四章：Agent 间的数据流

### 4.1 D1 Agent 的结论如何传递给 H1 Agent

```text
D1 Agent 每日收盘后产出：
  d1_perspective_state → state_cache/state_ef_YYYYMMDD.json

H1 Agent 每小时运行时：
  1. 读取当日 D1 Agent 的 state_cache 作为"日线背景"
  2. 计算 H1 视角下的五周期状态
  3. 对比 H1 状态与 D1 状态的差异
  4. 输出盘中监控信号
```

### 4.2 W1 Agent 的结论如何作为 D1 Agent 的"大周期背景"

```text
W1 Agent 每周末产出：
  w1_perspective_state → 周线趋势判断

D1 Agent 每日运行时：
  1. 读取最新 W1 Agent 的 MN1@W1 和 W1@W1 状态
  2. 作为"大周期背景"标签附加到 D1 信号
  3. 例如：W1 Agent 显示 MN1@W1 = E → D1 信号标注"月线背景健康"
```

### 4.3 Agent 间的信号冲突处理

**场景**：H1 Agent 看多（H1 State = E），但 D1 Agent 看空（D1 State = -C）

```text
处理原则：
  1. 不合并不同 Agent 的 State（禁止混用）
  2. 明确标注每个信号的视角来源
  3. 冲突时按分析目的选择 Agent：
     - 日频交易决策 → 以 D1 Agent 为准
     - 盘中监控/预警 → 以 H1 Agent 为准
     - 周线趋势判断 → 以 W1 Agent 为准
```

**冲突标记示例**：

```text
[盘中预警] 688010 福光股份
  H1 Agent: D1@H1 = E（小时线视角下日线结构突破）
  D1 Agent: D1@D1 = -C（日线视角下日线结构偏弱）
  冲突说明：盘中价格短暂突破，但日线收盘未确认
  建议：等待 D1 Agent 收盘确认
```

---

## 第五章：与现有系统的映射

### 5.1 当前 D1 Agent（已实现）

```text
表：d1_perspective_state
  mn1_state_hex = state_hex(D1, MN1)
  w1_state_hex  = state_hex(D1, W1)
  d1_state_hex  = state_hex(D1, D1)
  d1_close = 所有 position 的基准价

脚本：scripts/state_calc/p116_core.py
  → D1 Agent 的核心实现
```

### 5.2 当前 W1 Agent（脚本已有，未接入信号链路）

```text
脚本：scripts/build_weekly_state_independent.py
  → W1 Agent 的独立实现
  → 计算 state_hex(W1, MN1) 和 state_hex(W1, W1)
  → 使用 W1 close 作为 position 基准

状态：脚本存在，但未接入每日流水线
       未与 D1 Agent 的状态缓存联动
```

### 5.3 H1 Agent = 待实现

```text
需求：
  - H1 数据采集（5 分钟线聚合为小时线）
  - H1 SR 关键位计算
  - H1 视角五周期状态计算
  - H1 Agent 状态缓存

优先级：P1（参见 docs/H1_AGENT_FEASIBILITY_ANALYSIS.md）
适用场景：A 股盘中监控参考（T+1 制度下不用于交易信号）
```

### 5.4 MN1 Agent = 待实现（月度频率，优先级低）

```text
需求：
  - MN1 独立状态计算
  - 使用 MN1 close 作为 position 基准

优先级：P2
适用场景：月度宏观判断、长期配置决策
```

---

## 第六章：A 股系统的 Agent 选择

### 6.1 A 股系统：D1 Agent 为主，W1 Agent 为辅

```text
A 股制度约束：
  - T+1：买入当日不可卖出
  - 涨跌停：涨停无法买入，跌停无法卖出
  - 交易时间：09:30-11:30, 13:00-15:00

Agent 优先级：
  1. D1 Agent（日频信号触发、适配度计算）
  2. W1 Agent（周线趋势判断、周度报告）
  3. H1 Agent（仅用于盘中监控参考，不用于交易信号）

原因：T+1 制度下，H1 级别的高频信号无法当日执行，
      只能作为 D1 信号的"提前预警"。
```

### 6.2 T+1 制度对 Agent 选择的影响

| 制度 | D1 Agent 地位 | H1 Agent 地位 | 原因 |
|------|--------------|--------------|------|
| T+1（A股） | 核心 | 辅助监控 | 高频信号无法当日执行 |

---

## 第七章：术语表

| 术语 | 定义 |
|------|------|
| `view_tf` | 视角 Agent 的时间框架，决定 position 计算的基准价 |
| `structure_tf` | 被观察的结构周期，提供 trend/base/volatility 指标 |
| `perspective_close` | 当前 Agent 视角的收盘价，所有 position 计算的统一基准 |
| `Agent` | 独立的全局观察器，包含本周期及以上大周期的对齐状态 |
| `State` | 4-bit 编码的市场状态（0-15，可带负号） |
| `state_hex` | State 的十六进制表示（0-F，可带负号） |
| `ef_count` | 当前 Agent 内 E/F 状态的结构周期数量 |
| `D1@H1_view` | H1 Agent 视角下 D1 结构周期的状态 |
| `双 Agent 差异` | 同一标的同一天不同 Agent 给出不同 State（设计特性） |
| `Agent 冲突` | 不同 Agent 对同一标的给出相反信号（需按场景选择） |

---

## 附录：Agent 扩展决策树

```text
是否需要新增 Agent？
  ├── 当前 Agent 是否覆盖分析场景？
  │     ├── 是 → 不新增
  │     └── 否 → 继续
  ├── 新 Agent 的交易频率是否可执行？
  │     ├── T+1 市场 + 小时级信号 → 只能监控，不能交易
  │     └── T+0 市场 + 小时级信号 → 可以交易
  ├── 新 Agent 的数据和计算成本是否可接受？
  │     ├── H1 Agent：数据量 24×，计算量 5 周期
  │     └── M30 Agent：数据量 48×，计算量 6 周期
  └── 新 Agent 的信息增益是否大于噪音成本？
        ├── 是 → 新增 Agent
        └── 否 → 用现有 Agent + 辅助指标替代
```

---

> **Research Only** — 本文档为系统架构设计，不构成投资建议。所有 Agent 定义和计算规则以 `docs/STATE_BASE_CONTRACT.md` 为准。
