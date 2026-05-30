# 产业链动态表结构设计规范

版本：v1.0
日期：2026-05-23
状态：设计稿 — 待实现
关联脚本：`scripts/ifind_industry_chain.py`
关联数据库：`outputs/industry_chain/industry_chain_evidence.duckdb`

---

## 概述

本文档定义 `chain_dynamics`、`industry_position`、`chain_event_cross` 三张表的完整 Schema 和填充逻辑。这三张表是产业链动态证据层的核心结构，与现有的 `ifind_industry_chain_profile`（个股身份层）和 `macro_chain_prior`（宏观-产业链先验层）共同构成产业链分析的完整数据栈。

**数据栈分层**：

```text
Layer 0: ifind_industry_chain_profile    — 个股产业链身份（已有，fundamental_evidence.duckdb）
Layer 1: chain_dynamics                  — 产业链环节级动态指标（本文档）
Layer 2: industry_position               — 行业级产业链定位与景气度（本文档）
Layer 3: chain_event_cross               — 事件 × 产业链影响交叉（本文档）
Layer 4: macro_chain_prior               — 宏观-产业链先验评分（已有，outputs/macro_chain_prior/）
```

---

## 1. chain_dynamics — 产业链动态指标表

### 1.1 定位

记录产业链各环节的动态指标时序数据。每条记录代表某个产业链在某个环节上的某个指标的最新观测值、趋势方向和历史分位。

与现有 `chain_dynamics` 表（事件驱动，记录标题/摘要）的区别：新表是**指标驱动**，记录可量化、可比较的数值型指标。

### 1.2 Schema

```sql
CREATE TABLE IF NOT EXISTS chain_dynamics (
    chain_id         VARCHAR    NOT NULL,   -- 产业链标识，如 "AI算力链" "新能源车链"
    chain_node       VARCHAR    NOT NULL,   -- 环节标识，如 "上游芯片" "中游封装" "下游应用"
    indicator_name   VARCHAR    NOT NULL,   -- 指标名称，如 "产品均价" "开工率" "库存天数"
    indicator_unit   VARCHAR,               -- 指标单位，如 "元/吨" "%" "天"
    latest_value     DOUBLE,                -- 最新观测值
    prev_value       DOUBLE,                -- 上一期观测值（用于计算变化）
    trend            VARCHAR,               -- 趋势方向：up / down / flat / turning_up / turning_down
    percentile_1y    DOUBLE,                -- 近 1 年历史分位（0-100）
    percentile_3y    DOUBLE,                -- 近 3 年历史分位（0-100）
    data_frequency   VARCHAR,               -- 数据频率：daily / weekly / monthly / quarterly
    source_period    VARCHAR,               -- 数据对应期间，如 "2026-05" "2026Q1"
    source_vendor    VARCHAR    DEFAULT 'iFinD',  -- 数据来源
    source_query     VARCHAR,               -- 来源查询标识或 API 路径
    confidence       DOUBLE    DEFAULT 1.0, -- 数据可信度 0-1
    as_of_date       VARCHAR    NOT NULL,   -- 观测日期 YYYY-MM-DD
    collected_at     VARCHAR    NOT NULL,   -- 入库时间 ISO-8601
    PRIMARY KEY (chain_id, chain_node, indicator_name, as_of_date)
);
```

### 1.3 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| chain_id | VARCHAR | 是 | 产业链唯一标识。取值来自 `config/chain_catalog.json`（见 1.5） |
| chain_node | VARCHAR | 是 | 产业链环节。取值：`上游` / `中游` / `下游` / `配套`，或更细粒度如 `上游-芯片设计` |
| indicator_name | VARCHAR | 是 | 指标名称。标准化命名，见 1.6 |
| indicator_unit | VARCHAR | 否 | 指标单位 |
| latest_value | DOUBLE | 否 | 最新观测值 |
| prev_value | DOUBLE | 否 | 上一期值。用于计算环比变化 |
| trend | VARCHAR | 否 | 趋势判断。由填充逻辑自动计算 |
| percentile_1y | DOUBLE | 否 | 近 1 年历史分位（0-100）。需至少 12 个历史数据点 |
| percentile_3y | DOUBLE | 否 | 近 3 年历史分位（0-100）。需至少 36 个历史数据点 |
| data_frequency | VARCHAR | 否 | 数据更新频率 |
| source_period | VARCHAR | 否 | 数据所代表的期间 |
| source_vendor | VARCHAR | 是 | 数据来源供应商 |
| source_query | VARCHAR | 否 | 来源查询标识，用于审计回溯 |
| confidence | DOUBLE | 是 | 数据可信度。新导入数据默认 1.0；降级填充或估算值降低此字段 |
| as_of_date | VARCHAR | 是 | 观测日期 |
| collected_at | VARCHAR | 是 | 入库时间 |

