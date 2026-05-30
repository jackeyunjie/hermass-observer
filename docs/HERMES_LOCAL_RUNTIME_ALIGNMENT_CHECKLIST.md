# hermes-agent / 本地模型 运行时对齐清单

版本：v1.0  
日期：2026-05-28  
状态：活跃

> 目的：确保仓库外的 hermes-agent、本地模型、飞书运行时，都遵守和仓库内相同的 A 股主架构口径。

---

## 1. 适用范围

适用于以下运行环境：

- `~/.hermes/...` 下的 hermes-agent skills / gateway / cron
- 本地 DeepSeek API 调用层
- LM Studio / Ollama / 其他 OpenAI-compatible 本地模型
- 飞书 Bot 的实际运行环境

---

## 2. 必须同步的仓内文件

所有运行时都应以这些仓内文件为唯一规则源：

1. [README.md](/Users/lv111101/Documents/hermass-observer-product/README.md)
2. [docs/SYSTEM_ARCHITECTURE.md](/Users/lv111101/Documents/hermass-observer-product/docs/SYSTEM_ARCHITECTURE.md)
3. [docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md](/Users/lv111101/Documents/hermass-observer-product/docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md)
4. [config/prompts/runtime_architecture_prompt.md](/Users/lv111101/Documents/hermass-observer-product/config/prompts/runtime_architecture_prompt.md)
5. [config/deepseek_context.md](/Users/lv111101/Documents/hermass-observer-product/config/deepseek_context.md)

如果运行时涉及 State 解释，再补读：

6. [docs/STATE_BASE_CONTRACT.md](/Users/lv111101/Documents/hermass-observer-product/docs/STATE_BASE_CONTRACT.md)
7. [docs/AGENT_PERSPECTIVE_ARCHITECTURE.md](/Users/lv111101/Documents/hermass-observer-product/docs/AGENT_PERSPECTIVE_ARCHITECTURE.md)

---

## 3. 必须统一的架构事实

所有运行时必须统一写成：

- `shared core layer = agently_adapter/a_share_core.py`
- `core flow = agently_adapter/agently_a_share_flow.py`
- `full compatibility workflow = agently_adapter/agently_daily_flow.py`
- `API service layer = hermass_platform/api/a_share_service.py`

并且必须明确：

- 当前活跃系统仅限 A 股
- shell 脚本是过渡入口，不是长期主架构
- 飞书是交付层，不是系统本体
- hermes-agent 是渠道、调度、技能运行时

---

## 4. hermes-agent 对齐步骤

### 4.1 Skills

将仓内 `config/hermes_skills/*.md` 视为主副本：

- `config/hermes_skills/market-analyst.md`
- `config/hermes_skills/strategy-advisor.md`
- `config/hermes_skills/coach.md`
- `config/hermes_skills/daily-pipeline.md`
- `config/hermes_skills/sector-resonance.md`

如果 `~/.hermes/skills/` 下存在对应 skill：

1. 名称保持一致
2. 描述保持 A 股范围
3. 执行入口遵守仓内的架构路径规则
4. 不新增 MT5/US/Alpaca 相关 skill

### 4.2 Runtime Prompt

如果 hermes-agent 支持设置全局 system prompt 或 skill prompt：

优先注入：

- [config/prompts/runtime_architecture_prompt.md](/Users/lv111101/Documents/hermass-observer-product/config/prompts/runtime_architecture_prompt.md)

如果支持多段上下文：

再追加：

- [config/deepseek_context.md](/Users/lv111101/Documents/hermass-observer-product/config/deepseek_context.md)

### 4.3 Cron

cron 只负责触发，不承载业务编排。

推荐规则：

- `15:15` 收盘任务 → 优先调用 API 或 Flow 主入口
- `08:00` 早报任务 → 调用明确的 morning brief 入口
- 不把复杂业务逻辑堆进 shell

---

## 5. 本地模型对齐步骤

### 5.1 适用对象

- LM Studio
- Ollama
- Open WebUI 背后的本地模型
- 任何 OpenAI-compatible 本地推理网关

### 5.2 最小 system prompt

本地模型至少应加载：

1. [config/prompts/runtime_architecture_prompt.md](/Users/lv111101/Documents/hermass-observer-product/config/prompts/runtime_architecture_prompt.md)

如支持更长上下文，再追加：

2. [config/deepseek_context.md](/Users/lv111101/Documents/hermass-observer-product/config/deepseek_context.md)

### 5.3 本地模型职责边界

本地模型适合：

- 文档同步
- 架构术语统一
- 低风险机械改写
- 研究摘要整理
- 查询类解释层任务

本地模型不适合单独负责：

- 架构边界判断
- State 契约变更
- 跨层重构决策
- git 边界清理

---

## 6. 外部运行时检查项

每次接入新模型或新运行时，检查：

1. 是否先加载了 `runtime_architecture_prompt.md`
2. 是否知道系统仅限 A 股
3. 是否知道 `agently_daily_flow.py` 不是主线
4. 是否知道 shell 只是过渡入口
5. 是否把 `a_share_service.py` 识别为服务边界
6. 是否禁止输出交易指令
7. 是否禁止引用 MT5/US 归档作为当前规则源

---

## 7. 推荐落地方式

### 方案 A：单提示词

适用于上下文窗口较小的本地模型：

- 只注入 `runtime_architecture_prompt.md`

### 方案 B：双层提示词

适用于上下文窗口足够的模型：

- system prompt：`runtime_architecture_prompt.md`
- supplementary context：`deepseek_context.md`

### 方案 C：技能化

适用于 hermes-agent / 飞书 Bot：

- skill 描述层：`config/hermes_skills/*.md`
- runtime prompt：`runtime_architecture_prompt.md`
- 业务解释规则：`compliance_filter.get_system_prompt()`

---

## 8. 一句话标准

任何仓外模型只要接入 Hermass，就必须先学会这句话：

> A 股 only；API 优先；shared core 唯一；core/full flow 分离；shell 只是过渡入口。

