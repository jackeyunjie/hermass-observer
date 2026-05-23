# Agently DynamicTask DAG 技术设计方案
## 股票池每日更新流水线 — 三周期 E/F 共振选股系统

> **版本**: v1.0  
> **日期**: 2026-05-21  
> **适配框架**: Agently 4.1.x (Actions + TriggerFlow + DynamicTask DAG)  
> **目标系统**: P116 三周期全 E/F 股票池筛选系统

---

## 1. 现状分析与 DAG 设计目标

### 1.1 当前系统数据结构（从生产环境提取）

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `rank` | int | 排名 | 241 |
| `stock_code` | string | 股票代码 | 000518 |
| `symbol` | string | 完整代码 | 000518.SZ |
| `stock_name` | string | 股票名称 | *ST恒立 |
| `sw_l1` | string | 申万一级行业 | 医药生物 |
| `sw_l2` | string | 申万二级行业 | 生物制品 |
| `sw_l3` | string | 申万三级行业 | 其他生物制品 |
| `date` | date | 数据日期 | 2026-05-20 |
| `d1_close` | float | 日线收盘价 | 3.41 |
| `state_score_sum` | int | 状态分数总和 | 42 |
| `ef_strength` | int | E/F 强度 | 3 |
| `mn1_state` | enum(E/F) | 月线状态 | E |
| `w1_state` | enum(E/F) | 周线状态 | E |
| `d1_state` | enum(E/F) | 日线状态 | E |
| `mn1_score` | int | 月线分数 | 14 |
| `w1_score` | int | 周线分数 | 14 |
| `d1_score` | int | 日线分数 | 14 |
| `mn1_support` | float | 月线支撑值 | 1.72 |

### 1.2 行业分布（2026-05-20 快照）

```
电子(77) 机械设备(42) 基础化工(24) 电力设备(24) 医药生物(10) 计算机(9)
通信(7) 传媒(7) 建筑装饰(6) 汽车(6) 公用事业(5) 家用电器(4) ... = 246只
```

### 1.3 当前流程痛点

1. **手动触发**：每日收盘后需人工触发计算流程
2. **串行执行**：数据采集→计算→分类→发布依次进行，无法并行
3. **缺少容错**：某一步失败需全部重跑
4. **状态不透明**：无法实时查看哪个环节在进行中
5. **数据源单一**：仅依赖单一行情数据源

### 1.4 DAG 设计目标

- ✅ **全自动化**：收盘后自动触发，无需人工干预
- ✅ **并行采集**：多数据源同时采集，取最短完成时间
- ✅ **容错降级**：某数据源失败可降级到备用源
- ✅ **状态可视化**：每个节点状态可实时查询
- ✅ **动态规划**：模型可在运行时根据市场状况调整策略

---

## 2. DAG 架构设计

### 2.1 整体 DAG 拓扑

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        stockpool_daily_update (DAG)                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PHASE: start (并行采集层)                                                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  fetch_heilang  │  │  validate_data  │  │                 │             │
│  │   (Python沙盒)   │  │   (Python沙盒)   │  │  (Bash沙盒)      │             │
│  │  ─────────────  │  │  ─────────────  │  │  ─────────────  │             │
│  │  目标: 获取日线   │  │  目标: 获取日线   │  │  目标: 校验数据   │             │
│  │  超时: 120s     │  │  超时: 120s     │  │  完成性          │             │
│  │  降级: 本地缓存  │  │  失败: 重新下载   │  │                 │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           └────────────────────┼────────────────────┘                       │
│                                ▼                                            │
│                    ┌─────────────────────┐                                  │
│                    │   merge_data_sources │                                 │
│                    │     (Python沙盒)      │                                 │
│                    │   ────────────────   │                                 │
│                    │   合并多源数据去重     │                                 │
│                    └──────────┬──────────┘                                  │
│                               ▼                                             │
│  PHASE: seal (计算层)         ▼                                             │
│  ┌──────────────────────────────────────────────┐                          │
│  │         calculate_ef_states                  │                          │
│  │            (Python沙盒)                       │                          │
│  │         ─────────────────                    │                          │
│  │  输入: 日线OHLCV数据                           │                          │
│  │  算法: MN1/W1/D1三周期E/F状态共振              │                          │
│  │  输出: mn1_state,w1_state,d1_state,           │                          │
│  │        state_score_sum, ef_strength           │                          │
│  │  超时: 300s                                   │                          │
│  │  降级: 使用昨日缓存                            │                          │
│  └──────────────────────┬───────────────────────┘                          │
│                         ▼                                                   │
│  ┌──────────────────────────────────────────────┐                          │
│  │         classify_stock_pool                  │                          │
│  │            (Python沙盒)                       │                          │
│  │         ─────────────────                    │                          │
│  │  输入: 全部股票的E/F状态                      │                          │
│  │  逻辑: 与昨日对比 → 新进入/离开/留存           │                          │
│  │  输出: new_in(57), left(62), retained(189)   │                          │
│  │  超时: 60s                                    │                          │
│  └──────────────────────┬───────────────────────┘                          │
│                         ▼                                                   │
│  ┌──────────────────────────────────────────────┐                          │
│  │      enrich_industry_metrics                 │                          │
│  │            (Python沙盒)                       │                          │
│  │         ─────────────────                    │                          │
│  │  输入: 股票池分类结果                         │                          │
│  │  逻辑: 行业聚合统计+分数排名                   │                          │
│  │  输出: 行业分布(sw_l1计数)+rank排名           │                          │
│  │  超时: 60s                                    │                          │
│  └──────────────────────┬───────────────────────┘                          │
│                         ▼                                                   │
│  PHASE: close (发布层)       ▼                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────────┐   │
│  │  generate_  │  │   deploy_   │  │  notify_    │  │  archive_      │   │
│  │  json_data  │  │   static    │  │  subscribers│  │  history       │   │
│  │ (NodeJS沙盒) │  │  (Bash沙盒)  │  │  (MCP)       │  │ (Python沙盒)    │   │
│  │ ─────────── │  │ ─────────── │  │ ─────────── │  │ ───────────── │   │
│  │ 生成JSON文件 │  │ 部署到CDN   │  │ 推送邮件/   │  │ 归档到历史    │   │
│  │ 供API使用   │  │ /服务器     │  │ 微信/API    │  │ 数据库       │   │
│  │ 超时: 30s   │  │ 超时: 60s   │  │ 超时: 120s  │  │ 超时: 30s    │   │
│  └─────────────┘  └─────────────┘  └─────────────┘  └────────────────┘   │
│       │                │                │                │                 │
│       └────────────────┴────────────────┴────────────────┘                 │
│                                          │                                  │
│                                          ▼                                  │
│                              ┌─────────────────────┐                       │
│                              │    cleanup_cache    │                       │
│                              │     (Bash沙盒)       │                       │
│                              │   ────────────────  │                       │
│                              │   清理临时文件       │                       │
│                              │   标记完成状态       │                       │
│                              └─────────────────────┘                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 节点依赖矩阵

