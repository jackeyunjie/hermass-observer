# 策略绩效归因分析框架

版本：v1.0
日期：2026-05-23
状态：设计稿 — 可立即实现
数据依赖：全部来自现有前向观察账本和策略评估输出

---

## 概述

当策略信号产生超额收益或亏损时，需要系统性地回答一个问题：**这个结果归功于/归咎于什么？**

本框架将策略绩效归因到五个维度，帮助理解信号质量的来源，并为校准层提供权重调整依据。

```text
总超额收益 = State 环境贡献 + 市场阶段贡献 + 产业链景气贡献 + 宏观环境贡献 + 策略自身贡献 + 残差
```

---

## 1. 归因维度定义

### 1.1 五个归因维度

| 维度 | 归因对象 | 数据来源 | 可解释的问题 |
|------|----------|----------|-------------|
| State 环境 | 三周期 State 组合、适配度等级 | strategy_fit_log | "这个信号在正确的 State 环境下触发了吗？" |
| 市场阶段 | 全市场 E/F 池规模、波动率 | market_phase_{date}.json | "市场整体处于什么阶段？" |
| 产业链景气 | 行业景气度、ETF 共振 | industry_position + market_assets_state | "所在产业链是否支持？" |
| 宏观环境 | 象限、四维评分 | macro_chain_prior | "宏观背景是否有利？" |
| 策略自身 | 信号类型、信号强度、路径条件 | strategy_signal_daily | "策略规则本身捕捉到了什么？" |

### 1.2 归因模型

```text
excess_return_i = α + β_state × X_state_i + β_phase × X_phase_i
                + β_chain × X_chain_i + β_macro × X_macro_i
                + β_signal × X_signal_i + ε_i
```

其中：
- `excess_return_i`：信号 i 的 N 日超额收益
- `X_*`：各维度的特征向量
- `β_*`：归因权重（由历史数据回归得到）
- `ε`：残差（策略自身贡献 + 噪声）

---

## 2. 各维度特征编码

### 2.1 State 环境特征

```python
STATE_FEATURES = {
    "ef_count": "三周期中 E/F 的数量 (0-3)",
    "fit_score": "适配度评分 (0-100)",
    "lifecycle_stage_encoded": "生命周期阶段编码 (0-3)",
    "state_combo_type": "State 组合类型 (0-3)",
    "d1_ef_duration": "D1 E/F 持续天数",
    "d1_volatility_bit": "D1 波动率位 (0/1)",
}
```

编码方式：

| 特征 | 编码方法 | 取值范围 |
|------|----------|----------|
| ef_count | 直接使用 | 0, 1, 2, 3 |
| fit_score | min-max 归一化到 [0, 1] | 0.0-1.0 |
| lifecycle_stage | 有序编码：未知=0, 新生=1, 行进=2, 延展=3 | 0-3 |
| state_combo_type | 已验证组合=3, 模糊匹配=2, 单 bit=1, 不匹配=0 | 0-3 |
| d1_ef_duration | log(1 + days) / log(1 + 60) | 0.0-1.0 |
| d1_volatility_bit | 直接使用 | 0, 1 |

### 2.2 市场阶段特征

```python
PHASE_FEATURES = {
    "market_phase_encoded": "市场阶段编码 (0-4)",
    "pool_size_normalized": "E/F 池规模归一化",
    "pool_change_5d": "池规模 5 日变化率",
    "volatility_ratio": "全市场波动率占比",
}
```

编码方式：

| 特征 | 编码方法 | 取值范围 |
|------|----------|----------|
| market_phase | 有序编码：contraction=0, emergence=1, progression=2, extension=3, risk_release=4 | 0-4 |
| pool_size | pool_size / 500（A 股上限约 5000 只，E/F 池上限约 500） | 0.0-1.0 |
| pool_change_5d | 直接使用 | -1.0-1.0 |
| volatility_ratio | 直接使用 | 0.0-1.0 |

### 2.3 产业链景气特征

```python
CHAIN_FEATURES = {
    "chain_prosperity_normalized": "产业链景气度归一化 (0-1)",
    "chain_position_encoded": "产业链位置编码 (0-3)",
    "etf_ef_count": "行业 ETF 的 ef_count",
    "market_match_level_encoded": "市场匹配等级编码 (0-3)",
}
```

编码方式：

| 特征 | 编码方法 | 取值范围 |
|------|----------|----------|
| chain_prosperity | prosperity_score / 10.0 | 0.0-1.0 |
| chain_position | 上游=0, 中游=1, 下游=2, 综合/配套=3 | 0-3 |
| etf_ef_count | 直接使用 | 0, 1, 2, 3 |
| market_match_level | full_match=3, stock_only=2, market_unsupported=1, not_match=0 | 0-3 |

