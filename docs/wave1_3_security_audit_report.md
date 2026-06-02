# Hermass 波1-3 新增代码安全审计报告
> 范围：scripts/add_data_quality_fields.py、scripts/init_agent_memory.py、hermass_platform/agents/contraction_observer.py、hermass_platform/bus/agent_bus.py、hermass_platform/red_lines.py、config/redlines.yaml、web/templates/index.html、web/templates/watchlist.html
> 日期：2026-06-02
> 执行人：Codex（静态审计，不修改代码）
> 约束：BB/枢轴/ATR 表已建但无数据，本次不评价数据量/性能，只审结构、契约、安全与渲染。

---

## 执行摘要

- 高风险：1 项
- 中风险：4 项
- 低风险/信息项：6 项

最关键结论：
1. 数据质量脚本有实现遗漏和误判风险
2. 五条红线目前是“可选调用函数”，不是系统级强制拦截
3. AgentBus 文件队列存在竞态条件
4. contraction_observer 存在可预见的性能/执行模型风险，但内存泄漏有限
5. 前端模板与后端变量耦合过紧，删除面板会直接导致 Jinja2 500

---

## 逐项审计

### 1. scripts/add_data_quality_fields.py：数据标记逻辑
- 发现 1：ST 标记未实现。代码注释明确写了“当前库无 stock_name 列，预留扩展”，但 `update_data_quality_score()` 中没有把 ST 作为规则执行。
  - 严重性：中
  - 是否需要人干预：是
  - 建议：要么补齐 stock_name/ST 标记来源，要么显式在配置里关闭此规则并加警告注释。

- 发现 2：post_suspension_days 回填以“daily_bars 缺失即停牌”为核心假设。
  - 如果 daily_bars 本身有断层、未同步完成、或 ETF/指数混入，会把“数据缺失”误判为“停牌”。
  - 严重性：高
  - 是否需要人干预：是
  - 建议：引入独立 trade_calendar 表，并在脚本里显式区分“日历缺失 vs 个股数据缺失”。

- 发现 3：DEGRADED 规则只产出 0/1，不区分具体违规类型。
  - 无法追溯到底是“停牌”还是“涨跌停”导致标记。
  - 严重性：低
  - 是否需要人干预：否（建议后续改进）

- 发现 4：backup 表策略。
  - 当前是 `CREATE TABLE ... AS SELECT *` 全表快照；全量 `d1_perspective_state` 通常很大，DDL 期间锁表/IO 风险高。
  - 严重性：中
  - 是否需要人干预：是（至少确认存储空间和锁表窗口可接受）

### 2. scripts/init_agent_memory.py：DDL 和外键
- 发现 5：DuckDB 外键声明。
  - `judgment_outcomes` 声明了 `FOREIGN KEY (judgment_id) REFERENCES agent_judgments(judgment_id)`，但 DuckDB 默认不强制外键（需开启约束 enforcement）。脚本没有 `PRAGMA foreign_keys = ON` 或等效命令。
  - 严重性：中
  - 是否需要人干预：是
  - 建议：如果业务上需要级联删除保护，必须显式启用约束；否则删掉外键声明，避免“看起来有保护，实际没有”。

- 发现 6：幂等性。
  - `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` 已做到幂等，这很好。
  - 但表存在时不会更新已有索引定义（如字段类型变化不会自动改）。
  - 严重性：低
  - 是否需要人干预：否

### 3. hermass_platform/agents/contraction_observer.py：5510 只逐行查询
- 发现 7：全市场逐只 iterrows + 每只多次 SQL。
  - `evaluate_breakout()` 对每只股票执行多轮 SQL（V1-V6），没有批量化、没有 join 优化、没有缓存。
  - 5510 只 × 可能数百只触发收缩会导致大量串行查询。
  - 严重性：高
  - 是否需要人干预：是
  - 建议：把 V1-V6 改成批量 SQL 或 DataFrame 向量化计算；至少按 timeframe+stock_code 做批量 IN 查询。

- 发现 8：内存风险有限，但 DataFrame 累积风险存在。
  - 代码会累积 `breakout_results`、`judgments`、`extreme_stocks`，然后切片到 50/20。
  - 不会无限膨胀，因为目标只有收缩股票子集，不是全市场。
  - 严重性：低
  - 是否需要人干预：否

### 4. hermass_platform/bus/agent_bus.py：文件队列竞态
- 发现 9：poll 读后删除（unlink）无文件锁。
  - 多实例/多进程同时 poll 时，同一消息文件可能被重复处理或丢失。
  - subscriptions.json 读写也无锁，cross-process 下可能覆盖。
  - 严重性：高
  - 是否需要人干预：是
  - 建议：如果计划部署多进程/多 worker，先切换为带锁的队列（如 SQLite 或基于文件锁的文件队列）。至少加 advisory lock 或改成 move-to-processing 两阶段提交。

