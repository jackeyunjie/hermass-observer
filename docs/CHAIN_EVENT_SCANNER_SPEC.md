# 产业链事件扫描器设计

版本：v1.0
日期：2026-05-23
状态：设计稿
关联规范：`docs/industry_chain_dynamics_spec.md`（chain_event_cross 表 Schema）
关联模型：`docs/chain_prosperity_scoring_model.md`（事件分项 S_event，权重 0.20）
关联脚本：`scripts/ifind_event_radar.py`（公司级事件，本扫描器的产业链级扩展）

---

## 定位

产业链景气量化模型的事件分项（S_event，权重 0.20）需要实际的数据来源。本规范设计一个事件扫描器，从 iFinD Agent 输出、政策公告、行业新闻中自动提取对产业链有冲击的事件，写入 `chain_event_cross` 表。

**与现有 ifind_event_radar.py 的关系**：

```text
ifind_event_radar.py  → 公司级事件（stock_code × event_type）→ event_digest.duckdb
chain_event_scanner   → 产业链级事件（affected_chains × impact）→ industry_chain_evidence.duckdb
```

两者互补：事件雷达关注个股公告/业绩，事件扫描器关注产业链级别的宏观冲击。

---

## 1. 事件类型定义

### 1.1 六大事件类型

| event_type | event_subtype | 典型来源 | 影响范围 |
|------------|---------------|----------|----------|
| policy | 补贴政策 | 国务院/部委文件、行业协会公告 | 整条产业链 |
| policy | 产能管控 | 发改委/工信部 | 上游供给端 |
| policy | 反倾销/贸易壁垒 | 商务部/海关总署 | 涉及进出口的产业链 |
| policy | 行业准入 | 监管部门 | 新进入者/存量企业 |
| policy | 环保政策 | 生态环境部 | 高耗能产业链 |
| policy | 税收调整 | 财政部/税务总局 | 全产业链 |
| tech | 技术突破 | 行业会议/论文/企业发布 | 技术驱动型产业链 |
| tech | 新品发布 | 企业发布会/展会 | 产品周期驱动的产业链 |
| tech | 工艺升级 | 行业报告/产能公告 | 制造环节 |
| tech | 专利诉讼 | 法院公告/企业公告 | 特定环节 |
| overseas | 海外需求变化 | 海外经济数据/企业财报 | 出口导向型产业链 |
| overseas | 出口管制 | 外国政府公告 | 被制裁环节 |
| overseas | 汇率冲击 | 央行/外汇市场 | 进出口企业 |
| overseas | 海外产能变化 | 海外企业公告 | 全球供需格局 |
| overseas | 贸易摩擦 | 政府间谈判/关税公告 | 涉及贸易的产业链 |
| supply_demand | 产能扩张 | 企业公告/行业统计 | 供给端 |
| supply_demand | 产能收缩 | 企业停产/破产 | 供给端 |
| supply_demand | 库存累积 | 行业统计数据 | 中游 |
| supply_demand | 库存去化 | 行业统计数据 | 中游 |
| supply_demand | 供需缺口 | 行业分析/价格信号 | 全产业链 |
| earnings | 业绩超预期 | 企业季报/年报 | 龙头企业及同行 |
| earnings | 业绩不及预期 | 企业季报/年报 | 龙头企业及同行 |
| earnings | 盈利拐点 | 连续季度数据 | 行业整体 |
| capital | 并购重组 | 企业公告/证监会 | 涉及企业及行业格局 |
| capital | 大股东增减持 | 公司公告 | 个股信号 |
| capital | 产能投资 | 企业公告/地方政府 | 供给端预期 |

### 1.2 产业链映射规则

每个事件必须标注 `affected_chains`（JSON 数组），映射规则：

```python
CHAIN_EVENT_MAPPING = {
    # policy 类
    "新能源汽车补贴": ["nev"],
    "光伏补贴退坡": ["solar"],
    "半导体大基金": ["semiconductor", "ai_compute"],
    "军工采购计划": ["military"],
    "环保限产": ["solar", "semiconductor", "nev"],  # 高耗能环节

    # tech 类
    "AI大模型发布": ["ai_compute", "semiconductor"],
    "固态电池突破": ["nev"],
    "光刻机进展": ["semiconductor"],
    "钙钛矿效率突破": ["solar"],

    # overseas 类
    "芯片出口管制": ["semiconductor", "ai_compute"],
    "锂矿出口限制": ["nev"],
    "光伏反倾销": ["solar"],

    # supply_demand 类
    "锂价暴涨/暴跌": ["nev"],
    "硅料产能过剩": ["solar"],
    "算力需求激增": ["ai_compute", "semiconductor"],
    "白酒渠道库存": ["consumer_spirits"],
}
```

