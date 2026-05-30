# Coze 价值 Prompt 接入说明

版本：v1.1  
日期：2026-05-30  
范围：Hermass `value research` / `观象价值分析增强`

## 结论

当前网站里的 `价值组合` 视图，原来主要依赖：

- `external_research_evidence`
- `external_research_formatters`
- 本地结构化字段

它可以工作，但如果不接入过去 Coze 工作流里的专业输出提示词，确实容易显得：

- 结构化但偏硬
- 信息完整但不够像资深投研写出来的东西

因此，这次把 Coze 工作流中 **可复用、低风险、研究型** 的输出提示词资产，整理为：

- [config/prompts/coze_value_research_prompt_pack.md](/Users/lv111101/Documents/hermass-observer-product/config/prompts/coze_value_research_prompt_pack.md)

## 当前状态

### 已完成

1. 找出 Coze 工作流里真正高价值的研究型输出提示词
2. 按模块拆出可复用 prompt
3. 明确哪些模块不能进前台主链
4. 把部分专业表达骨架吸收到当前 formatter
5. 根据定向审计修复 Prompt Pack：
   - 补入 `175309` 的共享信源分级与数据清洗约束
   - 去掉 `191966` 中“兑现度”这类投资语境
   - 统一 Role 口径，去掉买方/卖方/分析师头衔
   - 恢复 `165674` / `181473` 的筛选逻辑，而不是只留空标题

### 尚未完成

1. `观象` 在“价值分析”场景下还没直接调用这份 prompt pack
2. `/research?render_profile=value` 仍主要是 formatter 输出，不是 LLM 提示词增强输出
3. 这批 Prompt 还没有真正接到线上价值分析增强链路，只完成了资产整理与接入规则澄清

## 接入优先级

### Phase 1：优先作为增强解释资产

适合先接：

- `观象` 的“价值分析看 XXX”回答
- 研究页 AI 总结卡中的价值分析扩展

原因：

- 风险低
- 不改变主链
- 可以让解释更像专业研究写作

### Phase 2：作为 value render 的可选增强层

后续可增加：

- `render_profile=value_llm`

规则：

- 默认仍是结构化 `value`
- `value_llm` 才使用 prompt pack + 平台托管模型增强
- 缺 key / 失败时回退 `value`

## 明确不接入的内容

这些虽然在 Coze 工作流里存在，但当前禁止进入前台：

- 目标价
- 合理估值计算
- 买入 / 增持 / 减持
- 盈利预测结论
- 投资建议
- 交易级 Alpha 机会

## 推荐接法

### 对观象

当用户问：

- `用价值分析看 000021`
- `对 000021 做深度价值分析`
- `用八大块分析这只票`

流程：

1. 先走现有股票识别与 session context
2. 读取 `coze_value_research_prompt_pack.md`
3. 选择对应模块 prompt：
   - 行业
   - 商业模式
   - 财务健康
   - 治理观察
   - 公开市场观点
4. 用平台托管模型增强生成解释
5. 仍按现有 JSON 合同回包

### 对 research value 页面

短期：

- 继续保留 formatter 主链
- 不直接改成 LLM 渲染

中期：

- 在顶部增加一个“价值解释增强”卡片
- 使用这份 prompt pack 生成 4-6 段人话说明
- 下面仍展示结构化 value card

## 推荐顺序

1. 先让 `观象` 的价值分析回答接入这份 prompt pack
2. 再决定是否把 `render_profile=value` 做成可选增强版
3. 不要先改整页渲染

一句话：

**Coze 的价值不在于恢复 8 大块长报告，而在于把那些真正专业的“输出提示词”重新变成 Hermass 里的解释层资产。**
