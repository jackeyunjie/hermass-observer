# State Timeline Observer 设计稿

版本：v1.0  
日期：2026-07-01  
状态：设计稿  
定位：查询与导出层 / 展示层  
关联文档：

- `docs/STATE_BASE_CONTRACT.md`
- `docs/STATE_DISPLAY_ALIAS_SPEC.md`
- `docs/state_base_extension_design.md`

---

## 1. 目标

`State Timeline Observer` 的目标不是替代策略判断，也不是提前定义 State 的唯一用法。

它的职责是：

1. 为任意股票组合提供可回溯的 State 时间表。
2. 支持任意时间窗口查询，而不是固定 `3/6/30` 这类预设。
3. 同时支持网站交互浏览、邮件摘要和批量导出。
4. 让用户自己观察、总结和验证 State 的用法。
5. 为后续 Strategy Agent、Router、Ledger 提供统一观察底座。
6. 不只统计 `E/F`，也统计 `A/B` 和 `0` 这类关键状态事件。

一句话定义：

```text
任意股票组合 × 任意时间窗口 的 State 时间表查询与导出系统
```

---

## 2. 边界

### 2.1 做什么

- 查询单只、多只、自选池、行业池、全市场的 State 时间表。
- 查询任意天数窗口或任意日期区间。
- 展示 `MN1 / W1 / D1` 三周期状态及其变化轨迹。
- 输出 CSV / JSON / HTML / 邮件摘要。
- 提供筛选、排序、分组、导出。

### 2.2 不做什么

- 不直接给买卖点、目标价、止损价。
- 不把 State 时间表包装成交易指令。
- 不修改 `State 底座契约` 中的底层编码规则。
- 不把 `E/F` 直接解释为“可以买/必须卖”。

### 2.3 与现有架构的关系

```text
Foundation DB / State Cache
    -> State Timeline Observer
        -> 网站表格 / 邮件摘要 / 导出任务
        -> Strategy Agent 消费
        -> Observation Ledger 后验分析
```

Observer 是消费层，不是底座层。

---

## 3. 核心原则

### 3.1 长表真相源

底层真相结构固定为：

```text
一只股票 × 一个交易日 = 一行
```

而不是：

- `3日一行`
- `6日一行`
- `30日一行`

这些都只是查询视图或导出形态，不是主数据结构。

### 3.2 任意参数，不写死预设

系统能力必须支持：

- 任意股票组合
- 任意时间窗口

`3/6/30`、`Top50`、`Watchlist` 只能作为快捷入口，不是边界。

### 3.3 小查询同步，大查询异步

产品语义可以是“任何参数都能查”，但实现不能假设“任何参数都秒开”。

因此分两类：

1. 交互式查询
   适合少量股票、短时间窗、页面直接展示。
2. 批量导出
   适合全市场、长时间窗、大行数导出。

---

## 4. 数据模型

### 4.1 真相表建议

建议新增或物化一张查询友好的长表，例如：

`state_timeline_daily`

建议来源：

- 主来源：`d1_perspective_state`
- 辅助补充：`daily_bars`、`timeframe_indicators`、行业映射、展示别名

### 4.2 建议字段

最小必备字段：

| 字段 | 说明 |
|------|------|
| `stock_code` | 股票代码 |
| `stock_name` | 股票简称 |
| `state_date` | 交易日 |
| `mn1_state_hex` | `state_hex(D1, MN1)` |
| `w1_state_hex` | `state_hex(D1, W1)` |
| `d1_state_hex` | `state_hex(D1, D1)` |
| `mn1_state_score` | 月线 State score |
| `w1_state_score` | 周线 State score |
| `d1_state_score` | 日线 State score |
| `mn1_is_ef` | 月线是否为 E/F |
| `w1_is_ef` | 周线是否为 E/F |
| `d1_is_ef` | 日线是否为 E/F |
| `mn1_is_ab` | 月线是否为 A/B |
| `w1_is_ab` | 周线是否为 A/B |
| `d1_is_ab` | 日线是否为 A/B |
| `mn1_is_zero` | 月线是否为 0 |
| `w1_is_zero` | 周线是否为 0 |
| `d1_is_zero` | 日线是否为 0 |
| `ef_count` | E/F 周期数，辅助字段 |
| `ef_pattern` | 例如 `MN1+W1` / `W1+D1` / `MN1+W1+D1` |
| `ab_count` | A/B 周期数，辅助字段 |
| `ab_pattern` | 例如 `MN1+W1` / `W1+D1` / `MN1+W1+D1` |
| `zero_count` | 0 周期数，辅助字段 |
| `zero_pattern` | 例如 `MN1+W1` / `W1+D1` / `MN1+W1+D1` |
| `close` | 当日收盘价 |
| `volume` | 当日成交量 |
| `industry_l1` | 一级行业 |
| `industry_l2` | 二级行业或主题 |
| `state_triplet` | 例如 `E/E/F` |
| `display_alias` | 展示别名 |
| `resonance_tag` | 共振标签 |
| `risk_tag` | 风险标签 |
| `as_of_date` | 数据有效日期 |

