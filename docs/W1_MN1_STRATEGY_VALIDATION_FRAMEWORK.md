# W1×MN1 组合 × D1 策略验证框架

版本：v1.0
日期：2026-05-23
状态：设计稿
关联脚本：`scripts/search_vcp_optimal_state.py`、`scripts/search_2560_optimal_state.py`、`scripts/search_bollinger_optimal_state.py`
关联白皮书：`docs/MULTICYCLE_STATE_STRATEGY_WHITEPAPER.md`

---

## 核心思路

当前系统的 State 验证聚焦在 D1 层面。但周线和月线的 State 组合构成了日线策略运行的**大背景环境**。

同一个 D1 策略信号，在不同的 W1×MN1 背景下，表现可能截然不同：

```text
VCP 收缩后释放 + MN1 扩张有趋势 / W1 扩张有趋势 → 大周期共振，成功率可能更高
VCP 收缩后释放 + MN1 收缩无趋势 / W1 收缩无趋势 → 大周期不支持，成功率可能更低
```

本框架将 W1 和 MN1 的 State 组合作为**环境分层变量**，对 D1 策略信号进行分层统计。不改变策略触发逻辑，只在统计层面拆分。

---

## 1. State 编码语义速查

### 1.1 完整 16 状态表

| score | hex | base | trend | position | volatility | 语义标签 |
|-------|-----|------|-------|----------|------------|----------|
| 0 | 0 | 收缩 | 无趋势 | 未突破 | 稳定 | 收缩沉寂 |
| 1 | 1 | 收缩 | 无趋势 | 未突破 | 活跃 | 收缩波动 |
| 2 | 2 | 收缩 | 无趋势 | 突破 | 稳定 | 收缩突破 |
| 3 | 3 | 收缩 | 无趋势 | 突破 | 活跃 | 收缩突破波动 |
| 4 | 4 | 收缩 | 有趋势 | 未突破 | 稳定 | 收缩趋势 |
| 5 | 5 | 收缩 | 有趋势 | 未突破 | 活跃 | 收缩趋势波动 |
| 6 | 6 | 收缩 | 有趋势 | 突破 | 稳定 | 收缩趋势突破 |
| 7 | 7 | 收缩 | 有趋势 | 突破 | 活跃 | 收缩趋势突破波动 |
| 8 | 8 | 扩张 | 无趋势 | 未突破 | 稳定 | 刚扩张 |
| 9 | 9 | 扩张 | 无趋势 | 未突破 | 活跃 | 扩张波动 |
| A | 10 | 扩张 | 无趋势 | 突破 | 稳定 | 扩张突破 |
| B | 11 | 扩张 | 无趋势 | 突破 | 活跃 | 扩张突破波动 |
| C | 12 | 扩张 | 有趋势 | 未突破 | 稳定 | 趋势行进 |
| D | 13 | 扩张 | 有趋势 | 未突破 | 活跃 | 趋势行进波动 |
| E | 14 | 扩张 | 有趋势 | 突破 | 稳定 | 强势突破 |
| F | 15 | 扩张 | 有趋势 | 突破 | 活跃 | 强势突破波动 |

### 1.2 负向状态

带负号的状态（如 -E、-C）表示 D1 收盘价低于该周期支撑位，方向为负。统计时需按绝对值解码 bit，再叠加方向信息。

---

## 2. 语义桶聚合

### 2.1 为什么需要聚合

16×16 = 256 种 W1×MN1 精确组合中，大部分组合样本量不足。需要按语义维度压缩到 20-30 个有意义的类别。

### 2.2 三个聚合维度

#### 维度 A：扩张/收缩（base 维度）

| 桶名 | 条件 | 含义 |
|------|------|------|
| expansion | base=8（score >= 8） | 周期处于扩张态 |
| contraction | base=0（score < 8） | 周期处于收缩态 |

#### 维度 B：趋势有无（trend 维度）

