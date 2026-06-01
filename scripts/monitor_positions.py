#!/usr/bin/env python3
"""持仓执行监控脚本 — 盘中跟踪持仓状态，自动检测止损/止盈/时间退出触发。

Usage:
    # 添加持仓
    python3 scripts/monitor_positions.py --add --stock 000997 --strategy vcp \
        --entry 13.50 --stop 12.69 --date 2026-05-22

    # 监控所有持仓（读取 foundation DB 最新数据）
    python3 scripts/monitor_positions.py --monitor --date 2026-05-22

    # 同时生成 HTML 报告
    python3 scripts/monitor_positions.py --monitor --date 2026-05-22 --html

Outputs:
    data/positions.json          — 持仓记录（用户手动标记的已入场交易）
    public/position_monitor.html — 可视化监控面板（可选）

合规声明：本脚本仅作研究参考，不构成投资建议。
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

# Import exit check functions from existing managers
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bollinger_execution_manager import BollingerPositionState, bb_full_exit_check
from ma2560_execution_manager import ma2560_exit_check
from vcp_exit_manager import VCPExitResult, vcp_exit_check

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("position_monitor")

ROOT = Path(__file__).resolve().parents[1]
POSITIONS_FILE = ROOT / "data" / "positions.json"
PUBLIC_DIR = ROOT / "public"
SOP_DIR = ROOT / "outputs" / "trading_sop"
FOUNDATION_DB_PATTERN = ROOT / "outputs" / "p116_foundation_*" / "p116_foundation.duckdb"

RESEARCH_ONLY_DISCLAIMER = (
    "Research-Only 声明：本监控仅为技术状态跟踪，不构成任何形式的投资建议。"
    "具体交易决策请基于自身风险承受能力独立判断。"
)


# ═════════════════════════════════════════════════════════════════════════════
# Data models
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class Position:
    stock_code: str
    stock_name: str = ""
    strategy: str = ""  # vcp | ma2560 | bollinger_bandit
    entry_price: float = 0.0
    entry_date: str = ""
    stop_price: float = 0.0
    stop_method: str = ""
    shares: int = 0
    added_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # Runtime fields (not persisted)
    current_close: float = 0.0
    current_date: str = ""
    hold_days: int = 0
    pnl_pct: float = 0.0
    status: str = "正常持有"  # 正常持有 / 止损触发 / 止盈触发 / 时间退出 / 假突破离场 / 接近止损
    exit_reason: str = ""
    exit_type: str = ""  # stop | profit | time | trailing | risk
    highest_since_entry: float = 0.0
    # Strategy-specific context
    pivot_point: float = 0.0
    contraction_low: float = 0.0
    entry_atr: float = 0.0
    ma25: float = 0.0
    ma60: float = 0.0
    bb_middle: float = 0.0
    bb_upper: float = 0.0
    current_atr: float = 0.0
    exit_ma: float = 0.0
    exit_ma_period: int = 0
    prev_above_upper: bool = False
    half_exited: bool = False


# ═════════════════════════════════════════════════════════════════════════════
# Persistence
# ═════════════════════════════════════════════════════════════════════════════


def load_positions() -> list[Position]:
    if not POSITIONS_FILE.exists():
        return []
    try:
        data = json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
        return [Position(**item) for item in data.get("positions", [])]
    except Exception as e:
        logger.warning("Failed to load positions: %s", e)
        return []


def save_positions(positions: list[Position]) -> None:
    POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().isoformat(),
        "disclaimer": RESEARCH_ONLY_DISCLAIMER,
        "positions": [asdict(p) for p in positions],
    }
    POSITIONS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved %d positions to %s", len(positions), POSITIONS_FILE)


# ═════════════════════════════════════════════════════════════════════════════
# Foundation DB helpers
# ═════════════════════════════════════════════════════════════════════════════


def find_foundation_db(date_str: str) -> Path | None:
    """Find the foundation DB for the given date (or latest available)."""
    date_ymd = date_str.replace("-", "")
    # Try exact date first
    exact = ROOT / "outputs" / f"p116_foundation_{date_ymd}" / "p116_foundation.duckdb"
    if exact.exists():
        return exact
    # Find latest available
    candidates = sorted(ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"), reverse=True)
    return candidates[0] if candidates else None


def fetch_latest_bars(db_path: Path, stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch latest daily bars for given stock codes."""
    if not db_path or not db_path.exists():
        logger.warning("Foundation DB not found: %s", db_path)
        return {}
    con = duckdb.connect(str(db_path), read_only=True)
    placeholders = ",".join(["?"] * len(stock_codes))
    query = f"""
        SELECT stock_code, date, open, high, low, close, volume
        FROM daily_bars
        WHERE stock_code IN ({placeholders})
          AND date = (SELECT MAX(date) FROM daily_bars)
    """
    rows = con.execute(query, stock_codes).fetchall()
    con.close()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        result[row[0]] = {
            "stock_code": row[0],
            "date": str(row[1]),
            "open": row[2],
            "high": row[3],
            "low": row[4],
            "close": row[5],
            "volume": row[6],
        }
    return result


