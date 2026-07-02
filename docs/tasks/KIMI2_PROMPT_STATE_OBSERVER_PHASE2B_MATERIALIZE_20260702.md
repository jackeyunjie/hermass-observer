# KIMI2 任务：State Timeline Observer Phase 2B — 预计算表 + 查询切换准备

日期：2026-07-02  
负责人：KIMI2  
范围：**只动物化脚本、`web/services/state_timeline_observer.py` 和对应测试**  

---

## 一、任务目标

为 State Timeline Observer 实现每日预计算表，并在查询服务中加入切换开关。本期**只实现脚本与开关逻辑**，默认关闭，不接入 cron、不改动页面、不发邮件。

---

## 二、必读前置文档

1. `docs/STATE_TIMELINE_OBSERVER_SPEC.md` — 设计稿
2. `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2_PLAN_20260701.md` — Phase 2 可执行方案
3. `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE1_DELIVERY_20260701.md` — Phase 1 交付说明
4. `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2B_IMPLEMENTATION_AUDIT_20260701.md` — Phase 2B 实现级审计（本文档的详细依据）

---

## 三、允许修改的文件（仅限以下 3 个）

| # | 路径 | 动作 | 说明 |
|---|------|------|------|
| 1 | `scripts/materialize_state_timeline_daily.py` | 新增 | 每日物化脚本 |
| 2 | `web/services/state_timeline_observer.py` | 修改 | 增加预计算表查询切换开关 |
| 3 | `tests/unit/test_state_timeline_materialize.py` | 新增 | 物化与切换单元测试 |

---

## 四、禁止修改的文件

以下文件本期**不要碰**，避免和产品主线冲突：

- `web/templates/state-observer.html`
- `web/main.py`
- `config/hermes_cron.json`
- `agently_adapter/tools/state_timeline_reader.py`
- `scripts/send_state_timeline_digest_email.py`
- `web/services/state_timeline_export_worker.py`
- `AGENTS.md`

---

## 五、具体实现要求

### 5.1 物化脚本 `scripts/materialize_state_timeline_daily.py`

#### 功能

读取最新 Foundation DB，执行与 `web/services/state_timeline_observer._build_core_query()` 等价的查询，生成当日的预计算 DuckDB。

#### 输出

```text
outputs/state_timeline/state_timeline_daily_YYYYMMDD.duckdb
```

例如：

```text
outputs/state_timeline/state_timeline_daily_20260702.duckdb
```

#### 表名

`state_timeline_daily`

#### 表字段

与 `_build_core_query()` 当前 SELECT 输出完全同构，必须包含：

```text
stock_code, stock_name, industry_l1, state_date,
mn1_state_hex, w1_state_hex, d1_state_hex,
mn1_state_score, w1_state_score, d1_state_score,
mn1_is_ef, w1_is_ef, d1_is_ef,
mn1_is_ab, w1_is_ab, d1_is_ab,
mn1_is_zero, w1_is_zero, d1_is_zero,
ef_count, ef_pattern,
ab_count, ab_pattern,
zero_count, zero_pattern,
state_triplet,
state_change_flag, ef_change, transition_label,
close, volume,
display_alias,
as_of_date
```

注意：
- `display_alias` 在物化阶段直接写入表，减少查询时读取 JSON 文件的开销。
- 只物化**单个交易日**的数据（`state_date = ?`），文件日期 = 数据日期。

#### 建索引

```sql
CREATE INDEX idx_stock_date ON state_timeline_daily(stock_code, state_date);
CREATE INDEX idx_state_date ON state_timeline_daily(state_date);
CREATE INDEX idx_industry ON state_timeline_daily(industry_l1);
CREATE INDEX idx_ef_pattern ON state_timeline_daily(ef_pattern);
CREATE INDEX idx_ab_pattern ON state_timeline_daily(ab_pattern);
CREATE INDEX idx_zero_pattern ON state_timeline_daily(zero_pattern);
```

#### CLI

```bash
.venv/bin/python scripts/materialize_state_timeline_daily.py --date 2026-07-02
.venv/bin/python scripts/materialize_state_timeline_daily.py               # 默认用 Foundation DB 最新日期
```

#### 实现建议

1. 从 `web.services.state_timeline_observer` import：
   - `find_foundation_db`
   - `_attach_fundamental`
   - `_resolve_date_range`
   - `_build_core_query`
   - `_compute_top50_codes`（若物化全市场，symbol_set 传 None 即可）
2. 连接 Foundation DB，attach fundamental。
3. 调用 `_resolve_date_range` 得到 `date_from == date_to` 的单个交易日。
4. 调用 `_build_core_query(symbols=None, symbol_set=None, ...)` 构造全市场单日查询。
5. 用该查询创建新 DuckDB 并写入表 + 索引。

---

### 5.2 查询服务 `web/services/state_timeline_observer.py`

#### 新增开关

在模块级增加：

```python
import os

USE_STATE_TIMELINE_MATERIALIZED = os.environ.get("USE_STATE_TIMELINE_MATERIALIZED", "0") == "1"
```

#### 命中预计算表的条件（必须同时满足）

