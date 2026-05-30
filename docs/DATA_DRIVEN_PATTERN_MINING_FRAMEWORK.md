# 数据驱动的机会模式挖掘框架

版本：v1.0
日期：2026-05-24
状态：设计稿
关联白皮书：`docs/MULTICYCLE_STATE_STRATEGY_WHITEPAPER.md`
关联验证：`docs/STATE_COMBO_CROSS_PERIOD_VALIDATION_DESIGN.md`
关联校准：`docs/CALIBRATION_TRIGGER_DESIGN.md`

---

## 核心理念

**规则是从数据中长出来的，不是从假设中推导出来的。**

当前系统的验证逻辑是"验证预设假设"——VCP 验证"收缩后释放"、2560 验证"E/E/F 组合"、布林强盗验证"volatility_bit=0"。这些假设来自策略理论和 KIMI 研究。

本框架翻转这个逻辑：**不预设任何假设，让历史数据自动发现哪些 State 变化模式与正期望收益相关。** 系统每天扫描所有 State 跃迁组合，按超额收益排序，输出候选模式。样本积累后自动升级为"已验证模式"。

---

## 1. 模式定义

### 1.1 模式的三层结构

```text
模式 = State 跃迁路径 + 三周期协同条件 + 观察窗口
```

| 层次 | 定义 | 示例 |
|------|------|------|
| 跃迁路径 | D1 State 从 A 变为 B | D1: 4→14（收缩有趋势→扩张有趋势突破） |
| 协同条件 | W1/MN1 在跃迁发生时的状态 | W1=12 AND MN1=14（周线趋势行进+月线强势突破） |
| 观察窗口 | 跃迁后 N 日的超额收益 | 20 日超额收益 |

### 1.2 模式维度

| 维度 | 变量数量 | 说明 |
|------|----------|------|
| D1 跃迁（from→to） | 16×16=256 种 | 日线状态变化 |
| W1 当前状态 | 16 种 | 周线背景 |
| MN1 当前状态 | 16 种 | 月线背景 |
| **理论组合总数** | **256×16×16 = 65,536** | |

### 1.3 模式编码

```python
def encode_pattern(
    d1_from: int,
    d1_to: int,
    w1_state: int,
    mn1_state: int,
) -> str:
    """
    模式编码格式：D{from}_{to}_W{w1}_M{mn1}

    示例：
        D4_14_W12_M14 → D1 从 4(收缩有趋势) 变为 14(强势突破)，
                         W1=12(趋势行进), MN1=14(强势突破)
        D0_8_W8_M8    → D1 从 0(收缩沉寂) 变为 8(刚扩张)，
                         W1=8(刚扩张), MN1=8(刚扩张)
    """
    sign_from = "+" if d1_from >= 0 else ""
    sign_to = "+" if d1_to >= 0 else ""
    return f"D{sign_from}{d1_from}_{sign_to}{d1_to}_W{w1_state}_M{mn1_state}"
```

### 1.4 模式的语义解码

```python
def decode_pattern(pattern_code: str) -> dict:
    """将模式编码解码为语义描述。"""
    # 解析编码
    parts = pattern_code.split("_")
    d1_from = int(parts[0][1:])
    d1_to = int(parts[1])
    w1 = int(parts[2][1:])
    mn1 = int(parts[3][1:])

    return {
        "d1_from": decode_state(d1_from),
        "d1_to": decode_state(d1_to),
        "d1_transition": f"{state_label(d1_from)} → {state_label(d1_to)}",
        "w1_context": decode_state(w1),
        "mn1_context": decode_state(mn1),
        "summary": f"D1 {state_label(d1_from)}→{state_label(d1_to)} | "
                   f"W1={state_label(w1)} MN1={state_label(mn1)}",
    }
```

---

## 2. 自动发现流程

### 2.1 总体流程

```python
def mine_opportunity_patterns(
    foundation_db: Path,
    start_date: str,
    end_date: str,
    windows: list[int] = [5, 10, 20],
    min_samples: int = 30,
    top_n: int = 50,
    n_bootstrap: int = 2000,
) -> dict:
    """
    自动发现机会模式。

    流程：
        1. 加载所有日期的 State 数据
        2. 构建 D1 跃迁序列
        3. 对每个跃迁，记录当时的 W1/MN1 状态
        4. 标注未来 N 日超额收益
        5. 按模式编码分组
        6. 过滤样本量 >= min_samples 的模式
        7. 按超额收益排序
        8. 计算 Bootstrap CI
        9. 输出 Top N
    """
```

