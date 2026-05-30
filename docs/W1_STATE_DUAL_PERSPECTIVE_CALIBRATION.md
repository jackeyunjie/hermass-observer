# W1 结构在 D1 Agent / W1 Agent 下的校准文档

版本：v1.0
日期：2026-05-24
状态：设计稿
关联白皮书：`docs/MULTICYCLE_STATE_STRATEGY_WHITEPAPER.md`
关联验证：`docs/STATE_COMBO_CROSS_PERIOD_VALIDATION_DESIGN.md`

---

## 核心问题

系统会出现两种不同的“周线结构 State”，它们的计算方式不同、含义不同、适用场景不同。如果不明确区分，会导致规则混淆和回测口径错误。

```text
D1 Agent 中的 W1 结构状态：state_hex(D1, W1)
  用 D1 收盘价比较 W1 SR 关键位
  → 回答"D1 价格在周线的支撑阻力体系中处于什么位置"

W1 Agent 中的 W1 结构状态：state_hex(W1, W1)
  用 W1 周线收盘价比较 W1 SR 关键位
  → 回答"周线本身处于什么趋势和位置"
```

---

## 1. 两种周线结构状态的定义

### 1.1 D1 Agent 中的 W1 结构状态（当前系统使用）

```text
计算方式：
  W1 position = D1 close vs W1 SR（周线支撑阻力位）
  W1 trend    = W1 ADX/DI（周线级别的趋势指标）
  W1 base     = W1 布林带宽分位（周线级别的收缩/扩张）
  W1 vol      = W1 ATR%（周线级别的波动率）

数据来源：
  foundation DB → d1_perspective_state 表
  字段：w1_state_hex, w1_state_score, w1_base, w1_trend_bit, w1_position_bit, w1_volatility_bit

关键特征：
  position 使用的是 D1 收盘价（日线最新价）
  trend/base/vol 使用的是周线级别指标
  → `state_hex(D1, W1)`，即“用日线价格看周线结构”
```

### 1.2 W1 Agent 中的 W1 结构状态

```text
计算方式：
  W1 position = W1 close vs W1 SR（周线收盘价 vs 周线支撑阻力位）
  W1 trend    = W1 ADX/DI
  W1 base     = W1 布林带宽分位
  W1 vol      = W1 ATR%

数据来源：
  foundation DB → weekly_bars + timeframe_indicators（W1 行级指标）
  抽象命名：`state_hex(W1, W1)` 等

关键特征：
  position 使用的是 W1 周线收盘价（周五收盘）
  trend/base/vol 使用的是周线级别指标
  → `state_hex(W1, W1)`，即“用周线价格看周线结构”
```

### 1.3 核心差异

| 维度 | `state_hex(D1, W1)` | `state_hex(W1, W1)` |
|------|-------------------|---------------|
| position 计算基准 | D1 收盘价 | W1 周线收盘价 |
| trend/base/vol 计算 | 周线指标 | 周线指标（相同） |
| 更新频率 | 每个交易日 | 每个周末（周五收盘后） |
| 含义 | "日线价格在周线结构中的位置" | "周线自身的趋势和位置" |
| 盘中可用性 | 可用（D1 close 实时更新） | 不可用（需等周五收盘） |

### 1.4 差异场景

```text
场景 1：周三，D1 close = 50.0，W1 close（上周五）= 48.0，W1 SR 阻力 = 49.0

  state_hex(D1, W1)：D1 close(50) > W1 阻力(49) → position_bit = 2（突破）
  state_hex(W1, W1)：W1 close(48) < W1 阻力(49) → position_bit = 0（未突破）

  → 同一只股票，同一天，两种 W1 State 的 position 完全不同
  → D1 Agent 说"D1 价格已站上周线阻力"
  → W1 Agent 说"周线尚未确认突破"
  → 都是对的，只是回答的问题不同
```

---

## 2. 适用场景规定

### 2.1 使用 `state_hex(D1, W1)` 的场景

