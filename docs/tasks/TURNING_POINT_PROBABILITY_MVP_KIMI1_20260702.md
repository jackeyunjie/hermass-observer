# 多周期转折概率 MVP 方案

> 任务：KIMI1 任务：多周期转折概率 MVP 方案  
> 日期：2026-07-02  
> 作者：KIMI1  
> 版本：MVP 设计稿（不写代码、不改库、不改前端）

---

## 1. MVP 目标

在不改变现有 Hermass 主线（State Cube + MOE 多 Agent 辩论 + Ledger）的前提下，引入一个**可解释的 Empirical Bayesian 转折概率层**，输出：

- **转强概率**（prob_turn_up）
- **转弱概率**（prob_turn_down）
- **延续概率**（prob_continue）
- **假突破概率**（prob_false_breakout）
- **置信度**（confidence）
- **关键证据**（evidence_items）

覆盖 4 个时间窗：3D / 3W / 3M / 6M。系统**只输出概率和证据**，不输出交易动作，不替代现有策略信号。

---

## 2. 数据源

| 数据层 | 路径 / 表 | 用途 |
|--------|-----------|------|
| Foundation | `d1_perspective_state` | `state_score`、`state_magnitude`、`state_hex`、EF/A/B/0、SR 关键位、ADX/ATR/BB |
| Foundation | `timeframe_bars`（D1） | 未来收益计算、价格突破确认 |
| Foundation | `timeframe_indicators` | D1/W1/MN1 的 ADX14、BB width、ATR14 等指标 |
| State Cube | `outputs/state_cube/state_cube.duckdb` | 多周期全景：MN1/W1/D1 state、MA/BB/ADX/ATR、future_r5/r20 |
| State Timeline | `outputs/state_timeline/state_timeline_daily_YYYYMMDD.duckdb` | 状态转移标签、transition_label、ef_pattern/ab_pattern/zero_pattern |
| Fundamental | `outputs/fundamental/fundamental_evidence.duckdb` | 股票名称、申万一级行业（可选分层） |
| Market State | `outputs/market_assets_state/market_assets_state_YYYYMMDD.json` | 市场环境分层（指数趋势、EF 数量占比） |

MVP 不新增外部数据，全部基于现有库表可计算。

---

## 3. 时间窗定义

| 名称 | 交易日 | 近似自然时间 | 定位 |
|------|--------|--------------|------|
| **3D** | 3 个交易日 | 约半个自然周 | 捕捉短线状态脉冲、日内/隔日假突破 |
| **3W** | 15 个交易日 | 约 3 周 | 捕捉短期 regime shift，对应现有 `future_r20` 附近 |
| **3M** | 66 个交易日 | 约 3 个月 | 捕捉季度级趋势转折 |
| **6M** | 126 个交易日 | 约 6 个月 | 捕捉结构性/周期级转折 |

**为什么这样定：**

1. 中国市场一年约 252 个交易日，按 `21 日/月、5 日/周` 取整。
2. 3D 足够短，用于识别“刚刚启动/刚刚破位”的噪声；3W 与现有 State Cube `future_r20` 对齐，便于直接复用 Ledger 回填；3M/6M 分别对应季报窗口和中期结构变化。
3. 4 个窗格覆盖了“盘中/短期/中期/长期”四个决策尺度，与首页观察台的“多周期”叙事一致。

> 实际实现时，可在 State Cube 中通过 `LEAD(close, N)` 动态计算 `future_r15 / future_r60 / future_r120`，无需每天重跑 Foundation。

---

## 4. 转折事件定义

所有事件均基于 **MN1 / W1 / D1 的 state_score、state_magnitude、EF/A/B/0 标志、关键位突破和状态连续变化**。

### 4.1 核心状态语义（复用现有定义）

- **EF**：`state_score ∈ {14, 15}`，正向极值状态。
- **A/B**：`state_magnitude ∈ {10, 11}`，边界活跃区。
- **0**：`state_magnitude = 0`，无方向/无结构。
- **state_score 正负**：正 = 偏多结构，负 = 偏空结构。
- **关键位**：`d1_sr_support / d1_sr_resistance` 等 SR 上下界。

### 4.2 事件类别

