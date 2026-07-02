# State Timeline Observer Phase 2A 交付说明

日期：2026-07-01  
执行者：KIMI  
审计：Codex  
范围：P2-A（watchlist 接入）+ P2-B 最小可用子集（变化字段）+ 验收同步

---

## 一、改了哪些文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `web/services/state_timeline_observer.py` | 修改 | watchlist 真实接入；`_resolve_watchlist_codes` 增加空/anonymous 保护；`transition_label` 改为紧凑箭头格式 |
| `web/main.py` | 修改（已在本地小修中） | `/api/state-observer` 传入 `user_key`，支持 `symbol_set=watchlist` |
| `web/templates/state-observer.html` | 修改（已在本地小修中） | 表格增加「变化」列；自选池下拉移除 Phase 2 提示 |
| `scripts/validate_website_data_sync.py` | 修改 | 新增 `validate_state_observer_watchlist()`，覆盖 watchlist 路径与变化字段 |
| `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE1_DELIVERY_20260701.md` | 更新 | 补充 Phase 2A 引用与已知缺口状态 |
| `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2A_DELIVERY_20260701.md` | 新增 | 本文档 |

未修改：

- `AGENTS.md`：Phase 2A 未引入新的全项目长期规则
- `config/hermes_cron.json`：Phase 2A 仍不做定时任务
- Foundation DB / State 底座契约：未改动

---

## 二、watchlist 接入实现

### 2.1 数据源

读取 `outputs/user_tasks/user_task_ledger.json`，通过 `agently_adapter.tools.user_tasks.list_user_tasks()` 统一接口过滤：

```python
list_user_tasks(
    user=user_key,
    status="active",
    task_type="watch_command",
    limit=500,
)
```

等价过滤条件：

- `task_type == "watch_command"`
- `status == "active"`
- `created_by == user_key`

### 2.2 用户隔离

`web/main.py` 复用 `_request_user_identity(request)` 提取 `user_key` 传入查询层：

- 已登录用户：`user_key = username`
- 访客用户：`user_key = hermass_visitor_id cookie`

查询层 `_resolve_watchlist_codes()` 增加硬保护：

```python
if not user_key or user_key.lower() in ("", "anonymous", "__anonymous__"):
    return []
```

空用户名或匿名用户直接返回空列表，防止跨用户泄露 watchlist。

### 2.3 无 watchlist 行为

当用户无 active watch_command 时：

- `_build_core_query()` 中 `symbol_clause = "FALSE"`
- 查询返回 `ok=true`、`rows=[]`、不报错
- 全结果统计均为 0

### 2.4 代码位置

- 读取逻辑：`web/services/state_timeline_observer.py::_resolve_watchlist_codes()`
- 调用位置：`web/services/state_timeline_observer.py::query_state_timeline()`
- Web 层传参：`web/main.py::state_observer_api()`

---

## 三、状态变化字段计算

在 `_build_core_query()` 的 `derived` CTE 之后新增 `lagged` CTE，使用 `LAG()` 按 `stock_code` 分区、`state_date` 排序：

```sql
lagged AS (
    SELECT
        *,
        LAG(mn1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_mn1_state_hex,
        LAG(w1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_w1_state_hex,
        LAG(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_d1_state_hex,
        LAG(ef_count) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_ef_count
    FROM derived
)
```

新增返回字段：

| 字段 | SQL 派生 | 说明 |
|------|----------|------|
| `state_change_flag` | `CASE WHEN prev IS NULL THEN false ELSE ((mn1_state_hex IS DISTINCT FROM prev_mn1_state_hex) OR ...) END` | 任一周期 state_hex 变化则为 true；首条记录明确为 false |
| `ef_change` | `ef_count - prev_ef_count` | 当前 EF 周期数 － 上一交易日 EF 周期数；首条记录为 NULL |
| `transition_label` | `CASE WHEN prev IS NULL THEN '初始状态' WHEN 变化 THEN 'prev -> current' ELSE '-' END` | 例如 `E/E/E -> E/E/F`；首条记录显示「初始状态」 |

注意：

- 这些字段仅在查询层派生，不写回 Foundation DB。
- 当查询窗口只有 1 天时，所有行都是各自股票在该窗口内的首条记录，因此 `transition_label` 会显示「初始状态」且 `state_change_flag=false`；要观察真实跨日变化需查询 `days >= 2`。

---

## 四、页面展示

### 4.1 自选池下拉

`symbol_set=watchlist` 下拉文案从「自选池（Phase 2 接入）」改为「自选池」。

### 4.2 表格「变化」列

在 EF 模式 / A/B 模式 / 0 模式之后增加「变化」列：

```html
<td>
  ${r.state_change_flag ? `<span title="${escapeHtml(r.transition_label)}">变 ${r.ef_change != null ? (r.ef_change > 0 ? '+' + r.ef_change : r.ef_change) : '-'}</span>` : '-'}
</td>
```

展示规则：

