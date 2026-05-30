# W1×MN1 环境标签工程实现规范

版本：v1.0
日期：2026-05-23
状态：实现规范
关联设计：`docs/W1_MN1_ENVIRONMENT_LABELS.md`
关联脚本：`scripts/daily_research_brief.py`、`scripts/strategy_reminder_brief.py`

---

## 概述

本规范将 `W1_MN1_ENVIRONMENT_LABELS.md` 的两层标签体系转化为可在现有脚本中直接实现的代码规格。

**改动范围**：

| 文件 | 改动类型 | 新增行数 |
|------|----------|---------|
| `scripts/bootstrap_stats.py` | 新增标签计算函数 | ~60 行 |
| `scripts/strategy_signal_ledger.py` | 信号账本新增字段 | ~15 行 |
| `scripts/strategy_reminder_brief.py` | 提醒卡片新增大周期标签行 | ~30 行 |
| `scripts/daily_research_brief.py` | 总报新增大周期列 + 排序权重 | ~40 行 |

---

## 1. 标签计算函数

### 1.1 放置位置

`scripts/bootstrap_stats.py`（与其他共享统计函数同模块）

### 1.2 核心函数

```python
# scripts/bootstrap_stats.py

# ── W1×MN1 Environment Label ──────────────────────────────────────

# 语义桶定义
W1_MN1_ENV_LABELS = {
    "strong_resonance": {
        "label": "大周期共振",
        "description": "月线+周线均扩张有趋势",
        "color": "#22c55e",  # 绿色
        "priority": 1,
    },
    "trend_gestation": {
        "label": "趋势孕育",
        "description": "周线有趋势但月线收缩",
        "color": "#3b82f6",  # 蓝色
        "priority": 2,
    },
    "week_strong_month_weak": {
        "label": "周强月弱",
        "description": "周线趋势确认但月线未跟上",
        "color": "#f59e0b",  # 黄色
        "priority": 3,
    },
    "month_strong_week_weak": {
        "label": "月强周弱",
        "description": "月线趋势但周线回调中",
        "color": "#f59e0b",  # 黄色
        "priority": 4,
    },
    "double_contraction": {
        "label": "双重收缩",
        "description": "大小周期均收缩",
        "color": "#ef4444",  # 红色
        "priority": 6,
    },
    "transition": {
        "label": "大周期过渡",
        "description": "无明确方向",
        "color": "#6b7280",  # 灰色
        "priority": 5,
    },
}

ENV_CATEGORY_FACTOR = {
    "strong_resonance":       {"vcp": 1.10, "ma2560": 1.12, "bollinger_bandit": 1.10},
    "trend_gestation":        {"vcp": 1.08, "ma2560": 0.98, "bollinger_bandit": 0.95},
    "week_strong_month_weak": {"vcp": 1.00, "ma2560": 1.02, "bollinger_bandit": 1.00},
    "month_strong_week_weak": {"vcp": 0.95, "ma2560": 1.05, "bollinger_bandit": 0.98},
    "double_contraction":     {"vcp": 0.92, "ma2560": 0.88, "bollinger_bandit": 0.90},
    "transition":             {"vcp": 1.00, "ma2560": 1.00, "bollinger_bandit": 1.00},
}


def _is_expansion(score: int | None) -> bool:
    """base=8 判断。"""
    if score is None:
        return False
    return abs(score) >= 8


def _is_trending(score: int | None) -> bool:
    """trend_bit=1 判断。"""
    if score is None:
        return False
    return (abs(score) >> 2) & 1 == 1


def compute_w1_mn1_env_category(
    mn1_state_score: int | None,
    w1_state_score: int | None,
) -> str:
    """
    根据 MN1 和 W1 的 state_score 计算 6 类环境分类。

    参数：
        mn1_state_score: 月线状态分数（0-15 或负值）
        w1_state_score: 周线状态分数（0-15 或负值）

    返回：
        env_category 字符串（6 选 1）

    逻辑：
        1. 提取 base 和 trend 维度
        2. 按优先级匹配 6 类环境
    """
    w1_exp = _is_expansion(w1_state_score)
    w1_trend = _is_trending(w1_state_score)
    mn1_exp = _is_expansion(mn1_state_score)
    mn1_trend = _is_trending(mn1_state_score)

    # 强共振：双扩张+有趋势
    if w1_exp and w1_trend and mn1_exp and mn1_trend:
        return "strong_resonance"

    # 趋势孕育：W1 有趋势但收缩，MN1 收缩或扩张初期
    if (not w1_exp and w1_trend) and (not mn1_exp or not mn1_trend):
        return "trend_gestation"

    # 周强月弱：W1 扩张有趋势，MN1 收缩或无趋势
    if w1_exp and w1_trend and (not mn1_exp or not mn1_trend):
        return "week_strong_month_weak"

    # 月强周弱：MN1 扩张有趋势，W1 收缩或无趋势
    if mn1_exp and mn1_trend and (not w1_exp or not w1_trend):
        return "month_strong_week_weak"

    # 双重收缩
    if not w1_exp and not mn1_exp:
        return "double_contraction"

    return "transition"


def compute_w1_mn1_env_label(
    mn1_state_score: int | None,
    w1_state_score: int | None,
) -> dict:
    """
    完整标签计算。

    返回：
        {
            "env_category": str,
            "label": str,
            "description": str,
            "color": str,
            "priority": int,
        }
    """
    category = compute_w1_mn1_env_category(mn1_state_score, w1_state_score)
    meta = W1_MN1_ENV_LABELS[category]
    return {
        "env_category": category,
        "label": meta["label"],
        "description": meta["description"],
        "color": meta["color"],
        "priority": meta["priority"],
    }


def compute_env_category_factor(
    env_category: str,
    strategy_id: str,
) -> float:
    """大周期环境对策略的调节系数。"""
    return ENV_CATEGORY_FACTOR.get(env_category, {}).get(strategy_id, 1.0)
```

