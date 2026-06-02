# Daily Data Refresh Dependency Audit

版本：v1.0
日期：2026-06-02

## 结论

Hermass 页面是否“最新”，不能看浏览器右上角日期，也不能看服务是否重启成功。必须看页面实际依赖的数据文件日期。

2026-06-02 的行业页排查结论：

- 页面服务是最新代码，没有证据显示代码回退。
- 页面实际数据日期是 `2026-06-01`。
- `strategy_signal_daily_20260602.json` 不存在。
- `foundation_delta_20260602/foundation_delta.duckdb` 不存在。
- 因此该页面不是 2026-06-02 最新数据，只是使用了上一轮同步成功的数据。

## 必须每日重算的数据

| 层级 | 产物 | 主要消费者 | 当前要求 |
|---|---|---|---|
| 原始行情 | P108 raw DB | Foundation | 每个交易日收盘后重算 |
| State 底座 | `outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb` | 研究页、回测、AI 个股判断 | 每个交易日重算 |
| State 缓存 | `outputs/state_cache/state_ef_YYYYMMDD.json`、`state_duration_YYYYMMDD.json`、`sr_boundary_YYYYMMDD.json` | 策略信号、提醒、统一视图 | 每个交易日重算，不能用旧缓存 |
| 策略信号 | `outputs/strategy_signals/strategy_signal_daily_YYYYMMDD.json` | 行业页近期信号、AI 行业扫描 | 每个交易日重算并上传 |
| 网站快照 | `outputs/daily_snapshot.json` | 首页、市场页、AI 市场回答 | 每个交易日重算并上传 |
| Foundation 增量 | `outputs/foundation_delta_YYYYMMDD/foundation_delta.duckdb` | 服务器 Foundation 合并 | 每个交易日生成并上传 |
| 前向观察 | `outputs/forward_observation/forward_observation_YYYYMMDD.json` | 执行页、AI 盯盘 | 每个交易日重算 |
| 宽基/行业 ETF | `outputs/market_assets_state/market_assets_state_YYYYMMDD.json` | 市场页、行业方向 | 每个交易日重算 |
| 统一视图 | `outputs/unified_view/unified_daily_snapshot_YYYY-MM-DD.csv` | 研究页资金流、行业承接 | 每个交易日重算 |
| 行业承接 | `outputs/industry_rotation/industry_rotation_YYYYMMDD.json` | 首页、研究页、AI 行业判断 | 每个交易日重算或明确标注非日更 |
| 宏观/产业链先验 | `outputs/macro_chain_prior/macro_chain_prior_latest.json` | 市场页、策略提醒 | 低频可容忍，但状态接口必须显示日期 |

## 后端验收口径

`/api/admin/data-sync-status?date=YYYYMMDD` 是服务器端真相源。

必须至少满足：

- `daily_snapshot.date == expected_date`
- `strategy_signal_daily.date == expected_date`
- `strategy_signal_latest.date == expected_date`
- `foundation_delta.exists == true`
- `foundation_db.latest_date >= expected_date`
- `foundation_db.daily_rows > 0`
- `foundation_db.state_rows > 0`
- `state_cache.state_ef.date == expected_date`
- `state_cache.state_duration.date == expected_date`
- `state_cache.sr_boundary.date == expected_date`
- `market_phase.date == expected_date`
- `market_assets_state.date == expected_date`
- `unified_view.date == expected_date`

如果任一项失败，当日网站不能称为已更新。

## 每日上传白名单

`/api/admin/upload-data` 只允许固定类型写入固定路径：

| type | 服务器落点 |
|---|---|
| `foundation_delta` | `outputs/foundation_delta_YYYYMMDD/foundation_delta.duckdb` |
| `snapshot` | `outputs/daily_snapshot.json` |
| `strategy_signal_daily` | `outputs/strategy_signals/strategy_signal_daily_YYYYMMDD.json` 和 latest |
| `state_ef` | `outputs/state_cache/state_ef_YYYYMMDD.json` |
| `state_duration` | `outputs/state_cache/state_duration_YYYYMMDD.json` |
| `sr_boundary` | `outputs/state_cache/sr_boundary_YYYYMMDD.json` |
| `market_phase` | `outputs/market_phase/market_phase_YYYYMMDD.json` 和 latest |
| `market_assets_state` | `outputs/market_assets_state/market_assets_state_YYYYMMDD.json` |
| `unified_view` | `outputs/unified_view/unified_daily_snapshot_YYYY-MM-DD.csv` |
| `forward_observation` | `outputs/forward_observation/forward_observation_YYYYMMDD.json` |
| `macro_chain_prior` | `outputs/macro_chain_prior/macro_chain_prior_YYYYMMDD.json` 和 latest |
| `industry_rotation` | `outputs/industry_rotation/industry_rotation_YYYYMMDD.json` |

## 前端验收口径

页面顶部日期只能表示“页面访问日期”或“数据日期”之一，不能混用。

行业页已固定为：

- 顶部显示 `数据 {{ industry.date }}`。
- “快照日期”显示策略信号文件日期。
- “近期信号”按公司去重，同一家公司命中多个策略时合并展示。

## AI 助手验收口径

AI 助手回答必须遵守同一套数据日期：

- 市场方向回答看 `daily_snapshot.date`。
- 行业回答看 `strategy_signal_daily.date` 和行业承接日期。
- 个股回答看 Foundation 最新 `state_date` 和研究证据 `as_of_date`。
- 如果用户问“今天”，而状态接口没有当天数据，必须说明“当前可用数据截至 YYYY-MM-DD”。

## Agent 分工

以后按四个 agent 职责检查，不再靠用户截图发现：

1. Data Build Agent：负责本地每日重算，保证所有产物日期一致。
2. Website Sync Agent：负责上传 `foundation_delta`、`daily_snapshot`、`strategy_signal_daily`，并调用状态接口。
3. Frontend Regression Agent：负责打开关键页面，看页面显示日期、数量、重复行、跳转链接。
4. AI Workflow Agent：负责 `/api/chat/query` 连续对话、行业追问、个股研究、任务模式验收。

## 关键假设

- “服务 active running”只说明程序在跑，不说明数据最新。
- “git log 是最新提交”只说明代码最新，不说明网站数据最新。
- “页面右上角是今天”不能证明数据是今天。
- “近期信号数变化”不能证明完整链路更新，必须结合状态接口。
- 同一股票多策略命中不是数据回退，但前端展示应按公司合并，避免用户误认为重复或回退。
