# Run Card 复现元数据与标准化回测报告规范

版本：v2.0
日期：2026-05-24
状态：规范文档
关联表：`config/strategy_registry.json`、`outputs/strategy_evaluation/`
关联规范：`docs/STRATEGY_EXECUTION_SPEC.md`、`docs/CALIBRATION_TRIGGER_IMPLEMENTATION_SPEC.md`

---

## 概述

Run Card 是每次校准/验证/回测运行的完整指纹——记录"这次运行用了什么数据、什么参数、什么环境"，使得任何结果都可以被精确复现。

v2.0 在 v1 的基础上增加了：
- 完整的标准化 Markdown 报告模板（覆盖校准、回测、State 搜索三种类型）
- SHA-256 完整性哈希（报告生成后自动计算，任何修改可被检测）
- 跨期稳定性分析和过拟合检测章节
- 与 `calibration_report_v1` schema 和 `strategy_registry.json` 的完整对齐

---

## 1. Run Card JSON Schema（v2）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Hermass Run Card v2",
  "type": "object",
  "required": [
    "run_card_version", "run_id", "run_type", "run_date",
    "data_range", "samples", "parameters", "environment",
    "inputs", "outputs", "verdict", "integrity"
  ],
  "properties": {
    "run_card_version": {
      "type": "string",
      "const": "v2"
    },
    "run_id": {
      "type": "string",
      "description": "唯一运行标识，格式：{run_type}_{strategy}_{YYYYMMDD}_{HHMMSS}",
      "pattern": "^[a-z_]+_[a-z_]+_\\d{8}_\\d{6}$"
    },
    "run_type": {
      "type": "string",
      "enum": ["state_search", "calibration", "backtest", "walk_forward", "attribution", "stability_check"]
    },
    "strategy_id": {
      "type": "string",
      "enum": ["vcp", "ma2560", "bollinger_bandit", "all"]
    },
    "run_date": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 格式，含时区"
    },
    "data_range": {
      "type": "object",
      "required": ["start_date", "end_date"],
      "properties": {
        "start_date": {"type": "string", "format": "date"},
        "end_date": {"type": "string", "format": "date"},
        "trading_days": {"type": "integer", "description": "区间内交易日总数"},
        "labeled_dates": {"type": "integer", "description": "有标注的日期数"},
        "earliest_label": {"type": "string", "format": "date", "description": "最早标注日期"},
        "latest_label": {"type": "string", "format": "date", "description": "最晚标注日期"}
      }
    },
    "samples": {
      "type": "object",
      "required": ["total_selected", "total_labeled"],
      "properties": {
        "total_selected": {"type": "integer", "description": "策略信号筛选出的总样本"},
        "total_labeled": {"type": "integer", "description": "已标注（有未来收益）的样本"},
        "labeled_with_future_data": {"type": "integer"},
        "label_windows": {
          "type": "array",
          "items": {"type": "integer"},
          "description": "收益窗口列表，如 [5, 10, 20]"
        },
        "primary_window": {"type": "integer", "description": "主观察窗口，如 20"},
        "per_fit_level": {
          "type": "object",
          "description": "按适配度等级分组的样本量",
          "additionalProperties": {"type": "integer"}
        },
        "per_lifecycle": {
          "type": "object",
          "description": "按生命周期阶段分组的样本量",
          "additionalProperties": {"type": "integer"}
        }
      }
    },
    "parameters": {
      "type": "object",
      "properties": {
        "primary_window": {"type": "integer", "description": "主观察窗口（如 20）"},
        "min_samples": {"type": "integer", "description": "最小样本门槛"},
        "raw_signals": {
          "type": "array",
          "items": {"type": "string"},
          "description": "使用的信号口径"
        },
        "state_combo_filter": {"type": "string", "nullable": true},
        "path_condition": {"type": "string", "nullable": true, "description": "路径条件描述（如 'D1 近20日收缩后释放'）"},
        "bootstrap_n": {"type": "integer", "description": "Bootstrap 重采样次数"},
        "random_seed": {"type": "integer", "description": "随机种子，确保可复现"},
        "benchmark": {"type": "string", "description": "超额收益基准，如 'market_equal_weight'"},
        "backtest_config": {
          "type": "object",
          "description": "回测专用参数（仅 backtest 类型）",
          "properties": {
            "initial_capital": {"type": "number"},
            "risk_per_trade": {"type": "number"},
            "liquidity_filter_enabled": {"type": "boolean"},
            "exit_rules_enabled": {"type": "boolean"},
            "position_sizing": {"type": "string", "enum": ["fixed", "atr_dynamic"]}
          }
        },
        "wfa_config": {
          "type": "object",
          "description": "Walk-Forward 参数（仅 wfa 类型）"
        }
      }
    },
    "environment": {
      "type": "object",
      "required": ["python_version", "numpy_version", "duckdb_version", "platform"],
      "properties": {
        "python_version": {"type": "string"},
        "numpy_version": {"type": "string"},
        "duckdb_version": {"type": "string"},
        "pandas_version": {"type": "string"},
        "platform": {"type": "string"},
        "hostname": {"type": "string"},
        "git_commit": {"type": "string", "description": "代码版本（前 8 位）"},
        "git_dirty": {"type": "boolean", "description": "运行时是否有未提交的更改"}
      }
    },
    "inputs": {
      "type": "object",
      "required": ["foundation_db"],
      "properties": {
        "foundation_db": {"type": "string", "description": "Foundation DB 路径"},
        "foundation_db_size_bytes": {"type": "integer"},
        "foundation_db_checksum": {"type": "string", "description": "SHA-256 前 16 位"},
        "foundation_db_date": {"type": "string", "format": "date", "description": "Foundation DB 生成日期"},
        "strategy_registry": {"type": "string"},
        "ma2560_rule_config": {"type": "string", "nullable": true},
        "vcp_rule_config": {"type": "string", "nullable": true},
        "market_phase_config": {"type": "string", "nullable": true},
        "calibration_trigger_config": {"type": "string", "nullable": true},
        "forward_observation_dir": {"type": "string", "nullable": true},
        "additional_inputs": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": {"type": "string"},
              "path": {"type": "string"},
              "checksum": {"type": "string"}
            }
          },
          "description": "其他输入文件"
        }
      }
    },
    "outputs": {
      "type": "object",
      "properties": {
        "json_path": {"type": "string"},
        "md_path": {"type": "string"},
        "csv_path": {"type": "string", "nullable": true},
        "html_path": {"type": "string", "nullable": true},
        "run_card_path": {"type": "string", "description": "本 Run Card JSON 的路径"}
      }
    },
    "verdict": {
      "type": "object",
      "required": ["overall"],
      "properties": {
        "overall": {
          "type": "string",
          "enum": ["pass", "marginal", "fail", "insufficient_data", "review_needed"]
        },
        "summary": {"type": "string", "description": "一句话结论"},
        "top_hypothesis": {
          "type": "object",
          "properties": {
            "name": {"type": "string"},
            "matched_n": {"type": "integer"},
            "outside_n": {"type": "integer"},
            "mean_excess": {"type": "number"},
            "ci_95_lo": {"type": "number"},
            "ci_95_hi": {"type": "number"},
            "win_rate": {"type": "number"},
            "win_rate_ci_lo": {"type": "number"},
            "win_rate_ci_hi": {"type": "number"},
            "payoff_ratio": {"type": "number"},
            "t_stat": {"type": "number"}
          }
        },
        "fit_ordering": {
          "type": "object",
          "description": "适配度排序有效性（校准类型专用）",
          "properties": {
            "valid": {"type": "boolean"},
            "sorted_correctly": {"type": "boolean"},
            "best_above_all": {"type": "boolean"},
            "means": {"type": "object", "additionalProperties": {"type": "number"}}
          }
        },
        "cross_period_stability": {
          "type": "object",
          "description": "跨期稳定性评估",
          "properties": {
            "n_folds": {"type": "integer"},
            "fold_results": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "fold_id": {"type": "integer"},
                  "start_date": {"type": "string"},
                  "end_date": {"type": "string"},
                  "n": {"type": "integer"},
                  "mean_excess": {"type": "number"},
                  "win_rate": {"type": "number"},
                  "t_stat": {"type": "number"}
                }
              }
            },
            "consistency_ratio": {"type": "number", "description": "方向一致的折数占比"},
            "stable": {"type": "boolean"}
          }
        },
        "overfit_detection": {
          "type": "object",
          "description": "过拟合检测结果",
          "properties": {
            "is_vs_oos_ratio": {"type": "number", "description": "样本内/样本外超额比值"},
            "degradation_pct": {"type": "number", "description": "样本外绩效下降百分比"},
            "overfit_risk": {"type": "string", "enum": ["low", "medium", "high"]},
            "n_params_vs_n_samples": {"type": "number", "description": "参数数量/样本量比值"},
            "multiple_testing_penalty": {"type": "number", "description": "多重检验惩罚后的 p 值"}
          }
        }
      }
    },
    "integrity": {
      "type": "object",
      "required": ["report_sha256", "report_generated_at"],
      "properties": {
        "report_sha256": {
          "type": "string",
          "description": "对应 Markdown 报告的 SHA-256 哈希（64 字符十六进制）",
          "pattern": "^[a-f0-9]{64}$"
        },
        "report_generated_at": {
          "type": "string",
          "format": "date-time"
        },
        "run_card_sha256": {
          "type": "string",
          "description": "本 Run Card JSON 自身的 SHA-256（计算 integrity 字段前的版本）",
          "pattern": "^[a-f0-9]{64}$"
        },
        "immutable": {
          "type": "boolean",
          "const": true,
          "description": "标记为不可修改。任何变更应生成新的 run_id。"
        }
      }
    },
    "notes": {
      "type": "string",
      "description": "自由文本备注"
    }
  }
}
```

---

## 2. 完整性哈希机制

### 2.1 设计目标

报告生成后不可修改。任何对 Markdown 报告或 Run Card JSON 的篡改都可被检测到。

### 2.2 计算流程

```text
步骤 1: 生成 Markdown 报告内容（report_content）
步骤 2: 计算 report_sha256 = SHA256(report_content)
步骤 3: 构建 Run Card JSON（不含 integrity 字段）
步骤 4: 计算 run_card_sha256 = SHA256(json.dumps(run_card_without_integrity, sort_keys=True))
步骤 5: 填入 integrity 字段
步骤 6: 写入两个文件
```

### 2.3 实现代码

```python
import hashlib
import json
from datetime import datetime, timezone


