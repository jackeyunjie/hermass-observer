# Foundation Delta Upload Design

日期：2026-06-01

用途：记录 Hermass 网站数据更新从“每日上传 3.7G 全量 Foundation DB”改为“每日上传当天增量包”的方案。

## 结论

每日网站数据更新不再默认上传完整 `p116_foundation.duckdb`。

当前默认上传两类数据：

1. `foundation_delta`
   - 当天 Foundation 增量包
   - 本地文件：`outputs/foundation_delta_YYYYMMDD/foundation_delta.duckdb`
   - 服务器收到后合并进已有完整 Foundation DB
2. `strategy_signal_daily`
   - 行业页、近期信号、AI 行业判断需要的策略信号快照
   - 本地文件：`outputs/strategy_signals/strategy_signal_daily_YYYYMMDD.json`
   - 服务器同时写入日期文件和 `strategy_signal_daily_latest.json`
3. `snapshot`
   - 每日页面快照
   - 本地文件：`outputs/daily_snapshot.json`
   - 服务器直接覆盖 `outputs/daily_snapshot.json`

2026-06-01 实测：

- 完整 Foundation DB：约 `3.7G`
- 当天增量 DuckDB：约 `8.8M`
- 增量 gzip 上传包：约 `4.4M`
- `strategy_signal_daily_20260601.json`：约 `1.5M`
- `daily_snapshot.json`：约 `1.7M`
- 每日上传量：约 `7.6M`

## 为什么不能只传 daily_snapshot

只传 `daily_snapshot.json` 可以更新首页、市场、行业等轻量页面，但不够支撑完整体验。

完整网站还需要 Foundation DB 支持：

- 股票研究页
- AI 问答中读取行业、状态、指标
- 回测和观察池
- 多周期状态查询

所以更好的体验不是“只传快照”，而是“服务器保留完整 Foundation DB，本地每天只传当天增量”。

## 增量包包含哪些表

脚本：`scripts/build_foundation_delta.py`

从本地当天完整 Foundation DB 中切出相关行：

- `daily_bars`
- `weekly_bars`
- `monthly_bars`
- `timeframe_bars`
- `sr_levels`
- `timeframe_indicators`
- `d1_d_sr`
- `d1_w_sr`
- `d1_mn1_sr`
- `d1_sr_context`
- `d1_perspective_state`

切分规则：

- D1 日线类：取当天 `date/state_date`
- W1 周线类：取当天所在周的 `period_start`
- MN1 月线类：取当天所在月的 `period_start`

原因：周线和月线的 `available_date` 不一定等于交易日。比如 2026-06-01 是周一，W1 的 `available_date` 可能是 2026-06-07，MN1 的 `available_date` 可能是 2026-06-30。如果只按 `available_date = 当天` 裁切，会漏掉周线/月线。

## 服务器如何合并

接口：`POST /api/admin/upload-data`

新增上传类型：

```text
type=foundation_delta
```

服务器保存到：

```text
outputs/foundation_delta_YYYYMMDD/foundation_delta.duckdb
```

然后执行合并：

1. 找服务器现有 Foundation DB
2. attach 上传的增量 DuckDB
3. 每张表按主键先删除旧行
4. 再插入增量行
5. 更新 `foundation_run_log.latest_date`

主键规则：

- `daily_bars`: `stock_code + date`
- `weekly_bars`: `stock_code + period_start`
- `monthly_bars`: `stock_code + period_start`
- `timeframe_bars`: `stock_code + timeframe + period_start`
- `sr_levels`: `stock_code + timeframe + period_start`
- `timeframe_indicators`: `stock_code + timeframe + period_start`
- `d1_*`: `stock_code + state_date`

## 每日流水线现在做什么

脚本：`scripts/run_daily_pipeline.sh`

网站数据更新阶段现在是：

1. 生成 Foundation 增量包

```bash
python scripts/build_foundation_delta.py --date YYYY-MM-DD
```

2. 上传并合并增量包

```bash
python scripts/upload_output_to_server.py --date YYYYMMDD --type foundation_delta
```

3. 上传策略信号快照

```bash
python scripts/upload_output_to_server.py --date YYYYMMDD --type strategy_signal_daily
```

4. 上传快照

```bash
python scripts/upload_output_to_server.py --date YYYYMMDD --type snapshot
```

5. 默认跳过完整 Foundation DB

```text
网站 Foundation DB 跳过（默认不上传 3.7G 大包；需要时设置 UPLOAD_FOUNDATION=1）
```

## 什么时候还要传 3.7G 全量

只有这些场景才需要完整上传：

- 服务器 Foundation DB 丢失或损坏
- 表结构大改
- 历史数据被重算
- 增量合并逻辑升级后需要重新铺底
- 本地和服务器数据长期不一致

手动命令：

```bash
UPLOAD_FOUNDATION=1 ./scripts/run_daily_pipeline.sh YYYY-MM-DD
```

或者单独上传：

```bash
python scripts/upload_output_to_server.py --date YYYYMMDD --type foundation
```

## 验证记录

本地已验证：

- `python -m py_compile web/main.py scripts/upload_output_to_server.py scripts/build_foundation_delta.py`
- `bash -n scripts/run_daily_pipeline.sh`
- 2026-06-01 增量包生成成功
- 临时复制库合并验证通过：
  - 每张表先删除同主键旧行
  - 再插入同数量增量行
  - 行数前后匹配

服务器端已验证：

- 当前 `foundation_delta` 上传方法可用
- 上传后的服务器合并数据可用
- 验收重点不是只看 HTTP 上传成功，还要确认合并后的 Foundation DB 数据能被网站继续读取

### 2026-06-01 网站数据同步记录

状态：成功。

已执行：

```bash
python scripts/upload_output_to_server.py --date 20260601 --type foundation_delta
python scripts/upload_output_to_server.py --date 20260601 --type strategy_signal_daily
python scripts/upload_output_to_server.py --date 20260601 --type snapshot
```

结果：

```text
Foundation 增量包：8.8M，gzip 后 4.4M
foundation_delta 上传并合并成功：11 tables
服务器增量包路径：/opt/hermass/outputs/foundation_delta_20260601/foundation_delta.duckdb
strategy_signal_daily 上传成功：/opt/hermass/outputs/strategy_signals/strategy_signal_daily_20260601.json
snapshot 上传成功：/opt/hermass/outputs/daily_snapshot.json
```

外部入口检查：

```text
http://8.130.125.201/ -> 200
Host: console.supertrader.world -> 401
```

说明：

- `200` 表示服务器入口可访问。
- `401` 表示 `console.supertrader.world` 的 Basic Auth 生效，属于正常结果。
- 本次数据同步后，网站快照数据和 Foundation 增量数据均已更新。
- 行业页依赖 `strategy_signal_daily_*.json`，不是 `daily_snapshot.json`。
- 如果行业页仍显示旧日期，优先检查服务器 `outputs/strategy_signals/strategy_signal_daily_YYYYMMDD.json` 是否已上传。
- 数据上传和合并不需要重启 `hermass-console`；只有部署代码变更时才需要重启服务。

行业页验收：

```text
GET /industry -> 200
最新信号数：1208
快照日期：2026-06-01
```

## 已推送提交

```text
426b0a7 feat: upload daily foundation delta instead of full db
```

该提交包含：

- 新增 `scripts/build_foundation_delta.py`
- 扩展 `scripts/upload_output_to_server.py`
- 扩展 `web/main.py` 的 `foundation_delta` 合并能力
- 调整 `scripts/run_daily_pipeline.sh`
- 更新 `docs/DAILY_WEBSITE_UPDATE_SOP.md`
