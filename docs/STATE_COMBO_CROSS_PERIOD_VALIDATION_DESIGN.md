# State 组合跨时间段稳定性验证框架

版本：v1.0
日期：2026-05-23
状态：设计稿
关联脚本：`scripts/search_vcp_optimal_state.py`、`scripts/search_2560_optimal_state.py`、`scripts/search_bollinger_optimal_state.py`
替代文档：`docs/WALK_FORWARD_VALIDATION_DESIGN.md`（传统 WFA，已废弃）

---

## 核心理解

本框架**不是**传统的 Walk-Forward 参数优化。区别：

| 传统 WFA | 本框架 |
|---------|--------|
| 在 IS 窗口内搜索最优参数 | State 组合已固定，不做参数搜索 |
| 在 OOS 窗口验证参数能否适配未来 | 在不同时间段上重复同一套验证逻辑 |
| 目的：找最优参数 | 目的：**检验统计稳定性**——组合在不同时期是否持续有效 |
| 输出：最优参数 + OOS 表现 | 输出：各时间段的指标 + 跨段一致性评估 |

**本质**：市场在不同时期的同一种状态下，策略信号的表现是否一致？

---

## 1. 验证对象

### 1.1 已固定的验证假设

以下假设已由 `search_*_optimal_state.py` 验证通过，本框架检验其跨时间段稳定性：

| 策略 | 固定假设 | 验证状态 |
|------|----------|----------|
| VCP | D1 近 20 日收缩后释放路径 | 路径假设通过初次验证 |
| 2560 | State 组合 {E/E/F, E/F/F, E/F/E} + ma2560_strong_hold | 已固化 |
| Bollinger | D1 volatility_bit=0 优于 volatility_bit=1 | KIMI 候选未通过，vol=0 通过 |

### 1.2 不涉及的操作

- 不做网格搜索
- 不做参数优化
- 不重新选择最优组合
- 不修改验证引擎的分组逻辑

---

## 2. 时间段划分策略

### 2.1 三种划分方案

#### 方案 A：按自然年/半年划分

```python
def split_by_calendar(start: str, end: str, granularity: str = "half_year") -> list[dict]:
    """按自然年或半年划分。"""
    if granularity == "half_year":
        return [
            {"period_id": "2022H1", "start": "2022-01-01", "end": "2022-06-30"},
            {"period_id": "2022H2", "start": "2022-07-01", "end": "2022-12-31"},
            {"period_id": "2023H1", "start": "2023-01-01", "end": "2023-06-30"},
            {"period_id": "2023H2", "start": "2023-07-01", "end": "2023-12-31"},
            {"period_id": "2024H1", "start": "2024-01-01", "end": "2024-06-30"},
            {"period_id": "2024H2", "start": "2024-07-01", "end": "2024-12-31"},
            {"period_id": "2025H1", "start": "2025-01-01", "end": "2025-06-30"},
            {"period_id": "2025H2", "start": "2025-07-01", "end": "2025-12-31"},
        ]
```

#### 方案 B：按市场阶段划分

```python
def split_by_market_phase(start: str, end: str) -> list[dict]:
    """按市场阶段（牛/熊/震荡）划分。"""
    # 读取历史 market_phase 数据，按连续相同阶段分段
    phases = load_market_phase_history(start, end)
    segments = []
    current_phase = None
    current_start = None

    for date, phase in phases:
        if phase != current_phase:
            if current_phase is not None:
                segments.append({
                    "period_id": f"{current_phase}_{current_start}_{date}",
                    "phase": current_phase,
                    "start": current_start,
                    "end": date,
                })
            current_phase = phase
            current_start = date

    return segments
```

阶段映射：

| market_phase | 归类 |
|-------------|------|
| emergence + progression | 牛市（趋势上行） |
| contraction + risk_release | 熊市（趋势下行） |
| extension + undetermined | 震荡/过渡 |

#### 方案 C：滚动固定窗口

```python
def split_by_rolling_window(start: str, end: str,
                            window_months: int = 6,
                            step_months: int = 3) -> list[dict]:
    """滚动固定窗口。"""
    segments = []
    current = parse_date(start)
    period_id = 0

    while True:
        window_end = add_months(current, window_months)
        if window_end > parse_date(end):
            break
        segments.append({
            "period_id": f"window_{period_id}",
            "start": current.isoformat(),
            "end": window_end.isoformat(),
        })
        period_id += 1
        current = add_months(current, step_months)

    return segments
```

### 2.2 推荐方案

**默认使用方案 A（半年划分）**，理由：
- 时间段数量适中（4-6 个段），每个段有足够样本
- 覆盖完整的牛熊周期
- 简单直观，易于解读

方案 B 作为补充——当需要回答"这个组合在牛市和熊市中是否都有效"时使用。

---

## 3. 验证逻辑

### 3.1 每个时间段的独立验证