def compute_sha256(content: str | bytes) -> str:
    """计算 SHA-256 哈希。"""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def build_integrity(report_content: str, run_card: dict) -> dict:
    """
    构建完整性哈希字段。

    流程：
    1. 计算报告内容的 SHA-256
    2. 从 Run Card 中移除 integrity 字段（如果存在）
    3. 计算 Run Card JSON 的 SHA-256
    4. 返回 integrity 字段
    """
    report_sha256 = compute_sha256(report_content)

    # 计算 Run Card 自身哈希（排除 integrity 字段）
    run_card_copy = {k: v for k, v in run_card.items() if k != "integrity"}
    run_card_json = json.dumps(run_card_copy, sort_keys=True, ensure_ascii=False)
    run_card_sha256 = compute_sha256(run_card_json)

    return {
        "report_sha256": report_sha256,
        "report_generated_at": datetime.now(timezone.utc).isoformat(),
        "run_card_sha256": run_card_sha256,
        "immutable": True,
    }


def verify_integrity(report_path: str, run_card_path: str) -> dict:
    """
    验证报告和 Run Card 的完整性。

    返回：
        {
            "report_valid": bool,       # 报告是否未被篡改
            "run_card_valid": bool,     # Run Card 是否未被篡改
            "report_expected": str,     # 期望的报告哈希
            "report_actual": str,       # 实际的报告哈希
            "run_card_expected": str,   # 期望的 Run Card 哈希
            "run_card_actual": str,     # 实际的 Run Card 哈希
        }
    """
    # 加载 Run Card
    with open(run_card_path, "r", encoding="utf-8") as f:
        run_card = json.load(f)

    integrity = run_card.get("integrity", {})
    expected_report_hash = integrity.get("report_sha256", "")
    expected_rc_hash = integrity.get("run_card_sha256", "")

    # 验证报告
    with open(report_path, "r", encoding="utf-8") as f:
        report_content = f.read()
    actual_report_hash = compute_sha256(report_content)

    # 验证 Run Card（排除 integrity 字段）
    run_card_copy = {k: v for k, v in run_card.items() if k != "integrity"}
    run_card_json = json.dumps(run_card_copy, sort_keys=True, ensure_ascii=False)
    actual_rc_hash = compute_sha256(run_card_json)

    return {
        "report_valid": actual_report_hash == expected_report_hash,
        "run_card_valid": actual_rc_hash == expected_rc_hash,
        "report_expected": expected_report_hash,
        "report_actual": actual_report_hash,
        "run_card_expected": expected_rc_hash,
        "run_card_actual": actual_rc_hash,
    }
