# 数据库性能与完整性审计报告
审计时间：2026-05-24 03:23 UTC

---

## 一、数据库清单

| # | 数据库 | 表数 | 总行数 | 磁盘大小 |
|---|--------|------|--------|----------|
| 1 | blackwolf_moneyflow/blackwolf_moneyflow.duckdb | 3 | 65,618 | 10.01 MB |
| 2 | event_digest/ifind_event_digest.duckdb | 6 | 2 | 2.01 MB |
| 3 | fundamental/fundamental_evidence.duckdb | 14 | 937,961 | 551.76 MB |
| 4 | fundamental/macro_indicator_data.duckdb | 1 | 3,588 | 1.01 MB |
| 5 | industry_chain/chain_dynamics.duckdb | 5 | 953 | 3.76 MB |
| 6 | industry_chain/industry_chain_evidence.duckdb | 5 | 984 | 3.76 MB |
| 7 | macro/macro_indicator_data.duckdb | 3 | 12,131 | 3.26 MB |
| 8 | market_assets/market_assets.duckdb | 2 | 4,868 | 2.01 MB |
| 9 | market_assets_expanded/market_assets.duckdb | 2 | 4,719 | 2.01 MB |
| 10 | market_assets_expanded_v2/market_assets.duckdb | 2 | 4,868 | 2.01 MB |
| 11 | market_assets_raw_20260521/market_assets_raw.duckdb | 2 | 3,249 | 0.76 MB |
| 12 | market_assets_raw_20260522/market_assets_raw.duckdb | 2 | 3,271 | 0.76 MB |
| 13 | market_assets_raw_expanded_v2_20260522/market_assets_raw.duckdb | 2 | 4,740 | 0.76 MB |
| 14 | market_assets_state_20260521/market_assets_state.duckdb | 14 | 32,608 | 5.51 MB |
| 15 | market_assets_state_20260522/market_assets_state.duckdb | 14 | 32,806 | 5.51 MB |
| 16 | market_assets_state_expanded_v2_20260522/market_assets_state.duckdb | 14 | 47,429 | 6.26 MB |
| 17 | p116_ashare_d1_native_state_v2_20260518/p116_ashare_d1_native_state_v2.duckdb | 2 | 50,820,852 | 1644.76 MB |
| 18 | p116_foundation_20260520/p116_foundation.duckdb | 12 | 85,201,963 | 3786.76 MB |
| 19 | p116_foundation_20260521/p116_foundation.duckdb | 12 | 85,251,494 | 3788.51 MB |
| 20 | p116_foundation_20260522/p116_foundation.duckdb | 12 | 85,301,072 | 3793.26 MB |
| 21 | p116_foundation_mt4like_20260520/p116_foundation.duckdb | 12 | 85,201,963 | 3787.01 MB |
| 22 | pattern_lifecycle/pattern_lifecycle.duckdb | 7 | 23,391 | 8.26 MB |
| 23 | state_cache/state_cache.duckdb | 6 | 3,265,300 | 76.51 MB |
| 24 | strategy_fit_observer/fit_log.duckdb | 2 | 3,009 | 3.01 MB |
| 25 | strategy_signals/strategy_signals.duckdb | 2 | 85,727 | 17.51 MB |
| 26 | unified_view/unified_daily_snapshot.duckdb | 1 | 388 | 2.26 MB |

**总计**：26 个数据库，396,314,954 行，17.1 GB

---

## 二、各库明细

### blackwolf_moneyflow/blackwolf_moneyflow.duckdb（10.01 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| moneyflow_daily | 32,806 | 12 | 0.03 |  | — |
| moneyflow_import_log | 6 | 6 | — |  | — |
| moneyflow_raw | 32,806 | 29 | 0.03 |  | — |

### event_digest/ifind_event_digest.duckdb（2.01 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| company_events | 0 | 13 | — |  | — |
| digest_run_log | 1 | 9 | — |  | — |
| event_pool_cross | 0 | 10 | — |  | — |
| news_briefs | 0 | 9 | — |  | — |
| performance_warnings | 0 | 10 | — |  | — |
| schema_info | 1 | 2 | — |  | — |

### fundamental/fundamental_evidence.duckdb（551.76 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| fundamental_evidence_packet | 5,704 | 13 | 0.01 |  | evidence_id |
| fundamental_profile | 5 | 16 | — |  | — |
| fundamental_quality_score | 5,522 | 10 | 0.01 |  | stock_code, as_of_date |
| fundamental_review_queue | 0 | 8 | — |  | — |
| ifind_business_segment_facts | 130,790 | 11 | 0.25 |  | — |
| ifind_capital_events | 0 | 14 | — |  | — |
| ifind_derived_metrics | 7 | 15 | — |  | stock_code, as_of_date |
| ifind_excel_facts | 790,377 | 11 | 1.47 |  | stock_code, as_of_date, metric_name, report_period, source_file |
| ifind_financial_metrics | 7 | 15 | — |  | — |
| ifind_industry_chain_profile | 5,522 | 15 | 0.01 |  | stock_code, as_of_date |
| ifind_macro_indicators | 16 | 9 | — |  | — |
| ifind_tracking_pool | 5 | 14 | — |  | stock_code |
| schema_info | 1 | 2 | — |  | — |
| stock_research_ledger | 5 | 18 | — |  | stock_code, as_of_date |

### fundamental/macro_indicator_data.duckdb（1.01 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| macro_indicators | 3,588 | 8 | — |  | — |

### industry_chain/chain_dynamics.duckdb（3.76 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| chain_dynamics | 920 | 16 | — |  | — |
| chain_event_cross | 0 | 6 | — |  | — |
| chain_run_log | 1 | 8 | — |  | — |
| industry_position | 31 | 21 | — |  | — |
| schema_info | 1 | 2 | — |  | — |

### industry_chain/industry_chain_evidence.duckdb（3.76 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| chain_dynamics | 920 | 16 | — |  | — |
| chain_event_cross | 0 | 6 | — |  | — |
| chain_run_log | 1 | 8 | — |  | — |
| industry_position | 62 | 21 | — |  | — |
| schema_info | 1 | 2 | — |  | — |

### macro/macro_indicator_data.duckdb（3.26 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| macro_indicator_history | 12,123 | 11 | 0.01 |  | — |
| macro_indicator_summary | 7 | 16 | — |  | — |
| macro_prior | 1 | 20 | — |  | — |

### market_assets/market_assets.duckdb（2.01 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| market_asset_daily | 4,708 | 14 | — |  | — |
| market_asset_import_log | 160 | 5 | — |  | — |

