# 系统架构演进路线图

版本：v1.0
日期：2026-05-23
状态：规划文档

---

## 当前系统状态总览

### MVP 已完成模块

| 模块 | 状态 | 关键产物 |
|------|------|----------|
| State 底座计算 | 已上线 | `scripts/state_calc/p116_core.py`、Foundation DB |
| 三策略信号模块 | 已上线 | `backtest/strategy_signals/{vcp,ma2560,bollinger_bandit}.py` |
| 策略信号账本 | 已上线 | `scripts/strategy_signal_ledger.py`、strategy_signals.duckdb |
| 适配度五级分类 | 已上线 | `compute_environment_fit()` in signal_ledger |
| 适配度观察持久化 | 已上线 | `scripts/strategy_fit_observer.py`、fit_log.duckdb |
| 前向观察账本 | 已上线 | `scripts/forward_observation_ledger.py` |
| 每日总报 | 已上线 | `scripts/daily_research_brief.py` |
| 策略提醒 | 已上线 | `scripts/strategy_reminder_brief.py` |
| 行业 ETF State | 已上线 | `scripts/build_industry_etf_config.py` |
| 宏观-产业链先验（骨架） | 已上线 | `scripts/build_macro_chain_prior.py`（单分数，低置信度） |
| 2560 State 匹配规则 | 已固化 | `config/ma2560_state_market_match_rule.json` |
| VCP 路径假设 | 初步验证 | `outputs/project/vcp_optimal_state_search.md` |
| 布林强盗候选 | 未通过 | KIMI 候选被本地数据拒绝 |
| 策略注册表 | 已上线 | `config/strategy_registry.json` |
| 策略环境验证编排器 | 已上线 | `scripts/strategy_environment_verifier.py` |

### 方法论文档清单（16 份）

| 序号 | 文档 | 定位 |
|------|------|------|
| 1 | `MULTICYCLE_STATE_STRATEGY_WHITEPAPER.md` | 系统完整方法论总纲 |
| 2 | `STRATEGY_DEFINITIONS.md` | 三策略权威定义 |
| 3 | `KIMI_STATE_STRATEGY_RESEARCH_DIGEST.md` | KIMI 研究消化记录 |
| 4 | `MA2560_STATE_MARKET_MATCH_RULE.md` | 2560 已固化规则 |
| 5 | `BOLLINGER_BANDIT_IMPLEMENTATION_AUDIT.md` | 布林强盗对账记录 |
| 6 | `STRATEGY_COLLABORATION_GUIDE.md` | 三策略协作说明（面向订阅者） |
| 7 | `USER_MANUAL.md` | 系统用户手册 |
| 8 | `CHIEF_ECONOMIST_BRIEF_TEMPLATE.md` | 首席报告模板 |
| 9 | `CHIEF_BRIEF_GENERATOR_SPEC.md` | 首席报告生成器规范 |
| 10 | `industry_chain_dynamics_spec.md` | 产业链三表 Schema 设计 |
| 11 | `chain_prosperity_scoring_model.md` | 产业链景气度评分模型 |
| 12 | `CHAIN_EVENT_SCANNER_SPEC.md` | 产业链事件扫描器设计 |
| 13 | `strategy_environment_fit_scoring_design.md` | 适配度评分模型设计 |
| 14 | `TRIPLE_RESONANCE_ENHANCEMENT.md` | 三重共振增强模型 |
| 15 | `MARKET_PHASE_IDENTIFICATION.md` | 市场阶段识别框架 |
| 16 | `MACRO_SCORING_MODEL.md` | 宏观评分四维模型 |
| 17 | `STATE_BASE_EXTENSION_DESIGN.md` | State 底座扩展设计 |
| 18 | `STRATEGY_PERFORMANCE_ATTRIBUTION.md` | 策略绩效归因分析框架 |
| 19 | `MONEYFLOW_EVIDENCE_MODEL.md` | 资金流证据层量化模型 |
| 20 | `calibration_trigger_design.md` | 校准触发机制设计 |
| 21 | `new_strategy_integration_guide.md` | 新策略标准接入规范 |
| 22 | `DATA_CONTRACT.md` | 数据契约 |

---

## 三阶段演进路径

```text
Phase 1: 数据补全          Phase 2: 深度增强          Phase 3: 智能化
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
宏观数据接入               市场阶段识别              校准自动触发
产业链数据填充             资金流证据层              策略权重动态调整
校准首次通过               三重共振增强              个性化配置
                           产业链事件扫描            首席报告自动生成
                           首席报告生成器            绩效归因自动运行
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
预估：4-6 周               预估：6-8 周              预估：4-6 周
```

