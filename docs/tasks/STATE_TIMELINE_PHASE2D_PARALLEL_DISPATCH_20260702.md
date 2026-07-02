# State Timeline Observer Phase 2D 总分发文档

日期：2026-07-02  
状态：**Phase 2A-2D 全部完成，进入部署收口**

---

## 一、Phase 2 已完成内容

### Phase 2A — 页面核心功能（已完成）

- watchlist 真实接入：`symbol_set=watchlist` 读取当前用户的 active `watch_command` 标的。
- 状态变化摘要字段：`state_change_flag` / `ef_change` / `transition_label` / `ab_change` / `zero_change` 已接入页面与 API。
- 页面最小变化列、筛选器、表头与 API 对齐。
- 验收：`validate_website_data_sync.py --date 20260702` 通过；`pm_test_preflight.py --date 2026-07-02` 17/17 passed。

相关文件：
- `web/templates/state-observer.html`
- `web/main.py`
- `agently_adapter/tools/state_timeline_reader.py`
- `tests/unit/test_state_observer_api.py`

### Phase 2B — 每日邮件摘要（已完成）

- 实现 `scripts/send_state_timeline_digest_email.py`
- HTML 邮件模板含免责声明、事件族分组（EF / A+B / 0 / 周期交集 / 状态变化 Top20）
- 支持 `--dry` 预览
- 已接入 `config/hermes_cron.json`（交易日 16:30）

相关文件：
- `scripts/send_state_timeline_digest_email.py`
- `config/hermes_cron.json`
- `tests/unit/test_send_state_timeline_digest_email.py`

### Phase 2C — 订阅派发（已完成）

- `--dispatch-subscriptions` 模式从 `user_task_ledger` 读取 active `state_timeline_digest` 订阅
- 按 `email/symbol_set/days` 独立发送，单订阅失败不影响其他
- 已实发至 `3393639019@qq.com` 成功

相关文件：
- `scripts/send_state_timeline_digest_email.py`

### Phase 2D — 订阅管理增强 + 派发日志（已完成）

- 订阅更新：`POST /api/state-observer/subscriptions/{task_id}/update`，仅 owner 可更新，保持去重。
- 派发日志持久化：`outputs/user_tasks/state_timeline_dispatch_log.jsonl`，字段含 `task_id/email/dispatch_date/status/error/created_by/symbol_set/days/timestamp`。
- 页面展示：订阅表新增“最近派发日”“最近结果”，支持点击修改回填表单。
- 用户隔离：`GET /api/state-observer/subscriptions/dispatch-logs` 仅返回当前用户拥有订阅的日志。

相关文件：
- `web/main.py`
- `web/templates/state-observer.html`
- `agently_adapter/tools/user_tasks.py`
- `scripts/send_state_timeline_digest_email.py`
- `tests/unit/test_user_tasks_api.py`
- `tests/unit/test_send_state_timeline_digest_email.py`
- `docs/tasks/STATE_TIMELINE_PHASE2D_SUBSCRIPTION_MANAGEMENT_DELIVERY_20260702.md`

### KIMI2 — 物化表默认启用策略（已完成）

- `materialized=None` 时默认走智能 auto
- 单日 + 物化文件存在 → 优先物化表；跨天 / 文件缺失 / 文件损坏 → 自动回退实时 CTE
- 环境变量 `USE_STATE_TIMELINE_MATERIALIZED` 默认 `1`，可设 `0` 全局关闭
- API `meta` 新增 `materialized_requested` / `materialized_used` / `materialized_reason`
- `/api/admin/data-sync-status.state_timeline_materialized` 新增 `healthy` / `enabled_by_default` / `auto_would_use`

相关文件：
- `web/services/state_timeline_observer.py`
- `web/main.py`
- `tests/unit/test_state_timeline_runtime_switch.py`
- `tests/unit/test_state_timeline_materialize.py`
- `docs/tasks/STATE_TIMELINE_PHASE2D_MATERIALIZED_POLICY_DELIVERY_20260702.md`

