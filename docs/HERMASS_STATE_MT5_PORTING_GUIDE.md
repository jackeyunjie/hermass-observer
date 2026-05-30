# Hermass State 系统 — MT5 平台移植与交叉验证指南

> 版本：v1.0
> 日期：2026-05-26
> 状态：**已归档**
> 目标读者：MT5/Windows 平台量化开发者（历史参考）
>
> 范围声明：本系统已专注 A 股市场。本文档仅作历史归档，不作为 A 股系统的设计依据或运行参考。
>
> 关联文件：
>   - `docs/STATE_BASE_CONTRACT.md`（State 底座宪法文件）
>   - `scripts/state_calc/p116_core.py`（Python 参考实现）
>   - `config/schema_v2.sql`（Foundation DB Schema）
>   - `outputs/p116_foundation_mt4like_20260520/`（MT4 风格输出样例）

---

## 第一章：State 是什么

### 1.1 一句话定义

State 是一个**4-bit 数字编码系统**，用一个字符（0-9/A-F，可带负号）描述一只股票在某个周期上的综合状态。四个维度同时编码在一个数字里：

```
状态编码 = 基数 + 趋势方向 + 价格位置 + 波动状态

  base (8 or 0)     + trend_bit × 4  + position_bit  + volatility_bit
  ↑                      ↑                ↑               ↑
  布林带宽是扩/缩       趋势ADX是否活跃   价格是否突破SR    ATR是否扩张
```

### 1.2 编码表

| score | hex | base | trend | position | volatility | 含义 |
|-------|-----|------|-------|----------|------------|------|
| 15 | F | 扩(8) | 有趋势(4) | 突破(2) | 波扩(1) | 最强状态——四维全开 |
| 14 | E | 扩(8) | 有趋势(4) | 突破(2) | 稳(0) | 最优质——趋势突破但不伴随过热 |
| 12 | C | 扩(8) | 有趋势(4) | 区间内(0) | 稳(0) | 扩张+趋势，但未突破边界 |
| 8 | 8 | 扩(8) | 无趋势(0) | 区间内(0) | 稳(0) | 扩张但缺乏方向 |
| 0 | 0 | 缩(0) | 无趋势(0) | 区间内(0) | 稳(0) | 完全收缩——蓄力阶段 |
| -12 | -C | 扩(8) | 有趋势(4) | 区间内(0) | 稳(0) | 与前向 C 相同幅度，但方向为负 |
| -14 | -E | 扩(8) | 有趋势(4) | 突破(2) | 稳(0) | 负向 E——破位确认 |
| -15 | -F | 扩(8) | 有趋势(4) | 突破(2) | 波扩(1) | 负向 F——最弱状态 |

### 1.3 E 和 F 的特殊地位

```
E = score = 14
F = score = 15

E/F 状态永远是正值。负值 '-E'、'-F' 不算 E/F 状态。
```

ef_count = MN1/W1/D1 三周期中处于 E 或 F 状态的周期数量，取值范围 0-3。

```
ef_count = 3 → 三周期共振（最强信号）
ef_count = 2 → 双周期共振（大概率信号）
ef_count = 1 → 单周期信号
ef_count = 0 → 无 E/F 状态
```


## 第二章：Agent 视角决定基准价 —— 这是最核心的概念

> **⚠ 关键纠正：不是所有场景都用 D1 收盘价。当前 Agent 决定了用哪个周期的收盘价。**

### 2.1 核心原理

State 系统的关键设计是：**每个周期视角都是独立 Agent，而 Agent 的基准周期决定所有 position 计算使用的收盘价**。

```
view_tf      = 视角 Agent 所在周期
structure_tf = 被观察的结构周期

你在哪个 Agent 上观察
  → 该 Agent 的收盘价就是所有 structure_tf position 的基准

D1 Agent（日线观察者）：
  MN1 position = D1 close vs MN1 SR
  W1  position = D1 close vs W1  SR
  D1  position = D1 close vs D1  SR

W1 Agent（周线观察者）：
  MN1 position = W1 close vs MN1 SR
  W1  position = W1 close vs W1  SR
  D1  position = W1 close vs D1  SR

H1 Agent（小时线观察者）：
  MN1 position = H1 close vs MN1 SR
  W1  position = H1 close vs W1  SR
  D1  position = H1 close vs D1  SR
  H4  position = H1 close vs H4  SR
  H1  position = H1 close vs H1  SR
```

