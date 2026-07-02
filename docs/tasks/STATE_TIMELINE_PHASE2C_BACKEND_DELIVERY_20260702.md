# State Timeline Phase 2C 后端鉴权与订阅 API 交付

日期：2026-07-02  
执行者：KIMI  
审计与收口：Codex

---

## 1. 完成内容

### A. 异步导出任务 owner 隔离

- `web/services/state_timeline_export_worker.py`
  - 创建任务时记录 `owner_key` / `owner_scope`（guest / user）。
  - 修复 `_normalize_query`：保留 `async` 强制异步标记，确保 `POST /api/state-observer/export {"async":1}` 能正确创建后台任务。
- `web/main.py`
  - 新增 `_check_export_ownership()`：校验当前身份是否匹配任务的 `owner_key` + `owner_scope`。
  - `GET /api/state-observer/export/{task_id}` 与 `GET /api/state-observer/export/{task_id}/download` 均已接入 owner 校验。
  - 非 owner 统一返回 `403 {"ok":false,"error":"forbidden"}`。

### B. State Timeline 邮件订阅 API

- `agently_adapter/tools/user_tasks.py`
  - 新增 `task_type = state_timeline_digest` 订阅记录。
  - 提供 `create_state_timeline_subscription()` / `list_state_timeline_subscriptions()` / `cancel_state_timeline_subscription()`。
  - 去重键：`created_by + email + symbol_set + days` 的 active 订阅。
  - 邮箱格式校验、`days` 边界保护（1-120）。
  - 复用现有 `user_task_ledger.json`，未新建第二套存储。
- `web/main.py`
  - `GET /api/state-observer/subscriptions`：按当前用户列出订阅。
  - `POST /api/state-observer/subscriptions`：创建订阅，重复返回 `409`，无效邮箱返回 `400`。
  - `POST /api/state-observer/subscriptions/{task_id}/cancel`：仅允许 owner 取消，非 owner 返回 `403`。

### C. 单元测试

- `tests/unit/test_state_observer_api.py`
  - 覆盖：导出创建时 owner_key / owner_scope 正确写入。
  - 覆盖：非 owner 访客、user 访问 guest 任务、guest 访问 user 任务均返回 `403`。
  - 覆盖：owner 可正常查看状态。
- `tests/unit/test_user_tasks_api.py`
  - 覆盖：访客创建/列表/取消订阅全流程。
  - 覆盖：用户间订阅隔离。
  - 覆盖：取消他人订阅返回 `403`。
  - 覆盖：重复订阅返回 `409`、无效邮箱返回 `400`。

### D. 接口冒烟

- 本地启动 `uvicorn web.main:app --host 127.0.0.1 --port 8020`。
- 验证：
  - 访客创建异步导出任务，owner 可查看状态/下载，其他访客与认证用户均 `403`。
  - 访客创建订阅、列表、取消均正常；他人取消返回 `403`。
- 冒烟后已清理测试数据（`user_task_ledger.json` / `task_log.jsonl` / CSV 产物）。

---

## 2. 修改文件

- `web/main.py`
- `web/services/state_timeline_export_worker.py`
- `agently_adapter/tools/user_tasks.py`
- `tests/unit/test_state_observer_api.py`
- `tests/unit/test_user_tasks_api.py`
- `docs/tasks/STATE_TIMELINE_PHASE2C_BACKEND_DELIVERY_20260702.md`（本文件）

---

## 3. 本地验收命令与结果

```bash
cd /Users/lv111101/Documents/hermass-observer-product
source .venv/bin/activate
python -m py_compile web/main.py
python -m py_compile web/services/state_timeline_export_worker.py
python -m py_compile agently_adapter/tools/user_tasks.py
python -m pytest tests/unit/test_state_observer_api.py -q
python -m pytest tests/unit/test_user_tasks_api.py -q
python -m pytest tests/unit/test_state_observer_export.py -q
```

结果：

```text
py_compile OK
tests/unit/test_state_observer_api.py .........    [9 passed]
tests/unit/test_user_tasks_api.py ..........       [10 passed]
tests/unit/test_state_observer_export.py ......... [9 passed]
```

接口冒烟结果：

| 场景 | 身份 | HTTP 状态 | 结果 |
|------|------|-----------|------|
| 创建异步导出 | owner 访客 | 200 | task_id 返回 |
| 查看状态 | owner 访客 | 200 | 状态可见 |
| 查看状态 | 其他访客 | 403 | forbidden |
| 查看状态 | 认证用户 | 403 | forbidden |
| 下载产物 | owner 访客 | 200 | 文件下载 |
| 下载产物 | 其他访客 | 403 | forbidden |
| 创建订阅 | owner 访客 | 200 | 订阅创建 |
| 列出订阅 | owner 访客 | 200 | 仅看自己 |
| 取消订阅 | 其他访客 | 403 | forbidden |
| 取消订阅 | owner 访客 | 200 | 已取消 |

---

## 4. 风险 / 未完成项

- **任务日志并发安全**：当前使用 threading 锁，单进程部署安全；多进程部署需补文件锁或迁移到 SQLite/DuckDB。
- **KIMI1 / KIMI2 待执行**：邮件派发脚本 `scripts/send_state_timeline_digest_email.py` 与 UI/物化表开关尚未接入，属于 Phase 2C 后续任务。
- **PM preflight 偶发**：`chat auth smoke: HTTP 0` 为网络/鉴权抖动，与本次后端修改无关。

---

## 5. 是否可进入 git add / commit / push

是。本次修改已通过本地编译、单元测试与接口冒烟，可按规范进入 git add / commit / push 流程。
