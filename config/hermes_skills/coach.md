---
name: coach
description: 交易知识问答、State 系统教学、策略概念解释
trigger: 什么是State / E/F是什么意思 / VCP怎么理解 / 2560是什么 / 学习 / 教我
---

# Coach Skill

当用户询问交易知识或系统概念时，从知识库中检索答案。

## 架构路径规则

- 活跃系统范围仅限 A 股。
- Coach 的概念解释以 `docs/SYSTEM_ARCHITECTURE.md`、`docs/STATE_BASE_CONTRACT.md`、`docs/AGENT_PERSPECTIVE_ARCHITECTURE.md` 为准。
- 解释运行时时，必须明确：
  - `shared core layer = agently_adapter/a_share_core.py`
  - `core flow = agently_adapter/agently_a_share_flow.py`
  - `full compatibility workflow = agently_adapter/agently_daily_flow.py`
  - `API service layer = hermass_platform/api/a_share_service.py`
- 不引用 MT5 / US / Alpaca 文档作为当前活跃规则。

## 执行命令

```bash
cd /Users/lv111101/Documents/hermass-observer-product && .venv/bin/python -c "
from hermass_platform.agents.coach import CoachAgent
agent = CoachAgent()
results = agent.search_knowledge(['USER_QUERY_KEYWORDS'])
for r in results[:3]:
    print(f'【{r[\"topic\"]}】{r[\"concept\"]}: {r[\"content\"]}')
"
```

## 知识库覆盖

- State 系统：4-bit 编码、E/F 定义、ef_count、D1 视角
- VCP 策略：策略逻辑、与 E/E/F 组合的验证数据
- MA2560 策略：金叉/死叉逻辑、出场规则
- 布林强盗：信号触发条件、vol=0 更优的发现
- 风险管理：止损方法、回撤分级
- 系统指南：简报解读、认知提升路径
