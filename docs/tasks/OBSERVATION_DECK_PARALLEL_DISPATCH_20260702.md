# Hermass 我的观察台 / 转折概率系统并发分发

日期：2026-07-02
负责人：Codex 统筹，KIMI / KIMI1 / KIMI2 并行

---

## 背景结论

产品主线已从“State Workbench / 新闻首页 / AI 科技感首页 / 持仓决策台”收敛为：

> Hermass 首页 = 我的观察台。围绕用户持仓、自选和候选标的，观察 3D / 3W / 3M / 6M 的转折概率、关键证据和风险。

系统只描述状态、概率和证据，不输出交易动作。

长期记忆文档：

- `data/research/conversations/22-我的观察台与转折概率系统产品收敛.md`
- `data/research/conversations/daily/2026-07-02.md`

---

## 三条并发线

| 角色 | 任务 | 重点产物 | 不做 |
|---|---|---|---|
| KIMI | 产品方案与首页信息架构 | 我的观察台 PRD、首页模块、导航收敛、禁用词清单 | 不写代码 |
| KIMI1 | 多周期转折概率 MVP | 3D/3W/3M/6M 概率字段、Empirical Bayesian MVP、验收样例 | 不改前端 |
| KIMI2 | 经典策略信号哨兵 | 经典策略 Agent 边界、信号契约、详情页字段 | 不混入 State 主概率 |

---

## 共同红线

所有任务必须遵守：

1. Research-Only：系统只描述状态变化，不输出交易动作。
2. 禁止作为系统结论出现：
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
3. 经典策略 Agent 只做信号提示，不参与 Hermass State 概率。
4. 首页服务用户自己的标的，不服务全市场热闹。
5. 不改后端生产代码、不提交代码，先交付方案文档。

---

## 分发文档

- KIMI：`docs/tasks/KIMI_TASK_OBSERVATION_DECK_PRODUCT_SPEC_20260702.md`
- KIMI1：`docs/tasks/KIMI1_TASK_TURNING_POINT_PROBABILITY_MVP_20260702.md`
- KIMI2：`docs/tasks/KIMI2_TASK_CLASSIC_STRATEGY_SIGNAL_SENTINEL_20260702.md`

---

## 合并顺序

1. Codex 收集三方结果。
2. 先合并产品命名、页面模块和禁用词。
3. 再合并概率字段契约。
4. 最后合并经典策略信号契约。
5. 形成一份正式改版总方案，再进入代码实现。

---

## Codex 后续验收口径

三方交付后，Codex 检查：

- 是否仍然守住 Research-Only。
- 是否有交易动作建议残留。
- 是否把经典策略和 State 主概率混淆。
- 是否能落到现有 State Timeline / State Cube / watchlist 数据基础上。
- 是否能拆成 Phase 1 可实现的小步。

