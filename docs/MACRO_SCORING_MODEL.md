# 宏观评分四维模型设计

版本：v1.0
日期：2026-05-23
状态：设计稿
关联评审：`outputs/macro/deepseek_macro_layer_review_20260522.md`
关联脚本：`scripts/build_macro_chain_prior.py`（现有宏观先验，本模型的升级基础）
关联指标：`config/ifind_macro_indicators.json`（指标注册表）
关联设计：`docs/strategy_environment_fit_scoring_design.md`（宏观调节系数衔接）

---

## 概述

当前 `macro_prior.score_0_10` 是单一分数，由 `build_macro_chain_prior.py` 的 `indicator_signal()` 函数基于少数可用指标简单加总得到。DeepSeek 评审报告指出：增长和流动性数据严重不足，系统无法判断当前处于"衰退/复苏/过热/滞胀"哪个宏观周期阶段。

本模型将单一分数拆为**增长、流动性、信用、通胀**四个子维度，每个维度独立评分（0-10），再通过象限映射合成宏观环境判断和策略加成系数。

---

## 1. 四维评分公式总览

```text
macro_score_0_10 = W_growth × S_growth
                 + W_liquidity × S_liquidity
                 + W_credit × S_credit
                 + W_inflation × S_inflation
```

| 维度 | 权重 | 取值范围 | 含义 |
|------|------|----------|------|
| S_growth | 0.30 | 0-10 | 经济增长动能 |
| S_liquidity | 0.30 | 0-10 | 流动性充裕程度 |
| S_credit | 0.25 | 0-10 | 信用扩张/收缩 |
| S_inflation | 0.15 | 0-10 | 通胀压力 |

权重设计理由：增长和流动性是市场最核心的驱动因素（各 0.30），信用是增长的领先指标（0.25），通胀更多是约束条件（0.15）。

---

## 2. 增长维度（S_growth）

### 2.1 指标清单

| 指标 | iFinD code | 频率 | 权重 | 当前状态 |
|------|-----------|------|------|----------|
| 制造业PMI | M002043802 | 月 | 0.30 | active |
| 制造业PMI:新订单 | M002043804 | 月 | 0.25 | active |
| 制造业PMI:生产 | M002043803 | 月 | 0.20 | active |
| 规模以上工业增加值:当月同比 | M001622302 | 月 | 0.15 | active |
| GDP:累计同比 | M0043257 | 季 | 0.10 | needs_validation |

待补指标（补数据后权重调整）：

| 指标 | 预期权重 | 来源状态 |
|------|---------|----------|
| 非制造业PMI | 0.15 | needs_ifind_code |
| 出口总值:当月同比 | 0.10 | formula_catalog_only |

### 2.2 单指标评分公式

每个指标的评分由**水平分**和**趋势分**合成：

```text
indicator_score = level_score × 0.6 + trend_score × 0.4
```

#### 水平分（level_score）

将当前值映射到历史分位，再转换为 0-10 分：

```text
percentile = 历史分位（近 3 年数据，至少 12 个数据点）

level_score = percentile / 10  （直接映射：分位 70 → 7.0 分）
```

**历史分位阈值表**：

| 指标 | 低位阈值（<20%） | 中位（40-60%） | 高位阈值（>80%） | 方向含义 |
|------|-----------------|---------------|-----------------|----------|
| PMI | < 49.0 | 49.5-50.5 | > 51.0 | 高 = 好 |
| PMI:新订单 | < 49.0 | 49.5-50.5 | > 51.5 | 高 = 好 |
| PMI:生产 | < 49.5 | 50.0-51.0 | > 52.0 | 高 = 好 |
| 工业增加值同比 | < 3.0% | 5.0-6.5% | > 7.5% | 高 = 好 |
| GDP累计同比 | < 4.5% | 5.0-5.5% | > 6.0% | 高 = 好 |

#### 趋势分（trend_score）

基于近 3 期数据的方向和加速度：

