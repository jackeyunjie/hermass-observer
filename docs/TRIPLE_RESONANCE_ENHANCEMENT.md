# 策略信号三重共振增强模型

版本：v1.0
日期：2026-05-23
状态：设计稿
关联文档：
- `docs/strategy_environment_fit_scoring_design.md`（策略评分五维公式）
- `docs/chain_prosperity_scoring_model.md`（产业链景气四维评分）
- `docs/MACRO_SCORING_MODEL.md`（宏观评分四维模型）

---

## 概述

系统的三层信号源各自独立运作：

```text
Layer 1: 宏观环境 → 四维评分 → 象限判定（MACRO_SCORING_MODEL.md）
Layer 2: 产业链景气 → 景气度评分 → 评级变化（chain_prosperity_scoring_model.md）
Layer 3: State 环境 → 五维适配度评分 → 生命周期阶段（strategy_environment_fit_scoring_design.md）
```

当三层同时指向同一方向时，信号置信度应获得显著加成；当三层冲突时，应降级或提示风险。本模型定义三重共振的判定条件、加成公式、等级分类和展示规则。

---

## 1. 三重共振判定条件

### 1.1 三个维度的信号定义

每个维度对每个策略产生一个方向信号：`positive`（利好）、`neutral`（中性）、`negative`（利空）。

#### 维度 1：宏观方向信号

基于 `MACRO_SCORING_MODEL.md` 的四维评分和象限判定：

```python
def macro_direction(strategy_id: str, quadrant: str, strategy_adj: float) -> str:
    """宏观维度对某策略的方向信号。"""
    # strategy_adj 来自 MACRO_SCORING_MODEL.md 第 8 节
    if strategy_adj >= 5.0:
        return "positive"
    elif strategy_adj <= -5.0:
        return "negative"
    else:
        return "neutral"
```

细化映射表：

| 宏观象限 | VCP 方向 | 2560 方向 | 布林强盗方向 | 理由 |
|----------|---------|----------|------------|------|
| 复苏 | positive | positive | positive | 流动性+增长双强，三策略均有利 |
| 过热 | negative | neutral | neutral | 收紧预期压制突破类，2560 回踩尚可 |
| 衰退 | neutral | positive | negative | 流动性宽松利好 2560 结构性机会，突破类受压 |
| 滞胀 | negative | negative | negative | 全面收缩，三策略均不利 |

当四维数据不足（`display_level = "insufficient"`）时，宏观方向为 `neutral`，不参与共振判定。

#### 维度 2：产业链景气方向信号

基于 `chain_prosperity_scoring_model.md` 的景气度评分：

```python
def chain_direction(strategy_id: str, prosperity_score: float,
                    prosperity_change: str, chain_position: str) -> str:
    """产业链维度对某策略的方向信号。"""
    if prosperity_score is None:
        return "neutral"  # 数据缺失，保持中性

    # 基础方向
    if prosperity_score >= 7.0:
        base = "positive"
    elif prosperity_score < 4.5:
        base = "negative"
    else:
        base = "neutral"

    # 趋势加成
    if prosperity_change == "improving" and base != "negative":
        return "positive"  # 景气改善提升方向
    elif prosperity_change == "deteriorating" and base != "positive":
        return "negative"  # 景气恶化降低方向

    return base
```

产业链-策略差异化：

| 产业链位置 | VCP 敏感度 | 2560 敏感度 | 布林强盗敏感度 |
|-----------|-----------|------------|--------------|
| 上游 | 中（供给信号） | 高（行业共振依赖） | 低 |
| 中游 | 高（制造景气反映趋势） | 高 | 中 |
| 下游 | 低 | 中（需求确认） | 高（终端需求驱动波动） |

敏感度影响加成系数的幅度（见第 2 节）。

#### 维度 3：State 环境方向信号

基于 `strategy_environment_fit_scoring_design.md` 的适配度评分：

```python
def state_direction(strategy_id: str, fit_score: float) -> str:
    """State 环境维度对某策略的方向信号。"""
    if fit_score is None:
        return "neutral"
    if fit_score >= 75:
        return "positive"
    elif fit_score < 40:
        return "negative"
    else:
        return "neutral"
```

### 1.2 共振判定逻辑

