# 产业链景气度量化模型

版本：v1.0
日期：2026-05-23
状态：设计稿
关联规范：`docs/industry_chain_dynamics_spec.md`（Schema 定义）

---

## 概述

本文档基于 `industry_chain_dynamics_spec.md` 定义的三张表 Schema，设计具体的景气度评分公式、权重体系和更新机制。景气度评分是 `industry_position.prosperity_score` 字段的计算依据。

---

## 1. 景气度评分总公式

```text
prosperity_score = clamp(
    W_indicator  × S_indicator
  + W_event      × S_event
  + W_market     × S_market
  + W_policy     × S_policy,
  0, 10
)
```

| 分项 | 权重 | 数据来源 | 说明 |
|------|------|----------|------|
| S_indicator | 0.40 | chain_dynamics 表 | 产业链环节级量化指标 |
| S_event | 0.20 | chain_event_cross 表 | 近期事件影响 |
| S_market | 0.25 | market_assets_state | 行业 ETF State 和收益 |
| S_policy | 0.15 | chain_event_cross 中 policy 类事件 | 政策环境 |

权重总和 = 1.00。

---

## 2. 指标分项评分（S_indicator）

### 2.1 计算逻辑

从 `chain_dynamics` 表中读取该行业所属产业链的所有环节指标：

```text
S_indicator = Σ(indicator_contribution) / N_indicators
```

每个指标的贡献：

```text
indicator_contribution = trend_score + level_score + percentile_score
```

### 2.2 趋势得分（trend_score）

| chain_dynamics.trend | trend_score | 含义 |
|---------------------|-------------|------|
| "up" | 3.0 | 指标上行 |
| "turning_up" | 4.0 | 拐点向上（加分最多） |
| "flat" | 2.0 | 持平 |
| "turning_down" | 1.0 | 拐点向下 |
| "down" | 0.5 | 指标下行 |
| NULL | 2.0 | 数据缺失，保持中性 |

设计理由：拐点（turning_up/turning_down）比方向本身更有信息量。

### 2.3 水平得分（level_score）

基于 `chain_dynamics.percentile_1y`（近 1 年历史分位）：

```text
IF percentile_1y >= 80: level_score = 4.0  （高位）
IF percentile_1y >= 60: level_score = 3.0  （偏高）
IF percentile_1y >= 40: level_score = 2.0  （中位）
IF percentile_1y >= 20: level_score = 1.0  （偏低）
IF percentile_1y <  20: level_score = 0.5  （低位）
IF percentile_1y IS NULL: level_score = 2.0（缺失中性）
```

注意：高位不一定是好（如库存高位是负面），需结合指标类别调整（见 2.5）。

### 2.4 分位变动得分（percentile_score）

比较当前分位与上期分位的变动：

```text
delta = percentile_1y - prev_percentile_1y（需额外存储上期分位）

IF delta >  10: percentile_score = 3.0（大幅改善）
IF delta >   0: percentile_score = 2.5（边际改善）
IF delta ==  0: percentile_score = 2.0（不变）
IF delta > -10: percentile_score = 1.5（边际恶化）
IF delta <= -10: percentile_score = 1.0（大幅恶化）
```

### 2.5 指标类别调整

不同类别的指标，"好"的方向不同：

| 指标类别 | 价格上行 | 库存高位 | 开工率高位 | 需求上行 |
|----------|---------|---------|-----------|---------|
| 价格指标 | 正面 (+0) | — | — | — |
| 库存指标 | — | 负面 (-1.5) | — | — |
| 产能指标 | — | — | 正面 (+0) | — |
| 需求指标 | — | — | — | 正面 (+0) |

调整方法：对库存类指标，将 level_score 反转：

```text
IF indicator_category == "库存":
    level_score = 4.5 - level_score  （高位变低位，低位变高位）
```

### 2.6 S_indicator 汇总

```text
S_indicator = clamp(Σ(trend_score + level_score + percentile_score) / (N × 9.0) × 10, 0, 10)
```

其中 9.0 是单个指标三项得分的最大值之和（4.0 + 4.0 + 3.0 = 11，但常态分布在 0-9）。