**trend、base、volatility 始终使用各自 structure_tf 的指标数据，只有 position 的基准价随 Agent 变化。**

### 2.2 为什么有多种 Agent

不同 Agent 回答不同的问题：

| Agent | 回答的问题 | 更新频率 | 典型用途 |
|------|-----------|----------|----------|
| **D1 Agent** | "日线价格在各周期结构中的位置" | 每个交易日 | 每日信号触发、适配度、前向观察 |
| **W1 Agent** | "周线自身处于什么趋势和位置" | 每个周末 | 周线趋势判断、周度回测、周报 |
| **H1 Agent** | "小时价格在各周期结构中的位置" | 每小时 | 盘中实时监控、日内交易 |
| **MN1 Agent** | "月线自身处于什么趋势和位置" | 每月末 | 月度宏观判断、长期配置 |

### 2.3 同一标的、同一天、不同 Agent 可能给出不同的 State

```
周三，某股票：
  D1 close = 50.0，W1 close（上周五）= 48.0
  W1 SR 阻力 = 49.0

  D1 Agent 的 W1 结构状态：D1 close(50) > W1 阻力(49) → position = 突破
  W1 Agent 的 W1 结构状态：W1 close(48) < W1 阻力(49) → position = 未突破

  两者都是对的——回答的问题不同
  D1 Agent 说"日线价格已站上阻力位"
  W1 Agent 说"周线收盘尚未确认突破"
```

**这不是 bug，是设计。**

### 2.4 MT5 中的 Agent 选择

| MT5 图表 | 推荐 Agent | 理由 |
|----------|---------|------|
| 日线图 | D1 Agent | 与策略信号系统一致 |
| 周线图 | W1 Agent | 周线自身趋势判断 |
| 小时图 | H1 Agent | 盘中实时监控 |
| 月线图 | MN1 Agent | 月度宏观环境判断 |

**关键：在 MT5 上切换图表周期时，State 的 position 基准价会自动变化。** 这是正确行为——不同图表周期对应不同 Agent。

### 2.5 与 MT5 多周期指标的关系

以 D1 Agent 为例（最常用），MT5 中的计算对应关系：

| 计算维度 | 使用哪根 bar |
|----------|-------------|
| MN1 base（布林带宽） | 月线 bar 的布林带 |
| MN1 trend（ADX 方向） | 月线 bar 的 ADX |
| MN1 volatility（ATR） | 月线 bar 的 ATR |
| MN1 position（价格位置） | **D1 bar 的收盘价** vs 月线 bar 的 SR 关键位 |
| W1 base/trend/volatility | 周线 bar 的各自指标 |
| W1 position | **D1 bar 的收盘价** vs 周线 bar 的 SR 关键位 |
| D1 base/trend/volatility | 日线 bar 的各自指标 |
| D1 position | **D1 bar 的收盘价** vs 日线 bar 的 SR 关键位 |

如果切换为 W1 Agent，只需把 position 列的"D1 bar 的收盘价"改为"W1 bar 的收盘价"。

### 2.6 双 Agent 差异率（实测数据）

我们的 Python 系统同时维护 `D1 Agent` 与 `W1 Agent` 对周线结构的观察，实测差异率：

| 差异类型 | 平均差异率 | 最大差异日 |
|----------|-----------|-----------|
| position_bit 不同 | 15-20% | 周三（20-30%） |
| 完全 State 不同 | 10-15% | 周三 |
| 最小差异日 | 5-10% | 周五（D1 close ≈ W1 close） |

**MT5 移植时，必须明确当前使用哪个 Agent 计算 State，不要混用。**


## 第三章：State 计算公式与参数

### 3.1 4-bit 编码公式（不可变）

