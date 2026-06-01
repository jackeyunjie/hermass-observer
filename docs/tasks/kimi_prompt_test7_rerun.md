# 给 KIMI 的提示词

**主题**：重跑 Test 7 — 连续对话记忆（Claude 代码修复后验证）

**背景**：
Claude 已修复 #10 连续对话记忆 的根因。修改了两个文件：

1. `web/main.py` `chat_query()` 入口：当 session 从 store 恢复后，将 `session.context`（含 `stock_code`）回填到 `query.session_context`，使 `_chat_stock_code()` 在第二轮能找到历史股票代码。
2. `hermass_platform/chat/conversation_manager.py`：`_extract_context()` 将 key 由 `last_stock_code` 改为 `stock_code`，与 `_chat_stock_code()` 读取的 `ctx.get("stock_code")` 对齐。

---

## 请你执行以下测试并输出完整结果

### 前置条件

- 确保服务已重启加载新代码（http://console.supertrader.world）
- 如果可能，先清掉旧 session：新建一个无历史的 session_id

### 测试步骤

**步骤 1：首轮提问**

```bash
curl -s -X POST http://console.supertrader.world/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{
    "message": "000021 怎么样",
    "stock_code": "000021.SZ",
    "page_context": "stock",
    "mode": "chat",
    "use_llm": true
  }' | python3 -m json.tool
```

记录 `session_id`、`remembered_stock_code`、`intent.scenario`、`answer` 前三行。

**步骤 2：追问行业（用步骤 1 的 session_id）**

```bash
curl -s -X POST http://console.supertrader.world/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{
    "message": "它是什么行业",
    "mode": "chat",
    "session_id": "<步骤1返回的session_id>"
  }' | python3 -m json.tool
```

### 验收标准（与 Test 7 一致）

| 检查项 | 期望 |
|--------|------|
| 两轮 session_id | 一致 |
| 第 2 轮 intent.scenario | industry_scan |
| 第 2 轮 remembered_stock_code | 000021.SZ 或 000021（不再为 null） |
| 第 2 轮 answer | 必须包含"电子行业"，不应再是泛泛的"空仓/防守/市场不好" |

### 输出格式

请以如下格式输出完整结果（附带两轮完整 JSON 响应的截取）：

| 结果 | 测试名 | 关键字段 | 备注 |
|------|--------|----------|------|
| ? | 连续对话记忆 | session= answer= remembered= | 待本次测试确认 |

若仍失败：附完整 JSON 响应，注明具体哪个字段不符预期（如 `remembered_stock_code=null` 或 answer 不含"电子"）。