1. `USE_STATE_TIMELINE_MATERIALIZED == "1"`
2. 存在 `outputs/state_timeline/state_timeline_daily_YYYYMMDD.duckdb`
3. 文件名日期 `YYYYMMDD` 等于本次查询的 `date_to`（或 Foundation DB 最新日期）
4. 查询时间范围是单个交易日：`date_from == date_to` 或 `days == 1`
5. `symbol_set` 为 `None` 或 `"top50"` 或 `"watchlist"`（预计算表是全市场，过滤在内存或 SQL 中完成）

任一条件不满足 → fallback 到现有实时 CTE。

#### 新增辅助函数

建议新增以下私有函数（名称可调整）：

```python
def _find_materialized_db(target_date: date) -> Path | None:
    """查找对应日期的预计算表文件。"""


def _query_materialized(
    materialized_db: Path,
    symbols: list[str] | None,
    symbol_set: str | None,
    target_date: date,
    filters: dict[str, Any],
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """从预计算表读取数据，返回 rows 和 columns。"""
```

#### `query_state_timeline()` 改动点

1. 在连接 Foundation DB 之前，先判断是否命中预计算表。
2. 若命中：
   - 连接预计算 DB（read_only=True）。
   - 执行带过滤/分页的 SQL，读取 `state_timeline_daily`。
   - 返回结构与实时查询完全一致（含 `ok`, `query`, `meta`, `rows`）。
   - `meta` 统计可直接从 `rows` 计算，无需全表 COUNT。
3. 若未命中：保持现有 CTE 逻辑不变。

#### CSV 导出

命中预计算表时，CSV 导出同样从预计算 DB 读取全部匹配行，不应用 `page`/`page_size`。

---

### 5.3 单元测试 `tests/unit/test_state_timeline_materialize.py`

#### 必备用例

1. `test_materialize_creates_duckdb`
   - 运行脚本，断言生成了 `outputs/state_timeline/state_timeline_daily_YYYYMMDD.duckdb`
   - 断言表存在、字段完整

2. `test_materialized_schema_matches_core_query`
   - 对比物化表字段与 `_build_core_query()` 输出字段一致

3. `test_query_uses_materialized_when_switch_on`
   - 设置 `USE_STATE_TIMELINE_MATERIALIZED=1`
   - 物化当天数据
   - 调用 `query_state_timeline(symbols="all", days=1)`
   - 断言返回结构与实时查询一致，且包含 `rows`

4. `test_query_falls_back_to_cte_when_no_materialized_db`
   - 设置开关打开但删除物化文件
   - 断言查询仍成功，走 CTE fallback

5. `test_query_falls_back_for_multi_day_range`
   - 设置开关打开
   - 查询 `days=5`
   - 断言走 CTE fallback（因为物化表只有单日）

6. `test_materialized_filters_work`
   - 物化后查询 `filters={"d1_is_ef": True}`
   - 断言返回行全部 `d1_is_ef is True`

#### 测试原则

- 不要依赖 `web/main.py` 或 HTTP 服务。
- 可以直接调用 `scripts/materialize_state_timeline_daily.py` 的 `main()` 或内部函数。
- 测试结束后尽量清理临时产物，但保留 `outputs/state_timeline/` 作为正常产物目录。

---

## 六、验收标准

1. `python -m py_compile` 通过：
   - `scripts/materialize_state_timeline_daily.py`
   - `web/services/state_timeline_observer.py`
   - `tests/unit/test_state_timeline_materialize.py`

2. 单元测试通过：
   ```bash
   .venv/bin/python -m pytest tests/unit/test_state_timeline_materialize.py -v
   ```

3. 物化脚本运行成功：
   ```bash
   .venv/bin/python scripts/materialize_state_timeline_daily.py --date 2026-07-02
   ls outputs/state_timeline/state_timeline_daily_20260702.duckdb
   ```

4. 开关关闭时，现有行为不变：
   ```bash
   .venv/bin/python -m pytest tests/unit/test_state_timeline_reader.py -v
   ```

5. 开关打开且物化表存在时，单日查询走预计算表且结果字段与实时查询一致。

---

## 七、红线

- 不要把预计算表切换开关默认打开。
- 不要修改 `web/templates/state-observer.html`。
- 不要修改 `web/main.py`。
- 不要把物化表做成跨多日宽表。
- 不要写入 AgentMemory / Observation Ledger。
- 不要把 `ef_count` 重新提升为主口径。

---

## 八、与产品主线的衔接

产品主线当前负责：
- watchlist 真实接入
- 状态变化摘要字段
- 页面最小展示

KIMI2 负责：
- 预计算表产物
- 查询层切换开关

衔接点：
- 若产品主线调整了 `_build_core_query()` 的 SELECT 字段，物化脚本必须同步。
- `state_change_flag` / `ef_change` / `transition_label` 已经存在，物化表直接包含即可。

---

## 九、提交前检查

```bash
cd /Users/lv111101/Documents/hermass-observer-product
.venv/bin/python -m py_compile scripts/materialize_state_timeline_daily.py
.venv/bin/python -m py_compile web/services/state_timeline_observer.py
.venv/bin/python -m py_compile tests/unit/test_state_timeline_materialize.py
.venv/bin/python -m pytest tests/unit/test_state_timeline_materialize.py tests/unit/test_state_timeline_reader.py -v
```

全部 green 后，告知父代理验收结果。
