# 本地模型任务：机械统一 Agently A 股术语

> 状态：已完成（2026-05-28）

## 任务概述

这是一个机械统一任务，不需要架构判断，只需要按既定规则检查表述一致性。

## 固定规则

1. 系统范围：A-share only
2. 禁止引入 MT5 / US / Alpaca 作为活跃方向
3. 不修改任何代码逻辑
4. 不删除文件
5. 不做 git reset / checkout

## 统一规则

### 规则 1

看到：

```text
agently_daily_flow.py 是主流程
```

改成建议：

```text
agently_daily_flow.py 是 full workflow compatibility flow
```

### 规则 2

看到：

```text
run-daily = 日流程 / 全量流程
```

改成建议：

```text
run-daily = core flow
```

### 规则 3

看到：

```text
run-full-daily 未定义或模糊
```

改成建议：

```text
run-full-daily = full compatibility workflow
```

### 规则 4

看到：

```text
verify_public_outputs = 全部产物
```

改成建议：

```text
verify_public_outputs = core outputs + public extensions
```

### 规则 5

看到：

```text
a_share_core.py = action 层 / runner 层
```

改成建议：

```text
a_share_core.py = shared core layer
```

## 输入范围

- `docs/*.md`
- `workflows/agently_stockpool_dag/README.md`
- `README.md`

## 输出格式

不要直接改文件，输出：

1. `命中的文件`
2. `原句`
3. `建议替换句`
4. `是否需要人工复核`

## 人工复核规则

以下情况标记为“需要人工复核”：

- 涉及 State 契约
- 涉及历史归档文档
- 无法判断是 core flow 还是 full workflow
