# 我的观察台 / 转折概率系统三线交付 Codex 整合审计

日期：2026-07-02
审计者：Codex
输入：

- `docs/tasks/OBSERVATION_DECK_PRODUCT_SPEC_KIMI_20260702.md`
- `docs/tasks/TURNING_POINT_PROBABILITY_MVP_KIMI1_20260702.md`
- `docs/tasks/CLASSIC_STRATEGY_SIGNAL_SENTINEL_KIMI2_20260702.md`
- `data/research/conversations/22-我的观察台与转折概率系统产品收敛.md`

---

## 总结论

三条线总体方向正确，可以进入“正式改版总方案 + Phase 1 实施计划”。

但有三处需要统一口径后再写代码：

1. 首页 Phase 1 不展示真实概率数值，只展示时间窗状态变化与转折类型。
2. KIMI1 的概率引擎先作为独立证据产物，不在 MVP 阶段新增“第 7 Agent”。
3. KIMI2 的经典策略哨兵不能只覆盖 entry 类信号；但首页必须用中性“规则信号”表达，避免交易动作语言。

---

## 一、KIMI 产品方案审计

### 采纳

采纳以下结论：

- 首页命名：`我的观察台`。
- 内部代号：`转折雷达`。
- 首页路由：保持 `/`。
- 顶层导航：`观察 / 状态 / 研究 / 策略`。
- `/state-observer` 继续作为完整 State Workbench。
- 首页模块顺序：
  1. 观象指令栏
  2. 我的标的转折雷达
  3. 3D / 3W / 3M / 6M 多时间窗矩阵
  4. 经典策略信号灯
  5. 全市场转折 Top
  6. 系统健康

### 修正

1. `研究` 默认落地页需要先确认现有路由。
   - 若 `/research` 不存在，Phase 1 不新建复杂研究首页。
   - 顶层导航可先指向现有单标的研究入口或保留二级菜单。

2. Phase 1 不应写“概率较高 / 概率下降”等真实概率语义。
   - 概率引擎未上线前，只展示：
     - `转强早期`
     - `确认转强`
     - `强势延续`
     - `转弱预警`
     - `确认转弱`
     - `结构未破坏`
     - `证据不足`

3. 首页不能写“建议持续观察”。
   - 建议也是动作语义。
   - 替换为：`状态：持续观察中`、`证据不足`、`等待更多数据确认`。

### Phase 1 可实施范围

KIMI 的 Phase 1 范围可接受：

- 改 `web/templates/index.html`。
- 改 `web/templates/_top_nav.html`。
- `web/main.py` 只做首页数据聚合，不新增持久化 schema。
- 不改 State Cube / State Timeline 生成逻辑。
- 不新增概率引擎。

---

## 二、KIMI1 概率 MVP 审计

### 采纳

采纳时间窗定义：

- 3D = 3 个交易日
- 3W = 15 个交易日
- 3M = 66 个交易日
- 6M = 126 个交易日

采纳概率字段主方向：

- `prob_turn_up`
- `prob_turn_down`
- `prob_continue`
- `prob_false_breakout`
- `confidence`
- `evidence_items`
- `risk_flags`
- `bucket_sample_size`
- `prior_weight`
- `model_version`
- `updated_at`

采纳方法：

- Empirical Bayesian MVP。
- 历史 State 转移统计形成先验。
- 当前多周期证据做似然修正。
- 样本不足时粗化回退并收缩到全局先验。
- 输出 DuckDB + latest JSON。

### 修正

1. `future_return_n` 和 `outcome_label` 不应出现在前端 live API 默认响应。
   - 它们属于回测 / 校准 / ledger 字段。
   - live API 可在 debug 或 admin 模式返回，默认不暴露。

2. `prob_turn_up + prob_turn_down + prob_continue + prob_false_breakout = 1` 可以作为模型内部约束，但前端不要强调四类相加。
   - 用户只需要知道主要观察方向、置信度和证据。

3. 暂缓“新增第 7 个概率 Agent”。
   - 这会过早改动 MOE 主线。
   - Phase 1/2 先作为独立证据层，被 Research 页或观察台读取。
   - 等概率校准通过后，再评估是否进入 Agent 辩论。

4. `turning_type` 命名需要产品化。
   - 内部可用 `early_turn_up / confirmed_turn_up / continue / turn_down_warning / confirmed_turn_down / noise / uncertain`。
   - 前端显示中文观察标签。

### 实施顺序建议

概率引擎不进入首页 Phase 1。

建议作为 Phase 2：

1. 先生成 `outputs/turning_point_probability/turning_point_probability_YYYYMMDD.duckdb`。
2. 生成 `turning_point_probability_latest.json`。
3. 先在本地跑历史回测和校准。
4. 通过后再接入首页一列“概率观察”。

---

## 三、KIMI2 经典策略信号哨兵审计

### 采纳

采纳核心边界：

- 经典策略哨兵独立于 Hermass State 主系统。
- 不参与 State 概率。
- 不进入 Agent 辩论。
- 不写 State Cube。
- 不写 Decision Ledger。
- 平时静默，触发时显示小标签。

