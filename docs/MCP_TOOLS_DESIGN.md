# MCP 工具接口设计

版本：v1.0
日期：2026-05-23
状态：设计稿
参考：Vibe-Trading MCP 实现（22 个 stdio 工具）

---

## 概述

将 Hermass 的核心查询能力封装为 MCP（Model Context Protocol）工具，让用户可以在 Claude Desktop / Cursor / OpenClaw 中直接用自然语言查询系统结果。

**设计原则**：只读查询，不暴露写入操作。所有工具返回 JSON，不返回 HTML。

---

## 1. 工具清单

| 工具名 | 功能 | 数据源 |
|--------|------|--------|
| `get_market_phase` | 获取当日市场阶段 | outputs/market_phase/ |
| `get_triple_resonance` | 获取三重共振信号 | strategy_signal_daily + macro + chain |
| `get_top_signals` | 获取最佳适配信号列表 | strategy_signal_daily |
| `get_state_snapshot` | 获取个股 State 快照 | p116_foundation.duckdb |
| `get_calibration_status` | 获取校准状态 | outputs/calibration/ |

---

## 2. 工具定义

### 2.1 get_market_phase

```json
{
  "name": "get_market_phase",
  "description": "获取指定日期的市场阶段判定结果。返回当前阶段（收缩/新生/行进/延展/风险释放）、判定指标和策略适配映射。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "date": {
        "type": "string",
        "description": "交易日期，格式 YYYY-MM-DD。省略则取最新可用日期。",
        "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
      }
    }
  }
}
```

**输出 Schema**：

```json
{
  "date": "2026-05-22",
  "market_phase": "progression",
  "phase_label": "趋势行进",
  "phase_summary": "趋势稳定运行，全三 E/F 池规模平稳，波动率处于舒适区间。",
  "confidence": 0.82,
  "indicators": {
    "pool_size": 216,
    "pool_change_rate_5d": 0.05,
    "volatility_ratio": 0.32,
    "industry_dispersion": 0.15,
    "contraction_release_density": 0.02
  },
  "strategy_implications": {
    "vcp": {"fit": "适配", "factor": 1.00},
    "ma2560": {"fit": "最佳适配", "factor": 1.10},
    "bollinger_bandit": {"fit": "适配", "factor": 1.00}
  },
  "phase_history": {
    "current_phase_days": 12,
    "previous_phase": "emergence"
  }
}
```

**错误处理**：

```json
{"error": "date_not_found", "message": "2026-05-25 非交易日或数据未生成"}
{"error": "data_not_ready", "message": "market_phase 数据尚未生成，请等待收盘后流水线完成"}
```

### 2.2 get_triple_resonance

```json
{
  "name": "get_triple_resonance",
  "description": "获取指定日期的三重共振信号列表。返回宏观-产业链-State 三维度均利好的信号，以及多重冲突的信号。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "date": {
        "type": "string",
        "description": "交易日期，省略取最新。"
      },
      "resonance_level": {
        "type": "string",
        "enum": ["triple", "double", "single", "mixed", "conflict", "all"],
        "description": "筛选共振等级，默认 triple。"
      },
      "strategy_id": {
        "type": "string",
        "enum": ["vcp", "ma2560", "bollinger_bandit", "all"],
        "description": "筛选策略，默认 all。"
      },
      "limit": {
        "type": "integer",
        "description": "返回条数上限，默认 20。",
        "default": 20
      }
    }
  }
}
```

**输出 Schema**：

```json
{
  "date": "2026-05-22",
  "resonance_level": "triple",
  "total": 5,
  "signals": [
    {
      "stock_code": "002049.SZ",
      "stock_name": "紫光国微",
      "strategy_id": "vcp",
      "signal_name": "VCP突破确认",
      "base_fit_score": 83.75,
      "enhanced_fit_score": 100.0,
      "resonance": {
        "macro_direction": "positive",
        "macro_quadrant": "复苏",
        "chain_direction": "positive",
        "chain_prosperity": 8.2,
        "state_direction": "positive",
        "lifecycle_stage": "新生"
      },
      "total_factor": 1.251
    }
  ]
}
```

### 2.3 get_top_signals

