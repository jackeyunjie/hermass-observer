# GitHub Benchmark Shortlist For Hermass

## 目标

这份短名单不是泛泛罗列 GitHub 量化项目，而是回答一个更具体的问题：

**有哪些成熟开源项目，值得被 Hermass 当前的 `State + 市场页 + 研究卡 + 执行页 + 回测页` 体系借鉴？**

借鉴原则：

1. **不复制别人的交易逻辑**
2. **只借产品分层、结果合同、页面组织、回测边界**
3. **所有借鉴都要落回 Hermass 自己的底座**
   - `state_hex / state_score / ef_count`
   - `market_phase / daily_snapshot / market_assets_state`
   - `quick / deep / evidence`
   - `watchlist / strategy signals / backtest`

---

## Hermass 当前产品骨架

你们当前已经有自己的核心底座，不应被外部项目带偏：

1. **Hermass State 底座**
   - 多周期 `MN1 / W1 / D1`
   - `state_hex / state_score / ef_count`
   - 结构环境优先，不做简单指标叠加

2. **市场判断层**
   - `market_phase`
   - `macro_chain_prior`
   - `market_assets_state`
   - `daily_snapshot`

3. **研究层**
   - `quick / deep / evidence`
   - `structured completeness`
   - `evidence first`

4. **执行层**
   - `watchlist`
   - `priority / observe / high RR`
   - `strategy overlay`

5. **回测层**
   - `backtest.engine`
   - `backtest.strategy_signals`
   - `backtest.metrics`

所以外部项目只能作为 **界面、合同、分层、工作流参考**，不是策略真理来源。

---

## 最值得深看 6 个项目

### 1. Freqtrade / FreqUI

- 仓库: <https://github.com/freqtrade/freqtrade>
- UI 文档: <https://github.com/freqtrade/freqtrade/blob/develop/docs/freq-ui.md>
- 定位: 交易机器人监控与交互前端

**最值得借的部分**

1. 监控台分层
   - dashboard
   - trade view
   - settings
   - backtesting

2. “前端是可选层”的边界
   - UI 不等于引擎
   - 引擎可以独立运行
   - 前端只负责监控、交互、配置、结果展示

3. Backtesting UI 的入口组织
   - 不把回测和实盘混成一页
   - 回测视图就是参数、结果、历史结果对比

**Hermass 对应映射**

- `/market`
  - 借它的 dashboard 一屏概览逻辑
  - 但展示内容要换成 `market_phase / breadth / macro prior / strategy climate`

- `/backtest`
  - 借它的“表单 + 结果视图 + 历史结果”组织方式
  - 不要借它的币圈交易语义

- `/watchlist`
  - 借“trade view = 当前处理对象工作台”的感觉
  - 但你们不是持仓监控，而是 `priority / observe / 已提醒`

**不要学的部分**

- 币圈账户、钱包、交易所接入
- 过多实时控制按钮
- 把 UI 做成“交易终端”

**一句话判断**

Hermass 可以把 `FreqUI` 当成 **内部控制台结构参考**，但不能把自己做成 Freqtrade 的 A 股翻版。

---

### 2. QSTrader

- 仓库: <https://github.com/quantstart/qstrader>
- README: <https://github.com/quantstart/qstrader/blob/master/README.md>
- 定位: 事件驱动股票回测平台

README 里最关键的一句是：

> `QSTrader is an open-source event-driven backtesting platform for use in the equities markets`

它最有价值的不是 UI，而是 **tearsheet 结果合同**。

**最值得借的部分**

1. 回测结果应该有“tearsheet”思维
   - equity curve
   - drawdown curve
   - portfolio stats
   - trade stats

2. 组合级 + 交易级双层统计
   - 不只看总收益
   - 还要看交易层统计和分布

3. 事件驱动边界
   - 策略逻辑
   - 组合管理
   - 绩效统计
   - 分层清晰

**Hermass 对应映射**

