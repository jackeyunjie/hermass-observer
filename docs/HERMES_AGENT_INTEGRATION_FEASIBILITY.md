# Hermes Agent 集成可行性评估

版本：v1.0
日期：2026-05-26
状态：评估文档

---

## 评估结论

**可行，推荐采用。** hermes-agent 可以替代我们手写的 3 个基础设施模块（飞书/钉钉 handler、pipeline_daemon、意图路由），同时提供我们目前没有的 3 个能力（自学习循环、多平台网关、定时任务）。

**集成方式：hermes-agent 作为运行时底层，Hermass 的 7 个 Agent 作为 hermes skills 注册。**

---

## 1. 能力对照

| 能力 | Hermass 当前实现 | hermes-agent 提供 | 集成收益 |
|------|-----------------|------------------|---------|
| 多平台网关 | 手写 lark_handler.py + dingtalk_server.py | 内置 Telegram/Discord/Slack/WhatsApp/Signal/Email | 替换手写代码，新增更多平台 |
| 定时任务 | 手写 pipeline_daemon.py（sleep 循环） | 内置 cron scheduler + 平台推送 | 替换手写代码，更可靠 |
| 意图路由 | 手写 intent_router.py（关键词匹配） | LLM 原生理解，无需关键词 | 替换手写代码，更智能 |
| 自学习 | 无 | 技能从经验中创建和改进，FTS5 会话搜索 | 新增能力 |
| MCP 集成 | 已设计 5 个工具 | 内置 MCP 服务器 | 直接复用 |
| 子 Agent 并行 | 无 | 内置 subagent spawning | 新增能力 |
| 记忆系统 | cognitive_ledger（JSON 文件） | MEMORY.md + USER.md + Honcho 用户建模 | 升级 |
| LLM 切换 | 硬编码 DeepSeek | 200+ 模型，`hermes model` 一键切换 | 升级 |

---

## 2. 集成架构

```text
用户
  │
  ▼
hermes-agent gateway（Telegram/Discord/飞书/钉钉）
  │
  ├─ 自然语言理解（hermes 内置 LLM）
  │
  ├─ Skill 路由 → Hermass Skills
  │   ├─ /market-analysis     → Market Analyst Agent
  │   ├─ /strategy-advisor    → Strategy Advisor Agent
  │   ├─ /cognitive-detective → Cognitive Detective Agent
  │   ├─ /risk-guardian       → Risk Guardian Agent
  │   ├─ /coach               → Coach Agent
  │   ├─ /monetization-butler → Monetization Butler Agent
  │   └─ /sector-resonance    → 板块共振检测
  │
  ├─ 定时任务 → Hermass Pipeline
  │   └─ cron: "15 15 * * 1-5" → run_daily_pipeline.sh
  │
  ├─ MCP 工具 → Hermass 查询
  │   ├─ get_market_phase
  │   ├─ get_top_signals
  │   └─ get_state_snapshot
  │
  └─ 自学习循环 → 技能改进
      └─ 从用户交互中提取模式，改进应答模板
```

---

## 3. 集成步骤

### Step 1：安装 hermes-agent

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

### Step 2：配置 LLM

```bash
hermes model  # 选择 DeepSeek 或其他 provider
```

### Step 3：注册 Hermass Skills

将我们的 7 个 Agent 封装为 hermes skills：

```yaml
# ~/.hermes/skills/market-analyst/skill.yaml
name: market-analyst
description: 查询 A 股市场状态、E/F 池、行业共振
trigger: 市场怎么样 / 今天市场 / 大盘状态
command: python3 /path/to/hermass_platform/agents/market_analyst.py --query "$INPUT"
```

### Step 4：配置定时任务

```
hermes cron add "每天 15:15 运行 A 股日频流水线" \
  --schedule "15 15 * * 1-5" \
  --command "bash /path/to/scripts/run_daily_pipeline.sh $(date +%Y-%m-%d)"
```

### Step 5：配置消息网关

```bash
hermes gateway setup  # 配置 Telegram/Discord/飞书
hermes gateway start
```

---

## 4. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| hermes-agent 依赖冲突 | 与 Hermass 现有 .venv 冲突 | 用独立 venv 安装 hermes-agent |
| LLM 调用成本 | hermes 每次交互都调 LLM | 用 DeepSeek（低成本），关键路径用规则而非 LLM |
| 中文支持 | hermes 主要面向英文 | 技能描述用中文，LLM 本身支持中文 |
| 数据安全 | hermes 访问 Hermass 数据 | hermes 只通过 skills 调用，不直接访问 DB |
| 升级维护 | hermes-agent 频繁更新 | 用 exact-pinned 依赖，手动升级 |

---

## 5. 替代方案对比

| 方案 | 优势 | 劣势 |
|------|------|------|
| **hermes-agent 集成** | 自学习、多平台、cron、MCP、MIT | 需要适配，有学习成本 |
| 保持现状（手写） | 完全可控，无外部依赖 | 维护成本高，功能有限 |
| Agently 框架 | Python 原生，Action Runtime | 缺少网关和自学习 |
| LangChain | 生态丰富 | 过重，不适合轻量场景 |

---

## 6. 建议

**立即做**：安装 hermes-agent，配置 DeepSeek 模型，注册 1-2 个 Hermass skills 作为 POC。

**验证通过后**：逐步将飞书/钉钉 handler 和 pipeline_daemon 迁移到 hermes-agent 网关和 cron。

**长期**：利用 hermes-agent 的自学习循环，让系统的应答模板从用户交互中自动改进。