### 2.2 Step 1：构建跃迁序列

```python
def build_transition_series(
    foundation_db: Path,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """
    构建全市场的 State 跃迁序列。

    每条记录：
        {
            "stock_code": str,
            "date": str,           # 跃迁发生日期
            "d1_from": int,        # 前一日 D1 State score
            "d1_to": int,          # 当日 D1 State score
            "w1_state": int,       # 当日 W1 State score
            "mn1_state": int,      # 当日 MN1 State score
            "ef_count": int,       # 当日 ef_count
            "d1_close": float,     # 当日收盘价
        }

    数据来源：p116_foundation.duckdb 中每日的 MN1/W1/D1 state_score
    """
    con = duckdb.connect(str(foundation_db), read_only=True)

    # 查询所有日期的 State 数据，按股票和日期排序
    rows = con.execute("""
        SELECT stock_code, date, mn1_state_score, w1_state_score, d1_state_score,
               ef_count, d1_close
        FROM p116_foundation
        WHERE date BETWEEN ? AND ?
        ORDER BY stock_code, date
    """, [start_date, end_date]).fetchall()

    con.close()

    # 构建跃迁：每只股票相邻两日的 D1 变化
    transitions = []
    prev_by_code = {}

    for code, date, mn1, w1, d1, ef, close in rows:
        prev = prev_by_code.get(code)
        if prev and prev["d1_score"] is not None and d1 is not None:
            transitions.append({
                "stock_code": code,
                "date": str(date),
                "d1_from": prev["d1_score"],
                "d1_to": d1,
                "w1_state": w1,
                "mn1_state": mn1,
                "ef_count": ef,
                "d1_close": close,
            })
        prev_by_code[code] = {"d1_score": d1, "date": str(date)}

    return transitions
```

### 2.3 Step 2：标注未来收益

```python
def attach_forward_returns(
    transitions: list[dict],
    foundation_db: Path,
    windows: list[int] = [5, 10, 20],
) -> list[dict]:
    """为每个跃迁标注未来 N 日超额收益。"""
    # 复用 forward_observation_ledger.py 的 attach_labels 逻辑
    # 从 Foundation DB 中获取未来收盘价
    # 计算个股收益 vs 全市场等权收益

    for t in transitions:
        for w in windows:
            stock_return = compute_forward_return(foundation_db, t["stock_code"], t["date"], w)
            market_return = compute_market_equal_weight_return(foundation_db, t["date"], w)
            if stock_return is not None and market_return is not None:
                t[f"excess_ret_{w}d"] = stock_return - market_return
            else:
                t[f"excess_ret_{w}d"] = None

    return transitions
```

### 2.4 Step 3：模式分组与统计

```python
def group_and_score_patterns(
    transitions: list[dict],
    window: int = 20,
    min_samples: int = 30,
    n_bootstrap: int = 2000,
) -> list[dict]:
    """
    按模式编码分组，计算统计量。

    步骤：
        1. 为每个跃迁生成模式编码
        2. 按编码分组
        3. 过滤样本量 < min_samples 的组
        4. 计算每组的 metric_row（含 Bootstrap CI）
        5. 按 mean_excess 降序排序
    """
    from bootstrap_stats import metric_row

    by_pattern = defaultdict(list)
    for t in transitions:
        if t.get(f"excess_ret_{window}d") is None:
            continue
        # 简化编码：只用 D1 跃迁 + W1 状态（减少组合数）
        pattern = encode_pattern_simple(t["d1_from"], t["d1_to"], t["w1_state"])
        by_pattern[pattern].append(t)

    results = []
    for pattern, items in by_pattern.items():
        if len(items) < min_samples:
            continue
        row = metric_row(pattern, items, window, n_bootstrap)
        row["d1_from"] = items[0]["d1_from"]
        row["d1_to"] = items[0]["d1_to"]
        row["w1_state"] = items[0]["w1_state"]
        row["mn1_states"] = list(set(t["mn1_state"] for t in items))
        results.append(row)

    results.sort(key=lambda r: r.get("mean_excess") or -999, reverse=True)
    return results
```

