# KIMI 任务：State Timeline Observer Phase 1 MVP

日期：2026-07-01  
负责人：KIMI  
审计与收口：Codex

---

## 一、背景

Hermass 当前已经完成 `2026-07-01` 日更与网站验收，PM preflight 通过。

现在进入下一条产品主线：

```text
State Timeline Observer
```

目标不是继续把 State 直接做成决策层，而是先做一个：

```text
任意股票组合 × 任意时间窗口 的 State 时间表查询与导出工作台
```

已确定原则见：

- `docs/STATE_TIMELINE_OBSERVER_SPEC.md`
- `docs/STATE_BASE_CONTRACT.md`
- `docs/STATE_DISPLAY_ALIAS_SPEC.md`

本轮最重要的产品原则：

1. 支持任意股票组合，不写死 `1/50/5000`
2. 支持任意时间窗口，不写死 `3/6/30`
3. 底层使用长表真相源：`一只股票 × 一个交易日 = 一行`
4. 主统计口径不再先看混合 `ef_count`
5. 主统计改为：
   - 月线 EF
   - 周线 EF
   - 日线 EF
   - 月线 A/B
   - 周线 A/B
   - 日线 A/B
   - 月线 0
   - 周线 0
   - 日线 0
   - 周期交集模式 `MN1+W1 / W1+D1 / MN1+D1 / MN1+W1+D1`
6. `A/B` 视为关键位突破事件，不得忽略
7. `0` 视为收缩充分事件，不得忽略
8. 注释、文档、前后端、验收脚本必须同步更新

---

## 二、目标

交付 `State Timeline Observer` Phase 1 MVP：

1. 后端有可查询的时间表数据层
2. 提供只读 API
3. 提供基础页面 `/state-observer`
4. 页面与 API 使用同一套字段和口径
5. 支持小范围同步查询
6. 支持 CSV 导出
7. 不引入交易建议表达

---

## 三、交付范围

### 1. 后端数据层

实现一个查询友好的长表视图或查询层，建议命名：

```text
state_timeline_daily
```

来源优先：

- `d1_perspective_state`
- `daily_bars`
- 必要的行业映射
- 展示别名派生字段

本轮必须产出的字段：

- `stock_code`
- `stock_name`
- `state_date`
- `mn1_state_hex`
- `w1_state_hex`
- `d1_state_hex`
- `mn1_state_score`
- `w1_state_score`
- `d1_state_score`
- `mn1_is_ef`
- `w1_is_ef`
- `d1_is_ef`
- `mn1_is_ab`
- `w1_is_ab`
- `d1_is_ab`
- `mn1_is_zero`
- `w1_is_zero`
- `d1_is_zero`
- `ef_count`
- `ef_pattern`
- `ab_count`
- `ab_pattern`
- `zero_count`
- `zero_pattern`
- `close`
- `volume`
- `industry_l1`
- `state_triplet`
- `display_alias`
- `as_of_date`

要求：

- `mn1_is_ef / w1_is_ef / d1_is_ef` 必须是正式字段
- `mn1_is_ab / w1_is_ab / d1_is_ab` 必须是正式字段
- `mn1_is_zero / w1_is_zero / d1_is_zero` 必须是正式字段
- `ef_pattern` 必须是正式字段，不能只在前端拼接
- `ab_pattern` 必须是正式字段，不能只在前端拼接
- `zero_pattern` 必须是正式字段，不能只在前端拼接
- `ef_count` 保留，但只能做辅助字段
- `ab_count` 保留，但只能做辅助字段
- `zero_count` 保留，但只能做辅助字段
- `A/B` 语义按现有项目口径处理：
  - `A = 扩张 + 无趋势 + 突破 + 稳定`
  - `B = 扩张 + 无趋势 + 突破 + 活跃`
  - 它们属于关键位突破与概率变化事件，不等同于 `E/F`
- `0` 语义按现有项目口径处理：
  - `0 = 收缩 + 无趋势 + 未突破 + 稳定`
  - 它属于收缩充分与等待释放事件，不等同于泛收缩

### 2. API 层

新增只读接口，建议：

```text
GET /api/state-observer
GET /api/state-observer/timeline
```

本轮至少支持参数：

- `symbols`
- `symbol_set`
- `date_from`
- `date_to`
- `days`
- `mn1_is_ef`
- `w1_is_ef`
- `d1_is_ef`
- `mn1_is_ab`
- `w1_is_ab`
- `d1_is_ab`
- `mn1_is_zero`
- `w1_is_zero`
- `d1_is_zero`
- `ef_pattern_any`
- `ab_pattern_any`
- `zero_pattern_any`
- `page`
- `page_size`
- `format=csv|json`

规则：

- `days` 与 `date_from/date_to` 二选一
- 单只、多只、Top50、全市场分页必须可用
- 小查询同步返回
- 本轮可以先不做后台异步导出任务