---

## 3. 事件分项评分（S_event）

### 3.1 计算逻辑

从 `chain_event_cross` 表中读取该行业近 30 天的事件：

```text
S_event = 5.0 + Σ(event_impact) / max(N_events, 1) × event_decay
```

### 3.2 单个事件影响

```text
event_impact = direction_factor × strength_normalized × recency_decay
```

| chain_event_cross.impact_direction | direction_factor |
|-----------------------------------|-----------------|
| "positive" | +1.0 |
| "negative" | -1.0 |
| "neutral" | 0.0 |
| "mixed" | +0.3（偏正面，因为市场通常对混合信息偏乐观） |

```text
strength_normalized = (impact_strength - 3) / 2  → 范围 [-1, 1]
```

### 3.3 时间衰减

```text
recency_decay = max(0.2, 1.0 - days_since_event / 30)
```

事件越近影响越大，30 天前的事件衰减至 20% 权重。

### 3.4 事件类型权重

| event_type | 类型权重 | 理由 |
|------------|---------|------|
| policy | 1.2 | 政策影响通常持久且确定 |
| supply_demand | 1.0 | 供需基本面 |
| tech | 0.9 | 技术突破需要时间验证 |
| earnings | 0.8 | 业绩信号滞后 |
| overseas | 0.7 | 海外事件传导有不确定性 |
| capital | 0.6 | 资本运作信号不确定性高 |

```text
event_impact = direction_factor × strength_normalized × recency_decay × type_weight
```

### 3.5 S_event 汇总

```text
S_event = clamp(5.0 + Σ(event_impact) × 2.0, 0, 10)
```

无事件时 S_event = 5.0（中性），正面事件推高，负面事件拉低。

---

## 4. 市场分项评分（S_market）

### 4.1 计算逻辑

基于行业 ETF 的 State 和近期收益：

```text
S_market = etf_state_score + etf_return_score
```

### 4.2 ETF State 得分

| 条件 | etf_state_score |
|------|----------------|
| ETF ef_count = 3（MN1/W1/D1 全 E/F） | 6.0 |
| ETF ef_count = 2 | 5.0 |
| ETF ef_count = 1 | 3.5 |
| ETF ef_count = 0 | 2.0 |
| 无 ETF 覆盖 | 3.0（中性偏低） |

### 4.3 ETF 近期收益得分

```text
etf_return_20d = ETF 近 20 日收益率

IF etf_return_20d >  5%: etf_return_score = 4.0
IF etf_return_20d >  2%: etf_return_score = 3.5
IF etf_return_20d >  0%: etf_return_score = 3.0
IF etf_return_20d > -2%: etf_return_score = 2.5
IF etf_return_20d > -5%: etf_return_score = 2.0
IF etf_return_20d <= -5%: etf_return_score = 1.0
```

### 4.4 S_market 汇总

```text
S_market = clamp(etf_state_score × 0.6 + etf_return_score × 0.4, 0, 10)
```

ETF State 权重高于收益，因为 State 是结构性信号，收益是结果。

---

## 5. 政策分项评分（S_policy）

### 5.1 计算逻辑

从 `chain_event_cross` 中筛选 `event_type = "policy"` 的事件：

```text
S_policy = 5.0 + policy_net_signal × 2.5
```

### 5.2 政策净信号

```text
policy_net_signal = Σ(policy_event_impact) / max(N_policy_events, 1)
```

其中每个政策事件的影响：

```text
policy_event_impact = direction_factor × (impact_strength / 5.0) × recency_decay
```

### 5.3 特殊政策信号

| 政策类型 | 正面方向 | 负面方向 |
|----------|---------|---------|
| 补贴政策 | 补贴标准提高/范围扩大 | 补贴退坡/取消 |
| 产能管控 | 限制新增产能（利好存量） | 放开产能管控（利空存量） |
| 行业准入 | 提高准入门槛 | 降低准入门槛 |
| 环保政策 | 环保限产（供给收缩） | 放松环保（供给增加） |
| 税收调整 | 减税降费 | 加税 |

