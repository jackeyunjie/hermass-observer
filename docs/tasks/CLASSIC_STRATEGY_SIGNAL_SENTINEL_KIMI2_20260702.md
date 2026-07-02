# 经典策略信号哨兵方案

日期：2026-07-02
作者：KIMI2
版本：v1.0

---

## 1. 经典策略哨兵定位

经典策略 Agent 是一个**安静的信号哨兵**。它不是 Hermass 的主策略引擎，不参与 State 概率计算，不和 State 输出混合结论。

### 核心比喻

```text
Hermass State 主系统  = 气象雷达（展示多周期多维度天气全景）
经典策略哨兵         = 地震警报灯（平时不亮，只有满足经典规则时才亮）
```

### 行为准则

| 行为 | 允许 | 不允许 |
|------|------|--------|
| 展示经典策略原始规则触发 | ✅ | - |
| 展示策略规则条文 | ✅ | - |
| 显示触发日期和价格位置 | ✅ | - |
| 解释 State 含义 | - | ❌ |
| 参与 State 概率计算 | - | ❌ |
| 输出同向/领先/冲突/证据不足 | - | ❌ |
| 生成综合交易结论 | - | ❌ |
| 影响"我的观察台"转折概率 | - | ❌ |
| 首页占固定区域 | - | ❌ |
| 写入 State Cube | - | ❌ |

### 一句话总结

**平时静默。只有某个经典策略明确触发时，首页出现一个小标签，点击可看详情。没有信号就不显示。**

---

## 2. 第一批策略建议

### 2.1 评估矩阵

对现有 4 个已实现策略逐一评估其是否适合作为第一批哨兵：

| 策略 | 代码模块 | 是否当前运行 | 信号类型 | 适合哨兵 | 理由 |
|------|----------|-------------|----------|---------|------|
| **VCP** | `backtest/strategy_signals/vcp.py` | 是（每日 signal_ledger） | 收缩结构 + 突破确认 | ✅ 第一批 | 最成熟的经典模式，有完整 entry/exit/confidence |
| **2560（趋势跟随）** | `backtest/strategy_signals/ma2560.py` | 是（每日 signal_ledger） | 金叉/死叉/多头排列 | ✅ 第一批 | 中国交易圈最经典的趋势系统，信号清晰 |
| **布林强盗** | `backtest/strategy_signals/bollinger_bandit.py` | 是（每日 signal_ledger） | 突破上轨 + 动态退出 | ✅ 第一批 | John Hill 经典系统，纪律清晰 |
| **ATR 吊灯** | `backtest/strategy_signals/atr_chandelier.py` | 是（每日 signal_ledger） | State 共振入场 | ⚠️ 暂缓 | 依赖多周期 State 过滤，容易和 State 主系统混淆 |
| **均值回归** | 无代码 | 否 | 超卖反弹 | ❌ 不做 | 无信号模块，需要从零开始 |
| **突破策略** | 无独立代码 | 否（部分含在 BB 中） | 高低点突破 | ❌ 不做 | 信号边界模糊，和 VCP/BB 重叠 |
| **CANSLIM** | 无代码 | 否 | 基本面+技术面多条件 | ❌ 不做 | 需要基本面数据，当前无实时数据 |
| **动量/相对强弱** | 无独立代码 | 否 | RSI/动量排名 | ❌ 不做 | 无信号模块，需从零构建 |

### 2.2 第一批推荐（3 个）

```text
第一批哨兵 = { VCP, 2560趋势跟随, 布林强盗 }
```

**选择理由**：

1. **代码已存在且每日运行**：三个策略都在 `backtest/strategy_signals/` 中有完整实现，`scripts/strategy_signal_ledger.py` 每日构建 `outputs/strategy_signals/strategy_signals.duckdb`，数据已就绪。
2. **信号语义清晰**：每个策略的触发条件都是经典交易文献中公认的规则，不依赖 Hermass State 解释。
3. **与 State 系统隔离清晰**：这些策略只使用自己的技术指标（MA25/MA60、ATR、BB、成交量），不依赖 State score。
4. **外部验证数据已准备**：`strategy_reminder_brief.py` 中已有 Minervini、Darvas、Bollinger 的外部环境匹配验证数据（如 Minervini 72.4%、Darvas 79.3%、Bollinger 73.5%）。
5. **前端 SOP 卡片已存在**：`_sop_card_vcp.html`、`_sop_card_2560.html`、`_sop_card_bollinger.html` 已经写好，可直接复用。

