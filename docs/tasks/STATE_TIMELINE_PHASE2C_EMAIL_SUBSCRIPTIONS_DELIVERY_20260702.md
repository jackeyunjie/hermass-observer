# State Timeline Phase 2C 邮件订阅派发交付说明

日期：2026-07-02  
执行者：KIMI1  
范围：邮件摘要从单次发送升级为订阅批量派发

---

## 1. 完成内容

- `scripts/send_state_timeline_digest_email.py` 新增 `--dispatch-subscriptions` 模式
- 脚本从 `user_task_ledger.json` 读取 `task_type == "state_timeline_digest"` 且 `status == "active"` 的订阅
- 每条订阅按自己的 `email`、`symbol_set`、`days` 生成独立邮件并发送
- 保留原有单次 `--dry` / 单次发送模式不变
- 订阅派发过程中单个订阅失败不影响其他订阅
- `config/hermes_cron.json` 的邮件任务改为订阅派发模式
- 新增/更新单元测试覆盖订阅读取、过滤、批量派发

---

## 2. 修改文件

| 文件 | 说明 |
|------|------|
| `scripts/send_state_timeline_digest_email.py` | 新增 `_load_subscriptions`、`_send_one_digest`、`_dispatch_subscriptions`；`send_email` 支持自定义收件人；`main` 路由到订阅派发或单次模式 |
| `config/hermes_cron.json` | 「State Timeline 每日邮件摘要」改为 `--dispatch-subscriptions` 模式 |
| `tests/unit/test_send_state_timeline_digest_email.py` | 新增 3 个订阅相关测试 |
| `docs/tasks/STATE_TIMELINE_PHASE2C_EMAIL_SUBSCRIPTIONS_DELIVERY_20260702.md` | 本文档 |

未修改：

- `web/main.py`
- `web/templates/state-observer.html`
- `web/services/state_timeline_export_worker.py`
- `web/services/state_timeline_observer.py`
- `agently_adapter/tools/user_tasks.py`
- `AGENTS.md`

---

## 3. 本地验收命令与结果

### 3.1 编译

```bash
.venv/bin/python -m py_compile scripts/send_state_timeline_digest_email.py
```

结果：通过。

### 3.2 单元测试

```bash
.venv/bin/python -m pytest tests/unit/test_send_state_timeline_digest_email.py -q
```

结果：`13 passed in 0.36s`

### 3.3 cron JSON 校验

```bash
.venv/bin/python -m json.tool config/hermes_cron.json > /dev/null
```

结果：有效。

### 3.4 订阅派发 dry-run（使用测试账本）

```bash
cat > /tmp/test_subscriptions.json << 'JSON'
{
  "version": "1.0.0",
  "tasks": [
    {
      "task_id": "state_timeline_digest_20260702_001",
      "task_type": "state_timeline_digest",
      "email": "3393639019@qq.com",
      "symbol_set": "watchlist",
      "days": 3,
      "status": "active",
      "created_by": "visitor_NsUz96BhIgf59nV-"
    },
    {
      "task_id": "state_timeline_digest_20260702_002",
      "task_type": "state_timeline_digest",
      "email": "1300893414@qq.com",
      "symbol_set": "top50",
      "days": 2,
      "status": "active",
      "created_by": ""
    }
  ]
}
JSON

.venv/bin/python scripts/send_state_timeline_digest_email.py \
  --dispatch-subscriptions --date 2026-07-02 --dry \
  --subscription-ledger /tmp/test_subscriptions.json
```

结果：生成 2 份 HTML 摘要，无异常。

### 3.5 订阅派发真实发送（使用测试账本）

```bash
set -a && source .env && set +a
.venv/bin/python scripts/send_state_timeline_digest_email.py \
  --dispatch-subscriptions --date 2026-07-02 \
  --subscription-ledger /tmp/test_subscriptions.json
```

结果：

```text
邮件已发送 → 3393639019@qq.com
[DISPATCH OK 1/2] state_timeline_digest_20260702_001 email=3393639019@qq.com symbol_set=watchlist days=3
邮件已发送 → 1300893414@qq.com
[DISPATCH OK 2/2] state_timeline_digest_20260702_002 email=1300893414@qq.com symbol_set=top50 days=2
派发完成: 2/2 成功
```

---

## 4. 风险 / 未完成项

1. **订阅 CRUD 不在本线**：`state_timeline_digest` 订阅的创建/修改/删除由 `KIMI` 负责的后端 API 提供。本脚本只负责读取已存在的 active 订阅。
2. **SMTP 凭据仍走 `.env`**：cron command 中通过 `source .env` 加载，没有把密钥写入 `config/hermes_cron.json` 或仓库文件。
3. **无持久化派发日志**：当前仅输出到 stdout；如需文件日志，可后续落到 `outputs/state_timeline_subscriptions/`。
4. **无缓存**：多个订阅若使用相同 `symbol_set/days/user_key`，会重复加载数据。当前订阅量小，暂未做缓存；如订阅量增大可优化。
5. **watchlist 订阅依赖 `created_by`**：当 `symbol_set == "watchlist"` 时，脚本使用订阅的 `created_by` 字段作为 `user_key` 读取该用户的 watchlist。

---

## 5. 是否可进入 git add / commit / push

**可以。**

建议提交：

```bash
git add scripts/send_state_timeline_digest_email.py \
        config/hermes_cron.json \
        tests/unit/test_send_state_timeline_digest_email.py \
        docs/tasks/STATE_TIMELINE_PHASE2C_EMAIL_SUBSCRIPTIONS_DELIVERY_20260702.md
git commit -m "feat(state-observer): Phase 2C subscription-based email dispatch"
```

部署后验证：

```bash
.venv/bin/python -m py_compile scripts/send_state_timeline_digest_email.py
.venv/bin/python -m pytest tests/unit/test_send_state_timeline_digest_email.py -q
```
