# 前向观察账本校准触发机制设计

版本：v1.0
日期：2026-05-23
状态：设计稿
关联脚本：`scripts/forward_observation_ledger.py`、`scripts/strategy_fit_observer.py`
关联注册表：`config/strategy_registry.json`

---

## 概述

前向观察账本（`outputs/forward_observation/`）每天记录提醒层信号及其未来收益标签。当积累到足够样本时，应自动触发校准更新，验证策略适配度评分的历史有效性。

本文档定义：**什么时候触发校准**、**校准什么内容**、**校准结果如何反馈到系统**。

---

## 1. 当前状态

### 1.1 前向观察账本结构

`scripts/forward_observation_ledger.py` 每天输出：

```text
outputs/forward_observation/forward_observation_{date}.json
```

每条记录包含：
- 信号元数据（strategy_id, signal_type, lifecycle_stage, strategy_environment_fit）
- State 环境（mn1_state, w1_state, d1_state, ef_count）
- 参考价格（reference_close）
- 未来收益标签（forward_return_{5,10,20}d, forward_excess_return_{5,10,20}d）
- 标注状态（label_status: "labeled" / "pending_future_data"）

### 1.2 当前缺失

- 没有自动触发校准的机制
- 没有校准结果自动写回系统的流程
- calibration_status 字段来自上游 reminder，非本地计算

---

## 2. 校准触发条件

### 2.1 三重触发门

校准必须同时满足三个条件才会触发：

```text
触发校准 = 时间门槛 AND 样本门槛 AND 变化门槛
```

| 门槛 | 条件 | 默认值 | 说明 |
|------|------|--------|------|
| 时间门槛 | 距上次校准 >= N 天 | N = 5 | 避免过于频繁的校准 |
| 样本门槛 | 新增已标注样本 >= M 条 | M = 100 | 确保统计有效性 |
| 变化门槛 | 适配度分布偏移 >= D | D = 0.10 | 避免无意义的重算 |

### 2.2 时间门槛

```text
days_since_last_calibration = (today - last_calibration_date).days

触发条件：days_since_last_calibration >= TIME_THRESHOLD（默认 5）
```

理由：太频繁的校准浪费计算资源且不会有显著统计变化。5 天保证至少有 5 个交易日的新数据。

### 2.3 样本门槛

```text
new_labeled_samples = SUM(
    labeled_count(date) - labeled_count(date_at_last_calibration)
    FOR date IN last_N_days
)

触发条件：new_labeled_samples >= SAMPLE_THRESHOLD（默认 100）
```

分策略阈值：

| 策略 | 样本门槛 | 理由 |
|------|---------|------|
| ma2560 | 100 | 信号量大，100 条约 3-5 天可达到 |
| vcp | 50 | 信号量中等，路径条件限制样本量 |
| bollinger_bandit | 80 | 信号量中等 |
| 新策略（注册 < 30 天） | 30 | 初期需要更快的反馈循环 |

### 2.4 变化门槛

检测适配度分布是否发生显著偏移：

```text
current_dist = 当前 N 天适配度分布（各等级占比）
baseline_dist = 上次校准时的适配度分布

drift = Σ|current_dist[i] - baseline_dist[i]| / 2  （总变差距离）

触发条件：drift >= DRIFT_THRESHOLD（默认 0.10）
```

含义：如果适配度分布没有显著变化（比如"最佳适配"始终占 40%），说明环境没有大的改变，不需要重算。

---

## 3. 校准内容

### 3.1 校准维度

每次校准计算以下内容：

| 校准项 | 计算方法 | 输出 |
|--------|----------|------|
| 适配度-收益相关性 | 各适配度等级的未来 N 日平均超额收益 | fit_return_table |
| 生命周期-收益相关性 | 各生命周期阶段的未来 N 日平均超额收益 | lifecycle_return_table |
| State 组合-收益表 | Top State 组合的未来收益统计 | state_return_table |
| 适配度分布快照 | 当前各等级占比 | fit_distribution_snapshot |
| 策略信号统计 | 各策略的信号数量和质量 | strategy_signal_stats |

### 3.2 适配度-收益相关性

