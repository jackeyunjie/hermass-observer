# KIMI1 任务：多周期转折概率 MVP 方案

日期：2026-07-02
执行者：KIMI1
任务类型：数据模型 / 概率引擎 / 字段契约

---

## 任务背景

Hermass 下一阶段核心不是简单标签，而是：

> 多周期贝叶斯转折概率系统。

目标是对用户持仓、自选、候选标的，在 3D / 3W / 3M / 6M 四个时间窗中输出：

- 转强概率
- 转弱概率
- 延续概率
- 假突破概率
- 置信度
- 关键证据

系统不输出交易动作。

---

## 你的目标

设计一个可先落地的 Empirical Bayesian MVP。

要求：

1. 基于现有 State Timeline / State Cube / Foundation 数据可实现。
2. 先用历史 State 转移统计形成先验。
3. 再用当前多周期证据做修正。
4. 输出字段要能直接被首页观察台消费。
5. 方案必须可回测、可解释、可逐步校准。

---

## 请重点研究

### 1. 时间窗定义

请定义：

- 3D 对应多少交易日。
- 3W 对应多少交易日。
- 3M 对应多少交易日。
- 6M 对应多少交易日。

并说明为什么。

### 2. 转折事件定义

请定义：

- 转强早期
- 确认转强
- 强势延续
- 转弱预警
- 确认转弱
- 噪声变化

每类事件应尽量基于：

- MN1 / W1 / D1 state_score / state_hex / state_magnitude。
- EF。
- A+B。
- 0。
- 关键位突破。
- 状态连续变化。

### 3. 概率字段契约

建议输出字段：

```text
stock_code
stock_name
state_date
window
turning_type
prob_turn_up
prob_turn_down
prob_continue
prob_false_breakout
confidence
evidence_score
evidence_items
risk_flags
source_state_summary
```

请评估字段是否足够，并给出最终字段契约。

### 4. 先验与更新

请设计：

- 历史 State 转移统计如何分桶。
- 如何避免样本不足。
- 如何按行业 / 市场环境做可选分层。
- 如何记录概率变化。
- 如何给出置信度。

---

## 输出要求

请输出并写入文档：

`docs/tasks/TURNING_POINT_PROBABILITY_MVP_KIMI1_20260702.md`

文档至少包含：

1. MVP 目标。
2. 数据源。
3. 时间窗定义。
4. 转折事件定义。
5. 概率字段契约。
6. Empirical Bayesian 计算方案。
7. 样本不足和置信度处理。
8. API / 表结构建议。
9. 首页消费方式。
10. 回测和验收标准。
11. 不做清单。

---

## 不要做

- 不写代码。
- 不改数据库。
- 不改前端。
- 不输出交易动作。
- 不把经典策略信号纳入 State 主概率。

---

## 返回格式

完成后回复：

1. 写入了哪些文件。
2. 推荐的时间窗定义。
3. 推荐的概率字段。
4. MVP 最小可实现版本。
5. 最大风险。

