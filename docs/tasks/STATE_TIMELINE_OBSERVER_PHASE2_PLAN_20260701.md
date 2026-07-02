# State Timeline Observer Phase 2 可执行方案

日期：2026-07-01  
复核对象：已上线 commit `7c8ddce` 的 Phase 1  
方案版本：v1.0  
状态：可执行计划（待决策后开工）

---

## 一、Phase 1 复核结论

### 1.1 已验收项（全部通过）

| 验收项 | 结果 | 说明 |
|--------|------|------|
| 代码编译 | ✅ | `web/main.py`、`web/services/state_timeline_observer.py`、`scripts/validate_website_data_sync.py` 均通过 `py_compile` |
| 公网页面 | ✅ | `http://console.supertrader.world/state-observer` 返回 200，包含必要文案 |
| Top50 查询 | ✅ | `/api/state-observer?symbol_set=top50&days=1` 返回 50 行，字段完整 |
| 单股轨迹 | ✅ | `/api/state-observer/timeline?stock_code=000001.SZ&days=30` 正常 |
| EF/A+B/0 筛选 | ✅ | 分周期布尔筛选与交集模式筛选生效 |
| CSV 导出 | ✅ | `format=csv` 返回全结果（非当前页），`Content-Disposition` 正确 |
| 全结果统计 | ✅ | `meta` 含 `row_count/symbol_count/ef_row_count/ab_row_count/zero_row_count`，非仅当前页 |
| fundamental 降级 | ✅ | 服务器无 fundamental DB 时，`stock_name=None`、`industry_l1='未分类'`，不 500 |
| PM preflight | ✅ | `pm_test_preflight.py --date 2026-07-01` 17/17 passed |
| 数据同步验收 | ✅ | `validate_website_data_sync.py --date 20260701` 通过 |

### 1.2 代码层面复核意见

**符合设计约束：**

- 长表模型 `一只股票 × 一个交易日 = 一行` 落实。
- `mn1_is_ef / w1_is_ef / d1_is_ef / ef_pattern` 等为正式字段。
- `mn1_is_ab / w1_is_ab / d1_is_ab / ab_pattern` 等为正式字段。
- `mn1_is_zero / w1_is_zero / d1_is_zero / zero_pattern` 等为正式字段。
- 页面第一屏以分周期事件族组织，未把混合 `ef_count` 提升为主口径。
- 无买卖点、目标价、止损价表达。

**发现的问题（已本地修复）：**

| 问题 | 严重度 | 修复方式 | 文件 |
|------|--------|----------|------|
| `page_size` 无后端上限，极端请求可能拖慢服务 | 🟡 中 | 后端限制 `1 <= page_size <= 500` | `web/services/state_timeline_observer.py` |
| `page=0` 与 `page=1` 返回相同结果，语义混乱 | 🟢 低 | 后端强制 `page >= 1` | `web/services/state_timeline_observer.py` |
| `date_from > date_to` 时返回空结果，不符合直觉 | 🟢 低 | `_resolve_date_range` 自动交换 | `web/services/state_timeline_observer.py` |
| 前端表格对 `stock_name`/`industry_l1`/`display_alias` 直接 HTML 插值，存在 XSS 隐患 | 🟡 中 | 新增 `escapeHtml` 辅助函数，并改用 `encodeURIComponent` 构造研究链接 | `web/templates/state-observer.html` |

**未修复但已识别的缺口（纳入 Phase 2）：**

1. **同步查询性能边界未硬保护**：全市场 + 120 天 + CSV 实测 4.55s / 77MB，需异步导出。
2. **watchlist 为占位实现**：当前 `symbol_set=watchlist` 强制返回空结果。
3. **状态变化字段缺失**：缺少 `state_change_flag`、`ef_change`、`transition_label` 等跨日对比字段。
4. **Agent 消费接口未独立封装**：缺少面向 Agent 的只读 SDK/接口。
5. **未接入 cron/邮件/任务队列**：Phase 1 为实时查询，Phase 2 需补齐邮件摘要与后台导出。
6. **无预计算表**：当前每次查询实时构造 CTE。

### 1.3 已知缺口确认

- `symbol_set=watchlist` 占位：Phase 1 故意返回空结果，前端已标注“Phase 2 接入”。
- 未写入 `AgentMemory.duckdb` / Observation Ledger：符合 Phase 1 “只读展示层”定位。

### 1.4 性能基线实测

