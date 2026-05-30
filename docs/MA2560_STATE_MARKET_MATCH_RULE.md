# 2560 State 与市场匹配规则

日期：2026-05-22  
规则状态：有条件成立  
配置文件：`config/ma2560_state_market_match_rule.json`  
复现脚本：`scripts/analyze_2560_state_market_match.py`

## 结论

2560 “适合”规则可以进入系统规则层，但只能作为候选质量证据，不是无条件买入信号。

当前可复现组合：

```text
VOL5 > VOL60
AND 买入日低点触及 MA25 2% 区间
AND (收盘在 MA25 2% 区间 OR 强势评分 >= 6)
AND 止跌代理成立
```

与 P116 state 对齐后，可先认定的 state 组合：

```text
{E/E/F, E/F/F, E/F/E} + ma2560_strong_hold
```

市场匹配：

```text
P116个股匹配
AND 行业ETF ef_count >= 2
```

行业ETF 支持字段优先级：

```text
1. recommendation/outputs/p116_recommendation_YYYYMMDD.csv 中的 macro_etf_ef_count
2. 若推荐 CSV 未覆盖该股票，则用 outputs/ifind/industry_YYYYMMDD.json 的 sw_l1
   映射 config/industry_rotation_assets.json 中的行业ETF
3. 再读取 outputs/market_assets_state/market_assets_state_YYYYMMDD.csv 的 ETF ef_count
```

只有行业ETF `ef_count >= 2` 才能认定为 `full_match`。行业未配置ETF时记为
`stock_only`；行业ETF存在但 `ef_count < 2` 时记为 `market_unsupported`。

2026-05-22 已将黑狼 ETF 清单与 iFind 一级行业映射接入覆盖审计，新增 10 个直接行业 ETF：

```text
交通运输、传媒、公用事业、建筑材料、房地产、机械设备、环保、石油石化、计算机、钢铁
```

剩余 `stock_only` 主要来自没有直接行业 ETF 的代理问题，例如轻工制造、社会服务、商贸零售、美容护理。

## 复现证据

`data/project` Top20 成功样本：

| 条件 | 命中 |
|---|---:|
| VOL5 > VOL60 | 20/20 |
| 买入日低点触及 MA25 2% 区间 | 20/20 |
| 收盘在 MA25 2% 区间 | 17/20 |
| MA25 上行 | 17/20 |
| 强势评分 >= 6 | 19/20 |

正式 P116 recommendation 输出中，`ma2560_strong_hold` 的 state 分布：

| state | 数量 |
|---|---:|
| E/E/F | 17 |
| E/F/F | 11 |
| E/F/E | 2 |

市场支持：

- 30 个 `ma2560_strong_hold` 推荐样本中，24 个有行业 ETF `ef_count >= 2` 支持。
- 5 个缺行业 ETF 字段。
- 少量行业状态不支持，因此不能说无条件成立。

扩展 ETF 覆盖后的全量策略账本证据见：

- `outputs/ma2560_market_match_forward/ma2560_market_match_forward_20260522.*`
- `outputs/ma2560_market_match_forward/ma2560_stock_only_gap_audit_20260522.*`
- `public/industry_etf_coverage_20260522.html`

## 使用边界

1. `data/project` 自身没有历史买入日正式 MN1/W1/D1 state 字段。
2. 历史 Top20 只能证明 2560 技术组合，不足以单独证明正式 P116 state。
3. 正式 state/市场匹配需要结合：
   - `recommendation/outputs/p116_recommendation_YYYYMMDD.csv`
   - `outputs/market_assets_state/market_assets_state_YYYYMMDD.csv`
4. 行业 ETF 缺失时，只能记为“个股规则成立”，不能记为“市场匹配完整成立”。

## 推荐系统用法

在推荐系统中建议增加三个布尔/枚举字段：

```text
ma2560_local_combo_pass
ma2560_p116_state_match
ma2560_market_match_level
```

其中 `ma2560_market_match_level` 可取：

```text
full_match        # 个股规则 + state组合 + 行业ETF ef_count >= 2
stock_only        # 个股规则 + state组合，但行业ETF字段缺失
market_unsupported# 个股规则 + state组合，但行业ETF不支持
not_match
```

截至 2026-05-22，全量 `strategy_signal_daily` 中的 `ma2560_strong_hold`
按该口径分布为：

| 匹配等级 | 数量 |
|---|---:|
| full_match | 62 |
| stock_only | 8 |
| market_unsupported | 97 |
| not_match | 519 |

说明：上述全量口径不同于 recommendation Top30 口径。Top30 只能用于展示层抽样，
不能作为全量策略研究样本。

`stock_only` 从扩展 ETF 前的 48 条下降为 8 条；新增直接行业 ETF 后，一部分样本被明确归入
`market_unsupported`，这表示“行业 ETF 已有数据但未达到 `ef_count >= 2`”，不再混同为缺数据。

前向验证脚本：

```bash
python3 scripts/analyze_ma2560_market_match_forward.py --date 2026-05-22
```

输出：

```text
outputs/ma2560_market_match_forward/ma2560_market_match_forward_YYYYMMDD.*
public/ma2560_market_match_forward_YYYYMMDD.html
```

## 复现命令

```bash
python3 scripts/analyze_2560_state_market_match.py --date 20260521
python3 -m py_compile scripts/analyze_2560_state_market_match.py
```

输出：

```text
outputs/project/2560_state_market_match.md
```
