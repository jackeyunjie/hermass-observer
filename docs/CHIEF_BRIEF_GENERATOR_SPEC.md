# 首席级投研报告生成器设计规范

版本：v1.0
日期：2026-05-23
状态：设计稿 — 可被 Codex2 实现
关联模板：`docs/CHIEF_ECONOMIST_BRIEF_TEMPLATE.md`（报告结构和语言规范）
关联模型：`docs/chain_prosperity_scoring_model.md`（景气度评分公式）
关联脚本：`scripts/daily_research_brief.py`（现有日报，本生成器的升级基础）

---

## 定位

本规范是 `CHIEF_ECONOMIST_BRIEF_TEMPLATE.md`（报告模板）和 `chain_prosperity_scoring_model.md`（景气度模型）的工程化合并。它定义一个可被 Codex2 直接实现的报告生成器，将分散在多个数据源中的信息组装为一份五层递进的首席级投研报告。

**与现有日报的关系**：首席报告是 `daily_research_brief.py` 输出的**升级版**，不是独立产出。现有日报覆盖信号汇总和策略适配度，首席报告在其基础上新增宏观象限、产业链景气扫描和综合适配建议三个层次。

---

## 1. 输入定义

### 1.1 输入清单

| 输入 ID | 数据源 | 必填 | 更新频率 | 用途 |
|---------|--------|------|----------|------|
| macro_snapshot | `outputs/macro/macro_snapshot_{date}.json` | 否 | 日/月 | 第一层：宏观象限和指标 |
| macro_chain_prior | `outputs/macro_chain_prior/macro_chain_prior_{date}.json` | 是 | 日 | 第一层策略先验 + 第二层行业先验 |
| chain_db | `outputs/industry_chain/industry_chain_evidence.duckdb` | 否 | 日 | 第二层：产业链景气（chain_dynamics + industry_position + chain_event_cross） |
| market_assets_state | `outputs/market_assets_state/market_assets_state_{date}.json` | 是 | 日 | 第三层：行业 ETF State |
| etf_config | `outputs/etf_config/industry_etf_config_{date}.json` | 是 | 日 | 第三层：行业 ETF 映射 |
| strategy_signals | `outputs/strategy_signals/strategy_signal_daily_{date}.json` | 是 | 日 | 第三/四层：策略信号 |
| ifind_industry | `outputs/ifind/industry_{date}.json` | 否 | 日 | 第四层：基本面摘要 |
| foundation_db | `outputs/p116_foundation_{date}/p116_foundation.duckdb` | 是 | 日 | 第四层：State 环境 |
| strategy_fit_observer | `outputs/strategy_fit_observer/fit_log_{date}.json` | 否 | 日 | 第四层：适配度观察 |

### 1.2 输入加载函数

```python
def load_inputs(date_str: str) -> dict[str, Any]:
    """加载所有输入数据源。每个数据源缺失时返回空 dict 而非抛异常。"""
    paths = paths_for(date_str)  # 复用 daily_research_brief.py 的路径逻辑
    return {
        "macro_snapshot": load_json_optional(paths["macro_snapshot"]),
        "macro_chain_prior": load_json_required(paths["macro_chain_prior"]),
        "chain_db": paths["chain_db"],  # DuckDB 连接延迟建立
        "market_assets_state": load_json_required(paths["market_assets_state"]),
        "etf_config": load_json_required(paths["etf_config"]),
        "strategy_signals": load_json_required(paths["strategy_signals"]),
        "ifind_industry": load_json_optional(paths["ifind_industry"]),
        "foundation_db": paths["foundation_db"],
        "fit_observer": load_json_optional(paths["fit_observer"]),
    }
```

### 1.3 输入 Schema 版本检查

```python
REQUIRED_VERSIONS = {
    "macro_chain_prior": "macro_chain_prior_v1",
    "strategy_signals": "strategy_signal_daily_v2",
}

def check_schema(inputs: dict) -> list[str]:
    """返回不兼容的输入列表。空列表 = 全部兼容。"""
    warnings = []
    for key, expected in REQUIRED_VERSIONS.items():
        actual = (inputs.get(key) or {}).get("schema_version")
        if actual and actual != expected:
            warnings.append(f"{key}: expected {expected}, got {actual}")
    return warnings
```

---

## 2. 生成逻辑

### 2.1 总体流程

