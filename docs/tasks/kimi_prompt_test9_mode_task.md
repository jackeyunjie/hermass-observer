# 给 KIMI 的提示词

**主题**：排查 #9 任务模式识别修复 `mode=task`

**背景**：
当前 `_chat_answer()`（`web/main.py`）中对 `mode` 的解析只有两档：
```python
mode = "agent" if str(query.mode or "").lower() == "agent" else "chat"
```
这意味着前端传 `"mode":"task"` 时，兜底走进了 `"chat"`，导致所有 task 模式下返回的 `mode_used` 都是 `"chat"` 而非 `"task"`。

**请你先定位再告诉我结论，不要直接改代码。**

---

## 排查步骤

### 步骤 1：确认传入值

用 curl 发一个明确带 `"mode":"task"` 的请求，返回中看 `mode_used`：

```bash
curl -s -X POST http://console.supertrader.world/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{
    "message": "帮我盯着 000021，跌破 10 元提醒我",
    "mode": "task",
    "use_llm": true
  }' | python3 -m json.tool
```

记录响应中的 `mode_used` 字段值。

### 步骤 2：确认前端是否真的传 task

查看前端代码中 `mode` 的取值，搜索关键词：`"mode"`、`"task"`、`mode=`、`pageContext.mode`。

如果是任务模式页面（如盯盘、长期跟踪），确认前端 JSON body 中是否传了 `"mode":"task"`。

### 步骤 3：确认后端收到后如何流转

搜索 `web/main.py` 中所有 `mode_used` 赋值点，判断整条链路：

| 路径 | mode 来源 | 当前值 |
|------|----------|--------|
| `_enhance_result_defaults()` | `setdefault("mode_used", "chat")` | 硬编码 chat |
| LLM 回退 | `"mode_used": "chat"` | 硬编码 chat |
| 规则路径各分支 | 局部变量 `mode` | agent → "agent"，否则 "chat" |
| 500 错误兜底 | `str(query.mode or "chat").lower()` | 能透传，但走不到 |

**问题**：局部变量 `mode` 在三元表达式里把 `task` 也归进了 `else` → `"chat"`。

### 步骤 4：确认修复点

修复只需要在 `_chat_answer()` 头部一行：

```python
# 当前（有问题）
mode = "agent" if str(query.mode or "").lower() == "agent" else "chat"

# 应在 front 变成
mode = str(query.mode or "chat").lower()
# 如果后端只认 agent/chat 两档，需要加一行映射：
mode = "task" if mode == "task" else ("agent" if mode == "agent" else "chat")
```

---

## 输出要求

### 如果确认问题存在

输出以下内容：

```
┌──────┬──────────────────┬──────────────────────────┬──────────────────────────┐
│ 结果 │ 测试名           │ 关键字段                 │ 备注                     │
├──────┼──────────────────┼──────────────────────────┼──────────────────────────┤
│  ❌  │ mode=task 识别   │ mode_used=chat           │ 三元表达式将 task 归入   │
│      │                  │                          │ else 分支                │
└──────┴──────────────────┴──────────────────────────┴──────────────────────────┘
```

### 如果前端根本没传 task

说明是前端问题，输出：
"前端未传 `mode":"task"`，当前传入值为 XXX，需要前端配合修改。"
附带你找到的前端代码片段。

---

**不修改代码，只定位和报告。** 定位完成后更新 `docs/tasks/open_issues_20260601.md` 中 #9 状态为"已定位，待修复"。
