# 指数月线 State 宏观环境过滤规则

版本：v1.0
日期：2026-05-24
状态：设计稿
关联白皮书：`docs/MULTICYCLE_STATE_STRATEGY_WHITEPAPER.md`
关联执行规范：`docs/STRATEGY_EXECUTION_SPEC.md`

---

## 核心原则

**以天下观天下**：大盘大周期环境不好时，个股信号再好也要克制。

指数月线 State 反映的是市场整体的大趋势结构。当沪深300月线处于负值区域（下跌趋势/破位）时，说明大环境不支持趋势策略，日线级别应该不交易或少交易。

---

## 1. 三层过滤体系

```text
┌─────────────────────────────────────────────────────┐
│ 大盘层：沪深300 月线 MN1 State                       │
│ → 决定整体仓位上限（0% / 50% / 80% / 100%）          │
├─────────────────────────────────────────────────────┤
│ 行业层：行业 ETF 月线 MN1 State                      │
│ → 决定该行业能否开仓（允许 / 限制 / 禁止）            │
├─────────────────────────────────────────────────────┤
│ 个股层：个股日线 State + 策略信号                     │
│ → 决定是否触发入场                                   │
└─────────────────────────────────────────────────────┘

最终仓位 = 基础仓位 × 大盘系数 × 行业系数
```

### 1.1 大盘层：沪深300 月线 MN1 State

基准标的：沪深300（000300.SH / 510300.SH）

数据来源：`outputs/market_assets_state/market_assets_state_{date}.json` 中 `symbol = "000300.SH"` 的 `mn1_state_hex` 和 `mn1_state_score`。

### 1.2 行业层：行业 ETF 月线 MN1 State

基准标的：`config/industry_rotation_assets.json` 中的行业 ETF 列表。

数据来源：同上，按 `sw_l1` 映射到行业 ETF。

### 1.3 个股层：日线 State + 策略信号

现有逻辑不变。策略信号触发 + 环境适配度 + 流动性过滤。

---

## 2. 大盘层映射规则

### 2.1 沪深300 月线 State → 宏观环境系数

| MN1 State Score | MN1 State Hex | 含义 | 宏观环境系数 | 仓位上限 | 开仓规则 |
|:-:|:-:|---|:-:|:-:|---|
| 14 | E | 扩张+有趋势+突破+稳定 | **1.0** | 100% | 正常开仓 |
| 15 | F | 扩张+有趋势+突破+活跃 | **1.0** | 100% | 正常开仓 |
| 12 | C | 扩张+有趋势+未突破+稳定 | **0.8** | 80% | 正常开仓，仓位减 20% |
| 13 | D | 扩张+有趋势+未突破+活跃 | **0.8** | 80% | 正常开仓，仓位减 20% |
| 10 | A | 扩张+无趋势+突破+稳定 | **0.6** | 60% | 谨慎开仓，只交易最佳适配 |
| 11 | B | 扩张+无趋势+突破+活跃 | **0.6** | 60% | 谨慎开仓，只交易最佳适配 |
| 8 | 8 | 扩张+无趋势+未突破+稳定 | **0.5** | 50% | 只交易最佳适配，仓位减半 |
| 9 | 9 | 扩张+无趋势+未突破+活跃 | **0.5** | 50% | 只交易最佳适配，仓位减半 |
| 4-7 | 4-7 | 收缩+有趋势 | **0.3** | 30% | 只交易三周期共振，仓位降至 30% |
| 0-3 | 0-3 | 收缩+无趋势 | **0.0** | 0% | **不开仓** |
| 负值 | -E, -C 等 | 负向（价格低于月线支撑） | **0.0** | 0% | **不开仓** |

### 2.2 简化版规则（实盘常用）

