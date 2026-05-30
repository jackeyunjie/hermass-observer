# Walk-Forward 验证框架设计

版本：v1.0
日期：2026-05-23
状态：设计稿
关联脚本：`scripts/search_vcp_optimal_state.py`、`scripts/search_2560_optimal_state.py`、`scripts/search_bollinger_optimal_state.py`

---

## 概述

当前 `search_*_optimal_state.py` 做全样本分组对比（如 2025-06 至 2026-05 的全部数据），没有样本外验证。这导致无法区分"真实有效的 State 组合"和"过拟合的噪声"。

Walk-Forward Analysis（WFA）将历史区间划分为多个 IS/OOS 窗口对，在 IS 窗口内搜索最优组合，在 OOS 窗口验证。只有在多个 OOS 窗口内持续有效的组合，才值得升格为规则。

**核心区别**：Vibe-Trading 的 WFA 用于时序策略参数优化（如"最优均线周期"），Hermass 的 WFA 用于截面验证（如"State 组合 E/E/F 是否在样本外持续跑赢"）。

---

## 1. 窗口设计

### 1.1 IS/OOS 窗口参数

```json
{
  "is_window_months": 6,
  "oos_window_months": 2,
  "step_months": 2,
  "min_is_samples_per_combo": 20,
  "min_oos_samples_per_combo": 10
}
```

### 1.2 窗口划分示意

```text
总区间：2025-06-01 至 2026-05-01（11 个月）

Fold 1: IS=[2025-06, 2025-11]  OOS=[2025-12, 2026-01]
Fold 2: IS=[2025-08, 2026-01]  OOS=[2026-02, 2026-03]
Fold 3: IS=[2025-10, 2026-03]  OOS=[2026-04, 2026-05]

共 3 个 Fold，IS 窗口 6 个月，OOS 窗口 2 个月，步进 2 个月
```

### 1.3 窗口划分函数

```python
def build_folds(
    start_date: str,
    end_date: str,
    is_months: int = 6,
    oos_months: int = 2,
    step_months: int = 2,
) -> list[dict]:
    """构建 Walk-Forward 折叠。"""
    folds = []
    fold_id = 0
    current = parse_date(start_date)

    while True:
        is_start = current
        is_end = add_months(is_start, is_months)
        oos_start = is_end
        oos_end = add_months(oos_start, oos_months)

        if oos_end > parse_date(end_date):
            break

        folds.append({
            "fold_id": fold_id,
            "is_start": is_start.isoformat(),
            "is_end": is_end.isoformat(),
            "oos_start": oos_start.isoformat(),
            "oos_end": oos_end.isoformat(),
        })
        fold_id += 1
        current = add_months(current, step_months)

    return folds
```

---

## 2. IS 窗口内的搜索逻辑

### 2.1 搜索流程

```python
def search_in_is_window(
    fold: dict,
    samples: list[dict],
    strategy_id: str,
    window: int = 20,
    min_samples: int = 20,
) -> dict:
    """在 IS 窗口内搜索最优 State 组合。"""
    # 1. 筛选 IS 窗口内的样本
    is_samples = [s for s in samples
                  if fold["is_start"] <= s["date"] <= fold["is_end"]
                  and s.get(f"excess_ret_{window}d") is not None]

    # 2. 按 State 组合分组
    by_combo = group_by_state_combo(is_samples)

    # 3. 计算每组的统计量
    combo_stats = []
    for combo, items in by_combo.items():
        if len(items) < min_samples:
            continue
        row = metric_row(combo, items, window)
        combo_stats.append(row)

    # 4. 按 mean_excess 排序，取 Top N
    combo_stats.sort(key=lambda r: r["mean_excess"] or -999, reverse=True)
    top_combos = combo_stats[:10]

    return {
        "fold_id": fold["fold_id"],
        "is_period": f"{fold['is_start']} to {fold['is_end']}",
        "total_samples": len(is_samples),
        "combos_evaluated": len(combo_stats),
        "top_combos": top_combos,
    }
```

### 2.2 策略特定的搜索维度

