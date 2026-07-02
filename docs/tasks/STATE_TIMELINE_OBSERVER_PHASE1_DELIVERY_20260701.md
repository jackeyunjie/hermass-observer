# State Timeline Observer Phase 1 MVP 交付说明

日期：2026-07-01  
执行者：KIMI  
审计：Codex

---

## 一、改了哪些文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `web/services/state_timeline_observer.py` | 新增 | State Timeline 查询服务：长表查询、Top50、A/B/0 事件族、CSV 导出 |
| `web/main.py` | 修改 | 新增 3 个路由：`/api/state-observer`、`/api/state-observer/timeline`、`/state-observer` |
| `web/templates/state-observer.html` | 新增 | State Timeline Observer 工作台页面 |
| `web/templates/_top_nav.html` | 修改 | 在工具箱菜单增加 `/state-observer` 入口 |
| `scripts/validate_website_data_sync.py` | 修改 | 增加 `/state-observer` 页面与 API 的最小冒烟验收 |

未修改：

- `AGENTS.md`：本轮未引入新的长期项目规则，无需修改
- `config/hermes_cron.json`：Phase 1 只做实时查询，未接入定时任务
- `outputs/agent_memory/AgentMemory.duckdb`：Observer 当前是只读展示层，未写入记忆层
- Foundation DB / State 底座契约：未改动

---

## 二、数据层做了什么

基于 `outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb` 的只读长表查询。

核心查询模型：

```text
一只股票 × 一个交易日 = 一行
```

来源表：

- `d1_perspective_state`：State 主表
- `daily_bars`：补充成交量
- `fundamental_evidence.duckdb.ifind_industry_chain_profile`：股票名称、一级行业

产出正式字段：

- `stock_code`, `stock_name`, `state_date`
- `mn1_state_hex`, `w1_state_hex`, `d1_state_hex`
- `mn1_state_score`, `w1_state_score`, `d1_state_score`
- `mn1_is_ef`, `w1_is_ef`, `d1_is_ef`
- `mn1_is_ab`, `w1_is_ab`, `d1_is_ab`
- `mn1_is_zero`, `w1_is_zero`, `d1_is_zero`
- `ef_count`, `ef_pattern`
- `ab_count`, `ab_pattern`
- `zero_count`, `zero_pattern`
- `state_triplet`, `display_alias`, `industry_l1`, `close`, `volume`, `as_of_date`

事件族判定规则：

- `EF`：`state_score IN (14, 15)`（仅正值，与 State 底座契约一致）
- `A/B`：`state_magnitude IN (10, 11)`（含正负方向）
- `0`：`state_magnitude = 0`

`ef_count / ab_count / zero_count` 只做辅助字段，主视图按分周期事件组织。

---

## 三、API 做了什么

### `GET /api/state-observer`

支持参数：

- `symbols`：逗号分隔股票代码，或 `all`
- `symbol_set`：`top50` / `watchlist`（Phase 2）
- `date_from`, `date_to`：绝对日期
- `days`：相对窗口天数
- `mn1_is_ef`, `w1_is_ef`, `d1_is_ef`
- `mn1_is_ab`, `w1_is_ab`, `d1_is_ab`
- `mn1_is_zero`, `w1_is_zero`, `d1_is_zero`
- `ef_pattern_any`, `ab_pattern_any`, `zero_pattern_any`
- `industry_l1`
- `page`, `page_size`
- `format=json|csv`

返回：

```json
{
  "ok": true,
  "query": {...},
  "meta": {"row_count", "symbol_count", "date_min", "date_max", "as_of_date"},
  "rows": [...]
}
```

### `GET /api/state-observer/timeline`

单只股票轨迹查询：

- `stock_code`
- `days`
- `date_from`, `date_to`

内部复用 `/api/state-observer` 的查询函数，只是默认不分页。

### CSV 导出

`format=csv` 时返回 `text/csv; charset=utf-8`，文件名带当前日期。

---

## 四、页面做了什么

新增页面：`/state-observer`

功能：

1. 顶部说明卡片：明确这是 State 观察工作台，不是交易指令面板。
2. 查询参数面板：
   - 股票代码 / 集合选择
   - 最近 N 天 / 日期区间
   - 每页行数
   - 一级行业过滤
