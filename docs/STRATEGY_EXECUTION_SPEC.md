# 三策略完整执行与测试规范

版本：v1.0
日期：2026-05-23
状态：设计稿
关联定义：`docs/STRATEGY_DEFINITIONS.md`
关联规则：`docs/MA2560_STATE_MARKET_MATCH_RULE.md`
关联审计：`docs/BOLLINGER_BANDIT_IMPLEMENTATION_AUDIT.md`

---

## 核心原则

策略不仅仅是入场信号。一个完整的策略包含入场确认、头寸管理、出场规则、假突破处理、量价过滤等不可分割的组成部分。当前系统的 `backtest/strategy_signals/` 只实现了入场信号，本文档补全剩余模块。

**A 股适应性**：所有规则必须考虑 T+1 制度（买入当日不可卖出）、涨跌停限制（涨停无法买入、跌停无法卖出）和流动性约束。

---

## 一、入场确认与量价过滤

### 1.1 三策略入场规则总览

| 维度 | VCP | 2560 | 布林强盗 |
|------|-----|------|---------|
| 核心入场 | 价格突破 Pivot Point + 收缩后释放路径 | 股价回踩/站上 25 日均线 + E/F 组合 | 收盘价 > 50 日 SMA+1σ 上轨 + 30 周期动量 |
| 成交量验证 | 突破日量 > 20 日均量 × 1.5 | 5 日均量 > 60 日均量；回调缩量 < 突破日 50% | 突破日量 > 20 日均量 × 1.2（S 级 × 2） |
| 假突破过滤 | 涨停假突破剔除；无量突破降级；3 日未确认→失效 | 多次回踩（>=3 次）放弃；缩量反弹警惕 | 次日收盘 < 信号日最低价→假突破离场；上影线 > 实体 2 倍→毛刺过滤 |

### 1.2 VCP 入场确认

```python
def vcp_entry_confirmation(row: dict, ctx: dict) -> dict:
    """
    VCP 入场确认（在 vcp_signal() 触发后执行）。

    返回：
        {
            "confirmed": bool,           # 是否确认入场
            "signal_grade": str,         # A/B/C 级别
            "rejection_reason": str,     # 拒绝原因（如不确认）
            "volume_ratio": float,       # 突破日量/20日均量
            "is_limit_up": bool,         # 是否涨停
        }
    """
    close = row.get("close", 0)
    pivot = ctx.get("pivot_point", 0)       # 最近一次收缩高点
    vol = row.get("volume", 0)
    vol_ma20 = ctx.get("volume_ma20", 1)
    vol_ratio = vol / vol_ma20 if vol_ma20 > 0 else 0

    # 涨停检查：涨停突破不可执行
    is_limit_up = _is_limit_up(row)
    if is_limit_up:
        return {"confirmed": False, "signal_grade": "C",
                "rejection_reason": "涨停突破，无法买入", "volume_ratio": vol_ratio,
                "is_limit_up": True}

    # 成交量验证
    vol_pass = vol_ratio >= 1.5
    vol_weak = 0.8 <= vol_ratio < 1.5

    # 信号分级
    if vol_pass and not is_limit_up:
        grade = "A"  # 放量突破，最强信号
    elif vol_weak:
        grade = "B"  # 量能偏弱，可观察
    else:
        grade = "C"  # 无量突破，降级

    confirmed = grade in ("A", "B")
    return {
        "confirmed": confirmed,
        "signal_grade": grade,
        "rejection_reason": "" if confirmed else "无量突破，降级为C",
        "volume_ratio": round(vol_ratio, 2),
        "is_limit_up": is_limit_up,
    }


def vcp_entry_timeout(row: dict, ctx: dict) -> bool:
    """VCP 入场超时检查：突破后 3 日收盘未站上 Pivot Point → 失效。"""
    days_since_signal = ctx.get("days_since_entry_signal", 0)
    if days_since_signal > 3 and row.get("close", 0) < ctx.get("pivot_point", 0):
        return True  # 失效
    return False
```

### 1.3 2560 入场确认