- `/backtest`
  - summary 不应该只停在 6 个指标卡
  - 后续应扩展为：
    - equity curve
    - drawdown curve
    - monthly / yearly summary
    - trade breakdown
    - strategy attribution

- `Hermass State Backtest`
  - `state-triggered entry`
  - `strategy overlay`
  - `market environment filter`
  这些是你们的特色，但输出层仍应遵循 tearsheet 合同

**不要学的部分**

- 直接照搬它的示例策略
- 围绕单一均线策略组织整个产品

**一句话判断**

QSTrader 最适合做 **Hermass 回测页结果合同模板**。

---

### 3. QuantConnect Lean

- 仓库: <https://github.com/QuantConnect/Lean>
- 定位: 算法交易引擎

它最有价值的是 **引擎边界意识**。

**最值得借的部分**

1. 研究、回测、执行是不同层
2. 引擎层和展示层分离
3. 数据、策略、执行、分析各自独立

**Hermass 对应映射**

- `State`
  - 继续做成底座，不和页面耦合

- `Research`
  - 继续让 `evidence payload` 做中间合同

- `Backtest`
  - 不直接从页面里写策略逻辑
  - 页面只传参数，真正逻辑留在 `backtest/`

- `Web`
  - 网站只做消费层，不做真引擎层

**不要学的部分**

- 不要现在就追求 Lean 级别的 execution engine 复杂度
- 不要把“多 broker / 多资产 / 多语言”引进当前阶段

**一句话判断**

Lean 不是前端参考，而是 **架构自律参考**。它提醒 Hermass：研究、回测、执行、展示必须一直分层。

---

### 4. VectorBT

- 仓库: <https://github.com/polakowo/vectorbt>
- 定位: 快速参数实验 / 大规模回测研究

仓库描述里最关键的一句是：

> `Run thousands of trading ideas before others finish one`

**最值得借的部分**

1. 参数实验室思维
   - 多参数
   - 多时间窗
   - 多组合比较

2. 研究效率优先
   - 不是做最终产品 UI
   - 是做策略迭代速度

**Hermass 对应映射**

- `/backtest`
  - Phase 1 是单次运行
  - Phase 2 应增加：
    - 多参数比较
    - 多策略横向对比
    - 同一 State 环境下的表现归因

- `Hermass State`
  - 最适合做的不是“指标参数遍历”
  - 而是：
    - `state combo × strategy overlay`
    - `market phase × strategy fit`
    - `industry resonance × strategy signal`

**不要学的部分**

- 不要把产品页做成研究 notebook
- 不要把用户暴露给过多参数维度

**一句话判断**

VectorBT 最适合启发你们未来的 **策略实验室**，而不是当前首页或研究卡。

---

### 5. TradeSight

- 仓库: <https://github.com/rmbell09-lang/tradesight>
- 定位: self-hosted AI strategy lab / paper trading dashboard

**最值得借的部分**

1. “内部实验室”产品感
2. 自托管控制台形态
3. 把研究、实验、跟踪放在一个轻页面系统里

**Hermass 对应映射**

- `/`
  - 三种视图切换，本质上就是 Hermass 自己的 strategy lab 入口

- `/research`
  - 不是写长报告，而是快速进入证据对象

- `/watchlist`
  - 不是交易终端，而是跟踪工作台

**不要学的部分**

- 不要把 AI 聊天框当成主产品
- 不要把自然语言交互覆盖掉结构化证据入口

**一句话判断**

TradeSight 更像是 **产品气质参考**，适合借“内部研究控制台”的感觉。

---

### 6. OpenAlgo

- 仓库: <https://github.com/marketcalls/openalgo>
- 定位: 全栈量化 / 策略 / 执行门户

**最值得借的部分**

1. 页面和功能入口组织
2. 从 idea 到 backtest 再到 execution 的链路感
3. 全站导航结构

**Hermass 对应映射**

- `/market -> /industry -> /research -> /watchlist -> /backtest`
  这条导航链很适合继续稳定下来