### 5.4 S_policy 汇总

```text
S_policy = clamp(5.0 + policy_net_signal × 2.5, 0, 10)
```

无政策事件时 S_policy = 5.0（中性）。

---

## 6. 产业链位置差异化权重

上中下游行业在各分项上的权重不同：

| 分项 | 上游行业 | 中游行业 | 下游行业 | 综合/配套行业 |
|------|---------|---------|---------|-------------|
| W_indicator | 0.45 | 0.40 | 0.35 | 0.35 |
| W_event | 0.15 | 0.20 | 0.25 | 0.20 |
| W_market | 0.25 | 0.25 | 0.25 | 0.30 |
| W_policy | 0.15 | 0.15 | 0.15 | 0.15 |

设计理由：上游行业更依赖量化指标（价格/库存），下游行业更受事件驱动（消费信号/需求变化）。

---

## 7. 景气度变化判定

### 7.1 prosperity_change 计算

```text
delta = prosperity_score_current - prosperity_score_previous

IF delta >  0.5: prosperity_change = "improving"
IF delta < -0.5: prosperity_change = "deteriorating"
ELSE:            prosperity_change = "stable"
```

### 7.2 rating 映射

```text
prosperity_score >= 7.0 → rating = "high"
prosperity_score >= 4.5 → rating = "medium"
prosperity_score <  4.5 → rating = "low"
```

### 7.3 rating_change 计算

```text
rating_rank = {"high": 3, "medium": 2, "low": 1, "unknown": 0}

IF rating_rank(current) > rating_rank(previous):
    rating_change = "upgraded"
ELIF rating_rank(current) < rating_rank(previous):
    rating_change = "downgraded"
ELSE:
    rating_change = "unchanged"
```

---

## 8. 置信度

```text
confidence = min(1.0, indicator_coverage × event_coverage × time_freshness)
```

| 因子 | 计算方法 | 范围 |
|------|----------|------|
| indicator_coverage | 该行业 chain_dynamics 有效指标数 / 理论最大指标数 | 0.2-1.0 |
| event_coverage | 1.0（事件可为 0） | 1.0 |
| time_freshness | max(0.3, 1.0 - days_since_latest_data / 30) | 0.3-1.0 |

---

## 9. 更新频率与触发条件

| 更新类型 | 频率 | 触发条件 |
|----------|------|----------|
| 指标更新 | 日频 | chain_dynamics 有新数据写入时 |
| 事件更新 | 实时 | chain_event_cross 有新事件入库时 |
| 市场更新 | 日频 | market_assets_state 更新后 |
| 景气度汇总 | 日频 | 上述任一更新后重算 |

---

## 附录：示例计算

### AI 算力链（假设数据）

```text
S_indicator:
  上游芯片均价 trend=up, percentile=85 → 3.0+4.0+3.0=10.0
  中游服务器开工率 trend=flat, percentile=70 → 2.0+3.0+2.5=7.5
  下游数据中心需求 trend=up, percentile=65 → 3.0+3.0+2.5=8.5
  S_indicator = (10.0+7.5+8.5) / (3×9.0) × 10 = 9.63

S_event:
  近期政策正面事件 1 条（strength=4, 5天前）→ +1.0×0.5×0.83×1.2 = +0.50
  技术突破事件 1 条（strength=3, 10天前）→ +1.0×0.0×0.67×0.9 = 0.00
  S_event = 5.0 + 0.50 × 2.0 = 6.0

S_market:
  ETF ef_count=2 → etf_state_score=5.0
  ETF 20d return=+8% → etf_return_score=4.0
  S_market = 5.0×0.6 + 4.0×0.4 = 4.6

S_policy:
  补贴政策正面（strength=4, 5天前）→ +1.0×0.8×0.83 = +0.66
  S_policy = 5.0 + 0.66 × 2.5 = 6.65

prosperity_score = 0.45×9.63 + 0.15×6.0 + 0.25×4.6 + 0.15×6.65
                 = 4.33 + 0.90 + 1.15 + 1.00
                 = 7.38 → rating = "high"
```
