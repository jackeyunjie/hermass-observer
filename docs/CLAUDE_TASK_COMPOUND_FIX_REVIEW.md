# Claude Task — 支线 A 修复方案审阅

版本：v1.0
日期：2026-05-31
执行对象：Claude
目标：审阅 Test 10 失败修复方案

---

## 0. 背景

支线 A 部署后 KIMI 测试：11/12 通过。Test 10 失败。

Test 10 输入："帮我盯着 000021，这个行业有什么变化"
结果：provider=rule_based，被 `_detect_watch_command()` 规则拦截，复合检测 `_should_compound()` 从未被执行。

---

## 1. 根因分析

```
_chat_answer()
    ├─ _llm_chat_answer(query)
    │    └─ _user_wants_llm() → False (use_llm=false)
    │         → return None ❌ 连 _should_compound() 都进不去
    │
    └─ _detect_watch_command(query)
         → 拦截"帮我盯着..." → rule_based 响应 ❌
```

复合检测 `_should_compound()` 在 `qa_entry.handle()` 里，该函数只在 LLM 路径中调用（`_llm_chat_answer → handle`）。`use_llm=false` 时，`_llm_chat_answer` 直接返回 None，规则路径 `_detect_watch_command` 先拦截了输入。

---

## 2. 修复方案

### 2.1 新增函数

在 web/main.py 中 `_detect_watch_command()` 之前，新增：

```python
def _has_compound_intent(msg: str) -> bool:
    watch_kws = ["盯着", "帮我盯", "突破提醒", "止损提醒"]
    industry_kws = ["行业", "板块", "什么行业", "它的行业", "这个行业"]
    return (
        any(k in msg for k in watch_kws)
        and any(k in msg for k in industry_kws)
    )
```

### 2.2 调用点

在 `_chat_answer()` 中，`_llm_chat_answer()` 返回 None 后、`_detect_watch_command()` 之前插入：

```python
if not query.use_llm and _has_compound_intent(msg_lower):
    fake = ChatQuery(..., use_llm=True)  # 仅覆盖 use_llm
    llm_result = _llm_chat_answer(fake)
    if llm_result:
        return llm_result
```

### 2.3 改动文件

| 文件 | 改动 | 说明 |
|------|------|------|
| `web/main.py` | +28 行 | `_has_compound_intent()` + `_chat_answer()` 中 1 处插入 |

commit: `e59bc3c`

---

## 3. 审阅清单

- [ ] `_has_compound_intent` 的 watch_kws 和 industry_kws 是否覆盖了足够的关键词？有没有漏掉的复合意图模式？
- [ ] 在 `_chat_answer()` 中创建 fake ChatQuery 的做法：`use_llm=True` 覆盖是否会影响其他字段（mode/session_id/session_context）的正确行为？
- [ ] 如果 LLM 路径真的不可用（深 seek 宕机），这个 fake retry 也会返回 None → 回退到 rule_based。此时是否应该给用户一个提示说明"复合意图需要 LLM 但当前不可用"？
- [ ] `_has_compound_intent` 与 qa_entry.py 中的 `_should_compound()` 有关键词重复。是否需要统一到一处？还是当前双保险（先 rule 层拦截、再 LLM 层确认）合理？
- [ ] 如果用户开着 use_llm=true，正常走 `_llm_chat_answer` → `_should_compound`，这个修复是否不影响已有路径？

---

## 4. 输出格式

结论写在 `docs/2026-05-31_COMPOUND_FIX_REVIEW.md`：

```
✅ / ⚠️ / ❌  结论  —  建议
```

末尾给出「可以部署 / 需调整」判断。
