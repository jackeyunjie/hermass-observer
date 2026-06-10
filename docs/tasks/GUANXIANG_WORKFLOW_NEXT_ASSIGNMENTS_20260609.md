# 观象外部工作流扩展 — 下一步任务总调度

## 当前已完成（2026-06-09）

| 组件 | 状态 | 路径 |
|------|------|------|
| 桥接层 | 已完成 + bugfix | `agently_adapter/workflow_bridge.py` |
| Web fallback | 已完成 | `web/main.py` `_llm_chat_answer()` |
| 前端标注 | 已完成 | `web/templates/_ai_assistant.html` |
| 平台配置文档 | 已完成 | `docs/workflow/external_workflow_setup.md` |
| Webhook 合同 | 已完成 | `docs/workflow/webhook_contract.md` |
| .env 模板 | 已完成 | `docs/workflow/.env.workflow.example` |
| 单元测试 | 16 passed | `tests/unit/test_workflow_bridge.py` + `test_chat_query_fallback.py` |

## 待执行（按优先级）

### P0：真实联调冒烟（Kimi 执行）

**任务文档：** `docs/tasks/KIMI_TASK_GUANXIANG_REAL_WORKFLOW_SMOKE_20260609.md`

- 搭建本地 mock 外部工作流或接入真实 N8N/Dify/Coze。
- 配置 `.env` 环境变量。
- 启动 Hermass，用 curl 验证 8 个问题类型。
- 浏览器验收：勾选"更自然的解释"，验证"外部工作流"标签和"暂无实际数据支持"。
- 输出 curl 结果截图或文本记录。

### P1：问题覆盖包验证（Kimi 执行）

**任务文档：** `docs/tasks/KIMI_TASK_GUANXIANG_ANSWER_COVERAGE_PACK_20260609.md`

- 系统性地对 8 个覆盖问题执行端到端测试。
- 每个问题记录：本地规则是否覆盖、外部工作流回答质量、来源标注是否正确。
- 输出覆盖率报告（Markdown）。

### P2：代码审计（Qoder / Codex 执行）

- 审计 `workflow_bridge.py` 的 guardrails 注入是否在生产环境可靠。
- 审计 `.env` 密钥是否可能通过日志/错误回溯泄露。
- 审计前端 `data_support` 标注是否在所有 fallback 路径生效。

## 分工

| 角色 | 任务 | 交付物 |
|------|------|--------|
| **Kimi** | P0 真实联调 + P1 覆盖包 | curl 日志、浏览器截图、覆盖率报告 |
| **Qoder** | P2 代码审计 | 审计报告、风险清单 |
| **Codex** | 最终兜底 + 上线 checklist | 审计确认、部署提示词 |

## 验收硬标准

1. `pytest tests/unit/test_workflow_bridge.py tests/unit/test_chat_query_fallback.py` 必须 16 passed。
2. `py_compile web/main.py agently_adapter/workflow_bridge.py` 必须 OK。
3. curl 8 个问题，至少 6 个返回 `"provider": "workflow_xxx"`。
4. 浏览器端必须同时显示**"外部工作流"**和**"暂无实际数据支持"**（无本地证据时）。
5. 不得提交真实 API Key 到 Git。
