# Hermass AI 认知检测与商业变现平台 — 项目落地计划

版本：v2.0
日期：2026-05-24
状态：规划文档（最终版）
决策来源：2026-05-24 团队会议共识 + DeepSeek 评审 + Claude 评审

---

## 会议共识摘要

1. **四大策略讨论终止**：团队对原 VCP/2560/布林强盗/吊灯四大策略展开式讨论缺乏认同与兴趣，不再作为项目推进主线。
2. **新核心诉求**：通过 AI 实现**个人认知的检测**与**商业变现**。
3. **角色转换**：从"策略研究系统"升级为"面向用户的 AI 认知交易中台"。
4. **验收标准**：用户能用自然语言与系统交互，获得个人认知画像与交易辅助，系统完成商业闭环。

## 关键决策记录

| 决策 | 结论 | 理由 |
|------|------|------|
| 美股/US 相关 | **已归档** | 系统专注 A 股，美股代码和文档仅作历史参考 |
| 独立 State 包迁移 | **不迁移，保持现状** | 现有 scripts/ 下的独立脚本已可工作，迁移是锦上添花而非必要条件，20 周时间不应花在代码重组上 |
| 产品语言 | **全中文平台** | 面向国内用户，所有交互、报告、文档、认知画像均为中文 |
| 认知检测上线时间 | **从 W15 提前到 W10** | 认知检测是核心差异化卖点，内测期（W14）必须有初步认知画像 |

---

## 第一章：项目定位与目标

### 1.1 新定位

```text
Hermass AI 认知交易中台
= State 数据底盘 + AI 多 Agent 协作层 + 用户认知检测引擎 + 商业变现层
```

核心问题从"哪个策略更好"转变为"**你适合什么样的交易方式**"。

### 1.2 核心目标

| 维度 | 目标 | 度量 |
|------|------|------|
| **认知检测** | 每个用户获得个性化认知画像 | 画像覆盖率 100%，特征 ≥ 12 维 |
| **对话交互** | 用户用自然语言完成全流程操作 | 自然语言意图识别准确率 ≥ 90% |
| **商业变现** | 完成认知服务付费闭环 | 支持 3 种变现模式运行 |
| **底座稳定** | State 底座 99.9% 可用 | 日频流水线成功率 ≥ 99%，单次故障恢复 ≤ 30min |
| **全中文平台** | 所有用户触点均为中文 | 对话、报告、认知画像、付费页面、用户手册零英文 |

### 1.3 用户画像

| 阶段 | 用户群 | 核心需求 | 付费意愿 |
|------|--------|----------|----------|
| 一阶段 | 私域种子用户（100-500 人） | "帮我搞清楚我的交易认知水平" | 内测免费，收集反馈 |
| 二阶段 | 付费订阅用户（500-5000 人） | "每天告诉我市场适不适合我" | 月费/年费订阅 |
| 三阶段 | 开放市场用户（5000+） | "AI 交易教练" | 分层付费 + 增值服务 |

---

## 第二章：核心基础模块建设

### 2.1 State 底座夯实

**当前状态**：Layer 2 State 底座已上线，具备 3 周期（MN1/W1/D1）State 计算能力，Foundation DB + State Cache 体系完整。

**会议后的新增要求**：

#### 2.1.1 架构收敛与边界加固

| 任务 | 当前问题 | 目标状态 | 工作量 |
|------|----------|----------|--------|
| `p116_core.py` 契约文档化 | 隐式约定分散在代码注释中 | 输出 `STATE_BASE_CONTRACT.md`，包含完整输入/输出 Schema、边界条件、不允许修改项清单 | 3 天 |
| Foundation DB Schema 版本锁定 | 建表语句分散在多个脚本 | 统一 `schema_v2.sql`，含版本号 + 迁移脚本 | 2 天 |
| State 缓存消费契约 | 下游直接读 JSON 字段，无版本检查 | 所有消费者启动时校验 `schema_version`，不匹配则终止 | 2 天 |
| 位置优先符号裁决测试 | 仅有隐式代码实现 | 编写 48 组边界 case 的单元测试 | 3 天 |

#### 2.1.2 双视角 State 体系

**背景**：系统存在两套 W1 State 计算方式。

| 视角 | 计算方式 | 适用场景 |
|------|----------|----------|
| `state_hex(D1, W1)` | D1 收盘价 vs W1 SR | 每日信号触发、适配度、前向观察 |
| `state_hex(W1, W1)` | W1 周线收盘价 vs W1 SR | 周线趋势判断、周度回测、周报 |

**已设计文档**：`docs/W1_STATE_DUAL_PERSPECTIVE_CALIBRATION.md`

**决策：不迁移，保持现状**。现有 `scripts/build_weekly_state_independent.py` 和 `scripts/build_monthly_state_independent.py` 已可独立工作。将它们重组为 `state_independent/` 包是锦上添花，不是平台建设的前提条件。20 周时间应聚焦 AI 中台和认知检测，不做代码重组。

**仅补充任务**：

| 任务 | 工作量 | 优先级 |
|------|--------|--------|
| 新建 `scripts/build_daily_state_independent.py`（补齐 D1 Agent 独立计算） | 半天 | P2 |
| 双视角差异月度校准（现有 validate_weekly_state.py 已可运行） | 无需额外工作 | — |

#### 2.1.3 数据一致性保障

| 任务 | 详细内容 | 验收标准 |
|------|----------|----------|
| 日频流水线原子性 | 将 12 步流水线包装为事务性流程，任一步失败则整批次标记 incomplete | 完整性检查脚本 `verify_daily_pipeline.py --date {date}` 输出 PASS/FAIL |
| 跨周期 State 一致性 | 检测 MN1/W1/D1 之间的计算依赖是否正确对齐（bisect 前向填充无漂移） | `scripts/verify_state_calculation.py` 全量校验通过 |
| 数据源切换降级 | 黑狼 API 不可用时自动切换 yfinance / AKShare 备用源 | 降级测试通过，切换延迟 ≤ 5s |

