#!/usr/bin/env python3
"""MCP server exposing Hermass strategy query tools.

Transport: stdio (Model Context Protocol)
Scope: read-only query. No strategy rules can be modified through these tools.

Three tools:
  1. get_backtest_result    — full backtest via simulate_historical_trading.run_simulation()
  2. get_today_top_signals  — today's best-fit signals from daily research brief + reminders
  3. get_position_monitor   — current simulated positions and recent triggers

Each tool delegates to the existing complete engine without simplification.
"""

from __future__ import annotations

import asyncio
import csv
import functools
import json
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Ensure project imports work ────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
scripts_dir = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Import existing engines (full engine, no simplification)
from simulate_historical_trading import (
    run_simulation as _run_simulation_engine,
    compute_performance as _compute_performance_engine,
)

# ═══════════════════════════════════════════════════════════════════════
# Constants & version metadata
# ═══════════════════════════════════════════════════════════════════════

STRATEGY_DOCS = {
    "execution_spec": "docs/STRATEGY_EXECUTION_SPEC.md",
    "definitions": "docs/STRATEGY_DEFINITIONS.md",
    "execution_detail": "docs/STRATEGY_EXECUTION_2560_BOLLINGER_DETAIL.md",
    "ma2560_rules": "docs/MA2560_STATE_MARKET_MATCH_RULE.md",
    "collaboration": "docs/STRATEGY_COLLABORATION_GUIDE.md",
}

OUTPUTS_DIR = ROOT / "outputs"
SIM_DIR = OUTPUTS_DIR / "simulation"
BRIEF_PATH = OUTPUTS_DIR / "daily_research_brief" / "daily_research_brief_latest.json"
REMINDER_PATH = OUTPUTS_DIR / "strategy_reminders" / "reminder_latest.json"
FINAL_POSITIONS_PATH = SIM_DIR / "final_positions.json"
TRADE_LOG_PATH = SIM_DIR / "trade_log.csv"
PERFORMANCE_MD_PATH = SIM_DIR / "performance_summary.md"

_READ_ONLY_NOTICE = "【只读声明】本工具仅提供策略查询，不可修改策略规则、信号参数或执行任何写入操作。"


# Simple in-memory LRU cache for backtest results: key -> result
def _make_cache_key(start: str, end: str, capital: float) -> str:
    return f"{start}|{end}|{capital}"


_BACKTEST_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_MAX_CACHE_SIZE = 4


def _strategy_rule_version() -> str:
    """Derive version from latest daily research brief date."""
    try:
        payload = json.loads(BRIEF_PATH.read_text(encoding="utf-8"))
        return payload.get("date", "unknown")
    except Exception:
        return "unknown"


def _docs_paths() -> dict[str, str]:
    """Return absolute paths to strategy documentation."""
    return {k: str(ROOT / v) for k, v in STRATEGY_DOCS.items()}


def _base_meta() -> dict[str, Any]:
    """Common metadata appended to every tool response."""
    return {
        "strategy_rule_version": _strategy_rule_version(),
        "docs_paths": _docs_paths(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only_disclaimer": _READ_ONLY_NOTICE,
    }


# ═══════════════════════════════════════════════════════════════════════
# Tool 1: get_backtest_result
# ═══════════════════════════════════════════════════════════════════════

GET_BACKTEST_RESULT_TOOL = Tool(
    name="get_backtest_result",
    description=(
        "运行完整策略回测引擎，返回标准化绩效报告。"
        "底层直接调用 simulate_historical_trading.run_simulation() 不做任何简化。"
        "注意：回测可能需要数十秒到数分钟，取决于区间长度。"
        f" {_READ_ONLY_NOTICE}"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "strategy": {
                "type": "string",
                "description": "策略过滤: all | vcp | ma2560 | bollinger_bandit",
                "enum": ["all", "vcp", "ma2560", "bollinger_bandit"],
                "default": "all",
            },
            "start_date": {
                "type": "string",
                "description": "回测开始日期 (YYYY-MM-DD)",
                "default": "2025-05-22",
            },
            "end_date": {
                "type": "string",
                "description": "回测结束日期 (YYYY-MM-DD)",
                "default": "2026-05-22",
            },
            "capital": {
                "type": "number",
                "description": "初始资金（默认 1,000,000）",
                "default": 1_000_000,
            },
        },
    },
)


