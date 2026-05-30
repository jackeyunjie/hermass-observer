# External Research Response Evidence Contract

版本：v1.0
日期：2026-05-28
状态：设计稿
定位：AI 助手公司研究回答的结构化证据合同

---

## 1. 目标与适用范围

### 1.1 本合同服务什么

本合同定义 AI 助手回答公司研究问题时使用的**结构化证据对象（Evidence Payload）**。它是以下三类产物的共享数据底座：

| 产物 | 场景 | 消费方式 |
|------|------|----------|
| 快速问答卡 | 飞书/钉钉群聊 | evidence → quick_formatter → Markdown |
| 深度研究卡 | 用户追问 | evidence → deep_formatter → Markdown |
| 证据卡 | 兜底可信度 | evidence → evidence_formatter → Markdown |

### 1.2 本合同不服务什么

- 不服务于传统的 10000 字投资价值分析报告
- 不生成买入/卖出/推荐等投资建议
- 不包含估值区间计算和投资结论
- 不涉及 MT5/美股/Alpaca 相关数据

### 1.3 适用架构

```
Layer 1: 数据采集层
  ifind_fundamental_collector.py / akshare_batch_collect.py
  foundation DB / industry_position / market_assets_state
       ↓
Layer 2: Evidence Builder（本合同定义的输出）
  research_evidence_builder.py（待实现）
       ↓
Layer 3: Response Composer
  quick_formatter / deep_formatter / evidence_formatter
       ↓
Layer 4: API / Bot
  a_share_service.py / lark_handler.py
```

---

## 2. 设计原则

| 原则 | 含义 |
|------|------|
| **Evidence First** | 先组装结构化证据，再让 formatter 组织语言。不从回答模板反推字段。 |
| **Structured Completeness** | 数据充分度是结构化规则产物，不是模型自由判断。 |
| **One Evidence, Multiple Formatters** | 三类卡片消费同一份 evidence payload，只是 formatter 不同。 |
| **A-Share Only** | 所有数据源限定 A 股，不引入美股/港股/加密货币。 |
| **Research Only** | 所有输出标注 research_only=true，不构成投资建议。 |
| **Source Traceable** | 每个数值字段绑定 source_map，可追溯到具体数据源和报告期。 |
| **Source Tiered** | source_map 除 source_type 外，还要记录 source_tier；默认优先 tier_1_core / tier_2_high。 |
| **Raw vs Derived** | 区分原始证据（从数据源直接读取）和派生证据（由规则计算），便于审计。 |

---

## 3. 顶层 Schema

```json
{
  "contract_version": "evidence_v1",
  "meta": { ... },
  "company_profile": { ... },
  "financial_trend": { ... },
  "industry_state": { ... },
  "state_core": { ... },
  "strategy_fit_overlay": { ... },
  "valuation_reference": { ... },
  "market_views": { ... },
  "risk_flags": { ... },
  "source_map": { ... },
  "completeness": { ... }
}
```

### 顶层对象职责

| 对象 | 职责 | Required | 允许 Missing |
|------|------|----------|-------------|
| `meta` | 元信息：股票代码、生成时间、版本 | 是 | 否 |
| `company_profile` | 公司概况：主营、行业、产品 | 是 | 否 |
| `financial_trend` | 财务趋势：营收/利润/EPS/ROE 近 3 年 | 是 | 部分字段允许 |
| `industry_state` | 行业景气：景气度、ETF State、板块共振 | 是 | 允许（覆盖率有限） |
| `state_core` | State 核心环境：三周期 State、ef_count、市场阶段 | 是 | 否 |
| `strategy_fit_overlay` | 策略适配叠加层：生命周期、适配度、适配策略 | 否 | 允许 |
| `valuation_reference` | 估值参考：PE/PB、可比公司 | 否 | 允许（待 iFinD 补全） |
| `market_views` | 市场观点：券商评级、目标价 | 否 | 允许（覆盖率有限） |
| `risk_flags` | 风险提示：财务/行业/估值/政策风险 | 是 | 否 |
| `source_map` | 来源映射：每个字段的数据来源 | 是 | 否 |
| `completeness` | 数据充分度：每个模块的状态 | 是 | 否 |

