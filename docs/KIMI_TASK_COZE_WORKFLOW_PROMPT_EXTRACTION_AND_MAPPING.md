# KIMI 任务：提取 COZE 工作流 Prompt 资产并映射到 Research Response 架构

状态：可执行  
日期：2026-05-28  
适用模型：KIMI  
任务类型：结构提炼 / Prompt 资产整理 / 架构映射  
输入文件：`data/Workflow-TouyanBaogao_Test_panyi_3_3-draft-1335.zip`

---

## 任务目标

不要把这份 COZE 工作流直接转成 Python，也不要尝试原样迁移长篇投研报告系统。

本次任务只做两件事：

1. **提取 COZE 工作流中的 prompt 资产**
2. **把原 8 章节报告结构映射到当前 Hermass 的 external research response 架构**

输出目标是让后续实现可以复用其中“有价值的结构”和“可复用的 prompt”，同时明确哪些部分必须降级或废弃。

---

## 必读文件

执行前先阅读：

1. `README.md`
2. `docs/SYSTEM_ARCHITECTURE.md`
3. `docs/A_SHARE_SERVICE_API.md`
4. `docs/EXTERNAL_RESEARCH_RESPONSE_FRAMEWORK.md`
5. `docs/EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md`
6. `docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md`
7. `docs/LARK_RESEARCH_RESPONSE_ENTRYPOINTS.md`

如需理解当前 research response 实现，再补读：

8. `hermass_platform/research/external_research_evidence.py`
9. `hermass_platform/research/external_research_formatters.py`
10. `hermass_platform/chat/lark_handler.py`

---

## 当前活跃架构事实

以下表述必须严格统一：

- `shared core layer` = `agently_adapter/a_share_core.py`
- `core flow` = `agently_adapter/agently_a_share_flow.py`
- `full compatibility workflow` = `agently_adapter/agently_daily_flow.py`
- `API service layer` = `hermass_platform/api/a_share_service.py`
- `external research evidence layer` = `hermass_platform/research/external_research_evidence.py`
- `external research formatter layer` = `hermass_platform/research/external_research_formatters.py`

---

## 范围限制

1. 系统只服务 A 股。
2. 不引入 MT5 / US / Alpaca 活跃语境。
3. 不修改 State 底座契约。
4. 不把 COZE 工作流原样迁移成新的平行体系。
5. 不直接生成“长篇投资价值报告”方案。
6. 不保留“投资建议 / 目标价 / 评级”作为当前对外主产品语义。
7. 不做 Python 代码实现。
8. 不做 destructive git 操作。

---

## 任务输入

请从这个文件开始：

- `data/Workflow-TouyanBaogao_Test_panyi_3_3-draft-1335.zip`

你需要解压并阅读其中的：

- `MANIFEST.yml`
- `workflow/*.yaml`

并基于 YAML 节点内容完成提炼。

---

## 输出文件

请生成以下两份文档：

1. `docs/COZE_WORKFLOW_PROMPT_CATALOG.md`
2. `docs/COZE_8_SECTION_TO_RESEARCH_RESPONSE_MAPPING.md`

---

## 文档 1 要求：Prompt Catalog

文件：

- `docs/COZE_WORKFLOW_PROMPT_CATALOG.md`

目标：

把 COZE workflow 中**所有关键 LLM 节点的 prompt 资产**整理成可检索目录。

### 必须包含的字段

对每个关键 LLM 节点，至少记录：

- `node_id`
- `node_title`
- `report_section`
- `node_role`
- `input_variables`
- `output_type`
- `prompt_summary`
- `risk_level`
- `keep_or_downgrade_or_discard`

### 风险分级规则

请至少分成三档：

- `low-risk reusable`
- `needs downgrade`
- `should discard`

### 必须特别标记的高风险内容

以下内容必须单独标记：

- 投资建议
- 目标价
- 投资评级
- 明确买入/增持/减持
- 强结论估值判断

### 不要做的事

- 不要把整段 prompt 原文无差别大段复制成文档主体
- 不要只做“节点清单”
- 不要只写摘要，不做风险判断