```

### 2.4 修正流程

如果发现报告被篡改（hash 不匹配），处理方式：

```text
1. 不覆盖原报告
2. 生成新的 run_id（原 run_id + "_amended_{YYYYMMDD}"）
3. 在 notes 字段注明修正原因
4. 保留原始 run_card 和报告作为历史记录
```

---

## 3. 标准化 Markdown 报告模板

### 3.1 校准报告模板

```markdown
# 校准报告 — {run_id}

> 本报告由系统自动生成，内容不可修改。任何变更将生成新的 run_id。
> 报告哈希：`{report_sha256}`

---

## 一、Run Card 元数据

| 字段 | 值 |
|------|-----|
| Run ID | `{run_id}` |
| 运行类型 | calibration |
| 策略 | {strategy_id} |
| 运行时间 | {run_date} |
| 数据区间 | {start_date} 至 {end_date} |
| 交易日数 | {trading_days} |
| 已标注日期 | {labeled_dates} |
| 总样本 | {total_selected} → 已标注 {total_labeled} |
| 主观察窗口 | {primary_window} 日 |
| Bootstrap 次数 | {bootstrap_n}（seed={random_seed}） |
| Foundation DB | {foundation_db} |
| DB 校验和 | `{db_checksum}` |
| Python | {python_version} |
| NumPy | {numpy_version} |
| DuckDB | {duckdb_version} |
| 代码版本 | `{git_commit}` |
| 完整性哈希 | `{report_sha256}` |