| 场景 | 结果集 | 耗时 | 备注 |
|------|--------|------|------|
| Top50 × 1 天 | 50 行 | <0.2s | 同步无压力 |
| 全市场 × 30 天 | 11 万行 | 0.63s | 分页查询无压力 |
| 全市场 × 60 天 CSV | ~21 万行 | 2.22s | 接近同步上限 |
| 全市场 × 120 天 CSV | ~42 万行 / 77MB | 4.55s | **必须走异步导出** |

---

## 二、Phase 2 目标与边界

### 2.1 目标

把 `/state-observer` 从“实时查询工作台”升级为：

```text
可订阅、可导出、可被 Agent 消费的 State 时间表服务
```

### 2.2 边界

**做：**

- 邮件/HTML 摘要（按事件族分组，限量样本）。
- 后台异步导出任务（全市场、长时间窗、CSV/Parquet）。
- 真实 `watchlist` 接入（基于现有 `user_task_ledger.json` 的 `watch_command`）。
- 状态变化摘要字段（跨日对比）。
- Agent 只读消费接口/SDK。
- 性能预计算表方案与落地开关。
- cron 集成（邮件、预计算、导出清理）。

**不做：**

- 不修改 State 底座契约。
- 不把 State Timeline 包装成交易指令。
- 不直接给买卖点、目标价、止损价。
- 不把 `ef_count` 重新提升回主口径。

---

## 三、Phase 2 任务拆解

### P2-A. 真实 watchlist 接入

**现状：** `symbol_set=watchlist` 返回空结果。  
**真实来源：** `outputs/user_tasks/user_task_ledger.json` 中 `task_type == "watch_command"` 且 `status == "active"` 的任务。

**实施：**

1. 在 `web/services/state_timeline_observer.py` 新增 `_resolve_watchlist_codes(user_key: str) -> list[str]`。
2. 读取 `agently_adapter.tools.user_tasks.list_user_tasks(user=user_key, status="active", task_type="watch_command", limit=500)`。
3. 提取 `stock_code`，去重并规范化。
4. 在 `query_state_timeline()` 的 `symbol_set == "watchlist"` 分支调用。
5. `web/main.py` 的 `/api/state-observer` 增加 `user_key` 解析（复用 `get_current_profile(request)` 的 `user_key`）。
6. 前端把下拉文案改为“自选池（watchlist）”。

**验收：**

```bash
curl -s "http://localhost:8020/api/state-observer?symbol_set=watchlist&days=3"
# 用户有 active watch_command 时返回对应股票；无任务时返回空结果+ok=true
```

---

### P2-B. 状态变化摘要（跨日对比）

**新增字段（仅展示层派生，不写回 Foundation）：**

| 字段 | 说明 |
|------|------|
| `prev_state_date` | 上一交易日 |
| `mn1_changed` | 月线 state_hex 是否变化 |
| `w1_changed` | 周线 state_hex 是否变化 |
| `d1_changed` | 日线 state_hex 是否变化 |
| `ef_change` | 较上一交易日的 `ef_count` 变化（+N / -N / 0） |
| `ab_change` | 较上一交易日的 `ab_count` 变化 |
| `zero_change` | 较上一交易日的 `zero_count` 变化 |
| `transition_label` | 例如“由单 E 转双 E”、“由 A/B 转 0” |
| `state_change_flag` | 任一周期 state_hex 变化则为 true |

**实施：**

1. 在 `_build_core_query()` 的 `derived` CTE 之后新增 `lag` CTE，使用 `LAG(...) OVER (PARTITION BY stock_code ORDER BY state_date)`。
2. 生成上述字段。
3. 在 API 返回中保留这些字段。
4. 前端表格增加“变化”列或抽屉展示。

**验收：**

```bash
curl -s "http://localhost:8020/api/state-observer?symbols=000001.SZ&days=10" | jq '.rows[0].transition_label'
```

---

### P2-C. 后台异步导出任务

**触发条件（满足任一即走异步）：**

- `symbols == "all"` 且 `format in ("csv", "parquet")`
- `estimated_rows > 10000`
- 显式 `async=1`

**任务存储：** 复用 `outputs/user_tasks/` 目录或新增 `outputs/state_timeline_exports/` JSONL 任务日志。

**实施：**

1. 新增 `web/services/state_timeline_export_worker.py`：
   - `create_export_task(query_json) -> task_id`
   - `run_export_task(task_id)`：连接 Foundation DB，执行查询，写入 `outputs/state_timeline_exports/{task_id}.csv`。
