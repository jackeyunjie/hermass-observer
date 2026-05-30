# 2560 与布林强盗执行规范细化

版本：v1.0
日期：2026-05-24
状态：设计稿
关联文档：
- `docs/STRATEGY_EXECUTION_SPEC.md`（三策略完整执行与测试规范）
- `docs/STRATEGY_DEFINITIONS.md`（经典策略定义与系统边界）
- `docs/MA2560_STATE_MARKET_MATCH_RULE.md`（2560 State 与市场匹配规则）
- `docs/BOLLINGER_BANDIT_IMPLEMENTATION_AUDIT.md`（布林强盗实现对账记录）

---

## 一、2560 执行细节细化

### 1.1 量价配合判定逻辑

2560 的成交量结构分为三个状态，入场确认时必须判定当前处于哪个状态，并应用对应的过滤规则。

#### 成交量状态机

```text
状态 A：冲量（Burst）
  条件：VOL5 刚上穿 VOL60（上穿当日或上穿后 3 日内）
  特征：短线成交动能突然放大，稳定性不足
  处理：信号降级为 B 级；若 VOL5/VOL60 比值 > 2.5，标记为"量能过热"，需额外观察 2 日

状态 B：做量（Build）
  条件：VOL5 反复接近 VOL60 但不下穿，持续 >= 5 日
  特征：波段结构较稳，筹码交换健康
  处理：正常入场；信号可评为 A 级

状态 C：缩量（Contract）
  条件：VOL5 长期位于 VOL60 上方后，出现地量（当日量 < 20 日均量 × 0.4）
  特征：筹码锁定，供应枯竭
  处理：优质信号；若同时满足"缩量小星线"或"坑量结构"，可评为 S 级
```

#### 入场量价配合判定流程

```python
def ma2560_volume_qualification(row: dict, ctx: dict) -> dict:
    """
    2560 入场量价配合判定。

    返回：
        {
            "vol_state": str,       # "冲量" / "做量" / "缩量" / "异常"
            "vol_grade": str,       # "S" / "A" / "B" / "C"
            "vol5_vol60_ratio": float,
            "rejection_reason": str,
        }
    """
    vol5 = ctx.get("volume_ma5", 0)
    vol60 = ctx.get("volume_ma60", 1)
    vol20 = ctx.get("volume_ma20", 1)
    vol_today = row.get("volume", 0)
    days_since_cross = ctx.get("vol5_cross_vol60_days", -1)  # -1=未上穿, 0=上穿当日, >0=上穿后天数

    ratio = vol5 / vol60 if vol60 > 0 else 0
    vol_today_ratio = vol_today / vol20 if vol20 > 0 else 0

    # 状态判定
    if days_since_cross >= 0 and days_since_cross <= 3:
        vol_state = "冲量"
        if ratio > 2.5:
            vol_grade = "C"
            rejection_reason = "冲量过热，VOL5/VOL60 > 2.5，需观察"
        else:
            vol_grade = "B"
            rejection_reason = ""
    elif days_since_cross > 3 and ratio >= 0.9:
        # 检查是否持续 >= 5 日未下穿
        if ctx.get("vol5_above_vol60_streak", 0) >= 5:
            vol_state = "做量"
            vol_grade = "A"
            rejection_reason = ""
        else:
            vol_state = "做量(初期)"
            vol_grade = "B"
            rejection_reason = ""
    elif ratio >= 1.0 and vol_today_ratio < 0.4:
        vol_state = "缩量"
        # 检查是否为缩量小星线或坑量
        is_doji = abs(row.get("close", 0) - row.get("open", 0)) / row.get("open", 1) < 0.005
        is_pit_volume = ctx.get("is_pit_volume", False)
        if is_doji or is_pit_volume:
            vol_grade = "S"
            rejection_reason = ""
        else:
            vol_grade = "A"
            rejection_reason = ""
    else:
        vol_state = "异常"
        vol_grade = "C"
        rejection_reason = "VOL5 低于 VOL60，量能结构不支持"

    return {
        "vol_state": vol_state,
        "vol_grade": vol_grade,
        "vol5_vol60_ratio": round(ratio, 2),
        "rejection_reason": rejection_reason,
    }
```

