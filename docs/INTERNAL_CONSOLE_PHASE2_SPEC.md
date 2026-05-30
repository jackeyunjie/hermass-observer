# Internal Console Phase 2 Spec

版本：v1.0  
日期：2026-05-29  
范围：Hermass Internal Console / 网站层第二阶段收口

---

## 1. 目标

Phase 2 的目标不是继续加页面，而是把当前网站从“可演示原型”推进到“可日常使用的内部工作台”。

一句话定义：

**保持 Hermass State 作为底座，用更成熟的 GitHub 产品信息架构，把 `/market / research / watchlist / backtest` 四条主路径收成稳定产品。**

---

## 2. 核心原则

1. **State First**
   - 所有页面都要回到 `state_hex / state_score / ef_count`
   - 不把 Hermass 降级成普通技术面看板

2. **Evidence Before Language**
   - 研究页先有 evidence，再有语言组织

3. **Backtest Is Validation, Not Decoration**
   - 回测页不是炫图页，而是验证页

4. **Execution Is Queue, Not Broker UI**
   - 执行页是处理队列，不是交易终端

5. **Information Offload, Not Overload**
   - 每页先告诉用户“现在看什么 / 先不看什么”

---

## 3. 外部基准如何落到 Hermass

### 3.1 Freqtrade / FreqUI

借：

- dashboard 的一屏概览
- backtest 视图组织
- control-room 式工作台感觉

不借：

- 钱包/交易所/实盘控制
- 高频实时交易 UI

Hermass 落点：

- `/market`
- `/watchlist`
- `/backtest`
- `/strategy-lab`

---

### 3.2 QSTrader

借：

- tearsheet 结果合同
- 组合级 + 交易级统计

不借：

- 具体策略示例

Hermass 落点：

- `/backtest`

---

### 3.3 Lean

借：

- 引擎层 / 展示层分离
- 研究 / 回测 / 执行边界

不借：

- 复杂 execution engine
- 多 broker / 多资产扩展

Hermass 落点：

- `state -> evidence -> backtest -> web`

---

### 3.4 VectorBT

借：

- 参数实验室思维
- 多策略横向比较

不借：

- notebook 化前端
- 参数维度过载

Hermass 落点：

- `/backtest` 的 Phase 3

---

### 3.5 TradeSight

借：

- 内部研究控制台的产品感
- self-hosted strategy lab 气质

不借：

- 以 AI 对话框为主入口

Hermass 落点：

- `/`
- `/research`
- `/watchlist`

---

## 4. Phase 2 页面目标

### 4.1 `/market`

定位：

**Hermass State 驱动的环境判断页**

必须回答的三个问题：

1. 现在是什么阶段
2. 当前更适合哪类策略
3. 哪些方向先看，哪些方向先少看

当前已有：

- `market_phase`
- `breadth`
- `macro_chain_prior`
- `broad_indices`
- `top_industries / weak_industries`
- `strategy_climate`

Phase 2 必须补强：

1. `State -> 结论` 压缩层更稳定
2. 行业判断更明确区分：
   - `顺风方向`
   - `观察方向`
   - `暂时降权方向`
3. 策略判断必须解释“为什么”
   - 为什么 VCP 顺风
   - 为什么 2560 次优
   - 为什么布林强盗降权

不做：

- 大量 K 线图
- 巨量宏观指标堆叠
- 实时盘口页

---

### 4.2 `/research`

定位：

**以 Evidence 为底座、以 State 为核心解释对象的研究助手页**

必须回答的三个问题：

1. 当前对象的结构环境怎样
2. 证据是否充分
3. 下一步该继续跟踪还是暂缓

当前已有：

- quick / deep / evidence
- decision frame
- evidence status
- not needed now
- strategy views
- current overlay

Phase 2 必须补强：

1. `State` 解读更稳定接入
   - raw state
   - structure explanation
   - rhythm prior

2. 策略解释更明确
   - `VCP` 是什么
   - `2560` 是什么
   - `布林强盗` 是什么
   - 当前对象为什么会被哪种策略关注

3. 研究页不只展示“卡片”
   - 还要展示“为什么值得现在看”

不做：

- 长篇研报化
- 买卖建议化
- 纯聊天问答化

---

### 4.3 `/watchlist`

定位：