| 桶名 | 条件 | 含义 |
|------|------|------|
| trending | trend_bit=1（score 中 bit2=1） | 有方向趋势 |
| flat | trend_bit=0 | 无方向/平 |

#### 维度 C：E/F 状态（最强状态）

| 桶名 | 条件 | 含义 |
|------|------|------|
| ef | score ∈ {14, 15} | 扩张+有趋势+突破（最强） |
| non_ef | 其他 | 非最强状态 |

### 2.3 聚合后的 W1×MN1 矩阵

按维度 A（base）× 维度 B（trend）组合，得到 4×4 = 16 个主要桶：

| | MN1 收缩无趋势 | MN1 收缩有趋势 | MN1 扩张无趋势 | MN1 扩张有趋势 |
|---|---|---|---|---|
| **W1 收缩无趋势** | 双重收缩沉寂 | 月线趋势孕育 | 周线收缩月线扩张 | 大周期错配 |
| **W1 收缩有趋势** | 月线收缩周线趋势 | 双重收缩趋势 | 周线趋势月线扩张 | 周线收缩月线强趋势 |
| **W1 扩张无趋势** | 周线扩张月线收缩 | 周线扩张月线趋势 | 双重扩张初期 | 月线趋势周线扩张 |
| **W1 扩张有趋势** | 大周期错配 | 月线收缩周线强趋势 | 周线强趋势月线扩张 | **双重扩张趋势** |

**高亮**：右下角（W1 扩张有趋势 × MN1 扩张有趋势）是最强的"大周期共振"背景。

### 2.4 进一步压缩：6 类环境分类

将 16 桶压缩为 6 个有实际交易含义的环境类别：

| 环境类别 | W1 条件 | MN1 条件 | 含义 | 预期对 D1 策略的影响 |
|----------|---------|----------|------|---------------------|
| **强共振** | 扩张+有趋势 | 扩张+有趋势 | 大小周期全面强势 | 三策略均应表现最佳 |
| **趋势孕育** | 收缩+有趋势 | 收缩或扩张初期 | 大周期正在酝酿趋势 | VCP 最佳环境 |
| **周强月弱** | 扩张+有趋势 | 收缩或无趋势 | 周线强但月线不确认 | 2560 可能有效但需谨慎 |
| **月强周弱** | 收缩或无趋势 | 扩张+有趋势 | 月线强但周线在回调 | 2560 回踩可能有效 |
| **双重收缩** | 收缩 | 收缩 | 大小周期均收缩 | 三策略均应表现较差 |
| **过渡/混合** | 其他组合 | 其他组合 | 无明确特征 | 中性参考 |

---

## 3. 分层统计方法

### 3.1 统计流程

```python
def validate_by_w1_mn1_background(
    strategy_id: str,
    d1_samples: list[dict],
    window: int = 20,
    min_samples: int = 20,
    n_bootstrap: int = 2000,
) -> dict:
    """按 W1×MN1 背景分层统计 D1 策略信号表现。"""
    results = []

    for w1_bucket in W1_BUCKETS:
        for mn1_bucket in MN1_BUCKETS:
            # 筛选同时满足 W1 和 MN1 条件的样本
            filtered = [s for s in d1_samples
                        if w1_bucket["condition"](s["w1_state_score"])
                        and mn1_bucket["condition"](s["mn1_state_score"])
                        and s.get(f"excess_ret_{window}d") is not None]

            if len(filtered) < min_samples:
                continue

            row = metric_row(
                f"{w1_bucket['name']}×{mn1_bucket['name']}",
                filtered, window, n_bootstrap
            )
            row["w1_bucket"] = w1_bucket["name"]
            row["mn1_bucket"] = mn1_bucket["name"]
            row["env_category"] = classify_env(w1_bucket, mn1_bucket)
            results.append(row)

    return results
```

### 3.2 桶定义

