# Kimi 任务：A 股兼容闭环语义审计

> 状态：已完成（2026-05-28）

## 任务概述

当前项目已经把 A 股主线拆成：

- shared core layer
- core flow
- full compatibility workflow

但仓库里可能仍有一些描述把这些边界混在一起。你的任务是只做审计，不做代码改动。

## 审计目标

扫描以下关键词及其上下文，找出语义不一致之处：

- `agently_daily_flow.py`
- `agently_a_share_flow.py`
- `run-daily`
- `run-full-daily`
- `verify_core_outputs`
- `verify_public_outputs`
- `shared core`
- `compatibility wrapper`
- `full workflow`

## 范围限制

1. 只服务 A 股语境
2. 不引入 MT5 / US / Alpaca 新讨论
3. 不做代码修改
4. 不做文档直接改写
5. 只输出问题清单

## 审计范围

- `docs/`
- `workflows/agently_stockpool_dag/`
- `README.md`
- `hermass_platform/api/`
- `agently_adapter/`

## 输出格式

按严重度排序输出：

### 1. 高优先级歧义

格式：

```text
文件路径
当前表述
问题原因
建议统一成什么
```

### 2. 中优先级歧义

同上格式。

### 3. 可忽略历史残留

只列出，不建议修改。

## 验收标准

- 明确列出哪些地方仍把 `core flow` 与 `full compatibility workflow` 混用
- 明确列出哪些地方仍把 `verify_core_outputs` 与 `verify_public_outputs` 混用
- 不把 archive 文档当成活跃问题