---

## 4. 模块级 Schema

### 4.1 company_profile（公司概况）

```json
{
  "stock_code": "002049.SZ",
  "stock_name": "紫光国微",
  "sw_l1": "电子",
  "sw_l2": "半导体",
  "sw_l3": "集成电路设计",
  "main_business": "集成电路设计，特种芯片+智能安全芯片",
  "main_product_types": "智能安全芯片、特种集成电路",
  "main_product_names": "智能安全芯片、特种集成电路",
  "comparable_companies": "兆易创新、北京君正、景嘉微",
  "competitor_companies": "兆易创新、北京君正",
  "ths_concepts": "半导体、芯片、国产替代"
}
```

| 字段 | 类型 | Required | 来源 |
|------|------|----------|------|
| stock_code | string | 是 | 输入参数 |
| stock_name | string | 是 | ifind_industry_chain_profile |
| sw_l1/l2/l3 | string | 是 | ifind_industry_chain_profile |
| main_business | string | 是 | ifind_industry_chain_profile |
| main_product_types | string | 否 | ifind_industry_chain_profile |
| main_product_names | string | 否 | ifind_industry_chain_profile |
| comparable_companies | string | 否 | ifind_industry_chain_profile |
| competitor_companies | string | 否 | ifind_industry_chain_profile |
| ths_concepts | string | 否 | ifind_industry_chain_profile |

**充分度规则**：stock_code + stock_name + sw_l1 + main_business 全部非空 → sufficient；缺 main_business → partial；缺 sw_l1 → missing。

### 4.2 financial_trend（财务趋势）

```json
{
  "period_rows": [
    {
      "report_period": "2022Q4",
      "revenue": 65.2,
      "net_profit": 19.5,
      "eps": 2.39,
      "roe": 18.2,
      "gross_margin": 65.7,
      "debt_ratio": 37.2,
      "operating_cashflow": 15.2,
      "source": {"source_type": "ifind", "source_table": "ifind_excel_facts", "updated_at": "2026-05-21"},
      "report_period_consistency": true
    },
    {
      "report_period": "2023Q4",
      "revenue": 72.8,
      "net_profit": 22.1,
      "eps": 2.62,
      "roe": 19.1,
      "gross_margin": 63.8,
      "debt_ratio": 36.4,
      "operating_cashflow": 18.5,
      "source": {"source_type": "ifind", "source_table": "ifind_excel_facts", "updated_at": "2026-05-21"},
      "report_period_consistency": true
    },
    {
      "report_period": "2024Q4",
      "revenue": 75.2,
      "net_profit": 21.8,
      "eps": 2.58,
      "roe": 17.8,
      "gross_margin": 62.9,
      "debt_ratio": 38.1,
      "operating_cashflow": 16.8,
      "source": {"source_type": "ifind", "source_table": "ifind_excel_facts", "updated_at": "2026-05-21"},
      "report_period_consistency": true
    }
  ],
  "latest_report_period": "2024Q4",
  "period_count": 3,
  "revenue_yoy": [12.3, 11.7, 3.3],
  "data_type": "raw"
}
```

**结构说明**：时间序列改为对象数组（`period_rows`），每个 period 独立记录 report_period 和 source，支持逐期追溯和混期检测。

**权威追溯规则**：

- `period_rows[].source` 是内联摘要，便于 formatter 和调试快速查看。
- **权威追溯来源始终是 `source_map` 的逐期 key**。
- 当两者不一致时，以 `source_map` 为准。

| 字段 | 类型 | Required | 说明 |
|------|------|----------|------|
| period_rows | object[] | 是 | 每期独立对象 |
| period_rows[].report_period | string | 是 | 报告期（如 "2024Q4"） |
| period_rows[].revenue | float | 是 | 营业总收入 |
| period_rows[].net_profit | float | 是 | 净利润 |
| period_rows[].eps | float | 是 | 基本每股收益 |
| period_rows[].roe | float | 否 | ROE |
| period_rows[].gross_margin | float | 否 | 毛利率 |
| period_rows[].debt_ratio | float | 否 | 资产负债率 |
| period_rows[].source | object | 是 | 该期数据来源 |
| period_rows[].report_period_consistency | bool | 是 | 该期各指标是否来自同一报告期 |
| latest_report_period | string | 是 | 最新报告期 |
| period_count | int | 是 | 有效期数 |
| revenue_yoy | float[] | 否 | derived：逐期同比增速 |
| data_type | string | 是 | "raw" 或 "estimated" |