### 1.4 趋势计算规则

```text
IF latest_value IS NULL OR prev_value IS NULL:
    trend = NULL
ELSE IF abs(latest_value - prev_value) / max(abs(prev_value), 0.001) < 0.02:
    trend = "flat"
ELSE IF latest_value > prev_value:
    IF 近 3 期连续下行后首次上行:
        trend = "turning_up"
    ELSE:
        trend = "up"
ELSE:
    IF 近 3 期连续上行后首次下行:
        trend = "turning_down"
    ELSE:
        trend = "down"
```

### 1.5 产业链目录（config/chain_catalog.json）

```json
{
  "schema_version": "chain_catalog_v1",
  "chains": [
    {
      "chain_id": "ai_compute",
      "chain_name": "AI算力链",
      "description": "AI 芯片 → 算力服务器 → 数据中心 → AI 应用",
      "nodes": ["上游-芯片", "上游-存储", "中游-服务器", "中游-光模块", "下游-数据中心", "下游-AI应用"],
      "related_sw_l1": ["电子", "通信", "计算机"],
      "priority": 1
    },
    {
      "chain_id": "nev",
      "chain_name": "新能源车链",
      "description": "锂矿 → 电池材料 → 电芯 → 整车 → 充电设施",
      "nodes": ["上游-锂矿", "上游-正极材料", "中游-电芯", "中游-电解液", "下游-整车", "配套-充电桩"],
      "related_sw_l1": ["有色金属", "基础化工", "电力设备", "汽车"],
      "priority": 1
    },
    {
      "chain_id": "solar",
      "chain_name": "光伏链",
      "description": "硅料 → 硅片 → 电池片 → 组件 → 电站",
      "nodes": ["上游-硅料", "上游-硅片", "中游-电池片", "中游-组件", "下游-电站运营"],
      "related_sw_l1": ["电力设备", "机械设备"],
      "priority": 2
    },
    {
      "chain_id": "semiconductor",
      "chain_name": "半导体链",
      "description": "设计 → 制造 → 封测 → 设备 → 材料",
      "nodes": ["上游-设计", "上游-EDA/IP", "中游-制造", "中游-封测", "配套-设备", "配套-材料"],
      "related_sw_l1": ["电子"],
      "priority": 1
    },
    {
      "chain_id": "military",
      "chain_name": "军工链",
      "description": "原材料 → 分系统 → 总装 → 军贸",
      "nodes": ["上游-特种材料", "上游-电子元器件", "中游-分系统", "下游-总装"],
      "related_sw_l1": ["国防军工"],
      "priority": 2
    },
    {
      "chain_id": "consumer_spirits",
      "chain_name": "白酒消费链",
      "description": "粮食 → 酿造 → 品牌白酒 → 渠道分销",
      "nodes": ["上游-粮食", "中游-酿造", "下游-品牌白酒", "配套-渠道分销"],
      "related_sw_l1": ["食品饮料"],
      "priority": 2
    }
  ]
}
```

`priority` 决定填充优先级（见第 4 节）。

### 1.6 标准化指标命名

