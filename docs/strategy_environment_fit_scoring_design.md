# 策略环境适配度评分模型设计

版本：v1.0
日期：2026-05-23
状态：设计稿 — 为未来校准层提供框架
关联脚本：`scripts/strategy_signal_ledger.py`（当前实现）、`scripts/strategy_fit_observer.py`（观察记录）

---

## 概述

本文档设计策略环境适配度的系统化评分模型。当前系统使用基于生命周期阶段的五级分类（`strategy_signal_ledger.py:479`），本文档将其扩展为可量化、可校准的评分框架，为未来从定性分类升级到定量评分提供基础。

**当前状态**：五级分类基于 lifecycle_stage 与 strategy_id 的简单映射，无连续分数。
**目标状态**：连续评分（0-100）+ 加权维度 + 宏观/产业调节因子 + 置信度。

---

## 1. 当前五级分类体系

### 1.1 现有实现

当前 `compute_environment_fit()` 函数位于 `scripts/strategy_signal_ledger.py:479-498`：

```python
best_stage = {
    "vcp": "新生",
    "ma2560": "行进",
    "bollinger_bandit": "延展",
}.get(strategy_id)

if lifecycle_stage == best_stage:
    fit = "最佳适配"
elif (strategy_id, lifecycle_stage) in 适配对:
    fit = "适配"
else:
    fit = "弱适配"
```

### 1.2 五级分类定义

| 等级 | 当前含义 | 未来评分管位 |
|------|----------|-------------|
| 最佳适配 | 策略的最佳生命周期阶段 | 80-100 |
| 适配 | 策略的次优阶段，有历史支撑 | 60-79 |
| 弱适配 | 策略可运行但历史表现较弱 | 40-59 |
| 待观察 | 缺乏足够数据判断 | 20-39 |
| 不适配 | 明确不适合当前环境 | 0-19 |

### 1.3 当前映射表

| 策略 | 最佳适配 | 适配 | 弱适配 |
|------|----------|------|--------|
| VCP (vcp) | 新生 | — | 行进、延展 |
| 2560 (ma2560) | 行进 | 新生 | 延展 |
| 布林强盗 (bollinger_bandit) | 延展 | 行进 | 新生 |

---

## 2. 评分公式设计

### 2.1 总体公式

```text
fit_score = clamp(
    w_state     × S_state
  + w_path      × S_path
  + w_vol       × S_volatility
  + w_market    × S_market
  + w_momentum  × S_momentum
  + macro_adj   × w_macro
  + chain_adj   × w_chain,
  0, 100
)
```

其中：
- `S_*` 为各维度得分（0-100）
- `w_*` 为各维度权重（总和 = 1.0）
- `macro_adj` / `chain_adj` 为调节因子（-15 到 +15）
- `clamp(x, 0, 100)` 确保分数在 0-100 之间

### 2.2 评分维度定义

#### 维度 1：State 组合得分（S_state）

基于 MN1/W1/D1 三周期 State 组合与策略最优组合的匹配程度。

```text
S_state = base_score + bit_bonus
```

| 条件 | base_score | 说明 |
|------|-----------|------|
| 精确匹配已验证组合（如 2560 的 E/E/F） | 90 | 最高置信 |
| 模糊 bit 匹配（如扩张+有趋势+突破） | 70 | 次高置信 |
| 单 bit 匹配（如 base=8 扩张态） | 50 | 中等置信 |
| 不匹配但不冲突 | 30 | 低置信 |
| 明确冲突（如收缩态 + 布林强盗） | 10 | 不适配 |

bit_bonus：每个已验证的 bit 条件满足时 +5，上限 +15。

#### 维度 2：路径得分（S_path）

基于 D1 近期状态转换路径，特别重要于 VCP。

```text
S_path = path_type_score + recency_bonus
```

| 路径类型 | path_type_score | 适用策略 |
|----------|----------------|----------|
| D1 近 N 日收缩后释放（N ≤ 20） | 90 | VCP（最佳） |
| 三周期共振新近形成（≤ 5 天） | 85 | VCP、2560 |
| D1 E/F 持续 5-20 天，波动稳定 | 80 | 2560（最佳） |
| D1 E/F 持续 > 20 天，波动活跃 | 75 | 布林强盗（最佳） |
| D1 波动从稳定转为活跃 | 70 | 布林强盗 |
| 无明显路径特征 | 40 | 通用 |