**report_period_consistency 规则**：

```python
def check_period_consistency(period_row: dict) -> bool:
    """检查同一行的各指标是否来自同一报告期。"""
    # 如果所有指标都来自同一 source + 同一 report_period → True
    # 如果 revenue 来自 2024Q4 但 eps 来自 2024Q3 → False（混期）
    return period_row.get("report_period_consistency", False)
```

**充分度规则**：
- sufficient：period_rows 有 >= 3 期 + 所有期 report_period_consistency=true + latest_report_period 非空
- partial：有 1-2 期，或有混期标记
- missing：period_rows 为空

### 4.3 industry_state（行业景气）

```json
{
  "sw_l1": "电子",
  "prosperity_score": 8.2,
  "prosperity_change": "improving",
  "chain_position": "综合",
  "etf_symbol": "512480.SH",
  "etf_state_hex": "E",
  "etf_ef_count": 2,
  "etf_20d_return": 8.5,
  "sector_resonance": true,
  "sector_resonance_count": 22
}
```

| 字段 | 类型 | Required | 来源 | raw/derived |
|------|------|----------|------|-------------|
| sw_l1 | string | 是 | 输入参数 | — |
| prosperity_score | float | 否 | industry_position（待填充） | raw |
| prosperity_change | string | 否 | industry_position | raw |
| chain_position | string | 否 | industry_position | raw |
| etf_symbol | string | 否 | industry_rotation_assets.json | raw |
| etf_state_hex | string | 否 | market_assets_state | raw |
| etf_ef_count | int | 否 | market_assets_state | raw |
| etf_20d_return | float | 否 | market_assets_state | derived |
| sector_resonance | bool | 否 | detect_sector_resonance() | derived |
| sector_resonance_count | int | 否 | detect_sector_resonance() | derived |

**充分度规则（阶段化）**：

Phase 1（当前，industry_position 待填充）：
- sufficient：etf_state_hex + etf_ef_count 非空（ETF State 已有数据）
- partial：只有 sw_l1 行业归属，缺 ETF State
- missing：sw_l1 都为空

Phase 2（industry_position 稳定后）：
- sufficient：etf_state_hex + etf_ef_count + prosperity_score 全部非空
- partial：有 ETF State 但缺 prosperity_score
- missing：ETF State 和 prosperity_score 都为空

**Phase 1 的合理性**：ETF State 已覆盖 31 个行业，ef_count + 20d 收益已能反映行业强弱。prosperity_score 是更高精度的补充，不是 Phase 1 的必要条件。

### 4.4 state_environment（State 环境，拆分为 state_core + strategy_fit_overlay）

**关键设计**：拆为 `state_core`（Foundation 层，稳定可得）和 `strategy_fit_overlay`（信号账本层，optional）。

#### state_core（required）

```json
{
  "mn1_state_hex": "E",
  "w1_state_hex": "E",
  "d1_state_hex": "E",
  "mn1_state_score": 14,
  "w1_state_score": 14,
  "d1_state_score": 14,
  "ef_count": 3,
  "market_phase": "progression"
}
```

| 字段 | 类型 | Required | 来源 |
|------|------|----------|------|
| mn1/w1/d1_state_hex | string | 是 | d1_perspective_state |
| mn1/w1/d1_state_score | int | 是 | d1_perspective_state |
| ef_count | int | 是 | d1_perspective_state |
| market_phase | string | 否 | classify_market_phase |

**state_core 充分度规则**：
- sufficient：mn1 + w1 + d1 三个 state_hex 全部非空
- partial：缺 1 个周期
- missing：三个全空

#### strategy_fit_overlay（optional）

```json
{
  "lifecycle_stage": "新生",
  "strategy_environment_fit": "最佳适配",
  "fit_strategy": "vcp",
  "env_category": "strong_resonance"
}
```