def fetch_indicator_context(db_path: Path, stock_code: str, date_str: str) -> dict[str, Any]:
    """Fetch indicator context (MA, ATR, BB) for exit checks."""
    if not db_path or not db_path.exists():
        return {}
    con = duckdb.connect(str(db_path), read_only=True)
    # Try exact date match first, then latest available
    query = """
        SELECT atr14, bb_middle_20, bb_std_20, prev_close, prev_high, prev_low,
               bb_width_pct, trend, volatility, compression
        FROM timeframe_indicators
        WHERE stock_code = ? AND timeframe = 'D1'
          AND period_end <= ?
        ORDER BY period_end DESC
        LIMIT 1
    """
    rows = con.execute(query, [stock_code, date_str]).fetchall()
    if not rows:
        con.close()
        return {}
    row = rows[0]
    con.close()
    return {
        "atr14": row[0],
        "bb_middle": row[1],
        "bb_std": row[2],
        "prev_close": row[3],
        "prev_high": row[4],
        "prev_low": row[5],
        "bb_width_pct": row[6],
        "trend": row[7],
        "volatility": row[8],
        "compression": row[9],
    }


def fetch_price_history(db_path: Path, stock_code: str, since_date: str) -> list[dict[str, Any]]:
    """Fetch price history since entry date for hold_days and highest calculation."""
    if not db_path or not db_path.exists():
        return []
    con = duckdb.connect(str(db_path), read_only=True)
    query = """
        SELECT date, close, high
        FROM daily_bars
        WHERE stock_code = ? AND date >= ?
        ORDER BY date ASC
    """
    rows = con.execute(query, [stock_code, since_date]).fetchall()
    con.close()
    return [{"date": str(r[0]), "close": r[1], "high": r[2]} for r in rows]


def fetch_ma_values(db_path: Path, stock_code: str, date_str: str) -> dict[str, float]:
    """Fetch MA25 and MA60 from timeframe_indicators or compute from bars."""
    if not db_path or not db_path.exists():
        return {}
    con = duckdb.connect(str(db_path), read_only=True)
    # Try to get from indicators or compute from recent bars
    query = """
        SELECT close
        FROM daily_bars
        WHERE stock_code = ? AND date <= ?
        ORDER BY date DESC
        LIMIT 60
    """
    rows = con.execute(query, [stock_code, date_str]).fetchall()
    con.close()
    closes = [r[0] for r in rows if r[0] is not None]
    if len(closes) < 25:
        return {}
    ma25 = sum(closes[:25]) / 25
    ma60 = sum(closes[:60]) / 60 if len(closes) >= 60 else ma25
    return {"ma25": ma25, "ma60": ma60}


# ═════════════════════════════════════════════════════════════════════════════
# Exit check dispatchers
# ═════════════════════════════════════════════════════════════════════════════


