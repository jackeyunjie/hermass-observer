# 多周期 State 底座扩展设计

版本：v1.0
日期：2026-05-23
状态：设计稿
关联模块：`scripts/state_calc/p116_core.py`、`scripts/state_calc/d1_perspective.py`

---

## 概述

当前 State 底座使用 MN1（月线）、W1（周线）、D1（日线）三个周期的 4-bit 编码。本文档设计两种扩展方向：

- **方向 A**：新增时间周期（小时线 H1、15 分钟线 M15）
- **方向 B**：新增 State 维度（资金流维度）

两种扩展均需保持现有契约不变：D1 视角天条、位置优先符号裁决、确认延迟+前向填充。

---

## 1. 方向 A：新增时间周期

### 1.1 现有三周期架构

```text
当前 State = f(MN1, W1, D1)
  每个周期：score = base + trend_bit*4 + position_bit*2 + volatility_bit
  D1 视角：所有周期的 position 都用 D1 close 比较该周期 SR
```

### 1.2 新增 H1（小时线）的挑战

**核心问题**：D1 视角天条要求"所有周期的 position 都用 D1 收盘价比较"。对于日内周期（H1、M15），D1 收盘价在盘中尚未确定。

**解决方案：盘中用最新价，收盘后用收盘价**

```text
盘中计算：
  H1 position = 最新成交价 vs H1 SR
  M15 position = 最新成交价 vs M15 SR

收盘后计算：
  H1 position = D1 close vs H1 SR
  M15 position = D1 close vs M15 SR
```

这保持了"同一个价格数据点统一比较所有周期"的契约，只是数据点从"D1 收盘价"扩展为"当前观察价"。

### 1.3 H1/M15 State 编码

复用现有 4-bit 公式：

```text
H1_score = H1_base + H1_trend_bit*4 + H1_position_bit*2 + H1_volatility_bit
M15_score = M15_base + M15_trend_bit*4 + M15_position_bit*2 + M15_volatility_bit
```

各分量计算参数：

| 分量 | D1 当前参数 | H1 建议参数 | M15 建议参数 |
|------|------------|------------|-------------|
| base（布林带宽分位） | 滑动窗口 120 日 | 滑动窗口 120 小时 | 滑动窗口 120 根 K 线 |
| trend（快/慢均线） | ADX/DI | MA12/MA26 | MA8/MA21 |
| position（SR 分形） | 分形 k=5 | 分形 k=5 | 分形 k=5 |
| volatility（ATR 比较） | ATR% vs 均值 | ATR% vs 均值 | ATR% vs 均值 |

### 1.4 扩展后的 State 向量

```text
当前：State = (MN1, W1, D1)          → 3 维向量，16³ = 4096 种组合
扩展：State = (MN1, W1, D1, H1)      → 4 维向量，16⁴ = 65536 种组合
扩展：State = (MN1, W1, D1, H1, M15) → 5 维向量，16⁵ = 1048576 种组合
```

**过拟合风险**：维数越高，精确组合越稀疏。必须配套模糊 bit 聚合和最小样本门槛。

### 1.5 H1/M15 的定位：不替代，只增强

H1/M15 不替代现有三周期，而是作为**辅助维度**：

| 用途 | 如何使用 |
|------|----------|
| 入场时机精确化 | D1 信号触发后，观察 H1 是否也处于 E/F，确认短期动量 |
| 止损位辅助 | H1 SR 可作为更灵敏的止损参考 |
| 盘中监控 | M15 用于日内状态变化的实时观察 |
| 不参与主排序 | 主排序仍使用 MN1/W1/D1 的 ef_count |

### 1.6 数据存储扩展

```sql
-- Foundation DB 新增表
CREATE TABLE IF NOT EXISTS h1_state (
    stock_code    VARCHAR NOT NULL,
    date          VARCHAR NOT NULL,
    hour_ts       VARCHAR NOT NULL,  -- 小时级时间戳
    h1_state_hex  VARCHAR,
    h1_state_score INTEGER,
    h1_base       INTEGER,
    h1_trend_bit  INTEGER,
    h1_position_bit INTEGER,
    h1_volatility_bit INTEGER,
    observation_price DOUBLE,  -- 盘中最新价 or D1 close
    PRIMARY KEY (stock_code, date, hour_ts)
);
```

### 1.7 实施路径

```text
阶段 1：H1 数据接入
  - 从黑狼 API 下载小时线数据（已有 5 分钟线基础设施）
  - 实现 H1 K 线聚合（5 分钟 → 1 小时）
  - 实现 H1 SR 计算（复用 sr_calculator.py）

阶段 2：H1 State 计算
  - 扩展 p116_core.py 支持 H1 周期
  - 盘中用最新价，收盘后切换为 D1 close
  - 输出 H1 state 到 Foundation DB

阶段 3：策略信号整合
  - strategy_signal_daily 新增 h1_state_hex 字段
  - 提醒层可展示"H1 也处于 E/F，短期动量确认"
  - 不改变主排序逻辑

阶段 4：M15（可选）
  - 仅在 H1 验证有效后考虑
  - 用于盘中实时监控，不进入日频账本
```

---

## 2. 方向 B：新增资金流维度

### 2.1 背景

当前 State 底座的 4 个维度（base/trend/position/volatility）全部基于价格和成交量衍生指标。资金流（大单净流入、主力资金方向等）是独立的信息维度，不在现有编码中。

项目已有资金流研究结论（`docs/moneyflow_usage_research.md`）：资金流最稳的用法是作为 State 之后的证据层，不作为独立维度改写 State 公式。

