# 经典策略信号哨兵 MVP 交付文档

日期：2026-07-02
执行者：KIMI2
任务来源：`docs/tasks/KIMI2_TASK_CLASSIC_STRATEGY_SENTINEL_IMPLEMENT_20260702.md`

---

## 1. 交付范围

### 1.1 新增文件

| 文件 | 用途 |
|------|------|
| `web/services/classic_strategy_sentinel.py` | 哨兵数据查询服务，只读消费 `outputs/strategy_signals/strategy_signal_daily_latest.json` 或 `strategy_signals.duckdb` |
| `web/templates/sentinel_overview.html` | 哨兵总览页，展示当日三类策略的规则信号统计 |
| `web/templates/sentinel_detail.html` | 单策略信号列表 + 单标的规则详情（含免责声明） |
| `tests/unit/test_classic_strategy_sentinel.py` | 单元测试，覆盖边界隔离、禁用词、路由、数据缺失等 26 个用例 |

### 1.2 修改文件

| 文件 | 修改内容 |
|------|----------|
| `web/main.py` | 新增 3 个页面路由 + 3 个 API 路由；导入哨兵服务 |
| `web/templates/_top_nav.html` | 工具箱下拉菜单增加「经典策略哨兵」入口 |

---

## 2. 新增路由

### 2.1 页面

```text
GET /sentinel?date=2026-07-02
GET /sentinel/{strategy}?date=2026-07-02          # strategy ∈ {vcp, ma2560, bollinger_bandit}
GET /sentinel/detail?strategy=vcp&stock_code=000021.SZ&date=2026-07-02
```

### 2.2 API

```text
GET /api/sentinel/overview?date=2026-07-02
GET /api/sentinel/signals?strategy=vcp&date=2026-07-02
GET /api/sentinel/detail?strategy=vcp&stock_code=000021.SZ&date=2026-07-02
```

---

## 3. 测试结果

### 3.1 编译检查

```bash
.venv/bin/python -m py_compile web/main.py
.venv/bin/python -m py_compile web/services/classic_strategy_sentinel.py
.venv/bin/python -m py_compile tests/unit/test_classic_strategy_sentinel.py
```

结果：全部通过。

### 3.2 单元测试

```bash
.venv/bin/python -m pytest tests/unit/test_classic_strategy_sentinel.py -q
```

结果：

```text
26 passed
```

### 3.3 回归测试

```bash
.venv/bin/python -m pytest tests/unit/test_state_observer_api.py tests/unit/test_strategy_signals.py -q
```

结果：

```text
70 passed
```

---

## 4. 与 State 主系统的隔离保证

| 维度 | 措施 |
|------|------|
| 数据源 | 只读 `outputs/strategy_signals/strategy_signal_daily_latest.json` 或 `strategy_signals.duckdb` |
| 数据流 | 不写入 `state_cube.duckdb`、`decision_observation.duckdb` 或任何 State 相关数据库 |
| 计算层 | Web 请求期间不调用策略信号函数，不做动态计算 |
| 语义层 | overview API 仅返回中性标签（如 `VCP 规则信号`、`2560 风险信号`），不出现「买入/卖出/止损/止盈/仓位」 |
| 展示层 | 原始规则条文仅在 `/sentinel/detail` 展示，且页面顶部固定 Research-Only 免责声明 |
| Agent | 不参与 Agent 辩论，不进入 Decision Observation Ledger |
| 路由 | 独立 `/sentinel/*` 路由，不影响 `/`、`/state-observer`、`/research`、`/mystrategies` |

### 4.1 禁用词扫描结果

单元测试已确认：

- overview API 文本中不包含：`买入、卖出、加仓、减仓、清仓、空仓、加杠杆、止盈、止损、目标价、收益承诺、适合交易、推荐买、推荐卖、入场、出场、买点、卖点、仓位`。
- 所有哨兵 API 文本中不包含：`同向、冲突、领先、转折概率`。

---

## 5. 当前第一批策略

```text
{vcp, ma2560, bollinger_bandit}
```

ATR 吊灯（`atr_chandelier`）已被服务层明确排除，单元测试已覆盖该边界。

---

## 6. 验收命令

```bash
.venv/bin/python -m py_compile web/main.py
.venv/bin/python -m py_compile web/services/classic_strategy_sentinel.py
.venv/bin/python -m py_compile tests/unit/test_classic_strategy_sentinel.py
.venv/bin/python -m pytest tests/unit/test_classic_strategy_sentinel.py -q
```

本地服务启动后可选：

```bash
curl -s http://127.0.0.1:8020/api/sentinel/overview?date=2026-07-02 | head -c 500
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8020/sentinel
```

---

## 7. 是否可进入 Codex 审计

是。本实现满足 `docs/tasks/OBSERVATION_DECK_CODEX_INTEGRATION_REVIEW_20260702.md` 的修正要求：

1. ✅ 文件位置改为 `web/services/classic_strategy_sentinel.py`，不再使用 `scripts/sentinel_api.py`。
2. ✅ 首页 overview 不只展示 entry，exit/risk 类信号也以中性标签展示。
3. ✅ 详情页展示原始规则条文，但顶部固定免责声明。
4. ✅ Web 请求期间只读 `strategy_signals.duckdb`，不动态调用策略函数。

---

## 8. 备注

- `outputs/strategy_signals/strategy_signal_daily_latest.json` 存在时优先使用；缺失时回退到 `strategy_signals.duckdb` 的 `strategy_signal_daily` 表。
- 缺数据时所有 API 返回 `ok=true`、空列表和 `warning`，不抛 500。
- 结构类（`structure`）信号不在 overview 首页展示，避免噪音。
