# 观象外部工作流接入指南（N8N / Dify / Coze）

## 定位

外部工作流只做**解释扩展、资料整理、导航建议**，不能替代 Hermass 本地数据真相源。

```text
本地规则/本地数据
  -> Agently + DeepSeek（优先）
  -> 外部工作流 webhook（N8N/Dify/Coze/Generic）（fallback）
  -> 明确标注来源与证据支持状态
```

## 已落地组件

| 组件 | 路径 | 职责 |
|------|------|------|
| 桥接层 | `agently_adapter/workflow_bridge.py` | 统一封装 webhook 调用、响应归一化、guardrails 注入 |
| Web fallback | `web/main.py` `_llm_chat_answer()` | Agently 无结果时自动尝试外部工作流 |
| 前端标注 | `web/templates/_ai_assistant.html` | 显示 `外部工作流` / `暂无实际数据支持` |

## 各平台最小工作流设计

### 1. N8N（推荐自托管）

**节点链：**

```text
Webhook (POST) -> Function (guardrails 校验) -> HTTP Request (LLM API 或知识库) -> Function (输出归一化) -> Respond to Webhook
```

**Webhook 节点设置：**
- Method: `POST`
- Path: `hermass-guanxiang`
- Response Mode: `Last Node`

**Function 节点（guardrails 校验）代码片段：**

```javascript
const input = $input.first().json.body || $input.first().json;

// 强制 guardrails
const guardrails = input.guardrails || {};
if (!guardrails.no_trade_execution) {
  return [{ json: { error: "Missing guardrails: no_trade_execution" } }];
}
if (!guardrails.no_position_sizing) {
  return [{ json: { error: "Missing guardrails: no_position_sizing" } }];
}
if (!guardrails.must_disclose_if_no_local_evidence) {
  return [{ json: { error: "Missing guardrails: must_disclose_if_no_local_evidence" } }];
}

// 透传给下游
return [{ json: { query: input.message, context: input.context, contract: input.response_contract } }];
```

**输出归一化 Function 节点：**

```javascript
const upstream = $input.first().json;
const answer = upstream.choices?.[0]?.message?.content || upstream.output || upstream.text || "暂无法回答";

return [{
  json: {
    answer: answer,
    why: "由 N8N 外部工作流返回。",
    multi_cycle_view: "",
    single_cycle_position: "",
    avoid: "不要把外部工作流回答直接当成本地数据结论。",
    next_actions: [],
    sources: ["external_workflow", "workflow_n8n"],
    freshness_note: "外部工作流生成，暂无本地实时数据支持。"
  }
}];
```

### 2. Dify

**应用类型：** Chatflow / Workflow

**开始节点输入变量：**

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `message` | string | 用户原始问题 |
| `query` | string | 同 message，冗余兼容 |
| `context` | object | Hermass 预取的本地上下文（已脱敏） |
| `response_contract` | object | 输出格式契约 |
| `guardrails` | object | 安全约束（必须校验） |

**HTTP 节点（如需调用外部 LLM）：**
- 在 Dify Chatflow 中可直接使用内置 LLM 节点，无需额外 HTTP 节点。

**结束节点输出：**

```json
{
  "answer": "{{#llm.answer#}}",
  "why": "Dify 工作流返回。",
  "multi_cycle_view": "",
  "single_cycle_position": "",
  "avoid": "不要把外部工作流回答直接当成本地数据结论。",
  "next_actions": [],
  "sources": ["external_workflow", "workflow_dify"],
  "freshness_note": "Dify 外部工作流生成，暂无本地实时数据支持。"
}
```

**Dify 发布为 API：**
- 在 Dify 应用 -> 发布 -> 访问 API 中获取 `API Endpoint` 和 `API Secret Key`。
- 配置到 Hermass `.env` 的 `HERMASS_AI_WORKFLOW_URL` / `HERMASS_AI_WORKFLOW_API_KEY`。

### 3. Coze

**Bot 设计：**
- 新建 Bot -> 选择工作流模式。
- 在工作流中添加**开始节点**和**结束节点**。

**开始节点输入：**
- `message` (string)
- `query` (string)
- `context` (object)
- `response_contract` (object)
- `guardrails` (object)

**工作流中的 LLM 节点提示词模板：**

```
用户问题：{{start.message}}
上下文：{{start.context}}
约束：
- 只做解释、导航、资料整理
- 不做买卖建议、不输出仓位
- 如果问题涉及具体股票/市场判断，必须声明"暂无本地实时数据支持"

请按以下 JSON 格式输出：
{
  "answer": "你的回答",
  "why": "简要说明",
  "multi_cycle_view": "",
  "single_cycle_position": "",
  "avoid": "不要把外部工作流回答直接当成本地数据结论。",
  "next_actions": [],
  "sources": ["external_workflow", "workflow_coze"],
  "freshness_note": "Coze 外部工作流生成，暂无本地实时数据支持。"
}
```

**发布与 webhook：**
- Coze 发布为 API Bot，获取 Webhook URL 和 Token。
- 若 Coze 返回的是嵌套 JSON（如 `{"data": {...}}`），`workflow_bridge.py` 的 `_pick_response_object` 已兼容。

## 部署清单

1. 选择平台（N8N / Dify / Coze / Generic）。
2. 按上方最小工作流模板搭建。
3. 获取 webhook URL 和 API Key。
4. 配置 Hermass `.env`（见 `docs/workflow/.env.workflow.example`）。
5. 重启 Hermass 服务。
6. 用 `docs/workflow/webhook_contract.md` 中的 curl 样例做一次冒烟测试。
7. 在浏览器端打开观象，勾选"更自然的解释"，验证来源标注。

## 安全红线

- 外部工作流 URL 必须 HTTPS。
- API Key 不要提交到 Git（使用 `.env` 或环境变量）。
- `guardrails.no_trade_execution` 必须校验为 `true`，否则拒绝响应。
- 外部工作流不得伪造 `daily_snapshot`、`research_evidence` 等本地源标识。
