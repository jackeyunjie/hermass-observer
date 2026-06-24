
## 修改 → 部署 → 测试 流水线（2026-05-31 固化）

**核心原则：优先本地代码修改 + git push；需要部署、同步数据或排障时，允许本机直接 SSH 到服务器执行必要操作。**

### 服务器操作规则

- ✅ 允许本机 SSH 到 8.130.125.201 执行部署、数据同步、日志排障和服务重启
- ✅ 允许本机 curl 服务器接口做冒烟验证
- 执行前先说明目的；执行后给出结果和下一步

### 三阶段流水线

| 阶段 | 执行者 | 动作 | 输入 |
|------|--------|------|------|
| 1. 审阅 | Claude | 代码 diff 审阅 | 本机 diff / commit |
| 2. 部署 | Codex / 服务器 Codex | git pull + 编译 + 重启 + 冒烟 | git push 后的 commit hash |
| 3. 测试 | Codex / KIMI | 接口或浏览器端回归测试 | 部署完成确认 |

### 部署提示词模板（发给服务器上的 Codex）

```
在 /opt/hermass 执行部署：

1. git pull
2. source .venv/bin/activate && python -m py_compile web/main.py
3. sudo systemctl restart hermass-console && sudo systemctl status hermass-console
4. 冒烟验证：
   - curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/
   - curl -s -X POST http://localhost:8020/api/chat/query ... | grep provider

验收：服务 active (running)，HTTP 200，provider 符合预期
```

### 模板 UndefinedError 处理规则

- 若遇到 `jinja2.exceptions.UndefinedError`，且根因是模板把 `stock.xxx.yyy` 当对象属性访问字典对象：
  - 优先修改模板，将 `stock.xxx.yyy` 改为 `stock.get('xxx', {}).get('yyy', '-')`
  - 不优先通过修改 `web/main.py` 的兜底对象或函数签名来绕过
  - 除非该字典字段缺失属于全站统一契约变更，才返回到本地统一补后端上下文

### 服务器编译规则

- ❌ 不要用系统 `python3` 或 `python -m py_compile` 编译项目，服务器系统 Python 版本可能不兼容。
- ✅ 必须使用项目虚拟环境编译：`source .venv/bin/activate && python -m py_compile <file>` 或 `/opt/hermass/.venv/bin/python -m py_compile <file>`。
- 若服务器 AI 尝试用系统 Python 做语法检查导致误报，一律视为未通过，必须改用 `.venv/bin/python` 复核。

### 服务器信息

- IP: 8.130.125.201
- 项目路径: /opt/hermass
- 服务: hermass-console (systemd, 端口 8020)
- Python: .venv 虚拟环境
- 网址: http://console.supertrader.world

### 服务器上传 413 / Nginx 容器入口快查

遇到网站数据上传失败、HTTP 413、Nginx 容器入口不清楚、`company-pager-nginx` 是否属于 Hermass 等问题，先看：

- `docs/SERVER_UPLOAD_413_RUNBOOK.md`

已确认背景：

- 服务器 80/443 入口是 Docker 容器 `company-pager-nginx`
- 宿主机配置文件是 `/opt/company-pager/nginx-backend.conf`
- 容器内配置文件是 `/etc/nginx/conf.d/default.conf`
- `company-pager-nginx` 虽然名字像另一个项目，但它代理了 `console.supertrader.world -> http://172.17.0.1:8020`
- 改完宿主机配置后，优先 `docker restart company-pager-nginx`，再用 `docker exec company-pager-nginx nginx -T` 验证是否真实生效

### 网站公网访问与 AI 对话认证验收（2026-06-24 固化）

- `console.supertrader.world` 当前浏览全站免登录；公网首页、`/chain-studio`、`/api/chain-studio` 不应再返回 Basic Auth `401`。
- 仅 AI 对话运行入口 `/api/chat/query` 需要 Basic Auth。
- 真实入口容器仍是 `company-pager-nginx`，配置位置：
  - 宿主机：`/opt/company-pager/nginx-backend.conf`
  - 容器内：`/etc/nginx/conf.d/default.conf`