### 2.4 宏观环境特征

```python
MACRO_FEATURES = {
    "macro_score_normalized": "宏观评分归一化 (0-1)",
    "quadrant_encoded": "宏观象限编码 (0-3)",
    "strategy_macro_adj": "策略专属宏观加成 [-15, +15]",
    "macro_confidence": "宏观置信度 (0-1)",
}
```

编码方式：

| 特征 | 编码方法 | 取值范围 |
|------|----------|----------|
| macro_score | macro_prior.score_0_10 / 10.0 | 0.0-1.0 |
| quadrant | 复苏=0, 过热=1, 衰退=2, 滞胀=3 | 0-3 |
| strategy_macro_adj | (adj + 15) / 30 | 0.0-1.0 |
| macro_confidence | 直接使用 | 0.0-1.0 |

### 2.5 策略自身特征

```python
SIGNAL_FEATURES = {
    "signal_type_encoded": "信号类型编码 (0-3)",
    "signal_strength": "信号强度 (0-1)",
    "path_condition_met": "路径条件是否满足 (0/1)",
    "strategy_id_encoded": "策略编码 (0-2)",
}
```

---

## 3. 归因计算方法

### 3.1 简化归因法（立即可用）

基于分组对比的简化归因，不需要回归分析：

```python
def simple_attribution(observations: list[dict], dimension: str,
                       feature: str, window: int = 20) -> dict:
    """简化归因：按某维度分组，比较各组的平均超额收益。"""
    groups = {}
    for obs in observations:
        key = obs.get(feature)
        if key is None:
            continue
        groups.setdefault(key, []).append(obs.get(f"forward_excess_return_{window}d"))

    result = {}
    for key, returns in groups.items():
        valid = [r for r in returns if r is not None]
        if valid:
            result[str(key)] = {
                "mean_excess": round(sum(valid) / len(valid), 4),
                "win_rate": round(sum(1 for r in valid if r > 0) / len(valid), 4),
                "count": len(valid),
            }

    return {
        "dimension": dimension,
        "feature": feature,
        "window": window,
        "groups": result,
        "attribution_strength": compute_attribution_strength(result),
    }
```

### 3.2 各维度归因计算

#### State 维度归因

```python
def state_attribution(observations: list[dict]) -> dict:
    """State 维度归因。"""
    return {
        "by_fit_level": simple_attribution(observations, "state", "strategy_environment_fit"),
        "by_lifecycle": simple_attribution(observations, "state", "lifecycle_stage"),
        "by_ef_count": simple_attribution(observations, "state", "ef_count"),
        "by_volatility": simple_attribution(observations, "state", "d1_volatility_bit"),
    }
```

#### 市场阶段归因

```python
def phase_attribution(observations: list[dict]) -> dict:
    """市场阶段归因。"""
    return {
        "by_market_phase": simple_attribution(observations, "phase", "market_phase"),
        "by_pool_size_bucket": simple_attribution(observations, "phase", "pool_size_bucket"),
    }
```

#### 产业链归因

```python
def chain_attribution(observations: list[dict]) -> dict:
    """产业链维度归因。"""
    return {
        "by_chain_prosperity": simple_attribution(observations, "chain", "chain_prosperity_bucket"),
        "by_chain_position": simple_attribution(observations, "chain", "chain_position"),
        "by_market_match": simple_attribution(observations, "chain", "ma2560_market_match_level"),
    }
```

#### 宏观归因

```python
def macro_attribution(observations: list[dict]) -> dict:
    """宏观维度归因。"""
    return {
        "by_quadrant": simple_attribution(observations, "macro", "macro_quadrant"),
        "by_macro_score_bucket": simple_attribution(observations, "macro", "macro_score_bucket"),
    }
```

#### 策略自身归因

```python
def strategy_attribution(observations: list[dict]) -> dict:
    """策略自身归因。"""
    return {
        "by_strategy": simple_attribution(observations, "strategy", "strategy_id"),
        "by_signal_type": simple_attribution(observations, "strategy", "signal_type"),
        "by_signal_strength_bucket": simple_attribution(observations, "strategy", "signal_strength_bucket"),
    }
```

### 3.3 归因强度指标

衡量某个维度对超额收益的解释力：

