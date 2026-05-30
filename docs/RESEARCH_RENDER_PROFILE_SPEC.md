# Research Render Profile Spec

版本：v1.0  
日期：2026-05-28  
范围：A 股 External Research Response / formatter layer

---

## 目标

本规范定义研究回答的**展示策略层**，而不是证据层。

它回答的问题是：

- 这次回答要展开到什么程度
- 哪些 evidence 模块必须激活
- 每种回答的最低质量要求是什么

它**不**定义：

- core evidence schema
- source_map
- completeness 计算

一句话：

**`research_depth` 属于 render profile，不属于 evidence contract。**

---

## 1. 分层原则

当前主链保持：

```text
evidence payload
  -> render profile
  -> formatter
  -> API / 飞书
```

其中：

- evidence 负责“有什么证据”
- render profile 负责“这次怎么展开”
- formatter 负责“怎么组织成回答”

---

## 2. Render Profiles

### 2.1 `quick`

适用场景：

- 飞书群聊
- “XX 怎么样”
- 需要 10 秒内返回的轻回答

**必须激活模块**

- `company_profile`
- `state_core`
- `risk_flags`

**可选模块**

- `industry_state`
- `strategy_fit_overlay`

**默认输出形态**

- `quick_research_card`

**最低质量要求**

- 必须回答公司做什么
- 必须回答当前 State 环境
- 必须给出至少 1 个风险提示
- 必须给出整体数据充分度

---

### 2.2 `standard`

适用场景：

- 普通个股研究回答
- API 默认详细模式
- 飞书一问一答中的中等展开

**必须激活模块**

- `company_profile`
- `financial_trend`
- `industry_state`
- `state_core`
- `risk_flags`

**可选模块**

- `strategy_fit_overlay`
- `valuation_reference`
- `market_views`

**默认输出形态**

- `deep_research_card` 的标准版

**最低质量要求**

- `financial_trend.period_rows >= 2`
- 风险类别至少覆盖 2 类
- 必须包含行业景气或 ETF State
- 必须包含数据来源摘要

---

### 2.3 `full`

适用场景：

- “深度分析 XX”
- 用户明确要求完整研究卡
- 后续按需追问时的增强模式

**必须激活模块**

- `company_profile`
- `financial_trend`
- `industry_state`
- `state_core`
- `risk_flags`

**优先激活模块**

- `strategy_fit_overlay`
- `valuation_reference`
- `market_views`
- `enrichment`

**默认输出形态**

- `deep_research_card` 的完全展开版
- 必要时叠加 `evidence_card`

**最低质量要求**

- `financial_trend.period_rows >= 3`
- 风险类别至少覆盖 3 类
- 必须包含行业景气 + ETF State + 板块共振（若有）
- 必须包含竞争格局或 peer 覆盖说明
- 若启用 enrichment，必须显示 enrichment 状态

---

## 3. 当前模块映射

### `quick` 推荐模块

- 公司概况摘要
- State 组合
- 核心风险
- 数据充分度

### `standard` 推荐模块

- 公司概况
- 财务趋势
- 行业景气 / State 环境
- 风险与限制

### `full` 推荐模块

- 公司概况
- 商业模式与核心竞争力
- 财务趋势
- 盈利质量与财务健康
- 行业景气 / State 环境
- 产业链与竞争格局
- 估值参考
- 券商观点（若有）
- enrichment 状态
- 风险与限制

---

## 4. 与当前实现的关系

当前代码已经具备这些模块：

- `quick_research_card`
- `deep_research_card`
- `evidence_card`

当前 `deep_research_card` 实际上更接近：

- `standard` 到 `full` 之间的混合版本

后续演进建议：

1. 保持当前默认 deep card 不变
2. 新增一个显式 `render_profile` 参数
3. 由 formatter 根据 `quick / standard / full` 决定章节展开粒度

---

## 5. 参数建议

未来如果要把 render profile 暴露到 CLI / API，建议使用：

```text
render_profile=quick
render_profile=standard
render_profile=full
```

而不是：

```text
research_depth=...
```

原因：

- `render_profile` 更明确地表达“展示策略”
- 避免和 evidence completeness / quality depth 混淆

---

## 6. 与 evidence contract 的边界

### evidence contract 应继续负责

- 模块 schema
- source_map
- completeness
- raw / derived 区分

### render profile 应负责

- 模块激活范围
- 最低展示要求
- 不同场景的展开粒度

---

## 7. 当前结论

对 Claude 提到的“高度 / 深度 / 宽度”，当前最合理的吸收方式是：

- 不改 `EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md`
- 不把 `research_depth` 写进 evidence payload
- 新增 `RESEARCH_RENDER_PROFILE_SPEC.md`
- 后续把 `quick / standard / full` 接到 formatter / API 参数层

---

## 一句话总结

**深度研究不是写更长，而是激活更多 evidence 模块。**  
但这个控制器属于 render profile，而不属于 core evidence。