### 2.2 两种接入方案

#### 方案 A：资金流作为第 5 位 bit（不推荐）

```text
score = base + trend_bit*4 + position_bit*2 + volatility_bit + moneyflow_bit
```

**不推荐原因**：
- 打破现有 0-15 编码空间，变为 0-31，所有下游筛选逻辑需重写
- E/F 定义失效（14/15 不再是最高状态）
- 资金流数据覆盖不完整（部分股票无数据），会产生大量 NULL
- 专利权利要求基于 4-bit 结构，扩展为 5-bit 需要重新申请

#### 方案 B：资金流作为独立证据层（推荐）

```text
State 底座（4-bit，不变）
  + 资金流证据层（独立评分，0-10）
  = 组合展示（State + 资金流标签）
```

**推荐原因**：
- State 底座契约不变，所有现有代码和文档不受影响
- 资金流数据缺失时不影响 State 计算
- 可以独立校准资金流权重，不与 State 耦合

### 2.3 资金流证据层设计

```python
# 新模块：scripts/state_calc/moneyflow_dimension.py

@dataclass
class MoneyflowEvidence:
    stock_code: str
    as_of_date: str
    # 核心指标
    net_inflow_1d: float | None      # 1 日大单净流入（万元）
    net_inflow_5d: float | None      # 5 日累计净流入
    consecutive_inflow_days: int | None  # 连续净流入天数
    # 评分
    moneyflow_score: float            # 0-10 综合评分
    moneyflow_label: str              # 强势流入/温和流入/中性/温和流出/强势流出
    # 与 State 的交互
    state_moneyflow_aligned: bool     # 资金流方向与 State 趋势是否一致
    divergence_flag: bool             # 价格创新高但资金不跟随
    # 元数据
    data_coverage: float              # 覆盖率 0-1
    confidence: float                 # 置信度 0-1
```

### 2.4 资金流评分公式

```text
moneyflow_score = clamp(
    0.35 × net_inflow_score
  + 0.25 × consecutive_score
  + 0.20 × divergence_adjustment
  + 0.20 × coverage_adjustment,
  0, 10
)
```

| 分项 | 计算方法 | 范围 |
|------|----------|------|
| net_inflow_score | 5 日累计净流入的百分位（近 60 日）× 10 | 0-10 |
| consecutive_score | min(连续净流入天数 / 5, 1.0) × 10 | 0-10 |
| divergence_adjustment | 价格创新高且资金净流出 → -3；价格回调且资金净流入 → +3 | -3 to +3 |
| coverage_adjustment | 覆盖率 < 50% 时扣减 2 分 | 0 or -2 |

### 2.5 资金流标签

```text
moneyflow_score >= 7.5 → "强势流入"
moneyflow_score >= 5.5 → "温和流入"
moneyflow_score >= 3.5 → "中性"
moneyflow_score >= 1.5 → "温和流出"
moneyflow_score <  1.5 → "强势流出"
```

### 2.6 与 State 底座的组合展示

```text
展示格式：State 组合 + 资金流标签
示例：E/F/F + 强势流入 → "三周期共振 + 资金面支持"
示例：E/F/F + 强势流出 → "三周期共振但资金分歧（背离警告）"
```

### 2.7 资金流在策略适配中的权重

基于 `docs/moneyflow_usage_research.md` 的结论：

| 场景 | 资金流作用 | 权重 |
|------|-----------|------|
| 三周期 E/F 已成立 + 资金同向 | 提高观察优先级 | +10 分适配度加成 |
| 三周期 E/F 已成立 + 资金反向 | 标记为背离复核 | -15 分适配度折扣 |
| State 不明确 | 资金流仅展示，不影响排序 | 0 |
| 资金流数据缺失 | 标注为数据缺口 | 0，不默认为负面 |

---

## 3. 向后兼容保证

### 3.1 不可变契约

以下内容在任何扩展中不可修改：

```text
1. score = base + trend_bit*4 + position_bit*2 + volatility_bit  → 4-bit 公式不变
2. D1 视角：所有周期用同一个价格数据点比较各自 SR  → 天条不变
3. E = 14, F = 15  → 最高状态定义不变
4. 位置优先符号裁决  → 规则不变
5. 确认延迟 + 前向填充  → 防未来数据机制不变
```

### 3.2 新增内容的命名规范

```text
H1/M15 字段前缀：h1_ / m15_
资金流字段前缀：mf_ / moneyflow_
扩展 State 字段：state_extended_hex（含新周期）
原有字段：state_hex（保持不变，下游无需修改）
```

### 3.3 下游影响评估

| 下游模块 | H1 扩展影响 | 资金流扩展影响 |
|----------|------------|---------------|
| strategy_signal_daily | 新增 h1_state_hex 字段（可选） | 新增 mf_score 字段（可选） |
| strategy_fit_observer | 不影响 | 可选记录 mf_label |
| strategy_reminder_brief | 可选展示 H1 动量确认 | 可选展示资金流标签 |
| macro_chain_prior | 不影响 | 不影响 |
| 专利 | 不影响（新增独立模块） | 不影响（不改 4-bit 公式） |

---

## 附录：实施优先级

| 优先级 | 扩展项 | 工作量 | 价值 |
|--------|--------|--------|------|
| 1 | 资金流证据层（方案 B） | 中 | 高 — 直接提升策略适配度质量 |
| 2 | H1 State 计算 | 高 | 中 — 入场时机精确化 |
| 3 | M15 盘中监控 | 高 | 低 — 仅日内参考，不进入日频账本 |