```python
def compute_attribution_strength(group_stats: dict) -> float:
    """计算某维度的归因强度（组间方差 / 总方差的近似）。"""
    means = [g["mean_excess"] for g in group_stats.values() if g["count"] >= 5]
    if len(means) < 2:
        return 0.0
    between_var = statistics.variance(means)
    # 归因强度：组间方差越大，该维度解释力越强
    return round(min(1.0, between_var * 100), 4)  # 粗略缩放
```

---

## 4. 归因报告格式

### 4.1 单信号归因卡片

```python
def build_signal_attribution(obs: dict, window: int = 20) -> dict:
    """为单个信号构建归因卡片。"""
    excess = obs.get(f"forward_excess_return_{window}d")
    if excess is None:
        return {"status": "pending_future_data"}

    return {
        "stock_code": obs["stock_code"],
        "strategy_id": obs["strategy_id"],
        "signal_date": obs["date"],
        "excess_return": excess,
        "outcome": "positive" if excess > 0 else "negative",
        "attribution": {
            "state": {
                "fit_level": obs["strategy_environment_fit"],
                "lifecycle": obs["lifecycle_stage"],
                "ef_count": obs["ef_count"],
                "contribution": classify_contribution("state", obs),
            },
            "phase": {
                "market_phase": obs.get("market_phase", "unknown"),
                "contribution": classify_contribution("phase", obs),
            },
            "chain": {
                "prosperity": obs.get("chain_prosperity"),
                "position": obs.get("chain_position"),
                "contribution": classify_contribution("chain", obs),
            },
            "macro": {
                "quadrant": obs.get("macro_quadrant"),
                "contribution": classify_contribution("macro", obs),
            },
            "signal": {
                "strength": obs["signal_strength"],
                "type": obs["signal_type"],
                "contribution": classify_contribution("signal", obs),
            },
        },
        "primary_driver": identify_primary_driver(obs, excess),
        "residual": compute_residual(obs, excess),
    }
```

### 4.2 贡献分类

```python
def classify_contribution(dimension: str, obs: dict) -> str:
    """判断某维度对本次结果的贡献方向。"""
    # 简化规则：基于该维度的条件是否"有利"
    if dimension == "state":
        fit = obs.get("strategy_environment_fit")
        if fit == "最佳适配":
            return "positive"
        elif fit in ("弱适配", "不适配"):
            return "negative"
        return "neutral"

    elif dimension == "phase":
        phase = obs.get("market_phase", "undetermined")
        strategy = obs.get("strategy_id")
        best = {"vcp": "emergence", "ma2560": "progression", "bollinger_bandit": "extension"}
        if phase == best.get(strategy):
            return "positive"
        elif phase in ("contraction", "risk_release"):
            return "negative"
        return "neutral"

    # ... 其他维度类似
    return "neutral"
```

### 4.3 主要驱动因子识别

```python
def identify_primary_driver(obs: dict, excess: float) -> str:
    """识别本次结果的主要驱动因子。"""
    contributions = []

    # 检查各维度的贡献方向与结果方向是否一致
    for dim in ["state", "phase", "chain", "macro", "signal"]:
        contrib = classify_contribution(dim, obs)
        if (contrib == "positive" and excess > 0) or (contrib == "negative" and excess < 0):
            contributions.append(dim)

    if not contributions:
        return "residual"  # 无法归因到已知维度

    # 返回贡献最大的维度（简化：返回第一个匹配的）
    return contributions[0]
```

---

## 5. 批量归因分析

### 5.1 全量归因报告

```python
def build_attribution_report(start_date: str, end_date: str) -> dict:
    """构建区间内的全量归因报告。"""
    observations = load_forward_observations(start_date, end_date)
    labeled = [o for o in observations if o.get("label_status") == "labeled"]

    return {
        "schema_version": "attribution_report_v1",
        "period": {"start": start_date, "end": end_date},
        "total_labeled": len(labeled),
        "overall": {
            "mean_excess_20d": mean(o["forward_excess_return_20d"] for o in labeled),
            "win_rate_20d": sum(1 for o in labeled if o["forward_excess_return_20d"] > 0) / len(labeled),
        },
        "attribution_by_dimension": {
            "state": state_attribution(labeled),
            "phase": phase_attribution(labeled),
            "chain": chain_attribution(labeled),
            "macro": macro_attribution(labeled),
            "signal": strategy_attribution(labeled),
        },
        "attribution_strengths": {
            "state": compute_dimension_strength(labeled, "state"),
            "phase": compute_dimension_strength(labeled, "phase"),
            "chain": compute_dimension_strength(labeled, "chain"),
            "macro": compute_dimension_strength(labeled, "macro"),
            "signal": compute_dimension_strength(labeled, "signal"),
        },
        "ranked_drivers": rank_drivers(labeled),
        "research_only": True,
    }
```