**State 变化与策略触发的执行队列页**

必须回答的三个问题：

1. 今天先处理谁
2. 为什么它在优先队列
3. 下一步动作是什么

当前已有：

- `priority / observe / high_rr`
- `why_this_lane`
- `next_action`

Phase 2 必须补强：

1. 队列标签更清晰
   - `待处理`
   - `继续观察`
   - `已提醒`
   - `可暂缓`

2. 每个对象的“入队理由”更结构化
   - `state reason`
   - `strategy reason`
   - `risk / reward reason`

3. 与研究页联动
   - 点击即进对应 research

不做：

- 持仓管理 UI
- 下单按钮
- 模拟交易控制面板

---

### 4.4 `/backtest`

定位：

**Hermass State 环境下的策略验证页**

必须回答的三个问题：

1. 这个策略在什么环境下有效
2. 回撤和收益结构怎样
3. 哪些结果值得继续研究，哪些不值得

当前已有：

- 参数表单
- metrics cards
- equity curve
- recent trades

Phase 2 必须补强：

1. tearsheet 化
   - equity curve
   - drawdown curve
   - trade breakdown
   - portfolio stats
   - trade stats

2. Hermass 特色归因
   - `state combo attribution`
   - `market phase attribution`
   - `industry resonance attribution`
   - `strategy overlay comparison`

3. 运行时稳定性
   - Foundation DB 发现稳定
   - 查询窗口裁剪
   - 慢查询/空结果/异常的前台可解释提示

不做：

- 大规模参数爆炸
- execution 模拟器 UI
- 多策略自由脚本输入

---

## 5. 三种首页模式在 Phase 2 的收口

### 5.1 Direction

首页第一屏只回答：

- 当前环境一句话
- 当前顺风策略
- 当前顺风行业
- 当前暂时少看什么

CTA：

- `/market`
- `/industry`

---

### 5.2 Research

首页第一屏只回答：

- 当前研究更适合看哪些对象
- 哪些对象证据更充分
- 当前先点哪张研究卡

CTA：

- `/research`

---

### 5.3 Execution

首页第一屏只回答：

- 今天先处理哪个队列
- 哪些对象是高优先级
- 哪些对象可以继续观察，不必动作

CTA：

- `/watchlist`

---

## 6. 与 Hermass State 的直接结合点

这部分是 Phase 2 最不能丢的东西。

### 6.1 市场页

- `MN1/W1/D1` 的宽基组合
- `ef_count` 宽度
- `market_phase`
- `state_display_alias`

### 6.2 研究页

- raw state 保留
- `State：E/E/F`
- `结构解读`
- `节奏先验`

### 6.3 执行页

- 队列理由必须可回溯到：
  - `state`
  - `strategy signal`
  - `reward/risk`

### 6.4 回测页

- 不只验证策略名
- 还要验证：
  - 这个策略在什么 `state combo` 更有效
  - 在哪个 `market phase` 更有效

---

## 7. Phase 2 交付优先级

### P0

1. `/backtest` 跑通并稳定可用
2. `/watchlist` 队列解释再结构化
3. `/research` 接入更完整的 State 解释

### P1

1. `/market` 增强顺风/降权判断层
2. `/backtest` 增加 drawdown curve 与 attribution
3. 首页三模式继续减噪

### P2

1. `/backtest` 多参数比较
2. 历史回测结果归档
3. 更明确的研究 -> 执行联动
4. 新增 `/strategy-lab`，承接 idea -> backtest -> tracking -> promoted 的新策略跟进链路

---

## 8. 成功标准

如果 Phase 2 做对了，内部团队会得到这几个结果：

1. 打开首页，能快速知道“今天看什么”
2. 打开研究页，能快速知道“这只票为什么值得现在看”
3. 打开执行页，能快速知道“先处理谁”
4. 打开回测页，能快速知道“这个策略在 Hermass 环境里是否值得继续”

如果做错了，会退化成：

1. 指标面板堆叠
2. 长文本过载
3. 参数表单堆砌
4. 控制台像“半成品后台”

---

## 9. 一句话结论

Phase 2 的本质不是“继续加功能”，而是：

**借成熟 GitHub 产品的信息架构，把 Hermass 自己的 State 底座翻译成更稳定、更好用的网站工作台。**