| 事件 | 定义 | 证据来源 |
|------|------|----------|
| **转强早期** | 任一主要周期（W1/D1）state_score 由负/低正（≤6）上行到 7–11，或首次出现正向 A/B；EF 尚未出现；ADX 开始抬升；价格站上 D1 中轨/支撑位。 | W1/D1 score 变化、AB 标志、ADX slope、BB position |
| **确认转强** | 至少两个周期 state_score ≥ 12 且为正，或 `ef_count ≥ 2`；价格突破阻力位；ADX ≥ 25 且 +DI > -DI。 | EF pattern、+DI/-DI、关键位突破 |
| **强势延续** | 多周期 state_score 保持高位正数且未出现显著回落；EF pattern 稳定；波动率未异常放大。 | 连续 N 日 score 同号、BB width、ATR ratio |
| **转弱预警** | 正向 score 从高位回落至 ≤10，或出现负向 A/B；ADX slope 转负；价格跌破 D1 中轨/支撑位但未创新低。 | score 回落、AB 负向、ADX slope、BB 中轨跌破 |
| **确认转弱** | 至少两个周期 state_score 为负且 |score| ≥ 12，或 `ef_count ≥ 2` 为负；价格跌破支撑位；ADX ≥ 25 且 -DI > +DI。 | 负 EF pattern、关键位跌破、-DI 占优 |
| **噪声变化** | state_hex 变化但 magnitude 低（≤6）、ADX < 20、BB width neutral、无关键位突破；未来收益方向不稳定。 | magnitude、ADX、BB width、突破标志 |

> 这些事件是**分类标签**，用于历史统计形成先验；对应当前观测时，输出的是“属于哪一类事件”的概率，而不是直接给事件定性。

---

## 5. 概率字段契约

### 5.1 任务建议字段评估

任务建议字段：

```text
stock_code
stock_name
state_date
window
turning_type
prob_turn_up
prob_turn_down
prob_continue
prob_false_breakout
confidence
evidence_score
evidence_items
risk_flags
source_state_summary
```

**评估结论：基础消费足够，但缺少可回测/可审计的操作字段。**

建议保留上述全部字段，并追加以下字段以支持解释、回测和校准：

| 追加字段 | 类型 | 说明 |
|----------|------|------|
| `bucket_sample_size` | INT | 当前指纹桶历史样本数 |
| `prior_weight` | DOUBLE | 收缩权重（样本越少越偏向全局先验） |
| `market_regime` | VARCHAR | 市场环境标签，如 `strong_trend / range / oversold / overheated` |
| `industry_l1` | VARCHAR | 申万一级行业（可选） |
| `future_return_n` | DOUBLE | 未来 N 日收益（用于回填验证） |
| `outcome_label` | VARCHAR | 事后回填的 `{turn_up, turn_down, continue, false_breakout}` |
| `model_version` | VARCHAR | 模型版本，便于 A/B 比较 |
| `updated_at` | TIMESTAMP | 生成时间 |

### 5.2 最终字段契约

```text
stock_code            VARCHAR
stock_name            VARCHAR
state_date            DATE
window                VARCHAR     -- 3D/3W/3M/6M
turning_type          VARCHAR     -- 当前最可能事件，如 early_turn_up / confirmed_turn_up / ...
prob_turn_up          DOUBLE      -- 转强概率
prob_turn_down        DOUBLE      -- 转弱概率
prob_continue         DOUBLE      -- 延续概率
prob_false_breakout   DOUBLE      -- 假突破概率
confidence            DOUBLE      -- 0-1
evidence_score        DOUBLE      -- 证据强度（log-odds 量级）
evidence_items        JSON        -- 证据列表
risk_flags            JSON        -- 风险提示
source_state_summary  JSON        -- 状态摘要
bucket_sample_size    INT
prior_weight          DOUBLE
market_regime         VARCHAR
industry_l1           VARCHAR
future_return_n       DOUBLE
outcome_label         VARCHAR
model_version         VARCHAR
updated_at            TIMESTAMP
```

约束：

- `prob_turn_up + prob_turn_down + prob_continue + prob_false_breakout = 1.0`（容差 ±0.01）。
- `confidence ∈ [0, 1]`，样本不足时强制 ≤0.5。
- `turning_type` 取四个概率中的 argmax，仅在 `confidence ≥ 0.3` 时显示；否则为 `uncertain`。

---

## 6. Empirical Bayesian 计算方案

### 6.1 总体思路