| 字段 | 类型 | Required | 来源 |
|------|------|----------|------|
| lifecycle_stage | string | 否 | strategy_signal_ledger（需 ef_count >= 2） |
| strategy_environment_fit | string | 否 | strategy_signal_ledger |
| fit_strategy | string | 否 | strategy_signal_ledger |
| env_category | string | 否 | signal_noise_filter |

**strategy_fit_overlay 缺失时的行为**：
- 快速问答卡：省略"策略适配"行，只展示 State 环境
- 深度研究卡：标注"该标的当前无策略信号覆盖"
- 证据卡：strategy_fit_overlay 状态标记为 "not_available"

**overlay 缺失不影响 state_core 的充分度判定。**

### 4.5 valuation_reference（估值参考）

```json
{
  "pe_ttm": 35.2,
  "pe_static": 38.1,
  "pb": 5.8,
  "ps": 12.5,
  "market_cap": 850.5,
  "industry_pe_avg": 42.3,
  "comparable_pe_range": [28.5, 55.2],
  "data_type": "reference"
}
```

| 字段 | 类型 | Required | 来源 |
|------|------|----------|------|
| pe_ttm | float | 否 | stock_value (AKShare) |
| pe_static | float | 否 | stock_value (AKShare) |
| pb | float | 否 | stock_value (AKShare) |
| market_cap | float | 否 | stock_value (AKShare) |
| industry_pe_avg | float | 否 | stock_industry_pe_ratio (AKShare) |
| comparable_pe_range | float[] | 否 | derived |

**充分度规则**：
- sufficient：pe_ttm + pb 非空 + industry_pe_avg 非空
- partial：有 pe_ttm 但缺 industry_pe_avg
- missing：pe_ttm 和 pb 都为空

### 4.6 market_views（市场观点）

```json
{
  "rating_distribution": {"买入": 3, "增持": 5, "中性": 1},
  "target_price_low": 85.0,
  "target_price_high": 120.0,
  "target_price_count": 8,
  "latest_report": {
    "institution": "华泰证券",
    "date": "2026-05-15",
    "rating": "买入",
    "target_price": 105.0
  }
}
```

**充分度规则**：
- sufficient：rating_distribution 非空 + latest_report 非空
- partial：有 rating_distribution 但缺 latest_report
- missing：rating_distribution 为空

### 4.7 risk_flags（风险提示）

```json
{
  "financial_risks": ["资产负债率 38.1%，处于行业正常水平"],
  "industry_risks": ["特种芯片需求受国防预算影响", "行业周期性波动"],
  "valuation_risks": ["PE 35.2 处于近 3 年 65% 分位"],
  "policy_risks": [],
  "data_risks": ["估值数据来源为 AKShare，非 iFinD"]
}
```

**充分度规则**：
- sufficient：至少有 financial_risks 或 industry_risks 非空
- partial：只有 data_risks
- missing：所有风险列表为空

---

## 5. Source Map 规范

### 5.1 source_map 结构

```json
{
  "source_map": {
    "company_profile.main_business": {
      "source_type": "ifind",
      "source_tier": "tier_2_high",
      "source_table": "ifind_industry_chain_profile",
      "source_field": "main_business",
      "report_period": null,
      "updated_at": "2026-05-21",
      "source_confidence": 0.95
    },
    "financial_trend.period_rows[2024Q4].revenue": {
      "source_type": "ifind",
      "source_tier": "tier_2_high",
      "source_table": "ifind_excel_facts",
      "source_field": "营业总收入",
      "report_period": "2024Q4",
      "updated_at": "2026-05-21",
      "source_confidence": 0.95
    },
    "valuation_reference.pe_ttm": {
      "source_type": "akshare",
      "source_tier": "tier_2_high",
      "source_table": "stock_value",
      "source_field": "PE(TTM)",
      "report_period": null,
      "updated_at": "2026-05-28",
      "source_confidence": 0.85
    },
    "state_core.d1_state_hex": {
      "source_type": "foundation",
      "source_tier": "tier_1_core",
      "source_table": "d1_perspective_state",
      "source_field": "d1_state_hex",
      "report_period": null,
      "updated_at": "2026-05-27",
      "source_confidence": 1.0
    },
    "financial_trend.period_rows[2024Q4].revenue_yoy": {
      "source_type": "derived",
      "source_tier": "tier_derived",
      "source_table": null,
      "source_field": null,
      "report_period": "2024Q4",
      "updated_at": "2026-05-28",
      "source_confidence": 0.9,
      "derivation": "revenue[i] / revenue[i-1] - 1"
    }
  }
}
```

