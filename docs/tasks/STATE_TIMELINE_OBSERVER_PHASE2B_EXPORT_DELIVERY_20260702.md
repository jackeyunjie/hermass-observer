# State Timeline Observer Phase 2B 异步导出交付说明

日期：2026-07-02  
执行者：KIMI  
范围：异步导出任务（P2-C）  
状态：本地完成，待审计

---

## 一、本周落地范围

按提示词只负责**异步导出**，不做：

- ❌ 邮件摘要
- ❌ 预计算表脚本
- ❌ cron 接入
- ❌ 服务器部署
- ❌ AGENTS.md 修改
- ❌ `web/services/state_timeline_observer.py` 核心查询逻辑修改

---

## 二、修改文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `web/services/state_timeline_export_worker.py` | 新增 | 导出任务创建、后台执行、任务日志、产物管理 |
| `web/main.py` | 修改 | 新增 3 个导出路由 + `FileResponse` 导入 |
| `web/templates/state-observer.html` | 修改 | 导出按钮支持同步/异步两种模式，显示任务状态 |
| `tests/unit/test_state_observer_export.py` | 新增 | 导出 worker 单元测试 |
| `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2B_EXPORT_DELIVERY_20260702.md` | 新增 | 本文档 |

未修改：

- `web/services/state_timeline_observer.py`
- `config/hermes_cron.json`
- `scripts/send_state_timeline_digest_email.py`
- `scripts/materialize_state_timeline_daily.py`
- `AGENTS.md`

---

## 三、API 设计

### 3.1 `POST /api/state-observer/export`

Body：

```json
{
  "symbols": "all",
  "symbol_set": "",
  "date_from": "2026-06-01",
  "date_to": "2026-07-01",
  "days": 60,
  "filters": {},
  "format": "csv",
  "async": 0
}
```

同步响应（小查询）：

```json
{
  "ok": true,
  "task_id": "",
  "status": "sync",
  "format": "csv",
  "estimated_rows": 1200,
  "download_path": ""
}
```

异步响应（大查询）：

```json
{
  "ok": true,
  "task_id": "state_timeline_export_20260702_db735bd6",
  "status": "queued",
  "format": "csv",
  "estimated_rows": 212218,
  "download_path": "/api/state-observer/export/state_timeline_export_20260702_db735bd6/download"
}
```

### 3.2 `GET /api/state-observer/export/{task_id}`

```json
{
  "ok": true,
  "task_id": "state_timeline_export_20260702_db735bd6",
  "status": "completed",
  "format": "csv",
  "estimated_rows": 212218,
  "row_count": 212218,
  "download_path": "/api/state-observer/export/state_timeline_export_20260702_db735bd6/download",
  "error": "",
  "created_at": "2026-07-02T08:16:49.389109+00:00",
  "finished_at": "2026-07-02T08:16:51.877120+00:00"
}
```

### 3.3 `GET /api/state-observer/export/{task_id}/download`

返回 `text/csv; charset=utf-8`，带 `Content-Disposition: attachment; filename="state_timeline_2026-07-02.csv"`。

---

## 四、异步触发条件

满足任一即走异步：

1. `symbols == "all"` 且 `format == "csv"`
2. 估算行数 `> 10000`
3. 显式 `async=1`

否则返回 `status="sync"`，前端复用现有 `/api/state-observer?format=csv` 直接下载。

---

## 五、后台执行方式

- 不引入 Celery / Redis / 外部队列。
- 使用 Python `threading.Thread(daemon=True)` 在后台执行导出。
- 任务日志落地到 `outputs/state_timeline_exports/task_log.jsonl`。
- 产物保存到 `outputs/state_timeline_exports/{task_id}.csv`。
- 通过追加 JSONL 记录实现状态流转：`queued -> running -> completed/failed`。

---

## 六、前端交互

`/state-observer` 页面导出按钮：