### 2.3 为什么 ATR 吊灯暂缓

ATR 吊灯的入场条件是 MN1/W1/D1 三周期 State 共振过滤，这使它更像 Hermass State 系统的衍生信号，而非独立的经典策略。如果放在哨兵中，容易造成"State 主系统 → ATR 吊灯 → 再引用 State"的循环依赖，混淆边界。

ATR 吊灯可以在 Phase 2 中，作为"State 共振观察"模块加入，但不应放入第一批经典策略哨兵。

---

## 3. 信号触发契约

### 3.1 数据来源

```text
outputs/strategy_signals/strategy_signals.duckdb
  └── 表: signal_records
```

该表由 `scripts/strategy_signal_ledger.py` 每日构建，包含 VCP、2560、布林强盗的完整信号记录。

### 3.2 信号字段契约

哨兵从 `signal_records` 中读取并转换为前端展示字段：

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `stock_code` | string | signal_records.stock_code | 6位代码 |
| `state_date` | date | signal_records.state_date | 信号日期 |
| `strategy_name` | string | 固定枚举 | `vcp` / `ma2560` / `bollinger_bandit` |
| `strategy_display_name` | string | 配置映射 | `VCP 收缩释放` / `2560 趋势推进` / `布林强盗` |
| `signal_name` | string | signal_records.signal_name | 如 `vcp_breakout`、`ma2560_golden_cross` |
| `signal_display_text` | string | SIGNAL_META 映射 | 如 "VCP突破确认"、"2560金叉" |
| `signal_type` | string | signal_records.signal_type | `entry` / `structure` / `exit` / `risk` |
| `confidence` | float | signal_records.confidence | 0.0-1.0 |
| `trigger_price` | float | signal_records.trigger_price | 触发时的收盘价 |
| `invalid_condition` | string | signal_records.invalid_condition | 失效条件文本（如有） |
| `position_rule_text` | string | SOP 卡片中的规则文本 | 如 "止损：入场价 -6%" |
| `evidence_items` | list[dict] | 从信号规则反推 | 触发该信号的各条件及其满足状态 |

### 3.3 完整信号枚举

从现有 `SIGNAL_META` 扩展：

**VCP 信号族**：
| signal_name | signal_type | display_text |
|-------------|-------------|--------------|
| `vcp_breakout` | entry | VCP突破确认 |
| `vcp_breakout_weak_vol` | entry | VCP弱放量突破 |
| `vcp_breakout_no_vol` | entry | VCP无放量突破 |
| `vcp_contraction` | structure | VCP收缩结构 |
| `vcp_early_contraction` | structure | VCP早期收缩结构 |

**2560 信号族**：
| signal_name | signal_type | display_text |
|-------------|-------------|--------------|
| `ma2560_golden_cross` | entry | 2560金叉 |
| `ma2560_golden_cross_weak_adx` | entry | 2560金叉（弱趋势） |
| `ma2560_golden_cross_flat_slope` | entry | 2560金叉（斜率走平） |
| `ma2560_strong_hold` | structure | 2560强多头结构 |
| `ma2560_strong_accel` | structure | 2560趋势加速 |
| `ma2560_aligned` | structure | 2560多头排列 |
| `ma2560_aligned_weak` | structure | 2560弱多头排列 |
| `ma2560_death_cross_exit` | exit | 2560死叉风险 |
| `ma2560_bearish` | risk | 2560空头排列 |

**布林强盗信号族**：
| signal_name | signal_type | display_text |
|-------------|-------------|--------------|
| `bb_bandit_long_entry` | entry | 布林强盗多头触发 |
| `bb_bandit_dynamic_ma_exit` | exit | 布林强盗MA退出 |
| `bb_bandit_bandwidth_exit` | exit | 布林强盗带宽收缩退出 |
| `bb_bandit_adx_decline_exit` | exit | 布林强盗ADX衰竭退出 |

### 3.4 信号筛选规则（首页展示用）

并非所有信号都适合上首页标签。筛选规则：

1. **只展示 entry 类信号**：`signal_type = 'entry'` — 因为哨兵的目的是提醒"有哪些经典策略触发了入场规则"。
2. **不展示 structure 类信号**：structure 是"正在搭结构"，不是触发，属于噪音。
3. **不展示 exit/risk 类信号**：exit 和 risk 是风险提醒，应在详情页展示但不作为首页标签。
4. **confidence >= 0.50**：过滤低置信度信号，避免首页标签泛滥。

