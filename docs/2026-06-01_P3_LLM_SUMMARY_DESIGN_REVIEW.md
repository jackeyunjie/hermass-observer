# Phase 3 LLM 摘要落盘设计审阅结论

版本：v1.0
日期：2026-06-01
审阅对象：`docs/CLAUDE_TASK_P3_SUMMARY_DESIGN.md`

---

## 一、核心问题结论

### 1. 触发策略：按轮数(每5轮)还是按时间(每30分钟)摘要？

**✅ 结论 — 以轮数触发为主，但必须基于数据库 turn ID 而非内存 `len(turns)`。**

**理由：**

设计文档中 `len(session.turns) % 5 == 0` 存在隐性缺陷：
- `Session.max_turns = 20`，内存 turns 达到 20 后会截断，长度不再增长，**后续永远不会再次触发摘要**
- 服务重启后从 SQLite 加载的 turns 同样最多 20 条，同一会话的后续轮次无法触发第二次及以上的摘要
- 这意味着一个长会话最多触发 4 次摘要（5/10/15/20 轮），之后摘要系统事实停摆

**建议实现：**

| 要素 | 建议 |
|------|------|
| 主触发条件 | 数据库 `turns` 表中该 session 的最新 `id` 与 `last_summarized_turn_end` 之差 ≥ 5 |
| 状态持久化 | 在 `session_summaries` 表中记录 `cover_turn_end`，或单独维护 `last_summarized_turn_id` |
| 辅助条件（可选） | 距离上次摘要超过 30 分钟且新增轮数 ≥ 2，可作为低频兜底 |
| 触发位置 | 保留在 `conversation_manager.add_message()` 中，assistant 回复后异步检查 |

时间间隔（30分钟）作为辅助条件即可，不作为主触发。投资对话通常密集发生，按轮数触发更贴合信息密度的自然节奏；纯时间触发会导致"1轮对话等了30分钟也生成摘要"的浪费。

---

### 2. 增量摘要 vs 滚动全量重写？

**✅ 结论 — 滚动全量重写（上一条摘要 + 最新覆盖的原始轮次 → 新的全量摘要）。**

**理由：**

增量合并的实现复杂度远高于收益：
- `core_conclusion`：需要覆盖还是追加？早期结论与后期矛盾的合并策略难以规则化
- `discussed_stocks`：需要合并去重，且 `context` 字段需更新（如从"问了个股诊断"演进为"已给出持仓建议"）
- `scenario_trace`：需追加但不能无限增长，需要截断策略
- `key_question_unresolved`：需要状态机判断"是否已解决"

这些合并逻辑写起来脆弱、容易出边界 bug，不如让 LLM 自行做信息压缩和取舍。

**建议实现：**

```
输入 = 上一条 summary_json（如有）+ 最新 5 轮原始对话（user/assistant message）
输出 = 新的全量 summary_json
存储 = 新记录写入 session_summaries，旧记录保留作为审计轨迹
使用 = 始终取该 session 最新一条 summary
```

Token 消耗完全可控：上条摘要约 300-500 token + 5 轮对话约 1000-2000 token = 单次约 1500-2500 token，在当前 DeepSeek 调用成本下可忽略。

---

### 3. conversation_summary 注入 router 还是只注入 fusion？

**✅ 结论 — 必须注入 router，同时注入 fusion。**

**理由：**

Phase 3 的核心目标是"让大模型跨多轮理解用户之前问过什么"。如果只注入 fusion，这个问题只解决了一半：

| 链路节点 | 当前问题 | summary 的价值 |
|---------|---------|---------------|
| **router** | 用户说"那这只呢"、"再详细说说"、"行业呢" —— 代词/省略主语/跨轮场景切换导致路由错误 | `discussed_stocks`、`scenario_trace` 可直接补全缺失的 symbol 和场景上下文，避免路由到 chitchat |
| **场景模块** | 各场景 agent 看不到 3 轮之前的历史 | summary 中的 `core_conclusion` 和 `key_question_unresolved` 可让诊断/分析更有连续性 |
| **fusion** | 已有 `recent_turns`（3轮），但代词解析和历史一致性依赖更长的上下文 | summary 可强化跨轮一致性约束 |

**router 是整条链的第一关**；router 误判，后续所有场景编排都是错的。例如：
- 用户前 5 轮在讨论 000021，第 6 轮问"那这只呢" → 无 summary 时 router 看到 `symbol=无`，极可能判为 chitchat
- 用户前 5 轮在做 stock_checkup，第 6 轮问"它所属行业怎么样" → 无 summary 时 router 可能继续路由到 stock_checkup，而非 industry_scan

**关于禁止事项"不改 router prompt"：**

此限制需要放宽。具体建议：
- **system prompt（PROMPT 常量）保持不变**
- **在 router.run() 的 `agent.input()` 中追加会话摘要段落** —— 这属于输入数据增强，不属于 prompt 逻辑变更
- 追加格式：
  ```
  会话摘要（最近讨论）：{summary_json}
  ```

如果严格禁止任何 router 修改，则 Phase 3 只能退而求其次：
1. 在 `web/main.py` 中利用 summary 做 **symbol 补全**（代词解析失败时从 `discussed_stocks` 提取），间接帮助 router
2. 在 `qa_entry.handle()` 的关键词兜底路由中，利用 `scenario_trace` 提升 `_keyword_fallback_route` 的准确度
3. 但这两个间接手段无法替代 router 直接消费 summary 的效果