| 节点ID | 所属Phase | 前置依赖 | 并行度 | 超时(秒) | 降级策略 |
|--------|----------|---------|--------|---------|---------|
| `fetch_heilang_data` | start | — | — | 180 | 本地昨日缓存 |
| `validate_data` | start | fetch_heilang_data | — | 30 | 重新下载 |
| `merge_data_sources` | start | 以上2个 | — | 60 | 使用缓存数据 |
| `calculate_ef_states` | seal | merge_data_sources | — | 300 | 使用昨日缓存+标记延迟 |
| `classify_stock_pool` | seal | calculate_ef_states | — | 60 | — |
| `enrich_industry_metrics` | seal | classify_stock_pool | — | 60 | 跳过行业统计 |
| `generate_json_data` | close | enrich_industry_metrics | 4路并行 | 30 | 标记失败不阻断 |
| `deploy_static` | close | enrich_industry_metrics | 4路并行 | 60 | 标记失败不阻断 |
| `notify_subscribers` | close | enrich_industry_metrics | 4路并行 | 120 | 标记失败不阻断 |
| `archive_history` | close | enrich_industry_metrics | 4路并行 | 30 | 标记失败不阻断 |
| `cleanup_cache` | close | 以上4个 | — | 30 | — |

---

## 3. TriggerFlow 生命周期设计

### 3.1 三阶段生命周期映射

```
Trigger (每日 15:35 CST 收盘后触发)
    │
    ▼
┌────────────────────────────────────────────────────────────┐
│  PHASE: start                                              │
│  目标: 完成数据采集，确保计算所需数据就绪                     │
│  超时: 300s (5分钟)                                        │
│  失败策略: 重试1次 → 仍失败则进入降级模式                    │
│                                                           │
│  Module-safe 检查清单:                                      │
│  □ 黑狼数据API token有效且未过期                            │
│  □ 采集脚本可正常调用黑狼数据API                       │
│  □ 本地缓存目录可读写                                       │
│  □ 目标日期数据未已存在（幂等检查）                           │
└────────────────────────────────────────────────────────────┘
    │
    │ seal 条件: merge_data_sources 输出非空且记录数 ≥ 4000
    │
    ▼
┌────────────────────────────────────────────────────────────┐
│  PHASE: seal                                               │
│  目标: 完成E/F计算和股票池分类，产出今日股票池                 │
│  超时: 600s (10分钟)                                       │
│  失败策略: 使用昨日缓存数据 + 发送延迟通知                    │
│                                                           │
│  Module-safe 检查清单:                                      │
│  □ 输入数据包含所需OHLCV字段                                │
│  □ 计算结果记录数 = 输入记录数（无丢失）                      │
│  □ E/F状态分布合理（非全E或全F）                            │
│  □ 三周期全部为E/F的品种数在预期范围(200-300)                 │
└────────────────────────────────────────────────────────────┘
    │
    │ close 条件: enrich_industry_metrics 完成
    │
    ▼
┌────────────────────────────────────────────────────────────┐
│  PHASE: close                                              │
│  目标: 完成数据发布、通知、归档，清理临时文件                  │
│  超时: 300s (5分钟)                                        │
│  失败策略: 各节点独立失败不影响其他节点（并行发布）              │
│                                                           │
│  Module-safe 检查清单:                                      │
│  □ JSON文件生成成功且大小合理                                │
│  □ CDN部署返回200                                          │
│  □ 历史归档记录写入成功                                     │
└────────────────────────────────────────────────────────────┘
    │
    ▼
Done → 触发 notify_admin (发送执行报告)
```

### 3.2 运行时动态规划策略

```python
# DynamicTask 运行时决策逻辑（由模型在执行中决策）

DECISION_RULES = {
    "holiday_check": {
        "condition": "date in chinese_holidays",
        "action": "SKIP_EXECUTION",
        "message": "节假日跳过执行"
    },
    "half_trading_day": {
        "condition": "is_half_day_trading(date)",
        "action": "DELAY_TRIGGER",
        "params": {"delay_to": "13:05"},
        "message": "半日市延迟到13:05触发"
    },
    "data_source_failure": {
        "condition": "heilang_status == 'FAILED'",
        "action": "ESCALATE",
        "fallback": "use_local_cache(date-1)",
        "message": "黑狼数据API调用失败，使用昨日缓存并告警"
    },
    "abnormal_pool_size": {
        "condition": "pool_size < 100 or pool_size > 500",
        "action": "PAUSE_AND_ALERT",
        "requires_human": True,
        "message": "股票池数量异常，需人工确认"
    },
    "market_crash_detected": {
        "condition": "drop_300 > 0.05",  # 沪深300跌幅>5%
        "action": "ADJUST_STRATEGY",
        "params": {"increase_defensive_weight": True},
        "message": "市场大幅波动，增加防御性标注"
    }
}
```

---

## 4. Actions 配置

### 4.1 已定义 Actions

```yaml
# agently_actions.yaml

actions:
  # ─── Python 沙盒 ──────────────────────────────────────────
  python_sandbox:
    type: python_sandbox
    version: "3.11"
    config:
      memory_limit: "512MB"
      cpu_limit: "2 cores"
      timeout_default: 120
      packages:  # 预装包
        - requests>=2.31.0
        - pandas>=2.0.0
        - numpy>=1.24.0
      env_vars:
        HEILANG_TOKEN: "${HEILANG_TOKEN}"
        HEILANG_API_URL: "${HEILANG_API_URL:-https://api.heilangdata.com}"
        CACHE_DIR: "/tmp/agently/cache"
      security:
        network_access: true   # 允许访问行情API
        file_write: true       # 允许写入缓存
        file_read: true        # 允许读取数据

  # ─── Bash 沙盒 ────────────────────────────────────────────
  bash_sandbox:
    type: bash_sandbox
    config:
      timeout_default: 60
      allowed_commands:
        - curl
        - rsync
        - mkdir
        - rm
        - cp
        - mv
        - echo
        - date
        - test
        - wc
      blocked_patterns:
        - "rm -rf /"
        - ">/dev/null"
      working_dir: "/tmp/agently"

  # ─── NodeJS 沙盒 ──────────────────────────────────────────
  nodejs_sandbox:
    type: nodejs_sandbox
    version: "20"
    config:
      memory_limit: "256MB"
      timeout_default: 30
      packages:
        - fs-extra
        - dayjs
        - lodash

  # ─── MCP (Model Context Protocol) ─────────────────────────
  notification_mcp:
    type: mcp
    server: "notification-server"
    config:
      transport: "stdio"
      tools:
        - send_email
        - send_wechat
        - webhook_post
      rate_limit: "100/min"
```

