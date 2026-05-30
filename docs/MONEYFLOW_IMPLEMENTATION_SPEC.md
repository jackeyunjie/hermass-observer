# 资金流证据层工程实现规范

版本：v1.0
日期：2026-05-23
状态：实现规范 — 供 Codex 工程实现
关联设计：`docs/MONEYFLOW_EVIDENCE_MODEL.md`
现有实现：`blackwolf_actions/build_moneyflow_evidence.py`（v1 简化版，本规范是 v2 升级版）

---

## 概述

本规范将 `MONEYFLOW_EVIDENCE_MODEL.md` 的五维评分模型转化为可被 Codex 直接实现的工程规格。v1 版本（`blackwolf_actions/build_moneyflow_evidence.py`）使用 5 分制简化评分，本规范升级为 0-10 分五维评分。

---

## 1. 数据源与输入

### 1.1 主数据源：moneyflow_daily 表

```sql
-- 位置：outputs/blackwolf_moneyflow/blackwolf_moneyflow.duckdb
-- 表名：moneyflow_daily
-- 当前行数：32806（截至 2026-05-22）

stock_code        VARCHAR    -- 股票代码（如 688069.SH）
date              DATE       -- 交易日期
buy_total         DOUBLE     -- 当日买入总额（万元）
sell_total        DOUBLE     -- 当日卖出总额（万元）
active_net        DOUBLE     -- 主动净流入 = buy_total - sell_total
big_order_net     DOUBLE     -- 大单净流入 = (特大单+大单)买入 - (特大单+大单)卖出
active_net_ratio  DOUBLE     -- 主动净流入占比 = active_net / buy_total
buynum            BIGINT     -- 买入笔数
sellnum           BIGINT     -- 卖出笔数
totalnum          BIGINT     -- 总笔数
source_csv        VARCHAR    -- 来源 CSV 路径
imported_at       TIMESTAMP  -- 入库时间
```

### 1.2 辅助数据源

| 数据源 | 路径 | 用途 |
|--------|------|------|
| State 缓存 | `outputs/state_cache/state_ef_{date}.json` | ef_count 用于判断 State 强势 |
| 行业映射 | `outputs/ifind/industry_{date}.json` | sw_l1 用于行业内排名 |
| 市场资产 | `outputs/market_assets_state/market_assets_state_{date}.json` | 全市场股票列表 |

### 1.3 日期窗口

```python
def compute_windows(end_date: str) -> dict:
    """计算评分需要的日期窗口。"""
    return {
        "recent_5d": recent_weekdays(end_date, 5),    # 近 5 个交易日
        "recent_20d": recent_weekdays(end_date, 20),   # 近 20 个交易日（价格新高判定）
        "recent_60d": recent_weekdays(end_date, 60),   # 近 60 个交易日（历史分位）
    }
```

---

## 2. 函数清单与接口定义

### 2.1 主函数

```python
def build_moneyflow_evidence(
    date_str: str,
    db_path: Path = DEFAULT_DB,
    state_cache_dir: Path = STATE_CACHE_DIR,
    ifind_dir: Path = IFIND_DIR,
) -> dict:
    """
    构建资金流证据层。

    输入：
        date_str: 交易日期
        db_path: moneyflow_daily 所在 DuckDB
        state_cache_dir: State 缓存目录
        ifind_dir: iFinD 行业映射目录

    输出：
        {
            "schema_version": "moneyflow_evidence_v2",
            "date": str,
            "generated_at": str,
            "total": int,
            "coverage_rate": float,
            "status_counts": dict,
            "divergence_alerts": list,
            "rows": list[dict],  # 每只股票的五维评分
            "research_only": True,
        }
    """
```

### 2.2 五维评分函数

#### S_inflow：净流入分项

```python
def compute_S_inflow(
    active_net_5d: float,
    big_order_net_5d: float,
    percentile_active_60d: float | None,
    percentile_big_60d: float | None,
) -> float:
    """
    净流入分项评分（0-10）。

    参数：
        active_net_5d: 近 5 日主动净流入累计（万元）
        big_order_net_5d: 近 5 日大单净流入累计（万元）
        percentile_active_60d: active_net_5d 在近 60 日的百分位（0-100），None=数据不足
        percentile_big_60d: big_order_net_5d 在近 60 日的百分位（0-100），None=数据不足

    返回：
        0-10 分

    计算逻辑：
        取两个分位的加权平均，大单权重更高（0.6），主动净流入权重 0.4
        percentile_combined = percentile_active × 0.4 + percentile_big × 0.6
        score = percentile_combined / 10.0
        两个分位都为 None 时返回 5.0（中性）
    """
```

