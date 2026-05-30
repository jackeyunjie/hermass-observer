# 新策略标准接入规范

版本：v1.0
日期：2026-05-23
状态：规范文档
适用对象：任何新经典趋势策略接入 Hermass Observer 系统

---

## 概述

本文档定义新策略接入系统的统一标准。任何新策略必须按以下流程接入：信号模块 → 信号账本 → 注册表 → 环境验证 → 规则升格 → 提醒层。

当前已接入策略：2560（ma2560）、VCP（vcp）、布林强盗（bollinger_bandit）。
未接入策略示例：ATR 吊灯（chandelier_exit，需持仓上下文，暂不支持）。

---

## 1. 信号输出标准

### 1.1 信号模块接口

每个策略必须提供一个 Python 信号函数，位于 `backtest/strategy_signals/` 目录下：

```python
def your_strategy_signal(row: dict, ctx: dict) -> tuple[str, float] | None:
    """
    输入:
        row: 当日行情数据（含 close, open, high, low, volume, 各 MA 等）
        ctx: 上下文数据（可以与 row 相同，或包含额外 SR/State 信息）
    输出:
        None: 无信号
        tuple[raw_signal_name, signal_strength]: 有信号
    """
```

**要求**：
- 函数是**纯函数**：给定相同输入，始终产生相同输出。
- 不访问网络、不写文件、不修改全局状态。
- `raw_signal_name` 必须在 `SIGNAL_META` 中注册（见 1.2）。
- `signal_strength` 为 0.0-1.0 的浮点数，表示信号强度。

### 1.2 信号名称注册

在 `scripts/strategy_signal_ledger.py` 的 `SIGNAL_META` 字典中注册：

```python
SIGNAL_META = {
    # 格式: "raw_signal_name": (strategy_id, signal_type, signal_name_cn)
    "your_entry_signal":    ("your_strategy", "entry",    "策略入场触发"),
    "your_structure_signal": ("your_strategy", "structure", "策略结构观察"),
    "your_exit_signal":     ("your_strategy", "exit",     "策略离场信号"),
    "your_risk_signal":     ("your_strategy", "risk",     "策略风险信号"),
}
```

### 1.3 signal_type 规范

| signal_type | 含义 | 提醒层处理 | 账本处理 |
|-------------|------|-----------|----------|
| entry | 入场信号 | 可进入提醒（需 reminder_eligible=true） | 记录为权威信号 |
| structure | 结构观察 | 仅研究层展示，不进入提醒 | 记录为研究信号 |
| exit | 离场信号 | 仅在有持仓上下文时展示 | 记录，等待执行层消费 |
| risk | 风险信号 | 可进入提醒作为风险提示 | 记录为风险信号 |

**禁止的 signal_type**：`buy`、`sell`、`hold`、`recommend`。

### 1.4 strategy_signal_daily 表字段要求

每条信号写入 `strategy_signal_daily` 表时，必须包含以下字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| signal_date | DATE | 是 | 信号日期 |
| stock_code | VARCHAR | 是 | 股票代码（6 位数字） |
| strategy_id | VARCHAR | 是 | 策略标识，如 `vcp`、`ma2560`、`bollinger_bandit` |
| signal_type | VARCHAR | 是 | `entry` / `structure` / `exit` / `risk` |
| signal_name | VARCHAR | 是 | 人类可读的信号名称 |
| stock_name | VARCHAR | 否 | 股票名称 |
| signal_strength | DOUBLE | 是 | 信号强度 0.0-1.0 |
| params_json | VARCHAR | 是 | 策略参数 JSON（用于审计回溯） |
| raw_signal | VARCHAR | 是 | 原始信号标识，对应 SIGNAL_META 的 key |
| source_module | VARCHAR | 是 | 来源模块路径，如 `backtest.strategy_signals.vcp` |
| research_only | BOOLEAN | 是 | 是否仅研究层可见 |
| reminder_eligible | BOOLEAN | 是 | 是否可进入提醒层（仅 entry 类型可为 true） |
| display_scope | VARCHAR | 是 | `reminder` 或 `research` |
| lifecycle_stage | VARCHAR | 是 | 生命周期阶段：新生/行进/延展/未知 |
| strategy_environment_fit | VARCHAR | 是 | 环境适配度：最佳适配/适配/弱适配/待观察/不适配 |
| fit_reasons | VARCHAR | 是 | 适配度原因（分号分隔） |
| created_at | VARCHAR | 是 | 入库时间 ISO-8601 |