### market_assets_expanded/market_assets.duckdb（2.01 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| market_asset_daily | 4,559 | 14 | — |  | — |
| market_asset_import_log | 160 | 5 | — |  | — |

### market_assets_expanded_v2/market_assets.duckdb（2.01 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| market_asset_daily | 4,708 | 14 | — |  | — |
| market_asset_import_log | 160 | 5 | — |  | — |

### market_assets_raw_20260521/market_assets_raw.duckdb（0.76 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| asset_metadata | 22 | 5 | — |  | — |
| blackwolf_ashare_daily_raw | 3,227 | 13 | — |  | — |

### market_assets_raw_20260522/market_assets_raw.duckdb（0.76 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| asset_metadata | 22 | 5 | — |  | — |
| blackwolf_ashare_daily_raw | 3,249 | 13 | — |  | — |

### market_assets_raw_expanded_v2_20260522/market_assets_raw.duckdb（0.76 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| asset_metadata | 32 | 5 | — |  | — |
| blackwolf_ashare_daily_raw | 4,708 | 13 | — |  | — |

### market_assets_state_20260521/market_assets_state.duckdb（5.51 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| asset_metadata | 22 | 5 | — |  | — |
| d1_d_sr | 3,227 | 7 | — |  | stock_code, as_of |
| d1_mn1_sr | 3,227 | 6 | — |  | stock_code, as_of |
| d1_perspective_state | 3,227 | 79 | — |  | stock_code, state_date |
| d1_sr_context | 3,227 | 15 | — |  | stock_code, as_of |
| d1_w_sr | 3,227 | 6 | — |  | stock_code, as_of |
| daily_bars | 3,227 | 8 | — |  | stock_code, trade_date |
| foundation_run_log | 1 | 11 | — |  | — |
| latest_market_asset_state | 22 | 20 | — |  | — |
| monthly_bars | 176 | 11 | — |  | stock_code, month_start |
| sr_levels | 4,107 | 20 | — |  | stock_code, level_date |
| timeframe_bars | 4,107 | 12 | — |  | — |
| timeframe_indicators | 4,107 | 45 | — |  | — |
| weekly_bars | 704 | 11 | — |  | stock_code, week_start |

### market_assets_state_20260522/market_assets_state.duckdb（5.51 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| asset_metadata | 22 | 5 | — |  | — |
| d1_d_sr | 3,249 | 7 | — |  | stock_code, as_of |
| d1_mn1_sr | 3,249 | 6 | — |  | stock_code, as_of |
| d1_perspective_state | 3,249 | 79 | — |  | stock_code, state_date |
| d1_sr_context | 3,249 | 15 | — |  | stock_code, as_of |
| d1_w_sr | 3,249 | 6 | — |  | stock_code, as_of |
| daily_bars | 3,249 | 8 | — |  | stock_code, trade_date |
| foundation_run_log | 1 | 11 | — |  | — |
| latest_market_asset_state | 22 | 20 | — |  | — |
| monthly_bars | 176 | 11 | — |  | stock_code, month_start |
| sr_levels | 4,129 | 20 | — |  | stock_code, level_date |
| timeframe_bars | 4,129 | 12 | — |  | — |
| timeframe_indicators | 4,129 | 45 | — |  | — |
| weekly_bars | 704 | 11 | — |  | stock_code, week_start |

### market_assets_state_expanded_v2_20260522/market_assets_state.duckdb（6.26 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| asset_metadata | 32 | 5 | — |  | — |
| d1_d_sr | 4,708 | 7 | — |  | stock_code, as_of |
| d1_mn1_sr | 4,708 | 6 | — |  | stock_code, as_of |
| d1_perspective_state | 4,708 | 79 | — |  | stock_code, state_date |
| d1_sr_context | 4,708 | 15 | — |  | stock_code, as_of |
| d1_w_sr | 4,708 | 6 | — |  | stock_code, as_of |
| daily_bars | 4,708 | 8 | — |  | stock_code, trade_date |
| foundation_run_log | 1 | 11 | — |  | — |
| latest_market_asset_state | 32 | 20 | — |  | — |
| monthly_bars | 256 | 11 | — |  | stock_code, month_start |
| sr_levels | 5,956 | 20 | 0.01 |  | stock_code, level_date |
| timeframe_bars | 5,956 | 12 | 0.01 |  | — |
| timeframe_indicators | 5,956 | 45 | 0.01 |  | — |
| weekly_bars | 992 | 11 | — |  | stock_code, week_start |

### p116_ashare_d1_native_state_v2_20260518/p116_ashare_d1_native_state_v2.duckdb（1644.76 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| ashare_d1_native_state_v2 | 25,410,426 | 22 | 24.23 |  | — |
| ashare_d1_native_state_v2_final | 25,410,426 | 24 | 24.23 |  | — |

### p116_foundation_20260520/p116_foundation.duckdb（3786.76 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| d1_d_sr | 8,481,138 | 7 | 8.09 |  | stock_code, as_of |
| d1_mn1_sr | 8,481,138 | 6 | 8.09 |  | stock_code, as_of |
| d1_perspective_state | 8,481,138 | 79 | 8.09 |  | stock_code, state_date |
| d1_sr_context | 8,481,138 | 15 | 8.09 |  | stock_code, as_of |
| d1_w_sr | 8,481,138 | 6 | 8.09 |  | stock_code, as_of |
| daily_bars | 8,481,138 | 8 | 8.09 |  | stock_code, trade_date |
| foundation_run_log | 1 | 11 | — |  | — |
| monthly_bars | 425,391 | 11 | 0.41 |  | stock_code, month_start |
| sr_levels | 10,699,068 | 20 | 10.2 |  | stock_code, level_date |
| timeframe_bars | 10,699,068 | 12 | 10.2 |  | — |
| timeframe_indicators | 10,699,068 | 45 | 10.2 |  | — |
| weekly_bars | 1,792,539 | 11 | 1.71 |  | stock_code, week_start |

### p116_foundation_20260521/p116_foundation.duckdb（3788.51 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| d1_d_sr | 8,486,641 | 7 | 8.09 |  | stock_code, as_of |
| d1_mn1_sr | 8,486,641 | 6 | 8.09 |  | stock_code, as_of |
| d1_perspective_state | 8,486,641 | 79 | 8.09 |  | stock_code, state_date |
| d1_sr_context | 8,486,641 | 15 | 8.09 |  | stock_code, as_of |
| d1_w_sr | 8,486,641 | 6 | 8.09 |  | stock_code, as_of |
| daily_bars | 8,486,641 | 8 | 8.09 |  | stock_code, trade_date |
| foundation_run_log | 1 | 11 | — |  | — |
| monthly_bars | 425,391 | 11 | 0.41 |  | stock_code, month_start |
| sr_levels | 10,704,572 | 20 | 10.21 |  | stock_code, level_date |
| timeframe_bars | 10,704,572 | 12 | 10.21 |  | — |
| timeframe_indicators | 10,704,572 | 45 | 10.21 |  | — |
| weekly_bars | 1,792,540 | 11 | 1.71 |  | stock_code, week_start |