def check_vcp_exit(pos: Position) -> tuple[str, str, str]:
    """Return (status, exit_reason, exit_type) for VCP position."""
    result = vcp_exit_check(
        entry_price=pos.entry_price,
        pivot_point=pos.pivot_point or pos.entry_price,
        contraction_low=pos.contraction_low or pos.entry_price * 0.94,
        entry_atr=pos.entry_atr or pos.entry_price * 0.03,
        current_close=pos.current_close,
        hold_days=pos.hold_days,
        highest_since_entry=pos.highest_since_entry or pos.entry_price,
    )
    if result is None:
        # Check proximity to stop
        stop_dist = (pos.current_close - pos.stop_price) / pos.stop_price if pos.stop_price > 0 else 999
        if 0 < stop_dist < 0.02:
            return "接近止损", f"距止损价仅 {stop_dist:.1%}", "proximity"
        return "正常持有", "", ""
    return "已触发", result.exit_reason, result.exit_type


def check_ma2560_exit(pos: Position) -> tuple[str, str, str]:
    """Return (status, exit_reason, exit_type) for 2560 position."""
    result = ma2560_exit_check(
        entry_price=pos.entry_price,
        current_close=pos.current_close,
        ma25=pos.ma25 or pos.entry_price * 0.95,
        ma60=pos.ma60 or pos.entry_price * 0.90,
        hold_days=pos.hold_days,
        half_exited=pos.half_exited,
    )
    if result is None:
        stop_dist = (pos.current_close - pos.stop_price) / pos.stop_price if pos.stop_price > 0 else 999
        if 0 < stop_dist < 0.02:
            return "接近止损", f"距止损价仅 {stop_dist:.1%}", "proximity"
        return "正常持有", "", ""
    return "已触发", result.exit_reason, result.exit_type


def check_bollinger_exit(pos: Position) -> tuple[str, str, str]:
    """Return (status, exit_reason, exit_type) for Bollinger Bandit position."""
    state = BollingerPositionState(
        entry_price=pos.entry_price,
        entry_date=pos.entry_date,
        entry_atr=pos.entry_atr or pos.entry_price * 0.02,
        half_exited=pos.half_exited,
        prev_above_upper=pos.prev_above_upper,
    )
    current_day = {"close": pos.current_close}
    ctx = {
        "hold_days": pos.hold_days,
        "atr": pos.current_atr or pos.entry_atr or pos.entry_price * 0.02,
        "bb_upper": pos.bb_upper or pos.entry_price * 1.05,
        "bb_middle": pos.bb_middle or pos.entry_price,
        "exit_ma": pos.exit_ma or pos.entry_price * 0.95,
        "exit_ma_period": pos.exit_ma_period or 50,
    }
    result = bb_full_exit_check(state, current_day, ctx)
    if result is None:
        stop_dist = (pos.current_close - pos.stop_price) / pos.stop_price if pos.stop_price > 0 else 999
        if 0 < stop_dist < 0.02:
            return "接近止损", f"距止损价仅 {stop_dist:.1%}", "proximity"
        return "正常持有", "", ""
    exit_type = result.get("exit_type", "stop")
    return "已触发", result.get("exit_reason", ""), exit_type


# ═════════════════════════════════════════════════════════════════════════════
# Core monitor logic
# ═════════════════════════════════════════════════════════════════════════════