| 策略 | IS 搜索维度 | 说明 |
|------|------------|------|
| VCP | 路径条件（收缩后释放 lookback=5/10/20） | 搜索最优路径窗口 |
| 2560 | State 组合（精确 combo + 模糊 bit） | 搜索最优 State 匹配 |
| Bollinger | volatility_bit 分组 + State 组合 | 搜索最优波动环境 |

---

## 3. OOS 窗口内的验证逻辑

### 3.1 验证流程

```python
def validate_in_oos_window(
    fold: dict,
    is_result: dict,
    samples: list[dict],
    window: int = 20,
    min_samples: int = 10,
) -> dict:
    """在 OOS 窗口验证 IS 窗口发现的 Top 组合。"""
    oos_samples = [s for s in samples
                   if fold["oos_start"] <= s["date"] <= fold["oos_end"]
                   and s.get(f"excess_ret_{window}d") is not None]

    oos_results = []
    for combo in is_result["top_combos"]:
        combo_key = combo["key"]
        matched = [s for s in oos_samples if state_combo_key(s) == combo_key]

        if len(matched) < min_samples:
            oos_results.append({
                "combo": combo_key,
                "is_mean_excess": combo["mean_excess"],
                "oos_status": "insufficient_samples",
                "oos_n": len(matched),
            })
            continue

        oos_row = metric_row(combo_key, matched, window)
        direction_preserved = (
            (combo["mean_excess"] or 0) > 0 and (oos_row["mean_excess"] or 0) > 0
        ) or (
            (combo["mean_excess"] or 0) < 0 and (oos_row["mean_excess"] or 0) < 0
        )

        oos_results.append({
            "combo": combo_key,
            "is_mean_excess": combo["mean_excess"],
            "is_win_rate": combo["win_rate"],
            "oos_mean_excess": oos_row["mean_excess"],
            "oos_win_rate": oos_row["win_rate"],
            "oos_n": oos_row["n"],
            "direction_preserved": direction_preserved,
            "oos_status": "validated" if direction_preserved else "failed",
        })

    return {
        "fold_id": fold["fold_id"],
        "oos_period": f"{fold['oos_start']} to {fold['oos_end']}",
        "results": oos_results,
        "validation_rate": sum(1 for r in oos_results if r["oos_status"] == "validated")
                          / max(len(oos_results), 1),
    }
```

---

## 4. 过拟合判定标准

### 4.1 IS-OOS 秩相关

```python
def rank_correlation_is_oos(fold_results: list[dict]) -> float:
    """IS 排名与 OOS 排名的 Spearman 秩相关。"""
    is_ranks = []
    oos_ranks = []

    for fold in fold_results:
        for combo in fold["results"]:
            if combo["oos_status"] == "insufficient_samples":
                continue
            is_ranks.append(combo["is_mean_excess"] or 0)
            oos_ranks.append(combo["oos_mean_excess"] or 0)

    if len(is_ranks) < 5:
        return 0.0

    return spearmanr(is_ranks, oos_ranks).correlation
```

**判定标准**：

| 秩相关系数 | 判定 | 含义 |
|-----------|------|------|
| >= 0.6 | 强一致 | IS 发现的规律在 OOS 持续有效 |
| 0.3-0.6 | 中等一致 | 部分有效，需更多数据 |
| < 0.3 | 弱一致 | IS 发现可能是过拟合 |

### 4.2 参数一致性率

```python
def parameter_consistency(fold_results: list[dict]) -> float:
    """各 Fold 中 IS Top1 组合出现在其他 Fold IS Top5 中的比例。"""
    top1_per_fold = []
    for fold in fold_results:
        if fold["is_result"]["top_combos"]:
            top1_per_fold.append(fold["is_result"]["top_combos"][0]["key"])

    if len(top1_per_fold) < 2:
        return 0.0

    consistency_count = 0
    for i, combo in enumerate(top1_per_fold):
        for j, fold in enumerate(fold_results):
            if i == j:
                continue
            top5_keys = [c["key"] for c in fold["is_result"]["top_combos"][:5]]
            if combo in top5_keys:
                consistency_count += 1
                break

    return consistency_count / len(top1_per_fold)
```

**判定标准**：