增强字段：

| 字段 | 说明 |
|------|------|
| `mn1_alias_label` | 月线中文别名 |
| `w1_alias_label` | 周线中文别名 |
| `d1_alias_label` | 日线中文别名 |
| `state_change_flag` | 是否发生切换 |
| `ef_change` | 对比上一个交易日的 EF 数量变化 |
| `resonance_score` | 共振强度评分 |
| `transition_label` | 例如 `E/E/0 -> E/A/0`；首条记录显示「初始状态」 |
| `watch_hint` | 观察提示，不是交易建议 |

### 4.3 不建议做法

不要把最近 `N` 天横向铺成大量列作为主表，例如：

- `mn1_state_t`
- `mn1_state_t1`
- `mn1_state_t2`

这种宽表可以用于某些邮件导出，但不应该作为核心真相表。

### 4.4 EF 统计原则

`ef_count` 不能作为主统计口径。

原因：

- 它把 `MN1 / W1 / D1` 三个周期的 E/F 混成一个总数。
- `MN1+W1`、`W1+D1`、`MN1+D1` 的意义完全不同。
- 对用户来说，“有 2 个 EF”不等于“我知道强在哪里”。

因此 Observer 的主视图和主统计必须改为：

1. 分周期统计
   - 月线 EF 有哪些
   - 周线 EF 有哪些
   - 日线 EF 有哪些
2. 周期交集统计
   - `MN1+W1`
   - `W1+D1`
   - `MN1+D1`
   - `MN1+W1+D1`

`ef_count` 只保留为：

- 后台过滤字段
- 辅助排序字段
- 详情中的附加信息

不应作为首页、邮件、Observer 第一屏的主指标。

### 4.5 关键状态事件原则

Observer 不能只围绕 `E/F` 建模。

至少要把三类事件拆开统计：

1. `E/F`
   - 含义：强趋势突破
   - 角色：强共振、强推进、强趋势延续
2. `A/B`
   - `A = 扩张 + 无趋势 + 突破 + 稳定`
   - `B = 扩张 + 无趋势 + 突破 + 活跃`
   - 角色：关键位已突破，但趋势尚未完全确立，属于重要概率变化事件
3. `0`
   - `0 = 收缩 + 无趋势 + 未突破 + 稳定`
   - 角色：收缩较为充分、蓄力较为完整、值得重点观察后续释放

因此 Observer 的事件层应采用：

```text
事件族 = EF 族 + AB 族 + ZERO 族 + 后续可扩展族
```

本轮先正式支持：

- `EF` 事件
- `A/B` 关键位突破事件
- `0` 收缩充分事件

不允许再把“所有重要状态”重新压扁成一个总数。

正确做法是：

1. 分事件族统计
   - 月线 EF
   - 周线 EF
   - 日线 EF
   - 月线 A/B
   - 周线 A/B
   - 日线 A/B
   - 月线 0
   - 周线 0
   - 日线 0
2. 分交集模式统计
   - `EF: MN1+W1`
   - `EF: W1+D1`
   - `AB: MN1+W1`
   - `AB: W1+D1`
   - `ZERO: MN1+W1`
   - `ZERO: W1+D1`
3. 再保留辅助计数字段
   - `ef_count`
   - `ab_count`
   - `zero_count`

---

## 5. 查询模型

### 5.1 查询能力定义

Observer 必须支持以下输入方式：

- 单只股票
- 多只股票
- 任意股票代码数组
- 全市场
- 预定义集合：`watchlist` / `top_n` / 行业池 / 策略池

时间范围支持：

- `days`
- `date_from + date_to`

两类参数只需支持其中一类作为最终条件：

```text
days = 20
或
date_from = 2026-06-01, date_to = 2026-07-01
```

### 5.2 Query Schema

建议统一为：