#### 回调期量价配合（回踩确认时）

```python
def ma2560_pullback_volume_check(row: dict, ctx: dict) -> dict:
    """
    2560 回踩期间的量价配合检查。

    规则：
        1. 回调缩量 < 突破日 50% → 优质（筹码锁定）
        2. 回调缩量在 50%-100% → 正常
        3. 回调放量 > 突破日 100% → 警惕（供应未枯竭）
    """
    breakout_vol = ctx.get("breakout_day_volume", 1)
    pullback_avg_vol = ctx.get("pullback_avg_volume", 0)
    vol_ratio = pullback_avg_vol / breakout_vol if breakout_vol > 0 else 1.0

    if vol_ratio < 0.5:
        quality = "high"
        reason = "缩量回踩，筹码锁定"
    elif vol_ratio < 1.0:
        quality = "medium"
        reason = "温和缩量"
    else:
        quality = "low"
        reason = "放量回踩，供应未枯竭"

    return {
        "quality": quality,
        "vol_ratio": round(vol_ratio, 2),
        "reason": reason,
    }
```

---

### 1.2 多次回踩计数规则

2560 的核心约束是"第一次回踩质量最高，多次回踩后信号质量下降"。需要精确定义"回踩"的判定标准和计数逻辑。

#### 回踩事件定义

```text
回踩（Pullback Event）判定条件（需同时满足）：
  1. 股价此前曾站上 MA25（收盘价 > MA25）
  2. 当前低点触及 MA25 的 ±2% 区间（即 low ∈ [MA25×0.98, MA25×1.02]）
  3. 当前收盘价 >= MA25×0.98（未有效跌破）
  4. 自上一次回踩事件后，股价曾再次明显站上 MA25（收盘价 > MA25×1.02）

有效跌破（Breakdown）判定：
  收盘价 < MA25×0.98 且次日收盘价仍 < MA25×0.98
  → 触发 exit 信号，回踩计数重置
```

#### 回踩计数器状态机

```python
@dataclass
class PullbackCounter:
    count: int = 0               # 当前回踩次数
    last_pullback_date: str = "" # 上次回踩日期
    last_breakout_date: str = "" # 上次有效站上 MA25 日期
    is_above_ma25: bool = False  # 当前是否站在 MA25 上方

    # 阈值配置
    MAX_PULLBACK_COUNT: int = 3  # >=3 次放弃
    PULLBACK_ZONE: float = 0.02  # MA25 ±2% 区间
    BREAKDOWN_THRESHOLD: float = 0.02  # 有效跌破阈值


def update_pullback_counter(counter: PullbackCounter, row: dict, ctx: dict) -> PullbackCounter:
    """
    更新回踩计数器。

    每日调用一次，根据当日 K 线更新状态。
    """
    close = row.get("close", 0)
    low = row.get("low", 0)
    ma25 = ctx.get("ma25", 0)
    date = row.get("date", "")

    if ma25 <= 0:
        return counter

    ma25_upper = ma25 * (1 + counter.PULLBACK_ZONE)
    ma25_lower = ma25 * (1 - counter.PULLDOWN_THRESHOLD)

    was_above = counter.is_above_ma25
    is_above = close > ma25 * (1 + counter.PULLBACK_ZONE)
    is_in_zone = ma25_lower <= low <= ma25_upper
    is_breakdown = close < ma25_lower

    # 状态转移
    if is_breakdown:
        # 有效跌破：重置计数器
        counter.count = 0
        counter.is_above_ma25 = False
        counter.last_breakout_date = ""
    elif was_above and is_in_zone and not is_above:
        # 从上方进入回踩区间：计数 +1
        counter.count += 1
        counter.last_pullback_date = date
        counter.is_above_ma25 = False
    elif not was_above and is_above:
        # 重新站上 MA25：记录突破日期
        counter.is_above_ma25 = True
        counter.last_breakout_date = date

    return counter
```

