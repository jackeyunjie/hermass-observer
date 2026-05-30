# Bootstrap 置信区间实现方案

版本：v1.0
日期：2026-05-23
状态：实现规范
关联脚本：`scripts/search_vcp_optimal_state.py`、`scripts/search_2560_optimal_state.py`、`scripts/search_bollinger_optimal_state.py`

---

## 概述

当前三个验证脚本（VCP / 2560 / 布林强盗）的 `metric_row()` 函数只输出点估计（mean_excess、win_rate、t_stat），缺乏置信区间。这导致统计说服力不足——一个 +1.67% 的超额收益，不知道是 [0.5%, 2.8%] 还是 [-0.3%, 3.6%]。

本方案通过 Bootstrap 重采样为每个统计量增加 95% 置信区间，同时提取三个脚本的重复代码为共享模块。

---

## 1. 当前代码分析

### 1.1 重复代码

三个脚本中以下函数完全重复：

| 函数 | 行号（VCP/2560/Bollinger） | 功能 |
|------|---------------------------|------|
| `pct()` | 43/39/43 | 百分比格式化 |
| `payoff_ratio()` | 376/321/317 | 盈亏比计算 |
| `metric_row()` | 387/332/328 | 核心统计（均值/中位数/胜率/t-stat） |
| `fmt_num()` | 493/455/456 | 数字格式化 |
| `safe_float()` | 从 calibrate 导入 | 安全浮点转换 |

### 1.2 当前 metric_row 输出

```python
# scripts/search_vcp_optimal_state.py:387-401
def metric_row(key: str, samples: list[dict[str, Any]], window: int) -> dict[str, Any]:
    values = [float(s[f"excess_ret_{window}d"]) for s in samples
              if s.get(f"excess_ret_{window}d") is not None]
    wins = [v for v in values if v > 0]
    mean = statistics.fmean(values) if values else None
    stdev = statistics.stdev(values) if len(values) > 1 else None
    t_stat = mean / (stdev / math.sqrt(len(values))) if mean is not None and stdev and stdev > 0 else None
    return {
        "key": key,
        "n": len(values),
        "mean_excess": mean,
        "median_excess": statistics.median(values) if values else None,
        "win_rate": len(wins) / len(values) if values else None,
        "payoff_ratio": payoff_ratio(values),
        "t_stat": t_stat,
    }
```

**缺失**：无置信区间。

---

## 2. 实现方案

### 2.1 新增共享模块

```text
scripts/bootstrap_stats.py
```

提取三个脚本的重复统计函数 + 新增 Bootstrap CI 计算。

### 2.2 Bootstrap CI 核心函数

```python
# scripts/bootstrap_stats.py

import math
import statistics
from typing import Any

import numpy as np


def bootstrap_ci(
    values: list[float],
    stat_fn: callable,
    n_bootstrap: int = 10000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float, float]:
    """
    Bootstrap 置信区间计算。

    参数：
        values: 原始观测值列表
        stat_fn: 统计量函数（如 np.mean, 自定义 win_rate 函数等）
        n_bootstrap: 重采样次数（默认 10000）
        confidence: 置信水平（默认 0.95）
        seed: 随机种子（保证可复现）

    返回：
        (ci_lower, ci_upper): 置信区间下界和上界

    算法：
        1. 从 values 中有放回地抽取 len(values) 个样本
        2. 计算该样本的 stat_fn 值
        3. 重复 n_bootstrap 次
        4. 取 (1-confidence)/2 和 1-(1-confidence)/2 分位数
    """
    if len(values) < 5:
        return (None, None)  # 样本太少，不计算 CI

    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=np.float64)
    n = len(arr)

    boot_stats = np.empty(n_bootstrap, dtype=np.float64)
    for i in range(n_bootstrap):
        sample = rng.choice(arr, size=n, replace=True)
        boot_stats[i] = stat_fn(sample)

    alpha = (1.0 - confidence) / 2.0
    ci_lower = float(np.percentile(boot_stats, alpha * 100))
    ci_upper = float(np.percentile(boot_stats, (1.0 - alpha) * 100))

    return (ci_lower, ci_upper)


def bootstrap_mean_ci(values: list[float], n_bootstrap: int = 10000,
                      confidence: float = 0.95) -> tuple[float, float]:
    """均值的 Bootstrap CI。"""
    return bootstrap_ci(values, np.mean, n_bootstrap, confidence)


def bootstrap_median_ci(values: list[float], n_bootstrap: int = 10000,
                        confidence: float = 0.95) -> tuple[float, float]:
    """中位数的 Bootstrap CI。"""
    return bootstrap_ci(values, np.median, n_bootstrap, confidence)


def bootstrap_win_rate_ci(values: list[float], n_bootstrap: int = 10000,
                          confidence: float = 0.95) -> tuple[float, float]:
    """胜率的 Bootstrap CI。"""
    def win_rate(arr):
        return np.mean(arr > 0)
    return bootstrap_ci(values, win_rate, n_bootstrap, confidence)


def bootstrap_payoff_ratio_ci(values: list[float], n_bootstrap: int = 10000,
                               confidence: float = 0.95) -> tuple[float, float]:
    """盈亏比的 Bootstrap CI。"""
    def payoff(arr):
        wins = arr[arr > 0]
        losses = arr[arr < 0]
        if len(wins) == 0 or len(losses) == 0:
            return np.nan
        return np.mean(wins) / abs(np.mean(losses))

    def payoff_safe(arr):
        result = payoff(arr)
        return result if np.isfinite(result) else 0.0

    return bootstrap_ci(values, payoff_safe, n_bootstrap, confidence)
```

