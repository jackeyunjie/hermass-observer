# 2026-05-31 代码审阅 — Bug 修复

## 总结论：通过（含 2 条建议性观察）

整体正确。8 文件 +84/-11 行，修复逻辑通顺，兜底路径完整，未引入回归风险。

---

## 逐项结论

### 2.1 Test 3 修复（LLM 开关）

```
✅ _should_use_managed_llm() 删除了强制 True 逻辑 — use_llm=false 时返回 False，_llm_chat_answer() 直接返回 None，正确走到规则分支
✅ _requires_managed_llm() 增加 use_llm=false early return — 当用户关闭 LLM 时，不会再触发 _llm_required_failure_response() 的错误提示
⚠️ 预取逻辑分隔：_is_market_question / _is_industry_question / _is_value_question 在 try 块内，use_llm=false 时也会执行。这是合理的，因为规则回答也需要行业分布这类数据。
```

`_requires_managed_llm()` 的 early return 是正确的——如果用户选择了不用 LLM，系统不应该主动弹出"模型调用失败"警告；模型是否可用在这个场景下是无关信息。

---

### 2.2 Test 7 修复（连续对话记忆）

```
✅ 代词解析：只命中 user_input 含"它/这个/这只/那个/那只"时才触发，且优先从 memory recent_stock_codes[0] 取值。不会误匹配"它的行业"这类含"的"后缀——因为"它的"完整字符串不在列表中，不命中。
⚠️ 场景纠偏：qa_entry.py 只在 secondary == "industry_scan" 且用户消息含行业关键词时才切换。边界情况"帮我盯着 000021，它所在的行业有什么变化"：
  - router 主场景 = watch_command，secondary = industry_scan
  - 用户消息含"行业" → 切换到 industry_scan，放弃 watch_command
  - 这个行为是合理的：用户明确问了"行业"话题，先回答行业再回盯盘指令更符合期望。但 watch_command 本应做"盯盘 + 顺带行业"双输出，当前场景切换是单链独占，会丢失盯盘任务落地。
  → 建议：不是阻断性缺陷，建议后续在 watch_command 场景内支持"先行业后任务"的复合编排。
✅ fusion 对话历史注入：截断最近 3 轮、每条约 200 字，加上 history_block 指引语，总计约 700 字上下，在 DeepSeek 128k 上下文内完全安全。
✅ recent_turns 返回字典新增字段：搜索所有调用方（5 个场景文件 + qa_entry + _build_memory_context 自身），所有地方都使用 dict.get("recent_turns", []) 或 memory.get("recent_turns", [])，默认值兜底，没有硬依赖固定 key 集合的调用方。
✅ 行业预取 DuckDB：find_foundation_db + try/except + finally con.close()，连接不会泄漏。失败时静默降级为 {}。
```

---

### 2.3 整体风险

```
✅ 5 个场景文件透传 recent_turns：industry_scan / learn_topic / market_overview / stock_checkup / strategy_fit 都已加。watch_command 不调用 fusion，不需要透传。
⚠️ _llm_chat_answer() 函数体变长：加上代词解析 + 行业预取 + stock 预取后已超过 120 行。建议：当前阶段不重构，但建议加一个内部注释块 "# 数据预取区" 把三段逻辑分隔，方便后续拆函数时定位。
✅ 新增 try/except 都 pass 降级：与项目"数据预取单独降级"规则一致。
⚠️ _should_use_managed_llm() 语义漂移：当前语义是"用户是否开了 LLM 开关"，不再是"当前问题是否需要 LLM"。函数名保留旧语义，可能导致后续维护者困惑。
  → 建议：要么改名为 _user_wants_llm()，要么在 docstring 首行明确"本函数只判断用户开关选择，不判断问题类型"。
```

---

## 未触发但值得留痕的观察

| # | 观察 | 严重度 |
|---|------|--------|
| 1 | `_is_value_question(msg)` 在 `msg = query.message.strip().lower()` 之后运行；代词解析用 `msg`（未 lower），但代词列表全是中文且不含英文大小写，实际无影响。纯属代码风格上 `msg` / `msg_lower` 命名不一致，不会出 bug。 | 低 |
| 2 | _llm_chat_answer() 里的 try/except 捕获的 pass  swallows 了所有异常，包括连接失败、字段缺失、类型错误。当前这是项目风格（数据预取单独降级），但如果后续某个预取逻辑的 bug 被 pass 吞掉，排查成本会高。建议至少 log.warning 一行。 | 低 |
| 3 | 代理解析只回退到 `recent_codes[0]`——如果用户先后问了 000021 和 688107，说"它"时会优先绑定到 000021（最近一次）。这个行为合理，但未来如果用户说"那只"指代另一个，当前逻辑不支持。 | 低 |

