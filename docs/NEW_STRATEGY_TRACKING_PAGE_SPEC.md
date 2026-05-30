# New Strategy Tracking Page Spec

## 1. 目标

本规范定义一个新的内部页面族：

- `/strategy-lab`
- `/strategy-lab/{experiment_id}`

它的职责不是替代 `/backtest`，也不是做成“自由策略编辑器”，而是承接：

1. 用户或团队提出一个策略想法
2. 用 Hermass State 框架做最小回测验证
3. 判断它在什么市场环境下有效
4. 将其放入持续跟踪，而不是立刻晋升为正式策略

这个页面要解决的问题是：

**用户自定义策略想法能不能通过回测与市场环境匹配形成一个“可继续跟踪的新策略对象”。**

---

## 2. 定位

定位：

**Hermass State 底座上的新策略孵化与跟进页**

与现有页面的关系：

- `/market`
  - 回答当前市场环境
- `/research`
  - 回答个股证据与结构
- `/watchlist`
  - 回答当前执行队列
- `/backtest`
  - 回答策略验证结果
- `/strategy-lab`
  - 回答“一个新策略是否值得继续跟进”

这意味着：

- `/backtest` 是验证工具
- `/strategy-lab` 是策略对象管理页

---

## 3. 核心原则

### 3.1 State First

新策略的有效性不能只看总收益或胜率，必须同时回答：

1. 它在什么 `State` 组合下有效
2. 它在什么 `market_phase` 下有效
3. 它在什么行业环境下更容易出现正样本

### 3.2 Template First

Phase 1 只支持模板化策略，不支持任意 Python 脚本输入。

允许的策略类型：

- `vcp_variant`
- `ma2560_variant`
- `bollinger_variant`
- `state_plus_filter`
- `state_plus_industry`
- `state_plus_strategy_overlay`

不允许：

- 用户随意上传代码
- 在网页直接写脚本
- 无边界的参数爆炸搜索

### 3.3 Tracking Before Promotion

一个新策略不能因为一次回测不错就进入正式策略列表。

必须先经历：

1. 回测验证
2. 环境匹配
3. 实时跟踪
4. 少量样本观察

再决定是否晋升。

### 3.4 Research Only

本页只做研究和跟踪，不做：

- 交易建议
- 自动下单
- 模拟执行控制

---

## 4. 页面结构

### 4.1 `/strategy-lab`

定位：

**新策略实验列表页**

回答三个问题：

1. 当前有哪些新策略在验证
2. 哪些已经进入跟踪
3. 哪些值得优先继续研究

页面区块：

1. `Lab Summary`
   - 总实验数
   - `draft / backtested / tracking / promoted / retired` 数量
   - 最近 7 天新增实验数

2. `Priority Experiments`
   - 当前最值得继续跟进的实验
   - 原因是：
     - 回测不差
     - 环境匹配清晰
     - 今天有现实候选标的

3. `Tracking Experiments`
   - 已通过最小验证，进入持续观察

4. `Retired / Failed Ideas`
   - 已淘汰的想法
   - 说明为什么淘汰

---

### 4.2 `/strategy-lab/{experiment_id}`

定位：

**单个新策略对象的完整跟进页**

必须回答的五个问题：

1. 这条新策略到底抓什么
2. 它在什么环境下有效
3. 回测结果是否值得继续跟进
4. 今天市场是否处于它的顺风环境
5. 当前是否已有候选标的进入观察

页面区块：

#### A. Strategy Definition

字段：

- `experiment_id`
- `strategy_name`
- `parent_template`
- `version`
- `owner`
- `created_at`
- `status`

解释字段：

- `what_it_captures`
- `what_it_avoids`
- `entry_logic`
- `exit_logic`
- `filters`

要求：

- 必须是结构化文本
- 不能只是“一个想法”
- 要明确抓的是什么，不抓的是什么

#### B. Market Fit

字段：

- `best_state_combos`
- `weak_state_combos`
- `best_market_phases`
- `weak_market_phases`
- `best_industries`
- `weak_industries`

展示原则：

- 不显示复杂原始统计名
- 前台只显示：
  - 顺风环境
  - 观察环境
  - 逆风环境

示例：

- 顺风环境：`E/E/F`、`趋势新生`、电子/汽车
- 逆风环境：`0/0/C`、`退潮期`、高离散无主线阶段

#### C. Backtest Validation

字段：

- `date_range`
- `universe`
- `total_trades`
- `win_rate`
- `max_drawdown`
- `annualized_return`
- `sharpe`
- `sample_quality`

补充拆解：

- `state_attribution`
- `market_phase_attribution`
- `industry_attribution`

解释原则：

- 不只展示总收益
- 要解释“结果主要来自什么环境”

#### D. Live Tracking

字段：

- `today_market_fit`
- `today_fit_reason`
- `candidate_count`
- `candidate_codes`
- `watchlist_link`

回答：

- 今天这条新策略是否值得观察
- 如果值得，当前有哪些候选标的
- 如果不值得，主要是环境不匹配还是标的不匹配

#### E. Promotion Status

字段：

- `status`
- `status_reason`
- `next_review_date`
- `review_checklist`

目的：

- 让每条新策略都有清晰的治理状态
- 不让实验一直挂着没有归属

---

## 5. 状态机

### 5.1 状态定义

#### `draft`

含义：

- 想法已定义
- 还未完成最小回测验证

进入条件：