### p116_foundation_20260522/p116_foundation.duckdb（3793.26 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| d1_d_sr | 8,492,147 | 7 | 8.1 |  | stock_code, as_of |
| d1_mn1_sr | 8,492,147 | 6 | 8.1 |  | stock_code, as_of |
| d1_perspective_state | 8,492,147 | 79 | 8.1 |  | stock_code, state_date |
| d1_sr_context | 8,492,147 | 15 | 8.1 |  | stock_code, as_of |
| d1_w_sr | 8,492,147 | 6 | 8.1 |  | stock_code, as_of |
| daily_bars | 8,492,147 | 8 | 8.1 |  | stock_code, trade_date |
| foundation_run_log | 1 | 11 | — |  | — |
| monthly_bars | 425,394 | 11 | 0.41 |  | stock_code, month_start |
| sr_levels | 10,710,084 | 20 | 10.21 |  | stock_code, level_date |
| timeframe_bars | 10,710,084 | 12 | 10.21 |  | — |
| timeframe_indicators | 10,710,084 | 45 | 10.21 |  | — |
| weekly_bars | 1,792,543 | 11 | 1.71 |  | stock_code, week_start |

### p116_foundation_mt4like_20260520/p116_foundation.duckdb（3787.01 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| d1_d_sr | 8,481,138 | 7 | 8.09 |  | stock_code, as_of |
| d1_mn1_sr | 8,481,138 | 6 | 8.09 |  | stock_code, as_of |
| d1_perspective_state | 8,481,138 | 79 | 8.09 |  | stock_code, state_date |
| d1_sr_context | 8,481,138 | 15 | 8.09 |  | stock_code, as_of |
| d1_w_sr | 8,481,138 | 6 | 8.09 |  | stock_code, as_of |
| daily_bars | 8,481,138 | 8 | 8.09 |  | stock_code, trade_date |
| foundation_run_log | 1 | 11 | — |  | — |
| monthly_bars | 425,391 | 11 | 0.41 |  | stock_code, month_start |
| sr_levels | 10,699,068 | 20 | 10.2 |  | stock_code, level_date |
| timeframe_bars | 10,699,068 | 12 | 10.2 |  | — |
| timeframe_indicators | 10,699,068 | 45 | 10.2 |  | — |
| weekly_bars | 1,792,539 | 11 | 1.71 |  | stock_code, week_start |

### pattern_lifecycle/pattern_lifecycle.duckdb（8.26 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| ma2560_candidate_pool | 800 | 14 | — |  | — |
| macro_regime_daily | 54 | 8 | — |  | — |
| pattern_events | 3,629 | 8 | — |  | — |
| pattern_lifecycle | 4,349 | 12 | — |  | — |
| pattern_observation_daily | 11,009 | 17 | 0.01 |  | — |
| schema_info | 1 | 2 | — |  | — |
| vcp_candidate_pool | 3,549 | 15 | — |  | — |

### state_cache/state_cache.duckdb（76.51 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| sr_boundary_daily | 1,258,054 | 14 | 1.2 |  | — |
| state_cache_manifest | 236 | 10 | — |  | — |
| state_distribution_daily | 175,316 | 7 | 0.17 |  | — |
| state_duration_daily | 1,217,874 | 20 | 1.17 |  | — |
| state_ef_daily | 45,611 | 12 | 0.04 |  | — |
| state_transition_daily | 568,209 | 9 | 0.54 |  | — |

### strategy_fit_observer/fit_log.duckdb（3.01 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| strategy_fit_log | 3,007 | 17 | 0.01 |  | — |
| strategy_fit_manifest | 2 | 7 | — |  | — |

### strategy_signals/strategy_signals.duckdb（17.51 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| strategy_signal_daily | 85,666 | 24 | 0.09 |  | — |
| strategy_signal_manifest | 61 | 7 | — |  | — |

### unified_view/unified_daily_snapshot.duckdb（2.26 MB）

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |
|------|------|------|-------------|----------|----------|
| unified_daily_snapshot | 388 | 112 | — |  | snapshot_date, stock_code |

---

## 三、主键唯一性检查

| 表 | 主键字段 | 总行数 | 唯一值 | 重复数 | 状态 |
|-----|---------|--------|--------|--------|------|
| fundamental_evidence_packet | evidence_id | 5,704 | 5,704 | 0 | ✅ 唯一 |
| fundamental_quality_score | stock_code, as_of_date | 5,522 | 5,522 | 0 | ✅ 唯一 |
| ifind_derived_metrics | stock_code, as_of_date | 7 | 7 | 0 | ✅ 唯一 |
| ifind_excel_facts | stock_code, as_of_date, metric_name, report_period, source_file | 790,377 | 790,377 | 0 | ✅ 唯一 |
| ifind_industry_chain_profile | stock_code, as_of_date | 5,522 | 5,522 | 0 | ✅ 唯一 |
| ifind_tracking_pool | stock_code | 5 | 5 | 0 | ✅ 唯一 |
| stock_research_ledger | stock_code, as_of_date | 5 | 5 | 0 | ✅ 唯一 |
| d1_perspective_state | stock_code, state_date | 3,227 | 3,227 | 0 | ✅ 唯一 |
| d1_perspective_state | stock_code, state_date | 3,249 | 3,249 | 0 | ✅ 唯一 |
| d1_perspective_state | stock_code, state_date | 4,708 | 4,708 | 0 | ✅ 唯一 |
| d1_perspective_state | stock_code, state_date | 8,481,138 | 8,481,138 | 0 | ✅ 唯一 |
| d1_perspective_state | stock_code, state_date | 8,486,641 | 8,486,641 | 0 | ✅ 唯一 |
| d1_perspective_state | stock_code, state_date | 8,492,147 | 8,492,147 | 0 | ✅ 唯一 |
| d1_perspective_state | stock_code, state_date | 8,481,138 | 8,481,138 | 0 | ✅ 唯一 |
| unified_daily_snapshot | snapshot_date, stock_code | 388 | 388 | 0 | ✅ 唯一 |

### 检查失败
- **d1_d_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "d1_close", "state_date", "stock_code", "d1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_d_sr" GROUP BY "stock_code", "as_of")
                                                                        ^
- **d1_mn1_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "state_date", "stock_code", "mn1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_mn1_sr" GROUP BY "stock_code", "as_of")
                                                                          ^
