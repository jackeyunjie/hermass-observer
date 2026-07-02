# KIMI 提示词：State Timeline Observer 同步实施

日期：2026-07-01  
执行者：KIMI  
审计与收口：Codex

---

## 一、使用方式

把下面整段直接发给 KIMI 执行。

---

## 二、发给 KIMI 的完整提示词

你现在在 Hermass Observer 项目里执行 `State Timeline Observer` Phase 1。

先读以下文档，再动代码：

- `docs/STATE_TIMELINE_OBSERVER_SPEC.md`
- `docs/tasks/KIMI_TASK_STATE_TIMELINE_OBSERVER_PHASE1_20260701.md`
- `docs/STATE_BASE_CONTRACT.md`
- `docs/STATE_DISPLAY_ALIAS_SPEC.md`

今天已经明确的新口径，必须全部落实，不能漏任何一层：

1. Observer 不只统计 `E/F`
2. `A/B` 必须作为关键位突破事件进入正式模型
3. `0` 必须作为收缩充分、等待释放事件进入正式模型
4. 主观察口径必须是分周期事件，而不是混合 `ef_count`
5. 网站、后端 API、查询层、注释、文档、服务器部署方案必须同步
6. 如果涉及定时任务、记忆层、运行约束、项目规则文档，也必须同步评估并给出实施或延期结论

你这次不是只改一个页面，而是做一套同步实施。按下面 7 个层次完成。

---

### A. 本地代码实施

目标：先在本地把查询层、API、页面、文档一次性打通。

必须完成：

1. 实现 `state_timeline_daily` 查询层或等价只读查询封装
2. 提供：
   - `GET /api/state-observer`
   - `GET /api/state-observer/timeline`
3. 提供页面：
   - `/state-observer`
4. 页面和 API 使用完全一致的字段命名
5. 不允许只改前端，不改后端
6. 不允许只改 API，不改页面

本地修改优先范围：

- `web/main.py`
- `web/templates/` 下新增或修改 `state-observer` 页面模板
- 若需要新增查询辅助模块，可放在现有项目合适位置，但不要大范围重构
- 必要时补 `scripts/validate_website_data_sync.py` 的最小验收逻辑
- 如字段口径变化，必须同步 `docs/STATE_TIMELINE_OBSERVER_SPEC.md`

---

### B. 数据库与查询层实施

目标：让 State Timeline Observer 有稳定、统一、可复用的长表真相源。

必须产出的正式字段：

- `stock_code`
- `stock_name`
- `state_date`
- `mn1_state_hex`
- `w1_state_hex`
- `d1_state_hex`
- `mn1_state_score`
- `w1_state_score`
- `d1_state_score`
- `mn1_is_ef`
- `w1_is_ef`
- `d1_is_ef`
- `mn1_is_ab`
- `w1_is_ab`
- `d1_is_ab`
- `mn1_is_zero`
- `w1_is_zero`
- `d1_is_zero`
- `ef_count`
- `ef_pattern`
- `ab_count`
- `ab_pattern`
- `zero_count`
- `zero_pattern`
- `state_triplet`
- `display_alias`
- `industry_l1`
- `close`
- `volume`
- `as_of_date`

字段规则：

1. `A/B` 定义：
   - `A = 扩张 + 无趋势 + 突破 + 稳定`
   - `B = 扩张 + 无趋势 + 突破 + 活跃`
2. `0` 定义：
   - `0 = 收缩 + 无趋势 + 未突破 + 稳定`
3. `mn1_is_zero / w1_is_zero / d1_is_zero` 必须为正式布尔字段
4. `zero_pattern` 必须为正式字段，不能只在前端拼
5. `ef_count / ab_count / zero_count` 都只能做辅助字段，不能回到主统计口径

数据源优先：

- `d1_perspective_state`
- `daily_bars`
- 必要行业映射
- 展示别名派生

实现要求：

1. 长表真相模型固定为：

```text
一只股票 × 一个交易日 = 一行
```