**主键**：`(signal_date, stock_code, strategy_id, raw_signal)`

### 1.5 禁止的输出内容

信号模块和提醒层不得输出以下内容：

```text
买入 / 卖出 / 加仓 / 减仓 / 满仓 / 空仓
建议 / 推荐 / 确定机会 / 必涨 / 必跌
止盈价 / 止损价 / 目标价（这些属于执行层）
```

---

## 2. 注册流程

### 2.1 在 strategy_registry.json 中新增条目

编辑 `config/strategy_registry.json`，在 `strategies` 对象中新增：

```json
{
  "strategies": {
    "your_strategy": {
      "description": "策略一句话描述。",
      "verification_adapter": "scripts/search_your_strategy_optimal_state.py",
      "runner_command": "search_your_strategy_optimal_state",
      "default_raw_signals": ["your_entry_signal"],
      "primary_verification": {
        "type": "hypothesis_comparison",
        "name": "Your strategy State environment hypothesis comparison"
      },
      "registered_hypotheses": [
        "假设1：在某 State 组合下表现优于其他组合。",
        "假设2：路径条件优于静态条件。"
      ],
      "outputs": {
        "strategy_evaluation_prefix": "your_strategy_optimal_state_search",
        "project_report": "outputs/project/your_strategy_optimal_state_search.md"
      },
      "status": "not_validated"
    }
  }
}
```

### 2.2 注册字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| description | 是 | 策略核心逻辑的一句话描述 |
| verification_adapter | 是 | 只读验证脚本路径 |
| runner_command | 是 | Agently runner 子命令名 |
| default_raw_signals | 是 | 默认验证的原始信号列表 |
| primary_verification.type | 是 | 验证类型：`state_combo_search` / `hypothesis_comparison` / `state_path` |
| primary_verification.name | 是 | 验证任务名称 |
| registered_hypotheses | 是 | 待验证的研究假设列表 |
| outputs | 是 | 输出文件路径配置 |
| status | 是 | 初始状态：`not_validated` |

### 2.3 status 状态机

```text
not_validated → path_hypothesis_supported → partially_validated → fully_validated
                    ↓                              ↓
            kimi_candidate_rejected        hypothesis_rejected
```

| 状态 | 含义 | 可否进入提醒层 |
|------|------|---------------|
| not_validated | 尚未执行本地验证 | 否 |
| path_hypothesis_supported | 路径假设通过初步验证 | 研究层可展示 |
| partially_validated | 部分假设通过，规则待固化 | 可进入提醒（标注"初步验证"） |
| fully_validated | 所有关键假设通过，规则已写入 | 可进入提醒 |
| kimi_candidate_rejected | KIMI 候选未通过本地验证 | 否，需新假设 |
| hypothesis_rejected | 本地假设被证伪 | 否 |

### 2.4 在 compute_environment_fit 中注册策略-生命周期映射

编辑 `scripts/strategy_signal_ledger.py:480`：

```python
best_stage = {
    "vcp": "新生",
    "ma2560": "行进",
    "bollinger_bandit": "延展",
    "your_strategy": "行进",  # 新增
}.get(strategy_id)
```

### 2.5 在 REMINDER_ENTRY_STRATEGIES 中注册

如果策略的 entry 信号可进入提醒层：

```python
REMINDER_ENTRY_STRATEGIES = {"vcp", "ma2560", "bollinger_bandit", "your_strategy"}
```

---

## 3. 验证流程

### 3.1 创建验证脚本

新建 `scripts/search_your_strategy_optimal_state.py`，参考现有脚本：

- `scripts/search_2560_optimal_state.py` — State 组合搜索模板
- `scripts/search_vcp_optimal_state.py` — 路径搜索模板
- `scripts/search_bollinger_optimal_state.py` — 假设对照模板

验证脚本**必须**满足：

```text
1. 只读：不修改 Foundation DB、不修改策略信号模块、不修改配置文件。
2. 可复现：相同输入参数产生相同输出。
3. 有边界声明：输出文件末尾包含 "边界" 章节，声明研究结论不等于交易规则。
4. 输出标准目录：
   outputs/strategy_evaluation/{strategy}_optimal_state_search_YYYYMMDD_*.json
   outputs/strategy_evaluation/{strategy}_optimal_state_search_YYYYMMDD_*.md
   outputs/project/{strategy}_optimal_state_search.md
```

### 3.2 通过标准

