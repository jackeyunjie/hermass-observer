# Hermass SuperTrader — 新任务承接文档

版本：2026-06-01
最新 commit：`7692243`
服务器：8.130.125.201

---

## 1. 项目是什么

Hermass（对外品牌 SuperTrader）是一个 **A 股多周期交易辅助平台**。核心差异化：用 State 十六进制编码（MN1/W1/D1 三周期各 4bit）描述每只股票的结构状态，然后做策略环境匹配、预警和 AI 对话。

当前阶段：**11 人内测**（单测试账号 `hermass-test`）。

---

## 2. 当前线上部署

| 项 | 值 |
|------|------|
| 服务器 | 阿里云 ECS 8.130.125.201 |
| 项目路径 | `/opt/hermass` |
| 网址 | `http://console.supertrader.world` |
| 测试账号 | `hermass-test / Hermass2026!Lab` |
| 服务 | `hermass-console`（systemd，端口 8020） |
| Python | `.venv`（虚拟环境） |
| 关键依赖 | duckdb, fastapi, uvicorn, jinja2, agently, openai |
| DEEPSEEK_API_KEY | 已配置在 systemd override 中 |
| agently 包 | ✅ 已安装（之前遗漏，已修复） |

---

## 3. 架构

```
用户 → Nginx:80 → uvicorn:8020 (web/main.py — FastAPI)
                      │
       ┌──────────────┼──────────────┐
       ▼              ▼              ▼
  DuckDB查询     agently_adapter/   规则回答
  (确定性数据)   (LLM多Agent链)    (兜底)
                      │
            ┌─────────┼─────────┐
            ▼         ▼         ▼
       agents/    scenarios/  deepseek.py
       (6个Agent) (6个场景链) (统一调用层)
```

**核心规则：**
- 数据/DB/Shell/邮件 → 确定性代码，不经过 LLM
- AI 对话 → `agently_adapter/qa_entry.handle()` 统一入口
- LLM 调用 → `agently_adapter/deepseek.call()` 统一封装
- 所有新功能路径 **必须走统一入口**，不要绕过

---

## 4. 已完成的功能板块

| 板块 | 路由 | 内容 |
|------|------|------|
| 首页 | `/` | 今日判断卡片 + 行业速览 + 节奏分布 |
| 市场 | `/market` | 宽基判断 + 策略环境 |
| 行业 | `/industry` | 行业轮动 + 资金流向 |
| 执行 | `/watchlist` | 三队列 + 退出信号 + 盯盘闭环 |
| 研究 | `/research` | 个股深度卡 + State 解读 |
| 回测 | `/backtest` | 五策略可选 + MN1 环境分层矩阵 |
| 策略编辑器 | `/mystrategies` | 中文条件块 + 即时预览 |
| 交易日志 | `/journal` | 记录 + 按 State 环境绩效归因 |
| 观象 AI | 右下角浮窗 | 6 Agent + 6 场景 + 多轮记忆 |
| 预警 | 邮件报告 | 三级警戒 + 诱多陷阱检测 |

---

## 5. State 系统速查

| Hex | 用户看到 | 含义 |
|------|---------|------|
| E(14)/F(15) | 🔥天时 | 强趋势+突破+扩张 |
| C(12)/D(13) | ☀️地利 | 趋势+行进中 |
| 8/9/A(10)/B(11) | 🌤人和 | 刚扩张/刚突破 |
| 4/5/6/7 | 🌥蓄力 | 收缩有趋势 |
| 0/1/2/3 | 🌧冬眠 | 收缩无趋势 |
| 负值 | ⚡逆位 | 方向向下 |

**映射规则：** `config/state_human_mapping.json`
**计算层不动：** Hex 编码在 DuckDB 侧 bit-exact 不变，只在渲染层映射。

**6 节奏：** 生长季 / 秋收期 / 破土期 / 萌芽期 / 冬藏期 / 逆风期
**节奏计算逻辑：** `outputs/v_perspective_state_human.sql`

---

## 6. 当前进行中

| 任务 | Agent | 状态 |
|------|-------|:--:|
| 观象 9 项前端交互测试 | KIMI | ⏳ 等待结果 |

---

## 7. 待办（按优先级）

### 🔴 P0 — 阻塞用户使用

