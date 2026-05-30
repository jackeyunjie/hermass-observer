# 首席级投研报告模板

版本：v1.0
日期：2026-05-23
用途：为 Codex1 未来生成的首席级投研报告提供内容框架和语言规范
文档性质：报告模板 — 非投资建议

---

## 概述

本模板定义系统每日/每周生成的首席级投研报告的结构、数据来源、语言标准和合规边界。报告由五个递进层次组成：宏观环境 → 产业链景气 → 行业-策略适配 → 重点个股信号 → 综合适配建议。

**数据源总览**：

| 层次 | 主要数据源 | 更新频率 |
|------|-----------|----------|
| 宏观环境 | `outputs/macro/macro_snapshot_*.json`、`config/ifind_macro_indicators.json` | 日/月 |
| 产业链景气 | `outputs/industry_chain/industry_chain_evidence.duckdb`、`outputs/macro_chain_prior/` | 日 |
| 行业-策略适配 | `outputs/market_assets_state/`、`outputs/etf_config/`、`outputs/ifind/industry_*.json` | 日 |
| 重点个股信号 | `outputs/strategy_signals/strategy_signal_daily_*.json`、`outputs/p116_foundation_*` | 日 |
| 综合适配 | 上述全部 + `outputs/strategy_fit_observer/` | 日 |

---

## 报告结构（5 层递进）

### 一、宏观环境速览

**目标**：用 3-5 句话让读者了解当前处于什么样的宏观环境，以及这个环境对哪类资产有利。

#### 1.1 当前宏观象限

基于 `classify_macro_quadrant()` 函数输出，明确标注当前所处象限：

```text
当前宏观象限：[宽货币 × 宽信用 / 宽货币 × 紧信用 / 紧货币 × 宽信用 / 紧货币 × 紧信用 / 数据不足]
```

**数据来源**：`outputs/macro_chain_prior/macro_chain_prior_{date}.json` → `macro_prior.score_0_10`

**象限说明**（用于解读，不写入报告正文）：

| 象限 | 一句话特征 |
|------|-----------|
| 宽货币 × 宽信用 | 流动性充裕且实体需求扩张，风险偏好高，成长股占优 |
| 宽货币 × 紧信用 | 流动性充裕但实体需求偏弱，资金寻找结构性机会 |
| 紧货币 × 宽信用 | 利率上行但经济尚可，估值承压但盈利有支撑 |
| 紧货币 × 紧信用 | 流动性和需求双收缩，防御为主 |

#### 1.2 核心宏观指标一句话总结

从以下维度各写一句话，取自 `ifind_macro_indicators.json` 中定义的指标：

| 维度 | 指标示例 | 输出格式 |
|------|----------|----------|
| 利率 | 10 年期国债收益率、DR007 | "长端利率 [方向]，当前 [值]，[解读]" |
| 通胀 | CPI 当月同比、PPI 当月同比 | "CPI [方向]，PPI [方向]，[解读]" |
| 增长 | PMI、社会融资规模同比 | "PMI [值]，信用周期 [方向]，[解读]" |
| 汇率 | 美元兑人民币 | "人民币 [方向]，[对外资流向的影响]" |
| 风格 | 创业板/沪深300 比值、半导体/券商比值 | "成长风格 [相对强/弱]，[解读]" |

**语言示例**：

```text
长端利率维持低位，10 年期国债收益率 1.72%，流动性环境偏宽松。
CPI 同比 0.3%，PPI 同比 -2.1%，通胀压力温和，企业盈利端仍有压力。
PMI 50.2，信用扩张趋势延续，经济基本面边际改善。
人民币兑美元 7.24，汇率稳定，外资流出压力可控。
创业板相对沪深300 近 20 日超额 +5.1%，成长风格占优。
```

#### 1.3 宏观环境对策略的启示

基于宏观象限和风格信号，给出方向性判断：

```text
当前宏观环境 [利好成长/利好价值/整体谨慎]。
对 VCP 策略：[有利/中性/不利]（理由一句话）。
对 2560 策略：[有利/中性/不利]（理由一句话）。
对布林强盗策略：[有利/中性/不利]（理由一句话）。
```

**数据来源**：`macro_chain_prior.strategy_priors` 中各策略的 `prior_fit_score`

**语言约束**：只说"有利/中性/不利"，不说"建议重仓/轻仓"。

---

### 二、产业链景气扫描

**目标**：让读者了解哪些产业链在扩张、哪些在收缩、利润正在往哪里迁移。

#### 2.1 扩张产业链

**数据来源**：`outputs/industry_chain/industry_chain_evidence.duckdb` → `industry_position` 表

```text
处于扩张期的产业链：
- [产业链名称]：景气度 [分数]/10，[上升/持平]，关键驱动：[一句话]
- ...
```

