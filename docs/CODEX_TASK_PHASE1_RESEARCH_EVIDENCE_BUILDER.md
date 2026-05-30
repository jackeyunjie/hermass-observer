# Codex 任务：实现 Phase 1 External Research Evidence Builder

状态：可执行  
日期：2026-05-28  
适用模型：Codex / KIMI / Claude / 本地模型  
任务类型：实现任务定义  
目标产物：Phase 1 research evidence builder（代码 + 最小验证 + 文档同步）

---

## 任务目标

基于：

- [EXTERNAL_RESEARCH_RESPONSE_FRAMEWORK.md](/Users/lv111101/Documents/hermass-observer-product/docs/EXTERNAL_RESEARCH_RESPONSE_FRAMEWORK.md)
- [EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md](/Users/lv111101/Documents/hermass-observer-product/docs/EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md)
- [SYSTEM_ARCHITECTURE.md](/Users/lv111101/Documents/hermass-observer-product/docs/SYSTEM_ARCHITECTURE.md)
- [A_SHARE_SERVICE_API.md](/Users/lv111101/Documents/hermass-observer-product/docs/A_SHARE_SERVICE_API.md)

实现一个 **Phase 1 external research evidence builder**，为三类外部研究回答卡片提供共享 evidence payload：

- 快速问答卡
- 深度研究卡
- 证据卡

这不是长报告生成器，不做前端，不做投资建议，不做估值强结论。

---

## 架构边界

必须遵守 Hermass 当前 A 股主架构：

- `shared core layer` = `agently_adapter/a_share_core.py`
- `core flow` = `agently_adapter/agently_a_share_flow.py`
- `full compatibility workflow` = `agently_adapter/agently_daily_flow.py`
- `API service layer` = `hermass_platform/api/a_share_service.py`

本任务实现的是 **research response lane 的 shared evidence layer**，不能另起一套与当前架构平行的系统。

允许参考的现有文件：

- `scripts/fundamental_evidence_schema.py`
- `scripts/build_strategy_evidence.py`
- `scripts/daily_research_brief.py`
- `scripts/build_stock_research_ledger.py`
- `hermass_platform/chat/response_enricher.py`

---

## 范围限制

1. 系统只服务 A 股。
2. 不引入 MT5 / US / Alpaca 活跃语境。
3. 不修改 State 底座契约。
4. 不把 shell 脚本写成长期主入口。
5. 不把 evidence builder 写成聊天 prompt 逻辑。
6. 不直接生成长篇报告正文。
7. 不做数据库 schema migration。
8. 不做破坏性 git 操作。

---

## 必读文件

实现前先阅读：

1. `README.md`
2. `docs/SYSTEM_ARCHITECTURE.md`
3. `docs/A_SHARE_SERVICE_API.md`
4. `docs/EXTERNAL_RESEARCH_RESPONSE_FRAMEWORK.md`
5. `docs/EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md`
6. `docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md`
7. `hermass_platform/chat/compliance_filter.py`
8. `agently_adapter/a_share_core.py`
9. `scripts/fundamental_evidence_schema.py`
10. `scripts/build_strategy_evidence.py`
11. `scripts/akshare_batch_collect.py`
12. `scripts/ifind_fundamental_collector.py`

---

## Phase 1 实现目标

实现一个共享 evidence builder，输入：

- `stock_code`
- `as_of_date`

输出一份符合 contract 的 evidence payload，至少覆盖：

- `meta`
- `company_profile`
- `financial_trend`
- `industry_state`
- `state_core`
- `strategy_fit_overlay`
- `risk_flags`
- `source_map`
- `completeness`

以下模块在 Phase 1 中允许是 `optional / partial`：

- `valuation_reference`
- `market_views`

---

## 推荐实现路径

优先复用现有目录，不新造大平行体系。

推荐实现方式之一：

- 在 `hermass_platform/` 下新增一个 research 相关模块，例如：
  - `hermass_platform/research/external_research_evidence.py`
  - `hermass_platform/research/external_research_completeness.py`

如果团队更倾向放在 `scripts/` 先做验证版，也可以先落：

