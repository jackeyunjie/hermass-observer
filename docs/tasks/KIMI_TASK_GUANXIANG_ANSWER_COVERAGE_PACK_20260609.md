# Kimi 任务：观象 8 问题覆盖包验证

## 目标

系统验证观象在 8 个典型问题类型上的回答覆盖情况，确认本地规则 fallback + 外部工作流 fallback 的完整矩阵。

## 8 个覆盖问题

| # | 问题类型 | 示例提问 | 期望本地覆盖 | 期望外部工作流 |
|---|----------|----------|--------------|----------------|
| 1 | 泛问题 | "你能帮我做什么" | 是（规则可答） | 如开启 LLM 则走外部 |
| 2 | 市场问题 | "现在能不能做" | 是（本地市场数据） | Agently 优先，fallback 外部 |
| 3 | 行业问题 | "今天先看什么方向" | 是（本地行业数据） | Agently 优先，fallback 外部 |
| 4 | 个股问题 | "000021 怎么看" | 是（本地 snapshot） | Agently 优先，fallback 外部 |
| 5 | 基本面问题 | "用价值分析看 000021" | 是（本地价值数据） | Agently 优先，fallback 外部 |
| 6 | 教学问题 | "什么是 State E/F" | 可能弱覆盖 | **优先走外部工作流** |
| 7 | 导航问题 | "我应该先去哪页" | 可能弱覆盖 | **优先走外部工作流** |
| 8 | 无本地数据问题 | "解释一下低空经济这个概念" | 无覆盖 | **必须走外部工作流** |

## 执行步骤

### 1. 本地规则基线（关闭 LLM）

每个问题先关闭"更自然的解释"，记录规则回答：

```bash
curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"message":"你能帮我做什么","page_context":"/","mode":"chat","use_llm":false}' | jq .
```

记录字段：
- `provider`
- `data_support`
- `answer`（前 100 字）
- 是否有实际数据支撑

### 2. LLM 增强路径（开启 LLM，Agently 优先）

勾选"更自然的解释"，记录：
- 若 Agently 有结果：provider = agently_deepseek / managed_deepseek
- 若 Agently 无结果：fallback 到外部工作流 provider = workflow_xxx

### 3. 外部工作流独占路径（强制无本地数据）

对问题 6/7/8，确认：
- 本地规则是否确实无法高质量回答
- 外部工作流是否被正确触发
- 前端是否显示"暂无实际数据支持"

### 4. 对比矩阵

输出 Markdown 表格：

```markdown
| 问题 | 规则回答 | LLM回答 | 外部工作流 | 数据支撑 | 缺陷 |
|------|----------|---------|------------|----------|------|
| 你能帮我做什么 | ... | ... | ... | ... | ... |
```

## 验收标准

- [ ] 问题 1-5：本地规则或 Agently 至少有一个能给出结构化回答
- [ ] 问题 6-8：至少触发一次外部工作流，且 `provider` 以 `workflow_` 开头
- [ ] 所有外部工作流回答：`data_support` 为 `llm_only`，`support_note` 含"暂无实际数据支持"
- [ ] 无本地数据的问题（8），外部工作流不得伪造 `daily_snapshot` 来源
- [ ] 输出覆盖率报告到 `outputs/reviews/guanxiang_coverage_YYYYMMDD.md`

## 输出模板

```markdown
# 观象回答覆盖报告（2026-06-09）

## 测试环境
- Hermass 版本：当前 commit
- 工作流提供商：generic / n8n / dify / coze
- 测试时间：YYYY-MM-DD HH:MM

## 覆盖矩阵

| # | 问题 | provider | data_support | 质量评级 | 备注 |
|---|------|----------|--------------|----------|------|
| 1 | ... | ... | ... | A/B/C/D | ... |

## 发现的问题

1. ...

## 下一步建议

1. ...
```

## 交付物

- `outputs/reviews/guanxiang_coverage_YYYYMMDD.md`
- 如有 bug，附带最小复现 curl 和修复 PR