**建议的注入路径：**

```
web/main.py _llm_chat_answer()
  └─ 从 conversation_manager / SQLite 读取最新 summary
  └─ 放入 context["conversation_summary"]
  └─ 传给 qa_entry.handle()

qa_entry.handle()
  ├─ router.run(user_input, context)  ← input 中追加 summary
  ├─ scenario_mod.run(user_input, context)  ← 各场景可在 context 中读取 summary
  └─ fusion.run(fusion_ctx)  ← input 中追加 summary
```

---

## 二、审阅清单其他项

### session.summary 内存字段 vs SQLite 读取

**⚠️ 结论 — 不建议在 `Session` dataclass 中加 `summary` 字段。**

理由：`get_session()` 从 SQLite 加载时不会恢复 summary，服务重启后该字段为空，造成状态不一致。如果代码路径中有 `if session.summary` 的判断，重启后行为会突变。

建议：
- 在 `ConversationStore` 中新增 `get_latest_summary(session_id: str) -> dict | None`
- `Session.get_context_for_prompt()` 中按需调用，不缓存
- 或者由 `ConversationManager` 在 `get_context()` 中统一拼接

### summarizer 输出 JSON schema — 股票代码解析

**⚠️ 结论 — 需要在 summarizer prompt 中明确约束，并做后处理校验。**

建议 prompt 追加：
> "discussed_stocks 中的 code 必须为 6 位纯数字 A 股代码（如 000021、688107），不要包含交易所后缀。"

后处理：summarizer 返回后，对 `discussed_stocks` 中每个 `code` 跑正则 `(?<!\d)\d{6}(?!\d)`，不合法则丢弃该条或修正。

### summarizer LLM 调用失败处理

**✅ 结论 — 不阻塞主链路，静默跳过，等下一轮再试。**

建议：
- `conversation_manager.add_message()` 中的摘要触发用独立 try/except 包裹
- 失败时记录 `logger.warning()`，包含 session_id 和异常信息
- 不抛异常、不中断用户回复流程
- 下次轮数满足条件时再次尝试

### session_summaries 表 TTL 清理

**⚠️ 结论 — 建议加 30 天 TTL，但优先级低，可作为后续优化。**

理由：
- 会话本身 TTL 仅 1 天（86400 秒），过期后 session 记录会被清理
- 但 `session_summaries` 中的历史摘要可作为审计轨迹保留更长时间
- 30 天是合理折中：足够回溯近期问题，不会无限膨胀

建议实现：
- `ConversationStore.cleanup_old_summaries(days=30)` 方法
- 由 `ConversationManager._gc()` 在会话 GC 时顺带触发（控制频率，如每 100 次 GC 触发 1 次）

---

## 三、改动文件调整建议

基于以上审阅，原设计文档的改动文件列表建议微调：

| 文件 | 原设计 | 审阅后调整 |
|------|--------|-----------|
| `conversation_store.py` | +1 表 `session_summaries` | ✅ 不变；**追加** `get_latest_summary()`、**追加** `cleanup_old_summaries()` |
| `conversation_manager.py` | `add_message()` 加触发，`Session` 加 `summary` 字段 | `add_message()` 触发逻辑改用数据库 turn ID 差值；**不在** `Session` 中加 `summary` 字段；**追加** `get_latest_summary()` 代理方法 |
| `agently_adapter/agents/summarizer.py` | 新建，~40 行 | ✅ 不变；prompt 中追加股票代码格式约束 |
| `web/main.py` | `_llm_chat_answer()` 注入 `conversation_summary` | ✅ 不变；从 SQLite（而非内存 Session）读取最新摘要 |
| `agently_adapter/agents/fusion.py` | prompt 中增加「会话摘要」段 | ✅ 不变；input 中追加 `conversation_summary` |
| `agently_adapter/agents/router.py` | （原设计未改动） | **建议增加**：input 中追加 `conversation_summary` 段落 |
| `agently_adapter/qa_entry.py` | （原设计未改动） | **建议增加**：将 `conversation_summary` 显式传入 router 和 fusion（当前已通过 context 隐式传递） |

---

## 四、实施优先级

| 优先级 | 事项 | 说明 |
|--------|------|------|
| P0 | 触发逻辑改为数据库 turn ID 基准 | 不修复则长会话摘要系统事实停摆 |
| P0 | 滚动全量重写策略 | 决定 summarizer Agent 的输入输出契约 |
| P0 | conversation_summary 注入 fusion | 原设计已覆盖，直接实施 |
| P1 | conversation_summary 注入 router | 对路由准确度有实质提升，建议放宽"不改 router prompt"限制 |
| P1 | summarizer 股票代码后处理 | 数据质量保障 |
| P2 | session_summaries TTL 清理 | 可延后，表数据量短期不会成问题 |

---

## 五、总体判断

**⚠️ 需调整后开始实现。**

三个核心问题中，触发策略（问题1）存在实现缺陷，必须修复；增量 vs 全量（问题2）需要明确为滚动全量重写；注入范围（问题3）强烈建议覆盖 router + fusion，否则 Phase 3 的核心目标只达成一半。

如果接受以上调整，可以开始实现。