筛选条件：`prosperity_score >= 7.0` 或 `prosperity_change = "improving"`

#### 2.2 稳定产业链

```text
处于稳定期的产业链：
- [产业链名称]：景气度 [分数]/10，[持平]
- ...
```

筛选条件：`4.5 <= prosperity_score < 7.0` 且 `prosperity_change = "stable"`

#### 2.3 收缩产业链 + 风险提示

```text
处于收缩期的产业链：
- [产业链名称]：景气度 [分数]/10，[下降]，风险点：[一句话]
- ...
```

筛选条件：`prosperity_score < 4.5` 或 `prosperity_change = "deteriorating"`

#### 2.4 产业链利润迁移方向

基于上中下游景气度分项（`industry_position.upstream_score` / `midstream_score` / `downstream_score`）：

```text
当前产业链利润迁移方向：[上游 → 中游 / 中游 → 下游 / 下游 → 上游 / 均衡]
依据：[上游景气 X 分，中游 Y 分，下游 Z 分]
```

**语言约束**：只描述事实和方向，不做"应该配置哪里"的建议。

---

### 三、行业-策略适配

**目标**：让读者了解当前哪些行业处于强势状态、各行业主要触发了什么策略信号、行业 ETF 是否形成共振。

#### 3.1 热点行业 EF 占比及变化

**数据来源**：`outputs/market_assets_state/market_assets_state_{date}.json`

```text
当前 E/F 占比最高的行业（ef_count >= 2 的标的占比）：
1. [行业]：[占比]%（较前日 [+/-N 个百分点]）
2. [行业]：[占比]%（较前日 [+/-N 个百分点]）
...
```

#### 3.2 各行业主要策略信号分布

**数据来源**：`outputs/strategy_signals/strategy_signal_daily_{date}.json` 按 `sw_l1` 分组统计

```text
[行业A]：VCP 信号 [N] 个，2560 信号 [N] 个，布林强盗信号 [N] 个
  其中最佳适配 [N] 个，适配 [N] 个
[行业B]：...
```

#### 3.3 行业 ETF State 共振情况

**数据来源**：`outputs/etf_config/industry_etf_config_{date}.json`、`outputs/macro_chain_prior/`

```text
行业 ETF 共振情况：
- 全共振（ETF + 个股均为 E/F）：[行业列表]
- ETF 强但个股弱：[行业列表]
- ETF 弱但个股强：[行业列表]（提示：市场支撑不足）
- 无 ETF 覆盖：[行业列表]
```

---

### 四、重点个股信号

**目标**：按产业链分组展示当日最佳适配信号，附带完整的环境证据链。

#### 4.1 分组逻辑

按以下优先级排序展示：

1. 最佳适配 + 三周期 E/F 共振 + 行业 ETF full_match
2. 最佳适配 + 三周期 E/F 共振
3. 适配 + 三周期 E/F 共振 + 行业 ETF full_match
4. 其他

同一优先级内按产业链分组。

#### 4.2 每个信号的展示格式

```text
[股票代码] [股票名称] | [策略名称] | [适配度]

  State 环境：MN1=[hex] W1=[hex] D1=[hex] | [生命周期阶段]
  产业链景气：[所属产业链] [景气度分数]/10 | [上/中/下游]
  市场匹配：[full_match / stock_only / market_unsupported]
  基本面摘要：[主营业务一句话] | [SW一级行业]
  本地统计：[20d 平均超额]% / [胜率]% / 样本[N]个
```

**数据来源**：

| 字段 | 来源 |
|------|------|
| State 环境 | `p116_foundation.duckdb` |
| 生命周期阶段 | `strategy_signal_daily.lifecycle_stage` |
| 适配度 | `strategy_signal_daily.strategy_environment_fit` |
| 产业链景气 | `industry_chain_evidence.duckdb` → `industry_position` |
| 市场匹配 | `strategy_signal_daily.ma2560_market_match_level` |
| 基本面摘要 | `outputs/ifind/industry_{date}.json` → `main_business` |
| 本地统计 | `outputs/strategy_evaluation/` 中的验证结果 |

#### 4.3 策略专属附加信息

**VCP 信号附加**：
```text
  VCP 路径：D1 近 [N] 日收缩后释放 | [10d 超额]% / [胜率]%
```

**2560 信号附加**：
```text
  2560 结构：MA25 [上行/走平] | VOL5 [>/</=] VOL60 | [做量型/缩量型/冲量型]
```

**布林强盗信号附加**：
```text
  布林强盗环境：D1 波动 [稳定/活跃] | 历史统计：vol=0 组 [超额]%, vol=1 组 [超额]%
```

#### 4.4 展示数量限制

- 每日最多展示 20 个重点信号
- 每个产业链最多展示 5 个
- 无信号的产业链不展示

---

