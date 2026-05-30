# 产业链数据填充方案

版本：v1.0
日期：2026-05-23
状态：执行蓝图
前置条件：宏观时序库已完善（7 个核心指标历史序列就绪）

---

## 现状

| 维度 | 状态 |
|------|------|
| 宏观时序库 | 已完善，7 个核心指标历史序列就绪 |
| ifind_industry_chain_profile | 5522 只股票的静态画像（sw_l1/l2/l3、主营、可比公司） |
| chain_dynamics | **0 条记录**，动态指标全空 |
| industry_position | **0 条记录**，景气度评分未计算 |
| chain_event_cross | **0 条记录**，事件数据未采集 |
| AKShare | 已安装（v1.18.63），期货接口可用 |

---

## 1. 填充策略

### 1.1 三张表的填充依赖关系

```text
Phase 1: chain_dynamics（指标时序） ← AKShare 期货数据
    ↓
Phase 2: industry_position（景气度评分） ← chain_dynamics + ETF State + 静态画像
    ↓
Phase 3: chain_event_cross（事件交叉） ← RSSHub 政策 + AKShare 异常检测
```

### 1.2 产业链填充优先级

| 优先级 | 产业链 | chain_id | 理由 | 期货代理品种 |
|--------|--------|----------|------|-------------|
| 1 | AI 算力链 | ai_compute | 当前市场主线 | 铜(CU) |
| 1 | 半导体链 | semiconductor | 国产替代主线 | 铜(CU) |
| 1 | 新能源车链 | nev | 数据透明度高 | 碳酸锂(LC) |
| 2 | 光伏链 | solar | 产能过剩观察重点 | 工业硅(SI)、多晶硅(PS) |
| 2 | 军工链 | military | 政策驱动 | 铝(AL) |
| 2 | 白酒消费链 | consumer_spirits | 下游消费品代表 | 无直接期货 |

### 1.3 指标填充优先级

| 优先级 | 指标类别 | 数据源 | 说明 |
|--------|----------|--------|------|
| 1 | 产品均价（期货结算价代理） | AKShare 期货日线 | 最直接的供需信号 |
| 2 | 库存（仓单代理） | AKShare 期货仓单 | 供给端状态 |
| 3 | 开工率 | iFinD 行业数据 / 协会数据 | Phase 2+ |
| 4 | 出货量/装机量/销量 | 协会月度统计 | Phase 2+ |
| 5 | 毛利率/单位盈利 | iFinD 财务数据 | Phase 3+ |

---

## 2. Phase 1：AKShare 期货数据填充（立即）

### 2.1 目标

用 AKShare 拉取碳酸锂、工业硅、多晶硅、铜的期货价格序列，填入 chain_dynamics 表。作为"产品均价"指标的代理。

### 2.2 数据源映射

| 产业链 | 环节 | 期货品种 | 交易所 | AKShare 接口 | 代理指标 |
|--------|------|---------|--------|-------------|---------|
| nev | 上游-锂矿 | 碳酸锂 LC | 广期所 | `futures_zh_daily_sina(symbol="LC0")` | 锂盐产品均价 |
| solar | 上游-硅料 | 工业硅 SI | 广期所 | `futures_zh_daily_sina(symbol="SI0")` | 工业硅产品均价 |
| solar | 上游-硅料 | 多晶硅 PS | 广期所 | `futures_zh_daily_sina(symbol="PS0")` | 多晶硅产品均价 |
| semiconductor | 配套-材料 | 铜 CU | 上期所 | `futures_zh_daily_sina(symbol="CU0")` | 铜价（半导体封装/连接材料成本代理） |
| ai_compute | 配套-材料 | 铜 CU | 上期所 | 同上 | 铜价（算力基础设施成本代理） |

### 2.3 新增脚本

```text
scripts/build_chain_dynamics_from_akshare.py
```

### 2.4 函数接口