#### S_consecutive：连续流入分项

```python
def compute_S_consecutive(
    daily_active_nets: list[float],
) -> float:
    """
    连续流入分项评分（0-10）。

    参数：
        daily_active_nets: 近 5 日每日主动净流入列表（从旧到新）

    返回：
        0-10 分

    计算逻辑：
        consecutive_days = 从最新一天向前数，连续为正的天数
        若最新一天为负，consecutive_days 为负值（连续流出天数）

        评分映射：
            >= 5 日连续流入 → 9.0
            3-4 日连续流入 → 7.0
            1-2 日连续流入 → 5.5
            0（无净流入）  → 5.0
            1-2 日连续流出 → 4.0
            3-4 日连续流出 → 3.0
            >= 5 日连续流出 → 1.5

        额外加成：若连续流入且每日金额递增，+0.5
    """
```

#### S_divergence：背离分项

```python
def compute_S_divergence(
    price_new_high_20d: bool,
    moneyflow_new_high_60d: bool,
    price_new_low_20d: bool,
    moneyflow_strong_outflow_60d: bool,
    ef_count: int,
) -> tuple[float, str | None]:
    """
    背离分项评分（0-10）+ 背离警告。

    参数：
        price_new_high_20d: 当日收盘价为近 20 日最高
        moneyflow_new_high_60d: 近 5 日累计净流入为近 60 日最高
        price_new_low_20d: 当日收盘价为近 20 日最低
        moneyflow_strong_outflow_60d: 近 5 日累计净流出为近 60 日最大
        ef_count: 三周期 E/F 数量（背离仅在 ef_count >= 2 时有意义）

    返回：
        (score: float, alert: str | None)

    计算逻辑：
        高位分歧：price_new_high AND NOT moneyflow_new_high AND ef_count >= 2
            → score = 2.0, alert = "高位分歧：价格创新高但资金不跟随"

        底部吸筹：price_new_low AND moneyflow_strong_outflow == False AND active_net_5d > 0
            → score = 8.0, alert = "底部吸筹：价格创新低但资金持续流入"

        量价齐升：price_new_high AND moneyflow_new_high
            → score = 7.0, alert = None

        量价齐跌：price_new_low AND moneyflow_strong_outflow_60d
            → score = 3.0, alert = None

        其他：score = 5.0, alert = None

        仅在 ef_count >= 2 时触发高位分歧警告（State 不强时不判定背离）
    """
```

#### S_relative：相对强度分项

```python
def compute_S_relative(
    stock_active_net_5d: float,
    all_stocks_active_net_5d: list[float],
    industry_active_net_5d: list[float],
) -> float:
    """
    相对强度分项评分（0-10）。

    参数：
        stock_active_net_5d: 该股票近 5 日主动净流入
        all_stocks_active_net_5d: 全市场所有股票的 active_net_5d 列表
        industry_active_net_5d: 同行业（sw_l1）所有股票的 active_net_5d 列表

    返回：
        0-10 分

    计算逻辑：
        market_rank_pct = 全市场排名百分位（0-100，越大越好）
        industry_rank_pct = 行业内排名百分位（0-100，越大越好）
        combined = market_rank_pct × 0.4 + industry_rank_pct × 0.6
        score = combined / 10.0

        行业内权重更高（0.6），因为同行比较更有参考价值
    """
```

#### S_coverage：数据覆盖分项

```python
def compute_S_coverage(
    days_available: int,
    required_days: int = 60,
) -> float:
    """
    数据覆盖分项评分（0-10）。

    参数：
        days_available: 该股票在近 60 个交易日中有资金流数据的天数
        required_days: 理想覆盖天数

    返回：
        0-10 分

    计算逻辑：
        coverage = min(1.0, days_available / required_days)
        score = coverage × 10.0

        特殊规则：
            coverage < 0.17（< 10 天）→ score = 0.0，标记为数据严重不足
            coverage < 0.50（< 30 天）→ score = coverage × 10 × 0.7（打折）
    """
```

### 2.3 辅助计算函数

