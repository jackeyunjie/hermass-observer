# W1×MN1 环境标签体系设计

版本：v1.0
日期：2026-05-23
状态：设计稿
关联框架：`docs/W1_MN1_STRATEGY_VALIDATION_FRAMEWORK.md`
关联手册：`docs/USER_MANUAL.md`

---

## 概述

当前系统只有一层环境标签（D1 层面），描述信号自身的质量特征。W1×MN1 验证框架提供了第二层标签——大周期背景。两层标签形成完整的环境描述：

```text
D1 标签：描述"信号自身质量"（这个信号本身的条件好不好）
W1×MN1 标签：描述"大周期背景"（信号运行的大环境支不支持）
```

类比：D1 标签是"种子质量"，W1×MN1 标签是"土壤质量"。

---

## 1. 两层标签体系

### 1.1 D1 层标签（现有，不变）

描述信号自身的 State 环境质量。

| 标签 | 含义 | 来源 |
|------|------|------|
| 三周期共振新近形成 | MN1/W1/D1 同时 E/F，形成 <=5 天 | lifecycle_stage |
| D1 刚脱离收缩 | D1 从收缩态进入扩张态 <=3 天 | lifecycle_stage |
| D1 收缩充分 | D1 经历了较长时间收缩 | lifecycle_stage |
| 波动稳定 | D1 volatility_bit=0 | d1_volatility_bit |
| 波动偏活跃 | D1 volatility_bit=1 | d1_volatility_bit |
| 价格位于阻力区间上方 | D1 收盘价 > D1 阻力位 | sr_position |
| full_match（2560） | 个股+State+行业 ETF 三重确认 | ma2560_market_match_level |
| not_match（2560） | 不满足 2560 适配 State | ma2560_market_match_level |

### 1.2 W1×MN1 层标签（新增）

描述信号运行的大周期背景环境。

| 标签 ID | 标签名 | 含义 | 条件 |
|---------|--------|------|------|
| strong_resonance | 大周期共振 | 月线+周线均扩张有趋势，大小周期全面强势 | W1=扩张有趋势 AND MN1=扩张有趋势 |
| trend_gestation | 趋势孕育 | 大周期正在酝酿趋势，周线有趋势但月线尚未全面确认 | W1=收缩有趋势 AND MN1=收缩或扩张初期 |
| week_strong_month_weak | 周强月弱 | 周线趋势确认但月线不支持，中期强势长期未确认 | W1=扩张有趋势 AND MN1=收缩或无趋势 |
| month_strong_week_weak | 月强周弱 | 月线趋势确认但周线在回调 | W1=收缩或无趋势 AND MN1=扩张有趋势 |
| double_contraction | 双重收缩 | 大小周期均收缩，趋势稀缺 | W1=收缩 AND MN1=收缩 |
| transition | 大周期过渡 | 无明确特征的过渡状态 | 其他组合 |

---

## 2. 标签对策略的影响方向

### 2.1 影响方向矩阵

| W1×MN1 标签 | VCP 影响 | 2560 影响 | Bollinger 影响 | 说明 |
|-------------|---------|----------|---------------|------|
| 大周期共振 | 正面 | 正面 | 正面 | 全面强势，三策略均受益 |
| 趋势孕育 | **正面（最强）** | 中性 | 偏负面 | 弹簧压缩最充分，VCP 最佳土壤 |
| 周强月弱 | 中性 | 正面 | 中性 | 周线支撑 2560 回踩质量 |
| 月强周弱 | 偏负面 | 正面 | 偏负面 | 月线强但周线回调，突破类受压 |
| 双重收缩 | 负面 | 负面 | 负面 | 趋势稀缺，三策略均不利 |
| 大周期过渡 | 中性 | 中性 | 中性 | 无明确方向 |

### 2.2 一句话描述（用于用户手册）

```python
W1_MN1_LABEL_DESCRIPTIONS = {
    "strong_resonance":     "大周期全面强势，信号运行在最佳土壤中",
    "trend_gestation":      "大周期正在酝酿趋势，收缩充分后释放的潜力最大",
    "week_strong_month_weak": "周线趋势确认但月线未完全跟上，需关注月线能否补位",
    "month_strong_week_weak": "月线趋势在但周线回调中，可能是回踩机会也可能是趋势减弱",
    "double_contraction":   "大小周期均在收缩，趋势信号的可靠性较低",
    "transition":           "大周期处于过渡状态，无明确方向",
}
```

---

## 3. env_category_factor 调节系数

### 3.1 系数定义

大周期环境对适配度评分的乘法调节系数。