#### 2.1.3 测试验收标准

| 测试类型 | 覆盖范围 | 通过标准 | 输出产物 |
|----------|----------|----------|----------|
| **单元测试** | `p116_core.py` 全部函数 / `sr_calculator.py` 全部函数 / `d1_perspective.py` 对齐逻辑 / `ef_screener.py` 筛选逻辑 | 覆盖率 ≥ 90%，边界 case 全通过 | `tests/reports/unit_test_report_{date}.html` |
| **集成测试** | 完整日频流水线端到端 / Foundation DB 读写 / State Cache 生成→消费 / 策略信号账本生成 | 全链路数据一致性校验通过 | `tests/reports/integration_test_report_{date}.html` |
| **压力测试** | 5000 只股票 × 250 交易日历史回放 / DuckDB 并发读取性能 | 全量计算 ≤ 15min / 并发 10 读取无锁冲突 | `tests/reports/stress_test_report_{date}.html` |
| **回归测试** | 取 2025-06-01 至 2026-05-23 全量历史数据，逐日重跑对比 | 输出值差异 = 0（bit-exact） | `tests/reports/regression_test_report_{date}.html` |
| **稳定性报告** | 汇总以上四类测试结果，含通过率、失败项、修复记录 | 通过率 100% | `tests/reports/core_module_stability_report.md` |

**测试基础设施**：

```text
tests/
├── unit/
│   ├── test_p116_core.py
│   ├── test_sr_calculator.py
│   ├── test_d1_perspective.py
│   └── test_ef_screener.py
├── integration/
│   ├── test_daily_pipeline.py
│   ├── test_state_cache_flow.py
│   └── test_signal_ledger_flow.py
├── stress/
│   ├── test_full_market_backfill.py
│   └── test_concurrent_read.py
├── regression/
│   └── test_historical_bit_exact.py
├── fixtures/
│   └── (标准测试数据集)
└── reports/
    └── (自动生成报告)
```

---

### 2.2 切片模块（Slicing Module）建设

**定义**：切片模块是 State 底座与 AI 中台之间的**数据切割与流转层**，负责将原始 State 数据按用户/策略/时间维度切片，以标准化的 Data Contract 交付给中台各 Agent 消费。

#### 2.2.1 切片维度定义

| 切片维度 | 说明 | 示例 |
|----------|------|------|
| **用户切片** | 按用户关注列表/持仓切片 | 用户 A 关注的 50 只股票的 State 快照 |
| **策略切片** | 按策略信号过滤切片 | 2560 策略 golden_cross 信号的 State 分布 |
| **时间切片** | 按时间窗口切片 | 近 20 日 E/F 状态变迁路径 |
| **行业切片** | 按申万一级行业切片 | 电子行业的 D1 State 分布热力图 |
| **认知切片** | 按用户认知特征切片 | 适合"高波动偏好"用户的状态组合 |

#### 2.2.2 切片模块架构

```text
                        ┌──────────────────────┐
                        │   State 底座 (Layer 2) │
                        │   Foundation DB        │
                        │   + State Cache        │
                        └──────────┬───────────┘
                                   │
                                   ▼
                        ┌──────────────────────┐
                        │   切片引擎             │
                        │   slice_engine.py     │
                        │   - 维度解析           │
                        │   - 过滤 & 聚合        │
                        │   - 格式标准化         │
                        │   - 缓存管理           │
                        └──────────┬───────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
   ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
   │ UserSlice        │ │ StrategySlice    │ │ CognitiveSlice   │
   │ (用户关注切片)    │ │ (策略信号切片)    │ │ (认知画像切片)    │
   └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘
            │                    │                    │
            └────────────────────┼────────────────────┘
                                 ▼
                        ┌──────────────────────┐
                        │  数据契约层            │
                        │  data_contract.py     │
                        │  - Schema 校验         │
                        │  - 版本兼容检查        │
                        │  - 异常兜底            │
                        └──────────┬───────────┘
                                   │
                                   ▼
                        ┌──────────────────────┐
                        │  AI 中台 (Agent 消费) │
                        └──────────────────────┘
```

#### 2.2.3 切片模块任务清单

| 编号 | 任务 | 输入 | 输出 | 工作量 |
|------|------|------|------|--------|
| S-01 | `slice_engine.py` 核心实现 | Foundation DB + State Cache | 标准化切片 JSON | 5 天 |
| S-02 | `user_slice.py` 用户维度切片 | 用户关注列表/持仓 | user_slice_{user_id}_{date}.json | 3 天 |
| S-03 | `strategy_slice.py` 策略维度切片 | strategy_signal_daily | strategy_slice_{strategy_id}_{date}.json | 3 天 |
| S-04 | `cognitive_slice.py` 认知维度切片 | 用户认知画像 + State 数据 | cognitive_slice_{user_id}_{date}.json | 4 天 |
| S-05 | `data_contract.py` 数据契约校验 | 任意切片输出 | 校验通过/失败 + 错误详情 | 3 天 |
| S-06 | 切片缓存层 `slice_cache.py` | 切片请求 | 缓存命中/回源 + TTL 管理 | 2 天 |
| S-07 | 切片模块集成测试 | 全切片类型 | 集成测试报告 | 3 天 |

#### 2.2.4 数据契约标准

```json
{
  "$schema": "https://hermass.dev/slice-contract/v1",
  "contract_version": "1.0.0",
  "slice_type": "user_slice",
  "slice_id": "user_001_20260524",
  "generated_at": "2026-05-24T16:30:00+08:00",
  "source": {
    "foundation_db": "outputs/p116_foundation_20260524/p116_foundation.duckdb",
    "state_cache": "outputs/state_cache/state_ef_20260524.json",
    "schema_version": "2.0"
  },
  "slice_params": {
    "user_id": "user_001",
    "date": "2026-05-24",
    "stock_codes": ["000001.SZ", "600519.SH"],
    "cycles": ["D1", "W1", "MN1"]
  },
  "data": {
    "stocks": [...],
    "summary": {...}
  },
  "integrity": {
    "checksum": "sha256:abc123...",
    "row_count": 50,
    "expected_row_count": 50
  }
}
```