### 5.2 驱动因子排名

```python
def rank_drivers(observations: list[dict]) -> list[dict]:
    """按归因强度排名各驱动因子。"""
    drivers = []
    for dim, feat in [
        ("state", "strategy_environment_fit"),
        ("state", "lifecycle_stage"),
        ("phase", "market_phase"),
        ("chain", "chain_prosperity_bucket"),
        ("macro", "macro_quadrant"),
        ("signal", "strategy_id"),
    ]:
        result = simple_attribution(observations, dim, feat)
        drivers.append({
            "dimension": dim,
            "feature": feat,
            "attribution_strength": result["attribution_strength"],
            "best_group": max(result["groups"].items(),
                            key=lambda x: x[1]["mean_excess"])[0] if result["groups"] else None,
        })

    return sorted(drivers, key=lambda d: d["attribution_strength"], reverse=True)
```

---

## 6. 与校准层的衔接

### 6.1 归因结果驱动权重调整

归因分析的直接应用是为校准层提供权重调整依据：

```python
def compute_weight_adjustments(attribution_report: dict) -> dict:
    """基于归因分析计算维度权重调整建议。"""
    strengths = attribution_report["attribution_strengths"]
    total = sum(strengths.values()) or 1.0

    return {
        "recommended_weights": {
            dim: round(strength / total, 4)
            for dim, strength in strengths.items()
        },
        "current_weights": {
            "state": 0.35,
            "phase": 0.15,
            "chain": 0.20,
            "macro": 0.15,
            "signal": 0.15,
        },
        "adjustment_needed": abs(sum(strengths.values()) - 1.0) > 0.1,
    }
```

### 6.2 归因异常检测

```python
def detect_attribution_anomalies(report: dict) -> list[str]:
    """检测归因异常。"""
    warnings = []

    # 检查：最佳适配信号是否确实跑赢
    state_data = report["attribution_by_dimension"]["state"]["by_fit_level"]
    best = state_data.get("groups", {}).get("最佳适配", {})
    worst = state_data.get("groups", {}).get("不适配", {})

    if best and worst:
        if best["mean_excess"] < worst["mean_excess"]:
            warnings.append("异常：最佳适配信号平均超额低于不适配信号，适配度排序可能失效")

    # 检查：残差占比是否过高
    residual_ratio = report.get("residual_ratio", 0)
    if residual_ratio > 0.6:
        warnings.append(f"残差占比 {residual_ratio:.0%}，超过 60%，存在未被捕捉的因子")

    return warnings
```

---

## 7. 输出格式

### 7.1 输出路径

```text
outputs/attribution/attribution_report_{date}.json
outputs/attribution/attribution_report_{start}_{end}.json
outputs/attribution/attribution_latest.json
```

### 7.2 每日流水线位置

```text
收盘后流水线：
  1. build_state_cache
  2. classify_market_phase
  3. build_strategy_signal_ledger
  4. build_forward_observation_ledger（更新收益标签）
  5. build_attribution_report                  ← 新增
  6. build_strategy_fit_observer（消费归因结果）
  7. daily_research_brief --mode chief
```

---

## 附录：归因示例

### 示例 1：正超额信号归因

```text
信号：002049 紫光国微 | VCP突破确认 | 2026-04-15
20 日超额：+8.5%

归因：
  State（主要驱动）：最佳适配（fit_score=88），三周期 E/E/F → 贡献 positive
  市场阶段（次要驱动）：趋势新生，VCP 最佳阶段 → 贡献 positive
  产业链景气：AI 算力链 8.2/10，景气上行 → 贡献 positive
  宏观环境：复苏象限，流动性充裕 → 贡献 positive
  策略自身：vcp_breakout，signal_strength=0.85 → 贡献 positive

主要驱动因子：State 环境（适配度排序有效）
共振状态：三重共振
```

### 示例 2：负超额信号归因

```text
信号：600519 贵州茅台 | 2560强多头结构 | 2026-03-20
20 日超额：-5.2%

归因：
  State：适配（fit_score=65），E/F/F → 贡献 neutral
  市场阶段：趋势延展，非 2560 最佳阶段 → 贡献 negative
  产业链景气：白酒消费链 4.8/10，景气下行 → 贡献 negative
  宏观环境：过热象限，流动性收紧 → 贡献 negative
  策略自身：signal_strength=0.70 → 贡献 neutral

主要驱动因子：产业链景气（行业景气下行拖累）
异常标记：适配度为"适配"但出现负超额，需复核产业链权重
```