```python
def classify_resonance(macro_dir: str, chain_dir: str, state_dir: str) -> dict:
    """判定三重共振等级。"""
    directions = [macro_dir, chain_dir, state_dir]
    positive_count = directions.count("positive")
    negative_count = directions.count("negative")

    if positive_count == 3:
        resonance_level = "triple"
        resonance_label = "三重共振"
    elif positive_count == 2 and negative_count == 0:
        resonance_level = "double"
        resonance_label = "双重共振"
    elif positive_count >= 1 and negative_count == 0:
        resonance_level = "single"
        resonance_label = "单维利好"
    elif negative_count >= 2:
        resonance_level = "conflict"
        resonance_label = "多重冲突"
    elif negative_count == 1 and positive_count >= 1:
        resonance_level = "mixed"
        resonance_label = "信号分歧"
    else:
        resonance_level = "neutral"
        resonance_label = "中性环境"

    return {
        "resonance_level": resonance_level,
        "resonance_label": resonance_label,
        "macro_direction": macro_dir,
        "chain_direction": chain_dir,
        "state_direction": state_dir,
        "positive_count": positive_count,
        "negative_count": negative_count,
    }
```

---

## 2. 共振加成公式

### 2.1 总公式

```text
enhanced_fit_score = base_fit_score × macro_factor × chain_factor × state_factor
```

其中：
- `base_fit_score`：来自 `strategy_environment_fit_scoring_design.md` 的五维评分（0-100）
- `macro_factor`：宏观加成系数（0.80-1.20）
- `chain_factor`：产业链加成系数（0.80-1.20）
- `state_factor`：State 环境加成系数（0.85-1.15）

### 2.2 各因子计算

#### macro_factor

```python
def macro_factor(strategy_adj: float, confidence: float) -> float:
    """宏观加成系数。strategy_adj 来自 MACRO_SCORING_MODEL.md。"""
    # 将 strategy_adj [-15, +15] 映射到 [0.80, 1.20]
    raw = 1.0 + strategy_adj / 75.0  # +15 → 1.20, -15 → 0.80, 0 → 1.00

    # 置信度收缩：低置信度时向 1.00 收缩
    return round(1.0 + (raw - 1.0) * confidence, 4)
```

置信度收缩的效果：

| strategy_adj | confidence=1.0 | confidence=0.5 | confidence=0.2 |
|-------------|----------------|----------------|----------------|
| +15 | 1.200 | 1.100 | 1.040 |
| +10 | 1.133 | 1.067 | 1.027 |
| +5 | 1.067 | 1.033 | 1.013 |
| 0 | 1.000 | 1.000 | 1.000 |
| -5 | 0.933 | 0.967 | 0.987 |
| -10 | 0.867 | 0.933 | 0.973 |
| -15 | 0.800 | 0.900 | 0.960 |

#### chain_factor

```python
def chain_factor(prosperity_score: float, prosperity_change: str,
                 chain_position: str, strategy_id: str,
                 chain_confidence: float) -> float:
    """产业链加成系数。"""
    if prosperity_score is None:
        return 1.0  # 数据缺失，不加不减

    # 基础映射：景气度 [0, 10] → [0.80, 1.20]
    raw = 0.80 + (prosperity_score / 10.0) * 0.40  # 0 → 0.80, 5 → 1.00, 10 → 1.20

    # 趋势加成
    if prosperity_change == "improving":
        raw += 0.03
    elif prosperity_change == "deteriorating":
        raw -= 0.03

    # 策略-位置敏感度调整
    sensitivity = {
        "vcp": {"上游": 0.8, "中游": 1.0, "下游": 0.6, "综合": 0.7},
        "ma2560": {"上游": 1.0, "中游": 1.0, "下游": 0.8, "综合": 0.9},
        "bollinger_bandit": {"上游": 0.6, "中游": 0.8, "下游": 1.0, "综合": 0.7},
    }.get(strategy_id, {}).get(chain_position, 0.7)

    # 应用敏感度：敏感度越高，偏离 1.0 的幅度越大
    deviation = (raw - 1.0) * sensitivity
    result = 1.0 + deviation

    # 置信度收缩
    return round(1.0 + (result - 1.0) * chain_confidence, 4)
```

#### state_factor

```python
def state_factor(fit_score: float, fit_confidence: float) -> float:
    """State 环境加成系数。"""
    if fit_score is None:
        return 1.0

    # 将 fit_score [0, 100] 映射到 [0.85, 1.15]
    raw = 0.85 + (fit_score / 100.0) * 0.30  # 0 → 0.85, 50 → 1.00, 100 → 1.15

    # 置信度收缩
    return round(1.0 + (raw - 1.0) * fit_confidence, 4)
```

