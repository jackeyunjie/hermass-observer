# Claude Task — 支线 A：复合场景编排设计审阅

版本：v1.0  
日期：2026-05-31  
执行对象：Claude  
目标：审阅 watch_command + industry_scan 复合编排的设计方案，确认可行后由本机 Trae 实现

---

## 0. 背景

今天完成了 Test 3（LLM 开关）和 Test 7（连续对话记忆）的修复，场景纠偏管道已打通。

当前系统能力：router 返回 `secondary_scenario`，但 `qa_entry.handle()` 只做**二选一切换**——要么走主场景，要么切到次场景。无法同时执行两个场景。

**目标**：当用户一句话包含两个意图时（如"帮我盯着 000021，这个行业有什么变化"），同时跑 `watch_command` + `industry_scan`，并将两个结果合并为一个完整响应。

---

## 1. 设计方案（待审阅）

### 1.1 触发条件

当 router 返回的 route 同时满足：
1. `scenario` 和 `secondary_scenario` 都非空
2. 用户消息包含两个场景的关键词（无需 LLM 判断，纯关键词匹配）

| 场景对 | 触发关键词（主） | 触发关键词（次） |
|--------|----------------|----------------|
| watch_command + industry_scan | 盯着/提醒/突破/止损 | 行业/板块/产业链 |
| watch_command + stock_checkup | 盯着/提醒/突破/止损 | 怎么样/分析/能买 |
| stock_checkup + industry_scan | 怎么样/分析 | 行业/板块 |

首批只实现 **watch_command + industry_scan**，其他场景对留待后续。

### 1.2 执行流程

```
router 返回 {scenario: "watch_command", secondary: "industry_scan"}
    ↓
关键词判定：复合场景触发
    ↓
┌─ 子链 1: watch_command.run(user_input, context)
│   产出：task_card, remembered_stock_code
└─ 子链 2: industry_scan.run(user_input, context)
    产出：answer, why, multi_cycle_view, ...
    ↓
合并策略（规则化，不走 LLM）：
- answer = industry_scan.answer
- task_card = watch_command 的任务卡片
- why = watch_command 的任务说明 + "\n\n" + industry_scan.why
- next_actions = watch_command 动作 + industry_scan 动作（去重）
- remembered_stock_code = symbol
- scenario = ["watch_command", "industry_scan"]
```

### 1.3 改动文件

| 文件 | 改动 | 行数 |
|------|------|------|
| `agently_adapter/qa_entry.py` | 新增 `_prepare_context()`、`_execute_compound()` 两个函数；`handle()` 中增加复合检测分支 | ~40 行 |
| `agently_adapter/scenarios/watch_command.py` | 支持作为子链执行时跳过最外层 fusion，返回结构化 dict 而非完整响应 | ~5 行 |

### 1.4 不变的部分

- Router 本身**不需要改**——它已经返回 `secondary_scenario`
- 5 个其他场景文件**不需要改**
- `_build_memory_context()` **不需要改**
- web/main.py **不需要改**

---

## 2. 审阅清单

### 2.1 设计层面

- [ ] 复合场景的触发条件（关键词匹配）是否太宽/太窄？
- [ ] 首批发 `watch_command + industry_scan` 是否覆盖了最高频场景？
- [ ] 合并策略（规则化拼接）是否可行？还是应该让 fusion Agent 来合并？如果用 fusion，会多一次 LLM 调用，延迟翻倍——权衡是否正确？

### 2.2 实现层面

- [ ] `watch_command.run()` 目前直接返回完整 dict。作为子链时，它是返回 `TaskCard` 结构，还是返回标记位让调用方组装？
- [ ] 复合执行时 context 的 `symbol` 字段——watch_command 和 industry_scan 共用同一个股票代码。如果用户说"帮我盯着 000021，电子行业怎么样"（两只不同的标的），这个场景不应触发复合模式——当前设计是否正确避免了这种情况？
- [ ] `_execute_compound()` 中任一子链失败时，是整体回退到主场景还是只降级保留成功的那个？

### 2.3 风险

- [ ] 复合模式下两次场景执行会增加延迟。watch_command 调了 diagnoser Agent，industry_scan 调了 4 个 Agent。并行执行还是串行？串行是 ~5 次 LLM 调用，当前可接受吗？
- [ ] 现有的 `route.get("scenario")` 和 `route.get("secondary_scenario")` 字段名——router 的输出格式是否需要显式加 `compound_scenarios` 字段？还是继续保持现在 secondary 的语义？
- [ ] 如果有复合场景的测试用例（如"帮我盯着 000021，这个行业有什么变化"），当前 router 能否正确识别出 `watch_command` + `industry_scan`？

---

## 3. 禁止事项

- 不讨论主线 Phase 3（LLM 摘要）、支线 B（value prompt pack）
- 不讨论 router prompt 重写（当前阶段不改 router）
- 不引入新的 Agent（复合编排只用现有 6 个 Agent）

---

## 4. 输出格式

审阅结论写在 `docs/2026-05-31_COMPOUND_SCENARIO_REVIEW.md`，格式：

```
✅ / ⚠️ / ❌  结论  —  建议
```

并在末尾给出「可以开始实现 / 需调整设计 / 需更多信息」的总判断。