```text
state_magnitude = base + (trend_bit × 4) + position_bit + volatility_bit
state_score     = sign × state_magnitude

取值范围：
  正号:  0 ~ 15
  负号: -15 ~ -1
```

### 3.2 Bit 位判定规则

#### base（基数）

| 值 | 条件 | 含义 |
|----|------|------|
| 8 | 布林带宽未处于 closed 状态 | 扩张——市场在动 |
| 0 | 布林带宽处于 closed 或 contracting | 收缩——蓄力阶段 |

**布林带宽分位计算**：当前 bar 的布林带宽 在 前 20 根 bar（不含当前）的带宽分布中的位置。

- BB 滚动窗口：**20 bar**
- BB 分位窗口：**前 20 bar（不含当前）**
- `compression = 'closed'` 条件：当前带宽 < Q20（前 20 bar 的 bandwidth 第 20 分位）

#### trend_bit（趋势）

| 值 | 条件 |
|----|------|
| 1 | ADX ≥ 25 且 ADX 斜率 > 0 且 +DI > -DI → bull_trend |
| 1 | ADX ≥ 25 且 ADX 斜率 > 0 且 -DI > +DI → bear_trend |
| 1 | ADX > 20 且 +DI > -DI → bull_start |
| 1 | ADX > 20 且 -DI > +DI → bear_start |
| 0 | ADX ≤ 13 且 ADX 斜率 < 0 → closed |
| 0 | 其他 → neutral |

ADX 窗口：**14 bar**
DI 窗口：**14 bar**
ADX 斜率：当前 adx14 - 前 3 根 bar 的 adx14

#### position_bit（位置突破）

| 值 | 条件 |
|----|------|
| 2 | perspective_close > sr_resistance（突破阻力位） |
| 2 | perspective_close < sr_support（突破支撑位） |
| 0 | 在 sr_support 和 sr_resistance 之间 |

**注意**：无论上突还是下突，position_bit 都是 2。方向的正负由符号裁决决定。

#### volatility_bit（波动）

| 值 | 条件 |
|----|------|
| 1 | 当前 ATR > 前一根 bar 的 ATR（ATR 扩张） |
| 0 | 当前 ATR ≤ 前一根 bar 的 ATR（ATR 稳定或收缩） |

ATR 窗口：**14 bar**

### 3.3 SR（支撑/阻力）关键位计算

SR 关键位使用分形算法：

```text
Step 1: SqFractal 5
  - 分形高点：high 大于前后各 2 根 bar 的 high → center_fractal_resistance
  - 分形低点：low 小于前后各 2 根 bar 的 low → center_fractal_support

Step 2: 确认延迟 3 根 bar
  - 确认后的分形高点 = lag(center_fractal_resistance, 3)
  - 确认后的分形低点 = lag(center_fractal_support, 3)

Step 3: 前向填充
  - sr_resistance = last_value(确认后分形高点 IGNORE NULLS)
  - sr_support = last_value(确认后分形低点 IGNORE NULLS)
```

参数：**fractal_period = 5, confirm_lag_bars = 3（不可变）**

### 3.4 符号裁决（sign determination）

```text
优先级 1（最高优先）—— 价格与 SR 的关系：
  IF perspective_close > mn1_sr_resistance → 正号 ✅
  IF perspective_close < mn1_sr_support     → 负号 ⚠️

优先级 2（仅当 close 在 SR 区间内时生效）—— 大周期框架方向：
  IF mn1_bear_context AND NOT mn1_bull_context → 负号
  ELSE → 正号

mn1_bear_context = (mn1_trend LIKE 'bear%' 或 mn1 D1 close < mn1 D1 support)
mn1_bull_context = (mn1_trend LIKE 'bull%' 且 mn1 D1 close > mn1 D1 support)
```


## 第四章：三周期的特征与关系

### 4.1 三个周期的定位

