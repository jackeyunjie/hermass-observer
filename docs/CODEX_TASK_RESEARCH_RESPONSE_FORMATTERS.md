# Codex 任务：实现 External Research Response Formatters

状态：可执行  
日期：2026-05-28  
适用模型：Codex / KIMI / Claude / 本地模型  
任务类型：实现任务定义  
目标产物：三类 research response formatter（代码 + 最小验证 + 文档同步）

---

## 任务目标

基于：

- [EXTERNAL_RESEARCH_RESPONSE_FRAMEWORK.md](/Users/lv111101/Documents/hermass-observer-product/docs/EXTERNAL_RESEARCH_RESPONSE_FRAMEWORK.md)
- [EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md](/Users/lv111101/Documents/hermass-observer-product/docs/EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md)
- `Phase 1 evidence builder`

实现三类外部研究回答 formatter：

1. 快速问答卡 formatter
2. 深度研究卡 formatter
3. 证据卡 formatter

三个 formatter 必须共享同一个 evidence payload，只允许渲染方式不同，不允许各自发明字段。

---

## 架构边界

必须遵守 Hermass 当前 A 股主架构：

- `shared core layer` = `agently_adapter/a_share_core.py`
- `core flow` = `agently_adapter/agently_a_share_flow.py`
- `full compatibility workflow` = `agently_adapter/agently_daily_flow.py`
- `API service layer` = `hermass_platform/api/a_share_service.py`

本任务实现的是 **research response lane 的 formatting layer**，不是新的核心计算层。

---

## 范围限制

1. 系统只服务 A 股。
2. 不修改 evidence contract 字段名。
3. 不引入 MT5 / US / Alpaca。
4. 不生成买入/卖出/推荐/确定性强结论。
5. 不做长篇卖方报告生成。
6. 不把 formatter 写成 prompt-only 黑盒。
7. 不做前端页面。
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
8. `hermass_platform/chat/response_enricher.py`
9. `Phase 1 evidence builder` 对应实现文件

---

## 实现目标

输入：

- 一份符合 contract 的 evidence payload

输出：

- 快速问答卡文本/结构化块
- 深度研究卡文本/结构化块
- 证据卡文本/结构化块

要求：

1. 三类 formatter 共享同一 evidence 对象
2. formatter 不负责再去拉数据
3. formatter 不负责自行判断数据充分度
4. formatter 必须消费 `completeness` 和 `source_map`

---

## 三类 formatter 的最低要求

### 1. 快速问答卡

定位：

- 飞书群聊 / Bot 快速回复
- 目标是 10 秒级可读结论

必须包含：

- 结论摘要
- 2 到 4 条关键事实
- 数据充分度
- 主要风险
- 免责声明简版

禁止：

- 长段展开
- 复杂估值推导
- 指令化建议

### 2. 深度研究卡

定位：

- 用户追问后的扩展回答

必须包含：

- 结论摘要
- 公司概况
- 财务趋势
- 行业景气 / State 环境
- 风险与限制
- 免责声明

允许：

- 比快速卡更详细
- 使用小标题

但仍然禁止：

- 生成传统长篇研究报告
- 写成“投资建议书”

### 3. 证据卡

定位：

- 给回答提供可追溯依据

必须包含：

- 关键来源摘要
- 最新报告期
- 各模块 completeness
- 交叉验证/来源局限提示

证据卡应优先结构化、少修辞。

---

## Partial / Missing 行为要求

formatter 必须严格使用 contract 规则：

- `sufficient`：正常渲染
- `partial`：保留回答，但显式提示局限
- `missing`：不输出该模块结论，只输出缺失说明

特别要求：

- `valuation_reference` missing 不能让整张卡崩掉
- `strategy_fit_overlay` missing 不得误写成“无 State”
- `market_views` missing 只能写“暂无充分公开市场观点”

---

## 合规要求

必须复用当前对外边界：

- Research-only
- A-share only
- 禁止买入/卖出/推荐类词汇
- 必须带免责声明
- 历史数据不代表未来

如有需要，可复用或扩展：

- `hermass_platform/chat/compliance_filter.py`

但不能绕开合规层直接输出强结论。

---

## 推荐实现路径

可在 `hermass_platform/` 下新增 research response 相关模块，例如：

- `hermass_platform/research/external_research_formatters.py`

或在已有聊天增强路径上增加 formatter 层，但要求：

1. formatter 逻辑可单测
2. 与数据拉取解耦
3. 与飞书渠道解耦

---

## 最小验证

至少完成：

1. 以一份样例 evidence payload 渲染三张卡
2. 验证 `partial` 场景不会输出越界结论
3. 验证 `missing` 模块会被跳过而不是瞎编
4. 验证三类卡片都能显示统一的 `stock_code / stock_name / as_of_date`

---

## 明确不做的事

本任务不做：

- evidence builder 本身
- 飞书路由
- 新 API 接口
- 多轮对话状态管理
- 前端展示页
- PDF / DOCX 报告导出

---

## 验收标准

完成后至少满足：

1. 三类卡片共享同一 evidence payload
2. `completeness` 和 `source_map` 真正参与渲染
3. `partial / missing` 行为与 contract 一致
4. 输出口径符合 external research response framework
5. 没有投资建议式表达

---

## 标准输出格式

执行该任务时，输出必须按以下格式汇报：

1. 变更摘要
2. 新增/修改文件
3. 三类 formatter 结构说明
4. partial/missing 渲染规则说明
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
6. hermass_platform/chat/compliance_filter.py
7. hermass_platform/chat/response_enricher.py
8. Phase 1 evidence builder 对应实现文件

当前活跃系统仅限 A 股。

统一架构事实：
- shared core layer = agently_adapter/a_share_core.py
- core flow = agently_adapter/agently_a_share_flow.py
- full compatibility workflow = agently_adapter/agently_daily_flow.py
- API service layer = hermass_platform/api/a_share_service.py

本次任务：
实现 external research response 的三类 formatter：
1. 快速问答卡
2. 深度研究卡
3. 证据卡

强约束：
- 三类 formatter 共享同一 evidence payload
- formatter 不自行拉数据
- formatter 不自行判断数据充分度
- 必须显式处理 sufficient / partial / missing
- 不输出买入卖出推荐类表达
- 不生成长篇投资报告

输出格式：
1. 变更摘要
2. 新增/修改文件
3. 三类 formatter 结构说明
4. partial/missing 渲染规则说明
5. 最小验证结果
6. 风险或未决点
```
