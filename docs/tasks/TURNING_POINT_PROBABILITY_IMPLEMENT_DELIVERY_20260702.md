# 转折概率 MVP 实现交付文档

- 日期：2026-07-02
- 执行者：KIMI1
- 任务：`docs/tasks/KIMI1_TASK_TURNING_POINT_PROBABILITY_IMPLEMENT_20260702.md`

---

## 1. 改了哪些文件

| 文件 | 说明 |
|---|---|
| `scripts/build_turning_point_probability.py` | 新增转折概率 MVP 构建脚本 |
| `tests/unit/test_turning_point_probability.py` | 新增单元测试 |
| `outputs/turning_point_probability/turning_point_probability_20260702.duckdb` | 生成的产物 |
| `outputs/turning_point_probability/turning_point_probability_latest.json` | 生成的产物 |
| `docs/tasks/TURNING_POINT_PROBABILITY_IMPLEMENT_DELIVERY_20260702.md` | 本文档 |

---

## 2. 生成的产物

```text
outputs/turning_point_probability/turning_point_probability_20260702.duckdb
outputs/turning_point_probability/turning_point_probability_latest.json
```

### 2.1 产物统计

- 目标日期：`2026-07-02`
- 数据源：State Cube 缺失该日期，已降级使用 Foundation DB（`outputs/p116_foundation_20260702/p116_foundation.duckdb`）
- 覆盖标的：5,519 只
- 总记录数：22,076 行（5,519 × 4 个时间窗）
- 时间窗分布：3D / 3W / 3M / 6M 各 5,519 行
- 主要 turning_type：`uncertain`（置信度阈值 0.3 以下）
- 市场环境：`oversold_bounce`
- 概率和最大偏差：≤ 0.0001
- 低样本 confidence 超限检查：0 条违规

### 2.2 DuckDB 表结构

表名：`turning_point_probability`

包含任务要求的全部字段：

```text
stock_code, stock_name, state_date, window, turning_type,
prob_turn_up, prob_turn_down, prob_continue, prob_false_breakout,
confidence, evidence_score, evidence_items, risk_flags, source_state_summary,
bucket_sample_size, prior_weight, market_regime, industry_l1,
future_return_n, outcome_label, model_version, updated_at
```

索引：

- `idx_tpp_pk`：`(stock_code, state_date, window, model_version)`
- `idx_tpp_date`：`(state_date)`
- `idx_tpp_window_type`：`(window, turning_type)`
- `idx_tpp_confidence`：`(confidence)`

### 2.3 JSON 摘要结构

```json
{
  "meta": { "state_date", "model_version", "generated_at", "market_regime", "row_count", "warnings" },
  "market_summary": { "3D": {...}, "3W": {...}, "3M": {...}, "6M": {...} },
  "top_by_window": { "3D": [...], "3W": [...], "3M": [...], "6M": [...] }
}
```

JSON 默认摘要不包含：

- `future_return_n`
- `outcome_label`

---

## 3. 测试结果

### 3.1 编译通过

```bash
.venv/bin/python -m py_compile scripts/build_turning_point_probability.py
.venv/bin/python -m py_compile tests/unit/test_turning_point_probability.py
```

### 3.2 单元测试通过

```bash
.venv/bin/python -m pytest tests/unit/test_turning_point_probability.py -q
```

结果：

```text
9 passed in ~2s
```

覆盖：

1. 脚本可生成 DuckDB 和 latest JSON。
2. 四个时间窗都有输出。
3. 概率字段在 `[0, 1]`。
4. 四概率和接近 1（容差 0.01）。
5. `confidence` 在 `[0, 1]`。
6. 样本不足时 `confidence <= 0.5`。
7. latest JSON 不暴露交易动作词，也不暴露 `future_return_n` / `outcome_label`。
8. State Cube 和 Foundation 均缺失时降级为空产物，不报错。

### 3.3 验收命令运行

```bash
.venv/bin/python scripts/build_turning_point_probability.py --date 2026-07-02
```

运行成功，生成 22,076 行产物，并记录降级 warning。

---

## 4. 概率口径与降级策略

### 4.1 概率计算（可解释启发式 + 历史分桶）

1. **状态指纹**：基于 `(D1_bucket, W1_bucket, MN1_bucket, ef_count_bucket)` 四维度粗粒度指纹。
   - bucket：strong_pos / pos / neutral / neg / strong_neg / zero / unknown
   - ef_count_bucket：0 / 1 / 2 / 3+
2. **历史 outcome 标签**：对每个历史 (stock, date)，按未来收益打上：
   - `turn_up`
   - `turn_down`
   - `continue`
   - `false_breakout`
3. **阈值**：
   - 3D：±2%
   - 3W：±5%
   - 3M：±10%
   - 6M：±20%
4. **经验频率**：统计同指纹下各 outcome 出现次数。
5. **收缩估计**：`P_final = w * P_empirical + (1 - w) * P_global`，其中 `w = N_f / (N_f + 50)`。
6. **回退链路**：细粒度指纹 → 粗粒度指纹（去掉 ef_count）→ 全局先验。
7. **置信度**：`confidence = min(1, sqrt(N_f / 100)) * (1 - entropy)`，原始指纹样本 `< 30` 时强制 `≤ 0.5`。
8. **turning_type**：四概率 argmax；`confidence < 0.3` 时标记为 `uncertain`。

### 4.2 数据源降级

- **主数据源**：`outputs/state_cube/state_cube.duckdb`
- **降级数据源**：`outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb`
- 若 State Cube 缺少目标日期，自动在内存中创建与 State Cube 字段对齐的临时视图，使用 Foundation 的 `d1_perspective_state` 继续计算。
- 若两者均缺失，生成空产物，并在 `meta.warnings` 中说明原因，不抛异常。

### 4.3 证据与风险

- **evidence_items**：基于 D1/W1/MN1 状态、EF 数量、ADX、BB 宽度、M30 信号生成。
- **risk_flags**：低置信、样本不足、ADX 偏弱、M30 假突破、波动压缩等。
- 全部文案避开交易动作词。

---

## 5. 是否可进入 Codex 审计

可以。

已确认：

- ✅ 不改 `web/main.py`。
- ✅ 不改 `web/templates/index.html`。
- ✅ 不接首页。
- ✅ 不新增 Agent。
- ✅ 不改 State Cube。
- ✅ 不改 Decision Ledger。
- ✅ 不引入黑盒深度学习。
- ✅ 不输出交易动作。
- ✅ 不使用经典策略信号修正概率。
- ✅ 概率和约束、置信度约束、字段契约符合任务要求。
- ✅ 单元测试全部通过。
- ✅ 真实数据运行成功。

### 待 Codex 重点审计项

1. `window` 是 DuckDB 保留关键字，表/索引/SQL 中已用双引号包裹；消费端是否兼容。
2. Foundation 降级模式下，M30 信号、BB position 等字段为 NULL，证据生成是否过度依赖这些字段。
3. 当前所有 `turning_type` 大多落在 `uncertain`，是否符合 Phase 2 MVP "不过度自信" 原则，还是过于保守。
4. `future_return_n` / `outcome_label` 是否真正未进入 JSON 默认摘要。
5. 概率口径阈值是否需要在后续根据 State Timeline / Ledger 回填结果校准。

---

## 6. 已知限制

- State Cube 最新日期为 `2026-06-30`，因此 `--date 2026-07-02` 实际使用 Foundation DB 降级模式。
- Foundation 视图缺少 M30 相关字段，导致部分证据项无法生成。
- 当前为启发式 MVP，概率校准、Brier Score、Top-K Precision 等指标需在后续回测中验证。
