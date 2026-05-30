# 市场阶段自动识别框架

版本：v1.0
日期：2026-05-23
状态：设计稿 — 可立即实现
数据依赖：全部来自现有 State 缓存，无需新增数据源

---

## 概述

当前系统的市场阶段判断依赖两个代理指标：全三 E/F 池规模和 State 分布。本文档设计一个系统化的自动分类器，基于已有 State 缓存数据将市场划分为 5 个阶段，为策略选择和三重共振模型提供市场维度信号。

**核心原则**：纯 State 驱动，不依赖宏观数据。所有输入均已存在于 `outputs/state_cache/` 和 `outputs/p116_daily_all_three_ef/`。

---

## 1. 五个市场阶段定义

| 阶段 | 代号 | 核心特征 | 典型持续时间 |
|------|------|----------|-------------|
| 收缩期 | contraction | 市场整体收缩，少数股票勉强维持 E/F | 2-8 周 |
| 趋势新生 | emergence | 从收缩中恢复，E/F 池快速扩大，收缩后释放路径密集 | 1-4 周 |
| 趋势行进 | progression | E/F 池稳定，波动率平稳，趋势健康运行 | 2-12 周 |
| 趋势延展 | extension | 波动率上升，部分股票进入极端状态，行业离散度增大 | 1-6 周 |
| 风险释放 | risk_release | E/F 池急剧收缩，大量股票从 E/F 退出，波动率飙升 | 1-4 周 |

---

## 2. 量化判定条件

### 2.1 四个核心指标

所有指标均从现有 State 缓存计算，无需额外数据。

#### 指标 1：全三 E/F 池规模变化率（pool_change_rate）

```python
def pool_change_rate(date_str: str, lookback: int = 5) -> float:
    """全三 E/F 池近 N 日的规模变化率。"""
    current = load_all_three_ef_count(date_str)      # p116_all_three_ef_{date}.json → total
    previous = load_all_three_ef_count(date_str, lookback_days=lookback)
    if previous == 0:
        return 0.0
    return (current - previous) / previous
```

数据来源：`outputs/p116_daily_all_three_ef/p116_all_three_ef_{date}.json` → `total` 字段

#### 指标 2：市场波动率分布（volatility_distribution）

```python
def market_volatility_ratio(date_str: str) -> float:
    """全市场 D1 volatility_bit=1 的股票占比。"""
    rows = load_state_ef(date_str)  # outputs/state_cache/state_ef_{date}.json
    if not rows:
        return 0.5  # 中性
    vol_active = sum(1 for r in rows if r.get("d1_state_hex") and
                     decode_volatility_bit(r["d1_state_hex"]) == 1)
    return vol_active / len(rows)
```

数据来源：`outputs/state_cache/state_ef_{date}.json` → 逐行解码 `d1_state_hex` 的 volatility bit

#### 指标 3：行业 EF 占比离散度（industry_dispersion）

```python
def industry_ef_dispersion(date_str: str) -> float:
    """各行业 EF 占比的标准差。离散度高说明少数行业独强。"""
    rows = load_market_assets_state(date_str)  # outputs/market_assets_state/
    industry_ef = {}
    for row in rows:
        if row.get("asset_type") != "industry_etf":
            continue
        sw = row.get("sw_l1", "")
        ef = row.get("ef_count", 0)
        industry_ef.setdefault(sw, []).append(1 if ef >= 2 else 0)

    ratios = [sum(v)/len(v) for v in industry_ef.values() if v]
    if len(ratios) < 3:
        return 0.0
    return statistics.stdev(ratios)
```

数据来源：`outputs/market_assets_state/market_assets_state_{date}.json`

#### 指标 4：收缩后释放路径密度（contraction_release_density）

```python
def contraction_release_density(date_str: str, lookback: int = 5) -> float:
    """近 N 日内从收缩态进入扩张态的股票占比。"""
    transitions = load_state_transitions(date_str)  # state_transition_{date}.json
    recent = [t for t in transitions
              if t["period"] == "D1"
              and t["obs_date"] >= date_str_minus(date_str, lookback)
              and abs(t["from_score"]) < 8   # 从收缩
              and abs(t["to_score"]) >= 8]    # 到扩张
    total = load_total_stocks(date_str)
    return len(recent) / max(total, 1)
```

数据来源：`outputs/state_cache/state_transition_{date}.json`

### 2.2 指标历史窗口

每个指标需要近期序列来计算趋势：

| 指标 | 计算窗口 | 数据源 |
|------|----------|--------|
| pool_change_rate | 近 5 日和 20 日 | p116_all_three_ef_{date}.json |
| market_volatility_ratio | 当日值 + 近 5 日均值 | state_ef_{date}.json |
| industry_ef_dispersion | 当日值 + 近 10 日均值 | market_assets_state_{date}.json |
| contraction_release_density | 近 5 日 | state_transition_{date}.json |

