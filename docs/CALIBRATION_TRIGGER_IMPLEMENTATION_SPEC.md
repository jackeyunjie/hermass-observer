# 校准触发脚本实现规范

版本：v1.0
日期：2026-05-23
状态：实现规范
关联设计：`docs/calibration_trigger_design.md`
关联状态：`docs/FORWARD_OBSERVATION_PROGRESS_20260523.md`
关联脚本：`scripts/strategy_environment_verifier.py`

---

## 概述

`scripts/calibration_trigger.py` 是校准系统的入口脚本。它每天检查三重门条件，满足时自动触发校准，产出统计结论。

**当前状态**：前向观察账本运行 2 天，已标注样本 0，预计 2026-05-27~28 首次触发。

---

## 1. 主函数接口

```python
def main() -> int:
    parser = argparse.ArgumentParser(description="Calibration trigger for forward observation ledger.")
    parser.add_argument("--date", required=True, help="Check date, e.g. 2026-05-27")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH,
                        help="Path to calibration_trigger.json")
    parser.add_argument("--force", action="store_true",
                        help="Force calibration regardless of trigger conditions")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check conditions only, do not run calibration")
    parser.add_argument("--strategy", default="all",
                        help="Strategy to calibrate: all / vcp / ma2560 / bollinger_bandit")
    args = parser.parse_args()

    result = run(date_str=args.date, config_path=args.config,
                 force=args.force, dry_run=args.dry_run, strategy=args.strategy)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
```

---

## 2. check_trigger() — 三重门检查

### 2.1 函数签名

```python
def check_trigger(
    date_str: str,
    config: dict,
    strategy_id: str | None = None,
) -> dict:
    """
    检查校准触发的三重门条件。

    返回：
        {
            "should_calibrate": bool,
            "trigger_reason": str | None,
            "gates": {
                "time": {"passed": bool, "detail": ...},
                "sample": {"passed": bool, "detail": ...},
                "drift": {"passed": bool, "detail": ...},
            },
            "first_calibration": bool,
        }
    """
```

### 2.2 时间门

```python
def check_time_gate(date_str: str, config: dict) -> dict:
    """检查距上次校准是否 >= N 天。"""
    threshold = config.get("time_threshold_days", 5)
    last_calibration = load_last_calibration_date()

    if last_calibration is None:
        # 首次校准：检查账本运行天数
        ledger_start = load_ledger_start_date()
        if ledger_start is None:
            return {"passed": False, "detail": "账本尚未启动", "days": 0}
        days = (parse_date(date_str) - parse_date(ledger_start)).days
        return {
            "passed": days >= threshold,
            "detail": f"首次校准，账本运行 {days} 天（阈值 {threshold}）",
            "days": days,
            "first_calibration": True,
        }

    days = (parse_date(date_str) - parse_date(last_calibration)).days
    return {
        "passed": days >= threshold,
        "detail": f"距上次校准 {days} 天（阈值 {threshold}）",
        "days": days,
        "first_calibration": False,
    }
```

### 2.3 样本门

```python
def check_sample_gate(date_str: str, config: dict, strategy_id: str | None) -> dict:
    """检查新增已标注样本是否 >= M 条。"""
    # 分策略阈值
    per_strategy = config.get("sample_threshold_per_strategy", {})
    default_threshold = config.get("sample_threshold_default", 100)

    if strategy_id and strategy_id != "all":
        threshold = per_strategy.get(strategy_id, default_threshold)
        labeled = count_labeled_since_last_calibration(date_str, strategy_id)
        return {
            "passed": labeled >= threshold,
            "detail": f"{strategy_id}: {labeled}/{threshold} 已标注",
            "labeled": labeled,
            "threshold": threshold,
        }

    # 全策略汇总
    total_labeled = 0
    details = {}
    all_passed = True
    for sid in ["vcp", "ma2560", "bollinger_bandit"]:
        t = per_strategy.get(sid, default_threshold)
        l = count_labeled_since_last_calibration(date_str, sid)
        details[sid] = {"labeled": l, "threshold": t, "passed": l >= t}
        total_labeled += l
        if l < t:
            all_passed = False

    return {
        "passed": all_passed,
        "detail": details,
        "total_labeled": total_labeled,
    }
```

### 2.4 变化门

```python
def check_drift_gate(date_str: str, config: dict) -> dict:
    """检查适配度分布偏移是否 >= D。"""
    threshold = config.get("drift_threshold", 0.10)
    baseline = load_baseline_distribution()

    if baseline is None:
        # 首次校准：无基线，跳过变化门
        return {
            "passed": True,
            "detail": "首次校准，无历史基线，跳过变化门",
            "drift": None,
            "skipped": True,
        }

    current = compute_fit_distribution(date_str)
    drift = compute_total_variation_distance(baseline, current)

    return {
        "passed": drift >= threshold,
        "detail": f"分布偏移 {drift:.3f}（阈值 {threshold}）",
        "drift": drift,
        "baseline": baseline,
        "current": current,
        "skipped": False,
    }
```

### 2.5 总判定