```python
def compute_percentile_60d(
    current_value: float,
    historical_values: list[float],
) -> float | None:
    """
    计算当前值在历史序列中的百分位。

    参数：
        current_value: 当前 5 日累计值
        historical_values: 近 60 个交易日的每日 5 日滚动累计值列表

    返回：
        0-100 的百分位，数据不足时返回 None
    """

def detect_consecutive_days(daily_nets: list[float]) -> int:
    """
    检测连续净流入/流出天数。

    返回：
        正值 = 连续净流入天数
        负值 = 连续净流出天数
        0 = 无连续方向
    """

def check_price_new_high(
    closes_20d: list[float],
    current_close: float,
) -> bool:
    """判断当前收盘价是否为近 20 日最高。"""

def check_moneyflow_new_high(
    active_net_5d_series: list[float],
    current_5d: float,
) -> bool:
    """判断当前 5 日净流入是否为近 60 日最高。"""
```

### 2.4 总评分函数

```python
def compute_moneyflow_score(
    S_inflow: float,
    S_consecutive: float,
    S_divergence: float,
    S_relative: float,
    S_coverage: float,
) -> float:
    """
    五维加权总分。

    公式：
        score = clamp(
            0.30 × S_inflow
          + 0.25 × S_consecutive
          + 0.20 × S_divergence
          + 0.15 × S_relative
          + 0.10 × S_coverage,
          0, 10
        )
    """

def label_moneyflow(score: float) -> str:
    """
    资金流标签。

    >= 8.0 → "强势流入"
    >= 6.5 → "温和流入"
    >= 4.5 → "中性"
    >= 2.5 → "温和流出"
    <  2.5 → "强势流出"
    """

def moneyflow_direction(score: float) -> str:
    """
    资金流方向。

    >= 6.5 → "positive"
    <= 3.5 → "negative"
    else   → "neutral"
    """
```

---

## 3. 输出表结构：moneyflow_evidence_daily

### 3.1 DuckDB 表定义

```sql
CREATE TABLE IF NOT EXISTS moneyflow_evidence_daily (
    stock_code              VARCHAR    NOT NULL,
    as_of_date              VARCHAR    NOT NULL,

    -- 五维评分
    mf_score                DOUBLE     NOT NULL,   -- 总分 0-10
    mf_label                VARCHAR    NOT NULL,   -- 强势流入/温和流入/中性/温和流出/强势流出
    mf_direction            VARCHAR    NOT NULL,   -- positive/neutral/negative

    -- 五维子分
    s_inflow                DOUBLE,    -- 净流入分项 0-10
    s_consecutive           DOUBLE,    -- 连续流入分项 0-10
    s_divergence            DOUBLE,    -- 背离分项 0-10
    s_relative              DOUBLE,    -- 相对强度分项 0-10
    s_coverage              DOUBLE,    -- 数据覆盖分项 0-10

    -- 原始指标
    active_net_1d           DOUBLE,    -- 当日主动净流入（万元）
    active_net_5d           DOUBLE,    -- 近 5 日主动净流入累计
    big_order_net_1d        DOUBLE,    -- 当日大单净流入
    big_order_net_5d        DOUBLE,    -- 近 5 日大单净流入累计
    consecutive_days        INTEGER,   -- 连续净流入天数（负=流出）
    percentile_active_60d   DOUBLE,    -- active_net_5d 的 60 日百分位
    percentile_big_60d      DOUBLE,    -- big_order_net_5d 的 60 日百分位
    price_new_high_20d      BOOLEAN,   -- 价格是否近 20 日新高
    moneyflow_new_high_60d  BOOLEAN,   -- 资金流是否近 60 日新高
    market_rank_pct         DOUBLE,    -- 全市场资金流排名百分位
    industry_rank_pct       DOUBLE,    -- 行业内资金流排名百分位
    sw_l1                   VARCHAR,   -- 申万一级行业

    -- 背离与置信度
    divergence_flag         VARCHAR,   -- NULL / "high_divergence" / "low_accumulation"
    divergence_alert        VARCHAR,   -- 背离警告文本
    confidence              DOUBLE,    -- 置信度 0-1
    data_days_available     INTEGER,   -- 近 60 日有数据的天数
    data_status             VARCHAR,   -- ok / partial / insufficient / missing

    -- 元数据
    collected_at            VARCHAR    NOT NULL,

    PRIMARY KEY (stock_code, as_of_date)
);
```

### 3.2 JSON 输出格式