- 当前 Nginx 配置应满足：
  - `server_name console.supertrader.world;`
  - server 块顶层不启用 `auth_basic`
  - 仅 `location /api/chat/query` 启用：
  - `auth_basic "Hermass Console";`
  - `auth_basic_user_file /etc/nginx/.htpasswd_hermass;`
- 当前公网验收账号：
  - 用户名：`hermass-test`
  - 密码：`Hermass2026!Lab`
- 验收规则：
  1. 未带凭证访问 `http://console.supertrader.world/` 应返回 `200`
  2. 未带凭证访问 `http://console.supertrader.world/chain-studio` 应返回 `200`
  3. 未带凭证访问 `http://console.supertrader.world/api/chain-studio` 应返回 JSON，且包含 `"ok": true`
  4. 未带凭证 POST `/api/chat/query` 应返回 `401`
  5. 带凭证 POST `/api/chat/query` 应返回 `200`
- 标准命令：
  - `curl -s -o /dev/null -w "%{http_code}" http://console.supertrader.world/`
  - `curl -s -o /dev/null -w "%{http_code}" http://console.supertrader.world/chain-studio`
  - `curl -s http://console.supertrader.world/api/chain-studio | head -c 400`
  - `curl -s -o /dev/null -w "%{http_code}" -X POST http://console.supertrader.world/api/chat/query -H 'Content-Type: application/json' -d '{"message":"ping","mode":"chat","use_llm":false}'`
  - `curl -s -u 'hermass-test:Hermass2026!Lab' -o /dev/null -w "%{http_code}" -X POST http://console.supertrader.world/api/chat/query -H 'Content-Type: application/json' -d '{"message":"ping","mode":"chat","use_llm":false}'`
- 2026-06-06 这次 `chain-studio` 恢复的真实根因不是登录限制，而是：
  - `web/templates/chain-studio.html` 曾漏提交
  - 服务器 `outputs/industry_chain/industry_chain_evidence.duckdb` 需要包含 `chain_studio_overview`、`chain_studio_nodes`、`chain_studio_events`、`chain_studio_candidates`
- 若本地 `localhost:8020/api/chain-studio` 已 `ok:true`，但公网 `/chain-studio` 或 `/api/chain-studio` 仍 `401`，优先检查 Nginx 是否残留 server 块级 `auth_basic`。

### 网站 public 静态文件入口与 AppleDouble（2026-06-04 固化）

- 对外 Nginx 当前实际 serve 目录是 `/opt/company-pager/public/`
- `/opt/hermass/public/` 不是 `console.supertrader.world` 当前 public 静态入口，不要把它当最终验收目标
- 从 macOS 上传 public 产物必须避免 `._*` AppleDouble 文件：
  - 推荐使用 `COPYFILE_DISABLE=1 tar --no-xattrs -czf ...`
  - 解包后必须确认 `find /opt/company-pager/public -name '._*' | wc -l` 为 `0`
- public 验收顺序：
  1. `find /opt/company-pager/public -maxdepth 2 -type f -name "*.html" | head`
  2. `find /opt/company-pager/public -maxdepth 2 -type f -name "._*" | wc -l`
  3. `curl -s -o /dev/null -w "%{http_code}" http://console.supertrader.world/`
- `public` 404 与 `market_assets_state` 失败是两类问题；不要混在一起排查。

### 每日 Foundation 增量上传快查

遇到“每天是否要传 3.7G Foundation DB”“能否只传当天数据”“网站数据上传方案”这类问题，先看：

- `docs/FOUNDATION_DELTA_UPLOAD_DESIGN.md`

已确认策略：

- 每日默认上传 `foundation_delta` 增量包 + `daily_snapshot.json`
- 2026-06-01 实测增量包约 `8.8M`，gzip 后约 `4.4M`
- 完整 `p116_foundation.duckdb` 约 `3.7G`，默认不每天上传
- 只有全量重铺时才设置 `UPLOAD_FOUNDATION=1`

---

## Agent 操作教训（2026-05-30）

### macOS 文件写入被拒的应对

当 `WriteFile` 工具被 macOS 安全沙箱拦截时（出现 "rejected by the user"）：

1. **不要反复重试 WriteFile** —— 会进入无效循环，表现为"宕机"
2. **立刻切 Shell** —— bash 系统调用绕过 IDE 沙箱
3. **先 cd 进项目目录** —— 用相对路径写文件，命令更短更安全

