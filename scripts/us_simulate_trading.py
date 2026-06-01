#!/usr/bin/env python3
"""美股三策略模拟交易 — 直接复用 load_state_data_from_duckdb + 策略信号函数。

US-specific: 同日收盘价入场 / 无涨跌停 / 1 股最小单位 / $0.01 佣金/股

用法:
  python3 scripts/us_simulate_trading.py
  python3 scripts/us_simulate_trading.py --start 2020-01-01 --end 2025-12-30 --capital 1000000
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import date as date_type
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (ROOT, SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from backtest.engine import load_state_data_from_duckdb
from backtest.strategy_signals.vcp import vcp_signal
from backtest.strategy_signals.ma2560 import ma2560_signal
from backtest.strategy_signals.bollinger_bandit import bollinger_bandit_signal
from vcp_exit_manager import vcp_exit_check
from ma2560_execution_manager import ma2560_exit_check
from bollinger_execution_manager import bb_full_exit_check
from position_sizing import calculate_dynamic_position

US_DB = ROOT / "outputs" / "us_stock" / "us_foundation.duckdb"
OUT_DIR = ROOT / "outputs" / "us_stock" / "simulation"
MAX_POS = 8
COMM = 0.01  # per share


def run_sim(start="2019-01-01", end="2025-12-30", capital=1_000_000.0):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    state_by_date = load_state_data_from_duckdb(US_DB, start, end)
    dates = sorted(state_by_date.keys())
    print(f"Loaded {len(dates)} trading days, {sum(len(v) for v in state_by_date.values()):,} state rows")

    # Generate signals per day — mimic strategy_signal_ledger logic
    signals_by_date: dict[str, dict[str, list[tuple[str, float, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for d in dates:
        for row in state_by_date[d]:
            close = row.get("close", 0)
            if close <= 0:
                continue
            # Ensure atr14 key exists (VCP expects it; engine key is 'd1_atr')
            if "atr14" not in row:
                row["atr14"] = row.get("d1_atr", close * 0.02)
            # Alias engine keys → signal function expected keys
            row.setdefault("volume_ma_50", row.get("avg_volume_50d", 0))
            row.setdefault("high_10d", row.get("high_10d_prev", close))
            for fn, sid in [
                (vcp_signal, "vcp"),
                (ma2560_signal, "ma2560"),
                (bollinger_bandit_signal, "bollinger_bandit"),
            ]:
                r = fn(row, row)
                if r:
                    raw_label, strength = r
                    signals_by_date[d][row["stock_code"]].append((sid, float(strength), raw_label))

    # Simulation
    cash = capital
    positions: dict[str, dict] = {}
    trades: list[dict] = []
    curve: list[dict] = []

    for d in dates:
        day_states = {r["stock_code"]: r for r in state_by_date[d]}
        day_close = {c: s["close"] for c, s in day_states.items() if s.get("close", 0) > 0}

        # Mark-to-market
        tot_val = cash
        for pos in positions.values():
            px = day_close.get(pos["stock_code"], pos["entry_price"])
            pos["cur_px"] = px
            pos["pnl"] = (px - pos["entry_price"]) / pos["entry_price"] if pos["entry_price"] > 0 else 0
            tot_val += px * pos["shares"]

        # Exit checks
        for code, pos in list(positions.items()):
            px = day_close.get(code, pos["entry_price"])
            if px <= 0:
                continue
            s = day_states.get(code, {})
            hold_days = (date_type.fromisoformat(d) - date_type.fromisoformat(pos["entry_date"])).days

            ctx = {
                "hold_days": hold_days,
                "atr": pos.get("entry_atr", 0),
                "pivot_point": pos.get("pivot", pos["entry_price"]),
                "contraction_low": pos.get("con_low", pos["entry_price"] * 0.94),
                "ma25": pos.get("ma25", 0),
                "ma60": pos.get("ma60", 0),
                "bb_upper": pos.get("bb_up", 0),
                "bb_middle": pos.get("bb_mid", 0),
                "entry_atr": pos.get("entry_atr", 0),
            }
            fn_exit = {
                "vcp": vcp_exit_check,
                "ma2560": ma2560_exit_check,
                "bollinger_bandit": bb_full_exit_check,
            }.get(pos["strategy"])
            result = None
            if fn_exit:
                try:
                    result = fn_exit(
                        pos, {"close": px, "open": px, "high": px, "low": px, "volume": 0, **s}, ctx
                    )
                except Exception:
                    pass
            if result:
                gross = (px - pos["entry_price"]) * pos["shares"]
                net = gross - COMM * pos["shares"] * 2
                cash += px * pos["shares"] - COMM * pos["shares"]
                trades.append(
                    {
                        "stock_code": code,
                        "strategy": pos["strategy"],
                        "entry_date": pos["entry_date"],
                        "entry_price": pos["entry_price"],
                        "exit_date": d,
                        "exit_price": round(px, 2),
                        "shares": pos["shares"],
                        "hold_days": hold_days,
                        "exit_reason": result.get("exit_reason", "?"),
                        "gross_pnl": round(gross, 2),
                        "net_pnl": round(net, 2),
                        "return_pct": round((px / pos["entry_price"] - 1) * 100, 2),
                    }
                )
                del positions[code]

        # Entries
        sig = signals_by_date.get(d, {})
        cap = MAX_POS - len(positions)
        if cap > 0 and sig:
            scored = []
            for code, sigs in sig.items():
                if code in positions:
                    continue
                px = day_close.get(code, 0)
                if px <= 0:
                    continue
                for sid, st, raw in sigs:
                    scored.append((st, code, sid, raw, px))
            scored.sort(key=lambda x: x[0], reverse=True)

            for st, code, sid, raw, px in scored[:cap]:
                if len(positions) >= MAX_POS:
                    break
                risk = (
                    calculate_dynamic_position("undetermined", 1.0, "复苏", "适配")["per_trade_risk_pct"]
                    / 100
                )
                risk_amt = capital * risk
                stop = px * 0.95
                rps = abs(px - stop)
                if rps <= 0:
                    continue
                sh = max(1, int(risk_amt / rps))
                cost = px * sh + COMM * sh
                if cost > cash:
                    sh = max(1, int(cash * 0.95 / (px + COMM)))
                    cost = px * sh + COMM * sh
                if sh <= 0 or cost > cash:
                    continue
                cash -= cost
                s = day_states.get(code, {})
                positions[code] = {
                    "stock_code": code,
                    "strategy": sid,
                    "entry_date": d,
                    "entry_price": px,
                    "shares": sh,
                    "stop_price": stop,
                    "entry_atr": s.get("d1_atr", 0),
                    "pivot": s.get("d1_sr_resistance", px),
                    "con_low": s.get("d1_sr_support", px * 0.94),
                    "ma25": s.get("ma25", 0),
                    "ma60": s.get("ma60", 0),
                    "bb_up": s.get("bb_upper_50_1", 0),
                    "bb_mid": s.get("ma50", 0),
                    "cur_px": px,
                    "pnl": 0.0,
                }
                trades.append(
                    {
                        "stock_code": code,
                        "strategy": sid,
                        "entry_date": d,
                        "entry_price": round(px, 2),
                        "exit_date": "",
                        "exit_price": 0,
                        "shares": sh,
                        "hold_days": 0,
                        "exit_reason": "open",
                        "gross_pnl": 0,
                        "net_pnl": round(-COMM * sh, 2),
                        "return_pct": 0,
                    }
                )

        pos_val = sum(p["cur_px"] * p["shares"] for p in positions.values())
        curve.append(
            {
                "date": d,
                "nav": round((cash + pos_val) / capital, 6),
                "position_count": len(positions),
                "cash": round(cash, 2),
                "total_assets": round(cash + pos_val, 2),
            }
        )

    # Close remaining
    for code, pos in list(positions.items()):
        px = pos.get("cur_px", pos["entry_price"])
        gross = (px - pos["entry_price"]) * pos["shares"]
        net = gross - COMM * pos["shares"]
        cash += px * pos["shares"] - COMM * pos["shares"]
        trades.append(
            {
                "stock_code": code,
                "strategy": pos["strategy"],
                "entry_date": pos["entry_date"],
                "entry_price": pos["entry_price"],
                "exit_date": dates[-1],
                "exit_price": round(px, 2),
                "shares": pos["shares"],
                "hold_days": 0,
                "exit_reason": "sim_end",
                "gross_pnl": round(gross, 2),
                "net_pnl": round(net, 2),
                "return_pct": round((px / pos["entry_price"] - 1) * 100, 2),
            }
        )

    # Stats
    done = [t for t in trades if t["exit_reason"] not in ("open",)]
    w = [t for t in done if t["net_pnl"] > 0]
    l = [t for t in done if t["net_pnl"] <= 0]
    wr = len(w) / len(done) * 100 if done else 0
    avg_w = sum(t["net_pnl"] for t in w) / len(w) if w else 0
    avg_l = abs(sum(t["net_pnl"] for t in l) / len(l)) if l else 0
    payoff = avg_w / avg_l if avg_l > 0 else 0
    tot_ret = (cash - capital) / capital * 100
    navs = [c["nav"] for c in curve]
    peak = navs[0] if navs else 1.0
    max_dd = 0.0
    for n in navs:
        if n > peak:
            peak = n
        dd = (peak - n) / peak * 100
        if dd > max_dd:
            max_dd = dd
    dr = [(navs[i] / navs[i - 1] - 1) for i in range(1, len(navs))]
    avg_dr = sum(dr) / len(dr) if dr else 0
    std_dr = (sum((r - avg_dr) ** 2 for r in dr) / len(dr)) ** 0.5 if dr else 0
    sharpe = ((avg_dr * 252 - 0.02) / (std_dr * math.sqrt(252))) if std_dr > 0 else 0
    hd = [t["hold_days"] for t in done if t["hold_days"] > 0]
    avg_hd = sum(hd) / len(hd) if hd else 0

    # Write
    eq_p = OUT_DIR / "equity_curve.csv"
    with eq_p.open("w", newline="") as f:
        wc = csv.DictWriter(f, ["date", "nav", "position_count", "cash", "total_assets"])
        wc.writeheader()
        wc.writerows(curve)

    tr_p = OUT_DIR / "trade_log.csv"
    with tr_p.open("w", newline="") as f:
        wc = csv.DictWriter(f, list(trades[0].keys()) if trades else [])
        wc.writeheader()
        wc.writerows(trades)

    # Perf markdown
    md = f"""# 美股三策略模拟交易绩效报告