```text
delta_1 = 当期值 - 上期值
delta_2 = 上期值 - 上上期值
acceleration = delta_1 - delta_2

IF delta_1 > 0 AND acceleration >= 0:   trend_score = 8.0  （加速上行）
IF delta_1 > 0 AND acceleration <  0:   trend_score = 6.5  （减速上行）
IF delta_1 == 0:                         trend_score = 5.0  （持平）
IF delta_1 < 0 AND acceleration <= 0:   trend_score = 2.0  （加速下行）
IF delta_1 < 0 AND acceleration >  0:   trend_score = 3.5  （减速下行）
```

### 2.3 维度汇总

```text
S_growth = clamp(Σ(indicator_score_i × weight_i) / Σ(weight_i), 0, 10)
```

仅对 status 为 "active" 且有至少 1 个历史数据点的指标计算。缺失指标不参与（不填充默认值）。

---

## 3. 流动性维度（S_liquidity）

### 3.1 指标清单

| 指标 | iFinD code | 频率 | 权重 | 当前状态 |
|------|-----------|------|------|----------|
| 中债国债到期收益率:10年 | L001619604 | 日 | 0.35 | active |
| 1年期LPR | M0017135 | 月 | 0.25 | needs_validation |
| DR007 | — | 日 | 0.25 | formula_catalog_only |
| 5年期LPR/利率互换代理 | — | 日 | 0.15 | formula_catalog_only |

### 3.2 利率指标的特殊处理

利率指标与增长/通胀方向相反：**利率下行 = 流动性宽松 = 高分**。

```text
对于利率类指标（国债收益率、LPR、DR007）：
  level_score = 10 - percentile / 10  （反转：分位 80 → 2.0 分）
  trend_score 反转：利率下行 = 正面
    IF delta_1 < 0: trend_score = 对应高分
    IF delta_1 > 0: trend_score = 对应低分
```

### 3.3 历史分位阈值表

| 指标 | 低位（宽松） | 中位 | 高位（收紧） | 方向含义 |
|------|------------|------|------------|----------|
| 10年国债收益率 | < 2.0% | 2.2-2.6% | > 2.8% | 低 = 宽松 = 好 |
| 1年期LPR | < 3.2% | 3.4-3.6% | > 3.8% | 低 = 宽松 = 好 |
| DR007 | < 1.5% | 1.7-2.0% | > 2.2% | 低 = 宽松 = 好 |

### 3.4 美元指数的调节作用

美元指数（G002600885，category=external）不直接进入流动性评分，但作为调节因子：

```text
IF 美元指数 percentile > 80（美元强势）:
    S_liquidity_adj = S_liquidity - 1.0  （外部流动性收紧）
ELIF 美元指数 percentile < 20（美元弱势）:
    S_liquidity_adj = S_liquidity + 0.5  （外部流动性宽松）
ELSE:
    S_liquidity_adj = S_liquidity
```

---

## 4. 信用维度（S_credit）

### 4.1 指标清单

| 指标 | iFinD code | 频率 | 权重 | 当前状态 |
|------|-----------|------|------|----------|
| 社会融资规模存量:期末同比 | M004891021 | 月 | 0.40 | active |
| 社会融资规模存量:同比 | M004028010 | 年 | 0.20 | active |
| M1期末值/同比 | — | 月 | 0.25 | formula_catalog_only |
| M2期末值/同比 | — | 月 | 0.15 | formula_catalog_only |

待补指标：

| 指标 | 预期权重 | 用途 |
|------|---------|------|
| M1-M2 剪刀差 | 0.20 | 信用活力的领先指标 |
| 新增人民币贷款 | 0.15 | 信贷需求的直接度量 |

### 4.2 信用指标评分

信用指标的评分逻辑与增长类似，但增加**边际变化**权重：

```text
indicator_score = level_score × 0.4 + trend_score × 0.3 + marginal_score × 0.3
```

#### 边际变化分（marginal_score）

信用的边际变化比绝对水平更重要：