### 3.5 信号互斥规则

同一只股票、同一天、同一策略，最多展示一个标签：

- VCP：优先 `vcp_breakout`，其次 `vcp_breakout_weak_vol`
- 2560：优先 `ma2560_golden_cross`，其次 `ma2560_golden_cross_weak_adx`
- 布林强盗：只有 `bb_bandit_long_entry`

---

## 4. 首页展示规则

### 4.1 展示位置

放在页面右上角（或状态栏下方），不与 Hermass State 面板争抢注意力。

### 4.2 展示内容

```text
┌─────────────────────────────────────────────┐
│  经典策略哨兵                                  │
│  ┌──────────┐ ┌──────────────┐               │
│  │ VCP 信号  │ │ 2560 信号     │  ← 小标签     │
│  │ 3 只标的  │ │ 12 只标的     │               │
│  └──────────┘ └──────────────┘               │
│            无布林强盗信号                      │
└─────────────────────────────────────────────┘
```

规则：
- **每个策略一个标签**（不是每只股票一个标签）
- 标签显示：策略名称 + 触发数量
- 有信号时标签为激活态（彩色/有边框）；无信号时不显示或灰显
- 标签可点击，进入该策略的当日信号列表页

### 4.3 不做的事情

- 不显示买卖动作
- 不显示仓位建议
- 不显示综合评分
- 不与 State 系统混合展示
- 不在首页占固定大区域

---

## 5. 详情页展示规则

### 5.1 页面结构