### 4.2 各节点 Action 调用

| 节点 | Action Type | 入口脚本 | 输入 | 输出 |
|------|------------|---------|------|------|
| `fetch_heilang_data` | `python_sandbox` | `actions/fetch_heilang.py` | target_date | 日线DataFrame (CSV) |
| `validate_data` | `python_sandbox` | `actions/validate_data.py` | CSV文件 | 校验报告 (JSON) |
| `merge_data_sources` | `python_sandbox` | `actions/merge_sources.py` | 多源CSV | 合并DataFrame (CSV) |
| `calculate_ef_states` | `python_sandbox` | `actions/calculate_ef.py` | OHLCV CSV | E/F状态 (CSV) |
| `classify_stock_pool` | `python_sandbox` | `actions/classify_pool.py` | 今日+昨日E/F | 分类结果 (JSON) |
| `enrich_industry_metrics` | `python_sandbox` | `actions/enrich_metrics.py` | 分类结果 | 完整股票池 (JSON) |
| `generate_json_data` | `nodejs_sandbox` | `actions/generate_json.js` | 完整股票池 | API JSON文件 |
| `deploy_static` | `bash_sandbox` | `actions/deploy.sh` | JSON文件 | 部署状态码 |
| `notify_subscribers` | `mcp` | `send_email` / `send_wechat` | 变动摘要 | 发送状态 |
| `archive_history` | `python_sandbox` | `actions/archive_history.py` | 完整数据 | DB记录 |
| `cleanup_cache` | `bash_sandbox` | `actions/cleanup.sh` | — | 清理状态 |

---

## 5. 核心计算脚本

### 5.1 E/F 状态计算（calculate_ef.py）

