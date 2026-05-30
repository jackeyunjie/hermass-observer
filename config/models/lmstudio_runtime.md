# LM Studio Runtime 模板

适用对象：

- LM Studio 本地模型
- 通过 LM Studio OpenAI-compatible 接口访问的模型

---

## 建议加载

1. `config/prompts/local_model_architecture_prompt.md`
2. `config/prompts/runtime_architecture_prompt.md`

如模型上下文足够，再补：

3. `config/deepseek_context.md`

---

## 推荐角色

- 飞书/邮件草稿解释层
- 查询结果改写层
- 研究材料摘要层
- KIMI/Claude 前置草稿层

---

## 不推荐角色

- 最终架构裁决
- git 状态清理决策
- State 公式或 Agent 视角定义修改

---

## 接入检查

接入后确认：

1. 是否明确 A 股 only
2. 是否知道 `a_share_service.py` 是服务边界
3. 是否知道 `agently_daily_flow.py` 不是主线
4. 是否禁止输出交易指令

