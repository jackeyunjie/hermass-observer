# KIMI State 策略研究消化记录

本文档用于消化以下 KIMI 集群研究输出，作为项目内部研究上下文。它不是策略定义文件，也不是交易建议。

来源目录：

- `data/Kimi_Agent_A股VCP多周期策略/`
- `data/Kimi_Agent_A股布林强盗VCP多周期策略/`

核心原则：

- State 底座只读。
- 策略模块仍以 `backtest/strategy_signals/` 和 `docs/STRATEGY_DEFINITIONS.md` 为权威定义。
- KIMI 研究只进入“场景标签、研究假设、回测设计、产品表达”层。
- 任何 KIMI 结论必须经过本地历史数据验证后，才能进入配置规则。

## 1. 必须纠正的 State 契约

KIMI 输出中有一部分文档正确使用了本项目 State bit 定义，也有一部分回测框架稿使用了不同 bit 顺序。后者不能直接采用。

本项目唯一有效的 State 契约如下：

```text
score = base + trend_bit * 4 + position_bit * 2 + volatility_bit

base:
  0 = 收缩
  8 = 扩张

trend_bit:
  0 = 无方向/平
  1 = 有方向

position_bit:
  0 = 未突破/中低位
  2 = 突破/位置确认

volatility_bit:
  0 = 波动稳定
  1 = 波动活跃

E = 14 = 8 + 4 + 2 + 0
F = 15 = 8 + 4 + 2 + 1
```

注意：

- Foundation DB 中存在 `-E`、`-F` 等空向 State。研究脚本需要按“方向 + 绝对值 bit”解码，不能把负值当作普通 0-15。
- `data/Kimi_Agent_A股VCP多周期策略/backtest_framework_design.md` 中的 bit mask 命名与本项目不一致，只能参考其统计流程，不能采用其 State 解码代码。

## 2. 可吸收的 VCP 研究结论

KIMI 关于 VCP 的主线结论与本项目现有哲学一致：

```text
VCP 不是抄底。
VCP 是上涨趋势中的波动收缩、供应枯竭、支点突破。
VCP 更适合趋势新生和收缩刚释放的环境，不一定最适合三周期全 E/F。
```

可进入研究层的 VCP 场景假设：

- D1 刚从收缩脱离，优先关注。
- D1 `base=0` 的收缩过程对应 VCP 的压缩阶段。
- D1 从 `0/4` 向 `10/12/14` 的路径，是 VCP 最值得验证的生命周期路径。
- W1 提供趋势背景，优先考虑 W1 已有趋势或进入扩张趋势的状态。
- MN1 不必已经 E/F。MN1 处于趋势孕育或早期趋势状态，可能保留更好的空间。
- VCP 在 `volatility_bit=0` 的突破初期，理论上优于高波动追涨。

KIMI 提出的候选组合需要本地验证，不能直接写入规则：

```text
D1 in {10, 12, 14}
W1 in {12, 14}
MN1 in {4, 12}
```

更保守的产品化表达：

```text
VCP信号出现，D1刚脱离收缩，W1具备趋势背景，MN1仍处于趋势孕育或早期扩张阶段，属于趋势新生观察场景。
```

## 3. 可吸收的布林强盗研究结论

KIMI 关于布林强盗的核心结论：

```text
布林强盗偏向扩张态。
VCP 偏向收缩态。
两者在 State 空间中互补。
```

可进入研究层的布林强盗场景假设：

- 扩张态是布林强盗适配的重要前提。本项目编码中应写作 `base=8`，不是 KIMI 部分草稿里的二值化 `base=1`。
- `trend_bit=1` 提供趋势延续背景。
- `position_bit=2` 表示突破确认。
- `volatility_bit=1` 对布林强盗可能是增强项，但同时也提高风险。
- E/F 更可能适合布林强盗或趋势持有管理，而非 VCP 的最优首次入场。

候选适配状态：

```text
D = 13 = 扩张 + 有趋势 + 未突破 + 波动活跃
E = 14 = 扩张 + 有趋势 + 突破 + 波动稳定
F = 15 = 扩张 + 有趋势 + 突破 + 波动活跃
```

产品化表达：

```text
布林强盗信号出现，当前 State 处于扩张趋势环境，波动开始或已经活跃，属于趋势延展观察场景。
```

## 4. VCP 与布林强盗的协同框架

可以吸收的协同观点：

| State 环境 | 更适合的策略 | 解释 |
|---|---|---|
| 收缩、趋势孕育、刚脱离收缩 | VCP | 等待支点突破，捕捉趋势新生 |
| 扩张、趋势确认、波动活跃 | 布林强盗 | 捕捉波动扩张后的趋势加速 |
| 三周期 E/F 稳固、波动稳定 | 2560 | 观察趋势行进中的回踩确认 |

这个框架只能用于“策略选择解释”和“场景标签”，不能用于自动买卖建议。

系统语言应保持：

```text
策略信号出现。
当前环境属于某类生命周期。
该策略与该环境的适配度为高/中/弱/待观察。
历史统计仍待校准或已由本地样本验证。
```

不得输出：

```text
买入
卖出
加仓
满仓
确定机会
必涨
```

## 5. A股特殊过滤项

KIMI 对 A股制度环境的提醒可进入风控标签研究层：

- T+1 导致信号日确认与次日执行之间有滑点和跳空风险。
- 涨停突破可能无法成交，不能把“突破涨停”简单视作可执行入场。
- 跌停导致退出困难，所有出场研究必须考虑不可成交情形。
- ST、停牌、低成交额、低市值、极端低价应进入基础可交易过滤。
- 板块退潮、题材一日游、业绩公告窗口、减持公告、监管事件，应作为风险标签，不应作为策略信号。