2. 新增 `POST /api/state-observer/export`：
   - 接收 JSON body（与 GET 参数等价）。
   - 估算行数（快速 `COUNT(*)`）。
   - 小查询直接返回同步下载；大查询返回 `{task_id, status: "queued"}`。
3. 新增 `GET /api/state-observer/export/{task_id}`：查询任务状态与下载路径。
4. 前端“导出 CSV”按钮在估算行数过大时提示“后台任务，稍后下载”。

**cron 清理：** 每日删除 7 天前的导出文件。

**验收：**

```bash
curl -s -X POST http://localhost:8020/api/state-observer/export \
  -H 'Content-Type: application/json' \
  -d '{"symbol_set":"all","days":60,"format":"csv"}'
# 返回 {"task_id":"...","status":"queued"}
```

---

### P2-D. 每日邮件摘要

**邮件不是全量长表，而是摘要视图：**

1. 今日状态变化最大 Top20（按 `|ef_change| + |ab_change| + |zero_change|` 排序）。
2. 月线 EF 样本（最多 10 只）。
3. 周线 EF 样本（最多 10 只）。
4. 日线 EF 样本（最多 10 只）。
5. 月线 A/B、周线 A/B、日线 A/B 各最多 10 只。
6. 月线 0、周线 0、日线 0 各最多 10 只。
7. 周期交集样本：`MN1+W1+D1`、`MN1+W1`、`W1+D1` 各最多 10 只。
8. 自选池 watchlist 最近 3 天变化。
9. 底部链接回 `/state-observer`。

**实施：**

1. 新增 `scripts/send_state_timeline_digest_email.py`：
   - 读取 `HERMASS_SMTP_HOST/PORT/USER/PASS/REPORT_TO` 环境变量（复用现有邮件模式）。
   - 调用 `query_state_timeline()` 生成各分组样本。
   - 生成 HTML 邮件（样式复用 `send_m30_second_wave_email.py` 的 disclaimer 模式）。
2. 新增 `config/hermes_cron.json` 任务：
   - 名称：`State Timeline 每日邮件摘要`
   - 调度：`30 16 * * 1-5`（收盘后 16:30）
   - 命令：`.venv/bin/python scripts/send_state_timeline_digest_email.py --date $(date +%Y-%m-%d)`
3. 支持 `--dry` 预览。

**验收：**

```bash
.venv/bin/python scripts/send_state_timeline_digest_email.py --dry
# 输出完整 HTML 到 stdout
```

---

### P2-E. Agent 只读消费接口

**目标：** 让 Strategy Agent / Router / Ledger 能稳定读取 State Timeline，不依赖 HTTP API 细节。

**实施：**

1. 新增 `agently_adapter/tools/state_timeline_reader.py`：
   - `load_state_timeline(symbols, days, filters) -> list[dict]`
   - `load_stock_timeline(stock_code, days) -> list[dict]`
   - `load_watchlist_timeline(user_key, days) -> list[dict]`
2. 该工具直接调用 `web.services.state_timeline_observer.query_state_timeline()`（本地 Python 调用，不绕 HTTP）。
3. 返回结构做标准化，供 Agent prompt 使用。
4. 新增单元测试 `tests/unit/test_state_timeline_reader.py`。

**验收：**

```bash
.venv/bin/python -m pytest tests/unit/test_state_timeline_reader.py -v
```

---

### P2-F. 性能预计算表方案

**触发条件：**

- 当 `/api/state-observer` 全市场查询平均耗时 > 2s 或并发下出现超时。

**方案：**

1. 新增 `scripts/materialize_state_timeline_daily.py`：
   - 读取最新 Foundation DB。
   - 生成 `outputs/state_timeline/state_timeline_daily_YYYYMMDD.duckdb`。
   - 表结构与 `_build_core_query()` 的 SELECT 输出一致（含 P2-B 变化字段）。
2. 在 `web/services/state_timeline_observer.py` 中新增开关：
   - 若存在当天的 `state_timeline_daily_YYYYMMDD.duckdb` 且查询条件简单（无行业过滤、无跨日变化过滤），优先读预计算表。
   - 否则 fallback 到实时 CTE 查询。
3. 新增 cron：每日 15:33（在 State Cube 15:32 之后）运行物化脚本。

**Phase 2 首期不强制启用**，先实现脚本与开关，默认关闭，待性能测试后开启。

**验收：**