---

## 二、当前接口与状态契约

### `/api/state-observer`

- 查询参数：`symbols`, `symbol_set`, `date_from`, `date_to`, `days`, `filters`, `page`, `page_size`, `format`, `materialized`
- `materialized=1`：强制物化表（单日 + 文件存在）
- `materialized=0`：强制实时 CTE
- 不传：智能 auto（默认启用）
- 返回行包含：`state_change_flag` / `ef_change` / `transition_label` / `ab_change` / `zero_change`

### `/api/state-observer/export`

- `POST /api/state-observer/export`：创建 CSV 导出任务
- `GET /api/state-observer/export/{task_id}`：查询任务状态
- `GET /api/state-observer/export/{task_id}/download`：下载 CSV
- 支持全市场 / 长时间窗异步导出，7 天产物清理

### `/api/state-observer/subscriptions`

- `GET`：列出当前用户 active 订阅
- `POST`：创建订阅
- `POST /{task_id}/update`：更新订阅参数
- `POST /{task_id}/cancel`：取消订阅
- `GET /dispatch-logs`：最近派发日志（用户隔离）

### `/api/admin/data-sync-status`

```json
{
  "state_timeline_materialized": {
    "path": "...",
    "exists": true,
    "size": 123456,
    "date": "2026-07-02",
    "row_count": 5519,
    "healthy": true,
    "enabled_by_default": true,
    "auto_would_use": true
  }
}
```

---

## 三、Cron 接入

`config/hermes_cron.json` 已新增：

- State Timeline 每日预计算（15:33）
- State Timeline 每日邮件摘要（16:30）
- State Timeline 导出产物清理（02:00）

---

## 四、验收标准（全部达成）

1. ✅ `symbol_set=watchlist` 返回真实 active watch_command 对应的 State Timeline
2. ✅ `/api/state-observer` 返回行包含 `state_change_flag` / `ef_change` / `transition_label`
3. ✅ `POST /api/state-observer/export` 对全市场/长时间窗返回任务 ID，任务完成后可下载 CSV
4. ✅ `scripts/send_state_timeline_digest_email.py --dry` 生成完整 HTML 邮件
5. ✅ `agently_adapter/tools/state_timeline_reader.py` 单元测试通过
6. ✅ `validate_website_data_sync.py --date YYYYMMDD` 仍通过
7. ✅ 默认 `materialized=None` 单日查询命中物化表，跨天自动回退 CTE

---

## 五、本地验收命令

```bash
cd /Users/lv111101/Documents/hermass-observer-product
source .venv/bin/activate

python -m py_compile web/main.py agently_adapter/tools/user_tasks.py scripts/send_state_timeline_digest_email.py web/services/state_timeline_observer.py web/services/state_timeline_export_worker.py
python -m pytest tests/unit -q
```

最新结果：`646 passed, 1 warning`

---

## 六、禁止事项

- 不要把 `ef_count` 重新提升为邮件或页面主口径
- 禁止在邮件/页面/导出中出现买入、卖出、目标价、止损价
- 不要把 A/B 或 0 事件族隐藏或降级
- 不要把 Observer 查询结果大规模写入 `AgentMemory.duckdb`
- 禁止在服务器上直接改业务逻辑或用系统 Python 编译

---

## 七、下一步建议

1. **Codex 最终 diff 审计**：审阅所有 Phase 2 diff，确认 `web/services/state_timeline_observer.py` 无冲突。
2. **统一部署与冒烟**：
   ```bash
   git pull
   source .venv/bin/activate && python -m py_compile web/main.py
   sudo systemctl restart hermass-console
   curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/state-observer
   ```
3. **持续监控**：观察 `state_timeline_dispatch_log.jsonl` 与导出任务状态，确保 cron 稳定运行。