### 2.3 升级后的 metric_row

```python
# scripts/bootstrap_stats.py

def metric_row_with_ci(
    key: str,
    samples: list[dict[str, Any]],
    window: int,
    n_bootstrap: int = 10000,
) -> dict[str, Any]:
    """
    升级版 metric_row：点估计 + 95% Bootstrap CI。

    输出格式：
        mean_excess: float
        mean_excess_ci: (float, float)  ← 新增
        median_excess: float
        median_excess_ci: (float, float)  ← 新增
        win_rate: float
        win_rate_ci: (float, float)  ← 新增
        payoff_ratio: float
        payoff_ratio_ci: (float, float)  ← 新增
        t_stat: float  ← 保持不变（t-stat 本身已有置信含义）
    """
    values = [float(s[f"excess_ret_{window}d"]) for s in samples
              if s.get(f"excess_ret_{window}d") is not None]
    wins = [v for v in values if v > 0]

    # 点估计（保持原有逻辑）
    mean = statistics.fmean(values) if values else None
    stdev = statistics.stdev(values) if len(values) > 1 else None
    t_stat = mean / (stdev / math.sqrt(len(values))) if mean and stdev and stdev > 0 else None
    med = statistics.median(values) if values else None
    wr = len(wins) / len(values) if values else None
    pr = payoff_ratio(values)

    # Bootstrap CI
    mean_ci = (None, None)
    median_ci = (None, None)
    wr_ci = (None, None)
    pr_ci = (None, None)

    if len(values) >= 10:  # 至少 10 个样本才计算 CI
        mean_ci = bootstrap_mean_ci(values, n_bootstrap)
        median_ci = bootstrap_median_ci(values, n_bootstrap)
        wr_ci = bootstrap_win_rate_ci(values, n_bootstrap)
        pr_ci = bootstrap_payoff_ratio_ci(values, n_bootstrap)

    return {
        "key": key,
        "n": len(values),
        "mean_excess": mean,
        "mean_excess_ci_lo": mean_ci[0],
        "mean_excess_ci_hi": mean_ci[1],
        "median_excess": med,
        "median_excess_ci_lo": median_ci[0],
        "median_excess_ci_hi": median_ci[1],
        "win_rate": wr,
        "win_rate_ci_lo": wr_ci[0],
        "win_rate_ci_hi": wr_ci[1],
        "payoff_ratio": pr,
        "payoff_ratio_ci_lo": pr_ci[0],
        "payoff_ratio_ci_hi": pr_ci[1],
        "t_stat": t_stat,
    }
```

### 2.4 提取的共享函数