```bash
cd /Users/lv111101/Documents/hermass-observer-product
cat > data/research/报告.md << 'HEREDOC'
...内容...
HEREDOC
```

**一句话：WriteFile 被拒 → 秒切 Shell，绝不纠缠。**

---

## 非技术用户执行规则（2026-06-01）

**约束：用户无法阅读、理解或修改代码，所有操作必须以“可直接复制粘贴的终端命令”形式交付。**

- 禁止向用户展示代码片段、代码解释或代码 diff
- 禁止让用户手动编辑代码文件
- 禁止让用户“看看报错再决定”——必须给出一套完整下一步
- 交付物必须是：终端命令、脚本路径、或可直接发给服务器 Codex 的提示词
- 如果任务涉及代码修改，由 AI 直接修改文件，用户只执行 git push 或运行脚本
- 如果任务涉及服务器部署，用户只复制粘贴"部署提示词"给服务器上的执行者

---

## Agently 架构调用规约与本项目洞察

### 1. 分层边界（强制）

- **Web 层**：`web/main.py` 只做请求聚合、模板渲染、导航和统一入口；
- **Agently 层**：`agently_adapter/` 是唯一官方主线，负责 AI 执行编排、LLM 调用、Agent/DAG/Scenario 管理；
- **Hermes 记忆层**：`hermass_platform/` + `AgentMemory.duckdb` 是唯一真相源，负责 Agent 记忆、判断回溯、进化日志、Bus 消息总线；
- **禁止**：`web/main.py` 直接调用 `Agently.create_agent()`、`agently_daily_flow.py` 直连、或自行拼接 provider 调用链。

### 2. Agently 在本项目的角色定位

| 维度 | 结论 |
|------|------|
| 优点 | TriggerFlow 适合做声明式 DAG；Action Runtime 让节点可编排、可重放；FastAPI 服务化边界清晰 |
| 缺点 | Action 粒度过粗时会导致黑盒化；运行时边界不清会混淆“编排”与“业务逻辑”；依赖外部版本升级风险 |
| 适用定位 | **只做编排层和执行调用层**，不做记忆层、不做持久化层、不做业务判断真相源 |
| 不适用定位 | 不替代 AgentMemory；不替代 AgentBus；不替代 `hermass_platform/agents/*.py` 的领域判断 |

### 3. 官方主线入口（不可动摇）

| 层级 | 路径 | 职责 |
|------|------|------|
| shared core layer | `agently_adapter/a_share_core.py` | 唯一共享实现 |
| core flow | `agently_adapter/agently_a_share_flow.py` | A 股最小核心链路 |
| full compatibility workflow | `agently_adapter/stockpool_daily_runner.py` | 兼容闭环 |
| deprecated | `agently_adapter/agently_daily_flow.py` | 不再当主线，仅历史兼容 |

硬规则：
- `a_share_core.py` 是唯一共享实现，所有 runner/flow/service 都必须复用，禁止复制命令逻辑；
- `agently_daily_flow.py` 不得在新文档中描述为“主流程”；
- 新增 Agent/Sceanrio 只能放 `agently_adapter/agents/` 和 `agently_adapter/scenarios/`。

### 4. Web → Agently 接入规则

1. `web/main.py` 如需 LLM 增强，必须调用封装后的服务接口，禁止直连 Agently runtime；
2. AI 对话统一入口是 `agently_adapter/qa_entry.py` 的 handle 层；
3. LLM 调用统一走 `agently_adapter/deepseek.py`；
4. Web 层不感知 Agently runtime 细节，只传结构化上下文，不传裸 prompt；
5. Agently 的会话摘要、历史记忆必须落地到 `AgentMemory.duckdb`，不依赖 Agently 内置会话状态。

### 5. Hermes 记忆与复盘规约

- **AgentMemory.duckdb** 是 Agent 判断、回溯、场景、因子权重、进化日志的唯一持久化层；
- **AgentBus** 是 Agent 间异步通信主干，只使用 6 类标准消息：
  - `contraction_extreme`
  - `market_phase_change`
  - `false_breakout`
  - `weight_adjusted`
  - `review_needed`
  - `data_stale`