---

## 2. 信号账本字段新增

### 2.1 strategy_signal_daily 表

在 `scripts/strategy_signal_ledger.py` 的 `create_tables()` 中新增：

```python
ensure_column(con, "strategy_signal_daily", "env_category", "VARCHAR DEFAULT 'transition'")
ensure_column(con, "strategy_signal_daily", "w1_mn1_label", "VARCHAR DEFAULT ''")
ensure_column(con, "strategy_signal_daily", "env_category_factor", "DOUBLE DEFAULT 1.0")
```

### 2.2 signal_rows_for_state() 中计算

在 `scripts/strategy_signal_ledger.py` 的 `signal_rows_for_state()` 函数中，组装信号行时新增：

```python
from bootstrap_stats import compute_w1_mn1_env_label, compute_env_category_factor

# 在信号行组装处新增：
mn1_score = row.get("mn1_state_score") or state_hex_to_score(row.get("mn1_state_hex"))
w1_score = row.get("w1_state_score") or state_hex_to_score(row.get("w1_state_hex"))
env_label = compute_w1_mn1_env_label(mn1_score, w1_score)

# 添加到信号行
signal_row["env_category"] = env_label["env_category"]
signal_row["w1_mn1_label"] = env_label["label"]
signal_row["env_category_factor"] = compute_env_category_factor(env_label["env_category"], strategy_id)
```

---

## 3. 提醒卡片展示

### 3.1 build_card() 修改

在 `scripts/strategy_reminder_brief.py` 的 `build_card()` 函数中，返回的 dict 新增：

```python
from bootstrap_stats import compute_w1_mn1_env_label

# 在 build_card() 返回 dict 中新增：
mn1_score = state.get("mn1_state_score")
w1_score = state.get("w1_state_score")
env_label = compute_w1_mn1_env_label(mn1_score, w1_score)

return {
    # ... 现有字段 ...
    "w1_mn1_env": env_label,  # 新增
}
```

### 3.2 HTML 渲染修改

在 `scripts/strategy_reminder_brief.py` 的 HTML 渲染函数中，在 D1 环境标签行下方新增：

