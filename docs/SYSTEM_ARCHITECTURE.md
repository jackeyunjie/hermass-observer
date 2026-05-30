# 系统整体架构设计

版本：v1.1
日期：2026-05-27
状态：架构文档（已同步 A 股专属化分层）
关联路线图：`docs/SYSTEM_EVOLUTION_ROADMAP.md`、`docs/AGENTLY_A_SHARE_INTEGRATION_PLAN.md`

> 范围声明：本文档描述的是当前 A 股活跃生产系统架构。已归档的 MT5、美股/US、Alpaca 相关文件不属于本架构的运行范围。

---

## 1. 系统总览

### 1.1 运行时分层（核心边界）

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ Layer 4: API / 服务层                                                       │
│  hermass_platform/api/a_share_service.py                                    │
│  POST /run-daily          → core flow                                       │
│  POST /run-full-daily     → full compatibility workflow                     │
│  POST /generate-brief     → 单独重建简报                                    │
│  GET  /query-signal       → 只读查询                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ Layer 3: Flow 编排层                                                        │
│                                                                             │
│  ┌─────────────────────────┐  ┌─────────────────────────────────────────┐  │
│  │ agently_a_share_flow.py │  │ agently_daily_flow.py                   │  │
│  │ TriggerFlow:            │  │ TriggerFlow:                            │  │
│  │ hermass-a-share-d1-     │  │ hermass-p116-full-compatibility-flow    │  │
│  │ core-flow               │  │                                         │  │
│  │                         │  │ 运行兼容闭环 → 校验公开产物 → 完成      │  │
│  │ 预检 → 底座 → 缓存 →    │  │                                         │  │
│  │ 证据 → 信号 → 前向 →    │  │ full_workflow_run + verification        │  │
│  │ 简报 → 校验核心产物      │  │ daily_run (兼容别名)                    │  │
│  │                         │  │                                         │  │
│  │ verify_core_outputs     │  │ verify_public_outputs                   │  │
│  │   = core outputs        │  │   = core outputs + public extensions    │  │
│  └─────────────────────────┘  └─────────────────────────────────────────┘  │
│            │                              │                                 │
│            └──────────────┬───────────────┘                                 │
│                           ▼                                                 │
│              agently_adapter/a_share_actions.py                             │
│              (Action 契约层：统一参数、统一返回)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ Layer 2: Shared Core Layer                                                  │
│  agently_adapter/a_share_core.py                                            │
│                                                                             │
│  唯一共享实现层，负责：                                                      │
│  - preflight / build_foundation / build_state_cache                         │
│  - build_strategy_evidence / build_strategy_signal_ledger                   │
│  - build_forward_observation / build_daily_brief                            │
│  - verify_core_outputs / verify_public_outputs                              │
│  - run_core_steps_from_foundation / run_core_flow                           │
│                                                                             │
│  消费方：a_share_actions.py、stockpool_daily_runner.py、FastAPI 服务        │
├─────────────────────────────────────────────────────────────────────────────┤
│ Layer 1: 数据与底座脚本层                                                   │
│  scripts/*.py  (build_p116_foundation.py, state_cache_builder.py, ...)      │
│  backtest/strategy_signals/{vcp,ma2560,bollinger_bandit}.py                 │
│  blackwolf_client.py, download_daily.py, collect_macro_multisource.py       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 四层边界定义

| 层级 | 名称 | 职责 | 关键文件 |
|------|------|------|----------|
| Layer 4 | API 层 | 暴露 HTTP 接口，路由到对应 Flow | `a_share_service.py` |
| Layer 3 | Flow 编排层 | 声明式 DAG 编排，调用 Action 契约 | `agently_a_share_flow.py` / `agently_daily_flow.py` |
| Layer 3 | Action 契约层 | 统一参数转换、超时控制、结果封装 | `a_share_actions.py` |
| Layer 2 | Shared Core Layer | 最小核心链路的唯一共享实现 | `a_share_core.py` |
| Layer 1 | 数据/脚本层 | 确定性计算、数据下载、State 底座 | `scripts/*.py`, `backtest/*.py` |

### 1.3 产物校验边界

```text
verify_core_outputs    = core outputs
                         (foundation_db, state_cache, strategy_evidence,
                          strategy_signal_ledger, forward_observation,
                          daily_research_brief)

verify_public_outputs  = core outputs + public extensions
                         (core outputs + p116_all_three_ef, recommendation,
                          macro_snapshot, macro_chain_prior, market_assets_state,
                          industry_etf_coverage, industry_etf_config,
                          strategy_reminder, ma2560_market_match_forward, ...)
```

### 1.4 层间接口

```text
Layer 1 → Layer 2:  scripts/*.py → a_share_core.py 调用
Layer 2 → Layer 3:  a_share_core.py → a_share_actions.py 封装
Layer 3 → Layer 4:  a_share_actions.py → agently_a_share_flow.py / agently_daily_flow.py 编排
Layer 4 → API:     Flow 结果 → a_share_service.py FastAPI 暴露
```

### 1.5 调用链示例

**Core Flow 调用链：**
```text
/run-daily (API)
  → agently_a_share_flow.py (TriggerFlow: hermass-a-share-d1-core-flow)
    → a_share_actions.verify_core_outputs()
      → a_share_core.verify_core_outputs()
        → 校验 core outputs 完整性
```

**Full Compatibility Workflow 调用链：**
```text
/run-full-daily (API)
  → agently_daily_flow.py (TriggerFlow: hermass-p116-full-compatibility-flow)
    → stockpool_daily_runner.py run (子进程)
      → a_share_core.run_core_flow() + runner 扩展节点
    → verify_public_outputs
      → a_share_core.verify_public_outputs()
        → 校验 core outputs + public extensions 完整性
```

### 1.6 底座只读边界

```text
Layer 1（数据/脚本层）和 Layer 2（Shared Core Layer）是只读的：
  - p116_core.py 的 calculate_state() 不可被任何下游修改
  - D1 视角天条不可修改
  - E=14/F=15 定义不可修改
  - 位置优先符号裁决不可修改

Layer 3（Flow/Action 层）及以上只消费 Layer 2 的输出，不写回。
```

---

## 2. 数据流向图

```text
黑狼 API ──→ data/raw/*.csv ──→ build_p116_foundation.py
                                         │
iFinD Excel ──→ fundamental_evidence.duckdb
                                         │
AKShare 期货 ──→ chain_dynamics (DuckDB)  │
                                         │
                                         ▼
                          p116_foundation.duckdb
                          (MN1/W1/D1 State, SR, ATR)
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
           state_cache/*.json    market_assets_state    classify_market_phase
           (state_ef, state_     (ETF State)            (市场阶段)
            distribution,
            state_transition,
            sr_boundary,
            state_duration)
                    │                    │                    │
                    └────────────────────┼────────────────────┘
                                         ▼
                            strategy_signal_ledger.py
                            (三策略信号 + 环境匹配 + 适配度)
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
           build_macro_          w1_mn1_env_label.py    build_strategy_
           chain_prior.py        (大周期环境标签)        evidence.py
           (宏观+产业链先验)                              (入选证据)
                    │                    │                    │
                    └────────────────────┼────────────────────┘
                                         ▼
                            forward_observation_ledger.py
                            (前向观察 + 收益标签)
                                         │
                                         ▼
                            calibration_trigger.py
                            (三重门检查 + 校准执行)
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                                         ▼
           strategy_reminder_brief.py              daily_research_brief.py
           (策略提醒 HTML)                          (总报 HTML --mode chief)
                    │                                         │
                    └────────────────────┬────────────────────┘
                                         ▼
                                public/*.html
                              (本地 HTTP 服务)
```

---

## 3. 模块依赖关系

### 3.1 运行时模块（按新分层）

| 模块 | 层级 | 定位 | 职责 | 消费方 |
|------|------|------|------|--------|
| `a_share_service.py` | Layer 4 | API 层 | FastAPI 暴露 `/run-daily` / `/run-full-daily` | 外部客户端 |
| `agently_a_share_flow.py` | Layer 3 | Core Flow | TriggerFlow 编排最小核心链路 | API 层 |
| `agently_daily_flow.py` | Layer 3 | Full Workflow | TriggerFlow 编排 full compatibility workflow | API 层 |
| `a_share_actions.py` | Layer 3 | Action 契约 | 统一参数、超时、结果封装 | Flow 层 |
| `a_share_core.py` | Layer 2 | Shared Core | 最小核心链路唯一共享实现 | Action 层、runner |
| `stockpool_daily_runner.py` | Layer 2-3 | Runner | core flow + public extensions 兼容闭环 | CLI、Flow |
| `build_p116_foundation.py` | Layer 1 | 底座脚本 | State 底座计算 | a_share_core |
| `state_cache_builder.py` | Layer 1 | 底座脚本 | State 缓存生成 | a_share_core |
| `strategy_signal_ledger.py` | Layer 1 | 底座脚本 | 三策略信号账本 | a_share_core |
| `forward_observation_ledger.py` | Layer 1 | 底座脚本 | 前向观察账本 | a_share_core |
| `daily_research_brief.py` | Layer 1 | 底座脚本 | 每日总报生成 | a_share_core |
| `calibration_trigger.py` | Layer 1 | 底座脚本 | 三重门检查 + 校准 | 独立调用 |
| `search_*_optimal_state.py` | Layer 1 | 底座脚本 | State 组合搜索 | 独立调用 |
| `bootstrap_stats.py` | Layer 1 | 底座脚本 | Bootstrap CI | 独立调用 |

### 3.2 数据采集脚本

| 脚本 | Layer | 功能 | 数据源 |
|------|-------|------|--------|
| `blackwolf_client.py` | 1 | 黑狼 API 客户端 | api.fxyz.site |
| `download_daily.py` | 1 | A 股日线下载 | 黑狼 API |
| `collect_macro_multisource.py` | 1 | 多源宏观数据采集 | AKShare / Tushare / iFinD |
| `build_ifind_macro_db.py` | 1 | iFinD 宏观指标入库 | iFinD Excel/CSV |
| `import_ifind_industry_chain_excel.py` | 1 | 产业链画像导入 | iFinD Excel |
| `build_chain_dynamics_phase1.py` | 1 | 期货数据填 chain_dynamics | AKShare 期货 |
| `build_industry_position.py` | 1 | 行业景气度计算 | chain_dynamics + ETF State |

### 3.3 策略信号模块

| 模块 | 路径 | 功能 |
|------|------|------|
| `vcp.py` | `backtest/strategy_signals/` | VCP 入场信号（breakout/breakout_no_vol/breakout_weak_vol/contraction） |
| `ma2560.py` | `backtest/strategy_signals/` | 2560 入场信号（golden_cross/strong_hold/aligned/death_cross_exit/bearish） |
| `bollinger_bandit.py` | `backtest/strategy_signals/` | 布林强盗入场信号（bb_bandit_long_entry）+ 递减均线出场 |
| `chandelier_exit.py` | `backtest/strategy_signals/` | ATR 吊灯（需持仓上下文，暂未接入账本） |
| `composite.py` | `backtest/strategy_signals/` | 组合回测引擎 |
| `engine.py` | `backtest/` | 回测引擎核心（State 数据加载） |

---

## 4. 配置文件清单

| 配置文件 | 用途 |
|----------|------|
| `config/settings.yaml` | 全局配置（黑狼 API、State 参数、筛选条件） |
| `config/strategy_registry.json` | 策略注册表（验证状态、假设、输出路径） |
| `config/ma2560_state_market_match_rule.json` | 2560 State 匹配规则 |
| `config/vcp_state_market_match_rule.json` | VCP State 匹配规则 |
| `config/industry_rotation_assets.json` | 行业 ETF 资产映射 |
| `config/industry_etf_proxy_whitelist.json` | 代理 ETF 人工审核白名单 |
| `config/ifind_macro_indicators.json` | iFinD 宏观指标注册表 |
| `config/macro_data_sources.json` | 宏观数据源配置 |
| `config/fixed_columns.yaml` | 固定 34 字段顺序定义 |
| `config/deepseek_context.md` | DeepSeek LLM 上下文注入 |

---

## 5. 输出产物清单

### 5.1 日频产物

| 产物 | 路径 | 格式 | 消费者 |
|------|------|------|--------|
| Foundation DB | `outputs/p116_foundation_{date}/p116_foundation.duckdb` | DuckDB | 全系统 |
| State 缓存 | `outputs/state_cache/state_{type}_{date}.json` | JSON | signal_ledger, reminder |
| 市场资产 State | `outputs/market_assets_state/market_assets_state_{date}.json` | JSON/CSV | macro_chain_prior |
| 策略信号 | `outputs/strategy_signals/strategy_signal_daily_{date}.json` | JSON | 全下游 |
| 宏观先验 | `outputs/macro_chain_prior/macro_chain_prior_{date}.json` | JSON/CSV | reminder, brief |
| 策略提醒 | `public/strategy_reminder_{date}.html` | HTML | 用户 |
| 每日总报 | `public/daily_research_brief_{date}.html` | HTML | 用户 |
| 前向观察 | `outputs/forward_observation/forward_observation_{date}.json` | JSON/CSV | calibration |
| 适配度观察 | `outputs/strategy_fit_observer/fit_log_{date}.json` | JSON/CSV | calibration |
| 全三 E/F 池 | `outputs/p116_daily_all_three_ef/p116_all_three_ef_{date}.json` | JSON/CSV | market_phase |
| 行业 ETF 配置 | `outputs/etf_config/industry_etf_config_{date}.json` | JSON | macro_chain_prior |
| iFinD 行业 | `outputs/ifind/industry_{date}.json` | JSON | signal_ledger |

### 5.2 按需产物

| 产物 | 路径 | 格式 | 触发方式 |
|------|------|------|----------|
| 校准报告 | `outputs/calibration/calibration_{date}.json` | JSON | calibration_trigger |
| 策略评估 | `outputs/strategy_evaluation/{strategy}_optimal_state_search_*.json` | JSON | search_* 脚本 |
| 项目报告 | `outputs/project/{strategy}_optimal_state_search.md` | MD | search_* 脚本 |
| 跨期验证 | `outputs/stability_validation/stability_*.json` | JSON | validate_state_combo |
| 绩效归因 | `outputs/attribution/attribution_report_*.json` | JSON | performance_attribution |
| Run Card | `outputs/run_cards/{run_id}.json` | JSON | 校准/验证运行 |
| 市场阶段 | `outputs/market_phase/market_phase_{date}.json` | JSON | classify_market_phase |

---

## 6. 部署架构

### 6.1 当前部署：本地单机

```text
/Users/lv111101/Documents/hermass-observer-product/
├── config/                    # 配置文件
├── data/                      # 原始数据（黑狼/iFinD/期货）
├── scripts/                   # Python 脚本（~90 个）
├── backtest/                  # 回测引擎和策略信号模块
├── agently_adapter/           # Agently 运行时层
│   ├── a_share_core.py        #   Layer 2: Shared Core Layer
│   ├── a_share_actions.py     #   Layer 3: Action 契约层
│   ├── agently_a_share_flow.py #   Layer 3: Core Flow 编排
│   ├── agently_daily_flow.py  #   Layer 3: Full Workflow Compatibility Flow
│   └── stockpool_daily_runner.py # Layer 2-3: Runner 兼容层
├── outputs/                   # 所有输出产物
│   ├── p116_foundation_*/     # State 底座（每日一个目录）
│   ├── state_cache/           # State 缓存
│   ├── strategy_signals/      # 策略信号账本
│   ├── strategy_evaluation/   # 策略评估
│   ├── forward_observation/   # 前向观察
│   ├── calibration/           # 校准报告
│   ├── macro_chain_prior/     # 宏观先验
│   ├── market_phase/          # 市场阶段
│   ├── industry_chain/        # 产业链证据
│   └── ...
├── public/                    # HTML 页面（本地 HTTP 服务）
├── docs/                      # 文档（24+ 份）
├── fixtures/                  # 固定产物
├── reports/                   # 报告（专利/审计）
└── .venv/                     # Python 虚拟环境
```

### 6.2 运行时依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | 3.14 | 运行时 |
| DuckDB | 1.3+ | 数据存储和查询 |
| NumPy | 2.4+ | Bootstrap CI 计算 |
| pandas | — | 数据处理 |
| PyYAML | — | 配置解析 |
| requests | — | API 调用 |
| AKShare | 1.18+ | 期货/宏观数据 |

### 6.3 扩展方向

| 方向 | 说明 | 复杂度 |
|------|------|--------|
| 云端部署 | 将 outputs/ 和 public/ 迁移到云存储，脚本定时执行 | 中 |
| API 服务化 | FastAPI 已暴露 `/run-daily` / `/run-full-daily`，下一步加执行状态查询 | 中 |
| MCP 集成 | 5 个 MCP 工具接入 Claude Desktop（见 MCP_TOOLS_DESIGN.md） | 低 |
| 分布式回测 | 将 search_* 脚本并行化，利用多核/多机 | 高 |

### 6.4 术语速查

| 术语 | 含义 | 对应文件/接口 |
|------|------|--------------|
| **core flow** | 最小核心链路（7 步） | `agently_a_share_flow.py` / `/run-daily` |
| **full compatibility workflow** | 全量兼容闭环（core + public extensions） | `agently_daily_flow.py` / `/run-full-daily` |
| **shared core layer** | 最小核心链路的唯一共享实现 | `a_share_core.py` |
| **core outputs** | 最小核心链路产物清单 | `verify_core_outputs()` |
| **public extensions** | runner 独有的扩展产物 | `public_extension_paths()` |
| **verify_core_outputs** | 只校验 core outputs | `a_share_core.verify_core_outputs()` |
| **verify_public_outputs** | 校验 core outputs + public extensions | `a_share_core.verify_public_outputs()` |

---

## 7. 文档清单

| 序号 | 文档 | 定位 |
|------|------|------|
| 1 | `MULTICYCLE_STATE_STRATEGY_WHITEPAPER.md` | 系统完整方法论总纲 |
| 2 | `STRATEGY_DEFINITIONS.md` | 三策略权威定义 |
| 3 | `STRATEGY_COLLABORATION_GUIDE.md` | 三策略协作说明（面向订阅者） |
| 4 | `USER_MANUAL.md` | 系统用户手册 |
| 5 | `MVP_DEMO_PRESENTATION.md` | MVP 试用展示投屏文档 |
| 6 | `MVP_MEETING_Q&A.md` | MVP 会议 Q&A 预判手册 |
| 7 | `CHIEF_ECONOMIST_BRIEF_TEMPLATE.md` | 首席报告模板 |
| 8 | `CHIEF_BRIEF_GENERATOR_SPEC.md` | 首席报告生成器规范 |
| 9 | `MACRO_SCORING_MODEL.md` | 宏观评分四维模型 |
| 10 | `CHAIN_PROSPERITY_SCORING_MODEL.md` | 产业链景气度评分模型 |
| 11 | `CHAIN_DATA_POPULATION_PLAN.md` | 产业链数据填充方案 |
| 12 | `CHAIN_EVENT_SCANNER_SPEC.md` | 产业链事件扫描器设计 |
| 13 | `CHAIN_EVENT_SCANNER_DATA_SOURCE_RESEARCH.md` | 事件扫描数据源调研 |
| 14 | `industry_chain_dynamics_spec.md` | 产业链三表 Schema |
| 15 | `W1_MN1_STRATEGY_VALIDATION_FRAMEWORK.md` | W1×MN1 组合验证框架 |
| 16 | `W1_MN1_ENVIRONMENT_LABELS.md` | W1×MN1 环境标签体系 |
| 17 | `W1_MN1_LABEL_IMPLEMENTATION_SPEC.md` | W1×MN1 标签工程实现规范 |
| 18 | `strategy_environment_fit_scoring_design.md` | 适配度评分模型 |
| 19 | `TRIPLE_RESONANCE_ENHANCEMENT.md` | 三重共振增强模型 |
| 20 | `MARKET_PHASE_IDENTIFICATION.md` | 市场阶段识别框架 |
| 21 | `STATE_BASE_EXTENSION_DESIGN.md` | State 底座扩展设计 |
| 22 | `MONEYFLOW_EVIDENCE_MODEL.md` | 资金流证据层模型 |
| 23 | `MONEYFLOW_IMPLEMENTATION_SPEC.md` | 资金流实现规范 |
| 24 | `STRATEGY_PERFORMANCE_ATTRIBUTION.md` | 策略绩效归因框架 |
| 25 | `STATE_COMBO_CROSS_PERIOD_VALIDATION_DESIGN.md` | 跨期稳定性验证 |
| 26 | `BOOTSTRAP_CI_IMPLEMENTATION_GUIDE.md` | Bootstrap CI 实现方案 |
| 27 | `CALIBRATION_TRIGGER_DESIGN.md` | 校准触发机制设计 |
| 28 | `CALIBRATION_TRIGGER_IMPLEMENTATION_SPEC.md` | 校准触发实现规范 |
| 29 | `RUN_CARD_SPEC.md` | Run Card 复现元数据标准 |
| 30 | `WALK_FORWARD_VALIDATION_DESIGN.md` | Walk-Forward 验证（已废弃） |
| 31 | `MCP_TOOLS_DESIGN.md` | MCP 工具接口设计 |
| 32 | `new_strategy_integration_guide.md` | 新策略标准接入规范 |
| 33 | `STRATEGY_EXECUTION_SPEC.md` | 三策略完整执行规范 |
| 34 | `STRATEGY_EXECUTION_2560_BOLLINGER_DETAIL.md` | 2560/布林强盗执行细节 |
| 35 | `SYSTEM_EVOLUTION_ROADMAP.md` | 三阶段演进路线图 |
| 36 | `SYSTEM_ARCHITECTURE.md` | 系统整体架构（本文） |
| 37 | `AGENTLY_A_SHARE_INTEGRATION_PLAN.md` | Agently A 股集成路线图 |
| 38 | `A_SHARE_SERVICE_API.md` | A 股服务 API 接口文档 |
| 39 | `AGENT_PERSPECTIVE_ARCHITECTURE.md` | Agent 视角体系架构设计 |
| 40 | `OPERATIONS_MANUAL.md` | 系统运维手册 |
| 41 | `DATA_CONTRACT.md` | 数据契约 |