### 三重门检查

| 门槛 | 通过 | 详情 |
|------|------|------|
| 时间门 | {time_passed} | 距上次校准 {days} 天（阈值 {threshold}） |
| 样本门 | {sample_passed} | 新增 {labeled}/{threshold} 已标注 |
| 变化门 | {drift_passed} | 分布偏移 {drift}（阈值 {threshold}） |

---

## 二、统计摘要

### 适配度-收益相关性

> 主观察窗口：{primary_window} 日超额收益 | 基准：{benchmark}

| 适配度等级 | n | 平均超额 | 95% CI | 胜率 | 95% CI | 盈亏比 | t-stat |
|---|---:|---:|---:|---:|---:|---:|---:|
| 最佳适配 | {n} | {mean_excess} | [{ci_lo}, {ci_hi}] | {win_rate} | [{wr_lo}, {wr_hi}] | {payoff} | {t_stat} |
| 适配 | ... | ... | ... | ... | ... | ... | ... |
| 弱适配 | ... | ... | ... | ... | ... | ... | ... |

### 生命周期-收益相关性

| 生命周期 | n | 平均超额 | 95% CI | 胜率 | t-stat |
|---|---:|---:|---:|---:|---:|
| 新生 | {n} | {mean} | [{lo}, {hi}] | {wr} | {t} |
| 行进 | ... | ... | ... | ... | ... |
| 延展 | ... | ... | ... | ... | ... |

### 适配度排序有效性

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 排序递减 | {sorted_correctly} | 适配度从高到低，超额收益是否递减 |
| 最佳高于均值 | {best_above_all} | 最佳适配的超额是否高于全样本均值 |
| **总判定** | **{overall}** | — |

适配度均值序列：{最佳适配: X%, 适配: Y%, 弱适配: Z%}

---

## 三、分组详情

### 按 State 组合分组（Top 10 按 |20日超额| 排序）

| 排名 | MN1/W1/D1 | 样本 | 20d 超额 | 95% CI | 胜率 | 盈亏比 | t-stat |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | {combo} | {n} | {excess} | [{lo}, {hi}] | {wr} | {payoff} | {t} |
| 2 | ... | ... | ... | ... | ... | ... | ... |

### 假设对照表

| 假设 | 命中 n | 未命中 n | 20d 超额（命中） | 20d 超额（未命中） | 差异 | t-stat | 结论 |
|------|---:|---:|---:|---:|---:|---:|---|
| {hypothesis_1} | {n1} | {n2} | {e1} | {e2} | {diff} | {t} | {conclusion} |
| {hypothesis_2} | ... | ... | ... | ... | ... | ... | ... |

### 多窗口收益表（Top 假设）

| 窗口 | n | 平均超额 | 95% CI | 胜率 | t-stat |
|---|---:|---:|---:|---:|---:|
| 5d | {n} | {e} | [{lo}, {hi}] | {wr} | {t} |
| 10d | {n} | {e} | [{lo}, {hi}] | {wr} | {t} |
| 20d | {n} | {e} | [{lo}, {hi}] | {wr} | {t} |
| 30d | {n} | {e} | [{lo}, {hi}] | {wr} | {t} |
| 60d | {n} | {e} | [{lo}, {hi}] | {wr} | {t} |

---

## 四、跨期稳定性

> 将数据区间按时间等分为 {n_folds} 折，检验结论在各子区间是否方向一致。

| 折 | 区间 | 样本 | 平均超额 | 胜率 | t-stat | 方向 |
|---:|---|---:|---:|---:|---:|:---|
| 1 | {start} ~ {end} | {n} | {e} | {wr} | {t} | {方向} |
| 2 | ... | ... | ... | ... | ... | ... |

| 指标 | 值 |
|------|-----|
| 方向一致折数 | {consistent}/{total} |
| 一致性比率 | {ratio} |
| 稳定性判定 | **{stable}** |

---

## 五、过拟合检测