```text
marginal = 当期同比 - 前 3 期均值同比

IF marginal > 2%:  marginal_score = 9.0  （信用大幅扩张）
IF marginal > 0%:  marginal_score = 7.0  （信用温和扩张）
IF marginal == 0%: marginal_score = 5.0  （信用持平）
IF marginal > -2%: marginal_score = 3.0  （信用温和收缩）
IF marginal <= -2%: marginal_score = 1.0 （信用大幅收缩）
```

### 4.3 M1-M2 剪刀差（待数据补全后启用）

```text
M1-M2 剪刀差 = M1同比 - M2同比

剪刀差 > 0: 资金活化，经济活力上升 → S_credit 加成 +1.0
剪刀差 < -5%: 资金沉淀，经济活力下降 → S_credit 折扣 -1.5
```

---

## 5. 通胀维度（S_inflation）

### 5.1 指标清单

| 指标 | iFinD code | 频率 | 权重 | 当前状态 |
|------|-----------|------|------|----------|
| CPI:当月同比 | M002826730 | 月 | 0.35 | active |
| PPI:当月同比 | M002826865 | 月 | 0.35 | active |
| CPI:同比 | M002826721 | 年 | 0.15 | active |
| PPI:同比 | M002826826 | 年 | 0.15 | active |

待补指标：

| 指标 | 预期权重 | 用途 |
|------|---------|------|
| 南华商品指数 | 0.15 | 输入型通胀压力 |
| 布伦特原油 | 0.10 | 能源价格传导 |

### 5.2 通胀的特殊评分逻辑

通胀不是简单的"越高越好"或"越低越好"，而是存在**舒适区间**：

```text
温和通胀（CPI 1-3%, PPI 0-5%）→ 高分（6-8 分）
通缩（CPI < 0%, PPI < -3%）→ 低分（2-4 分）— 需求不足
高通胀（CPI > 5%, PPI > 8%）→ 低分（2-4 分）— 政策收紧风险
```

#### CPI 评分映射

```text
IF CPI 在 1.0%-3.0%:  level_score = 7.0 + (CPI - 1.0) / 2.0 × 1.0  （7.0-8.0，舒适区）
IF CPI 在 0%-1.0%:    level_score = 5.0 + CPI / 1.0 × 2.0            （5.0-7.0，偏低）
IF CPI < 0%:           level_score = max(2.0, 5.0 + CPI × 2.0)       （2.0-5.0，通缩风险）
IF CPI 在 3.0%-5.0%:  level_score = 7.0 - (CPI - 3.0) / 2.0 × 2.0   （5.0-7.0，偏高）
IF CPI > 5.0%:         level_score = max(2.0, 5.0 - (CPI - 5.0) × 1.0)（2.0-5.0，高通胀）
```

#### PPI 评分映射

```text
IF PPI 在 0%-5.0%:    level_score = 7.0 + PPI / 5.0 × 1.0           （7.0-8.0，温和上行）
IF PPI 在 -3%-0%:     level_score = 5.0 + PPI / 3.0 × 2.0            （3.0-5.0，通缩压力）
IF PPI < -3%:          level_score = max(1.5, 3.0 + (PPI + 3) × 0.5) （1.5-3.0，严重通缩）
IF PPI 在 5%-8%:      level_score = 7.0 - (PPI - 5) / 3.0 × 2.0     （5.0-7.0，偏高）
IF PPI > 8%:           level_score = max(2.0, 5.0 - (PPI - 8) × 0.5) （2.0-5.0，高通胀）
```

### 5.3 通胀趋势加成

```text
IF PPI 从负转正（拐点）:  trend_score += 2.0  （工业品价格拐点，利好盈利修复）
IF CPI 连续 3 月下行:     trend_score -= 1.0  （消费端持续走弱）
```

---

## 6. 四象限映射

### 6.1 坐标轴定义

```text
横轴（增长周期）= 0.60 × S_growth + 0.40 × S_inflation
纵轴（货币信用周期）= 0.55 × S_liquidity + 0.45 × S_credit
```