- **d1_sr_context**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "d1_close", "state_date", "stock_code", "d1_period_start", "w1_period_start"

LINE 1: ...code", "as_of" FROM "d1_sr_context" GROUP BY "stock_code", "as_of")
                                                                      ^
- **d1_w_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "state_date", "stock_code", "w1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_w_sr" GROUP BY "stock_code", "as_of")
                                                                        ^
- **daily_bars**：Binder Error: Referenced column "trade_date" not found in FROM clause!
Candidate bindings: "date", "stock_code", "amount"

LINE 1: ...", "trade_date" FROM "daily_bars" GROUP BY "stock_code", "trade_date")
                                                                    ^
- **monthly_bars**：Binder Error: Referenced column "month_start" not found in FROM clause!
Candidate bindings: "amount", "period_start", "open", "source_bar_count", "close"

LINE 1: ...", "month_start" FROM "monthly_bars" GROUP BY "stock_code", "month_start")
                                                                       ^
- **sr_levels**：Binder Error: Referenced column "level_date" not found in FROM clause!
Candidate bindings: "available_date", "source_bar_count", "timeframe", "close", "fractal_resistance"

LINE 1: ...", "level_date" FROM "sr_levels" GROUP BY "stock_code", "level_date")
                                                                   ^
- **weekly_bars**：Binder Error: Referenced column "week_start" not found in FROM clause!
Candidate bindings: "period_start", "source_bar_count"

LINE 1: ...", "week_start" FROM "weekly_bars" GROUP BY "stock_code", "week_start")
                                                                     ^
- **d1_d_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "d1_close", "state_date", "stock_code", "d1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_d_sr" GROUP BY "stock_code", "as_of")
                                                                        ^
- **d1_mn1_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "state_date", "stock_code", "mn1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_mn1_sr" GROUP BY "stock_code", "as_of")
                                                                          ^
- **d1_sr_context**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "d1_close", "state_date", "stock_code", "d1_period_start", "w1_period_start"

LINE 1: ...code", "as_of" FROM "d1_sr_context" GROUP BY "stock_code", "as_of")
                                                                      ^
- **d1_w_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "state_date", "stock_code", "w1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_w_sr" GROUP BY "stock_code", "as_of")
                                                                        ^
- **daily_bars**：Binder Error: Referenced column "trade_date" not found in FROM clause!
Candidate bindings: "date", "stock_code", "amount"

LINE 1: ...", "trade_date" FROM "daily_bars" GROUP BY "stock_code", "trade_date")
                                                                    ^
- **monthly_bars**：Binder Error: Referenced column "month_start" not found in FROM clause!
Candidate bindings: "amount", "period_start", "open", "source_bar_count", "close"

LINE 1: ...", "month_start" FROM "monthly_bars" GROUP BY "stock_code", "month_start")
                                                                       ^
- **sr_levels**：Binder Error: Referenced column "level_date" not found in FROM clause!
Candidate bindings: "available_date", "source_bar_count", "timeframe", "close", "fractal_resistance"

LINE 1: ...", "level_date" FROM "sr_levels" GROUP BY "stock_code", "level_date")
                                                                   ^
- **weekly_bars**：Binder Error: Referenced column "week_start" not found in FROM clause!
Candidate bindings: "period_start", "source_bar_count"

LINE 1: ...", "week_start" FROM "weekly_bars" GROUP BY "stock_code", "week_start")
                                                                     ^
- **d1_d_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "d1_close", "state_date", "stock_code", "d1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_d_sr" GROUP BY "stock_code", "as_of")
                                                                        ^
- **d1_mn1_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "state_date", "stock_code", "mn1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_mn1_sr" GROUP BY "stock_code", "as_of")
                                                                          ^
- **d1_sr_context**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "d1_close", "state_date", "stock_code", "d1_period_start", "w1_period_start"

LINE 1: ...code", "as_of" FROM "d1_sr_context" GROUP BY "stock_code", "as_of")
                                                                      ^
- **d1_w_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "state_date", "stock_code", "w1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_w_sr" GROUP BY "stock_code", "as_of")
                                                                        ^
- **daily_bars**：Binder Error: Referenced column "trade_date" not found in FROM clause!
Candidate bindings: "date", "stock_code", "amount"

LINE 1: ...", "trade_date" FROM "daily_bars" GROUP BY "stock_code", "trade_date")
                                                                    ^
- **monthly_bars**：Binder Error: Referenced column "month_start" not found in FROM clause!
Candidate bindings: "amount", "period_start", "open", "source_bar_count", "close"

LINE 1: ...", "month_start" FROM "monthly_bars" GROUP BY "stock_code", "month_start")
                                                                       ^
- **sr_levels**：Binder Error: Referenced column "level_date" not found in FROM clause!
Candidate bindings: "available_date", "source_bar_count", "timeframe", "close", "fractal_resistance"

LINE 1: ...", "level_date" FROM "sr_levels" GROUP BY "stock_code", "level_date")
                                                                   ^
- **weekly_bars**：Binder Error: Referenced column "week_start" not found in FROM clause!
Candidate bindings: "period_start", "source_bar_count"

LINE 1: ...", "week_start" FROM "weekly_bars" GROUP BY "stock_code", "week_start")
                                                                     ^
- **d1_d_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "d1_close", "state_date", "stock_code", "d1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_d_sr" GROUP BY "stock_code", "as_of")
                                                                        ^
- **d1_mn1_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "state_date", "stock_code", "mn1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_mn1_sr" GROUP BY "stock_code", "as_of")
                                                                          ^
- **d1_sr_context**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "d1_close", "state_date", "stock_code", "d1_period_start", "w1_period_start"

LINE 1: ...code", "as_of" FROM "d1_sr_context" GROUP BY "stock_code", "as_of")
                                                                      ^
- **d1_w_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "state_date", "stock_code", "w1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_w_sr" GROUP BY "stock_code", "as_of")
                                                                        ^
- **daily_bars**：Binder Error: Referenced column "trade_date" not found in FROM clause!
Candidate bindings: "date", "stock_code", "amount"

LINE 1: ...", "trade_date" FROM "daily_bars" GROUP BY "stock_code", "trade_date")
                                                                    ^
- **monthly_bars**：Binder Error: Referenced column "month_start" not found in FROM clause!
Candidate bindings: "amount", "period_start", "open", "source_bar_count", "close"

LINE 1: ...", "month_start" FROM "monthly_bars" GROUP BY "stock_code", "month_start")
                                                                       ^
- **sr_levels**：Binder Error: Referenced column "level_date" not found in FROM clause!
Candidate bindings: "available_date", "source_bar_count", "timeframe", "close", "fractal_resistance"