```python
def validate_in_period(
    period: dict,
    hypothesis: dict,
    all_samples: list[dict],
    window: int = 20,
    n_bootstrap: int = 2000,
) -> dict:
    """在单个时间段内验证固定假设。"""
    # 1. 筛选该时间段内的样本
    period_samples = [s for s in all_samples
                      if period["start"] <= s["date"] <= period["end"]
                      and s.get(f"excess_ret_{window}d") is not None]

    # 2. 应用固定假设条件（与 search 脚本相同的筛选逻辑）
    matched = [s for s in period_samples if hypothesis["condition_fn"](s)]
    outside = [s for s in period_samples if not hypothesis["condition_fn"](s)]

    # 3. 计算统计量 + Bootstrap CI
    matched_row = metric_row("matched", matched, window, n_bootstrap)
    outside_row = metric_row("outside", outside, window, n_bootstrap)

    return {
        "period_id": period["period_id"],
        "period_range": f"{period['start']} to {period['end']}",
        "total_samples": len(period_samples),
        "matched_n": matched_row["n"],
        "outside_n": outside_row["n"],
        "matched_mean_excess": matched_row["mean_excess"],
        "matched_mean_excess_ci": (matched_row["mean_excess_ci_lo"], matched_row["mean_excess_ci_hi"]),
        "matched_win_rate": matched_row["win_rate"],
        "matched_win_rate_ci": (matched_row["win_rate_ci_lo"], matched_row["win_rate_ci_hi"]),
        "matched_t_stat": matched_row["t_stat"],
        "outside_mean_excess": outside_row["mean_excess"],
        "direction_positive": (matched_row["mean_excess"] or 0) > 0,
        "ci_excludes_zero": (matched_row["mean_excess_ci_lo"] or 0) > 0,
    }
```

### 3.2 固定假设条件函数

```python
# VCP 路径假设
def vcp_compression_release(sample: dict) -> bool:
    """D1 近 20 日经历收缩后释放。"""
    d1_since_exit = sample.get("d1_days_since_contraction_exit")
    return d1_since_exit is not None and 0 <= d1_since_exit <= 20

# 2560 State 组合假设
def ma2560_state_match(sample: dict) -> bool:
    """State 组合在适配区间。"""
    combo = f"{sample.get('mn1_state_hex','')}/{sample.get('w1_state_hex','')}/{sample.get('d1_state_hex','')}"
    return combo in {"E/E/F", "E/F/F", "E/F/E"}

# Bollinger 波动稳定假设
def bollinger_vol_stable(sample: dict) -> bool:
    """D1 volatility_bit=0。"""
    return sample.get("d1_volatility_bit") == 0
```

---

## 4. 跨段一致性指标

### 4.1 方向一致性率

```python
def direction_consistency(period_results: list[dict]) -> float:
    """正收益时间段占总时间段的比例。"""
    positive = sum(1 for r in period_results if r["direction_positive"])
    return positive / len(period_results) if period_results else 0.0
```

**标准**：>= 0.6（过半数时间段超额为正）

### 4.2 跨段变异系数

```python
def cross_period_cv(period_results: list[dict]) -> float:
    """跨段超额收益的变异系数。"""
    means = [r["matched_mean_excess"] for r in period_results
             if r["matched_mean_excess"] is not None]
    if len(means) < 2:
        return float("inf")
    return statistics.stdev(means) / abs(statistics.fmean(means)) if statistics.fmean(means) != 0 else float("inf")
```

**标准**：< 1.0（变异系数小于均值的绝对值，说明波动可控）

### 4.3 时间衰减检测

```python
def detect_time_decay(period_results: list[dict]) -> dict:
    """检测最近时间段是否比早期差很多。"""
    if len(period_results) < 3:
        return {"has_decay": False, "reason": "insufficient_periods"}

    early_means = [r["matched_mean_excess"] for r in period_results[:len(period_results)//2]
                   if r["matched_mean_excess"] is not None]
    late_means = [r["matched_mean_excess"] for r in period_results[len(period_results)//2:]
                  if r["matched_mean_excess"] is not None]

    if not early_means or not late_means:
        return {"has_decay": False, "reason": "insufficient_data"}

    early_avg = statistics.fmean(early_means)
    late_avg = statistics.fmean(late_means)
    decay_ratio = late_avg / early_avg if early_avg != 0 else float("inf")

    return {
        "has_decay": decay_ratio < 0.5,  # 后半段不到前半段的一半
        "early_avg": round(early_avg, 4),
        "late_avg": round(late_avg, 4),
        "decay_ratio": round(decay_ratio, 3),
    }
```

**标准**：后半段均值不低于前半段的 50%

### 4.4 综合稳定性评分