### 2.5 简化编码：降低组合爆炸

65,536 种理论组合中大部分样本量不足。采用两步压缩：

```python
def encode_pattern_simple(d1_from: int, d1_to: int, w1_state: int) -> str:
    """
    简化编码：只用 D1 跃迁 + W1 base 维度。

    将 16×16×16 = 4096 压缩为 256×4 = 1024 种组合：
        D1 跃迁：16×16 = 256 种
        W1 维度：4 种（收缩无趋势/收缩有趋势/扩张无趋势/扩张有趋势）
    """
    w1_base = "exp" if abs(w1_state) >= 8 else "con"
    w1_trend = "t" if (abs(w1_state) >> 2) & 1 else "f"
    w1_tag = f"{w1_base}_{w1_trend}"

    return f"D{d1_from}_{d1_to}_W{w1_tag}"
```

进一步压缩：只保留 D1 发生了**实质性变化**的跃迁。

```python
def is_significant_transition(d1_from: int, d1_to: int) -> bool:
    """过滤掉无实质变化的跃迁。"""
    # 绝对值变化 >= 4（至少一个 bit 翻转）
    if abs(abs(d1_to) - abs(d1_from)) >= 4:
        return True
    # base 翻转（收缩↔扩张）
    if (abs(d1_from) >= 8) != (abs(d1_to) >= 8):
        return True
    # 方向翻转
    if (d1_from >= 0) != (d1_to >= 0):
        return True
    return False
```

---

## 3. 模式分级

### 3.1 三级分级体系

| 级别 | 条件 | 含义 | 可展示 |
|------|------|------|--------|
| **已验证** | n >= 100 且 CI 不含零 且 跨期方向一致率 >= 60% | 统计显著且稳定 | 可展示具体数字 |
| **候选观察** | 30 <= n < 100 且 mean_excess > 0 | 有正期望但样本不足 | 展示方向，标注"待积累" |
| **待观察** | n < 30 或 mean_excess <= 0 | 数据不足或无正期望 | 不展示 |

### 3.2 升级条件

```python
def classify_pattern_status(pattern: dict, cross_period_results: list[dict] | None) -> str:
    """模式状态分级。"""
    n = pattern["n"]
    mean_excess = pattern.get("mean_excess") or 0
    ci_lo = pattern.get("mean_excess_ci_lo")
    ci_hi = pattern.get("mean_excess_ci_hi")

    # 已验证：样本充足 + CI 不含零 + 跨期一致
    if n >= 100 and ci_lo is not None and ci_lo > 0:
        if cross_period_results:
            positive_periods = sum(1 for r in cross_period_results
                                   if (r.get("mean_excess") or 0) > 0)
            if positive_periods / len(cross_period_results) >= 0.6:
                return "verified"

    # 候选观察：正期望但样本不足
    if n >= 30 and mean_excess > 0:
        return "candidate"

    # 待观察
    return "pending"
```

---

## 4. 与现有验证引擎的对接

### 4.1 复用组件

```text
复用 scripts/bootstrap_stats.py：
  - metric_row() — 含 Bootstrap CI
  - pct() / fmt_num() — 格式化

复用 scripts/forward_observation_ledger.py：
  - attach_labels() — 未来收益标注逻辑
  - market_equal_weight_return() — 全市场基准

复用 scripts/validate_state_combo_stability.py：
  - 跨期稳定性验证逻辑
```

### 4.2 新增脚本

```text
scripts/mine_opportunity_patterns.py
```

### 4.3 执行命令

```bash
# 每日模式挖掘
python3 scripts/mine_opportunity_patterns.py \
  --start-date 2025-06-01 \
  --end-date 2026-05-24 \
  --foundation-db outputs/p116_foundation_20260524/p116_foundation.duckdb \
  --window 20 \
  --min-samples 30 \
  --top-n 50

# 仅扫描 D1 跃迁（快速模式，不考虑 W1/MN1）
python3 scripts/mine_opportunity_patterns.py \
  --start-date 2025-06-01 \
  --end-date 2026-05-24 \
  --mode d1_only

# 全三周期模式（完整模式，样本量要求更高）
python3 scripts/mine_opportunity_patterns.py \
  --start-date 2025-06-01 \
  --end-date 2026-05-24 \
  --mode full_three_period

# 跨期稳定性验证
python3 scripts/mine_opportunity_patterns.py \
  --start-date 2022-01-01 \
  --end-date 2026-05-24 \
  --validate-stability
```