---

### 2.3 核心模块交付里程碑

```text
M1: State 底座稳定性报告通过（全部测试 100% PASS）        → 第 3 周末
M2: 切片引擎上线，支持 3 种切片维度（User/Strategy/Time） → 第 5 周末
M3: 数据契约层校验 100% 覆盖，Schema 版本管理就绪        → 第 6 周末
M4: 核心模块稳定性报告输出（含单元/集成/压力/回归测试）    → 第 6 周末
```

---

## 第三章：AI 交易中台整体规划与搭建

### 3.1 中台定位

AI 交易中台是连接**用户**、**数据底座**与**AI Agent** 的中间层，核心能力：

1. **多 Agent 编排**：管理多个专业化 AI Agent 的生命周期与协作
2. **对话交互引擎**：自然语言 → 意图识别 → Agent 路由 → 结果生成
3. **认知检测引擎**：分析用户行为数据，生成认知画像
4. **商业变现层**：会员体系 + 增值服务 + 认知报告付费

### 3.2 技术架构总览

```text
┌─────────────────────────────────────────────────────────────────────┐
│                          用户触达层                                   │
│  Lark IM │ 微信 │ Web Chat │ API                                    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     AI 交易中台 (Core Platform)                       │
│                                                                     │
│  ┌───────────────┐  ┌───────────────┐  ┌────────────────────────┐  │
│  │ 对话交互引擎    │  │ Agent 编排器   │  │ 认知检测引擎            │  │
│  │ Conversation   │  │ Agent         │  │ Cognitive Detection    │  │
│  │ Engine         │  │ Orchestrator  │  │ Engine                 │  │
│  └───────┬───────┘  └───────┬───────┘  └───────────┬────────────┘  │
│          │                  │                       │               │
│          └──────────────────┼───────────────────────┘               │
│                             ▼                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    数据切片层 (Slice Engine)                    │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      State 底座 (Layer 1-4)                          │
│  Foundation DB │ State Cache │ Strategy Signals │ Market Phase      │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.3 Agent 矩阵设计

| Agent 名称 | 角色定位 | 核心能力 | 依赖模型 |
|------------|----------|----------|----------|
| **Market Analyst** | 市场环境分析师 | 解读市场阶段、宏观环境、行业景气度 | DeepSeek / GPT-4o |
| **Strategy Advisor** | 策略适配顾问 | 评估用户与策略的匹配度，输出适配报告 | DeepSeek + 本地规则引擎 |
| **Cognitive Detective** | 认知检测师 | 分析用户交易行为，生成认知画像 | DeepSeek / 微调模型 |
| **Risk Guardian** | 风控守门人 | 持仓风险评估、止损止盈参考 | 本地规则引擎 + LLM |
| **Coach** | 交易教练 | 基于认知画像提供个性化训练建议 | DeepSeek |
| **Chief Brief** | 首席报告官 | 生成每日总报、策略提醒 | DeepSeek（已有基础） |
| **Monetization Butler** | 变现管家 | 引导付费转化、权益管理 | 规则引擎 + LLM |

### 3.4 Agent 协作流程

```text
用户消息 "今天市场适合我吗？"
        │
        ▼
对话引擎 ──→ 意图识别: [market_query, personal]
        │
        ▼
编排器路由 ──→ Cognitive Detective: 获取用户认知画像
        │    → Market Analyst: 获取当前市场环境
        │    → Strategy Advisor: 评估策略适配度
        │
        ▼
编排器聚合 ──→ 生成个性化回复:
        │    "你的认知画像显示你偏好中长线趋势交易（特征1、特征2...）。
        │     当前市场处于趋势行进阶段，与你偏好的 2560 策略高度适配。
        │     近 20 日信号胜率统计为 62%，建议关注的 State 组合为..."
        │
        ▼
输出层 ──→ Lark/微信/Web 推送
```

### 3.5 对话交互引擎设计

#### 3.5.1 意图分类体系

| 一级意图 | 二级意图 | 示例问句 | 路由 Agent |
|----------|----------|----------|------------|
| **market_query** | market_phase | "现在市场什么阶段？" | Market Analyst |
| | sector_heat | "电子行业怎么样？" | Market Analyst |
| | macro_outlook | "宏观环境怎么样？" | Market Analyst |
| **personal_cognitive** | my_profile | "我的交易风格是什么？" | Cognitive Detective |
| | my_fit | "当前环境适合我吗？" | Strategy Advisor |
| | my_risk | "我该注意什么风险？" | Risk Guardian |
| **strategy_advice** | strategy_fit | "2560 适合现在吗？" | Strategy Advisor |
| | signal_explore | "有哪些好信号？" | Strategy Advisor |
| | exit_rule | "什么时候该走？" | Risk Guardian |
| **coaching** | learn_topic | "什么是 VCP 形态？" | Coach |
| | practice | "给我出个测试题" | Coach |
| **subscription** | upgrade | "怎么升级会员？" | Monetization Butler |
| | benefits | "高级版有什么功能？" | Monetization Butler |

#### 3.5.2 对话引擎模块

| 模块 | 路径 | 功能 | 工作量 |
|------|------|------|--------|
| `intent_router.py` | `platform/chat/intent_router.py` | NLP 意图识别 + Agent 路由 | 5 天 |
| `conversation_manager.py` | `platform/chat/conversation_manager.py` | 会话管理、上下文维护、多轮对话 | 4 天 |
| `response_composer.py` | `platform/chat/response_composer.py` | 合规过滤 + 多 Agent 结果聚合 + 格式输出 | 3 天 |
| `compliance_filter.py` | `platform/chat/compliance_filter.py` | 禁止措辞拦截、合规句式替换（复用现有模板） | 2 天 |
| `platform/chat/handlers/` | 各意图处理器 | market_handler / cognitive_handler / strategy_handler / coach_handler / subscription_handler | 8 天 |

### 3.6 Agent 接入规范

```python
# platform/agents/base_agent.py
class BaseAgent:
    agent_id: str
    agent_name: str
    system_prompt: str
    tools: list  # MCP tools
    input_schema: dict
    output_schema: dict

    def prepare_context(self, user_id: str, slice_data: dict) -> str:
        """准备 LLM 上下文"""
        pass

    def execute(self, user_message: str, context: dict) -> dict:
        """执行 Agent 推理"""
        pass

    def validate_output(self, output: dict) -> bool:
        """校验输出合规性"""
        pass