### 五、综合适配建议

**目标**：用 3-5 句话总结当前环境的核心特征和需要关注的风险点。

#### 5.1 三重共振方向

```text
当前宏观-产业-State 三重共振的方向：
[方向描述，如"AI 算力链上游在宽货币+景气扩张+三周期共振下表现突出"]
```

三重共振条件：
- 宏观：`macro_prior.score_0_10 >= 6.5`
- 产业：`industry_position.prosperity_score >= 7.0`
- State：行业内 `ef_count >= 2` 的标的占比 >= 30%

#### 5.2 需要关注的风险点

```text
需要关注的风险：
- [风险点 1，如"某产业链景气度边际下降"]
- [风险点 2，如"宏观数据不足导致先验置信度低"]
- [风险点 3，如"某策略适配度集中在弱适配区间"]
```

**数据来源**：扫描以下条件

| 风险类型 | 触发条件 |
|----------|----------|
| 产业链景气下降 | `prosperity_change = "deteriorating"` |
| 宏观数据不足 | `macro_prior.status = "data_insufficient"` |
| 行业 ETF 缺失 | `mapping_status = "no_etf_coverage"` 的行业占比 > 50% |
| 策略适配度偏低 | 当日 `strategy_environment_fit` 中"弱适配"或"不适配"占比 > 60% |
| iFinD API 异常 | `ifind_errorcode` 非空 |

#### 5.3 免责声明

每份报告必须包含以下声明（不可删除或修改）：

```text
本报告由 Hermass Observer 系统自动生成，仅供研究参考，不构成任何投资建议。
报告中的所有数据、统计和适配度评估均基于历史回溯，不代表未来表现。
任何投资决策应由投资者独立做出，系统不承担因使用本报告内容而产生的任何损失。
```

---

## 语言规范

### 允许使用的词汇

```text
观察 / 关注 / 研究 / 统计 / 历史表现 / 适配度 / 环境
景气 / 趋势 / 方向 / 信号 / 结构 / 共振 / 支撑
有利 / 中性 / 不利 / 偏强 / 偏弱 / 边际改善 / 边际恶化
```

### 禁止使用的词汇

以下词汇在报告全文中不得出现：

```text
买入 / 卖出 / 建仓 / 加仓 / 减仓 / 清仓 / 空仓 / 满仓
止盈 / 止损 / 目标价 / 预期收益 / 保底 / 稳赚
推荐 / 建议 / 确定机会 / 必涨 / 必跌 / 荐股
操盘 / 抄底 / 逃顶 / 追高 / 割肉 / 套牢
```

### 语气标准

- **客观陈述**：只说"数据显示"，不说"我们判断"。
- **留有余地**：用"历史统计显示"代替"一定会"。
- **不越界**：用"适配度为高"代替"建议关注"。
- **透明可信**：标注样本量和数据来源。

---

## 生成流程

### 数据准备

```text
1. 宏观快照：outputs/macro/macro_snapshot_{date}.json
2. 产业链数据：outputs/industry_chain/industry_chain_evidence.duckdb
3. 宏观-产业链先验：outputs/macro_chain_prior/macro_chain_prior_{date}.json
4. 市场资产 State：outputs/market_assets_state/market_assets_state_{date}.json
5. 策略信号：outputs/strategy_signals/strategy_signal_daily_{date}.json
6. 行业 ETF 配置：outputs/etf_config/industry_etf_config_{date}.json
7. iFinD 行业数据：outputs/ifind/industry_{date}.json
8. Foundation DB：outputs/p116_foundation_{date}/p116_foundation.duckdb
```

### 输出格式

```text
outputs/daily_research_brief/chief_economist_brief_{date}.json
outputs/daily_research_brief/chief_economist_brief_{date}.md
public/chief_economist_brief_{date}.html
public/chief_economist_brief_latest.html
```

### 人工确认

报告生成后，必须经过人工确认才能对外分发：

```text
1. 系统自动生成报告草稿
2. 人工审核：检查数据一致性、禁止词汇、逻辑合理性
3. 人工确认后标记为 "confirmed": true
4. 对外分发
```

---

## 附录：数据不足时的降级策略

当某个数据源不可用时，报告相应章节按以下规则降级：

| 数据源 | 降级处理 |
|--------|----------|
| 宏观指标不足 | 宏观象限标注"数据不足"，不输出策略启示，保持中性 |
| 产业链数据为空 | 产业链章节输出"产业链动态数据暂缺"，不猜测 |
| 行业 ETF 缺失 | 标注"无 ETF 覆盖"，不强行认定市场共振 |
| 策略信号为空 | 标注"当日无信号"，不输出空洞的分析 |
| Foundation DB 缺失 | 不生成报告，报错退出 |

原则：数据不足时**明确告知**，不用默认值伪装为事实。