```python
def check_trigger(date_str: str, config: dict, strategy_id: str | None = None) -> dict:
    time_gate = check_time_gate(date_str, config)
    sample_gate = check_sample_gate(date_str, config, strategy_id)
    drift_gate = check_drift_gate(date_str, config)

    first_calibration = time_gate.get("first_calibration", False)

    # 首次校准：三重门退化为双重门（跳过变化门）
    if first_calibration:
        should = time_gate["passed"] and sample_gate["passed"]
        reason = "first_calibration_time_and_sample_met" if should else None
    else:
        should = time_gate["passed"] and sample_gate["passed"] and drift_gate["passed"]
        reason = "all_three_gates_met" if should else None

    return {
        "should_calibrate": should,
        "trigger_reason": reason,
        "first_calibration": first_calibration,
        "gates": {
            "time": time_gate,
            "sample": sample_gate,
            "drift": drift_gate,
        },
    }
```

---

## 3. run_calibration() — 执行校准

### 3.1 函数签名

```python
def run_calibration(
    date_str: str,
    config: dict,
    strategy_id: str | None = None,
) -> dict:
    """
    触发后执行校准计算。

    流程：
        1. 加载前向观察账本中的已标注样本
        2. 按策略 × 适配度分组统计
        3. 计算 Bootstrap CI
        4. 判定适配度排序有效性
        5. 输出校准报告

    返回：校准报告 JSON
    """
```

### 3.2 核心逻辑

```python
def run_calibration(date_str: str, config: dict, strategy_id: str | None) -> dict:
    window = config.get("primary_window", 20)
    n_bootstrap = config.get("bootstrap_n", 2000)

    # 1. 加载已标注样本
    observations = load_labeled_observations(date_str, strategy_id)

    # 2. 按适配度分组统计
    fit_groups = {}
    for level in ["最佳适配", "适配", "弱适配", "待观察", "不适配"]:
        group = [o for o in observations if o["strategy_environment_fit"] == level]
        if group:
            values = [o[f"forward_excess_return_{window}d"] for o in group
                      if o.get(f"forward_excess_return_{window}d") is not None]
            if values:
                fit_groups[level] = metric_row(level, group, window, n_bootstrap)

    # 3. 按生命周期分组统计
    lifecycle_groups = {}
    for stage in ["新生", "行进", "延展", "未知"]:
        group = [o for o in observations if o["lifecycle_stage"] == stage]
        if group:
            lifecycle_groups[stage] = metric_row(stage, group, window, n_bootstrap)

    # 4. 判定适配度排序有效性
    fit_ordering = check_fit_ordering(fit_groups)

    # 5. 生成报告
    return {
        "schema_version": "calibration_report_v1",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "calibration_window": {
            "start_date": find_earliest_observation(observations),
            "end_date": date_str,
            "total_labeled": len(observations),
        },
        "fit_return_table": fit_groups,
        "lifecycle_return_table": lifecycle_groups,
        "verdict": {
            "fit_ordering_valid": fit_ordering["valid"],
            "fit_ordering_detail": fit_ordering["detail"],
            "overall": "pass" if fit_ordering["valid"] else "review_needed",
        },
        "run_card": build_run_card(date_str, config, observations, fit_groups),
        "research_only": True,
    }
```

### 3.3 适配度排序有效性判定

```python
def check_fit_ordering(fit_groups: dict) -> dict:
    """检查适配度排序是否与收益方向一致。"""
    levels = ["最佳适配", "适配", "弱适配", "待观察", "不适配"]
    available = [(l, fit_groups[l]) for l in levels if l in fit_groups]

    if len(available) < 2:
        return {"valid": False, "detail": "可用适配度等级不足 2 个", "insufficient": True}

    # 检查：排序是否递减
    means = [(l, r["mean_excess"]) for l, r in available if r["mean_excess"] is not None]
    if len(means) < 2:
        return {"valid": False, "detail": "有效均值不足"}

    sorted_correctly = all(
        means[i][1] >= means[i+1][1] for i in range(len(means)-1)
    )

    # 检查：最佳适配 > 全样本均值
    best_mean = means[0][1]
    all_mean = sum(r["mean_excess"] for _, r in available) / len(available)
    best_above_all = best_mean > all_mean

    valid = sorted_correctly and best_above_all

    return {
        "valid": valid,
        "detail": {
            "sorted_correctly": sorted_correctly,
            "best_above_all": best_above_all,
            "means": {l: round(m, 4) for l, m in means},
        },
    }
```

---

## 4. apply_feedback() — 反馈执行

### 4.1 函数签名

```python
def apply_feedback(
    calibration_result: dict,
    config: dict,
) -> dict:
    """
    根据校准结果执行反馈。

    pass → 自动更新基线
    review_needed → 生成告警
    insufficient_data → 无操作
    """
```

### 4.2 逻辑

