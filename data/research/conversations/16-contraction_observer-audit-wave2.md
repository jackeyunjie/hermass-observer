# ContractionObserver 审计报告（Wave 2）
> 范围：`hermass_platform/agents/contraction_observer.py`
> 说明：BB/枢轴/ATR 表已建但无数据，本次不审数据量，只审结构、逻辑与接口契约。

---

## 1) AgentContext 继承是否一致
- 代码中已导入 `AgentContext` 和 `AgentResult`
- 入口函数 `observe_contraction()` 显式构造了 `AgentContext(agent_id=..., agent_name=..., user_id=..., session_id=..., target_date=..., foundation_db=...)`
- 但后续仍自行打开 `AgentMemory.duckdb`，未通过 `AgentContext` 传入
- **结论**：继承关系成立，但上下文基类与 AgentMemory 连接逻辑未统一

## 2) 三重交叉“三选二”是否正确
- `contraction_count = bb + pivot + atr`
- `is_contraction = contraction_count >= 2`
- 与需求一致
- **结论**：实现正确

## 3) 六重确认是强制 gate 还是加权评分
- 当前实现：
  - `V1` 单独为 False 时直接进入“未突破/观察”
  - `V1+V2` → “疑似突破”
  - `V1+V2+V3+V4` → “确认突破”
  - `V5/V6` 只作为加分权重
- 等于“V1 必选 + 组合门槛”，不是六重全硬卡
- **结论**：若规格要求“V1-V4 必须全通过”，则代码尚未满足

## 4) Supersede 20日去重是否精确
- 确实按 20 日窗口检查
- 但是：
  - 用 `LIKE '%{stock_code}%'` 做去重，不是精确键
  - 多次开库：`write_judgment()` 与 `check_supersede()` 分开连库，并发或重入下可能重复写入
- **结论**：机制存在，但不精确，有重复触发风险

## 5) AgentMemory 写入字段是否与 schema 匹配
- 写入字段：`agent_id, judgment_id, judgment_date, judgment_type, judgment_content, confidence, factors_used, context_snapshot`
- `scripts/init_agent_memory.py` 的 `agent_judgments` 表正好是这 8 字段
- **结论**：当前路径匹配

## 6) AgentBus 是否覆盖 6 topic + JSON schema 校验
- 当前代码只用到 `AgentBus.publish(from_agent, to_agent, topic, payload, priority)`
- 只发了 `contraction_extreme`
- 未看到 6 topic 常量定义，也未看到 JSON schema 校验
- **结论**：尚未完成 6 topic schema 落地

## 7) 全市场 5510 只股票的内存/性能风险
- 主循环 `for _, row in contraction_df.iterrows():`
- 每次循环若干次 `conn.execute(...).fetchdf()`
- 内存风险为中等，性能风险为高
- **结论**：当前实现是“逐只股票串行查询”，不适合全市场

---

## 问题清单（严重性 + 建议）

| 编号 | 问题 | 严重性 | 建议 |
|------|------|--------|------|
| A | V1-V4 未做成硬 gate，与规范可能不一致 | High | 将 V1-V4 设为 break_required，代码里只做 through or reject |
| B | Supersede 用 LIKE 字符串匹配，精度不足 | High | 增加 breakout_id 或唯一索引，避免 stock_code 前缀/子串误匹配 |
| C | 主循环逐行查询，5510 只股票会慢 | High | 改成批量 DataFrame/join 或批次执行的向量化逻辑 |
| D | AgentMemory 每次任务重复开/关连接 | Medium | 复用同一连接或用连接池，避免反复 open/close |
| E | AgentBus 只有 1 个 topic，无 schema 校验 | Medium | 定义 topic 常量与 schema，并在 publish 前校验 |
| F | 6 个标准 topic 之名与实现不一致 | Medium | 先冻结 6 topic 清单，再逐一补到 publish 路径 |
| G | 极端收缩提示广播数量硬编码为 10 | Low | 更像配置项而非硬编码 |