```

---

## 第四章：用户认知检测模块

### 4.1 认知检测定义

用户认知检测是通过分析用户的**交易行为数据**和**交互行为数据**，构建多维认知画像，帮助用户认识自己的交易模式、偏好、优势与盲区。

### 4.2 认知特征维度（≥ 12 维）

| 维度 | 特征名 | 数据来源 | 计算方式 |
|------|--------|----------|----------|
| **时间偏好** | holding_period_preference | 历史持仓记录 | 平均持仓天数的分位数 |
| **风险偏好** | risk_tolerance_level | 最大回撤 / 波动率暴露 | 持仓股票的平均 ATR% 分位数 |
| **策略吻合度** | strategy_alignment | 策略信号账本 vs 用户操作 | 用户操作与策略信号方向一致的比率 |
| **反应速度** | reaction_speed | 信号→操作的时间延迟 | 信号触发到用户操作的时间间隔分布 |
| **决策独立性** | decision_autonomy | 是否跟风 vs 独立判断 | AI 建议与用户操作的偏差比率 |
| **情绪稳定性** | emotional_stability | 操作频率波动 | 交易频率的变异系数 |
| **学习曲线** | learning_curve_score | 认知检测周期变化 | 连续周期的策略吻合度趋势 |
| **认知偏差** | cognitive_bias_flags | 行为模式检测 | 处置效应、锚定效应、过度自信等标签 |
| **State 敏感度** | state_sensitivity | D1/W1/MN1 State 与操作关联 | 不同 State 下用户操作成功率 |
| **规模管理** | position_sizing_discipline | 仓位变化模式 | 仓位变异系数 vs 合理范围 |
| **止损纪律** | stop_loss_discipline | 止损执行率 | 触发止损条件后实际执行的比例 |
| **复盘习惯** | review_frequency | 交互日志 | 主动查询历史信号的频次 |

### 4.3 认知画像输出

```json
{
  "user_id": "user_001",
  "profile_version": "v2.3",
  "generated_at": "2026-05-24",
  "data_period": {"from": "2026-03-01", "to": "2026-05-24"},
  "sample_size": {"trades": 47, "signals_viewed": 230, "questions_asked": 89},
  "confidence": 0.78,
  "summary": "你是一位中长线趋势交易者，偏好低换手、高胜率策略...",
  "strengths": ["止损纪律性高", "State 敏感度优秀", "不追高"],
  "blind_spots": ["对 VCP 收缩形态识别不足", "在震荡市中过度交易"],
  "recommended_path": "建议以 2560 为主策略，VCP 为辅助信号确认工具...",
  "dimensions": {
    "holding_period_preference": {"value": "medium_long", "score": 72, "percentile": 78},
    "risk_tolerance_level": {"value": "moderate", "score": 55, "percentile": 52},
    "strategy_alignment": {"value": 0.68, "trend": "improving"},
    ...
  }
}
```

### 4.4 认知检测数据流

```text
用户交易行为 ──→ 行为日志采集
        │
用户交互行为 ──→ 对话日志采集
        │
        ▼
behavior_ingestor.py ──→ cognitive_ledger.duckdb
        │
        ▼
cognitive_scorer.py  ──→ 12 维特征计算
        │
        ▼
cognitive_profile_builder.py ──→ cognitive_profile_{user_id}_{date}.json
        │
        ▼
Cognitive Detective Agent ──→ 自然语言解读 → 用户
```

### 4.5 认知检测模块任务清单

| 编号 | 任务 | 工作量 |
|------|------|--------|
| C-01 | `behavior_ingestor.py` 行为日志采集器 | 5 天 |
| C-02 | `cognitive_ledger.py` 认知账本数据库 | 3 天 |
| C-03 | `cognitive_scorer.py` 12 维特征计算引擎 | 7 天 |
| C-04 | `cognitive_profile_builder.py` 画像构建器 | 4 天 |
| C-05 | `cognitive_bias_detector.py` 认知偏差检测 | 5 天 |
| C-06 | Cognitive Detective Agent 实现 | 5 天 |
| C-07 | 认知检测模块测试 | 4 天 |

---

## 第五章：商业变现路径设计

### 5.1 变现模式总览

| 模式 | 描述 | 定价参考 | 目标转化率 |
|------|------|----------|-----------|
| **免费层** | 每日市场简报 + 基础 State 查询（3 次/日） | 免费 | N/A（引流） |
| **基础会员** | 无限制查询 + 个人认知画像（月度更新） + 策略适配建议 | ¥99/月 或 ¥899/年 | 15% |
| **高级会员** | 基础全部 + 实时认知检测 + AI 交易教练 + 优先级 Agent 响应 | ¥299/月 或 ¥2699/年 | 5% |
| **认知深度报告** | 单次购买深度认知分析报告（12 维 + 行为建议） | ¥49/次 | 8% |
| **企业/机构版** | 团队认知分析 + 批量 State 数据 + API 接入 | 定制报价 | B2B 线索 |

### 5.2 变现技术实现

| 模块 | 路径 | 功能 |
|------|------|------|
| `subscription_manager.py` | `platform/monetization/subscription_manager.py` | 会员状态管理、权益校验 |
| `tier_gate.py` | `platform/monetization/tier_gate.py` | 功能门控、按 Tier 放行 |
| `usage_meter.py` | `platform/monetization/usage_meter.py` | 用量计量（免费层 3 次/日限制） |
| `payment_webhook.py` | `platform/monetization/payment_webhook.py` | 支付回调处理（微信/支付宝） |
| `monetization_butler.py` | `platform/agents/monetization_butler.py` | 变现管家 Agent |

### 5.3 商业闭环验证

```text
免费用户 ──→ 体验基础功能 ──→ 获取认知画像预览
                                         │
                                         ▼
                               "想了解完整的交易认知报告吗？"
                                         │
                                  ┌──────┴──────┐
                                  ▼              ▼
                            基础会员         深度报告
                            ¥99/月          ¥49/次
                                  │              │
                                  └──────┬──────┘
                                         ▼
                                   高级会员 ¥299/月
                                   "每日认知更新 + AI 教练"