- **复盘闭环**必须按以下顺序运行：
  1. `agent_self_review.py` 产出 `.alert_self_review`
  2. `agent_cross_review.py` 产出 `.alert_cross_review`
  3. `alert_scanner.py` 消费标记文件，调用 `agent_bus.publish_review_needed()`，归档标记
- 任何新 topic 必须先更新 `hermass_platform/bus/agent_bus.py` 的 `MESSAGE_TYPES` 与 `PAYLOAD_SCHEMAS`，再被 Agent 发布。

### 6. 部署与运行约束

- 服务器部署后必须确认：
  - `agently` 包已安装在 `.venv`（当前版本 `4.1.2.4`）；如缺失，运行 `source .venv/bin/activate && pip install agently==4.1.2.4`；
  - `DEEPSEEK_API_KEY` / `HERMASS_DEEPSEEK_API_KEY` 等变量已配置；推荐通过 systemd drop-in 配置：
    ```bash
    mkdir -p /etc/systemd/system/hermass-console.service.d
    cat > /etc/systemd/system/hermass-console.service.d/override.conf << 'EOF'
    [Service]
    Environment=DEEPSEEK_API_KEY=sk-...
    EOF
    chmod 600 /etc/systemd/system/hermass-console.service.d/override.conf
    systemctl daemon-reload
    sudo systemctl restart hermass-console
    ```
  - `outputs/agent_bus/outbox/` 目录存在且可写；
- 禁止在服务器上直接新增 Agent 行为到 `web/main.py`；
- 新增脚本只能放 `scripts/`，由 `config/hermes_cron.json` 调用；
- 服务器编译/运行统一使用 `.venv/bin/python`，不用系统 `python3`。

### 7. 与外部项目的分工（防混淆）

| 项目 | 借用内容 | 不借用内容 |
|------|----------|-----------|
| `AgentEra/Agently` | Action Runtime、TriggerFlow、Skills/MCP 扩展点、FastAPI 服务化能力 | 聊天代理作为系统主入口、独立运行时替换当前 Hermes 架构 |
| `daily_stock_analysis` | 日报结构、Web 工作台入口组织 | A/H/US 混合市场定位、决策仪表盘式买卖建议语义 |
| `TradingAgents-CN` | 多 Agent 展示层、页面分工 | 重型前后端基础设施、多市场分析框架作为底座 |
| `hermes-agent` | 技能沉淀、会话记忆与检索、定时任务机制 | 聊天代理作为系统主入口、独立运行时替换当前 Agently 方向 |

### 8. 当前迁移状态（已落地）

- **调度层**：`config/hermes_cron.json` 已接管日频、复盘、告警任务；
- **执行层**：`agently_a_share_flow.py` 是 A 股 core flow，`stockpool_daily_runner.py` 是兼容层；
- **记忆层**：`AgentMemory.duckdb`、`agent_self_review.py`、`agent_cross_review.py`、`alert_scanner.py` 已具备闭环脚本，但真实调度和连续运行证据必须按“Agent 复盘与自组织运行真实状态”复核；
- **服务层**：`web/main.py` 仍为 FastAPI + Jinja2 主入口，不直接暴露 Agently runtime。

## 三模型协作分工（2026-06-02 固化，06-02 修订：Kimi 优先）

**Kimi 有套餐，尽量把工作交给 Kimi。Codex 专职代码审计和最后兜底。SSH 所有模型都可用。**

| 角色 | 负责 | 产物 |
|------|------|------|
| **Kimi（主力）** | 策略蓝图 + 工程落地 + 每日数据更新 | JSON/YAML、Python 脚本、DDL、HTML |
| **Qoder** | 协助 Kimi：复杂工程问题、Kimi 遇到瓶颈时接手 | .py/.sql/.html 文件 |
| **Codex（审计+兜底）** | 代码审查、全链路审计、上线前 checklist、混沌演练 | 审计报告、风险评估、安全确认 |

### 修改后的工作流

```text
1. Kimi 直接写代码 → 修改文件
2. 人 git add + commit + push
3. 人 SSH 到服务器执行部署（任何模型都可以给 SSH 命令）
4. Codex 审计 Kimi/Qoder 产出代码
5. 发现的问题 → 1
```

---

## State Cube + MOE 多 Agent 主线（2026-06-04 固化）

