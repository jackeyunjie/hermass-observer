#!/usr/bin/env python3
"""交易后复盘脚本：对比系统信号与实际执行，统计出场规则遵守率。

Usage:
    # 从 CSV 导入实际交易记录
    python3 scripts/trade_review.py --import-csv data/trades_2026w21.csv

    # 命令行录入单条交易
    python3 scripts/trade_review.py --add-trade --date 2026-05-22 --stock 000997.SZ --strategy vcp --action entry --price 13.50 --shares 1000 --notes "手工录入"

    # 生成周度复盘报告（默认上周）
    python3 scripts/trade_review.py --week 2026-05-22

    # 列出所有交易记录
    python3 scripts/trade_review.py --list-trades

CSV 格式要求：
    date,stock_code,stock_name,strategy,action,price,shares,notes
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
TRADING_SOP_DIR = OUTPUTS_DIR / "trading_sop"
REMINDER_DIR = OUTPUTS_DIR / "strategy_reminders"
TRADE_REVIEW_DIR = OUTPUTS_DIR / "trade_review"

TRADE_RECORDS_CSV = DATA_DIR / "trade_records.csv"
TRADE_RECORDS_JSON = DATA_DIR / "trade_records.json"


@dataclass
class TradeRecord:
    id: str
    date: str  # YYYY-MM-DD
    stock_code: str
    stock_name: str
    strategy: str
    action: str  # entry | exit
    price: float
    shares: int
    notes: str
    created_at: str


# ═════════════════════════════════════════════════════════════════════════════
# Persistence
# ═════════════════════════════════════════════════════════════════════════════


def ensure_trade_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TRADE_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    if not TRADE_RECORDS_CSV.exists():
        with open(TRADE_RECORDS_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["id", "date", "stock_code", "stock_name", "strategy", "action", "price", "shares", "notes", "created_at"]
            )


def load_trades() -> list[TradeRecord]:
    ensure_trade_storage()
    trades: list[TradeRecord] = []
    with open(TRADE_RECORDS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(
                TradeRecord(
                    id=row["id"],
                    date=row["date"],
                    stock_code=row["stock_code"],
                    stock_name=row.get("stock_name", ""),
                    strategy=row["strategy"],
                    action=row["action"],
                    price=float(row["price"]),
                    shares=int(row["shares"]),
                    notes=row.get("notes", ""),
                    created_at=row.get("created_at", ""),
                )
            )
    return trades


def save_trade(trade: TradeRecord) -> None:
    ensure_trade_storage()
    with open(TRADE_RECORDS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                trade.id,
                trade.date,
                trade.stock_code,
                trade.stock_name,
                trade.strategy,
                trade.action,
                trade.price,
                trade.shares,
                trade.notes,
                trade.created_at,
            ]
        )


# ═════════════════════════════════════════════════════════════════════════════
# System signal loaders
# ═════════════════════════════════════════════════════════════════════════════


def load_sop(date_str: str) -> dict[str, Any]:
    """加载指定日期的每日交易 SOP。"""
    path = TRADING_SOP_DIR / f"daily_trading_sop_{date_str}.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_reminder(date_str: str) -> dict[str, Any]:
    """加载指定日期的策略提醒。"""
    path = REMINDER_DIR / f"reminder_{date_str.replace('-', '')}.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sop_candidate_lookup(sop: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """返回 {stock_code: candidate} 映射。"""
    result: dict[str, dict[str, Any]] = {}
    for c in sop.get("candidates", []):
        code = c.get("stock_code", "")
        if code:
            result[code] = c
    return result


def get_week_range(anchor_date: str) -> tuple[str, str]:
    """以 anchor_date 所在周的周一~周日为范围。"""
    dt = datetime.strptime(anchor_date, "%Y-%m-%d")
    monday = dt - timedelta(days=dt.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


# ═════════════════════════════════════════════════════════════════════════════
# Core review logic
# ═════════════════════════════════════════════════════════════════════════════


def match_entry_with_system(trade: TradeRecord) -> dict[str, Any] | None:
    """将实际 entry 交易与当日系统 SOP 候选匹配，返回候选详情。"""
    sop = load_sop(trade.date)
    candidates = sop_candidate_lookup(sop)
    return candidates.get(trade.stock_code)


def check_exit_compliance(
    exit_trade: TradeRecord,
    entry_trade: TradeRecord,
    entry_sop: dict[str, Any] | None,
) -> dict[str, Any]:
    """检查出场是否符合系统规则。

    合规标准（满足任一即视为合规）：
    1. 实际出场价 <= 系统止损价（执行了硬止损）
    2. 出场当日该股票已不在 SOP 候选列表中（系统已放弃）
    3. 出场前一日该股票还在 SOP 中，但出场当日已不在（±1天容忍度）
    """
    result = {
        "compliant": False,
        "reason": "",
        "system_stop_price": None,
        "exit_sop_present": False,
        "prev_day_sop_present": False,
    }

    if entry_sop is None:
        result["reason"] = "无对应入场系统信号，无法评估出场合规性"
        return result

    stop_price = entry_sop.get("stop_price")
    result["system_stop_price"] = stop_price

    if stop_price is not None and exit_trade.price <= stop_price:
        result["compliant"] = True
        result["reason"] = f"出场价 {exit_trade.price:.3f} <= 系统止损价 {stop_price:.3f}，执行止损"
        return result

    # 检查出场当日 SOP
    exit_sop = load_sop(exit_trade.date)
    exit_candidates = sop_candidate_lookup(exit_sop)
    if exit_trade.stock_code not in exit_candidates:
        result["exit_sop_present"] = False
        # 检查前一日是否还在 SOP 中
        prev_date = (
            datetime.strptime(exit_trade.date, "%Y-%m-%d") - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        prev_sop = load_sop(prev_date)
        prev_candidates = sop_candidate_lookup(prev_sop)
        if prev_candidates and exit_trade.stock_code in prev_candidates:
            result["prev_day_sop_present"] = True
            result["compliant"] = True
            result["reason"] = "出场当日系统已将该股票移出候选列表（前一日仍在），±1天容忍度内"
            return result
        result["compliant"] = True
        result["reason"] = "出场当日该股票不在系统候选列表中"
        return result

    # 出场当日股票仍在 SOP 中：检查下一日是否被移出（±1天容忍度）
    next_date = (
        datetime.strptime(exit_trade.date, "%Y-%m-%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")
    next_sop = load_sop(next_date)
    next_candidates = sop_candidate_lookup(next_sop)
    if next_candidates and exit_trade.stock_code not in next_candidates:
        result["compliant"] = True
        result["reason"] = "出场次日系统将该股票移出候选列表，±1天容忍度内"
        return result

    result["exit_sop_present"] = True
    result["reason"] = (
        f"出场价 {exit_trade.price:.3f} > 系统止损价 {stop_price:.3f}，"
        f"且出场当日及次日系统仍在推荐该股票，视为提前出场"
    )
    return result


def compute_pnl(
    entry: TradeRecord,
    exit_trade: TradeRecord,
    entry_sop: dict[str, Any] | None,
) -> dict[str, Any]:
    """计算实际盈亏与系统参考盈亏。"""
    actual_return_pct = (exit_trade.price - entry.price) / entry.price * 100.0
    actual_pnl = (exit_trade.price - entry.price) * entry.shares

    system_return_pct: float | None = None
    system_pnl: float | None = None

    if entry_sop:
        sop_entry_price = entry_sop.get("d1_close") or entry_sop.get("entry_price")
        stop_price = entry_sop.get("stop_price")
        if sop_entry_price and stop_price:
            # 系统保守参考：按系统入场价 + 硬止损价计算
            system_return_pct = (stop_price - sop_entry_price) / sop_entry_price * 100.0
            system_pnl = (stop_price - sop_entry_price) * entry.shares

    return {
        "actual_return_pct": round(actual_return_pct, 2),
        "actual_pnl": round(actual_pnl, 2),
        "system_return_pct": round(system_return_pct, 2) if system_return_pct is not None else None,
        "system_pnl": round(system_pnl, 2) if system_pnl is not None else None,
        "deviation_pct": (
            round(actual_return_pct - system_return_pct, 2)
            if system_return_pct is not None
            else None
        ),
    }


def run_weekly_review(anchor_date: str) -> dict[str, Any]:
    """执行周度复盘，返回完整复盘数据。"""
    week_start, week_end = get_week_range(anchor_date)
    all_trades = load_trades()

    # 筛选本周交易
    week_trades = [
        t for t in all_trades if week_start <= t.date <= week_end
    ]

    # 按股票分组配对 entry / exit
    stock_actions: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in week_trades:
        stock_actions[t.stock_code].append(t)

    # 统计维度
    entries: list[dict[str, Any]] = []
    exits: list[dict[str, Any]] = []
    system_signals_best_fit: set[tuple[str, str]] = set()  # (date, stock_code)
    system_signals_any: set[tuple[str, str]] = set()

    # 遍历本周所有交易日，收集系统信号
    current = datetime.strptime(week_start, "%Y-%m-%d")
    end = datetime.strptime(week_end, "%Y-%m-%d")
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        sop = load_sop(date_str)
        for c in sop.get("candidates", []):
            code = c.get("stock_code", "")
            fit = c.get("strategy_fit", "")
            if code:
                system_signals_any.add((date_str, code))
                if fit == "最佳适配":
                    system_signals_best_fit.add((date_str, code))
        current += timedelta(days=1)

    # 已执行的最佳适配信号
    executed_best_fit: set[tuple[str, str]] = set()
    executed_any: set[tuple[str, str]] = set()

    for stock_code, actions in stock_actions.items():
        actions.sort(key=lambda t: t.date)
        entry_trade: TradeRecord | None = None
        for t in actions:
            if t.action == "entry":
                entry_trade = t
                entry_sop = match_entry_with_system(t)
                fit = entry_sop.get("strategy_fit") if entry_sop else None
                is_best = fit == "最佳适配"
                if is_best:
                    executed_best_fit.add((t.date, t.stock_code))
                executed_any.add((t.date, t.stock_code))

                entry_info = {
                    "date": t.date,
                    "stock_code": t.stock_code,
                    "stock_name": t.stock_name,
                    "strategy": t.strategy,
                    "price": t.price,
                    "shares": t.shares,
                    "system_match": entry_sop is not None,
                    "system_fit": fit,
                    "system_entry_price": entry_sop.get("d1_close") if entry_sop else None,
                    "system_stop_price": entry_sop.get("stop_price") if entry_sop else None,
                    "notes": t.notes,
                }
                entries.append(entry_info)

            elif t.action == "exit" and entry_trade:
                entry_sop = match_entry_with_system(entry_trade)
                compliance = check_exit_compliance(t, entry_trade, entry_sop)
                pnl = compute_pnl(entry_trade, t, entry_sop)
                exits.append(
                    {
                        "date": t.date,
                        "stock_code": t.stock_code,
                        "stock_name": t.stock_name,
                        "strategy": t.strategy,
                        "exit_price": t.price,
                        "shares": t.shares,
                        "hold_days": (
                            datetime.strptime(t.date, "%Y-%m-%d")
                            - datetime.strptime(entry_trade.date, "%Y-%m-%d")
                        ).days,
                        "compliant": compliance["compliant"],
                        "compliance_reason": compliance["reason"],
                        **pnl,
                        "notes": t.notes,
                    }
                )
                entry_trade = None  # 简单假设：一次 entry 对应一次 exit

    # 指标计算
    total_best_fit_signals = len(system_signals_best_fit)
    executed_best_fit_count = len(executed_best_fit)
    signal_execution_rate = (
        executed_best_fit_count / total_best_fit_signals * 100.0
        if total_best_fit_signals > 0
        else 0.0
    )

    total_exits = len(exits)
    compliant_exits = sum(1 for e in exits if e["compliant"])
    exit_compliance_rate = (
        compliant_exits / total_exits * 100.0 if total_exits > 0 else 0.0
    )

    total_actual_pnl = sum(e["actual_pnl"] for e in exits)
    total_system_pnl = sum(
        e["system_pnl"] for e in exits if e["system_pnl"] is not None
    )

    return {
        "week_start": week_start,
        "week_end": week_end,
        "anchor_date": anchor_date,
        "total_entries": len(entries),
        "total_exits": total_exits,
        "total_best_fit_signals": total_best_fit_signals,
        "executed_best_fit": executed_best_fit_count,
        "signal_execution_rate": round(signal_execution_rate, 1),
        "exit_compliance_rate": round(exit_compliance_rate, 1),
        "total_actual_pnl": round(total_actual_pnl, 2),
        "total_system_pnl": round(total_system_pnl, 2) if exits else None,
        "entries": entries,
        "exits": exits,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ═════════════════════════════════════════════════════════════════════════════
# Report generation
# ═════════════════════════════════════════════════════════════════════════════


def build_review_markdown(review: dict[str, Any]) -> str:
    ws = review["week_start"]
    we = review["week_end"]
    entries = review["entries"]
    exits = review["exits"]

    lines = [
        f"# 交易后复盘报告（{ws} ~ {we}）",
        "",
        f"> 生成时间：{review['generated_at']}",
        "",
        "## 一、核心指标",
        "",
        f"- **信号执行率**：{review['signal_execution_rate']}%（实际执行 {review['executed_best_fit']} / 系统最佳适配信号 {review['total_best_fit_signals']}）",
        f"- **出场规则遵守率**：{review['exit_compliance_rate']}%（合规出场 {sum(1 for e in exits if e['compliant'])} / 总出场 {len(exits)}）",
        f"- **实际总盈亏**：¥{review['total_actual_pnl']:,.2f}",
    ]
    if review.get("total_system_pnl") is not None:
        deviation = review["total_actual_pnl"] - review["total_system_pnl"]
        lines.append(
            f"- **系统参考盈亏**：¥{review['total_system_pnl']:,.2f}（偏差：¥{deviation:,.2f}）"
        )
    lines.append("")

    # Entry table
    lines.extend(["## 二、入场记录", ""])
    if entries:
        lines.append(
            "| 日期 | 股票 | 策略 | 实际价 | 股数 | 系统匹配 | 系统适配度 | 系统止损价 | 备注 |"
        )
        lines.append(
            "|------|------|------|--------|------|----------|------------|------------|------|"
        )
        for e in entries:
            match_text = "是" if e["system_match"] else "否"
            fit_text = e.get("system_fit") or "-"
            stop = f"¥{e['system_stop_price']:.2f}" if e.get("system_stop_price") else "-"
            lines.append(
                f"| {e['date']} | {e['stock_code']} {e['stock_name']} | {e['strategy']} | "
                f"¥{e['price']:.2f} | {e['shares']} | {match_text} | {fit_text} | {stop} | {e['notes']} |"
            )
    else:
        lines.append("本周无入场记录。")
    lines.append("")

    # Exit table
    lines.extend(["## 三、出场记录", ""])
    if exits:
        lines.append(
            "| 日期 | 股票 | 策略 | 出场价 | 持有天数 | 合规性 | 实际盈亏 | 系统参考盈亏 | 偏差 | 备注 |"
        )
        lines.append(
            "|------|------|------|--------|----------|--------|----------|--------------|------|------|"
        )
        for e in exits:
            compliant_badge = "✅ 合规" if e["compliant"] else "❌ 偏差"
            actual_pnl = f"¥{e['actual_pnl']:,.2f} ({e['actual_return_pct']:+.2f}%)"
            sys_pnl = (
                f"¥{e['system_pnl']:,.2f} ({e['system_return_pct']:+.2f}%)"
                if e.get("system_pnl") is not None
                else "-"
            )
            dev = f"{e['deviation_pct']:+.2f}%" if e.get("deviation_pct") is not None else "-"
            lines.append(
                f"| {e['date']} | {e['stock_code']} {e['stock_name']} | {e['strategy']} | "
                f"¥{e['exit_price']:.2f} | {e['hold_days']} | {compliant_badge} | {actual_pnl} | {sys_pnl} | {dev} | {e['notes']} |"
            )
    else:
        lines.append("本周无出场记录。")
    lines.append("")

    # Deviation analysis
    lines.extend(["## 四、偏差分析", ""])
    non_compliant = [e for e in exits if not e["compliant"]]
    if non_compliant:
        lines.append(f"**非合规出场共 {len(non_compliant)} 笔：**")
        lines.append("")
        for e in non_compliant:
            lines.append(
                f"- {e['stock_code']} {e['stock_name']}：{e['compliance_reason']}"
            )
    else:
        lines.append("本周所有出场均符合系统规则。")
    lines.append("")

    lines.extend(
        [
            "## 五、执行一致性建议",
            "",
            "- 信号执行率低于 80% 时，建议检查是否因盘中情绪波动导致漏单。",
            "- 出场规则遵守率低于 90% 时，建议加强止损纪律训练。",
            "- 实际盈亏显著偏离系统参考盈亏时，建议复盘出入场时机选择。",
            "",
            "> 免责声明：本报告仅用于交易一致性复盘，不构成投资建议。",
        ]
    )

    return "\n".join(lines)


def write_weekly_report(review: dict[str, Any]) -> Path:
    md = build_review_markdown(review)
    path = TRADE_REVIEW_DIR / f"weekly_review_{review['anchor_date']}.md"
    path.write_text(md, encoding="utf-8")
    return path


# ═════════════════════════════════════════════════════════════════════════════
# CLI handlers
# ═════════════════════════════════════════════════════════════════════════════


def handle_import_csv(csv_path: str) -> None:
    path = Path(csv_path)
    if not path.exists():
        print(f"错误：CSV 文件不存在 {csv_path}", file=sys.stderr)
        sys.exit(1)

    count = 0
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trade = TradeRecord(
                id=str(uuid.uuid4())[:8],
                date=row["date"],
                stock_code=row["stock_code"],
                stock_name=row.get("stock_name", ""),
                strategy=row["strategy"],
                action=row["action"].lower().strip(),
                price=float(row["price"]),
                shares=int(row["shares"]),
                notes=row.get("notes", ""),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            save_trade(trade)
            count += 1
    print(f"成功导入 {count} 条交易记录。")


def handle_add_trade(
    date: str,
    stock: str,
    strategy: str,
    action: str,
    price: float,
    shares: int,
    notes: str,
    stock_name: str | None = None,
) -> None:
    # 自动补全股票名称（尝试从最近 SOP 查找）
    name = stock_name or ""
    if not name:
        sop = load_sop(date)
        for c in sop.get("candidates", []):
            if c.get("stock_code") == stock:
                name = c.get("stock_name", "")
                break

    trade = TradeRecord(
        id=str(uuid.uuid4())[:8],
        date=date,
        stock_code=stock,
        stock_name=name,
        strategy=strategy,
        action=action.lower().strip(),
        price=price,
        shares=shares,
        notes=notes,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    save_trade(trade)
    print(f"已保存交易记录：{trade.id} | {trade.date} {trade.stock_code} {trade.action} @ {trade.price}")


def handle_list_trades() -> None:
    trades = load_trades()
    if not trades:
        print("暂无交易记录。")
        return
    print(f"{'ID':<10} {'日期':<12} {'代码':<12} {'策略':<18} {'动作':<8} {'价格':>10} {'股数':>8} {'备注'}")
    print("-" * 100)
    for t in trades[-50:]:  # 最近 50 条
        print(
            f"{t.id:<10} {t.date:<12} {t.stock_code:<12} {t.strategy:<18} {t.action:<8} {t.price:>10.2f} {t.shares:>8} {t.notes}"
        )


def handle_weekly_review(anchor_date: str) -> None:
    review = run_weekly_review(anchor_date)
    path = write_weekly_report(review)
    print(f"周度复盘报告已生成：{path}")
    print(f"  - 信号执行率：{review['signal_execution_rate']}%")
    print(f"  - 出场规则遵守率：{review['exit_compliance_rate']}%")
    print(f"  - 实际总盈亏：¥{review['total_actual_pnl']:,.2f}")
    if review.get("total_system_pnl") is not None:
        print(f"  - 系统参考盈亏：¥{review['total_system_pnl']:,.2f}")


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════


def main() -> int:
    parser = argparse.ArgumentParser(description="交易后复盘脚本")
    parser.add_argument("--import-csv", dest="import_csv", help="从 CSV 导入交易记录")
    parser.add_argument("--add-trade", action="store_true", help="录入单条交易")
    parser.add_argument("--date", help="交易日期（YYYY-MM-DD）")
    parser.add_argument("--stock", help="股票代码")
    parser.add_argument("--stock-name", default="", help="股票名称（可选）")
    parser.add_argument("--strategy", choices=["vcp", "ma2560", "bollinger_bandit"], help="策略")
    parser.add_argument("--action", choices=["entry", "exit"], help="动作")
    parser.add_argument("--price", type=float, help="成交价格")
    parser.add_argument("--shares", type=int, help="成交股数")
    parser.add_argument("--notes", default="", help="备注")
    parser.add_argument("--list-trades", action="store_true", help="列出所有交易记录")
    parser.add_argument("--week", help="生成周度复盘报告（传入锚定日期）")

    args = parser.parse_args()

    if args.import_csv:
        handle_import_csv(args.import_csv)
    elif args.add_trade:
        if not all([args.date, args.stock, args.strategy, args.action, args.price is not None, args.shares is not None]):
            print("错误：--add-trade 需要配合 --date --stock --strategy --action --price --shares 使用", file=sys.stderr)
            return 1
        handle_add_trade(
            args.date,
            args.stock,
            args.strategy,
            args.action,
            args.price,
            args.shares,
            args.notes,
            args.stock_name,
        )
    elif args.list_trades:
        handle_list_trades()
    elif args.week:
        handle_weekly_review(args.week)
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