```text
FOR each fit_level IN [最佳适配, 适配, 弱适配, 待观察, 不适配]:
    samples = SELECT * FROM forward_observation WHERE strategy_environment_fit = fit_level AND label_status = 'labeled'
    FOR each window IN [5, 10, 20]:
        avg_excess = AVG(forward_excess_return_{window}d)
        win_rate = COUNT(CASE WHEN excess > 0 END) / COUNT(*)
        sample_count = COUNT(*)
        t_stat = avg_excess / (STDDEV(excess) / SQRT(sample_count))
```

**校准通过标准**：

```text
"最佳适配" 的 20d 平均超额 > "不适配" 的 20d 平均超额
且 "最佳适配" 的 20d 胜率 > 全样本胜率
```

### 3.3 生命周期-收益相关性

```text
FOR each stage IN [新生, 行进, 延展, 未知]:
    同上计算各窗口的超额收益和胜率
```

**校准通过标准**：

```text
"新生" 样本中 VCP 信号的超额 > 非"新生" 样本中 VCP 信号的超额
"行进" 样本中 2560 信号的超额 > 非"行进" 样本中 2560 信号的超额
"延展" 样本中布林强盗信号的超额 > 非"延展" 样本中布林强盗信号的超额
```

### 3.4 State 组合-收益表

```text
FOR each state_combo IN Top 30 MN1/W1/D1 组合（按样本量排序）:
    同上计算各窗口的超额收益、胜率、t-stat
```

用于验证已固化的 State 组合是否仍然有效。

---

## 4. 校准结果输出

### 4.1 输出文件

```text
outputs/calibration/calibration_{date}.json
outputs/calibration/calibration_{date}.md
outputs/calibration/calibration_latest.json
outputs/calibration/calibration_latest.md
```

### 4.2 输出 JSON 结构

```json
{
  "schema_version": "calibration_v1",
  "date": "2026-05-23",
  "trigger_reason": "sample_threshold_met",
  "trigger_details": {
    "days_since_last": 7,
    "new_labeled_samples": 156,
    "fit_distribution_drift": 0.12
  },
  "calibration_window": {
    "start_date": "2026-04-01",
    "end_date": "2026-05-23",
    "total_labeled": 2340
  },
  "fit_return_table": {
    "最佳适配": {"5d": {"excess": 0.012, "wr": 0.52, "n": 450}, "20d": {"excess": 0.035, "wr": 0.55, "n": 380}},
    "适配": {"5d": {...}, "20d": {...}},
    "弱适配": {"5d": {...}, "20d": {...}},
    "待观察": {"5d": {...}, "20d": {...}},
    "不适配": {"5d": {...}, "20d": {...}}
  },
  "lifecycle_return_table": {...},
  "state_return_table": {...},
  "fit_distribution_snapshot": {
    "最佳适配": 0.18,
    "适配": 0.32,
    "弱适配": 0.25,
    "待观察": 0.15,
    "不适配": 0.10
  },
  "calibration_verdict": {
    "fit_ordering_valid": true,
    "lifecycle_ordering_valid": true,
    "state_combos_valid": true,
    "overall": "pass"
  },
  "recommendations": [
    "适配度排序有效，可继续使用当前映射",
    "VCP 新生组 20d 超额仍显著，路径假设持续有效",
    "布林强盗适配组样本偏少（n=45），建议积累更多样本后复核"
  ],
  "research_only": true
}
```

### 4.3 校准判定（calibration_verdict）

```text
fit_ordering_valid:
  "最佳适配" 20d 超额 > "适配" 20d 超额 > "弱适配" 20d 超额
  AND "最佳适配" 20d 超额 > 全样本 20d 超额

lifecycle_ordering_valid:
  各策略在其最佳生命周期阶段的超额 > 其他阶段

state_combos_valid:
  已固化 State 组合（如 2560 的 E/E/F）的超额 > 非匹配组合

overall:
  IF all three valid: "pass"
  IF any invalid: "review_needed"
  IF sample insufficient: "insufficient_data"
```

---

## 5. 校准结果反馈

### 5.1 自动反馈（pass 时）

```text
1. 更新 strategy_registry.json 中策略的 latest_calibration 字段
2. 更新 strategy_fit_observer 的 baseline_dist
3. 写入 calibration_{date}.json
4. 不修改任何策略信号规则（规则变更仍需人工确认）
```

### 5.2 人工审核（review_needed 时）

```text
1. 写入 calibration_{date}.json，标记 overall = "review_needed"
2. 在 recommendations 中列出具体问题
3. 生成告警标记（可在 daily_research_brief 中展示）
4. 不自动修改任何规则
5. 等待人工审核后决定：
   a. 确认环境变化，更新适配度映射
   b. 确认为噪声，重置校准基线
   c. 暂停该策略的提醒层展示
```