| 指标类别 | indicator_name 示例 | 适用环节 | 单位 |
|----------|---------------------|----------|------|
| 价格 | 产品均价 / 现货价 / 合同价 | 上中下游 | 元/吨、元/片、万元 |
| 产能 | 产能利用率 / 开工率 | 上中游 | % |
| 库存 | 库存天数 / 库存周转 | 上中游 | 天 |
| 需求 | 出货量 / 装机量 / 销量 | 中下游 | MW、GWh、万辆 |
| 盈利 | 毛利率 / 单位盈利 | 全环节 | %、元 |
| 技术 | 转换效率 / 良率 / 算力密度 | 中游 | %、TOPS |
| 政策 | 补贴标准 / 产能审批 | 全环节 | 万元/GW |
| 供需 | 供需缺口 / 产能过剩率 | 上中游 | % |

---

## 2. industry_position — 行业产业链定位与景气度表

### 2.1 定位

记录行业级（申万一级行业）在产业链中的位置、景气度评分和评级变化。与现有 `industry_position` 表（个股级，stock_code × industry）的区别：新表是**行业级**，以 `sw_l1` 为主键。

### 2.2 Schema

```sql
CREATE TABLE IF NOT EXISTS industry_position (
    sw_l1                VARCHAR    NOT NULL,   -- 申万一级行业
    chain_position       VARCHAR,               -- 产业链位置：上游 / 中游 / 下游 / 综合
    chain_ids            VARCHAR,               -- 所属产业链 ID 列表（JSON 数组），如 ["semiconductor","ai_compute"]
    prosperity_score     DOUBLE,                -- 景气度评分 0-10
    prosperity_prev      DOUBLE,                -- 上期景气度评分
    prosperity_change    VARCHAR,               -- 景气度变化：improving / stable / deteriorating
    rating               VARCHAR,               -- 当前评级：high / medium / low / unknown
    rating_prev          VARCHAR,               -- 上期评级
    rating_change        VARCHAR,               -- 评级变化：upgraded / downgraded / unchanged
    evidence_summary     VARCHAR,               -- 景气度证据摘要（不超过 500 字）
    upstream_score       DOUBLE,                -- 上游景气分项
    midstream_score      DOUBLE,                -- 中游景气分项
    downstream_score     DOUBLE,                -- 下游景气分项
    policy_support       VARCHAR,               -- 政策支持力度：strong / neutral / weak
    etf_symbol           VARCHAR,               -- 关联行业 ETF 代码
    etf_ef_count         INTEGER,               -- 关联行业 ETF 的 ef_count
    dynamic_indicator_count INTEGER,             -- 该行业 chain_dynamics 中有效指标数
    dynamic_event_count  INTEGER,               -- 该行业近 30 天 chain_event_cross 事件数
    source_vendor        VARCHAR    DEFAULT 'iFinD',
    as_of_date           VARCHAR    NOT NULL,
    collected_at         VARCHAR    NOT NULL,
    PRIMARY KEY (sw_l1, as_of_date)
);
```

### 2.3 景气度评分计算

景气度评分由以下分项加权得到：

```text
prosperity_score = clamp(
    0.30 * upstream_prosperity
  + 0.35 * midstream_prosperity
  + 0.20 * downstream_prosperity
  + 0.15 * policy_adjustment,
  0, 10
)
```

各分项计算：

| 分项 | 数据来源 | 计算方法 |
|------|----------|----------|
| upstream_prosperity | chain_dynamics 中该行业上游指标 | 上游指标中 trend=up/upturn 的比例 × 10 + 价格分位 × 0.3 |
| midstream_prosperity | chain_dynamics 中该行业 + ETF State | 开工率/产能利用率分位 × 5 + ETF ef_count × 2 + 趋势分 |
| downstream_prosperity | chain_dynamics 下游需求指标 + 行业 ETF 20d 收益 | 需求指标趋势 × 5 + ETF 近期表现 × 0.3 |
| policy_adjustment | chain_event_cross 中政策类事件 | 近 30 天正面政策事件数 × 0.5 - 负面政策事件数 × 0.5 |

### 2.4 评级映射

```text
prosperity_score >= 7.0  → rating = "high"
prosperity_score >= 4.5  → rating = "medium"
prosperity_score <  4.5  → rating = "low"
prosperity_score IS NULL  → rating = "unknown"
```

评级变化判定：