```json
{
  "schema_version": "moneyflow_evidence_v2",
  "date": "2026-05-23",
  "generated_at": "2026-05-23T07:00:00+00:00",
  "total": 5200,
  "coverage_rate": 0.85,
  "status_counts": {
    "ok": 4420,
    "partial": 520,
    "insufficient": 180,
    "missing": 80
  },
  "divergence_alerts": [
    {"stock_code": "600519.SH", "type": "high_divergence", "mf_score": 3.2, "alert": "高位分歧：价格创新高但资金不跟随"}
  ],
  "rows": [
    {
      "stock_code": "002049.SZ",
      "mf_score": 7.8,
      "mf_label": "温和流入",
      "mf_direction": "positive",
      "sub_scores": {"inflow": 8.0, "consecutive": 7.0, "divergence": 7.0, "relative": 8.5, "coverage": 9.0},
      "consecutive_days": 3,
      "divergence_flag": null,
      "confidence": 0.9,
      "data_status": "ok"
    }
  ],
  "research_only": true
}
```

### 3.3 CSV 输出字段

```text
stock_code, mf_score, mf_label, mf_direction,
s_inflow, s_consecutive, s_divergence, s_relative, s_coverage,
active_net_1d, active_net_5d, big_order_net_1d, big_order_net_5d,
consecutive_days, percentile_active_60d, percentile_big_60d,
price_new_high_20d, moneyflow_new_high_60d,
market_rank_pct, industry_rank_pct, sw_l1,
divergence_flag, divergence_alert, confidence,
data_days_available, data_status
```

---

## 4. 与 State 展示层的对接

### 4.1 不改 State 公式

资金流证据层**不修改** `scripts/state_calc/p116_core.py` 的任何计算逻辑。State 编码公式、E/F 定义、位置优先符号裁决全部不变。

### 4.2 在 strategy_signal_daily 中新增字段

```sql
ALTER TABLE strategy_signal_daily ADD COLUMN mf_score DOUBLE;
ALTER TABLE strategy_signal_daily ADD COLUMN mf_label VARCHAR DEFAULT '';
ALTER TABLE strategy_signal_daily ADD COLUMN mf_direction VARCHAR DEFAULT '';
ALTER TABLE strategy_signal_daily ADD COLUMN mf_divergence VARCHAR DEFAULT '';
```

### 4.3 信号账本接入逻辑

在 `scripts/strategy_signal_ledger.py` 的 `signal_rows_for_state()` 函数中新增：

```python
def enrich_with_moneyflow(
    signal_row: dict,
    moneyflow_data: dict[str, dict],
) -> dict:
    """为信号行附加资金流数据。"""
    code = code6(signal_row["stock_code"])
    mf = moneyflow_data.get(code)

    if mf is None:
        signal_row["mf_score"] = None
        signal_row["mf_label"] = ""
        signal_row["mf_direction"] = "neutral"
        signal_row["mf_divergence"] = ""
    else:
        signal_row["mf_score"] = mf["mf_score"]
        signal_row["mf_label"] = mf["mf_label"]
        signal_row["mf_direction"] = mf["mf_direction"]
        signal_row["mf_divergence"] = mf.get("divergence_flag") or ""

    return signal_row
```

### 4.4 适配度调节

资金流仅在 ef_count >= 2 时调节适配度：

```python
def apply_moneyflow_to_fit(
    base_fit_score: float,
    mf_score: float | None,
    mf_direction: str,
    ef_count: int,
) -> float:
    """资金流对适配度的调节。"""
    if mf_score is None or ef_count < 2:
        return base_fit_score

    if mf_direction == "positive":
        return min(100, base_fit_score + 5)
    elif mf_direction == "negative":
        return max(0, base_fit_score - 8)  # 惩罚大于加成
    return base_fit_score
```

### 4.5 提醒层展示

在 `scripts/strategy_reminder_brief.py` 中新增资金流行：

```python
def render_moneyflow_line(mf_score: float | None, mf_label: str,
                           mf_divergence: str) -> str:
    if mf_score is None:
        return "  资金面：数据暂缺"

    line = f"  资金面：{mf_score:.1f}/10 | {mf_label}"
    if mf_divergence == "high_divergence":
        line += " | ⚠ 高位分歧"
    elif mf_divergence == "low_accumulation":
        line += " | 底部吸筹"
    return line
```

---

## 5. 背离检测详细规则

### 5.1 高位分歧检测