```json
{
  "symbols": "all",
  "symbol_list": [],
  "symbol_set": "",
  "date_from": "2026-06-01",
  "date_to": "2026-07-01",
  "days": 20,
  "filters": {
    "mn1_is_ef": null,
    "w1_is_ef": null,
    "d1_is_ef": null,
    "mn1_is_ab": null,
    "w1_is_ab": null,
    "d1_is_ab": null,
    "mn1_is_zero": null,
    "w1_is_zero": null,
    "d1_is_zero": null,
    "ef_pattern_any": [],
    "ab_pattern_any": [],
    "zero_pattern_any": [],
    "ef_count_min": null,
    "ab_count_min": null,
    "zero_count_min": null,
    "industry_l1": [],
    "state_hex_any": [],
    "resonance_tag": [],
    "risk_tag": []
  },
  "sort_by": "state_date_desc",
  "fields": [
    "stock_code",
    "stock_name",
    "state_date",
    "mn1_state_hex",
    "w1_state_hex",
    "d1_state_hex",
    "ef_count"
  ],
  "page": 1,
  "page_size": 100
}
```

### 5.3 参数说明

| 参数 | 说明 |
|------|------|
| `symbols` | `all` 或保留空 |
| `symbol_list` | 明确给定的股票数组 |
| `symbol_set` | 命名集合，如 `watchlist` / `top50` / `industry:半导体` |
| `days` | 相对窗口天数 |
| `date_from/date_to` | 绝对区间 |
| `mn1_is_ef / w1_is_ef / d1_is_ef` | 分周期 EF 过滤 |
| `mn1_is_ab / w1_is_ab / d1_is_ab` | 分周期 A/B 过滤 |
| `mn1_is_zero / w1_is_zero / d1_is_zero` | 分周期 0 过滤 |
| `ef_pattern_any` | 指定交集模式，如 `["MN1+W1", "W1+D1"]` |
| `ab_pattern_any` | 指定 A/B 交集模式，如 `["MN1+W1", "W1+D1"]` |
| `zero_pattern_any` | 指定 0 交集模式，如 `["MN1+W1", "W1+D1"]` |
| `filters` | 结构、行业、风险等过滤 |
| `fields` | 只取需要展示或导出的列 |
| `page/page_size` | 页面交互式分页 |

规则：

- `days` 与 `date_from/date_to` 二选一，若同时存在，优先 `date_from/date_to`
- `symbol_list` 优先级高于 `symbols`

---

## 6. 输出模型

### 6.1 交互式查询输出

适用于网站和 API。

```json
{
  "ok": true,
  "query": {...},
  "meta": {
    "row_count": 1200,
    "symbol_count": 50,
    "date_min": "2026-06-24",
    "date_max": "2026-07-01",
    "as_of_date": "2026-07-01"
  },
  "rows": [...]
}
```

### 6.2 导出任务输出

适用于全市场或长时间窗。

```json
{
  "ok": true,
  "task_id": "state_timeline_export_20260701_xxx",
  "status": "queued",
  "format": "csv",
  "estimated_rows": 165390,
  "download_path": ""
}
```

### 6.3 支持格式

- `json`
- `csv`
- `html`
- `parquet`（后续可选）

---

## 7. 网站交互设计

### 7.1 页面定位

建议新增页面：

`/state-observer`

不是仪表盘，也不是研究页替代，而是“状态时间表工作台”。

### 7.2 页面结构

1. 顶部参数条
   - 股票集合选择
   - 单只/多只输入
   - 时间窗口输入
   - 行业筛选
   - State 筛选
   - 事件族切换：`全部 / EF / A+B / 0`
   - 分周期 EF 筛选
   - 分周期 A/B 筛选
   - 分周期 0 筛选
   - EF 交集模式筛选
   - A/B 交集模式筛选
   - 0 交集模式筛选
   - 导出按钮

2. 主表格
   - 一行 = 一只股票某一天
   - 默认按 `stock_code, state_date desc` 展示
   - 同一只票连续多行上下排列，方便目视对比

3. 右侧或抽屉详情
   - 点某只票后展示这只票的时间轨迹
   - 可附加状态切换摘要

### 7.3 表格默认列

- 股票代码
- 股票简称
- 日期
- `MN1`
- `W1`
- `D1`
- `月线 EF`
- `周线 EF`
- `日线 EF`
- `月线 A/B`
- `周线 A/B`
- `日线 A/B`
- `月线 0`
- `周线 0`
- `日线 0`
- `EF 模式`
- `A/B 模式`
- `0 模式`
- 行业
- 收盘价
- 风险标签
- 研究入口

### 7.4 重要交互