#### 入场时的回踩次数检查

```python
def ma2560_pullback_entry_check(counter: PullbackCounter, row: dict) -> dict:
    """
    2560 入场时的回踩次数检查。

    返回：
        {
            "can_enter": bool,
            "pullback_count": int,
            "rejection_reason": str,
            "quality_tag": str,  # "首次回踩" / "二次回踩" / "多次回踩" / "放弃"
        }
    """
    count = counter.count

    if count >= counter.MAX_PULLBACK_COUNT:
        return {
            "can_enter": False,
            "pullback_count": count,
            "rejection_reason": f"多次回踩({count}次)，信号质量下降，放弃",
            "quality_tag": "放弃",
        }

    quality_tags = {0: "首次回踩", 1: "首次回踩", 2: "二次回踩"}
    quality_tag = quality_tags.get(count, "多次回踩")

    # 首次回踩质量最高，二次回踩可接受，三次及以上放弃
    can_enter = count < counter.MAX_PULLBACK_COUNT

    return {
        "can_enter": can_enter,
        "pullback_count": count,
        "rejection_reason": "" if can_enter else f"回踩次数={count}，已达上限",
        "quality_tag": quality_tag,
    }
```

---

### 1.3 分批止盈触发顺序

2560 的分批止盈规则需要明确触发顺序、条件判定和状态跟踪。

#### 止盈规则明细

```text
第一止盈点：盈利 5%-10%
  触发：pnl_pct >= 5% 且 pnl_pct < 10%
  动作：减仓 50%（卖出半仓）
  后续：剩余仓位继续跟踪，止损上移至入场价

第二止盈点：盈利 > 10%
  触发：pnl_pct >= 10%
  动作：全部清仓
  前提：第一止盈点尚未触发时，直接触发第二止盈点

止损上移规则：
  触发第一止盈后，剩余仓位的止损从 MA25 下方 1% 上移至入场价
  若股价回落至入场价，清仓剩余仓位
```

#### 分批止盈状态机