### 6.2 四象限划分

```text
                    货币信用宽松（纵轴 >= 5.5）
                         │
              ┌──────────┼──────────┐
              │          │          │
              │  复苏     │   过热    │
              │ Recovery  │Overheat  │
              │          │          │
  增长弱 ─────┼──────────┼──────────┼───── 增长强
  (横轴<5.0)  │          │          │    (横轴>=5.0)
              │  衰退     │   滞胀    │
              │Recession  │Stagflate │
              │          │          │
              └──────────┼──────────┘
                         │
                    货币信用收紧（纵轴 < 5.5）
```

### 6.3 象限特征与策略含义

| 象限 | 增长 | 流动性/信用 | 典型特征 | 策略含义 |
|------|------|-----------|----------|----------|
| 复苏 | 强 | 宽 | 经济上行 + 流动性充裕 | 三策略均有利，VCP 最佳 |
| 过热 | 强 | 紧 | 经济强但政策收紧 | 布林强盗可跟踪，VCP 受压 |
| 滞胀 | 弱 | 紧 | 经济弱 + 流动性收紧 | 全面防御，三策略均不利 |
| 衰退 | 弱 | 宽 | 经济弱但流动性宽松 | 2560 可寻找结构性机会 |

### 6.4 象限判定函数

```python
def classify_macro_quadrant_v2(S_growth: float, S_liquidity: float,
                                S_credit: float, S_inflation: float) -> dict:
    growth_cycle = 0.60 * S_growth + 0.40 * S_inflation
    money_credit_cycle = 0.55 * S_liquidity + 0.45 * S_credit

    if growth_cycle >= 5.0 and money_credit_cycle >= 5.5:
        quadrant = "复苏"
    elif growth_cycle >= 5.0 and money_credit_cycle < 5.5:
        quadrant = "过热"
    elif growth_cycle < 5.0 and money_credit_cycle >= 5.5:
        quadrant = "衰退"
    else:
        quadrant = "滞胀"

    return {
        "quadrant": quadrant,
        "growth_cycle": round(growth_cycle, 2),
        "money_credit_cycle": round(money_credit_cycle, 2),
        "sub_scores": {
            "growth": round(S_growth, 2),
            "liquidity": round(S_liquidity, 2),
            "credit": round(S_credit, 2),
            "inflation": round(S_inflation, 2),
        },
    }
```

---

## 7. 宏观先验置信度

### 7.1 置信度公式

```text
confidence = coverage_factor × history_factor × freshness_factor
```

| 因子 | 计算方法 | 范围 |
|------|----------|------|
| coverage_factor | 参与评分的指标数 / 理论最大指标数（当前 22 个） | 0.1-1.0 |
| history_factor | min(1.0, 平均历史数据点数 / 24) — 24 个月为满分 | 0.1-1.0 |
| freshness_factor | min(1.0, 最新数据距今天数的衰减) | 0.3-1.0 |

### 7.2 分维度置信度

```python
def dimension_confidence(indicators: list[dict], dimension: str) -> float:
    """计算单个维度的置信度。"""
    dim_indicators = [i for i in indicators if i["category"] == dimension and i["status"] == "active"]
    total_indicators = [i for i in indicators if i["category"] == dimension]

    if not total_indicators:
        return 0.0

    coverage = len(dim_indicators) / len(total_indicators)
    history = mean(i.get("history_count", 0) for i in dim_indicators) if dim_indicators else 0
    history_factor = min(1.0, history / 24)

    return round(min(1.0, coverage * history_factor * 0.9), 4)  # 0.9 = freshness 上限
```

### 7.3 置信度等级

| 置信度 | 等级 | 报告行为 |
|--------|------|----------|
| >= 0.7 | 高 | 完整展示四维评分 + 象限 + 策略启示 |
| 0.5-0.7 | 中 | 展示四维评分，标注部分维度数据不足 |
| 0.3-0.5 | 低 | 仅展示有数据的维度，象限标注"待确认" |
| < 0.3 | 极低 | 输出"宏观数据严重不足，保持中性"，不展示具体评分 |

