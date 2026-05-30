# Claude 任务：撰写 External Research Response Evidence Contract

状态：可执行  
日期：2026-05-28  
适用模型：Claude  
任务类型：架构设计文档  
输出目标：`docs/EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md`

---

## 任务背景

当前仓库已经完成：

1. [EXTERNAL_RESEARCH_RESPONSE_FRAMEWORK.md](/Users/lv111101/Documents/hermass-observer-product/docs/EXTERNAL_RESEARCH_RESPONSE_FRAMEWORK.md)
2. [SYSTEM_ARCHITECTURE.md](/Users/lv111101/Documents/hermass-observer-product/docs/SYSTEM_ARCHITECTURE.md)
3. [MODEL_ARCHITECTURE_USAGE_GUIDE.md](/Users/lv111101/Documents/hermass-observer-product/docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md)
4. [A_SHARE_SERVICE_API.md](/Users/lv111101/Documents/hermass-observer-product/docs/A_SHARE_SERVICE_API.md)

现阶段目标不是直接写代码，而是先定义一个**结构化证据合同**，作为后续“快速问答卡 / 深度研究卡 / 证据卡”共享的数据底座。

这个合同文档必须服务于当前 Hermass 主架构：

- `shared core layer = agently_adapter/a_share_core.py`
- `core flow = agently_adapter/agently_a_share_flow.py`
- `full compatibility workflow = agently_adapter/agently_daily_flow.py`
- `API service layer = hermass_platform/api/a_share_service.py`

并且必须符合当前产品边界：

- 系统只服务 A 股
- 对外提供 AI 助手研究回答服务
- 不做常规“投资建议”输出
- 不把长篇投资价值报告作为主产品形态

---

## 核心设计原则

你必须严格按以下三个原则来写：

1. **先做 evidence payload，再做回答**
   不要从回答模板反推字段，而是先定义稳定的结构化证据对象。

2. **数据充分度必须是结构化字段**
   不能让模型自由判断“充足/部分/缺失”，必须写成规则产物。

3. **三类卡片共享同一个 evidence 对象**
   快速问答卡、深度研究卡、证据卡必须消费同一份 evidence payload，只是 formatter 不同。

---

## 必读文件

写作前先阅读以下文件：

1. `README.md`
2. `docs/SYSTEM_ARCHITECTURE.md`
3. `docs/A_SHARE_SERVICE_API.md`
4. `docs/EXTERNAL_RESEARCH_RESPONSE_FRAMEWORK.md`
5. `docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md`
6. `hermass_platform/chat/compliance_filter.py`
7. `scripts/ifind_fundamental_collector.py`
8. `scripts/akshare_batch_collect.py`
9. `data/框架公司投资价值分析报告.md`

如需补充上下文，可参考：

10. `docs/AI_AGENT_TRADING_GUIDE_TEMPLATES.md`

---

## 文档目标

请撰写一份设计文档：

`docs/EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md`

这不是实现文档，不写代码，不写伪 API，不写数据库迁移细节。  
它的任务是：**把 shared evidence object 的合同定清楚。**

---

## 文档必须包含的章节

请严格使用以下结构：

### 1. 目标与适用范围

写清楚：

- 该 contract 服务的是“外部 AI 助手公司研究回答”
- 不服务于传统 10000 字投资报告
- 适用产物：
  - 快速问答卡
  - 深度研究卡
  - 证据卡

### 2. 设计原则

必须明确：

- evidence first
- structured completeness
- one evidence, multiple formatters
- A-share only
- research-only

### 3. 顶层 Schema

请定义 evidence payload 的顶层结构，至少包括：

- `meta`
- `company_profile`
- `financial_trend`
- `industry_state`
- `state_environment`
- `valuation_reference`
- `market_views`
- `risk_flags`
- `source_map`
- `completeness`

对于每个顶层对象，写清楚：

- 职责
- 是否 required
- 是否允许 missing

### 4. 模块级 Schema

请分别展开以下模块：

- `company_profile`
- `financial_trend`
- `industry_state`
- `state_environment`
- `valuation_reference`
- `market_views`
- `risk_flags`

每个模块都必须写清楚：

- 核心字段
- required / optional / nullable
- raw evidence 和 derived evidence 的区别
- 对应的数据来源候选

### 5. Source Map 规范

这是重点章节，必须写细。

要求定义：

- 每个数值字段如何绑定来源
- source map 的最小字段集合

建议至少包含：

- `source_type`
- `source_table`
- `source_field`
- `report_period`
- `updated_at`
- `source_confidence`

并明确：

- `ifind`
- `akshare`
- `foundation`
- `derived`
- `manual`

这五类来源的使用边界。

### 6. 数据充分度规则

这也是重点章节，必须落到规则表。

请定义三档：

- `sufficient`
- `partial`
- `missing`

并按模块分别说明：

- 什么条件下是 `sufficient`
- 什么条件下是 `partial`
- 什么条件下是 `missing`

至少覆盖：

- 公司概况
- 财务趋势
- 行业景气
- State 环境
- 估值参考
- 市场观点
- 风险提示

### 7. Partial / Missing 行为规则

请不要只定义状态，还要定义系统行为。

明确：

- `sufficient` 时回答层可以如何使用
- `partial` 时必须怎样提示用户
- `missing` 时必须禁止输出哪些结论

### 8. 三类卡片共享字段

请单独列一节，定义：

- 快速问答卡
- 深度研究卡
- 证据卡

三者共享哪些字段，哪些字段是扩展字段。

至少要回答：

- 什么字段是三者都必须有的
- 什么字段只在深度研究卡中展开
- 什么字段只在证据卡中显示

### 9. 示例 Payload

必须给一份简化但真实风格的 JSON 示例。

要求：

- 字段名稳定
- 同时出现 `sufficient` / `partial`
- 至少有 1 个 `source_map`
- 至少有 1 个 derived 字段

### 10. Phase 1 实现边界

这节必须写，避免 scope 膨胀。

请明确第一版：

- 要做什么
- 不做什么

建议第一版只覆盖：

- 公司概况
- 财务趋势
- 行业景气
- State 环境
- 风险提示
- 基础 completeness
- 基础 source map

建议第一版不做：

- 复杂估值区间计算
- 主观投资结论
- 大量低稳定性字段
- 复杂自然语言质量评分

---

## 强约束

以下事项禁止：

1. 不要把文档写成“报告模板说明”
2. 不要写成“直接生成长报告”的方案
3. 不要让模型自由判断 completeness
4. 不要把估值分析写成强结论模块
5. 不要引入 MT5 / US / Alpaca 活跃语境
6. 不要写成与现有主架构平行的新体系
7. 不要直接设计前端页面
8. 不要直接写实现代码

---

## 写作风格要求

- 使用中文
- 结构化
- 工程化
- 可直接供后续 Codex 实现使用
- 不空谈，不写泛泛原则
- 所有章节都要尽量落到字段、规则、状态、行为

---

## 期望结果

最终文档应达到这个标准：

- Codex 读完之后，可以直接开始写 `evidence builder`
- 后续做 `report_quality_checker.py` 时，知道该检查什么
- 飞书 Bot / API / formatter 层知道该消费什么字段
- 不需要再重新争论“什么是 sufficient / partial / missing”

---

## Claude 输出要求

请直接生成最终文档内容，不要只给提纲。  
如果存在你认为必须先确认的开放问题，请放在文末 `Open Questions` 一节，数量不超过 5 条。