这些过滤项属于：

```text
可交易性过滤
风险环境标签
研究层提示
```

不属于：

```text
State 底座
VCP/布林强盗原始触发条件
```

## 6. 回测设计可吸收部分

可采用的统计目标：

- 按 `strategy_id × raw_signal × MN1/W1/D1 State combo` 统计未来收益。
- 同时做精确组合和模糊 bit 聚合，避免 4096 组合过拟合。
- 观察未来 `5/10/20/30/60` 日收益和超额收益。
- 与全市场等权、沪深300、中证1000等基准对比。
- 设置最小样本数门槛。
- 做样本内/样本外拆分。
- 对单个组合只做候选发现，不直接升格为规则。

本项目已有对应实践：

- `scripts/search_2560_optimal_state.py`
- 后续可扩展为 `scripts/search_vcp_optimal_state.py`
- 后续可扩展为 `scripts/search_bollinger_optimal_state.py`
- 布林强盗代码对账记录：`docs/BOLLINGER_BANDIT_IMPLEMENTATION_AUDIT.md`

推荐统一输出：

```text
outputs/strategy_evaluation/{strategy}_optimal_state_search_YYYYMMDD_*.json
outputs/strategy_evaluation/{strategy}_optimal_state_search_YYYYMMDD_*.md
```

## 7. 后续落地建议

### 7.1 VCP

新增只读研究脚本：

```text
scripts/search_vcp_optimal_state.py
```

输入：

- `strategy_signal_daily_YYYYMMDD.json`
- 或直接复用权威 `vcp_signal` 重算全市场信号
- Foundation DB 中的 MN1/W1/D1 State
- daily_bars 未来收益标签

输出：

- VCP 在不同 State 组合下的未来收益统计
- 当前“三周期 E/F”规则与非同步候选组合的对比
- `D1 0/4 -> 10/12/14` 路径的条件表现

本地初次验证已完成：

```bash
python3 agently_adapter/stockpool_daily_runner.py search_vcp_optimal_state \
  --start-date 2025-06-01 \
  --end-date 2026-05-01 \
  --foundation-db outputs/p116_foundation_20260521/p116_foundation.duckdb \
  --primary-window 20 \
  --min-samples 30
```

输出：

```text
outputs/strategy_evaluation/vcp_optimal_state_search_20260501_breakout_breakout_no_vol_breakout_weak_vol_all.json
outputs/strategy_evaluation/vcp_optimal_state_search_20260501_breakout_breakout_no_vol_breakout_weak_vol_all.md
outputs/project/vcp_optimal_state_search.md
```

样本概况：

```text
selected_samples = 43262
labeled_samples  = 43259
labeled_dates    = 223
```

关键结果：

| 假设 | 20d 样本 | 20d 平均超额 | 20d 胜率 | 结论 |
|---|---:|---:|---:|---|
| D1 近5日经历收缩后释放 | 1415 | +1.66% | 43.18% | 优于外侧组 |
| D1 近10日经历收缩后释放 | 2525 | +1.62% | 42.18% | 优于外侧组 |
| D1 近20日经历收缩后释放 | 4955 | +1.67% | 43.21% | 通过路径假设 |
| 当前扩张但近20日无收缩前兆 | 35202 | +0.45% | 40.64% | 弱于路径组 |
| KIMI静态候选组合 | 10410 | +0.47% | 41.07% | 不优于候选外 |
| D1 in {10,12,14} | 31307 | +0.64% | 41.18% | 静态状态弱于路径条件 |

因此，当前本地数据支持“VCP 是收缩后释放路径”的方向，不支持把 KIMI 静态组合直接升格为规则。

### 7.2 布林强盗

新增只读研究脚本：

```text
scripts/search_bollinger_optimal_state.py
```

重点验证：

- `D/E/F` 是否优于普通 E/F。
- 扩张态 `base=8` 是否显著提高信号后收益。
- `volatility_bit=1` 是增强项还是风险项。
- VCP 与布林强盗信号是否呈现低相关或时序接力。

### 7.3 提醒层

在 `strategy_signal_daily` 或 `strategy_reminder_brief` 中保留现有字段：

```text
lifecycle_stage
strategy_environment_fit
fit_reasons
```

后续可新增策略专属环境标签：

```text
vcp_lifecycle_stage
vcp_environment_fit
vcp_fit_reasons
bb_lifecycle_stage
bb_environment_fit
bb_fit_reasons
```

但必须保证这些字段是场景描述，不是交易动作。

## 8. 采用状态

| 内容 | 处理方式 |
|---|---|
| VCP 偏收缩、趋势新生 | 采纳为研究假设 |
| 布林强盗偏扩张、趋势延展 | 采纳为研究假设 |
| VCP 与布林强盗互补 | 采纳为产品解释框架 |
| KIMI 候选最优 State 组合 | 待本地回测验证 |
| KIMI 中错误 bit mask 代码 | 禁止采用 |
| KIMI 中收益/胜率数字 | 未经本地复现不得展示 |
| A股制度过滤项 | 采纳为风险标签研究方向 |

## 9. 给 LLM/Agent 的提示

当 DeepSeek、KIMI、Agently 后续引用这些研究时，必须先声明：

```text
以下内容是研究假设，不是已经校准通过的统计结论。
State bit 定义以 config/deepseek_context.md 和本文第 1 节为准。
策略触发条件以 docs/STRATEGY_DEFINITIONS.md 和 backtest/strategy_signals/ 为准。
```