LINE 1: ...", "level_date" FROM "sr_levels" GROUP BY "stock_code", "level_date")
                                                                   ^
- **weekly_bars**：Binder Error: Referenced column "week_start" not found in FROM clause!
Candidate bindings: "period_start", "source_bar_count"

LINE 1: ...", "week_start" FROM "weekly_bars" GROUP BY "stock_code", "week_start")
                                                                     ^
- **d1_d_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "d1_close", "state_date", "stock_code", "d1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_d_sr" GROUP BY "stock_code", "as_of")
                                                                        ^
- **d1_mn1_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "state_date", "stock_code", "mn1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_mn1_sr" GROUP BY "stock_code", "as_of")
                                                                          ^
- **d1_sr_context**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "d1_close", "state_date", "stock_code", "d1_period_start", "w1_period_start"

LINE 1: ...code", "as_of" FROM "d1_sr_context" GROUP BY "stock_code", "as_of")
                                                                      ^
- **d1_w_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "state_date", "stock_code", "w1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_w_sr" GROUP BY "stock_code", "as_of")
                                                                        ^
- **daily_bars**：Binder Error: Referenced column "trade_date" not found in FROM clause!
Candidate bindings: "date", "stock_code", "amount"

LINE 1: ...", "trade_date" FROM "daily_bars" GROUP BY "stock_code", "trade_date")
                                                                    ^
- **monthly_bars**：Binder Error: Referenced column "month_start" not found in FROM clause!
Candidate bindings: "amount", "period_start", "open", "source_bar_count", "close"

LINE 1: ...", "month_start" FROM "monthly_bars" GROUP BY "stock_code", "month_start")
                                                                       ^
- **sr_levels**：Binder Error: Referenced column "level_date" not found in FROM clause!
Candidate bindings: "available_date", "source_bar_count", "timeframe", "close", "fractal_resistance"

LINE 1: ...", "level_date" FROM "sr_levels" GROUP BY "stock_code", "level_date")
                                                                   ^
- **weekly_bars**：Binder Error: Referenced column "week_start" not found in FROM clause!
Candidate bindings: "period_start", "source_bar_count"

LINE 1: ...", "week_start" FROM "weekly_bars" GROUP BY "stock_code", "week_start")
                                                                     ^
- **d1_d_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "d1_close", "state_date", "stock_code", "d1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_d_sr" GROUP BY "stock_code", "as_of")
                                                                        ^
- **d1_mn1_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "state_date", "stock_code", "mn1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_mn1_sr" GROUP BY "stock_code", "as_of")
                                                                          ^
- **d1_sr_context**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "d1_close", "state_date", "stock_code", "d1_period_start", "w1_period_start"

LINE 1: ...code", "as_of" FROM "d1_sr_context" GROUP BY "stock_code", "as_of")
                                                                      ^
- **d1_w_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "state_date", "stock_code", "w1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_w_sr" GROUP BY "stock_code", "as_of")
                                                                        ^
- **daily_bars**：Binder Error: Referenced column "trade_date" not found in FROM clause!
Candidate bindings: "date", "stock_code", "amount"

LINE 1: ...", "trade_date" FROM "daily_bars" GROUP BY "stock_code", "trade_date")
                                                                    ^
- **monthly_bars**：Binder Error: Referenced column "month_start" not found in FROM clause!
Candidate bindings: "amount", "period_start", "open", "source_bar_count", "close"

LINE 1: ...", "month_start" FROM "monthly_bars" GROUP BY "stock_code", "month_start")
                                                                       ^
- **sr_levels**：Binder Error: Referenced column "level_date" not found in FROM clause!
Candidate bindings: "available_date", "source_bar_count", "timeframe", "close", "fractal_resistance"

LINE 1: ...", "level_date" FROM "sr_levels" GROUP BY "stock_code", "level_date")
                                                                   ^
- **weekly_bars**：Binder Error: Referenced column "week_start" not found in FROM clause!
Candidate bindings: "period_start", "source_bar_count"

LINE 1: ...", "week_start" FROM "weekly_bars" GROUP BY "stock_code", "week_start")
                                                                     ^
- **d1_d_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "d1_close", "state_date", "stock_code", "d1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_d_sr" GROUP BY "stock_code", "as_of")
                                                                        ^
- **d1_mn1_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "state_date", "stock_code", "mn1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_mn1_sr" GROUP BY "stock_code", "as_of")
                                                                          ^
- **d1_sr_context**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "d1_close", "state_date", "stock_code", "d1_period_start", "w1_period_start"

LINE 1: ...code", "as_of" FROM "d1_sr_context" GROUP BY "stock_code", "as_of")
                                                                      ^
- **d1_w_sr**：Binder Error: Referenced column "as_of" not found in FROM clause!
Candidate bindings: "state_date", "stock_code", "w1_period_start"

LINE 1: ... "stock_code", "as_of" FROM "d1_w_sr" GROUP BY "stock_code", "as_of")
                                                                        ^
- **daily_bars**：Binder Error: Referenced column "trade_date" not found in FROM clause!
Candidate bindings: "date", "stock_code", "amount"

LINE 1: ...", "trade_date" FROM "daily_bars" GROUP BY "stock_code", "trade_date")
                                                                    ^
- **monthly_bars**：Binder Error: Referenced column "month_start" not found in FROM clause!
Candidate bindings: "amount", "period_start", "open", "source_bar_count", "close"

LINE 1: ...", "month_start" FROM "monthly_bars" GROUP BY "stock_code", "month_start")
                                                                       ^
- **sr_levels**：Binder Error: Referenced column "level_date" not found in FROM clause!
Candidate bindings: "available_date", "source_bar_count", "timeframe", "close", "fractal_resistance"

LINE 1: ...", "level_date" FROM "sr_levels" GROUP BY "stock_code", "level_date")
                                                                   ^
- **weekly_bars**：Binder Error: Referenced column "week_start" not found in FROM clause!
Candidate bindings: "period_start", "source_bar_count"

LINE 1: ...", "week_start" FROM "weekly_bars" GROUP BY "stock_code", "week_start")
                                                                     ^

---

## 四、跨库关联完整性

以统一底座（unified_daily_snapshot）最新快照为基准，对比各源数据表的 stock_code 交集。

| 源库 | 统一底座标的数 | 源库标的数 | 交集 | 仅底座 | 仅源库 | 覆盖率 |
|------|-------------|-----------|------|--------|--------|--------|
| p116_foundation_latest | 223 | 5,500 | 223 | 0 | 5,277 | 100.0% |
| fundamental_evidence | 223 | 5,522 | 223 | 0 | 5,299 | 100.0% |
| strategy_signals | — | — | — | — | — | ❌ Catalog Error: Table with name strategy_signal_ledger does not exist!
Did you mean "strategy_signal_daily"?