```python
#!/usr/bin/env python3
"""
三周期 E/F 状态共振计算
输入: OHLCV 日线数据
输出: mn1_state, w1_state, d1_state, state_score_sum, ef_strength
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Literal
import json
import sys

State = Literal["E", "F"]

@dataclass
class EFResult:
    stock_code: str
    symbol: str
    stock_name: str
    sw_l1: str
    sw_l2: str
    sw_l3: str
    date: str
    d1_close: float
    mn1_state: State
    w1_state: State
    d1_state: State
    mn1_score: int
    w1_score: int
    d1_score: int
    state_score_sum: int
    ef_strength: int
    mn1_support: float


class EFCalculator:
    """三周期 E/F 状态计算器"""

    # ── 参数配置（可根据市场状况动态调整）────
    D1_PARAMS = {
        "ema_fast": 5,
        "ema_slow": 13,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
    }

    W1_PARAMS = {
        "ema_fast": 4,   # 周线约20日线
        "ema_slow": 8,   # 周线约40日线
    }

    MN1_PARAMS = {
        "ema_fast": 3,   # 月线约60日线
        "ema_slow": 6,   # 月线约120日线
    }

    # E/F 判定阈值
    THRESHOLDS = {
        "strong_E": 3,    # 强趋势(3分)
        "weak_E": 2,      # 中趋势(2分)
        "neutral": 1,     # 弱信号(1分)
        "weak_F": 2,      # 中反趋势(2分)
        "strong_F": 3,    # 强反趋势(3分)
    }

    def __init__(self, df_daily: pd.DataFrame):
        """
        Args:
            df_daily: 日线OHLCV数据，列: [ts_code, trade_date, open, high, low, close, vol]
        """
        self.df = df_daily.sort_values(["ts_code", "trade_date"])
        self.results: list[EFResult] = []

    # ── 日线 E/F 计算 ──────────────────
    def _calc_d1_state(self, stock_df: pd.DataFrame) -> tuple[State, int, float]:
        """计算日线E/F状态"""
        p = self.D1_PARAMS

        # EMA交叉
        ema_fast = stock_df["close"].ewm(span=p["ema_fast"], adjust=False).mean()
        ema_slow = stock_df["close"].ewm(span=p["ema_slow"], adjust=False).mean()

        # MACD
        ema12 = stock_df["close"].ewm(span=p["macd_fast"], adjust=False).mean()
        ema26 = stock_df["close"].ewm(span=p["macd_slow"], adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=p["macd_signal"], adjust=False).mean()
        macd = (dif - dea) * 2

        # 最新值
        latest_close = stock_df["close"].iloc[-1]
        latest_ema_fast = ema_fast.iloc[-1]
        latest_ema_slow = ema_slow.iloc[-1]
        latest_dif = dif.iloc[-1]
        latest_dea = dea.iloc[-1]
        latest_macd = macd.iloc[-1]

        # E: 多头信号 / F: 空头信号
        score = 0

        # 均线排列
        if latest_ema_fast > latest_ema_slow:
            score += 1
        else:
            score -= 1

        # DIF-DEA
        if latest_dif > latest_dea:
            score += 1
        else:
            score -= 1

        # MACD方向
        if len(macd) >= 2 and latest_macd > macd.iloc[-2]:
            score += 1
        else:
            score -= 1

        # 收盘价vs EMA
        if latest_close > latest_ema_fast:
            score += 1
        else:
            score -= 1

        # 转换为E/F状态和分数
        if score >= 2:
            return "E", self.THRESHOLDS["strong_E"], latest_ema_slow
        elif score >= 0:
            return "E", self.THRESHOLDS["weak_E"], latest_ema_slow
        elif score >= -1:
            return "F", self.THRESHOLDS["neutral"], latest_ema_slow
        else:
            return "F", self.THRESHOLDS["strong_F"], latest_ema_slow

    # ── 周线 E/F 计算 ──────────────────
    def _calc_w1_state(self, stock_df: pd.DataFrame) -> tuple[State, int]:
        """计算周线E/F状态（将日线聚合为周线）"""
        p = self.W1_PARAMS

        # 日线→周线
        stock_df["week"] = pd.to_datetime(stock_df["trade_date"]).dt.isocalendar().week
        stock_df["year"] = pd.to_datetime(stock_df["trade_date"]).dt.isocalendar().year

        weekly = stock_df.groupby(["year", "week"]).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "vol": "sum"
        }).reset_index()

        if len(weekly) < p["ema_slow"]:
            return "E", 1  # 数据不足时默认

        ema_fast = weekly["close"].ewm(span=p["ema_fast"], adjust=False).mean()
        ema_slow = weekly["close"].ewm(span=p["ema_slow"], adjust=False).mean()

        latest_close = weekly["close"].iloc[-1]
        latest_ema_fast = ema_fast.iloc[-1]
        latest_ema_slow = ema_slow.iloc[-1]

        score = 0
        if latest_ema_fast > latest_ema_slow:
            score += 1
        if latest_close > latest_ema_fast:
            score += 1

        if score >= 2:
            return "E", self.THRESHOLDS["strong_E"]
        elif score == 1:
            return "E", self.THRESHOLDS["weak_E"]
        elif score == 0:
            return "F", self.THRESHOLDS["neutral"]
        else:
            return "F", self.THRESHOLDS["strong_F"]

    # ── 月线 E/F 计算 ──────────────────
    def _calc_mn1_state(self, stock_df: pd.DataFrame) -> tuple[State, int, float]:
        """计算月线E/F状态"""
        p = self.MN1_PARAMS

        # 日线→月线
        stock_df["month"] = pd.to_datetime(stock_df["trade_date"]).dt.month
        stock_df["year"] = pd.to_datetime(stock_df["trade_date"]).dt.year

        monthly = stock_df.groupby(["year", "month"]).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "vol": "sum"
        }).reset_index()

        if len(monthly) < p["ema_slow"]:
            return "E", 1, monthly["close"].mean()

        ema_fast = monthly["close"].ewm(span=p["ema_fast"], adjust=False).mean()
        ema_slow = monthly["close"].ewm(span=p["ema_slow"], adjust=False).mean()

        latest_close = monthly["close"].iloc[-1]
        latest_ema_fast = ema_fast.iloc[-1]
        latest_ema_slow = ema_slow.iloc[-1]

        score = 0
        if latest_ema_fast > latest_ema_slow:
            score += 1
        if latest_close > latest_ema_fast:
            score += 1

        if score >= 2:
            return "E", self.THRESHOLDS["strong_E"], latest_ema_slow
        elif score == 1:
            return "E", self.THRESHOLDS["weak_E"], latest_ema_slow
        elif score == 0:
            return "F", self.THRESHOLDS["neutral"], latest_ema_slow
        else:
            return "F", self.THRESHOLDS["strong_F"], latest_ema_slow

    # ── 全量计算 ───────────────────────
    def calculate_all(self, stock_info: pd.DataFrame) -> pd.DataFrame:
        """
        对所有股票计算三周期E/F状态

        Args:
            stock_info: 股票基础信息 [ts_code, name, industry]
        Returns:
            DataFrame with all EFResult fields
        """
        target_date = self.df["trade_date"].max()

        for ts_code in self.df["ts_code"].unique():
            stock_df = self.df[self.df["ts_code"] == ts_code]

            # 数据量检查
            if len(stock_df) < 60:  # 至少需要60个交易日
                continue

            # 三级计算
            d1_state, d1_score, _ = self._calc_d1_state(stock_df)
            w1_state, w1_score = self._calc_w1_state(stock_df)
            mn1_state, mn1_score, mn1_support = self._calc_mn1_state(stock_df)

            # 只有当三周期全部为E或全部为F时才纳入
            all_E = (mn1_state == "E" and w1_state == "E" and d1_state == "E")
            all_F = (mn1_state == "F" and w1_state == "F" and d1_state == "F")

            if not (all_E or all_F):
                continue

            # 获取股票信息
            info = stock_info[stock_info["ts_code"] == ts_code]
            name = info["name"].values[0] if len(info) > 0 else ""
            sw_l1 = info["industry"].values[0] if len(info) > 0 else ""

            # 汇总分数
            state_score_sum = mn1_score + w1_score + d1_score
            ef_strength = max(mn1_score, w1_score, d1_score)

            result = EFResult(
                stock_code=ts_code.split(".")[0],
                symbol=ts_code,
                stock_name=name,
                sw_l1=sw_l1,
                sw_l2="",
                sw_l3="",
                date=target_date,
                d1_close=stock_df["close"].iloc[-1],
                mn1_state=mn1_state,
                w1_state=w1_state,
                d1_state=d1_state,
                mn1_score=mn1_score,
                w1_score=w1_score,
                d1_score=d1_score,
                state_score_sum=state_score_sum,
                ef_strength=ef_strength,
                mn1_support=round(mn1_support, 2)
            )
            self.results.append(result)

        return self._to_dataframe()

    def _to_dataframe(self) -> pd.DataFrame:
        """转换为DataFrame输出"""
        if not self.results:
            return pd.DataFrame()

        data = [r.__dict__ for r in self.results]
        df = pd.DataFrame(data)

        # 按 state_score_sum 降序排列
        df = df.sort_values("state_score_sum", ascending=False)
        df["rank"] = range(1, len(df) + 1)

        return df


# ─── 主入口 ─────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="输入CSV文件路径")
    parser.add_argument("--info", required=True, help="股票信息CSV路径")
    parser.add_argument("--output", required=True, help="输出CSV文件路径")
    parser.add_argument("--date", required=True, help="目标日期 YYYYMMDD")
    args = parser.parse_args()

    # 读取数据
    df_daily = pd.read_csv(args.input)
    stock_info = pd.read_csv(args.info)

    # 计算
    calculator = EFCalculator(df_daily)
    result_df = calculator.calculate_all(stock_info)

    # 输出
    result_df.to_csv(args.output, index=False)
    print(json.dumps({
        "status": "success",
        "date": args.date,
        "total_stocks": len(result_df),
        "all_E_count": int((result_df["mn1_state"] == "E").sum()),
        "all_F_count": int((result_df["mn1_state"] == "F").sum()),
        "output_path": args.output
    }))
```

### 5.2 股票池分类（classify_pool.py）

```python
#!/usr/bin/env python3
"""
股票池分类：与昨日对比，产出新进入/离开/留存
"""

import pandas as pd
import json
import sys
import argparse
from pathlib import Path


def classify_stock_pool(
    today_df: pd.DataFrame,
    yesterday_df: pd.DataFrame,
    target_date: str
) -> dict:
    """
    分类股票池变动

    Returns:
        {
            "new_in": [...],      # 新进入（今日在池，昨日不在）
            "left": [...],        # 离开（今日不在池，昨日在）
            "retained": [...],    # 留存（今日在池，昨日也在）
            "summary": {
                "new_in_count": 57,
                "left_count": 62,
                "retained_count": 189,
                "total_count": 246
            }
        }
    """
    today_symbols = set(today_df["symbol"])
    yesterday_symbols = set(yesterday_df["symbol"])

    new_in_symbols = today_symbols - yesterday_symbols
    left_symbols = yesterday_symbols - today_symbols
    retained_symbols = today_symbols & yesterday_symbols

    # 标记每只股票的状态
    today_df = today_df.copy()
    today_df["pool_status"] = today_df["symbol"].apply(
        lambda s: "new_in" if s in new_in_symbols
        else "retained"
    )

    result = {
        "date": target_date,
        "baseline_date": yesterday_df["date"].iloc[0] if len(yesterday_df) > 0 else "",
        "new_in": today_df[today_df["symbol"].isin(new_in_symbols)].to_dict("records"),
        "left": yesterday_df[yesterday_df["symbol"].isin(left_symbols)].to_dict("records"),
        "retained": today_df[today_df["symbol"].isin(retained_symbols)].to_dict("records"),
        "summary": {
            "new_in_count": len(new_in_symbols),
            "left_count": len(left_symbols),
            "retained_count": len(retained_symbols),
            "total_count": len(today_symbols)
        }
    }

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--today", required=True, help="今日股票池CSV")
    parser.add_argument("--yesterday", required=True, help="昨日股票池CSV")
    parser.add_argument("--date", required=True, help="目标日期")
    parser.add_argument("--output", required=True, help="输出JSON路径")
    args = parser.parse_args()

    today_df = pd.read_csv(args.today)
    yesterday_df = pd.read_csv(args.yesterday)

    result = classify_stock_pool(today_df, yesterday_df, args.date)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "status": "success",
        **result["summary"]
    }))
```