```json
{
  "name": "get_top_signals",
  "description": "获取指定日期的最佳适配信号列表，按共振等级和适配度排序。这是系统每日最核心的输出。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "date": {
        "type": "string",
        "description": "交易日期，省略取最新。"
      },
      "strategy_id": {
        "type": "string",
        "enum": ["vcp", "ma2560", "bollinger_bandit", "all"],
        "default": "all"
      },
      "fit_level": {
        "type": "string",
        "enum": ["最佳适配", "适配", "all"],
        "default": "最佳适配",
        "description": "筛选适配度等级。"
      },
      "sw_l1": {
        "type": "string",
        "description": "筛选行业（申万一级），如 '电子'。"
      },
      "limit": {
        "type": "integer",
        "default": 20
      }
    }
  }
}
```

**输出 Schema**：

```json
{
  "date": "2026-05-22",
  "filters": {"strategy_id": "all", "fit_level": "最佳适配"},
  "total_available": 69,
  "displayed": 20,
  "signals": [
    {
      "stock_code": "300969.SZ",
      "stock_name": "恒帅股份",
      "sw_l1": "汽车",
      "strategy_id": "vcp",
      "signal_name": "VCP突破确认",
      "lifecycle_stage": "新生",
      "fit_level": "最佳适配",
      "state_combo": "E/E/E",
      "ef_count": 3,
      "market_match_level": "not_match",
      "environment_tags": ["波动稳定", "D1收缩充分", "三周期共振新近形成"],
      "local_stats": {
        "hypothesis": "D1近20日收缩后释放",
        "mean_excess_20d": 0.0469,
        "sample_count": 43259
      },
      "main_business": "车用微电机及清洗系统"
    }
  ]
}
```

### 2.4 get_state_snapshot

```json
{
  "name": "get_state_snapshot",
  "description": "获取指定股票的三周期 State 快照。返回 MN1/W1/D1 的状态码、各分量和 SR 关键位。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "stock_code": {
        "type": "string",
        "description": "股票代码，如 '002049.SZ' 或 '002049'。"
      },
      "date": {
        "type": "string",
        "description": "交易日期，省略取最新。"
      }
    },
    "required": ["stock_code"]
  }
}
```

**输出 Schema**：

```json
{
  "stock_code": "002049.SZ",
  "stock_name": "紫光国微",
  "date": "2026-05-22",
  "d1_close": 85.30,
  "mn1": {
    "state_hex": "E",
    "state_score": 14,
    "base": 8, "trend_bit": 1, "position_bit": 2, "volatility_bit": 0,
    "comp_label": "扩", "trend_label": "牛", "position_label": "上突", "volatility_label": "稳",
    "sr_support": 72.5, "sr_resistance": 80.0
  },
  "w1": {
    "state_hex": "E",
    "state_score": 14,
    "base": 8, "trend_bit": 1, "position_bit": 2, "volatility_bit": 0,
    "comp_label": "扩", "trend_label": "牛", "position_label": "上突", "volatility_label": "稳",
    "sr_support": 78.0, "sr_resistance": 82.0
  },
  "d1": {
    "state_hex": "E",
    "state_score": 14,
    "base": 8, "trend_bit": 1, "position_bit": 2, "volatility_bit": 0,
    "comp_label": "扩", "trend_label": "牛", "position_label": "上突", "volatility_label": "稳",
    "sr_support": 80.0, "sr_resistance": 84.0
  },
  "ef_count": 3,
  "state_score_sum": 42,
  "d1_ef_duration": 5,
  "all_three_ef_duration": 2
}
```

### 2.5 get_calibration_status

```json
{
  "name": "get_calibration_status",
  "description": "获取系统校准状态。返回各策略的校准进度、适配度排序有效性、最近一次校准结果。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "strategy_id": {
        "type": "string",
        "enum": ["vcp", "ma2560", "bollinger_bandit", "all"],
        "default": "all"
      }
    }
  }
}
```

**输出 Schema**：