LINE 1: SELECT DISTINCT stock_code FROM _src_strategy_signals.strategy_signal_ledger
                                        ^ |

---

## 五、存储效率

### blackwolf_moneyflow/blackwolf_moneyflow.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| moneyflow_daily | 32,806 | 12 | 0.03 | 1.0 | ✅ 行列比合理 |
| moneyflow_import_log | 6 | 6 | 0.0 | 1.0 | ✅ 行列比合理 |
| moneyflow_raw | 32,806 | 29 | 0.03 | 1.0 | ✅ 行列比合理 |

### event_digest/ifind_event_digest.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| company_events | 0 | 13 | 0.0 | 0 | — |
| digest_run_log | 1 | 9 | 0.0 | 1.0 | ✅ 行列比合理 |
| event_pool_cross | 0 | 10 | 0.0 | 0 | — |
| news_briefs | 0 | 9 | 0.0 | 0 | — |
| performance_warnings | 0 | 10 | 0.0 | 0 | — |
| schema_info | 1 | 2 | 0.0 | 1.0 | ✅ 行列比合理 |

### fundamental/fundamental_evidence.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| fundamental_evidence_packet | 5,704 | 13 | 0.01 | 1.0 | ✅ 行列比合理 |
| fundamental_profile | 5 | 16 | 0.0 | 1.0 | ✅ 行列比合理 |
| fundamental_quality_score | 5,522 | 10 | 0.01 | 1.0 | ✅ 行列比合理 |
| fundamental_review_queue | 0 | 8 | 0.0 | 0 | — |
| ifind_business_segment_facts | 130,790 | 11 | 0.25 | 2.0 | ✅ 行列比合理 |
| ifind_capital_events | 0 | 14 | 0.0 | 0 | — |
| ifind_derived_metrics | 7 | 15 | 0.0 | 2.1 | ✅ 行列比合理 |
| ifind_excel_facts | 790,377 | 11 | 1.47 | 2.0 | ✅ 行列比合理 |
| ifind_financial_metrics | 7 | 15 | 0.0 | 2.1 | ✅ 行列比合理 |
| ifind_industry_chain_profile | 5,522 | 15 | 0.01 | 1.0 | ✅ 行列比合理 |
| ifind_macro_indicators | 16 | 9 | 0.0 | 1.0 | ✅ 行列比合理 |
| ifind_tracking_pool | 5 | 14 | 0.0 | 1.0 | ✅ 行列比合理 |
| schema_info | 1 | 2 | 0.0 | 1.0 | ✅ 行列比合理 |
| stock_research_ledger | 5 | 18 | 0.0 | 1.0 | ✅ 行列比合理 |

### fundamental/macro_indicator_data.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| macro_indicators | 3,588 | 8 | 0.0 | 1.0 | ✅ 行列比合理 |

### industry_chain/chain_dynamics.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| chain_dynamics | 920 | 16 | 0.0 | 1.0 | ✅ 行列比合理 |
| chain_event_cross | 0 | 6 | 0.0 | 0 | — |
| chain_run_log | 1 | 8 | 0.0 | 1.0 | ✅ 行列比合理 |
| industry_position | 31 | 21 | 0.0 | 3.0 | ✅ 行列比合理 |
| schema_info | 1 | 2 | 0.0 | 1.0 | ✅ 行列比合理 |

### industry_chain/industry_chain_evidence.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| chain_dynamics | 920 | 16 | 0.0 | 1.0 | ✅ 行列比合理 |
| chain_event_cross | 0 | 6 | 0.0 | 0 | — |
| chain_run_log | 1 | 8 | 0.0 | 1.0 | ✅ 行列比合理 |
| industry_position | 62 | 21 | 0.0 | 1.0 | ✅ 行列比合理 |
| schema_info | 1 | 2 | 0.0 | 1.0 | ✅ 行列比合理 |

### macro/macro_indicator_data.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| macro_indicator_history | 12,123 | 11 | 0.01 | 1.0 | ✅ 行列比合理 |
| macro_indicator_summary | 7 | 16 | 0.0 | 9.1 | ✅ 行列比合理 |
| macro_prior | 1 | 20 | 0.0 | 1.0 | ✅ 行列比合理 |

### market_assets/market_assets.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| market_asset_daily | 4,708 | 14 | 0.0 | 1.0 | ✅ 行列比合理 |
| market_asset_import_log | 160 | 5 | 0.0 | 1.0 | ✅ 行列比合理 |

### market_assets_expanded/market_assets.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| market_asset_daily | 4,559 | 14 | 0.0 | 1.0 | ✅ 行列比合理 |
| market_asset_import_log | 160 | 5 | 0.0 | 1.0 | ✅ 行列比合理 |

### market_assets_expanded_v2/market_assets.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| market_asset_daily | 4,708 | 14 | 0.0 | 1.0 | ✅ 行列比合理 |
| market_asset_import_log | 160 | 5 | 0.0 | 1.0 | ✅ 行列比合理 |

### market_assets_raw_20260521/market_assets_raw.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| asset_metadata | 22 | 5 | 0.0 | 1.0 | ✅ 行列比合理 |
| blackwolf_ashare_daily_raw | 3,227 | 13 | 0.0 | 1.0 | ✅ 行列比合理 |

### market_assets_raw_20260522/market_assets_raw.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| asset_metadata | 22 | 5 | 0.0 | 1.0 | ✅ 行列比合理 |
| blackwolf_ashare_daily_raw | 3,249 | 13 | 0.0 | 1.0 | ✅ 行列比合理 |

### market_assets_raw_expanded_v2_20260522/market_assets_raw.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| asset_metadata | 32 | 5 | 0.0 | 1.0 | ✅ 行列比合理 |
| blackwolf_ashare_daily_raw | 4,708 | 13 | 0.0 | 1.0 | ✅ 行列比合理 |

### market_assets_state_20260521/market_assets_state.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| asset_metadata | 22 | 5 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_d_sr | 3,227 | 7 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_mn1_sr | 3,227 | 6 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_perspective_state | 3,227 | 79 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_sr_context | 3,227 | 15 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_w_sr | 3,227 | 6 | 0.0 | 1.0 | ✅ 行列比合理 |
| daily_bars | 3,227 | 8 | 0.0 | 1.0 | ✅ 行列比合理 |
| foundation_run_log | 1 | 11 | 0.0 | 1.0 | ✅ 行列比合理 |
| latest_market_asset_state | 22 | 20 | 0.0 | 1.0 | ✅ 行列比合理 |
| monthly_bars | 176 | 11 | 0.0 | 1.0 | ✅ 行列比合理 |
| sr_levels | 4,107 | 20 | 0.0 | 1.0 | ✅ 行列比合理 |
| timeframe_bars | 4,107 | 12 | 0.0 | 1.0 | ✅ 行列比合理 |
| timeframe_indicators | 4,107 | 45 | 0.0 | 1.0 | ✅ 行列比合理 |
| weekly_bars | 704 | 11 | 0.0 | 1.0 | ✅ 行列比合理 |

