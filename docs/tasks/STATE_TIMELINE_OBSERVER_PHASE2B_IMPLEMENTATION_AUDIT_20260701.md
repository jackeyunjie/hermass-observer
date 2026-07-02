# State Timeline Observer Phase 2B 实现级审计

日期：2026-07-01  
审计对象：Phase 2 异步导出 / 邮件摘要 / 预计算表  
状态：可直接进入编码（本线不正式落地到主流程）  

---

## 说明

本文档只输出 Phase 2B 三块能力的**实现级方案**，不直接写业务脚本、不改 `web/main.py`、不接 `config/hermes_cron.json`、不发送真实邮件。目的是让并行线或下一阶段能直接按此文编码，避免和当前产品主线（watchlist 接入 / 状态变化摘要 / 页面最小展示）冲突。

---

## 一、异步导出

### 1.1 任务状态存哪里

推荐：**`outputs/state_timeline_exports/task_log.jsonl`**

原因：
- 不新增数据库依赖，和现有文件型产物风格一致。
- JSONL 追加写，崩溃后可读。
- 每条任务一行，便于 `GET /api/state-observer/export/{task_id}` 直接 tail 读取。

任务记录 schema：

```json
{
  "task_id": "state_timeline_export_20260701_abc123",
  "status": "queued",
  "format": "csv",
  "query": {
    "symbols": "all",
    "symbol_set": "",
    "date_from": "2026-06-01",
    "date_to": "2026-07-01",
    "days": 60,
    "filters": {}
  },
  "estimated_rows": 165390,
  "output_path": "outputs/state_timeline_exports/state_timeline_export_20260701_abc123.csv",
  "row_count": 0,
  "error": "",
  "created_at": "2026-07-01T16:00:00+08:00",
  "finished_at": ""
}
```

状态机：

```text
queued -> running -> completed
                -> failed
```

读写建议：
- 写：追加一行新记录；状态更新时重新写整行并替换旧行（或写新行以 task_id 去重后读最新）。
- 读：`GET /api/state-observer/export/{task_id}` 扫描 JSONL，按 `task_id` 取最后一条。

备选方案（若未来任务量变大）：迁移到 `outputs/agent_memory/AgentMemory.duckdb` 的 `state_timeline_export_tasks` 表。Phase 2B 先保持简单。

### 1.2 导出文件存哪里

**`outputs/state_timeline_exports/{task_id}.csv`**

- 目录：`outputs/state_timeline_exports/`
- 命名：`{task_id}.csv` 或 `{task_id}.{format}`
- 编码：UTF-8 with BOM（Excel 友好）
- 文件头：与实时查询 `format=csv` 完全一致，字段顺序相同。

目录需要 `mkdir -p`，可由脚本或服务启动时创建。

### 1.3 API 形状

新增两个路由（建议放在 `web/main.py`，由产品主线合并时决定是否接入）：

#### `POST /api/state-observer/export`

Body：

```json
{
  "symbols": "all",
  "symbol_set": "",
  "date_from": "2026-06-01",
  "date_to": "2026-07-01",
  "days": 60,
  "filters": {},
  "format": "csv"
}
```

Response（小查询直接同步返回）：

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

Response（大查询走异步）：

```json
{
  "ok": true,
  "task_id": "state_timeline_export_20260701_abc123",
  "status": "queued",
  "format": "csv",
  "estimated_rows": 165390,
  "download_path": "/api/state-observer/export/state_timeline_export_20260701_abc123/download"
}
```

#### `GET /api/state-observer/export/{task_id}`

Response：

```json
{
  "ok": true,
  "task_id": "state_timeline_export_20260701_abc123",
  "status": "completed",
  "format": "csv",
  "estimated_rows": 165390,
  "row_count": 165388,
  "download_path": "/api/state-observer/export/state_timeline_export_20260701_abc123/download",
  "error": ""
}
```

#### `GET /api/state-observer/export/{task_id}/download`

直接返回 `text/csv; charset=utf-8`，`Content-Disposition: attachment; filename=state_timeline_20260701.csv`。

### 1.4 异步触发条件

满足任一即走异步：

1. `symbols == "all"` 且 `format in ("csv", "parquet")`
2. 估算行数 `estimated_rows > 10000`
3. 显式 `async=1`

估算行数方法：
- 先执行一次快速 `COUNT(*)`，使用与 `_build_core_query()` 相同的 `symbol_clause` + 时间范围 + 过滤条件，但不 SELECT 全部字段。
- 实测全市场 × 120 天约 42 万行，COUNT(*) 通常在 100ms 内完成。

### 1.5 后台执行方式