```python
# 维度 A：base
EXPANSION = lambda score: abs(score) >= 8
CONTRACTION = lambda score: abs(score) < 8

# 维度 B：trend
TRENDING = lambda score: (abs(score) >> 2) & 1 == 1
FLAT = lambda score: (abs(score) >> 2) & 1 == 0

# 维度 C：E/F
IS_EF = lambda score: abs(score) in {14, 15}

W1_BUCKETS = [
    {"name": "W1_扩张有趋势", "condition": lambda s: EXPANSION(s) and TRENDING(s)},
    {"name": "W1_扩张无趋势", "condition": lambda s: EXPANSION(s) and FLAT(s)},
    {"name": "W1_收缩有趋势", "condition": lambda s: CONTRACTION(s) and TRENDING(s)},
    {"name": "W1_收缩无趋势", "condition": lambda s: CONTRACTION(s) and FLAT(s)},
]

MN1_BUCKETS = [
    {"name": "MN1_扩张有趋势", "condition": lambda s: EXPANSION(s) and TRENDING(s)},
    {"name": "MN1_扩张无趋势", "condition": lambda s: EXPANSION(s) and FLAT(s)},
    {"name": "MN1_收缩有趋势", "condition": lambda s: CONTRACTION(s) and TRENDING(s)},
    {"name": "MN1_收缩无趋势", "condition": lambda s: CONTRACTION(s) and FLAT(s)},
]
```

### 3.3 6 类环境分类函数

```python
def classify_env(w1_bucket: dict, mn1_bucket: dict) -> str:
    w1 = w1_bucket["name"]
    mn1 = mn1_bucket["name"]

    # 强共振
    if "扩张有趋势" in w1 and "扩张有趋势" in mn1:
        return "强共振"

    # 趋势孕育
    if "收缩有趋势" in w1 and "收缩" in mn1:
        return "趋势孕育"
    if "收缩有趋势" in w1 and "扩张无趋势" in mn1:
        return "趋势孕育"

    # 周强月弱
    if "扩张有趋势" in w1 and "收缩" in mn1:
        return "周强月弱"

    # 月强周弱
    if "收缩" in w1 and "扩张有趋势" in mn1:
        return "月强周弱"

    # 双重收缩
    if "收缩" in w1 and "收缩" in mn1:
        return "双重收缩"

    return "过渡/混合"
```

---

## 4. 研究假设

### 4.1 通用假设（三策略）

| 假设 | 内容 | 预期结果 |
|------|------|----------|
| H1 | 强共振环境下 D1 策略信号超额 > 双重收缩环境 | 所有策略 |
| H2 | 强共振环境的超额 > 全样本平均超额 | 所有策略 |
| H3 | 双重收缩环境的超额 < 全样本平均超额 | 所有策略 |

### 4.2 VCP 专属假设

| 假设 | 内容 | 预期 |
|------|------|------|
| H4 | 趋势孕育环境下 VCP 超额 >= 强共振环境 | VCP 在趋势酝酿期可能比强趋势期更有效（空间更大） |
| H5 | W1 收缩有趋势 + MN1 收缩有趋势 → VCP 超额最高 | 双重收缩趋势 = 弹簧压缩最充分 |

### 4.3 2560 专属假设

| 假设 | 内容 | 预期 |
|------|------|------|
| H6 | 强共振环境下 2560 超额 > 周强月弱环境 | 2560 需要大周期全面支持 |
| H7 | MN1 E/F + W1 E/F 的 2560 信号超额 > MN1 非 E/F | 与已固化规则一致 |

### 4.4 布林强盗专属假设

| 假设 | 内容 | 预期 |
|------|------|------|
| H8 | 强共振 + D1 vol=0 → 布林强盗超额最高 | 最强背景 + 最佳波动环境 |
| H9 | W1 扩张有趋势环境下布林强盗超额 > W1 收缩环境 | 周线趋势支撑突破延续 |