```python
@dataclass
class MA2560PositionState:
    entry_price: float
    entry_date: str
    half_exited: bool = False      # 是否已执行第一止盈
    full_exited: bool = False      # 是否已清仓
    stop_price: float = 0.0        # 当前止损价
    highest_pnl_pct: float = 0.0   # 持仓期间最高盈利比例

    # 止盈阈值
    PROFIT_TAKE_1: float = 0.05    # 第一止盈点 5%
    PROFIT_TAKE_2: float = 0.10   # 第二止盈点 10%
    STOP_BELOW_MA25: float = 0.01 # MA25 下方 1% 止损


def ma2560_exit_check_detailed(state: MA2560PositionState, row: dict, ctx: dict) -> dict | None:
    """
    2560 出场检查（细化版）。

    优先级：强制清仓(跌破60日线) > 止损(跌破25日线) > 第二止盈 > 第一止盈 > 移动止损

    返回 None = 继续持有，返回 dict = 触发出场。
    """
    current = row.get("close", 0)
    ma25 = ctx.get("ma25", 0)
    ma60 = ctx.get("ma60", 0)

    pnl_pct = (current - state.entry_price) / state.entry_price
    state.highest_pnl_pct = max(state.highest_pnl_pct, pnl_pct)

    # 1. 强制清仓：收盘跌破 60 日线
    if current < ma60:
        return {
            "exit_reason": "跌破60日线，强制清仓",
            "exit_type": "stop",
            "exit_pct": 1.0,
            "trigger_price": current,
            "ma60": ma60,
        }

    # 2. 止损：收盘跌破 25 日均线
    if current < ma25:
        return {
            "exit_reason": "跌破25日均线，止损",
            "exit_type": "stop",
            "exit_pct": 1.0 if not state.half_exited else 0.5,
            "trigger_price": current,
            "ma25": ma25,
        }

    # 3. 第二止盈点：盈利 >= 10%，全部清仓
    if pnl_pct >= state.PROFIT_TAKE_2 and not state.full_exited:
        state.full_exited = True
        return {
            "exit_reason": f"止盈(盈利≥{state.PROFIT_TAKE_2*100:.0f}%，全部清仓)",
            "exit_type": "profit",
            "exit_pct": 0.5 if state.half_exited else 1.0,
            "trigger_price": current,
            "pnl_pct": round(pnl_pct, 4),
        }

    # 4. 第一止盈点：盈利 5%-10%，减仓 50%
    if state.PROFIT_TAKE_1 <= pnl_pct < state.PROFIT_TAKE_2 and not state.half_exited:
        state.half_exited = True
        state.stop_price = state.entry_price  # 止损上移至入场价
        return {
            "exit_reason": f"止盈(盈利{state.PROFIT_TAKE_1*100:.0f}%-{state.PROFIT_TAKE_2*100:.0f}%，减仓50%)",
            "exit_type": "profit",
            "exit_pct": 0.5,
            "trigger_price": current,
            "pnl_pct": round(pnl_pct, 4),
            "new_stop": state.entry_price,
        }

    # 5. 移动止损：第一止盈后，回落至入场价清仓
    if state.half_exited and current <= state.stop_price:
        return {
            "exit_reason": "移动止损(回落至入场价，清仓剩余仓位)",
            "exit_type": "trailing",
            "exit_pct": 0.5,
            "trigger_price": current,
            "stop_price": state.stop_price,
        }

    return None
```

#### 分批止盈触发顺序图

```text
持仓开始
  │
  ▼
盈利 < 5% ──→ 继续持有，止损=MA25下方1%
  │
  ▼
盈利 5%-10% ──→ 第一止盈：减仓50%，止损上移至入场价
  │
  ▼
盈利 ≥ 10% ──→ 第二止盈：全部清仓（若第一止盈已执行，则清仓剩余50%）
  │
  ▼
跌破 25 日线 ──→ 止损清仓（或清仓剩余仓位）
  │
  ▼
跌破 60 日线 ──→ 强制清仓（最高优先级）
```

---

## 二、布林强盗执行细节细化

### 2.1 递减均线逐日计算

布林强盗的自适应均线（递减均线）是核心出场机制，需要精确到每日的计算逻辑。

#### 递减均线定义

```text
入场日（hold_days = 0）：exit_ma_period = 50，使用 50 日 SMA
持有每增加 1 日：exit_ma_period 减 1
最低递减至：exit_ma_period = 10，使用 10 日 SMA

公式：
  exit_ma_period = max(10, 50 - hold_days)
  exit_ma = SMA(close, exit_ma_period)
```

#### 逐日计算实现