```text
IF rating != rating_prev AND rating_prev IS NOT NULL:
    IF rating_rank(rating) > rating_rank(rating_prev):
        rating_change = "upgraded"
    ELSE:
        rating_change = "downgraded"
ELSE:
    rating_change = "unchanged"
```

### 2.5 产业链位置映射

基于 `config/chain_catalog.json` 中 `chains[].nodes` 的定义，自动推导各行业在产业链中的位置：

```text
上游：sw_l1 对应节点名称含 "上游" 或 "配套-材料" 的行业
中游：sw_l1 对应节点名称含 "中游" 或 "配套-设备" 的行业
下游：sw_l1 对应节点名称含 "下游" 的行业
综合：sw_l1 对应多个产业链且跨越上中下游的行业（如 "电子"）
```

位置映射配置（`config/chain_position_map.json`）：

```json
{
  "schema_version": "chain_position_map_v1",
  "mappings": [
    {"sw_l1": "有色金属", "chain_position": "上游", "reason": "锂矿、铜、稀土等原材料"},
    {"sw_l1": "基础化工", "chain_position": "上游", "reason": "电解液、正极材料前驱体"},
    {"sw_l1": "钢铁",     "chain_position": "上游", "reason": "钢材、特钢原材料"},
    {"sw_l1": "煤炭",     "chain_position": "上游", "reason": "能源原材料"},
    {"sw_l1": "石油石化", "chain_position": "上游", "reason": "能源原材料"},
    {"sw_l1": "电子",     "chain_position": "综合", "reason": "横跨设计(上游)、制造(中游)、封测(中游)"},
    {"sw_l1": "电力设备", "chain_position": "中游", "reason": "电池、组件制造"},
    {"sw_l1": "机械设备", "chain_position": "中游", "reason": "设备制造"},
    {"sw_l1": "汽车",     "chain_position": "下游", "reason": "整车制造与销售"},
    {"sw_l1": "食品饮料", "chain_position": "下游", "reason": "终端消费品"},
    {"sw_l1": "家用电器", "chain_position": "下游", "reason": "终端消费品"},
    {"sw_l1": "计算机",   "chain_position": "下游", "reason": "软件与应用层"},
    {"sw_l1": "通信",     "chain_position": "中游", "reason": "通信设备与光模块"},
    {"sw_l1": "国防军工", "chain_position": "综合", "reason": "横跨材料(上游)到总装(下游)"},
    {"sw_l1": "医药生物", "chain_position": "综合", "reason": "横跨原料药(上游)到制剂(下游)"},
    {"sw_l1": "银行",     "chain_position": "配套", "reason": "金融服务，不属于生产链"},
    {"sw_l1": "非银金融", "chain_position": "配套", "reason": "金融服务"},
    {"sw_l1": "房地产",   "chain_position": "下游", "reason": "终端需求"}
  ]
}
```

---

## 3. chain_event_cross — 产业链事件交叉表

### 3.1 定位

记录影响产业链的重大事件，标注事件类型、影响方向和影响强度。与现有 `chain_dynamics`（原事件表）的区别：新表增加了**影响方向**和**影响强度**的量化字段，且以产业链而非个股为影响对象。

### 3.2 Schema

```sql
CREATE TABLE IF NOT EXISTS chain_event_cross (
    event_id           VARCHAR    PRIMARY KEY,  -- 事件唯一标识
    event_date         VARCHAR    NOT NULL,     -- 事件日期
    event_type         VARCHAR    NOT NULL,     -- 事件大类：policy / tech / overseas / supply_demand / earnings / capital
    event_subtype      VARCHAR,                 -- 事件子类，如 "补贴政策" "技术突破" "产能扩张" "反倾销"
    title              VARCHAR    NOT NULL,     -- 事件标题
    summary            VARCHAR,                 -- 事件摘要
    affected_chains    VARCHAR    NOT NULL,     -- 影响的产业链 ID 列表（JSON 数组）
    impact_direction   VARCHAR    NOT NULL,     -- 影响方向：positive / negative / neutral / mixed
    impact_strength    DOUBLE    NOT NULL,      -- 影响强度 1-5（1=微弱, 5=重大）
    impact_duration    VARCHAR,                 -- 影响持续性：short_term / medium_term / long_term
    affected_nodes     VARCHAR,                 -- 主要影响环节（JSON 数组），如 ["上游-芯片","中游-服务器"]
    affected_sw_l1     VARCHAR,                 -- 主要影响行业（JSON 数组），如 ["电子","通信"]
    source_agent       VARCHAR,                 -- 来源 Agent 或 API
    source_url         VARCHAR,                 -- 来源链接
    raw_json           VARCHAR,                 -- 原始 JSON（截断至 3000 字符）
    as_of_date         VARCHAR    NOT NULL,
    collected_at       VARCHAR    NOT NULL
);
```

