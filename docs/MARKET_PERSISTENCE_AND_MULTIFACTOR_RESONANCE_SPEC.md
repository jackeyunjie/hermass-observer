# Market Persistence And Multifactor Resonance Spec

版本：v1.0  
日期：2026-05-28  
范围：A 股 External Research Response / 市场与行业解释层

---

## 1. 目标

本规范回答两个问题：

1. 当前市场状态已经持续多久了
2. 哪些“多因素共振”值得被前台点出来

这不是恢复“8 大章节长报告”，而是在现有 research lane 中补更高价值的解释框架。

---

## 2. 基本原则

### 2.1 市场持续度是结构化指标，不是主观判断

应优先来自：

- `outputs/market_phase/market_phase_history.json`
- `outputs/p116_daily_all_three_ef/`
- `outputs/state_cache/`

### 2.2 多因素共振不是“堆更多信号”

点出来的前提是：

- 对当前行业/个股有解释价值
- 有结构化证据支持
- 能说明“为什么值得关注”

### 2.3 行业驱动和事件驱动分层处理

- 行业驱动 → `industry_state`
- 事件驱动 → `public_news_digest`
- 不回退到旧长报告模式

---

## 3. 市场状态持续度指标

### 3.1 推荐核心字段

| 字段 | 含义 | 数据源 |
|------|------|--------|
| `market_phase` | 当前阶段 | `market_phase_latest.json` |
| `market_phase_duration_days` | 当前阶段已持续天数 | `market_phase_history.json` |
| `all_three_ef_pool_size` | 全三 E/F 池规模 | `p116_all_three_ef_{date}.json` |
| `all_three_ef_pool_change_5d` | 近 5 日池规模变化 | 同上 |
| `release_density_5d` | 近 5 日收缩后释放密度 | `state_transition_{date}.json` |
| `industry_dispersion` | 行业离散度 | `market_assets_state` |

### 3.2 推荐前台话术

```text
市场阶段：progression
持续时间：已持续 11 个交易日
状态特征：全三 E/F 池规模平稳，趋势延续但未见明显风险释放
```

不建议只说：

- “市场很好”
- “市场很强”

而应尽量包含：

- 阶段名称
- 持续时间
- 一个结构化原因

**前台边界**：

- `release_density_5d`
- `industry_dispersion`

这类指标只用于内部判定，不直接把指标名暴露给用户。
前台只展示：

- 阶段名称
- 持续时间
- 结构化原因

---

## 4. 多因素共振框架

### 4.1 Phase 1 建议的 3 个维度

| 维度 | 字段示例 | 位置 |
|------|----------|------|
| State 共振 | `ef_count`, `state_combo` | `state_core` |
| 行业共振 | `sector_resonance`, `sector_resonance_count`, `etf_state_hex` | `industry_state` |
| 事件驱动 | `public_news_digest.digest_items` | `enrichment` |

### 4.2 为什么 Phase 1 先收窄到 3 维

因为它们刚好覆盖：

- 趋势结构
- 行业合力
- 外部催化

已经足够支撑“为什么值得看”，而且都具备明确的数据落点。

### 4.3 暂不前台展示的维度

以下维度保留为后续候选，不进入 Phase 1 前台共振框架：

| 维度 | 原因 |
|------|------|
| 龙头属性 | 当前没有稳定生产级字段，容易变成模型自由发挥 |
| 盈利共振 | 字段已开始具备，但前台规则和行业差异还需再收紧 |

---

## 5. 行业共振规则

### 5.1 当前已有

已有字段：

- `industry_state.etf_state_hex`
- `industry_state.etf_ef_count`
- `industry_state.sector_resonance`
- `industry_state.sector_resonance_count`

### 5.2 推荐前台条件

当满足以下任一条件时，值得点出：

1. `sector_resonance = true`
2. `etf_ef_count >= 2`
3. `prosperity_score >= 7`

推荐展示：

```text
行业共振：已确认（60 家）
原因：行业 ETF 已进入 E/F 支撑区，板块内部存在同步强化信号
```

---

## 6. 龙头属性规则（后续候选，不进入 Phase 1 前台）

### 6.1 当前现实

当前系统对“龙头”没有稳定生产级字段，不能让模型自由判断。

### 6.2 建议的渐进式实现

Phase 1：

- 只展示“peer 是否覆盖”
- 只提示“当前行业对标是否充分”

Phase 2：

- 增加 `industry_rank_bucket`
- 增加 `market_cap_rank_in_sw_l3`
- 增加 `signal_strength_percentile_in_industry`

### 6.3 前台边界

在 Phase 1，不建议直接说：

- “这是行业龙头”

只建议说：

- “在当前证据层里已具备可比公司/竞争对手覆盖”
- “个股处于行业核心对标池”

---

## 7. 盈利大幅增长规则（后续候选，不进入 Phase 1 共振展示）

### 7.1 推荐规则

仅当以下条件满足时，才值得前台点出：

1. `revenue_yoy_same_quarter > 20%`
2. 或 `net_profit_yoy_same_quarter > 30%`
3. 且对应指标对该行业确实重要

### 7.2 为什么要加行业相关性

因为“利润大幅增长”并不总是同等重要：

- 周期行业：可能只是价格弹性
- 银行：利润同比和现金流口径解释逻辑不同
- 轻资产成长股：利润弹性更值得关注

所以应采用：

```text
增长发生了
→ 对这个行业是否关键
→ 为什么关键
```

而不是只看到增速就推给用户。

---

## 8. 事件驱动规则

### 8.1 位置

事件驱动应来自：

- `public_news_digest`

而不是回到旧的“股价催化剂”长段落。

### 8.2 推荐前台条件

当最近 30 天内存在：

- `earnings`
- `policy`
- `capital`
- `tech`

且 `impact_hint != neutral` 时，可前台点出。

示例：

```text
事件驱动：近 30 天内存在政策/业绩相关外部催化
说明：该因素属于辅助解释，不替代本地证据层
```

---

## 9. 推荐输出形态

### 9.1 Deep Card

建议加入一段：

```text
多因素共振：
- State 共振：ef=3，三周期结构已确认
- 行业共振：板块共振确认 60 家
- 事件驱动：当前未接入真实外部摘要 / 已有事件补充
```

### 9.2 Evidence Card

建议更适合做结构化说明：

```text
多因素共振说明层：
- market_phase 持续 11 个交易日
- industry resonance = true
- event driver = not_enabled
```

---

## 10. 与 8 大板块的关系

结论：

- 不恢复原 `8` 大章节主线
- 只继续拆最有价值的行业侧资产

推荐优先顺序：

1. `191966` 短期增速与驱动因素
2. `138087` 政策环境与技术变革
3. `130160` 行业周期与整体判断

原因：

- 这三块最直接增强当前 research lane 的解释力
- 不会把系统拉回长篇投研报告模式

---

## 11. 与 Claude 讨论的窄范围

如果需要和 Claude 讨论，建议只讨论：

1. `State` 展示别名字典是否自然
2. 多因素共振的 5 维框架是否足够
3. 市场状态持续度前台最小展示字段是否过多

不建议和 Claude 讨论：

- State 底层编码
- 恢复 8 大章节
- 重新设计一套平行的行业/事件框架