```text
当前状态指纹 f
  -> 历史同指纹样本中各 outcome 频率（经验先验）
  -> 用当前多周期证据做似然修正
  -> 后验概率四元组
  -> 置信度、证据、风险标记
```

### 6.2 步骤 1：构造状态指纹

从 State Cube / State Timeline 提取一个**粗粒度指纹向量**，避免维度爆炸：

| 维度 | 取值 | 说明 |
|------|------|------|
| `d1_bucket` | `strong_pos / pos / neutral / neg / strong_neg / zero` | 基于 D1 state_score 分桶 |
| `w1_bucket` | 同上 | W1 分桶 |
| `mn1_bucket` | 同上 | MN1 分桶 |
| `ef_count_bucket` | `0 / 1 / 2 / 3` | 现有 ef_count |
| `ab_count_bucket` | `0 / 1 / 2 / 3` | 现有 ab_count |
| `zero_count_bucket` | `0 / 1 / 2 / 3` | 现有 zero_count |
| `bb_width_regime` | `squeeze / neutral / expanding` | D1 BB20 width |
| `adx_regime` | `weak(<20) / building(20-35) / strong(≥35)` | D1 ADX14 |
| `breakout_flag` | `none / up_break / down_break / false_up / false_down` | 基于 D1 close 与 SR/BB 关系 |
| `transition_flag` | `same / improve / worsen / noise` | 与上一日 triplet 比较 |

指纹维度控制在 10^5–10^6 组合以内，且可进一步做分层回退。

### 6.3 步骤 2：定义 outcome Y

对每个历史 (stock_code, state_date, window)，用未来收益 `future_return_N` 和状态变化给 outcome 打标：

| outcome | 条件（可同时加入状态变化约束） |
|---------|-------------------------------|
| `turn_up` | `future_return_N > +阈值`（如 3D>2%, 3W>5%, 3M>10%, 6M>20%）且期间正向状态持续增强 |
| `turn_down` | `future_return_N < -阈值` 且负向状态持续增强 |
| `continue` | `|future_return_N| ≤ 阈值` 且主要周期方向与当前一致 |
| `false_breakout` | 短期（3D 内）出现向上突破但 `future_return_N` 最终为负，或向下突破后最终为正 |

阈值按波动率 ATR 或收益率分位数校准，不固定。

### 6.4 步骤 3：经验先验

对指纹 `f`，统计历史中 `count(Y | f)`：

```text
P_prior(Y | f) = (count(Y|f) + α_Y) / (N_f + Σα_Y)
```

- `α_Y = 1`（Laplace 平滑），或 `α_Y = α0 * P_global(Y)`（经验 Dirichlet 先验）。
- `N_f` 为指纹 `f` 的历史样本数。

### 6.5 步骤 4：证据似然修正

当前观测到若干证据 `e_i`（如“D1 站上阻力位”“W1 ADX slope 转正”“BB width 从 squeeze 释放”）。对每条证据：

```text
LR_i(Y) = P(e_i | Y) / P(e_i)
```

从历史同 outcome 样本中统计 `P(e_i | Y)`。为避免过度拟合，只使用 **5–8 条强证据**，且每条证据的权重用信息增益预先筛选。

后验（log-odds 形式）：

```text
log P_post(Y | f, E) ∝ log P_prior(Y|f) + Σ_i log LR_i(Y)
```

然后 softmax 归一化为概率。

### 6.6 步骤 5：置信度

```text
effective_n = N_f * evidence_bonus
entropy = -Σ p_i log_4(p_i)   -- 以 4 个 outcome 为底，范围 [0,1]
confidence = min(1, sqrt(effective_n / n_target)) * (1 - entropy)
```

- `n_target` 建议 100（每个指纹桶）。
- 如果 `N_f < n_min`（如 30），`confidence` 上限 0.5，并标记 `low_sample`。

---

## 7. 样本不足和置信度处理

### 7.1 分桶粗化回退

当指纹桶样本不足时，按以下顺序回退：

1. **指纹维度回退**：去掉 `industry_l1` → 去掉 `transition_flag` → 去掉 `bb_width_regime` → 只用 `(d1_bucket, w1_bucket, mn1_bucket, ef_count_bucket)`。
2. **市场环境回退**：如果分层市场环境下样本不足，回退到全市场。
3. **全局先验**：如果仍不足，返回全局先验 `P_global(Y)`，confidence 强制 0.2。

### 7.2 收缩估计

