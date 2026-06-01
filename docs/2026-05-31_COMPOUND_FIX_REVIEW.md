# 2026-05-31 复合场景编排 — 二次修复审阅

版本：v1.0  
审阅对象：e59bc3c（前置拦截）+ 7b68349（双向兜底 + 顺序规范化）  
文件：`agently_adapter/qa_entry.py`（+40/-22）+ `web/main.py`（+28）

---

## 总结论：通过（含 3 条观察，2 条建议，1 条需要后续处理）

根因修复正确。两个 commit 合起来是完整闭环——e59bc3c 解决"规则路径先拦截台 ompos"的问题，7b68349 解决"router 失败时 secondary 为空与缺反向 fallback"的问题。无回归风险。

---

## 逐项结论

### 修复 1：双向集合匹配（7b68349 — `_should_compound`）

```python
# 修复前
if primary == p and secondary == s and ...

# 修复后
pair = {primary, secondary}
if pair == {p, s} and ...
```

✅ **正确**。集合消序使 watch_command → industry_scan 和 industry_scan → watch_command 两个方向都成立。现有 COMPOUND_PAIRS 只有一对 `(watch_command, industry_scan)`，集合匹配后双向一致，无歧义。

### 修复 2：`_compound_fallback_secondary` 推断 secondary

```python
def _compound_fallback_secondary(primary: str, user_input: str) -> str:
    msg = user_input.strip().lower()
    for p, s, p_kws, s_kws in COMPOUND_PAIRS:
        if primary == p and _has_keywords(msg, s_kws):
            return s
        if primary == s and _has_keywords(msg, p_kws):
            return p
    return ""
```

✅ **设计正确**——当 router 失败（`route is None`，secondary="" ）时，从 primary 方向反推另一端。

⚠️ **副作用有待理解**：当前调用发生在 `handle()` 的 line 176：

```python
secondary = _compound_fallback_secondary(scenario_name, user_input)
```

这里的 `scenario_name` 来自 `_keyword_fallback_route()`，在 router 失败时是"watch_command"或任意被 keyword 匹配的场景。`_compound_fallback_secondary` 会遍历 COMPOUND_PAIRS，检查 user_input 是否含 watch 关键词——如果用户只是说"帮我盯着 000021，突破周线提醒我"（**不含行业关键词**），`_has_keywords(msg, s_kws)` 为 False，返回 ""，`_should_compound` 返回 False，复合不触发。行为正确。

但如果用户说"帮我盯着 000021"（仅任务词），`_compound_fallback_secondary` 返回 ""，不触发。正确。  
如果用户说"电子行业有什么变化"（仅行业词）， `_keyword_fallback_route` 返回 `"industry_scan"` 作为主场景，_compound_fallback_secondary 对 primary=industry_scan 检查 p_kws（行业关键词）会命中 → secondary 推断为 watch_command。这会导致**无任务意图的行业问题被误判为复合**。`_should_compound` 会在下一步检查用户消息是否同时含两组关键词来过滤，但**推断本身降低了触发门槛**。

> **建议（非阻断）**：`_compound_fallback_secondary` 的"主动推断"放过了空消息权利，建议加一个更严格的触发前提——或限制"空 secondary 时才触发推断"且需要 primary 已经含某些特定词。当前行为不会出错，但边界较窄，后续维护者可能不理解"为什么无任务意图的行业扫描偶尔也被复合"。

### 修复 3：`_execute_compound` 顺序强制规范

```python
task_scenario = "watch_command"
answer_scenario = "industry_scan"
```

✅ **顺序正确**——watch_command 先跑，产出 task_card + remembered_stock_code；industry_scan 再跑，产出 answer/why。合并时 task_card 才存在可被提升。

⚠️ **hardcode 局限**：当前 COMPOUND_PAIRS 只有一对，hardcode 可行。但如果后续扩展到 stock_checkup+industry_scan（如"分析下这只，它是什么行业"），stock_checkup 不是 task_scenario，"task_card"字段就不存在，`result.setdefault("task_card", task_result.get("task_card"))` 会为空。`setdefault` 不会出错（因为 `task_result.get("task_card")` 返回 None），空值后融合层不会显示任务卡，但也不会 crash。行为降级正确，但不优雅。

> **建议**：如果 Phase 3 扩展场景对，`task_scenario` 应由 COMPOUND_PAIRS 的元数据驱动（加一个 `task_provider` 标记），而非硬编码。

### 修复 4：`intent` 字段与 `_build_memory_context` 的兼容性

