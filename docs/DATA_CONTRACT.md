# Hermass Observer Product Data Contract

日期：2026-05-18

## 1. 必需文件

```text
fixtures/daily_observation_card.json
fixtures/p116d_omni_summary.json
reports/import_manifest.json
```

## 2. daily_observation_card.json 必需字段

```text
schema_version
as_of_date
data_level_current
cards
research_only_flag
```

每个 card 必须至少含：

```text
code
observation_reason
research_only_flag
```

## 3. p116d_omni_summary.json 必需字段

```text
schema_version
data_level
latest_sync_date
symbol_count
d1_observer_rows
w1_observer_rows
mn1_observer_rows
omni_rows
research_only_flag
```

## 4. 禁止字段 / 文案

```text
D1视角_MN1状态
D1_view_MN1_state
MN1混沌值_仅背景
W1混沌值_仅背景
盘前保守口径
prior_high_60 作为关键位
买入
卖出
加仓
减仓
止盈
止损
荐股
收益承诺
```

## 5. 数据层级

当前允许：

```text
L2_OFFICIAL_SR_KEY_POSITION_STATE_OBSERVATION
L2_OMNI_CYCLE_ALIGNMENT_SMOKE
```

不允许产品层自称：

```text
P17 verdict
P35 conclusion
P34 fund-manager conclusion
策略已验证有效
```