---

## 5. 输出报告结构

### 5.1 报告章节

每个策略一个章节，包含：

```markdown
# {策略名称} × W1×MN1 背景分层验证

## 1. W1×MN1 收益矩阵

| | MN1 收缩无趋势 | MN1 收缩有趋势 | MN1 扩张无趋势 | MN1 扩张有趋势 |
|---|---|---|---|---|
| W1 收缩无趋势 | +0.2% (n=45) | +1.1% (n=38) | -0.3% (n=22) | +0.8% (n=15) |
| W1 收缩有趋势 | +0.5% (n=52) | +2.8%✓ (n=67) | +0.9% (n=31) | +1.5% (n=28) |
| W1 扩张无趋势 | +0.1% (n=41) | +1.3% (n=55) | +0.6% (n=48) | +1.8%✓ (n=35) |
| W1 扩张有趋势 | -0.2% (n=18) | +1.9%✓ (n=42) | +1.2% (n=39) | **+3.5%✓** (n=86) |

✓ = CI 不包含零（统计显著）
**加粗** = 最高超额

## 2. 6 类环境对比

| 环境类别 | 样本 | 20d 超额 | 95% CI | 胜率 | vs 全样本 |
|----------|------|---------|--------|------|----------|
| 强共振 | 86 | +3.5% | [+1.8%, +5.2%] | 58.1% | +1.8% |
| 趋势孕育 | 109 | +2.8% | [+1.2%, +4.4%] | 55.0% | +1.1% |
| 周强月弱 | 42 | +1.9% | [+0.1%, +3.7%] | 52.4% | +0.2% |
| 月强周弱 | 35 | +1.8% | [-0.2%, +3.8%] | 51.4% | +0.1% |
| 双重收缩 | 45 | +0.2% | [-1.5%, +1.9%] | 46.7% | -1.5% |
| 过渡/混合 | 120 | +0.8% | [-0.3%, +1.9%] | 49.2% | -0.9% |
| **全样本** | **437** | **+1.7%** | | **51.3%** | |

## 3. 矩阵可视化（文本热力图）

20d 超额收益热力图：
高 ████████ +3.5%（强共振）
   ██████   +2.8%（趋势孕育）
   ████     +1.9%（周强月弱）
   ███      +1.8%（月强周弱）
   ██       +1.2%
   █        +0.8%
低 ░        +0.2%（双重收缩）

## 4. 假设验证

| 假设 | 内容 | 结果 |
|------|------|------|
| H1 | 强共振 > 双重收缩 | ✓ (+3.5% vs +0.2%, 差异显著) |
| H2 | 强共振 > 全样本 | ✓ (+3.5% vs +1.7%) |
| H4 | 趋势孕育 >= 强共振 | ✗ (+2.8% < +3.5%) |
```

### 5.2 JSON 输出

```json
{
  "schema_version": "w1_mn1_validation_v1",
  "strategy_id": "vcp",
  "hypothesis": "compression_release_20d",
  "date": "2026-05-23",
  "data_range": "2022-01-01 to 2026-05-01",
  "window": 20,
  "min_samples": 20,
  "total_samples": 437,
  "matrix": [
    {"w1_bucket": "W1_收缩无趋势", "mn1_bucket": "MN1_收缩无趋势", "env_category": "双重收缩", "n": 45, "mean_excess": 0.002, "ci_95": [-0.015, 0.019], "win_rate": 0.467, "significant": false},
    ...
  ],
  "env_summary": [
    {"env_category": "强共振", "n": 86, "mean_excess": 0.035, "ci_95": [0.018, 0.052], "win_rate": 0.581, "significant": true},
    ...
  ],
  "hypothesis_results": [
    {"id": "H1", "description": "强共振 > 双重收缩", "result": "pass", "diff": 0.033, "diff_ci": [0.012, 0.054]},
    ...
  ],
  "research_only": true
}
```