### market_assets_state_20260522/market_assets_state.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| asset_metadata | 22 | 5 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_d_sr | 3,249 | 7 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_mn1_sr | 3,249 | 6 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_perspective_state | 3,249 | 79 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_sr_context | 3,249 | 15 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_w_sr | 3,249 | 6 | 0.0 | 1.0 | ✅ 行列比合理 |
| daily_bars | 3,249 | 8 | 0.0 | 1.0 | ✅ 行列比合理 |
| foundation_run_log | 1 | 11 | 0.0 | 1.0 | ✅ 行列比合理 |
| latest_market_asset_state | 22 | 20 | 0.0 | 1.0 | ✅ 行列比合理 |
| monthly_bars | 176 | 11 | 0.0 | 1.0 | ✅ 行列比合理 |
| sr_levels | 4,129 | 20 | 0.0 | 1.0 | ✅ 行列比合理 |
| timeframe_bars | 4,129 | 12 | 0.0 | 1.0 | ✅ 行列比合理 |
| timeframe_indicators | 4,129 | 45 | 0.0 | 1.0 | ✅ 行列比合理 |
| weekly_bars | 704 | 11 | 0.0 | 1.0 | ✅ 行列比合理 |

### market_assets_state_expanded_v2_20260522/market_assets_state.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| asset_metadata | 32 | 5 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_d_sr | 4,708 | 7 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_mn1_sr | 4,708 | 6 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_perspective_state | 4,708 | 79 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_sr_context | 4,708 | 15 | 0.0 | 1.0 | ✅ 行列比合理 |
| d1_w_sr | 4,708 | 6 | 0.0 | 1.0 | ✅ 行列比合理 |
| daily_bars | 4,708 | 8 | 0.0 | 1.0 | ✅ 行列比合理 |
| foundation_run_log | 1 | 11 | 0.0 | 1.0 | ✅ 行列比合理 |
| latest_market_asset_state | 32 | 20 | 0.0 | 1.0 | ✅ 行列比合理 |
| monthly_bars | 256 | 11 | 0.0 | 1.0 | ✅ 行列比合理 |
| sr_levels | 5,956 | 20 | 0.01 | 1.0 | ✅ 行列比合理 |
| timeframe_bars | 5,956 | 12 | 0.01 | 1.0 | ✅ 行列比合理 |
| timeframe_indicators | 5,956 | 45 | 0.01 | 1.0 | ✅ 行列比合理 |
| weekly_bars | 992 | 11 | 0.0 | 1.0 | ✅ 行列比合理 |

### p116_ashare_d1_native_state_v2_20260518/p116_ashare_d1_native_state_v2.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| ashare_d1_native_state_v2 | 25,410,426 | 22 | 24.23 | 1.0 | ✅ 行列比合理 |
| ashare_d1_native_state_v2_final | 25,410,426 | 24 | 24.23 | 1.0 | ✅ 行列比合理 |

### p116_foundation_20260520/p116_foundation.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| d1_d_sr | 8,481,138 | 7 | 8.09 | 1.0 | ✅ 行列比合理 |
| d1_mn1_sr | 8,481,138 | 6 | 8.09 | 1.0 | ✅ 行列比合理 |
| d1_perspective_state | 8,481,138 | 79 | 8.09 | 1.0 | ✅ 行列比合理 |
| d1_sr_context | 8,481,138 | 15 | 8.09 | 1.0 | ✅ 行列比合理 |
| d1_w_sr | 8,481,138 | 6 | 8.09 | 1.0 | ✅ 行列比合理 |
| daily_bars | 8,481,138 | 8 | 8.09 | 1.0 | ✅ 行列比合理 |
| foundation_run_log | 1 | 11 | 0.0 | 1.0 | ✅ 行列比合理 |
| monthly_bars | 425,391 | 11 | 0.41 | 1.0 | ✅ 行列比合理 |
| sr_levels | 10,699,068 | 20 | 10.2 | 1.0 | ✅ 行列比合理 |
| timeframe_bars | 10,699,068 | 12 | 10.2 | 1.0 | ✅ 行列比合理 |
| timeframe_indicators | 10,699,068 | 45 | 10.2 | 1.0 | ✅ 行列比合理 |
| weekly_bars | 1,792,539 | 11 | 1.71 | 1.0 | ✅ 行列比合理 |

### p116_foundation_20260521/p116_foundation.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| d1_d_sr | 8,486,641 | 7 | 8.09 | 1.0 | ✅ 行列比合理 |
| d1_mn1_sr | 8,486,641 | 6 | 8.09 | 1.0 | ✅ 行列比合理 |
| d1_perspective_state | 8,486,641 | 79 | 8.09 | 1.0 | ✅ 行列比合理 |
| d1_sr_context | 8,486,641 | 15 | 8.09 | 1.0 | ✅ 行列比合理 |
| d1_w_sr | 8,486,641 | 6 | 8.09 | 1.0 | ✅ 行列比合理 |
| daily_bars | 8,486,641 | 8 | 8.09 | 1.0 | ✅ 行列比合理 |
| foundation_run_log | 1 | 11 | 0.0 | 1.0 | ✅ 行列比合理 |
| monthly_bars | 425,391 | 11 | 0.41 | 1.0 | ✅ 行列比合理 |
| sr_levels | 10,704,572 | 20 | 10.21 | 1.0 | ✅ 行列比合理 |
| timeframe_bars | 10,704,572 | 12 | 10.21 | 1.0 | ✅ 行列比合理 |
| timeframe_indicators | 10,704,572 | 45 | 10.21 | 1.0 | ✅ 行列比合理 |
| weekly_bars | 1,792,540 | 11 | 1.71 | 1.0 | ✅ 行列比合理 |