- 支持按股票分组折叠
- 支持按日期倒序
- 支持冻结表头
- 支持只看“状态发生变化”的行
- 支持只看月线 EF / 周线 EF / 日线 EF
- 支持只看月线 A/B / 周线 A/B / 日线 A/B
- 支持只看月线 0 / 周线 0 / 日线 0
- 支持只看指定交集模式，如 `MN1+W1`
- 支持在 `EF`、`A/B`、`0` 三类事件之间切换
- 支持切换显示 raw state / 中文别名

### 7.5 页面主文案原则

必须明确：

```text
这是 State 观察表，不是交易指令面板。
```

---

## 8. 邮件输出设计

### 8.1 邮件不是全量导出

邮件不适合发 5000 多只股票的长表。

邮件只发摘要视图，例如：

- 今日状态变化最大的股票
- 月线 EF 样本
- 周线 EF 样本
- 日线 EF 样本
- 月线 A/B 样本
- 周线 A/B 样本
- 日线 A/B 样本
- 月线 0 样本
- 周线 0 样本
- 日线 0 样本
- 周期交集样本
- 风险标签新增样本
- 某个用户自选池最近 N 天状态表

### 8.2 邮件参数

建议支持：

```json
{
  "symbol_set": "watchlist",
  "days": 3,
  "sort_by": "change_strength_desc",
  "limit": 50,
  "format": "html_email"
}
```

### 8.3 邮件结构

1. 顶部摘要
2. 状态变化样本表
3. 月线 EF / 周线 EF / 日线 EF 分组
4. 月线 A/B / 周线 A/B / 日线 A/B 分组
5. 月线 0 / 周线 0 / 日线 0 分组
6. 周期交集分组
7. 风险提示分组
8. 链接回网站完整表格

---

## 9. 性能分层

### 9.1 同步查询阈值

建议：

- `symbol_count <= 200`
- `date_rows <= 30`
- `estimated_rows <= 10000`

则走同步查询。

### 9.2 异步导出阈值

以下任一满足，转后台任务：

- 全市场
- 日期范围超过 60 个交易日
- 预计行数超过 10000
- 请求 `csv/parquet` 导出

### 9.3 导出任务模型

建议新增：

- `task_id`
- `query_json`
- `status`
- `created_at`
- `finished_at`
- `output_path`
- `row_count`

可复用现有用户任务或批处理任务机制。

---

## 10. 与现有模块衔接

### 10.1 Foundation DB

主依赖：

- `d1_perspective_state`
- `daily_bars`
- 必要时 `timeframe_indicators`

### 10.2 daily_snapshot

`daily_snapshot` 继续做首页和市场页的压缩摘要，不替代 State 时间表。

### 10.3 strategy_signal_daily

可在 Observer 中追加策略标签列，但策略信号不是 Observer 的主键。

关系应为：

```text
State Timeline = 基础观察层
Strategy Signal = 策略解释层
```

### 10.4 research

研究页可从 Observer 跳入：

- 单只股票最近 N 天 State 轨迹

### 10.5 Strategy Agent / Ledger

后续每个 Strategy Agent 都可以直接消费同一张时间表。

优势：

- 用户先看原始状态轨迹
- Agent 再解释这些轨迹
- Ledger 再记录解释是否有效

---

## 11. API 建议

### 11.1 查询接口

建议新增：

`GET /api/state-observer`

支持 query params：

- `symbols`
- `symbol_set`
- `date_from`
- `date_to`
- `days`
- `ef_count_min`
- `industry_l1`
- `page`
- `page_size`

### 11.2 导出接口

建议新增：

`POST /api/state-observer/export`

返回任务状态。

### 11.3 单票轨迹接口

建议新增：

`GET /api/state-observer/timeline?stock_code=000001.SZ&days=30`

用于研究页和详情抽屉。

---

## 12. 实施路径

### Phase 1：MVP

目标：

- 先支持网站浏览和小规模导出

任务：

1. 构建 `state_timeline_daily` 查询层
2. 提供 `/api/state-observer`
3. 新建 `/state-observer` 页面
4. 支持：
   - 单只
   - 多只
   - Top50
   - 全市场分页
   - 任意 `days`

### Phase 2：邮件与导出

目标：

- 支持用户自选池、任意窗口 HTML 邮件和 CSV 导出

任务：

1. 增加导出任务接口
2. 增加邮件模板
3. 支持 `watchlist` 与 `custom symbol_list`

### Phase 3：与 Agent 融合

目标：

- Observer 成为多 Strategy Agent 的公共输入层

任务：

1. 给 Agent 统一读取接口
2. 增加状态变化摘要字段
3. 把 Agent 判断写入 Ledger 后可反向对照时间表

