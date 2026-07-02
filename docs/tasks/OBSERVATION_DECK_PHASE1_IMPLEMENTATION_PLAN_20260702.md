# 我的观察台 Phase 1 实施计划

日期：2026-07-02
状态：待执行
依据：

- `docs/tasks/OBSERVATION_DECK_CODEX_INTEGRATION_REVIEW_20260702.md`
- `docs/tasks/OBSERVATION_DECK_PRODUCT_SPEC_KIMI_20260702.md`
- `docs/tasks/TURNING_POINT_PROBABILITY_MVP_KIMI1_20260702.md`
- `docs/tasks/CLASSIC_STRATEGY_SIGNAL_SENTINEL_KIMI2_20260702.md`

---

## 目标

把首页从导航型页面收敛为：

> 我的观察台：围绕用户持仓、自选和候选标的，观察 3D / 3W / 3M / 6M 的结构变化、证据与风险。

Phase 1 不实现真实概率引擎，不新增数据库 schema，不改变 State Cube / State Timeline 生成逻辑。

---

## Phase 1 范围

### 必做

1. 首页标题与定位改为“我的观察台”。
2. 顶层导航收敛为：
   - 观察
   - 状态
   - 研究
   - 策略
3. 首页第一屏包含：
   - 观象指令栏
   - 我的标的转折雷达
   - 3D / 3W / 3M / 6M 时间窗矩阵
   - 经典策略信号灯
   - 全市场转折 Top
   - 系统健康
4. 复用现有数据：
   - `state-observer` API / State Timeline
   - `daily_snapshot`
   - `forward_observation`
   - `strategy_signal_daily`
   - `user_task_ledger`
   - `admin data-sync-status`
5. 增加首页禁用词扫描验收。

### 不做

1. 不实现 Empirical Bayesian 概率引擎。
2. 不展示真实概率数值。
3. 不新增 DuckDB 表。
4. 不新建 Agent。
5. 不把经典策略信号写入 State Cube / Decision Ledger。
6. 不输出交易动作建议。
7. 不做新闻流首页。

---

## 建议文件范围

### 修改

- `web/templates/index.html`
  - 首页重构为我的观察台。

- `web/templates/_top_nav.html`
  - 顶层导航收敛。

- `web/main.py`
  - 只做首页所需数据聚合。
  - 不新增持久化 schema。

- `scripts/validate_website_data_sync.py`
  - 增加首页 200、禁用词、关键模块文案冒烟。

### 可选新增

- `web/services/classic_strategy_sentinel.py`
  - 若首页需要真实读取经典策略信号标签，则从 `outputs/strategy_signals/strategy_signals.duckdb` 只读查询。
  - 不动态调用策略函数。

---

## 首页数据降级策略

Phase 1 必须允许部分数据缺失而不 500。

| 数据 | 缺失时 |
|---|---|
| watchlist / user_tasks | 展示全市场转折 Top |
| strategy_signal_daily | 隐藏经典策略信号灯 |
| state_timeline materialized | 回退实时 CTE 或显示“状态数据读取中” |
| system health | 显示“部分状态未知”，不阻断首页 |
| stock_name / industry | 显示代码，不阻断 |

---

## 首页文案口径

允许：

- 转强早期
- 确认转强
- 强势延续
- 转弱预警
- 确认转弱
- 结构未破坏
- 未进入候选
- 证据不足
- 假突破风险
- 数据异常
- 状态：持续观察中
- 等待更多数据确认

禁止作为系统结论出现：

- 买入
- 卖出
- 加仓
- 减仓
- 清仓
- 空仓
- 加杠杆
- 止盈
- 止损
- 目标价
- 收益承诺
- 推荐买
- 推荐卖
- 适合交易

---

## 经典策略信号灯 Phase 1 规则

首页只显示聚合标签，不显示详情条文。

允许标签：

- `VCP 规则信号`
- `2560 规则信号`
- `布林规则信号`
- `VCP 失效信号`
- `2560 风险信号`
- `布林规则风险`

不允许首页出现：

- 入场
- 离场
- 止损
- 止盈
- 仓位
- 买点
- 卖点

信号来源：

- 只读 `outputs/strategy_signals/strategy_signals.duckdb` 或最新 JSON。
- 不在 Web 请求时重新计算策略。

---

## 验收标准

### 本地验收

```bash
.venv/bin/python -m py_compile web/main.py
.venv/bin/python -m py_compile scripts/validate_website_data_sync.py
.venv/bin/python scripts/validate_website_data_sync.py --date 20260702
.venv/bin/python scripts/pm_test_preflight.py --date 2026-07-02
```

如新增 service / tests，补充：

```bash
.venv/bin/python -m py_compile web/services/classic_strategy_sentinel.py
.venv/bin/python -m pytest tests/unit/test_classic_strategy_sentinel.py -q
```

### 页面验收

1. `/` HTTP 200。
2. 首页标题包含“我的观察台”。
3. 顶层导航只有“观察 / 状态 / 研究 / 策略”四项。
4. 首页包含：
   - 观象指令栏
   - 我的标的转折雷达
   - 3D / 3W / 3M / 6M
   - 经典策略信号灯
   - 全市场转折 Top
   - 系统健康
5. 首页不出现禁用词。
6. `/state-observer` 原功能不回归。
7. `/api/chat/query` 仍保持未授权 401、授权 200。

### 公网验收

```bash
curl -s -o /dev/null -w "%{http_code}" http://console.supertrader.world/
curl -s -o /dev/null -w "%{http_code}" http://console.supertrader.world/state-observer
curl -s -o /dev/null -w "%{http_code}" -X POST http://console.supertrader.world/api/chat/query -H 'Content-Type: application/json' -d '{"message":"ping","mode":"chat","use_llm":false}'
curl -s -u 'hermass-test:Hermass2026!Lab' -o /dev/null -w "%{http_code}" -X POST http://console.supertrader.world/api/chat/query -H 'Content-Type: application/json' -d '{"message":"ping","mode":"chat","use_llm":false}'
```

预期：

- 首页 200
- State Observer 200
- chat 未授权 401
- chat 授权 200

---

## 实施顺序

1. 读取当前首页、导航、main 路由和现有数据聚合函数。
2. 先实现静态结构和禁用文案。
3. 再接入低风险现有数据。
4. 最后接入经典策略信号灯，只读最新信号产物。
5. 本地验收。
6. Git commit / push。
7. 服务器 git pull、py_compile、restart、公网冒烟。

---

## 风险控制

1. 如果首页数据聚合复杂度过高，Phase 1 先用已有 JSON 生成静态摘要，不接新 API。
2. 如果经典策略信号表结构与 KIMI2 文档不一致，先隐藏信号灯，不阻断首页。
3. 如果导航收敛影响旧入口，保留工具箱二级入口，不删除路由。
4. 如果出现禁用词，优先改文案，不改底层策略数据。