---

## 2. 扫描频率与触发

### 2.1 扫描频率

**日频**：每个交易日收盘后执行一次。

### 2.2 扫描窗口

```text
扫描过去 24 小时内的新事件（从上次扫描时间到当前时间）
```

对于 iFinD Agent 输出，扫描当日导出的 JSON 文件。
对于政策公告，扫描当日的政府公告 RSS/API。

### 2.3 去重逻辑

```python
def is_duplicate(event: dict, existing: list[dict]) -> bool:
    """检查事件是否已入库。"""
    for existing_event in existing:
        if (existing_event["title"] == event["title"]
            and existing_event["event_date"] == event["event_date"]):
            return True
        # 语义去重：标题相似度 > 80% 且同日
        if (existing_event["event_date"] == event["event_date"]
            and text_similarity(existing_event["title"], event["title"]) > 0.8):
            return True
    return False
```

---

## 3. 影响判定

### 3.1 方向判定（impact_direction）

```python
def classify_direction(event_type: str, event_subtype: str, title: str, summary: str) -> str:
    """判定事件对产业链的影响方向。"""
    text = f"{title} {summary}".lower()

    # 正面关键词
    positive_signals = ["补贴", "扶持", "减税", "大基金", "需求增长", "产能不足",
                        "涨价", "突破", "超预期", "增持", "订单增长", "供不应求"]
    # 负面关键词
    negative_signals = ["制裁", "限产", "过剩", "暴跌", "退坡", "加税", "减持",
                        "不及预期", "反倾销", "管制", "破产", "停产", "库存累积"]

    pos_count = sum(1 for kw in positive_signals if kw in text)
    neg_count = sum(1 for kw in negative_signals if kw in text)

    if pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    elif pos_count == 0 and neg_count == 0:
        return "neutral"
    else:
        return "mixed"
```

### 3.2 强度判定（impact_strength）

```python
def classify_strength(event_type: str, title: str, summary: str) -> int:
    """判定事件影响强度 1-5。"""
    text = f"{title} {summary}"

    # 5 分：国家级政策拐点 / 全球性事件
    if any(kw in text for kw in ["国务院", "全国人大", "全面", "重大", "历史性"]):
        return 5

    # 4 分：部委级政策 / 行业龙头重大事件
    if any(kw in text for kw in ["部委", "工信部", "发改委", "龙头", "全球"]):
        return 4

    # 3 分：行业级事件
    if any(kw in text for kw in ["行业", "协会", "产业链", "产能"]):
        return 3

    # 2 分：细分环节事件
    if any(kw in text for kw in ["细分", "局部", "个别", "子公司"]):
        return 2

    # 1 分：其他
    return 2  # 默认 2 分而非 1 分，避免低估
```

### 3.3 持续性判定（impact_duration）

```python
def classify_duration(event_type: str, impact_strength: int) -> str:
    """判定影响持续性。"""
    if event_type == "policy":
        return "long_term" if impact_strength >= 4 else "medium_term"
    elif event_type == "tech":
        return "medium_term"
    elif event_type == "supply_demand":
        return "medium_term" if impact_strength >= 3 else "short_term"
    elif event_type == "earnings":
        return "short_term"
    elif event_type == "overseas":
        return "medium_term" if impact_strength >= 4 else "short_term"
    elif event_type == "capital":
        return "short_term"
    return "short_term"
```

### 3.4 产业链环节映射（affected_nodes）

```python
def map_affected_nodes(event_type: str, event_subtype: str, chain_id: str) -> list[str]:
    """确定事件主要影响的产业链环节。"""
    # 基于事件类型和产业链的节点列表推导
    chain_nodes = CHAIN_CATALOG[chain_id]["nodes"]

    if event_subtype in ("补贴政策", "税收调整"):
        return chain_nodes  # 全产业链
    elif event_subtype in ("产能管控", "产能扩张", "产能收缩"):
        return [n for n in chain_nodes if "上游" in n or "中游" in n]
    elif event_subtype in ("需求变化", "海外需求"):
        return [n for n in chain_nodes if "下游" in n]
    elif event_subtype in ("技术突破", "工艺升级"):
        return [n for n in chain_nodes if "中游" in n]
    else:
        return chain_nodes[:2]  # 默认影响上游和中游
```