```python
def generate_chief_brief(date_str: str) -> dict:
    inputs = load_inputs(date_str)
    schema_warnings = check_schema(inputs)

    section_1 = build_section_macro(inputs)           # 宏观环境速览
    section_2 = build_section_chain_prosperity(inputs)  # 产业链景气扫描
    section_3 = build_section_industry_fit(inputs)     # 行业-策略适配
    section_4 = build_section_top_signals(inputs)      # 重点个股信号
    section_5 = build_section_synthesis(inputs, section_1, section_2, section_3, section_4)  # 综合适配建议

    return {
        "schema_version": "chief_brief_v1",
        "date": date_str,
        "generated_at": utc_now(),
        "sections": [section_1, section_2, section_3, section_4, section_5],
        "schema_warnings": schema_warnings,
        "research_only": True,
    }
```

### 2.2 第一层：宏观环境速览

**数据源**：macro_snapshot + macro_chain_prior

**聚合方法**：

```python
def build_section_macro(inputs: dict) -> dict:
    macro = inputs["macro_snapshot"]
    prior = inputs["macro_chain_prior"]

    # 象限判定（复用 strategy_environment_verifier.py:classify_macro_quadrant）
    quadrant = classify_macro_quadrant(macro)

    # 核心指标提取（5 维各取一句话）
    indicators = extract_indicators(macro)  # 利率/通胀/增长/汇率/风格

    # 策略先验评分
    strategy_priors = (prior.get("strategy_priors") or {})
    vcp_prior = strategy_priors.get("vcp", {}).get("prior_fit_score", 5.0)
    ma2560_prior = strategy_priors.get("ma2560", {}).get("prior_fit_score", 5.0)
    bb_prior = strategy_priors.get("bollinger_bandit", {}).get("prior_fit_score", 5.0)

    # 宏观环境对策略的启示
    strategy_implications = classify_strategy_implication(quadrant, vcp_prior, ma2560_prior, bb_prior)

    return {
        "section_id": "macro_overview",
        "quadrant": quadrant,
        "indicators": indicators,
        "strategy_implications": strategy_implications,
        "data_status": "ok" if macro else "data_insufficient",
    }
```

**展示规则**：

| 数据状态 | 展示方式 |
|----------|----------|
| ok | 完整展示象限 + 指标 + 启示 |
| data_insufficient | 标注"宏观数据暂缺，以下分析不含宏观维度"，不猜测 |
| partial | 展示已有指标，缺失项标注"暂无" |

### 2.3 第二层：产业链景气扫描

**数据源**：chain_db（industry_position 表）+ macro_chain_prior.industry_priors

**聚合方法**：

```python
def build_section_chain_prosperity(inputs: dict) -> dict:
    chain_db = inputs["chain_db"]
    prior = inputs["macro_chain_prior"]

    # 从 industry_position 表读取景气度
    positions = query_chain_db(chain_db, "SELECT * FROM industry_position WHERE as_of_date = ?", date_str)

    # 分三组
    expanding = [p for p in positions if p["prosperity_score"] >= 7.0 or p["prosperity_change"] == "improving"]
    stable = [p for p in positions if 4.5 <= p["prosperity_score"] < 7.0 and p["prosperity_change"] == "stable"]
    contracting = [p for p in positions if p["prosperity_score"] < 4.5 or p["prosperity_change"] == "deteriorating"]

    # 利润迁移方向
    upstream_avg = avg(p["upstream_score"] for p in positions if p["upstream_score"])
    midstream_avg = avg(p["midstream_score"] for p in positions if p["midstream_score"])
    downstream_avg = avg(p["downstream_score"] for p in positions if p["downstream_score"])
    migration = detect_profit_migration(upstream_avg, midstream_avg, downstream_avg)

    return {
        "section_id": "chain_prosperity",
        "expanding": expanding,
        "stable": stable,
        "contracting": contracting,
        "profit_migration": migration,
        "data_status": "ok" if positions else "chain_data_empty",
    }
```

**展示规则**：

| 数据状态 | 展示方式 |
|----------|----------|
| ok | 完整展示三组 + 利润迁移 |
| chain_data_empty | 标注"产业链动态数据暂缺"，跳过本层，不猜测 |
| partial | 展示已有行业，标注"数据覆盖不完整" |

### 2.4 第三层：行业-策略适配

**数据源**：market_assets_state + strategy_signals + etf_config

**聚合方法**：

