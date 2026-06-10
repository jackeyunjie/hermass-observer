# Qoder 任务：观象真实工作流接入验收审计

## 背景

Kimi 将进行真实 N8N / Dify / Coze webhook 联调，并整理观象问题覆盖包。你需要在 Kimi 完成后做上线前审计。

## 审计输入

请重点审计：

```text
agently_adapter/workflow_bridge.py
web/main.py
web/templates/_ai_assistant.html
tests/unit/test_workflow_bridge.py
tests/unit/test_chat_query_fallback.py
docs/GUANXIANG_ANSWER_COVERAGE_PACK_20260609.md
config/guanxiang_question_routes.example.json
docs/tasks/KIMI_TASK_GUANXIANG_REAL_WORKFLOW_SMOKE_20260609.md
docs/tasks/KIMI_TASK_GUANXIANG_ANSWER_COVERAGE_PACK_20260609.md
```

## 审计重点

1. 真实 webhook 是否会泄露敏感上下文。
2. API key 是否可能进入日志、前端或 Git。
3. 外部工作流是否伪造本地数据源。
4. 无本地证据时是否稳定显示“暂无实际数据支持”。
5. workflow 超时/失败是否不影响本地规则回答。
6. `next_actions` 是否只包含 `label/url`，不透传平台私有动作对象。
7. 是否有买卖建议、仓位建议、自动交易动作。
8. 是否破坏 Web → Agently → workflow_bridge 的分层边界。

## 必跑命令

```bash
.venv/bin/python -m pytest tests/unit/test_workflow_bridge.py tests/unit/test_chat_query_fallback.py
.venv/bin/python -m py_compile web/main.py agently_adapter/workflow_bridge.py
```

如果 Kimi 提供了真实 webhook 环境变量，再跑：

```bash
curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H 'Content-Type: application/json' \
  -d '{"message":"你能帮我做什么","mode":"chat","use_llm":true}' | head -c 1200
```

## 审计输出格式

```text
结论：通过 / 不通过

阻塞问题：
1. ...

非阻塞建议：
1. ...

已补测试：
1. ...

上线前提醒：
1. ...
```

## 硬规则

- 不要把外部工作流描述成 Hermass 本地事实源。
- 不要让工作流覆盖五条红线。
- 不要把 `agently_adapter/agently_daily_flow.py` 描述成主流程。
- 不要提交真实 webhook key。