### 3.3 事件类型分类

| event_type | event_subtype 示例 | 说明 |
|------------|-------------------|------|
| policy | 补贴政策 / 产能管控 / 反倾销 / 行业准入 / 环保政策 / 税收调整 | 国内产业政策变化 |
| tech | 技术突破 / 新品发布 / 工艺升级 / 专利诉讼 | 技术驱动的产业链变化 |
| overseas | 海外需求 / 出口管制 / 汇率冲击 / 海外产能 / 贸易摩擦 | 海外市场或地缘政治事件 |
| supply_demand | 产能扩张 / 产能收缩 / 库存累积 / 库存去化 / 供需缺口 | 供需基本面变化 |
| earnings | 业绩超预期 / 业绩不及预期 / 盈利拐点 / 毛利率变化 | 产业链相关公司业绩信号 |
| capital | 并购重组 / 定增融资 / 大股东增减持 / IPO / 产能投资 | 资本运作信号 |

### 3.4 影响强度评分标准

| impact_strength | 含义 | 判定标准 |
|-----------------|------|----------|
| 1 | 微弱 | 个别公司层面事件，不影响行业格局 |
| 2 | 较弱 | 细分环节事件，影响局部供需 |
| 3 | 中等 | 行业级事件，影响一个完整产业链环节 |
| 4 | 较强 | 跨产业链事件，影响多个环节或多个行业 |
| 5 | 重大 | 政策拐点、技术代际变革、全球供需重构 |

### 3.5 事件与产业链的交叉逻辑

事件入库后，自动执行以下交叉分析：

```text
1. 解析 affected_chains 字段，确定受影响的产业链 ID 列表。
2. 对每个受影响产业链，查找 chain_dynamics 中对应环节的指标。
3. 更新 industry_position 中受影响行业的 dynamic_event_count。
4. 如果 impact_strength >= 3 且 impact_direction = "positive":
   → 提升受影响行业 prosperity_score 的政策/供需分项。
5. 如果 impact_strength >= 3 且 impact_direction = "negative":
   → 降低受影响行业 prosperity_score 的政策/供需分项。
```

---

## 4. 填充优先级

### 4.1 产业链填充优先级

按 `config/chain_catalog.json` 中的 `priority` 字段排序：

| 优先级 | 产业链 | 理由 |
|--------|--------|------|
| 1 (最高) | AI算力链 (ai_compute) | 当前市场主线，ETF 覆盖率高，数据源丰富 |
| 1 | 半导体链 (semiconductor) | 国产替代主线，政策驱动明确 |
| 1 | 新能源车链 (nev) | 数据透明度高（月度销量/装机量），产业链完整 |
| 2 | 光伏链 (solar) | 产能过剩周期观察重点 |
| 2 | 军工链 (military) | 政策驱动，数据频率偏低 |
| 2 | 白酒消费链 (consumer_spirits) | 下游消费品代表，季节性明显 |
| 3+ | 后续扩展 | 基于 ifind_industry_chain_profile 中 sw_l1 覆盖度扩展 |

### 4.2 指标填充优先级

每个产业链的指标按以下顺序填充：