---

## 13. 前后端与网站同步要求

`State Timeline Observer` 不能只改后端查询，也不能只改页面样式。

每次迭代必须同步三层：

### 13.1 后端契约同步

后端改动必须同时同步：

- 代码注释
- 查询视图注释
- 查询参数 schema
- 返回字段 schema
- 导出任务 schema
- 字段解释文档

硬要求：

1. 新增字段时，先更新设计稿和 API 返回说明。
2. 删除或重命名字段时，必须先做兼容层，不能直接破坏前端。
3. `mn1_is_ef / w1_is_ef / d1_is_ef / ef_pattern` 必须作为正式字段暴露，不允许只在前端临时拼接。
4. 查询层和接口层如果存在容易误解的字段，必须加短注释说明，不允许只靠历史记忆。

### 13.2 前端展示同步

网站设计必须跟查询模型一起演进。

硬要求：

1. 页面主口径与后端主口径一致：
   - 主统计看月线 EF / 周线 EF / 日线 EF / 交集模式
   - 不再以混合 `ef_count` 做第一屏组织
2. 页面筛选器名称必须与 API 参数一致：
   - `mn1_is_ef`
   - `w1_is_ef`
   - `d1_is_ef`
   - `ef_pattern_any`
3. 页面表头、筛选项、详情抽屉、导出字段要用同一套命名。
4. 网站、邮件、导出三端显示顺序保持一致：
   - 分周期 EF
   - 周期交集
   - 状态轨迹
   - 风险提示

### 13.3 网站设计同步

`/state-observer` 页面不是技术调试台，必须按产品化页面设计。

设计同步要求：

1. 第一屏先给用户明确任务入口：
   - 看哪组股票
   - 看多长时间
   - 看哪个周期的 EF
2. 不要让第一屏堆满全市场统计数字。
3. 默认视图先给“分周期 EF 分组”和“交集分组”，再给长表。
4. 数字、字母、中文解释的显示顺序保持统一：
   - 默认数字
   - 辅助字母
   - 悬停或展开时显示中文解释
5. 网站和邮件使用同一套用户语言，不用内部脚本口径。

### 13.4 验收同步

每次迭代至少要同步验收以下四项：

1. API 验收
   - 参数是否按设计稿生效
   - 返回字段是否完整
2. 页面验收
   - 筛选器是否与 API 对齐
   - 第一屏主口径是否仍正确
3. 导出验收
   - CSV/JSON 字段是否与页面字段一致
4. 邮件验收
   - 分组逻辑、字段名称、链接参数是否与网站一致

### 13.5 注释与文档同步

除了代码和页面本身，还必须同步更新以下内容：

1. 代码注释
   - 查询主逻辑
   - 分周期 EF 派生逻辑
   - `ef_pattern` 生成规则
2. 产品/设计文档
   - `STATE_TIMELINE_OBSERVER_SPEC.md`
   - 如有新增 API，再补接口说明文档
3. 运行/交付文档
   - 若接入日更流水线、邮件或导出任务，必须补到对应 SOP
4. 验收文档
   - 若页面主口径变化，必须同步更新 PM 测试说明和验收脚本

执行原则：

- 改字段，要同步改注释
- 改页面口径，要同步改设计文档
- 改导出逻辑，要同步改运行文档
- 改验收规则，要同步改验收脚本

### 13.6 禁止事项

以下做法禁止：

- 后端已经切到分周期 EF，前端仍显示混合 `ef_count` 主统计
- 页面写“月线 EF”，接口实际返回的是总 `ef_count`
- 邮件摘要用一套分组逻辑，网站页面用另一套分组逻辑
- 设计稿已改，但 API/页面/导出没有一起更新
- 代码逻辑已改，但注释和文档还停留在旧口径

---

## 14. 成功标准

任意一个用户都可以完成以下任务：

1. 查询任意股票组合最近任意天数的 `MN1/W1/D1` State 轨迹。
2. 在网页中直接上下对比同一只票多天状态变化。
3. 导出大范围时间表做自定义研究。
4. 不依赖系统预设结论，自己总结 State 用法。
5. 后续在同一时间表上叠加 Strategy Agent 的解释。

---

## 15. 最终结论

`State Timeline Observer` 不应该被做成几个固定数字的报表，也不应该被包装成已经完成策略结论的系统。

它应该被定义为：

```text
一个基于 State 底座的任意股票组合 × 任意时间窗口 查询、浏览、导出工作台
```

这会比当前“把 State 直接推成决策层”更稳，也更适合后面扩展多个 Strategy Agent。