recency_bonus：路径事件越近得分越高。当日发生 +10，3 日内 +5，7 日内 +2，超过 7 日 +0。

#### 维度 3：波动率位得分（S_volatility）

基于 D1 的 volatility_bit 与策略偏好的匹配。

| 策略 | volatility_bit=0 得分 | volatility_bit=1 得分 | 依据 |
|------|----------------------|----------------------|------|
| VCP | 70 | 60 | VCP 偏好突破初期的低波动 |
| 2560 | 80 | 50 | 2560 最佳环境是波动稳定 |
| 布林强盗 | 70 | 40 | 本地验证：vol=0 组 +0.59%，vol=1 组 -0.49% |

注：布林强盗的 vol=0 得分高于 vol=1，与直觉相反，但本地数据支持。

#### 维度 4：市场支撑得分（S_market）

基于行业 ETF 的 ef_count 和市场匹配等级。

```text
S_market = etf_score + market_match_bonus
```

| 条件 | etf_score | 说明 |
|------|-----------|------|
| 行业 ETF ef_count >= 2 | 80 | 市场共振成立 |
| 行业 ETF ef_count = 1 | 50 | 部分共振 |
| 行业 ETF ef_count = 0 或缺失 | 30 | 无市场共振 |
| 无行业 ETF 覆盖 | 20 | 数据缺失 |

| market_match_level | market_match_bonus |
|-------------------|--------------------|
| full_match | +15 |
| stock_only | +5 |
| market_unsupported | -5 |
| not_match | -15 |

#### 维度 5：动量/趋势得分（S_momentum）

基于 MA 趋势状态和成交量结构。

| 条件 | 得分 | 说明 |
|------|------|------|
| MA25 坚定向上 + VOL5 > VOL60 | 85 | 2560 最佳动量环境 |
| MA25 向上 + 成交量平 | 65 | 趋势存在但动能不足 |
| MA25 走平 | 45 | 趋势不确定 |
| MA25 向下 | 20 | 趋势反转风险 |

### 2.3 各策略权重设计

不同策略对各维度的侧重不同：

| 维度 | VCP 权重 | 2560 权重 | 布林强盗权重 | 设计理由 |
|------|---------|----------|------------|----------|
| State 组合 (w_state) | 0.20 | **0.35** | 0.20 | 2560 已固化 State 组合，权重最高 |
| 路径 (w_path) | **0.35** | 0.15 | 0.15 | VCP 以收缩后释放路径为核心 |
| 波动率 (w_vol) | 0.15 | 0.15 | **0.30** | 布林强盗对波动率最敏感 |
| 市场支撑 (w_market) | 0.10 | **0.20** | 0.10 | 2560 需要行业 ETF 共振确认 |
| 动量/趋势 (w_momentum) | 0.20 | 0.15 | 0.25 | VCP 和布林强盗都依赖趋势方向 |

权重总和：每列 = 1.00。

### 2.4 VCP 评分示例

```text
场景：D1 近 10 日收缩后释放，MN1/W1/D1 = E/E/F，行业 ETF ef_count=2
  S_state   = 90（精确匹配 E/E/F）
  S_path    = 90（收缩后释放）+ 5（10 日内）= 95
  S_vol     = 70（D1 vol_bit=1，VCP 偏好 0 但可接受）
  S_market  = 80 + 15 = 95
  S_momentum = 85

  fit_score = 0.20×90 + 0.35×95 + 0.15×70 + 0.10×95 + 0.20×85
            = 18.0 + 33.25 + 10.5 + 9.5 + 17.0
            = 88.25 → 最佳适配
```

### 2.5 2560 评分示例

```text
场景：D1 E/F 持续 15 天，MN1/W1/D1 = E/F/F，波动稳定，行业 ETF ef_count=1
  S_state   = 90（精确匹配 E/F/F）
  S_path    = 80（行进期）
  S_vol     = 80（D1 vol_bit=0，2560 最佳）
  S_market  = 50 + (-5) = 45（ef_count=1，market_unsupported）
  S_momentum = 85

  fit_score = 0.35×90 + 0.15×80 + 0.15×80 + 0.20×45 + 0.15×85
            = 31.5 + 12.0 + 12.0 + 9.0 + 12.75
            = 77.25 → 适配
```

