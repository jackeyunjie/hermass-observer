# KIMI1 任务：转折概率 MVP 独立脚本实现

日期：2026-07-02
执行者：KIMI1
任务类型：后端脚本 / DuckDB 产物 / 单元测试

---

## 背景

设计文档：

- `docs/tasks/TURNING_POINT_PROBABILITY_MVP_KIMI1_20260702.md`
- `docs/tasks/OBSERVATION_DECK_CODEX_INTEGRATION_REVIEW_20260702.md`

Codex 裁决：

- 概率引擎作为 Phase 2 独立证据层。
- 暂不接首页。
- 暂不新增第 7 Agent。
- 不进入 Agent 辩论。
- 不和经典策略信号混合。

---

## 你的目标

实现一个可跑通的独立 MVP：

```text
scripts/build_turning_point_probability.py --date 2026-07-02
```

生成：

```text
outputs/turning_point_probability/turning_point_probability_20260702.duckdb
outputs/turning_point_probability/turning_point_probability_latest.json
```

---

## MVP 范围

### 时间窗

- 3D = 3 个交易日
- 3W = 15 个交易日
- 3M = 66 个交易日
- 6M = 126 个交易日

### 输出字段

最小必须包含：

```text
stock_code
stock_name
state_date
window
turning_type
prob_turn_up
prob_turn_down
prob_continue
prob_false_breakout
confidence
evidence_score
evidence_items
risk_flags
source_state_summary
bucket_sample_size
prior_weight
market_regime
industry_l1
model_version
updated_at
```

`future_return_n` 和 `outcome_label` 属于回测字段，允许写入 DuckDB，但不要写入 latest JSON 默认前端摘要。

### 概率口径

MVP 可以先用可解释启发式 + 历史分桶雏形：

1. 从 Foundation / State Timeline 读取当日 MN1/W1/D1 状态。
2. 构造粗粒度状态指纹。
3. 若历史样本可用，统计同类状态的 outcome 频率。
4. 若历史样本不足，回退全局先验。
5. 输出四概率，置信度样本不足时不超过 0.5。

不要追求完美贝叶斯，先保证：

- 可运行。
- 可解释。
- 字段稳定。
- 不过度自信。

---

## 数据源优先级

优先复用现有：

- `outputs/state_timeline/state_timeline_daily_YYYYMMDD.duckdb`
- `outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb`
- `outputs/fundamental/fundamental_evidence.duckdb`（可选，缺失时降级）

如果某数据源缺失：

- 不允许 500。
- 写出空产物或降级产物。
- 在 JSON meta 中写 warning。

---

## 不要做

- 不改 `web/main.py`。
- 不改 `web/templates/index.html`。
- 不接首页。
- 不新增 Agent。
- 不改 State Cube。
- 不改 Decision Ledger。
- 不引入黑盒深度学习。
- 不输出交易动作。
- 不使用经典策略信号修正概率。

---

## 测试要求

新增：

`tests/unit/test_turning_point_probability.py`

至少覆盖：

1. 脚本可生成 DuckDB 和 latest JSON。
2. 四个时间窗都有输出。
3. 概率字段在 `[0, 1]`。
4. 四概率和接近 1。
5. `confidence` 在 `[0, 1]`。
6. 样本不足时 `confidence <= 0.5`。
7. latest JSON 不暴露交易动作词。
8. fundamental DB 缺失时降级不报错。

---

## 验收命令

```bash
.venv/bin/python -m py_compile scripts/build_turning_point_probability.py
.venv/bin/python -m py_compile tests/unit/test_turning_point_probability.py
.venv/bin/python -m pytest tests/unit/test_turning_point_probability.py -q
.venv/bin/python scripts/build_turning_point_probability.py --date 2026-07-02
```

---

## 输出文件

请写入交付文档：

`docs/tasks/TURNING_POINT_PROBABILITY_IMPLEMENT_DELIVERY_20260702.md`

---

## 返回格式

完成后回复：

1. 改了哪些文件。
2. 生成了哪些产物。
3. 测试结果。
4. 概率口径如何降级。
5. 是否可进入 Codex 审计。