推荐：**同步任务队列足够**，不需要引入 Celery/RQ。

实现：`web/services/state_timeline_export_worker.py`

```python
def create_export_task(query_json: dict) -> dict:
    """创建任务，写入 task_log.jsonl，返回 task_id。"""

def run_export_task(task_id: str) -> dict:
    """实际执行导出：连 Foundation DB -> 执行查询 -> 写 CSV -> 更新任务状态。"""
```

执行模式二选一：

- 模式 A（简单）：`POST /api/state-observer/export` 在返回 `queued` 后，由当前进程在后台线程 `threading.Thread` 中执行 `run_export_task`。
- 模式 B（更稳）：由 `scripts/run_hermes_cron.py` 增加一个 `run-export-task` 子命令，每 30 秒扫描 `task_log.jsonl` 中 `status=queued` 的任务并执行。

Phase 2B 推荐模式 A，因为导出任务不频繁，且避免增加新调度器。

### 1.6 清理策略

**文件清理**：cron 每日 02:00 删除 7 天前的导出文件。

```bash
find outputs/state_timeline_exports -name 'state_timeline_export_*.csv' -mtime +7 -delete
```

**任务日志清理**：可选，保留 30 天任务记录用于审计，过期条目归档到 `outputs/state_timeline_exports/task_log_archive.jsonl`。

### 1.7 实现 checklist

- [ ] 新增 `web/services/state_timeline_export_worker.py`
- [ ] 新增 `POST /api/state-observer/export`
- [ ] 新增 `GET /api/state-observer/export/{task_id}`
- [ ] 新增 `GET /api/state-observer/export/{task_id}/download`
- [ ] 确保 CSV 字段与实时查询同构
- [ ] 补单元测试：小查询同步、大查询异步、任务状态流转、下载 200

---

## 二、邮件摘要

### 2.1 脚本入口

**`scripts/send_state_timeline_digest_email.py`**

用法：

```bash
.venv/bin/python scripts/send_state_timeline_digest_email.py --date 2026-07-01
.venv/bin/python scripts/send_state_timeline_digest_email.py --dry   # 仅输出 HTML 到 stdout
```

环境变量（复用现有邮件配置）：

- `HERMASS_SMTP_HOST`
- `HERMASS_SMTP_PORT`
- `HERMASS_SMTP_USER`
- `HERMASS_SMTP_PASS`
- `HERMASS_REPORT_TO`

### 2.2 邮件内容结构

邮件不是全量长表，而是**摘要视图**。建议分以下分组：

1. **今日状态变化最大 Top20**
   - 排序：`|ef_change| + |ab_change| + |zero_change|` 降序
   - 字段：stock_code, stock_name, state_date, transition_label, ef_change, ab_change, zero_change
2. **月线 EF 样本**（最多 10 只）
3. **周线 EF 样本**（最多 10 只）
4. **日线 EF 样本**（最多 10 只）
5. **月线 A/B 样本**（最多 10 只）
6. **周线 A/B 样本**（最多 10 只）
7. **日线 A/B 样本**（最多 10 只）
8. **月线 0 样本**（最多 10 只）
9. **周线 0 样本**（最多 10 只）
10. **日线 0 样本**（最多 10 只）
11. **周期交集样本**：`MN1+W1+D1` / `MN1+W1` / `W1+D1` 各最多 10 只
12. **自选池 watchlist 最近 3 天变化**（如果 watchlist 已接入且用户有 active watch_command）
13. **底部链接回 `/state-observer`**

### 2.3 依赖哪些 Observer 字段

必须字段：

- `stock_code`, `stock_name`, `state_date`
- `mn1_state_hex`, `w1_state_hex`, `d1_state_hex`
- `mn1_is_ef`, `w1_is_ef`, `d1_is_ef`
- `mn1_is_ab`, `w1_is_ab`, `d1_is_ab`
- `mn1_is_zero`, `w1_is_zero`, `d1_is_zero`
- `ef_count`, `ef_pattern`
- `ab_count`, `ab_pattern`
- `zero_count`, `zero_pattern`
- `state_change_flag`, `ef_change`, `ab_change`, `zero_change`, `transition_label`
- `close`, `industry_l1`
- `display_alias`

这些字段当前 `_build_core_query()` 已经全部返回，邮件脚本直接复用 `agently_adapter.tools.state_timeline_reader.load_state_timeline(symbols="all", days=1)` 即可。

### 2.4 是否依赖 watchlist 接入

**软依赖**。

- 邮件整体不阻塞：即使 watchlist 未接入或用户无 active watch_command，也可以发送邮件。
- watchlist 分组作为可选块：有数据则展示，无数据则跳过或显示“无 active watch_command”。
- 实现时调用 `load_watchlist_timeline(user_key, days=3)`，空结果不报错。