### 2.3 加成系数范围保护

```python
def clamp_factor(factor: float, lo: float = 0.75, hi: float = 1.30) -> float:
    """防止极端加成。"""
    return max(lo, min(hi, factor))
```

总乘积的理论范围：

| 场景 | macro_factor | chain_factor | state_factor | 总乘积 |
|------|-------------|-------------|-------------|--------|
| 三重利好（高置信） | 1.20 | 1.20 | 1.15 | 1.656 → 上限 1.30 |
| 三重利好（中置信） | 1.10 | 1.10 | 1.08 | 1.306 |
| 中性环境 | 1.00 | 1.00 | 1.00 | 1.000 |
| 三重利空（中置信） | 0.90 | 0.90 | 0.92 | 0.745 → 下限 0.75 |
| 三重利空（高置信） | 0.80 | 0.80 | 0.85 | 0.544 → 下限 0.75 |

---

## 3. 共振等级分类

### 3.1 六级分类

| 等级 | 条件 | 增强效果 | 展示标记 |
|------|------|---------|---------|
| triple | 三维度均 positive | enhanced_fit × [1.15, 1.30] | "三重共振" |
| double | 两维度 positive，无 negative | enhanced_fit × [1.05, 1.15] | "双重共振" |
| single | 一维度 positive，无 negative | enhanced_fit × [0.95, 1.05] | "单维利好" |
| neutral | 全部 neutral | enhanced_fit × [0.95, 1.05] | "中性环境" |
| mixed | 正面和负面并存 | enhanced_fit × [0.85, 0.95] | "信号分歧" |
| conflict | 两维度以上 negative | enhanced_fit × [0.75, 0.85] | "多重冲突" |

### 3.2 等级到适配度等级的映射

增强后的 fit_score 映射回五级分类：

```text
enhanced_fit >= 85 → "最佳适配"
enhanced_fit >= 65 → "适配"
enhanced_fit >= 45 → "弱适配"
enhanced_fit >= 25 → "待观察"
enhanced_fit <  25 → "不适配"
```

注意：三重共振可能将原本"适配"的信号提升为"最佳适配"；多重冲突可能将"适配"降级为"弱适配"。

---

## 4. 完整计算示例

### 4.1 场景：VCP 信号在宽货币 + AI 算力链景气 + 收缩后释放路径下

```text
标的：某 AI 芯片股
策略：VCP
信号：vcp_breakout（收缩后放量突破支点）
日期：2026-05-23
```

#### Step 1：基础适配度评分（strategy_environment_fit_scoring_design.md）

```text
S_state   = 85（MN1/W1/D1 = E/E/F，精确匹配 VCP 最佳组合）
S_path    = 92（D1 近 15 日收缩后释放，路径得分最高档 + 7 天内 recency bonus）
S_vol     = 65（D1 volatility_bit=1，VCP 偏好 0 但可接受）
S_market  = 88（行业 ETF ef_count=3，full_match）
S_momentum = 80（MA25 向上，VOL5 > VOL60）

VCP 权重：w_state=0.20, w_path=0.35, w_vol=0.15, w_market=0.10, w_momentum=0.20

base_fit_score = 0.20×85 + 0.35×92 + 0.15×65 + 0.10×88 + 0.20×80
               = 17.0 + 32.2 + 9.75 + 8.8 + 16.0
               = 83.75

fit_confidence = 0.85（样本量充足，数据质量好）
```

#### Step 2：宏观方向判定（MACRO_SCORING_MODEL.md）

```text
S_growth = 6.5, S_liquidity = 7.5, S_credit = 6.0, S_inflation = 5.5
象限 = "复苏"（growth_cycle=6.1, money_credit_cycle=6.83）
VCP strategy_adj = +8.5（流动性充裕 + 增长确认 → 利好突破类策略）
macro_confidence = 0.55

macro_direction = "positive"（strategy_adj >= 5.0）
macro_factor = 1.0 + (8.5 / 75.0) × 0.55 = 1.0 + 0.062 = 1.062
```

#### Step 3：产业链景气方向判定（chain_prosperity_scoring_model.md）

```text
AI 算力链景气度 = 8.2/10
景气变化 = "improving"
产业链位置 = "上游"（芯片设计）
chain_confidence = 0.70

chain_direction = "positive"（景气 >= 7.0 且 improving）
chain_factor = 1.0 + ((0.80 + 8.2/10×0.40 + 0.03 - 1.0) × 0.8 + (1.0 - 1.0)) × 0.70
             = 1.0 + (0.156 × 0.8) × 0.70
             = 1.0 + 0.087
             = 1.087
```