| # | 任务 | 说明 |
|---|------|------|
| 1 | KIMI 测试结果出来后，修发现的问题 | 按钮没反应、模式切换不工作等 |
| 2 | 发内测通知到群 | 网址 + 账号密码，模板见附录 |

### 🟡 P1 — 本周

| # | 任务 |
|---|------|
| 1 | QQ 邮箱 SMTP 授权码轮换 |
| 2 | 服务器 `crontab` 或 systemd timer 跑 `run_daily_pipeline.sh`（当前可能没配） |
| 3 | `mystrategies` 页「运行回测」按钮打通（当前置灰） |
| 4 | 首页节奏预告改为真实数据（当前读 `daily_brief` 的 rhythm_distribution） |

### 🟢 P2 — 后续

| # | 任务 |
|---|------|
| 1 | 用户自定义策略回测 + 环境分层 |
| 2 | 融合 Agent A/B 对比框架 |
| 3 | 观象记忆真正流入 Agent prompt（当前只到 context，router 没用） |
| 4 | 公开多租户部署（Linux + systemd + 多账号） |

---

## 8. 关键文件速查

| 文件 | 作用 |
|------|------|
| `web/main.py` | 整个网站后端（3649 行，过厚但暂不拆分） |
| `web/templates/` | Jinja2 模板（_ai_assistant.html 前端观象逻辑在此） |
| `agently_adapter/qa_entry.py` | AI 对话统一入口 |
| `agently_adapter/deepseek.py` | DeepSeek/Agently 统一调用封装 |
| `agently_adapter/agents/` | 6 个 LLM Agent 定义 |
| `agently_adapter/scenarios/` | 6 个场景编排链 |
| `hermass_platform/strategy/condition_translator.py` | 中文条件→DuckDB SQL |
| `hermass_platform/trade_journal.py` | 交易日志存储 |
| `hermass_platform/chat/conversation_manager.py` | 会话管理 |
| `hermass_platform/chat/conversation_store.py` | SQLite 会话持久化 |
| `hermass_platform/api/user_profiles.py` | 用户身份（当前默认 admin） |
| `scripts/build_daily_warning.py` | 每日预警计算 |
| `scripts/send_daily_report.py` | 邮件报告（含预警卡片） |
| `scripts/run_daily_pipeline.sh` | 每日流水线 |
| `config/state_human_mapping.json` | Hex→中文映射表 |
| `outputs/v_perspective_state_human.sql` | 人类可读 State 视图 |
| `outputs/conversations.db` | 会话历史 SQLite |
| `outputs/trades.db` | 交易日志 SQLite（服务器上） |
| `docs/SUPERTRADER_UPGRADE_ROADMAP.md` | 升级路线图 |
| `docs/STRATEGY_EDITOR_DESIGN.md` | 策略编辑器技术方案 |
| `docs/2026-05-31_RETROSPECTIVE.md` | 两天工作复盘 |
| `docs/website_v2_improvement/` | V2 改进文档套件 |
| `data/research/` | 暴跌回溯研究报告 |

---

## 9. 开发规则（踩坑经验）

1. **新增功能路径必须走统一入口** — 不要绕过 `qa_entry.handle()` 直接调 LLM
2. **数据预取单独降级** — 每个数据函数独立 try，失败设空不对，不阻塞链路
3. **会议明确说「不做」的事，不做** — 11 人账号回退已经证明
4. **服务器部署后验证 LLM 链路** — `agently` 包、`DEEPSEEK_API_KEY` 环境变量都要确认
5. **多 Agent 并行交付时，任务分配到不重叠的文件集** — 避免 merge conflict
6. **WriteFile 被 macOS 沙箱拦截时，切 Shell 用 `cat > file << 'EOF'`** — 见 `AGENTS.md`
7. **推送失败时，直接在终端跑 `git push`** — Trae sandbox 网络偶断

---

## 10. 附录：内测通知模板

```
Hermass 内测入口已就绪

网址：http://console.supertrader.world
账号：hermass-test
密码：Hermass2026!Lab

登录弹出输入框，填入上面的用户名和密码。
首页打开就能看到今天的市场判断和节奏分布。
右下角「观象」AI 助手也可以问了——试试「现在能不能做」「000021 怎么看」。
有问题群里说。
```