| 场景 | 理由 |
|------|------|
| 策略信号触发（VCP/2560/Bollinger entry） | 信号在日线上触发，需要与日线价格一致的 State |
| strategy_signal_daily 表 | 确保信号和 State 基于同一价格点 |
| 每日适配度计算 | lifecycle_stage 和 environment_fit 基于 D1 Agent |
| W1×MN1 环境标签 | 大周期背景标签基于 D1 Agent |
| 三重共振模型 | State 维度基于 D1 Agent |
| 前向观察账本 | 信号和 State 同日对齐 |

**原则**：所有需要与 D1 信号日期对齐的场景，使用 `D1 Agent` 中的周线结构状态。

### 2.2 使用 `state_hex(W1, W1)` 的场景

| 场景 | 理由 |
|------|------|
| 周线趋势判断 | 周线自身的趋势和位置，不依赖日线价格 |
| 周线级别的策略回测 | 用周线收盘价触发和退出的回测 |
| 跨期稳定性验证 | 按自然周分段验证时，使用 `state_hex(W1, W1)` |
| 周报/周度研究 | 周度频率的分析应基于 `state_hex(W1, W1)` |
| W1 SR 关键位有效性验证 | 验证周线 SR 是否在周线价格上有意义 |

**原则**：所有以自然周为分析单位的场景，使用 `W1 Agent` 中的周线结构状态。

### 2.3 不应混用的场景

```text
错误：用 `state_hex(D1, W1)` 触发信号，但用 `state_hex(W1, W1)` 计算回测收益
正确：信号触发和回测收益使用同一视角的 State

错误：周三看到 `state_hex(D1, W1) = E`，认为"周线已确认突破"
正确：`state_hex(D1, W1) = E` 意味着"D1 价格已站上 W1 阻力位"，
      但 `state_hex(W1, W1)` 仍可能未确认（需等周五）

错误：用 `state_hex(W1, W1)` 计算每日信号的 lifecycle_stage
正确：lifecycle_stage 基于 `D1 Agent`，因为信号在日线上触发
```

---

## 3. 差异量化分析

### 3.1 差异出现的频率

```python
def measure_w1_perspective_divergence(foundation_db: Path, date: str) -> dict:
    """测量某日 state_hex(D1, W1) 与 state_hex(W1, W1) 的差异率。"""
    # D1 Agent：d1_perspective_state.w1_state_score
    # W1 Agent：基于 weekly_bars 的 W1 close 计算

    # 差异类型：
    # 1. position_bit 不同（最常见）— 周中价格穿越 W1 SR
    # 2. trend_bit 不同（少见）— 周中 ADX 跨阈值
    # 3. base/vol 不同（极少见）— 周中带宽或 ATR 跨阈值

    return {
        "total_stocks": int,
        "position_divergence_count": int,  # position_bit 不同的数量
        "position_divergence_rate": float,  # 比例
        "full_state_divergence_count": int,  # state_hex 完全不同的数量
        "full_state_divergence_rate": float,
    }
```

**预期差异分布**：

| 日期类型 | position 差异率 | 完全 State 差异率 | 说明 |
|----------|----------------|-------------------|------|
| 周一 | 15-25% | 10-15% | 周末后开盘，D1 与上周五 W1 close 偏差最大 |
| 周三 | 20-30% | 15-20% | 周中最活跃，D1 价格穿越 W1 SR 概率最高 |
| 周五 | 5-10% | 3-5% | D1 close 与 W1 close 接近（同日收盘） |
| **平均** | **15-20%** | **10-15%** | |

### 3.2 差异对策略信号的影响

| 策略 | `state_hex(D1, W1)` 用于 | `state_hex(W1, W1)` 用于 | 差异影响 |
|------|----------------------|-------------------|---------|
| VCP | 信号触发 + 适配度 | 周线趋势确认 | 低 — VCP 主要看 D1 路径 |
| 2560 | State 组合匹配 + 市场匹配 | 周线趋势持续性 | 中 — 2560 的 E/F 组合可能因视角不同而变化 |
| Bollinger | 适配度 + 环境标签 | 周线波动率判定 | 低 — Bollinger 主要看 D1 波动 |