#### Step 4：State 环境方向判定

```text
fit_score = 83.75
fit_confidence = 0.85

state_direction = "positive"（fit_score >= 75）
state_factor = 1.0 + ((0.85 + 83.75/100×0.30) - 1.0) × 0.85
             = 1.0 + (1.101 - 1.0) × 0.85
             = 1.0 + 0.086
             = 1.086
```

#### Step 5：共振判定与增强

```text
三维度方向：macro=positive, chain=positive, state=positive
共振等级：triple（三重共振）

总乘积 = macro_factor × chain_factor × state_factor
       = 1.062 × 1.087 × 1.086
       = 1.251

clamp 至 [0.75, 1.30] → 1.251

enhanced_fit_score = base_fit_score × 总乘积
                   = 83.75 × 1.251
                   = 104.77 → clamp 至 [0, 100] → 100

增强后适配度等级：100 → "最佳适配"
（原本 83.75 已是"最佳适配"，三重共振进一步确认了高置信度）
```

#### Step 6：输出记录

```json
{
  "stock_code": "002049",
  "strategy_id": "vcp",
  "signal_name": "VCP突破确认",
  "base_fit_score": 83.75,
  "enhanced_fit_score": 100.0,
  "resonance": {
    "resonance_level": "triple",
    "resonance_label": "三重共振",
    "macro_direction": "positive",
    "chain_direction": "positive",
    "state_direction": "positive",
    "macro_factor": 1.062,
    "chain_factor": 1.087,
    "state_factor": 1.086,
    "total_factor": 1.251,
    "macro_quadrant": "复苏",
    "chain_prosperity": 8.2,
    "lifecycle_stage": "新生"
  },
  "fit_level_before": "最佳适配",
  "fit_level_after": "最佳适配",
  "confidence": 0.75
}
```

### 4.2 对比示例：同一 VCP 信号在滞胀 + 产业链收缩 + 弱适配下

```text
base_fit_score = 45.0（弱适配）
macro_factor = 0.90（滞胀，宏观利空）
chain_factor = 0.88（景气 3.2/10，deteriorating）
state_factor = 0.93（fit_score 低，折扣）
总乘积 = 0.90 × 0.88 × 0.93 = 0.736 → clamp 至 0.75
enhanced_fit_score = 45.0 × 0.75 = 33.75 → "待观察"
共振等级：conflict（多重冲突）
```

---

## 5. 与提醒层和首席报告的衔接

### 5.1 提醒卡片展示

在 `scripts/strategy_reminder_brief.py` 的提醒卡片中新增共振标记：

```python
def render_resonance_tag(resonance: dict) -> str:
    level = resonance.get("resonance_level", "neutral")
    tags = {
        "triple": "三重共振",
        "double": "双重共振",
        "single": "单维利好",
        "neutral": "",
        "mixed": "信号分歧",
        "conflict": "多重冲突",
    }
    return tags.get(level, "")
```

提醒卡片展示格式：

```text
三重共振（最佳适配）
  002049 紫光国微 | VCP突破确认
  State 环境：E/E/F | 新生
  产业链景气：AI算力链 8.2/10 | 上游
  宏观环境：复苏 | 流动性充裕
  共振强度：1.25x
```

```text
信号分歧（弱适配）
  600519 贵州茅台 | 2560强多头结构
  State 环境：E/F/F | 行进
  产业链景气：白酒消费链 5.5/10 | 下游
  宏观环境：过热 | 流动性收紧
  共振强度：0.92x
  注意：宏观与产业链方向分歧，谨慎参考
```

### 5.2 提醒卡片中的共振详情

当用户展开详情时，展示三个维度的独立判定：

```text
共振详情：
  宏观：利好（复苏象限，VCP加成 +8.5）
  产业链：利好（AI算力链景气上行 8.2/10）
  State：利好（适配度 83.75，最佳适配）
  → 三重共振，信号增强 25.1%
```

### 5.3 首席报告中的展示

在 `CHIEF_ECONOMIST_BRIEF_TEMPLATE.md` 第四层（重点个股信号）中：

```python
# 信号卡片新增共振行
SIGNAL_TEMPLATES["resonance_line"] = "  共振：{resonance_label} | 宏观{macro_dir} 产业{chain_dir} State{state_dir} | {factor}x"
```