```text
w = N_f / (N_f + N_prior)
P_final(Y) = w * P_empirical(Y|f) + (1 - w) * P_global(Y)
```

- `N_prior` 建议 50（相当于需要 50 个样本才能让经验估计占一半权重）。
- 这样即使指纹桶只有 10 个样本，也不会出现极端 0/1 概率。

### 7.3 置信度阈值建议

| confidence | 前端展示 | 含义 |
|------------|----------|------|
| ≥ 0.7 | 高置信 | 可直接进入观察池 |
| 0.4–0.7 | 中置信 | 需结合 Agent 辩论二次确认 |
| < 0.4 | 低置信 | 仅作为背景信息，不做重点展示 |

---

## 8. 可选分层：行业 / 市场环境

MVP 中把分层做成**可选开关**，默认关闭，避免样本稀疏：

- **行业分层**：使用 `fund.ifind_industry_chain_profile.sw_l1`。只在行业样本 ≥ 500 时启用。
- **市场环境分层**：基于当日 `market_assets_state` 的指数趋势和全市场 EF 数量占比，划分为：
  - `strong_bull`
  - `trend_bull`
  - `range`
  - `trend_bear`
  - `oversold_bounce`

当某分层样本不足时，自动回退到上一层。分层结果写入 `market_regime` 字段，用于后续复盘和阈值校准。

---

## 9. API / 表结构建议

### 9.1 输出产物

1. **DuckDB 主表**：
   - 路径：`outputs/turning_point_probability/turning_point_probability_YYYYMMDD.duckdb`
   - 表名：`turning_point_probability`
   - 主键：`(stock_code, state_date, window, model_version)`

2. **最新快照 JSON**：
   - 路径：`outputs/turning_point_probability/turning_point_probability_latest.json`
   - 包含每个窗口的 Top 50 标的和市场级聚合。

3. **回测 Ledger 表**（可复用现有 `decision_observation.duckdb`）：
   - `hypothesis_id = 'TURNING_POINT_PROBABILITY_MVP'`
   - 字段：`observation_id, stock_code, state_date, window, predicted_probabilities, future_return_n, outcome_label, review_status`

### 9.2 索引

```sql
CREATE UNIQUE INDEX idx_tpp_pk ON turning_point_probability(stock_code, state_date, window, model_version);
CREATE INDEX idx_tpp_date ON turning_point_probability(state_date);
CREATE INDEX idx_tpp_window_type ON turning_point_probability(window, turning_type);
CREATE INDEX idx_tpp_confidence ON turning_point_probability(confidence) WHERE confidence >= 0.4;
```

### 9.3 API 接口建议

```text
GET /api/turning-point-probability?stock_code=688107.SH&window=3W&date=2026-07-02
POST /api/turning-point-probability/batch
GET /api/turning-point-probability/market-summary?window=3W&date=2026-07-02
GET /api/turning-point-probability/top?window=3W&turning_type=turn_up&limit=20
```

- 单只查询返回该标的 4 个窗口的概率。
- 市场摘要返回全市场 `turn_up / turn_down / continue / false_breakout` 的分布、各窗口的 Top 5。
- Top 接口用于首页观察台的“重点观察”卡片。

---

## 10. 首页消费方式

将转折概率作为首页观察台的**新增信息面板**，不替代现有 State Cube / Agent 辩论面板。

### 10.1 市场级卡片

- **4 个时间窗横排**：每个窗格显示当前全市场 `turn_up / turn_down / continue / false_breakout` 的占比条。
- **最高置信事件**：高亮当前 market_regime 下置信度最高的事件类型。
- **风险提示**：当 `false_breakout` 占比 > 25% 或 `confidence < 0.4` 时显示黄色/红色警告。

### 10.2 个股级消费

- 在**观察候选池**的每行追加一列“转折概率”：显示 `turning_type` + `confidence`。
- 点击后弹出详情面板，展示：
  - 四个概率的堆叠条
  - `evidence_items` 列表
  - `risk_flags`
  - `source_state_summary`（triplet + EF/AB/0 pattern）

### 10.3 与现有 Agent 辩论的衔接

新增一个 **“概率 Agent”** 作为第 7 个 Agent（或替换边界 Agent 的部分输入）：

- 读取 Empirical Bayesian 后验概率作为输入证据。
- 在 debate 中专门负责“基于历史频率的反驳/支持”。
- 其输出写入 `decision_observation.duckdb`，形成后验验证闭环。