1. 点击后先 POST `/api/state-observer/export`。
2. 若返回 `status="sync"`：直接打开现有 CSV 下载 URL。
3. 若返回 `status="queued"`：显示任务 ID，每 2 秒轮询状态。
4. 任务完成后显示下载链接。
5. 失败时显示错误信息。

---

## 七、本地验收结果

### 7.1 编译

```bash
python -m py_compile web/main.py
python -m py_compile web/services/state_timeline_export_worker.py
# ✅ 通过
```

### 7.2 单元测试

```bash
python -m pytest tests/unit/test_state_observer_export.py -v
# 9 passed in 3.18s
```

### 7.3 已有测试回归

```bash
python -m pytest tests/unit/test_state_timeline_reader.py -v
# 10 passed in 0.64s

python scripts/pm_test_preflight.py --date 2026-07-01
# [SUMMARY] total=17 failed=0

HERMASS_SITE_URL=http://127.0.0.1:8020 python scripts/validate_website_data_sync.py --date 20260701
# [SUMMARY] all website data sync checks passed
```

### 7.4 接口冒烟

```bash
# 1. 同步导出（小查询）
curl -s -X POST http://127.0.0.1:8020/api/state-observer/export \
  -H 'Content-Type: application/json' \
  -d '{"symbols":"000001.SZ","days":1,"format":"csv"}'
# {"ok": true, "status": "sync", "estimated_rows": 1}

# 2. 异步导出（全市场 60 天）
curl -s -X POST http://127.0.0.1:8020/api/state-observer/export \
  -H 'Content-Type: application/json' \
  -d '{"symbols":"all","days":60,"format":"csv"}'
# {"ok": true, "task_id": "...", "status": "queued", "estimated_rows": 212218}

# 3. 轮询状态（2-3 秒后）
curl -s http://127.0.0.1:8020/api/state-observer/export/{task_id}
# {"ok": true, "status": "completed", "row_count": 212218}

# 4. 下载产物
curl -s -D - http://127.0.0.1:8020/api/state-observer/export/{task_id}/download
# HTTP/1.1 200 OK
# Content-Disposition: attachment; filename="state_timeline_2026-07-02.csv"
```

实测全市场 60 天（21.2 万行）后台完成约 2.5 秒。

---

## 八、风险与未完成项

### 8.1 风险

1. **并发任务日志写入**：已加 `threading.Lock`，单进程多线程安全。若未来多进程部署，需改用文件锁或 DuckDB。
2. **大查询估算耗时**：估算复用 `query_state_timeline(page_size=1)`，全市场 120 天约 2-3 秒。对导出创建请求可接受。
3. **产物清理**：当前未接入 cron，需 Phase 2B 后续或运维手动清理 `outputs/state_timeline_exports/` 下 7 天以上文件。
4. **下载链接未按用户隔离**：当前仅按 task_id 访问，无用户鉴权。内测阶段可接受；正式多用户场景需补充 `user_key` 校验。

### 8.2 未完成项

- cron 清理脚本
- 邮件摘要
- 预计算表脚本
- 产物大小/数量上限控制

---

## 九、是否可进入 git add / commit / push

**本地代码已验证，建议先由 Codex 审计后再提交。**

如需提交，范围建议：

```bash
git add web/main.py
 git add web/templates/state-observer.html
 git add web/services/state_timeline_export_worker.py
 git add tests/unit/test_state_observer_export.py
 git add docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2B_EXPORT_DELIVERY_20260702.md

git commit -m "feat(state-observer): Phase 2B async export with task queue and polling"
git push
```

---

## 十、部署建议

```bash
# 服务器执行
cd /opt/hermass
git pull
source .venv/bin/activate
python -m py_compile web/main.py
python -m py_compile web/services/state_timeline_export_worker.py
sudo systemctl restart hermass-console
sudo systemctl status hermass-console

# 服务器冒烟
curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/state-observer
curl -s -X POST http://localhost:8020/api/state-observer/export \
  -H 'Content-Type: application/json' \
  -d '{"symbols":"all","days":60,"format":"csv"}' | head -c 200
```
