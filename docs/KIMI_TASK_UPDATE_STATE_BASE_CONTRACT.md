# Kimi 任务：更新 STATE_BASE_CONTRACT.md 第六章

## 任务概述

将 `docs/STATE_BASE_CONTRACT.md` 的第六章"双视角 State 体系"升级为完整的"Agent 视角体系"，与 `AGENT_PERSPECTIVE_ARCHITECTURE.md` 保持一致。

## 当前状态

第六章当前内容是"D1 Agent vs W1 Agent"的二元对比。需要升级为覆盖 D1/W1/H1/MN1 四个 Agent 的完整视角体系。

## 修改范围

**只修改第六章**，其他章节不动。

## 新第六章结构

```
## 第六章：Agent 视角体系

### 6.1 设计原则
  - 每个周期视角是一个独立 Agent
  - 视角决定基准价（view_tf 的 close）
  - 各结构周期的 trend/base/volatility 独立

### 6.2 视角矩阵
  - 完整的 view_tf × structure_tf 二维表
  - 每个 Agent 包含哪些 (view_tf, structure_tf) 对

### 6.3 各 Agent 定义
  6.3.1 D1 Agent（日频，当前主系统）
    - 构成：MN1@D1, W1@D1, D1@D1
    - 更新：每个交易日
    - 用途：策略信号触发、适配度计算、前向观察

  6.3.2 W1 Agent（周频，辅助系统）
    - 构成：MN1@W1, W1@W1
    - 更新：每周末
    - 用途：周线趋势判断、周度报告

  6.3.3 H1 Agent（小时频，盘中监控参考）
    - 构成：MN1@H1, W1@H1, D1@H1, H4@H1, H1@H1
    - 更新：每小时
    - 用途：盘中实时监控参考
    - 状态：暂不实现（参见 H1 可行性分析报告）

  6.3.4 MN1 Agent（月频，长期参考）
    - 构成：MN1@MN1
    - 更新：每月末
    - 用途：月度宏观判断、长期配置

### 6.4 Agent 间差异
  - 同一标的同一天不同 Agent 可能给出不同 State
  - 差异率数据引用 W1_STATE_DUAL_PERSPECTIVE_CALIBRATION.md
  - 差异是设计特性，不是 bug

### 6.5 使用规则
  - 日频分析 → D1 Agent
  - 周频分析 → W1 Agent
  - 盘中监控 → H1 Agent
  - 月度宏观 → MN1 Agent
  - 不可混用不同 Agent 的 State

### 6.6 与现有系统的映射
  - 当前 scripts/state_calc/p116_core.py = D1 Agent 实现
  - 当前 scripts/build_weekly_state_independent.py = W1 Agent 实现
  - H1 Agent = 暂不实现（A 股 T+1 制度下价值有限）
```

## 约束

- 只改第六章，其他章节不动
- 不改 D1 视角天条的定义（第三章），只是在第六章中将其泛化
- 所有 State 编码公式保持不变
- 引用 `AGENT_PERSPECTIVE_ARCHITECTURE.md` 作为详细设计参考
- 全中文撰写
- 保持现有文档的格式风格（表格 + 代码块 + 引用）

## 参考文件

- `docs/STATE_BASE_CONTRACT.md` — 当前版本（只改第六章）
- `docs/AGENT_PERSPECTIVE_ARCHITECTURE.md` — 完整架构设计（如果已存在）
- `docs/W1_STATE_DUAL_PERSPECTIVE_CALIBRATION.md` — 差异率数据