```python
def apply_feedback(calibration_result: dict, config: dict) -> dict:
    verdict = calibration_result["verdict"]["overall"]
    date_str = calibration_result["date"]

    if verdict == "pass":
        # 1. 更新基线分布
        new_baseline = extract_fit_distribution(calibration_result["fit_return_table"])
        save_baseline_distribution(date_str, new_baseline)

        # 2. 更新 strategy_registry.json 的 latest_calibration
        update_registry_calibration(date_str, calibration_result)

        # 3. 写入校准报告
        write_calibration_report(date_str, calibration_result)

        return {
            "action": "auto_updated",
            "baseline_updated": True,
            "registry_updated": True,
            "report_written": True,
        }

    elif verdict == "review_needed":
        # 1. 写入校准报告（标记为 review_needed）
        write_calibration_report(date_str, calibration_result)

        # 2. 生成告警
        alert = generate_calibration_alert(calibration_result)
        write_alert(date_str, alert)

        return {
            "action": "alert_generated",
            "alert": alert,
            "report_written": True,
        }

    else:  # insufficient_data
        return {
            "action": "no_action",
            "reason": "数据不足，等待更多样本",
        }
```

---

## 5. 辅助函数

### 5.1 数据加载

```python
def load_last_calibration_date() -> str | None:
    """读取上次校准日期。"""
    path = ROOT / "outputs" / "calibration" / "calibration_manifest.json"
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return manifest.get("latest_calibration_date")

def load_ledger_start_date() -> str | None:
    """读取前向观察账本的启动日期。"""
    obs_dir = ROOT / "outputs" / "forward_observation"
    files = sorted(obs_dir.glob("forward_observation_????????.json"))
    if not files:
        return None
    # 从文件名提取日期
    return files[0].stem.replace("forward_observation_", "")[:8]

def load_labeled_observations(date_str: str, strategy_id: str | None) -> list[dict]:
    """加载所有已标注的前向观察记录。"""
    obs_dir = ROOT / "outputs" / "forward_observation"
    all_obs = []
    for f in sorted(obs_dir.glob("forward_observation_????????.json")):
        payload = json.loads(f.read_text(encoding="utf-8"))
        for row in payload.get("rows", []):
            if row.get("label_status") != "labeled":
                continue
            if strategy_id and row.get("strategy_id") != strategy_id:
                continue
            all_obs.append(row)
    return all_obs

def count_labeled_since_last_calibration(date_str: str, strategy_id: str) -> int:
    """计算自上次校准以来的已标注样本数。"""
    last = load_last_calibration_date() or "2000-01-01"
    observations = load_labeled_observations(date_str, strategy_id)
    return sum(1 for o in observations if o.get("date", "") >= last)
```

### 5.2 分布计算

```python
def compute_fit_distribution(date_str: str) -> dict[str, float]:
    """计算当前适配度分布（各等级占比）。"""
    observations = load_labeled_observations(date_str, strategy_id=None)
    total = len(observations)
    if total == 0:
        return {}
    counts = Counter(o["strategy_environment_fit"] for o in observations)
    return {level: count / total for level, count in sorted(counts.items())}

def compute_total_variation_distance(p: dict, q: dict) -> float:
    """计算两个分布的总变差距离。"""
    all_keys = set(p) | set(q)
    return sum(abs(p.get(k, 0) - q.get(k, 0)) for k in all_keys) / 2
```

### 5.3 基线管理

```python
BASELINE_PATH = ROOT / "outputs" / "calibration" / "calibration_baseline.json"

def load_baseline_distribution() -> dict | None:
    if not BASELINE_PATH.exists():
        return None
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

def save_baseline_distribution(date_str: str, distribution: dict) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": date_str,
        "distribution": distribution,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    BASELINE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

---

## 6. 配置文件

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
  "drift_threshold": 0.10,
  "primary_window": 20,
  "bootstrap_n": 2000,
  "auto_feedback_on_pass": true,
  "alert_on_review_needed": true,
  "first_calibration_skip_drift": true
}
```

---

## 7. 输出路径

```text
outputs/calibration/calibration_{date}.json        — 校准报告
outputs/calibration/calibration_baseline.json       — 当前基线分布
outputs/calibration/calibration_manifest.json       — 校准历史索引
outputs/calibration/calibration_alert_{date}.json   — 告警（review_needed 时）
outputs/calibration/calibration_check_{date}.json   — 每日检查记录（即使未触发）
```

---

## 8. 执行命令

```bash
# 每日检查（推荐加入收盘后流水线）
python3 scripts/calibration_trigger.py --date 2026-05-27

# 强制校准（跳过三重门）
python3 scripts/calibration_trigger.py --date 2026-05-27 --force

# 仅检查不执行
python3 scripts/calibration_trigger.py --date 2026-05-27 --dry-run

# 分策略校准
python3 scripts/calibration_trigger.py --date 2026-05-27 --strategy vcp
```

---

## 9. 首次校准的特殊情况处理

根据 `FORWARD_OBSERVATION_PROGRESS_20260523.md`：

| 情况 | 处理 |
|------|------|
| 无历史基线 | 跳过变化门，三重门退化为双重门 |
| 已标注样本为 0 | 样本门不通过，不触发 |
| 账本运行 < 5 天 | 时间门不通过，不触发 |
| 首次校准完成后 | 自动写入基线分布，后续校准恢复三重门 |

预计首次触发：**2026-05-28**（T+6，累计已标注约 288 条，时间门+样本门均满足）。