```python
def fetch_futures_daily(symbol: str, start_date: str, end_date: str) -> list[dict]:
    """
    从 AKShare 拉取期货日线数据。

    参数：
        symbol: 期货品种代码（如 "LC0" 碳酸锂主力合约）
        start_date: 起始日期
        end_date: 截止日期

    返回：
        [{"date": "2026-05-22", "close": 85000.0, "volume": 12345, ...}, ...]
    """

def compute_chain_dynamics_from_futures(
    futures_data: list[dict],
    chain_id: str,
    chain_node: str,
    indicator_name: str,
    lookback_percentile: int = 252,
) -> list[dict]:
    """
    将期货数据转换为 chain_dynamics 表的记录。

    计算：
        latest_value: 最新收盘价
        prev_value: 前一日收盘价
        trend: 基于近 5 日方向判定（up/down/flat/turning_up/turning_down）
        percentile_1y: 当前价格在近 252 个交易日的百分位
        percentile_3y: 当前价格在近 756 个交易日的百分位（如有）

    返回：
        符合 chain_dynamics 表 Schema 的记录列表
    """

def write_to_chain_dynamics(con: duckdb.DuckDBPyConnection, records: list[dict]) -> int:
    """写入 chain_dynamics 表。"""
```

### 2.5 趋势判定逻辑

```python
def compute_trend(daily_closes: list[float]) -> str:
    """基于近 5 日收盘价判定趋势。"""
    if len(daily_closes) < 5:
        return "flat"

    recent_5 = daily_closes[-5:]
    delta_1 = recent_5[-1] - recent_5[-2]
    delta_2 = recent_5[-2] - recent_5[-3]
    delta_3 = recent_5[-3] - recent_5[-4]

    # 连续上行后首次下行
    if delta_3 > 0 and delta_2 > 0 and delta_1 < 0:
        return "turning_down"
    # 连续下行后首次上行
    if delta_3 < 0 and delta_2 < 0 and delta_1 > 0:
        return "turning_up"
    # 整体上行
    if recent_5[-1] > recent_5[0]:
        return "up"
    # 整体下行
    if recent_5[-1] < recent_5[0]:
        return "down"
    return "flat"
```

### 2.6 百分位计算

```python
def compute_percentile(current: float, history: list[float]) -> float:
    """计算当前值在历史序列中的百分位（0-100）。"""
    if not history:
        return 50.0
    below = sum(1 for v in history if v < current)
    return round(below / len(history) * 100, 1)
```

### 2.7 执行命令

```bash
# Phase 1：拉取期货数据填入 chain_dynamics
python3 scripts/build_chain_dynamics_from_akshare.py \
  --date 2026-05-23 \
  --lookback-days 252

# 指定产业链
python3 scripts/build_chain_dynamics_from_akshare.py \
  --date 2026-05-23 \
  --chains nev,solar

# 仅检查不写入
python3 scripts/build_chain_dynamics_from_akshare.py \
  --date 2026-05-23 --dry-run
```

### 2.8 预期输出

Phase 1 完成后，chain_dynamics 表预期：

| chain_id | chain_node | indicator_name | 数据源 | 预期记录数 |
|----------|-----------|---------------|--------|-----------|
| nev | 上游-锂矿 | 锂盐均价（期货代理） | 碳酸锂 LC | ~252 条 |
| solar | 上游-硅料 | 工业硅均价（期货代理） | 工业硅 SI | ~252 条 |
| solar | 上游-硅料 | 多晶硅均价（期货代理） | 多晶硅 PS | ~100 条（上市较晚） |
| semiconductor | 配套-材料 | 铜价（成本代理） | 铜 CU | ~252 条 |
| ai_compute | 配套-材料 | 铜价（成本代理） | 铜 CU | 同上 |

---

## 3. Phase 2：industry_position 景气度评分（1-2 周后）

### 3.1 目标

基于 Phase 1 的 chain_dynamics 数据 + 行业 ETF State + 静态画像，生成首版 industry_position 景气度评分。

### 3.2 数据输入

| 输入 | 来源 | 用途 |
|------|------|------|
| chain_dynamics 价格指标 | Phase 1 产出 | 价格趋势和分位 → 上游景气 |
| 行业 ETF State | `outputs/market_assets_state/` | ef_count + 20d 收益 → 市场景气 |
| ifind_industry_chain_profile | `fundamental_evidence.duckdb` | sw_l1 → 产业链位置初始值 |
| 行业 ETF 配置 | `config/industry_rotation_assets.json` | sw_l1 → ETF 映射 |