更好的格式是：

1. 总览表
2. 逐节点摘要
3. 高风险 prompt 专区
4. 可复用 prompt 专区

---

## 文档 2 要求：8 章节映射

文件：

- `docs/COZE_8_SECTION_TO_RESEARCH_RESPONSE_MAPPING.md`

目标：

把原 8 章节投研报告，映射到当前 Hermass 的：

- evidence payload
- quick card
- deep card
- evidence card

### 必须回答的问题

对每一章分别判断：

1. 这一章的核心价值是什么
2. 它更适合进入：
   - `evidence payload`
   - `quick card`
   - `deep card`
   - `evidence card`
   - 还是应被废弃
3. 它在当前架构里应当：
   - `保留`
   - `降级`
   - `拆散`
   - `废弃`
4. 它依赖哪些数据字段
5. 它是否触碰合规高风险边界

### 建议使用的判断标签

请统一使用：

- `keep`
- `downgrade`
- `split`
- `discard`

### 特别要求

以下几个章节必须重点讨论：

- `一、基本结论`
- `六、估值分析`
- `七、市场观点`
- `八、投资建议`

因为这四章最容易与当前 external research response 边界冲突。

---

## 明确的预期结论

如果你的分析是正确的，通常会得出类似方向：

- `公司概况`：可保留，适合 deep card
- `行业分析`：可拆成 deep card 模块
- `公司分析`：可拆成 deep card 模块
- `盈利预测`：可降级为趋势观察或表格型 evidence
- `估值分析`：降级为 `valuation_reference`
- `市场观点`：降级为 `market_views`
- `投资建议`：废弃，不进入对外活跃系统

你可以得出不同细节结论，但不能违背当前 A 股 `Research-Only` 边界。

---

## 严禁输出的方向

本次任务严禁把结论导向：

- “建议把 COZE 工作流完整迁移进 Python”
- “建议恢复长篇投研报告生成”
- “建议保留目标价和评级作为对外输出”
- “建议直接把 ch8 投资建议接到飞书”

这些都与当前架构方向冲突。

---

## 标准输出格式

请按以下格式汇报任务结果：

1. 变更摘要
2. `COZE_WORKFLOW_PROMPT_CATALOG.md` 的核心发现
3. `COZE_8_SECTION_TO_RESEARCH_RESPONSE_MAPPING.md` 的核心结论
4. 哪些 prompt 可直接复用
5. 哪些章节必须降级或废弃
6. 风险或未决点

---

## 推荐执行提示词

```text
你在 hermass-observer-product 仓库中工作。

先阅读以下文件建立架构上下文：
1. README.md
2. docs/SYSTEM_ARCHITECTURE.md
3. docs/A_SHARE_SERVICE_API.md
4. docs/EXTERNAL_RESEARCH_RESPONSE_FRAMEWORK.md
5. docs/EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md
6. docs/LARK_RESEARCH_RESPONSE_ENTRYPOINTS.md

当前活跃系统仅限 A 股，且为 Research-Only。

统一架构事实：
- shared core layer = agently_adapter/a_share_core.py
- core flow = agently_adapter/agently_a_share_flow.py
- full compatibility workflow = agently_adapter/agently_daily_flow.py
- API service layer = hermass_platform/api/a_share_service.py
- external research evidence layer = hermass_platform/research/external_research_evidence.py
- external research formatter layer = hermass_platform/research/external_research_formatters.py

本次任务：
读取 data/Workflow-TouyanBaogao_Test_panyi_3_3-draft-1335.zip，
输出两份文档：
1. docs/COZE_WORKFLOW_PROMPT_CATALOG.md
2. docs/COZE_8_SECTION_TO_RESEARCH_RESPONSE_MAPPING.md

强约束：
- 不转 Python
- 不设计新平行体系
- 不恢复长篇投研报告主线
- 不保留投资建议/目标价/评级为当前对外主语义

输出格式：
1. 变更摘要
2. Prompt Catalog 核心发现
3. 8 章节映射核心结论
4. 可直接复用的 prompt
5. 必须降级或废弃的章节
6. 风险或未决点
```
