# Ollama Runtime 模板

适用对象：

- Ollama 本地模型
- Open WebUI 经由 Ollama 暴露的模型

---

## 建议加载

最小配置：

1. `config/prompts/local_model_architecture_prompt.md`

增强配置：

2. `config/prompts/runtime_architecture_prompt.md`
3. `config/deepseek_context.md`（仅上下文够大时）

---

## 定位

Ollama 本地模型在 Hermass 中优先承担：

- 文档同步
- 机械统一术语
- 查询结果整理
- 研究摘要压缩

不应单独承担：

- State 契约修改
- 架构边界判断
- 跨层重构决策

---

## 一句话规则

> 本地模型只做低风险解释和整理，不重定义 Hermass 主架构。