| 检测项 | 值 | 风险等级 | 说明 |
|--------|-----|----------|------|
| 样本内/样本外比值 | {ratio} | {risk} | > 2.0 为高风险 |
| 样本外绩效下降 | {pct}% | {risk} | > 50% 为高风险 |
| 参数数/样本量 | {ratio} | {risk} | > 0.01 为高风险 |
| 多重检验惩罚后 p 值 | {p_value} | {risk} | > 0.05 为不显著 |
| **综合过拟合风险** | — | **{overall_risk}** | — |

### 过拟合检测说明

- **样本内/样本外比值**：将数据分为前 70%（样本内）和后 30%（样本外），比较两段的超额收益。比值 > 2.0 说明样本外表现大幅衰减。
- **参数数/样本量**：参数越多、样本越少，过拟合风险越高。
- **多重检验惩罚**：如果同一数据上测试了 k 个假设，需要将原始 p 值乘以 k（Bonferroni 校正）。

---

## 六、Run Card（JSON 完整数据）

> 以下 JSON 为本次运行的完整复现元数据。此 JSON 的 SHA-256 哈希记录在文件头部。

```json
{run_card_json}
```

---

## 七、免责声明

本报告由 Hermass Observer 系统自动生成，仅供内部研究参考，不构成任何形式的投资建议。

- 校准通过不代表策略"有效"，只代表适配度排序与历史收益方向一致。
- 所有统计数字均为历史回溯结果，不代表未来表现。
- 任何规则变更仍需人工确认。
- Past performance is not indicative of future results.

---

> 报告生成时间：{generated_at}
> 报告哈希：`{report_sha256}`
> 如需验证报告完整性，运行：`python3 scripts/verify_run_card.py --run-id {run_id}`
```

### 3.2 回测报告模板

```markdown
# 回测报告 — {run_id}

> 本报告由系统自动生成，内容不可修改。
> 报告哈希：`{report_sha256}`

---

## 一、Run Card 元数据

| 字段 | 值 |
|------|-----|
| Run ID | `{run_id}` |
| 运行类型 | backtest |
| 策略 | {strategy_id} |
| 运行时间 | {run_date} |
| 回测区间 | {start_date} 至 {end_date} |
| 交易日数 | {trading_days} |
| 初始资金 | ¥{initial_capital:,.0f} |
| 单笔风险 | {risk_per_trade}% |
| 流动性过滤 | {enabled/disabled} |
| 出场规则 | {enabled/disabled} |
| 仓位模式 | {fixed/atr_dynamic} |
| Foundation DB | {foundation_db} |
| DB 校验和 | `{db_checksum}` |
| 随机种子 | {random_seed} |
| Python | {python_version} |
| NumPy | {numpy_version} |
| DuckDB | {duckdb_version} |
| 代码版本 | `{git_commit}` |
| 完整性哈希 | `{report_sha256}` |

---

## 二、绩效概览

| 指标 | 值 |
|------|-----|
| 年化收益 | {annual_return}% |
| 夏普比率 | {sharpe_ratio} |
| 最大回撤 | {max_drawdown}% |
| 最大回撤持续 | {max_dd_duration} 天 |
| 总交易笔数 | {total_trades} |
| 胜率 | {win_rate}% |
| 盈亏比 | {payoff_ratio} |
| 平均持仓天数 | {avg_hold_days} |
| 总换手 | {total_turnover} |

---

## 三、入场质量分析

### 量价配合统计

| 信号级别 | 笔数 | 胜率 | 平均收益 | 盈亏比 |
|----------|---:|---:|---:|---:|
| A（放量突破） | {n} | {wr} | {ret} | {payoff} |
| B（量能偏弱） | ... | ... | ... | ... |
| C（无量突破） | ... | ... | ... | ... |

### 假突破过滤效果

| 指标 | 过滤前 | 过滤后 | 改善 |
|------|--------|--------|------|
| 信号数 | {before} | {after} | — |
| 胜率 | {wr_before} | {wr_after} | +{diff} pp |
| 平均收益 | {ret_before} | {ret_after} | +{diff}% |

---

## 四、出场规则分析

### 各出场类型触发频率

| 出场类型 | 触发笔数 | 占比 | 平均盈亏 | 平均持仓天数 |
|----------|---:|---:|---:|---:|
| 假突破离场 | {n} | {pct} | {pnl} | {days} |
| 硬止损 | ... | ... | ... | ... |
| ATR 止损 | ... | ... | ... | ... |
| 技术止损 | ... | ... | ... | ... |
| 时间退出 | ... | ... | ... | ... |
| 移动止损 | ... | ... | ... | ... |
| 止盈 | ... | ... | ... | ... |

---

## 五、按 State 环境分层

### 按适配度等级

| 适配度 | 笔数 | 胜率 | 平均收益 | 夏普 |
|--------|---:|---:|---:|---:|
| 最佳适配 | {n} | {wr} | {ret} | {sharpe} |
| 适配 | ... | ... | ... | ... |
| 弱适配 | ... | ... | ... | ... |

