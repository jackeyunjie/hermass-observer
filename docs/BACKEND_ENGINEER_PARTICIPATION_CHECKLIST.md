# 后端工程师参与清单

版本：v1.0  
日期：2026-05-30  
适用对象：Hermass 后端工程师 / 服务端协作者

## 目的

当前 `Hermass 多周期观察台` 已经不是单页原型，已经包含：

- 多页面 FastAPI + Jinja2 网站
- `观象` AI 助手
- `对话 / 任务` 双模式
- 盯盘命令账本
- 邮件提醒脚本
- `DeepSeek` 增强解释链路骨架
- 分层数据包与 `outputs/` 依赖

因此后端工程师现在参与，不是从零重做，而是帮助把当前原型收成更稳的服务结构。

---

## 一、必须先了解的系统事实

### 1. 当前部署形态

- 域名：`http://console.supertrader.world/`
- 入口认证：Nginx Basic Auth
- 服务进程：`hermass-console`
- 启动方式：`systemd + uvicorn`
- 代码目录：`/opt/hermass`
- 反代：现网 `company-pager-nginx`

### 2. 当前主要页面

- `/`
- `/market`
- `/industry`
- `/watchlist`
- `/research?stock_code=000021.SZ`
- `/backtest`

### 3. 当前 AI 助手能力

- 名称：`观象`
- 模式：
  - `对话`
  - `任务`
- 已支持：
  - 市场/行业/个股解释
  - 连续上下文（股票 + 邮箱）
  - 价值分析入口
  - 盯盘命令写账本
  - 邮件提醒脚本

---

## 二、必须看

### 1. 服务主入口

- `web/main.py`

重点关注：

- 路由是否过厚
- 页面聚合逻辑是否需要拆 service layer
- AI 助手逻辑是否需要模块化
- `outputs/` 读取是否需要统一数据访问层

### 2. 助手前端

- `web/templates/_ai_assistant.html`

重点关注：

- 对话/任务模式切换
- 会话上下文存储方式
- 追问按钮和任务确认卡是否适合继续扩展

### 3. 盯盘与提醒

- `scripts/process_watch_command_alerts.py`
- `config/hermes_cron.json`

重点关注：

- 是否应继续保留脚本式 job
- 是否需要单独抽成后台任务模块
- 任务去重、关闭、幂等性是否足够

### 4. 数据更新

- `docs/DAILY_WEBSITE_UPDATE_SOP.md`

重点关注：

- 当前是“代码更新”和“数据更新”分离
- 是否需要把数据更新正式改成服务器端重建主线

---

## 三、建议看

### 1. 价值研究链路

- `hermass_platform/research/external_research_formatters.py`
- `config/prompts/coze_value_research_prompt_pack.md`
- `docs/COZE_VALUE_PROMPT_INTEGRATION_SPEC.md`

重点关注：

- `value` 视图是否应继续走 formatter 主链
- LLM 增强是否应只做解释层

### 2. AI 助手回答合同

- `docs/AI_ASSISTANT_RESPONSE_CONTRACT.md`
- `docs/AI_ASSISTANT_AGENTLY_DEEPSEEK_ENHANCEMENT_SPEC.md`
- `docs/AI_WATCH_COMMAND_EMAIL_ALERT_SPEC.md`

重点关注：

- 输出合同是否稳定
- Provider 抽象是否应该单独封装

### 3. 部署与运维

- `docs/SERVER_DEPLOY_RUNBOOK.md`
- `docs/PREDEPLOY_SCOPE_FREEZE.md`

重点关注：

- 当前部署链是否足够清晰
- 是否需要补 `OPS_RUNBOOK_V2`

---

## 四、暂时别动

这些部分短期不要先推翻：

1. 不要立刻把 Jinja2 全改 SPA
2. 不要立刻上完整用户体系
3. 不要立刻开放客户自配模型 / API
4. 不要把规则助手一次性改成纯 LLM 助手
5. 不要先动现有部署入口（`company-pager-nginx + systemd`）

原因：

- 当前已经上线可测
- 现在最重要的是稳定性与反馈闭环
- 不是技术重构窗口

---

## 五、优先给出的后端意见

请优先回答这 5 个问题：

1. `web/main.py` 是否需要拆分为更清晰的 service / router / provider 结构？
2. `观象` 的任务链路（会话、账本、提醒）是否需要独立模块？
3. `DeepSeek / Agently` 增强链路是否需要统一 provider 抽象？
4. `outputs/` 文件读取是否需要一层稳定的数据访问封装？
5. 当前 `邮件提醒 + cron + 脚本` 是否足够，还是该升级成正式后台任务体系？

---

## 六、当前最有价值的参与方式

不是“推翻重做”，而是：

1. 帮当前原型收成更稳的服务结构
2. 帮 AI 助手的 provider / task / data access 做分层
3. 帮数据更新链路从“人工同步”走向“服务器端重建”
4. 帮盯盘和提醒链路做可运维化

一句话：

**当前最需要的是工程化收口，不是架构炫技。**