**Phase 2 主线已经从“单指标知识卡片”纠偏为：State Cube + 多 Agent 辩论 + 动态权重路由 + 决策观察账本。**

### 核心定位

- `strategy_rules/priors/*.json` 是**指标状态 token 字典**，只解释单个指标状态本身；
- `outputs/state_cube/state_cube.duckdb` 是 Phase 2 的**同一时刻多周期多指标状态全景图**；
- 真正决策层不是单指标 empirical_prior，也不是单状态前端卡片，而是：

```text
State Cube 一行/一组候选
  -> 多 Agent 辩论
  -> Dynamic Weight Router 分配权重
  -> Decision Observation Ledger 记录判断与后验
  -> 前端多 Agent 辩论面板
```

### 已落地

| 组件 | 路径 | 状态 |
|------|------|------|
| State Cube 构建 | `scripts/build_state_cube.py` | 已完成 MVP |
| State Cube 数据 | `outputs/state_cube/state_cube.duckdb` | 718 万行 × 25 字段，约 767MB |
| Agent 辩论 | `scripts/agent_debate_runner.py` | 已接入 State Cube，每日运行 |
| 动态权重路由 | `scripts/dynamic_weight_router.py` | 已产出市场级 verdict |
| 决策观察账本 | `scripts/decision_observation_ledger.py` | 已写入 `decision_observation.duckdb`，支持 future_r5 回填 |
| 历史回填 | `scripts/backfill_market_observation_ledger.py` | 默认回填最近 90 天市场级信号 |
| 前端面板 | `web/templates/debate_dashboard.html` | 已展示 Agent 辩论、Router 结论、准确率、市场择时账本 |

State Cube 当前覆盖：

```text
stock_code, state_date
MN1/W1/D1 Hermass state_hex
W1/D1 MA 144/169/200 state
W1/D1 BB20 position/width
W1/D1 BB50 position
W1/D1 ATR14, ADX14, +DI/-DI
D1/W1 close
future_r5, future_r20
```

### 硬规则

1. **不要再把 Phase 2 主线带回单指标前端卡片。**
2. 单指标 `priors` 只作为状态解释词典，不作为最终交易决策层。
3. 单指标 empirical 统计只能作为证据特征，不能直接给交易方向染色。
4. ~~下一步优先做：agent_debate_runner / dynamic_weight_router / decision_observation_ledger / 前端面板~~（2026-06-22 已完成并接入每日管线）。
5. ~~把 per-stock 决策记录接入 Ledger~~（2026-06-22 已完成）：`scripts/agent_debate_runner.py` 对 EF≥2 的 Top 50 标的逐只产出 6-Agent 评分，`decision_observation.duckdb` 按 `PER_STOCK_OBSERVATION` hypothesis 写入个股判断，前端 debate_dashboard 展示「个股决策账本」。
6. 当前重点是：
   - 基于 Ledger 后验持续校准 Router 阈值；
   - 将 Risk Agent 命中率从 46.2% 提升至基线以上；
   - ~~为 per-stock Ledger 增加历史回填~~（2026-06-22 已完成：回填 90 天、2650 条记录、前端展示正收益比例与分档统计）；
   - ~~增加单标的复盘详情页/曲线~~（2026-06-22 已完成：点击个股账本行弹出历史轨迹面板，含评分折线图、胜率统计、30 日信号表）。
5. 前端优先展示多 Agent 意见、冲突、共振、权重和风险反驳；不要优先做单指标红绿灯。
6. Router 权重必须来自同一时刻状态全景、冲突/共振、周期层级和历史 outcome；不要写死 `ef_count_min` 作为入口。
7. M30 Agent 只做盘中观察和精确位置判断，不单独拍板。
8. Risk Agent 必须作为常驻反驳者，专门寻找假突破、过热、数据异常和回撤风险。

### MOE 类比

| 大模型概念 | Hermass 对应 |
|------------|--------------|
| token | 每个周期、每个指标的 state |
| embedding | 价格位置、带宽、斜率、间距、支撑阻力等结构化特征 |
| expert | W1/D1/M30/趋势/动量/波动/边界/风险 Agent |
| router/gate | Dynamic Weight Router |
| attention | 找出当前最关键的周期与指标碰撞 |
| output | 重点标的、策略适配、风险边界、观察结论 |