---

## 6. 通过标准

### 6.1 单组合通过标准

| 标准 | 阈值 | 说明 |
|------|------|------|
| 最小样本量 | n >= 20 | 低于此数不进入统计 |
| 超额收益方向 | mean_excess > 0 | 方向正确 |
| 统计显著性 | 95% CI 不包含零 | 排除随机波动 |

### 6.2 环境分层通过标准

| 标准 | 阈值 | 说明 |
|------|------|------|
| 强共振 > 全样本 | diff > 0.5% | 大周期共振有增量价值 |
| 强共振 > 双重收缩 | CI 不重叠 | 环境差异显著 |
| 方向一致性 | 至少 3/6 环境类别超额为正 | 策略不是只在单一环境有效 |

### 6.3 升格标准

从研究结论升格为规则的额外要求：

| 标准 | 阈值 |
|------|------|
| 强共振环境连续 3 个半年段超额为正 | 跨时间段稳定性 |
| 趋势孕育环境 VCP 超额 >= 强共振环境 | 如果 H4 通过，可为 VCP 新增专属环境标签 |
| Bootstrap CI 宽度 < 超额均值的 2 倍 | 估计精度 |

---

## 7. 与现有系统的衔接

### 7.1 新增环境标签

如果验证通过，可在提醒层新增以下标签：

```python
W1_MN1_ENV_TAGS = {
    "强共振": "大周期共振：月线+周线均扩张有趋势",
    "趋势孕育": "大周期趋势酝酿：周线有趋势但仍在收缩",
    "周强月弱": "周线强月线弱：中期强势但长期未确认",
    "月强周弱": "月线强周线弱：长期趋势但中期回调",
    "双重收缩": "大周期收缩：月线+周线均收缩",
    "过渡/混合": "大周期过渡：无明确方向",
}
```

### 7.2 与三重共振的衔接

W1×MN1 环境分类可以作为三重共振模型中 State 维度的细化：

```text
当前：state_direction = positive/neutral/negative（基于 fit_score）
升级：state_direction = positive/neutral/negative + env_category（基于 W1×MN1）

示例：state_direction=positive + env_category=强共振 → "State 强 + 大周期共振"
示例：state_direction=positive + env_category=双重收缩 → "State 强但大周期不支持"
```

### 7.3 与适配度评分的衔接

```python
def env_category_factor(env_category: str, strategy_id: str) -> float:
    """大周期环境对适配度的调节系数。"""
    factors = {
        "强共振":      {"vcp": 1.10, "ma2560": 1.12, "bollinger_bandit": 1.10},
        "趋势孕育":    {"vcp": 1.08, "ma2560": 0.98, "bollinger_bandit": 0.95},
        "周强月弱":    {"vcp": 1.00, "ma2560": 1.02, "bollinger_bandit": 1.00},
        "月强周弱":    {"vcp": 0.95, "ma2560": 1.05, "bollinger_bandit": 0.98},
        "双重收缩":    {"vcp": 0.92, "ma2560": 0.88, "bollinger_bandit": 0.90},
        "过渡/混合":   {"vcp": 1.00, "ma2560": 1.00, "bollinger_bandit": 1.00},
    }
    return factors.get(env_category, {}).get(strategy_id, 1.0)
```

---

## 8. 实施路径

| 阶段 | 任务 | 工作量 |
|------|------|--------|
| 1 | 实现 `scripts/validate_w1_mn1_background.py`（分层统计 + Bootstrap CI） | 1 周 |
| 2 | 接入三个策略的样本加载（复用 search_* 脚本的 load 函数） | 2 天 |
| 3 | 报告渲染（收益矩阵 + 环境对比 + 假设验证） | 2 天 |
| 4 | 首次全量验证（2022-2026，三个策略） | 1 天 |
| 5 | 结果分析 + 环境标签写入（如果通过） | 1 天 |