### 5.3 黑狼数据采集（fetch_heilang.py）

```python
#!/usr/bin/env python3
"""
黑狼数据全量A股日线数据采集
适配黑狼数据API接口，支持分页获取、字段映射、本地缓存
"""

import os
import sys
import time
import json
import argparse
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path


class HeilangDataClient:
    """黑狼数据API客户端"""

    def __init__(self, token: str, base_url: str = "https://api.heilangdata.com"):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

    def _request(self, endpoint: str, params: dict = None, retries: int = 3) -> dict:
        """发送API请求，带重试机制"""
        url = f"{self.base_url}{endpoint}"

        for attempt in range(retries):
            try:
                resp = self.session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                if data.get("code") != 0:
                    raise RuntimeError(f"API错误: {data.get('msg', '未知错误')}")

                return data

            except requests.exceptions.Timeout:
                if attempt < retries - 1:
                    wait = 2 ** attempt  # 指数退避
                    time.sleep(wait)
                    continue
                raise

            except requests.exceptions.HTTPError as e:
                if resp.status_code == 429:  # 限流
                    time.sleep(5)
                    continue
                raise

        raise RuntimeError(f"请求失败，已重试{retries}次")

    def get_daily_kline(
        self,
        trade_date: str,
        page: int = 1,
        page_size: int = 500
    ) -> pd.DataFrame:
        """
        获取指定日期的全量A股日线数据

        Args:
            trade_date: 交易日期 YYYYMMDD
            page: 页码
            page_size: 每页数量(最大500)

        Returns:
            DataFrame with columns: [ts_code, trade_date, open, high, low, close, vol, amount]
        """
        params = {
            "date": trade_date,
            "page": page,
            "page_size": page_size
        }

        data = self._request("/v1/stock/daily", params)
        items = data.get("data", {}).get("items", [])

        if not items:
            return pd.DataFrame()

        # 字段映射: 黑狼API字段 -> 内部标准字段
        field_map = {
            "code": "ts_code",           # 股票代码(带后缀 .SH/.SZ)
            "trade_date": "trade_date",   # 交易日期
            "open": "open",              # 开盘价
            "high": "high",              # 最高价
            "low": "low",                # 最低价
            "close": "close",            # 收盘价
            "volume": "vol",             # 成交量(股)
            "amount": "amount",          # 成交额(元)
            "turnover": "turnover_rate",  # 换手率
            "pct_chg": "pct_change",     # 涨跌幅
        }

        df = pd.DataFrame(items)

        # 重命名字段(只保留存在的)
        rename_cols = {k: v for k, v in field_map.items() if k in df.columns}
        df = df.rename(columns=rename_cols)

        # 确保必要字段存在
        required = ["ts_code", "trade_date", "open", "high", "low", "close", "vol"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"缺少必要字段: {missing}, 实际字段: {list(df.columns)}")

        # 数据类型转换
        numeric_cols = ["open", "high", "low", "close", "vol", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 过滤无效数据
        df = df.dropna(subset=["close", "vol"])
        df = df[df["vol"] > 0]

        return df

    def get_all_stocks(self, trade_date: str, max_pages: int = 20) -> pd.DataFrame:
        """分页获取全量A股数据"""
        all_dfs = []

        for page in range(1, max_pages + 1):
            df = self.get_daily_kline(trade_date, page=page, page_size=500)

            if df.empty:
                break

            all_dfs.append(df)
            print(f"  第{page}页: {len(df)}条记录", file=sys.stderr)

            # 最后一页不足500条说明已取完
            if len(df) < 500:
                break

            # 礼貌限速: 每秒最多2次请求
            time.sleep(0.5)

        if not all_dfs:
            return pd.DataFrame()

        return pd.concat(all_dfs, ignore_index=True)


def fetch_heilang_data(date: str, token: str, output: str) -> dict:
    """主函数: 采集指定日期的全量A股日线数据"""
    cache_path = Path(output)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # 幂等检查: 如果文件已存在且有效，直接返回
    if cache_path.exists():
        existing = pd.read_csv(output)
        if len(existing) >= 5000:  # A股全市场约5000+
            return {
                "status": "cached",
                "date": date,
                "records": len(existing),
                "output": output,
                "message": "使用已缓存数据"
            }

    # API采集
    api_url = os.environ.get("HEILANG_API_URL", "https://api.heilangdata.com")
    client = HeilangDataClient(token=token, base_url=api_url)

    print(f"[Heilang] 开始采集 {date} 全量A股日线数据...", file=sys.stderr)
    start_time = time.time()

    df = client.get_all_stocks(trade_date=date)

    duration = time.time() - start_time
    print(f"[Heilang] 采集完成: {len(df)}条记录, 耗时{duration:.1f}秒", file=sys.stderr)

    if len(df) < 5000:
        raise RuntimeError(f"数据量异常: 仅获取{len(df)}条, A股全市场应≥5000")

    # 保存到CSV
    df.to_csv(output, index=False)

    return {
        "status": "success",
        "date": date,
        "records": len(df),
        "fields": list(df.columns),
        "duration_sec": round(duration, 1),
        "output": output
    }


# ─── 主入口 ─────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="黑狼数据全量A股日线采集")
    parser.add_argument("--date", required=True, help="交易日期 YYYYMMDD")
    parser.add_argument("--output", required=True, help="输出CSV路径")
    parser.add_argument("--token", default=os.environ.get("HEILANG_TOKEN"),
                        help="API Token (默认从环境变量HEILANG_TOKEN读取)")
    args = parser.parse_args()

    if not args.token:
        print("Error: 未提供API Token", file=sys.stderr)
        sys.exit(1)

    try:
        result = fetch_heilang_data(args.date, args.token, args.output)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"status": "failed", "error": str(e)}), file=sys.stdout)
        sys.exit(1)
```

### 5.4 数据校验（validate_data.py）