### 下一步验收标准

任取一只股票和一个日期：

```text
1. 系统能从 State Cube 读取完整状态图；
2. 至少 6 个 Agent 输出结构化意见；
3. Router 给出权重、冲突、共振和最终观察结论；
4. Ledger 写入本次判断；
5. 后续可回填 5/20 日结果做复盘。
```

详细复盘文档：

- `data/research/conversations/18-State Cube与MOE多Agent主线复盘.md`

---

## Obsidian 知识沉淀规则（2026-06-03 固化）

**目标：把项目对话、Markdown 文档、网页资料沉淀到 Obsidian；支持一次执行、历史回填、定时执行，并可迁移到任何项目。**

### 工具入口

| 场景 | 命令 |
|------|------|
| Hermass 项目内 | `.venv/bin/python tools/obsidian_exporter/cli.py export` |
| Hermass 历史回填 | `.venv/bin/python tools/obsidian_exporter/cli.py export --all` |
| 同步项目文档 | `.venv/bin/python tools/obsidian_exporter/cli.py sync-docs --pattern "docs/**/*.md"` |
| 抓取网页快照 | `.venv/bin/python tools/obsidian_exporter/cli.py clip-url "https://example.com"` |
| 任意项目全局 Skill | `python3 ~/.codex/skills/obsidian-knowledge-sync/scripts/obsidian_sync.py export` |

### 默认路径

- Vault: `data/research/conversations/`
- 对话数据库: `outputs/conversations.db`
- 对话日记: `daily/YYYY-MM-DD.md`
- 项目文档: `project-docs/`
- 网页快照: `web-clips/`

### 自动执行边界

- ✅ 可以自动执行 `init`、`export`、`sync-docs`、`clip-url`
- ✅ 可以把 `config/hermes_cron.json` 的定时任务指向 `tools/obsidian_exporter/cli.py export`
- ✅ 可以用环境变量覆盖路径：`OBSIDIAN_VAULT`、`OBSIDIAN_SOURCE_DB`、`OBSIDIAN_PROJECT_ROOT`
- ❌ 不要让定时任务执行 `export --all`，历史回填只能手动一次性跑
- ❌ 不要把 vault 自身再同步进 vault
- ❌ 不要把生成的 `daily/*.md` 默认推送到服务器；本地知识库默认本地使用，除非用户明确要求纳入 Git/push
- ❌ 不要为了适配某个项目随意改 `web/main.py`；对话导出只读 `outputs/conversations.db`

### 对话库 schema

当前通用导出器优先支持：

- `turns(session_id, role, message, intent, agent, timestamp)`
- 可选：`sessions(session_id, user_id)`

如果其他项目的 schema 不同，先查看表结构，再扩展 `tools/obsidian_exporter/import_conversations.py` 或全局 Skill 脚本，不要把数据硬塞成 Hermass 专用结构。

---

## 每日数据更新 SOP（2026-06-02 固化）

**核心策略：本地全流程 + 只上传产物。不传 3.7G Foundation DB，也不在服务器上跑重脚本。**

### 正确流程（Kimi 执行，已验证）

```text
1. Kimi 本机下载今天 K 线（黑狼 API）+ 资金流数据
   - 同时必须下载指数/行业 ETF 市场资产行情：
     blackwolf_actions/download_market_assets.py --date YYYY-MM-DD --days 3
   - 逐日导入市场资产库：
     blackwolf_actions/import_market_assets_duckdb.py --date YYYY-MM-DD
2. Kimi 本机构建 Foundation DB（build_p116_foundation.py --date YYYY-MM-DD）
3. Kimi 本地跑全部脚本（因为本地有完整 Foundation DB）：
   - strategy_signal_ledger.py --date YYYY-MM-DD
   - estimate_reward_risk.py --date YYYY-MM-DD
   - forward_observation_ledger.py --date YYYY-MM-DD
   - run_recommendation_workflow.py --date YYYY-MM-DD
   - build_stock_percentiles.py --date YYYY-MM-DD
   - rebuild_bb_pivot_atr.py --date YYYY-MM-DD
   - build_daily_snapshot.py --date YYYY-MM-DD
   - send_daily_hermass_digest_to_lark.py --date YYYY-MM-DD（推送群消息 + 同步决策观察账本到飞书 Base）
4. Kimi 只上传产物 JSON/CSV 到服务器 outputs/ 对应目录
5. 人 SSH 重启服务 + 冒烟
```