```python
def build_section_industry_fit(inputs: dict) -> dict:
    state_rows = inputs["market_assets_state"]
    signals = inputs["strategy_signals"]
    etf_config = inputs["etf_config"]

    # EF 占比统计（按 sw_l1 分组）
    industry_ef = compute_industry_ef_ratio(state_rows)

    # 策略信号分布（按 sw_l1 × strategy_id 分组）
    signal_dist = compute_signal_distribution(signals)

    # ETF 共振情况
    etf_resonance = compute_etf_resonance(state_rows, etf_config)

    return {
        "section_id": "industry_strategy_fit",
        "industry_ef_ratios": industry_ef,
        "signal_distribution": signal_dist,
        "etf_resonance": etf_resonance,
    }
```

**展示规则**：本层依赖 market_assets_state 和 strategy_signals，两者均为必填输入。缺失时报错退出。

### 2.5 第四层：重点个股信号

**数据源**：strategy_signals + foundation_db + chain_db + ifind_industry

**聚合方法**：

```python
def build_section_top_signals(inputs: dict, max_signals: int = 20) -> dict:
    signals = inputs["strategy_signals"]
    chain_db = inputs["chain_db"]
    ifind = inputs["ifind_industry"]

    # 按适配度排序
    sorted_signals = sort_signals(signals)

    # 按产业链分组
    grouped = group_by_chain(sorted_signals, chain_db, ifind)

    # 每组最多 5 个，总共最多 20 个
    top_signals = select_top(grouped, per_group=5, total=max_signals)

    # 为每个信号附加完整证据链
    enriched = [enrich_signal(s, inputs) for s in top_signals]

    return {
        "section_id": "top_signals",
        "signals": enriched,
        "total_available": len(sorted_signals),
        "displayed": len(enriched),
    }
```

**信号排序优先级**：

```text
1. strategy_environment_fit = "最佳适配" AND ef_count >= 2 AND market_match = "full_match"  → 优先级 1
2. strategy_environment_fit = "最佳适配" AND ef_count >= 2                                   → 优先级 2
3. strategy_environment_fit = "适配" AND ef_count >= 2 AND market_match = "full_match"       → 优先级 3
4. 其他                                                                                      → 优先级 4
```

同一优先级内按产业链分组，组内按 signal_strength 降序。

**信号证据链组装**：

```python
def enrich_signal(signal: dict, inputs: dict) -> dict:
    code = signal["stock_code"]
    return {
        "stock_code": code,
        "stock_name": signal.get("stock_name"),
        "strategy_id": signal["strategy_id"],
        "signal_name": signal["signal_name"],
        "environment_fit": signal["strategy_environment_fit"],
        "lifecycle_stage": signal["lifecycle_stage"],
        "state_combo": f"{signal.get('mn1_state')}/{signal.get('w1_state')}/{signal.get('d1_state')}",
        "ef_count": signal.get("ef_count"),
        "chain_position": lookup_chain_position(code, inputs["chain_db"]),
        "chain_prosperity": lookup_chain_prosperity(code, inputs["chain_db"]),
        "market_match_level": signal.get("ma2560_market_match_level"),
        "main_business": lookup_main_business(code, inputs["ifind_industry"]),
        "local_stats": lookup_local_stats(signal["strategy_id"]),  # 从 outputs/strategy_evaluation/
        # 策略专属附加
        "strategy_extras": build_strategy_extras(signal),
    }
```

### 2.6 第五层：综合适配建议

**数据源**：前四层输出的汇总

**聚合方法**：

```python
def build_section_synthesis(inputs: dict, s1: dict, s2: dict, s3: dict, s4: dict) -> dict:
    # 三重共振方向
    triple_resonance = find_triple_resonance(s1, s2, s3, s4)

    # 风险点扫描
    risks = scan_risks(inputs, s1, s2, s3)

    return {
        "section_id": "synthesis",
        "triple_resonance": triple_resonance,
        "risks": risks,
    }
```

**三重共振条件**：

```text
宏观先验 >= 6.5 AND 产业链景气 >= 7.0 AND 行业内 ef_count>=2 占比 >= 30%
```

**风险扫描条件**：

| 风险类型 | 触发条件 |
|----------|----------|
| 产业链景气下降 | industry_position.prosperity_change == "deteriorating" |
| 宏观数据不足 | macro_chain_prior.macro_prior.status == "data_insufficient" |
| 行业 ETF 缺失 | mapping_status == "no_etf_coverage" 的行业占比 > 50% |
| 适配度偏低 | "弱适配"+"不适配" 占比 > 60% |
| iFinD API 异常 | macro_chain_prior.ifind_errorcode 非空 |
| 策略信号稀少 | 当日信号总数 < 10 |

