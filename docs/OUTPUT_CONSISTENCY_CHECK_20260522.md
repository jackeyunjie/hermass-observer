# 2026-05-22 输出产物数据一致性校验报告

版本：v1.0  
日期：2026-05-23  
校验范围：5 个核心输出文件

---

## 1. 校验项总览

| 校验项 | 状态 | 说明 |
|--------|------|------|
| 提醒总数 vs 总报 total_reminders | 一致 | 145 = 145 |
| 策略分布：提醒 vs 总报 vs 信号账本 | 部分一致 | 提醒/总报/前向观察一致，信号账本含 structure 信号 |
| VCP 收缩后释放命中数 | 一致 | 13 = 13 = 13 |
| 前向观察样本总数 vs 信号账本 | 部分一致 | 145 提醒 vs 1668 总信号 |
| State 值跨文件一致性 | 一致 | 抽查 5 只股票全部一致 |
| 标签跨文件一致性 | 一致 | 抽查 5 只股票全部一致 |

---

## 2. 详细校验结果

### 2.1 校验项 1：提醒总数 vs 总报 total_reminders

| 文件 | 字段 | 值 |
|------|------|-----|
| reminder_20260522.json | total_reminders | 145 |
| daily_research_brief_20260522.json | signal_stats.total_reminders | 145 |
| forward_observation_20260522.json | total | 145 |

**结果：一致**  
三个文件均记录 145 条提醒/观测记录。

---

### 2.2 校验项 2：策略分布一致性

#### 提醒 JSON / 总报 / 前向观察（entry 信号层级）

| 策略 | reminder_20260522 | daily_research_brief | forward_observation |
|------|-------------------|----------------------|---------------------|
| bollinger_bandit | 86 | 86 | 86 |
| ma2560 | 9 | 9 | 9 |
| vcp | 50 | 50 | 50 |
| **合计** | **145** | **145** | **145** |

**结果：一致**  
三个文件的策略分布完全匹配。

#### 信号账本（含 structure 信号）

| 策略 | signal_type | strategy_signal_daily | 备注 |
|------|-------------|----------------------|------|
| bollinger_bandit | entry | 86 | 仅 entry |
| ma2560 | entry | 9 | 另有 structure=730, risk=57 |
| vcp | entry | 50 | 另有 structure=736 |
| **合计 entry** | | **145** | 与提醒一致 |
| **合计全部** | | **1668** | 含 structure/risk |

**结果：部分一致，需说明**  
- 信号账本的 `strategy_counts` 包含所有信号类型（entry + structure + risk），总计 1668
- 提醒 JSON 仅包含 `reminder_eligible=true` 的 entry 信号，总计 145
- 两者的 entry 层级策略分布（86/9/50）完全一致
- **非不一致，是数据粒度差异**

---

### 2.3 校验项 3：VCP 收缩后释放命中数量

| 文件 | 字段 | 值 |
|------|------|-----|
| daily_research_brief_20260522.json | quality_summary.vcp_compression_release_count | 13 |
| forward_observation_20260522.json | sample_progress.key_scene_counts.vcp_path_match | 13 |
| reminder_20260522.json | vcp_environment.path_match=true 计数 | 13 |

**结果：一致**  
三个文件均记录 13 个 VCP 收缩后释放命中。

**补充说明**：当日 50 个 VCP 信号中，37 个未命中路径（path_match=false），13 个命中（path_match=true）。命中率为 26%。

---

### 2.4 校验项 4：前向观察样本总数 vs 信号账本

| 文件 | 字段 | 值 | 说明 |
|------|------|-----|------|
| forward_observation_20260522.json | total | 145 | 仅 reminder_eligible entry 信号 |
| strategy_signal_daily_20260522.json | signal_count | 1668 | 全部信号（entry+structure+risk）|

**结果：部分一致，需说明**  
- 前向观察账本明确声明：`Consumes only strategy reminder rows generated from reminder_eligible signals`
- 信号账本包含 structure 信号（VCP structure=736, MA2560 structure=730）和 risk 信号（MA2560 risk=57）
- 前向观察的 145 = 信号账本中 entry 信号的子集（86+9+50）
- **非不一致，是消费范围差异**

---

### 2.5 校验项 5 & 6：State 值和标签跨文件一致性抽查

#### 抽查股票 1：002806.SZ 华锋股份（ma2560 策略）