```bash
.venv/bin/python scripts/materialize_state_timeline_daily.py --date 2026-07-01
# 生成 outputs/state_timeline/state_timeline_daily_20260701.duckdb
```

---

### P2-G. Observation Ledger 接入评估

**结论：Phase 2 不直接写入 Ledger，但为 Phase 3 预留接口。**

原因：

- Observer 当前定位是“观察事实层”，Ledger 是“判断与后验层”。
- Phase 2 先让 Agent 通过 `state_timeline_reader` 消费 Observer；Agent 的判断再由 Router/Ledger 写入。
- 如需在 Phase 2 写入，建议只写“每日 State Timeline 摘要快照”到 Ledger，作为可回溯上下文，而不是每行都写。

**预留接口：**

- 在 `scripts/decision_observation_ledger.py` 中预留 `attach_state_timeline_context(obs_date)` 函数，供后续调用。

---

## 四、数据模型扩展

### 4.1 查询层新增字段

在现有 `_build_core_query()` 基础上扩展：

```sql
lag_state_date AS (
    SELECT *,
        LAG(state_date) OVER w AS prev_state_date,
        LAG(mn1_state_hex) OVER w AS prev_mn1_state_hex,
        LAG(w1_state_hex) OVER w AS prev_w1_state_hex,
        LAG(d1_state_hex) OVER w AS prev_d1_state_hex,
        LAG(ef_count) OVER w AS prev_ef_count,
        LAG(ab_count) OVER w AS prev_ab_count,
        LAG(zero_count) OVER w AS prev_zero_count
    FROM derived
    WINDOW w AS (PARTITION BY stock_code ORDER BY state_date)
)
```

新增字段派生：

```sql
mn1_changed := mn1_state_hex IS DISTINCT FROM prev_mn1_state_hex,
w1_changed  := w1_state_hex  IS DISTINCT FROM prev_w1_state_hex,
d1_changed  := d1_state_hex  IS DISTINCT FROM prev_d1_state_hex,
ef_change   := ef_count - COALESCE(prev_ef_count, 0),
ab_change   := ab_count - COALESCE(prev_ab_count, 0),
zero_change := zero_count - COALESCE(prev_zero_count, 0),
state_change_flag := mn1_changed OR w1_changed OR d1_changed,
transition_label := CASE ... END
```

### 4.2 预计算表 DDL（可选）

```sql
CREATE TABLE state_timeline_daily AS
SELECT *
FROM (上述完整查询)
WHERE state_date = ?;

CREATE INDEX idx_stock_date ON state_timeline_daily(stock_code, state_date);
CREATE INDEX idx_state_date ON state_timeline_daily(state_date);
CREATE INDEX idx_industry ON state_timeline_daily(industry_l1);
```

---

## 五、API 扩展

### 5.1 现有接口增强

`GET /api/state-observer`：

- 返回字段增加 P2-B 变化字段。
- `symbol_set=watchlist` 生效。
- 增加 `async` 参数（可选）。

`GET /api/state-observer/timeline`：

- 返回字段同步增加变化字段。

### 5.2 新增接口

`POST /api/state-observer/export`

- Body: `{symbols, symbol_set, date_from, date_to, days, filters, format}`
- Response: `{ok, task_id, status, estimated_rows, download_path}`

`GET /api/state-observer/export/{task_id}`

- Response: `{ok, task_id, status, row_count, download_path, error}`

---

## 六、前端扩展

1. **watchlist 下拉**：移除“Phase 2 接入”提示。
2. **变化列**：表格可选展示 `state_change_flag`、`ef_change`、`transition_label`。
3. **抽屉详情**：点击行弹出该股票最近 30 天轨迹（调用 `/api/state-observer/timeline`）。
4. **导出按钮**：
   - 小范围（estimated_rows <= 10000）：直接下载 CSV。
   - 大范围：创建后台任务，显示任务 ID 与轮询状态。
5. **邮件订阅入口**（可选）：在页面 footer 增加“订阅每日 State Timeline 摘要”。

---

## 七、cron 与流水线集成

新增 `config/hermes_cron.json` 任务：