```python
#!/usr/bin/env python3
"""
数据完整性校验: 检查黑狼数据下载的CSV文件
校验项: 字段完整性、记录数、日期一致性、数值有效性
"""

import os
import sys
import json
import argparse
import pandas as pd
from datetime import datetime


class DataValidator:
    """数据质量校验器"""

    # 必要字段清单
    REQUIRED_FIELDS = ["ts_code", "trade_date", "open", "high", "low", "close", "vol"]

    # A股市场合理范围
    MIN_RECORDS = 5000       # A股全市场至少5000只
    MAX_RECORDS = 5500       # A股全市场最多5500只
    MIN_PRICE = 0.01         # 最低股价
    MAX_PRICE = 10000.0      # 最高股价(考虑茅台等高价股)

    def __init__(self, df: pd.DataFrame, target_date: str):
        self.df = df
        self.target_date = target_date
        self.errors = []
        self.warnings = []

    def validate_fields(self) -> bool:
        """校验字段完整性"""
        missing = [f for f in self.REQUIRED_FIELDS if f not in self.df.columns]
        if missing:
            self.errors.append(f"缺少必要字段: {missing}")
            return False

        # 检查空值比例
        for col in self.REQUIRED_FIELDS:
            null_ratio = self.df[col].isna().sum() / len(self.df)
            if null_ratio > 0.1:  # 空值超过10%
                self.warnings.append(f"字段{col}空值比例{null_ratio:.1%}")

        return True

    def validate_record_count(self) -> bool:
        """校验记录数量"""
        count = len(self.df)

        if count < self.MIN_RECORDS:
            self.errors.append(f"记录数不足: {count} < {self.MIN_RECORDS}")
            return False

        if count > self.MAX_RECORDS:
            self.warnings.append(f"记录数超预期: {count} > {self.MAX_RECORDS}")

        return True

    def validate_date_consistency(self) -> bool:
        """校验日期一致性"""
        if "trade_date" not in self.df.columns:
            return True  # 无日期字段时跳过

        unique_dates = self.df["trade_date"].unique()

        if len(unique_dates) > 1:
            self.warnings.append(f"数据包含多日期: {unique_dates}")

        # 检查是否包含目标日期
        target = self.target_date
        if target not in unique_dates:
            self.errors.append(f"缺少目标日期数据: {target}, 实际日期: {unique_dates}")
            return False

        return True

    def validate_numeric_values(self) -> bool:
        """校验数值有效性"""
        df = self.df

        # 价格范围检查
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                invalid = df[(df[col] < self.MIN_PRICE) | (df[col] > self.MAX_PRICE)]
                if len(invalid) > 0:
                    self.warnings.append(f"{col}有{len(invalid)}条记录价格异常")

        # OHLC逻辑检查
        if all(c in df.columns for c in ["high", "low", "open", "close"]):
            invalid_ohlc = df[
                (df["high"] < df["low"]) |
                (df["open"] > df["high"]) |
                (df["open"] < df["low"]) |
                (df["close"] > df["high"]) |
                (df["close"] < df["low"])
            ]
            if len(invalid_ohlc) > 0:
                self.warnings.append(f"OHLC逻辑异常: {len(invalid_ohlc)}条记录")

        # 成交量检查
        if "vol" in df.columns:
            zero_vol = df[df["vol"] <= 0]
            if len(zero_vol) > 0:
                self.warnings.append(f"成交量为零: {len(zero_vol)}条记录")

        return True

    def run_all(self) -> dict:
        """执行全部校验"""
        checks = [
            self.validate_fields(),
            self.validate_record_count(),
            self.validate_date_consistency(),
            self.validate_numeric_values(),
        ]

        is_valid = all(checks) and len(self.errors) == 0

        return {
            "valid": is_valid,
            "records": len(self.df),
            "fields": list(self.df.columns),
            "errors": self.errors,
            "warnings": self.warnings,
            "summary": f"{'通过' if is_valid else '失败'}: {len(self.df)}条记录, "
                       f"{len(self.errors)}个错误, {len(self.warnings)}个警告"
        }


# ─── 主入口 ─────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="校验黑狼数据CSV文件")
    parser.add_argument("--input", required=True, help="输入CSV文件路径")
    parser.add_argument("--date", required=True, help="目标交易日期 YYYYMMDD")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        result = {"valid": False, "errors": [f"文件不存在: {args.input}"]}
        print(json.dumps(result))
        sys.exit(1)

    df = pd.read_csv(args.input)
    validator = DataValidator(df, args.date)
    result = validator.run_all()

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["valid"] else 1)
```

---

## 6. DynamicTask DAG 配置

### 6.1 DAG YAML 定义

