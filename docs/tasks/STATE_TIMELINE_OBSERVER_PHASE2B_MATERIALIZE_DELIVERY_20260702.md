# State Timeline Observer Phase 2B 交付说明：预计算表与切换准备

日期：2026-07-02  
范围：`state_timeline_daily` 物化脚本 + 查询层可选切换开关  
状态：本地验收通过，默认关闭，不影响线上现状

---

## 一、交付内容

本线新增了 `State Timeline Observer` 的单日预计算产物能力，并让查询层具备受控切换能力：

1. 新增脚本 `scripts/materialize_state_timeline_daily.py`
2. 新增物化产物目录 `outputs/state_timeline/`
3. 在 `web/services/state_timeline_observer.py` 增加：
   - `USE_STATE_TIMELINE_MATERIALIZED=1` 开关
   - 单日查询优先读物化表
   - 缺文件 / 跨天 / 条件不满足时自动 fallback 到实时 CTE
4. 补充物化与切换单元测试

---

## 二、产物约定

脚本：

```bash
.venv/bin/python scripts/materialize_state_timeline_daily.py --date 2026-07-01
```

输出：

```text
outputs/state_timeline/state_timeline_daily_20260701.duckdb
```

表名：

```text
state_timeline_daily
```

字段口径：

- 与当前 `State Timeline Observer` 核心查询输出同构
- 包含 EF / A+B / 0 事件族字段
- 包含 `state_change_flag` / `ef_change` / `transition_label`
- 包含 `display_alias`

索引：

- `idx_stock_date`
- `idx_state_date`
- `idx_industry`
- `idx_ef_pattern`
- `idx_ab_pattern`
- `idx_zero_pattern`

---

## 三、切换规则

默认行为：

- 继续走实时 CTE
- 不改变现有 API 返回结构

只有同时满足以下条件时，才会命中物化表：

1. `USE_STATE_TIMELINE_MATERIALIZED=1`
2. 查询是单日（`date_from == date_to`）
3. 对应日期的 `state_timeline_daily_YYYYMMDD.duckdb` 存在

不满足时自动 fallback 到实时查询，不报错。

---

## 四、边界说明

本线没有改：

- `web/main.py`
- `web/templates/state-observer.html`
- `config/hermes_cron.json`
- `scripts/send_state_timeline_digest_email.py`
- `agently_adapter/tools/state_timeline_reader.py`
- `AGENTS.md`

本线不负责：

- 异步导出 API
- 邮件摘要
- 正式 cron 接入
- 服务器部署

---

## 五、本地验收

```bash
cd /Users/lv111101/Documents/hermass-observer-product
.venv/bin/python -m py_compile scripts/materialize_state_timeline_daily.py
.venv/bin/python -m py_compile web/services/state_timeline_observer.py
.venv/bin/python -m pytest tests/unit/test_state_timeline_materialize.py -q
.venv/bin/python scripts/materialize_state_timeline_daily.py --date 2026-07-01
```

补充验证：

```bash
USE_STATE_TIMELINE_MATERIALIZED=1 .venv/bin/python - <<'PY'
from web.services.state_timeline_observer import query_state_timeline
r = query_state_timeline(symbol_set='top50', days=1, page_size=5)
print(r['ok'], len(r['rows']), r['meta']['row_count'])
PY
```

验收结论：

- 编译通过
- 单测通过
- 物化脚本成功生成 `5513` 行 DuckDB
- 开关开启后单日 Top50 查询可正常命中物化表
- 空 watchlist 在物化路径下不会错误退化成全市场

---

## 六、已知风险

1. 物化表字段与核心查询保持同步，后续若核心查询字段调整，物化脚本需同步修改。
2. 默认开关关闭，尚未进行正式线上 A/B。
3. 目前仅针对单日查询命中物化表，跨天窗口仍走实时 CTE。