```python
# scripts/bootstrap_stats.py — 完整模块

"""Bootstrap statistics for strategy verification scripts.

Extracted from search_vcp_optimal_state.py, search_2560_optimal_state.py,
search_bollinger_optimal_state.py to eliminate code duplication and add
Bootstrap confidence intervals.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

import numpy as np


# ── Format utilities (extracted from 3 scripts) ──────────────────────

def pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.{digits}f}%"


def fmt_num(value: Any, digits: int = 4) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


# ── Stat utilities (extracted from 3 scripts) ────────────────────────

def payoff_ratio(values: list[float]) -> float | None:
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    if not wins or not losses:
        return None
    loss_mean = statistics.fmean(losses)
    if loss_mean == 0:
        return None
    return statistics.fmean(wins) / abs(loss_mean)


# ── Bootstrap CI core ────────────────────────────────────────────────

def bootstrap_ci(
    values: list[float],
    stat_fn: callable,
    n_bootstrap: int = 10000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float | None, float | None]:
    """Bootstrap confidence interval via percentile method."""
    if len(values) < 5:
        return (None, None)

    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=np.float64)
    n = len(arr)

    boot_stats = np.empty(n_bootstrap, dtype=np.float64)
    for i in range(n_bootstrap):
        sample = rng.choice(arr, size=n, replace=True)
        boot_stats[i] = stat_fn(sample)

    alpha = (1.0 - confidence) / 2.0
    return (
        float(np.percentile(boot_stats, alpha * 100)),
        float(np.percentile(boot_stats, (1.0 - alpha) * 100)),
    )


def bootstrap_mean_ci(values, n_bootstrap=10000, confidence=0.95):
    return bootstrap_ci(values, np.mean, n_bootstrap, confidence)


def bootstrap_win_rate_ci(values, n_bootstrap=10000, confidence=0.95):
    return bootstrap_ci(values, lambda a: np.mean(a > 0), n_bootstrap, confidence)


def bootstrap_payoff_ratio_ci(values, n_bootstrap=10000, confidence=0.95):
    def payoff(arr):
        w = arr[arr > 0]
        l = arr[arr < 0]
        if len(w) == 0 or len(l) == 0:
            return 0.0
        r = np.mean(w) / abs(np.mean(l))
        return r if np.isfinite(r) else 0.0
    return bootstrap_ci(values, payoff, n_bootstrap, confidence)


# ── metric_row (replaces 3 copies) ──────────────────────────────────

def metric_row(
    key: str,
    samples: list[dict[str, Any]],
    window: int,
    n_bootstrap: int = 10000,
) -> dict[str, Any]:
    """Compute point estimates + 95% Bootstrap CI for a group of samples."""
    values = [float(s[f"excess_ret_{window}d"]) for s in samples
              if s.get(f"excess_ret_{window}d") is not None]
    wins = [v for v in values if v > 0]

    mean = statistics.fmean(values) if values else None
    stdev = statistics.stdev(values) if len(values) > 1 else None
    t_stat = mean / (stdev / math.sqrt(len(values))) if mean and stdev and stdev > 0 else None
    med = statistics.median(values) if values else None
    wr = len(wins) / len(values) if values else None
    pr = payoff_ratio(values)

    ci_mean = ci_med = ci_wr = ci_pr = (None, None)
    if len(values) >= 10:
        ci_mean = bootstrap_mean_ci(values, n_bootstrap)
        ci_med = bootstrap_ci(values, np.median, n_bootstrap)
        ci_wr = bootstrap_win_rate_ci(values, n_bootstrap)
        ci_pr = bootstrap_payoff_ratio_ci(values, n_bootstrap)

    return {
        "key": key, "n": len(values),
        "mean_excess": mean,
        "mean_excess_ci_lo": ci_mean[0], "mean_excess_ci_hi": ci_mean[1],
        "median_excess": med,
        "median_excess_ci_lo": ci_med[0], "median_excess_ci_hi": ci_med[1],
        "win_rate": wr,
        "win_rate_ci_lo": ci_wr[0], "win_rate_ci_hi": ci_wr[1],
        "payoff_ratio": pr,
        "payoff_ratio_ci_lo": ci_pr[0], "payoff_ratio_ci_hi": ci_pr[1],
        "t_stat": t_stat,
    }
```

---

## 3. 三个脚本的修改点

### 3.1 修改清单

| 文件 | 修改 | 改动量 |
|------|------|--------|
| `scripts/search_vcp_optimal_state.py` | 删除 `pct`/`payoff_ratio`/`metric_row`/`fmt_num`/`safe_float`，改为从 `bootstrap_stats` 导入 | 删 ~50 行，改 ~5 行导入 |
| `scripts/search_2560_optimal_state.py` | 同上 | 同上 |
| `scripts/search_bollinger_optimal_state.py` | 同上 | 同上 |
| `scripts/bootstrap_stats.py` | **新增**共享模块 | ~130 行 |

### 3.2 每个脚本的具体修改

#### search_vcp_optimal_state.py