3. 事件族切换：`全部 / EF / A+B / 0`
4. 分周期筛选：月线/周线/日线的 EF、A/B、0
5. 交集模式筛选：`MN1+W1`、`W1+D1` 等
6. 统计卡片：EF 行数、A/B 行数、0 行数、股票数、总行数
7. 长表：一行 = 一只股票一天，默认按日期倒序
8. 分页与 CSV 导出
9. 每行提供研究页入口

页面文案硬约束：

- 无买入、卖出、止损、目标价、收益承诺等表达
- 第一屏主口径是分周期事件，不是混合 `ef_count`
- `A/B` 和 `0` 都进入主视图，没有隐藏到详情

---

## 五、文档和注释同步了什么

- `web/services/state_timeline_observer.py`：模块级 docstring、函数注释、字段规则注释
- `web/main.py`：新增路由的 docstring
- `scripts/validate_website_data_sync.py`：新增验收函数注释
- 新增本文档：`docs/tasks/STATE_TIMELINE_OBSERVER_PHASE1_DELIVERY_20260701.md`

未改动：

- `docs/STATE_TIMELINE_OBSERVER_SPEC.md`：实现与 Phase 1 口径一致，无字段口径变更，未修改
- `AGENTS.md`：本轮未新增长期项目规则，未修改

---

## 六、cron / memory / AGENTS.md 结论

### cron：`config/hermes_cron.json`

**结论：Phase 1 不接入。**

原因：

1. State Timeline Observer Phase 1 是交互式查询工作台，小查询实时返回即可。
2. 当前数据已落在 Foundation DB，查询函数直接读取，无需每日预计算。
3. CSV 导出和大范围查询可通过实时 API 完成，当前数据量和查询性能足够 Phase 1 使用。

Phase 2 接入 cron 的条件：

- 需要每日自动发送 State Timeline 邮件摘要
- 需要预计算全市场长时间窗离线产物
- 需要为 Agent 层准备固定缓存表

### AgentMemory：`outputs/agent_memory/AgentMemory.duckdb`

**结论：Phase 1 不写入。**

原因：

1. Observer Phase 1 定位是查询与展示层，不是新记忆系统。
2. 页面查询结果不应默认写入 `AgentMemory.duckdb`。
3. 后续 Strategy Agent 可直接消费 `/api/state-observer` 作为只读输入。

Phase 2 可考虑的接入点：

- 将 Observer 的观察结论写入 Observation Ledger，用于后验分析
- 为特定 Agent 预留只读消费接口

### `AGENTS.md`

**结论：不改。**

原因：

1. 本轮只是新增一个页面和 API，没有改变全项目长期运行规则。
2. 新增的约束（如禁止交易建议表达、A/B/0 事件族）属于功能实现细节，留在任务文档和设计文档即可。
3. 只有当 State Timeline Observer 成为全项目统一规则（例如所有页面必须同步事件族口径）时，才需要修改 `AGENTS.md`。

---

## 七、本地验收结果

已执行：

```bash
cd /Users/lv111101/Documents/hermass-observer-product
.venv/bin/python -m py_compile web/main.py
.venv/bin/python -m py_compile web/services/state_timeline_observer.py
.venv/bin/python -m py_compile scripts/validate_website_data_sync.py
```

全部通过。

已启动本地服务 `uvicorn web.main:app --host 127.0.0.1 --port 8020` 并验证：

| 验收项 | 结果 |
|--------|------|
| `/state-observer` 页面 | HTTP 200，包含必要文案 |
| `/api/state-observer?symbol_set=top50&days=3&page=1&page_size=20` | JSON 200，字段完整 |
| `/api/state-observer?symbol_set=top50&days=3&d1_is_ab=1` | 返回 A/B 结果 |
| `/api/state-observer?symbol_set=top50&days=3&d1_is_zero=1` | 返回 0 结果（Top50 中可能为空，全市场有数据） |
| `/api/state-observer/timeline?stock_code=000001.SZ&days=30` | 返回单只股票轨迹 |
| `/api/state-observer?...&format=csv` | 返回 `text/csv` |
| 多只股票查询 | 正常 |
| 日期区间查询 | 正常 |
| 交集模式筛选 `MN1+W1` | 正常（URL 编码后） |
| 行业过滤 | 正常 |
| `scripts/pm_test_preflight.py --date 2026-07-01` | 17/17 passed |

