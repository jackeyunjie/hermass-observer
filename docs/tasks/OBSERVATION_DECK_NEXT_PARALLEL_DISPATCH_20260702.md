# 我的观察台下一阶段并发分发

日期：2026-07-02
基线提交：`db81708`（我的观察台 Phase 1 已上线）
统筹：Codex

---

## 当前状态

已完成：

- 首页已改为“我的观察台”。
- 顶层导航已收敛为“观察 / 状态 / 研究 / 策略”。
- 首页包含观象指令栏、状态脉冲、我的标的转折雷达、3D/3W/3M/6M、经典策略信号灯、全市场转折 Top、系统健康。
- 公网已部署并验收：
  - `validate_website_data_sync.py --date 20260702` 通过。
  - `pm_test_preflight.py --date 2026-07-02` 17/17 passed。
  - 首页 200，`/state-observer` 200，AI 对话未授权 401 / 授权 200。

下一阶段拆三条并行线。

---

## 并行任务

| 角色 | 任务 | 是否可并行 | 是否改代码 |
|---|---|---:|---:|
| KIMI | Phase 1 线上体验复核与 PM 验收包 | 是 | 否，除非发现 P0 |
| KIMI1 | 转折概率 MVP 独立脚本实现 | 是 | 是，只改概率脚本/测试/文档 |
| KIMI2 | 经典策略信号哨兵 MVP | 是 | 是，只改哨兵 service/API/页面/测试 |

---

## 共同红线

所有任务必须遵守 Research-Only：

- 系统只描述状态、概率、证据和风险。
- 不输出交易动作建议。
- 首页不出现：
  - 买入
  - 卖出
  - 加仓
  - 减仓
  - 清仓
  - 空仓
  - 加杠杆
  - 止盈
  - 止损
  - 目标价
  - 收益承诺
  - 适合交易
  - 推荐买
  - 推荐卖

经典策略信号：

- 只做独立规则信号灯。
- 不参与 State 概率。
- 不进入 Agent 辩论。
- 不写 State Cube。
- 不写 Decision Ledger。

---

## 分发文档

- KIMI：`docs/tasks/KIMI_TASK_OBSERVATION_DECK_PHASE1_ACCEPTANCE_20260702.md`
- KIMI1：`docs/tasks/KIMI1_TASK_TURNING_POINT_PROBABILITY_IMPLEMENT_20260702.md`
- KIMI2：`docs/tasks/KIMI2_TASK_CLASSIC_STRATEGY_SENTINEL_IMPLEMENT_20260702.md`

---

## 合并顺序

1. 先收 KIMI 体验复核，若有 P0 文案/页面问题，优先修首页。
2. 再收 KIMI1 概率 MVP，只要独立脚本与测试通过，不接首页。
3. 再收 KIMI2 哨兵 MVP，先接独立页面/API，首页标签只保留聚合入口。
4. Codex 最后统一审计、运行全链验收、提交部署。

---

## Codex 最终验收

三线回报后，Codex 必须检查：

- 是否存在交易动作语言泄露。
- 是否出现经典策略与 State 主系统混合结论。
- 是否影响 `/`、`/state-observer`、`/research`、`/mystrategies`。
- 是否保持 `pm_test_preflight.py` 17/17 passed。
- 是否保持 `validate_website_data_sync.py --date 20260702` 全绿。
