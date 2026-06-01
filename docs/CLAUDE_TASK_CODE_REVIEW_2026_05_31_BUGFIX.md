# Claude Task — 2026-05-31 观象 Bug 修复代码审阅

版本：v1.0  
日期：2026-05-31  
执行对象：Claude  
目标：审阅 8 个修改文件，检查修复方案是否正确、有无遗漏边界、是否引入回归风险

---

## 0. 背景

Hermass 观象 AI 助手前端交互测试结果：7/9 通过，2 项失败。

| # | 失败项 | 根因 |
|---|--------|------|
| 3 | LLM 开关关（`use_llm=false`） | `_should_use_managed_llm()` 对高价值问题强制返回 True，绕过用户选择 |
| 7 | 连续对话记忆（"000021 怎么样" → "它是什么行业"） | 代词"它"未解析为股票代码；场景编排/fusion 未消费对话历史 |

修复涉及 8 个文件，+84/-11 行。

---

## 1. 审阅范围

你只需要审阅以下文件本次修改的 diff（不需要通读全文）：

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `web/main.py` | 核心逻辑 | `_should_use_managed_llm` / `_requires_managed_llm` 去强制、代词解析、`_build_memory_context` 补 `recent_turns`、行业预取、stock 预取 |
| `agently_adapter/qa_entry.py` | 路由纠偏 | 场景二次纠偏：router 给出 `stock_checkup`+`secondary=industry_scan` 时，关键词匹配后切换场景 |
| `agently_adapter/agents/fusion.py` | 融合层 | 注入对话历史到 prompt，引导回答关联上下文 |
| `agently_adapter/scenarios/market_overview.py` | 场景管道 | 透传 `recent_turns` 到 fusion |
| `agently_adapter/scenarios/stock_checkup.py` | 场景管道 | 透传 `recent_turns` 到 fusion |
| `agently_adapter/scenarios/industry_scan.py` | 场景管道 | 透传 `recent_turns` 到 fusion |
| `agently_adapter/scenarios/strategy_fit.py` | 场景管道 | 透传 `recent_turns` 到 fusion |
| `agently_adapter/scenarios/learn_topic.py` | 场景管道 | 透传 `recent_turns` 到 fusion |

完整 diff 在本地工作区可直接 `git diff HEAD` 查看。

---

## 2. 审阅检查清单

### 2.1 Test 3 修复（LLM 开关）

- [ ] `_should_use_managed_llm()` 删除了高价值问题强制返回 True 的逻辑。确认：`use_llm=false` 时，`_chat_answer()` 是否仍会正确走到规则回答分支（watch_command / 页面导航 / 规则摘要）？
- [ ] `_requires_managed_llm()` 增加了 `use_llm=false` 的 early return。确认：这会阻止 `_llm_required_failure_response()` 对关 LLM 的用户返回"模型调用失败"提示吗？如果关了 LLM 但确实是高价值问题，理论上该不该给回退提示？
- [ ] `_is_market_question` / `_is_industry_question` / `_is_value_question` 这三个函数在 `_llm_chat_answer()` 中仍被用来决定数据预取策略。`use_llm=false` 时这些预取仍会执行——这是合理的吗？（个人判断：合理，因为规则回答也需要这些数据）

### 2.2 Test 7 修复（连续对话记忆）

- [ ] **代词解析**：`"它"/"这个"/"这只"/"那个"/"那只"` 的匹配是不是太宽？有没有可能误匹配？例如用户说"它的行业前景怎么样"，"它的"前缀是否需要处理？
- [ ] **场景纠偏**：`qa_entry.py` 中当 `secondary == "industry_scan"` 且用户消息含行业关键词时切换场景。这个纠偏是否过于激进？`watch_command` 场景也需要支持吗？考虑边界："帮我盯着 000021，它所在的行业有什么变化"——这种情况 `industry_scan` 还是 `watch_command`？
- [ ] **fusion 注入对话历史**：对话历史是拼在 `agent.input()` 中传给 LLM 的。确认：这是否会超 token 限制？目前截断到最近 3 轮、每条 200 字，结合整个 fusion input 是否安全？
- [ ] **`_build_memory_context`**：返回字典新增 `recent_turns` 字段。确认：是否有其他地方读取这个返回值并假设了固定 key 集合？（搜索调用方验证）
- [ ] **行业预取**：在 `_llm_chat_answer()` 中为行业问题从 DuckDB 查 `sw_l1_name`——这个查询失败时 `try/except` 正确吗？DuckDB 连接是否在异常时泄漏？

### 2.3 整体风险

- [ ] 8 个文件修改，5 个场景文件只加了一行 `recent_turns` 透传。确认：有没有新增场景文件遗漏这个透传？
- [ ] `_llm_chat_answer()` 函数体已超过 100 行。本次加了代词解析 + 行业预取 + stock 预取，是否考虑拆分？还是当前阶段暂不重构？
- [ ] 所有新增的 `try/except` 是否都是 `pass`（静默降级）——符合项目"数据预取单独降级"规则？
- [ ] `_should_use_managed_llm()` 改后语义变为"用户是否开了 LLM 开关"，与原函数名含义有偏差。是否需要改名或更新注释？

---

## 3. 不需要做的事

- 不需要通读 `web/main.py` 全 3600+ 行
- 不需要执行部署或测试
- 不需要讨论市场/个股业务逻辑
- 不需要提交代码

---

## 4. 输出格式

请用列表形式输出每个检查项的结论，格式：

```
✅ / ⚠️ / ❌  描述  —  建议（如有）
```

审阅完成后，把审阅报告写在 `docs/2026-05-31_CODE_REVIEW_BUGFIX.md`。