### 按生命周期阶段

| 阶段 | 笔数 | 胜率 | 平均收益 | 夏普 |
|------|---:|---:|---:|---:|
| 新生 | {n} | {wr} | {ret} | {sharpe} |
| 行进 | ... | ... | ... | ... |
| 延展 | ... | ... | ... | ... |

---

## 六、月度收益热力图

| 年\月 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|-------|---|---|---|---|---|---|---|---|---|---|---|---|
| {year} | {ret}% | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |

---

## 七、跨期稳定性

> 将回测区间按时间等分为 5 折，检验绩效在各子区间是否稳定。

| 折 | 区间 | 交易笔数 | 胜率 | 平均收益 | 夏普 |
|---:|---|---:|---:|---:|---:|
| 1 | {start} ~ {end} | {n} | {wr} | {ret} | {sharpe} |
| 2 | ... | ... | ... | ... | ... |

| 指标 | 值 |
|------|-----|
| 各折胜率标准差 | {std} |
| 各折夏普标准差 | {std} |
| 稳定性判定 | **{stable}** |

---

## 八、过拟合检测

| 检测项 | 值 | 风险等级 |
|--------|-----|----------|
| 样本内/样本外收益比 | {ratio} | {risk} |
| 样本外收益下降 | {pct}% | {risk} |
| 参数数/交易笔数 | {ratio} | {risk} |
| **综合过拟合风险** | — | **{overall_risk}** |

---

## 九、流动性过滤统计

| 指标 | 值 |
|------|-----|
| 过滤前信号数 | {before} |
| 过滤后信号数 | {after} |
| 过滤通过率 | {pct}% |
| 主要过滤原因 | {top_reasons} |

---

## 十、Run Card（JSON 完整数据）

```json
{run_card_json}
```

---

## 十一、免责声明

本报告由 Hermass Observer 系统自动生成，仅供内部研究参考，不构成任何形式的投资建议。

- 回测结果基于历史数据，不代表未来表现。
- 回测中的交易执行假设（滑点、流动性）可能与实际有偏差。
- 任何投资决策请基于自身风险承受能力独立判断。
- Past performance is not indicative of future results.

---

> 报告生成时间：{generated_at}
> 报告哈希：`{report_sha256}`
```

### 3.3 State 搜索报告模板

```markdown
# State 组合搜索报告 — {run_id}

> 报告哈希：`{report_sha256}`

---

## 一、Run Card 元数据

| 字段 | 值 |
|------|-----|
| Run ID | `{run_id}` |
| 运行类型 | state_search |
| 策略 | {strategy_id} |
| 信号口径 | {raw_signals} |
| 数据区间 | {start_date} 至 {end_date} |
| 已标注样本 | {total_labeled} |
| 已标注日期 | {labeled_dates} |
| 主窗口 | {primary_window} 日 |
| 最小样本 | {min_samples} |
| Bootstrap | {bootstrap_n} 次（seed={random_seed}） |
| Foundation DB | {foundation_db}（{checksum}） |
| 完整性哈希 | `{report_sha256}` |

---

## 二、研究假设对照

> 按 |20日超额| 排序。每个假设标注样本量和验证区间。

### 假设 1：{hypothesis_name}

- 命中样本：{matched_n}
- 未命中样本：{outside_n}

| 口径 | 窗口 | n | 平均超额 | 95% CI | 胜率 | 95% CI | 盈亏比 | t-stat |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| matched | 5d | {n} | {e} | [{lo}, {hi}] | {wr} | [{wlo}, {whi}] | {payoff} | {t} |
| matched | 10d | ... | ... | ... | ... | ... | ... | ... |
| matched | 20d | ... | ... | ... | ... | ... | ... | ... |
| outside | 20d | ... | ... | ... | ... | ... | ... | ... |
| all | 20d | ... | ... | ... | ... | ... | ... | ... |

### 假设 2：{hypothesis_name}

（同上格式）

---

## 三、精确 State 组合 Top 10

| 排名 | MN1/W1/D1 | 样本 | 5d 超额 | 10d 超额 | 20d 超额 | 20d 胜率 | t-stat |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | {combo} | {n} | {e5} | {e10} | {e20} | {wr} | {t} |
| 2 | ... | ... | ... | ... | ... | ... | ... |

---

## 四、跨期稳定性

（同校准报告格式）

---

## 五、过拟合检测

（同校准报告格式）

---

## 六、Run Card（JSON 完整数据）

```json
{run_card_json}
```

---

## 七、免责声明

本报告仅供研究参考，不构成投资建议。
统计数字基于历史回溯，不代表未来表现。

---