```python
def calculate_exit_ma(hold_days: int, price_history: list[float]) -> tuple[int, float]:
    """
    计算递减均线。

    参数：
        hold_days: 持仓天数（从 0 开始）
        price_history: 收盘价历史序列，最近日在末尾

    返回：
        (exit_ma_period, exit_ma_value)
    """
    exit_ma_period = max(10, 50 - hold_days)

    if len(price_history) < exit_ma_period:
        # 数据不足时，使用可用数据的最大周期
        exit_ma_period = len(price_history)

    exit_ma = sum(price_history[-exit_ma_period:]) / exit_ma_period
    return exit_ma_period, exit_ma


def bollinger_bandit_exit_ma_daily(position: dict, row: dict, ctx: dict) -> dict:
    """
    布林强盗每日递减均线计算与出场检查。

    每日开盘前计算当日 exit_ma，收盘后检查是否触发。
    """
    hold_days = ctx.get("hold_days", 0)
    price_history = ctx.get("close_history", [])

    exit_ma_period, exit_ma = calculate_exit_ma(hold_days, price_history)

    current_close = row.get("close", 0)
    bb_upper = ctx.get("bb_upper", 0)

    # 出场条件：收盘价低于递减均线
    exit_triggered = current_close < exit_ma

    # 额外约束：递减均线必须低于布林上轨（避免在趋势初期过早出场）
    # 当 hold_days 较小时（< 20），exit_ma 可能仍接近或高于 bb_upper
    # 此时不触发出场，直到 exit_ma 低于 bb_upper
    if hold_days < 20 and exit_ma >= bb_upper:
        exit_triggered = False
        constraint_note = "exit_ma 仍高于上轨，暂不触发"
    else:
        constraint_note = ""

    return {
        "exit_ma_period": exit_ma_period,
        "exit_ma": round(exit_ma, 4),
        "bb_upper": bb_upper,
        "current_close": current_close,
        "exit_triggered": exit_triggered,
        "constraint_note": constraint_note,
        "hold_days": hold_days,
    }
```

#### 递减均线周期表

| 持仓天数 | 均线周期 | 说明 |
|----------|----------|------|
| 0 | 50 | 入场日，使用 50 日 SMA |
| 5 | 45 | 持有 5 日 |
| 10 | 40 | 持有 10 日 |
| 20 | 30 | 持有 20 日；此时 exit_ma 通常已低于上轨 |
| 30 | 20 | 持有 30 日 |
| 40 | 10 | 持有 40 日；达到最低周期 10 日 |
| >=40 | 10 | 继续持有，保持 10 日 SMA |

---

### 2.2 中轨跌破与上轨回落减仓优先级

布林强盗有两个独立的减仓/出场条件，需要明确优先级和互斥逻辑。

#### 条件定义

```text
条件 A：中轨跌破（Middle Band Breakdown）
  触发：收盘价 < 50 日 SMA（布林中轨）
  动作：全部清仓
  性质：趋势反转信号，最高优先级止损

条件 B：上轨回落减仓（Upper Band Pullback）
  触发：前一日收盘价 > 上轨，当日收盘价 < 上轨
  动作：减仓 50%
  性质：趋势中的正常回调，保留部分仓位
```

#### 优先级与互斥规则

```text
优先级：中轨跌破 > 上轨回落减仓

互斥规则：
  1. 若当日同时满足中轨跌破和上轨回落，只执行中轨跌破（全部清仓）
  2. 上轨回落减仓只执行一次；执行后标记"已减仓"，后续不再重复触发
  3. 若减仓后股价再次突破上轨并再次回落，可再次触发减仓（需重新判定）
```

#### 实现代码