### 3. 前端页面

新增页面：

```text
/state-observer
```

页面要求：

1. 第一屏先给用户参数入口，不堆大统计数字
2. 第一屏必须支持事件族切换：
   - `EF`
   - `A+B`
   - `0`
   - `全部`
3. 在任一事件族下，主分组必须是：
   - 月线 EF
   - 周线 EF
   - 日线 EF
   - 周期交集
   如果切到 `A+B`，则对应为：
   - 月线 A/B
   - 周线 A/B
   - 日线 A/B
   - 周期交集
   如果切到 `0`，则对应为：
   - 月线 0
   - 周线 0
   - 日线 0
   - 周期交集
4. 长表按：
   - 股票
   - 日期
   上下排列，方便用户比较连续多天
5. 默认显示：
   - 数字 `state_score`
   - 辅助字母 `state_hex`
   - 展开后显示中文解释
6. 不允许第一屏主标题或主统计仍然以混合 `ef_count` 组织
7. 不允许把 `A/B` 隐藏到详情里，只给 `E/F`
8. 不允许把 `0` 降级成普通明细字段，不进入主观察分组

本轮最小功能：

- 单只股票最近 `N` 天
- 多只股票最近 `N` 天
- 全市场分页
- Top50
- 分周期 EF 筛选
- 分周期 A/B 筛选
- 分周期 0 筛选
- 交集模式筛选
- 导出 CSV

### 4. 文档与注释同步

除了代码实现，必须同步更新：

- 必要代码注释
- 如新增接口，补接口注释/说明
- 若页面口径落地与设计稿有偏差，必须更新：
  - `docs/STATE_TIMELINE_OBSERVER_SPEC.md`
- 若验收口径变化，必须同步：
  - `scripts/validate_website_data_sync.py`（仅在确有必要时）

禁止出现：

- 代码改了，设计稿没改
- 后端字段变了，前端表头还是旧口径
- 页面按月线/周线/日线分组，API 却只返回 `ef_count`

---

## 四、实施建议

### Step 1：先做查询层

优先做一个最小查询实现，不要一开始就铺太多 UI。

建议先做：

- 查询函数
- API
- JSON 返回

先确认以下请求可用：

1. 单只票最近 20 天
2. 50 只票最近 6 天
3. 全市场最近 3 天分页
4. 仅月线 EF
5. 仅周线 A/B
6. 仅日线 0
7. 仅 `W1+D1`

### Step 2：再做页面

页面先做工作台，不做花哨大屏。

关键是：

- 参数可控
- 表格清楚
- 上下对比直观

### Step 3：最后做导出

本轮先支持：

- `json`
- `csv`

不需要先做邮件。

---

## 五、验收命令

本地至少执行：

```bash
cd /Users/lv111101/Documents/hermass-observer-product
.venv/bin/python -m py_compile web/main.py
.venv/bin/python -m py_compile 你修改过的 Python 文件
```

如果新增 API，至少补一个最小接口验收：

```bash
curl -s "http://localhost:8020/api/state-observer?symbol_set=top50&days=3&page=1&page_size=20" | head -c 1200
```

如本地需要启动服务，自行选择未占用端口。

页面验收至少覆盖：

1. `/state-observer`
2. 单只票最近 20 天
3. Top50 最近 6 天
4. 仅月线 EF
5. 仅 `MN1+W1`
6. CSV 导出

---

## 六、硬约束

1. 不要重写 `State 底座契约`
2. 不要把 `ef_count` 又提升回主统计口径
3. 不要把 `A/B` 关键位突破排除在外
4. 不要把 `0` 收缩充分事件排除在外
5. 不要在页面里出现买入、卖出、止损、目标价等表达
6. 不要把本轮做成固定 `3/6/30` 报表
7. 不要让前后端字段名各说各话
8. 不要大范围改动无关页面
9. 不要提交原始数据、大型 DuckDB、导出文件

---

## 七、交付物

请交付：

1. 实现代码
2. 更新后的注释与必要文档
3. 本地验收结果
4. 一段简短说明：
   - 做了什么
   - 哪些参数已支持
   - 哪些能力留到 Phase 2

---

## 八、Codex 复核重点

Codex 会重点审：

1. 是否真的支持任意股票组合与任意时间窗口
2. 是否把 `mn1_is_ef / w1_is_ef / d1_is_ef / ef_pattern` 做成正式字段
3. 是否把 `mn1_is_ab / w1_is_ab / d1_is_ab / ab_pattern` 做成正式字段
4. 是否把 `mn1_is_zero / w1_is_zero / d1_is_zero / zero_pattern` 做成正式字段
5. 页面第一屏是否仍偷偷用混合 `ef_count` 当主统计，或把 `A/B`、`0` 藏起来不展示
6. API / 页面 / 导出 / 文档是否同步
7. 是否引入新的交易建议边界风险
