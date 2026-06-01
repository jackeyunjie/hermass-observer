#!/usr/bin/env python3
"""Generate a strategy signal outcome report.

The report answers a narrow question:
for the stocks shown in a daily reminder brief, what happened afterwards under
the approved strategy observation rules?

This is not an order simulator. It uses signal-date close as the reference
price, reports follow-through returns, and only reports rule exits for
strategies that already have an implemented exit rule in code.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.engine import load_state_data_from_duckdb
from backtest.strategy_signals.bollinger_bandit import bollinger_bandit_exit_signal, exit_ma_period
from backtest.strategy_signals.ma2560 import ma2560_signal
from backtest.strategy_signals.vcp_management import vcp_management_observation


OUTPUT_DIR = ROOT / "outputs" / "strategy_outcome_report"
PUBLIC_DIR = ROOT / "public"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def pct(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def code6(value: Any) -> str:
    text = str(value or "").upper().strip()
    digits = "".join(ch for ch in text.split(".", 1)[0] if ch.isdigit())
    return digits[-6:] if digits else text


def load_json(path: Path, required: bool = False) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def default_foundation_db(as_of_date: str) -> Path:
    exact = ROOT / "outputs" / f"p116_foundation_{ymd(as_of_date)}" / "p116_foundation.duckdb"
    if exact.exists():
        return exact
    candidates = sorted(ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"))
    if not candidates:
        raise FileNotFoundError("No foundation DB found under outputs/")
    return candidates[-1]


def load_reminder_rows(signal_date: str) -> list[dict[str, Any]]:
    path = ROOT / "outputs" / "strategy_reminders" / f"reminder_{ymd(signal_date)}.json"
    payload = load_json(path, required=True)
    rows = payload.get("reminders", []) or []
    return rows


def available_reminder_dates(start_date: str, end_date: str) -> list[str]:
    out: list[str] = []
    for path in sorted((ROOT / "outputs" / "strategy_reminders").glob("reminder_????????.json")):
        date_str = f"{path.stem[-8:-4]}-{path.stem[-4:-2]}-{path.stem[-2:]}"
        if start_date <= date_str <= end_date:
            out.append(date_str)
    return out


def strategy_id(row: dict[str, Any]) -> str:
    strategy = row.get("strategy")
    if isinstance(strategy, dict):
        return str(strategy.get("strategy_id") or "")
    return str(strategy or "")


def signal_name(row: dict[str, Any]) -> str:
    strategy = row.get("strategy")
    if isinstance(strategy, dict):
        return str(
            strategy.get("signal_name") or strategy.get("raw_signal") or strategy.get("strategy_id") or ""
        )
    return str(row.get("signal_name") or strategy or "")


def stock_code(row: dict[str, Any]) -> str:
    return str(row.get("stock_code") or "")


def trading_dates(con: duckdb.DuckDBPyConnection, start: str, end: str) -> list[str]:
    return [
        r[0]
        for r in con.execute(
            """
            SELECT DISTINCT date::VARCHAR
            FROM daily_bars
            WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
            ORDER BY 1
            """,
            (start, end),
        ).fetchall()
    ]


def market_return(con: duckdb.DuckDBPyConnection, start: str, end: str) -> float | None:
    value = con.execute(
        """
        SELECT AVG((b.close / a.close) - 1.0)
        FROM daily_bars a
        JOIN daily_bars b ON a.stock_code = b.stock_code
        WHERE a.date = CAST(? AS DATE)
          AND b.date = CAST(? AS DATE)
          AND a.close > 0
          AND b.close > 0
        """,
        (start, end),
    ).fetchone()[0]
    return float(value) if value is not None else None


def load_price_map(
    foundation_db: Path,
    codes: set[str],
    start: str,
    end: str,
) -> dict[str, list[dict[str, Any]]]:
    if not codes:
        return {}
    con = duckdb.connect(str(foundation_db), read_only=True)
    placeholders = ",".join(["?"] * len(codes))
    rows = con.execute(
        f"""
        SELECT stock_code, date::VARCHAR AS date, open, high, low, close
        FROM daily_bars
        WHERE stock_code IN ({placeholders})
          AND date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        ORDER BY stock_code, date
        """,
        (*sorted(codes), start, end),
    ).fetchall()
    con.close()
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for code, date, open_, high, low, close in rows:
        out[code].append(
            {
                "stock_code": code,
                "date": date,
                "open": float(open_ or 0),
                "high": float(high or 0),
                "low": float(low or 0),
                "close": float(close or 0),
            }
        )
    return dict(out)


def load_strategy_state_map(
    foundation_db: Path, start: str, end: str, codes: set[str]
) -> dict[str, list[dict[str, Any]]]:
    by_date = load_state_data_from_duckdb(foundation_db, start, end)
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for date in sorted(by_date):
        for row in by_date[date]:
            code = str(row.get("stock_code") or "")
            if code in codes:
                out[code].append(row)
    return dict(out)


def find_window_return(series: list[dict[str, Any]], window: int) -> tuple[str | None, float | None]:
    if len(series) <= window:
        return None, None
    start_close = series[0].get("close") or 0
    end_row = series[window]
    end_close = end_row.get("close") or 0
    if start_close <= 0 or end_close <= 0:
        return None, None
    return end_row.get("date"), (end_close / start_close) - 1.0


def detect_rule_exit(
    strategy: str, state_series: list[dict[str, Any]], entry_price: float | None = None
) -> dict[str, Any]:
    if strategy == "vcp":
        return vcp_management_observation(float(entry_price or 0), state_series)

    if strategy == "ma2560":
        for row in state_series[1:]:
            result = ma2560_signal(row, row)
            if result and result[0] == "ma2560_death_cross_exit":
                return {
                    "exit_rule_status": "rule_exit_observed",
                    "exit_date": row.get("date"),
                    "exit_price": row.get("close"),
                    "exit_rule_note": "2560 死叉退出信号已出现。",
                }
        return {
            "exit_rule_status": "still_active_by_rule",
            "exit_rule_note": "截至观察日，2560 死叉退出信号未出现。",
        }

    if strategy == "bollinger_bandit":
        hold_bars = 0
        for row in state_series[1:]:
            hold_bars += 1
            period = exit_ma_period(hold_bars)
            ma_by_period = row.get("ma_by_period") or {}
            exit_ma = ma_by_period.get(period)
            result = bollinger_bandit_exit_signal(float(row.get("close") or 0), float(exit_ma or 0))
            if result:
                return {
                    "exit_rule_status": "rule_exit_observed",
                    "exit_date": row.get("date"),
                    "exit_price": row.get("close"),
                    "exit_rule_note": f"布林强盗动态 MA{period} 退出信号已出现。",
                    "exit_ma_period": period,
                }
        return {
            "exit_rule_status": "still_active_by_rule",
            "exit_rule_note": "截至观察日，布林强盗动态 MA 退出信号未出现。",
        }

    return {"exit_rule_status": "unknown_strategy", "exit_rule_note": f"{strategy} 未识别。"}


def build_rows(
    signal_date: str, as_of_date: str, foundation_db: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    reminder_rows = load_reminder_rows(signal_date)
    codes = {stock_code(r) for r in reminder_rows if stock_code(r)}
    price_map = load_price_map(foundation_db, codes, signal_date, as_of_date)
    state_map = load_strategy_state_map(foundation_db, signal_date, as_of_date, codes)

    con = duckdb.connect(str(foundation_db), read_only=True)
    dates = trading_dates(con, signal_date, as_of_date)
    benchmark_by_end: dict[str, float | None] = {}
    if dates:
        for date in dates:
            benchmark_by_end[date] = market_return(con, dates[0], date)
    con.close()

    out: list[dict[str, Any]] = []
    for source in reminder_rows:
        code = stock_code(source)
        prices = price_map.get(code, [])
        if not prices:
            continue
        strategy = strategy_id(source)
        entry = prices[0]
        end = prices[-1]
        entry_close = float(entry.get("close") or 0)
        end_close = float(end.get("close") or 0)
        if entry_close <= 0 or end_close <= 0:
            continue

        ret_to_asof = (end_close / entry_close) - 1.0
        bench_to_asof = benchmark_by_end.get(end.get("date"))
        exit_info = detect_rule_exit(strategy, state_map.get(code, []), entry_close)
        exit_price = exit_info.get("exit_price")
        exit_return = None
        if exit_price and entry_close > 0:
            exit_return = (float(exit_price) / entry_close) - 1.0

        windows: dict[str, Any] = {}
        for window in (5, 10, 20):
            window_date, window_return = find_window_return(prices, window)
            benchmark = benchmark_by_end.get(window_date) if window_date else None
            windows[f"{window}d"] = {
                "date": window_date,
                "return": window_return,
                "benchmark_return": benchmark,
                "excess_return": window_return - benchmark
                if window_return is not None and benchmark is not None
                else None,
            }

        eval_info = source.get("strategy_evaluation") or {}
        row = {
            "stock_code": code,
            "stock_code_6": code6(code),
            "stock_name": source.get("stock_name") or eval_info.get("stock_name") or "",
            "strategy_id": strategy,
            "signal_name": signal_name(source),
            "maturity": source.get("maturity"),
            "strategy_environment_fit": source.get("strategy_environment_fit"),
            "fit_reasons": source.get("fit_reasons"),
            "state_environment": source.get("state_environment"),
            "state_duration": source.get("state_duration"),
            "industry": eval_info.get("sw_l1") or "",
            "signal_date": signal_date,
            "reference_price": entry_close,
            "as_of_date": end.get("date"),
            "as_of_price": end_close,
            "return_to_asof": ret_to_asof,
            "benchmark_return_to_asof": bench_to_asof,
            "excess_return_to_asof": ret_to_asof - bench_to_asof if bench_to_asof is not None else None,
            "windows": windows,
            "exit_observation": exit_info,
            "exit_rule_return": exit_return,
            "source_note": "收益使用信号日收盘价作参考，不含费用、滑点、停牌处理与实际成交约束。",
        }
        out.append(row)

    meta = {
        "signal_date": signal_date,
        "as_of_date": as_of_date,
        "foundation_db": str(foundation_db),
        "input_reminders": len(reminder_rows),
        "rows": len(out),
        "trading_dates": dates,
    }
    return out, meta


def row_from_source(
    source: dict[str, Any],
    signal_date: str,
    as_of_date: str,
    prices: list[dict[str, Any]],
    state_series: list[dict[str, Any]],
    benchmark_by_end: dict[str, float | None],
) -> dict[str, Any] | None:
    if not prices:
        return None
    code = stock_code(source)
    strategy = strategy_id(source)
    entry = prices[0]
    end = prices[-1]
    entry_close = float(entry.get("close") or 0)
    end_close = float(end.get("close") or 0)
    if entry_close <= 0 or end_close <= 0:
        return None

    ret_to_asof = (end_close / entry_close) - 1.0
    bench_to_asof = benchmark_by_end.get(end.get("date"))
    exit_info = detect_rule_exit(strategy, state_series, entry_close)
    exit_price = exit_info.get("exit_price")
    exit_return = None
    if exit_price and entry_close > 0:
        exit_return = (float(exit_price) / entry_close) - 1.0

    windows: dict[str, Any] = {}
    for window in (5, 10, 20):
        window_date, window_return = find_window_return(prices, window)
        benchmark = benchmark_by_end.get(window_date) if window_date else None
        windows[f"{window}d"] = {
            "date": window_date,
            "return": window_return,
            "benchmark_return": benchmark,
            "excess_return": window_return - benchmark
            if window_return is not None and benchmark is not None
            else None,
        }

    eval_info = source.get("strategy_evaluation") or {}
    return {
        "stock_code": code,
        "stock_code_6": code6(code),
        "stock_name": source.get("stock_name") or eval_info.get("stock_name") or "",
        "strategy_id": strategy,
        "signal_name": signal_name(source),
        "maturity": source.get("maturity"),
        "strategy_environment_fit": source.get("strategy_environment_fit"),
        "fit_reasons": source.get("fit_reasons"),
        "state_environment": source.get("state_environment"),
        "state_duration": source.get("state_duration"),
        "industry": eval_info.get("sw_l1") or "",
        "signal_date": signal_date,
        "reference_price": entry_close,
        "as_of_date": end.get("date"),
        "as_of_price": end_close,
        "return_to_asof": ret_to_asof,
        "benchmark_return_to_asof": bench_to_asof,
        "excess_return_to_asof": ret_to_asof - bench_to_asof if bench_to_asof is not None else None,
        "windows": windows,
        "exit_observation": exit_info,
        "exit_rule_return": exit_return,
        "source_note": "收益使用信号日收盘价作参考，不含费用、滑点、停牌处理与实际成交约束。",
    }


def build_range_rows(
    start_date: str,
    end_date: str,
    as_of_date: str,
    foundation_db: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    signal_dates = [d for d in available_reminder_dates(start_date, end_date) if d <= as_of_date]
    reminders_by_date: dict[str, list[dict[str, Any]]] = {d: load_reminder_rows(d) for d in signal_dates}
    codes = {stock_code(row) for rows in reminders_by_date.values() for row in rows if stock_code(row)}

    price_map = load_price_map(foundation_db, codes, start_date, as_of_date)
    state_map = load_strategy_state_map(foundation_db, start_date, as_of_date, codes)

    con = duckdb.connect(str(foundation_db), read_only=True)
    all_dates = trading_dates(con, start_date, as_of_date)
    date_set = set(all_dates)
    benchmark_cache: dict[tuple[str, str], float | None] = {}

    def benchmark(start: str, end: str | None) -> float | None:
        if not end or start not in date_set or end not in date_set:
            return None
        key = (start, end)
        if key not in benchmark_cache:
            benchmark_cache[key] = market_return(con, start, end)
        return benchmark_cache[key]

    out: list[dict[str, Any]] = []
    input_count = 0
    for signal_date in signal_dates:
        for source in reminders_by_date[signal_date]:
            input_count += 1
            code = stock_code(source)
            prices = [row for row in price_map.get(code, []) if row.get("date") >= signal_date]
            states = [row for row in state_map.get(code, []) if row.get("date") >= signal_date]
            if not prices:
                continue
            benchmark_by_end: dict[str, float | None] = {}
            for price_row in prices:
                date_value = price_row.get("date")
                benchmark_by_end[date_value] = benchmark(signal_date, date_value)
            row = row_from_source(source, signal_date, as_of_date, prices, states, benchmark_by_end)
            if row:
                out.append(row)

    con.close()
    meta = {
        "start_date": start_date,
        "end_date": end_date,
        "as_of_date": as_of_date,
        "foundation_db": str(foundation_db),
        "signal_dates": signal_dates,
        "signal_date_count": len(signal_dates),
        "input_reminders": input_count,
        "rows": len(out),
        "trading_dates": all_dates,
    }
    return out, meta


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        rets = [r["return_to_asof"] for r in items if r.get("return_to_asof") is not None]
        excess = [r["excess_return_to_asof"] for r in items if r.get("excess_return_to_asof") is not None]
        exit_rets = [r["exit_rule_return"] for r in items if r.get("exit_rule_return") is not None]
        return {
            "count": len(items),
            "avg_return_to_asof": mean(rets) if rets else None,
            "median_return_to_asof": sorted(rets)[len(rets) // 2] if rets else None,
            "win_rate_to_asof": sum(1 for x in rets if x > 0) / len(rets) if rets else None,
            "avg_excess_return_to_asof": mean(excess) if excess else None,
            "rule_exit_count": sum(
                1
                for r in items
                if (r.get("exit_observation") or {}).get("exit_rule_status") == "rule_exit_observed"
            ),
            "still_active_count": sum(
                1
                for r in items
                if (r.get("exit_observation") or {}).get("exit_rule_status") == "still_active_by_rule"
            ),
            "no_exit_rule_count": sum(
                1
                for r in items
                if (r.get("exit_observation") or {}).get("exit_rule_status") == "not_available"
            ),
            "profit_protection_count": sum(
                1
                for r in items
                if (r.get("exit_observation") or {}).get("exit_rule_status") == "profit_protection_zone"
            ),
            "time_stop_count": sum(
                1
                for r in items
                if (r.get("exit_observation") or {}).get("exit_rule_status") == "time_stop_observed"
            ),
            "avg_exit_rule_return": mean(exit_rets) if exit_rets else None,
        }

    by_strategy: dict[str, Any] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["strategy_id"]].append(row)
    for key, items in grouped.items():
        by_strategy[key] = summary(items)

    by_signal_date: dict[str, Any] = {}
    grouped_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped_by_date[row["signal_date"]].append(row)
    for key, items in grouped_by_date.items():
        by_signal_date[key] = summary(items)

    return {
        "overall": summary(rows),
        "by_strategy": by_strategy,
        "by_signal_date": by_signal_date,
        "strategy_counts": dict(Counter(r["strategy_id"] for r in rows)),
        "exit_status_counts": dict(
            Counter((r.get("exit_observation") or {}).get("exit_rule_status") for r in rows)
        ),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    agg = payload["aggregate"]
    rows = payload["rows"]
    if "signal_date" in meta:
        title = f"策略样本追踪报告：{meta['signal_date']} → {meta['as_of_date']}"
        sample_line = f"- 样本来源：`outputs/strategy_reminders/reminder_{ymd(meta['signal_date'])}.json`"
        input_line = f"- 输入提醒：{meta['input_reminders']} 条；有效追踪：{meta['rows']} 条"
    else:
        title = (
            f"策略样本综合追踪报告：{meta['start_date']} → {meta['end_date']}，观察至 {meta['as_of_date']}"
        )
        sample_line = f"- 样本来源：`outputs/strategy_reminders/reminder_*.json`，共 {meta['signal_date_count']} 个简报日期"
        input_line = f"- 输入提醒：{meta['input_reminders']} 条；有效追踪：{meta['rows']} 条"
    lines: list[str] = [
        f"# {title}",
        "",
        "## 报告口径",
        "",
        sample_line,
        f"- 观察底座：`{meta['foundation_db']}`",
        input_line,
        "- 收益口径：信号日收盘价到观察日收盘价；不含费用、滑点和真实成交约束。",
        "- 管理口径：2560/布林强盗使用已实现的退出规则；VCP 使用本地指南版触发后管理观察（8% 初始防守、5 日时间过滤、2R 利润保护区）。",
        "",
        "## 总览",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 样本数 | {agg['overall']['count']} |",
        f"| 平均观察收益 | {pct(agg['overall']['avg_return_to_asof'])} |",
        f"| 观察胜率 | {pct(agg['overall']['win_rate_to_asof'])} |",
        f"| 平均相对全市场等权超额 | {pct(agg['overall']['avg_excess_return_to_asof'])} |",
        f"| 已出现标准退出规则 | {agg['overall']['rule_exit_count']} |",
        f"| 截至观察日仍按规则延续 | {agg['overall']['still_active_count']} |",
        f"| 暂无标准退出模块 | {agg['overall']['no_exit_rule_count']} |",
        f"| VCP/规则进入利润保护区 | {agg['overall']['profit_protection_count']} |",
        f"| VCP时间过滤触发 | {agg['overall']['time_stop_count']} |",
        "",
        "## 按策略分组",
        "",
        "| 策略 | 样本 | 平均观察收益 | 观察胜率 | 平均超额 | 标准退出出现 | 利润保护区 | 时间过滤 | 仍按规则延续 | 无标准退出模块 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy, data in sorted(agg["by_strategy"].items()):
        lines.append(
            "| {strategy} | {count} | {avg} | {win} | {excess} | {exit_count} | {protect} | {time_stop} | {active} | {no_rule} |".format(
                strategy=strategy,
                count=data["count"],
                avg=pct(data["avg_return_to_asof"]),
                win=pct(data["win_rate_to_asof"]),
                excess=pct(data["avg_excess_return_to_asof"]),
                exit_count=data["rule_exit_count"],
                protect=data["profit_protection_count"],
                time_stop=data["time_stop_count"],
                active=data["still_active_count"],
                no_rule=data["no_exit_rule_count"],
            )
        )

    if agg.get("by_signal_date"):
        lines.extend(
            [
                "",
                "## 按简报日期汇总",
                "",
                "| 简报日期 | 样本 | 平均观察收益 | 观察胜率 | 平均超额 | 标准退出出现 | 仍按规则延续 | 无标准退出模块 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for date_key, data in sorted(agg["by_signal_date"].items()):
            lines.append(
                "| {date} | {count} | {avg} | {win} | {excess} | {exit_count} | {active} | {no_rule} |".format(
                    date=date_key,
                    count=data["count"],
                    avg=pct(data["avg_return_to_asof"]),
                    win=pct(data["win_rate_to_asof"]),
                    excess=pct(data["avg_excess_return_to_asof"]),
                    exit_count=data["rule_exit_count"],
                    active=data["still_active_count"],
                    no_rule=data["no_exit_rule_count"],
                )
            )

    lines.extend(
        [
            "",
            "## 样本明细（按观察收益排序前 50）",
            "",
            "| 代码 | 名称 | 策略 | 信号 | State | 持续 | 观察收益 | 超额 | 退出状态 | 说明 |",
            "|---|---|---|---|---|---|---:|---:|---|---|",
        ]
    )
    for row in sorted(rows, key=lambda x: x.get("return_to_asof") or -999, reverse=True)[:50]:
        state = row.get("state_environment") or {}
        duration = row.get("state_duration") or {}
        exit_obs = row.get("exit_observation") or {}
        lines.append(
            "| {code} | {name} | {strategy} | {signal} | {state} | {duration} | {ret} | {excess} | {exit_status} | {note} |".format(
                code=row["stock_code"],
                name=row.get("stock_name") or "",
                strategy=row["strategy_id"],
                signal=row["signal_name"],
                state=f"MN1:{state.get('mn1_state', '-')} W1:{state.get('w1_state', '-')} D1:{state.get('d1_state', '-')}",
                duration=f"D1 {duration.get('d1_ef_duration', '-')} / 三周期 {duration.get('all_three_ef_duration', '-')}",
                ret=pct(row.get("return_to_asof")),
                excess=pct(row.get("excess_return_to_asof")),
                exit_status=exit_obs.get("exit_rule_status", ""),
                note=exit_obs.get("exit_rule_note", ""),
            )
        )

    lines.extend(
        [
            "",
            "## 用户路径复盘",
            "",
            "1. 打开当日简报，先看策略信号是否出现在三周期 E/F 环境中。",
            "2. 进入样本追踪表，确认该信号属于 VCP、2560 还是布林强盗。",
            "3. 对已有标准退出模块的策略，跟踪退出规则是否出现；对 VCP，跟踪指南版初始防守、时间过滤和利润保护状态。",
            "4. 每天滚动生成同类报告，持续积累“信号出现后到底如何”的真实样本。",
            "5. 当样本足够后，再把统计结论展示在每日简报中；样本不足时继续显示待校准。",
            "",
            "## 产品判断",
            "",
            "- 好用：用户可以从每日简报直接跳到后续追踪，不需要手工翻行情。",
            "- 易用：报告按策略分组，并明确区分观察收益、超额收益、退出规则状态。",
            "- 敢用：VCP 管理规则来自本地指南且单独标注为观察口径，统计不足不编胜率，所有数字都可回查。",
        ]
    )
    return "\n".join(lines) + "\n"


def render_html(payload: dict[str, Any], markdown_text: str) -> str:
    meta = payload["meta"]
    agg = payload["aggregate"]
    rows = sorted(payload["rows"], key=lambda x: x.get("return_to_asof") or -999, reverse=True)
    title_sub = (
        f"样本日期：{html.escape(meta['signal_date'])} · 观察至：{html.escape(meta['as_of_date'])}"
        if "signal_date" in meta
        else f"样本区间：{html.escape(meta['start_date'])} 至 {html.escape(meta['end_date'])} · 观察至：{html.escape(meta['as_of_date'])}"
    )
    doc_title = (
        f"策略样本追踪报告 {html.escape(meta['signal_date'])}"
        if "signal_date" in meta
        else f"策略样本综合追踪报告 {html.escape(meta['start_date'])}-{html.escape(meta['end_date'])}"
    )
    source_label = (
        "来自单日策略简报" if "signal_date" in meta else f"来自 {meta['signal_date_count']} 个策略简报日期"
    )
    input_text = (
        f"输入提醒 {meta['input_reminders']} 条，有效追踪 {meta['rows']} 条。"
        if "signal_date" in meta
        else f"覆盖 {meta['signal_date_count']} 个简报日期，输入提醒 {meta['input_reminders']} 条，有效追踪 {meta['rows']} 条。"
    )
    strategy_cards = ""
    for strategy, data in sorted(agg["by_strategy"].items()):
        strategy_cards += f"""
        <section class="metric-card">
          <div class="metric-title">{html.escape(strategy)}</div>
          <div class="metric-value">{data["count"]}</div>
          <div class="metric-sub">平均观察收益 {pct(data["avg_return_to_asof"])} · 胜率 {pct(data["win_rate_to_asof"])}</div>
          <div class="metric-sub">平均超额 {pct(data["avg_excess_return_to_asof"])}</div>
        </section>
        """

    row_html = ""
    for row in rows:
        state = row.get("state_environment") or {}
        duration = row.get("state_duration") or {}
        exit_obs = row.get("exit_observation") or {}
        status = exit_obs.get("exit_rule_status", "")
        status_class = {
            "rule_exit_observed": "tag-warn",
            "still_active_by_rule": "tag-ok",
            "not_available": "tag-muted",
        }.get(status, "tag-muted")
        row_html += f"""
        <tr>
          <td><strong>{html.escape(row["stock_code"])}</strong><br><span>{html.escape(row.get("stock_name") or "")}</span></td>
          <td>{html.escape(row["strategy_id"])}<br><span>{html.escape(row["signal_name"])}</span><br><span>{html.escape(row["signal_date"])}</span></td>
          <td>MN1:{html.escape(str(state.get("mn1_state", "-")))} W1:{html.escape(str(state.get("w1_state", "-")))} D1:{html.escape(str(state.get("d1_state", "-")))}<br>
              <span>D1 {html.escape(str(duration.get("d1_ef_duration", "-")))} / 三周期 {html.escape(str(duration.get("all_three_ef_duration", "-")))}</span></td>
          <td class="num">{pct(row.get("return_to_asof"))}</td>
          <td class="num">{pct(row.get("excess_return_to_asof"))}</td>
          <td><span class="tag {status_class}">{html.escape(status)}</span><br><span>{html.escape(exit_obs.get("exit_rule_note", ""))}</span></td>
        </tr>
        """

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{doc_title}</title>
<style>
body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif; background:#f4f6f8; color:#172033; }}
.hero {{ background:#172033; color:white; padding:28px 34px; }}
.hero h1 {{ margin:0 0 10px; font-size:28px; letter-spacing:0; }}
.hero p {{ margin:4px 0; color:#d8e0ec; }}
.wrap {{ padding:24px 34px 44px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:14px; margin:18px 0 22px; }}
.metric-card {{ background:white; border:1px solid #dfe5ee; border-radius:8px; padding:16px; }}
.metric-title {{ font-size:13px; color:#5b677a; }}
.metric-value {{ font-size:30px; font-weight:700; margin:4px 0; }}
.metric-sub {{ font-size:13px; color:#5b677a; line-height:1.5; }}
.panel {{ background:white; border:1px solid #dfe5ee; border-radius:8px; padding:18px; margin:16px 0; }}
h2 {{ font-size:18px; margin:0 0 12px; }}
table {{ width:100%; border-collapse:collapse; background:white; font-size:13px; }}
th,td {{ border-bottom:1px solid #e6ebf2; padding:10px 8px; text-align:left; vertical-align:top; }}
th {{ color:#5b677a; font-weight:600; background:#f9fafc; position:sticky; top:0; }}
td span {{ color:#687386; font-size:12px; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.tag {{ display:inline-block; padding:3px 8px; border-radius:999px; font-size:12px; font-weight:600; }}
.tag-ok {{ background:#e8f6ed; color:#1f7a3a; }}
.tag-warn {{ background:#fff2d8; color:#946200; }}
.tag-muted {{ background:#eef2f7; color:#536072; }}
.note {{ color:#5b677a; line-height:1.7; }}
.table-wrap {{ overflow:auto; max-height:720px; border:1px solid #dfe5ee; border-radius:8px; }}
@media (max-width: 720px) {{ .hero,.wrap {{ padding-left:16px; padding-right:16px; }} th,td {{ min-width:120px; }} }}
</style>
</head>
<body>
<section class="hero">
  <h1>策略样本追踪报告</h1>
  <p>{title_sub}</p>
  <p>{input_text}收益使用信号日收盘价作参考，不含费用、滑点和真实成交约束。</p>
</section>
<main class="wrap">
  <div class="grid">
    <section class="metric-card"><div class="metric-title">有效样本</div><div class="metric-value">{agg["overall"]["count"]}</div><div class="metric-sub">{source_label}</div></section>
    <section class="metric-card"><div class="metric-title">平均观察收益</div><div class="metric-value">{pct(agg["overall"]["avg_return_to_asof"])}</div><div class="metric-sub">观察胜率 {pct(agg["overall"]["win_rate_to_asof"])}</div></section>
    <section class="metric-card"><div class="metric-title">平均超额</div><div class="metric-value">{pct(agg["overall"]["avg_excess_return_to_asof"])}</div><div class="metric-sub">相对全市场等权</div></section>
    <section class="metric-card"><div class="metric-title">规则状态</div><div class="metric-value">{agg["overall"]["rule_exit_count"]}</div><div class="metric-sub">标准退出出现；{agg["overall"]["profit_protection_count"]} 进入利润保护区；{agg["overall"]["still_active_count"]} 仍延续</div></section>
  </div>
  <div class="grid">{strategy_cards}</div>
  <section class="panel">
    <h2>怎么读这份报告</h2>
    <div class="note">它不是复杂的交易终端，而是把当日简报里的策略样本逐条追踪到观察日。已有标准退出规则的策略会显示规则状态；没有标准退出模块的策略只显示后续表现，不做伪模拟。每天滚动生成后，用户能看到信号出现后真实发生了什么。</div>
  </section>
  <section class="panel">
    <h2>样本明细</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>股票</th><th>策略信号</th><th>State 环境</th><th>观察收益</th><th>超额</th><th>退出规则状态</th></tr></thead>
        <tbody>{row_html}</tbody>
      </table>
    </div>
  </section>
</main>
</body>
</html>"""