### 5.3 数据不足（insufficient_data 时）

```text
1. 写入 calibration_{date}.json，标记 overall = "insufficient_data"
2. 不触发任何反馈
3. 等待更多样本积累
```

---

## 6. 触发执行流程

### 6.1 每日检查流程

```text
每日收盘后：
  1. forward_observation_ledger.py 更新账本
  2. calibration_trigger.py 检查三重门
  3. IF 触发：
       a. 执行校准计算
       b. 输出 calibration_{date}.json
       c. 执行反馈（自动 or 告警）
  4. IF 未触发：
       a. 输出 calibration_check_{date}.json（记录检查结果，无校准）
```

### 6.2 新增脚本

```text
scripts/calibration_trigger.py
```

主要函数：

```python
def check_trigger(date_str: str) -> dict:
    """检查三重门条件是否满足，返回触发详情。"""

def run_calibration(date_str: str) -> dict:
    """执行校准计算，输出 calibration 报告。"""

def apply_feedback(calibration_result: dict) -> dict:
    """根据校准结果执行反馈。"""
```

### 6.3 与 strategy_environment_verifier 的关系

```text
strategy_environment_verifier.py — 注册表驱动的策略级验证
  - 验证策略假设是否成立
  - 产出: outputs/project/{strategy}_optimal_state_search.md
  - 频率: 手动触发或定期（周/月）

calibration_trigger.py — 账本驱动的适配度级校准
  - 验证适配度评分是否有效
  - 产出: outputs/calibration/calibration_{date}.json
  - 频率: 自动触发（满足三重门时）
```

两者互补，不重复。

---

## 7. 参数配置

### 7.1 配置文件

```json
// config/calibration_trigger.json
{
  "schema_version": "calibration_trigger_v1",
  "time_threshold_days": 5,
  "sample_threshold_default": 100,
  "sample_threshold_per_strategy": {
    "ma2560": 100,
    "vcp": 50,
    "bollinger_bandit": 80
  },
  "new_strategy_sample_threshold": 30,
  "new_strategy_window_days": 30,
  "drift_threshold": 0.10,
  "primary_window": 20,
  "min_t_stat": 1.65,
  "auto_feedback_on_pass": true,
  "alert_on_review_needed": true
}
```

### 7.2 参数调优建议

| 参数 | 保守设置 | 激进设置 | 推荐 |
|------|---------|---------|------|
| time_threshold_days | 10 | 3 | 5 |
| sample_threshold | 200 | 50 | 100 |
| drift_threshold | 0.15 | 0.05 | 0.10 |
| primary_window | 20 | 10 | 20 |
| min_t_stat | 1.96 | 1.28 | 1.65 |

---

## 8. 合规边界

- 校准是**只读研究操作**，不修改策略信号规则。
- 校准通过不代表策略"有效"，只代表适配度排序与历史收益方向一致。
- 校准失败不代表策略"无效"，可能是环境变化或样本不足。
- 任何规则变更仍需人工确认。
- 校准结果不构成投资建议。

---

## 附录：校准报告示例

```markdown
# 适配度校准报告 - 2026-05-23

## 触发原因
- 距上次校准：7 天（阈值 5）
- 新增已标注样本：156 条（阈值 100）
- 适配度分布偏移：0.12（阈值 0.10）

## 适配度-收益相关性（20d）

| 适配度等级 | 样本 | 平均超额 | 胜率 | t-stat |
|-----------|------|---------|------|--------|
| 最佳适配 | 380 | +3.50% | 55% | 2.31 |
| 适配 | 620 | +1.80% | 48% | 1.85 |
| 弱适配 | 480 | +0.50% | 42% | 0.65 |
| 待观察 | 300 | -0.20% | 40% | -0.30 |
| 不适配 | 200 | -1.50% | 35% | -1.80 |

## 校准判定
- 适配度排序有效：是（最佳 > 适配 > 弱适配）
- 生命周期排序有效：是
- State 组合有效：是
- 总体判定：**通过**

## 建议
- 适配度排序有效，可继续使用当前映射
- "不适配" 组超额为负且胜率低，确认该等级的警示作用有效
- 布林强盗适配组样本偏少（n=45），建议积累更多样本后复核
```