验证通过需要同时满足以下条件：

| 条件 | 标准 | 说明 |
|------|------|------|
| 样本量 | 主假设组 n >= 30 | 最小统计有效性 |
| 超额收益 | 主假设组 20d 平均超额 > 0 | 方向正确 |
| 胜率 | 主假设组 20d 胜率 > 全样本胜率 | 优于无条件 |
| 统计显著性 | t-stat > 1.65（90% 置信度） | 排除随机波动 |
| 样本外一致性 | 样本内/样本外方向一致 | 排除过拟合 |
| 优于候选外 | 假设组表现优于假设外组 | 假设有增量价值 |

**特别说明**：VCP 的路径假设以"路径组优于非路径组"为标准，不要求 t-stat > 1.65（路径组样本量通常较小）。

### 3.3 执行验证

```bash
# 方式 1：直接运行验证脚本
python3 scripts/search_your_strategy_optimal_state.py \
  --start-date 2025-06-01 \
  --end-date 2026-05-01 \
  --foundation-db outputs/p116_foundation_20260521/p116_foundation.duckdb \
  --primary-window 20 \
  --min-samples 30

# 方式 2：通过 Agently runner
python3 agently_adapter/stockpool_daily_runner.py search_your_strategy_optimal_state \
  --start-date 2025-06-01 \
  --end-date 2026-05-01 \
  --foundation-db outputs/p116_foundation_20260521/p116_foundation.duckdb

# 方式 3：通过注册表编排器
python3 scripts/strategy_environment_verifier.py --date 2026-05-21
```

### 3.4 验证报告格式

验证报告必须包含以下章节：

```markdown
# 策略最优 State 环境搜索 - YYYY-MM-DD

- 历史区间: ...
- Foundation DB: ...
- 信号口径: ...
- 主观察窗口: ...
- 最小样本数: ...
- 已标注样本: ...
- 已标注日期: ...

## 研究假设对照
### 假设 1: ...
（含 matched / outside / all_selected 的 5d/10d/20d 统计表）

## 精确 State 组合 Top
（Top 30 组合的样本量、超额收益、胜率、t-stat）

## 模糊 bit 形态 Top
（按 bit 签名聚合的 Top 30）

## 边界
（研究声明、不构成交易建议、待人工确认等）
```

---

## 4. 升格流程

### 4.1 升格五步

```text
步骤 1：验证脚本产出报告
  ↓
步骤 2：人工审核报告（样本量、显著性、方向一致性）
  ↓
步骤 3：写入规则文件（config/*.json）
  ↓
步骤 4：更新策略定义（docs/STRATEGY_DEFINITIONS.md）
  ↓
步骤 5：更新提醒层（scripts/strategy_reminder_brief.py）
```

### 4.2 步骤 3：写入规则文件

如果验证通过，新建或更新配置文件：

```json
// config/your_strategy_state_match_rule.json
{
  "schema_version": "your_strategy_rule_v1",
  "strategy_id": "your_strategy",
  "validated_date": "2026-05-23",
  "validation_range": "2025-06-01 to 2026-05-01",
  "sample_count": 12345,
  "p116_state_match": {
    "allowed_states": ["E/E/F", "E/F/F"],
    "path_conditions": {
      "d1_compression_release_lookback": 20
    }
  },
  "market_match": {
    "preferred": "macro_etf_ef_count >= 2",
    "missing_macro_etf_policy": "stock_rule_only_not_market_confirmed"
  },
  "research_only": true
}
```

### 4.3 步骤 4：更新策略定义

在 `docs/STRATEGY_DEFINITIONS.md` 中新增策略章节，包含：

```markdown
## N. 策略名称

### 核心思想
一句话描述策略逻辑。

### 适用周期
日线及以上。

### 核心参数
参数列表。

### 信号规则
入场条件、离场条件、风险条件。

### 系统映射
- strategy_id: your_strategy
- 正式 entry 信号可进入提醒层。

### State 与市场匹配口径
已验证的 State 组合、市场匹配等级、全量分布数据。
```

### 4.4 步骤 5：更新提醒层

在 `scripts/strategy_reminder_brief.py` 中新增策略的提醒逻辑：

```python
# 新增策略专用提醒模板
YOUR_STRATEGY_NOTE = "本地验证：..."

# 在 assemble 函数中新增策略分支
if strategy_id == "your_strategy":
    body.append(YOUR_STRATEGY_NOTE)
```

提醒层语言标准：