PM preflight 仍全绿，未因本次改动回归。

---

## 八、审计后修复（Codex 复核意见）

### 修复 1：fundamental DB 缺失时优雅降级

问题：`_attach_fundamental()` 在库不存在时直接返回，但主查询仍无条件引用 `fund.ifind_industry_chain_profile`，导致某些环境直接 500。

修复：

- `_attach_fundamental()` 现在返回 bool，标识是否 attach 成功。
- `_build_core_query()` 增加 `has_fundamental` 参数。
- 当 fundamental DB 不可用时，SQL 不再 JOIN 该表，而是直接 SELECT `NULL AS stock_name` 和 `'未分类' AS industry_l1`。
- 行业过滤仅在 fundamental DB 存在时才生效。

验证：临时移走 `fundamental_evidence.duckdb` 后，`/api/state-observer` 仍能正常返回，`stock_name=None`，`industry_l1='未分类'`。

### 修复 2：CSV 导出当前查询全集

问题：CSV 导出只导出当前页（服务层先分页再写入 CSV，前端也把 page/page_size 传过去）。

修复：

- 服务层：`format=csv` 时忽略 `page`/`page_size`，直接查询全部匹配行。
- 前端：`exportCsv()` 独立构建 URL，不带 `page`/`page_size`。

验证：`symbol_set=top50&days=3&page_size=5&format=csv` 返回 150 行数据，不是 5 行。

### 修复 3：symbol_count 与统计卡改为全结果统计

问题：`meta.symbol_count` 和页面统计卡只按当前页 rows 计算，但 UI 文案看起来像全结果统计。

修复：

- 服务层新增 `_compute_full_stats()`，对 core 查询做全量聚合：
  - `row_count`：全结果总行数
  - `symbol_count`：全结果不重复股票数
  - `ef_row_count`：全结果中 EF 行数
  - `ab_row_count`：全结果中 A/B 行数
  - `zero_row_count`：全结果中 0 行数
- 前端统计卡标签明确改为“（全结果）”，并直接使用 API 返回的全结果统计字段。

验证：`symbol_set=top50&days=3&page_size=5` 返回 `meta.symbol_count=50`，`meta.row_count=150`，与全结果一致。

### 已知缺口（非阻塞）

- `symbol_set=watchlist` 当前是占位项，后端故意返回空结果。前端下拉文案已改为“自选池（Phase 2 接入）”。

---

## 九、哪些留到 Phase 2

1. **邮件摘要**：Observer 的每日 HTML 邮件和定时推送。
2. **后台导出任务**：全市场、长时间窗的 CSV/Parquet 异步导出。
3. **自选池 `watchlist`**：当前 `symbol_set=watchlist` 返回空结果，Phase 2 接入真实用户自选。
4. **状态变化摘要**：`state_change_flag`、`transition_label`、`watch_hint` 等增强字段。
5. **Agent 消费接口**：给 Strategy Agent 提供统一只读接口，写入 Observation Ledger。
6. **性能预计算**：如果实时查询性能下降，再考虑每日预计算 `state_timeline_daily` 物化表。
7. **共振/风险标签**：`resonance_tag`、`risk_tag` 等需要更多先验数据后再补充。

---

## 十、部署说明

按 Hermass 固定流程部署：

1. 本地改完并验收通过（已完成）
2. `git add / commit / push`
3. 服务器执行：
   ```bash
   cd /opt/hermass
   git pull
   source .venv/bin/activate
   python -m py_compile web/main.py
   python -m py_compile web/services/state_timeline_observer.py
   sudo systemctl restart hermass-console
   sudo systemctl status hermass-console
   ```
4. 服务器冒烟：
   ```bash
   curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/state-observer
   curl -s "http://localhost:8020/api/state-observer?symbol_set=top50&days=3&page=1&page_size=5" | head -c 200
   ```

不要在服务器上：

- 直接改业务逻辑
- 用系统 Python 编译
- 重新跑重型 Foundation 构建
- 只部署页面不部署 API