```python
@dataclass
class BollingerBanditPositionState:
    entry_price: float
    entry_date: str
    entry_atr: float
    half_exited: bool = False      # 是否已执行上轨回落减仓
    prev_above_upper: bool = False # 前一日是否收在上轨上方


def bb_exit_priority_check(state: BollingerBanditPositionState, row: dict, ctx: dict) -> dict | None:
    """
    布林强盗出场检查（优先级细化版）。

    优先级：波动率异常 > 中轨跌破 > 递减均线止损 > 上轨回落减仓 > 时间退出

    返回 None = 继续持有，返回 dict = 触发出场。
    """
    current = row.get("close", 0)
    hold_days = ctx.get("hold_days", 0)
    entry_atr = state.entry_atr
    current_atr = ctx.get("atr", 0)
    bb_upper = ctx.get("bb_upper", 0)
    bb_middle = ctx.get("bb_middle", 0)  # 50 日 SMA

    # 计算递减均线
    exit_ma_period = max(10, 50 - hold_days)
    exit_ma = ctx.get(f"ma{exit_ma_period}", bb_middle)

    pnl_pct = (current - state.entry_price) / state.entry_price

    # 更新"前一日是否在上轨上方"状态
    above_upper = current > bb_upper

    # 1. 波动率异常：ATR > 入场时 2 倍 → 减仓
    if entry_atr > 0 and current_atr > entry_atr * 2:
        return {
            "exit_reason": "波动率异常(ATR>2x入场时)",
            "exit_type": "risk",
            "exit_pct": 0.5,
            "trigger_price": current,
            "current_atr": current_atr,
            "entry_atr": entry_atr,
        }

    # 2. 中轨跌破：收盘价 < 50 日 SMA → 全部清仓（最高优先级）
    if current < bb_middle:
        return {
            "exit_reason": "中轨跌破(50日SMA)，趋势反转",
            "exit_type": "stop",
            "exit_pct": 1.0,
            "trigger_price": current,
            "bb_middle": bb_middle,
        }

    # 3. 递减均线止损
    if current < exit_ma:
        # 额外约束：hold_days < 20 时，exit_ma 可能高于上轨，此时不触发
        if hold_days >= 20 or exit_ma < bb_upper:
            return {
                "exit_reason": f"递减均线止损(MA{exit_ma_period})",
                "exit_type": "stop",
                "exit_pct": 1.0,
                "trigger_price": current,
                "exit_ma": exit_ma,
            }

    # 4. 上轨回落减仓：前一日在上轨上方，当日跌破上轨
    if state.prev_above_upper and current < bb_upper and not state.half_exited:
        state.half_exited = True
        return {
            "exit_reason": "上轨回落减仓(跌破布林上轨)",
            "exit_type": "profit",
            "exit_pct": 0.5,
            "trigger_price": current,
            "bb_upper": bb_upper,
        }

    # 5. 时间退出：持仓 > 10 日未达 5% 盈利
    if hold_days > 10 and pnl_pct < 0.05:
        return {
            "exit_reason": "时间退出(10日未达5%盈利)",
            "exit_type": "time",
            "exit_pct": 1.0,
            "trigger_price": current,
            "pnl_pct": round(pnl_pct, 4),
        }

    # 更新状态
    state.prev_above_upper = above_upper

    return None
```

#### 优先级判定流程图

```text
每日收盘后检查：
  │
  ├─ ATR > 2×入场ATR ?
  │   └─ 是 → 减仓50%（波动率异常保护）
  │
  ├─ 收盘价 < 中轨(50日SMA) ?
  │   └─ 是 → 全部清仓（趋势反转，最高优先级）
  │       └─ [忽略后续所有条件]
  │
  ├─ 收盘价 < 递减均线 ?
  │   └─ 是 → 检查：hold_days>=20 或 exit_ma<上轨 ?
  │       └─ 是 → 全部清仓
  │
  ├─ 前日收盘>上轨 且 当日收盘<上轨 且 未减仓 ?
  │   └─ 是 → 减仓50%（正常回调）
  │
  ├─ 持仓>10日 且 盈利<5% ?
  │   └─ 是 → 全部清仓（时间退出）
  │
  └─ 继续持有
```

---

### 2.3 假突破快速离场判定

布林强盗的假突破判定需要结合次日表现和形态特征。

#### 假突破定义

```text
假突破（False Breakout）判定条件（满足任一即触发）：

类型 1：次日快速回落
  条件：信号日收盘价 > 上轨，次日收盘价 < 信号日最低价
  动作：次日开盘即离场
  优先级：最高（在常规出场条件之前执行）

类型 2：上影线毛刺
  条件：信号日上影线 > 实体 × 2
  动作：信号降级为 B 级；若次日收盘价 < 上轨，离场
  优先级：入场确认时即过滤

类型 3：无量突破
  条件：突破日成交量 < 20 日均量 × 1.2
  动作：信号降级为 B 级；不直接离场，但收紧止损
  优先级：入场确认时降级
```

