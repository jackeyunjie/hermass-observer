# 2026-05-31 复合场景编排设计审阅

## 总判断：可以开始实现，含 4 条必改 + 2 条建议

设计方向正确。规则合并（不走 LLM）控制住了延迟；首批只做 watch_command + industry_scan 收敛得当。

---

## 逐项结论

### 2.1 设计层面

```
✅ 触发条件：关键词表【盯着/提醒/突破/止损】+【行业/板块/产业链】的组合是合理的。
  实际覆盖：用户说"帮我盯着 000021，这个行业有什么变化"全命中。
  但当前判定"两条都非空"这个门槛太低——router 的 secondary 字段经常非空（见 Test 7 的场景纠偏），
  导致大量"主 watch_command + secondary industry_scan"被误触发。
  → 必须改：触发条件改为"主任务场景关键词 AND 次场景关键词 AND 消息长度 > 12 字"。
  或者更稳妥：只当用户消息显式包含两个场景关键词时才判定为复合（现有表格已做到），
  但 router 必须把 secondary 设为"" 而不是"industry_scan"当用户没提行业时。

✅ 合并策略：规则化合并正确，不用 fusion。sequencial LLM 合并会多一次调用，
  而规则合并已经能拼出完整的结构化响应。将来如果需要，可以加 Phase C：
  "如果两条链都成功了再用 fusion 润色"作为可选增强。

⚠️ 合并字典未定义：设计方案没明确最终合并结果里 task_card 字段怎么来。
  watch_command 当前把任务信息写在 answer/freshness_note 文字里，不是 task_card dict。
  文档里写"task_card = watch_command 的任务卡片"暗示存在一个结构化对象——实际上还没有。
  → 必改：要么由 _chat_answer() 的规则侧从文本解析出 task_card（太重），
      要么 watch_command 先把"任务待配置"信息结构化地写入一个内部字段，
      复合编排时把这个字段提升到返回顶层。
```

### 2.2 实现层面

```
✅ 同一股票代码约束：设计方案的路由条件已经限制了"股票代码存在"。
  具体来说：watch_command 要求 symbol 非空（见 watch_command.py:12），
  industry_scan 只要用户消息含行业词就能跑。
  边界"帮我盯着 000021，电子行业怎么样"→ compound 触发 ✓
  边界"电子行业怎么样"→ 只有 industry_scan，不触发 ✓
  边界"帮我盯着 000021"→ 只有 watch_command，不触发 ✓
  边界"帮我盯着 000021，再看看 688010 怎么样"→ 含两只代码、stock_checkup 关键词，
    当前逻辑绑定 symbol=000021（ pronoun fallback 优先最近历史），
    不会把 688010 拉进 industry_scan——合理，但略粗暴。
  → 建议：不是阻断。

⚠️ _execute_compound() 失败策略：设计方案写"任一子链失败时整体回退到主场景"。
  但设计文档 1.2 节的合并策略里没体现这个逻辑——只写了成功路径。
  → 必改：明确写"subchain_failed → 降级为只保留成功子链的结果；两者都失败 → 主场景 fallback response"。
  当前 _llm_chat_answer() 里有 try/except 降级（见 Test 7 修复），qa_entry 里也有 _fallback_response，
  但 compound 的故障语义需要显式定义，否则后续维护者以为"有一处兜底"其实两处不覆盖同一个分支。

⚠️ watch_command 作为子链：当前 watch_command.run() 返回完整的 ChatResponse 结构，
  作为子链时诊断逻辑会再调一次 diagnoser-run()（与 stock_checkup 共用）。
  主链 watch_command 调 diagnoser → 返回结果。复合模式下 diagnoser 再调一次。
  两次 LLM 调用负担不均—— diagnoser 调用代价较小（单 Agent），
  但 compound 总共要走的 LLM 调用数：watch_command(diagnoser) + industry_scan(judge + industry + translator + fusion)
  = 1 + 4 = 5 次，在 DeepSeek 平均 3s / 调用下约 15s，用户体感略慢但可接受。
  → 建议：不是阻断，但应该在真实 API 环境里测一次 total latency。
```

### 2.3 风险

```
⚠️ 触发条件的 router 联动：router 已经会把"行业"相关问题的 secondary 设为 industry_scan。
  当前 qa_entry.py 的二次纠偏（Test 7 修复）已经把 secondary 切换逻辑做进去了。
  复合模式的触发的重复：如果 router 已经切到了 industry_scan（主场景 = industry_scan），
  复合模式不应该再触发，因为此时不需要 watch_command。
  → 必改：在 _execute_compound() 顶部加判断"if scenario_name == secondary: 不走 compound，
      直接走单链"。

✅ 并发 vs 串行：串行即可。两条链共享诊断结果（watch_command 的 diagnoser 结果可注入 context，
  industry_scan 不需要 diagnoser 结果），但串行已经 15s 内可接受。
  没必要加并发增加复杂度。

✅ Router 字段：继续沿用 secondary_scenario 字段，不需要新增 compound_scenarios。
  触发逻辑由 qa_entry 而非 router 负责，职责边界清晰。

✅ 测试：设计方案里没写测试，但 easy to add——在 qa_entry 测试里 mock 两个 scenario.run()，
  断言返回 dict 里同时有 task_card 和 answer。
  这个不是设计评审的范围，但提一句：实现时顺手加一条。
```

---

## 需要注意的设计遗漏

| # | 遗漏 | 严重度 | 建议 |
|---|------|--------|------|
| 1 | 合并结果里 `task_card` 字段的来源没定义（watch_command 没产出结构化 task_card） | 高 | watch_command 返回里加一个 `pending_task` 子字典 |
| 2 | 复合失败的故障语义没定义（两处都失败？一处失败？） | 高 | 在 `_execute_compound()` 顶部加显式分支 |
| 3 | 触发条件里 router secondary 经常非空的现状没有被考虑，会误触发 | 中 | 加"主场景 ≠ 次场景"的硬条件 |
| 4 |  串行 5 次 LLM 调用的延迟没在上线前做一次真实测量 | 低 | 有了 DeepSeek key 后测一次 P95 |

---

## 未讨论但被强制禁止提及的事项

- Phase 3（LLM 摘要）——按设计文档禁止讨论，跳过。
- Router prompt 重写——禁止，跳过。
- 新 Agent 引入——禁止，跳过。

---

## 总判断

**可以开始实现。** 修改范围精确（只动 qa_entry.py + watch_command.py），触发条件可安全收窄，合并策略方向正确。先补上面 4 条必改建议，再落代码。