### 5.2 source_type 枚举

| source_type | 含义 | 典型来源 | confidence 默认值 |
|------------|------|----------|-----------------|
| `ifind` | iFinD 数据 | ifind_excel_facts, ifind_industry_chain_profile | 0.95 |
| `akshare` | AKShare 数据 | stock_value, stock_financial_analysis_indicator | 0.85 |
| `foundation` | State 底座 | d1_perspective_state | 1.0 |
| `derived` | 派生计算 | 由 raw 字段计算得出 | 0.9 |
| `manual` | 人工输入 | 用户提供的数据 | 0.7 |

### 5.2.1 source_tier 枚举

| source_tier | 含义 | 默认用途 |
|------------|------|---------|
| `tier_1_core` | 核心可信来源 | 默认优先进入研究结论 |
| `tier_2_high` | 高可信结构化来源 | 默认允许进入研究结论 |
| `tier_3_general` | 一般公开资料 | 只作补充，不单独支撑结论 |
| `tier_derived` | 规则派生结果 | 必须可追溯到上游结构化来源 |

### 5.3 source_map 最小字段集合

每个数值字段的 source_map 必须包含：

| 字段 | 必填 | 说明 |
|------|------|------|
| source_type | 是 | 五选一 |
| source_tier | 是 | 四选一 |
| source_table | 否 | derived 时可为空 |
| source_field | 否 | derived 时可为空 |
| report_period | 否 | 财务数据必须填 |
| updated_at | 是 | ISO 日期 |
| source_confidence | 是 | 0-1 |
| derivation | 否 | derived 时必须填 |

### 5.4 时间序列字段命名规范

`financial_trend` 这类多期字段，`source_map` 必须使用逐期 key，不允许只写聚合路径。

默认研究回答链还必须遵守以下信源边界：

- 禁止使用 `guba / 股吧 / 自媒体 / 营销号 / weibo / zhihu / 据传 / 爆料` 等模式作为证据来源
- 如果运行时存在这类输入，只能作为噪音过滤对象，不得写入 `source_map`
- formatter 可以展示 `source_tier` 或 `source_policy` 摘要，但不得将禁用信源重新转述为事实

推荐格式：

```text
financial_trend.period_rows[2024Q4].revenue
financial_trend.period_rows[2024Q4].net_profit
financial_trend.period_rows[2024Q4].eps
financial_trend.period_rows[2024Q4].revenue_yoy
```

禁止格式：

```text
financial_trend.revenue
financial_trend.net_profit
financial_trend.eps
```

原因：

- 聚合 key 无法表达逐期来源
- 无法检查 mixed-period
- 无法判断 latest_report_period 是否与各字段一致

---

## 6. 数据充分度规则

### 6.1 模块级充分度

| 模块 | sufficient 条件 | partial 条件 | missing 条件 |
|------|----------------|-------------|-------------|
| company_profile | stock_code + name + sw_l1 + main_business 全非空 | 缺 main_business | 缺 sw_l1 |
| financial_trend | period_rows >= 3 期 + 全部 consistency=true | 有 1-2 期或有混期 | period_rows 为空 |
| industry_state (Phase 1) | etf_state_hex + ef_count 非空 | 只有 sw_l1 行业归属 | sw_l1 为空 |
| state_core | mn1 + w1 + d1 state_hex 全非空 | 缺 1 个周期 | 三个全空 |
| strategy_fit_overlay | 不参与整体充分度 | — | — |
| valuation_reference | pe_ttm + pb 非空 + industry_pe_avg 非空 | 有 pe 但缺行业均值 | pe 和 pb 都空 |
| market_views | rating_distribution + latest_report 非空 | 有评级但缺最新研报 | 评级分布为空 |
| risk_flags | financial_risks 或 industry_risks 非空 | 只有 data_risks | 所有列表为空 |

