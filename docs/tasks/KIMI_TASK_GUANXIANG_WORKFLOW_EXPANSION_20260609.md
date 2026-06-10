# Kimi 任务：观象接入 N8N / Dify / Coze 工作流扩展

## 背景

观象目前对很多开放问题无法回答，且容易让用户误以为回答有本地数据支撑。现已补入最小桥接层：

- `agently_adapter/workflow_bridge.py`
- `web/main.py` 中 `_llm_chat_answer()` 在 Agently 无结果时尝试外部 workflow fallback
- 前端 `_ai_assistant.html` 会显示 `support_note` / `data_support`

硬边界：

- 外部工作流只能做解释扩展、资料整理、导航建议。
- 不能替代 `AgentMemory.duckdb`、State Cube、Hermass 本地数据真相源。
- 外部返回必须标明是否有本地数据证据。没有证据时明确显示“暂无实际数据支持”。
- 不做买卖建议，不自动交易，不输出仓位建议。

## 目标

把观象回答范围扩展到 N8N、Dify、Coze 等工作流，但保持 Hermass 本地事实优先：

```text
本地规则/本地数据
  -> Agently + DeepSeek
  -> 外部工作流 webhook（N8N/Dify/Coze/Generic）
  -> 明确标注来源与证据支持状态
```

## 环境变量合同

当前桥接层读取：

```bash
HERMASS_AI_WORKFLOW_PROVIDER=n8n|dify|coze|generic
HERMASS_AI_WORKFLOW_URL=https://...
HERMASS_AI_WORKFLOW_API_KEY=...
HERMASS_AI_WORKFLOW_AUTH_HEADER=Authorization
HERMASS_AI_WORKFLOW_AUTH_SCHEME=Bearer
HERMASS_AI_WORKFLOW_TIMEOUT_SEC=12
```

## 你要做

1. 设计并部署一个最小 N8N/Dify/Coze 工作流。
2. 输入接受 `message`、`query`、`context`、`response_contract`、`guardrails`。
3. 输出必须兼容以下 JSON：

```json
{
  "answer": "string",
  "why": "string",
  "multi_cycle_view": "string",
  "single_cycle_position": "string",
  "avoid": "string",
  "next_actions": [{"label": "string", "url": "string"}],
  "sources": ["external_workflow"],
  "freshness_note": "string"
}
```

4. 如果工作流没有读取 Hermass 本地证据，`sources` 不要伪造 `daily_snapshot`、`research_evidence` 等本地源。
5. 把工作流 URL 和鉴权方式整理成 `.env` 部署说明，不要提交真实密钥。
6. 设计至少 8 个覆盖问题：
   - 泛问题：“你能帮我做什么”
   - 市场问题：“现在能不能做”
   - 行业问题：“今天先看什么方向”
   - 个股问题：“000021 怎么看”
   - 基本面问题：“用价值分析看 000021”
   - 教学问题：“什么是 State E/F”
   - 导航问题：“我应该先去哪页”
   - 无本地数据问题：“解释一下某个新行业概念”

## 验收

本地执行：

```bash
.venv/bin/python -m pytest tests/unit/test_workflow_bridge.py tests/unit/test_chat_query_fallback.py
.venv/bin/python -m py_compile web/main.py agently_adapter/workflow_bridge.py
```

浏览器验收：

1. 打开任意页面的“观象”。
2. 勾选“更自然的解释”。
3. 问一个本地规则无法覆盖的问题。
4. 页面必须显示“外部工作流”。
5. 如果未使用本地证据，必须显示“暂无实际数据支持”。

## 交付物

- 工作流平台配置说明。
- webhook 输入/输出样例。
- `.env` 变量说明。
- 测试截图或 curl 验收输出。
- 不要提交真实 API key。
