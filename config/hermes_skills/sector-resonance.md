---
name: sector-resonance
description: 查询今日板块共振信号（哪些行业正在集体启动）
trigger: 哪些行业在动 / 板块共振 / 什么板块在涨 / 资金流向 / 行业共振
---

# Sector Resonance Skill

当用户询问板块或行业动向时，执行板块共振检测。

## 架构路径规则

- 活跃系统范围仅限 A 股。
- 这是查询型 skill，优先走只读检测。
- 板块共振结果属于观察层，不是交易指令层。
- 如果后续补服务接口，优先挂到 `hermass_platform/api/a_share_service.py` 的只读扩展，而不是新增独立入口。
- 回答时不要把行业共振描述成操作建议。

## 执行命令

```bash
cd /Users/lv111101/Documents/hermass-observer-product && .venv/bin/python -c "
from hermass_platform.slice.industry_slice import detect_sector_resonance
from hermass_platform.agents.base_agent import find_foundation_db
db = find_foundation_db()
if db:
    results = detect_sector_resonance(str(db))
    print(f'板块共振信号: {len(results)} 个行业')
    for r in results[:5]:
        print(f'  {r[\"sw_l1\"]}: {r[\"resonance_count\"]} 只共振（置信度: {r[\"confidence\"]}）')
"
```

## 回答模板

列出共振行业、共振数量、置信度。如果无共振，说明"今日无板块级共振信号"。

## 合规规则

- 板块共振是"资金正在涌入"的客观描述，不是"应该买入"的建议
- 末尾加免责声明
