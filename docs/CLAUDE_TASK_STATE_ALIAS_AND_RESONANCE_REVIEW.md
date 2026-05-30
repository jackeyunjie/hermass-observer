# Claude Task — State Alias And Resonance Review

版本：v1.0  
日期：2026-05-28  
执行对象：Claude  
目标：只审阅两个窄问题，不扩 scope

---

## 0. 任务定位

你在仓库 `hermass-observer-product` 中工作。

当前系统边界已经明确：

- A 股 only
- Research-Only
- `shared core layer` / `core flow` / `full compatibility workflow` 已分层
- external research response 已经基于 `evidence -> formatter -> API/飞书` 主线运行

本次任务**不是**重新设计系统，不是恢复长篇报告工作流，也不是讨论底层 State 公式。

本次任务只允许审阅这两个规范：

1. `docs/STATE_DISPLAY_ALIAS_SPEC.md`
2. `docs/MARKET_PERSISTENCE_AND_MULTIFACTOR_RESONANCE_SPEC.md`

---

## 1. 必须遵守的边界

### 1.1 允许讨论

- `State` 的前台展示别名是否自然、是否有歧义
- raw state 与 display alias 的分层是否合理
- 结构解读模板是否稳定、是否过度主观
- “市场状态持续多久”应不应该进入前台解释层
- “多因素共振”当前 5 维框架是否足够
- 行业驱动 / 事件驱动在当前 research lane 中的位置是否合理

### 1.2 禁止讨论

- 不讨论修改 `state_score` / `state_hex` / `ef_count`
- 不讨论改写 `STATE_BASE_CONTRACT.md`
- 不讨论恢复 8 大章节长报告主线
- 不讨论引入买卖建议、评级、目标价输出
- 不讨论美股/MT5/Alpaca
- 不讨论重建另一套平行架构

---

## 2. 你需要阅读的文件

请阅读并仅围绕以下文件审阅：

### 核心规范

- `docs/STATE_DISPLAY_ALIAS_SPEC.md`
- `docs/MARKET_PERSISTENCE_AND_MULTIFACTOR_RESONANCE_SPEC.md`

### 必要上下文

- `docs/STATE_BASE_CONTRACT.md`
- `docs/EXTERNAL_RESEARCH_RESPONSE_FRAMEWORK.md`
- `docs/EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md`
- `docs/RESEARCH_ENRICHMENT_PROVIDER_CONTRACTS.md`
- `docs/RESEARCH_RENDER_PROFILE_SPEC.md`

---

## 3. 你要回答的两个问题

### 问题 A：State 展示别名是否合理

请评审：

1. `E/F/C/0/-C` 这种别名设计是否自然
2. “结构语义”是否优于“牛/熊/强/弱”这类定性词
3. `State：E/E/F + 结构解读` 的前台形式是否合适
4. 哪些卡片该显示 raw state，哪些卡片该显示 alias
5. 是否有会让用户误解成买卖建议的表达

重点是：

- 不要改 raw state
- 只讨论 display alias 是否够好

### 问题 B：市场持续度与多因素共振框架是否够窄够稳

请评审：

1. `market_phase + duration + pool_size/change + release_density + dispersion` 这组持续度指标是否过多
2. 当前 5 维共振框架是否合理：
   - State 共振
   - 行业共振
   - 龙头属性
   - 盈利共振
   - 事件驱动
3. 行业驱动放 `industry_state`、事件驱动放 `public_news_digest` 是否正确
4. 是否还需要补一个非常关键但当前缺失的维度
5. 是否会不小心把系统重新带回“长报告分析框架”

重点是：

- 框架要“够用”，不要变成大全套
- 不要建议恢复 8 大章节主线

---

## 4. 输出格式

请只输出以下结构：

### 4.1 总体判断

两段以内：

- `State alias` 是否基本可用
- `market persistence + multifactor resonance` 是否适合作为下一阶段解释层框架

### 4.2 Findings

按严重程度排序，使用这个格式：

```text
1. [severity] 文件:行号
   问题：
   建议：
```

severity 只允许：

- `high`
- `medium`
- `low`

### 4.3 Keep / Adjust / Avoid

请分别列出：

- `Keep`：当前规范里应该保留的点
- `Adjust`：建议微调的点
- `Avoid`：明确不要做的点

### 4.4 One-line Recommendation

最后只给一句：

```text
下一步最值得做的是：...
```

---

## 5. 重要提醒

你不是在设计一个新系统，你是在评审两个展示/解释层规范。

你最重要的责任是：

- 帮我们发现歧义
- 防止展示层措辞越界
- 防止“市场解释层”重新长成旧报告体系

不是：

- 重开底层架构讨论
- 重新设计 State
- 提议恢复 8 大章节长报告

