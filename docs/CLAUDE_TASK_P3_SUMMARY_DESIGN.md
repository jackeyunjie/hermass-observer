# Claude Task — 主线 Phase 3：LLM 摘要落盘设计审阅

版本：v1.0
日期：2026-06-01
执行对象：Claude
目标：审阅「多轮对话 LLM 摘要落盘」的设计方案

---

## 0. 背景

Phase 1（规则记忆提取）和 Phase 2（意图追踪 + 场景纠偏）已闭环。

当前「连续对话记忆」的实现：
- `_build_memory_context()` 从最近 3 轮 raw text 中提取 `recent_stock_codes`、`recent_topics`
- `recent_turns` 透传到 fusion Agent 作为 prompt 上下文
- **问题**：只有最近 3 轮，大模型不能跨多轮理解「用户之前都问过什么、结论是什么」

Phase 3 目标：每 N 轮对话触发一次 LLM 摘要，压缩为结构化 JSON，存入 SQLite，后续请求自动注入最近摘要。

---

## 1. 现有基础设施（不新建）

| 组件 | 文件 | 可复用部分 |
|------|------|-----------|
| 会话存储 | `conversation_store.py` | `sessions` + `turns` 表，SQLite stdlib |
| 会话管理 | `conversation_manager.py` | `Session` dataclass, `add_turn()`, `get_context_for_prompt()` |
| 记忆提取 | `web/main.py:_build_memory_context()` | 已读取最近 3 轮 |
| LLM 调用 | `agently_adapter/deepseek.py:call()` | 统一封装 |
| Agent 基类 | `agently_adapter/agents/base.py` | `create_agent()`, `safe_get_response()` |

---

## 2. 设计方案

### 2.1 新表

在 `conversation_store.py` 的 `_init_db()` 中新增：

```sql
CREATE TABLE IF NOT EXISTS session_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    summary_json TEXT NOT NULL,       -- LLM 输出的结构化 JSON
    cover_turn_start INTEGER NOT NULL, -- 覆盖的 turns 起始 ID
    cover_turn_end INTEGER NOT NULL,   -- 覆盖的 turns 结束 ID
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
)
```

### 2.2 新 Agent

`agently_adapter/agents/summarizer.py`：

```
输入：最近 N 轮对话的 user/assistant 消息列表
输出：
{
  "core_conclusion": "用户主要关注...",
  "discussed_stocks": [{"code": "000021", "name": "深科技", "context": "问了个股诊断"}],
  "scenario_trace": ["stock_checkup", "industry_scan"],
  "key_question_unresolved": "用户尚未完成盯盘注册"
}
```

不经过场景编排链，直接由 `conversation_manager` 调用。一次 DeepSeek 调用。

### 2.3 触发时机

在 `conversation_manager.add_message()` 中：
- 每次 assistant 回复后检查 `session.turns` 数量
- 当 `len(session.turns) >= 5` 且 `len(session.turns) % 5 == 0` 时触发摘要
- 摘要写入 SQLite 后，`session.summary` 字段更新为最新摘要 JSON

### 2.4 上下文注入

在 `_llm_chat_answer()` 中（web/main.py）：
- 调用 `_build_memory_context()` 后，从 `conversation_manager` 读取 `session.summary`
- 注入到 `context["conversation_summary"]`，由 `qa_entry.handle()` 传入 router 和 fusion

### 2.5 改动文件

| 文件 | 改动 |
|------|------|
| `conversation_store.py` | +1 表 `session_summaries` |
| `conversation_manager.py` | `add_message()` 中加摘要触发，`Session` 加 `summary` 字段 |
| `agently_adapter/agents/summarizer.py` | 新建，~40 行 |
| `web/main.py` | `_llm_chat_answer()` 注入 `conversation_summary` 到 context |
| `agently_adapter/agents/fusion.py` | prompt 中增加「会话摘要」段 |

---

## 3. 审阅清单

- [ ] 触发策略：`len(turns) % 5 == 0` 是否合理？是否应该按时间间隔（如 30 分钟）而非轮数触发？
- [ ] 摘要覆盖范围：是「增量」（只补充最新 5 轮）还是「全量重写」（用已有摘要 + 新的 5 轮生成滚动摘要）？
- [ ] `session.summary` 字段放在 Session dataclass 内存中，服务重启后丢失。是否应该每次都从 SQLite 读？
- [ ] summarizer Agent 的输出 JSON schema——`discussed_stocks` 中股票代码是否正确解析为 6 位？需要 prompt 约束吗？
- [ ] 在 `_llm_chat_answer()` 中注入 `conversation_summary` 到 router 的 input 中是否能提升路由准确度？还是只注入 fusion 就够了？
- [ ] 如果 summarizer LLM 调用失败，是否阻塞摘要？还是静默跳过，等下一轮再试？
- [ ] `session_summaries` 表是否需要对旧记录做 TTL 清理（如 30 天）？

---

## 4. 禁止事项

- 不改 router prompt
- 不改 5 个场景编排文件
- 不引入新依赖

---

## 5. 输出

结论写 `docs/2026-06-01_P3_LLM_SUMMARY_DESIGN_REVIEW.md`，格式：`✅/⚠️/❌ 结论 — 建议`。末尾给出「可以开始实现 / 需调整」判断。