```python
def render_w1_mn1_env_row(card: dict) -> str:
    """渲染大周期背景标签行。"""
    env = card.get("w1_mn1_env") or {}
    label = env.get("label", "大周期过渡")
    color = env.get("color", "#6b7280")
    desc = env.get("description", "")

    return (
        f'<td colspan="100%" style="padding:2px 10px;font-size:12px;color:{color};">'
        f'大周期背景：{label}'
        f' <span style="color:#999;">— {desc}</span>'
        f'</td>'
    )
```

### 3.3 卡片展示效果

```text
┌──────────────────────────────────────────────────────────┐
│ 300969 恒帅股份                                           │
│ ──────────────────────────────────────────────────────── │
│ 策略信号：VCP突破确认          适配度：最佳适配           │
│ 生命周期：趋势新生                                        │
│ State 环境：MN1: E  W1: E  D1: E  (ef=3)                 │
│ D1 标签：波动稳定 / D1收缩充分 / 三周期共振新近形成        │
│ 大周期背景：大周期共振 — 月线+周线均扩张有趋势   ← 新增   │
│ 基本面：质量健康 / 现金流健康                              │
│ 统计：收缩后释放路径，20d超额 +1.67%                      │
└──────────────────────────────────────────────────────────┘
```

---

## 4. 总报展示

### 4.1 概览卡片：新增"当前大周期环境"指标

在 `scripts/daily_research_brief.py` 的 `build_market_summary()` 中新增：

```python
def build_w1_mn1_overview(cards: list[dict]) -> dict:
    """统计当日信号的大周期环境分布。"""
    env_counts = Counter()
    for card in cards:
        env = (card.get("w1_mn1_env") or {}).get("env_category", "transition")
        env_counts[env] += 1

    # 找出占比最高的环境
    total = sum(env_counts.values()) or 1
    top_env = env_counts.most_common(1)[0] if env_counts else ("transition", 0)

    return {
        "dominant_env": top_env[0],
        "dominant_env_label": W1_MN1_ENV_LABELS.get(top_env[0], {}).get("label", ""),
        "dominant_env_pct": round(top_env[1] / total * 100, 1),
        "env_distribution": dict(env_counts.most_common()),
    }
```

概览卡片展示：

```text
┌─────────────────┬─────────────────┬─────────────────┐
│  全三 E/F 池    │  最佳适配信号   │  大周期环境     │
│     216 只      │    69 条        │  大周期共振     │
│                 │                 │  占比 45%       │
└─────────────────┴─────────────────┴─────────────────┘
```

### 4.2 聚焦表：新增"大周期背景"列

在 `scripts/daily_research_brief.py` 的 `display_rows()` 排序逻辑和表格渲染中新增：

#### 排序权重修改

```python
# 现有排序（daily_research_brief.py:187-194）
FIT_ORDER = {"最佳适配": 0, "适配": 1, "弱适配": 2, "待观察": 3}
ENV_PRIORITY = {
    "strong_resonance": 0, "trend_gestation": 1,
    "week_strong_month_weak": 2, "month_strong_week_weak": 3,
    "transition": 4, "double_contraction": 5,
}

rows.sort(
    key=lambda card: (
        FIT_ORDER.get(card.get("strategy_environment_fit") or "待观察", 99),
        ENV_PRIORITY.get(
            (card.get("w1_mn1_env") or {}).get("env_category", "transition"), 99
        ),  # 新增：大周期环境优先级排序
        card_industry(card),
        STRATEGY_ORDER.get(card_strategy(card), 99),
        -(float(((card.get("strategy_evaluation") or {}).get("evidence_score") or 0.0))),
        str(card.get("stock_code") or ""),
    )
)
```

#### 表格列新增

在聚焦表的 `<thead>` 和 `<tbody>` 中新增一列：

```python
# 表头新增
"<th>大周期背景</th>"

# 表体新增
env = card.get("w1_mn1_env") or {}
f"<td style='color:{env.get(\"color\", \"#666\")}'>{env.get('label', '-')}</td>"
```

### 4.3 聚焦表展示效果