### 5. hermass_platform/red_lines.py：五条红线是否真的无法绕过
- 发现 10：红线是“可用函数”，不是“系统级硬门控”。
  - 五条红线都实现了独立函数，但业务代码是否在“所有触发点”调用它们，代码层面没有全局强制。
  - 例如：
    - 红线 1（止损/止盈）需要业务层在每次执行前调用 `require_human_confirmation()`，目前没有装饰器或 middleware 证明所有下单路径都覆盖。
    - 红线 2（策略结构修改）只拦截通过 `guard_strategy_structure()` 的修改；若某处直接改文件/DB，不会触发。
    - 红线 4（仓位上限）参数 `override_token` 虽然注释说“目前无效”，但函数签名存在，容易变成未来绕过口子。
  - 严重性：高
  - 是否需要人干预：是
  - 建议：
    1. 在 risk_guardian 和交易执行入口处加显式调用点；
    2. 移除 `override_token` 参数，避免误导；
    3. 对策略文件启用只读文件系统 mount 或应用层只读检查。

- 发现 11：红线文件 `strategy_structure_lock.json` 定义在 red_lines.py，但实际代码中没有写/读这个文件。当前策略保护完全靠内存里的 `PROTECTED_STRATEGIES`。
  - 严重性：中
  - 是否需要人干预：是
  - 建议：如果配置要求持久化锁，就补上读写；如果不需要，删掉常量减少歧义。

### 6. config/redlines.yaml：配置是否完整
- 发现 12：配置内容完整，覆盖 5 条红线及审计日志路径。
  - 但配置与代码之间有两处“双轨定义”：
    - `audit.log_file` 在 yaml 和 `RED_LINE_AUDIT_LOG` 常量并存
    - `strategy_structure_lock.json` 在 yaml 和代码并存
  - 严重性：低
  - 是否需要人干预：是（建议统一来源，避免以后维护时两边不一致）

### 7. web/templates/index.html：面板删除是否影响 Jinja2 渲染
- 发现 13：模板高度依赖后端变量，存在结构性脆弱。
  - 关键变量：`daily_brief`、`mode`、`industry`、`research_lane`、`execution`、`stock_code`、`render_profile`。
  - 若后端重构删除任何一块数据提供或字段改名，Jinja2 会直接抛 `UndefinedError`，导致整页 500。
  - 严重性：中
  - 是否需要人干预：是
  - 建议：在模板层加 `default()` 过滤，或后端提供最小兜底字典；高风险变量至少加 `is defined` / `default`。

- 发现 14：前端展示层已收敛，但仍然暴露内部术语（State/EF/RR/Cron）。
  - 这不属于安全漏洞，但属于产品语义风险。
  - 严重性：低
  - 是否需要人干预：否（信息项）

### 8. web/templates/watchlist.html：4 列是否正确显示
- 发现 15：当前 watchlist.html 主要表格为 5-6 列，不符合“4 列”表述。
  - 优先队列/观察队列/常规队列都是 6 列；高风报比是 5 列。
  - 如果产品要求“执行观察表 4 列”，当前实现不匹配。
  - 严重性：中（如果是 UI 规范要求）
  - 是否需要人干预：是
  - 建议：明确是否要求 4 列，以及“4 列”具体指哪 4 个字段。

---

## 总表：发现 + 严重性 + 是否需要人干预

| 编号 | 文件 | 发现 | 严重性 | 需要人干预 |
|------|------|------|--------|------------|
| 1 | add_data_quality_fields.py | ST 标记未实现 | 中 | 是 |
| 2 | add_data_quality_fields.py | 停牌判定依赖 daily_bars 缺失 | 高 | 是 |
| 3 | add_data_quality_fields.py | DEGRADED 不区分类型 | 低 | 否 |
| 4 | add_data_quality_fields.py | 全量备份表可能有 IO/锁风险 | 中 | 是 |
| 5 | init_agent_memory.py | 外键实际不强制 | 中 | 是 |
| 6 | init_agent_memory.py | 索引不自动演化 | 低 | 否 |
| 7 | contraction_observer.py | 全市场串行 SQL 性能风险 | 高 | 是 |
| 8 | contraction_observer.py | 内存累积可控 | 低 | 否 |
| 9 | agent_bus.py | 文件队列 poll 无锁 | 高 | 是 |
| 10 | red_lines.py | 红线是函数，不是系统强制门控 | 高 | 是 |
| 11 | red_lines.py | strategy_structure_lock.json 实际未使用 | 中 | 是 |
| 12 | redlines.yaml | 双轨定义（yaml vs 常量） | 低 | 是 |
| 13 | index.html | 强依赖后端变量，删除面板易 500 | 中 | 是 |
| 14 | index.html | 术语暴露（信息项） | 低 | 否 |
| 15 | watchlist.html | 当前不是 4 列，若规范要求 4 列则需调整 | 中 | 是 |

---

## 建议修复优先级（不修改代码，只列优先级）

1. 立即确认并统一：
   - 红线如何变成“全局强制拦截”（红10）
   - AgentBus 是否会在多 worker 下运行（红9）

2. 上线前确认：
   - daily_bars 断层假设是否成立（红2）
   - index.html 依赖的后端变量删除边界（红13）
   - 5510 只股票逐行查询的可接受时长（红7）

3. 后续优化：
   - ST 标记补齐（红1）
   - 备份表容量/锁表策略（红4）
   - 外键 enforcement 或删除声明（红5）
   - yaml 与常量双轨整理（红12）
   - watchlist 4 列需求澄清（红15）

---

## 结论

波1-3 新增代码在“功能可用性”上基本到位，但在**安全边界、并发正确性和前后端契约稳定性**上还有明显缺口。建议在进入下一阶段前，优先处理红2、红7、红9、红10。