---

## 3. 语言模板

### 3.1 第一层模板

```python
MACRO_TEMPLATES = {
    "quadrant": "当前宏观象限：{quadrant}",
    "indicator": "{dimension}：{value_text}",
    "strategy_implication": "对{strategy}：{stance}（{reason}）",
    "data_insufficient": "宏观数据暂缺，本报告不含宏观维度分析。",
}
```

**生成示例**：

```text
当前宏观象限：宽货币 × 宽信用

利率：长端利率维持低位，10 年期国债收益率 1.72%，流动性环境偏宽松。
通胀：CPI 同比 0.3%，PPI 同比 -2.1%，通胀压力温和。
增长：PMI 50.2，信用扩张趋势延续。
风格：创业板相对沪深300 近 20 日超额 +5.1%，成长风格占优。

对 VCP：有利（成长风格占优 + 流动性充裕）。
对 2560：中性（行业共振条件独立于宏观象限）。
对布林强盗：有利（风险偏好上升，波动扩张环境）。
```

### 3.2 第二层模板

```python
CHAIN_TEMPLATES = {
    "expanding": "处于扩张期的产业链：\n{items}",
    "item": "- {chain_name}：景气度 {score}/10，{change_text}，关键驱动：{driver}",
    "stable": "处于稳定期的产业链：\n{items}",
    "contracting": "处于收缩期的产业链：\n{items}",
    "risk_item": "- {chain_name}：景气度 {score}/10，{change_text}，风险点：{risk}",
    "migration": "产业链利润迁移方向：{direction}（上游 {up} 分，中游 {mid} 分，下游 {down} 分）",
    "data_empty": "产业链动态数据暂缺，本层跳过。",
}
```

### 3.3 第三层模板

```python
INDUSTRY_TEMPLATES = {
    "ef_header": "当前 E/F 占比最高的行业：",
    "ef_item": "{rank}. {industry}：{ratio}%（较前日 {change}）",
    "signal_header": "各行业主要策略信号分布：",
    "signal_item": "{industry}：VCP {vcp_n} 个，2560 {ma2560_n} 个，布林强盗 {bb_n} 个",
    "resonance_header": "行业 ETF 共振情况：",
    "resonance_full": "全共振：{industries}",
    "resonance_etf_only": "ETF 强但个股弱：{industries}",
    "resonance_stock_only": "ETF 弱但个股强：{industries}（提示：市场支撑不足）",
}
```

### 3.4 第四层模板

```python
SIGNAL_TEMPLATES = {
    "group_header": "【{chain_name}】",
    "signal_card": """{stock_code} {stock_name} | {strategy_name} | {fit_level}
  State 环境：{state_combo} | {lifecycle_stage}
  产业链景气：{chain_name} {prosperity}/10 | {position}
  市场匹配：{market_match}
  基本面：{main_business}
  本地统计：{excess_20d}% / 胜率 {wr_20d}% / 样本 {n} 个""",
    "vcp_extra": "  VCP 路径：D1 近 {lookback} 日收缩后释放 | {excess}% / {wr}%",
    "ma2560_extra": "  2560 结构：MA25 {ma_dir} | VOL5 {vol_relation} VOL60 | {vol_type}",
    "bb_extra": "  布林强盗环境：D1 波动 {vol_state} | 统计：vol=0 组 {excess_0}%，vol=1 组 {excess_1}%",
}
```

### 3.5 第五层模板

```python
SYNTHESIS_TEMPLATES = {
    "resonance": "当前宏观-产业-State 三重共振的方向：{description}",
    "risk_header": "需要关注的风险：",
    "risk_item": "- {risk_text}",
    "disclaimer": """本报告由 Hermass Observer 系统自动生成，仅供研究参考，不构成任何投资建议。
报告中的所有数据、统计和适配度评估均基于历史回溯，不代表未来表现。""",
}
```

### 3.6 禁止词汇过滤器

```python
FORBIDDEN_WORDS = [
    "买入", "卖出", "建仓", "加仓", "减仓", "清仓", "空仓", "满仓",
    "止盈", "止损", "目标价", "预期收益", "保底", "稳赚",
    "推荐", "建议", "确定机会", "必涨", "必跌", "荐股",
    "操盘", "抄底", "逃顶", "追高", "割肉", "套牢",
]

def sanitize_text(text: str) -> str:
    """替换禁止词汇为 [合规过滤]。"""
    for word in FORBIDDEN_WORDS:
        text = text.replace(word, "[合规过滤]")
    return text
```