| 字段 | reminder | daily_brief | state_cache | forward_obs | 一致性 |
|------|----------|-------------|-------------|-------------|--------|
| mn1_state | E | E | E | E | 一致 |
| w1_state | E | E | E | E | 一致 |
| d1_state | E | E | E | E | 一致 |
| state_score_sum | 42 | 42 | 42 | 42 | 一致 |
| ef_count | 3 | 3 | 3 | 3 | 一致 |
| lifecycle_stage | 新生 | 新生 | - | 新生 | 一致 |
| strategy_environment_fit | 适配 | 适配 | - | 适配 | 一致 |
| signal_strength | 0.85 | 0.85 | - | 0.85 | 一致 |
| signal_name | 2560金叉 | 2560金叉 | - | 2560金叉 | 一致 |

**结果：全部一致**

---

#### 抽查股票 2：000417.SZ 合百集团（ma2560 策略）

| 字段 | reminder | daily_brief | state_cache | forward_obs | 一致性 |
|------|----------|-------------|-------------|-------------|--------|
| mn1_state | F | - | F | F | 一致 |
| w1_state | E | - | E | E | 一致 |
| d1_state | F | - | F | F | 一致 |
| state_score_sum | 44 | - | 44 | 44 | 一致 |
| ef_count | 3 | - | 3 | 3 | 一致 |
| lifecycle_stage | 延展 | - | - | 延展 | 一致 |
| strategy_environment_fit | 弱适配 | - | - | 弱适配 | 一致 |
| signal_strength | 0.85 | - | - | 0.85 | 一致 |

**注意**：该股票未出现在 daily_research_brief 的 `ma2560_market_match` 列表中（因 market_match_level=not_match，可能未被选入展示列表）。

**结果：跨文件一致，总报中未展示属于预期行为**

---

#### 抽查股票 3：300964.SZ 本川智能（vcp 策略，path_match=true）

| 字段 | reminder | daily_brief | state_cache | forward_obs | 一致性 |
|------|----------|-------------|-------------|-------------|--------|
| mn1_state | E | E | E | E | 一致 |
| w1_state | E | E | E | E | 一致 |
| d1_state | E | E | E | E | 一致 |
| state_score_sum | 42 | 42 | 42 | 42 | 一致 |
| ef_count | 3 | 3 | 3 | 3 | 一致 |
| lifecycle_stage | 新生 | 新生 | - | 新生 | 一致 |
| strategy_environment_fit | 最佳适配 | 最佳适配 | - | 最佳适配 | 一致 |
| signal_strength | 0.7 | 0.7 | - | 0.7 | 一致 |
| signal_name | VCP弱放量突破 | VCP弱放量突破 | - | VCP弱放量突破 | 一致 |
| vcp_path_match | true | - | - | true | 一致 |
| d1_days_since_contraction_exit | 10 | 10 | - | - | 一致 |

**结果：全部一致**

---

#### 抽查股票 4：300969.SZ 恒帅股份（vcp 策略，path_match=false）

| 字段 | reminder | daily_brief | state_cache | forward_obs | 一致性 |
|------|----------|-------------|-------------|-------------|--------|
| mn1_state | E | E | E | E | 一致 |
| w1_state | E | E | E | E | 一致 |
| d1_state | E | E | E | E | 一致 |
| state_score_sum | 42 | 42 | 42 | 42 | 一致 |
| ef_count | 3 | 3 | 3 | 3 | 一致 |
| lifecycle_stage | 新生 | 新生 | - | 新生 | 一致 |
| strategy_environment_fit | 最佳适配 | 最佳适配 | - | 最佳适配 | 一致 |
| signal_strength | 0.95 | 0.95 | - | 0.95 | 一致 |
| vcp_path_match | false | - | - | false | 一致 |
| d1_days_since_contraction_exit | 27 | 27 | - | - | 一致 |

**结果：全部一致**

---

#### 抽查股票 5：603667.SH 五洲新春（vcp 策略，path_match=true）

| 字段 | reminder | daily_brief | state_cache | forward_obs | 一致性 |
|------|----------|-------------|-------------|-------------|--------|
| mn1_state | E | E | E | E | 一致 |
| w1_state | E | E | E | E | 一致 |
| d1_state | F | F | F | F | 一致 |
| state_score_sum | 43 | 43 | 43 | 43 | 一致 |
| ef_count | 3 | 3 | 3 | 3 | 一致 |
| lifecycle_stage | 延展 | 延展 | - | 延展 | 一致 |
| strategy_environment_fit | 弱适配 | 弱适配 | - | 弱适配 | 一致 |
| signal_strength | 0.95 | 0.95 | - | 0.95 | 一致 |
| vcp_path_match | true | - | - | true | 一致 |
| d1_days_since_contraction_exit | 13 | 13 | - | - | 一致 |

**结果：全部一致**

---

## 3. 发现的问题

### 3.1 问题 1：总报中部分股票未展示（非数据不一致）