---

## 4. 迁移方案

### 4.1 当前状态

```text
d1_perspective_state 表：
  w1_state_hex     = state_hex(D1, W1) ✓
  w1_state_score   = state_score(D1, W1) ✓
  w1_position_bit  = D1 close vs W1 SR ✓

  无 W1 Agent 兼容字段
```

### 4.2 Phase 1：新增 W1 Agent 兼容字段

如果需要在 `d1_perspective_state` 中并排展示两种 Agent 结论，可新增 W1 Agent 兼容字段：

```sql
ALTER TABLE d1_perspective_state ADD COLUMN w1_agent_state_hex VARCHAR;
ALTER TABLE d1_perspective_state ADD COLUMN w1_agent_state_score INTEGER;
ALTER TABLE d1_perspective_state ADD COLUMN w1_agent_position_bit INTEGER;
ALTER TABLE d1_perspective_state ADD COLUMN w1_agent_available BOOLEAN DEFAULT false;
```

**计算逻辑**：

```python
def compute_w1_agent_state(
    w1_close: float,        # 周线收盘价（来自 weekly_bars）
    w1_sr_support: float,
    w1_sr_resistance: float,
    w1_trend_bit: int,      # 与 D1 Agent 相同（周线指标）
    w1_base: int,           # 与 D1 Agent 相同
    w1_volatility_bit: int, # 与 D1 Agent 相同
) -> int:
    """
    计算 W1 Agent 中的周线结构状态。

    与 D1 Agent 中周线结构状态的唯一区别：
      position_bit 使用 W1 close 而非 D1 close
    """
    if w1_close > w1_sr_resistance:
        position_bit = 2  # 上突
    elif w1_close < w1_sr_support:
        position_bit = 0  # 下突（实际为 negative）
    else:
        position_bit = 0  # 中位

    score = w1_base + w1_trend_bit * 4 + position_bit * 2 + w1_volatility_bit

    # 符号裁决（位置优先）
    if w1_close < w1_sr_support:
        score = -score

    return score
```

**更新时机**：每个周末（周五收盘后），从 `weekly_bars` 表读取最新 W1 close，更新全量股票的 W1 Agent 状态。

### 4.3 Phase 2：双 Agent 报告

在 State 缓存和报告中同时展示两个 Agent 下的周线结构状态：

```text
报告展示格式：
  W1 结构 @ D1 Agent：E  ← 用于信号匹配
  W1 结构 @ W1 Agent：C  ← 用于周线趋势判断
  差异标记：D1 Agent 与 W1 Agent 不一致（position 差异）
```

```python
def w1_dual_label(d1_agent_hex: str, w1_agent_hex: str) -> str:
    if d1_agent_hex == w1_agent_hex:
        return d1_agent_hex
    return f"{d1_agent_hex}(D1 Agent) / {w1_agent_hex}(W1 Agent)"
```

### 4.4 Phase 3：规则迁移

逐步将特定规则从 `D1 Agent` 迁移到 `W1 Agent`：

| 规则 | 当前使用 | 迁移目标 | 迁移时机 |
|------|----------|----------|----------|
| 策略信号触发 | D1 Agent | D1 Agent | **不迁移** — 信号在日线上触发 |
| lifecycle_stage | D1 Agent | D1 Agent | **不迁移** — 适配度基于日线 |
| 2560 E/F 组合匹配 | D1 Agent | D1 Agent | **不迁移** — 已固化规则 |
| 周线趋势持续性验证 | D1 Agent | W1 Agent | Phase 3 |
| 跨期稳定性验证（按周分段） | D1 Agent | W1 Agent | Phase 3 |
| 周报/周度研究 | 混用 | W1 Agent | Phase 3 |
| W1×MN1 环境标签 | D1 Agent | 待评估 | Phase 3+ |