- 已填写结构化策略定义

退出条件：

- 完成首次回测

#### `backtested`

含义：

- 已有最小回测结果
- 但尚未进入持续观察

进入条件：

- 至少完成一次标准回测
- 结果可解释

退出条件：

- 进入 tracking
- 或直接 retired

#### `tracking`

含义：

- 回测具备继续跟进价值
- 开始观察现实市场中的候选标的与环境匹配

进入条件：

- 至少一个顺风环境较明确
- 回测样本不完全失真
- 可以连接到现实候选池

退出条件：

- promoted
- retired

#### `promoted`

含义：

- 已经值得纳入正式策略体系

进入条件：

- 回测 + 跟踪 + 现实样本都通过
- 能被明确映射到 `/watchlist` 和 `/research`

#### `retired`

含义：

- 当前不再继续投入研究

进入条件：

- 回测失真
- 环境适配过窄
- 实盘候选长期缺失
- 与现有策略高度重复

---

## 6. 与现有页面的连接

### 6.1 与 `/backtest`

`/backtest` 提供：

- 参数表单
- tearsheet
- 回测原始结果

`/strategy-lab/{experiment_id}` 消费：

- 回测摘要
- 归因结果
- 环境拆解

结论：

- `/backtest` 是工具页
- `/strategy-lab` 是策略对象页

### 6.2 与 `/market`

`/market` 提供：

- 当前 `market_phase`
- 当前 `strategy_climate`
- 当前行业顺风/逆风

`/strategy-lab/{experiment_id}` 要把它翻译成：

- 今天这条新策略顺风还是逆风

### 6.3 与 `/watchlist`

`/watchlist` 提供：

- 当前优先/观察/常规执行对象

`/strategy-lab/{experiment_id}` 要显示：

- 这条策略今天是否已有现实候选标的进入 watchlist

### 6.4 与 `/research`

如果候选标的存在：

- 直接链接到对应 `/research?stock_code=...`

目的：

- 不让新策略停留在抽象层
- 能立即落到具体个股研究

---

## 7. 数据合同

### 7.1 Experiment Meta

```json
{
  "experiment_id": "vcp_state_filter_v1",
  "strategy_name": "VCP + 三周期共振过滤",
  "parent_template": "vcp_variant",
  "version": "v1",
  "owner": "internal",
  "status": "tracking",
  "created_at": "2026-05-29"
}
```

### 7.2 Definition

```json
{
  "what_it_captures": "抓收缩突破中同时具备中大周期背景支持的对象",
  "what_it_avoids": "避免仅靠日线冲高但大周期无共振的普通突破",
  "entry_logic": [
    "VCP 路径匹配",
    "ef_count >= 2",
    "D1 处于突破或活跃推进段"
  ],
  "exit_logic": [
    "跌破关键均线",
    "State 跌出有效组合"
  ],
  "filters": [
    "行业不处于明显退潮",
    "市场阶段不处于全面收缩"
  ]
}
```

### 7.3 Fit Summary

```json
{
  "best_state_combos": ["E/E/F", "E/F/F"],
  "weak_state_combos": ["0/0/C", "C/0/0"],
  "best_market_phases": ["趋势新生", "趋势延展早期"],
  "weak_market_phases": ["退潮", "高离散震荡"],
  "best_industries": ["电子", "汽车"],
  "weak_industries": ["房地产", "非银金融"]
}
```

### 7.4 Tracking Summary

```json
{
  "today_market_fit": "适配",
  "today_fit_reason": "当前市场 breadth 改善，VCP climate 为最佳适配",
  "candidate_count": 4,
  "candidate_codes": ["000997.SZ", "300975.SZ"],
  "watchlist_link": "/watchlist"
}
```

---

## 8. 页面状态与前台文案

### 8.1 给用户看的不是“策略很强”

前台文案要避免：

- “新策略效果很好”
- “值得重点买入”
- “大概率有效”

前台应该说：

- 这条新策略目前处于什么阶段
- 它在哪些环境下更有研究价值
- 今天是否值得继续跟踪

### 8.2 推荐前台句式

#### 顶部一句话

- `当前处于 tracking：回测结果具备继续跟踪价值，但仍需观察现实样本是否稳定出现。`

#### 环境判断

- `这条策略更适合在 E/E/F、趋势新生阶段观察，不适合在高离散退潮环境中直接使用。`

#### 今日结论

- `今天市场环境与该策略基本匹配，已有 4 个候选对象进入观察。`

---

## 9. 不做什么

Phase 1 不做：

1. 自由策略脚本编辑器
2. 网页端参数网格搜索
3. 自动晋升正式策略
4. 下单/模拟交易入口
5. 复杂协作审批流

---

## 10. 实施优先级

### P0

1. 新增实验对象 schema
2. 新增 `/strategy-lab` 列表页
3. 新增 `/strategy-lab/{experiment_id}` 详情页静态合同
4. 与 `/backtest` 结果结构打通

### P1

1. 接入 `market_phase` / `strategy_climate`
2. 接入 `watchlist` 候选对象
3. 显示今日市场适配状态

### P2

1. 接入更多环境归因
2. 增加实验版本对比
3. 增加 promoted / retired 治理看板

---

## 11. 一句话结论

这个页面值得做，但它的本质不是“再造一个回测页”，而是：

**把新策略从一个想法，变成一个有状态、有环境解释、有现实候选标的连接的可跟进对象。**