**区间**: {start} ~ {end}  |  **本金**: ${capital:,.0f}

| 指标 | 数值 |
|------|------|
| 总收益率 | {tot_ret:+.2f}% |
| 最终资金 | ${cash:,.2f} |
| 交易笔数 | {len(done)} |
| 胜率 | {wr:.1f}% ({len(w)}/{len(done)}) |
| 盈亏比 | {payoff:.2f} |
| 最大回撤 | {max_dd:.2f}% |
| 夏普比率 | {sharpe:.2f} |
| 平均持仓 | {avg_hd:.0f} 天 |

## 策略分布

| 策略 | 笔数 | 胜率 | 平均盈亏 |
|------|------|------|----------|
"""
    ss: dict[str, list] = defaultdict(list)
    for t in done:
        ss[t["strategy"]].append(t["net_pnl"])
    for sid, pnls in sorted(ss.items()):
        swr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
        md += f"| {sid} | {len(pnls)} | {swr:.1f}% | ${sum(pnls) / len(pnls):,.0f} |\n"
    md += "\n---\n*Research-Only — 历史模拟，不构成交易建议。*\n"
    pm = OUT_DIR / "performance_summary.md"
    pm.write_text(md)

    return {
        "total_return": round(tot_ret, 2),
        "trades": len(done),
        "win_rate": round(wr, 1),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_dd, 2),
        "equity_curve": str(eq_p),
        "trade_log": str(tr_p),
        "performance": str(pm),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2025-12-30")
    ap.add_argument("--capital", type=float, default=1_000_000)
    a = ap.parse_args()
    r = run_sim(a.start, a.end, a.capital)
    print(json.dumps(r, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