2. 不要把最近 3/6/30 天横向铺成核心真相表
3. 不要改动 State 底座契约
4. 不要在数据库层引入交易建议字段

---

### C. 前后端同步实施

目标：字段、筛选、分组、文案口径一致。

前端必须支持：

1. 事件族切换：
   - `全部`
   - `EF`
   - `A+B`
   - `0`
2. 分周期主分组：
   - 月线 EF / 周线 EF / 日线 EF
   - 月线 A/B / 周线 A/B / 日线 A/B
   - 月线 0 / 周线 0 / 日线 0
3. 交集模式筛选：
   - `ef_pattern_any`
   - `ab_pattern_any`
   - `zero_pattern_any`
4. 查询方式：
   - 单只股票
   - 多只股票
   - `symbol_set`
   - `Top50`
   - 全市场分页
5. 时间方式：
   - `days`
   - `date_from/date_to`
6. 导出：
   - `json`
   - `csv`

页面文案要求：

1. 这是观察工作台，不是交易指令面板
2. 不允许出现买入、卖出、止损、目标价等表达
3. 不允许第一屏继续按混合 `ef_count` 组织
4. 不允许把 `A/B` 或 `0` 藏进详情，不进入主视图

默认展示要求：

1. 数字 `state_score` 为主
2. `state_hex` 为辅
3. 中文解释放展开层或辅助层

---

### D. 服务器与部署同步实施

目标：本地完成后，按 Hermass 固定流程部署到服务器，不在服务器上重新设计实现。

部署原则：

1. 先本地改完
2. 本地自验通过
3. git add / commit / push
4. 再到服务器部署
5. 服务器只做：
   - `git pull`
   - `.venv` 语法检查
   - `systemctl restart`
   - HTTP 冒烟

不要做的事：

1. 不要直接在服务器改业务逻辑
2. 不要用系统 Python 编译
3. 不要在服务器上重新跑重型 Foundation 构建
4. 不要只部署页面不部署 API

如果页面依赖新模板或新静态资源，部署时一起同步验证公网入口。

部署后至少确认：

1. `/state-observer` 能打开
2. `/api/state-observer` 返回 200
3. 单只票最近 20 天可查
4. `A/B` 筛选生效
5. `0` 筛选生效

---

### E. 定时任务与运行编排同步实施

目标：确认这次能力是否进入每日自动化链路；如果本轮不进入，也要明确写入延期结论。

必须检查：

1. `config/hermes_cron.json`
2. 是否已有适合复用的导出/预计算脚本
3. 是否需要新增：
   - 预构建 `state_timeline_daily`
   - 定时导出 CSV/HTML
   - 给邮件或站内页面准备缓存产物

硬规则：

1. 本轮如果不接入定时任务，必须在交付说明里明确写：
   - 为什么先不接
   - 现在由什么路径实时查询
   - Phase 2 何时接入 cron
2. 本轮如果接入 cron：
   - 新脚本只能放 `scripts/`
   - 调度只能通过 `config/hermes_cron.json`
   - 不要在 `web/main.py` 里偷偷做重计算
3. 不要为了 Observer 把每日 Foundation 构建链路改成更重
4. 不要把“页面查询能力”和“定时离线产物”混成一套不清楚的逻辑

建议判断口径：

1. 小查询走实时查询
2. 大查询和导出走异步或离线
3. 若后续要发邮件摘要，可在 Phase 2 再接 cron

---

### F. 记忆层与 Agent 协同同步实施

目标：确认 Observer 与记忆层、Agent 层的边界，不破坏现有架构。

必须检查：

1. `outputs/agent_memory/AgentMemory.duckdb`
2. `hermass_platform/`
3. `agently_adapter/`
4. 当前是否已有合适的 Ledger 或观察记录入口

硬规则：

1. Observer Phase 1 首先是查询与展示层，不是新记忆系统
2. 不要把页面查询结果直接写进 `AgentMemory.duckdb` 当成默认行为
3. 不要在 `web/main.py` 里直接新建 Agent 运行逻辑
4. 如果需要给 Agent 层预留消费接口，只做只读、结构化输出
5. 如果你认为需要新增 Observer→Ledger 或 Observer→Agent 的接口，只能先给扩展位或设计说明，除非本轮最小实现真的必须