```

### 5.4 变现模块任务清单

| 编号 | 任务 | 工作量 |
|------|------|--------|
| MZ-01 | `subscription_manager.py` + `tier_gate.py` | 5 天 |
| MZ-02 | `usage_meter.py` 免费层用量计量 | 2 天 |
| MZ-03 | `payment_webhook.py` 支付集成 | 5 天 |
| MZ-04 | Monetization Butler Agent | 4 天 |
| MZ-05 | 层级功能开关配置系统 | 3 天 |
| MZ-06 | 支付流程端到端测试 | 3 天 |

---

## 第六章：全周期推进时间表

### 6.1 三阶段总体规划

```text
Phase 1: 底座夯实 + 切片上线           Phase 2: AI 中台搭建                       Phase 3: 认知+变现闭环
（第 1-6 周）                          （第 7-14 周）                              （第 15-20 周）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
State 底座测试 → 切片引擎 → 数据契约    对话引擎 → Agent 矩阵 → MCP 工具升级      认知检测上线 → 变现层对
                                                                               接 → 闭环验证

核心产物:                              核心产物:                                  核心产物:
- 稳定性报告                            - 自然语言对话 MVP                         - 认知画像系统
- 切片引擎 + 3 种切片                    - 7 Agent 矩阵                            - 订阅+付费系统
- 数据契约 1.0                          - 意图路由链路                             - 端到端商业闭环
```

### 6.2 详细时间表

#### Phase 1：底座夯实 + 切片上线（第 1-6 周）

| 周次 | 里程碑 | 交付物 | 责任人 | 验收标准 |
|------|--------|--------|--------|----------|
| W1 | State 底座契约化 | `STATE_BASE_CONTRACT.md`、`schema_v2.sql` | 后端负责人 | 契约文档评审通过，Schema 版本升级完成 |
| W2 | 单元测试 + 集成测试 | unit/integration test suite | 测试工程师 | 覆盖率 ≥ 90%，核心路径全部 PASS |
| W3 | 压力测试 + 回归测试 + 稳定性报告 | stress/regression test + stability report | 测试工程师 + 后端 | bit-exact 重现通过，稳定性报告 ≥ 99% |

| W4 | 切片引擎核心开发 | `slice_engine.py`、`user_slice.py`、`strategy_slice.py` | 后端负责人 | 3 种切片类型可正常生成 |
| W5 | 切片引擎完成 + 数据契约 | `data_contract.py`、`slice_cache.py`、`cognitive_slice.py` | 后端负责人 | 数据契约校验 100% 通过 |
| W6 | Phase 1 集成验收 | 完整测试报告 + 切片模块 API 文档 | 全团队 | 所有 M1-M4 里程碑通过 |

#### Phase 2：AI 中台搭建（第 7-14 周）

| 周次 | 里程碑 | 交付物 | 责任人 | 验收标准 |
|------|--------|--------|--------|----------|
| W7 | 对话引擎基础 | `intent_router.py`、`conversation_manager.py` | AI 工程师 | 5 类意图识别准确率 ≥ 85% |
| W8 | 对话引擎完善 | `response_composer.py`、`compliance_filter.py` | AI 工程师 | 合规过滤零漏过 |
| W9 | Market Analyst + Strategy Advisor Agent | Agent + MCP tools + 策略适配推荐 | AI 工程师 | 市场查询准确率 ≥ 90%，策略推荐与 State 数据一致 |
| W10 | 认知画像基础版（6 维）+ Risk Guardian | 6 维认知画像 + 风控守门人 | AI 工程师 + 数据 | 基于交互行为的 6 维认知画像可输出 |
| W11 | Coach Agent + 认知检测 V1 | 交易教练 + 认知偏差检测 | AI 工程师 | 教练建议有据可查，认知偏差检测可运行 |
| W12 | Monetization Butler Agent + 意图全覆盖 | 变现管家 + 所有意图 handler 就绪 | AI 工程师 | 10 种二级意图全部路由正确 |
| W14 | Phase 2 集成验收 + 内测启动 | 中台可对话 MVP + 内测用户 100 人 | 全团队 | 端到端对话流程验收通过 |

#### Phase 3：认知+变现闭环（第 15-20 周）

| 周次 | 里程碑 | 交付物 | 责任人 | 验收标准 |
|------|--------|--------|--------|----------|
| W15 | 行为日志采集上线 | `behavior_ingestor.py` + `cognitive_ledger.duckdb` | 后端 + 数据 | 行为数据无丢失采集 |
| W16 | 认知评分引擎 | `cognitive_scorer.py`（12 维） | 数据工程师 | 12 维特征全量计算 |
| W17 | 认知画像构建 + 变现基础层 | `cognitive_profile_builder.py` + `subscription_manager.py` | 后端 | 画像生成 + 会员状态管理 |
| W18 | 支付集成 + 层级门控 | `payment_webhook.py` + `tier_gate.py` + `usage_meter.py` | 后端 | 支付→开通→权益生效闭环 |
| W19 | 端到端商业闭环测试 | 全链路测试（注册→画像→付费→服务） | 全团队 | 闭环全部通过 |
| W20 | 正式发布 | V2.0 Release + 运维手册 + 用户文档 | 全团队 | 发布检查清单全部通过 |

### 6.3 责任人角色定义

| 角色 | 职责范围 | 建议人数 |
|------|----------|----------|
| **项目负责人** | 整体进度把控、风险管理、对外沟通 | 1 |
| **后端负责人** | State 底座、切片引擎、数据契约、认知账本 | 1 |
| **AI 工程师** | 对话引擎、Agent 实现、LLM Prompt 工程 | 1-2 |
| **数据工程师** | 认知检测引擎、行为数据分析、画像构建 | 1 |
| **测试工程师** | 测试用例编写、自动化测试、稳定性报告 | 1 |
| **前端工程师**（可选） | Web Chat 界面、管理后台 | 0-1 |

**核心团队最小配置**：3 人（项目负责人兼后端 + AI 工程师 + 数据工程师）

---

## 第七章：项目风险与应对预案

### 7.1 技术风险

| 风险编号 | 风险描述 | 影响等级 | 发生概率 | 应对预案 |
|----------|----------|----------|----------|----------|
| R-T01 | State 底座回归测试未 100% bit-exact 重现 | 高 | 中 | 优先排查已知差异点（浮点精度、数据源版本），允许可控差异并文档记录，差异 ≤ 0.01% 可接受 |
| R-T02 | LLM API 不稳定（DeepSeek 限流/宕机） | 高 | 中 | 实现多模型 fallback（DeepSeek → GPT-4o → 本地小模型）；对话降级为预设模板回复 |
| R-T03 | DuckDB 并发读写锁冲突 | 中 | 高 | 严格限制写操作为单进程串行；读操作用 `read_only=True` 模式；增加重试机制 |
| R-T04 | MCP 工具与 LLM 上下文窗口超限 | 中 | 中 | 切片数据压缩；只传摘要而非全量数据；分级加载策略 |
| R-T05 | 数据源 API 不稳定（黑狼/ifind 配额） | 中 | 高 | 已有 yfinance / AKShare 备用源；增加数据缓存层；提前预警配额消耗 |
| R-T06 | AI Agent 输出越界（合规风险） | 高 | 中 | 强制 `compliance_filter.py` 前置过滤；所有输出经合规检查后再返回用户；敏感词库持续更新 |

### 7.2 产品风险

| 风险编号 | 风险描述 | 影响等级 | 发生概率 | 应对预案 |
|----------|----------|----------|----------|----------|
| R-P01 | 用户认知画像准确度不足，用户不信任 | 高 | 中 | 先开放需较少数据的基础维度（5-6 维），积累数据后逐步开放全 12 维；展示置信度；允许用户反馈修正 |
| R-P02 | 付费转化率低于预期 | 高 | 中 | 免费层提供足够价值吸引留存；认知画像预览作为核心转化钩子；A/B 测试定价策略 |
| R-P03 | 合规审查导致产品下架 | 极高 | 低 | 严格遵循"禁止投资建议"红线；所有 Agent 应答经合规过滤；法律顾问定期审查话术 |
| R-P04 | 用户活跃度持续下降 | 中 | 中 | 每日推送个性化市场简报（基于认知画像）；增加游戏化元素（认知成长曲线）；社区互动功能 |

### 7.3 管理风险

| 风险编号 | 风险描述 | 影响等级 | 发生概率 | 应对预案 |
|----------|----------|----------|----------|----------|
| R-M01 | 核心人员离职 | 高 | 低 | 代码 + 文档 + 知识库完整；每个模块至少 2 人可接手；关键决策记录在文档中 |
| R-M02 | 需求蔓延导致延期 | 中 | 高 | 严格 Phase 门控，每 Phase 结束 Review 范围；新需求进 backlog 而非当前 Phase |
| R-M03 | 外部依赖阻塞（支付资质审核等） | 中 | 中 | 提前启动支付资质申请；Phase 2 即开始对接流程；有 Mock 支付用于测试 |

### 7.4 风险缓解总表

| 缓解措施 | 对应风险 | 实施时间 |
|----------|----------|----------|
| 多模型 fallback 机制 | R-T02 | Phase 2 W8 前 |
| 合规过滤前置拦截 | R-T06, R-P03 | Phase 2 W8 |
| 数据源多路备份 | R-T05 | Phase 1 W1 |
| 认知画像置信度展示 | R-P01 | Phase 3 W17 |
| 免费层价值钩子设计 | R-P02 | Phase 3 W16 |
| 模块 Bus Factor ≥ 2 | R-M01 | 持续 |
| Phase Gate 范围锁死 | R-M02 | 每 Phase 启动时 |

---

## 第八章：验收标准总表

### 8.1 Phase 1 验收标准

| 编号 | 标准 | 度量方式 |
|------|------|----------|
| A-P1-01 | 单元测试覆盖率 ≥ 90% | `pytest --cov` 报告 |
| A-P1-02 | 集成测试全链路 PASS | 日频流水线端到端 10 次重复无失败 |
| A-P1-03 | 历史回归 bit-exact 重现率 ≥ 99.99% | 223 个交易日逐日对比 |
| A-P1-04 | 全量计算耗时 ≤ 15 min | 5000 只股票压力测试 |
| A-P1-05 | 切片引擎支持 3 种维度 | User / Strategy / Time 切片生成正确 |
| A-P1-06 | 数据契约校验覆盖率 100% | 任意非法切片被拦截 |
| A-P1-07 | 稳定性报告输出完成 | 文档评审通过 |

### 8.2 Phase 2 验收标准

| 编号 | 标准 | 度量方式 |
|------|------|----------|
| A-P2-01 | 意图识别准确率 ≥ 90% | 500 条标注测试集 |
| A-P2-02 | 对话多轮上下文保持 ≥ 5 轮 | 人工评测通过 |
| A-P2-03 | 合规过滤零漏过 | 1000 条越界用例测试 |
| A-P2-04 | 7 个 Agent 全部可正常推理 | 各 Agent 100 条测试通过 |
| A-P2-05 | MCP 工具可用数 ≥ 10 个 | 工具调用成功率 ≥ 95% |
| A-P2-06 | 端到端响应延迟 ≤ 8s（P95） | 压测 50 并发 |
| A-P2-07 | 100 人内测零严重事故 | 故障跟踪表 |

### 8.3 Phase 3 验收标准

| 编号 | 标准 | 度量方式 |
|------|------|----------|
| A-P3-01 | 认知画像 12 维全量产出 | 画像 JSON Schema 校验 |
| A-P3-02 | 画像更新周期 ≤ 7 天 | 自动调度验证 |
| A-P3-03 | 会员订阅→权益生效 ≤ 30s | 支付回调端到端 |
| A-P3-04 | 免费层限流准确无误 | 用量计量校验 |
| A-P3-05 | 商业闭环端到端可用 | 注册→对话→画像→付费→高级功能→续费 |
| A-P3-06 | 系统可用性 ≥ 99.5% | 30 天监控数据 |

---

## 第九章：附录

### 9.1 项目目录规划（Phase 2-3 新增）

```text
hermass-observer-product/
├── platform/                       # AI 交易中台（Phase 2 新增）
│   ├── __init__.py
│   ├── chat/                       # 对话交互引擎
│   │   ├── __init__.py
│   │   ├── intent_router.py
│   │   ├── conversation_manager.py
│   │   ├── response_composer.py
│   │   ├── compliance_filter.py
│   │   └── handlers/
│   │       ├── market_handler.py
│   │       ├── cognitive_handler.py
│   │       ├── strategy_handler.py
│   │       ├── coach_handler.py
│   │       └── subscription_handler.py
│   ├── agents/                     # Agent 矩阵
│   │   ├── __init__.py
│   │   ├── base_agent.py
│   │   ├── market_analyst.py
│   │   ├── strategy_advisor.py
│   │   ├── cognitive_detective.py
│   │   ├── risk_guardian.py
│   │   ├── coach.py
│   │   ├── chief_brief.py
│   │   └── monetization_butler.py
│   ├── cognitive/                  # 认知检测引擎
│   │   ├── __init__.py
│   │   ├── behavior_ingestor.py
│   │   ├── cognitive_ledger.py
│   │   ├── cognitive_scorer.py
│   │   ├── cognitive_profile_builder.py
│   │   ├── cognitive_bias_detector.py
│   │   └── schemas/
│   │       ├── cognitive_profile_v1.json
│   │       └── behavior_event_v1.json
│   ├── monetization/               # 商业变现层
│   │   ├── __init__.py
│   │   ├── subscription_manager.py
│   │   ├── tier_gate.py
│   │   ├── usage_meter.py
│   │   └── payment_webhook.py
│   ├── slice/                      # 切片引擎
│   │   ├── __init__.py
│   │   ├── slice_engine.py
│   │   ├── user_slice.py
│   │   ├── strategy_slice.py
│   │   ├── cognitive_slice.py
│   │   ├── data_contract.py
│   │   └── slice_cache.py
│   └── api/                        # API 层
│       ├── __init__.py
│       ├── mcp_tools.py
│       └── webhook_handlers.py
├── tests/                          # 测试（新增）
│   ├── unit/
│   ├── integration/
│   ├── stress/
│   ├── regression/
│   ├── fixtures/
│   └── reports/
└── config/
    └── platform/
        ├── agent_registry.json     # Agent 注册表
        ├── tier_config.yaml        # 会员层级配置
        └── intent_routing.yaml     # 意图路由规则