---

## 3. 阶段判定规则

### 3.1 判定流程

```python
def classify_market_phase(date_str: str) -> dict:
    pool_5d = pool_change_rate(date_str, lookback=5)
    pool_20d = pool_change_rate(date_str, lookback=20)
    vol_ratio = market_volatility_ratio(date_str)
    vol_ratio_5d_avg = avg_market_volatility_ratio(date_str, lookback=5)
    dispersion = industry_ef_dispersion(date_str)
    release_density = contraction_release_density(date_str, lookback=5)
    pool_size = load_all_three_ef_count(date_str)

    phase = _classify(pool_5d, pool_20d, vol_ratio, vol_ratio_5d_avg,
                      dispersion, release_density, pool_size)
    return phase
```

### 3.2 判定规则表

按优先级从高到低匹配（先匹配到的阶段生效）：

| 优先级 | 阶段 | 条件 | 核心逻辑 |
|--------|------|------|----------|
| 1 | risk_release | pool_5d <= -20% AND vol_ratio > vol_ratio_5d_avg + 0.10 | E/F 池急缩 + 波动飙升 |
| 2 | contraction | pool_size < 50 OR (pool_20d <= -30% AND pool_5d <= -5%) | 池极小或持续萎缩 |
| 3 | emergence | release_density >= 0.05 AND pool_5d > 10% AND pool_size >= 50 | 密集收缩后释放 + 池快速扩大 |
| 4 | extension | vol_ratio >= 0.45 OR dispersion >= 0.25 | 波动率偏高或行业极度分化 |
| 5 | progression | pool_size >= 80 AND pool_5d between -10% and +15% AND vol_ratio < 0.45 | 池稳定 + 波动平稳 |
| 6 | 未分类 | 以上均不满足 | 标记为 "undetermined" |

### 3.3 判定函数

```python
def _classify(pool_5d, pool_20d, vol_ratio, vol_5d_avg,
              dispersion, release_density, pool_size):

    # 优先级 1：风险释放
    if pool_5d <= -0.20 and vol_ratio > vol_5d_avg + 0.10:
        return "risk_release"

    # 优先级 2：收缩期
    if pool_size < 50 or (pool_20d <= -0.30 and pool_5d <= -0.05):
        return "contraction"

    # 优先级 3：趋势新生
    if release_density >= 0.05 and pool_5d > 0.10 and pool_size >= 50:
        return "emergence"

    # 优先级 4：趋势延展
    if vol_ratio >= 0.45 or dispersion >= 0.25:
        return "extension"

    # 优先级 5：趋势行进
    if pool_size >= 80 and -0.10 <= pool_5d <= 0.15 and vol_ratio < 0.45:
        return "progression"

    return "undetermined"
```

### 3.4 阈值参数配置

```json
// config/market_phase_thresholds.json
{
  "schema_version": "market_phase_v1",
  "risk_release": {
    "pool_5d_drop": -0.20,
    "vol_spike_over_avg": 0.10
  },
  "contraction": {
    "pool_size_min": 50,
    "pool_20d_drop": -0.30,
    "pool_5d_drop": -0.05
  },
  "emergence": {
    "release_density_min": 0.05,
    "pool_5d_growth_min": 0.10,
    "pool_size_min": 50
  },
  "extension": {
    "vol_ratio_high": 0.45,
    "dispersion_high": 0.25
  },
  "progression": {
    "pool_size_min": 80,
    "pool_5d_range": [-0.10, 0.15],
    "vol_ratio_max": 0.45
  }
}
```

---

## 4. 市场阶段对策略选择的指导映射

### 4.1 策略适配矩阵

| 市场阶段 | VCP | 2560 | 布林强盗 | 指导理由 |
|----------|-----|------|---------|----------|
| 收缩期 | 弱适配 | 不适配 | 不适配 | 趋势稀缺，VCP 可观察但不急于入场 |
| 趋势新生 | **最佳适配** | 适配 | 弱适配 | 收缩后释放密集，VCP 的主场 |
| 趋势行进 | 适配 | **最佳适配** | 适配 | 趋势稳定运行，2560 回踩质量高 |
| 趋势延展 | 弱适配 | 适配 | **最佳适配** | 波动放大，布林强盗突破概率高 |
| 风险释放 | 不适配 | 弱适配 | 不适配 | 趋势反转，以防守为主 |

### 4.2 市场阶段加成系数

基于市场阶段对各策略的适配度提供额外加成：

