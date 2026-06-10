# Kimi 任务：观象外部工作流真实联调冒烟

## 目标

验证 Hermass -> workflow_bridge -> 外部工作流 -> 前端标注 的完整链路真实可用。

## 环境准备

### 步骤 1：搭建本地 Mock 工作流（如果无真实 N8N/Dify/Coze）

已有脚本：`scripts/mock_external_workflow.py`（FastAPI，端口 19999）。

启动命令：

```bash
cd /Users/lv111101/Documents/hermass-observer-product
.venv/bin/python scripts/mock_external_workflow.py
```

若使用真实工作流，跳过此步，直接配置真实 URL。

### 步骤 2：配置 .env

在项目根目录 `.env` 或 `.env.workflow` 写入：

```bash
HERMASS_AI_WORKFLOW_PROVIDER=generic
HERMASS_AI_WORKFLOW_URL=http://127.0.0.1:19999/webhook
HERMASS_AI_WORKFLOW_API_KEY=test-key-local-only
HERMASS_AI_WORKFLOW_TIMEOUT_SEC=10
```

**注意：不要提交到 Git。**

### 步骤 3：启动 Hermass

```bash
cd /Users/lv111101/Documents/hermass-observer-product
source .venv/bin/activate
python web/main.py
```

服务默认在 `http://127.0.0.1:8020`。

## 冒烟测试（curl）

在另一个终端执行以下命令。若本轮验收目标是强制验证 workflow fallback，请先确保 Agently 返回空结果或使用 mock/e2e 测试中的 patch；这时每个问题都应返回 `"provider": "workflow_generic"` 和 `"data_support": "llm_only"`。

如果真实 Agently / DeepSeek 已经给出有效回答，则不应强行要求返回 `workflow_generic`；此时验收重点改为确认前端正确标注 `agently_deepseek` / `managed_deepseek` 以及本地数据支持状态。

### 1. 泛问题

```bash
curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"message":"你能帮我做什么","page_context":"/","mode":"chat","use_llm":true}' | jq '.provider, .data_support, .support_note'
```

### 2. 市场问题

```bash
curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"message":"现在能不能做","page_context":"/","mode":"chat","use_llm":true}' | jq '.provider, .data_support'
```

### 3. 行业问题

```bash
curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"message":"今天先看什么方向","page_context":"/","mode":"chat","use_llm":true}' | jq '.provider, .data_support'
```

### 4. 个股问题

```bash
curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"message":"000021怎么看","page_context":"/","mode":"chat","use_llm":true}' | jq '.provider, .data_support'
```

### 5. 基本面问题

```bash
curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"message":"用价值分析看000021","page_context":"/","mode":"chat","use_llm":true}' | jq '.provider, .data_support'
```

### 6. 教学问题

```bash
curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"message":"什么是State E/F","page_context":"/","mode":"chat","use_llm":true}' | jq '.provider, .data_support'
```

### 7. 导航问题

```bash
curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"message":"我应该先去哪页","page_context":"/","mode":"chat","use_llm":true}' | jq '.provider, .data_support'
```

### 8. 无本地数据问题

```bash
curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"message":"解释一下低空经济这个概念","page_context":"/","mode":"chat","use_llm":true}' | jq '.provider, .data_support'
```

## 浏览器验收

1. 打开 `http://127.0.0.1:8020`
2. 点击右下角"观象"大象图标
3. 勾选"更自然的解释"
4. 输入："解释一下低空经济这个概念"
5. 观察回答下方元信息，必须包含：
   - `外部工作流`
   - `暂无实际数据支持`

## 预期返回示例

```json
{
  "answer": "【外部工作流】我是观象外部助手，可以为你解释概念、整理资料...",
  "provider": "workflow_generic",
  "data_support": "llm_only",
  "support_note": "外部工作流生成，暂无实际数据支持。"
}
```

## 排障

| 现象 | 排查 |
|------|------|
| provider 是 rule_based | 检查 `use_llm` 是否 true；检查 `.env` 是否加载 |
| 请求超时 | 检查 mock 服务是否运行；调大 `HERMASS_AI_WORKFLOW_TIMEOUT_SEC` |
| 无 "外部工作流" 标签 | 检查前端模板是否最新；Hard Refresh 浏览器 |
| 500 错误 | 看 Hermass 终端日志；检查 `workflow_bridge.py` 是否抛异常 |

## 交付物

- 8 个 curl 的原始返回（可贴到 `outputs/workflow_smoke_YYYYMMDD.jsonl`）
- 浏览器截图或文字确认
- 如有失败，附排障过程和修复 diff
