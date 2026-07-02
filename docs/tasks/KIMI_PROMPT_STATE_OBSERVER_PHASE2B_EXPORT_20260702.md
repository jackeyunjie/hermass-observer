# KIMI 提示词：State Timeline Observer Phase 2B 异步导出

日期：2026-07-02  
执行者：KIMI  
协调与收口：Codex

---

## 一、使用方式

把下面整段直接发给 `KIMI` 执行。

---

## 二、发给 KIMI 的完整提示词

你现在在 Hermass Observer 项目里执行 `State Timeline Observer` Phase 2B 的“异步导出”子任务。

先读以下文档，再动代码：

- `docs/STATE_TIMELINE_OBSERVER_SPEC.md`
- `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2_PLAN_20260701.md`
- `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2B_IMPLEMENTATION_AUDIT_20260701.md`
- `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2A_DELIVERY_20260701.md`

当前基线：

- `main` 已到 `5d320b9`
- `/state-observer`、`/api/state-observer`、`/api/state-observer/timeline` 已上线
- watchlist、变化字段、Agent SDK 已完成

你的目标只有一条：

```text
把 State Timeline 的大范围 CSV 导出改成可排队、可轮询、可下载的后台任务。
```

---

### A. 任务边界

你只负责异步导出，不负责：

- 邮件摘要
- 预计算表脚本
- cron 接入
- 服务器部署

尽量不要改：

- `web/services/state_timeline_observer.py`

优先修改文件：

- `web/main.py`
- `web/templates/state-observer.html`
- `web/services/state_timeline_export_worker.py`（新建）
- `tests/unit/test_state_observer_api.py`（如需补）
- `tests/unit/test_state_observer_export.py`（可新建）
- `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2B_EXPORT_DELIVERY_20260702.md`（新建）

不要改：

- `config/hermes_cron.json`
- `scripts/send_state_timeline_digest_email.py`
- `scripts/materialize_state_timeline_daily.py`

---

### B. 要实现的能力

必须新增 3 个 API：

1. `POST /api/state-observer/export`
2. `GET /api/state-observer/export/{task_id}`
3. `GET /api/state-observer/export/{task_id}/download`

导出逻辑要求：

1. 小查询继续同步
2. 满足以下任一条件时必须走异步：
   - `symbols == "all"` 且 `format == "csv"`
   - 估算行数 `> 10000`
   - 显式 `async=1`
3. 任务日志使用文件落地，目录：
   - `outputs/state_timeline_exports/task_log.jsonl`
4. 导出文件目录：
   - `outputs/state_timeline_exports/`
5. 导出字段顺序必须与现有 `format=csv` 同构
6. 下载接口必须带 `Content-Disposition`

后台执行方式：

- 不引入 Celery / Redis / 外部队列
- 使用项目内最简单可靠方案
- 推荐后台线程或等价轻量方式

---

### C. 前端要求

`/state-observer` 页面导出按钮要支持两种结果：

1. 小查询：直接下载
2. 大查询：提示“已创建后台导出任务”，并显示任务状态

最小可接受交互：

- 一个导出状态区域
- 能看到 `queued/running/completed/failed`
- 完成后能点击下载

不要重做整页 UI。

---

### D. 风险控制

1. 不要把大查询继续堵在请求线程里
2. 不要新增数据库依赖
3. 不要改现有 State Timeline 字段契约
4. 不要引入交易建议文案
5. 不要用系统临时目录做唯一真相，产物应留在项目 `outputs/`

---

### E. 本地验收要求

至少执行并记录结果：

```bash
cd /Users/lv111101/Documents/hermass-observer-product
.venv/bin/python -m py_compile web/main.py
.venv/bin/python -m py_compile web/services/state_timeline_export_worker.py
.venv/bin/python -m pytest tests/unit/test_state_observer_api.py -q
.venv/bin/python -m pytest tests/unit/test_state_observer_export.py -q
```

如果新增测试文件名不同，按实际路径执行。

另外要给出最小接口验收示例，例如：

```bash
curl -s -X POST http://127.0.0.1:8020/api/state-observer/export \
  -H 'Content-Type: application/json' \
  -d '{"symbol_set":"all","days":60,"format":"csv"}'
```

---

### F. 回复格式

完成后只按下面格式回复：

```text
1. 完成内容
2. 修改文件
3. 本地验收命令与结果
4. 风险 / 未完成项
5. 是否可进入 git add / commit / push
```

