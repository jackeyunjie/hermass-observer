#!/usr/bin/env python3
"""Generate US strategy leverage comparison reports.

Reads backtest JSON outputs and produces:
  1. Per-strategy leverage reports (3 files)
  2. Summary leverage effect report (1 file)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "us_stock" / "backtest"
REPORT_DIR = ROOT / "outputs" / "us_stock"

STRATEGIES = ["vcp", "ma2560", "bollinger_bandit"]
LEVERAGE_LEVELS = [1.0, 2.0, 3.0]


def load_backtest(strategy: str, leverage: float, start: str, end: str) -> dict[str, Any] | None:
    """Load backtest result JSON."""
    fname = f"us_backtest_{strategy}_lev{leverage:.0f}x_{start.replace('-', '')}_{end.replace('-', '')}.json"
    path = OUT_DIR / fname
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def format_pct(val: float) -> str:
    return f"{val * 100:+.2f}%"


def format_num(val: float, decimals: int = 2) -> str:
    return f"{val:.{decimals}f}"


def generate_strategy_report(
    strategy: str,
    results: dict[float, dict[str, Any]],
    start_date: str,
    end_date: str,
) -> str:
    """Generate per-strategy leverage comparison markdown."""
    lines = [
        f"# {strategy.upper()} 策略杠杆回测报告",
        "",
        f"- **回测区间**: {start_date} ~ {end_date}",
        f"- **初始资金**: $1,000,000",
        f"- **最大持仓**: 10",
        f"- **借款利率**: 5%% 年化",
        f"- **爆仓阈值**: 净值 < 初始资金 × 25%%",
        "",
        "## 三档杠杆绩效对比",
        "",
        "| 指标 | 1倍杠杆 | 2倍杠杆 | 3倍杠杆 |",
        "|------|---------|---------|---------|",
    ]

    metrics = [
        ("总收益率", lambda r: format_pct(r.get("total_return", 0))),
        ("年化收益率", lambda r: format_pct(r.get("annualized_return", 0))),
        ("SPY基准收益", lambda r: format_pct(r.get("spy_return", 0))),
        ("超额收益", lambda r: format_pct(r.get("excess_return", 0))),
        ("最大回撤", lambda r: format_pct(-r.get("max_drawdown", 0))),
        ("夏普比率", lambda r: format_num(r.get("sharpe_ratio", 0), 3)),
        ("卡玛比率", lambda r: format_num(r.get("calmar_ratio", 0), 3)),
        ("总交易笔数", lambda r: str(r.get("total_trades", 0))),
        ("胜率", lambda r: f"{r.get('win_rate', 0) * 100:.2f}%"),
        ("平均收益", lambda r: format_pct(r.get("avg_pnl_pct", 0))),
        ("平均持仓天数", lambda r: format_num(r.get("avg_hold_days", 0), 1)),
        ("总借款成本", lambda r: f"${r.get('total_borrow_cost', 0):,.2f}"),
        ("最大借款额", lambda r: f"${r.get('max_borrowed', 0):,.2f}"),
        ("是否爆仓", lambda r: "⚠️ 是" if r.get("margin_called") else "否"),
    ]

    for label, fn in metrics:
        cells = [label]
        for lev in LEVERAGE_LEVELS:
            r = results.get(lev, {})
            cells.append(fn(r) if r else "N/A")
        lines.append(f"| {' | '.join(cells)} |")

    # Leverage sensitivity analysis
    lines.extend([
        "",
        "## 杠杆效应分析",
        "",
    ])

    r1 = results.get(1.0, {})
    r2 = results.get(2.0, {})
    r3 = results.get(3.0, {})

    if r1 and r2:
        ret_amplify = r2.get("total_return", 0) / r1.get("total_return", 1) if r1.get("total_return") else 0
        dd_amplify = r2.get("max_drawdown", 0) / r1.get("max_drawdown", 1) if r1.get("max_drawdown") else 0
        lines.append(f"- **2倍 vs 1倍**: 收益放大 {ret_amplify:.2f} 倍，回撤放大 {dd_amplify:.2f} 倍")

    if r1 and r3:
        ret_amplify = r3.get("total_return", 0) / r1.get("total_return", 1) if r1.get("total_return") else 0
        dd_amplify = r3.get("max_drawdown", 0) / r1.get("max_drawdown", 1) if r1.get("max_drawdown") else 0
        lines.append(f"- **3倍 vs 1倍**: 收益放大 {ret_amplify:.2f} 倍，回撤放大 {dd_amplify:.2f} 倍")

    if r2 and r3:
        ret_amplify = r3.get("total_return", 0) / r2.get("total_return", 1) if r2.get("total_return") else 0
        dd_amplify = r3.get("max_drawdown", 0) / r2.get("max_drawdown", 1) if r2.get("max_drawdown") else 0
        lines.append(f"- **3倍 vs 2倍**: 收益放大 {ret_amplify:.2f} 倍，回撤放大 {dd_amplify:.2f} 倍")

    # Exit reasons
    lines.extend(["", "## 出场原因分布 (1倍杠杆)", ""])
    if r1:
        for reason, count in r1.get("exit_reasons", {}).items():
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- 无数据")

    lines.extend([
        "",
        "## 净值曲线数据",
        "",
        "```json",
    ])

    # Export daily NAV for charting
    nav_data = {}
    for lev in LEVERAGE_LEVELS:
        r = results.get(lev, {})
        if r and r.get("daily_nav"):
            nav_data[f"{lev:.0f}x"] = [
                {"date": d["date"], "nav": d["nav"]}
                for d in r["daily_nav"]
            ]
    lines.append(json.dumps(nav_data, ensure_ascii=False, indent=2))
    lines.append("```")

    lines.extend([
        "",
        "---",
        "*本报告为研究用途，不构成投资建议。*",
        "",
    ])

    return "\n".join(lines)


def generate_summary_report(
    all_results: dict[str, dict[float, dict[str, Any]]],
    start_date: str,
    end_date: str,
) -> str:
    """Generate summary leverage effect report."""
    lines = [
        "# 美股三策略杠杆效应评估报告",
        "",
        f"- **回测区间**: {start_date} ~ {end_date}",
        f"- **初始资金**: $1,000,000/策略",
        f"- **借款利率**: 5%% 年化",
        f"- **爆仓阈值**: 净值 < 25%%",
        "",
        "## 一、各策略杠杆绩效总览",
        "",
        "| 策略 | 杠杆 | 总收益 | 最大回撤 | 夏普 | 胜率 | 交易笔数 | 爆仓 |",
        "|------|------|--------|----------|------|------|----------|------|",
    ]

    for strategy in STRATEGIES:
        for lev in LEVERAGE_LEVELS:
            r = all_results.get(strategy, {}).get(lev, {})
            if not r:
                lines.append(f"| {strategy} | {lev:.0f}x | N/A | N/A | N/A | N/A | N/A | N/A |")
                continue
            total_ret = format_pct(r.get("total_return", 0))
            max_dd = format_pct(-r.get("max_drawdown", 0))
            sharpe = format_num(r.get("sharpe_ratio", 0), 3)
            win_rate = f"{r.get('win_rate', 0) * 100:.1f}%"
            trades = str(r.get("total_trades", 0))
            margin = "⚠️" if r.get("margin_called") else "否"
            lines.append(f"| {strategy} | {lev:.0f}x | {total_ret} | {max_dd} | {sharpe} | {win_rate} | {trades} | {margin} |")

    lines.extend(["", "## 二、杠杆敏感度分析", ""])

    for strategy in STRATEGIES:
        lines.append(f"\n### {strategy.upper()}")
        r1 = all_results.get(strategy, {}).get(1.0, {})
        r2 = all_results.get(strategy, {}).get(2.0, {})
        r3 = all_results.get(strategy, {}).get(3.0, {})

        if not r1:
            lines.append("- 1倍杠杆数据缺失")
            continue

        ret1 = r1.get("total_return", 0)
        dd1 = r1.get("max_drawdown", 0)

        lines.append(f"- **1倍基准**: 收益 {format_pct(ret1)} / 回撤 {format_pct(-dd1)}")

        if r2:
            ret2 = r2.get("total_return", 0)
            dd2 = r2.get("max_drawdown", 0)
            ret_amp = ret2 / ret1 if ret1 != 0 else 0
            dd_amp = dd2 / dd1 if dd1 != 0 else 0
            lines.append(f"- **2倍效应**: 收益 {format_pct(ret2)} (放大 {ret_amp:.2f}x) / 回撤 {format_pct(-dd2)} (放大 {dd_amp:.2f}x)")

        if r3:
            ret3 = r3.get("total_return", 0)
            dd3 = r3.get("max_drawdown", 0)
            ret_amp = ret3 / ret1 if ret1 != 0 else 0
            dd_amp = dd3 / dd1 if dd1 != 0 else 0
            lines.append(f"- **3倍效应**: 收益 {format_pct(ret3)} (放大 {ret_amp:.2f}x) / 回撤 {format_pct(-dd3)} (放大 {dd_amp:.2f}x)")

        # Risk-adjusted assessment
        if r1 and r2 and r3:
            sharpe1 = r1.get("sharpe_ratio", 0)
            sharpe2 = r2.get("sharpe_ratio", 0)
            sharpe3 = r3.get("sharpe_ratio", 0)
            lines.append(f"- **夏普变化**: 1x={sharpe1:.3f} → 2x={sharpe2:.3f} → 3x={sharpe3:.3f}")

            if r3.get("margin_called"):
                lines.append("- ⚠️ **3倍杠杆触发爆仓，不建议使用**")
            elif r2.get("margin_called"):
                lines.append("- ⚠️ **2倍杠杆触发爆仓，建议最高1倍**")
            elif sharpe2 > sharpe1 and sharpe2 > 0:
                lines.append("- ✅ **2倍杠杆夏普提升，风险调整后收益最优**")
            elif sharpe1 > sharpe2 and sharpe1 > 0:
                lines.append("- ✅ **1倍杠杆夏普最高，不加杠杆更优**")
            else:
                lines.append("- ⚠️ **所有杠杆水平夏普均为负，当前环境不适合该策略**")

    lines.extend(["", "## 三、策略间杠杆适配排名", ""])

    # Rank strategies by Calmar at each leverage level
    for lev in LEVERAGE_LEVELS:
        lines.append(f"\n### {lev:.0f}x 杠杆 — 按卡玛比率排名")
        ranked = []
        for strategy in STRATEGIES:
            r = all_results.get(strategy, {}).get(lev, {})
            if r:
                calmar = r.get("calmar_ratio", 0)
                ranked.append((strategy, calmar, r.get("total_return", 0), r.get("max_drawdown", 0)))
        ranked.sort(key=lambda x: -x[1])
        for i, (strategy, calmar, ret, dd) in enumerate(ranked, 1):
            lines.append(f"{i}. **{strategy}**: 卡玛={calmar:.3f} | 收益={format_pct(ret)} | 回撤={format_pct(-dd)}")

    lines.extend(["", "## 四、建议杠杆区间", ""])

    for strategy in STRATEGIES:
        lines.append(f"\n### {strategy.upper()}")
        r1 = all_results.get(strategy, {}).get(1.0, {})
        r2 = all_results.get(strategy, {}).get(2.0, {})
        r3 = all_results.get(strategy, {}).get(3.0, {})

        if r3 and r3.get("margin_called"):
            lines.append("- **保守**: 1倍（3倍已爆仓）")
            lines.append("- **平衡**: 1倍（2倍存在爆仓风险）")
            lines.append("- **激进**: 不建议加杠杆")
        elif r2 and r2.get("margin_called"):
            lines.append("- **保守**: 1倍")
            lines.append("- **平衡**: 1倍")
            lines.append("- **激进**: 1-1.5倍（需严格风控）")
        elif r2 and r1:
            sharpe1 = r1.get("sharpe_ratio", 0)
            sharpe2 = r2.get("sharpe_ratio", 0)
            if sharpe2 > sharpe1 and sharpe2 > 0:
                lines.append("- **保守**: 1倍")
                lines.append("- **平衡**: 1.5-2倍")
                lines.append("- **激进**: 2倍")
            else:
                lines.append("- **保守**: 1倍")
                lines.append("- **平衡**: 1倍")
                lines.append("- **激进**: 1.5倍")
        else:
            lines.append("- **保守/平衡/激进**: 1倍（数据不足）")

    # A-share comparison placeholder
    lines.extend([
        "",
        "## 五、与 A 股对比",
        "",
        "| 策略 | 美股1x年化 | 美股1x回撤 | A股1x年化 | A股1x回撤 |",
        "|------|-----------|-----------|-----------|-----------|",
    ])

    for strategy in STRATEGIES:
        r1 = all_results.get(strategy, {}).get(1.0, {})
        us_ann = format_pct(r1.get("annualized_return", 0)) if r1 else "待跑"
        us_dd = format_pct(-r1.get("max_drawdown", 0)) if r1 else "待跑"
        lines.append(f"| {strategy} | {us_ann} | {us_dd} | 待对比 | 待对比 |")

    lines.extend([
        "",
        "---",
        "*本报告为研究用途，不构成投资建议。*",
        "",
    ])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2023-01-01")
    parser.add_argument("--end-date", default="2025-12-30")
    args = parser.parse_args()

    start = args.start_date
    end = args.end_date

    # Load all results
    all_results: dict[str, dict[float, dict[str, Any]]] = {}
    for strategy in STRATEGIES:
        all_results[strategy] = {}
        for lev in LEVERAGE_LEVELS:
            result = load_backtest(strategy, lev, start, end)
            if result:
                all_results[strategy][lev] = result
                print(f"Loaded: {strategy} @ {lev}x → {result.get('total_trades', 0)} trades, "
                      f"return={result.get('total_return', 0):.2%}, dd={result.get('max_drawdown', 0):.2%}")
            else:
                print(f"Missing: {strategy} @ {lev}x")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate per-strategy reports
    for strategy in STRATEGIES:
        if not all_results.get(strategy):
            continue
        md = generate_strategy_report(strategy, all_results[strategy], start, end)
        path = REPORT_DIR / f"us_backtest_{strategy}_leverage_1x_2x_3x.md"
        path.write_text(md, encoding="utf-8")
        print(f"Wrote: {path}")

    # Generate summary report
    summary_md = generate_summary_report(all_results, start, end)
    path = REPORT_DIR / "us_leverage_effect_report.md"
    path.write_text(summary_md, encoding="utf-8")
    print(f"Wrote: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