```python
MARKET_PHASE_FACTORS = {
    "contraction":     {"vcp": 0.90, "ma2560": 0.80, "bollinger_bandit": 0.80},
    "emergence":       {"vcp": 1.15, "ma2560": 1.00, "bollinger_bandit": 0.90},
    "progression":     {"vcp": 1.00, "ma2560": 1.10, "bollinger_bandit": 1.00},
    "extension":       {"vcp": 0.90, "ma2560": 1.00, "bollinger_bandit": 1.15},
    "risk_release":    {"vcp": 0.80, "ma2560": 0.90, "bollinger_bandit": 0.80},
    "undetermined":    {"vcp": 1.00, "ma2560": 1.00, "bollinger_bandit": 1.00},
}
```

### 4.3 典型阶段特征描述

用于报告展示的标准化语言：

```python
PHASE_DESCRIPTIONS = {
    "contraction": {
        "label": "收缩期",
        "summary": "市场整体收缩，全三 E/F 池规模偏小，多数股票处于收缩态。",
        "strategy_hint": "以观察为主，关注收缩充分后可能释放的标的。"
    },
    "emergence": {
        "label": "趋势新生",
        "summary": "市场从收缩中恢复，全三 E/F 池快速扩大，收缩后释放路径密集。",
        "strategy_hint": "重点关注 VCP 类支点突破信号。"
    },
    "progression": {
        "label": "趋势行进",
        "summary": "趋势稳定运行，全三 E/F 池规模平稳，波动率处于舒适区间。",
        "strategy_hint": "重点关注 2560 类趋势回踩确认信号。"
    },
    "extension": {
        "label": "趋势延展",
        "summary": "波动率上升或行业极度分化，趋势进入加速或过热阶段。",
        "strategy_hint": "关注布林强盗类波动突破信号，同时警惕反转风险。"
    },
    "risk_release": {
        "label": "风险释放",
        "summary": "全三 E/F 池急剧收缩，波动率飙升，市场进入风险释放阶段。",
        "strategy_hint": "以防守为主，减少新开仓，关注已有持仓的出场信号。"
    },
}
```

---

## 5. 与三重共振模型的衔接

### 5.1 市场阶段在三重共振中的定位

三重共振模型（`TRIPLE_RESONANCE_ENHANCEMENT.md`）的三个维度：

```text
维度 1: 宏观（MACRO_SCORING_MODEL.md）
维度 2: 产业链（chain_prosperity_scoring_model.md）
维度 3: State 环境（strategy_environment_fit_scoring_design.md）
```

市场阶段是 **State 维度的补充信息**，不作为独立的第四维度，而是用于调节 State 维度的置信度和方向判定。

### 5.2 市场阶段对 State 方向的调节

```python
def state_direction_with_phase(strategy_id: str, fit_score: float,
                                market_phase: str) -> tuple[str, str]:
    """市场阶段调节后的 State 方向判定。"""
    base_dir = state_direction(strategy_id, fit_score)  # 原始方向

    # 市场阶段与策略的最佳阶段一致时，增强方向
    best_phase = {
        "vcp": "emergence",
        "ma2560": "progression",
        "bollinger_bandit": "extension",
    }.get(strategy_id)

    if market_phase == best_phase and base_dir == "positive":
        return "positive", "strong"  # 强化正面
    elif market_phase == "risk_release":
        if base_dir == "positive":
            return "neutral", "downgraded"  # 风险释放期降级正面信号
    elif market_phase == "contraction":
        if base_dir == "positive":
            return "neutral", "downgraded"  # 收缩期降级正面信号

    return base_dir, "normal"
```

### 5.3 市场阶段对共振加成的调节

在 `TRIPLE_RESONANCE_ENHANCEMENT.md` 的总公式中新增市场阶段因子：

```text
enhanced = base × macro_factor × chain_factor × state_factor × phase_factor
```

```python
def phase_factor(market_phase: str, strategy_id: str) -> float:
    """市场阶段对策略的加成系数。"""
    return MARKET_PHASE_FACTORS.get(market_phase, {}).get(strategy_id, 1.0)
```

phase_factor 的范围与 state_factor 类似（0.80-1.15），作为乘积的一部分。

### 5.4 市场阶段变化的过渡处理

市场阶段不是瞬间切换的，需要平滑过渡：

```python
def smooth_phase_transition(current_phase: str, previous_phase: str,
                            days_in_phase: int) -> str:
    """阶段切换时的平滑处理。"""
    if current_phase == previous_phase:
        return current_phase

    # 新阶段需持续 2 天以上才确认切换
    if days_in_phase < 2:
        return previous_phase  # 保持前一阶段

    return current_phase
```

---

## 6. 输出格式

### 6.1 每日市场阶段快照