```python
def ma2560_entry_confirmation(row: dict, ctx: dict) -> dict:
    """
    2560 入场确认。

    检查项：
        1. 回踩次数：>=3 次放弃
        2. 回调缩量：回调期间成交量 < 突破日均量 50%
        3. 涨停回踩：回踩日涨停不可执行
    """
    pullback_count = ctx.get("pullback_count", 0)
    vol_ratio = ctx.get("pullback_vol_ratio", 1.0)  # 回调期量/突破日均量
    is_limit_up = _is_limit_up(row)

    if pullback_count >= 3:
        return {"confirmed": False, "rejection_reason": "多次回踩(>=3次)，信号质量下降"}

    if is_limit_up:
        return {"confirmed": False, "rejection_reason": "回踩日涨停，无法买入"}

    # 回调缩量是好信号（供应枯竭），但缩量反弹要警惕
    if vol_ratio < 0.5:
        quality = "high"   # 缩量回踩，筹码锁定
    elif vol_ratio < 1.0:
        quality = "medium"  # 温和缩量
    else:
        quality = "low"    # 放量回踩，警惕

    return {
        "confirmed": quality != "low",
        "quality": quality,
        "rejection_reason": "" if quality != "low" else "放量回踩，供应未枯竭",
    }
```

### 1.4 布林强盗入场确认

```python
def bb_entry_confirmation(row: dict, ctx: dict) -> dict:
    """
    布林强盗入场确认。

    检查项：
        1. 上影线过滤：上影线 > 实体 2 倍 → 毛刺行情
        2. 成交量：突破日量 > 20日均量 × 1.2（S 级需 × 2）
        3. 涨停突破：不可执行
    """
    o, h, l, c = row.get("open", 0), row.get("high", 0), row.get("low", 0), row.get("close", 0)
    body = abs(c - o)
    upper_shadow = h - max(o, c)
    vol_ratio = row.get("volume", 0) / ctx.get("volume_ma20", 1)

    # 上影线过滤
    if body > 0 and upper_shadow / body > 2.0:
        return {"confirmed": False, "rejection_reason": "上影线过长(>实体2倍)，毛刺行情"}

    # 涨停检查
    if _is_limit_up(row):
        return {"confirmed": False, "rejection_reason": "涨停突破，无法买入"}

    # 成交量分级
    if vol_ratio >= 2.0:
        grade = "S"  # 超强放量突破
    elif vol_ratio >= 1.2:
        grade = "A"  # 正常放量突破
    else:
        grade = "B"  # 量能偏弱

    return {
        "confirmed": grade in ("S", "A"),
        "signal_grade": grade,
        "volume_ratio": round(vol_ratio, 2),
        "rejection_reason": "" if grade in ("S", "A") else "量能不足",
    }
```

### 1.5 通用涨停/跌停检测

```python
def _is_limit_up(row: dict) -> bool:
    """判断当日是否涨停（A 股 10%/20% 限制简化版）。"""
    close = row.get("close", 0)
    prev_close = row.get("prev_close", 0)
    if prev_close <= 0:
        return False
    change_pct = (close - prev_close) / prev_close
    # 主板 10%，创业板/科创板 20%，简化为 9.8%/19.8% 含误差
    return change_pct >= 0.098

def _is_limit_down(row: dict) -> bool:
    """判断当日是否跌停。"""
    close = row.get("close", 0)
    prev_close = row.get("prev_close", 0)
    if prev_close <= 0:
        return False
    change_pct = (close - prev_close) / prev_close
    return change_pct <= -0.098
```

---

## 二、头寸管理规则

### 2.1 统一风险预算框架

```python
@dataclass
class PositionConfig:
    risk_per_trade: float = 0.02       # 单笔风险 2%（可配置 1%-2%）
    max_positions_per_strategy: int = 10
    max_positions_total: int = 20
    max_industry_concentration: float = 0.30  # 单行业 30% 上限
    atr_period: int = 20
    atr_position_scale: float = 2.0    # ATR 倍数基准
```

### 2.2 仓位计算