```text
可以：
  "策略信号出现"
  "当前环境属于某类生命周期"
  "该策略与该环境的适配度为高/中/弱/待观察"
  "历史统计仍待校准或已由本地样本验证"

不可以：
  "买入" / "卖出" / "加仓" / "确定机会" / "必涨"
```

### 4.5 更新策略注册表状态

```bash
# 验证通过后更新 status
# 手动编辑 config/strategy_registry.json
# 将 status 从 "not_validated" 改为 "partially_validated" 或 "fully_validated"
```

---

## 5. 合规检查

### 5.1 禁止词汇扫描

任何写入提醒层或公开输出的文本不得包含以下词汇：

```text
买入 / 卖出 / 加仓 / 减仓 / 满仓 / 空仓
推荐 / 建议 / 确定机会 / 必涨 / 必跌 / 稳赚
止盈 / 止损 / 目标价 / 预期收益 / 保底
荐股 / 操盘 / 建仓 / 清仓 / 爆仓
```

扫描命令：

```bash
grep -rn "买入\|卖出\|加仓\|减仓\|推荐\|建议\|确定机会\|必涨\|荐股" \
  scripts/strategy_reminder_brief.py \
  outputs/strategy_reminders/ \
  public/strategy_reminder_* \
  --include="*.py" --include="*.json" --include="*.html" --include="*.md"
```

### 5.2 信号类型边界

| 允许 | 禁止 |
|------|------|
| entry / structure / exit / risk | buy / sell / hold / recommend |
| signal_strength 0.0-1.0 | 百分比收益预测 |
| lifecycle_stage 文本标签 | 价格目标 |
| strategy_environment_fit 五级分类 | 仓位建议 |

### 5.3 数据边界

| 层级 | 可以写入 | 不可以写入 |
|------|----------|-----------|
| 信号模块 | raw_signal, strength | 仓位、价格目标 |
| 信号账本 | 信号事实 + 环境标签 | 重新计算信号 |
| 提醒层 | 组装展示文本 | 推断缺失信号、简化规则 |
| 执行层 | 独立的进入/离开/调整规则 | 依赖提醒层输出 |

### 5.4 上市前检查清单

新策略进入生产前，必须逐项确认：

```text
□ 信号函数在 backtest/strategy_signals/ 中，纯函数，无副作用
□ SIGNAL_META 已注册，signal_type 合规
□ strategy_registry.json 已新增条目
□ 验证脚本产出报告，通过标准全部满足
□ 规则文件已写入 config/（如有）
□ docs/STRATEGY_DEFINITIONS.md 已更新
□ scripts/strategy_reminder_brief.py 已更新（如有提醒需求）
□ scripts/strategy_signal_ledger.py 的 best_stage 和 REMINDER_ENTRY_STRATEGIES 已更新
□ 禁止词汇扫描通过
□ 信号类型边界检查通过
□ 人工审核签字
```

---

## 附录

### A. 现有策略接入状态

| 策略 | strategy_id | 信号模块 | 注册状态 | 规则文件 | 提醒层 |
|------|-------------|----------|----------|----------|--------|
| 2560 | ma2560 | backtest/strategy_signals/ma2560.py | partially_validated | config/ma2560_state_market_match_rule.json | 已接入 |
| VCP | vcp | backtest/strategy_signals/vcp.py | path_hypothesis_supported | 待写入 | 已接入 |
| 布林强盗 | bollinger_bandit | backtest/strategy_signals/bollinger_bandit.py | kimi_candidate_rejected | 待写入 | 已接入 |
| ATR 吊灯 | atr_chandelier | backtest/strategy_signals/chandelier_exit.py | 未注册 | — | 未接入（需持仓上下文） |

### B. 关键文件路径

| 文件 | 用途 |
|------|------|
| `backtest/strategy_signals/*.py` | 策略信号模块 |
| `scripts/strategy_signal_ledger.py` | 信号账本（SIGNAL_META、compute_environment_fit） |
| `scripts/strategy_fit_observer.py` | 适配度观察持久化 |
| `scripts/strategy_environment_verifier.py` | 注册表驱动的验证编排器 |
| `scripts/strategy_reminder_brief.py` | 提醒层组装 |
| `config/strategy_registry.json` | 策略注册表 |
| `docs/STRATEGY_DEFINITIONS.md` | 策略定义文档 |
| `docs/strategy_environment_fit_scoring_design.md` | 适配度评分模型设计 |
