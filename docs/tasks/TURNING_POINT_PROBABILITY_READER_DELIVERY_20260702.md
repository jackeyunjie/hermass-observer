# Turning Point Probability Reader 交付文档

- 日期：2026-07-02
- 执行者：KIMI1
- 任务：`docs/tasks/KIMI1_TASK_TURNING_POINT_PROBABILITY_READER_20260702.md`

---

## 1. 改了哪些文件

| 文件 | 说明 |
|---|---|
| `web/services/turning_point_probability_reader.py` | 新增只读 reader 服务 |
| `web/main.py` | 注册 3 个新 API 路由 |
| `tests/unit/test_turning_point_probability_reader.py` | 新增单元测试 |
| `docs/tasks/TURNING_POINT_PROBABILITY_READER_DELIVERY_20260702.md` | 本文档 |

---

## 2. API 契约

### 2.1 `GET /api/turning-point-probability/summary`

返回产物级摘要。

字段：

- `ok`
- `state_date`
- `model_version`
- `row_count`
- `market_regime`
- `warnings`
- `market_summary`
- `disclaimer`

### 2.2 `GET /api/turning-point-probability/signals?window=3W&limit=50`

返回指定时间窗的 Top 信号列表。

参数：

- `window`：3D / 3W / 3M / 6M，默认 3W
- `limit`：默认 50

返回字段：

- `ok`
- `window`
- `limit`
- `count`
- `signals`：每条含
  - `stock_code`
  - `stock_name`
  - `window`
  - `turning_type`
  - `prob_turn_up`
  - `prob_turn_down`
  - `prob_continue`
  - `prob_false_breakout`
  - `confidence`
  - `evidence_score`
  - `risk_flags`
  - `bucket_sample_size`
  - `market_regime`
  - `industry_l1`
- `disclaimer`

### 2.3 `GET /api/turning-point-probability/stock?stock_code=000001.SZ`

返回单标的 3D / 3W / 3M / 6M 四行。

返回字段：

- `ok`
- `stock_code`
- `count`
- `rows`：数组，字段与 signals 单行一致
- `disclaimer`

---

## 3. 本地验收结果

### 3.1 编译

```bash
.venv/bin/python -m py_compile web/main.py web/services/turning_point_probability_reader.py
```

通过。

### 3.2 单元测试

```bash
.venv/bin/python -m pytest tests/unit/test_turning_point_probability_reader.py -q
```

结果：**8 passed**

覆盖：

1. summary 从 JSON 读取并返回正确字段。
2. summary 在产物缺失时返回 `ok=true`、空数据、warning。
3. signals 从 JSON `top_by_window` 读取。
4. signals 对非法 `window` 返回 `ok=false`。
5. signals 在 JSON 缺失时降级读 DuckDB。
6. stock 从 DuckDB 读取并按 3D/3W/3M/6M 排序。
7. stock 缺少 `stock_code` 时返回 `ok=false`。
8. 三个端点响应中均不含中文交易动作禁用词。

### 3.3 全量网站数据同步校验

```bash
.venv/bin/python scripts/validate_website_data_sync.py --date 20260702
```

结果：**all website data sync checks passed**

### 3.4 预发布巡检

```bash
.venv/bin/python scripts/pm_test_preflight.py --date 2026-07-02
```

结果：**total=17 failed=0**

### 3.5 服务冒烟（可选）

本地服务未启动，未执行 curl 冒烟。测试覆盖已通过 `TestClient` 完成。

---

## 4. 实现要点

### 4.1 读取策略

- **JSON 优先**：`turning_point_probability_latest.json` 存在时直接返回。
- **DuckDB 降级**：JSON 缺失时，summary / signals 回退读 DuckDB；stock 因 JSON 只含 Top 50，直接读 DuckDB。
- **缺产物不 500**：任何读取异常均返回 `ok=true` + `warning` + 空结构。

### 4.2 字段过滤

signals 与 stock 均通过 `_filter_signal_fields` 过滤，不暴露：

- `future_return_n`
- `outcome_label`
- `evidence_items`（保留 `risk_flags`，不返回原始证据列表）
- `source_state_summary`
- `updated_at`

### 4.3 文案边界

- API 不新增任何中文交易动作文案。
- 保留产物中已有的 `risk_flags`（如“低置信”），已通过禁用词检查。
- 返回 `disclaimer` 声明“仅返回状态观察与概率证据，不构成交易建议”。

---

## 5. 风险 / 未完成项

| 风险 | 说明 | 状态 |
|---|---|---|
| `window` 为 DuckDB 保留字 | 已在 reader 的 SQL 中用双引号包裹，消费端无需额外处理 | 已处理 |
| JSON 仅含 Top 50 | stock 端点已直接读 DuckDB，避免覆盖不全 | 已处理 |
| 本地服务未启动 curl 冒烟 | 已通过 `TestClient` 完成路由测试；线上部署后可补 curl | 可选 |
| 概率层未与首页/Agent/Ledger 连接 | 按任务要求保持只读，不接入 | 符合边界 |

---

## 6. 是否可进入 Codex 审计

可以。

已确认：

- ✅ 只新增 `web/services/turning_point_probability_reader.py` 和 3 个只读 API。
- ✅ 修改了 `web/main.py`，未改首页、模板、决策账本。
- ✅ 不接首页、不接 Agent、不写 Ledger。
- ✅ 缺产物时返回 `ok=true`、空数据、warning，不 500。
- ✅ 响应中不含交易动作禁用词。
- ✅ 单元测试、网站同步校验、预发布巡检全部通过。

### 建议 Codex 重点审计

1. `web/main.py` 中新路由是否遵循现有错误处理约定。
2. `disclaimer` 文案是否合适，是否会被前端误读为系统结论。
3. `signals` 返回字段是否满足前端“转折概率”列的需求，是否需要补充 `evidence_items`。
4. DuckDB 降级路径在真实产物上的性能（当前 stock 端点做全表按 stock_code 查询，数据量 2.2 万行，可接受）。