```
MN1（月线）
├── 角色：大周期背景板
├── 特征：变动慢，稳定性高
├── 作用：决定整体市场环境（牛市/震荡/收缩/破位）
└── 对决策的意义：MN1 处于 E/F → 趋势背景健康
                   MN1 为负值 → 大周期不支持做多

W1（周线）
├── 角色：中期节奏控制器
├── 特征：比月线灵敏，比日线稳定
├── 作用：识别中期蓄力/释放的节奏
└── 对决策的意义：W1 在 8-B（扩张未突破）→ 蓄力中，突破前夜
                   W1 为 E/F → 中期强势，趋势延续

D1（日线）
├── 角色：短期动量指示器
├── 特征：变动最快，最灵敏
├── 作用：捕捉日线级别的突破/回踩信号
└── 对决策的意义：D1 为 F(15) → 短期最强，但需防过热
                   D1 为 -C/-E/-F → 短期风险，注意出场
```

### 4.2 周期间的关系——ef_count 的作用

```
ef_count 是 MN1 + W1 + D1 三周期 E/F 计数的总和（0-3）

这就是多周期共振的核心度量：
  ef=3  → 三个周期都在说同一件事 → "合力"
  ef=2  → 两个周期确认 → "大概率"
  ef=1  → 仅一个周期 → "需要更多确认"
  ef=0  → 无一确认 → "缺乏共振"

同一个 ef=3 信号，在不同月线环境下表现不同：
  MN1=E/F 时 ef=3 → 顺势，期望收益高
  MN1 为负时 ef=3 → 逆大周期，需警惕（降噪）
```

### 4.3 周期间的特征差异（为什么 D1 比 MN1 更容易出现 E/F）

在 D1 Agent 下：D1 价格变动最快，同一个 SR 区间内 D1 的 position_bit 触发概率远高于月线。同时 D1 的布林带宽变化也更频繁。

**这不是 bug，是设计意图**——日线的高频 E/F 提供短期入场信号，月线的低频 E/F 提供环境框架验证。两者配合使用。

**注意**：如果切换为 W1 Agent，W1 的 E/F 出现频率会比 D1 Agent 下的 W1 更高（因为 W1 close 通常比 D1 close 更稳定地处于某个位置）。这是正确行为。

### 4.4 混合 Agent 陷阱（MT5 特有）

**最常见的错误**：在 MT5 的日线图上看到 D1 State = E，然后切换到周线图看 W1 State，以为两者使用了同一个基准价。实际上：

```
日线图上的 W1 State = D1 close vs W1 SR（D1 Agent）
周线图上的 W1 State = W1 close vs W1 SR（W1 Agent）

两者可能不同！
```

**正确做法**：
- 要看"日线价格在周线结构中的位置" → 在日线图上看 W1 State
- 要看"周线自身的趋势和位置" → 在周线图上看 W1 State
- 两者不能混用

**MT5 实现建议**：在指标面板上明确标注当前 Agent（"D1 Agent" / "W1 Agent"），避免用户混淆。


## 第五章：MT5 平台 MQL5 实现指南

### 5.1 整体架构

MT5 上需要实现以下组件：

```text
MT5 Indicators（独立指标）
├── P116_SR_Fractal.ex5       ← 分形关键位 (fractal_period=5)
├── P116_BB_Bandwidth.ex5     ← 布林带宽分位 (BB=20, 分位窗口=20)
├── P116_ADX_State.ex5        ← ADX/DI 趋势判定 (ADX=14, slope=3)
└── P116_ATR_Volatility.ex5   ← ATR 波动状态 (ATR=14)

MT5 Script/EA（综合脚本）
└── P116_State_Calculator.ex5 ← 读取上述指标 → 计算 State → 输出 CSV
```

### 5.2 核心 MQL5 伪代码：State 计算