`_execute_compound`（qa_entry.py:111-115）设置的 intent：

```python
result.setdefault("intent", {
    "scenario": [primary, secondary],   # ← list
    ...
})
```

序列化后存入 turn.intent（JSON 字符串）。`_build_memory_context()` 的解析逻辑（web/main.py:2899-2902）：

```python
obj = _json.loads(raw)
sc = obj.get("scenario")
if sc:
    scenario_counts[sc] = scenario_counts.get(sc, 0) + 1
```

❌ **此处有 bug，但被 try/except 吞掉**：当 `scenario` 是 list 时（如 `["watch_command", "industry_scan"]`），`scenario_counts[sc]` 尝试将 list 作为字典键——raise TypeError，然后被第 2903 行的 `except Exception: pass` 静默吞掉。

效果是：用户最后若干轮复合场景的 intent 整个被忽略，user_preferred_scenarios 不包含它们，但不影响功能正确性（只是偏好统计不完整）。

> **建议（中优先级）**：有两种解法：
> - (a) `_build_memory_context` 里判断 if isinstance(sc, list): 循环计数
> - (b) intent 存 list 改为存 primary + secondary 两个分开的字段（拖主管复更大）
>
> 推荐 (a)，改动最小，一行。

这个 bug 的根因不是这两次 commit 引入的——早在 Phase 2 intent 追踪落地时，`qa_entry.handle()` 的普通分支（line 215-218）已经把 `scenario` 设为 list `[primary, secondary]` 了（当 secondary 为空时 list 单元素）。两次修复只是让复合场景的 list-scenario 出现在更多turn里，让这个 bug 暴露得更频繁。

### `_has_compound_intent` 的作用边界

e59bc3c 加的这个函数解决了关键问题：watch_command 原本由 `_detect_watch_command()` 在 `_chat_answer()` 里**直接拦截**（不经过 LLM），复合场景配置需要穿过拦截点。`_has_compound_intent` 做到了：

```python
if not query.use_llm and _has_compound_intent(msg_lower):
    fake = ChatQuery(..., use_llm=True)
    llm_result = _llm_chat_answer(fake)
```

✅ **正确**——它只在 `use_llm=false` 时才强制切换，不改变已开 LLM 的用户路径。fake ChatQuery 只改 use_llm，不污染别的字段。

⚠️ **构造 fake ChatQuery 的测试可维护性**：如果后续 ChatQuery 加了必填字段，这里会报错。建议改为改字段值再重用现 query，或把强制 LLM 逻辑移到 `_should_use_managed_llm()` 内部。当前不阻塞，因为 QA 层有字段默认值回退，但这属于技术债。

---

## 整体风险

```
✅ wire-up 范围精确：只动 qa_entry.py 和 _has_compound_intent 一个 web/main.py 函数，
   router、scenarios 文件、web layer 其余部分不动。
✅ 失败路径完整：两处子链都失败 → _fallback_response；一处失败 → 降级 + freshness_note 说明。
✅ 不新增 Agent，复用 diagnoser 和 judge。
✅ 无回归风险：现有单链执行路径不受影响。
```

---

## 未触发但值得留痕的观察

| # | 观察 | 严重度 |
|---|------|--------|
| 1 | `_compound_fallback_secondary` 对空 secondary 的推断可能让非复合意图触发复合（见上方"副作用"项） | 低 |
| 2 | intent.scenario 存 list 导致 `_build_memory_context`统计跳过——非阻断，但会降低记忆偏好图的准确率 | 低（建议尽快修） |
| 3 | _has_compound_intent 的行业关键词 `"它的行业"` 与 `_keyword_fallback_route` 不形成对称覆盖，用户说"它是什么行业"不会被复合检测命中，但会被 keyword fallback 路由到 industry_scan。行为上没问题，但不对称让人困惑 | 低 |
| 4 | _execute_compound 的 `task_card = task_result.get("task_card")` 会拿到 None（因为 watch_command 当前返回里没有 task_card dict），后续 web 层 `if data.task_card` 判断为 False，不会展示任务卡——实际上用户的"盯盘任务待配置"只留在 detailed answer 文字里，任务卡片 UI 不会出现 | 低（规划阶段已知，留 Phase 4 解决） |

---

## 结论重申

两 commit 修复方向正确，完成了"双向触发 + 顺序规范 + router 失败容错"的目标。有一个低严重度的已存在 bug（intent 存 list 导致 memory context 统计跳过）需要 Phase 3 顺手处理，但不阻塞当前交付。