### 2.5 HTML 模板建议

复用 `scripts/send_m30_second_wave_email.py` 的 CSS 风格：

- 顶部标题 + 日期
- 摘要卡
- 每个分组一个 `<h2>` + `<table>`
- 底部免责声明：**“仅作研究观察，不构成交易建议”**
- 底部链接：`http://console.supertrader.world/state-observer`

### 2.6 cron 接入建议

在 `config/hermes_cron.json` 增加：

```json
{
  "name": "State Timeline 每日邮件摘要",
  "schedule": "30 16 * * 1-5",
  "command": "cd /Users/lv111101/Documents/hermass-observer-product && .venv/bin/python scripts/send_state_timeline_digest_email.py --date $(date +%Y-%m-%d)",
  "description": "每日收盘后发送 State Timeline 摘要邮件",
  "delivery": "terminal"
}
```

### 2.7 实现 checklist

- [ ] 新增 `scripts/send_state_timeline_digest_email.py`
- [ ] 复用 `state_timeline_reader` 读取数据
- [ ] 实现 `--dry` 预览
- [ ] HTML 含免责声明与回链
- [ ] 单元测试：HTML 生成、空数据不崩溃、分组字段存在

---

## 三、预计算表

### 3.1 脚本入口

**`scripts/materialize_state_timeline_daily.py`**

用法：

```bash
.venv/bin/python scripts/materialize_state_timeline_daily.py --date 2026-07-01
```

默认读取最新 Foundation DB：

```bash
.venv/bin/python scripts/materialize_state_timeline_daily.py
```

### 3.2 脚本输出结构

输出文件：

```text
outputs/state_timeline/state_timeline_daily_YYYYMMDD.duckdb
```

例如：

```text
outputs/state_timeline/state_timeline_daily_20260701.duckdb
```

表名：`state_timeline_daily`

表结构：与 `_build_core_query()` 的 SELECT 输出**完全同构**，包含 Phase 2B 新增的变化字段：

- 所有 `_build_core_query()` 当前返回的字段
- `state_change_flag`, `ef_change`, `transition_label`
- `display_alias` 可以在物化时预计算并写入表，减少查询时 JSON 读取开销

DDL 建议：

```sql
CREATE TABLE state_timeline_daily AS
SELECT
    stock_code,
    stock_name,
    state_date,
    mn1_state_hex,
    w1_state_hex,
    d1_state_hex,
    mn1_state_score,
    w1_state_score,
    d1_state_score,
    mn1_is_ef, w1_is_ef, d1_is_ef,
    mn1_is_ab, w1_is_ab, d1_is_ab,
    mn1_is_zero, w1_is_zero, d1_is_zero,
    ef_count, ef_pattern,
    ab_count, ab_pattern,
    zero_count, zero_pattern,
    state_triplet,
    state_change_flag,
    ef_change,
    transition_label,
    close,
    volume,
    industry_l1,
    display_alias,
    as_of_date
FROM (上述完整查询)
WHERE state_date = ?;

CREATE INDEX idx_stock_date ON state_timeline_daily(stock_code, state_date);
CREATE INDEX idx_state_date ON state_timeline_daily(state_date);
CREATE INDEX idx_industry ON state_timeline_daily(industry_l1);
CREATE INDEX idx_ef_pattern ON state_timeline_daily(ef_pattern);
CREATE INDEX idx_ab_pattern ON state_timeline_daily(ab_pattern);
CREATE INDEX idx_zero_pattern ON state_timeline_daily(zero_pattern);
```

注意：物化表**只保留一个交易日**的数据，文件名即数据日期。长时间窗查询仍需实时 CTE。

### 3.3 是否与实时查询同构

**字段同构，但能力不完全等价**：

| 能力 | 实时 CTE | 预计算表 |
|------|----------|----------|
| 单天全市场查询 | ✅ | ✅ 推荐 |
| 多天查询 | ✅ | ❌ 需回退 CTE |
| 行业过滤 | ✅ | ✅ |
| EF/A/B/0 过滤 | ✅ | ✅ |
| 模式过滤 | ✅ | ✅ |
| 跨日变化过滤 | ✅ | 部分（表内已有变化字段） |
| 任意 symbol_set | ✅ | ✅ |

因此预计算表只作为**单日全市场查询的加速层**，不是完全替代。

### 3.4 切换开关

推荐：**默认关闭，通过环境变量启用**。

在 `web/services/state_timeline_observer.py` 中增加：

