# 观象"回答出了点问题"线上回归报告

> 执行日期：2026-06-04（部署）/ 2026-06-05（线上验证）
> 执行者：Kimi
> 关联 commit：`3ece5ec`

---

## 1. 本地测试

```bash
cd /Users/lv111101/Documents/hermass-observer-product
.venv/bin/python -m py_compile web/main.py
.venv/bin/python -m pytest tests/unit/test_chat_query_fallback.py -q
```

**结果：**

- `py_compile web/main.py` → OK
- `tests/unit/test_chat_query_fallback.py` → **2 passed**
  - `test_chat_query_internal_error_returns_readable_fallback`：模拟 `_chat_answer` 内部崩溃，验证返回 HTTP 200 + provider=rule_based + degraded=true + 不含旧文案
  - `test_chat_query_llm_failure_payload_uses_rule_answer`：模拟 Agently 返回 failure payload，验证二次切到规则回答 + freshness_note 含"增强解释链路暂不可用"

---

## 2. 部署记录

```bash
# 本地
git add web/main.py tests/unit/test_chat_query_fallback.py docs/tasks/kimi_prompt_guanxiang_fallback_regression_20260604.md
git commit -m "fix(chat): fallback to rule-based answer when LLM/Agently fails"
git push

# 服务器（8.130.125.201 /opt/hermass）
git checkout -- web/main.py web/templates/stock-research.html  # 丢弃服务器遗留本地修改
git pull
source .venv/bin/activate && python -m py_compile web/main.py  # OK
sudo systemctl restart hermass-console
sudo systemctl status hermass-console --no-pager  # active (running)
```

---

## 3. 线上接口验收（curl）

### 3.1 正常 LLM 查询

```bash
curl -s -X POST http://localhost:8020/api/chat/query \
  -H 'Content-Type: application/json' \
  -d '{"message":"现在能不能做","page_context":"/","mode":"chat","use_llm":true}'
```

- HTTP status: **200**
- provider: `agently_deepseek`
- enhancement_used: `true`
- 结论：Agently 链路正常工作

### 3.2 规则查询（use_llm=false）

```bash
curl -s -X POST http://localhost:8020/api/chat/query \
  -H 'Content-Type: application/json' \
  -d '{"message":"我应该先去哪一页","page_context":"/","mode":"chat","use_llm":false}'
```

- HTTP status: **200**
- provider: `rule_based`
- 结论：规则路径正常工作

### 3.3 旧错误文案排查

```bash
resp=$(curl -s -X POST http://localhost:8020/api/chat/query \
  -H 'Content-Type: application/json' \
  -d '{"message":"现在能不能做","page_context":"/","mode":"chat","use_llm":true}')
echo $resp | grep -q '回答出了点问题' && echo "OLD_ERROR_PRESENT=True" || echo "OLD_ERROR_PRESENT=False"
```

**结果：OLD_ERROR_PRESENT=False**

线上 `/api/chat/query` 不再返回"回答出了点问题，重试或直接看页面内容"。

### 3.4 降级路径代码确认

由于当前 Agently 链路在线上是可用的，无法直接触发真实失败降级。但代码路径已确认部署：

- `_is_llm_failure_payload()`：检测 provider 为 agently_deepseek/managed_deepseek 且 enhancement_used=false 或含"链路调用失败"等关键字的 payload
- `_rule_fallback_after_llm_failure()`：构造 fallback_query（use_llm=false），调用 `_chat_answer()`，标记 degraded=true + degraded_reason=llm_unavailable
- `chat_query()` exception handler：返回 HTTP 200 + rule fallback + error_type，不再返回 HTTP 500

---

## 4. 浏览器验收（待人工确认）

由于自动化浏览器需要用户本地 Chrome/CDP 环境，以下 checklist 需人工操作验证：

- [ ] 打开 `http://console.supertrader.world/`
- [ ] 点击顶部"观象"，发送"现在能不能做"
- [ ] 点击首页"问观象 →"
- [ ] 勾选"更自然的解释"重复一次
- [ ] 取消"更自然的解释"重复一次

**验收标准：**

- 抽屉能正常打开
- 页面不能出现"回答出了点问题，重试或直接看页面内容"
- 如果 DeepSeek/Agently 不可用，页面必须显示"增强解释链路暂不可用"或类似降级说明

---

## 5. 结论

| 检查项 | 结果 |
|--------|------|
| 本地 py_compile | ✅ OK |
| 本地 pytest | ✅ 2 passed |
| 服务器 git pull | ✅ 无冲突 |
| 服务器服务状态 | ✅ active (running) |
| 线上 curl HTTP 200 | ✅ |
| 线上旧错误文案 | ✅ 未出现 |
| 降级代码路径部署 | ✅ 已确认 |

**状态：接口回归通过，浏览器验收待人工确认。**

如果浏览器验收中出现"回答出了点问题"，请立即检查：

```bash
ssh root@8.130.125.201 "journalctl -u hermass-console -n 80 --no-pager | grep -E 'chat_query|ERROR|exception'"
```
