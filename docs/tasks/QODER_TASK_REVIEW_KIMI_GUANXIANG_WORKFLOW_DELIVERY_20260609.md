# Qoder 任务：审计 Kimi 本次观象外部工作流交付

## 审计范围

Kimi 于 2026-06-09 完成的观象外部工作流扩展交付，具体包括：

| 交付项 | 路径 | 说明 |
|--------|------|------|
| 桥接层修复 | `agently_adapter/workflow_bridge.py` | messages 数组格式 bugfix + normalize_response 重构 |
| Mock 工作流 | `scripts/mock_external_workflow.py` | 本地冒烟测试用 |
| 单元测试 | `tests/unit/test_workflow_bridge.py` | 新增 7 个测试 |
| 端到端测试 | `tests/integration/test_guanxiang_workflow_e2e.py` | 8 问题覆盖 |
| 覆盖报告 | `outputs/reviews/guanxiang_coverage_20260609.md` | 测试结论 |
| 配置文档 | `docs/workflow/*.md` | 平台配置 + webhook 合同 + .env 模板 |
| 调度文档 | `docs/tasks/*` | 3 份提示词文档 |

## 审计重点

### 1. 安全与密钥

- [ ] `.env` 模板中未出现真实 API Key。
- [ ] `workflow_bridge.py` 的 `_compact` 是否正确脱敏 `api_key`/`token`/`password`/`secret`。
- [ ] 异常日志中不会打印完整 `payload` 或 `headers`。
- [ ] `guardrails` 是否在生产链路中被校验（不只是 mock）。

### 2. 代码质量

- [ ] `normalize_response` 的 BFS 展开 (`_iter_response_dicts`) 是否可能导致无限循环或内存爆炸。
- [ ] `timeout_sec` 是否在合理范围（1-60 秒），且不会阻塞主请求线程过久。
- [ ] `requests.post` 失败时是否返回 None，不会抛未捕获异常导致 500。
- [ ] 新增测试是否 flaky（是否依赖外部网络或端口）。

### 3. 业务边界

- [ ] 外部工作流是否**只在 Agently 无结果时才触发**（避免重复调用）。
- [ ] 前端 `data_support` 是否在所有 workflow 路径都标记为 `llm_only`。
- [ ] `sources` 中是否真的没有伪造本地源标识。
- [ ] 规则回答、Agently 回答、外部工作流回答三者的优先级是否清晰。

### 4. 可维护性

- [ ] 文档是否足够让非 Kimi 的人独立搭建 N8N/Dify/Coze 工作流。
- [ ] Mock 服务是否有清晰注释说明"仅用于测试"。
- [ ] `.env` 变量命名是否统一、易理解。

## 审计方法

1. 读代码 diff：
   ```bash
   git diff HEAD -- agently_adapter/workflow_bridge.py
   git diff HEAD -- web/main.py
   git diff HEAD -- tests/unit/test_workflow_bridge.py
   git diff HEAD -- tests/integration/test_guanxiang_workflow_e2e.py
   ```

2. 运行全部测试：
   ```bash
   .venv/bin/python -m pytest tests/unit/test_workflow_bridge.py tests/unit/test_chat_query_fallback.py tests/integration/test_guanxiang_workflow_e2e.py -v
   .venv/bin/python -m py_compile web/main.py agently_adapter/workflow_bridge.py
   ```

3. 人工走读关键路径：
   - `_llm_chat_answer` -> `handle()` -> `call_workflow()` -> `normalize_response()` -> 前端渲染

## 输出格式

```markdown
# Qoder 审计报告：观象外部工作流交付

## 评分
- 安全：X/10
- 代码质量：X/10
- 业务边界：X/10
- 可维护性：X/10
- 综合：X/10

## 通过项
1. ...

## 风险项
1. **风险**：...
   **建议**：...

## 阻塞项（如有）
1. ...

## 结论
- [ ] 通过，可进入下一步（Kimi 30 问覆盖包）
- [ ] 有条件通过，需修复以下项后复测
- [ ] 不通过，需返工
```

## 交付物

- `outputs/reviews/qoder_audit_guanxiang_workflow_YYYYMMDD.md`
- 如有阻塞项，附带具体行号和修复建议