### 3.3 景气度计算（简化版，基于可用数据）

```python
def compute_industry_position_phase2(
    chain_dynamics: list[dict],
    etf_state_rows: list[dict],
    industry_profile: dict,
    chain_config: dict,
) -> list[dict]:
    """
    Phase 2 简化景气度计算。

    由于 Phase 2 只有价格/库存代理数据，景气度计算简化为：
        prosperity_score = 0.40 × price_score + 0.35 × etf_score + 0.25 × breadth_score

    其中：
        price_score: chain_dynamics 价格指标的趋势+分位综合分（0-10）
        etf_score: 行业 ETF 的 ef_count + 20d 收益综合分（0-10）
        breadth_score: 该行业内有 State 数据的股票中，E/F 占比（0-10）
    """
```

### 3.4 产业链位置初始值

从 ifind_industry_chain_profile 推导：

```python
def derive_chain_position(sw_l1: str) -> str:
    """从静态画像推导产业链位置。"""
    position_map = {
        "有色金属": "上游", "基础化工": "上游", "钢铁": "上游",
        "煤炭": "上游", "石油石化": "上游",
        "电子": "综合", "国防军工": "综合", "医药生物": "综合",
        "电力设备": "中游", "机械设备": "中游", "通信": "中游",
        "汽车": "下游", "食品饮料": "下游", "家用电器": "下游",
        "计算机": "下游",
        "银行": "配套", "非银金融": "配套",
        "房地产": "下游",
    }
    return position_map.get(sw_l1, "未知")
```

### 3.5 质量检查

```python
def validate_industry_position(positions: list[dict], etf_state: list[dict]) -> list[str]:
    """景气度评分质量检查。"""
    warnings = []

    # 检查 1：景气度与 ETF State 方向一致性
    for pos in positions:
        etf = find_etf_for_industry(pos["sw_l1"], etf_state)
        if etf:
            etf_score = asset_state_score(etf)
            if pos["prosperity_score"] >= 7 and etf_score <= 4:
                warnings.append(f"{pos['sw_l1']}: 景气高({pos['prosperity_score']})但ETF弱({etf_score})，方向不一致")
            if pos["prosperity_score"] <= 3 and etf_score >= 7:
                warnings.append(f"{pos['sw_l1']}: 景气低({pos['prosperity_score']})但ETF强({etf_score})，方向不一致")

    # 检查 2：每个产业链至少 3 个环节有数据
    for chain in chain_config["chains"]:
        chain_positions = [p for p in positions if p.get("chain_id") == chain["chain_id"]]
        if len(chain_positions) < 3:
            warnings.append(f"{chain['chain_name']}: 环节数据不足 ({len(chain_positions)}/3)")

    return warnings
```

---

## 4. Phase 3：chain_event_cross 事件采集（后续）

### 4.1 目标

接入 RSSHub 政策事件 + AKShare 期货异常波动检测，激活 chain_event_cross 表。

### 4.2 数据源

| 数据源 | 事件类型 | 接入方式 | 状态 |
|--------|---------|---------|------|
| AKShare 期货异常波动 | supply_demand | 价格/库存突变检测 | Phase 1 完成后可立即实现 |
| RSSHub 国务院政策 | policy | `/gov/zhengce/govall` 路由 | 需部署 RSSHub 实例 |
| iFinD Agent 人工导出 | policy/tech/earnings | 人工导出 JSON | 需定义标准化格式 |

### 4.3 期货异常波动检测

```python
def detect_futures_anomaly(
    daily_closes: list[float],
    daily_volumes: list[int],
    warehouse_receipts: list[float] | None = None,
) -> list[dict]:
    """
    检测期货数据中的异常波动，作为产业链事件信号。

    规则：
        1. 价格突变：单日涨跌幅 > 5% 或连续 3 日累计 > 10%
        2. 成交量异常：当日成交量 > 近 20 日均值的 3 倍
        3. 仓单异常：仓单连续 5 日变化 > 20%（如有数据）

    返回：
        [{"date": "...", "type": "supply_demand", "subtype": "价格突变",
          "title": "碳酸锂期货单日涨幅 6.2%", "impact_strength": 3, ...}]
    """
```