def build_report(signal_date: str, as_of_date: str, foundation_db: Path | None = None) -> dict[str, Any]:
    foundation_db = foundation_db or default_foundation_db(as_of_date)
    rows, meta = build_rows(signal_date, as_of_date, foundation_db)
    payload = {
        "schema_version": "strategy_outcome_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "meta": meta,
        "aggregate": aggregate(rows),
        "rows": rows,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"strategy_outcome_{ymd(signal_date)}_to_{ymd(as_of_date)}"
    json_path = OUTPUT_DIR / f"{stem}.json"
    md_path = OUTPUT_DIR / f"{stem}.md"
    html_path = PUBLIC_DIR / f"{stem}.html"
    latest_html = PUBLIC_DIR / "strategy_outcome_latest.html"

    markdown_text = render_markdown(payload)
    html_text = render_html(payload, markdown_text)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_text, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    latest_html.write_text(html_text, encoding="utf-8")

    return {
        "ok": True,
        "signal_date": signal_date,
        "as_of_date": as_of_date,
        "foundation_db": str(foundation_db),
        "input_reminders": meta["input_reminders"],
        "tracked_rows": meta["rows"],
        "aggregate": payload["aggregate"],
        "json_output": str(json_path),
        "markdown_output": str(md_path),
        "html_output": str(html_path),
        "latest_html": str(latest_html),
    }


def build_range_report(
    start_date: str,
    end_date: str,
    as_of_date: str,
    foundation_db: Path | None = None,
) -> dict[str, Any]:
    foundation_db = foundation_db or default_foundation_db(as_of_date)
    rows, meta = build_range_rows(start_date, end_date, as_of_date, foundation_db)
    payload = {
        "schema_version": "strategy_outcome_range_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "meta": meta,
        "aggregate": aggregate(rows),
        "top_50": sorted(rows, key=lambda x: x.get("return_to_asof") or -999, reverse=True)[:50],
        "rows": rows,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"strategy_outcome_range_{ymd(start_date)}_{ymd(end_date)}_to_{ymd(as_of_date)}"
    json_path = OUTPUT_DIR / f"{stem}.json"
    md_path = OUTPUT_DIR / f"{stem}.md"
    top50_json_path = OUTPUT_DIR / f"{stem}_top50.json"
    html_path = PUBLIC_DIR / f"{stem}.html"
    latest_html = PUBLIC_DIR / "strategy_outcome_range_latest.html"

    markdown_text = render_markdown(payload)
    html_text = render_html(payload, markdown_text)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    top50_json_path.write_text(json.dumps(payload["top_50"], ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_text, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    latest_html.write_text(html_text, encoding="utf-8")

    return {
        "ok": True,
        "start_date": start_date,
        "end_date": end_date,
        "as_of_date": as_of_date,
        "foundation_db": str(foundation_db),
        "signal_date_count": meta["signal_date_count"],
        "input_reminders": meta["input_reminders"],
        "tracked_rows": meta["rows"],
        "aggregate": payload["aggregate"],
        "json_output": str(json_path),
        "top50_json_output": str(top50_json_path),
        "markdown_output": str(md_path),
        "html_output": str(html_path),
        "latest_html": str(latest_html),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build strategy outcome report from a daily reminder brief.")
    parser.add_argument("--signal-date", help="Reminder signal date, YYYY-MM-DD")
    parser.add_argument("--start-date", help="Start reminder date for range report, YYYY-MM-DD")
    parser.add_argument("--end-date", help="End reminder date for range report, YYYY-MM-DD")
    parser.add_argument("--as-of-date", required=True, help="Observation end date, YYYY-MM-DD")
    parser.add_argument("--foundation-db", type=Path)
    args = parser.parse_args()
    if args.start_date:
        result = build_range_report(
            args.start_date, args.end_date or args.as_of_date, args.as_of_date, args.foundation_db
        )
    else:
        if not args.signal_date:
            raise ValueError("--signal-date is required unless --start-date is provided")
        result = build_report(args.signal_date, args.as_of_date, args.foundation_db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