---

## 4. 降级策略

### 4.1 降级矩阵

| 缺失数据 | 降级处理 | 报告影响 |
|----------|----------|----------|
| macro_snapshot | 象限标注"数据不足"，策略启示保持中性 | 第一层精简 |
| macro_chain_prior | **报错退出** — 这是核心输入 | 不可降级 |
| chain_db 为空 | 第二层标注"产业链数据暂缺"，跳过 | 第二层缺失 |
| chain_db 部分填充 | 展示已有行业，标注覆盖不完整 | 第二层部分 |
| market_assets_state | **报错退出** — 行业 ETF 是核心数据 | 不可降级 |
| strategy_signals | **报错退出** — 策略信号是核心数据 | 不可降级 |
| ifind_industry | 基本面摘要显示"暂无" | 第四层简化 |
| foundation_db | **报错退出** — State 是核心数据 | 不可降级 |
| 某行业无 ETF 覆盖 | 标注"无 ETF 覆盖"，不强行共振 | 展示降级 |

### 4.2 降级状态标记

```python
def degrade_status(inputs: dict) -> dict:
    return {
        "macro": "ok" if inputs["macro_snapshot"] else "missing",
        "chain": classify_chain_status(inputs["chain_db"]),
        "market": "ok",  # 必填，不缺失
        "signals": "ok",  # 必填，不缺失
        "fundamental": "ok" if inputs["ifind_industry"] else "missing",
    }
```

报告头部展示数据完整性状态：

```text
数据完整性：宏观 [ok/缺失] | 产业链 [ok/部分/缺失] | 行业ETF [ok] | 策略信号 [ok]
```

---

## 5. 与现有总报的关系

### 5.1 架构关系

```text
现有日报（daily_research_brief.py）
  ↓ 升级
首席报告（chief_brief_generator.py）
  = 日报全部内容
  + 宏观象限层（新增）
  + 产业链景气层（新增）
  + 综合适配建议层（新增）
  + 更严格的语言合规检查
```

### 5.2 实现关系

**推荐方案：扩展现有脚本，非新建**

```python
# scripts/daily_research_brief.py 新增模式参数

def main():
    parser.add_argument("--mode", choices=["standard", "chief"], default="standard")
    args = parser.parse_args()

    if args.mode == "chief":
        result = build_chief_brief(args.date)
    else:
        result = build_standard_brief(args.date)
```

理由：
- 复用现有的数据加载、信号聚合、HTML 渲染逻辑
- 避免维护两套相似代码
- chief 模式是 standard 模式的超集

### 5.3 输出路径

```text
standard 模式（现有）：
  outputs/daily_research_brief/daily_research_brief_{date}.json
  public/daily_research_brief_{date}.html

chief 模式（新增）：
  outputs/daily_research_brief/chief_brief_{date}.json
  public/chief_brief_{date}.html
  public/chief_brief_latest.html
```

### 5.4 执行时序

```text
收盘后流水线：
  1. build_state_cache（State 缓存）
  2. build_strategy_signal_ledger（信号账本）
  3. build_macro_chain_prior（宏观-产业链先验）
  4. build_strategy_fit_observer（适配度观察）
  5. chain_event_scan（事件扫描，见 CHAIN_EVENT_SCANNER_SPEC.md）
  6. daily_research_brief --mode standard（标准日报）
  7. daily_research_brief --mode chief（首席报告）  ← 依赖 1-6 全部完成
```

---

## 附录：Codex2 实现检查清单

```text
□ load_inputs() — 加载 9 个输入源，缺失时返回空 dict
□ build_section_macro() — 象限判定 + 5 维指标 + 策略启示
□ build_section_chain_prosperity() — 从 industry_position 读取，分三组，利润迁移
□ build_section_industry_fit() — EF 占比 + 信号分布 + ETF 共振
□ build_section_top_signals() — 排序 + 分组 + 证据链组装（最多 20 个）
□ build_section_synthesis() — 三重共振 + 风险扫描
□ 语言模板实例化 — 每层的标准句式
□ sanitize_text() — 禁止词汇过滤
□ degrade_status() — 降级状态标记
□ render_html() — HTML 输出
□ render_markdown() — Markdown 输出
□ --mode chief 参数接入 daily_research_brief.py
□ 人工确认流程 — 生成后标记 confirmed
```