```python
ENV_CATEGORY_FACTOR = {
    "strong_resonance":     {"vcp": 1.10, "ma2560": 1.12, "bollinger_bandit": 1.10},
    "trend_gestation":      {"vcp": 1.08, "ma2560": 0.98, "bollinger_bandit": 0.95},
    "week_strong_month_weak": {"vcp": 1.00, "ma2560": 1.02, "bollinger_bandit": 1.00},
    "month_strong_week_weak": {"vcp": 0.95, "ma2560": 1.05, "bollinger_bandit": 0.98},
    "double_contraction":   {"vcp": 0.92, "ma2560": 0.88, "bollinger_bandit": 0.90},
    "transition":           {"vcp": 1.00, "ma2560": 1.00, "bollinger_bandit": 1.00},
}
```

### 3.2 设计理由

| 系数 | 策略 | 理由 |
|------|------|------|
| 1.12 | 2560 + 大周期共振 | 2560 最依赖行业共振，大周期全面强势对回踩质量提升最大 |
| 1.10 | VCP + 大周期共振 | 大周期强势提供趋势延续的背景支撑 |
| 1.08 | VCP + 趋势孕育 | 弹簧压缩最充分时释放力度最大 |
| 0.98 | 2560 + 趋势孕育 | 趋势尚未确认，2560 回踩可能不够可靠 |
| 0.95 | VCP + 月强周弱 | 周线回调压制短期突破动力 |
| 0.88 | 2560 + 双重收缩 | 大周期收缩时回踩质量最低 |
| 0.90 | Bollinger + 双重收缩 | 大周期收缩时波动突破的持续性最差 |

### 3.3 调节方式

```python
def apply_env_category_factor(
    base_fit_score: float,
    env_category: str,
    strategy_id: str,
) -> float:
    """大周期环境对适配度的乘法调节。"""
    factor = ENV_CATEGORY_FACTOR.get(env_category, {}).get(strategy_id, 1.0)
    return round(min(100, max(0, base_fit_score * factor)), 2)
```

### 3.4 与现有调节因子的关系

```text
最终适配度 = base_fit_score
           × macro_factor        （宏观加成，0.80-1.20）
           × chain_factor        （产业链加成，0.80-1.20）
           × state_factor        （State 环境加成，0.85-1.15）
           × phase_factor        （市场阶段加成，0.80-1.15）
           × env_category_factor （大周期环境加成，0.88-1.12）← 新增
```

env_category_factor 的调节幅度最小（0.88-1.12），因为它与 state_factor 高度相关——两者都基于 State 数据，只是粒度不同。

---

## 4. 两层标签组合展示规则

### 4.1 提醒卡片展示

```text
┌──────────────────────────────────────────────────────────┐
│ 300969 恒帅股份                                           │
│ ──────────────────────────────────────────────────────── │
│ 策略信号：VCP突破确认          适配度：最佳适配           │
│ 生命周期：趋势新生                                        │
│ ──────────────────────────────────────────────────────── │
│ State 环境：MN1: E  W1: E  D1: E  (ef=3)                 │
│ ──────────────────────────────────────────────────────── │
│ D1 标签：波动稳定 / D1收缩充分 / 三周期共振新近形成        │
│ 大周期标签：大周期共振 — 月线+周线均扩张有趋势              │
│ ──────────────────────────────────────────────────────── │
│ 基本面：质量健康 / 现金流健康                              │
│ 本地验证：收缩后释放路径，20d超额 +1.67%                  │
└──────────────────────────────────────────────────────────┘
```

### 4.2 两层标签的展示位置

```text
D1 标签 → 现有"环境标签"字段，紧跟 State 环境行
W1×MN1 标签 → 新增"大周期标签"字段，在 D1 标签下方
```

### 4.3 展示优先级

当标签过多时，按以下优先级展示（最多 3 个 D1 + 1 个 W1×MN1）：

**D1 标签优先级**：
1. 三周期共振新近形成
2. D1 刚脱离收缩
3. full_match（2560）
4. 波动稳定 / 波动偏活跃
5. 其他

**W1×MN1 标签优先级**：
1. 大周期共振（最强正面信号）
2. 双重收缩（最强负面信号）
3. 趋势孕育（VCP 专属正面）
4. 其他

### 4.4 总报展示

在总报的"最佳适配聚焦表"中新增一列：

```text
┌──────────┬────────┬──────────┬──────┬────────────────────┬──────────────┬──────────┐
│ 股票     │ 行业   │ 策略     │ 阶段 │ D1 环境标签        │ 大周期背景   │ 统计     │
├──────────┼────────┼──────────┼──────┼────────────────────┼──────────────┼──────────┤
│ 恒帅股份 │ 汽车   │ VCP      │ 新生 │ 波动稳定/D1收缩充分│ 大周期共振   │ +1.67%   │
│ 科创新源 │ 化工   │ VCP      │ 新生 │ 三周期共振新近形成 │ 趋势孕育     │ +1.67%   │
│ 播恩集团 │ 农牧   │ Bollinger│ 延展 │ 价格突破阻力区间   │ 周强月弱     │ +0.59%   │
└──────────┴────────┴──────────┴──────┴────────────────────┴──────────────┴──────────┘
```