```python
# 删除以下函数（约 43-60, 376-401, 493-500 行）：
#   def pct()
#   def payoff_ratio()
#   def metric_row()
#   def fmt_num()

# 新增导入：
from bootstrap_stats import metric_row, pct, fmt_num, safe_float

# 无需修改调用方：
#   summarize_grouped() 中的 metric_row(key, items, window) 调用不变
#   render_hypothesis_table() 中的 pct()/fmt_num() 调用不变
```

#### search_2560_optimal_state.py 和 search_bollinger_optimal_state.py

完全相同的修改模式。

### 3.3 报告渲染修改

`render_markdown()` 函数需要新增 CI 列。以 VCP 为例：

#### 假设对照表（修改前）

```markdown
| 口径 | 窗口 | n | 平均超额 | 胜率 | 盈亏比 | t-stat |
```

#### 假设对照表（修改后）

```markdown
| 口径 | 窗口 | n | 平均超额 | 95% CI | 胜率 | 95% CI | 盈亏比 | t-stat |
```

渲染函数修改：

```python
def render_hypothesis_table(name: str, block: dict[str, Any], windows: list[int]) -> list[str]:
    lines = [
        f"### {name}", "",
        "- 命中样本: `{}`".format(block.get("matched_samples")),
        "- 未命中样本: `{}`".format(block.get("outside_samples")), "",
        "| 口径 | 窗口 | n | 平均超额 | 95% CI | 胜率 | 95% CI | 盈亏比 | t-stat |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, key in [("matched", "matched"), ("outside", "outside"), ("all_selected", "all")]:
        for window in windows:
            row = ...  # 从 block 中取对应行
            ci_mean = f"[{pct(row.get('mean_excess_ci_lo'))}, {pct(row.get('mean_excess_ci_hi'))}]"
            ci_wr = f"[{pct(row.get('win_rate_ci_lo'))}, {pct(row.get('win_rate_ci_hi'))}]"
            lines.append(
                f"| {label} | {window}d | {row['n']} "
                f"| {pct(row['mean_excess'])} | {ci_mean} "
                f"| {pct(row['win_rate'])} | {ci_wr} "
                f"| {fmt_num(row.get('payoff_ratio'))} | {fmt_num(row['t_stat'])} |"
            )
    return lines
```

### 3.4 JSON 输出修改

`metric_row_with_ci` 的输出自动包含 CI 字段，JSON 序列化无需额外修改。下游消费者（calibration_trigger、attribution）可以读取 CI 字段做判断。

---

## 4. 性能考虑

### 4.1 计算开销

| 样本量 | 10000 次 Bootstrap 耗时（单组） | 总组数（典型） | 总耗时 |
|--------|-------------------------------|---------------|--------|
| 100 | ~50ms | 30 | ~1.5s |
| 1000 | ~200ms | 30 | ~6s |
| 10000 | ~1.5s | 30 | ~45s |
| 43000 | ~6s | 30 | ~180s |

### 4.2 优化方案

如果全量计算耗时过长，可采用以下优化：

```python
# 方案 A：减少 Bootstrap 次数（快速模式）
n_bootstrap = 2000  # 精度足够，耗时降为 1/5

# 方案 B：仅对 Top N 组合计算 CI
TOP_N_FOR_CI = 30  # 只对 Top 30 精确组合计算 CI
# 模糊 bit 形态全部计算（组数少）

# 方案 C：仅对主要窗口计算 CI
CI_WINDOWS = [20]  # 只对 20d 窗口计算 CI，5d/10d 不计算
```

推荐方案：**方案 A + B 组合**——2000 次 Bootstrap + 仅 Top 30 组合。总耗时约 10-15 秒。

### 4.3 随机种子

固定 `seed=42` 确保每次运行结果完全可复现。如果需要多次运行取平均，可通过参数覆盖。

---

## 5. CI 的解读规则

### 5.1 CI 不包含零 → 统计显著

```text
mean_excess = +1.67%
CI = [+0.8%, +2.5%]
→ CI 不包含 0，统计显著
```

### 5.2 CI 包含零 → 不显著

```text
mean_excess = +1.67%
CI = [-0.3%, +3.6%]
→ CI 包含 0，不能排除"无超额"的可能
```

### 5.3 CI 报告中的标注

```python
def significance_tag(ci_lo: float | None, ci_hi: float | None) -> str:
    if ci_lo is None or ci_hi is None:
        return ""
    if ci_lo > 0:
        return " ✓"  # 显著正超额
    if ci_hi < 0:
        return " ✗"  # 显著负超额
    return ""  # 不显著
```

