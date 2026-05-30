# 模型架构使用指南

版本：v1.0  
日期：2026-05-28  
状态：活跃  
适用对象：KIMI、本地模型、hermes-agent skills、飞书 Bot、Codex

> 范围声明：本指南只适用于当前 A 股活跃系统。MT5、美股/US、Alpaca 相关内容均为历史归档，不属于当前模型执行范围。

---

## 1. 目标

本指南用于让不同模型在调用 Hermass 能力时，统一走同一套主架构，避免：

- 直接绕过共享核心层
- 把 shell 脚本误当成系统主入口
- 把归档文档或历史路线重新当成活跃系统
- 混淆 `core flow` 与 `full compatibility workflow`

---

## 2. 先读哪些文件

所有模型在执行任务前，优先按以下顺序建立上下文：

1. [README.md](/Users/lv111101/Documents/hermass-observer-product/README.md)
2. [docs/SYSTEM_ARCHITECTURE.md](/Users/lv111101/Documents/hermass-observer-product/docs/SYSTEM_ARCHITECTURE.md)
3. [docs/A_SHARE_SERVICE_API.md](/Users/lv111101/Documents/hermass-observer-product/docs/A_SHARE_SERVICE_API.md)
4. [docs/AGENTLY_A_SHARE_INTEGRATION_PLAN.md](/Users/lv111101/Documents/hermass-observer-product/docs/AGENTLY_A_SHARE_INTEGRATION_PLAN.md)

如果任务涉及 State 语义，再补读：

5. [docs/STATE_BASE_CONTRACT.md](/Users/lv111101/Documents/hermass-observer-product/docs/STATE_BASE_CONTRACT.md)
6. [docs/AGENT_PERSPECTIVE_ARCHITECTURE.md](/Users/lv111101/Documents/hermass-observer-product/docs/AGENT_PERSPECTIVE_ARCHITECTURE.md)

---

## 3. 四层主路径

```text
Layer 4 API / 服务层
  hermass_platform/api/a_share_service.py

Layer 3 Flow / Action 层
  agently_adapter/agently_a_share_flow.py
  agently_adapter/agently_daily_flow.py
  agently_adapter/a_share_actions.py

Layer 2 Shared Core Layer
  agently_adapter/a_share_core.py

Layer 1 数据与底座脚本层
  scripts/*.py
  backtest/*.py
```

所有模型都应优先理解为：

- `a_share_core.py` 是唯一共享实现
- `agently_a_share_flow.py` 是 A 股 `core flow`
- `agently_daily_flow.py` 是 `full compatibility workflow`
- `a_share_service.py` 是当前最清晰的服务边界

---

## 4. 入口优先级

### 4.1 查询类任务

例如：

- 市场状态
- 个股状态
- 板块共振
- 交易知识问答

优先级：

1. 现有 hermes skill
2. `hermass_platform/agents/*.py` 包装层
3. 只读查询 API 或只读脚本

禁止事项：

- 不要直接改 `a_share_core.py`
- 不要把“查询”误写成“执行”

### 4.2 执行类任务

例如：

- 跑日频流水线
- 重建日报
- 运行完整兼容闭环

优先级：

1. `a_share_service.py`
2. `agently_a_share_flow.py` / `agently_daily_flow.py`
3. `stockpool_daily_runner.py`
4. 历史 shell 脚本

解释：

- API 是最清晰的服务边界
- Flow 是主编排层
- Runner 是兼容层
- shell 脚本只应作为过渡入口或本地 cron 包装

### 4.3 文档与概念类任务

优先级：

1. `SYSTEM_ARCHITECTURE.md`
2. `STATE_BASE_CONTRACT.md`
3. `AGENT_PERSPECTIVE_ARCHITECTURE.md`
4. 相关专题文档

禁止事项：

- 不引用已归档的 MT5/US 文档作为当前规则来源

---

## 5. 核心术语

| 术语 | 正确含义 |
|------|----------|
| `shared core layer` | `agently_adapter/a_share_core.py`，唯一共享实现 |
| `core flow` | `agently_adapter/agently_a_share_flow.py`，A 股最小核心链路 |
| `full compatibility workflow` | `agently_adapter/agently_daily_flow.py`，兼容闭环 |
| `verify_core_outputs` | 只校验核心产物 |
| `verify_public_outputs` | 校验核心产物 + 公开扩展产物 |
| `D1 Agent` | 当前正式活跃 Agent |
| `view_tf × structure_tf` | State 的二维坐标命名方式 |

---

## 6. 模型执行规则

所有模型统一遵守：

1. 系统只服务 A 股。
2. 不把 MT5、美股/US、Alpaca 当成活跃路线。
3. 不修改 State 底座定义，不重写 `E=14/F=15`。
4. 不把旧 shell 包装入口误写成主架构。
5. 新增服务入口时，优先挂到 API 或 Flow 层，不直接散落在脚本层。
6. 若任务只是查询或汇报，优先复用现有 skill。
7. 若任务涉及定时任务，cron 只负责触发，不承载业务编排。

---

## 7. 模型到入口映射

| 模型/通道 | 推荐入口 | 说明 |
|-----------|----------|------|
| 飞书 Bot | hermes skills + `a_share_service.py` | 飞书是交付层，不是系统本体 |
| hermes-agent | skills + cron + API/Flow | 负责渠道、调度、技能路由 |
| KIMI | 先读本指南，再按任务提示词执行 | 适合文档同步、审计、机械整理 |
| 本地模型 | 只做低风险机械任务 | 不负责架构判断 |
| Codex | 可跨层收口 | 负责最终架构一致性与实现 |

---

## 8. 对 KIMI / 本地模型的最小提示

```text
你在 hermass-observer-product 仓库内工作。

活跃系统范围仅限 A 股。
先阅读：
1. README.md
2. docs/SYSTEM_ARCHITECTURE.md
3. docs/A_SHARE_SERVICE_API.md
4. docs/AGENTLY_A_SHARE_INTEGRATION_PLAN.md

架构规则：
- shared core layer = agently_adapter/a_share_core.py
- core flow = agently_adapter/agently_a_share_flow.py
- full compatibility workflow = agently_adapter/agently_daily_flow.py
- API 入口 = hermass_platform/api/a_share_service.py

禁止事项：
- 不把 MT5/US/Alpaca 当作活跃范围
- 不改 State 底座契约
- 不把旧 shell 脚本描述成主架构
```

---

## 9. 当前迁移判断

当前系统处于“调度层已升级、业务主干仍在迁移”的过渡态：

- `launchd` / `hermes cron`：已开始成型
- `a_share_service.py`：已成型
- `agently_*_flow.py`：已成型
- `scripts/run_daily_pipeline.sh` / `send_daily_report.py`：仍属过渡入口

因此所有模型在描述当前架构时，必须明确：

> shell 脚本当前仍存在，但不应被定义为长期主入口。