你需要在交付说明里明确回答：

1. 本轮是否写入记忆层：`是 / 否`
2. 如果否，原因是什么
3. 后续哪些 Agent 可以消费这张时间表
4. 是否需要在 Phase 2 接入 Observation Ledger

---

### G. 注释、文档、规则文档、验收同步实施

目标：代码和文档不能脱节。

必须同步：

1. 必要代码注释
2. API 字段说明
3. 设计稿口径
4. 如验收规则变动，更新对应验收脚本或验收说明
5. 检查是否需要同步项目规则文档，例如：
   - `AGENTS.md`
   - 运行 SOP
   - 部署说明
   - PM 验收说明

关于 `AGENTS.md` 的规则：

1. 只有当本轮引入新的长期固定规则时才修改
2. 如果只是实现一个页面和 API，而不改变全项目长期规则，不要为了“看起来完整”去改 `AGENTS.md`
3. 但必须在交付说明里明确写：
   - 是否需要改 `AGENTS.md`
   - 如果不改，为什么不改
   - 哪些信息只需要留在任务文档或设计文档

最少同步检查：

1. 后端字段名是否和前端使用完全一致
2. 页面筛选项是否和 API 参数完全一致
3. `A/B/0` 是否在文档、代码、页面三处都出现
4. 是否仍有旧口径把首页主统计写成 `ef_count`
5. 是否已经对 cron / memory / 项目规则文档给出明确结论

---

## 三、实施顺序

请严格按顺序执行：

1. 先实现查询层
2. 再实现 API
3. 再实现页面
4. 再检查 cron / memory / 文档规则层影响
5. 再同步注释和文档
6. 再本地验证
7. 再整理变更说明

不要一开始就先做 UI 美化。

---

## 四、本地验收要求

至少完成以下验收：

1. Python 语法检查通过
2. 本地服务可启动
3. API 可返回 JSON
4. 页面可打开
5. `EF / A+B / 0` 三类事件都能筛选
6. `csv` 导出可用
7. 明确说明：
   - 是否接入 cron
   - 是否接入 AgentMemory
   - 是否需要修改 `AGENTS.md`

至少给出这些验收结果：

```bash
cd /Users/lv111101/Documents/hermass-observer-product
.venv/bin/python -m py_compile web/main.py
.venv/bin/python -m py_compile 你修改过的 Python 文件
curl -s "http://localhost:8020/api/state-observer?symbol_set=top50&days=3&page=1&page_size=20" | head -c 1200
curl -s "http://localhost:8020/api/state-observer?symbol_set=top50&days=3&d1_is_ab=1&page=1&page_size=20" | head -c 1200
curl -s "http://localhost:8020/api/state-observer?symbol_set=top50&days=3&d1_is_zero=1&page=1&page_size=20" | head -c 1200
```

---

## 五、交付格式

请按下面格式回复：

1. 改了哪些文件
2. 数据层做了什么
3. API 做了什么
4. 页面做了什么
5. 文档和注释同步了什么
6. cron / memory / `AGENTS.md` 是否需要同步，结论是什么
7. 本地验收结果
8. 哪些留到 Phase 2

如果遇到阻塞，不要泛泛而谈，直接指出：

1. 阻塞文件
2. 阻塞原因
3. 你建议的最小可行替代方案

---

## 三、Codex 复核标准

Codex 会重点审：

1. 是否真的支持任意股票组合与任意时间窗口
2. 是否把 `A/B/0` 都做成正式事件族，而不是临时前端标签
3. 是否仍然偷偷回到了 `ef_count` 主视图
4. 前后端参数和字段是否一一对应
5. 是否对 cron / memory / `AGENTS.md` 给出明确、合理、最小化的结论
6. 本地、数据库、前后端、服务器、定时任务、记忆层、规则文档七层计划是否闭环
7. 是否引入新的交易建议边界风险