在 Markdown 表格中：

```markdown
| 平均超额 | 95% CI | 标注 |
| +1.67% | [+0.8%, +2.5%] | ✓ |
| +0.45% | [-0.3%, +1.2%] |   |
```

---

## 6. 验证方案

### 6.1 单元测试

```python
# tests/test_bootstrap_stats.py

def test_bootstrap_mean_ci_known_distribution():
    """已知正态分布的 CI 应包含真实均值。"""
    rng = np.random.default_rng(42)
    values = rng.normal(0.05, 0.10, size=500).tolist()  # mean=5%, std=10%
    ci_lo, ci_hi = bootstrap_mean_ci(values, n_bootstrap=10000)
    assert ci_lo < 0.05 < ci_hi, f"CI [{ci_lo}, {ci_hi}] should contain 0.05"

def test_bootstrap_ci_small_sample():
    """样本 < 5 时返回 (None, None)。"""
    ci = bootstrap_mean_ci([1, 2, 3, 4], n_bootstrap=1000)
    assert ci == (None, None)

def test_bootstrap_win_rate_ci():
    """80% 胜率的 CI 应该在 [70%, 90%] 附近。"""
    values = [1.0] * 80 + [-1.0] * 20
    ci_lo, ci_hi = bootstrap_win_rate_ci(values, n_bootstrap=10000)
    assert 0.70 < ci_lo < 0.80
    assert 0.80 < ci_hi < 0.90

def test_metric_row_ci_fields():
    """metric_row 输出包含 CI 字段。"""
    samples = [{"excess_ret_20d": 0.05} for _ in range(50)]
    row = metric_row("test", samples, window=20, n_bootstrap=1000)
    assert "mean_excess_ci_lo" in row
    assert "mean_excess_ci_hi" in row
    assert "win_rate_ci_lo" in row
    assert row["mean_excess_ci_lo"] is not None
```

### 6.2 集成验证

```bash
# 运行 VCP 验证脚本，检查 CI 输出
python3 scripts/search_vcp_optimal_state.py \
  --start-date 2025-06-01 --end-date 2026-05-01 \
  --foundation-db outputs/p116_foundation_20260521/p116_foundation.duckdb

# 检查输出 JSON 中包含 CI 字段
python3 -c "
import json
d = json.load(open('outputs/strategy_evaluation/vcp_optimal_state_search_*.json'))
h = d['hypotheses']['D1 近20日经历收缩后释放']
matched = h['matched'][0]  # 20d
print(f'mean={matched[\"mean_excess\"]:.4f}')
print(f'CI=[{matched[\"mean_excess_ci_lo\"]:.4f}, {matched[\"mean_excess_ci_hi\"]:.4f}]')
"
```

---

## 附录：修改后的完整报告示例

```markdown
## 研究假设对照

### D1 近20日经历收缩后释放

- 命中样本: `354`
- 未命中样本: `2573`

| 口径 | 窗口 | n | 平均超额 | 95% CI | 胜率 | 95% CI | 盈亏比 | t-stat |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| matched | 5d | 354 | 0.52% | [0.05%, 0.98%] | 42.66% | [37.5%, 47.8%] | 1.5654 | 1.0093 |
| matched | 10d | 354 | 2.30% | [1.10%, 3.50%] | 47.46% | [42.2%, 52.7%] | 1.7659 | 2.9136 |
| matched | 20d | 73 | 4.69% | [1.20%, 8.20%] | 56.16% | [44.5%, 67.5%] | 1.5006 | 1.9595 |
| outside | 5d | 2573 | 0.10% | [-0.12%, 0.32%] | 42.75% | [40.8%, 44.7%] | 1.3859 | 0.5969 |
| outside | 10d | 2570 | 1.04% | [0.65%, 1.43%] | 42.33% | [40.4%, 44.3%] | 1.7242 | 3.9381 |
| outside | 20d | 529 | 1.17% | [0.20%, 2.15%] | 44.05% | [39.8%, 48.3%] | 1.5260 | 1.4770 |

CI 解读：
- matched 20d: CI=[+1.20%, +8.20%] 不包含零 → 统计显著 ✓
- matched 5d: CI=[+0.05%, +0.98%] 勉强不包含零 → 边际显著
- outside 5d: CI=[-0.12%, +0.32%] 包含零 → 不显著
```