这样既保留了 MOE 主线的可解释性，又让概率层成为增强证据而非黑盒替代。

---

## 11. 回测和验收标准

### 11.1 回测设计

- **训练期**：2019-01-01 至 2023-12-31（约 5 年）。
- **验证期**：2024-01-01 至 2025-12-31（约 2 年）。
- **滚动方式**：每月滚动重算先验，避免 look-ahead bias。
- **评估单元**：每个 (stock, date, window) 为一个样本。

### 11.2 评估指标

| 指标 | 说明 | MVP 验收门槛 |
|------|------|--------------|
| **Brier Score** | 概率校准度 | ≤ 0.20（4 类平均） |
| **Calibration Error** | 分桶校准误差 | ≤ 0.08 |
| **Top-K Precision（turn_up）** | 取 prob_turn_up 最高的 K 只，未来 N 日正收益比例 | 3D/3W K=50 时 ≥ 52%；3M K=50 时 ≥ 55% |
| **Top-K Precision（false_breakout）** | 取 prob_false_breakout 最高的 K 只，未来反向收益比例 | ≥ 50% |
| **方向准确率** | `turn_up` vs `turn_down` 二分类 AUC | ≥ 0.58 |
| **置信度区分度** | 高置信样本 vs 低置信样本的胜率差 | ≥ 10% |

### 11.3 稳定性验收

- 连续 20 个交易日运行，无 `bucket_sample_size < 10` 导致的全市场概率异常（所有标的概率全相等）。
- 新增一天数据后，先验表增量更新耗时 ≤ 10 分钟（基于现有 State Cube）。
- 生成的 JSON 大小 ≤ 20MB，便于上传服务器。

---

## 12. 不做清单

- **不写代码**：本阶段只输出设计文档和字段契约。
- **不改数据库**：不新建表、不新增字段、不迁移 Foundation。
- **不改前端**：只给出首页消费方式建议，不修改 HTML/JS/CSS。
- **不输出交易动作**：概率层只到“转强/转弱/延续/假突破”四概率，不产生买/卖/持仓建议。
- **不把经典策略信号纳入 State 主概率**：VCP/2560/Bollinger/composite 信号可作为独立证据，但不直接修改四概率。
- **不引入黑盒深度学习**：MVP 限定为 Empirical Bayes + 规则证据，保证可解释。
- **不做实时 M30 独立触发**：M30 只作为 D1 证据的盘中精细位置输入，不单独拍板。

---

## 13. 推荐摘要

### 推荐的时间窗定义

- **3D = 3 个交易日**
- **3W = 15 个交易日**
- **3M = 66 个交易日**
- **6M = 126 个交易日**

### 推荐的概率字段

保留任务建议的全部 14 个字段，追加 `bucket_sample_size`、`prior_weight`、`market_regime`、`industry_l1`、`future_return_n`、`outcome_label`、`model_version`、`updated_at`，共 22 个字段。

### MVP 最小可实现版本

1. 以 State Cube 为主数据源，通过 `LEAD(close, N)` 补齐 `future_r15 / future_r60 / future_r120`。
2. 构造 8–10 维粗粒度指纹，统计历史 outcome 频率作为先验。
3. 使用 5–8 条强证据做似然修正，输出四概率。
4. 样本不足时按维度回退并收缩到全局先验。
5. 生成 `turning_point_probability_YYYYMMDD.duckdb` 和 `turning_point_probability_latest.json`。
6. 首页消费：市场级分布卡片 + 个股候选池“转折概率”列 + 新增“概率 Agent”输入。

### 最大风险

1. **样本稀疏导致过度自信**：指纹桶过细或市场环境分层过早开启，会让某些标的出现 0.99/0.01 的极端概率。必须通过粗化回退、收缩估计和置信度上限来压制。
2. **未来收益标签滞后与幸存者偏差**：退市、停牌股票的历史 future return 缺失会抬高赢家概率。需要在回填时显式处理缺失 outcome。
3. **与现有 MOE 主线的耦合风险**：如果概率层被前端直接当作“最终结论”展示，会弱化 Agent 辩论和 Router 的作用。必须通过产品形态明确其为“证据层”。

---

## 14. 交付物

- 本文档：`docs/tasks/TURNING_POINT_PROBABILITY_MVP_KIMI1_20260702.md`