| 优先级 | 指标类别 | 理由 | 数据来源 |
|--------|----------|------|----------|
| 1 | 产品均价 / 现货价 | 最直接的供需信号，日频/周频可得 | iFinD Agent / 行业数据库 |
| 2 | 开工率 / 产能利用率 | 反映供给端实际状态 | iFinD Agent / 行业协会 |
| 3 | 库存天数 / 库存周转 | 领先指标，反映供需错配程度 | iFinD Agent / 行业协会 |
| 4 | 出货量 / 装机量 / 销量 | 需求端核心指标 | 行业月度公告 / iFinD |
| 5 | 毛利率 / 单位盈利 | 滞后但高可信度的景气指标 | iFinD 财务数据 |
| 6 | 技术指标（效率/良率） | 技术驱动型产业链的核心竞争力指标 | iFinD Agent / 行业报告 |
| 7 | 政策/补贴标准 | 政策驱动型产业链的关键变量 | 政策公告 / iFinD Agent |

### 4.3 环节填充优先级

每个产业链内部，按信息价值排序：

| 优先级 | 环节 | 理由 |
|--------|------|------|
| 1 | 供给瓶颈环节 | 该环节的供需状态对整条链的定价权最大 |
| 2 | 中游制造环节 | 最直接反映产业链的开工和需求状态 |
| 3 | 上游原材料环节 | 成本端信号，影响中下游盈利 |
| 4 | 下游终端环节 | 需求端信号，但受消费/投资周期影响大 |
| 5 | 配套服务环节 | 辅助信息，非核心驱动 |

---

## 5. 与现有 ifind_industry_chain_profile 的对接关系

### 5.1 数据栈关系

```text
fundamental_evidence.duckdb
  ├── ifind_industry_chain_profile   ← 个股身份层（已有）
  │     stock_code, sw_l1, sw_l2, sw_l3, main_business, ...
  │
  └── ifind_business_segment_facts   ← 个股营收构成（已有）
        stock_code, metric_name, metric_value, report_period, ...

industry_chain_evidence.duckdb
  ├── chain_dynamics                  ← 产业链指标时序（本文档，待实现）
  │     chain_id, chain_node, indicator_name, latest_value, trend, ...
  │
  ├── industry_position               ← 行业景气度（本文档，待实现升级）
  │     sw_l1, chain_position, prosperity_score, rating, ...
  │
  └── chain_event_cross               ← 事件 × 产业链交叉（本文档，待实现）
        event_id, event_type, affected_chains, impact_direction, ...
```

### 5.2 从 ifind_industry_chain_profile 到 chain_dynamics 的映射

`ifind_industry_chain_profile` 中的以下字段直接用于确定 `chain_dynamics` 的填充范围：

| ifind_industry_chain_profile 字段 | chain_dynamics 用途 |
|----------------------------------|---------------------|
| sw_l1 | 确定行业归属，关联 `config/chain_position_map.json` 得到 chain_id |
| sw_l2, sw_l3 | 细分环节归属，辅助确定 chain_node |
| main_business | 用于语义匹配产业链环节（当 sw_l1 映射到多条链时） |
| main_product_types | 用于确定该标的最相关的产业链指标 |
| comparable_companies | 用于扩展产业链覆盖（同行业可比公司共享产业链指标） |

### 5.3 从 ifind_business_segment_facts 到 industry_position 的映射

`ifind_business_segment_facts` 中的营收构成数据用于确定个股在产业链中的位置：

```text
IF 某公司 70%+ 营收来自 "上游原材料" 类产品:
    → 该公司归入上游环节
ELIF 某公司 50%+ 营收来自 "中游制造/加工" 类产品:
    → 该公司归入中游环节
ELIF 某公司 50%+ 营收来自 "终端产品/服务" 类产品:
    → 该公司归入下游环节
```

这一归属结果汇总到行业级别，形成 `industry_position.chain_position`。

### 5.4 从 chain_dynamics 到 macro_chain_prior 的反馈

`chain_dynamics` 的指标数据补充 `macro_chain_prior` 中行业先验评分的证据层：

```text
macro_chain_prior.industry_priors[].evidence 中可新增:
  - "上游锂价近1月上涨15%，分位85%"（来自 chain_dynamics）
  - "中游开工率维持高位，趋势flat"（来自 chain_dynamics）
  - "行业评级上调，景气度7.2/10"（来自 industry_position）
```