### market_assets_state 验收硬规则（2026-06-04 事故复盘）

- `outputs/market_assets_state/market_assets_state_YYYYMMDD.json` 的文件名日期不等于数据有效日期。
- 网站验收读取 JSON 列表中每行的 `state_date`，要求最大 `state_date == YYYY-MM-DD` 且 `row_count > 0`。
- 如果失败表现为“文件存在、行数正常、但 `/api/admin/data-sync-status` 中 `market_assets_state.date` 是旧日期”，根因通常是 `outputs/market_assets/market_assets.duckdb` 没有导入当天指数/行业 ETF 行情。
- 正确修复顺序：
  1. 下载市场资产行情：`blackwolf_actions/download_market_assets.py --date YYYY-MM-DD --days 3`
  2. 逐日导入：`blackwolf_actions/import_market_assets_duckdb.py --date YYYY-MM-DD`
  3. 重建：`scripts/build_market_assets_state.py --date YYYY-MM-DD`
  4. 上传：`scripts/upload_output_to_server.py --date YYYYMMDD --type market_assets_state`
  5. 验收：`scripts/validate_website_data_sync.py --date YYYYMMDD`
- 不要通过改验收脚本或把旧 `state_date` 当成今天来绕过。

### 飞书每日复盘推送

- 群消息依赖 `config/platform/lark_app.yaml` 中的 `push.chat_id`，使用 Bot 身份发送（`lark-cli im +messages-send`）。
- Base 同步依赖 `config/platform/lark_digest.yaml` 中的 `base_token` 与 `table_id`；首次使用需运行 `scripts/setup_lark_base_digest_table.py --base-token <base_token>` 建表。
- 已加入 `config/hermes_cron.json`：交易日 15:46 自动执行 `send_daily_hermass_digest_to_lark.py`。

### 为什么不在服务器跑

- 服务器只有 05-29 的 Foundation DB，没有今天的数据
- 在服务器上跑 `build_daily_snapshot.py` 会把已有 snapshot 覆盖成旧数据
- 本地有完整 Foundation DB，结果正确

### 全量重铺（仅必要时）

设置 `UPLOAD_FOUNDATION=1`，上传完整 3.7G p116_foundation.duckdb。
详见 `docs/FOUNDATION_DELTA_UPLOAD_DESIGN.md`。

---

## Agent 复盘与自组织运行真实状态（2026-06-05 复核）

### 当前结论

- `scripts/run_hermes_cron.py` 已落地，负责读取 `config/hermes_cron.json` 并真实执行任务。
- `config/platform/com.hermass.hermes-cron.plist` 已提供 launchd 常驻配置，并已安装到 `~/Library/LaunchAgents/com.hermass.hermes-cron.plist`。
- 2026-06-05 复核 launchd 状态：`state = running`，PID `76941`，`last exit code = (never exited)`。
- `scripts/agent_self_review.py` 存在，设计为每 4 小时自评。
- `scripts/agent_cross_review.py` 存在，设计为每日收盘后互评。
- `scripts/alert_scanner.py` 存在，设计为消费 `.alert_*` 标记并广播 `AgentBus.review_needed`。
- 已手动验收一次最小闭环：`run_hermes_cron.py run-once --task "AI 自评健康检查"` 产出自评，自动调用 `alert_scanner.py`，归档 `.alert_self_review`，并向 `human_reviewer` 写入 AgentBus `review_needed`。
- 已手动验收互评：`cross_review_20260604.json` 生成，结果 `overall=ok`。
- 已生成人机对齐复盘：`outputs/reviews/human_review_20260604.md`。
- 自评已连续运行超过一个完整 4 小时周期：2026-06-04 20:00、2026-06-05 00:00、2026-06-05 04:00（最新 `self_review_20260605_0400.json`，UTC 11:00 生成），`self_review_latest.json` 时间戳在 4.5 小时内。
- 当前自评仍有 `health` warning：`HTTP Error 502: Bad Gateway`（服务未在本地 8020 运行），`data_freshness` 正常（最新 `20260604`，28 小时未过期，阈值 48 小时）。

