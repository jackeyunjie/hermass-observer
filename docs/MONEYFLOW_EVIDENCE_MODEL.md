# 资金流证据层量化模型

版本：v1.0
日期：2026-05-23
状态：设计稿
关联设计：`docs/state_base_extension_design.md` 方向 B（优先级最高）
关联研究：`docs/moneyflow_usage_research.md`

---

## 概述

资金流证据层是 State 底座扩展设计中优先级最高的方向。核心原则：**资金流不改写 State 公式，只做独立证据层增强**。将大单净流入、主力资金方向等信息量化为 0-10 分，与 State 适配度组合展示。

基于 `docs/moneyflow_usage_research.md` 的已验证结论：
- 资金流最稳用法是 State 之后的证据层
- 三周期 E/F 已成立时，资金流同向提高观察优先级
- 价格创新高但大额资金不跟随，标记为高位分歧
- 资金流缺失不等于看空，只标记为数据缺口

---

## 1. 评分公式

### 1.1 总公式

```text
moneyflow_score = clamp(
    0.30 × S_inflow
  + 0.25 × S_consecutive
  + 0.20 × S_divergence
  + 0.15 × S_relative
  + 0.10 × S_coverage,
  0, 10
)
```

### 1.2 分项定义

#### S_inflow：净流入分项（权重 0.30）

```python
def compute_S_inflow(net_inflow_1d: float, net_inflow_5d: float,
                     percentile_60d: float) -> float:
    """基于净流入水平和历史分位。"""
    # 5 日累计净流入的 60 日分位
    if percentile_60d is None:
        return 5.0  # 数据缺失，中性
    return percentile_60d / 10.0  # 分位 70 → 7.0 分
```

| 数据字段 | 来源 | 说明 |
|----------|------|------|
| net_inflow_1d | 当日大单净流入（万元） | 黑狼数据 API |
| net_inflow_5d | 近 5 日累计净流入 | 滚动求和 |
| percentile_60d | 5 日净流入在近 60 日的百分位 | 历史分位 |

#### S_consecutive：连续流入分项（权重 0.25）

```python
def compute_S_consecutive(consecutive_days: int) -> float:
    """基于连续净流入/流出天数。"""
    if consecutive_days >= 5:
        return 9.0  # 连续 5+ 日净流入
    elif consecutive_days >= 3:
        return 7.0  # 连续 3-4 日净流入
    elif consecutive_days >= 1:
        return 5.5  # 近 1-2 日净流入
    elif consecutive_days == 0:
        return 5.0  # 无净流入
    elif consecutive_days >= -2:
        return 4.0  # 近 1-2 日净流出
    elif consecutive_days >= -4:
        return 3.0  # 连续 3-4 日净流出
    else:
        return 1.5  # 连续 5+ 日净流出
```

`consecutive_days` 正值表示连续净流入天数，负值表示连续净流出天数。

#### S_divergence：背离分项（权重 0.20）

```python
def compute_S_divergence(price_new_high: bool, moneyflow_new_high: bool,
                         price_new_low: bool, moneyflow_new_low: bool) -> float:
    """基于价格与资金流的背离。"""
    # 高位背离：价格创新高但资金不跟随
    if price_new_high and not moneyflow_new_high:
        return 2.0  # 高位分歧，风险信号

    # 低位背离：价格创新低但资金流入
    if price_new_low and moneyflow_new_high:
        return 8.0  # 底部吸筹信号

    # 同向
    if price_new_high and moneyflow_new_high:
        return 7.0  # 量价齐升
    if price_new_low and not moneyflow_new_low:
        return 3.0  # 量价齐跌

    return 5.0  # 无明显背离
```

判定标准：

| 条件 | 定义 |
|------|------|
| price_new_high | 当日收盘价为近 20 日最高 |
| moneyflow_new_high | 近 5 日累计净流入为近 60 日最高 |
| price_new_low | 当日收盘价为近 20 日最低 |
| moneyflow_new_low | 近 5 日累计净流出为近 60 日最大 |

#### S_relative：相对强度分项（权重 0.15）

```python
def compute_S_relative(stock_inflow_rank: int, total_stocks: int,
                       industry_inflow_rank: int, industry_size: int) -> float:
    """基于资金流在全市场和行业内的排名。"""
    # 全市场排名分位
    market_pct = (1 - stock_inflow_rank / max(total_stocks, 1)) * 100
    # 行业内排名分位
    industry_pct = (1 - industry_inflow_rank / max(industry_size, 1)) * 100

    # 加权平均
    combined = market_pct * 0.4 + industry_pct * 0.6
    return combined / 10.0  # 转换为 0-10 分
```