```cpp
// P116_State_Calculator.mq5
// 参数（不可变 !!!）
input int BB_Period = 20;
input int BB_Quantile_Bars = 20;
input int ADX_Period = 14;
input int ADX_Slope_Bars = 3;
input int Fractal_Period = 5;
input int Confirm_Lag_Bars = 3;
input int ATR_Period = 14;

// --- struct StateResult ---
struct StateResult {
    int    base;           // 0 or 8
    int    trend_bit;      // 0 or 1
    int    position_bit;   // 0 or 2
    int    volatility_bit; // 0 or 1
    int    score;
    string hex;
};

// --- 工具：十六进制转换 ---
string ToHex(int score) {
    if (score >= 0) return StringFormat("%X", score);
    return StringFormat("-%X", -score);
}

// --- 计算函数（每个周期复用同一下述逻辑）---
StateResult CalculateState(
    double perspective_close,     // ★Agent 基准价（D1 Agent→d1_close, W1 Agent→w1_close, H1 Agent→h1_close）
    double sr_support,            // 本周期SR支撑（各自周期的！）
    double sr_resistance,         // 本周期SR阻力（各自周期的！）
    double trend_ma_fast,         // 本周期快均线（各自周期的！）
    double trend_ma_slow,         // 本周期慢均线（各自周期的！）
    double atr_current,           // 本周期当前ATR（各自周期的！）
    double atr_previous,          // 本周期前一根ATR（各自周期的！）
    bool   is_compression_closed  // 本周期布林带宽是否处于closed
) {
    StateResult res;

    // ---- position_bit：Agent 基准价 vs 本周期SR ----
    // ⚠ perspective_close 取决于当前 Agent：
    //    D1 Agent → d1_close, W1 Agent → w1_close, H1 Agent → h1_close
    if (perspective_close > sr_resistance) {
        res.position_bit = 2;
    } else if (perspective_close < sr_resistance) {
        res.position_bit = 2;
    } else {
        res.position_bit = 0;
    }

    // ---- trend_bit：MA比较 ----
    if (trend_ma_fast != trend_ma_slow) {
        res.trend_bit = 1;
    } else {
        res.trend_bit = 0;
    }

    // ---- base：布林带宽 ----
    res.base = (!is_compression_closed && res.trend_bit == 1) ? 8 : 0;

    // ---- volatility_bit：ATR方向 ----
    res.volatility_bit = (atr_current > atr_previous) ? 1 : 0;

    // ---- 计算score ----
    res.score = res.base
              + (res.trend_bit * 4)
              + res.position_bit
              + res.volatility_bit;

    // ---- 符号裁决（用 MN1 的 SR 判定）----
    res.hex = ToHex(res.score);

    return res;
}
```

### 5.3 MT5 坐标对齐的关键注意事项

**这是最容易出错的地方**。Python 版本用的是数据帧（DataFrame），MT5 用的是时间序列数组。

**黄金规则**：

```
在 MT5 中，每个周期的当前bar索引不同 ON THE SAME DAY:

  日线 D1 bar[0]     → 2024-05-26 当日日线
  周线 W1 bar[0]     → 2024-05-26 所在的周K线（可能尚未闭合！）
  月线 MN1 bar[0]    → 2024-05-26 所在的月K线（可能尚未闭合！）
```

由于 MT5 **每周一生成新周K线、每月一生成新月K线**，在周二/周三调用时：
- 周线 `bar[0]` 的数据（high/low/close）可能随当周后续交易日变化
- 月线同理

**解决方案**：向后偏移一根 bar 来获取"已闭合"的周期数据：

```cpp
// 获取已闭合的月线 bar（即前一根月线）
int mn1_idx = 1;  // 前一根月线（已闭合）
double mn1_close = iClose(_Symbol, PERIOD_MN1, mn1_idx);

// 获取已闭合的周线 bar
int w1_idx = 1;   // 前一根周线（如果本周未结束）
double w1_close = iClose(_Symbol, PERIOD_W1, w1_idx);

// 日线用最新（因为是当天数据）
int d1_idx = 0;
double d1_close = iClose(_Symbol, PERIOD_D1, d1_idx);

// ★ 视角基准价：根据当前图表周期自动选择
// D1 图表 → perspective_close = d1_close
// W1 图表 → perspective_close = w1_close
// H1 图表 → perspective_close = h1_close
double perspective_close;
if (Period() == PERIOD_D1) perspective_close = d1_close;
else if (Period() == PERIOD_W1) perspective_close = w1_close;
else if (Period() == PERIOD_H1) perspective_close = iClose(_Symbol, PERIOD_H1, 0);
else perspective_close = d1_close; // 默认 D1 Agent
```

