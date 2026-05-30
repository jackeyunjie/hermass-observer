# Active State Alerts Spec

版本：v0.1  
日期：2026-05-28  
范围：A 股 / Research-Only / 飞书群主动推送

## 1. 目标

主动推送不是替代研究卡，而是把“值得马上知道的状态变化”从被动问答改成系统提醒。

Phase 1 目标：

- 不盯盘
- 不刷屏
- 不做交易指令
- 只推最小结构变化

## 2. Phase 1 触发条件

只做 3 类提醒：

1. `State` 跌出提醒  
   例：`E/E/F -> E/E/C`

2. `D1` 连续走弱提醒  
   例：`D1` 状态分值连续 3 个交易日下降，且仍处于用户近期关注标的范围内

3. 行业共振 / 退潮提醒  
   例：标的所在一级行业进入共振，或原有共振明显回落

## 3. 用户范围

Phase 1 不做“全市场广播”，只对以下对象推送：

- 飞书群中的公共 watchlist
- 或最近 7 天被群内问过的股票

当前最小数据来源：

- `outputs/cognitive/behavior_*.json`
- 近期飞书消息形成的 `stock_lookup / market_query / strategy_query`

## 4. 推送格式

必须极简：

```text
000021 State 提醒：D1 从 F 回落到 C。
原因：三周期共振被打断，短周期先转入确认。
```

或：

```text
电子行业共振提醒：今日共振确认家数升至 8。
原因：板块同步强化，个股信号更适合结合行业一起观察。
```

限制：

- 最多两行
- 不给建议
- 不贴长表
- 不重复推相同事件

## 5. 去重规则

同一股票 / 同一事件类型 / 同一交易日，只推一次。

建议唯一键：

```text
{trade_date}:{stock_code}:{alert_type}:{new_state_or_bucket}
```

## 6. 数据来源

Phase 1 只用本地结构化数据：

- `d1_perspective_state`
- `strategy_reminders`
- `state_transition_latest.json`
- `industry_slice.detect_sector_resonance(...)`
- `behavior ledger`

不依赖外网新闻。

## 7. 建议落点

建议新增一条独立脚本：

```text
scripts/send_active_state_alerts_to_lark.py
```

推荐执行顺序：

1. 读取最近 7 天关注标的
2. 对每只标的计算是否命中 3 类提醒
3. 写入去重 ledger
4. 用 `lark-cli` 发群消息

## 8. 暂不做

- 个性化订阅中心
- 持仓级别盈亏提醒
- 盘中分钟级推送
- 多轮自然语言解释
