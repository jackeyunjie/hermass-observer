---
name: strategy-advisor
description: 查询今日最佳适配策略信号、个股 State 快照、策略表现
trigger: 今天有什么机会 / 有什么信号 / XX股票怎么样 / VCP表现 / 2560表现 / 布林强盗表现
---

# Strategy Advisor Skill

当用户询问策略信号或个股状态时，执行相应脚本获取数据。

## 架构路径规则

- 活跃系统范围仅限 A 股。
- 这是查询型 skill，不负责修改底座，不负责触发完整流水线。
- State 语义统一遵守 `docs/STATE_BASE_CONTRACT.md` 与 `docs/AGENT_PERSPECTIVE_ARCHITECTURE.md`。
- 如果后续补服务接口，优先挂到 `hermass_platform/api/a_share_service.py` 或其只读扩展。
- 不把历史 shell 脚本、MT5 文档、美股文档当成主路径。

## 查询今日信号

```bash
cd /Users/lv111101/Documents/hermass-observer-product && .venv/bin/python -c "
from hermass_platform.agents.strategy_advisor import StrategyAdvisor
agent = StrategyAdvisor()
result = agent.get_top_signals(limit=10)
print(result)
"
```

## 查询个股状态

当用户提到具体股票代码时：

```bash
cd /Users/lv111101/Documents/hermass-observer-product && .venv/bin/python -c "
from hermass_platform.agents.market_analyst import MarketAnalyst
agent = MarketAnalyst()
result = agent.get_stock_state('STOCK_CODE')
print(result)
"
```

## 回答模板

每条信号包含：股票代码+名称、策略类型、适配度、State 环境、本地验证数据。

## 合规规则

- 使用"观察"/"关注"等措辞，不用"买入"/"推荐"
- 末尾加免责声明
