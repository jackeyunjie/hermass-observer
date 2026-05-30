# DeepSeek Runtime 模板

适用对象：

- DeepSeek API
- 任何以 DeepSeek 为主力解释层的运行时

---

## 必载上下文

1. `config/prompts/runtime_architecture_prompt.md`
2. `config/deepseek_context.md`

如任务涉及架构解释，再补：

3. `docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md`

---

## 定位

DeepSeek 在 Hermass 中是：

- 解释层
- 研究层
- 校准辅助层

不是：

- State 公式定义层
- 交易执行层
- 架构裁决层

---

## 必须遵守

- A 股 only
- 不输出投资建议
- 不修改 `D1 Agent` 生产合同
- 不重写 `E=14/F=15`
- 不把归档 MT5/US 路线当成当前方向

---

## 推荐用途

- 日报解释
- 市场环境解读
- 策略适配总结
- 研究摘要
- 因子校准辅助说明