async def _do_backtest(
    strategy: str,
    start_date: str,
    end_date: str,
    capital: float,
) -> dict[str, Any]:
    """Execute the full backtest engine in a thread pool.

    stdout is suppressed during engine execution to avoid corrupting
    MCP stdio JSON-RPC messages.
    """
    cache_key = _make_cache_key(start_date, end_date, capital)
    if cache_key in _BACKTEST_CACHE:
        raw = _BACKTEST_CACHE[cache_key]
    else:
        loop = asyncio.get_running_loop()

        def _run_with_redirect():
            import os

            sys.stdout.flush()
            old_stdout_fd = os.dup(1)
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, 1)
            os.close(devnull)
            sys.stdout.flush()
            try:
                return _run_simulation_engine(start_date, end_date, capital)
            finally:
                sys.stdout.flush()
                os.dup2(old_stdout_fd, 1)
                os.close(old_stdout_fd)

        raw = await loop.run_in_executor(None, _run_with_redirect)
        _BACKTEST_CACHE[cache_key] = raw
        if len(_BACKTEST_CACHE) > _MAX_CACHE_SIZE:
            _BACKTEST_CACHE.popitem(last=False)

    # Compute performance (full engine helper)
    perf = _compute_performance_engine(raw["equity_curve"], raw["trades"], capital)
    perf["start_date"] = start_date
    perf["end_date"] = end_date
    perf["capital"] = capital

    # Strategy filter
    trades = raw["trades"]
    if strategy != "all":
        trades = [t for t in trades if t.strategy == strategy]

    # Recompute per-strategy performance if filtered
    if strategy != "all":
        winning = [t for t in trades if t.net_pnl > 0]
        losing = [t for t in trades if t.net_pnl <= 0]
        win_rate = len(winning) / len(trades) * 100.0 if trades else 0.0
        avg_win = sum(t.return_pct for t in winning) / len(winning) if winning else 0.0
        avg_loss = sum(t.return_pct for t in losing) / len(losing) if losing else 0.0
        payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
        avg_hold = sum(t.hold_days for t in trades) / len(trades) if trades else 0.0
        perf.update(
            {
                "total_trades": len(trades),
                "winning_trades": len(winning),
                "losing_trades": len(losing),
                "win_rate_pct": round(win_rate, 2),
                "payoff_ratio": round(payoff_ratio, 2),
                "avg_return_pct": round(sum(t.return_pct for t in trades) / len(trades), 2)
                if trades
                else 0.0,
                "avg_win_pct": round(avg_win, 2),
                "avg_loss_pct": round(avg_loss, 2),
                "avg_hold_days": round(avg_hold, 1),
                "total_net_pnl": round(sum(t.net_pnl for t in trades), 2),
                "total_commission": round(sum(t.commission for t in trades), 2),
                "total_stamp_tax": round(sum(t.stamp_tax for t in trades), 2),
            }
        )

    # Serialize trades
    trade_rows = [
        {
            "stock_code": t.stock_code,
            "stock_name": t.stock_name,
            "strategy": t.strategy,
            "industry": t.industry,
            "entry_date": t.entry_date,
            "entry_price": t.entry_price,
            "exit_date": t.exit_date,
            "exit_price": t.exit_price,
            "shares": t.shares,
            "hold_days": t.hold_days,
            "exit_reason": t.exit_reason,
            "net_pnl": t.net_pnl,
            "return_pct": t.return_pct,
        }
        for t in trades
    ]

    # Final positions (strategy-filtered)
    final_positions = raw["final_positions"]
    if strategy != "all":
        final_positions = {k: v for k, v in final_positions.items() if v.strategy == strategy}

    pos_rows = [
        {
            "stock_code": p.stock_code,
            "stock_name": p.stock_name,
            "strategy": p.strategy,
            "industry": p.industry,
            "entry_date": p.entry_date,
            "entry_price": p.entry_price,
            "shares": p.shares,
            "stop_price": p.stop_price,
            "highest_price": p.highest_price,
        }
        for p in final_positions.values()
    ]

    return {
        "performance": perf,
        "trades": trade_rows,
        "final_positions": pos_rows,
        "strategy_filter": strategy,
    }


# ═══════════════════════════════════════════════════════════════════════
# Tool 2: get_today_top_signals
# ═══════════════════════════════════════════════════════════════════════

GET_TODAY_TOP_SIGNALS_TOOL = Tool(
    name="get_today_top_signals",
    description=(
        "查询今日最佳适配信号列表。"
        "底层读取每日研究简报和策略提醒的完整引擎输出，不做任何简化。"
        f" {_READ_ONLY_NOTICE}"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "fit_level": {
                "type": "string",
                "description": "适配等级过滤（可选）",
                "enum": ["", "最佳适配", "适配", "弱适配", "待观察"],
                "default": "",
            },
            "strategy": {
                "type": "string",
                "description": "策略过滤（可选）",
                "enum": ["", "vcp", "ma2560", "bollinger_bandit"],
                "default": "",
            },
            "limit": {
                "type": "integer",
                "description": "返回条数上限（默认 10）",
                "default": 10,
                "minimum": 1,
                "maximum": 50,
            },
        },
    },
)