```yaml
# dag_stockpool_daily.yaml
dag:
  name: stockpool_daily_update
  version: "1.0.0"
  description: "三周期E/F共振股票池每日更新流水线"
  schedule: "0 35 15 * * MON-FRI"  # 工作日 15:35 CST
  timezone: "Asia/Shanghai"

  triggerflow:
    lifecycle:
      start:
        timeout: 300
        seal_condition: "nodes.merge_data_sources.status == 'SUCCESS' AND nodes.merge_data_sources.output.record_count >= 5000"
        on_timeout: "RETRY_ONCE_THEN_ESCALATE"
      seal:
        timeout: 600
        close_condition: "nodes.enrich_industry_metrics.status == 'SUCCESS'"
        on_timeout: "USE_FALLBACK_DATA"
      close:
        timeout: 300
        on_timeout: "MARK_PARTIAL_SUCCESS"

    dynamic_planning:
      enabled: true
      decision_model: "default"
      rules:
        - name: "holiday_skip"
          condition: "date.in_holidays('china')"
          action: "SKIP_EXECUTION"
        - name: "half_day_delay"
          condition: "market.is_half_trading_day()"
          action: "DELAY_TRIGGER"
          params: { "to": "13:05" }
        - name: "abnormal_pool_alert"
          condition: "nodes.calculate_ef_states.output.pool_size < 100 OR nodes.calculate_ef_states.output.pool_size > 500"
          action: "PAUSE_AND_ALERT"

  nodes:
    # ─── PHASE: start ──────────────────────────
    fetch_heilang_data:
      action: python_sandbox
      script: actions/fetch_heilang.py
      params:
        - "--date"
        - "{{trigger.date}}"
        - "--output"
        - "/tmp/agently/cache/heilang_{{trigger.date}}.csv"
        - "--token"
        - "{{env.HEILANG_TOKEN}}"
      timeout: 180
      fallback:
        strategy: "USE_CACHE"
        cache_path: "/tmp/agently/cache/heilang_{{trigger.prev_date}}.csv"
        notify: true

    validate_data:
      action: python_sandbox
      script: actions/validate_data.py
      params:
        - "--input"
        - "/tmp/agently/cache/heilang_{{trigger.date}}.csv"
        - "--date"
        - "{{trigger.date}}"
      timeout: 30
      dependencies:
        - fetch_heilang_data
      on_failure: "RETRY"
      max_retries: 2

    merge_data_sources:
      action: python_sandbox
      script: actions/merge_sources.py
      params:
        - "--sources"
        - "/tmp/agently/cache/heilang_{{trigger.date}}.csv"
        - "--output"
        - "/tmp/agently/cache/merged_{{trigger.date}}.csv"
      dependencies:
        - fetch_heilang_data
        - validate_data
      join_strategy: "ALL_COMPLETED"

    # ─── PHASE: seal ───────────────────────────
    calculate_ef_states:
      action: python_sandbox
      script: actions/calculate_ef.py
      params:
        - "--input"
        - "/tmp/agently/cache/merged_{{trigger.date}}.csv"
        - "--info"
        - "data/stock_info.csv"
        - "--output"
        - "/tmp/agently/cache/ef_states_{{trigger.date}}.csv"
        - "--date"
        - "{{trigger.date}}"
      timeout: 300
      dependencies:
        - merge_data_sources
      fallback:
        strategy: "USE_FALLBACK"
        fallback_path: "/tmp/agently/cache/ef_states_{{trigger.prev_date}}.csv"
        notify: true

    classify_stock_pool:
      action: python_sandbox
      script: actions/classify_pool.py
      params:
        - "--today"
        - "/tmp/agently/cache/ef_states_{{trigger.date}}.csv"
        - "--yesterday"
        - "/tmp/agently/cache/ef_states_{{trigger.prev_date}}.csv"
        - "--date"
        - "{{trigger.date}}"
        - "--output"
        - "/tmp/agently/output/classified_{{trigger.date}}.json"
      timeout: 60
      dependencies:
        - calculate_ef_states

    enrich_industry_metrics:
      action: python_sandbox
      script: actions/enrich_metrics.py
      params:
        - "--input"
        - "/tmp/agently/output/classified_{{trigger.date}}.json"
        - "--output"
        - "/tmp/agently/output/stockpool_{{trigger.date}}.json"
        - "--date"
        - "{{trigger.date}}"
      timeout: 60
      dependencies:
        - classify_stock_pool

    # ─── PHASE: close ──────────────────────────
    generate_json_data:
      action: nodejs_sandbox
      script: actions/generate_json.js
      params:
        - "/tmp/agently/output/stockpool_{{trigger.date}}.json"
        - "/tmp/agently/output/api/v1/stockpool/{{trigger.date}}.json"
      timeout: 30
      dependencies:
        - enrich_industry_metrics
      failure_policy: "CONTINUE"  # 失败不影响其他节点

    deploy_static:
      action: bash_sandbox
      script: actions/deploy.sh
      params:
        - "/tmp/agently/output/api/"
        - "cdn:/stockpool/api/"
      timeout: 60
      dependencies:
        - enrich_industry_metrics
      failure_policy: "CONTINUE"

    notify_subscribers:
      action: mcp
      tool: send_email
      params:
        template: "stockpool_daily"
        data_path: "/tmp/agently/output/stockpool_{{trigger.date}}.json"
        recipients: "{{config.subscribers}}"
      timeout: 120
      dependencies:
        - enrich_industry_metrics
      failure_policy: "CONTINUE"

    archive_history:
      action: python_sandbox
      script: actions/archive_history.py
      params:
        - "--input"
        - "/tmp/agently/output/stockpool_{{trigger.date}}.json"
        - "--db"
        - "{{config.history_db_url}}"
        - "--date"
        - "{{trigger.date}}"
      timeout: 30
      dependencies:
        - enrich_industry_metrics
      failure_policy: "CONTINUE"

    cleanup_cache:
      action: bash_sandbox
      script: actions/cleanup.sh
      params:
        - "{{trigger.date}}"
        - "--keep-days"
        - "30"
      dependencies:
        - generate_json_data
        - deploy_static
        - notify_subscribers
        - archive_history
      join_strategy: "ALL_COMPLETED"

  outputs:
    primary: "/tmp/agently/output/stockpool_{{trigger.date}}.json"
    api_endpoint: "https://cdn.example.com/stockpool/api/v1/stockpool/{{trigger.date}}.json"

  notifications:
    on_success:
      channel: "admin_email"
      template: "dag_success_report"
    on_failure:
      channel: "admin_email+wechat"
      template: "dag_failure_alert"
      escalate_after: "15min"
```

### 6.2 运行时状态查询

```python
# 查询DAG执行状态
from agently import Agently

client = Agently()

# 获取今日执行状态
status = client.dags.get_execution_status(
    dag_name="stockpool_daily_update",
    date="20260521"
)

# 返回:
{
    "dag_id": "stockpool_daily_update_20260521",
    "status": "SEAL_PHASE",  # START / SEAL / CLOSE / DONE / FAILED
    "phase": "seal",
    "progress": "75%",
    "nodes": {
        "fetch_heilang_data": {"status": "SUCCESS", "duration": 120, "output_size": "45.2MB"},
        "validate_data": {"status": "SUCCESS", "duration": 8, "records_valid": 5312},
        "merge_data_sources": {"status": "SUCCESS", "duration": 8, "records": 5312},
        "calculate_ef_states": {"status": "RUNNING", "duration": 120, "progress": "85%"},
        "classify_stock_pool": {"status": "PENDING"},
        "enrich_industry_metrics": {"status": "PENDING"},
        "generate_json_data": {"status": "PENDING"},
        "deploy_static": {"status": "PENDING"},
        "notify_subscribers": {"status": "PENDING"},
        "archive_history": {"status": "PENDING"},
        "cleanup_cache": {"status": "PENDING"}
    },
    "start_time": "2026-05-21T15:35:00+08:00",
    "estimated_completion": "2026-05-21T15:42:00+08:00"
}
```

---

## 7. 部署架构

### 7.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Agently Orchestrator                          │
│                         (TriggerFlow + DAG Engine)                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            ┌──────────┐    ┌──────────┐    ┌──────────────┐
            │ Scheduler │    │  DAG     │    │  State Store │
            │ (Cron)   │    │ Engine   │    │  (SQLite/    │
            │          │    │          │    │   PostgreSQL) │
            └──────────┘    └────┬─────┘    └──────────────┘
                                 │
            ┌────────────────────┼────────────────────┐
            ▼                    ▼                    ▼
    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
    │ Python沙盒   │    │ Bash沙盒    │    │ MCP Client   │
    │ (计算核心)   │    │ (部署/清理)  │    │ (通知服务)   │
    └──────┬───────┘    └──────┬───────┘    └──────┬───────┘
           │                   │                   │
           ▼                   ▼                   ▼
    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
    │ 黑狼数据API  │    │ CDN/服务器   │    │ 邮件/微信    │
    │ (付费数据源) │    │              │    │ Webhook      │
    │ 本地缓存     │    │              │    │              │
    └──────────────┘    └──────────────┘    └──────────────┘