```json
// outputs/market_phase/market_phase_{date}.json
{
  "schema_version": "market_phase_v1",
  "date": "2026-05-23",
  "generated_at": "2026-05-23T07:00:00+00:00",
  "market_phase": "progression",
  "phase_label": "趋势行进",
  "phase_summary": "趋势稳定运行，全三 E/F 池规模平稳，波动率处于舒适区间。",
  "confidence": 0.82,
  "indicators": {
    "pool_size": 216,
    "pool_change_rate_5d": 0.05,
    "pool_change_rate_20d": 0.18,
    "volatility_ratio": 0.32,
    "volatility_ratio_5d_avg": 0.30,
    "industry_dispersion": 0.15,
    "contraction_release_density": 0.02
  },
  "phase_history": {
    "current_phase_days": 12,
    "previous_phase": "emergence",
    "phase_sequence_30d": ["contraction", "contraction", "emergence", "emergence", "progression"]
  },
  "strategy_implications": {
    "vcp": {"fit": "适配", "factor": 1.00},
    "ma2560": {"fit": "最佳适配", "factor": 1.10},
    "bollinger_bandit": {"fit": "适配", "factor": 1.00}
  },
  "research_only": true
}
```

### 6.2 与 strategy_signal_daily 的衔接

在 `strategy_signal_daily` 表中新增字段：

```sql
ALTER TABLE strategy_signal_daily ADD COLUMN market_phase VARCHAR DEFAULT 'undetermined';
ALTER TABLE strategy_signal_daily ADD COLUMN phase_factor DOUBLE DEFAULT 1.0;
```

---

## 7. 置信度计算

```python
def phase_confidence(indicators: dict, phase: str) -> float:
    """市场阶段判定的置信度。"""
    # 指标越极端，置信度越高
    pool_5d = abs(indicators["pool_change_rate_5d"])
    vol = indicators["volatility_ratio"]
    dispersion = indicators["industry_dispersion"]

    # 各指标对各阶段的判定强度
    strength = 0.0
    if phase == "contraction":
        strength = min(1.0, (50 - indicators["pool_size"]) / 30) if indicators["pool_size"] < 80 else 0.3
    elif phase == "emergence":
        strength = min(1.0, indicators["contraction_release_density"] / 0.08)
    elif phase == "progression":
        strength = 1.0 - abs(indicators["pool_change_rate_5d"]) / 0.15
    elif phase == "extension":
        strength = min(1.0, max(vol - 0.35, dispersion - 0.15) / 0.15)
    elif phase == "risk_release":
        strength = min(1.0, pool_5d / 0.25)

    # 阶段持续天数加成
    duration_bonus = min(0.2, indicators.get("current_phase_days", 0) * 0.02)

    return round(min(1.0, max(0.3, strength * 0.8 + duration_bonus)), 2)
```

---

## 8. 实现脚本

### 8.1 新增脚本

```text
scripts/classify_market_phase.py
```

### 8.2 执行命令

```bash
# 每日分类
python3 scripts/classify_market_phase.py --date 2026-05-23

# 回溯生成历史阶段
python3 scripts/classify_market_phase.py --start-date 2025-06-01 --end-date 2026-05-23

# 仅检查不写入
python3 scripts/classify_market_phase.py --date 2026-05-23 --dry-run
```

### 8.3 输出路径

```text
outputs/market_phase/market_phase_{date}.json
outputs/market_phase/market_phase_latest.json
outputs/market_phase/market_phase_history.json  （近 60 日阶段序列）
public/market_phase_latest.html
```

### 8.4 在每日流水线中的位置

```text
收盘后流水线：
  1. build_state_cache
  2. classify_market_phase          ← 新增，在策略信号之前
  3. build_strategy_signal_ledger（消费 market_phase）
  4. build_macro_chain_prior
  5. build_strategy_fit_observer
  6. daily_research_brief --mode chief（展示市场阶段）
```

---

## 附录 A：历史回测验证方法

```python
def validate_phase_returns(start_date: str, end_date: str):
    """验证各市场阶段下策略的超额收益是否符合预期。"""
    for date in trading_dates(start_date, end_date):
        phase = load_market_phase(date)
        signals = load_signals(date)
        for signal in signals:
            excess = compute_forward_excess(signal, windows=[5, 10, 20])
            record(signal["strategy_id"], phase, excess)
    # 汇总：策略 × 阶段 → 平均超额、胜率、t-stat
```

验证通过标准：各策略在其"最佳适配"阶段的超额收益应显著高于其他阶段。

---

## 附录 B：与现有 all_three_ef_diff 的关系

`outputs/p116_daily_all_three_ef/p116_all_three_ef_diff_{date}.json` 已包含每日 entered/left/stayed 统计。市场阶段判定可直接消费这些 diff 数据：

```python
def pool_change_from_diff(date_str: str) -> tuple[int, int, int]:
    """从 diff 文件读取池变化。"""
    diff = load_json(f"p116_all_three_ef_diff_{ymd(date_str)}.json")
    entered = len(diff.get("entered", []))
    left = len(diff.get("left", []))
    stayed = len(diff.get("stayed", []))
    return entered, left, stayed
```

`entered - left` 即为池的净变化，可直接用于 pool_change_rate 计算。
