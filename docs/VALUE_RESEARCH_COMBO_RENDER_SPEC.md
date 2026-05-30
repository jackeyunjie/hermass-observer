# Value Research Combo Render Spec

版本：v1.0  
日期：2026-05-30  
范围：Hermass `/research` 价值组合输出

## 目标

当用户明确要求“对个股进行深度价值分析”时，系统不恢复传统 8 大章节长报告，而是在现有 `external_research_evidence -> formatter -> /research` 主链中，按合规边界组合输出一张 **价值研究组合卡**。

这个输出的定位是：

- 服务深度研究阅读
- 强化行业 / 公司 / 财务 / 估值参考的组合阅读
- 保留 Hermass 的多周期 State 底座
- 不进入投资建议、目标价、盈利预测、仓位建议

## 入口

- 页面：`/research?stock_code=...&render_profile=value`
- API：`POST /research/card/deep` with `render_profile=value`

## 输出结构

### 1. 研究说明

- 说明当前不是恢复 8 大块长报告
- 说明当前输出是“拆散保留 + 降级保留”的组合版
- 保留 State 组合与结构解读作为底座

### 2. 公司概况

来源：
- `evidence.company_profile`

### 3. 行业分析（拆散保留）

来源：
- `evidence.industry_state`
- 本地行业/ETF/共振数据

包含：
- 产业链与竞争格局
- 短期增速与驱动因素
- 政策环境与技术变革
- 行业周期与整体判断

### 4. 公司分析（拆散保留）

来源：
- `evidence.company_profile`
- `evidence.financial_trend`
- `evidence.market_views`

包含：
- 商业模式与核心竞争力
- 发展前景与增长线索
- 盈利质量与财务健康
- 管理与治理观察（降级弱观察）
- 事件观察（替代“催化剂”）

### 5. 盈利趋势观察（非预测）

来源：
- `evidence.financial_trend`

说明：
- 只描述历史趋势
- 明确写“非预测”

### 6. 估值参考（非结论）

来源：
- `evidence.valuation_reference`

说明：
- 只做参考
- 不输出合理估值 / 目标价 / 买卖建议

### 7. 市场预期（公开信息）

来源：
- `evidence.market_views`

说明：
- 只展示公开市场覆盖与机构关注点
- 不把券商观点当系统观点

### 8. 风险与限制

来源：
- `evidence.risk_flags`
- `evidence.completeness`
- `source_map`

## 与原 8 大块的映射

| 原章节 | 处理方式 | 当前输出位置 |
|--------|----------|--------------|
| 一、基本结论 | discard | 不单独输出 |
| 二、公司概况 | keep | 公司概况 |
| 三、行业分析 | split | 行业分析组合 |
| 四、公司分析 | split | 公司分析组合 |
| 五、盈利预测 | downgrade | 盈利趋势观察（非预测） |
| 六、估值分析 | downgrade | 估值参考（非结论） |
| 七、市场观点 | downgrade | 市场预期（公开信息） |
| 八、投资建议 | discard | 不输出 |

## 关键边界

必须保留：

- 多周期 State
- 单周期位置
- 数据来源
- 风险与限制

必须避免：

- 投资建议
- 目标价
- 合理估值计算
- 未来盈利预测
- “推荐/回避/买入/卖出” 评级语气

## 与现有 render profile 的关系

- `standard`：中等展开，研究默认模式
- `full`：完整展开，偏结构化证据阅读
- `value`：价值投研组合阅读模式

一句话：

**`value` 不是更长的 `full`，而是更偏“价值研究框架组合”的阅读视角。**
