# Claude 任务：修订 External Research Response Evidence Contract

状态：可执行  
日期：2026-05-28  
适用模型：Claude  
任务类型：设计文档修订  
目标文件：`docs/EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md`

---

## 任务目标

请基于当前版本的：

- [EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md](/Users/lv111101/Documents/hermass-observer-product/docs/EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md)

只做**结构漏洞修订**，不要扩 scope，不要新增大段新需求，不要转向实现细节。

本次修订的目标是让后续：

- `evidence builder`
- `formatter`
- `report_quality_checker`

不会因为 contract 的结构问题而做散。

---

## 必读文件

请先阅读：

1. `docs/EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md`
2. `docs/EXTERNAL_RESEARCH_RESPONSE_FRAMEWORK.md`
3. `docs/SYSTEM_ARCHITECTURE.md`
4. `docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md`
5. `scripts/ifind_fundamental_collector.py`
6. `scripts/akshare_batch_collect.py`

---

## 只修这 4 个问题

### 1. 整体充分度算法错误惩罚 optional 模块

当前问题：

- `valuation_reference`
- `market_views`

在顶层被定义为 optional，但整体充分度算法仍给它们固定权重。

这会导致：

- 核心事实层完整
- 但估值/券商观点缺失

的公司被系统性降分。

#### 修订要求

请把 contract 改成以下任一清晰方案：

方案 A：
- `required_modules_score`
- `optional_modules_score`
- `overall_completeness`

三层分开

方案 B：
- 只对“当前启用且应出现的模块”做归一化加权

无论选哪种，都必须明确：

- optional 模块缺失不能直接拖垮整体 completeness
- required 模块仍然应主导整体 completeness

请在文档中显式写出修订后的计算逻辑，不要只改措辞。

---

### 2. financial_trend 的时间序列 source_map 粒度不够

当前问题：

- `financial_trend` 用数组表示多期数据
- `source_map` 只有 `financial_trend.revenue` 这种粗粒度映射

这无法表达：

- 每个 period 对应哪个报告期
- 是否混用了不同报告期
- 每个值是否来自同一来源

而数据质量的核心规则恰恰是：

- 不能混用 `2024Q3` 和 `2024Q4`

#### 修订要求

请把 contract 改成可追溯的时间序列结构。

可选方向：

方案 A：对象数组

```json
"financial_trend": {
  "period_rows": [
    {
      "report_period": "2022Q4",
      "revenue": 65.2,
      "net_profit": 19.5,
      "eps": 2.39
    }
  ]
}
```

方案 B：保留数组，但 source_map 对每个 period 单独建 key

无论选哪种，都必须满足：

- 每个值可追溯
- 可以检查混期
- 可以检查最新报告期是否一致

并明确：

- `report_period_consistency` 如何定义
- mixed-period 如何标记

---

### 3. state_environment 混入了 strategy overlay，required 边界错误

当前问题：

`state_environment` 里同时包含：

- Foundation 层稳定字段：
  - `mn1_state_hex`
  - `w1_state_hex`
  - `d1_state_hex`
  - `ef_count`

- Strategy overlay 字段：
  - `lifecycle_stage`
  - `strategy_environment_fit`
  - `fit_strategy`

后者来自 `strategy_signal_ledger`，并不保证每只股票每天都有。

当前把它们一起设成 required，会导致：

- 有 State
- 但无策略信号

的股票被误判为 evidence 不完整。

#### 修订要求

请将这部分显式拆开，推荐：

- `state_environment`
  - 只保留 foundation / state core

- `strategy_fit_overlay`
  - 单独模块
  - optional

请明确：

- 哪些字段是 state core
- 哪些字段是 overlay
- 两者各自的 completeness 规则
- 快速卡/深度卡如何消费 overlay 缺失场景

---

### 4. industry_state 的 Phase 1 规则与当前现实冲突

当前问题：

- contract 把 `prosperity_score` 纳入 `sufficient` 条件
- 但文档里又承认 `industry_position` 目前“待填充”

这样会导致 Phase 1 中：

- `industry_state` 几乎永远只能是 `partial`

#### 修订要求

请把 Phase 1 和后续阶段显式区分：

推荐写法：

- Phase 1：
  - `ETF State + ef_count + sector_resonance` 可构成 `sufficient`
  - `prosperity_score` 缺失不直接降为 partial

- Phase 2：
  - 当 `industry_position` 稳定后，再把 `prosperity_score` 纳入更高标准

请在 contract 中把这种“阶段化 completeness 规则”写明，不要留在 Open Question。

---

## 修订输出要求

请不要重写整份文档。  
请在现有文档基础上做**精确修订**，保持原有结构尽量稳定。

你需要输出：

1. 修订后的完整文档内容
2. 一份简短变更摘要

变更摘要必须说明：

- 修改了哪 4 类问题
- 为什么这样改
- 对后续实现的直接影响

---

## 强约束

禁止：

1. 扩展到前端设计
2. 扩展到 API 设计
3. 扩展到长篇报告系统
4. 新增大量 Phase 2/3 范围
5. 把 contract 改成实现方案文档
6. 删除已有的 evidence-first 主方向

---

## 期望效果

修完后应达到：

- completeness 不再错误惩罚 optional 模块
- financial_trend 可以做报告期一致性校验
- state core 与 strategy overlay 边界清楚
- industry_state 的 Phase 1 规则能在当前数据现实下成立

