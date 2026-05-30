# 布林强盗实现对账记录

本文对账对象：

- 研究来源：`data/Kimi_Agent_A股布林强盗VCP多周期策略/`
- 当前权威策略定义：`docs/STRATEGY_DEFINITIONS.md`
- 当前代码实现：`backtest/strategy_signals/bollinger_bandit.py`

本文只做实现对账，不修改策略逻辑，不构成交易建议。

## 1. 当前工程契约

当前布林强盗模块实现的是 John Hill 风格的 long-only A 股版本：

```text
Channel basis: SMA(close, 50)
Upper band: SMA(close, 50) + 1 * STD(close, 50)
Momentum filter: close > close_30_ago
Entry: close crosses above upper band while momentum filter is true
Exit reference: degrading MA, 50 -> 10
Short side: disabled
```

对应代码：

- `bollinger_bandit_signal(row, ctx)`
- `exit_ma_period(hold_bars, start_period=50, floor_period=10)`
- `bollinger_bandit_exit_signal(close, exit_ma_value)`

## 2. 已一致的部分

| 项目 | KIMI/报告口径 | 当前代码 | 结论 |
|---|---|---|---|
| 策略方向 | A 股只做多 | short side disabled | 一致 |
| 中轨周期 | `SMA(Close, 50)` | `bb_upper_50_1` 依赖 MA50 | 一致 |
| 标准差倍数 | 强盗标准组 `1.0` | `bb_upper_50_1` | 一致 |
| 趋势过滤 | `Close > Close[30]` | `close > close_30_ago` | 一致 |
| 入场触发 | 收盘突破上轨 | `close > upper` | 一致 |
| 出场思想 | 自适应/退化均线 | `exit_ma_period()` 50 递减至 10 | 一致 |

当前代码还额外要求：

```text
prev_close <= prev_upper
```

也就是只在“从上轨下方穿越到上轨上方”的当日触发 entry。这个约束比“持续站在上轨上方”更严格，能避免同一轮趋势中重复发出 entry 信号。该约束与账本式信号系统匹配，应保留。

## 3. 不应直接照抄的部分

KIMI 报告中有大量 A 股增强建议，包括：

- `1.5` 或更高标准差倍数的参数扫描。
- 成交量确认。
- 市值、流动性、ST、停牌、涨跌停过滤。
- 市场指数过滤。
- State 条件过滤。
- ATR 或硬止损。
- S/A/B/C 信号分级。
- 分批止盈、回撤管理、执行滑点假设。

这些内容不应直接写入 `bollinger_bandit_signal()`，原因：

1. 它们属于研究过滤、可交易性过滤、执行层或回测层，不是当前布林强盗核心触发条件。
2. 一旦混入核心信号，会破坏“策略模块输出权威信号，提醒层只组装”的边界。
3. 其中部分参数是 KIMI 的回测设计空间，不是已由本地数据复现的最优结论。

正确落点：

| KIMI 增强项 | 推荐落点 |
|---|---|
| 流动性、市值、ST、停牌、涨跌停 | `strategy_signal_ledger.py` 的可交易性/风险标签，或回测过滤 |
| State 环境适配 | `strategy_environment_fit` / 只读 state search 脚本 |
| 参数扫描 | `search_bollinger_optimal_state.py` 或独立回测脚本 |
| ATR、硬止损、滑点 | 前向模拟/实盘执行账本 |
| S/A/B/C 分级 | 样本充足后进入校准层，不进入原始触发函数 |

## 4. State 规则的关键防错

不要把 KIMI 原文中的“base=1 / base=0”直接照抄为配置。本项目 State 契约是：

```text
score = base + trend_bit * 4 + position_bit * 2 + volatility_bit
base = 0 表示收缩
base = 8 表示扩张
```

因此：

```text
10 = 8 + 0 + 2 + 0  -> 扩张 + 位置确认 + 波动稳定
12 = 8 + 4 + 0 + 0  -> 扩张 + 有趋势 + 波动稳定
14 = 8 + 4 + 2 + 0  -> 扩张 + 有趋势 + 位置确认 + 波动稳定
15 = 8 + 4 + 2 + 1  -> 扩张 + 有趋势 + 位置确认 + 波动活跃
```

如果把 `10/12/14` 解释为 `base=0` 收缩态，就是错误的。VCP 的合理表达应是：

```text
D1 经历过收缩，并在近期从收缩释放到扩张/趋势确认状态。
```

而不是：

```text
D1 当前为 10/12/14，所以仍是收缩态。
```

同理，布林强盗候选状态 `13/14/15` 可以作为“扩张趋势环境”的研究假设，但必须经过本地历史数据复现后，才能进入正式配置。

## 5. 当前结论

当前代码实现与布林强盗标准核心规则基本一致，暂不需要修改 `backtest/strategy_signals/bollinger_bandit.py`。

下一步应做的是研究验证，而不是直接改触发条件：

1. 新增只读脚本 `scripts/search_bollinger_optimal_state.py`。
2. 统计布林强盗 entry 在不同 MN1/W1/D1 State 组合下的未来 5/10/20/30/60 日表现。
3. 对比 `13/14/15`、E/F、三周期共振、波动活跃等候选环境。
4. 只有样本量、样本外验证和质量闸门通过后，才把结果写入规则文件。

### 5.1 本地初次验证记录

已新增只读脚本：

```text
scripts/search_bollinger_optimal_state.py
```

Agently runner 子命令：

```bash
python3 agently_adapter/stockpool_daily_runner.py search_bollinger_optimal_state \
  --start-date 2025-06-01 \
  --end-date 2026-05-01 \
  --foundation-db outputs/p116_foundation_20260521/p116_foundation.duckdb \
  --primary-window 20 \
  --min-samples 30
```

输出：

```text
outputs/strategy_evaluation/bollinger_optimal_state_search_20260501_entry_all.json
outputs/strategy_evaluation/bollinger_optimal_state_search_20260501_entry_all.md
outputs/project/bollinger_optimal_state_search.md
```

样本概况：

```text
selected_samples = 47220
labeled_samples  = 47219
labeled_dates    = 223
```

关键结果（2025-06-01 至 2026-05-01，本地 P116 foundation）：

| 假设 | 20d 样本 | 20d 平均超额 | 20d 胜率 | 结论 |
|---|---:|---:|---:|---|
| KIMI候选组合：D1 in {13,14,15}, W1 in {14,15}, MN1 in {12,14,15} | 6358 | -0.40% | 37.50% | 未通过 |
| KIMI候选组合外 | 39684 | +0.37% | 39.30% | 优于候选组 |
| 三周期 E/F 共振 | 1215 | -0.02% | 39.26% | 20d 不成立，5/10d 较强 |
| D1 in {13,14,15} | 23888 | -0.09% | 38.07% | 未通过 |
| D1 volatility_bit=1 | 13879 | -0.49% | 36.96% | 未通过 |
| D1 volatility_bit=0 | 32163 | +0.59% | 39.95% | 明显更稳 |

因此，当前本地数据不支持把 KIMI 的布林强盗候选 State 组合直接写入正式配置。更接近本地证据的临时研究判断是：

```text
布林强盗的触发本身是波动突破信号；
但信号出现时，D1 已经波动活跃并不一定更好。
当前样本中，D1 波动稳定组的 20d 表现更稳。
```

这仍然只是研究结论，不进入生产规则。

## 6. 推荐的工程命名

保留当前策略为：

```text
bollinger_bandit_original
```

若未来要引入 A 股增强版，建议单独命名：

```text
bollinger_bandit_a_share_enhanced
```

两者必须分开入账，避免历史统计口径混淆。