```text
┌──────────┬────────┬──────────┬──────┬────────────────────┬──────────────┬──────────┐
│ 股票     │ 行业   │ 策略     │ 阶段 │ D1 环境标签        │ 大周期背景   │ 统计     │
├──────────┼────────┼──────────┼──────┼────────────────────┼──────────────┼──────────┤
│ 恒帅股份 │ 汽车   │ VCP      │ 新生 │ 波动稳定/D1收缩充分│ 大周期共振   │ +1.67%   │
│ 科创新源 │ 化工   │ VCP      │ 新生 │ 三周期共振新近形成 │ 趋势孕育     │ +1.67%   │
│ 播恩集团 │ 农牧   │ Bollinger│ 延展 │ 价格突破阻力区间   │ 周强月弱     │ +0.59%   │
│ 信维通信 │ 电子   │ VCP      │ 延展 │ D1收缩充分         │ 双重收缩     │ 待校准   │
└──────────┴────────┴──────────┴──────┴────────────────────┴──────────────┴──────────┘
                                                                         ↑ 新增列
```

颜色编码：大周期共振=绿色，趋势孕育=蓝色，周强月弱/月强周弱=黄色，双重收缩=红色，过渡=灰色。

---

## 5. 策略信号排序规则

### 5.1 排序权重完整定义

```python
# 聚焦表排序（从高优先到低优先）
sort_key = (
    1. FIT_ORDER           — 适配度等级（最佳适配=0 > 适配=1 > 弱适配=2）
    2. ENV_PRIORITY         — 大周期环境（强共振=0 > 趋势孕育=1 > ... > 双重收缩=5）← 新增
    3. card_industry        — 行业名称（字母序）
    4. STRATEGY_ORDER       — 策略类型
    5. evidence_score       — 证据评分（降序）
    6. stock_code           — 股票代码（升序）
)
```

### 5.2 与现有排序的兼容性

新增的 ENV_PRIORITY 是第 2 排序键，只在适配度等级相同时起作用。这意味着：
- 最佳适配 + 大周期共振 > 最佳适配 + 双重收缩
- 适配 + 趋势孕育 > 适配 + 大周期过渡

不影响现有的适配度等级排序主体逻辑。

---

## 6. 与三重共振的衔接

### 6.1 在 strategy_fit_observer 中记录

`scripts/strategy_fit_observer.py` 的 `normalize_row()` 新增：

```python
"w1_mn1_env": row.get("env_category", "transition"),
"w1_mn1_label": row.get("w1_mn1_label", ""),
"env_category_factor": row.get("env_category_factor", 1.0),
```

### 6.2 在三重共振计算中的使用

三重共振增强模型中，env_category_factor 作为 State 维度的附加乘数：

```python
# 三重共振总公式（更新版）
enhanced = base_fit_score × macro_factor × chain_factor × state_factor × phase_factor × env_category_factor
```

env_category_factor 范围 [0.88, 1.12]，是最小幅度的调节因子。

---

## 7. 实施检查清单

```text
□ scripts/bootstrap_stats.py — 新增 compute_w1_mn1_env_category / compute_w1_mn1_env_label / compute_env_category_factor
□ scripts/strategy_signal_ledger.py — ensure_column 新增 env_category / w1_mn1_label / env_category_factor
□ scripts/strategy_signal_ledger.py — signal_rows_for_state() 中调用 compute_w1_mn1_env_label
□ scripts/strategy_reminder_brief.py — build_card() 新增 w1_mn1_env 字段
□ scripts/strategy_reminder_brief.py — HTML 渲染新增大周期背景行
□ scripts/daily_research_brief.py — build_market_summary() 新增大周期环境概览
□ scripts/daily_research_brief.py — display_rows() 排序新增 ENV_PRIORITY
□ scripts/daily_research_brief.py — 聚焦表新增"大周期背景"列
□ scripts/strategy_fit_observer.py — normalize_row() 新增 w1_mn1_env 字段
□ 运行一次完整流水线验证无报错
□ 检查提醒卡片 HTML 渲染效果
□ 检查总报聚焦表排序和颜色编码
```
