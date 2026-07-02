# State Timeline Observer Phase 2B 邮件摘要交付说明

日期：2026-07-02  
执行者：KIMI  
范围：每日邮件摘要 + cron 配置

---

## 1. 完成内容

- 新增可 `dry-run` 的邮件脚本 `scripts/send_state_timeline_digest_email.py`
- 邮件结构覆盖：顶部摘要、月线/周线/日线 EF、月线/周线/日线 A/B、月线/周线/日线 0、周期交集、今日变化 Top20、自选池最近 3 天变化、底部免责声明与回链
- 在 `config/hermes_cron.json` 中接入交易日 16:30 的邮件摘要定时任务
- 同步增加 `outputs/state_timeline_exports` 目录的 7 天清理任务（为后续异步导出预留）
- 新增单元测试 `tests/unit/test_send_state_timeline_digest_email.py`

---

## 2. 修改文件

| 文件 | 说明 |
|------|------|
| `scripts/send_state_timeline_digest_email.py` | 新增邮件脚本，支持 `--date`、`--dry`、`--symbol-set`、`--days`、`--user-key` |
| `config/hermes_cron.json` | 新增「State Timeline 每日邮件摘要」和「State Timeline 导出产物清理」两个定时任务 |
| `tests/unit/test_send_state_timeline_digest_email.py` | 新增单元测试：HTML 生成、变化计算、空数据、禁用词检查 |
| `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2B_EMAIL_DELIVERY_20260702.md` | 本文档 |

未修改：

- `web/main.py`
- `web/templates/state-observer.html`
- `web/services/state_timeline_observer.py`
- `scripts/materialize_state_timeline_daily.py`
- `AGENTS.md`

---

## 3. 本地验收命令与结果

### 3.1 编译

```bash
.venv/bin/python -m py_compile scripts/send_state_timeline_digest_email.py
```

结果：通过。

### 3.2 dry-run 生成 HTML

```bash
.venv/bin/python scripts/send_state_timeline_digest_email.py --date 2026-07-01 --dry > /tmp/state_timeline_digest_20260701.html
```

结果：成功生成 HTML，包含所有要求分组。

### 3.3 带自选池的 dry-run

```bash
.venv/bin/python scripts/send_state_timeline_digest_email.py --date 2026-07-01 --user-key visitor_NsUz96BhIgf59nV- --dry > /tmp/state_timeline_digest_watchlist.html
```

结果：成功生成 HTML，包含「自选池最近 3 天变化」分组。

### 3.4 单元测试

```bash
.venv/bin/python -m pytest tests/unit/test_send_state_timeline_digest_email.py -q
```

结果：

```text
9 passed in 0.03s
```

### 3.5 cron JSON 校验

```bash
.venv/bin/python -m json.tool config/hermes_cron.json > /dev/null
```

结果：JSON 格式有效。

---

## 4. 风险 / 未完成项

1. **真实邮件发送未验证**：验收使用 `--dry` 模式，真实发送依赖 `HERMASS_SMTP_HOST/PORT/USER/PASS/REPORT_TO` 环境变量配置。
2. **自选池用户标识**：邮件脚本通过 `--user-key` 指定 watchlist 用户；cron 默认未带 `--user-key`，因此默认邮件不含 watchlist 分组。如需为特定用户发送，需在 cron command 中追加 `--user-key <user>`。
3. **导出清理 cron 提前接入**：清理任务针对 `outputs/state_timeline_exports` 目录，当前异步导出功能尚未实现，该 cron 为预留，不会产生副作用（目录不存在时 `mkdir -p` + `find` 安全退出）。
4. **`ab_change` / `zero_change` 查询层字段缺失**：当前 State Timeline 查询层仅返回 `ef_change`，邮件脚本在 Python 层按股票分组计算 `ab_change` 和 `zero_change`，用于变化强度排序。
5. **未实现异步导出 API**：Phase 2B 邮件线不涉及 `web/services/state_timeline_export_worker.py` 和 `/api/state-observer/export`。

---

## 5. 是否可进入 git add / commit / push

**可以。**

建议提交文件：

```bash
git add scripts/send_state_timeline_digest_email.py \
        config/hermes_cron.json \
        tests/unit/test_send_state_timeline_digest_email.py \
        docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2B_EMAIL_DELIVERY_20260702.md
git commit -m "feat(state-observer): Phase 2B daily digest email + cron"
```

部署后需验证：

```bash
.venv/bin/python scripts/send_state_timeline_digest_email.py --date 2026-07-01 --dry | head -c 200
sudo systemctl status hermass-console
```
