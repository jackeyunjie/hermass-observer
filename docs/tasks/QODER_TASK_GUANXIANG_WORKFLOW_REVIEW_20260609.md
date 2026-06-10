# Qoder 任务：观象工作流扩展审计与补强

## 背景

观象准备通过 N8N / Dify / Coze / Generic webhook 扩展回答范围。Codex 已补入最小桥接层与证据标注：

- `agently_adapter/workflow_bridge.py`
- `web/main.py`
- `web/templates/_ai_assistant.html`
- `web/static/style.css`
- `web/static/ai-assistant.css`

请从代码审计角度检查，不要重构主架构。

## 审计目标

确认外部工作流扩展不会破坏以下边界：

1. Web 层不直连平台 SDK，只调用 `agently_adapter/workflow_bridge.py`。
2. 外部工作流不是本地事实源，不得伪装为 `daily_snapshot`、`research_evidence`、`state_cube`。
3. 没有本地数据支持时，前端必须明确显示“暂无实际数据支持”。
4. 工作流失败、超时、返回非 JSON 时，观象必须安静降级，不影响原有规则回答。
5. API key 不落日志、不进入响应、不写入前端。
6. 不输出买卖建议、仓位建议、自动交易动作。

## 重点检查文件

```text
agently_adapter/workflow_bridge.py
web/main.py
web/templates/_ai_assistant.html
web/static/style.css
web/static/ai-assistant.css
tests/unit/test_workflow_bridge.py
tests/unit/test_chat_query_fallback.py
docs/tasks/KIMI_TASK_GUANXIANG_WORKFLOW_EXPANSION_20260609.md
```

## 需要补强的点

如果发现缺口，请直接修改并补测试：

- `workflow_bridge.normalize_response()` 对 Dify、Coze、N8N 常见返回结构的兼容性。
- `workflow_bridge.build_payload()` 是否泄露过多会话上下文。
- `web.main._annotate_chat_support()` 是否能正确区分：
  - `rule_based`
  - `agently_deepseek`
  - `managed_deepseek`
  - `workflow_n8n`
  - `workflow_dify`
  - `workflow_coze`
- 前端 meta 是否准确展示：
  - DeepSeek 增强
  - 外部工作流
  - 本地数据支持
  - 暂无实际数据支持
- 单测是否覆盖超时、非 JSON、空答案、带本地 source、无本地 source。

## 验收命令

```bash
.venv/bin/python -m pytest tests/unit/test_workflow_bridge.py tests/unit/test_chat_query_fallback.py
.venv/bin/python -m py_compile web/main.py agently_adapter/workflow_bridge.py
```

## 输出要求

给出审计结论：

```text
结论：通过 / 不通过
阻塞问题：
1. ...
非阻塞建议：
1. ...
已补测试：
1. ...
```

不要把 `agently_adapter/agently_daily_flow.py` 描述成主流程；当前官方主线仍是 `agently_adapter/qa_entry.py` + `agently_adapter/deepseek.py` + 可选 `workflow_bridge.py`。