**关键原则**：已固化的规则（2560 E/F 组合）不迁移。新规则优先使用 `W1 Agent` 明确口径。

---

## 5. 校准方法

### 5.1 D1 Agent 与 W1 Agent 的一致性校准

定期（每月）运行一致性校准，确保两个 Agent 的差异在预期范围内：

```python
def calibrate_w1_perspective(foundation_db: Path, month: str) -> dict:
    """
    月度校准：统计 state_hex(D1, W1) 与 state_hex(W1, W1) 的差异。
    """
    # 1. 统计全月每个交易日的差异率
    # 2. 检查差异率是否在预期范围（15-20%）
    # 3. 检查差异是否集中在特定行业或特定 State 值
    # 4. 输出校准报告

    return {
        "month": str,
        "avg_position_divergence_rate": float,  # 预期 15-20%
        "avg_full_divergence_rate": float,       # 预期 10-15%
        "worst_day": str,                        # 差异最大的日期
        "worst_day_rate": float,
        "by_day_of_week": dict,                  # 按星期几分组的差异率
        "verdict": "normal" / "elevated" / "investigate",
    }
```

### 5.2 策略信号口径校准

当引入 `W1 Agent` 后，需要校准策略信号在两种口径下的表现差异：

```python
def calibrate_signal_impact(foundation_db: Path, strategy_id: str) -> dict:
    """
    校准同一策略信号在 D1 Agent vs W1 Agent 下的适配度差异。
    """
    # 1. 用 D1 Agent 计算 fit_score
    # 2. 用 W1 Agent 计算 fit_score
    # 3. 比较两者的差异
    # 4. 统计 fit_score 变化的信号占比

    return {
        "total_signals": int,
        "fit_score_unchanged": int,      # 两种口径下 fit_score 相同
        "fit_score_upgraded": int,       # W1 Agent 口径下 fit 更高
        "fit_score_downgraded": int,     # W1 Agent 口径下 fit 更低
        "avg_fit_change": float,         # 平均 fit_score 变化
    }
```

### 5.3 校准报告

```text
outputs/calibration/w1_perspective_calibration_{YYYYMM}.json
outputs/calibration/w1_perspective_calibration_latest.json
```

---

## 6. 决策矩阵

遇到"该用哪种 W1 State"时，查此表：

| 问题 | 答案 |
|------|------|
| 今天要触发一个 VCP entry 信号 | `state_hex(D1, W1)` |
| 计算信号的 lifecycle_stage | `state_hex(D1, W1)` |
| 判断 W1×MN1 大周期环境 | `state_hex(D1, W1)` |
| 做跨期稳定性验证（按半年分段） | `D1 Agent`（信号口径一致性） |
| 写周报分析周线趋势 | `state_hex(W1, W1)` |
| 验证 W1 SR 关键位有效性 | `state_hex(W1, W1)` |
| 回测周线级别的策略（周线收盘触发） | `state_hex(W1, W1)` |
| 三重共振模型的 State 维度 | `state_hex(D1, W1)` |
| 市场阶段识别 | `state_hex(D1, W1)` |
| 机会模式挖掘 | `D1 Agent`（跃迁路径基于日频） |

**一句话规则**：日频分析用 `D1 Agent`，周频分析用 `W1 Agent`。

---

## 7. 术语表

| 术语 | 定义 |
|------|------|
| `state_hex(D1, W1)` | 用 D1 收盘价比较 W1 SR 关键位计算得到的 W1 结构状态 |
| `state_hex(W1, W1)` | 用 W1 周线收盘价比较 W1 SR 关键位计算得到的 W1 结构状态 |
| position_divergence | `D1 Agent` 与 `W1 Agent` 的 position_bit 不同（最常见差异） |
| full_state_divergence | `D1 Agent` 与 `W1 Agent` 的 state_hex 完全不同 |
| D1 Agent 天条 | 当前系统核心原则：D1 Agent 内所有结构周期的 position 用 D1 收盘价统一比较 |
| W1 SR | 周线级别的支撑位和阻力位（由分形计算） |