> 报告生成时间：{generated_at}
> 报告哈希：`{report_sha256}`
```

---

## 4. 与现有系统的对接

### 4.1 strategy_registry.json

每个策略的 `latest_local_finding` 引用 Run Card ID：

```json
{
  "vcp": {
    "latest_local_finding": {
      "run_card_id": "state_search_vcp_20260523_073000",
      "as_of": "2026-05-01",
      "sample_count": 43259,
      "report_hash": "a1b2c3d4...",
      "summary": "D1 近20日收缩后释放路径通过，20d超额 +1.66%，t-stat=3.98"
    }
  }
}
```

### 4.2 校准报告（calibration_report_v1 对齐）

`outputs/calibration/calibration_{date}.json` 中的 `run_card` 字段升级为完整 Run Card v2：

```json
{
  "schema_version": "calibration_report_v1",
  "date": "2026-05-23",
  "run_card": {
    "run_card_version": "v2",
    "run_id": "calibration_all_20260523_232756",
    "run_type": "calibration",
    "strategy_id": "all",
    "...": "..."
  },
  "fit_return_table": { "...": "..." },
  "verdict": { "...": "..." }
}
```

### 4.3 输出路径

```text
outputs/run_cards/{run_id}.json           — 完整 Run Card JSON
outputs/run_cards/{run_id}.md             — 标准化 Markdown 报告
outputs/run_cards/run_cards_index.json    — 索引文件（所有 run_id 列表 + hash）
outputs/run_cards/verify_log_{date}.json  — 每日完整性校验日志
```

### 4.4 索引文件格式

```json
{
  "last_updated": "2026-05-24T10:00:00+00:00",
  "total_runs": 15,
  "runs": [
    {
      "run_id": "state_search_vcp_20260523_073000",
      "run_type": "state_search",
      "strategy_id": "vcp",
      "run_date": "2026-05-23T07:30:00+00:00",
      "verdict": "pass",
      "report_hash": "a1b2c3d4...",
      "json_path": "outputs/run_cards/state_search_vcp_20260523_073000.json",
      "md_path": "outputs/run_cards/state_search_vcp_20260523_073000.md"
    }
  ]
}
```

---

## 5. 自动生成函数

### 5.1 Run Card 构建

```python
def build_run_card_v2(
    run_type: str,
    strategy_id: str,
    foundation_db: Path,
    parameters: dict,
    samples: dict,
    verdict: dict,
    outputs: dict,
    notes: str = "",
) -> dict:
    """生成标准 Run Card v2。"""
    import platform
    import subprocess
    import numpy
    import duckdb

    run_id = f"{run_type}_{strategy_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Git 信息
    try:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
        git_dirty = subprocess.call(
            ["git", "diff", "--quiet"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ) != 0
    except Exception:
        git_commit = "unknown"
        git_dirty = True

    run_card = {
        "run_card_version": "v2",
        "run_id": run_id,
        "run_type": run_type,
        "strategy_id": strategy_id,
        "run_date": datetime.now(timezone.utc).isoformat(),
        "samples": samples,
        "parameters": {
            "random_seed": 42,
            "bootstrap_n": 2000,
            "benchmark": "market_equal_weight",
            **parameters,
        },
        "environment": {
            "python_version": platform.python_version(),
            "numpy_version": numpy.__version__,
            "duckdb_version": duckdb.__version__,
            "pandas_version": pd.__version__,
            "platform": platform.platform(),
            "hostname": platform.node(),
            "git_commit": git_commit,
            "git_dirty": git_dirty,
        },
        "inputs": {
            "foundation_db": str(foundation_db),
            "foundation_db_size_bytes": foundation_db.stat().st_size,
            "foundation_db_checksum": file_checksum(foundation_db)[:16],
            "foundation_db_date": extract_date_from_path(foundation_db),
        },
        "outputs": outputs,
        "verdict": verdict,
        "notes": notes,
        # integrity 字段在报告生成后填充
    }

    return run_card
```

### 5.2 报告生成与哈希绑定

```python
def write_report_with_integrity(
    run_card: dict,
    report_content: str,
    output_dir: Path,
) -> tuple[Path, Path]:
    """
    生成报告并绑定完整性哈希。

    流程：
    1. 计算报告哈希
    2. 构建 Run Card 自身哈希
    3. 填入 integrity 字段
    4. 写入 .md 和 .json 文件
    """
    run_id = run_card["run_id"]

    # 1. 计算报告哈希
    report_hash = compute_sha256(report_content)

    # 2. 构建 Run Card 自身哈希（不含 integrity）
    rc_json = json.dumps(run_card, sort_keys=True, ensure_ascii=False)
    rc_hash = compute_sha256(rc_json)

    # 3. 填入 integrity
    run_card["integrity"] = {
        "report_sha256": report_hash,
        "report_generated_at": datetime.now(timezone.utc).isoformat(),
        "run_card_sha256": rc_hash,
        "immutable": True,
    }

    # 4. 写入文件
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / f"{run_id}.md"
    md_path.write_text(report_content, encoding="utf-8")

    json_path = output_dir / f"{run_id}.json"
    json_path.write_text(
        json.dumps(run_card, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 5. 更新索引
    update_run_cards_index(output_dir, run_card)

    return md_path, json_path


def update_run_cards_index(output_dir: Path, run_card: dict) -> None:
    """更新 run_cards_index.json 索引文件。"""
    index_path = output_dir / "run_cards_index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index = {"last_updated": "", "total_runs": 0, "runs": []}

    entry = {
        "run_id": run_card["run_id"],
        "run_type": run_card["run_type"],
        "strategy_id": run_card["strategy_id"],
        "run_date": run_card["run_date"],
        "verdict": run_card.get("verdict", {}).get("overall", "unknown"),
        "report_hash": run_card.get("integrity", {}).get("report_sha256", ""),
        "json_path": f"outputs/run_cards/{run_card['run_id']}.json",
        "md_path": f"outputs/run_cards/{run_card['run_id']}.md",
    }

    index["runs"].append(entry)
    index["total_runs"] = len(index["runs"])
    index["last_updated"] = datetime.now(timezone.utc).isoformat()

    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
```

---

## 6. 完整性校验脚本

```bash
# 验证单个 Run Card
python3 scripts/verify_run_card.py --run-id state_search_vcp_20260523_073000

# 验证所有 Run Card
python3 scripts/verify_run_card.py --all

# 每日校验（推荐加入收盘后流水线）
python3 scripts/verify_run_card.py --date 2026-05-24
```

### 校验输出示例

```json
{
  "date": "2026-05-24",
  "total_checked": 15,
  "valid": 14,
  "invalid": 1,
  "invalid_details": [
    {
      "run_id": "calibration_all_20260523_232756",
      "report_valid": false,
      "run_card_valid": true,
      "report_expected": "a1b2c3d4...",
      "report_actual": "e5f6g7h8...",
      "action": "report may have been modified"
    }
  ]
}
```

---

## 7. 最佳实践

### 7.1 何时生成 Run Card

| 场景 | run_type | 触发方式 |
|------|----------|----------|
| State 组合搜索 | state_search | search_*_optimal_state.py 运行时自动生成 |
| 校准触发 | calibration | calibration_trigger.py 运行时自动生成 |
| 完整回测 | backtest | run_strategy_backtest 运行时自动生成 |
| 跨期稳定性检查 | stability_check | validate_state_combo_stability.py 运行时自动生成 |
| 绩效归因 | attribution | performance_attribution.py 运行时自动生成 |

### 7.2 何时校验 Run Card

| 时机 | 操作 |
|------|------|
| 每日收盘后 | `verify_run_card.py --date {today}` |
| 引用历史结论前 | `verify_run_card.py --run-id {id}` |
| 写入 strategy_registry.json 前 | 验证对应 Run Card 完整性 |
| 发布报告前 | 验证所有关联 Run Card |

### 7.3 报告修订规则

| 情况 | 处理方式 |
|------|----------|
| 发现报告有误 | 生成新 run_id（`{原id}_amended_{date}`），notes 注明修正原因 |
| 数据源更新 | 生成新 run_id，不覆盖原报告 |
| 参数调整 | 生成新 run_id，视为新的实验 |
| 格式修正（不影响数据） | 可原地修正，但需更新 integrity 哈希 |

---

## 附录

### A. v1 → v2 变更清单

| 变更项 | v1 | v2 |
|--------|----|----|
| run_card_version | "v1" | "v2" |
| integrity 字段 | 无 | 新增（report_sha256 + run_card_sha256） |
| Markdown 报告 | 简单格式 | 三套标准化模板（校准/回测/搜索） |
| 跨期稳定性 | 无 | 新增章节 |
| 过拟合检测 | 无 | 新增章节 |
| 环境信息 | 基础 | 新增 git_commit、git_dirty、pandas_version |
| 索引文件 | 无 | 新增 run_cards_index.json |
| 完整性校验脚本 | 无 | 新增 verify_run_card.py |
| verdict 扩展 | 基础 | 新增 cross_period_stability、overfit_detection |

### B. 文档版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-05-23 | 初版：Run Card JSON Schema + 基础 Markdown 模板 |
| v2.0 | 2026-05-24 | 升级：SHA-256 完整性哈希、三套标准化报告模板、跨期稳定性、过拟合检测、与 calibration_report_v1 完整对齐 |
