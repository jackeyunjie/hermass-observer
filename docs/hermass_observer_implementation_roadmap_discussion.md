# Hermass Observer 落地计划（团队讨论稿）
> 基础来源：10 个核心问题 + Codex-2/3 + 三模型辩论结果 + Codex 5.5x 评审版
> 目的：把架构讨论转成团队可对齐的“目标-里程碑-owner-验收”框架，形成下一步行动共识

---

## 一、本计划使用说明

本文件不是最终 ToDo，而是**讨论用架构草案**。

- 其中日期、优先级、Owner 都是占位符，由团队会议拍板后替换。
- 用户无法修改代码，因此所有“讨论”最终都会收敛为：
  - 提交给服务器 Codex 的部署提示词
  - 可直接运行的本地脚本
  - 明确的产品/工程验收标准

---

## 二、漏斗层：先定义“我们到底在做什么”

### A. 用什么名字对内对外？
三个候选口径：

| 口径 | 对内工程叙述 | 对外产品叙述 | 风险 |
|------|-------------|-------------|------|
| A1 纯内核 | 多周期 Agent 市场态运转系统 | 市场态运转系统 | 与 Kimi 的 EF 筛选卖点冲突 |
| A2 分层包装 | 内核 = 运转系统；EF 是策略层信号灯 | 先呈现 EF 场，再下钻到运转系统 | 两面都需要维护 |
| A3 偏保守 | 仍把 EF 当首页第一信号，底层是运转系统 | 用户看不到术语变化 | 以后容易反绑 |

建议默认采用 **A2**，因为：
- 对工程师：系统是运转系统，容易做任务拆分。
- 对用户：EF 共振是直观入口，且与 3 个策略触发强关联。

### B. 首页到底保留什么？
团队必须先在这个问题上对齐，否则前端会持续陷入“信息过载”与“用户看不懂”的内耗。

**必须保留的功能块：**
1. 当前周期位置（三周期分布）
2. 策略触发计数（VCP / 2560 / Bandit）
3. Agent 脉搏（每个 Agent 简短摘要）
4. 行业 State 流（资金流向感）

**必须移除的页面块：**
1. 嵌套多层的物料装饰页
2. 账本详情级调试信息直接进入用户面
3. 原始价格图表/技术指标原始值公开版

### C. 必须避免的认知陷阱
- 不要把“首页展示 EF 股票列表”与“首页只展示 EF 股票列表”混为一谈。
- 不要把“动态权重”实现成“每天自由浮动”，必须有规则窗口与熔断。
- 不要把“自组织 Agent”实现成“任意 Agent 可改策略结构”，那会越过 Kimi 提出的红线。

---

## 三、里程碑草案（建议分 3 波）

### 第一波：可观测性与数据主权（建议 1-2 周）
目标：让系统从“能看到 EF”升级为“能看到运转状态”。

| 任务 | 预期产出 | 验收标准 |
|------|----------|----------|
| DuckDB 物化视图 `bb_pivot_atr_daily` | 可查询表 | 全市场 5510×3 可在分钟级返回 |
| 数据质量主权层 | `data_quality_score` 字段 | 停牌/涨跌停/ST/IPO 首日显式标记 |
| 三周期权重基线接入 | 权重配置表 | W1/D1/MN1 可以在配置中心切换 |
| EF2 首页面板替换 | 先去掉装饰页，只保留触发计数+行业流 | 不依赖原概念页 |

**讨论点：** 数据质量层里“ST/上市首日无涨跌幅限制”的异常值，是否直接废弃日线计入三周期，还是标为 DEGRADED 仍计入？

### 第二波：收缩观测 Agent 独立上线（建议 2-3 周）
目标：把 Q7 从概念验证转成可稳定运行的 Agent。

| 任务 | 预期产出 | 验收标准 |
|------|----------|----------|
| Triple Squeeze 检测 | 三重交叉任务 | BB+SR+ATR 三重同时满足才触发 |
| 四重突破确认 | 策略辅助层 | V1/V2/V3/V4 映射到置信度分档 |
| Supersede 机制 | 重入控制 | 同标的突破后 20 日内不再重复触发 |
| 触发日志写前向观察账本 | 可审计样本 | 每个触点保存 stock/code/date/rule_set_hash |

**讨论点：** 是否允许“V1+V2”就确认突破？Claude 主张四选三最高优先级，Kimi 主张两重满足+延迟确认。建议默认 **四选三**，但 V3（EF2/State）可兑换一个等价分，作为保留意见。

### 第三波：多 Agent 自组织 + 降级运行（建议 1-2 个月）
目标：系统从“有”演化到“可自治且可失败”；强调 Assume Failure。

| 任务 | 预期产出 | 验收标准 |
|------|----------|----------|
| Agent 死亡计数器 | fail_count 机制 | 超过阈值自动停用并广播 agent_disabled |
| 静态降级映射表 | fallback_pipeline | market_analyst/strategy_advisor/contraction_observer 有兜底 |
| Redis Streams/事件总线 | message schema | source/target/event_type/payload/ttl/req_id |
| 混沌演练 | kill 一个 Agent | 不级联瘫痪，降级 1 分钟内生效 |

**讨论点：** 是否现在就把 Hermes-agent 的“Skill 自动创建”引入？建议本次先不引入，待第三波稳定后再讨论。

---

