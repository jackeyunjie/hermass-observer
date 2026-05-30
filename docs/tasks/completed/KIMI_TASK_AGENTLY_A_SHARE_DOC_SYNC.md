# Kimi 任务：Agently A 股架构文档同步

> 状态：已完成（2026-05-28）

## 任务概述

当前仓库已经完成以下架构收口：

- 系统范围只服务 A 股
- `agently_adapter/a_share_core.py` 是 shared core layer
- `agently_adapter/agently_a_share_flow.py` 是 A 股 core flow
- `agently_adapter/stockpool_daily_runner.py run` 是 full compatibility workflow
- `hermass_platform/api/a_share_service.py` 已拆成 `/run-daily` 与 `/run-full-daily` 双入口

现在需要你只做文档同步，不做代码实现。

## 目标

统一活跃文档中的以下术语边界：

- `core flow`
- `full compatibility workflow`
- `shared core layer`
- `core outputs`
- `public extensions`

并消除以下歧义：

- 不再把 `agently_daily_flow.py` 描述成“默认主线”
- 不再把 `/run-daily` 描述成“全量日流程”
- 不再把 `verify_core_outputs` 和 `verify_public_outputs` 混为一谈

## 范围限制

1. 系统只服务 A 股
2. MT5 / US / Alpaca 只允许以历史归档身份出现
3. 不修改任何代码文件
4. 不修改 State 计算契约
5. 不做破坏性 git 操作
6. 只处理我指定的文档

## 指定文件

- `docs/AGENTLY_A_SHARE_INTEGRATION_PLAN.md`
- `docs/A_SHARE_SERVICE_API.md`
- `workflows/agently_stockpool_dag/README.md`

## 必须统一的表述

### 1. `a_share_core.py`

统一写法：

```text
shared core layer
```

含义：
- A 股最小核心链路的唯一共享实现层
- 负责 shared core steps、core outputs 校验

### 2. `agently_a_share_flow.py`

统一写法：

```text
A 股 core flow
```

含义：
- 对应最小核心链路
- 不是 full workflow

### 3. `agently_daily_flow.py`

统一写法：

```text
full workflow compatibility flow
```

含义：
- 只是对 `stockpool_daily_runner.py run` 的 Agently 包装
- 不再是推荐主入口

### 4. API 边界

统一写法：

```text
/run-daily = core flow
/run-full-daily = full compatibility workflow
```

### 5. 校验边界

统一写法：

```text
verify_core_outputs = core outputs
verify_public_outputs = core outputs + public extensions
```

## 输出要求

不要直接给大段改写正文，先输出：

1. `变更摘要`
2. `按文件列出的修改建议`
3. `仍有歧义的表述`
4. `建议保留原文不改的部分`

## 验收标准

- 三个文件对 `core/full/shared core` 的叫法一致
- `agently_daily_flow.py` 不再被描述为主线
- `/run-daily` 与 `/run-full-daily` 边界明确
- `verify_core_outputs` 与 `verify_public_outputs` 的差异明确
- 不引入任何 MT5 / US 新内容