#### S_coverage：数据覆盖分项（权重 0.10）

```python
def compute_S_coverage(data_days_available: int, required_days: int = 60) -> float:
    """基于资金流数据的覆盖率。"""
    coverage = min(1.0, data_days_available / required_days)
    if coverage < 0.3:
        return 0.0  # 数据严重不足，不参与评分
    return coverage * 10.0
```

---

## 2. 资金流标签

### 2.1 标签定义

```python
MONEYFLOW_LABELS = {
    (8.0, 10.0): "强势流入",
    (6.5, 8.0):  "温和流入",
    (4.5, 6.5):  "中性",
    (2.5, 4.5):  "温和流出",
    (0.0, 2.5):  "强势流出",
}

def label_moneyflow(score: float) -> str:
    for (lo, hi), label in MONEYFLOW_LABELS.items():
        if lo <= score < hi:
            return label
    return "数据不足"
```

### 2.2 信号方向

```python
def moneyflow_direction(score: float) -> str:
    """资金流对策略信号的方向判定。"""
    if score >= 6.5:
        return "positive"
    elif score <= 3.5:
        return "negative"
    return "neutral"
```

---

## 3. 与 State 底座的组合规则

### 3.1 组合展示

资金流证据层不改变 State 编码，只在展示层组合：

```text
State 组合 + 资金流标签 = 组合展示

示例：E/F/F + 强势流入 → "三周期共振 + 资金面支持"
示例：E/F/F + 温和流入 → "三周期共振 + 资金面中性偏正"
示例：E/F/F + 强势流出 → "三周期共振 + 资金分歧（背离警告）"
```

### 3.2 与适配度的交互

```python
def moneyflow_fit_adjustment(base_fit_score: float, mf_score: float,
                              ef_count: int) -> float:
    """资金流对适配度评分的调节。"""
    mf_dir = moneyflow_direction(mf_score)

    # 仅在 State 强势时（ef_count >= 2）资金流才有调节作用
    if ef_count < 2:
        return base_fit_score  # State 不强时，资金流不调节

    if mf_dir == "positive":
        return min(100, base_fit_score + 5)  # 加成 +5
    elif mf_dir == "negative":
        return max(0, base_fit_score - 8)    # 折扣 -8（资金分歧惩罚更大）
    return base_fit_score
```

**设计理由**：资金流出的惩罚（-8）大于资金流入的加成（+5），因为 `moneyflow_usage_research.md` 指出"背离复核"比"同向增强"更重要。

### 3.3 背离警告

```python
def check_moneyflow_divergence(ef_count: int, mf_direction: str,
                                price_trend: str) -> str | None:
    """检查资金流背离。"""
    if ef_count >= 2 and mf_direction == "negative" and price_trend == "up":
        return "高位分歧：三周期共振成立但资金持续流出，标记为背离复核"

    if ef_count >= 2 and mf_direction == "positive" and price_trend == "down":
        return "底部吸筹：价格回调但资金持续流入，可能存在低估机会"

    return None
```

---

## 4. 数据来源与接入

### 4.1 现有资金流数据

项目已有资金流相关数据：

| 数据 | 路径 | 说明 |
|------|------|------|
| 黑狼资金流 | `data/blackwolf_moneyflow_recent/` | 近期大单净流入 |
| 资金流证据 | `outputs/moneyflow_evidence/` | 已有资金流证据输出 |
| 资金流探测 | `data/moneyflow_probe/` | 资金流 API 探测数据 |

### 4.2 数据字段映射

```python
MONEYFLOW_FIELDS = {
    "net_inflow_1d": "当日大单净流入（万元）",
    "net_inflow_5d": "近5日累计净流入",
    "consecutive_inflow_days": "连续净流入天数（正=流入，负=流出）",
    "percentile_60d": "5日净流入的60日历史分位",
    "price_new_high_20d": "近20日价格是否创新高",
    "moneyflow_new_high_60d": "近5日净流入是否为60日最高",
    "stock_inflow_rank": "全市场资金流排名",
    "industry_inflow_rank": "行业内资金流排名",
    "data_days_available": "可用数据天数",
}
```

### 4.3 数据缺失处理

```python
def moneyflow_score_with_gaps(data: dict) -> tuple[float, float, str]:
    """数据缺失时的降级处理。"""
    coverage = data.get("data_days_available", 0)

    if coverage < 10:
        return 5.0, 0.0, "数据严重不足"  # 中性分数，零置信度
    if coverage < 30:
        score = compute_moneyflow_score(data)
        return score, 0.3, "数据不足，置信度低"
    if coverage < 60:
        score = compute_moneyflow_score(data)
        return score, 0.6, "数据基本充足"

    score = compute_moneyflow_score(data)
    return score, 0.9, "数据充足"
```