当前 `build_macro_chain_prior.py` 中的 `chain_event_counts` 来自旧版 `chain_dynamics` 表。升级后应改为：

```python
# 旧版：只统计事件数量
chain_event_counts = load_chain_event_counts(chain_db, date_str)

# 升级版：同时加载动态指标和事件强度
chain_indicators = load_chain_dynamics(chain_db, date_str)
chain_events = load_chain_event_cross(chain_db, date_str)
industry_ratings = load_industry_position(chain_db, date_str)
```

---

## 6. 与现有表的兼容与迁移

### 6.1 现有 chain_dynamics 表处理

现有 `chain_dynamics` 表（事件驱动，含 dynamic_id / title / summary）需要迁移：

- **方案 A（推荐）**：将现有数据迁移至 `chain_event_cross`，然后重命名 `chain_dynamics` 为指标时序表。迁移脚本将现有 `event_type` / `title` / `summary` 映射到 `chain_event_cross` 的字段。
- **方案 B**：保留现有 `chain_dynamics` 表不动，新建 `chain_indicator_timeseries` 表作为指标时序存储。

推荐方案 A，原因：现有 `chain_dynamics` 数据量极小（多数日期为 0 条导入），迁移成本低，且新表命名更准确。

### 6.2 现有 industry_position 表处理

现有 `industry_position` 表是个股级（stock_code × industry），与新表（sw_l1 × as_of_date）主键不同，可共存。建议：

- 重命名现有表为 `stock_chain_position`（个股产业链定位）。
- 新建 `industry_position`（行业产业链景气度）。

### 6.3 现有 chain_event_cross 表处理

现有 `chain_event_cross` 表（stock_code × as_of_date，交叉 P116 池与产业链事件）需要迁移：

- 重命名为 `stock_chain_event_cross`。
- 新建 `chain_event_cross` 以产业链为影响对象。

### 6.4 迁移脚本

```text
scripts/migrate_chain_tables_v2.py
```

执行顺序：

```bash
# 1. 备份现有数据库
cp outputs/industry_chain/industry_chain_evidence.duckdb \
   outputs/industry_chain/industry_chain_evidence_v1_backup.duckdb

# 2. 执行迁移
python3 scripts/migrate_chain_tables_v2.py --date 2026-05-23

# 3. 验证
python3 scripts/migrate_chain_tables_v2.py --date 2026-05-23 --verify-only
```

---

## 7. 下游消费方

| 消费方 | 消费的表 | 用途 |
|--------|----------|------|
| `build_macro_chain_prior.py` | chain_dynamics + industry_position + chain_event_cross | 行业先验评分的证据层 |
| `build_strategy_evidence.py` | industry_position | 策略环境标签中的产业链景气度信息 |
| strategy_reminder_brief | chain_event_cross | 提醒层中的产业链事件背景 |
| recommendation pipeline | industry_position | 推荐排序中的行业景气度加分 |
| DeepSeek / KIMI Agent | 全部三张表 | 研究分析的上下文注入 |

---

## 8. 合规边界

- 三张表均为**只读证据层**，不直接生成交易信号。
- 景气度评分和评级变化是**场景描述**，不是投资建议。
- 影响强度和影响方向是**定性判断**，需标注 `confidence` 和 `source_vendor`。
- 数据缺失时保持 `NULL`，不填充默认值后伪装为事实。
- 不输出"建议买入/卖出某产业链"类语言。

---

## 附录：与现有脚本的关系

| 现有脚本 | 关系 |
|----------|------|
| `scripts/ifind_industry_chain.py` | 主改造对象。现有 CREATE_STATEMENTS 替换为新 Schema |
| `scripts/import_ifind_industry_chain_excel.py` | 不变。继续将 iFinD Excel 导入 fundamental_evidence.duckdb |
| `scripts/build_macro_chain_prior.py` | 改造消费逻辑，从新表读取指标和评级 |
| `scripts/ifind_event_radar.py` | 不变。公司级事件继续写入 event_digest.duckdb |
| `scripts/build_industry_etf_config.py` | 不变。行业 ETF 配置逻辑不受影响 |
