# Daily Website Update SOP

版本：v1.0  
日期：2026-05-30  
对象：Hermass 运营 / 内部维护者

## 目标

把“每日数据更新”和“网站功能更新”拆开处理。  
默认情况下：

- **每日只更新数据**
- **只有功能改动时才更新代码**

这样可以避免每个交易日都重新部署整站。

---

## 1. 两类更新的区别

### 1.1 数据更新

适用场景：

- 新交易日收盘后
- 需要更新 market / industry / watchlist / research / backtest 数据

特点：

- 不改代码
- 不需要 `git push`
- 重点是生成新的 `outputs/`

### 1.2 代码更新

适用场景：

- 页面改版
- AI 助手升级
- 新增研究视图
- 修 Bug

特点：

- 需要 `git commit` / `git push`
- 服务器需要 `git pull`

---

## 2. 每个交易日的数据更新

### 2.1 标准做法：收盘后跑流水线

优先使用一键入口：

```bash
python3 agently_adapter/stockpool_daily_runner.py run \
  --date 2026-05-30 \
  --previous-date 2026-05-29 \
  --foundation-db outputs/p116_foundation_20260530/p116_foundation.duckdb
```

如果需要分步执行，参考：

```bash
python3 scripts/download_daily.py --date 2026-05-30
python3 scripts/build_p116_foundation.py --date 2026-05-30
python3 scripts/state_cache_builder.py --date 2026-05-30
python3 scripts/build_market_assets_state.py --date 2026-05-30
python3 scripts/build_industry_etf_config.py --date 2026-05-30
python3 scripts/strategy_signal_ledger.py --date 2026-05-30
python3 scripts/build_macro_chain_prior.py --date 2026-05-30
python3 scripts/run_daily_all_three_ef_workflow.py --date 2026-05-30
python3 scripts/strategy_reminder_brief.py --date 2026-05-30
python3 scripts/daily_research_brief.py --date 2026-05-30
python3 scripts/forward_observation_ledger.py --date 2026-05-30
python3 scripts/calibration_trigger.py --date 2026-05-30
```

### 2.2 跑完后的最小核对

至少确认：

- `outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb`
- `outputs/state_cache/`
- `outputs/strategy_signals/`
- `outputs/daily_snapshot.json`
- `outputs/forward_observation/`

要看的是：

- 文件是否存在
- 文件内的 `date / state_date / signal_date / snapshot_date` 是否真的是当天

---

## 3. 网站数据更新

### 3.1 如果只是更新当天数据

不需要重新部署代码。

流程：

1. 本地跑完数据流水线
2. 生成并上传 `foundation_delta` 增量包
3. 上传 `daily_snapshot.json`
4. 刷页面验收

说明：

- 只更新数据时，不需要重启 `hermass-console`
- 只有部署代码变更时，才需要 `systemctl restart hermass-console`

### 3.2 当前推荐的数据同步思路

按价值分层：

1. `轻量包`
   - 首页 / 市场 / 行业 / 执行观察
2. `研究增强包`
   - 研究页需要的 `fundamental_evidence` / `strategy_signals`
3. `foundation 大包`
   - `/backtest` 和完整底座

长期目标：

- 逐步切到“服务器端直接重建数据”
- 减少人肉传输大包

### 3.3 当前每日上传策略

每日流水线默认上传：

1. `Foundation 增量包`
   - 本地从 `outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb` 切出当天相关行
   - 产物：`outputs/foundation_delta_YYYYMMDD/foundation_delta.duckdb`
   - 上传类型：`foundation_delta`
   - 服务器收到后按主键覆盖合并到现有 Foundation DB
2. `daily_snapshot.json`
   - 产物：`outputs/daily_snapshot.json`
   - 上传类型：`snapshot`

默认不上传完整 `p116_foundation.duckdb`。

原因：

- 完整 Foundation DB 当前约 `3.7G`
- 2026-06-01 的当天增量包约 `8.8M`，gzip 后约 `4.4M`
- `daily_snapshot.json` 约 `1.7M`
- 每日上传量从数 GB 降到约数 MB，同时网站仍保留完整 Foundation DB 查询能力

只有需要全量重铺底座时，才手动打开：

```bash
UPLOAD_FOUNDATION=1 ./scripts/run_daily_pipeline.sh YYYY-MM-DD
```

手动同步当天网站数据时，可执行：

```bash
python scripts/build_foundation_delta.py --date YYYY-MM-DD
python scripts/upload_output_to_server.py --date YYYYMMDD --type foundation_delta
python scripts/upload_output_to_server.py --date YYYYMMDD --type snapshot
```

---

## 4. 网站代码更新

### 4.1 本地修改后

```bash
git status --short
python3 -m py_compile web/main.py
git add <相关文件>
git commit -m "feat: ..."
git push -u origin main
```

### 4.2 服务器更新代码

```bash
cd /opt/hermass
git fetch origin
git checkout main
git reset --hard origin/main
systemctl restart hermass-console
```

---

## 5. 每日网站验收清单

### 5.1 必看页面

- `/`
- `/market`
- `/industry`
- `/watchlist`
- `/research?stock_code=000021.SZ`
- `/backtest`

### 5.2 最少检查内容

首页：

- 不是空白
- 日期正确
- 核心摘要有值

市场页：

- 市场阶段有值
- 当前重点 / 暂时少看 有值

执行页：

- 有优先队列或观察样本
- 资金流 / 板块承接 / 真假突破不为空白

研究页：

- quick / deep / evidence 至少能生成
- `render_profile=value` 可打开

回测页：

- 页面能打开
- 有 foundation 时可以运行

AI 助手：

- 右下角可打开
- `/api/chat/query` 返回正常

---

## 6. 周更 / 低频数据

不是所有数据都必须按日更新。

### 主判断层（日更）

- Foundation DB
- state_cache
- strategy_signals
- forward_observation
- daily_snapshot

### 辅助判断层（周更 / 准日更）

- unified_view
- industry_rotation
- reward_risk

### 背景参考层（低频）

- macro_chain_prior
- macro_snapshot
- industry_chain
- industry_position

原则：

- 低频数据可以滞后
- 但页面必须标 `as_of_date`
- 不得伪装成“今天的结论”

---

## 7. 常见更新策略

### 场景 A：今天只有数据更新

- 跑流水线
- 同步 `outputs`
- 重启服务
- 验收页面

### 场景 B：今天有页面/功能更新

- 本地改代码
- commit / push
- 服务器拉代码
- 若新功能依赖数据，再同步相应数据包

### 场景 C：研究页或回测页空

优先检查：

- `fundamental_evidence.duckdb`
- `strategy_signals.duckdb`
- `p116_foundation.duckdb`

---

## 8. 一句话原则

**每天更新数据，不是每天重新部署网站。**  
**只有代码变了，才做代码发布。**