```python
def stability_verdict(
    direction_rate: float,
    cv: float,
    decay: dict,
) -> dict:
    """综合稳定性判定。"""
    score = 0.0

    # 方向一致性（权重 0.4）
    if direction_rate >= 0.75:
        score += 0.4
    elif direction_rate >= 0.6:
        score += 0.3
    elif direction_rate >= 0.5:
        score += 0.2

    # 变异系数（权重 0.3）
    if cv < 0.5:
        score += 0.3
    elif cv < 1.0:
        score += 0.2
    elif cv < 1.5:
        score += 0.1

    # 时间衰减（权重 0.3）
    if not decay["has_decay"]:
        score += 0.3
    elif decay.get("decay_ratio", 0) > 0.7:
        score += 0.15

    if score >= 0.7:
        return {"score": round(score, 2), "verdict": "stable", "label": "统计稳定"}
    elif score >= 0.4:
        return {"score": round(score, 2), "verdict": "marginal", "label": "边际稳定"}
    else:
        return {"score": round(score, 2), "verdict": "unstable", "label": "不稳定"}
```

---

## 5. 与现有验证引擎的对接

### 5.1 复用组件

```text
复用 scripts/bootstrap_stats.py：
  - metric_row() — 含 Bootstrap CI
  - bootstrap_mean_ci() — 均值 CI
  - bootstrap_win_rate_ci() — 胜率 CI
  - pct() / fmt_num() — 格式化

复用 scripts/search_*_optimal_state.py：
  - load_vcp_samples() / load_2560_samples() / load_bollinger_samples() — 样本加载
  - 条件函数（收缩后释放、State 组合匹配、volatility_bit）
```

### 5.2 新增脚本

```text
scripts/validate_state_combo_stability.py
```

### 5.3 执行命令

```bash
# 验证 VCP 路径假设的跨段稳定性
python3 scripts/validate_state_combo_stability.py \
  --strategy vcp \
  --hypothesis compression_release_20d \
  --start-date 2022-01-01 \
  --end-date 2026-05-01 \
  --split half_year \
  --foundation-db outputs/p116_foundation_20260521/p116_foundation.duckdb

# 验证 2560 State 组合
python3 scripts/validate_state_combo_stability.py \
  --strategy ma2560 \
  --hypothesis eef_eff_efe \
  --start-date 2022-01-01 \
  --end-date 2026-05-01 \
  --split half_year

# 按市场阶段划分
python3 scripts/validate_state_combo_stability.py \
  --strategy bollinger_bandit \
  --hypothesis vol_bit_zero \
  --start-date 2022-01-01 \
  --end-date 2026-05-01 \
  --split market_phase
```

---

## 6. 报告输出

### 6.1 输出路径

```text
outputs/stability_validation/stability_{strategy}_{hypothesis}_{date}.json
outputs/stability_validation/stability_{strategy}_{hypothesis}_{date}.md
outputs/stability_validation/stability_latest.json
```

### 6.2 Markdown 报告

```markdown
# State 组合稳定性验证 — VCP 收缩后释放路径

- 验证假设：D1 近 20 日收缩后释放
- 总区间：2022-01-01 至 2026-05-01
- 划分方式：半年
- 验证窗口：20 日超额收益

## 各时间段结果

| 时间段 | 匹配样本 | 20d 超额 | 95% CI | 胜率 | 方向 | CI 显著 |
|--------|---------|---------|--------|------|------|---------|
| 2022H1 | 312 | +3.8% | [+1.2%, +6.4%] | 54.2% | ✓ | ✓ |
| 2022H2 | 287 | +2.1% | [-0.5%, +4.7%] | 51.9% | ✓ |   |
| 2023H1 | 398 | +5.2% | [+2.8%, +7.6%] | 57.8% | ✓ | ✓ |
| 2023H2 | 345 | +1.9% | [-0.3%, +4.1%] | 52.5% | ✓ |   |
| 2024H1 | 421 | +4.5% | [+2.1%, +6.9%] | 55.6% | ✓ | ✓ |
| 2024H2 | 367 | +3.1% | [+0.7%, +5.5%] | 53.7% | ✓ | ✓ |
| 2025H1 | 289 | +2.8% | [+0.2%, +5.4%] | 53.3% | ✓ | ✓ |

## 跨段一致性

| 指标 | 值 | 标准 | 判定 |
|------|-----|------|------|
| 方向一致性率 | 7/7 = 100% | >= 60% | ✓ |
| 跨段变异系数 | 0.38 | < 1.0 | ✓ |
| 时间衰减 | 早期 3.7% → 近期 2.8% | 后半 >= 前半×50% | ✓ |
| **综合评分** | **0.90** | **>= 0.7** | **统计稳定** |
```

---

## 附录：与废弃文档的关系

`docs/WALK_FORWARD_VALIDATION_DESIGN.md` 描述的是传统 WFA（IS 内搜索参数 → OOS 验证），适用于未来可能的参数优化场景。本文档是当前实际需要的稳定性验证框架，两者不冲突但适用场景不同。