def _do_top_signals(
    fit_level: str,
    strategy: str,
    limit: int,
) -> dict[str, Any]:
    """Read today's signals from the full engine outputs."""
    reminders: list[dict[str, Any]] = []
    brief_date = "unknown"
    try:
        payload = json.loads(REMINDER_PATH.read_text(encoding="utf-8"))
        reminders = payload.get("reminders", [])
        brief_date = payload.get("date", "unknown")
    except Exception as exc:
        return {
            "error": f"无法读取提醒数据: {exc}",
            "signals": [],
            "date": brief_date,
        }

    # Filter
    filtered = reminders
    if fit_level:
        filtered = [r for r in filtered if r.get("strategy_environment_fit") == fit_level]
    if strategy:
        filtered = [r for r in filtered if r.get("strategy", {}).get("strategy_id") == strategy]

    # Sort by signal_strength desc, then by reward_risk rr_ratio desc
    def _sort_key(r: dict[str, Any]) -> tuple[float, float]:
        sig = r.get("strategy", {})
        strength = sig.get("signal_strength", 0.0) or 0.0
        rr = r.get("reward_risk", {})
        rr_ratio = rr.get("rr_ratio", 0.0) or 0.0
        return (-strength, -rr_ratio)

    filtered.sort(key=_sort_key)

    # Build output rows
    rows: list[dict[str, Any]] = []
    for r in filtered[:limit]:
        sig = r.get("strategy", {})
        rr = r.get("reward_risk", {})
        state_env = r.get("state_environment", {})
        macro = r.get("macro_chain_prior", {})
        industry_prior = macro.get("industry_prior", {}) if isinstance(macro, dict) else {}

        rows.append(
            {
                "stock_code": r.get("stock_code"),
                "stock_name": r.get("stock_name"),
                "strategy": sig.get("strategy_id"),
                "signal_name": sig.get("signal_name"),
                "signal_strength": sig.get("signal_strength"),
                "fit_level": r.get("strategy_environment_fit"),
                "fit_reasons": r.get("fit_reasons"),
                "lifecycle_stage": r.get("lifecycle_stage"),
                "state_combo": state_env.get("state_combo"),
                "ef_count": state_env.get("ef_count"),
                "rr_ratio": rr.get("rr_ratio"),
                "upside_pct": rr.get("upside_pct"),
                "downside_pct": rr.get("downside_pct"),
                "high_value": rr.get("high_value"),
                "industry": r.get("ifind", {}).get("industry", {}).get("sw_l1"),
                "industry_prior_score": industry_prior.get("chain_prior_score")
                if isinstance(industry_prior, dict)
                else None,
                "calibration_status": r.get("calibration", {}).get("status"),
                "research_only": r.get("research_only"),
            }
        )

    # Summary stats
    summary = {
        "total_reminders": len(reminders),
        "filtered_count": len(filtered),
        "returned_count": len(rows),
        "date": brief_date,
        "strategy_distribution": {},
        "fit_distribution": {},
    }
    for r in reminders:
        sid = r.get("strategy", {}).get("strategy_id", "unknown")
        summary["strategy_distribution"][sid] = summary["strategy_distribution"].get(sid, 0) + 1
        fit = r.get("strategy_environment_fit", "unknown")
        summary["fit_distribution"][fit] = summary["fit_distribution"].get(fit, 0) + 1

    return {
        "summary": summary,
        "signals": rows,
        "filters_applied": {
            "fit_level": fit_level or None,
            "strategy": strategy or None,
            "limit": limit,
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# Tool 3: get_position_monitor
# ═══════════════════════════════════════════════════════════════════════

GET_POSITION_MONITOR_TOOL = Tool(
    name="get_position_monitor",
    description=(
        "监控当前模拟持仓状态及触发情况。"
        "底层读取完整模拟引擎输出的持仓和交易记录，不做任何简化。"
        f" {_READ_ONLY_NOTICE}"
    ),
    inputSchema={
        "type": "object",
        "properties": {},
    },
)


def _do_position_monitor() -> dict[str, Any]:
    """Read current positions and recent trades from simulation outputs."""
    positions: dict[str, Any] = {}
    try:
        positions = json.loads(FINAL_POSITIONS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        positions = {"_error": f"无法读取持仓数据: {exc}"}

    # Read recent trades (last 20)
    recent_trades: list[dict[str, Any]] = []
    try:
        with open(TRADE_LOG_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            all_trades = list(reader)
            recent_trades = all_trades[-20:] if len(all_trades) > 20 else all_trades
            # Reverse so newest first
            recent_trades = list(reversed(recent_trades))
    except Exception as exc:
        recent_trades = [{"_error": f"无法读取交易记录: {exc}"}]

    # Read performance summary if available
    perf_summary: dict[str, Any] = {}
    try:
        md_text = PERFORMANCE_MD_PATH.read_text(encoding="utf-8")
        # Quick parse of key metrics from markdown
        for line in md_text.splitlines():
            if "总收益率" in line and "+" in line:
                perf_summary["total_return_pct"] = line.split("+")[1].replace("%", "").strip()
            elif "最大回撤" in line:
                perf_summary["max_drawdown_pct"] = line.split("%")[0].split()[-1].strip()
            elif "夏普比率" in line:
                perf_summary["sharpe_ratio"] = line.split()[-1].strip()
            elif "总交易笔数" in line:
                perf_summary["total_trades"] = line.split()[-1].strip()
            elif "胜率" in line and "%" in line:
                perf_summary["win_rate_pct"] = line.split("%")[0].split()[-1].strip()
            elif "最终资金" in line:
                perf_summary["final_assets"] = line.split("¥")[1].replace(",", "").strip()
    except Exception:
        pass

    # Position summary by strategy
    pos_list = []
    if isinstance(positions, dict) and "_error" not in positions:
        for code, p in positions.items():
            pos_list.append(
                {
                    "stock_code": p.get("stock_code", code),
                    "stock_name": p.get("stock_name", ""),
                    "strategy": p.get("strategy", "unknown"),
                    "industry": p.get("industry", "unknown"),
                    "entry_date": p.get("entry_date", ""),
                    "entry_price": p.get("entry_price", 0.0),
                    "shares": p.get("shares", 0),
                    "stop_price": p.get("stop_price", 0.0),
                    "highest_price": p.get("highest_price", 0.0),
                }
            )

    strategy_summary: dict[str, dict[str, Any]] = {}
    for p in pos_list:
        sid = p["strategy"]
        if sid not in strategy_summary:
            strategy_summary[sid] = {"count": 0, "total_shares": 0, "positions": []}
        strategy_summary[sid]["count"] += 1
        strategy_summary[sid]["total_shares"] += p["shares"]
        strategy_summary[sid]["positions"].append(p)

    return {
        "active_positions": pos_list,
        "position_count": len(pos_list),
        "strategy_summary": strategy_summary,
        "recent_trades": recent_trades,
        "performance_summary": perf_summary,
        "data_source": {
            "final_positions_path": str(FINAL_POSITIONS_PATH),
            "trade_log_path": str(TRADE_LOG_PATH),
            "performance_md_path": str(PERFORMANCE_MD_PATH),
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# MCP Server setup
# ═══════════════════════════════════════════════════════════════════════

server = Server("hermass-strategy-query-server")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        GET_BACKTEST_RESULT_TOOL,
        GET_TODAY_TOP_SIGNALS_TOOL,
        GET_POSITION_MONITOR_TOOL,
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    result: dict[str, Any]

    if name == "get_backtest_result":
        strategy = arguments.get("strategy", "all")
        start_date = arguments.get("start_date", "2025-05-22")
        end_date = arguments.get("end_date", "2026-05-22")
        capital = float(arguments.get("capital", 1_000_000))

        try:
            result = await _do_backtest(strategy, start_date, end_date, capital)
        except Exception as exc:
            result = {"error": str(exc), "traceback": str(sys.exc_info()[2])}

    elif name == "get_today_top_signals":
        fit_level = arguments.get("fit_level", "")
        strategy = arguments.get("strategy", "")
        limit = int(arguments.get("limit", 10))

        try:
            result = _do_top_signals(fit_level, strategy, limit)
        except Exception as exc:
            result = {"error": str(exc), "traceback": str(sys.exc_info()[2])}

    elif name == "get_position_monitor":
        try:
            result = _do_position_monitor()
        except Exception as exc:
            result = {"error": str(exc), "traceback": str(sys.exc_info()[2])}

    else:
        result = {"error": f"Unknown tool: {name}"}

    # Attach common metadata
    result["_meta"] = _base_meta()

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