---

## 4. 数据来源与扫描接口

### 4.1 数据来源优先级

| 优先级 | 来源 | 接口 | 可靠性 |
|--------|------|------|--------|
| 1 | iFinD Agent 导出 JSON | 本地文件 | 高 |
| 2 | 政策公告 RSS/API | HTTP | 高 |
| 3 | 行业协会数据 | iFinD API / HTTP | 中 |
| 4 | 新闻聚合 | iFinD Agent / 第三方 | 中 |
| 5 | 社交媒体/论坛 | 低可靠性，仅做辅助参考 | 低 |

### 4.2 iFinD Agent 扫描接口

```python
def scan_ifind_agents(date_str: str) -> list[dict]:
    """从 iFinD Agent 导出 JSON 中扫描产业链事件。"""
    events = []

    # 1. 算力行业头部公司动态跟踪助手
    agent_path = ROOT / "data" / "Kimi_Agent_股票服务升级" / "research"
    for file in agent_path.glob("*.json"):
        data = json.loads(file.read_text(encoding="utf-8"))
        for item in data.get("events", []):
            event = normalize_ifind_event(item, source_agent="算力行业头部公司动态跟踪助手")
            if event:
                events.append(event)

    # 2. 每日热点快讯简报
    hot_news_path = ROOT / "data" / "hot_news"
    for file in hot_news_path.glob(f"*{ymd(date_str)}*.json"):
        data = json.loads(file.read_text(encoding="utf-8"))
        for item in data.get("news", []):
            event = normalize_news_event(item)
            if event:
                events.append(event)

    return events
```

### 4.3 政策公告扫描接口

```python
def scan_policy_announcements(date_str: str) -> list[dict]:
    """扫描政策公告。"""
    events = []

    # 从 iFinD 宏观数据中提取政策信号
    macro_path = ROOT / "outputs" / "macro" / f"macro_snapshot_{ymd(date_str)}.json"
    if macro_path.exists():
        macro = json.loads(macro_path.read_text(encoding="utf-8"))
        for policy_item in macro.get("policy_signals", []):
            event = normalize_policy_event(policy_item)
            if event:
                events.append(event)

    return events
```

### 4.4 行业数据扫描接口

```python
def scan_industry_data(date_str: str) -> list[dict]:
    """从行业数据中检测供需突变信号。"""
    events = []

    # 检测 chain_dynamics 中的异常值
    chain_db = ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"
    if chain_db.exists():
        con = duckdb.connect(str(chain_db), read_only=True)
        # 检测趋势突变（从 up 变为 down 或反之）
        anomalies = con.execute("""
            SELECT chain_id, chain_node, indicator_name, latest_value, prev_value, trend
            FROM chain_dynamics
            WHERE as_of_date = ?
              AND (
                (trend = 'turning_up' OR trend = 'turning_down')
                OR (latest_value / NULLIF(prev_value, 0) > 1.15)
                OR (latest_value / NULLIF(prev_value, 0) < 0.85)
              )
        """, [date_str]).fetchall()

        for chain_id, node, indicator, value, prev, trend in anomalies:
            event = build_anomaly_event(chain_id, node, indicator, value, prev, trend)
            events.append(event)
        con.close()

    return events
```

---

## 5. 输出格式

### 5.1 chain_event_cross 标准写入

```python
def write_to_chain_event_cross(con: duckdb.DuckDBPyConnection, events: list[dict]) -> int:
    """将扫描到的事件写入 chain_event_cross 表。"""
    count = 0
    for event in events:
        event_id = f"scan_{event['event_type']}_{event['event_date']}_{count}"
        con.execute("""
            INSERT OR IGNORE INTO chain_event_cross
            (event_id, event_date, event_type, event_subtype, title, summary,
             affected_chains, impact_direction, impact_strength, impact_duration,
             affected_nodes, affected_sw_l1,
             source_agent, source_url, raw_json, as_of_date, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_id,
            event["event_date"],
            event["event_type"],
            event.get("event_subtype"),
            event["title"],
            event.get("summary"),
            json.dumps(event["affected_chains"], ensure_ascii=False),
            event["impact_direction"],
            event["impact_strength"],
            event.get("impact_duration"),
            json.dumps(event.get("affected_nodes", []), ensure_ascii=False),
            json.dumps(event.get("affected_sw_l1", []), ensure_ascii=False),
            event.get("source_agent", "chain_event_scanner"),
            event.get("source_url"),
            json.dumps(event, ensure_ascii=False)[:3000],
            event["event_date"],
            datetime.now(timezone.utc).isoformat(),
        ))
        count += 1
    return count
```

