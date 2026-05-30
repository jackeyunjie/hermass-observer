# Agently A 股专属集成路线图

版本：v1.0
日期：2026-05-27
状态：执行方案
关联文件：
- `agently_adapter/a_share_core.py`
- `agently_adapter/stockpool_daily_runner.py`
- `agently_adapter/a_share_actions.py`
- `agently_adapter/agently_a_share_flow.py`
- `workflows/agently_stockpool_dag/stockpool_daily_update.yaml`

> 范围声明：本路线图仅服务当前 A 股活跃生产系统。MT5、美股/US、Alpaca 相关内容均为历史归档，不在本路线图范围内。

---

## 1. 目标

把当前"脚本集合 + 大一统 CLI"的 full compatibility workflow，收束为：

- 一个 A 股专属的 Agently core flow
- 一组稳定的核心 Action 契约
- 一个可追踪、可组合、可服务化的 TriggerFlow DAG

本路线图不改变 State 底座计算契约，只改变上层编排方式。

---

## 2. 非目标

本阶段不做以下事情：

- 不重写 `scripts/build_p116_foundation.py`
- 不修改 `STATE_BASE_CONTRACT.md` 的计算规则
- 不引入 MT5、MQL、跨市场执行逻辑
- 不把 `daily_stock_analysis`、`TradingAgents-CN`、`hermes-agent` 并入本仓库
- 不新增买卖指令或自动交易能力

---

## 3. 外部仓库的使用边界

### 3.1 `AgentEra/Agently`

用途：主线运行时。

借用内容：

- Action Runtime
- TriggerFlow
- Skills / MCP 扩展点
- FastAPI 服务暴露能力

### 3.2 `daily_stock_analysis`

用途：参考产品入口层。

借用内容：

- 日报结构
- Web 工作台入口组织
- 多渠道通知与历史报告管理思路

不借用内容：

- A/H/US 混合市场定位
- 决策仪表盘式买卖建议语义
- 新闻驱动替代 State 底座的主逻辑

### 3.3 `TradingAgents-CN`

用途：参考多 Agent 展示层。

借用内容：

- 多角色分析呈现方式
- 页面分工与状态展示方式

不借用内容：

- 重型前后端基础设施
- 混合许可证组件
- 多市场分析框架作为底座

### 3.4 `hermes-agent`

用途：只参考机制。

借用内容：

- 技能沉淀
- 会话记忆与检索
- 定时任务机制

不借用内容：

- 聊天代理作为系统主入口
- 独立运行时替换当前 Agently 方向

---

## 4. 当前问题

当前 `agently_adapter/agently_daily_flow.py` 只是对：

```text
stockpool_daily_runner.py run
```

的薄封装，问题有三类：

1. Action 粒度过粗
   - 整条 full compatibility workflow 是一个黑盒命令
   - 无法单独复用 `build_state_cache`、`build_strategy_signal_ledger` 等关键节点

2. 运行时边界不清
   - `run_full_workflow()` 同时承担编排、调用、产物汇总
   - 不利于后续服务化和观测

3. A 股 core flow 未被最小化
   - 当前 DAG 很大，但缺少"最小可稳定运行的 A 股核心链路"

---

## 5. 目标架构

### 5.1 最小核心链路

```text
build_foundation
  → build_state_cache
  → build_strategy_evidence
  → build_strategy_signal_ledger
  → build_forward_observation
  → build_daily_brief
  → verify_core_outputs
```

### 5.2 运行时分层

```text
Layer A: 确定性底座脚本
  scripts/*.py

Layer B: A 股共享核心层
  agently_adapter/a_share_core.py

Layer C: Runner 兼容层
  agently_adapter/stockpool_daily_runner.py

Layer D: Action 契约层
  agently_adapter/a_share_actions.py

Layer E: A 股 core flow 编排层
  agently_adapter/agently_a_share_flow.py

Layer F: 服务/API 层（下一阶段）
  /run-daily
  /query-signal
  /generate-brief
```

说明：

- `a_share_core.py` 是当前 A 股最小核心链路的唯一共享实现层
- `stockpool_daily_runner.py`、`a_share_actions.py`、FastAPI 服务都应复用它，而不是各自复制命令逻辑
- `agently_a_share_flow.py` 应保持为声明式 step 编排层；新增核心节点时先改 step spec，再决定是否新增共享 core 能力
- `stockpool_daily_runner.py run` 当前应被理解为：shared core steps + runner 独有的 public/recommendation/pattern/diagnostics 扩展节点，即 full compatibility workflow
- full compatibility workflow 的产物校验也应遵循同一边界：`core outputs` 由 `a_share_core.py` 负责，runner 只补 `public extension` 清单