### 7.4 降级展示策略

```python
def degrade_macro_display(confidence: float, sub_scores: dict) -> dict:
    if confidence >= 0.7:
        return {"display_level": "full", "sub_scores": sub_scores}
    elif confidence >= 0.5:
        # 标注低置信维度
        flagged = {k: {"score": v, "flag": "low_confidence"}
                   for k, v in sub_scores.items()}
        return {"display_level": "partial", "sub_scores": flagged}
    elif confidence >= 0.3:
        # 仅展示置信维度
        reliable = {k: v for k, v in sub_scores.items() if dimension_confidence(...) >= 0.5}
        return {"display_level": "minimal", "sub_scores": reliable}
    else:
        return {"display_level": "insufficient", "sub_scores": {},
                "message": "宏观数据严重不足，保持中性分数，不参与策略调整。"}
```

---

## 8. 四维评分到策略加成系数的映射

### 8.1 与 strategy_environment_fit_scoring_design.md 的衔接

本模型输出替代该文档中 3.2 节的"宏观调节因子"（macro_adj），从粗粒度的四象限映射升级为细粒度的四维评分映射。

### 8.2 策略加成公式

```text
strategy_macro_adj = Σ(dimension_weight_i × dimension_score_normalized_i) × 15
```

其中 `dimension_score_normalized = (S_dimension - 5.0) / 5.0`，范围 [-1, 1]。

### 8.3 各策略的维度权重

| 维度 | VCP 权重 | 2560 权重 | 布林强盗权重 | 设计理由 |
|------|---------|----------|------------|----------|
| S_growth | 0.30 | 0.20 | 0.25 | VCP 更依赖经济增长确认突破 |
| S_liquidity | 0.35 | 0.25 | 0.35 | 突破类策略需要流动性配合 |
| S_credit | 0.20 | 0.35 | 0.20 | 2560 需要信用扩张支撑行业共振 |
| S_inflation | 0.15 | 0.20 | 0.20 | 温和通胀利好趋势延续 |

### 8.4 加成系数范围

```text
每维度贡献范围：(-1 × weight) × 15 到 (+1 × weight) × 15
总加成范围：-15 到 +15
```

### 8.5 象限级加成系数（简化版，当四维数据不足时使用）

| 象限 | VCP macro_adj | 2560 macro_adj | 布林强盗 macro_adj |
|------|--------------|----------------|-------------------|
| 复苏 | +12 | +8 | +10 |
| 过热 | -3 | +3 | +5 |
| 衰退 | +5 | +8 | +3 |
| 滞胀 | -10 | -5 | -12 |

### 8.6 计算示例

```text
S_growth = 6.5, S_liquidity = 7.0, S_credit = 5.5, S_inflation = 6.0

VCP:
  = (0.30×(6.5-5)/5 + 0.35×(7.0-5)/5 + 0.20×(5.5-5)/5 + 0.15×(6.0-5)/5) × 15
  = (0.30×0.30 + 0.35×0.40 + 0.20×0.10 + 0.15×0.20) × 15
  = (0.09 + 0.14 + 0.02 + 0.03) × 15
  = 0.28 × 15 = +4.2

2560:
  = (0.20×0.30 + 0.25×0.40 + 0.35×0.10 + 0.20×0.20) × 15
  = (0.06 + 10 + 0.035 + 0.04) × 15
  = 0.235 × 15 = +3.5

布林强盗:
  = (0.25×0.30 + 0.35×0.40 + 0.20×0.10 + 0.20×0.20) × 15
  = (0.075 + 0.14 + 0.02 + 0.04) × 15
  = 0.275 × 15 = +4.1

象限：增长周期 = 0.60×6.5+0.40×6.0 = 6.3，货币信用 = 0.55×7.0+0.45×5.5 = 6.3
→ 象限 = "复苏"
```