**不要学的部分**

- 不要在当前阶段追求 broker/execution 复杂度
- 不要把整站重心切到“自动交易平台”

**许可证提醒**

- OpenAlgo 是 `AGPL-3.0`
- 可以学习设计与信息架构
- 不建议直接复制代码进 Hermass

**一句话判断**

OpenAlgo 适合借 **导航和工具入口组织**，不适合直接当实现模板。

---

## 把外部项目映射回 Hermass State

这里是最关键的一层。不是“看了很多项目”，而是要回到你们自己的独特底座。

### 1. 市场页 `/market`

外部参考：

- `FreqUI dashboard`
- `OpenAlgo` 的门户分层

Hermass 自己的核心应该保持：

- `market_phase`
- `macro_chain_prior`
- `breadth`
- `broad index state triplet`
- `top / weak industries`
- `strategy climate`

**结论**

你们的市场页不应变成普通技术面大盘页，而应成为：

**“Hermass State 驱动的环境判断页”**

也就是：

- 现在是哪个阶段
- 阶段持续多久
- 哪类策略顺风
- 哪些行业顺风
- 哪些方向暂时少看

---

### 2. 研究页 `/research`

外部参考：

- `TradeSight` 的实验室感
- `Lean` 的分层纪律

Hermass 自己的核心应该保持：

- `quick / deep / evidence`
- `structured completeness`
- `state core + strategy overlay + enrichment`

**结论**

研究页不应被外部项目带成：

- 长篇研报页
- 纯聊天页
- 技术指标堆叠页

而应继续保持为：

**“以 Evidence 为底座，以 State 为中心解释对象的研究助手页”**

---

### 3. 执行页 `/watchlist`

外部参考：

- `FreqUI trade view`
- `TradeSight` 的 control-room 感

Hermass 自己的核心应该保持：

- `priority`
- `observe`
- `high RR`
- `already alerted`

**结论**

执行页不应等于“持仓页”，而应是：

**“State 变化和策略触发的处理队列页”**

---

### 4. 回测页 `/backtest`

外部参考：

- `QSTrader tearsheet`
- `VectorBT` 参数实验室
- `FreqUI backtesting` 的页面组织

Hermass 自己的核心应该保持：

- `state-triggered entry`
- `strategy overlay`
- `market phase filter`
- `industry / regime attribution`

**结论**

你们的回测页最值得形成自己的特色：

1. **不是普通指标回测**
2. **是 Hermass State 环境下的策略验证**

后续最值得增加的维度：

- `state combo attribution`
- `market phase attribution`
- `industry resonance attribution`
- `strategy overlay comparison`

---

## 对当前产品最有价值的借鉴顺序

如果只按“现在就有用”的顺序排：

1. **Freqtrade / FreqUI**
   - 借 dashboard / backtest / control-room 的信息架构

2. **QSTrader**
   - 借回测结果合同

3. **Lean**
   - 借架构边界

4. **TradeSight**
   - 借内部产品气质

5. **VectorBT**
   - 借未来策略实验室方向

6. **OpenAlgo**
   - 借全站导航，不借执行复杂度

---

## 不要跑偏的红线

1. 不要把 Hermass 做成币圈 bot 平台
2. 不要让聊天式入口替代结构化研究入口
3. 不要把回测页做成参数堆场
4. 不要让网站页面直接承载策略核心逻辑
5. 不要把 `state_hex / state_score / ef_count` 降级成普通技术指标标签

---

## 最终建议

当前最合理的借鉴路线是：

1. 用 `FreqUI` 的分层感收口你们的网站导航和工作台布局
2. 用 `QSTrader` 的 tearsheet 思维升级 `/backtest`
3. 用 `Lean` 的架构纪律约束 `state -> evidence -> web -> backtest`
4. 继续把一切解释都回收到 **Hermass State** 上

换句话说：

**外部项目给你们的是“产品壳、结果合同、架构边界”；Hermass 自己真正不可替代的是 State 底座。**