---

## Phase 1：数据补全（4-6 周）

**目标**：将现有骨架填充为有实际数据支撑的系统，使宏观先验置信度从 0.25 提升至 0.5+。

### 1.1 宏观数据接入

| 任务 | 优先级 | 工作量 | 依赖 | 产出 |
|------|--------|--------|------|------|
| iFinD 指标码映射 | P0 | 1 周 | iFinD API 配额 | `data/macro/ifind_indicator_mapping.csv` |
| 核心指标数据获取 | P0 | 1 周 | 指标码映射 | `outputs/macro/macro_indicator_data.duckdb` |
| 宏观指标时间序列入库 | P0 | 3 天 | 数据获取 | 至少 10 个指标 × 12 个月历史 |
| 宏观四维评分模型实现 | P1 | 1 周 | 时间序列入库 | `scripts/macro_scoring_v2.py` |

**核心指标优先级**（按对系统价值排序）：

| 优先级 | 指标 | 维度 | 当前状态 | 接入后效果 |
|--------|------|------|----------|-----------|
| 1 | DR007 | 流动性 | formula_catalog_only | 流动性维度从缺失变为可用 |
| 2 | 1年期LPR | 流动性 | needs_validation | 验证后直接可用 |
| 3 | 非制造业PMI | 增长 | needs_ifind_code | 增长维度补全 |
| 4 | M1同比 | credit | formula_catalog_only | 信用维度核心指标 |
| 5 | M2同比 | credit | formula_catalog_only | 信用维度+M1-M2剪刀差 |
| 6 | 美元兑人民币 | 外部 | needs_ifind_code | 外部流动性调节 |
| 7 | 出口总值同比 | 增长 | formula_catalog_only | 增长维度补全 |
| 8 | 南华商品指数 | 通胀 | formula_catalog_only | 输入型通胀压力 |

**接入后的系统升级顺序**：

```text
Step 1: 指标码映射 + 数据获取
  → build_macro_chain_prior.py 的 indicator_signal() 覆盖率提升

Step 2: 实现 macro_scoring_v2.py（四维评分）
  → macro_prior 从单一分数拆为 growth/liquidity/credit/inflation 四子分
  → 象限判定（复苏/过热/滞胀/衰退）可用

Step 3: 更新 strategy_priors 计算
  → VCP/2560/布林强盗的 prior_fit_score 从粗粒度升级为四维加权
  → 置信度从 0.25 提升至 0.5+

Step 4: 首席报告生成器的宏观层
  → build_section_macro() 从"数据不足"升级为完整四维展示
```

### 1.2 产业链数据填充

| 任务 | 优先级 | 工作量 | 依赖 | 产出 |
|------|--------|--------|------|------|
| iFinD 产业链 profile 导入 | P1 | 2 天 | iFinD Excel | ifind_industry_chain_profile 表更新 |
| 产业链三表 Schema 实现 | P1 | 1 周 | Schema 设计文档 | chain_dynamics / industry_position / chain_event_cross |
| 优先产业链指标采集（AI算力/半导体/新能源车） | P1 | 1 周 | 三表 Schema | chain_dynamics 填充 |
| 产业链景气度评分实现 | P2 | 3 天 | 指标采集 | industry_position.prosperity_score |

### 1.3 校准首次通过

| 任务 | 优先级 | 工作量 | 依赖 | 产出 |
|------|--------|--------|------|------|
| 校准触发机制实现 | P1 | 3 天 | 设计文档 | `scripts/calibration_trigger.py` |
| 首次全量校准（2025-06 至今） | P1 | 1 天 | 触发机制 + 前向观察数据 | `outputs/calibration/calibration_{date}.json` |
| 校准结果写入策略注册表 | P2 | 1 天 | 校准通过 | strategy_registry.json 更新 status |

### Phase 1 里程碑

```text
M1: 宏观四维评分可用，置信度 >= 0.5
M2: 产业链景气度评分覆盖 Top 3 产业链
M3: 校准首次通过，适配度排序与历史收益方向一致
M4: 首席报告宏观层从"数据不足"升级为完整展示
```

---

## Phase 2：深度增强（6-8 周）

**目标**：在数据补全的基础上，实现市场阶段识别、资金流证据层、三重共振增强、产业链事件扫描和首席报告自动生成。

### 2.1 模块实现顺序