```python
def macro_coefficient(mn1_state_score: int | None) -> float:
    """大盘层宏观环境系数。"""
    if mn1_state_score is None:
        return 0.5  # 数据缺失，保守处理

    score = abs(mn1_state_score)
    is_negative = mn1_state_score < 0

    # 负向状态：不开仓
    if is_negative:
        return 0.0

    # 收缩态（base=0）
    if score < 8:
        if score >= 4:
            return 0.3  # 收缩有趋势
        return 0.0       # 收缩无趋势

    # 扩张态（base=8）
    trend = (score >> 2) & 1
    position = ((score >> 1) & 1) * 2

    if trend == 1 and position == 2:
        return 1.0       # E/F：扩张+有趋势+突破
    elif trend == 1:
        return 0.8       # C/D：扩张+有趋势+未突破
    elif position == 2:
        return 0.6       # A/B：扩张+无趋势+突破
    else:
        return 0.5       # 8/9：扩张+无趋势+未突破
```

### 2.3 当前市场快照（2026-05-22）

| 指数 | MN1 State | Score | 宏观系数 | 含义 |
|------|-----------|-------|----------|------|
| 沪深300 | **E** | 14 | **1.0** | 扩张+有趋势+突破+稳定 |
| 上证指数 | D | 13 | 0.8 | 扩张+有趋势+未突破+活跃 |
| 中证500 | D | 13 | 0.8 | 扩张+有趋势+未突破+活跃 |
| 中证1000 | D | 13 | 0.8 | 扩张+有趋势+未突破+活跃 |
| 深证成指 | C | 12 | 0.8 | 扩张+有趋势+未突破+稳定 |
| 创业板指 | C | 12 | 0.8 | 扩张+有趋势+未突破+稳定 |

当前大盘层判定：**正常环境**（沪深300 MN1=E，宏观系数 1.0），可正常开仓。

---

## 3. 行业层映射规则

### 3.1 行业 ETF 月线 State → 行业系数

| 行业 ETF MN1 State | 含义 | 行业系数 | 开仓规则 |
|:-:|---|:-:|---|
| E 或 F（正值） | 行业月线扩张+有趋势+突破 | **1.0** | 允许开仓 |
| 8-D（正值，非 E/F） | 行业月线扩张但未达最强 | **0.7** | 允许开仓，仓位减 30% |
| 4-7（正值） | 行业月线收缩有趋势 | **0.3** | 限制开仓，只交易最佳适配 |
| 0-3（正值） | 行业月线收缩无趋势 | **0.0** | 禁止开仓 |
| 负值 | 行业月线破位 | **0.0** | 禁止开仓 |

### 3.2 行业系数计算

```python
def industry_coefficient(etf_mn1_state_score: int | None) -> float:
    """行业层系数。"""
    if etf_mn1_state_score is None:
        return 0.5  # 无 ETF 数据，保守处理

    score = abs(etf_mn1_state_score)
    is_negative = etf_mn1_state_score < 0

    if is_negative:
        return 0.0       # 月线破位

    if score < 8:
        if score >= 4:
            return 0.3   # 收缩有趋势
        return 0.0        # 收缩无趋势

    if score >= 14:
        return 1.0        # E/F
    elif score >= 8:
        return 0.7        # 扩张但非 E/F

    return 0.5
```

### 3.3 行业 ETF 映射

从 `config/industry_rotation_assets.json` 读取行业 ETF 映射：

```python
def get_industry_etf(sw_l1: str, market_assets: list[dict]) -> dict | None:
    """查找行业的 ETF 及其月线 State。"""
    for asset in market_assets:
        if asset.get("asset_type") == "industry_etf" and asset.get("sw_l1") == sw_l1:
            return asset
    return None
```

---

## 4. 综合判定公式

### 4.1 仓位计算

```text
final_position_size = base_position × macro_coefficient × industry_coefficient
```

其中：
- `base_position`：策略信号的基础仓位（由 risk_per_trade 和止损距离计算）
- `macro_coefficient`：大盘层系数（0.0-1.0）
- `industry_coefficient`：行业层系数（0.0-1.0）

### 4.2 开仓判定