### 6.2 整体充分度

**关键设计**：required 模块和 optional 模块分开计算，optional 模块缺失不拖垮整体。

```python
REQUIRED_MODULES = {
    "company_profile": 0.15,
    "financial_trend": 0.30,
    "industry_state": 0.15,
    "state_core": 0.30,
    "risk_flags": 0.10,
}

OPTIONAL_MODULES = {
    "valuation_reference": 0.50,
    "market_views": 0.50,
}

def compute_overall_completeness(completeness: dict) -> dict:
    """
    整体充分度 = required_modules_score + optional_modules_bonus。

    required 模块单独评分（0-1），optional 模块单独评分（0-1）。
    整体分数 = required_score × 0.85 + optional_score × 0.15
    """
    score_map = {"sufficient": 1.0, "partial": 0.5, "missing": 0.0}

    # Required 模块评分
    required_total = 0.0
    for mod, weight in REQUIRED_MODULES.items():
        required_total += weight * score_map.get(completeness.get(mod, "missing"), 0)

    # Optional 模块评分（缺失时按 0.5 基线计算，而非 0）
    optional_total = 0.0
    optional_count = 0
    for mod, weight in OPTIONAL_MODULES.items():
        status = completeness.get(mod)
        if status is not None:  # 模块已启用
            optional_total += weight * score_map.get(status, 0)
            optional_count += 1
        else:  # 模块未启用
            optional_total += weight * 0.5  # 基线分
            optional_count += 1

    # 整体 = required × 0.85 + optional × 0.15
    overall = required_total * 0.85 + optional_total * 0.15

    if overall >= 0.75:
        label = "sufficient"
    elif overall >= 0.40:
        label = "partial"
    else:
        label = "missing"

    return {
        "required_modules_score": round(required_total, 3),
        "optional_modules_score": round(optional_total, 3),
        "overall_score": round(overall, 3),
        "overall": label,
    }
```

**效果**：核心事实层完整但缺估值/券商观点的公司，required_score 可达 0.9+，overall 仍为 "sufficient"。

---

## 7. Partial / Missing 行为规则

### 7.1 sufficient 时

回答层可以正常使用该模块数据，标注来源和报告期。

### 7.2 partial 时

```text
必须：
  - 在回答中显式提示该模块数据不完整
  - 标注缺失的具体字段
  - 结论降级为"参考"级别

示例：
  "财务趋势（部分数据）：营收和 EPS 有近 2 年数据，最新季度数据待补。"
  "估值参考（部分数据）：有 PE 数据但缺行业均值对比。"
```

### 7.3 missing 时

```text
必须：
  - 不生成该模块的任何结论
  - 只输出缺失说明
  - 不用默认值或模型推测填充

示例：
  "行业景气度数据暂缺，无法给出行业环境判断。"
  "估值数据暂缺，无法给出估值参考。"
```

### 7.4 行为规则表

| 充分度 | 快速问答卡 | 深度研究卡 | 证据卡 |
|--------|-----------|-----------|--------|
| sufficient | 正常展示 | 正常展开 | 标注来源 |
| partial | 标注"部分数据" | 展开但标注局限 | 详细列出缺失字段 |
| missing | 输出"暂无数据" | 跳过该模块 | 列出缺失原因 |

---

## 8. 三类卡片共享字段

### 8.1 共享字段（三者必须有）

```json
{
  "stock_code": "002049.SZ",
  "stock_name": "紫光国微",
  "report_date": "2026-05-28",
  "latest_report_period": "2024Q4",
  "overall_completeness": "partial",
  "major_risks": ["特种芯片需求受国防预算影响"],
  "source_summary": "iFinD + AKShare + State 底座",
  "disclaimer": "以上为基于公开数据的研究观察，不构成投资建议。"
}
```

### 8.2 快速问答卡扩展字段