#### 假突破离场实现

```python
def bb_false_breakout_check(signal_day: dict, next_day: dict, ctx: dict) -> dict:
    """
    布林强盗假突破检查。

    在信号日次日开盘前调用，判定是否假突破。

    参数：
        signal_day: 信号日 K 线数据
        next_day: 次日 K 线数据（可为 None，表示次日数据尚未到达）
        ctx: 上下文数据

    返回：
        {
            "is_false_breakout": bool,
            "false_breakout_type": str,  # "次日回落" / "上影线毛刺" / "无量突破" / ""
            "action": str,               # "立即离场" / "降级观察" / "正常持有"
            "reason": str,
        }
    """
    if next_day is None:
        return {
            "is_false_breakout": False,
            "false_breakout_type": "",
            "action": "等待次日数据",
            "reason": "次日数据尚未到达",
        }

    signal_close = signal_day.get("close", 0)
    signal_low = signal_day.get("low", 0)
    signal_high = signal_day.get("high", 0)
    signal_open = signal_day.get("open", 0)
    signal_vol = signal_day.get("volume", 0)

    next_close = next_day.get("close", 0)
    bb_upper = ctx.get("bb_upper", 0)
    vol_ma20 = ctx.get("volume_ma20", 1)

    # 类型 1：次日快速回落
    if next_close < signal_low:
        return {
            "is_false_breakout": True,
            "false_breakout_type": "次日回落",
            "action": "立即离场",
            "reason": f"次日收盘({next_close}) < 信号日最低({signal_low})，假突破确认",
        }

    # 类型 2：上影线毛刺
    body = abs(signal_close - signal_open)
    upper_shadow = signal_high - max(signal_open, signal_close)
    if body > 0 and upper_shadow / body > 2.0:
        if next_close < bb_upper:
            return {
                "is_false_breakout": True,
                "false_breakout_type": "上影线毛刺",
                "action": "立即离场",
                "reason": f"上影线({upper_shadow:.2f}) > 实体({body:.2f})×2，且次日回落至上轨下方",
            }
        else:
            return {
                "is_false_breakout": False,
                "false_breakout_type": "上影线毛刺",
                "action": "降级观察",
                "reason": "上影线过长但次日仍站上上轨，降级为B级信号",
            }

    # 类型 3：无量突破
    vol_ratio = signal_vol / vol_ma20 if vol_ma20 > 0 else 0
    if vol_ratio < 1.2:
        return {
            "is_false_breakout": False,
            "false_breakout_type": "无量突破",
            "action": "降级观察",
            "reason": f"突破日量/20日均量={vol_ratio:.2f} < 1.2，量能不足，降级为B级",
        }

    return {
        "is_false_breakout": False,
        "false_breakout_type": "",
        "action": "正常持有",
        "reason": "未触发假突破条件",
    }
```

#### 假突破与常规出场的优先级

```text
出场优先级总序（布林强盗）：

1. 假突破快速离场（次日开盘即执行）
2. 波动率异常减仓（ATR > 2×入场ATR）
3. 中轨跌破清仓（趋势反转）
4. 递减均线止损（自适应均线）
5. 上轨回落减仓（正常回调）
6. 时间退出（10日未达5%盈利）

注意：
  - 假突破判定在"次日"执行，而常规出场条件在"每日收盘后"执行
  - 若次日同时触发假突破和常规出场，假突破优先
  - 假突破离场后，该笔交易结束，不再检查后续出场条件
```

---

## 三、状态跟踪与数据持久化

### 3.1 2560 持仓状态