```python
def should_open_position(
    signal: dict,
    macro_coeff: float,
    industry_coeff: float,
    current_fit: str,
) -> tuple[bool, str]:
    """综合判定是否允许开仓。"""
    # 大盘层硬性过滤
    if macro_coeff <= 0.0:
        return False, "大盘月线State为负值或收缩无趋势，不开仓"

    # 行业层硬性过滤
    if industry_coeff <= 0.0:
        return False, "行业ETF月线State为负值或收缩无趋势，不开仓"

    # 大盘收缩期（0.3）：只交易最佳适配
    if macro_coeff <= 0.3 and current_fit != "best_fit":
        return False, "大盘收缩期，只交易最佳适配信号"

    # 行业收缩期（0.3）：只交易最佳适配
    if industry_coeff <= 0.3 and current_fit != "best_fit":
        return False, "行业收缩期，只交易最佳适配信号"

    return True, f"允许开仓（大盘系数={macro_coeff}, 行业系数={industry_coeff}）"
```

### 4.3 完整仓位计算

```python
def calculate_filtered_position(
    base_position_size: float,
    macro_coeff: float,
    industry_coeff: float,
) -> float:
    """计算经过宏观环境过滤后的最终仓位。"""
    return base_position_size * macro_coeff * industry_coeff
```

### 4.4 计算示例

```text
场景 1：大盘 E（1.0）× 行业 E（1.0）× 最佳适配
  → 1.0 × 1.0 = 1.0 → 全仓位

场景 2：大盘 E（1.0）× 行业 C（0.7）× 适配
  → 1.0 × 0.7 = 0.7 → 70% 仓位

场景 3：大盘 C（0.8）× 行业 E（1.0）× 最佳适配
  → 0.8 × 1.0 = 0.8 → 80% 仓位

场景 4：大盘 8（0.5）× 行业 D（0.7）× 适配
  → 0.5 × 0.7 = 0.35 → 35% 仓位
  + 大盘 0.5 要求只交易最佳适配 → 如果是"适配"则不开仓

场景 5：大盘 -C（0.0）× 任何
  → 0.0 → 不开仓

场景 6：大盘 E（1.0）× 行业 -E（0.0）
  → 0.0 → 行业破位，不开仓
```

---

## 5. 月度复盘机制

### 5.1 复盘流程

```text
每月第一个交易日：
  1. 读取上月末的指数月线收盘价
  2. 计算沪深300、各行业 ETF 的月线 MN1 State
  3. 更新宏观环境系数和行业系数
  4. 输出月度宏观环境报告
  5. 将系数写入配置文件，供当月日线回测和实盘参考
```

### 5.2 月度报告格式

```markdown
# 月度宏观环境报告 — 2026 年 6 月

## 大盘层
| 指数 | 上月末收盘 | MN1 State | MN1 Score | 宏观系数 |
|------|-----------|-----------|-----------|----------|
| 沪深300 | 4845.10 | E | 14 | **1.0** |
| 上证指数 | 4112.90 | D | 13 | 0.8 |
| 中证1000 | 8692.67 | D | 13 | 0.8 |

**大盘判定：正常环境（沪深300 MN1=E），可正常开仓。**

## 行业层（Top 10）
| 行业 | ETF | MN1 State | 行业系数 | 判定 |
|------|-----|-----------|----------|------|
| 电子 | 512480.SH | E | 1.0 | 允许 |
| 汽车 | 515700.SH | C | 0.7 | 允许，减仓 |
| 食品饮料 | 159928.SZ | -C | 0.0 | 禁止 |

## 当月开仓规则
- 大盘系数：1.0（正常开仓）
- 限制行业：食品饮料、房地产（月线破位）
- 总仓位上限：100%
```

### 5.3 自动化脚本

```bash
# 月初运行
python3 scripts/build_macro_env_filter.py --month 2026-06

# 输出
outputs/macro_env/macro_env_filter_202606.json
outputs/macro_env/macro_env_filter_202606.md
```

### 5.4 配置文件输出