```json
{
  "main_business_short": "集成电路设计",
  "state_combo": "E/E/E",
  "ef_count": 3,
  "prosperity_score": 8.2,
  "fit_strategy": "vcp",
  "fit_level": "最佳适配",
  "eps_latest": 2.39,
  "roe_latest": 18.2,
  "pe_ttm": 35.2,
  "top_risk": "特种芯片需求受国防预算影响"
}
```

### 8.3 深度研究卡扩展字段

```json
{
  "financial_trend": { "revenue": [...], "eps": [...], ... },
  "industry_analysis": { "prosperity_score": 8.2, "etf_state": "E", ... },
  "competitive_advantage": { "comparable_companies": "...", ... },
  "valuation_detail": { "pe_ttm": 35.2, "industry_pe_avg": 42.3, ... },
  "market_views_detail": { "rating_distribution": {...}, ... },
  "risk_detail": { "financial_risks": [...], "industry_risks": [...] }
}
```

### 8.4 证据卡扩展字段

```json
{
  "source_map": { ... },
  "completeness_detail": {
    "company_profile": "sufficient",
    "financial_trend": "partial",
    "industry_state": "partial",
    "state_core": "sufficient",
    "strategy_fit_overlay": "partial",
    "valuation_reference": "partial",
    "market_views": "missing",
    "risk_flags": "sufficient"
  },
  "cross_validation": {
    "pe_source_agreement": true,
    "financial_period_consistency": true
  },
  "last_update": "2026-05-28T07:30:00+08:00"
}
```

---

## 9. 示例 Payload

```json
{
  "contract_version": "evidence_v1",
  "meta": {
    "stock_code": "002049.SZ",
    "stock_name": "紫光国微",
    "generated_at": "2026-05-28T07:30:00+08:00",
    "research_only": true
  },
  "company_profile": {
    "stock_code": "002049.SZ",
    "stock_name": "紫光国微",
    "sw_l1": "电子",
    "sw_l2": "半导体",
    "sw_l3": "集成电路设计",
    "main_business": "集成电路设计，特种芯片+智能安全芯片",
    "comparable_companies": "兆易创新、北京君正、景嘉微",
    "ths_concepts": "半导体、芯片、国产替代"
  },
  "financial_trend": {
    "period_rows": [
      {"report_period": "2022Q4", "revenue": 65.2, "net_profit": 19.5, "eps": 2.39, "roe": 18.2, "gross_margin": 65.7, "debt_ratio": 37.2, "source": {"source_type": "ifind", "updated_at": "2026-05-21"}, "report_period_consistency": true},
      {"report_period": "2023Q4", "revenue": 72.8, "net_profit": 22.1, "eps": 2.62, "roe": 19.1, "gross_margin": 63.8, "debt_ratio": 36.4, "source": {"source_type": "ifind", "updated_at": "2026-05-21"}, "report_period_consistency": true},
      {"report_period": "2024Q4", "revenue": 75.2, "net_profit": 21.8, "eps": 2.58, "roe": 17.8, "gross_margin": 62.9, "debt_ratio": 38.1, "source": {"source_type": "ifind", "updated_at": "2026-05-21"}, "report_period_consistency": true}
    ],
    "latest_report_period": "2024Q4",
    "period_count": 3,
    "revenue_yoy": [12.3, 11.7, 3.3],
    "data_type": "raw"
  },
  "industry_state": {
    "sw_l1": "电子",
    "prosperity_score": 8.2,
    "prosperity_change": "improving",
    "chain_position": "综合",
    "etf_symbol": "512480.SH",
    "etf_state_hex": "E",
    "etf_ef_count": 2,
    "etf_20d_return": 8.5,
    "sector_resonance": true,
    "sector_resonance_count": 22
  },
  "state_core": {
    "mn1_state_hex": "E", "w1_state_hex": "E", "d1_state_hex": "E",
    "mn1_state_score": 14, "w1_state_score": 14, "d1_state_score": 14,
    "ef_count": 3,
    "market_phase": "progression"
  },
  "strategy_fit_overlay": {
    "lifecycle_stage": "新生",
    "strategy_environment_fit": "最佳适配",
    "fit_strategy": "vcp",
    "env_category": "strong_resonance"
  },
  "valuation_reference": {
    "pe_ttm": 35.2,
    "pb": 5.8,
    "market_cap": 850.5,
    "industry_pe_avg": 42.3,
    "data_type": "reference"
  },
  "market_views": {
    "rating_distribution": {"买入": 3, "增持": 5, "中性": 1},
    "target_price_low": 85.0,
    "target_price_high": 120.0,
    "target_price_count": 8,
    "latest_report": {
      "institution": "华泰证券",
      "date": "2026-05-15",
      "rating": "买入",
      "target_price": 105.0
    }
  },
  "risk_flags": {
    "financial_risks": ["资产负债率 38.1%，处于行业正常水平"],
    "industry_risks": ["特种芯片需求受国防预算影响", "行业周期性波动"],
    "valuation_risks": ["PE 35.2 处于近 3 年 65% 分位"],
    "policy_risks": [],
    "data_risks": ["估值数据来源为 AKShare，非 iFinD"]
  },
  "source_map": {
    "company_profile.main_business": {
      "source_type": "ifind",
      "source_table": "ifind_industry_chain_profile",
      "source_field": "main_business",
      "updated_at": "2026-05-21",
      "source_confidence": 0.95
    },
    "financial_trend.period_rows[2024Q4].revenue": {
      "source_type": "ifind",
      "source_table": "ifind_excel_facts",
      "source_field": "营业总收入",
      "report_period": "2024Q4",
      "updated_at": "2026-05-21",
      "source_confidence": 0.95
    },
    "valuation_reference.pe_ttm": {
      "source_type": "akshare",
      "source_table": "stock_value",
      "source_field": "PE(TTM)",
      "updated_at": "2026-05-28",
      "source_confidence": 0.85
    },
    "state_core.d1_state_hex": {
      "source_type": "foundation",
      "source_table": "d1_perspective_state",
      "source_field": "d1_state_hex",
      "updated_at": "2026-05-27",
      "source_confidence": 1.0
    }
  },
  "completeness": {
    "company_profile": "sufficient",
    "financial_trend": "sufficient",
    "industry_state": "sufficient",
    "state_core": "sufficient",
    "strategy_fit_overlay": "sufficient",
    "valuation_reference": "partial",
    "market_views": "sufficient",
    "risk_flags": "sufficient",
    "required_modules_score": 0.92,
    "optional_modules_score": 0.75,
    "overall_score": 0.90,
    "overall": "sufficient"
  }
}
```