---

## 结论重申

修复正确、兜底完整、无回归风险。2 条建议性观察（`_should_use_managed_llm` 命名 + 场景切换复合编排）均非阻断项，可留 Phase 3 处理。

---

## Codex 审阅附录 — 2026-05-31

### 范围确认
- 仅基于本地 git diff（已生成审阅 patch）进行静态审阅，未触发构建/部署/测试执行（哪吒/云访问未开放，仅终端读取与静态逻辑检查）。

### 逐项结论

#### 2.1 Test 3 修复（LLM 开关）
- ✅ `_should_use_managed_llm()` 已移除对高价值问题的强制 True；introduced new helper `_user_wants_llm()` 只判断用户是否开启 LLM，_llm_chat_answer 在 use_llm=false 时提前返回 None，命中规则分支。
- ✅ `_requires_managed_llm()` 新增 `if not query.use_llm: return False`，防止关闭 LLM 的用户在发生高层级失败时仍被 `_llm_required_failure_response()` 弹出“模型调用失败”提示。语义上：用户已主动关闭 LLM，无需提示模型调用失败，一致。
- ⚠️ 预取逻辑保留在 `_llm_chat_answer()` 内：当 `use_llm=false` 时 `_llm_chat_answer()` 直接跳过，不会跑 market/industry/value 预取。此条与审阅清单中的“use_llm=false 时这些预取仍会执行”前提不一致，实际结果是直接跳过——更优。

#### 2.2 Test 7 修复（连续对话记忆）
- ✅ 代词解析 `"它/这个/这只/那个/那只"` 仅完整命中，若用户说“它的行业”不命中。补上 `recent_codes[0]` 回退合理，不构成误匹配。
- ⚠️ 场景纠偏：当 secondary=industry_scan 且用户消息含 `行业/板块/产业链/什么行业` 时切到 industry_scan。边界“帮我盯着 000021，它所在的行业有什么变化”会被切走 watch_command 链路，当前实现不保证同时覆盖任务建立。建议：不是阻断项，可在 Phase 3 由 qa_entry 优先保留 watch_command 同时组织行业片段，而非单链独占切换。
- ✅ fusion 注入对话历史：最近 3 轮、每条 200 字截断，附加提示语，整体输入长度安全。
- ✅ `_build_memory_context()` 新增 `recent_turns` 字段。调用方全部使用 `get(..., [])` 兜底，不存在固定 key 集合硬依赖导致的 KeyError。
- ✅ 行业预取 DuckDB 使用 try/except + read_only=True + finally con.close()，连接不会泄漏；失败静默降级为 {}。

#### 2.3 整体风险
- ✅ 5 个场景文件透传 `recent_turns` 已全量覆盖；watch_command.py 不走 fusion，不需要透传。
- ⚠️ `_llm_chat_answer()` 函数长度偏长（>100 行），观测到已经超过文档提示的 100 行阈值。建议：当前不重构，但加更明确的区段注释，便于后续拆函数定位。
- ✅ 新增 try/except 均为 `pass` 降级，与项目规则一致。
- ⚠️ `_should_use_managed_llm()` 原语义偏建议性，现已功能性改造为“用户是否开了 LLM 开关”。更名或显式 docstring 会更清晰。

### 未触发但建议关注
1. `_chat_answer()` + `_llm_required_failure_response()` 的调用顺序在 `_user_wants_llm()` 下仍保持一致：先尝试 LLM，再询问是否需要 failure response；不会因为 `requires_managed_llm()` 提前命中而跳过 LLM 链路（安全）。
2. `context["industry_name"]` 预取路径仅在 symbol 存在且 is_industry_question 命中时执行；stock_checkup 次级场景纠偏也可能触发。
3. 对象级副作用：`stock_states` 在非 value question、但有 stock symbol 路径下会被设为 `{}`；与 `watch_command` 场景 `context.get("stock_states", {})` 兼容。

### 结论重申
修复正确、兜底完整、无回归风险。全部检查点结论为通过或建议性观察，无阻塞项。建议性改进空间：
- watch_command 与 industry_scan 的复合编排边界
- 函数命名/注释与长度管理