---

## 5. 输出设计

### 5.1 每日输出

```json
// outputs/project/opportunity_patterns_daily.json
{
  "schema_version": "opportunity_patterns_v1",
  "date": "2026-05-24",
  "generated_at": "2026-05-24T07:30:00+00:00",
  "data_range": {"start": "2025-06-01", "end": "2026-05-24"},
  "mode": "d1_w1",
  "window": 20,
  "min_samples": 30,
  "total_patterns_scanned": 1024,
  "patterns_with_sufficient_samples": 87,
  "patterns": [
    {
      "pattern_code": "D4_14_Wexp_t",
      "status": "verified",
      "d1_transition": "收缩有趋势 → 强势突破",
      "w1_context": "扩张有趋势",
      "n": 156,
      "mean_excess": 0.0523,
      "mean_excess_ci_lo": 0.028,
      "mean_excess_ci_hi": 0.077,
      "win_rate": 0.583,
      "t_stat": 2.85,
      "payoff_ratio": 1.72,
      "summary": "D1从收缩有趋势跃迁至强势突破，W1扩张有趋势背景"
    },
    ...
  ],
  "status_counts": {
    "verified": 12,
    "candidate": 35,
    "pending": 40
  },
  "research_only": true
}
```

### 5.2 月度报告

```markdown
# 机会模式月度报告 — 2026 年 5 月

## 概览
- 扫描模式数：1,024
- 有效模式（n>=30）：87
- 已验证模式：12
- 候选观察模式：35

## 已验证模式 Top 10

| 排名 | 模式 | D1 跃迁 | W1 背景 | n | 20d 超额 | 95% CI | 胜率 | 状态 |
|------|------|---------|---------|---|---------|--------|------|------|
| 1 | D4→14 W_exp_t | 收缩有趋势→强势突破 | 扩张有趋势 | 156 | +5.23% | [+2.8%,+7.7%] | 58.3% | 已验证 |
| 2 | D0→14 W_exp_t | 沉寂→强势突破 | 扩张有趋势 | 89 | +4.81% | [+1.9%,+7.7%] | 56.2% | 已验证 |
| 3 | D8→14 W_exp_t | 刚扩张→强势突破 | 扩张有趋势 | 134 | +3.95% | [+1.5%,+6.4%] | 55.2% | 已验证 |
| ... |

## 候选观察模式（待积累样本）

| 排名 | 模式 | D1 跃迁 | n | 20d 超额 | 状态 |
|------|------|---------|---|---------|------|
| 13 | D5→14 W_con_t | 收缩有趋势波动→强势突破 | 45 | +6.12% | 候选 |
| 14 | D0→12 W_exp_f | 沉寂→趋势行进 | 38 | +5.44% | 候选 |
| ... |

## 新发现（本月新增的候选模式）
- D5→14：收缩有趋势波动→强势突破（本月新增 15 个样本，总计 45）
- D3→14：收缩突破波动→强势突破（本月新增 8 个样本，总计 33）

## 模式演变（已有模式的本月表现）
- D4→14 W_exp_t：本月 12 个新样本，超额 +3.8%（低于历史均值但仍为正）
- D0→14 W_exp_t：本月 5 个新样本，超额 +7.2%（高于历史均值）

## 与已知策略的对比
- VCP "收缩后释放"（D1 近 20 日路径）：对应模式 D4→14，已验证
- 2560 "E/E/F 组合"：对应多周期静态组合，不在本框架扫描范围（本框架关注跃迁）
- 布林强盗 "vol=0"：对应 D1 volatility_bit 维度，可在扩展扫描中覆盖
```

---

## 6. 复利效应：每日更新机制

### 6.1 增量更新