| 一致性率 | 判定 | 含义 |
|---------|------|------|
| >= 0.67 | 高一致 | 至少 2/3 的 Fold 选出相同组合 |
| 0.33-0.67 | 中等 | 部分 Fold 一致 |
| < 0.33 | 低一致 | 各 Fold 选出不同组合，过拟合风险高 |

### 4.3 综合过拟合评分

```python
def overfit_score(rank_corr: float, param_consistency: float,
                  oos_validation_rate: float) -> dict:
    """综合过拟合评分。"""
    score = (rank_corr * 0.4 + param_consistency * 0.3 + oos_validation_rate * 0.3)

    if score >= 0.6:
        verdict = "robust"
        label = "稳健"
    elif score >= 0.4:
        verdict = "marginal"
        label = "边际"
    else:
        verdict = "overfit_risk"
        label = "过拟合风险"

    return {
        "overfit_score": round(score, 3),
        "verdict": verdict,
        "label": label,
        "components": {
            "rank_correlation": round(rank_corr, 3),
            "parameter_consistency": round(param_consistency, 3),
            "oos_validation_rate": round(oos_validation_rate, 3),
        },
    }
```

---

## 5. 三策略适配

### 5.1 VCP：路径验证

```text
IS 搜索：在 IS 窗口内，搜索最优收缩后释放路径窗口（5/10/20 日）
OOS 验证：在 OOS 窗口内，用 IS 选出的最优窗口重新计算路径条件，验证超额是否保持

特殊：VCP 的路径条件是动态的（近 N 日是否经历收缩），不是静态 State 组合
```

### 5.2 2560：State 组合验证

```text
IS 搜索：在 IS 窗口内，搜索最优 MN1/W1/D1 State 组合
OOS 验证：在 OOS 窗口内，用 IS 选出的 Top5 组合验证超额

特殊：2560 已有固化规则（E/E/F, E/F/F, E/F/E），WFA 用于验证该规则在不同时期是否持续有效
```

### 5.3 布林强盗：波动环境验证

```text
IS 搜索：在 IS 窗口内，验证 volatility_bit=0 vs 1 的差异是否持续
OOS 验证：在 OOS 窗口内，重新检验该差异

特殊：布林强盗的验证维度较少（主要是 volatility_bit），Fold 间一致性更容易判断
```

---

## 6. 报告输出

### 6.1 输出格式

```text
outputs/walk_forward/wfa_{strategy}_{date}.json
outputs/walk_forward/wfa_{strategy}_{date}.md
```

### 6.2 Markdown 报告模板

```markdown
# Walk-Forward 验证报告 — {strategy} — {date}

## 窗口设计
- IS 窗口：{is_months} 个月
- OOS 窗口：{oos_months} 个月
- 步进：{step_months} 个月
- 总 Folds：{n_folds}

## Fold 汇总

| Fold | IS 区间 | OOS 区间 | IS Top1 组合 | IS 超额 | OOS 超额 | 方向一致 |
|------|---------|---------|-------------|---------|---------|---------|
| 1 | 06-11 | 12-01 | E/E/F | +3.2% | +2.1% | ✓ |
| 2 | 08-01 | 02-03 | E/E/F | +2.8% | +1.5% | ✓ |
| 3 | 10-03 | 04-05 | E/F/F | +4.1% | +0.8% | ✓ |

## 过拟合评估

| 指标 | 值 | 判定 |
|------|-----|------|
| IS-OOS 秩相关 | 0.72 | 强一致 |
| 参数一致性率 | 0.67 | 高一致 |
| OOS 验证率 | 0.85 | 高 |
| **综合评分** | **0.75** | **稳健** |

## 结论
IS 发现的 Top 组合在 OOS 窗口内持续有效，过拟合风险低。
```

---

## 7. 实施路径

| 阶段 | 任务 | 工作量 |
|------|------|--------|
| 1 | 实现 `scripts/walk_forward_engine.py`（窗口划分 + IS 搜索 + OOS 验证） | 1 周 |
| 2 | 接入三个 search 脚本（复用 metric_row + bootstrap_stats） | 2 天 |
| 3 | 实现过拟合评估和报告渲染 | 2 天 |
| 4 | 首次全量 WFA（VCP + 2560 + Bollinger） | 1 天 |