---

## 9. 输出格式

### 9.1 macro_prior JSON 升级

```json
{
  "schema_version": "macro_prior_v2",
  "date": "2026-05-23",
  "score_0_10": 6.45,
  "sub_scores": {
    "growth": {"score": 6.5, "confidence": 0.65, "indicators_used": 4, "indicators_total": 5},
    "liquidity": {"score": 7.0, "confidence": 0.40, "indicators_used": 1, "indicators_total": 4},
    "credit": {"score": 5.5, "confidence": 0.50, "indicators_used": 2, "indicators_total": 4},
    "inflation": {"score": 6.0, "confidence": 0.70, "indicators_used": 4, "indicators_total": 4}
  },
  "quadrant": {
    "name": "复苏",
    "growth_cycle": 6.3,
    "money_credit_cycle": 6.3
  },
  "confidence": 0.55,
  "display_level": "partial",
  "strategy_adj": {
    "vcp": 4.2,
    "ma2560": 3.5,
    "bollinger_bandit": 4.1
  },
  "evidence": [
    "增长：PMI 50.2（分位 55%），新订单 50.8（分位 60%）",
    "流动性：10 年国债 1.72%（分位 15%，宽松）",
    "信用：社融同比 8.5%（边际 +0.3%）",
    "通胀：CPI 0.3%（偏低），PPI -2.1%（通缩压力）"
  ],
  "data_gaps": ["DR007: formula_catalog_only", "M1同比: formula_catalog_only"],
  "research_only": true
}
```

### 9.2 向后兼容

现有的 `macro_prior.score_0_10` 字段保持不变，由四维子分加权计算得到。下游消费者（strategy_priors、industry_priors）无需修改即可继续使用。

新增 `sub_scores`、`quadrant`、`strategy_adj` 字段供进阶消费者使用。

---

## 10. 与现有 build_macro_chain_prior.py 的改造点

| 函数 | 当前逻辑 | 改造内容 |
|------|----------|----------|
| `indicator_signal()` | 基于指标名关键词的 if-else 规则 | 替换为四维评分公式，每指标有独立的 level/trend/marginal 计算 |
| `build_macro_prior()` | 单一 score_0_10 | 拆为四维 sub_scores + 象限 + 置信度 |
| `build_strategy_priors()` | 粗粒度的三策略先验 | 替换为四维到策略的加权映射 |
| 新增 | — | `classify_macro_quadrant_v2()` 象限判定函数 |
| 新增 | — | `degrade_macro_display()` 降级展示函数 |
| 新增 | — | `dimension_confidence()` 分维度置信度函数 |

---

## 附录：指标状态速查

| 指标 | category | status | 可参与评分 |
|------|----------|--------|-----------|
| 制造业PMI | growth | active | 是 |
| 制造业PMI:新订单 | growth | active | 是 |
| 制造业PMI:生产 | growth | active | 是 |
| 规模以上工业增加值:当月同比 | growth | active | 是 |
| GDP:累计同比 | growth | needs_validation | 待验证 |
| 非制造业PMI | growth | needs_ifind_code | 否 |
| 中债国债收益率:10年 | liquidity | active | 是 |
| 1年期LPR | liquidity | needs_validation | 待验证 |
| DR007 | liquidity | formula_catalog_only | 否 |
| 社融存量:期末同比 | credit | active | 是 |
| 社融存量:同比 | credit | active | 是 |
| M1同比 | credit | formula_catalog_only | 否 |
| M2同比 | credit | formula_catalog_only | 否 |
| CPI:当月同比 | inflation | active | 是 |
| PPI:当月同比 | inflation | active | 是 |
| CPI:同比 | inflation | active | 是 |
| PPI:同比 | inflation | active | 是 |
| 美元指数 | external | active | 调节因子 |
| 成长风格 | style | active | market_style_prior |
| CFETS人民币汇率 | external | active | 调节因子 |
