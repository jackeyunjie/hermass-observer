---
name: daily-pipeline
description: 运行 A 股日频数据流水线（下载→Foundation→信号→快照）
trigger: 运行流水线 / 更新数据 / 跑一下今天的数据 / 刷新数据
---

# Daily Pipeline Skill

当用户要求运行或刷新数据时，执行完整流水线。

## 架构路径规则

- 活跃系统范围仅限 A 股。
- 这是执行型 skill。
- 长期主路径优先级：
  1. `hermass_platform/api/a_share_service.py`
  2. `agently_adapter/agently_a_share_flow.py`
  3. `agently_adapter/agently_daily_flow.py`
  4. `agently_adapter/stockpool_daily_runner.py`
  5. 历史 shell 脚本
- 当前命令仍使用 shell 包装，是过渡入口，不应被描述为长期主架构。
- cron 只负责触发，不承载业务编排。

## 执行命令

```bash
cd /Users/lv111101/Documents/hermass-observer-product && bash scripts/run_daily_pipeline.sh $(date +%Y-%m-%d)
```

## 流水线步骤

1. 下载日线数据（黑狼 API）
2. 构建 Raw DB
3. 构建 Foundation DB（12 张表）
4. 策略信号账本
5. 策略提醒
6. 前向观察账本（含 MN1 环境分层）
7. 每日快照（50ms 响应）

## 预计耗时

15-35 分钟（取决于网络和数据量）

## 回答模板

流水线完成后，汇报：完成步骤数、是否有错误、最新数据日期。
