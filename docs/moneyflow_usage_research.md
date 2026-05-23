# 资金流有效用法调研与 P116 落地规则

## 结论

资金流最稳的用法不是单独选股，而是作为 P116 state 之后的证据层：

1. **确认**：三周期 E/F 已成立时，资金流同向提高观察优先级。
2. **否决/降级**：状态强但资金持续流出，标记为背离复核，不进入组合候选前列。
3. **风险预警**：价格创新高但大额资金不跟随，标记为高位分歧。
4. **新进排序**：新进入三周期 E/F 的股票里，优先看大额净流入和连续净流入。
5. **覆盖审计**：资金流缺失不等于看空，只标记为数据缺口。

## 不采用的弱用法

- 不用“单日主力净流入”为独立买点。
- 不用“资金流排名第一”覆盖 state、SR、AMA、周线质量门。
- 不把大单/特大单简单等同机构；A 股按订单大小识别投资者类型存在误判风险。
- 不用资金流生成收益承诺或确定性方向判断。

## 最高确定性组合规则

### Gate 0: 数据覆盖

- `moneyflow_coverage = row_count / code_count`
- 覆盖不足时资金流只作显示，不进评分。
- 请求错误和无记录分开记录。

### Gate 1: P116 状态先行

只在以下基础池里使用资金流：

- `MN1/W1/D1` 全部为正向 `E/F`
- 通过 W1 质量门：非连续 3 周下跌，且 W1 close >= AMA10
- SR 位置没有负向破位

### Gate 2: 资金流确认

计算字段：

- `active_net = 主买总额 - 主卖总额`
- `big_order_net = (特大单主买 + 大单主买) - (特大单主卖 + 大单主卖)`
- `active_net_ratio = active_net / 主买总额`
- `positive_days_5d = active_net > 0 的天数`
- `big_positive_days_5d = big_order_net > 0 的天数`
- `latest_active_net`
- `latest_big_order_net`

确认条件：

```text
positive_days_5d >= 3
AND big_positive_days_5d >= 3
AND active_net_5d > 0
AND big_order_net_5d > 0
AND latest_active_net > 0
```

### Gate 3: 背离复核

以下情况不直接剔除，但进入风险复核：

```text
state_score_sum 高
AND d1_close > d1_sr_resistance
AND active_net_5d < 0
```

或者：

```text
price_5d_change > 0
AND big_order_net_5d < 0
```

### Gate 4: 排序，不做裁决

资金流只调整排序权重，不决定入池：

```text
final_score =
  state_score * 1.00
  + structure_quality * 1.00
  + moneyflow_confirmation * 0.25
  - moneyflow_divergence_penalty * 0.50
```

资金流权重低于 state/SR/趋势结构。

## P116 字段映射

黑狼资金流字段：

- `buytddcje`, `selltddcje`: 特大单主买/主卖成交额
- `buyddcje`, `sellddcje`: 大单主买/主卖成交额
- `buyzdcje`, `sellzdcje`: 中单主买/主卖成交额
- `buysdcje` 或 `buyxdcje`, `sellxdcje`: 小单主买/主卖成交额
- `buynum`, `sellnum`, `totalnum`: 买卖笔数/总笔数

派生字段：

```text
buy_total = buytddcje + buyddcje + buyzdcje + buyxdcje/buysdcje
sell_total = selltddcje + sellddcje + sellzdcje + sellxdcje
active_net = buy_total - sell_total
big_order_net = (buytddcje + buyddcje) - (selltddcje + sellddcje)
```

## 研究依据

- Order imbalance 比单纯成交量更接近买卖压力方向；但短周期里会受到 bid-ask bounce 和流动性冲击影响。
- A 股里大户/机构订单流对未来收益的预测更稳定，小散订单流经常反向预测。
- 按订单大小区分散户/机构在 A 股存在误判，不能把“大单=机构”当成强结论。
- 资金流预测能力对测量方法和持有期敏感，因此必须通过 walk-forward 验证。

## 落地优先级

1. 建立 `moneyflow_evidence_YYYYMMDD.json/csv`
2. 给推荐工作台增加资金流确认/背离字段
3. 回测 `state only` vs `state + moneyflow confirmation`
4. 加入行业层面的资金流集中度
5. 对缺失/错误代码做 retry 和 coverage 报告

## Sources

- Chordia & Subrahmanyam, "Order imbalance and individual stock returns: Theory and evidence"
- Chordia, Roll & Subrahmanyam, "Order Imbalance, Liquidity and Market Returns"
- Bennett & Sias, "Can Money Flows Predict Stock Returns?"
- Li, Wu, Zhang & Zhang, "Tracking Retail and Institutional Investors Activity in China"
- "Understanding Retail Investors: Evidence from China"
- Annual Review of Financial Economics, "Retail and Institutional Investor Trading Behaviors: Evidence from China"