- `scripts/build_external_research_evidence.py`

但必须满足：

1. builder 是结构化代码层，不是 prompt 层
2. 后续可被 API / Bot / formatter 复用
3. 不和 `a_share_core.py` 的职责冲突

---

## 必须实现的能力

### 1. Evidence builder 主入口

提供一个稳定入口，例如：

- `build_external_research_evidence(stock_code, as_of_date, ...)`

要求：

- 返回 Python `dict`
- 字段名与 contract 对齐
- 不返回自由文本结论

### 2. Source map 生成

每个关键字段必须能追溯来源，至少包括：

- `source_type`
- `source_table`
- `source_field`
- `report_period`
- `updated_at`
- `source_confidence`

时间序列字段必须按 contract 使用逐期 key，不允许回退到粗粒度：

- 正确：`financial_trend.period_rows[2024Q4].revenue`
- 禁止：`financial_trend.revenue`

### 3. Completeness 判定

必须按 contract 输出：

- 模块级 `sufficient / partial / missing`
- 整体 completeness

要求：

- 由规则产出
- 不允许把“数据充分度”交给模型自由判断

### 4. Phase 1 现实边界

必须显式遵守当前 contract 的 Phase 1 边界：

- `industry_state` 以 ETF State 路径即可满足 Phase 1
- `state_core` 为 required
- `strategy_fit_overlay` 为 optional
- `valuation_reference` 和 `market_views` 不可拖垮 required layer

### 5. 最小验证

至少给一个最小 smoke path：

- 指定单只 A 股
- 指定 `as_of_date`
- 输出 JSON evidence
- 检查顶层字段齐全
- 检查 source map key 命名正确

---

## 明确不做的事

Phase 1 不做：

- 飞书问答接入
- 新 API 路由
- 大模型文案生成
- 长篇报告导出
- 估值计算器
- 市场观点抓取系统
- 跨市场扩展

---

## 验收标准

完成后至少满足：

1. 可以对单只股票生成一份 contract 对齐的 evidence payload
2. `state_core` 与 `strategy_fit_overlay` 不混淆
3. `financial_trend` 使用 `period_rows`
4. `source_map` 为逐期可追溯模型
5. `completeness` 由规则产出
6. 可区分 `required modules score` 与 `optional modules score`
7. 代码可被后续 formatter 直接复用

---

## 标准输出格式

执行该任务时，输出必须按以下格式汇报：

1. 变更摘要
2. 新增/修改文件
3. evidence builder 主入口说明
4. completeness 规则落地说明
5. 最小验证结果
6. 风险或未决点

---

## 推荐执行提示词

```text
你在 hermass-observer-product 仓库中工作。

先阅读以下文件建立上下文：
1. README.md
2. docs/SYSTEM_ARCHITECTURE.md
3. docs/A_SHARE_SERVICE_API.md
4. docs/EXTERNAL_RESEARCH_RESPONSE_FRAMEWORK.md
5. docs/EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md
6. docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md
7. agently_adapter/a_share_core.py
8. scripts/fundamental_evidence_schema.py
9. scripts/build_strategy_evidence.py

当前活跃系统仅限 A 股。

统一架构事实：
- shared core layer = agently_adapter/a_share_core.py
- core flow = agently_adapter/agently_a_share_flow.py
- full compatibility workflow = agently_adapter/agently_daily_flow.py
- API service layer = hermass_platform/api/a_share_service.py

本次任务：
实现 Phase 1 external research evidence builder，生成符合 docs/EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md 的 evidence payload。

强约束：
- evidence first，不先做 formatter
- 数据充分度必须由规则产出
- financial_trend 必须使用 period_rows
- source_map 必须逐期可追溯
- state_core 和 strategy_fit_overlay 必须解耦
- 不写前端，不写长篇报告生成
- 不引入 MT5/US/Alpaca

输出格式：
1. 变更摘要
2. 新增/修改文件
3. evidence builder 主入口说明
4. completeness 规则落地说明
5. 最小验证结果
6. 风险或未决点
```