def enrich_position(pos: Position, db_path: Path, current_date: str) -> Position:
    """Fetch latest data and compute runtime fields for a position."""
    # Normalize stock code
    code = pos.stock_code
    if "." not in code:
        # Try to guess exchange suffix
        if code.startswith(("6", "68")):
            code = f"{code}.SH"
        else:
            code = f"{code}.SZ"

    # Fetch latest bar
    bars = fetch_latest_bars(db_path, [code])
    bar = bars.get(code, {})
    if not bar:
        logger.warning("No price data for %s", code)
        pos.current_close = 0.0
        pos.status = "数据缺失"
        return pos

    pos.current_close = bar.get("close", 0.0)
    pos.current_date = bar.get("date", current_date)

    # Fetch price history for hold_days and highest
    history = fetch_price_history(db_path, code, pos.entry_date)
    pos.hold_days = len(history) - 1 if history else 0
    pos.highest_since_entry = max((h["high"] for h in history), default=pos.entry_price)

    # PnL
    pos.pnl_pct = (pos.current_close - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0

    # Fetch indicator context
    ctx = fetch_indicator_context(db_path, code, current_date)
    pos.entry_atr = ctx.get("atr14") or pos.entry_atr
    pos.bb_middle = ctx.get("bb_middle")
    pos.bb_upper = ctx.get("bb_middle", 0) + 2 * (ctx.get("bb_std") or 0)
    pos.current_atr = ctx.get("atr14")

    # Fetch MA values
    ma_vals = fetch_ma_values(db_path, code, current_date)
    pos.ma25 = ma_vals.get("ma25")
    pos.ma60 = ma_vals.get("ma60")

    # Compute exit MA for Bollinger
    if pos.hold_days > 0:
        period = max(10, 51 - pos.hold_days)
        pos.exit_ma_period = period
        # exit_ma will be computed from closes in check_bollinger_exit via ctx
        if pos.ma25 and pos.ma60:
            pos.exit_ma = pos.ma25 if period <= 25 else pos.ma60

    # Run strategy-specific exit check
    if pos.strategy == "vcp":
        pos.status, pos.exit_reason, pos.exit_type = check_vcp_exit(pos)
    elif pos.strategy == "ma2560":
        pos.status, pos.exit_reason, pos.exit_type = check_ma2560_exit(pos)
    elif pos.strategy == "bollinger_bandit":
        pos.status, pos.exit_reason, pos.exit_type = check_bollinger_exit(pos)
    else:
        pos.status = "未知策略"

    return pos


def monitor_positions(positions: list[Position], date_str: str) -> list[Position]:
    """Monitor all positions and return enriched list."""
    db_path = find_foundation_db(date_str)
    if not db_path:
        logger.error("No foundation DB found")
        return positions

    logger.info("Using foundation DB: %s", db_path)
    enriched = []
    for pos in positions:
        enriched.append(enrich_position(pos, db_path, date_str))
    return enriched


# ═════════════════════════════════════════════════════════════════════════════
# Output formatters
# ═════════════════════════════════════════════════════════════════════════════


def print_terminal_report(positions: list[Position]) -> None:
    """Print colored terminal report."""
    print(f"\n{'=' * 80}")
    print(f"  持仓监控报告 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 80}")
    print(f"  {RESEARCH_ONLY_DISCLAIMER}")
    print(f"{'=' * 80}")

    if not positions:
        print("  暂无持仓")
        return

    header = f"  {'代码':<12} {'策略':<14} {'入场价':>8} {'现价':>8} {'盈亏':>8} {'持有':>4} {'状态':<12} {'触发原因':<20}"
    print(header)
    print(f"  {'-' * 78}")

    for pos in positions:
        pnl_str = f"{pos.pnl_pct:+.1%}"
        status_color = (
            "\033[32m" if pos.status == "正常持有" else "\033[31m" if pos.status == "已触发" else "\033[33m"
        )
        reset = "\033[0m"
        line = (
            f"  {pos.stock_code:<12} {pos.strategy:<14} "
            f"{pos.entry_price:>8.2f} {pos.current_close:>8.2f} "
            f"{pnl_str:>8} {pos.hold_days:>4}d "
            f"{status_color}{pos.status:<10}{reset} {pos.exit_reason:<20}"
        )
        print(line)

    print(f"{'=' * 80}")
    triggered = [p for p in positions if p.status == "已触发"]
    holding = [p for p in positions if p.status == "正常持有"]
    proximity = [p for p in positions if p.status == "接近止损"]
    print(
        f"  总计: {len(positions)} | 正常持有: {len(holding)} | 接近止损: {len(proximity)} | 已触发: {len(triggered)}"
    )
    print(f"{'=' * 80}\n")


def generate_html(positions: list[Position]) -> str:
    """Generate HTML monitoring dashboard."""

    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    def status_badge(pos: Position) -> str:
        if pos.status == "正常持有":
            return f'<span style="background:#dcfce7;color:#166534;padding:2px 8px;border-radius:4px;font-size:12px;">正常持有</span>'
        if pos.status == "已触发":
            return f'<span style="background:#fee2e2;color:#991b1b;padding:2px 8px;border-radius:4px;font-size:12px;">已触发</span>'
        if pos.status == "接近止损":
            return f'<span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:12px;">接近止损</span>'
        return f'<span style="background:#f3f4f6;color:#4b5563;padding:2px 8px;border-radius:4px;font-size:12px;">{esc(pos.status)}</span>'

    def pnl_color(pnl: float) -> str:
        if pnl > 0:
            return f'<span style="color:#16a34a;font-weight:600;">{pnl:+.1%}</span>'
        if pnl < 0:
            return f'<span style="color:#dc2626;font-weight:600;">{pnl:+.1%}</span>'
        return f"<span>{pnl:+.1%}</span>"

    rows = []
    for pos in positions:
        exit_detail = f"{esc(pos.exit_reason)} ({esc(pos.exit_type)})" if pos.exit_reason else "-"
        rows.append(
            f"<tr>"
            f'<td><strong>{esc(pos.stock_code)}</strong><br><span style="color:#6b7280;font-size:12px;">{esc(pos.stock_name)}</span></td>'
            f"<td>{esc(pos.strategy)}</td>"
            f"<td>{pos.entry_price:.2f}</td>"
            f"<td>{pos.current_close:.2f}</td>"
            f"<td>{pnl_color(pos.pnl_pct)}</td>"
            f"<td>{pos.hold_days}</td>"
            f"<td>{status_badge(pos)}</td>"
            f"<td>{f'{pos.stop_price:.2f}' if pos.stop_price else '-'}</td>"
            f"<td>{esc(exit_detail)}</td>"
            f"</tr>"
        )

    triggered = [p for p in positions if p.status == "已触发"]
    holding = [p for p in positions if p.status == "正常持有"]
    proximity = [p for p in positions if p.status == "接近止损"]

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>持仓监控面板</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 1200px; margin: 40px auto; padding: 0 20px; line-height: 1.6; color: #333; }}
    .disclaimer {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px 16px; margin-bottom: 20px; font-size: 14px; color: #92400e; }}
    .summary {{ display: flex; gap: 16px; margin-bottom: 20px; }}
    .summary-card {{ background: #f8fafc; border: 1px solid #e1e6ef; border-radius: 8px; padding: 16px; flex: 1; text-align: center; }}
    .summary-card strong {{ display: block; font-size: 24px; margin-bottom: 4px; color: #1e293b; }}
    .summary-card span {{ font-size: 13px; color: #64748b; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 10px 12px; text-align: left; }}
    th {{ background: #f3f4f6; font-weight: 600; }}
    tr:nth-child(even) {{ background: #f9fafb; }}
    .meta {{ color: #6b7280; font-size: 12px; margin-top: 8px; }}
  </style>
</head>
<body>
  <div class="disclaimer">{RESEARCH_ONLY_DISCLAIMER}</div>
  <h1>持仓监控面板</h1>
  <p class="meta">生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
  <div class="summary">
    <div class="summary-card"><strong>{len(positions)}</strong><span>总持仓</span></div>
    <div class="summary-card"><strong style="color:#16a34a;">{len(holding)}</strong><span>正常持有</span></div>
    <div class="summary-card"><strong style="color:#f59e0b;">{len(proximity)}</strong><span>接近止损</span></div>
    <div class="summary-card"><strong style="color:#dc2626;">{len(triggered)}</strong><span>已触发</span></div>
  </div>
  <table>
    <thead>
      <tr>
        <th>代码/名称</th>
        <th>策略</th>
        <th>入场价</th>
        <th>现价</th>
        <th>盈亏</th>
        <th>持有天数</th>
        <th>状态</th>
        <th>止损价</th>
        <th>触发详情</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
</body>
</html>"""


# ═════════════════════════════════════════════════════════════════════════════
# CLI commands
# ═════════════════════════════════════════════════════════════════════════════


def cmd_add(args: argparse.Namespace) -> int:
    """Add a new position."""
    positions = load_positions()

    # Auto-fill from SOP if available
    stock_name = ""
    stop_method = ""
    if args.sop_date:
        sop_path = SOP_DIR / f"daily_trading_sop_{args.sop_date}.json"
        if sop_path.exists():
            try:
                sop_data = json.loads(sop_path.read_text(encoding="utf-8"))
                for c in sop_data.get("candidates", []):
                    if c.get("stock_code") == args.stock:
                        stock_name = c.get("stock_name", "")
                        if not args.stop:
                            args.stop = c.get("stop_price", 0.0)
                        stop_method = c.get("stop_method", "")
                        break
            except Exception as e:
                logger.warning("Failed to read SOP: %s", e)

    pos = Position(
        stock_code=args.stock,
        stock_name=stock_name,
        strategy=args.strategy,
        entry_price=args.entry,
        entry_date=args.date,
        stop_price=args.stop or 0.0,
        stop_method=stop_method,
        shares=args.shares or 0,
    )
    positions.append(pos)
    save_positions(positions)
    logger.info("Added position: %s %s @ %.2f", args.stock, args.strategy, args.entry)
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    """Monitor all positions."""
    positions = load_positions()
    if not positions:
        print("暂无持仓记录。使用 --add 添加持仓。")
        return 0

    positions = monitor_positions(positions, args.date)
    save_positions(positions)
    print_terminal_report(positions)

    if args.html:
        html_content = generate_html(positions)
        html_path = PUBLIC_DIR / "position_monitor.html"
        html_path.write_text(html_content, encoding="utf-8")
        logger.info("HTML report: %s", html_path)

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List all positions without monitoring."""
    positions = load_positions()
    print_terminal_report(positions)
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    """Remove a position by stock code."""
    positions = load_positions()
    original_len = len(positions)
    positions = [p for p in positions if p.stock_code != args.stock]
    if len(positions) == original_len:
        logger.warning("Position not found: %s", args.stock)
        return 1
    save_positions(positions)
    logger.info("Removed position: %s", args.stock)
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════


def main() -> int:
    parser = argparse.ArgumentParser(description="持仓执行监控")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # add
    add_parser = subparsers.add_parser("add", help="添加持仓")
    add_parser.add_argument("--stock", required=True, help="股票代码（如 000997 或 000997.SZ）")
    add_parser.add_argument("--strategy", required=True, choices=["vcp", "ma2560", "bollinger_bandit"])
    add_parser.add_argument("--entry", type=float, required=True, help="入场价")
    add_parser.add_argument("--stop", type=float, default=0.0, help="止损价")
    add_parser.add_argument("--shares", type=int, default=0, help="股数")
    add_parser.add_argument("--date", required=True, help="入场日期 YYYY-MM-DD")
    add_parser.add_argument("--sop-date", help="SOP日期（自动填充止损价和名称）")

    # monitor
    monitor_parser = subparsers.add_parser("monitor", help="监控持仓状态")
    monitor_parser.add_argument("--date", required=True, help="当前日期 YYYY-MM-DD")
    monitor_parser.add_argument("--html", action="store_true", help="生成 HTML 报告")

    # list
    subparsers.add_parser("list", help="列出所有持仓")

    # remove
    remove_parser = subparsers.add_parser("remove", help="移除持仓")
    remove_parser.add_argument("--stock", required=True, help="股票代码")

    args = parser.parse_args()

    if args.command == "add":
        return cmd_add(args)
    if args.command == "monitor":
        return cmd_monitor(args)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "remove":
        return cmd_remove(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