```text
┌──────────────────────────────────────────────────┐
│  ← 返回首页          经典策略哨兵 > VCP 收缩释放      │
├──────────────────────────────────────────────────┤
│                                                    │
│  免责声明：以下为经典策略规则触发说明，               │
│  仅作研究观察，不构成交易建议。                       │
│                                                    │
│  ┌──────────────────────────────────────────────┐ │
│  │  环境匹配度                                   │ │
│  │  该环境与 Mark Minervini 72.4% 的交易选择一致 │ │
│  └──────────────────────────────────────────────┘ │
│                                                    │
│  ┌──────────────────────────────────────────────┐ │
│  │  VCP 信号  |  3 只标的  |  2026-07-02         │ │
│  ├──────────────────────────────────────────────┤ │
│  │  标的        信号类型    置信度   触发价格     │ │
│  │  000001     VCP突破确认   0.85    32.50       │ │
│  │  600519     VCP弱放量突破  0.65   1680.00     │ │
│  │  300750     VCP突破确认   0.80    218.00      │ │
│  └──────────────────────────────────────────────┘ │
│                                                    │
│  ┌─ 点击某只标的可展开 ─────────────────────────┐  │
│  │  000001  VCP突破确认  详情                    │  │
│  │  ┌─ 入场条件 ────────────────────────────┐   │  │
│  │  │ ✓ 波幅收缩：ATR 近期收窄              │   │  │
│  │  │ ✓ 量能枯竭：收缩区间成交量递减        │   │  │
│  │  │ ✓ 突破确认：收盘 > 10日最高           │   │  │
│  │  │ ✓ 量能确认：成交量 ≥ 1.5×20日均量    │   │  │
│  │  │ ✗ 基底站上 MA50（未满足）            │   │  │
│  │  └───────────────────────────────────────┘   │  │
│  │  ┌─ 止损规则 ────────────────────────────┐   │  │
│  │  │ 硬止损：32.50 × 0.94 = 30.55          │   │  │
│  │  │ 技术止损：最近收缩低点 × 0.99 = 29.80 │   │  │
│  │  │ ATR止损：32.50 - 2×ATR = 29.40       │   │  │
│  │  └───────────────────────────────────────┘   │  │
│  │  ┌─ 退出规则 ────────────────────────────┐   │  │
│  │  │ 假突破：3日内收盘 < 突破点 → 离场     │   │  │
│  │  │ 时间退出：20日后未达目标 → 离场       │   │  │
│  │  │ 移动止盈：盈利后跟踪止损              │   │  │
│  │  └───────────────────────────────────────┘   │  │
│  │  ┌─ 外部验证 ────────────────────────────┐   │  │
│  │  │ Mark Minervini 72.4% 选择一致          │   │  │
│  │  └───────────────────────────────────────┘   │  │
│  └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

### 5.2 详情页三原则

1. **展示原始规则条文**：每个策略的入场条件、止损规则、退出规则直接引用 SOP 卡片内容。
2. **逐条标注满足/不满足**：每条规则前面打勾/打叉，直观展示哪些条件触发、哪些未触发。
3. **附外部验证数据**：如果有历史环境匹配数据（如 Minervini 72.4%），在底部展示。

### 5.3 页面路由设计

```text
/sentinel                          ← 哨兵总览（按日期显示三个策略的触发统计）
/sentinel/vcp?date=2026-07-02      ← VCP 当日信号列表
/sentinel/2560?date=2026-07-02     ← 2560 当日信号列表
/sentinel/bollinger?date=2026-07-02 ← 布林强盗当日信号列表
/sentinel/detail?strategy=vcp&stock=000001&date=2026-07-02 ← 单标的信号详情
```

数据接口：

```text
/api/sentinel/overview?date=2026-07-02          ← 当日三个策略的触发统计
/api/sentinel/signals?strategy=vcp&date=2026-07-02  ← 策略信号列表
/api/sentinel/detail?strategy=vcp&stock=000001&date=2026-07-02 ← 单标的详情
```

### 5.4 数据结构（API 返回示例）

```json
{
  "date": "2026-07-02",
  "strategies": [
    {
      "strategy_name": "vcp",
      "display_name": "VCP 收缩释放",
      "signal_count": 3,
      "signals": [
        {
          "stock_code": "000001",
          "signal_name": "vcp_breakout",
          "signal_type": "entry",
          "display_text": "VCP突破确认",
          "confidence": 0.85,
          "trigger_price": 32.50,
          "evidence_items": [
            {"condition": "波幅收缩：ATR 近期持续收窄", "met": true},
            {"condition": "量能枯竭：收缩区间成交量递减", "met": true},
            {"condition": "突破确认：收盘价 > 10日最高价", "met": true},
            {"condition": "量能确认：成交量 ≥ 1.5×20日均量", "met": true},
            {"condition": "趋势强度过滤：ADX14 > 20", "met": true},
            {"condition": "基底站上 MA50", "met": false}
          ],
          "stop_rules": [
            {"rule": "硬止损", "detail": "入场价 -6%"},
            {"rule": "技术止损", "detail": "最近收缩低点 × 0.99"},
            {"rule": "ATR止损", "detail": "入场价 - 2×ATR"}
          ],
          "exit_rules": [
            {"rule": "假突破", "detail": "3日内收盘 < 突破点，立即离场"},
            {"rule": "时间退出", "detail": "持仓20日后未达目标，离场"},
            {"rule": "移动止盈", "detail": "盈利后启用跟踪止损"}
          ],
          "external_validation": "Mark Minervini 72.4% 的交易选择一致",
          "position_rule_text": "单笔风险 2%，ATR 调整仓位，100股起"
        }
      ],
      "env_match": {
        "text": "该环境与 Mark Minervini 72.4% 的交易选择一致",
        "source": "MARK_MINERVINI_STATE_MATCH_ANALYSIS.md"
      }
    }
  ]
}
```

---

## 6. 与 Hermass State 主系统的隔离边界

### 6.1 硬隔离规则

```text
┌─────────────────────────────────────────────────────────┐
│                   Hermass State 主系统                    │
│                                                         │
│  State Cube → Multi-Agent Debate → Dynamic Router       │
│       ↓                                                 │
│  Decision Observation Ledger                            │
│       ↓                                                 │
│  观察台转折概率 / 多 Agent 辩论面板                       │
│                                                         │
│  ═══════════════ 硬隔离墙 ═══════════════                │
│                                                         │
│  经典策略哨兵（只读消费，不回流）                          │
│                                                         │
│  strategy_signals.duckdb → 信号标签 → 详情页             │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 6.2 具体隔离措施

| 维度 | 措施 |
|------|------|
| **数据流** | 哨兵只从 `strategy_signals.duckdb` 读取，不写回任何 State 相关的数据库 |
| **展示层** | 哨兵标签独立于 State 面板，有独立的视觉区域和路由 |
| **语义层** | 哨兵信号只展示经典策略规则条文，不翻译成 Hermass State 语义 |
| **计算层** | 哨兵不参与 State 概率计算，不进入 Agent 辩论流程 |
| **路由层** | 哨兵页面 `/sentinel/*` 与 State 相关页面 `/debate`、`/watchlist` 分开 |
| **定时任务** | 哨兵数据生成复用现有 `strategy_signal_ledger.py`，不加新的定时任务 |