**检验方法**：用 Python 端提取同一天的 MT4-like Foundation DB（`p116_foundation_mt4like_20260520`），将当天任意一只股票的三周期 State hex 与 MT5 计算结果逐一对比，不一致即表示坐标对齐错误。

### 5.4 ADX/DI 判定（MQL5 实现）

```cpp
int adx = iADX(_Symbol, period, 14);
int adx_prev_3 = iADX(_Symbol, period, 14, 3); // 往前3根
double adx_slope = adx - adx_prev_3;
double pdi = ...;
double ndi = ...;

bool is_closed  = (adx <= 13 && adx_slope < 0);
bool is_bull    = (adx >= 25 && adx_slope > 0 && pdi > ndi);
bool is_bear    = (adx >= 25 && adx_slope > 0 && ndi > pdi);
bool is_bull_s  = (adx > 20 && pdi > ndi);
bool is_bear_s  = (adx > 20 && ndi > pdi);
```

### 5.5 分形关键位（MQL5 实现）

```cpp
// Fractal 高点：high 大于前后各 2 根
bool is_high = (
    high[i] > high[i-1] && high[i] > high[i-2] &&
    high[i] > high[i+1] && high[i] > high[i+2]
);

// 确认延迟 3 根
double confirmed_high = is_high_at[i-3] ? high[i-3] : prev_confirmed;

// 前向填充
double current_resistance = (confirmed_high != 0)
    ? confirmed_high
    : last_valid_resistance;
```


## 第六章：交叉验证方法

### 6.1 Python → MT5 单向验证

MT5 的 State 计算结果必须与 Python 端一致。**验证时必须明确当前 Agent**：

```text
验证 D1 Agent：在 MT5 日线图上运行，对比 Python 的 d1_perspective_state
验证 W1 Agent：在 MT5 周线图上运行，对比 Python 的 build_weekly_state_independent 输出
```

两种视角的 State 可能不同——这是正确行为，不是错误。验证流程：

```text
1. Python 端提取基准数据：
   python3 scripts/build_p116_foundation.py --date YYYY-MM-DD  # 生成 Foundation DB
   python3 scripts/build_p116_ashare_d1_native_state_v2.py       # 生成 state_hex

2. 从 Foundation DB 提取当日任意 10 只股票的 MN1/W1/D1 State Hex：
   duckdb outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb -c "
       SELECT stock_code, state_date,
              mn1_state_hex, w1_state_hex, d1_state_hex,
              ef_count, d1_close
       FROM d1_perspective_state
       WHERE state_date = 'YYYY-MM-DD'
       LIMIT 10
   "

3. 在 MT5 上对同一批标的运行 P116_State_Calculator，
   逐一对标 MN1/W1/D1 state_hex 和 ef_count

4. 一致 → 通过
   不一致 → 检查以下三个最常见的错位：
     a) 周线/月线 bar 索引错误（偏移量不对）
     b) ADX 窗口参数不一致
     c) SR 确认延迟根数不对
```

### 6.2 参考输出样例

以下是从 MT4-like Foundation DB 提取的真实数据作为交叉验证样本：

```
stock_code  state_date  mn1  w1   d1   ef  d1_close
000001.SZ   2026-05-20  -E   -C   -C   0   26.32
000007.SZ   2026-05-20  E    E    F    3   41.20
000012.SZ   2026-05-20  8    C    -C   0   18.45
000977.SZ   2026-05-20  E    E    C    2   38.90
```

这些是 Python 端（正确的）状态数据。MT5 端必须输出与之完全一致的 hex 值。


## 第七章：混沌值系统与不同编码的统一

### 7.1 问题的根源

你之前使用的"混沌值系统"和现在的 State 系统在编码上可能存在差异：

1. **编码位数不同**——有的混沌系统用 8-bit 或更多位编码
2. **周期 Agent 不同**——有的系统各周期独立计算 position，而非当前文档定义的 D1 Agent
3. **符号裁决不同**——大周期方向对符号的影响权重不同
4. **指标参数不同**——ADX/BB/ATR 的窗口期可能不同

### 7.2 统一的方法

建议分三步走：