```python
USE_STATE_TIMELINE_MATERIALIZED = os.environ.get("USE_STATE_TIMELINE_MATERIALIZED", "0") == "1"
```

命中预计算表的条件（必须同时满足）：

1. `USE_STATE_TIMELINE_MATERIALIZED == "1"`
2. 存在 `outputs/state_timeline/state_timeline_daily_YYYYMMDD.duckdb`
3. 文件名日期 `YYYYMMDD` 等于查询的 `date_to` 或 Foundation DB 最新日期
4. 查询时间范围是单个交易日（`date_from == date_to`）或 `days == 1`
5. 无需要跨日 Lag 才能计算的复杂过滤（如 `transition_label` 包含特定文本，可接受，因为物化表已含该字段）

Fallback：以上任一不满足，走现有实时 CTE。

开关扩展建议：
- 后续可支持 `?materialized=1` query param，覆盖环境变量，便于 A/B 测试。
- 默认环境变量关闭，避免在产品主线未完成状态变化摘要时引入数据一致性问题。

### 3.5 cron 接入建议

在 `config/hermes_cron.json` 增加：

```json
{
  "name": "State Timeline 每日预计算",
  "schedule": "33 15 * * 1-5",
  "command": "cd /Users/lv111101/Documents/hermass-observer-product && .venv/bin/python scripts/materialize_state_timeline_daily.py --date $(date +%Y-%m-%d)",
  "description": "每日收盘后预计算 State Timeline 表（默认关闭实时切换，仅生成产物）",
  "delivery": "terminal"
}
```

### 3.6 实现 checklist

- [ ] 新增 `scripts/materialize_state_timeline_daily.py`
- [ ] 表结构与实时查询 SELECT 同构
- [ ] 建索引
- [ ] 在 `web/services/state_timeline_observer.py` 增加 `USE_STATE_TIMELINE_MATERIALIZED` 开关与 fallback 逻辑
- [ ] 单元测试：物化表字段与实时查询一致、开关 fallback 生效

---

## 四、与主线的合并注意事项

### 4.1 文件冲突风险

| 文件 | 当前状态 | 风险 |
|------|----------|------|
| `web/services/state_timeline_observer.py` | Phase 1 已上线，Phase 2 主线可能改 | 预计算表开关需插入查询入口，注意合并 |
| `web/main.py` | Phase 1 已上线 | 新增 `/api/state-observer/export/*` 路由，需避开 watchlist 相关改动 |
| `web/templates/state-observer.html` | **不要碰** | 由产品主线负责 |
| `config/hermes_cron.json` | 不要正式接入 | 本文只给出建议条目，落地时再由负责 cron 的线合并 |

### 4.2 数据一致性

- 预计算表必须在 Foundation DB 构建完成后生成（建议 15:33，在 State Cube 15:32 之后）。
- 邮件摘要 cron 建议 16:30，确保预计算表和 Foundation DB 都是当天数据。
- 异步导出不依赖预计算表，直接读 Foundation DB。

### 4.3 安全与红线

- 邮件文案必须包含“仅作研究观察，不构成交易建议”。
- 邮件/导出中**禁止**出现买入、卖出、目标价、止损价。
- 导出文件 URL 不能泄露其他用户的任务，需按 user_key 隔离（如后续增加用户维度）。
- 全市场导出必须走异步，不能用同步请求拖垮服务。

### 4.4 推荐落地顺序

1. 先由产品主线完成 watchlist 接入 + 状态变化摘要。
2. 再落地异步导出（改动最小，收益最大）。
3. 再落地预计算表脚本（默认关闭，不影响现有行为）。
4. 最后落地邮件摘要（依赖 watchlist 软接入）。

---

## 五、验收建议

Phase 2B 正式落地后，至少验收：

```bash
# 1. 预计算表生成
.venv/bin/python scripts/materialize_state_timeline_daily.py --date 2026-07-01
ls outputs/state_timeline/state_timeline_daily_20260701.duckdb

# 2. 邮件摘要预览
.venv/bin/python scripts/send_state_timeline_digest_email.py --dry

# 3. 异步导出创建与状态查询
curl -s -X POST http://localhost:8020/api/state-observer/export \
  -H 'Content-Type: application/json' \
  -d '{"symbol_set":"all","days":60,"format":"csv"}' | jq

# 4. SDK 单元测试仍通过
.venv/bin/python -m pytest tests/unit/test_state_timeline_reader.py -v

# 5. 编译通过
.venv/bin/python -m py_compile web/main.py
.venv/bin/python -m py_compile web/services/state_timeline_observer.py
.venv/bin/python -m py_compile agently_adapter/tools/state_timeline_reader.py
```