```python
def calculate_position_size(
    capital: float,
    entry_price: float,
    stop_price: float,
    atr: float,
    config: PositionConfig,
) -> dict:
    """
    计算头寸规模。

    公式：
        risk_amount = capital × risk_per_trade
        raw_size = risk_amount / (entry_price - stop_price)
        atr_adjusted = raw_size × (config.atr_position_scale / (atr / entry_price * 100))
        final_size = min(raw_size, atr_adjusted)

    返回：
        {
            "shares": int,           # 建议股数（100 股取整）
            "risk_amount": float,    # 风险金额
            "position_value": float, # 持仓市值
            "position_pct": float,   # 占总资金比例
        }
    """
    risk_amount = capital * config.risk_per_trade
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        return {"shares": 0, "risk_amount": 0, "position_value": 0, "position_pct": 0}

    raw_shares = risk_amount / stop_distance

    # ATR 动态调整：波动率高时降低仓位
    atr_pct = atr / entry_price * 100
    atr_factor = min(2.0, config.atr_position_scale / max(atr_pct, 0.5))
    adjusted_shares = raw_shares * atr_factor

    # 取整到 100 股（A 股最小交易单位）
    shares = int(adjusted_shares / 100) * 100
    position_value = shares * entry_price
    position_pct = position_value / capital

    return {
        "shares": shares,
        "risk_amount": round(risk_amount, 2),
        "position_value": round(position_value, 2),
        "position_pct": round(position_pct, 4),
    }
```

### 2.3 持仓限制检查

```python
def check_position_limits(
    current_positions: list[dict],
    new_industry: str,
    config: PositionConfig,
) -> tuple[bool, str]:
    """检查是否超出持仓限制。"""
    strategy_count = sum(1 for p in current_positions if p["strategy_id"] == new_industry)
    total_count = len(current_positions)

    if total_count >= config.max_positions_total:
        return False, f"总持仓已达上限({config.max_positions_total})"

    industry_value = sum(p["position_value"] for p in current_positions if p["industry"] == new_industry)
    total_value = sum(p["position_value"] for p in current_positions)
    if total_value > 0 and industry_value / total_value >= config.max_industry_concentration:
        return False, f"{new_industry}行业集中度已达{config.max_industry_concentration*100:.0f}%上限"

    return True, ""
```

---

## 三、出场规则体系

### 3.1 出场规则总览

| 出场类型 | VCP | 2560 | 布林强盗 |
|----------|-----|------|---------|
| 止损 | 收缩低点下方 1%；2×ATR；硬止损 -6% | 收盘跌破 25 日均线 | 递减均线止损（50→10）；中轨跌破 |
| 止盈/跟踪 | 盈利 >5% 后移动止损至入场价 | 分批（5-10% 减半，>10% 全部） | 上轨回落减 50%；递减均线跟踪 |
| 时间退出 | 持仓 >20 日未达 5%→退出 | 无硬性时间退出 | 持仓 >10 日未达 5%→退出 |
| 特殊规则 | 突破后 3 日收盘 < Pivot→假突破离场 | 跌破 60 日线→强制清仓 | ATR > 入场时 2 倍→减仓 |

### 3.2 VCP 出场规则

```python
def vcp_exit_check(position: dict, row: dict, ctx: dict) -> dict | None:
    """
    VCP 出场检查。返回 None = 继续持有，返回 dict = 触发出场。

    优先级：假突破离场 > 硬止损 > ATR止损 > 技术止损 > 时间退出 > 移动止损
    """
    entry_price = position["entry_price"]
    entry_date = position["entry_date"]
    pivot_point = position.get("pivot_point", entry_price)
    hold_days = ctx.get("hold_days", 0)
    highest_since_entry = position.get("highest_since_entry", entry_price)
    atr = ctx.get("atr", 0)

    current = row.get("close", 0)
    pnl_pct = (current - entry_price) / entry_price

    # 1. 假突破离场：突破后 3 日收盘 < Pivot Point
    if hold_days <= 3 and current < pivot_point:
        return {"exit_reason": "假突破离场", "exit_type": "stop"}

    # 2. 硬止损：-6%
    if pnl_pct <= -0.06:
        return {"exit_reason": "硬止损(-6%)", "exit_type": "stop"}

    # 3. ATR 止损：2×ATR
    atr_stop = entry_price - 2 * atr
    if current < atr_stop:
        return {"exit_reason": "ATR止损(2x)", "exit_type": "stop"}

    # 4. 技术止损：收缩低点下方 1%
    contraction_low = position.get("contraction_low", entry_price * 0.95)
    tech_stop = contraction_low * 0.99
    if current < tech_stop:
        return {"exit_reason": "技术止损(收缩低点)", "exit_type": "stop"}

    # 5. 时间退出：持仓 >20 日未达 5% 盈利
    if hold_days > 20 and pnl_pct < 0.05:
        return {"exit_reason": "时间退出(20日未达5%)", "exit_type": "time"}

    # 6. 移动止损：盈利 >5% 后上移至入场价
    if highest_since_entry >= entry_price * 1.05 and current <= entry_price:
        return {"exit_reason": "移动止损(盈利回吐)", "exit_type": "trailing"}

    return None
```

