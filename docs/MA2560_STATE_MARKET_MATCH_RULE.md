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
AND (macro_etf_ef_count >= 2 OR 无行业ETF字段时仅记为个股规则成立)
```

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

## 复现命令

```bash
python3 scripts/analyze_2560_state_market_match.py --date 20260521
python3 -m py_compile scripts/analyze_2560_state_market_match.py
```

输出：

```text
outputs/project/2560_state_market_match.md
```

