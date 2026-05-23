# Hermass Observer Product Technical Design

日期：2026-05-18
状态：V0.1_PRODUCT_SHELL

## 1. 架构原则

产品工程只读研究母库标准产物，不在产品层重新计算金融公式。

```text
research repo -> standard fixtures -> product public pages -> verify -> publish
```

## 2. 上游母库

默认路径：

```text
../hongrun-chaos-trading-system
```

必要上游产物：

```text
reports/p108_daily_consumer_observation_card_20260518/fixtures/daily_observation_card.json
reports/p108_daily_consumer_observation_card_20260518/index.html
outputs/p116d_ashare_omni_cycle_alignment_20260518/p116d_ashare_omni_cycle_alignment.duckdb
reports/p116_data_foundation_acceleration_20260518/p116d_ashare_omni_cycle_alignment_summary.json
```

## 3. 产品目录

```text
public/index.html
fixtures/daily_observation_card.json
fixtures/p116d_omni_summary.json
reports/import_manifest.json
scripts/import_from_research_repo.py
scripts/verify_release.py
```

## 4. 数据边界

产品层不得出现：

```text
prior_high_60 被称为关键位
D1视角_MN1状态
D1_view_MN1_state
MN1混沌值_仅背景
W1混沌值_仅背景
```

产品层必须保留：

```text
research_only_flag
as_of_date
data_level_current
schema_version
```

## 5. 发布流程

```text
1. 母库跑完 daily release
2. 产品层 import_from_research_repo.py
3. 产品层 verify_release.py
4. 打开 public/index.html
5. 人工确认后对外分发
```

## 6. 回测接入位置

回测结果未来只从母库标准输出导入。

产品层只展示：

```text
state_pool_id
sample_count
coverage_status
time_drift_audit_status
robustness_status
research_only_flag
```

不展示原始逐笔交易，不输出行动指令。