### 3.3 2560 出场规则

```python
def ma2560_exit_check(position: dict, row: dict, ctx: dict) -> dict | None:
    """
    2560 出场检查。

    优先级：跌破60日线 > 跌破25日均线 > 分批止盈
    """
    entry_price = position["entry_price"]
    current = row.get("close", 0)
    ma25 = ctx.get("ma25", 0)
    ma60 = ctx.get("ma60", 0)
    pnl_pct = (current - entry_price) / entry_price
    half_exited = position.get("half_exited", False)

    # 1. 强制清仓：跌破 60 日线
    if current < ma60:
        return {"exit_reason": "跌破60日线", "exit_type": "stop", "exit_pct": 1.0}

    # 2. 止损：收盘跌破 25 日均线
    if current < ma25:
        return {"exit_reason": "跌破25日均线", "exit_type": "stop", "exit_pct": 1.0}

    # 3. 分批止盈
    if pnl_pct > 0.10 and not half_exited:
        return {"exit_reason": "止盈(>10%全部)", "exit_type": "profit", "exit_pct": 1.0}
    if pnl_pct > 0.05 and not half_exited:
        return {"exit_reason": "止盈(5-10%减半)", "exit_type": "profit", "exit_pct": 0.5}

    return None
```

### 3.4 布林强盗出场规则

```python
def bb_exit_check(position: dict, row: dict, ctx: dict) -> dict | None:
    """
    布林强盗出场检查。

    优先级：ATR异常 > 递减均线止损 > 中轨跌破 > 上轨回落减仓
    """
    entry_price = position["entry_price"]
    hold_days = ctx.get("hold_days", 0)
    current = row.get("close", 0)
    entry_atr = position.get("entry_atr", 0)
    current_atr = ctx.get("atr", 0)
    bb_upper = ctx.get("bb_upper", 0)
    bb_middle = ctx.get("bb_middle", 0)  # 50日SMA

    # 递减均线：持有天数越多，均线越短（50→10）
    exit_ma_period = max(10, 50 - hold_days)
    exit_ma = ctx.get(f"ma{exit_ma_period}", bb_middle)

    pnl_pct = (current - entry_price) / entry_price

    # 1. 波动率异常：ATR > 入场时 2 倍 → 减仓
    if entry_atr > 0 and current_atr > entry_atr * 2:
        return {"exit_reason": "波动率异常(ATR>2x)", "exit_type": "risk", "exit_pct": 0.5}

    # 2. 递减均线止损
    if current < exit_ma:
        return {"exit_reason": f"递减均线止损(MA{exit_ma_period})", "exit_type": "stop", "exit_pct": 1.0}

    # 3. 中轨跌破止损
    if current < bb_middle:
        return {"exit_reason": "中轨跌破(50日SMA)", "exit_type": "stop", "exit_pct": 1.0}

    # 4. 上轨回落减仓：从上方跌破上轨
    if position.get("prev_above_upper", False) and current < bb_upper:
        return {"exit_reason": "上轨回落减仓", "exit_type": "profit", "exit_pct": 0.5}

    # 5. 时间退出：持仓 >10 日未达 5% 盈利
    if hold_days > 10 and pnl_pct < 0.05:
        return {"exit_reason": "时间退出(10日未达5%)", "exit_type": "time"}

    return None
```

### 3.5 止损优先级规则

```python
def select_final_stop_loss(
    current_price: float,
    stop_candidates: list[tuple[str, float]],
) -> tuple[str, float]:
    """
    取各止损线中最靠近当前价者（最保守）。

    参数：
        stop_candidates: [(名称, 止损价), ...]

    返回：
        (选中的止损名称, 选中的止损价)
    """
    # 取最高止损价（最靠近当前价 = 最保守）
    valid = [(name, price) for name, price in stop_candidates if price > 0]
    if not valid:
        return ("无止损", 0)
    return max(valid, key=lambda x: x[1])
```

---

## 四、A 股流动性过滤