---

## 6. 六个核心 Action

### 6.1 Action 列表

| Action | 输入 | 输出 |
|--------|------|------|
| `build_foundation` | `date`, `foundation_db?` | `foundation_db`, `raw_db` |
| `build_state_cache` | `date`, `foundation_db`, `boundary_pct?` | `state_ef_json`, `state_distribution_json`, `state_transition_json`, `sr_boundary_json` |
| `build_strategy_evidence` | `date`, `foundation_db`, `lookback_days?` | `strategy_evidence_json`, `strategy_evidence_csv`, `strategy_evidence_html` |
| `build_strategy_signal_ledger` | `date`, `foundation_db`, `min_ef?` | `ledger_db`, `ledger_json` |
| `build_forward_observation` | `date`, `foundation_db`, `windows?` | `json`, `csv`, `html`, `latest_json`, `latest_html` |
| `build_daily_brief` | `date` | `json`, `markdown`, `html`, `latest_json`, `latest_html` |

### 6.2 辅助 Action

| Action | 用途 |
|--------|------|
| `preflight` | 日期与运行环境检查 |
| `verify_core_outputs` | 只校验最小核心链路产物是否完整，不等于全量 `public` 闭环校验 |

---

## 7. TriggerFlow 设计

### 7.1 核心 DAG

```text
preflight
  → build_foundation
  → build_state_cache
  → build_strategy_evidence
  → build_strategy_signal_ledger
  → build_forward_observation
  → build_daily_brief
  → verify_core_outputs
  → finish
```

### 7.2 设计原则

- 每个节点只做一件事
- 每个节点输出标准 JSON
- 上一节点输出可直接作为下一节点输入的一部分
- 失败点必须能单独重放

---

## 8. 服务化下一步

最小 API 面：

### 8.1 `/run-daily`

用途：触发 A 股 core flow。

输入：

```json
{
  "date": "YYYY-MM-DD",
  "previous_date": "YYYY-MM-DD",
  "foundation_db": "outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb"
}
```

### 8.2 `/run-full-daily`

用途：触发 full compatibility workflow（runner 兼容全量闭环）。

说明：

- `/run-daily` 对应最小核心链路
- `/run-full-daily` 对应 full compatibility workflow，即 `shared core + runner extensions`

### 8.3 `/query-signal`

用途：只读查询某日某标的的标准化信号事实。

来源：

- `outputs/strategy_signals/strategy_signal_daily_YYYYMMDD.json`
- `outputs/state_cache/state_ef_YYYYMMDD.json`

### 8.4 `/generate-brief`

用途：单独重建某日简报，不重跑全链路。

---

## 9. 执行分期

### Phase 1（当前）

目标：完成最小可运行骨架。

- 新增 A 股专属 Action 契约模块
- 新增 A 股专属 core flow 模块（agently_a_share_flow.py）
- 保留 `stockpool_daily_runner.py` 作为兼容层

### Phase 2

目标：服务化。

- 用 FastAPI 暴露 `/run-daily`（core flow）与 `/run-full-daily`（full compatibility workflow）
- 加执行状态查询
- 加核心产物只读查询

### Phase 3

目标：研究助理 Agent。

- 只读查询本地产物
- 生成研究总结
- 不改 State，不发交易指令

---

## 10. 成功标准

满足以下条件即可视为第一阶段完成：

1. A 股核心链路可由 TriggerFlow 单独运行
2. 六个核心 Action 都有稳定输入输出
3. core flow 不再依赖一个黑盒 `run` 命令
4. 服务层可以直接复用这些 Action 与 DAG

---

## 11. 当前落地文件

本轮落地新增或约定的文件：

- `docs/AGENTLY_A_SHARE_INTEGRATION_PLAN.md`
- `agently_adapter/a_share_actions.py`
- `agently_adapter/agently_a_share_flow.py`

这三者构成当前 A 股专属 Agently core flow 的第一版落地骨架。agently_daily_flow.py 作为 full workflow compatibility flow 继续保留，但不再是推荐主入口。