---

## 5. 在三重共振中的定位

### 5.1 资金流作为 State 维度的补充

资金流不作为独立的第四共振维度，而是 State 维度的增强信号：

```text
三重共振模型：
  维度 1: 宏观 → macro_factor
  维度 2: 产业链 → chain_factor
  维度 3: State → state_factor × moneyflow_modifier

moneyflow_modifier = 1.0 + (mf_score - 5.0) / 5.0 × 0.10 × confidence
```

范围：0.90-1.10（资金流对共振的调节幅度比 State 本身小）。

### 5.2 资金流在共振等级判定中的作用

```python
def state_direction_with_moneyflow(strategy_id: str, fit_score: float,
                                    mf_score: float, ef_count: int) -> str:
    """资金流调节后的 State 方向判定。"""
    base_dir = state_direction(strategy_id, fit_score)

    # 仅在 State 强势时资金流有影响
    if ef_count < 2:
        return base_dir

    mf_dir = moneyflow_direction(mf_score)

    # 资金流同向：强化
    if base_dir == "positive" and mf_dir == "positive":
        return "positive"  # 强化确认

    # 资金流背离：降级
    if base_dir == "positive" and mf_dir == "negative":
        return "neutral"   # 降级为中性，触发背离警告

    return base_dir
```

---

## 6. 提醒层展示

### 6.1 展示格式

```text
002049 紫光国微 | VCP突破确认 | 最佳适配
  State 环境：E/E/F | 新生
  资金面：7.8/10 | 温和流入 | 连续 3 日净流入
  共振：三重共振 + 资金面支持
```

```text
600519 贵州茅台 | 2560强多头结构 | 适配
  State 环境：E/F/F | 行进
  资金面：3.2/10 | 温和流出 | ⚠ 高位分歧
  共振：双重共振 + 资金分歧（背离警告）
```

### 6.2 背离警告展示

当检测到背离时，在提醒卡片中增加警告标记：

```python
DIVERGENCE_WARNINGS = {
    "high_divergence": "⚠ 高位分歧：价格强势但资金流出，建议复核",
    "low_accumulation": "底部吸筹：价格回调但资金流入，可能存在低估",
}
```

---

## 7. 输出格式

### 7.1 每日输出

```json
// outputs/moneyflow_evidence/moneyflow_evidence_{date}.json
{
  "schema_version": "moneyflow_evidence_v1",
  "date": "2026-05-23",
  "total": 216,
  "coverage_rate": 0.85,
  "rows": [
    {
      "stock_code": "002049",
      "mf_score": 7.8,
      "mf_label": "温和流入",
      "mf_direction": "positive",
      "sub_scores": {
        "inflow": 8.0,
        "consecutive": 7.0,
        "divergence": 7.0,
        "relative": 8.5,
        "coverage": 9.0
      },
      "net_inflow_5d": 12500.5,
      "consecutive_days": 3,
      "divergence_flag": null,
      "confidence": 0.9,
      "data_status": "ok"
    }
  ],
  "divergence_alerts": [
    {"stock_code": "600519", "type": "high_divergence", "mf_score": 3.2}
  ],
  "research_only": true
}
```

### 7.2 与 strategy_signal_daily 的衔接

```sql
ALTER TABLE strategy_signal_daily ADD COLUMN mf_score DOUBLE;
ALTER TABLE strategy_signal_daily ADD COLUMN mf_label VARCHAR DEFAULT '';
ALTER TABLE strategy_signal_daily ADD COLUMN mf_divergence VARCHAR DEFAULT '';
```

---

## 8. 实施路径

### 8.1 阶段 1：数据接入（1-2 天）

```bash
# 接入黑狼资金流数据
python3 scripts/import_moneyflow_data.py --date 2026-05-23

# 验证数据覆盖率
python3 scripts/audit_moneyflow_coverage.py --date 2026-05-23
```

### 8.2 阶段 2：评分计算（1 天）

```bash
# 计算资金流评分
python3 scripts/build_moneyflow_evidence.py --date 2026-05-23
```

### 8.3 阶段 3：信号整合（1 天）

在 `scripts/strategy_signal_ledger.py` 中新增资金流字段。
在 `scripts/strategy_reminder_brief.py` 中新增资金流展示。

### 8.4 阶段 4：校准验证（持续）

用 `forward_observation_ledger` 的数据验证资金流分项与未来收益的相关性。