### 4.1 基础过滤（所有策略共用）

```python
@dataclass
class LiquidityFilter:
    min_market_cap: float = 3e9          # 流通市值 >= 30 亿
    min_avg_turnover_20d: float = 5e7    # 20日均成交额 >= 5000 万
    min_price: float = 5.0               # 股价 >= 5 元
    min_turnover_rate: float = 0.005     # 换手率 >= 0.5%
    max_turnover_rate: float = 0.20      # 换手率 <= 20%
    min_listing_days: int = 120          # 上市 >= 120 个交易日
    exclude_st: bool = True              # 排除 ST/*ST
    exclude_delisting: bool = True       # 排除退市整理期


def passes_liquidity_filter(row: dict, config: LiquidityFilter) -> tuple[bool, str]:
    """基础流动性过滤。"""
    if config.exclude_st and (row.get("is_st") or row.get("name", "").startswith("*")):
        return False, "ST/*ST"
    if row.get("market_cap", 0) < config.min_market_cap:
        return False, f"市值<{config.min_market_cap/1e8:.0f}亿"
    if row.get("avg_turnover_20d", 0) < config.min_avg_turnover_20d:
        return False, "成交额不足"
    if row.get("close", 0) < config.min_price:
        return False, f"股价<{config.min_price}"
    tr = row.get("turnover_rate", 0)
    if tr < config.min_turnover_rate or tr > config.max_turnover_rate:
        return False, f"换手率异常({tr:.1%})"
    if row.get("listing_days", 999) < config.min_listing_days:
        return False, "上市不足120日"
    return True, ""
```

### 4.2 入场时点过滤

```python
def passes_entry_timing_filter(row: dict, next_day_row: dict | None) -> tuple[bool, str]:
    """入场时点过滤。"""
    # 当日涨停无法买入
    if _is_limit_up(row):
        return False, "涨停无法买入"

    # 次日高开 > 3% 放弃追高
    if next_day_row:
        gap = (next_day_row.get("open", 0) - row.get("close", 0)) / row.get("close", 1)
        if gap > 0.03:
            return False, f"高开{gap:.1%}，放弃追高"

    # 停牌前/复牌后 3 日内不交易
    if row.get("suspended_recently", False):
        return False, "近期停牌"

    return True, ""
```

### 4.3 离场流动性保护

```python
def handle_exit_liquidity(position: dict, row: dict) -> dict:
    """离场流动性保护：跌停无法卖出时的处理。"""
    if _is_limit_down(row):
        return {
            "can_exit": False,
            "action": "次日集合竞价挂跌停价止损",
            "reason": "当日跌停无法卖出",
        }

    if row.get("consecutive_limit_down", 0) >= 2:
        return {
            "can_exit": False,
            "action": "首个可卖出日执行止损",
            "reason": f"连续{row['consecutive_limit_down']}日跌停",
        }

    return {"can_exit": True, "action": "正常执行", "reason": ""}
```

---

## 五、完整测试方案

### 5.1 测试目标

| 目标 | 验证内容 | 通过标准 |
|------|----------|----------|
| 入场质量 | 量价配合、假突破过滤效果 | 过滤后胜率提升 >= 5 个百分点 |
| 出场效果 | 各止损/止盈触发比例和效果 | 止损触发后最大回撤可控（< 10%） |
| 头寸管理 | ATR 动态仓位、持仓限制 | 仓位与波动率负相关（相关系数 < -0.3） |
| 流动性过滤 | 过滤前后可执行性 | 过滤后成交率 > 95% |
| 完整回测 | 全生命周期净值曲线 | 夏普 > 1.0，最大回撤 < 15% |
| 前向观察 | 样本外持续跟踪 | 与回测绩效偏差 < 20% |

### 5.2 测试矩阵

| 测试类型 | 测试内容 | 方法 | 输出 |
|----------|----------|------|------|
| 入场质量回测 | Pivot Point 突破有效性、量价配合 | 分组对比（有量 vs 无量） | 胜率提升表 |
| 假突破统计 | 假突破发生率、过滤效果 | 统计 3 日内回落比例 | 假突破率 |
| 出场规则回测 | 各止损/止盈触发频率 | 逐笔记录触发类型 | 出场规则触发分布 |
| 头寸管理模拟 | ATR 动态仓位效果 | 对比固定仓位 vs ATR 仓位 | 波动率-仓位相关性 |
| 流动性过滤测试 | 过滤前后可执行性 | 模拟实际成交 | 过滤通过率 |
| 完整回测 | 全生命周期净值 | 逐日模拟 | 净值曲线 + 月度热力图 |
| 前向观察对比 | 回测 vs 实际观察 | 逐信号对比 | 偏差分析表 |

