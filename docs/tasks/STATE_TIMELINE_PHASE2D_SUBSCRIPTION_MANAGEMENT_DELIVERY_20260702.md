# State Timeline Phase 2D 订阅管理与派发日志交付 · 2026-07-02

## 完成内容

基于已上线 Phase 2C，补齐订阅“可管理、可追踪”的产品闭环：

1. **订阅更新能力**
   - 新增 `POST /api/state-observer/subscriptions/{task_id}/update`
   - 支持修改邮箱、集合（symbol_set）、时间窗口（days）
   - 仅 owner 可更新，更新后仍保持同一 owner 下去重

2. **派发日志持久化**
   - `scripts/send_state_timeline_digest_email.py` 在每次非 dry 派发后写入
     `outputs/user_tasks/state_timeline_dispatch_log.jsonl`
   - 日志字段：`task_id`, `email`, `dispatch_date`, `status`, `error`, `created_by`, `symbol_set`, `days`, `timestamp`
   - `status` 取值为 `sent` / `empty` / `failed`

3. **站内最近派发状态展示**
   - `/state-observer` 订阅表新增“最近派发日”“最近结果”两列
   - 页面通过 `GET /api/state-observer/subscriptions/dispatch-logs` 拉取当前用户拥有订阅的最新日志
   - 支持点击“修改”按钮回填表单，保存时走 update API

## 修改文件

- `web/main.py`
  - 新增 `POST /api/state-observer/subscriptions/{task_id}/update`
  - 新增 `GET /api/state-observer/subscriptions/dispatch-logs`（用户隔离）
- `web/templates/state-observer.html`
  - 订阅表增加“最近派发日”“最近结果”列
  - 新增 `editSubscription`、`cancelSubscriptionEdit`、`formatDispatchStatus`
  - `createSubscription` 支持新增/更新双模式
- `agently_adapter/tools/user_tasks.py`
  - 新增 `update_state_timeline_subscription`
- `scripts/send_state_timeline_digest_email.py`
  - 新增 `_write_dispatch_log`、`load_recent_dispatch_logs`
  - `_dispatch_subscriptions` 非 dry 模式下每次派发后写日志
- `tests/unit/test_user_tasks_api.py`
  - 新增订阅更新成功、越权、重复、派发日志 API 隔离等测试
- `tests/unit/test_send_state_timeline_digest_email.py`
  - 新增 `_write_dispatch_log`、日志读取、派发成功/失败写日志等测试

## 未改文件

- `web/services/state_timeline_export_worker.py`：未改动
- `web/services/state_timeline_observer.py`：未改动
- `config/hermes_cron.json`：Phase 2C 已接入派发任务，本次无需调整

## 本地验收命令与结果

```bash
cd /Users/lv111101/Documents/hermass-observer-product
source .venv/bin/activate

python -m py_compile web/main.py agently_adapter/tools/user_tasks.py scripts/send_state_timeline_digest_email.py
python -m pytest tests/unit/test_user_tasks_api.py tests/unit/test_send_state_timeline_digest_email.py -q
```

结果：

```
33 passed, 1 warning
```

（StarletteDeprecationWarning 为 httpx 版本提示，不影响功能。）

## 页面 / API 冒烟说明

1. 打开 `http://localhost:8020/state-observer`，在“邮件订阅”区域新增订阅。
2. 列表出现该订阅，最近派发日/结果初始为 `-`。
3. 点击“修改”按钮，表单回填，修改天数或集合后保存，列表即时刷新。
4. 运行一次派发（或 dry run 预览）：
   ```bash
   .venv/bin/python scripts/send_state_timeline_digest_email.py --dispatch-subscriptions --date 2026-07-02 --dry
   ```
   真实派发（写日志）请去掉 `--dry` 并配置 SMTP。
5. 刷新 `/state-observer` 页面，订阅行显示最近派发日与结果。

## 风险 / 未完成项

- 日志文件为 JSONL 追加写，长期运行后可能变大；当前未做按日期轮转，如需轮转可在后续阶段补充。
- 派发日志按 `created_by` 用户隔离返回；访客（visitor）订阅在换浏览器/清 cookie 后可能无法看到自己的日志，与现有访客任务隔离策略一致。

## 是否可进入 git add / commit / push

是。所有本地验收通过，未改导出 worker 与物化查询层。