采纳第一批策略：

- VCP
- 2560 趋势推进
- 布林强盗

采纳暂缓：

- ATR 吊灯暂缓，因其依赖 State 共振，容易混淆边界。
- CANSLIM、均值回归、动量暂缓，因当前无稳定代码基础。

### 必须修正

#### 1. 首页不应只展示 entry 类信号

KIMI2 提出“只展示 entry 类信号”，这对首页过窄。

原因：

- 用户最关心的是持有标的是否发生转折。
- 经典策略的失效、风险、退出类信号对持有标的同样重要。
- 但首页不能展示交易动作语言。

修正为：

首页可展示所有明确触发的经典策略规则信号，但显示文本必须中性化：

| 原始类型 | 首页显示 |
|---|---|
| entry | `VCP 规则信号` / `2560 规则信号` |
| exit | `VCP 失效信号` / `2560 风险信号` |
| risk | `布林规则风险` |
| structure | Phase 1 默认不展示，避免噪音 |

首页不显示：

- 入场
- 出场
- 买入
- 卖出
- 止损
- 止盈
- 仓位

#### 2. 详情页可以展示经典策略原始规则，但需要隔离文案

KIMI2 文档中的详情页包含大量 `入场 / 止损 / 离场 / 仓位` 词。

这些词不适合出现在首页，也不适合作为 Hermass 系统结论。

在经典策略详情页可以出现，但必须满足：

1. 页面标题明确：`经典策略规则详情`。
2. 顶部固定免责声明：
   - `以下为经典策略原始规则触发说明，仅作研究观察，不构成交易建议。`
3. 所有字段命名用“规则条文”，不要写成“系统建议”。
4. 不显示“推荐”、“适合交易”、“应当执行”等词。

#### 3. 服务文件位置应调整

KIMI2 建议新建 `scripts/sentinel_api.py` 不合适。

Web 查询服务应放：

`web/services/classic_strategy_sentinel.py`

原因：

- `scripts/` 用于离线任务和 cron。
- Web API 查询服务应在 `web/services/`。
- `web/main.py` 只做路由聚合。

#### 4. 不要动态调用策略函数

KIMI2 文档后面说“哨兵 API 可以通过策略名动态调用信号函数”，这和“只读 strategy_signals.duckdb”矛盾。

Phase 1 必须只读：

`outputs/strategy_signals/strategy_signals.duckdb`

不在 Web 请求时动态计算策略。

---

## 四、统一后的产品结构

### 首页 Phase 1

首页展示：

1. 观象指令栏。
2. 我的标的转折雷达。
3. 3D / 3W / 3M / 6M 状态变化矩阵。
4. 经典策略信号灯。
5. 全市场转折 Top。
6. 系统健康。

首页不展示：

- 真实概率数值。
- 买卖动作。
- 仓位规则。
- 目标价 / 止损价。
- 经典策略详情条文。

### State Workbench

`/state-observer` 保留完整表格、导出、订阅、物化表。

### 概率引擎

Phase 2 独立建设，不抢 Phase 1。

### 经典策略哨兵

Phase 1 可先只做首页聚合标签和独立详情页。

---

## 五、下一步实施拆分

### Phase 1A：正式改版总方案

输出：

`docs/tasks/OBSERVATION_DECK_PHASE1_IMPLEMENTATION_PLAN_20260702.md`

内容：

- 页面结构。
- 数据源映射。
- 需要修改的文件。
- 禁用词扫描规则。
- 验收命令。

### Phase 1B：代码实现

建议文件范围：

- `web/templates/index.html`
- `web/templates/_top_nav.html`
- `web/main.py`
- `web/services/classic_strategy_sentinel.py`（如果首页要读取策略标签）
- `scripts/validate_website_data_sync.py`（增加首页文案/状态冒烟）

### Phase 2：转折概率 MVP

建议文件范围：

- `scripts/build_turning_point_probability.py`
- `web/services/turning_point_probability.py`
- `tests/unit/test_turning_point_probability.py`
- `docs/tasks/TURNING_POINT_PROBABILITY_DELIVERY_*.md`

### Phase 3：经典策略哨兵详情页

建议文件范围：

- `web/services/classic_strategy_sentinel.py`
- `web/templates/sentinel_overview.html`
- `web/templates/sentinel_detail.html`
- `web/main.py`
- `tests/unit/test_classic_strategy_sentinel.py`

---

## 六、最终裁决

| 输入 | 裁决 |
|---|---|
| KIMI 首页方案 | 采纳，需确认 `/research` 路由与“建议”文案 |
| KIMI1 概率 MVP | 采纳为 Phase 2，暂缓第 7 Agent |
| KIMI2 经典策略哨兵 | 采纳边界与第一批策略，修正 entry-only、文件位置和动态计算 |

最终产品口径：

> Hermass 首页是“我的观察台”。它观察用户标的在 3D / 3W / 3M / 6M 的结构变化、证据与风险；经典策略只做独立信号灯；概率引擎作为后续独立证据层；系统不输出交易动作。

