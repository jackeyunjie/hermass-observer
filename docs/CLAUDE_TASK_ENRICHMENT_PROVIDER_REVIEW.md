# Claude Task: Enrichment Provider Review

版本：v1.0  
日期：2026-05-28  
目标：请 Claude Opus 4.7 审阅当前 research enrichment 设计，并只回答 provider 边界与展示层问题

---

## 背景

当前项目是 **A 股专属、Research-Only** 的研究助手系统。  
核心链路已经是：

- `evidence payload`
- `formatter`
- `API / 飞书`

最近新增了一个 **optional enrichment** 层，用来承接未来的联网增强能力，但要求：

- **local evidence first**
- enrichment 只做补充，不替代本地 evidence
- 不生成投资建议 / 目标价 / 评级判断
- 外部补充必须可追溯

目前已落地：

- enrichment skeleton
- enrichment visible status
- 第一个 provider contract:
  - `industry_competition_external_peers`

---

## 请先阅读这些文件

1. `docs/RESEARCH_ENRICHMENT_PROVIDER_CONTRACTS.md`
2. `hermass_platform/research/external_research_enrichment.py`
3. `hermass_platform/research/external_research_formatters.py`
4. `docs/EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md`
5. `docs/COZE_PROMPT_ASSET_PHASE1_PRIORITIES.md`

---

## 你的任务

请只审这 3 个问题：

### 1. Provider contract 是否足够稳定

重点看：

- `industry_competition_external_peers` 的输入/输出 shape 是否够清楚
- `placeholder / local_peer_fields_already_present / ready_for_external_peer_supplement` 这组状态是否合理
- 是否还缺少 1-2 个关键字段，才能支撑后续真实 provider 接入

### 2. 展示层是否应该显示 provider 级状态

当前卡片层已经显示：

- enrichment 总状态
- enrichment policy
- enrichment hints

请判断：

- 是否应该进一步显示 provider 级状态
- 如果要显示，应该显示到 `evidence card`、`deep card`，还是两者都显示
- 显示到什么粒度最合适，既不打扰用户，又能帮助调试

### 3. 下一步最值得做的 provider 是不是它

请只在下面 3 个候选里选优先级：

1. `industry_competition_external_peers`
2. `public_news_digest`
3. `web_search_summary`

要求：

- 结合当前 Hermass 架构
- 结合 A 股 Research-Only 边界
- 结合“本地 evidence 优先”原则

---

## 明确禁止

请不要做这些事：

- 不要把系统改回长篇投研报告路线
- 不要建议直接让外网搜索替代本地 evidence
- 不要引入买入/卖出/目标价/评级生成
- 不要发散到前端或多市场系统
- 不要建议另起平行架构

---

## 期望输出格式

请按以下结构输出：

### A. 总体判断

用 3-6 句话说明当前 enrichment 设计是否成立。

### B. 主要发现

列出 1-5 条，按优先级排序。  
每条必须包含：

- 问题或判断
- 原因
- 建议动作

### C. 是否显示 provider 级状态

明确回答：

- 显示 / 不显示
- 显示到哪张卡
- 用什么最小字段显示

### D. 下一步 provider 优先级

只给出：

1. 第一优先
2. 第二优先
3. 第三优先

每个候选只写 1-3 句理由。

---

## 你要遵守的系统事实

- 当前系统只服务 A 股
- 当前系统是 Research-Only
- `evidence payload` 是主证据层
- enrichment 只能补充，不能覆盖本地 evidence
- formatter 已经有 company / finance / industry 三类增强章节
- `industry_competition_external_peers` 是第一个 provider contract

---

## 一句话目标

请帮助我们判断：

**当前 enrichment provider 设计是否已经足够好，可以继续往真实 provider 接入推进；如果还不够，缺的最关键一刀是什么。**