```json
// config/macro_env_filter_current.json
{
  "schema_version": "macro_env_filter_v1",
  "month": "2026-06",
  "generated_at": "2026-06-02T09:00:00+00:00",
  "macro_coefficient": 1.0,
  "index_state": {
    "symbol": "000300.SH",
    "name": "沪深300",
    "mn1_state_hex": "E",
    "mn1_state_score": 14
  },
  "industry_coefficients": {
    "电子": {"etf": "512480.SH", "mn1_hex": "E", "coefficient": 1.0},
    "汽车": {"etf": "515700.SH", "mn1_hex": "C", "coefficient": 0.7},
    "食品饮料": {"etf": "159928.SZ", "mn1_hex": "-C", "coefficient": 0.0}
  },
  "rules": {
    "macro_coeff_le_0": "不开仓",
    "macro_coeff_le_0_3": "只交易最佳适配",
    "industry_coeff_le_0": "该行业不开仓",
    "industry_coeff_le_0_3": "该行业只交易最佳适配"
  },
  "research_only": true
}
```

---

## 6. 与回测脚本的对接

### 6.1 在 us_strategy_backtest.py 中的集成

```python
# 在入场判定前加载宏观环境系数
macro_env = load_json(CONFIG_DIR / "macro_env_filter_current.json")
macro_coeff = macro_env.get("macro_coefficient", 1.0)

# 在入场循环中
for sig in entry_signals:
    industry = get_industry(sig["stock_code"])
    industry_coeff = macro_env.get("industry_coefficients", {}).get(industry, {}).get("coefficient", 0.5)

    can_open, reason = should_open_position(sig, macro_coeff, industry_coeff, fit)
    if not can_open:
        continue

    # 仓位经过宏观过滤
    final_size = calculate_filtered_position(base_size, macro_coeff, industry_coeff)
```

### 6.2 在 A 股策略信号账本中的集成

在 `scripts/strategy_signal_ledger.py` 的信号行中新增：

```python
signal_row["macro_coefficient"] = macro_coeff
signal_row["industry_coefficient"] = industry_coeff
signal_row["macro_filtered"] = macro_coeff < 1.0 or industry_coeff < 1.0
```

---

## 7. 历史回测对比

### 7.1 对比维度

| 测试 | 内容 | 预期差异 |
|------|------|----------|
| 无过滤 vs 大盘过滤 | 仅加入沪深300 MN1 State 过滤 | 回撤降低，收益可能略降 |
| 大盘过滤 vs 大盘+行业过滤 | 加入行业 ETF MN1 State 过滤 | 进一步降低行业集中风险 |
| 2022 年熊市对比 | 2022 年沪深300 MN1 State 长期为负 | 过滤版应大幅减少亏损 |

### 7.2 预期效果

| 场景 | 无过滤 | 有宏观过滤 | 预期改善 |
|------|--------|-----------|---------|
| 2022 年熊市 | 满仓运行，频繁止损 | 大盘系数 0.0-0.3，不开仓或极轻仓 | 回撤降低 10-20pp |
| 2023 年牛市 | 正常开仓 | 大盘系数 0.8-1.0，正常开仓 | 收益略降（过滤掉部分信号） |
| 行业轮动期 | 所有行业等权 | 弱势行业被过滤 | 行业集中度降低 |

---

## 8. 合规声明

本规则属于系统内部的宏观环境过滤机制，用于控制整体风险暴露。

- 本规则不构成对外投资建议。
- 宏观环境系数基于历史 State 数据计算，不代表未来市场走势。
- 行业系数基于 ETF 月线 State，不等于行业基本面判断。
- 所有投资决策应由投资者独立做出。

---

## 附录：A 股指数月线 State 速查

| 指数 | 代码 | 当前 MN1 State | 当前宏观系数 |
|------|------|---------------|-------------|
| 沪深300 | 000300.SH | E (14) | 1.0 |
| 上证指数 | 000001.SH | D (13) | 0.8 |
| 深证成指 | 399001.SZ | C (12) | 0.8 |
| 创业板指 | 399006.SZ | C (12) | 0.8 |
| 中证500 | 000905.SH | D (13) | 0.8 |
| 中证1000 | 000852.SH | D (13) | 0.8 |

数据截止：2026-05-22
