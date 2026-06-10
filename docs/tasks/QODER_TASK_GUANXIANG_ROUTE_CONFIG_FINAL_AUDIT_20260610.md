# Qoder 任务：观象路由配置最终上线前审计

## 背景

观象外部工作流扩展已经完成代码、文档、8 问 e2e、30 问覆盖脚本和路由配置样例。当前要做最后一轮上线前审计，重点不是再扩功能，而是确认路由边界、数据支撑标注和真实 webhook 接入风险。

## 审计输入

请在 `/Users/lv111101/Documents/hermass-observer-product` 审计以下文件：

```text
agently_adapter/workflow_bridge.py
web/main.py
web/templates/_ai_assistant.html
config/guanxiang_question_routes.example.json
docs/GUANXIANG_ANSWER_COVERAGE_PACK_20260609.md
docs/workflow/external_workflow_setup.md
docs/workflow/webhook_contract.md
scripts/run_guanxiang_30q_coverage.py
scripts/mock_external_workflow.py
tests/unit/test_workflow_bridge.py
tests/unit/test_chat_query_fallback.py
tests/integration/test_guanxiang_workflow_e2e.py
```

## 审计重点

1. `config/guanxiang_question_routes.example.json` 是否准确表达当前实现：规则优先，Agently/DeepSeek 次之，只有 Agently 无结果才进入 workflow fallback。
2. 30 问脚本是否自包含复跑，不依赖真实网络、外部端口或后台 mock 服务。
3. 30 问脚本是否把 `workflow_`、`llm_only`、“暂无实际数据支持”、伪造本地源过滤作为硬断言。
4. `workflow_bridge.py` 是否只发送收口后的上下文，不泄露 `recent_turns`、`value_call`、`api_key`、`token`、`password`、`secret`。
5. 外部工作流 sources 是否无法伪装为 `daily_snapshot`、`research_evidence`、`state_cube`、`p116_foundation` 等本地事实源。
6. `next_actions` 是否只归一化为 `label/url`，不透传 Dify/Coze/N8N 私有动作对象。
7. 前端是否能稳定显示“外部工作流”和“暂无实际数据支持”。
8. 文档是否没有把外部工作流回答描述成 Hermass 本地事实结论。

## 必跑命令

```bash
cd /Users/lv111101/Documents/hermass-observer-product
.venv/bin/python scripts/run_guanxiang_30q_coverage.py
.venv/bin/python -m pytest tests/unit/test_workflow_bridge.py tests/unit/test_chat_query_fallback.py tests/integration/test_guanxiang_workflow_e2e.py
.venv/bin/python -m py_compile web/main.py agently_adapter/workflow_bridge.py scripts/mock_external_workflow.py scripts/run_guanxiang_30q_coverage.py tests/integration/test_guanxiang_workflow_e2e.py
python3 -m json.tool config/guanxiang_question_routes.example.json >/tmp/guanxiang_routes_check.json
```

## 真实 webhook 附加验收

如果当前环境提供了真实变量，再追加 live smoke；没有真实变量则明确记录“未执行 live smoke”。

```bash
export HERMASS_AI_WORKFLOW_PROVIDER=generic
export HERMASS_AI_WORKFLOW_URL=替换为真实 webhook
export HERMASS_AI_WORKFLOW_API_KEY=替换为真实 key
export GUANXIANG_30Q_USE_REAL_WORKFLOW=1
curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H 'Content-Type: application/json' \
  -d '{"message":"解释一下低空经济这个概念","mode":"chat","use_llm":true}' | head -c 1200
```

验收时不要强行要求真实 Agently/DeepSeek 已有效回答的请求返回 `workflow_generic`。只有强制 workflow fallback 或 Agently 返回空结果时，才要求 `workflow_` 和 `llm_only`。

## 输出格式

```text
结论：通过 / 不通过

阻塞问题：
1. ...

非阻塞建议：
1. ...

已运行验证：
1. ...

上线前提醒：
1. ...
```

## 硬规则

- 不要提交真实 webhook key。
- 不要让外部工作流覆盖五条红线。
- 不要把 workflow 回答标成 Hermass 本地数据结论。
- 不要把 `agently_adapter/agently_daily_flow.py` 描述成主流程。