---

## 3. 宏观环境加成/折扣系数

### 3.1 宏观象限分类

基于 `classify_macro_quadrant()` 函数（`scripts/strategy_environment_verifier.py:48`），宏观环境分为四个象限：

| 象限 | 货币 | 信用 | 典型特征 |
|------|------|------|----------|
| 宽货币+宽信用 | 宽松 | 扩张 | 风险偏好高，成长股占优 |
| 宽货币+紧信用 | 宽松 | 收缩 | 流动性充裕但实体需求弱 |
| 紧货币+宽信用 | 收紧 | 扩张 | 利率上行但经济尚可 |
| 紧货币+紧信用 | 收紧 | 收缩 | 防御为主，高股息占优 |

### 3.2 宏观调节因子

```text
macro_adj = macro_score × macro_weight
```

| 宏观象限 | VCP macro_adj | 2560 macro_adj | 布林强盗 macro_adj | 理由 |
|----------|--------------|----------------|-------------------|------|
| 宽货币+宽信用 | +12 | +5 | +10 | 成长风格+流动性充裕，利好突破类策略 |
| 宽货币+紧信用 | +5 | +8 | +3 | 流动性好但需求弱，2560 回踩更安全 |
| 紧货币+宽信用 | -5 | +3 | -3 | 利率上行压制估值，突破类策略风险增加 |
| 紧货币+紧信用 | -10 | -5 | -12 | 全面收缩，防御为主 |
| 宏观数据不足 | 0 | 0 | 0 | 保持中性，不加不减 |

宏观数据来源：`outputs/macro_chain_prior/macro_chain_prior_YYYYMMDD.json` 中的 `macro_prior.score_0_10`。

```text
macro_factor = (macro_prior.score_0_10 - 5.0) / 5.0  → 范围 [-1, 1]
macro_adj = macro_factor × macro_weight × 15  → 范围 [-15, +15]
```

### 3.3 风格偏好加成

基于 `market_style_prior`（`build_macro_chain_prior.py` 输出）：

| 风格信号 | VCP 加成 | 2560 加成 | 布林强盗加成 |
|----------|---------|----------|------------|
| 成长相对强（growth_vs_hs300 > 1%） | +5 | 0 | +3 |
| 小盘相对强（small_vs_hs300 > 1%） | +3 | +3 | 0 |
| 半导体相对券商强（> 5%） | +3 | 0 | +3 |
| 风险偏谨慎（risk_appetite < 4.5） | -5 | +2 | -8 |

---

## 4. 产业链景气调节因子

### 4.1 调节逻辑

产业链景气度（来自 `industry_position.prosperity_score`）对策略适配度的调节：

```text
chain_adj = (prosperity_score - 5.0) / 5.0 × chain_weight × 10
```

### 4.2 各策略的产业链敏感度

| 策略 | chain_weight | 理由 |
|------|-------------|------|
| VCP | 0.6 | VCP 偏趋势新生，对产业链景气敏感（景气上行时突破成功率更高） |
| 2560 | 0.8 | 2560 需要行业共振，产业链景气直接影响回踩质量 |
| 布林强盗 | 0.4 | 布林强盗更依赖波动率本身，产业链景气是次要因素 |

### 4.3 产业链位置的差异化调节

| 产业链位置 | VCP 调节 | 2560 调节 | 布林强盗调节 |
|-----------|---------|----------|------------|
| 上游（原材料） | 景气上行时 +2 | 景气上行时 +3 | 不调节 |
| 中游（制造） | 景气上行时 +3 | 景气上行时 +2 | 景气上行时 +2 |
| 下游（终端） | 不调节 | 景气上行时 +2 | 景气上行时 +3 |

理由：上游景气传导到终端有滞后，VCP 捕捉趋势新生时更关注中游信号。

---

## 5. 评分置信度与样本量关系

### 5.1 置信度公式