### 5.2 单条事件标准结构

```json
{
  "event_date": "2026-05-23",
  "event_type": "policy",
  "event_subtype": "补贴政策",
  "title": "国务院常务会议通过新能源汽车下乡补贴方案",
  "summary": "补贴标准较去年提高 10%，覆盖车型范围扩大...",
  "affected_chains": ["nev"],
  "impact_direction": "positive",
  "impact_strength": 4,
  "impact_duration": "long_term",
  "affected_nodes": ["上游-锂矿", "上游-正极材料", "中游-电芯", "下游-整车"],
  "affected_sw_l1": ["有色金属", "基础化工", "电力设备", "汽车"],
  "source_agent": "政策公告扫描",
  "source_url": null,
  "raw_json": "..."
}
```

---

## 6. 与景气度评分模型的对接

### 6.1 数据流

```text
chain_event_scanner
  ↓ 扫描并判定
chain_event_cross 表（写入）
  ↓ 被评分模型读取
chain_prosperity_scoring_model → S_event 分项
  ↓ 汇入总分
industry_position.prosperity_score
```

### 6.2 S_event 分项的读取逻辑

```python
def compute_S_event(chain_id: str, date_str: str, chain_db: Path) -> float:
    """从 chain_event_cross 表读取事件并计算 S_event 分项。"""
    con = duckdb.connect(str(chain_db), read_only=True)

    # 读取近 30 天影响该产业链的事件
    events = con.execute("""
        SELECT event_date, event_type, impact_direction, impact_strength, impact_duration
        FROM chain_event_cross
        WHERE as_of_date >= CAST(? AS DATE) - INTERVAL 30 DAY
          AND as_of_date <= CAST(? AS DATE)
          AND affected_chains LIKE ?
        ORDER BY event_date DESC
    """, [date_str, date_str, f'%{chain_id}%']).fetchall()

    con.close()

    if not events:
        return 5.0  # 无事件 = 中性

    total_impact = 0.0
    for event_date, event_type, direction, strength, duration in events:
        days_ago = (parse_date(date_str) - parse_date(event_date)).days
        recency_decay = max(0.2, 1.0 - days_ago / 30)
        direction_factor = {"positive": 1.0, "negative": -1.0, "neutral": 0.0, "mixed": 0.3}.get(direction, 0.0)
        strength_normalized = (strength - 3) / 2  # 范围 [-1, 1]
        type_weight = {"policy": 1.2, "supply_demand": 1.0, "tech": 0.9,
                       "earnings": 0.8, "overseas": 0.7, "capital": 0.6}.get(event_type, 0.8)

        total_impact += direction_factor * strength_normalized * recency_decay * type_weight

    return max(0.0, min(10.0, 5.0 + total_impact * 2.0))
```

### 6.3 更新触发

```text
chain_event_scanner 每次写入新事件后：
  1. 触发 industry_position 重算（受影响行业的 prosperity_score）
  2. 触发 macro_chain_prior 中行业先验的更新
  3. 如果新事件 impact_strength >= 3，在 daily_research_brief 中展示
```

---

## 7. 执行命令

```bash
# 每日扫描
python3 scripts/chain_event_scanner.py --date 2026-05-23

# 带外部 JSON 导入
python3 scripts/chain_event_scanner.py --date 2026-05-23 --import-json /path/to/events.json

# 仅检查不写入
python3 scripts/chain_event_scanner.py --date 2026-05-23 --dry-run
```

### 输出

```text
outputs/industry_chain/chain_event_scan_{date}.json
outputs/industry_chain/chain_event_scan_latest.json
```

---

## 8. 合规边界

- 事件扫描器是**只读证据采集工具**，不生成交易信号。
- 影响方向和强度是**自动分类**，需标注 confidence。
- 关键词匹配为基础方法，可能误判；高影响事件（strength >= 4）需人工确认。
- 不输出"某产业链即将爆发/崩溃"类语言。
- 事件缺失不等于"无风险"，只标注"当日无新扫描事件"。