```

### 9.2 技术选型建议

| 层面 | 技术选型 | 理由 |
|------|----------|------|
| **LLM** | DeepSeek（主力） + GPT-4o（备选） | DeepSeek 性价比高，GPT-4o 作 fallback |
| **Agent 框架** | 自研轻量 Agent（基于现有 MCP 工具体系） | 避免 LangChain 等重框架的复杂度 |
| **对话存储** | SQLite / DuckDB | 与现有技术栈一致 |
| **支付** | 微信支付 + 支付宝（Lark 生态内可用 Lark 支付） | 覆盖主流支付方式 |
| **消息推送** | Lark 机器人（现有） + 微信公众号模板消息 | 复用现有 Lark 推送 + 扩展微信 |
| **监控告警** | 日志文件 + Lark 告警推送 | 轻量级，无需引入 Prometheus/Grafana |
| **API 网关** | FastAPI（如果独立 Web 服务）或 MCP stdio | 视部署方式决定 |

### 9.3 关键假设与依赖

| 假设 | 说明 | 如果不成立 |
|------|------|-----------|
| **用户有交易行为数据** | 认知检测需要用户的历史交易记录或模拟交易数据 | 初期仅提供基于交互行为的 6 维画像，待数据积累后升级 |
| **DeepSeek API 稳定可用** | 主力 LLM 依赖 DeepSeek | 自动切换至 GPT-4o fallback |
| **Lark 生态可承载变现** | 初期依托 Lark 机器人实现付费闭环 | 如受限则转向独立 Web 应用 + 微信支付 |
| **3 人核心团队稳定** | 最小团队配置 | 减少 Phase 3 非核心功能，聚焦认知+付费闭环 |
| **用户接受自然语言交互** | 目标用户愿意通过对话获取服务 | 增加预设按钮式交互作为兜底 |

---

> **文档状态**：待团队评审
> **下一步**：评审通过后，按 Phase 1 W1 启动执行
> **更新频率**：每 Phase 结束复盘更新

---

## 第十章：已完成工作盘点与最终路径

### 10.1 已交付文档清单（38 份）

| 类别 | 文档 | 状态 |
|------|------|------|
| **方法论总纲** | `MULTICYCLE_STATE_STRATEGY_WHITEPAPER.md` | 已完成 |
| | `SYSTEM_ARCHITECTURE.md` | 已完成 |
| | `SYSTEM_EVOLUTION_ROADMAP.md` | 已完成 |
| | `SYSTEM_CREDIBILITY_SUMMARY.md` | 已完成 |
| **策略定义** | `STRATEGY_DEFINITIONS.md`（含 ATR 吊灯） | 已完成 |
| | `STRATEGY_COLLABORATION_GUIDE.md`（四策略） | 已完成 |
| | `STRATEGY_EXECUTION_SPEC.md` | 已完成 |
| | `STRATEGY_EXECUTION_2560_BOLLINGER_DETAIL.md` | 已完成 |
| | `STRATEGY_PERFORMANCE_ATTRIBUTION.md` | 已完成 |
| **验证与校准** | `STATE_COMBO_CROSS_PERIOD_VALIDATION_DESIGN.md` | 已完成 |
| | `BOOTSTRAP_CI_IMPLEMENTATION_GUIDE.md` | 已完成 |
| | `CALIBRATION_TRIGGER_DESIGN.md` | 已完成 |
| | `CALIBRATION_TRIGGER_IMPLEMENTATION_SPEC.md` | 已完成 |
| | `RUN_CARD_SPEC.md` | 已完成 |
| | `DATA_DRIVEN_PATTERN_MINING_FRAMEWORK.md` | 已完成 |
| | `OPPORTUNITY_PATTERN_TO_SIGNAL_SPEC.md` | 已完成 |
| **宏观与产业链** | `MACRO_SCORING_MODEL.md` | 已完成 |
| | `MACRO_ENVIRONMENT_FILTER_RULES.md` | 已完成 |
| | `CHAIN_PROSPERITY_SCORING_MODEL.md` | 已完成 |
| | `CHAIN_DATA_POPULATION_PLAN.md` | 已完成 |
| | `CHAIN_EVENT_SCANNER_SPEC.md` | 已完成 |
| | `CHAIN_EVENT_SCANNER_DATA_SOURCE_RESEARCH.md` | 已完成 |
| | `industry_chain_dynamics_spec.md` | 已完成 |
| **State 体系** | `W1_MN1_STRATEGY_VALIDATION_FRAMEWORK.md` | 已完成 |
| | `W1_MN1_ENVIRONMENT_LABELS.md` | 已完成 |
| | `W1_MN1_LABEL_IMPLEMENTATION_SPEC.md` | 已完成 |
| | `W1_STATE_DUAL_PERSPECTIVE_CALIBRATION.md` | 已完成 |
| | `STATE_BASE_EXTENSION_DESIGN.md` | 已完成 |
| | `MONEYFLOW_EVIDENCE_MODEL.md` | 已完成 |
| | `MARKET_PHASE_IDENTIFICATION.md` | 已完成 |
| | `TRIPLE_RESONANCE_ENHANCEMENT.md` | 已完成 |
| **用户与展示** | `USER_MANUAL.md` | 已完成 |
| | `AI_QUERY_TEMPLATES.md` | 已完成 |
| | `MVP_DEMO_PRESENTATION.md` | 已完成 |
| | `MVP_MEETING_Q&A.md` | 已完成 |
| | `THREE_STRATEGIES_FOUNDER_VALIDATION_COMPARISON.md` | 已完成 |
| **项目管理** | `PROJECT_DELIVERY_PLAN_AI_COGNITIVE_PLATFORM.md` | 本文档 |

### 10.2 最终完整路径

```text
当前位置 → 目标：20 周交付 AI 认知交易中台 V2.0