```text
并行线 A（市场维度）：           并行线 B（信号增强）：
  市场阶段识别器                   资金流证据层
       ↓                              ↓
  phase_factor 接入信号账本         mf_score 接入信号账本
       ↓                              ↓
       └──────────┬──────────────────┘
                  ↓
            三重共振增强模型
                  ↓
            首席报告生成器
                  ↓
            绩效归因分析框架
```

### 2.2 详细任务

| 任务 | 优先级 | 工作量 | 依赖 | 产出 |
|------|--------|--------|------|------|
| **市场阶段识别器** | P1 | 1 周 | State 缓存（已有） | `scripts/classify_market_phase.py` |
| market_phase 接入 signal_ledger | P1 | 2 天 | 识别器 | strategy_signal_daily 新增字段 |
| **资金流证据层** | P1 | 1 周 | 黑狼资金流 API | `scripts/build_moneyflow_evidence.py` |
| mf_score 接入 signal_ledger | P1 | 2 天 | 证据层 | strategy_signal_daily 新增字段 |
| **产业链事件扫描器** | P1 | 1 周 | 三表 Schema | `scripts/chain_event_scanner.py` |
| 事件扫描接入景气度评分 | P2 | 2 天 | 事件扫描器 | S_event 分项自动更新 |
| **三重共振增强模型** | P0 | 1 周 | market_phase + moneyflow + macro_scoring | `scripts/triple_resonance.py` |
| resonance 接入 signal_ledger | P0 | 2 天 | 共振模型 | enhanced_fit_score 字段 |
| resonance 接入提醒层 | P1 | 2 天 | signal_ledger 更新 | 提醒卡片新增共振标记 |
| **首席报告生成器** | P1 | 1 周 | 全部上游模块 | `daily_research_brief.py --mode chief` |
| **绩效归因分析框架** | P2 | 1 周 | 前向观察账本 + 全部上游 | `scripts/performance_attribution.py` |

### 2.3 Phase 2 里程碑

```text
M1: 市场阶段识别器每日输出 market_phase_{date}.json
M2: 资金流证据层覆盖全市场，mf_score 接入信号账本
M3: 三重共振模型上线，提醒卡片展示共振等级
M4: 首席报告 --mode chief 可生成完整五层报告
M5: 绩效归因报告首次输出
```

### 2.4 宏观数据接入后的系统升级顺序（详细）

```text
宏观数据到位后的第一周：
  1. macro_scoring_v2.py 上线 → 四维评分 + 象限
  2. strategy_priors 更新 → VCP/2560/布林强盗的宏观加成系数
  3. 首席报告第一层（宏观速览）从降级模式升级为完整模式

宏观数据到位后的第二周：
  4. 三重共振模型接入宏观维度 → macro_factor 可用
  5. 市场阶段识别器接入宏观信号 → 象限辅助阶段判定

宏观数据到位后的第三周：
  6. 首席报告完整版可生成 → 五层全部有数据
  7. 绩效归因报告新增宏观维度归因
```

---

## Phase 3：智能化（4-6 周）

**目标**：系统从"人工触发 + 规则驱动"升级为"自动触发 + 数据驱动"。

### 3.1 详细任务

| 任务 | 优先级 | 工作量 | 依赖 | 产出 |
|------|--------|--------|------|------|
| **校准自动触发** | P0 | 1 周 | calibration_trigger.py + 前向观察积累 | 自动校准流水线 |
| 校准结果自动反馈适配度权重 | P0 | 3 天 | 校准通过 | fit_score 权重自动调整 |
| **策略权重动态调整** | P1 | 1 周 | 绩效归因 + 校准数据 | `scripts/dynamic_weight_adjustment.py` |
| 适配度评分公式自动优化 | P1 | 1 周 | 归因数据积累 | 五维权重自动调整 |
| **个性化配置** | P2 | 1 周 | 系统稳定运行 | 用户偏好配置文件 |
| 关注策略/行业/产业链过滤 | P2 | 3 天 | 配置文件 | 个性化提醒和报告 |
| 报告推送自动化 | P2 | 3 天 | 首席报告稳定 | 飞书/邮件自动推送 |
| H1/M15 辅助维度接入 | P3 | 2 周 | State 底座扩展设计 | 短周期 State 辅助入场时机 |
| 新策略接入（ATR 吊灯等） | P3 | 1 周/策略 | 持仓上下文解决 | 新策略信号模块 |

### 3.2 Phase 3 里程碑

```text
M1: 校准自动触发运行，三重门条件满足时自动执行
M2: 适配度权重基于归因数据自动优化
M3: 个性化配置上线，用户可选择关注的策略/行业
M4: 首席报告自动推送到飞书/邮件
```