**现象**：000417.SZ 合百集团出现在 reminder 和 forward_observation 中，但未在 daily_research_brief 的 `ma2560_market_match` 列表中找到。

**根因**：daily_research_brief 的 `ma2560_market_match` 列表仅展示 `market_match_level` 为 `full_match`、`stock_only`、`market_unsupported` 的股票。000417.SZ 的 `market_match_level=not_match`，因此被过滤。

**结论**：非数据不一致，是展示过滤逻辑导致的预期行为。

### 3.2 问题 2：信号账本总数与前向观察总数差异（非数据不一致）

**现象**：signal_count=1668，forward_observation total=145。

**根因**：前向观察仅消费 `reminder_eligible=true` 的 entry 信号。信号账本包含大量 structure 信号（VCP structure=736, MA2560 structure=730）和 risk 信号（57）。

**结论**：非数据不一致，是数据消费范围差异。entry 信号（145）在提醒、总报、前向观察中完全一致。

---

## 4. 一致性矩阵

### 4.1 数值一致性矩阵

| 指标 | Reminder | Daily Brief | Signal Daily | Forward Obs | State Cache | 一致性 |
|------|----------|-------------|--------------|-------------|-------------|--------|
| total_reminders/total | 145 | 145 | 145 (entry) | 145 | 223 (EF池) | 一致 |
| bollinger_bandit | 86 | 86 | 86 | 86 | - | 一致 |
| ma2560 (entry) | 9 | 9 | 9 | 9 | - | 一致 |
| vcp (entry) | 50 | 50 | 50 | 50 | - | 一致 |
| vcp_path_match | 13 | 13 | - | 13 | - | 一致 |
| fit: 最佳适配 | 69 | 69 | - | - | - | 一致 |
| fit: 适配 | 4 | 4 | - | - | - | 一致 |
| fit: 弱适配 | 60 | 60 | - | - | - | 一致 |
| fit: 待观察 | 12 | 12 | - | - | - | 一致 |
| lifecycle: 新生 | 21 | 21 | - | 21 | - | 一致 |
| lifecycle: 行进 | 10 | 10 | - | 10 | - | 一致 |
| lifecycle: 延展 | 102 | 102 | - | 102 | - | 一致 |
| lifecycle: 未知 | 12 | 12 | - | 12 | - | 一致 |
| all_three_ef_count | - | 223 | - | - | 223 | 一致 |

### 4.2 抽查股票 State 一致性矩阵

| 股票 | mn1 | w1 | d1 | score_sum | ef_count | path_match | 一致性 |
|------|-----|-----|-----|-----------|----------|------------|--------|
| 002806.SZ | E/E/E/E | E/E/E/E | E/E/E/E | 42/42/42/42 | 3/3/3/3 | - | 一致 |
| 000417.SZ | F/F/F/F | E/E/E/E | F/F/F/F | 44/44/44/44 | 3/3/3/3 | - | 一致 |
| 300964.SZ | E/E/E/E | E/E/E/E | E/E/E/E | 42/42/42/42 | 3/3/3/3 | true/true | 一致 |
| 300969.SZ | E/E/E/E | E/E/E/E | E/E/E/E | 42/42/42/42 | 3/3/3/3 | false/false | 一致 |
| 603667.SH | E/E/E/E | E/E/E/E | F/F/F/F | 43/43/43/43 | 3/3/3/3 | true/true | 一致 |

（列顺序：Reminder / Daily Brief / State Cache / Forward Obs）

---

## 5. 结论

**2026-05-22 的全部输出产物数据一致性良好，未发现实质性数据不一致。**

### 5.1 完全一致的校验项
- 提醒总数（145）跨文件一致
- 策略分布（86/9/50）跨文件一致
- VCP 收缩后释放命中数（13）跨文件一致
- 适配度分布（最佳适配/适配/弱适配/待观察）跨文件一致
- 生命周期分布（新生/行进/延展/未知）跨文件一致
- 抽查的 5 只股票 State 值和标签跨文件完全一致

### 5.2 需要说明的差异
- 信号账本 total（1668）> 前向观察 total（145）：信号账本包含 structure/risk 信号，前向观察仅消费 entry 信号
- 部分股票未在总报特定列表中展示：受 market_match_level 过滤逻辑影响，属预期行为

### 5.3 建议
1. **无需修复**：当前数据流一致性良好，所有"差异"均可通过数据粒度/消费范围解释
2. **可选增强**：在一致性校验脚本中显式标注 `signal_count` 与 `forward_observation_total` 的关系，避免未来误判
3. **可选增强**：在 daily_research_brief 中增加 `filtered_out_count` 字段，说明被过滤的股票数量