---

## 5. 与三重共振增强模型的衔接

### 5.1 当前三重共振

```text
维度 1: 宏观 → macro_factor
维度 2: 产业链 → chain_factor
维度 3: State → state_factor × phase_factor
```

### 5.2 升级后三重共振

W1×MN1 环境标签不作为独立的第四维度，而是 **State 维度的细化信息**：

```text
维度 3: State → state_factor × phase_factor × env_category_factor
```

在共振方向判定中，W1×MN1 标签用于调节 State 方向的强度：

```python
def state_direction_with_env_category(
    strategy_id: str,
    fit_score: float,
    env_category: str,
) -> tuple[str, str]:
    """大周期环境调节后的 State 方向判定。"""
    base_dir = state_direction(strategy_id, fit_score)

    # 大周期共振：强化正面
    if env_category == "strong_resonance" and base_dir == "positive":
        return "positive", "strong"

    # 双重收缩：降级正面
    if env_category == "double_contraction" and base_dir == "positive":
        return "neutral", "downgraded"

    # 趋势孕育 + VCP：强化正面
    if env_category == "trend_gestation" and strategy_id == "vcp" and base_dir == "positive":
        return "positive", "strong"

    return base_dir, "normal"
```

### 5.3 共振等级计算中的使用

```python
def classify_resonance_with_env(
    macro_dir: str,
    chain_dir: str,
    state_dir: str,
    env_category: str,
) -> dict:
    """在三重共振判定中加入大周期环境的强度调节。"""
    base = classify_resonance(macro_dir, chain_dir, state_dir)

    # 大周期共振可以将"双重共振"提升为"准三重共振"
    if base["resonance_level"] == "double" and env_category == "strong_resonance":
        base["resonance_level"] = "double_plus"
        base["resonance_label"] = "双重共振+大周期共振"
        base["env_boost"] = True

    # 双重收缩可以将"双重共振"降级为"弱共振"
    if base["resonance_level"] == "double" and env_category == "double_contraction":
        base["resonance_level"] = "double_minus"
        base["resonance_label"] = "双重共振+大周期收缩"
        base["env_penalty"] = True

    return base
```

---

## 6. 新增字段清单

### 6.1 strategy_signal_daily 表

```sql
ALTER TABLE strategy_signal_daily ADD COLUMN env_category VARCHAR DEFAULT 'transition';
ALTER TABLE strategy_signal_daily ADD COLUMN w1_mn1_label VARCHAR DEFAULT '';
ALTER TABLE strategy_signal_daily ADD COLUMN env_category_factor DOUBLE DEFAULT 1.0;
```

### 6.2 strategy_fit_log 表

```sql
ALTER TABLE strategy_fit_log ADD COLUMN env_category VARCHAR DEFAULT 'transition';
ALTER TABLE strategy_fit_log ADD COLUMN w1_mn1_label VARCHAR DEFAULT '';
```

### 6.3 提醒卡片 JSON

```json
{
  "d1_tags": ["波动稳定", "D1收缩充分", "三周期共振新近形成"],
  "w1_mn1_tag": {
    "env_category": "strong_resonance",
    "label": "大周期共振",
    "description": "月线+周线均扩张有趋势，大小周期全面强势",
    "factor": 1.10
  }
}
```

---

## 7. 用户手册更新

### 7.1 新增 FAQ

```markdown
### Q：大周期标签和 D1 环境标签有什么区别？

A：D1 标签描述信号自身的质量（如"波动稳定"、"收缩后释放"），
大周期标签描述信号运行的背景环境（如"大周期共振"、"双重收缩"）。
两者互补：一个好种子（D1 标签）种在好土壤（大周期标签）里，
成功率最高。

### Q："大周期共振"和"三周期共振新近形成"是一回事吗？

A：不完全一样。"三周期共振新近形成"是 D1 标签，强调三周期同时 E/F 且刚形成。
"大周期共振"是 W1×MN1 标签，强调月线+周线均扩张有趋势（不要求一定是 E/F）。
两者经常同时出现，但不完全重合。
```

### 7.2 标签速查表更新

| D1 标签 | W1×MN1 标签 | 组合含义 | 建议关注度 |
|---------|------------|----------|-----------|
| 三周期共振新近形成 | 大周期共振 | 最强组合：信号质量高 + 土壤最优 | 最高 |
| D1 收缩充分 | 趋势孕育 | VCP 最佳：弹簧压缩 + 大周期酝酿 | 高（VCP） |
| 波动稳定 | 大周期共振 | 2560/Bollinger 优质：稳定 + 强势背景 | 高 |
| 任何 D1 标签 | 双重收缩 | 信号质量再好，土壤不支持也要谨慎 | 低 |