### 禁止夸大

不要写“Agent 复盘闭环已稳定自组织运行”，除非同时满足下面验收：

1. 真实调度器已安装并可查看（crontab、launchd、systemd timer 或 Python daemon）。
2. `self_review_latest.json` 时间戳在最近 4.5 小时内。
3. 当天存在 `cross_review_YYYYMMDD.json`。
4. `alert_scanner.py` 已被定时调用或串在 review 后调用。
5. `outputs/agent_bus/outbox/` 有 `review_needed` 消息，或无告警时有 scanner 日志证明扫描过。
6. 人类对齐复盘有明确产物：`outputs/reviews/human_review_YYYYMMDD.md` 或飞书/Obsidian 同步记录。

### 下一步真正落地

真实运行器已经补齐，launchd 已安装并运行。后续如需重新安装/重启：

```text
cp config/platform/com.hermass.hermes-cron.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.hermass.hermes-cron.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.hermass.hermes-cron.plist
launchctl list | grep com.hermass.hermes-cron
```

复盘链路应当固化为：

```text
agent_self_review.py
  -> 如异常写 .alert_self_review
  -> alert_scanner.py
  -> AgentBus.review_needed

agent_cross_review.py --date YYYY-MM-DD
  -> 如差异写 .alert_cross_review
  -> alert_scanner.py
  -> AgentBus.review_needed

human_review_YYYYMMDD.md
  -> 人类确认当天异常、分歧和权重调整
  -> 同步 Obsidian
```

---

## 三波建设成果速查（2026-06-02）

### 波 1：底座加固
- `p116_foundation.duckdb` 追加 `data_quality_score`、`market_segment`、`bar_history_days`、`post_suspension_days`
- `outputs/agent_memory/AgentMemory.duckdb`：5 表 9 索引
- `bb_pivot_atr` 物化视图表
- Makefile `db-migrate` target

### 波 2：收缩观测 + Agent 协作
- `hermass_platform/agents/contraction_observer.py`
- `hermass_platform/bus/agent_bus.py`（6 topic + JSON schema）
- `scripts/build_stock_percentiles.py`

### 波 3：自进化 + 前端
- `scripts/factor_homeostasis.py`（免疫稳态）
- `scripts/build_scenario_library.py`（场景库自动构建）
- **五条红线**：`config/redlines.yaml` + `hermass_platform/red_lines.py`
- 前端：`index.html` 面板收敛（10+→6）、`watchlist.html` 列精简（14→4）

---

## 关键数据库表速查

| 数据库 | 关键表 | 用途 |
|--------|--------|------|
| p116_foundation.duckdb | `d1_perspective_state` | MN1/W1/D1 State 矩阵（8.5M 行） |
| p116_foundation.duckdb | `timeframe_indicators` | BB/ATR/ADX 指标 |
| p116_foundation.duckdb | `bb_pivot_atr` | BB+枢轴+ATR 物化视图 |
| AgentMemory.duckdb | `agent_judgments` | Agent 每次判断记录 |
| AgentMemory.duckdb | `judgment_outcomes` | 判断回溯结果 |
| AgentMemory.duckdb | `agent_scenario_library` | 场景模板库 |
| AgentMemory.duckdb | `factor_weights_history` | 因子权重演进历史 |
| AgentMemory.duckdb | `agent_evolution_log` | Agent 成长日志 |

---

## 五条红线（不可绕过）

1. **止损/止盈不可自动执行** — 需人类确认
2. **策略结构不可变** — VCP/2560/Bollinger/composite 四策略保护
3. **数据异常必报人类** — DEGRADED 后自动 AgentBus 广播 review_needed
4. **仓位上限不可突破** — 单只 25% / 单行业 40%，不可覆盖
5. **Admin kill-switch** — 24h 自动过期，暂停所有自进化

配置：`config/redlines.yaml`，代码加载时读取。
审计日志：`outputs/red_line_audit_log.jsonl`

---

## 研发存档

全部设计文档、对话记录、辩论结果：`data/research/conversations/`（共 16 份）
全链上下文交接文档：`data/research/conversations/16-全链上下文-新对话交接.md`