---

## 依赖关系图

```text
┌─────────────────────────────────────────────────────────────────┐
│                        Phase 1: 数据补全                         │
│                                                                 │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                   │
│  │ iFinD    │    │ 产业链   │    │ 校准     │                   │
│  │ 指标码   │───→│ 三表     │    │ 触发     │                   │
│  │ 映射     │    │ Schema   │    │ 机制     │                   │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘                   │
│       ↓               ↓               ↓                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                   │
│  │ 四维宏观 │    │ 产业链   │    │ 首次     │                   │
│  │ 评分模型 │    │ 景气度   │    │ 校准     │                   │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘                   │
│       ↓               ↓               ↓                         │
├───────┴───────────────┴───────────────┴─────────────────────────┤
│                        Phase 2: 深度增强                         │
│                                                                 │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                   │
│  │ 市场阶段 │    │ 资金流   │    │ 产业链   │                   │
│  │ 识别器   │    │ 证据层   │    │ 事件扫描 │                   │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘                   │
│       ↓               ↓               ↓                         │
│       └───────────┬───┴───────────────┘                         │
│                   ↓                                              │
│            ┌──────────┐                                         │
│            │ 三重共振 │                                         │
│            │ 增强模型 │                                         │
│            └────┬─────┘                                         │
│                 ↓                                                │
│  ┌──────────────────────┐    ┌──────────┐                       │
│  │ 首席报告生成器       │    │ 绩效归因 │                       │
│  │ --mode chief         │    │ 分析框架 │                       │
│  └──────────────────────┘    └──────────┘                       │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                        Phase 3: 智能化                           │
│                                                                 │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                   │
│  │ 校准自动 │    │ 权重动态 │    │ 个性化   │                   │
│  │ 触发     │───→│ 调整     │    │ 配置     │                   │
│  └──────────┘    └──────────┘    └──────────┘                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 关键路径

**最短路径到系统完整性**：

```text
iFinD 指标码映射（1 周）
  → 四维宏观评分（1 周）
    → 三重共振模型（1 周）
      → 首席报告生成器（1 周）

总计：4 周可实现首席报告完整版
```

**阻塞风险**：

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| iFinD API 配额不足 | Phase 1 宏观数据接入延迟 | GUI 离线导入 + Tushare 备选 |
| 前向观察样本不足 | 校准无法触发 | 降低初始阈值至 30 条/策略 |
| 资金流数据覆盖不足 | 资金流证据层置信度低 | 分级降级策略（coverage < 30% 时不参与评分） |
| 产业链数据采集人工成本高 | Phase 2 产业链事件扫描延迟 | 优先覆盖 Top 3 产业链，其余渐进补充 |

---

## 每阶段交付物汇总

### Phase 1 交付物

```text
新增脚本：
  scripts/macro_scoring_v2.py
  scripts/chain_dynamics_builder.py
  scripts/calibration_trigger.py

新增配置：
  config/macro_scoring_weights.json
  config/chain_catalog.json

新增数据：
  outputs/macro/macro_indicator_data.duckdb
  outputs/industry_chain/industry_chain_evidence.duckdb（升级）
  outputs/calibration/calibration_{date}.json

升级脚本：
  scripts/build_macro_chain_prior.py → 消费四维评分
  config/strategy_registry.json → 校准状态更新
```

### Phase 2 交付物

```text
新增脚本：
  scripts/classify_market_phase.py
  scripts/build_moneyflow_evidence.py
  scripts/chain_event_scanner.py
  scripts/triple_resonance.py
  scripts/performance_attribution.py

升级脚本：
  scripts/strategy_signal_ledger.py → 新增 market_phase / mf_score / resonance 字段
  scripts/strategy_reminder_brief.py → 新增共振标记、资金流标签
  scripts/daily_research_brief.py → --mode chief 完整版

新增输出：
  outputs/market_phase/market_phase_{date}.json
  outputs/moneyflow_evidence/moneyflow_evidence_{date}.json
  outputs/attribution/attribution_report_{date}.json
  outputs/daily_research_brief/chief_brief_{date}.json
```

### Phase 3 交付物

```text
新增脚本：
  scripts/dynamic_weight_adjustment.py
  scripts/user_preference_config.py
  scripts/report_push.py

新增配置：
  config/user_preferences.json
  config/calibration_auto_trigger.json

新增输出：
  outputs/calibration/auto_calibration_log_{date}.json
  outputs/weight_adjustment/weight_history.json
```