```python
def detect_high_divergence(
    close_20d: list[float],
    current_close: float,
    active_net_5d_history: list[float],
    current_active_net_5d: float,
    ef_count: int,
) -> tuple[bool, str | None]:
    """
    高位分歧检测。

    条件（全部满足）：
        1. current_close == max(close_20d)  -- 价格创新高
        2. current_active_net_5d < percentile(active_net_5d_history, 70)  -- 资金流未创新高
        3. ef_count >= 2  -- State 处于强势（分歧在强势时才有意义）

    返回：
        (is_divergence: bool, alert_message: str | None)
    """
    price_high = current_close >= max(close_20d) * 0.99  # 允许 1% 误差
    moneyflow_high = current_active_net_5d >= percentile(active_net_5d_history, 90)

    if price_high and not moneyflow_high and ef_count >= 2:
        return True, "高位分歧：价格创新高但资金不跟随，标记为背离复核"
    return False, None
```

### 5.2 底部吸筹检测

```python
def detect_low_accumulation(
    close_20d: list[float],
    current_close: float,
    active_net_5d: float,
    consecutive_days: int,
) -> tuple[bool, str | None]:
    """
    底部吸筹检测。

    条件（全部满足）：
        1. current_close == min(close_20d)  -- 价格创新低
        2. active_net_5d > 0  -- 资金净流入
        3. consecutive_days >= 2  -- 连续 2+ 日净流入

    返回：
        (is_accumulation: bool, alert_message: str | None)
    """
    price_low = current_close <= min(close_20d) * 1.01  # 允许 1% 误差

    if price_low and active_net_5d > 0 and consecutive_days >= 2:
        return True, "底部吸筹：价格创新低但资金持续流入，可能存在低估机会"
    return False, None
```

### 5.3 背离对适配度的影响

| 背离类型 | 适配度影响 | 展示行为 |
|----------|-----------|---------|
| 高位分歧 | -8 分 | 卡片增加 ⚠ 警告标记 |
| 底部吸筹 | +3 分（仅在 State 强势时） | 卡片增加"底部吸筹"标签 |
| 无背离 | 无影响 | 正常展示 |

---

## 6. 置信度计算

```python
def compute_confidence(
    data_days_available: int,
    required_days: int = 60,
    industry_coverage: float = 0.0,
) -> float:
    """
    资金流评分的置信度。

    参数：
        data_days_available: 有数据的天数
        required_days: 理想天数
        industry_coverage: 同行业有数据的股票占比

    返回：
        0.0-1.0

    计算：
        time_factor = min(1.0, data_days_available / required_days)
        coverage_factor = min(1.0, industry_coverage * 2)  # 行业覆盖 50% 时满分
        confidence = time_factor * 0.7 + coverage_factor * 0.3

        特殊：
            data_days_available < 10 → confidence = 0.0
            data_days_available < 30 → confidence *= 0.5
    """
```

---

## 7. 每日执行命令

```bash
# 标准执行
python3 scripts/build_moneyflow_evidence.py --date 2026-05-23

# 指定 DuckDB 路径
python3 scripts/build_moneyflow_evidence.py --date 2026-05-23 \
  --db outputs/blackwolf_moneyflow/blackwolf_moneyflow.duckdb

# 仅检查不写入
python3 scripts/build_moneyflow_evidence.py --date 2026-05-23 --dry-run
```

### 输出路径

```text
outputs/moneyflow_evidence/moneyflow_evidence_{date}.json
outputs/moneyflow_evidence/moneyflow_evidence_{date}.csv
outputs/moneyflow_evidence/moneyflow_evidence_latest.json
outputs/moneyflow_evidence/moneyflow_evidence_latest.csv
```

---

## 8. 与现有 v1 的差异

| 特性 | v1（blackwolf_actions/） | v2（本规范） |
|------|-------------------------|-------------|
| 评分范围 | 0-5 分（整数） | 0-10 分（浮点） |
| 评分维度 | 单一 confirmation_score | 五维子分加权 |
| 历史分位 | 无 | 60 日百分位 |
| 行业排名 | 无 | 行业内相对排名 |
| 背离检测 | 简化（仅 active_net_5d < 0） | 高位分歧 + 底部吸筹，含 ef_count 门槛 |
| 置信度 | 无 | 多因子置信度 |
| 数据源 | CSV + DuckDB | 优先 DuckDB，CSV 降级 |
| 与 State 对接 | 无 | mf_score 接入 strategy_signal_daily |
| 提醒层 | 无 | mf_label + divergence_alert 展示 |