---

## 10. Phase 1 实现边界

### 10.1 要做什么

| 模块 | Phase 1 范围 |
|------|-------------|
| company_profile | 完整实现（ifind_industry_chain_profile 已有 5522 只） |
| financial_trend | 核心字段（revenue/net_profit/eps/roe/gross_margin/debt_ratio），来源 ifind_excel_facts + AKShare |
| industry_state | ETF State + 板块共振（已有），prosperity_score 待产业链数据补全 |
| state_core | 完整实现（p116_foundation 已有） |
| strategy_fit_overlay | 条件实现（依赖 strategy_signal_ledger，有信号时输出） |
| risk_flags | 基础版（财务风险 + 行业风险 + 数据风险） |
| completeness | 规则驱动的结构化判定 |
| source_map | 每个数值字段绑定来源 |

### 10.2 不做什么

| 不做 | 原因 |
|------|------|
| 复杂估值区间计算 | 涉及主观假设，Phase 1 只提供 raw PE/PB |
| 投资建议 | 合规边界 |
| 低稳定性字段（EPS 一致预期） | 数据源不稳定，等 iFinD 配额恢复 |
| 自然语言质量评分 | Phase 1 只做结构化规则 |
| 前端页面 | Phase 1 只输出 JSON/Markdown |

---

## Open Questions

1. **AKShare 数据更新频率**：`stock_value` 是日频更新还是按需拉取？需要确认是否需要每日批量采集。
2. **iFinD 配额恢复后的优先级**：PE/PB 全量、一致预期、股东结构，哪个优先接入？
3. **行业景气度数据**：`industry_position` 表当前为空，需要等 `chain_dynamics` 数据填充后才能生成 prosperity_score。Phase 1 是否用 ETF State 作为替代？