### p116_foundation_20260522/p116_foundation.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| d1_d_sr | 8,492,147 | 7 | 8.1 | 1.0 | ✅ 行列比合理 |
| d1_mn1_sr | 8,492,147 | 6 | 8.1 | 1.0 | ✅ 行列比合理 |
| d1_perspective_state | 8,492,147 | 79 | 8.1 | 1.0 | ✅ 行列比合理 |
| d1_sr_context | 8,492,147 | 15 | 8.1 | 1.0 | ✅ 行列比合理 |
| d1_w_sr | 8,492,147 | 6 | 8.1 | 1.0 | ✅ 行列比合理 |
| daily_bars | 8,492,147 | 8 | 8.1 | 1.0 | ✅ 行列比合理 |
| foundation_run_log | 1 | 11 | 0.0 | 1.0 | ✅ 行列比合理 |
| monthly_bars | 425,394 | 11 | 0.41 | 1.0 | ✅ 行列比合理 |
| sr_levels | 10,710,084 | 20 | 10.21 | 1.0 | ✅ 行列比合理 |
| timeframe_bars | 10,710,084 | 12 | 10.21 | 1.0 | ✅ 行列比合理 |
| timeframe_indicators | 10,710,084 | 45 | 10.21 | 1.0 | ✅ 行列比合理 |
| weekly_bars | 1,792,543 | 11 | 1.71 | 1.0 | ✅ 行列比合理 |

### p116_foundation_mt4like_20260520/p116_foundation.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| d1_d_sr | 8,481,138 | 7 | 8.09 | 1.0 | ✅ 行列比合理 |
| d1_mn1_sr | 8,481,138 | 6 | 8.09 | 1.0 | ✅ 行列比合理 |
| d1_perspective_state | 8,481,138 | 79 | 8.09 | 1.0 | ✅ 行列比合理 |
| d1_sr_context | 8,481,138 | 15 | 8.09 | 1.0 | ✅ 行列比合理 |
| d1_w_sr | 8,481,138 | 6 | 8.09 | 1.0 | ✅ 行列比合理 |
| daily_bars | 8,481,138 | 8 | 8.09 | 1.0 | ✅ 行列比合理 |
| foundation_run_log | 1 | 11 | 0.0 | 1.0 | ✅ 行列比合理 |
| monthly_bars | 425,391 | 11 | 0.41 | 1.0 | ✅ 行列比合理 |
| sr_levels | 10,699,068 | 20 | 10.2 | 1.0 | ✅ 行列比合理 |
| timeframe_bars | 10,699,068 | 12 | 10.2 | 1.0 | ✅ 行列比合理 |
| timeframe_indicators | 10,699,068 | 45 | 10.2 | 1.0 | ✅ 行列比合理 |
| weekly_bars | 1,792,539 | 11 | 1.71 | 1.0 | ✅ 行列比合理 |

### pattern_lifecycle/pattern_lifecycle.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| ma2560_candidate_pool | 800 | 14 | 0.0 | 1.0 | ✅ 行列比合理 |
| macro_regime_daily | 54 | 8 | 0.0 | 1.0 | ✅ 行列比合理 |
| pattern_events | 3,629 | 8 | 0.0 | 1.0 | ✅ 行列比合理 |
| pattern_lifecycle | 4,349 | 12 | 0.0 | 1.0 | ✅ 行列比合理 |
| pattern_observation_daily | 11,009 | 17 | 0.01 | 1.0 | ✅ 行列比合理 |
| schema_info | 1 | 2 | 0.0 | 1.0 | ✅ 行列比合理 |
| vcp_candidate_pool | 3,549 | 15 | 0.0 | 1.0 | ✅ 行列比合理 |

### state_cache/state_cache.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| sr_boundary_daily | 1,258,054 | 14 | 1.2 | 1.0 | ✅ 行列比合理 |
| state_cache_manifest | 236 | 10 | 0.0 | 1.3 | ✅ 行列比合理 |
| state_distribution_daily | 175,316 | 7 | 0.17 | 1.0 | ✅ 行列比合理 |
| state_duration_daily | 1,217,874 | 20 | 1.17 | 1.0 | ✅ 行列比合理 |
| state_ef_daily | 45,611 | 12 | 0.04 | 1.0 | ✅ 行列比合理 |
| state_transition_daily | 568,209 | 9 | 0.54 | 1.0 | ✅ 行列比合理 |

### strategy_fit_observer/fit_log.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| strategy_fit_log | 3,007 | 17 | 0.01 | 4.9 | ✅ 行列比合理 |
| strategy_fit_manifest | 2 | 7 | 0.0 | 4.5 | ✅ 行列比合理 |

### strategy_signals/strategy_signals.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| strategy_signal_daily | 85,666 | 24 | 0.09 | 1.1 | ✅ 行列比合理 |
| strategy_signal_manifest | 61 | 7 | 0.0 | 1.1 | ✅ 行列比合理 |

### unified_view/unified_daily_snapshot.duckdb

| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |
|------|------|------|-------------|----------|------|
| unified_daily_snapshot | 388 | 112 | 0.0 | 2.0 | ✅ 行列比合理 |

---

## 六、性能基线

| 数据库 | 表 | 查询 | 耗时(ms) | 结果行数 |
|--------|-----|------|----------|----------|
| small | unified_daily_snapshot | 全表扫描 COUNT | 0.5 | 1 |
| small | unified_daily_snapshot | 日期筛选（最近一天） | 0.7 | 1 |
| small | unified_daily_snapshot | 聚合 GROUP BY | 0.5 | 2 |
| small × medium (JOIN) | unified + fundamental_quality_score | 跨库 JOIN（基本面评分 × 统一底座） | 2.0 | 223 |
| medium | fundamental_quality_score | 全表扫描 COUNT | 0.1 | 1 |
| medium | fundamental_quality_score | 日期筛选（最近一天） | 0.6 | 1 |
| medium | fundamental_quality_score | 聚合 GROUP BY | 0.6 | 10 |
| large | d1_perspective_state | 全表扫描 COUNT | 0.8 | 1 |
| large | d1_perspective_state | 日期筛选（最近一天） | 3.5 | 1 |
| large | d1_perspective_state | 聚合 GROUP BY | 8.4 | 10 |

---

## 七、建议与后续行动

- **大库优化**：fundamental/fundamental_evidence.duckdb, p116_ashare_d1_native_state_v2_20260518/p116_ashare_d1_native_state_v2.duckdb, p116_foundation_20260520/p116_foundation.duckdb, p116_foundation_20260521/p116_foundation.duckdb, p116_foundation_20260522/p116_foundation.duckdb, p116_foundation_mt4like_20260520/p116_foundation.duckdb 均超过 500MB，建议启用索引：`CREATE INDEX idx_stock_date ON d1_perspective_state(stock_code, state_date);`
- **历史版本清理**：`fundamental` 存在 2 个日期版本（551.76MB, 1.01MB），合计 553MB。建议仅保留最新 2 个版本，旧版归档或删除。

---

*报告由 `scripts/db_audit.py` 自动生成，审计时间 2026-05-24 03:23 UTC*