在第五层（综合适配建议）中：

```python
# 三重共振统计
triple_count = sum(1 for s in signals if s["resonance"]["resonance_level"] == "triple")
conflict_count = sum(1 for s in signals if s["resonance"]["resonance_level"] == "conflict")

SYNTHESIS_TEMPLATES["resonance_summary"] = (
    "当日信号中，{triple} 个达到三重共振（宏观+产业链+State 均利好），"
    "{conflict} 个处于多重冲突状态。"
)
```

### 5.4 共振等级在排序中的作用

在首席报告第四层的信号排序中，共振等级作为额外排序键：

```text
原排序：适配度等级 → ef_count → market_match_level → signal_strength
新排序：共振等级 → 适配度等级 → ef_count → market_match_level → signal_strength
```

排序权重：

| 共振等级 | 排序分 |
|----------|--------|
| triple | 100 |
| double | 80 |
| single | 60 |
| neutral | 50 |
| mixed | 30 |
| conflict | 10 |

---

## 6. 置信度合成

### 6.1 共振置信度

三重共振的置信度由三个维度的置信度合成：

```text
resonance_confidence = min(1.0,
    macro_confidence × 0.35
  + chain_confidence × 0.30
  + state_confidence × 0.35
)
```

### 6.2 置信度对展示的影响

| resonance_confidence | 展示行为 |
|---------------------|----------|
| >= 0.7 | 展示共振等级和具体加成系数 |
| 0.5-0.7 | 展示共振等级，标注"置信度中等" |
| 0.3-0.5 | 仅展示共振等级，不展示具体系数 |
| < 0.3 | 不展示共振信息，仅展示原始适配度 |

---

## 7. 边界与防护

### 7.1 单维度缺失时的处理

| 缺失维度 | 处理方式 |
|----------|----------|
| 宏观数据不足 | macro_factor = 1.0，该维度标记为 "data_missing"，不参与共振判定 |
| 产业链数据为空 | chain_factor = 1.0，该维度标记为 "data_missing" |
| State 数据缺失 | state_factor = 1.0（不应发生，State 是核心必填数据） |

两个以上维度缺失时，不输出共振等级，仅展示原始适配度。

### 7.2 防止过度增强

```text
enhanced_fit_score = min(100, base_fit_score × total_factor)
```

即使三重共振，enhanced_fit_score 上限为 100，不产生超过量表范围的分数。

### 7.3 防止过度折扣

```text
enhanced_fit_score = max(0, base_fit_score × max(0.75, total_factor))
```

即使多重冲突，折扣下限为 0.75，避免将有效信号完全压零。

### 7.4 不改变信号事实

共振增强只影响适配度评分和展示优先级，不改变：
- 信号是否触发（由策略模块决定）
- 信号类型（entry/structure/exit/risk）
- 信号强度（signal_strength）
- 信号账本记录（strategy_signal_daily 的原始字段不变）

---

## 8. 实施路径

### 8.1 阶段 1：观察期

- 新增 `resonance_level` 和 `resonance_factors` 字段到 `strategy_signal_daily` 和提醒卡片
- 仅展示，不影响排序和适配度等级
- 积累共振-收益相关性的历史数据

### 8.2 阶段 2：校准期

- 用 `forward_observation_ledger` 的数据验证共振等级与未来收益的相关性
- 校准加成系数的幅度（当前 0.75-1.30 可能需要调整）
- 验证三重共振信号的超额收益是否显著优于非共振信号

### 8.3 阶段 3：切换期

- 共振增强正式影响适配度等级
- 提醒卡片和首席报告按共振等级排序
- 置信度达标后展示具体加成系数

---

## 附录：关键文件修改清单

| 文件 | 修改内容 |
|------|----------|
| `scripts/strategy_signal_ledger.py` | 新增 resonance 计算函数，enhanced_fit_score 字段 |
| `scripts/strategy_reminder_brief.py` | 新增共振标记渲染，排序加入共振等级 |
| `scripts/strategy_fit_observer.py` | 记录共振等级和增强后的 fit_score |
| `scripts/daily_research_brief.py` | chief 模式下展示共振统计 |
| `config/strategy_registry.json` | 新增 resonance_enhancement 配置段 |
| `docs/CHIEF_ECONOMIST_BRIEF_TEMPLATE.md` | 第四/五层新增共振展示模板 |