```

### 7.2 Docker Compose 部署

```yaml
# docker-compose.yaml
version: "3.8"

services:
  agently-orchestrator:
    image: agentera/agently:4.1.3
    container_name: agently-stockpool
    restart: unless-stopped
    environment:
      - AGENTLY_ENV=production
      - HEILANG_TOKEN=${HEILANG_TOKEN}
      - TZ=Asia/Shanghai
    volumes:
      - ./config:/app/config
      - ./actions:/app/actions
      - ./data:/app/data
      - ./cache:/tmp/agently/cache
      - ./output:/tmp/agently/output
    ports:
      - "8080:8080"
    networks:
      - stockpool-net

  agently-scheduler:
    image: agentera/agently:4.1.3
    container_name: agently-scheduler
    restart: unless-stopped
    command: scheduler
    environment:
      - TZ=Asia/Shanghai
      - ORCHESTRATOR_URL=http://agently-orchestrator:8080
    depends_on:
      - agently-orchestrator
    networks:
      - stockpool-net

  redis:
    image: redis:7-alpine
    container_name: agently-redis
    restart: unless-stopped
    volumes:
      - redis_data:/data
    networks:
      - stockpool-net

  postgres:
    image: postgres:16-alpine
    container_name: agently-db
    restart: unless-stopped
    environment:
      - POSTGRES_USER=agently
      - POSTGRES_PASSWORD=${DB_PASSWORD}
      - POSTGRES_DB=stockpool
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - stockpool-net

volumes:
  redis_data:
  postgres_data:

networks:
  stockpool-net:
    driver: bridge
```

### 7.3 环境变量配置

```bash
# .env
# ─── 数据源 ───
HEILANG_TOKEN=your_heilang_api_token_here
HEILANG_API_URL=https://api.heilangdata.com

# ─── 数据库 ───
DB_PASSWORD=your_secure_password
DB_URL=postgresql://agently:${DB_PASSWORD}@postgres:5432/stockpool

# ─── 通知 ───
SMTP_HOST=smtp.example.com
SMTP_USER=alert@example.com
SMTP_PASS=your_smtp_password
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx

# ─── CDN 部署 ───
CDN_ACCESS_KEY=your_cdn_key
CDN_SECRET=your_cdn_secret
CDN_ENDPOINT=https://cdn.example.com

# ─── Agently ───
AGENTLY_LOG_LEVEL=INFO
AGENTLY_MAX_PARALLEL=4
```

---

## 8. 监控与告警

### 8.1 关键指标

| 指标 | 类型 | 阈值 | 告警级别 |
|------|------|------|---------|
| `dag_execution_duration` | 执行时长 | > 15min | WARNING |
| `pool_size` | 股票池数量 | < 100 or > 500 | CRITICAL |
| `data_fetch_success_rate` | 采集成功率 | < 100% | WARNING |
| `ef_calculation_coverage` | 计算覆盖率 | < 95% | CRITICAL |
| `notification_delivery_rate` | 通知送达率 | < 98% | WARNING |

### 8.2 告警规则

```yaml
# alerts.yaml
alerts:
  - name: "dag_execution_slow"
    condition: "dag_execution_duration > 900"
    severity: warning
    channels: ["email"]
    message: "股票池更新执行缓慢，当前已运行 {{duration}} 秒"

  - name: "pool_size_abnormal"
    condition: "pool_size < 100 OR pool_size > 500"
    severity: critical
    channels: ["email", "wechat"]
    message: "股票池数量异常: {{pool_size}}，需人工确认"
    auto_resolve: false  # 需人工确认

  - name: "heilang_api_failure"
    condition: "heilang_status == FAILED"
    severity: critical
    channels: ["email", "wechat", "sms"]
    message: "黑狼数据API调用失败，已切换至昨日缓存"
    escalate_after: "5min"

  - name: "holiday_execution"
    condition: "date.in_holidays AND dag_status == RUNNING"
    severity: info
    channels: ["email"]
    message: "节假日执行检测，DAG已自动跳过"
```

---

## 9. 实施计划

| 阶段 | 周期 | 工作内容 | 交付物 |
|------|------|---------|--------|
| **Phase 0** | 3天 | 环境准备、Docker部署、Action配置 | 运行环境、测试流水线 |
| **Phase 1** | 5天 | 数据采集Action开发（黑狼数据API） | fetch_heilang.py、validate_data.py |
| **Phase 2** | 7天 | E/F计算核心开发（calculate_ef.py） | 计算脚本、单元测试、回测验证 |
| **Phase 3** | 3天 | 股票池分类+行业统计（classify+enrich） | classify_pool.py、enrich_metrics.py |
| **Phase 4** | 3天 | 发布层开发（JSON生成+CDN部署+通知） | generate_json.js、deploy.sh |
| **Phase 5** | 3天 | DAG配置、TriggerFlow生命周期调试 | dag_stockpool_daily.yaml |
| **Phase 6** | 5天 | 联调测试、灰度运行、监控配置 | 完整流水线、监控面板 |
| **Phase 7** |  ongoing | 生产运行、动态策略调优 | 持续优化 |

**总计**: 约29天（4周）完成从开发到生产上线

---

## 10. 与 Agently Skills 的集成展望

当 **SkillsExecutor** 发布后，可将整个股票池服务封装为可复用的 Skill：

```yaml
# Skill 定义（未来）
skill:
  name: stockpool-resonance-service
  version: "1.0.0"
  description: "三周期E/F共振股票池每日更新服务"
  author: "your-team"

  actions:
    - ref: python_sandbox
      id: ef_calculator
    - ref: bash_sandbox
      id: deploy_tool
    - ref: mcp
      id: notification_service

  dag: dag_stockpool_daily.yaml

  triggers:
    - type: cron
      value: "0 35 15 * * MON-FRI"
    - type: manual

  exports:
    - name: "get_stockpool"
      type: api
      endpoint: "/api/v1/stockpool/{date}"
    - name: "get_changes"
      type: api
      endpoint: "/api/v1/stockpool/{date}/changes"
    - name: "get_industry_distribution"
      type: api
      endpoint: "/api/v1/stockpool/{date}/industries"
```

安装方式：
```bash
# 任何 Agently Agent 均可通过 Skills 获得股票池能力
agently skills install stockpool-resonance-service

# Agent 自动获得的能力:
# - "查询今日股票池" → 调用 get_stockpool
# - "看看今天有哪些新进入的股票" → 调用 get_changes
# - "电子行业有多少只在池子里" → 调用 get_industry_distribution
```

---

> **文档版本**: v1.0  
> **适配 Agently**: 4.1.1+ (Actions) / 4.1.2+ (TriggerFlow) / 4.1.3+ (DynamicTask DAG)  
> **下一步**: Phase 0 环境准备 → Phase 1 数据采集Action开发