```python
def incremental_update(
    existing_patterns: dict,
    new_date: str,
    foundation_db: Path,
) -> dict:
    """
    增量更新：只处理新日期的数据，追加到现有模式统计中。

    复利效应：
        - 每天新增 ~5000 个跃迁样本
        - 每月新增 ~100,000 个样本
        - 候选模式的样本量持续增长
        - 部分候选模式将升级为已验证模式
    """
    # 1. 加载新日期的跃迁
    new_transitions = build_transitions_for_date(foundation_db, new_date)
    new_transitions = attach_forward_returns(new_transitions, foundation_db, windows=[5, 10, 20])

    # 2. 按模式编码分组
    new_by_pattern = group_by_pattern(new_transitions)

    # 3. 合并到现有模式
    for pattern_code, new_items in new_by_pattern.items():
        existing = existing_patterns.get(pattern_code, {"items": [], "status": "pending"})
        existing["items"].extend(new_items)
        existing["n"] = len(existing["items"])
        # 重新计算统计量
        if existing["n"] >= 30:
            values = [t["excess_ret_20d"] for t in existing["items"]
                       if t.get("excess_ret_20d") is not None]
            existing["mean_excess"] = statistics.fmean(values) if values else 0
            # ... 更新 CI, win_rate 等
        existing_patterns[pattern_code] = existing

    return existing_patterns
```

### 6.2 样本积累曲线

```text
月份    | 累计跃迁样本 | 有效模式数(n>=30) | 已验证模式数
--------|-------------|-------------------|-------------
2025-06 | ~100K       | ~20               | 0
2025-09 | ~300K       | ~45               | 3
2025-12 | ~500K       | ~65               | 8
2026-03 | ~700K       | ~80               | 12
2026-06 | ~900K       | ~87               | 15+
```

---

## 7. 与三重共振的衔接

### 7.1 已验证模式作为新的环境标签

当某个模式被验证为"已验证"状态后，可以转化为系统中的环境标签：

```python
# 示例：D4→14 W_exp_t 被验证后
VERIFIED_PATTERNS = {
    "D4_14_Wexp_t": {
        "label": "收缩释放突破",
        "description": "D1 从收缩有趋势跃迁至强势突破，W1 扩张有趋势",
        "env_category": "strong_resonance",  # 归入现有环境分类
        "strategy_implication": {"vcp": "best_fit", "ma2560": "fit", "bollinger": "fit"},
    },
}
```

### 7.2 模式作为策略信号的附加证据

```python
def enrich_signal_with_patterns(
    signal_row: dict,
    current_transition: dict,
    verified_patterns: dict,
) -> dict:
    """如果当前信号的 State 跃迁匹配某个已验证模式，附加证据。"""
    pattern_code = encode_pattern_simple(
        current_transition["d1_from"],
        current_transition["d1_to"],
        current_transition["w1_state"],
    )

    if pattern_code in verified_patterns:
        pattern = verified_patterns[pattern_code]
        signal_row["matched_pattern"] = pattern_code
        signal_row["pattern_mean_excess"] = pattern["mean_excess"]
        signal_row["pattern_status"] = pattern["status"]
    else:
        signal_row["matched_pattern"] = None

    return signal_row
```

---

## 8. 扩展维度

### 8.1 当前框架的限制

| 限制 | 说明 | 未来扩展 |
|------|------|----------|
| 只看单日跃迁 | D1 从 A 到 B 的单日变化 | 扩展为多日路径（如 A→B→C） |
| 只看 State score | 不含 SR 距离、成交量等 | 扩展为多因子模式 |
| W1/MN1 只看当前状态 | 不看 W1/MN1 的跃迁 | 扩展为三周期协同跃迁 |
| 不含资金流 | 无资金流维度 | Phase 2 后可加入 |

### 8.2 多日路径模式（未来）

```text
当前：D1 单日跃迁 A→B
扩展：D1 多日路径 A→B→C（3 日内）

路径编码：D4_14_15_Wexp_t
含义：D1 第 1 天从 4 变为 14，第 2 天变为 15，W1 扩张有趋势
```

### 8.3 三周期协同跃迁（未来）

```text
当前：D1 跃迁 + W1 当前状态
扩展：D1 跃迁 + W1 跃迁 + MN1 当前状态

编码：D4_14_W8_14_M14
含义：D1 4→14，W1 8→14，MN1=14
含义（语义）：日线收缩释放+周线刚扩张转强势+月线强势突破
```

---

## 9. 合规边界

- 模式挖掘是**研究工具**，不直接生成交易信号。
- "已验证模式"是统计发现，不是操作建议。
- 候选观察模式标注"待积累"，不展示具体收益预测。
- 模式挖掘结果不修改现有策略触发逻辑。
- 所有输出包含 `research_only: true`。