### 4.4 RSSHub 政策事件接入

```python
def scan_rsshub_policy(date_str: str) -> list[dict]:
    """
    从 RSSHub 获取国务院政策文件。

    前置条件：
        RSSHub 实例部署在 localhost:1200（或配置地址）

    路由：
        /gov/zhengce/govall/:advance?

    处理：
        1. 解析 RSS 条目标题和摘要
        2. 关键词匹配：半导体/新能源/光伏/芯片/锂/军工/白酒
        3. 映射到 affected_chains
        4. 判定 impact_direction 和 impact_strength
    """
```

---

## 5. 质量检查标准

### 5.1 chain_dynamics 质量检查

| 检查项 | 标准 | 不通过处理 |
|--------|------|-----------|
| 每个产业链至少 1 个环节有数据 | chain_id 维度覆盖率 >= 50% | 标注 "partial_coverage" |
| 数据时效性 | 最新数据 <= 3 个交易日 | 标注 "stale_data" |
| 百分位计算有效性 | 历史数据 >= 60 个点 | 百分位标记为 NULL |
| 趋势判定有效性 | 至少 5 个连续数据点 | trend 标记为 NULL |

### 5.2 industry_position 质量检查

| 检查项 | 标准 | 不通过处理 |
|--------|------|-----------|
| 景气度与 ETF State 方向一致性 | 无严重冲突（景气>=7 且 ETF<=3） | 生成 warning |
| 每个产业链至少 3 个环节有数据 | 环节覆盖率 >= 50% | 降低 confidence |
| 景气度分数分布合理性 | 不应全部集中在 5.0 | 检查是否数据不足导致中性聚集 |

### 5.3 chain_event_cross 质量检查

| 检查项 | 标准 | 不通过处理 |
|--------|------|-----------|
| 事件可回溯性 | 每条事件有 raw_json 字段 | 不入库 |
| 影响强度合理性 | 新建事件不全部为 5 分 | 检查强度校准 |
| 去重 | 同日同标题不重复入库 | INSERT OR IGNORE |

---

## 6. 实施时间表

```text
Week 1:
  [Phase 1] scripts/build_chain_dynamics_from_akshare.py
  - 实现期货数据拉取（碳酸锂/工业硅/多晶硅/铜）
  - 实现趋势判定和百分位计算
  - 写入 chain_dynamics 表
  - 质量检查和数据验证

Week 2:
  [Phase 2] scripts/build_industry_position.py
  - 消费 chain_dynamics + ETF State + 静态画像
  - 实现简化版景气度评分（价格分 + ETF 分 + 覆盖分）
  - 推导产业链位置初始值
  - 写入 industry_position 表
  - 质量检查

Week 3+:
  [Phase 3] scripts/chain_event_scanner.py
  - 实现期货异常波动检测
  - RSSHub 部署和政策路由接入
  - iFinD Agent 人工导出格式定义
  - 写入 chain_event_cross 表

持续:
  - chain_dynamics 每日更新（收盘后流水线）
  - industry_position 每日重算
  - chain_event_cross 实时/日频扫描
```

---

## 7. 与下游模块的衔接

### 7.1 产业链景气度评分模型

Phase 2 产出的 industry_position 直接消费 `chain_prosperity_scoring_model.md` 中的评分公式。Phase 2 使用简化版（只用价格+ETF+覆盖），Phase 3 后升级为完整四维评分。

### 7.2 首席报告

`CHIEF_BRIEF_GENERATOR_SPEC.md` 第二层（产业链景气扫描）需要 industry_position 数据。Phase 2 完成后，首席报告的产业链层从"数据暂缺"升级为"简化版景气度"。

### 7.3 三重共振模型

`TRIPLE_RESONANCE_ENHANCEMENT.md` 的产业链方向信号需要 industry_position.prosperity_score。Phase 2 完成后，产业链维度从"neutral"升级为有实际数据支撑的方向判定。
