# State Timeline Phase 2D 导出稳态加固交付

日期：2026-07-02  
执行者：KIMI  
审计与收口：Codex

---

## 1. 完成内容

### A. 任务日志文件锁（单机多进程安全）

- `web/services/state_timeline_export_worker.py`
  - 保留 `threading.Lock` 保证同进程线程安全。
  - 新增 `_task_log_file_lock`：在 macOS/Linux 使用 `fcntl` 对 `task_log.jsonl` 加独占/共享锁，无 `fcntl` 时降级为线程锁。
  - `_append_task_record` 与 `_read_latest_record` 均使用「线程锁 + 文件锁」双层保护，并发追加不会损坏 JSONL。
  - 写完后显式 `flush` + `fsync`，降低进程崩溃丢数据风险。

### B. 任务状态机加固

- 定义合法转移：
  - `queued -> running / failed`
  - `running -> completed / failed`
  - `completed -> expired`
  - `failed` / `expired` 为终态
- 新增 `_advance_task_record()`：推进状态时校验转移合法性。
- `run_export_task()` 改用状态机推进，非法转移会报错。
- `get_task_status()` 增强：
  - 已完成但产物文件缺失时，状态返回 `expired`，`file_present=False`，`download_path=""`。
  - 保留 `expired_at`、`error` 等字段。

### C. 下载接口明确返回过期状态

- `web/main.py` `/api/state-observer/export/{task_id}/download`
  - 任务状态为 `expired` 或产物文件被清理时，返回 `410 Gone` + `{"ok":false,"error":"file expired or cleaned","file_present":false}`，不再返回模糊 404。

### D. 清理策略收口

- 新增 `scripts/clean_state_timeline_exports.py`
  - `--retention-days`：默认 7 天。
  - `--dry-run`：扫描并报告将要清理的文件，不实际删除。
  - 删除超期 CSV 文件，跳过 `running` / `queued` 任务文件。
  - 对已删除文件对应任务追加 `expired` 记录。
- 更新 `config/hermes_cron.json` 中 "State Timeline 导出产物清理" 任务，改为调用新脚本，保持每日 02:00 执行。

### E. 单元测试

- `tests/unit/test_state_observer_export.py`
  - 并发追加不损坏 JSONL（多进程）。
  - 状态机合法/非法转移。
  - `_advance_task_record` 推进与拒绝。
  - 文件缺失时 `expired`、文件存在时 `completed`。
  - `mark_task_expired` 与幂等性。
  - `clean_old_exports` 删除并标记 expired、跳过运行中任务、保留近期文件。
- `tests/unit/test_state_observer_api.py`
  - 新增：产物过期后下载接口返回 `410`。

### F. 接口冒烟

- 本地启动 8020 服务，创建全市场异步导出任务。
- 验证：完成后状态为 `completed`、`file_present=true`、可下载。
- 手动删除 CSV 文件后，状态变为 `expired`、`file_present=false`，下载返回 `410 Gone`。
- 冒烟后已清理测试数据。

---

## 2. 修改文件

- `web/services/state_timeline_export_worker.py`
- `web/main.py`
- `scripts/clean_state_timeline_exports.py`（新建）
- `config/hermes_cron.json`
- `tests/unit/test_state_observer_export.py`
- `tests/unit/test_state_observer_api.py`
- `docs/tasks/STATE_TIMELINE_PHASE2D_EXPORT_HARDENING_DELIVERY_20260702.md`（本文件）

---

## 3. 本地验收命令与结果

```bash
cd /Users/lv111101/Documents/hermass-observer-product
source .venv/bin/activate
python -m py_compile web/services/state_timeline_export_worker.py
python -m py_compile web/main.py
python -m py_compile scripts/clean_state_timeline_exports.py
python -m pytest tests/unit/test_state_observer_export.py -q
python -m pytest tests/unit/test_state_observer_api.py -q
```

结果：

```text
py_compile OK
tests/unit/test_state_observer_export.py .......................  [23 passed]
tests/unit/test_state_observer_api.py ..........                  [10 passed]
```

扩展验证：

```bash
python -m pytest tests/unit/test_user_tasks_api.py tests/unit/test_state_timeline_reader.py -q
python scripts/clean_state_timeline_exports.py --dry-run --retention-days 7
```

结果：`tests/unit/test_user_tasks_api.py 15 passed`，`test_state_timeline_reader.py 10 passed`；dry-run 无候选清理项。

接口冒烟结果：

| 场景 | 结果 |
|---|---|
| 创建全市场异步导出 | 200，task_id 返回，estimated_rows=22054 |
| 完成后查状态 | `completed`，`file_present=true`，`download_path` 非空 |
| 删除 CSV 后查状态 | `expired`，`file_present=false`，`download_path` 为空 |
| 删除 CSV 后下载 | `410 Gone`，`error=file expired or cleaned` |

---

## 4. 风险 / 未完成项

- **Windows 部署**：`fcntl` 不可用，降级为 `threading.Lock`，多进程 Windows 部署仍不安全；当前项目实际运行在 macOS/Linux，可接受。
- **分布式多机部署**：文件锁只能保证单机多进程安全，多机部署仍需外部锁（如分布式文件锁或数据库）。
- **KIMI1 / KIMI2 待执行**：订阅管理增强与物化表默认策略不属于本次范围。
- **JSONL 长期体积**：任务日志只追加不裁剪，长期运行可能变大；当前每日清理任务仅追加 expired 记录，未做日志轮转，可后续评估。

---

## 5. 是否可进入 git add / commit / push

是。本次修改已通过本地编译、单元测试与接口冒烟，可按规范进入 git add / commit / push 流程。