Phase 1（第 1-6 周）：底座夯实 + 切片上线
  W1: State 底座契约化
      └─ STATE_BASE_CONTRACT.md + schema_v2.sql
  W2: 单元测试 + 集成测试
      └─ tests/unit/ + tests/integration/ 全覆盖
  W3: 压力测试 + 回归测试 + 稳定性报告
      └─ 5000 只 × 250 日回放，bit-exact 重现
  W4-5: 切片引擎 + 数据契约
      └─ slice_engine.py + data_contract.py
  W6: Phase 1 集成验收
      └─ 核心模块稳定性报告
         ↓
Phase 2（第 7-14 周）：AI 中台搭建
  W7-8: 对话引擎
      └─ intent_router.py + conversation_manager.py + compliance_filter.py
  W9:  Market Analyst + Strategy Advisor Agent
  W10: 认知画像基础版（6维）+ Risk Guardian Agent
  W11: Coach Agent + 认知检测 V1
  W12: Monetization Butler Agent + 意图全覆盖
  W14: 内测启动（100 人，已有初步认知画像）
         ↓
Phase 3（第 15-20 周）：认知升级 + 变现闭环
  W15-16: 认知评分引擎升级（12 维）
  W17-18: 商业变现层（订阅 + 支付 + 权益）
  W19: 端到端商业闭环测试
  W20: 正式发布 V2.0
```

### 10.3 当前阻塞项

| 阻塞项 | 影响 | 解除条件 |
|--------|------|----------|
| iFinD API 配额超限 | 宏观数据信用维度缺失 | Tushare 频率重置后补充 M1/M2/社融 |
| 前向观察样本积累中 | 校准未触发 | 2026-05-28 预计首次触发（4 天后） |