### 6.3 必须避免的反模式

```text
❌ 哨兵信号 → "同向" / "领先" / "冲突" → 影响 Router 权重
❌ 哨兵标签 → "建议关注" / "适合交易" → 决策级语义
❌ 哨兵数据 → 写入 State Cube → 污染 State 主系统
❌ 哨兵数量 → "3个策略触发 vs 2个策略触发" → 综合评分
❌ "VCP触发 + State EF≥3 → 高概率标的" → 混合结论
```

---

## 7. 需要复用的现有代码 / 数据

### 7.1 数据层（直接复用）

| 组件 | 路径 | 复用方式 |
|------|------|----------|
| 策略信号账本 | `outputs/strategy_signals/strategy_signals.duckdb` | 唯一数据源，只读查询 |
| 信号枚举 | `strategy_signal_ledger.py` 中的 `SIGNAL_META` | 定义信号展示文本 |
| 信号权重 | `composite.py` 中的 `SIGNAL_WEIGHTS` | 置信度参考 |

### 7.2 计算层（直接复用）

| 组件 | 路径 | 复用方式 |
|------|------|----------|
| 信号生成 | `scripts/strategy_signal_ledger.py` | 每日管线中已运行，不新增调用 |
| 策略信号函数 | `backtest/strategy_signals/vcp.py`、`ma2560.py`、`bollinger_bandit.py` | 不重复实现，由 signal_ledger 统一消费 |
| 外部验证数据 | `strategy_reminder_brief.py` 中的验证常量 | 环境匹配文案 |

### 7.3 展示层（部分复用）

| 组件 | 路径 | 复用方式 |
|------|------|----------|
| VCP SOP 卡片 | `web/templates/_sop_card_vcp.html` | 详情页直接 include |
| 2560 SOP 卡片 | `web/templates/_sop_card_2560.html` | 详情页直接 include |
| 布林 SOP 卡片 | `web/templates/_sop_card_bollinger.html` | 详情页直接 include |
| 站点样式 | `static/style.css` | 复用现有样式变量 |

### 7.4 不需要新建的

- 不需要新建 DuckDB 数据库
- 不需要新建定时任务（cron 中已有 signal_ledger 步骤）
- 不需要新建策略信号算法
- 不需要修改 State Cube 或 Agent 辩论流程

---

## 8. Phase 1 MVP

### 8.1 MVP 范围

```text
MVP = 3 个策略哨兵 + 1 个总览页 + 3 个策略详情页 + 首页标签
```

### 8.2 需要新建的文件

| 文件 | 类型 | 用途 |
|------|------|------|
| `scripts/sentinel_api.py` | Python | 哨兵数据查询 API（从 strategy_signals.duckdb 读取） |
| `web/templates/sentinel_overview.html` | Jinja2 | 哨兵总览页（三个策略的触发统计） |
| `web/templates/sentinel_detail.html` | Jinja2 | 单策略信号列表 + 单标的详情展开 |

### 8.3 需要修改的文件

| 文件 | 修改内容 |
|------|----------|
| `web/main.py` | 新增 4 个路由：`/sentinel`、`/sentinel/<strategy>`、`/sentinel/detail`、`/api/sentinel/*` |
| `web/templates/index.html` | 在适当位置添加哨兵标签区域 |
| `web/templates/_top_nav.html` | 导航中新增"经典策略哨兵"入口（可选，MVP 可先不放） |

### 8.4 MVP 不包含

- 不包含历史日期浏览（MVP 只看最新交易日）
- 不包含 ATR 吊灯策略
- 不包含移动端适配
- 不包含飞书推送
- 不包含信号趋势图

### 8.5 API 接口（MVP）

```text
GET /api/sentinel/overview?date=YYYY-MM-DD
  → { strategies: [...], total_stocks: N }

GET /api/sentinel/signals?strategy=vcp&date=YYYY-MM-DD
  → { signals: [...], env_match: {...} }

GET /api/sentinel/detail?strategy=vcp&stock=000001&date=YYYY-MM-DD
  → { signal_detail: {...}, evidence_items: [...], stop_rules: [...], exit_rules: [...] }
```

### 8.6 sentinel_api.py 核心查询