```json
{
  "overall_status": "accumulating",
  "strategies": {
    "vcp": {
      "status": "accumulating",
      "labeled_samples": 2100,
      "target_samples": 3000,
      "progress_pct": 70,
      "latest_calibration": null,
      "days_until_estimate": 45
    },
    "ma2560": {
      "status": "accumulating",
      "labeled_samples": 1800,
      "target_samples": 3000,
      "progress_pct": 60,
      "latest_calibration": null,
      "days_until_estimate": 60
    },
    "bollinger_bandit": {
      "status": "accumulating",
      "labeled_samples": 1500,
      "target_samples": 2400,
      "progress_pct": 62.5,
      "latest_calibration": null,
      "days_until_estimate": 55
    }
  },
  "message": "前向观察样本积累中。预计 2026-Q4 至 2027-Q1 完成首批校准。"
}
```

---

## 3. MCP 传输协议

### 3.1 stdio 传输

参考 Vibe-Trading 的 stdio 模式：

```python
# scripts/mcp_server.py

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TOOLS = [
    {"name": "get_market_phase", "description": "...", "inputSchema": {...}},
    {"name": "get_triple_resonance", "description": "...", "inputSchema": {...}},
    {"name": "get_top_signals", "description": "...", "inputSchema": {...}},
    {"name": "get_state_snapshot", "description": "...", "inputSchema": {...}},
    {"name": "get_calibration_status", "description": "...", "inputSchema": {...}},
]

def handle_request(request: dict) -> dict:
    method = request.get("method")

    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "hermass-observer", "version": "1.0"}}

    if method == "tools/list":
        return {"tools": TOOLS}

    if method == "tools/call":
        tool_name = request["params"]["name"]
        arguments = request["params"].get("arguments", {})
        result = dispatch_tool(tool_name, arguments)
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

    return {"error": {"code": -32601, "message": f"Unknown method: {method}"}}

def dispatch_tool(name: str, args: dict) -> dict:
    if name == "get_market_phase":
        return get_market_phase(args)
    elif name == "get_triple_resonance":
        return get_triple_resonance(args)
    # ... 其他工具
    return {"error": "unknown_tool"}

def main():
    for line in sys.stdin:
        request = json.loads(line)
        response = {"jsonrpc": "2.0", "id": request.get("id")}
        try:
            result = handle_request(request)
            response["result"] = result
        except Exception as e:
            response["error"] = {"code": -32000, "message": str(e)}
        print(json.dumps(response), flush=True)

if __name__ == "__main__":
    main()
```

### 3.2 Claude Desktop 配置

```json
{
  "mcpServers": {
    "hermass-observer": {
      "command": "python3",
      "args": ["/Users/lv111101/Documents/hermass-observer-product/scripts/mcp_server.py"],
      "cwd": "/Users/lv111101/Documents/hermass-observer-product"
    }
  }
}
```

### 3.3 用户查询示例

```
用户：当前市场处于什么阶段？
Claude：调用 get_market_phase → 返回 progression（趋势行进）

用户：今天有哪些三重共振的信号？
Claude：调用 get_triple_resonance(resonance_level="triple") → 返回 5 条信号

用户：电子行业有什么好信号？
Claude：调用 get_top_signals(sw_l1="电子", fit_level="最佳适配") → 返回电子行业 Top 信号

用户：紫光国微的 State 是什么？
Claude：调用 get_state_snapshot(stock_code="002049.SZ") → 返回 E/E/E 三周期共振

用户：系统校准到什么程度了？
Claude：调用 get_calibration_status → 返回各策略积累进度
```

---

## 4. 安全边界

| 规则 | 说明 |
|------|------|
| 只读 | 所有工具只返回查询结果，不修改任何数据 |
| 无交易建议 | 输出不含买入/卖出/加仓等词汇 |
| 数据标注 | 所有输出包含 `research_only: true` |
| 无敏感信息 | 不暴露 API key、文件路径的绝对路径（使用相对路径） |
| 速率限制 | 每分钟最多 30 次调用（防止刷数据） |

---

## 5. 实施路径

| 阶段 | 任务 | 工作量 |
|------|------|--------|
| 1 | 实现 `scripts/mcp_server.py` 框架（stdio + JSON-RPC） | 2 天 |
| 2 | 实现 5 个工具的数据读取函数 | 2 天 |
| 3 | Claude Desktop 配置 + 端到端测试 | 1 天 |
| 4 | 文档 + 用户指引 | 半天 |
