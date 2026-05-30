---
name: market-analyst
description: 查询 A 股市场状态、E/F 池规模、行业共振、宏观环境
trigger: 市场怎么样 / 今天市场 / 大盘状态 / 宏观环境 / 哪些行业在动
---

# Market Analyst Skill

当用户询问市场状态时，执行以下脚本获取数据，然后用中文回答。

## 架构路径规则

- 活跃系统范围仅限 A 股。
- 这是查询型 skill，优先走只读查询，不触发执行链路。
- 回答口径以 `README.md`、`docs/SYSTEM_ARCHITECTURE.md`、`docs/STATE_BASE_CONTRACT.md` 为准。
- 不把 MT5 / US / Alpaca 相关内容当成当前规则源。
- 如果后续改造成服务调用，优先接 `hermass_platform/api/a_share_service.py` 的只读接口，而不是新增散落脚本。

## 执行命令

```bash
cd /Users/lv111101/Documents/hermass-observer-product && .venv/bin/python -c "
from hermass_platform.agents.market_analyst import MarketAnalyst
agent = MarketAnalyst()
result = agent.analyze_market_environment()
print(result)
"
```

## 回答模板

根据返回数据，用以下结构回答：

1. 市场阶段：（趋势行进/趋势新生/趋势延展/收缩期/风险释放）
2. 全三 E/F 池：X 只（较前日 +/-N）
3. 宏观环境：X/10（象限名称）
4. 板块共振：X 个行业出现共振（列出前 3 个）

## 合规规则

- 不输出买入/卖出/推荐/建议等词汇
- 末尾加免责声明："以上为环境观察，不构成操作建议。"
