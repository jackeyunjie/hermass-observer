# KIMI2 任务：经典策略信号哨兵 MVP 实现

日期：2026-07-02
执行者：KIMI2
任务类型：Web service / API / 页面 / 单元测试

---

## 背景

设计文档：

- `docs/tasks/CLASSIC_STRATEGY_SIGNAL_SENTINEL_KIMI2_20260702.md`
- `docs/tasks/OBSERVATION_DECK_CODEX_INTEGRATION_REVIEW_20260702.md`

Codex 裁决：

- 经典策略哨兵独立于 State 主系统。
- 第一批策略：VCP、2560、布林强盗。
- ATR 吊灯暂缓。
- 首页只显示中性规则标签。
- 详情页可以展示经典策略原始规则，但必须有 Research-Only 免责声明。

---

## 你的目标

实现经典策略信号哨兵 MVP。

核心能力：

1. 从 `outputs/strategy_signals/strategy_signal_daily_latest.json` 或 `strategy_signals.duckdb` 只读读取信号。
2. 提供独立 API。
3. 提供独立页面。
4. 不影响首页、不影响 State 系统。

---

## 建议文件范围

新增：

- `web/services/classic_strategy_sentinel.py`
- `web/templates/sentinel_overview.html`
- `web/templates/sentinel_detail.html`
- `tests/unit/test_classic_strategy_sentinel.py`
- `docs/tasks/CLASSIC_STRATEGY_SENTINEL_DELIVERY_20260702.md`

修改：

- `web/main.py`
  - 增加 API / 页面路由。
- `web/templates/_top_nav.html`
  - 工具箱增加“经典策略哨兵”入口。

---

## 路由要求

页面：

```text
/sentinel
/sentinel/{strategy}
/sentinel/detail?strategy=vcp&stock_code=000021.SZ&date=2026-07-02
```

API：

```text
GET /api/sentinel/overview?date=2026-07-02
GET /api/sentinel/signals?strategy=vcp&date=2026-07-02
GET /api/sentinel/detail?strategy=vcp&stock_code=000021.SZ&date=2026-07-02
```

---

## 首页与语义边界

本任务不改首页。

首页后续只消费 overview 聚合标签：

- `VCP 规则信号`
- `2560 规则信号`
- `布林规则信号`
- `VCP 失效信号`
- `2560 风险信号`
- `布林规则风险`

首页不出现：

- 入场
- 离场
- 止损
- 止盈
- 仓位
- 买点
- 卖点

详情页可以出现经典策略原始术语，但必须加免责声明：

> 以下为经典策略原始规则触发说明，仅作研究观察，不构成交易建议。

---

## 实现边界

必须：

- 只读 `strategy_signal_daily_latest.json` 或 `strategy_signals.duckdb`。
- 不在 Web 请求时动态计算策略。
- 不写 State Cube。
- 不写 Decision Ledger。
- 不进入 Agent 辩论。
- 不影响 State Timeline。
- 缺数据时返回 `ok=true`、空列表和 warning，不 500。

禁止：

- 输出“适合交易 / 推荐 / 应执行”。
- 把策略信号和 State 说成同向/冲突/领先。
- 生成综合评分。
- 修改策略信号生成算法。

---

## 测试要求

新增：

`tests/unit/test_classic_strategy_sentinel.py`

至少覆盖：

1. overview 返回三类策略聚合。
2. 只包含允许策略：vcp / ma2560 / bollinger_bandit。
3. ATR 吊灯不会进入第一批。
4. 缺少信号文件时 ok=true 且 rows=[]。
5. detail 页面/API 有免责声明。
6. API 不返回 State 同向/冲突/领先字段。
7. 首页禁用词不会从哨兵 API 泄露。

---

## 验收命令

```bash
.venv/bin/python -m py_compile web/main.py
.venv/bin/python -m py_compile web/services/classic_strategy_sentinel.py
.venv/bin/python -m py_compile tests/unit/test_classic_strategy_sentinel.py
.venv/bin/python -m pytest tests/unit/test_classic_strategy_sentinel.py -q
```

如启动本地服务：

```bash
curl -s http://127.0.0.1:8020/api/sentinel/overview?date=2026-07-02 | head -c 500
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8020/sentinel
```

---

## 输出文件

请写入交付文档：

`docs/tasks/CLASSIC_STRATEGY_SENTINEL_DELIVERY_20260702.md`

---

## 返回格式

完成后回复：

1. 改了哪些文件。
2. 新增了哪些 API / 页面。
3. 测试结果。
4. 如何保证与 State 主系统隔离。
5. 是否可进入 Codex 审计。