```text
Step 1: 锁定参数
  - 以本文档的数值为准（4-bit 编码、D1 Agent、各窗口参数）
  - 在 MT5 上全部重写，不继承旧代码的参数

Step 2: 输出并行对比
  - 同一日期、同一标的，同时输出 Python State 和 MT5 State
  - 对比两个系统的输出，标记差异

Step 3: 差异归因
  - 逐一排查差异：
    a) 布林带宽分位计算方式 → 统一为前 20 根 bar 分布
    b) ADX 判定阈值 → 统一为 13/20/25 三档
    c) SR 分形确认延迟 → 统一为 3 根 bar
    d) 周期 bar 索引偏移 → 统一为前一根已闭合 bar
    e) 符号裁决规则 → 统一为本文档 3.4 节的优先级
```

### 7.3 不可变参数清单

以下参数的值是**不可变**的。如果旧系统的参数与下列不同，需要改为下列值：

| 参数 | 值 | 含义 |
|------|-----|------|
| BB 滚动窗口 | **20** | 布林中轨/标准差 |
| BB 分位窗口 | **20** | 不含当前 bar |
| ATR 窗口 | **14** | ATR14 |
| ADX 窗口 | **14** | ADX/DI |
| ADX 斜率 | **3** bar | 当前 vs 前 3 根 |
| ADX closed 阈值 | **≤ 13** | 无趋势 |
| ADX trend 阈值 | **≥ 25** | 强趋势 |
| ADX start 阈值 | **> 20** | 趋势启动 |
| 分形 period | **5** | SqFractal |
| 分形确认 lag | **3** bar | 延迟确认 |
| 编码位数 | **4-bit** | base+trend+pos+vol |


## 第八章：每日数据自动对齐方案

MT5 平台与 Python 并行运行后，每日流程：

```text
每日 15:15 CST：
  ├── Python 端：run_daily_pipeline.sh
  │   └── → outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb
  │
  ├── MT5 端：运行 P116_State_Calculator
  │   └── → 输出 CSV（MN1/W1/D1 state_hex + ef_count 每只股票）
  │
  └── 交叉验证脚本：
      python3 scripts/verify_state_calculation.py --mt5-csv <path>
        → 跨平台对比输出（一致/pass vs 差异/fail）
```

---

## 附录 A：关键术语对照

| 中文 | 英文 | 缩写 |
|------|------|------|
| 收缩 | Compression / Contraction | comp |
| 扩张 | Expansion | exp |
| 支撑位 | Support | SR_support |
| 阻力位 | Resistance | SR_resistance |
| 突破 | Breakout | — |
| 布林带宽度 | Bollinger Bandwidth | BBWidth |
| 分形 | Fractal | — |
| 前向填充 | Forward Fill | ffilled |

## 附录 B：参考运行命令

```bash
# Python 端：生成一天的数据
python3 scripts/build_p116_foundation.py --date 2026-05-25

# Python 端：验证任何一天的 State 计算
python3 scripts/verify_state_calculation.py --date 2026-05-25

# Python 端：提取任意股票的 State 详情
python3 scripts/query_state_detail.py --code 000001 --date 2026-05-25
```

---

## 附录 C：关键纠正清单（v1.1 更新）

| 编号 | 纠正内容 | 影响 |
|------|----------|------|
| C1 | **position 基准价由 Agent 决定，不是固定用 D1 close** | D1 Agent→D1 close；W1 Agent→W1 close；H1 Agent→H1 close |
| C2 | **不同 Agent 下同一标的同一天可能给出不同 State** | 正确行为，不是 bug |
| C3 | **MT5 切换图表周期时，State 计算自动切换 Agent** | 需要在指标面板标注当前 Agent |
| C4 | **trend/base/volatility 始终用各自周期指标** | 只有 position 的基准价随 Agent 变化 |
| C5 | **混合 Agent 是 MT5 上最常见的错误** | 日线图看 W1 State ≠ 周线图看 W1 State |

---

> **Research Only** — 本文档与 State 底座均为研究工具，不构成投资建议。所有参数值经团队全票确认后不可单方面修改。