```python
@dataclass
class MA2560PositionRecord:
    stock_code: str
    entry_date: str
    entry_price: float
    shares: int
    strategy_id: str = "ma2560"

    # 2560 特有状态
    pullback_count_at_entry: int = 0   # 入场时的回踩次数
    vol_state_at_entry: str = ""       # 入场时的成交量状态
    breakout_volume: float = 0.0       # 突破日成交量

    # 止盈状态
    half_exited: bool = False
    half_exit_date: str = ""
    half_exit_price: float = 0.0
    full_exited: bool = False
    full_exit_date: str = ""
    full_exit_price: float = 0.0

    # 止损跟踪
    current_stop_price: float = 0.0
    stop_reason: str = ""
```

### 3.2 布林强盗持仓状态

```python
@dataclass
class BollingerBanditPositionRecord:
    stock_code: str
    entry_date: str
    entry_price: float
    shares: int
    strategy_id: str = "bollinger_bandit"

    # 布林强盗特有状态
    entry_atr: float = 0.0             # 入场时 ATR
    entry_bb_upper: float = 0.0        # 入场时布林上轨
    half_exited: bool = False
    prev_above_upper: bool = False     # 前一日是否在上轨上方

    # 递减均线跟踪
    current_exit_ma_period: int = 50
    current_exit_ma: float = 0.0

    # 假突破标记
    false_breakout_checked: bool = False  # 是否已完成假突破检查
    is_false_breakout: bool = False
```

---

## 四、与主规范的衔接

### 4.1 2560 与 STRATEGY_EXECUTION_SPEC.md 的衔接

| 主规范章节 | 2560 细化内容 |
|-----------|--------------|
| 1.3 2560 入场确认 | 增加量价配合判定（冲量/做量/缩量三状态） |
| 1.3 回踩次数 | 精确定义回踩事件和计数器状态机 |
| 3.3 2560 出场规则 | 明确分批止盈触发顺序和互斥逻辑 |
| 2.2 仓位计算 | 2560 适用标准 ATR 仓位公式 |

### 4.2 布林强盗与 STRATEGY_EXECUTION_SPEC.md 的衔接

| 主规范章节 | 布林强盗细化内容 |
|-----------|----------------|
| 1.4 布林强盗入场确认 | 增加上影线毛刺过滤和成交量分级（S/A/B） |
| 3.4 布林强盗出场规则 | 细化递减均线逐日计算、中轨跌破优先级、假突破判定 |
| 2.2 仓位计算 | 布林强盗适用标准 ATR 仓位公式 |

### 4.3 与 STRATEGY_DEFINITIONS.md 的衔接

本文档是对 `STRATEGY_DEFINITIONS.md` 中"离场规则"和"系统映射"的细化，不改变策略核心定义：

- 2560 的核心参数（MA25、VOL5、VOL60）不变
- 布林强盗的核心参数（MA50、1σ、30日动量）不变
- 自适应均线机制（50→10）不变
- 本文档只增加执行层的判定细节和状态跟踪

---

## 五、测试要点

### 5.1 2560 测试要点

| 测试项 | 验证内容 | 通过标准 |
|--------|----------|----------|
| 回踩计数 | 多次回踩是否正确计数 | 3 次后拒绝入场 |
| 量价状态 | 冲量/做量/缩量判定 | 与人工判定一致率 > 90% |
| 分批止盈 | 5%-10% 减半，>10% 清仓 | 触发比例符合预期 |
| 止损上移 | 第一止盈后止损移至入场价 | 回落时正确清仓 |

### 5.2 布林强盗测试要点

| 测试项 | 验证内容 | 通过标准 |
|--------|----------|----------|
| 递减均线 | 每日周期正确递减 | 50→10 逐日减 1 |
| 中轨跌破 | 优先级高于上轨回落 | 同时触发时只执行中轨跌破 |
| 假突破 | 次日回落判定 | 次日收盘 < 信号日最低时正确离场 |
| 上影线过滤 | 入场时过滤 | 上影线 > 实体 2 倍时降级/拒绝 |

---

*本文档由 STRATEGY_EXECUTION_SPEC.md 细化而来，只补充执行层细节，不修改策略核心规则。*