```json
{
  "name": "State Timeline 每日预计算",
  "schedule": "33 15 * * 1-5",
  "command": "cd /Users/lv111101/Documents/hermass-observer-product && .venv/bin/python scripts/materialize_state_timeline_daily.py --date $(date +%Y-%m-%d)",
  "description": "每日收盘后预计算 State Timeline 表（默认关闭实时切换，仅生成产物）",
  "delivery": "terminal"
},
{
  "name": "State Timeline 每日邮件摘要",
  "schedule": "30 16 * * 1-5",
  "command": "cd /Users/lv111101/Documents/hermass-observer-product && .venv/bin/python scripts/send_state_timeline_digest_email.py --date $(date +%Y-%m-%d)",
  "description": "每日收盘后发送 State Timeline 摘要邮件",
  "delivery": "terminal"
},
{
  "name": "State Timeline 导出产物清理",
  "schedule": "0 2 * * *",
  "command": "cd /Users/lv111101/Documents/hermass-observer-product && find outputs/state_timeline_exports -name 'export_*.csv' -mtime +7 -delete",
  "description": "清理 7 天前的异步导出文件",
  "delivery": "terminal"
}
```

---

## 八、验收标准

### 8.1 最小验收

1. `symbol_set=watchlist` 返回用户 active watch_command 对应的 State Timeline。
2. `/api/state-observer` 返回行包含 `state_change_flag`、`ef_change`、`transition_label`。
3. `POST /api/state-observer/export` 对全市场/长时间窗返回任务 ID，任务完成后可下载 CSV。
4. `scripts/send_state_timeline_digest_email.py --dry` 生成完整 HTML 邮件。
5. `agently_adapter/tools/state_timeline_reader.py` 可通过单元测试。
6. `validate_website_data_sync.py --date 20260701` 仍通过。

### 8.2 部署验收

```bash
# 服务器编译
source .venv/bin/activate
python -m py_compile web/main.py
python -m py_compile web/services/state_timeline_observer.py
python -m py_compile web/services/state_timeline_export_worker.py
python -m py_compile agently_adapter/tools/state_timeline_reader.py
python -m py_compile scripts/send_state_timeline_digest_email.py
python -m py_compile scripts/materialize_state_timeline_daily.py

# 服务重启
sudo systemctl restart hermass-console

# 冒烟
curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/state-observer
curl -s "http://localhost:8020/api/state-observer?symbol_set=top50&days=1&page_size=1" | head -c 200
```

---

## 九、风险与禁止事项

### 9.1 风险

1. **邮件被当成交易建议**：邮件文案必须沿用“仅作研究观察，不构成交易建议”免责声明。
2. **全市场导出拖垮服务**：必须通过 estimated_rows 阈值强制转异步。
3. **watchlist 用户隔离**：不同用户的 `user_key` 必须隔离，不能 A 用户看到 B 用户的 watchlist。
4. **预计算表日期不一致**：物化表必须按 `state_date` 分天，查询时校验最新 Foundation DB 日期与物化表日期一致。

### 9.2 禁止事项

1. 禁止把 `ef_count` 重新提升为邮件或页面主口径。
2. 禁止在邮件/页面/导出中出现买入、卖出、目标价、止损价。
3. 禁止把 A/B 或 0 事件族隐藏或降级。
4. 禁止在服务器上直接改业务逻辑或用系统 Python 编译。
5. 禁止把 Observer 查询结果大规模写入 `AgentMemory.duckdb`（Phase 2 只读消费，不写入）。

---

## 十、执行顺序建议

按优先级分两周落地：

**第一周（核心可用）—— 已完成：**

交付文档：`docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2_WEEK1_DELIVERY_20260701.md`

1. ✅ P2-A 真实 watchlist 接入
2. ✅ P2-B 状态变化摘要
3. ✅ P2-E Agent 只读消费接口
4. ✅ 同步更新 `validate_website_data_sync.py` 与单元测试
5. ✅ 本地加固：分页上限、日期校正、XSS 转义

**第二周（服务化）—— 待开工：**

1. P2-C 后台异步导出任务
2. P2-D 每日邮件摘要
3. P2-F 性能预计算表脚本（默认关闭）
4. P2-G Observation Ledger 预留接口
5. 更新 `config/hermes_cron.json`
6. 部署与冒烟

---

## 十一、文档同步清单

- [ ] 更新 `docs/STATE_TIMELINE_OBSERVER_SPEC.md`（新增字段、接口、邮件设计）
- [ ] 新增 `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2_DELIVERY_YYYYMMDD.md`（交付时填写）
- [ ] 更新 `scripts/validate_website_data_sync.py`（验证新字段与 watchlist）
- [ ] 新增/更新单元测试
- [ ] 更新 `AGENTS.md`（若 Phase 2 形成全项目统一规则，例如异步导出阈值）
- [ ] 更新 `config/hermes_cron.json`