### 5.3 执行命令

```bash
# 完整回测
python3 agently_adapter/stockpool_daily_runner.py run_strategy_backtest \
    --strategy vcp \
    --start-date 2024-01-01 \
    --end-date 2026-05-01 \
    --initial-capital 1000000 \
    --risk-per-trade 0.02 \
    --enable-liquidity-filter \
    --enable-exit-rules \
    --output-mode full_report

# 对比测试
python3 agently_adapter/stockpool_daily_runner.py compare_backtest_modes \
    --strategy vcp \
    --mode fixed_hold_20d,full_execution \
    --start-date 2024-01-01 \
    --end-date 2026-05-01

# 三策略完整回测
for strategy in vcp ma2560 bollinger_bandit; do
  python3 agently_adapter/stockpool_daily_runner.py run_strategy_backtest \
      --strategy $strategy \
      --start-date 2024-01-01 \
      --end-date 2026-05-01 \
      --enable-liquidity-filter --enable-exit-rules
done
```

### 5.4 输出报告结构

```text
outputs/strategy_backtest/{strategy}_backtest_{start}_{end}.json
outputs/strategy_backtest/{strategy}_backtest_{start}_{end}.md
public/strategy_backtest_{strategy}_{end}.html
```

报告包含：

```markdown
# {策略} 完整回测报告

## 绩效概览
- 年化收益 / 夏普比率 / 最大回撤
- 总交易笔数 / 胜率 / 盈亏比
- 平均持仓天数

## 净值曲线
（图表）

## 月度收益热力图
（图表）

## 入场质量分析
- 量价配合统计
- 假突破过滤效果
- 信号分级（A/B/C）的绩效对比

## 出场规则分析
- 各出场类型触发频率
- 平均盈亏按出场类型分组
- 最大回撤序列

## 头寸管理效果
- ATR 动态仓位 vs 固定仓位对比
- 行业集中度分布

## 按 State 环境分层
- 各适配度等级的绩效
- 各生命周期阶段的绩效
- 各大周期环境的绩效

## 流动性过滤统计
- 过滤前/后可执行信号数
- 模拟滑点影响

## 逐笔交易记录
（完整交易明细表）
```

### 5.5 前向观察对比

```python
def compare_backtest_vs_forward(
    backtest_trades: list[dict],
    forward_observations: list[dict],
) -> dict:
    """对比回测结果与前向观察账本。"""
    # 按信号日期+股票匹配
    matched = []
    for obs in forward_observations:
        bt = find_matching_backtest_trade(backtest_trades, obs)
        if bt:
            matched.append({
                "signal_date": obs["date"],
                "stock_code": obs["stock_code"],
                "backtest_return": bt["pnl_pct"],
                "forward_return": obs.get("forward_excess_return_20d"),
                "deviation": abs(bt["pnl_pct"] - (obs.get("forward_excess_return_20d") or 0)),
            })

    avg_deviation = statistics.fmean(m["deviation"] for m in matched) if matched else 0

    return {
        "matched_count": len(matched),
        "avg_deviation": round(avg_deviation, 4),
        "deviation_acceptable": avg_deviation < 0.20,  # 偏差 < 20%
    }
```

---

## 附录：A 股制度约束速查

| 约束 | 影响 | 处理方式 |
|------|------|----------|
| T+1 | 买入当日不可卖出 | 入场信号次日执行；止损最早 T+1 日触发 |
| 涨停 10%/20% | 涨停无法买入 | 涨停突破信号标记为不可执行 |
| 跌停 10%/20% | 跌停无法卖出 | 次日集合竞价挂跌停价 |
| 停牌 | 无法交易 | 停牌前/复牌后 3 日不交易 |
| 最小交易单位 | 100 股 | 仓位计算取整到 100 股 |
| ST/*ST | 涨跌停 5%，风险高 | 基础过滤排除 |
| 新股 | 波动大，数据不足 | 上市 < 120 日排除 |