```python
# 从 strategy_signals.duckdb 读取当日 entry 信号
SELECT
    stock_code,
    signal_name,
    signal_type,
    confidence,
    state_date,
    trigger_price
FROM signal_records
WHERE strategy = '{strategy_name}'
  AND signal_type = 'entry'
  AND confidence >= 0.50
  AND state_date = '{date}'
ORDER BY confidence DESC
```

---

## 9. 验收标准

### 9.1 数据验收

1. `GET /api/sentinel/overview?date=2026-07-02` 返回当日三个策略的触发统计
2. `GET /api/sentinel/signals?strategy=vcp&date=2026-07-02` 返回 VCP entry 信号列表，数量与 `strategy_signals.duckdb` 一致
3. `GET /api/sentinel/detail?strategy=vcp&stock=000001&date=2026-07-02` 返回该标的的证据项、止损规则、退出规则

### 9.2 页面验收

1. 首页有经典策略哨兵标签区域，有信号时显示激活标签，无信号时灰显或隐藏
2. 点击标签进入对应策略的详情页
3. 详情页展示信号列表，点击单只标的展开详情（证据项逐条勾/叉标注、止损/退出规则）
4. 详情页顶部有免责声明
5. 页面不与 State 面板混淆

### 9.3 隔离验收

1. 哨兵不修改 `state_cube.duckdb`
2. 哨兵不修改 `decision_observation.duckdb`
3. 哨兵页面不包含 State 语义（如同向/领先/冲突/转折概率）
4. 哨兵标签不包含交易建议（如买入/卖出/加仓/减仓）

### 9.4 性能验收

1. `/api/sentinel/overview` 响应时间 < 500ms
2. 详情页加载时间 < 1s

---

## 10. 不做清单

| 序号 | 内容 | 原因 |
|------|------|------|
| 1 | 不写策略信号计算代码 | 已有 `strategy_signal_ledger.py` |
| 2 | 不改 State 概率或 State Cube | 隔离边界 |
| 3 | 不改 `web/templates/index.html` 的 State 面板 | 哨兵标签是独立区域 |
| 4 | 不把哨兵信号解释成 Hermass 主结论 | 硬隔离规则 |
| 5 | 不输出综合交易动作 | Research-Only 边界 |
| 6 | 不做均值回归/突破策略/CANSLIM/动量 | 无代码基础，Phase 2 再评估 |
| 7 | 不做飞书/微信推送 | 超出 MVP 范围 |
| 8 | 不建新的 DuckDB 数据库 | 复用 `strategy_signals.duckdb` |
| 9 | 不新增定时任务 | 复用现有 signal_ledger 管线 |
| 10 | 不把 ATR 吊灯放入第一批哨兵 | 依赖 State 共振，容易混淆边界 |
| 11 | 不把 structure 类信号上首页标签 | 噪音，只有 entry 才上标签 |
| 12 | 不在首页为每个标的显示标签 | 每策略一个聚合标签 |

---

## 11. 附录：当前策略信号管线现状

### 11.1 每日管线中已有步骤

```text
hermes_cron.json 中 strategy_signal_ledger 已存在
  → build_state_cache
  → build_strategy_evidence
  → build_strategy_signal_ledger  ← 这一步产出 strategy_signals.duckdb
  → build_forward_observation
  → build_daily_brief
```

### 11.2 strategy_signals.duckdb 表结构（关键字段）

```sql
signal_records (
    stock_code TEXT,
    state_date DATE,
    strategy TEXT,          -- vcp / ma2560 / bollinger_bandit / atr_chandelier
    signal_name TEXT,       -- vcp_breakout / ma2560_golden_cross / ...
    signal_type TEXT,       -- entry / structure / exit / risk
    confidence REAL,        -- 0.0 - 1.0
    trigger_price REAL,
    w1_mn1_env_label TEXT,  -- 趋势新生 / 趋势行进 / ...
    env_category_factor TEXT,
    source TEXT
)
```

### 11.3 三个策略的信号函数签名（统一接口）

```python
# 所有策略信号函数遵循同一签名：
def xxx_signal(row: dict[str, Any], ctx: dict[str, Any]) -> tuple[str, float] | None:
    """
    row: 当前 bar 数据（close, volume, high, low, etc.）
    ctx: 上下文数据（均线、ATR、ADX 等历史计算值）
    返回: (signal_name, confidence) 或 None
    """
```

这个统一签名意味着哨兵 API 可以通过策略名动态调用信号函数，不需要为每个策略写独立查询。