```text
confidence = min(1.0, sqrt(n / N_threshold)) × data_quality_factor
```

其中：
- `n` = 该策略 × State 组合的历史样本数
- `N_threshold` = 最小有效样本门槛（默认 30）
- `data_quality_factor` = 数据质量系数（0-1）

### 5.2 样本量-置信度对照表

| 样本量 n | 置信度（data_quality=1.0 时） | 等级 |
|----------|------------------------------|------|
| < 5 | < 0.41 | 极低 — 不展示具体数字 |
| 5-14 | 0.41-0.68 | 低 — 标注"样本有限" |
| 15-29 | 0.68-0.99 | 中 — 标注"初步验证" |
| 30-99 | 1.00 | 高 — 可展示统计数字 |
| 100+ | 1.00 | 最高 — 可进入规则层 |

### 5.3 数据质量系数

```text
data_quality_factor = coverage_factor × recency_factor × consistency_factor
```

| 因子 | 计算方法 | 范围 |
|------|----------|------|
| coverage_factor | 有效指标数 / 理论最大指标数 | 0.5-1.0 |
| recency_factor | 最新数据距今天数衰减：max(0.5, 1 - days/365) | 0.5-1.0 |
| consistency_factor | 近 5 期统计方向一致的比例 | 0.5-1.0 |

### 5.4 置信度对评分的影响

```text
effective_score = fit_score × confidence + 50 × (1 - confidence)
```

含义：置信度低时，评分向中性值（50）收缩。置信度为 0 时，无论数据如何，评分均为 50（中性）。

---

## 6. 从当前五级到连续评分的升级路径

### 6.1 阶段 1：观察期（当前）

保持现有五级分类不变。新增 `fit_score_numeric` 字段，写入 `strategy_signal_daily` 和 `strategy_fit_log`，但不影响提醒层展示。

```sql
ALTER TABLE strategy_signal_daily ADD COLUMN fit_score_numeric DOUBLE DEFAULT 50.0;
ALTER TABLE strategy_signal_daily ADD COLUMN fit_confidence DOUBLE DEFAULT 0.0;
```

### 6.2 阶段 2：校准期

用 `strategy_fit_observer` 积累的历史数据回测评分公式：

```bash
python3 scripts/calibrate_fit_scoring.py \
  --start-date 2025-06-01 \
  --end-date 2026-05-01 \
  --foundation-db outputs/p116_foundation_20260521/p116_foundation.duckdb
```

校准目标：验证 fit_score 与未来 5/10/20 日超额收益的相关性。

### 6.3 阶段 3：切换期

当校准期样本量 >= 100 个日期且相关性显著时，将 `fit_score_numeric` 作为主字段，五级分类降级为人类可读别名：

```text
fit_score >= 80 → "最佳适配"
fit_score >= 60 → "适配"
fit_score >= 40 → "弱适配"
fit_score >= 20 → "待观察"
fit_score <  20 → "不适配"
```

### 6.4 与提醒层的关系

提醒层展示语言不变：

```text
"该策略与该环境的适配度为高/中/弱/待观察"
```

但底层依据从规则映射升级为量化评分。

---

## 7. 合规边界

- 评分模型是**研究工具**，不直接生成交易信号。
- 适配度评分是**场景描述**，不是投资建议。
- 评分管位与历史超额收益的关系只在质量闸门通过后展示。
- 宏观/产业链调节因子在数据不足时必须保持中性（adj=0），不得猜测。
- 置信度低于 0.5 时，不展示具体评分数字，只展示五级分类。

---

## 附录：关键文件索引

| 文件 | 用途 |
|------|------|
| `scripts/strategy_signal_ledger.py` | 当前五级分类实现（`compute_environment_fit` 函数） |
| `scripts/strategy_fit_observer.py` | 适配度观察记录持久化 |
| `scripts/strategy_environment_verifier.py` | 策略环境验证编排器 |
| `config/strategy_registry.json` | 策略注册表，含验证状态和假设 |
| `outputs/strategy_fit_observer/fit_log_*.json` | 历史适配度观察数据 |
| `outputs/macro_chain_prior/macro_chain_prior_*.json` | 宏观+产业链先验数据 |
