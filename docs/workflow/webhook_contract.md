# 观象外部工作流 Webhook 输入/输出合同

## 输入（POST body）

```json
{
  "message": "你能帮我做什么",
  "query": "你能帮我做什么",
  "context": {
    "user_type": "执行型",
    "current_page": "/",
    "symbol": "",
    "mode": "chat",
    "recent_topics": [],
    "recent_stock_codes": [],
    "user_focus": "",
    "market_data": { "phase": "observe" }
  },
  "response_contract": {
    "answer": "string",
    "why": "string",
    "multi_cycle_view": "string",
    "single_cycle_position": "string",
    "avoid": "string",
    "next_actions": [{"label": "string", "url": "string"}],
    "sources": ["string"],
    "freshness_note": "string"
  },
  "guardrails": {
    "research_only": true,
    "no_trade_execution": true,
    "no_position_sizing": true,
    "must_disclose_if_no_local_evidence": true
  }
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | string | 是 | 用户原始输入 |
| `query` | string | 是 | 同 message，冗余兼容 |
| `context` | object | 否 | Hermass 预取的本地上下文（已脱敏、截断） |
| `response_contract` | object | 否 | 输出格式契约提示，工作流可参考但非强制按此 schema |
| `guardrails` | object | 是 | 安全约束，工作流应校验并遵守 |

### context 脱敏规则

`workflow_bridge.py` 在发送前会执行 `_compact`：
- 移除 `api_key`、`token`、`password`、`secret` 字段。
- 字典最多 60 个键，列表最多 60 个元素。
- 字符串截断到 5000 字符。
- 嵌套深度超过 4 层标记为 `<truncated>`。

## 输出（HTTP 200 JSON）

### 标准格式

```json
{
  "answer": "我是观象，可以帮你查看市场状态、行业方向、个股多周期分析和价值投研。",
  "why": "命中通用介绍意图。",
  "multi_cycle_view": "",
  "single_cycle_position": "",
  "avoid": "外部工作流回答仅供参考，不构成投资建议。",
  "next_actions": [
    {"label": "打开首页", "url": "/"},
    {"label": "查看自选", "url": "/watchlist"}
  ],
  "sources": ["external_workflow", "workflow_n8n"],
  "freshness_note": "外部工作流生成，暂无本地实时数据支持。"
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `answer` | string | **是** | 主回答内容，空字符串会被视为无效响应 |
| `why` | string | 否 | 回答依据简述 |
| `multi_cycle_view` | string | 否 | 多周期视角简述 |
| `single_cycle_position` | string | 否 | 单周期位置简述 |
| `avoid` | string | 否 | 风险提示/暂不关注说明 |
| `next_actions` | array | 否 | 导航链接列表 |
| `sources` | array | 否 | 来源标识列表 |
| `freshness_note` | string | 否 | 时效性说明 |

### 响应兼容性

`workflow_bridge.py` 的 `normalize_response` 兼容以下平台返回的异构格式：

| 平台 | 典型返回结构 | 兼容方式 |
|------|-------------|----------|
| N8N | 直接返回归一化 JSON | 直接使用 |
| Dify | `{"answer": "...", "sources": [...]}` | 直接使用 |
| Coze | `{"data": {"answer": "..."}}` | `_pick_response_object` 自动提取 `data` |
| Generic | `{"output": "{\"answer\":\"...\"}"}` | 自动解析嵌套 JSON 字符串 |
| Generic | `{"messages": [{"role":"assistant","content":"..."}]}` | `_message_answer` 提取 assistant 内容 |

## curl 冒烟测试样例

### 泛问题："你能帮我做什么"

```bash
curl -s -X POST "https://YOUR_WORKFLOW_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "message": "你能帮我做什么",
    "query": "你能帮我做什么",
    "context": {"current_page": "/", "mode": "chat"},
    "guardrails": {"research_only": true, "no_trade_execution": true, "no_position_sizing": true, "must_disclose_if_no_local_evidence": true}
  }' | jq .
```

### 市场问题："现在能不能做"

```bash
curl -s -X POST "https://YOUR_WORKFLOW_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "message": "现在能不能做",
    "query": "现在能不能做",
    "context": {"current_page": "/", "mode": "chat", "market_data": {"phase": "observe"}},
    "guardrails": {"research_only": true, "no_trade_execution": true, "no_position_sizing": true, "must_disclose_if_no_local_evidence": true}
  }' | jq .
```

### 行业问题："今天先看什么方向"

```bash
curl -s -X POST "https://YOUR_WORKFLOW_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "message": "今天先看什么方向",
    "query": "今天先看什么方向",
    "context": {"current_page": "/", "mode": "chat"},
    "guardrails": {"research_only": true, "no_trade_execution": true, "no_position_sizing": true, "must_disclose_if_no_local_evidence": true}
  }' | jq .
```

### 个股问题："000021 怎么看"

```bash
curl -s -X POST "https://YOUR_WORKFLOW_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "message": "000021 怎么看",
    "query": "000021 怎么看",
    "context": {"current_page": "/", "mode": "chat", "symbol": "000021.SZ"},
    "guardrails": {"research_only": true, "no_trade_execution": true, "no_position_sizing": true, "must_disclose_if_no_local_evidence": true}
  }' | jq .
```

### 基本面问题："用价值分析看 000021"

```bash
curl -s -X POST "https://YOUR_WORKFLOW_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "message": "用价值分析看 000021",
    "query": "用价值分析看 000021",
    "context": {"current_page": "/", "mode": "chat", "symbol": "000021.SZ", "value_prompt_pack": true},
    "guardrails": {"research_only": true, "no_trade_execution": true, "no_position_sizing": true, "must_disclose_if_no_local_evidence": true}
  }' | jq .
```

### 教学问题："什么是 State E/F"

```bash
curl -s -X POST "https://YOUR_WORKFLOW_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "message": "什么是 State E/F",
    "query": "什么是 State E/F",
    "context": {"current_page": "/", "mode": "chat"},
    "guardrails": {"research_only": true, "no_trade_execution": true, "no_position_sizing": true, "must_disclose_if_no_local_evidence": true}
  }' | jq .
```

### 导航问题："我应该先去哪页"

```bash
curl -s -X POST "https://YOUR_WORKFLOW_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "message": "我应该先去哪页",
    "query": "我应该先去哪页",
    "context": {"current_page": "/", "mode": "chat"},
    "guardrails": {"research_only": true, "no_trade_execution": true, "no_position_sizing": true, "must_disclose_if_no_local_evidence": true}
  }' | jq .
```

### 无本地数据问题："解释一下低空经济这个概念"

```bash
curl -s -X POST "https://YOUR_WORKFLOW_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "message": "解释一下低空经济这个概念",
    "query": "解释一下低空经济这个概念",
    "context": {"current_page": "/", "mode": "chat"},
    "guardrails": {"research_only": true, "no_trade_execution": true, "no_position_sizing": true, "must_disclose_if_no_local_evidence": true}
  }' | jq .
```

## 浏览器验收步骤

1. 打开任意页面的"观象"（右下角大象图标）。
2. 勾选"更自然的解释"。
3. 问一个本地规则无法覆盖的问题，例如"解释一下低空经济这个概念"。
4. 页面必须显示**"外部工作流"**来源标签。
5. 必须显示**"暂无实际数据支持"**。

## 期望的 Hermass 前端渲染效果

```
┌─────────────────────────────────────┐
│ 观象                                 │
├─────────────────────────────────────┤
│ 低空经济是指...（回答内容）           │
│                                      │
│ 外部工作流 · 暂无实际数据支持         │
└─────────────────────────────────────┘
```