- `state_change_flag = false` 时显示 `-`
- `state_change_flag = true` 时显示「变 ±N」，悬停查看 `transition_label`
- `ef_change` 为 NULL 时显示 `-`

### 4.3 约束保持

- 页面仍无买入、卖出、止损、目标价、收益承诺等表达
- 主口径继续是分周期 EF / A+B / 0 三事件族
- `ef_count` 未提升回主口径

---

## 五、验收同步

`scripts/validate_website_data_sync.py` 新增 `validate_state_observer_watchlist()`：

1. 调用 `/api/state-observer?symbol_set=watchlist&days=5`
2. 校验 `ok=true`
3. 校验 `rows` 为列表
4. 校验 `meta.date_max == expected_date`
5. 若有数据，校验行包含 `stock_code`、`state_date`、`state_change_flag`、`ef_change`、`transition_label`

同时 `validate_state_observer_api()` 继续校验 `state_change_flag`、`ef_change`、`transition_label` 三个字段存在。

---

## 六、本地验收结果

### 6.1 编译

```bash
cd /Users/lv111101/Documents/hermass-observer-product
.venv/bin/python -m py_compile web/main.py
.venv/bin/python -m py_compile web/services/state_timeline_observer.py
.venv/bin/python -m py_compile scripts/validate_website_data_sync.py
```

全部通过。

### 6.2 API 功能验证

启动本地服务 `uvicorn web.main:app --host 127.0.0.1 --port 8020` 后验证：

| 验收项 | 结果 |
|--------|------|
| `/api/state-observer?symbol_set=watchlist&days=5`（访客用户，无 active watch_command） | `ok=true`，`rows=[]`，不报错 |
| `/api/state-observer?symbol_set=watchlist&days=5`（带 active watch_command 用户） | 返回对应股票真实数据 |
| `/api/state-observer?symbol_set=top50&days=1&page_size=1` | 包含 `state_change_flag`、`ef_change`、`transition_label` |
| `/api/state-observer?symbols=000021.SZ&days=10` | 正确输出跨日变化标签，如 `E/E/E -> E/E/F` |
| `/api/state-observer/timeline?stock_code=000021.SZ&days=30` | 正常返回单股轨迹，含变化字段 |
| `format=csv` | 导出包含变化字段 |

### 6.3 验收脚本

```bash
HERMASS_SITE_URL=http://127.0.0.1:8020 .venv/bin/python scripts/validate_website_data_sync.py --date 20260701
```

结果：`[SUMMARY] all website data sync checks passed`

新增 watchlist 验收项输出：

```text
[OK] state-observer watchlist date_max=2026-07-01
[OK] state-observer watchlist returned ok=true rows=0
```

### 6.4 PM Preflight

```bash
.venv/bin/python scripts/pm_test_preflight.py --date 2026-07-01
```

结果：`[SUMMARY] total=17 failed=0`

---

## 七、部署建议

按 Hermass 固定流程部署：

1. 本地确认 `git status` 只包含 Phase 2A 相关修改
2. `git add web/services/state_timeline_observer.py web/main.py web/templates/state-observer.html scripts/validate_website_data_sync.py docs/tasks/STATE_TIMELINE_OBSERVER_PHASE1_DELIVERY_20260701.md docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2A_DELIVERY_20260701.md`
3. `git commit -m "feat(state-observer): Phase 2A watchlist + change fields"`
4. `git push`
5. 服务器执行：

```bash
cd /opt/hermass
git pull
source .venv/bin/activate
python -m py_compile web/main.py
python -m py_compile web/services/state_timeline_observer.py
python -m py_compile scripts/validate_website_data_sync.py
sudo systemctl restart hermass-console
sudo systemctl status hermass-console
```

6. 服务器冒烟：

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/state-observer
curl -s "http://localhost:8020/api/state-observer?symbol_set=top50&days=1&page_size=1" | head -c 200
curl -s "http://localhost:8020/api/state-observer?symbol_set=watchlist&days=5"
```

7. 部署后再次运行：

```bash
.venv/bin/python scripts/validate_website_data_sync.py --date 20260701
.venv/bin/python scripts/pm_test_preflight.py --date 2026-07-01
```

---

## 八、Phase 2 剩余项

Phase 2A 未包含以下内容，留在后续：

1. 后台异步导出任务（P2-C）
2. 每日邮件摘要（P2-D）
3. Agent 只读消费接口 / SDK（P2-E）
4. 性能预计算表（P2-F）
5. cron 集成（P2-G 相关）
6. Observation Ledger 写入（Phase 3 评估）

---

## 九、禁止事项复核

Phase 2A 未违反以下约束：

- 未把 `ef_count` 重新提升为主口径
- 页面/API/导出中未出现买入、卖出、目标价、止损价
- A/B 与 0 事件族未隐藏或降级
- 未在服务器直接改业务逻辑
- Observer 查询结果未大规模写入 `AgentMemory.duckdb`