## 四、可以直接发给服务器 Codex 的部署提示词模板

以下三段文本，团队会议对齐后可直接发给服务器执行者。

### 4.1 部署版本 A：仅页脚与展示层调整（最小可行）
```
在 /opt/hermass 执行部署：

1. git pull
2. source .venv/bin/activate && python -m py_compile web/main.py
3. sudo systemctl restart hermass-console && sudo systemctl status hermass-console
4. 冒烟验证：
   - curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/
   - curl -s -X POST http://localhost:8020/api/chat/query ... | grep provider

验收：服务 active (running)，HTTP 200，provider 符合预期
```

### 4.2 部署版本 B：收缩观测物化视图上线（中等）
```
在 /opt/hermass 执行部署：

1. git pull
2. source .venv/bin/activate && python -m py_compile web/main.py && python scripts/rebuild_bb_pivot_atr.py
3. sudo systemctl restart hermass-console && sudo systemctl status hermass-console
4. 冒烟验证：
   - curl -s http://localhost:8020/api/contract_quality | jq '.rows | length'
   - curl -s http://localhost:8020/api/contract_quality | jq '.rows[] | select(.state=="DEGRADED") | .code' | head

验收：服务 active (running)；2026-06-01 批次可返回 DEGRADED 标记
```

### 4.3 部署版本 C：全链路灰度（大变更）
```
在 /opt/hermass 执行部署：

1. git pull
2. make db-migrate
3. source .venv/bin/activate && python -m py_compile web/main.py
4. sudo systemctl restart hermass-console && sudo systemctl status hermass-console
5. 冒烟验证：
   - curl -s http://localhost:8020/health
   - curl -s http://localhost:8020/api/agents/status
   - 日志 grep 'agent_disabled' 0 条
   - 日志 grep 'degraded' 有且仅当故意演练时

验收：服务 active (running)；health 200；Agent 无意外降级
```

---

## 五、给前端/产品的建议落地版本

### 5.1 首页信息架构重新切割

| 层级 | 受众 | 内容 | 建议交互 |
|------|------|------|----------|
| L1（秒级） | 用户 | 当日 EF 新增/消失数量和策略触发计数 | 红黄绿灯 + 数字 |
| L2（分钟级） | 用户 | 行业 State 流 + 三周期共振热点 | 颜色条+收缩/突破标签 |
| L3（日级） | 用户 | 需要人工介入异常数和胜率偏离榜 | 列表+下钻入口 |
| 调试层 | 运维/产品 | 原始 K 线、指标数值、Agent 推理链 | 需要登录+权限，默认折叠 |

### 5.2 权重配置化读法
- 不要放在前端参数表单里直接改数值；
- 改为“策略档位”：
  - 震荡市档位
  - 趋势市档位
  - 极端分叉档位
- 三个档位各自绑定一组 W1/D1/MN1 权重，由系统策略 advisor 根据市场熵切换。

### 5.3 行业表达逻辑
- 一级行业只用于展示层热力图；
- 二级行业才进入信号修正；
- 对外口径统一为“行业先验修正系数”，不出现“行业权重”用户术语。

---

## 六、团队讨论清单（可直接拿去开会）

建议按顺序讨论并给出明确结论：

1. 口径选择：A1/A2/A3，你们要哪个？
2. 数据质量异常值：停牌/涨跌停/ST/IPO 首日，是什么策略？（废弃、降级、保留标记）
3. 三重/四重验证：突破确认默认几重？V3 是否允许等价得分？
4. 权重切换：静态基线还是目录档位？谁有权切换？
5. 自组织边界：Q4 阶段 3 是否现在就启动消息总线？
6. 外部引入优先级：agentmemory vs Karpathy vs Harness，先来哪个？
7. 混沌演练：多久一次？谁来 kill？
8. 前端展示层：L1/L2/L3 三层分级是否接受？
9. 降级演练：Acceptable degradation 是什么？
10. 下一步唯一输出：会后必须有“一条可落地的动作”和负责人。

---

## 七、风险与盲点总览（供讨论前阅读）

| 风险 | 来源问题 | 讨论重点 |
|------|----------|----------|
| 行业口径问题 | Q3 | 二级行业用 Wind/同花顺/申万，还是自建？ |
| 小样本漂移 | Q4/Q6/Q9 | 500+ 样本需要约 2 年，是否先用模拟迁移学习？ |
| 降级时数据完整 | Q8/Codex-3 | 功能可以降级，数据历史不允许丢 |
| 前端信任迁移 | Q1 | 去掉 K 线会削弱专业用户信任，需保留“透视”下钻 |
| 因子免疫稳态缺失 | Q6/加分题 | 目前所有模型都未给出“耐受带”机制 |
| 政策驱动无先验 | Kimi-2 | 贝叶斯在无历史先验场景可能过于保守 |
| 质量主权 | Codex 挑战 | DuckDB 不会自动知道脏数据，前置 QC 层是强约束 |

---

## 八、结论模板（供会议后填写）

| 决策点 | 结论 | 负责人 | 下次检查时间 |
|--------|------|--------|------------|
| 产品内核命名 | | | |
| 首页保留项 | | | |
| 权重方案 | | | |
| 异常数据处理 | | | |
| 引入外部方案 | | | |
| 降级演练频率 | | | |
| 唯一下一步动作 | | | |

