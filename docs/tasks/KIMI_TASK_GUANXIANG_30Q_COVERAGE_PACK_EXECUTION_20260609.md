# Kimi 任务：观象 30 问覆盖包执行

## 目标

在 8 问基础上扩展到 30 问，系统验证观象回答的路由正确性、数据支撑标注、来源标识完整性。

## 30 问清单

### A. 泛问题（3 问）
1. 你能帮我做什么
2. 你是谁
3. 怎么使用这个系统

### B. 市场问题（4 问）
4. 现在能不能做
5. 市场怎么样
6. 今天能买吗
7. 要不要等待

### C. 行业问题（4 问）
8. 今天先看什么方向
9. 哪个行业好
10. 顺风方向是什么
11. 板块轮动怎么看

### D. 个股问题（5 问）
12. 000021 怎么看
13. 600519 怎么样
14. 帮我看一只票
15. 这只票如何
16. 它现在什么状态

### E. 基本面/价值问题（4 问）
17. 用价值分析看 000021
18. 基本面如何
19. 八大块分析
20. 深度价值

### F. 教学问题（4 问）
21. 什么是 State E/F
22. VCP 是什么
23. 2560 什么意思
24. 多周期怎么看

### G. 导航问题（3 问）
25. 我应该先去哪页
26. 怎么看自选
27. 设置在哪

### H. 无本地数据/新概念（3 问）
28. 解释一下低空经济这个概念
29. 固态电池产业链
30. 量子计算概念股

## 执行步骤

### 1. 启动 Mock 工作流

```bash
cd /Users/lv111101/Documents/hermass-observer-product
.venv/bin/python scripts/mock_external_workflow.py &
```

### 2. 设置环境变量

```bash
export HERMASS_AI_WORKFLOW_PROVIDER=generic
export HERMASS_AI_WORKFLOW_URL=http://127.0.0.1:19999/webhook
export HERMASS_AI_WORKFLOW_API_KEY=test-key
export HERMASS_AI_WORKFLOW_TIMEOUT_SEC=10
```

### 3. 运行批量测试

已有端到端测试框架：`tests/integration/test_guanxiang_workflow_e2e.py`

复制并扩展为 30 问版本，或直接用脚本批量调用 `/api/chat/query`。

### 4. 记录每个问题的回答路径

对每个问题记录：
- `provider`：rule_based / agently_deepseek / managed_deepseek / workflow_xxx
- `data_support`：rule_only / local_data / llm_only
- `answer` 前 120 字
- `sources` 列表
- 是否正确标注了"暂无实际数据支持"

### 5. 输出 CSV + Markdown 报告

CSV 格式：
```csv
id,question_type,question,provider,data_support,sources,has_local_evidence,quality_note
```

## 验收标准

- [ ] 30 问全部有非空回答
- [ ] 无本地数据的问题（21-30）至少 70% 触发外部工作流或 LLM 增强
- [ ] 所有外部工作流回答 `data_support` 为 `llm_only`
- [ ] 规则回答的 `data_support` 为 `rule_only` 或 `local_data`
- [ ] 无 500 错误或异常降级
- [ ] 输出报告到 `outputs/reviews/guanxiang_30q_coverage_YYYYMMDD.md`

## 交付物

- `outputs/reviews/guanxiang_30q_coverage_YYYYMMDD.md`
- `outputs/reviews/guanxiang_30q_coverage_YYYYMMDD.csv`
- 如有路由异常，附带最小复现 curl 和修复建议
