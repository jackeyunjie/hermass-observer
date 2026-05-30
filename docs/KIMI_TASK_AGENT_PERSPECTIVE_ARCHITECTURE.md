# Kimi 任务：Agent 视角体系架构设计

## 任务概述

基于团队已达成的共识——"每个周期视角都是一个独立 Agent，每个 Agent 内部包含本周期及以上大周期的时间戳对齐状态"——设计完整的 Agent 视角体系架构文档。

## 核心概念（必须理解）

团队已定义的二维坐标体系：

```
view_tf      = 视角 Agent（观察者所在的时间框架）
structure_tf = 被观察的结构周期
```

每个 Agent 的构成：

```
D1 Agent:
  MN1@D1_view, W1@D1_view, D1@D1_view

W1 Agent:
  MN1@W1_view, W1@W1_view

H1 Agent:
  MN1@H1_view, W1@H1_view, D1@H1_view, H4@H1_view, H1@H1_view
```

关键约束：
- 每个 Agent 的 position 计算全部使用该 Agent 的视角基准价（view_tf 的 close）
- 各结构周期的 trend/base/volatility 始终来自各自周期的指标
- 不同 Agent 观察同一标的同一天可能给出不同的 State（这是正确行为）

## 产出文件

`docs/AGENT_PERSPECTIVE_ARCHITECTURE.md`

## 文档结构要求

```
第一章：设计原则
  1.1 为什么需要多 Agent 视角体系
  1.2 与单一 D1 视角的区别
  1.3 核心约束：视角决定基准价

第二章：Agent 定义
  2.1 视角矩阵（view_tf × structure_tf 二维表）
  2.2 各 Agent 的构成（列出每个 Agent 包含的 view_tf@structure_tf 对）
  2.3 各 Agent 的更新频率和触发条件
  2.4 Agent 间的层级关系（H1 是最细粒度，MN1 是最粗粒度）

第三章：计算规则
  3.1 position 计算：所有结构周期共用 view_tf 的 close
  3.2 trend/base/volatility 计算：各结构周期独立
  3.3 State 编码公式：score = base + trend×4 + pos×2 + vol（不变）
  3.4 ef_count 在各 Agent 中的定义
  3.5 符号裁决规则（位置优先）

第四章：Agent 间的数据流
  4.1 D1 Agent 的结论如何传递给 H1 Agent
  4.2 W1 Agent 的结论如何作为 D1 Agent 的"大周期背景"
  4.3 Agent 间的信号冲突处理（如 H1 看多但 D1 看空）

第五章：与现有系统的映射
  5.1 当前 D1 视角 = D1 Agent（已实现）
  5.2 当前 W1 Agent（脚本已有，未接入信号链路）
  5.3 H1 Agent = 待实现
  5.4 MN1 Agent = 待实现（月度频率，优先级低）

第六章：A 股系统的 Agent 选择
  6.1 A 股系统：D1 Agent 为主，W1 Agent 为辅
  6.2 T+1 制度对 Agent 选择的影响

第七章：术语表
  view_tf, structure_tf, perspective_close, Agent, State, ef_count 等
```

## 约束

- 不涉及具体代码实现（那是 Codex 的任务）
- 所有 State 编码公式必须与 `STATE_BASE_CONTRACT.md` 一致
- 必须引用 `W1_STATE_DUAL_PERSPECTIVE_CALIBRATION.md` 中的差异率数据
- 不得修改 D1 视角天条——只是将其泛化为"视角决定基准价"
- 全中文撰写

## 参考文件

- `docs/STATE_BASE_CONTRACT.md` — State 底座宪法
- `docs/W1_STATE_DUAL_PERSPECTIVE_CALIBRATION.md` — 双视角校准
- `docs/H1_AGENT_FEASIBILITY_ANALYSIS.md` — H1 Agent 可行性分析（A 股暂不实现）
- `docs/MULTICYCLE_STATE_STRATEGY_WHITEPAPER.md` — 系统方法论
