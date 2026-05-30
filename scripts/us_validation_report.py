#!/usr/bin/env python3
"""US stock three-strategy validation report generator.

Integrates signal ledger, forward observation, and backtest data
to produce a comprehensive validation report.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
US_DIR = ROOT / "outputs" / "us_stock"
OUT_DIR = US_DIR / "validation_report"


def ymd(d: str) -> str:
    return d.replace("-", "")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_all_forward_observations() -> list[dict]:
    """Load all forward observation records."""
    obs_dir = US_DIR / "forward_observation"
    all_obs = []
    for f in sorted(obs_dir.glob("us_forward_obs_????????.json")):
        payload = json.loads(f.read_text(encoding="utf-8"))
        all_obs.extend(payload.get("rows", []))
    return all_obs


def load_backtest_result() -> dict:
    """Load latest backtest result."""
    return load_json(US_DIR / "backtest" / "us_backtest_latest.json")


def compute_fit_return_table(observations: list[dict], window: int = 20) -> dict:
    """Compute returns grouped by strategy_environment_fit."""
    by_fit = defaultdict(list)
    for obs in observations:
        if obs.get("label_status") != "labeled":
            continue
        fit = obs.get("strategy_environment_fit", "pending")
        excess = obs.get(f"forward_excess_return_{window}d")
        if excess is not None:
            by_fit[fit].append(excess)

    result = {}
    for fit, values in sorted(by_fit.items()):
        if not values:
            continue
        wins = [v for v in values if v > 0]
        result[fit] = {
            "n": len(values),
            "mean_excess": round(statistics.mean(values), 4),
            "win_rate": round(len(wins) / len(values), 4) if values else 0,
            "median_excess": round(statistics.median(values), 4),
        }
    return result


def compute_strategy_return_table(observations: list[dict], window: int = 20) -> dict:
    """Compute returns grouped by strategy."""
    by_strategy = defaultdict(list)
    for obs in observations:
        if obs.get("label_status") != "labeled":
            continue
        sid = obs.get("strategy_id", "unknown")
        excess = obs.get(f"forward_excess_return_{window}d")
        if excess is not None:
            by_strategy[sid].append(excess)

    result = {}
    for sid, values in sorted(by_strategy.items()):
        wins = [v for v in values if v > 0]
        result[sid] = {
            "n": len(values),
            "mean_excess": round(statistics.mean(values), 4),
            "win_rate": round(len(wins) / len(values), 4) if values else 0,
        }
    return result


def compute_lifecycle_return_table(observations: list[dict], window: int = 20) -> dict:
    """Compute returns grouped by lifecycle stage."""
    by_lc = defaultdict(list)
    for obs in observations:
        if obs.get("label_status") != "labeled":
            continue
        lc = obs.get("lifecycle_stage", "unknown")
        excess = obs.get(f"forward_excess_return_{window}d")
        if excess is not None:
            by_lc[lc].append(excess)

    result = {}
    for lc, values in sorted(by_lc.items()):
        wins = [v for v in values if v > 0]
        result[lc] = {
            "n": len(values),
            "mean_excess": round(statistics.mean(values), 4),
            "win_rate": round(len(wins) / len(values), 4) if values else 0,
        }
    return result


def build_validation_report(date_str: str) -> dict:
    """Build comprehensive US stock validation report."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load data
    observations = load_all_forward_observations()
    backtest = load_backtest_result()

    labeled = [o for o in observations if o.get("label_status") == "labeled"]
    total_signals = len(observations)
    labeled_count = len(labeled)

    # Compute tables
    fit_table = compute_fit_return_table(labeled)
    strategy_table = compute_strategy_return_table(labeled)
    lifecycle_table = compute_lifecycle_return_table(labeled)

    # Signal distribution
    signal_dist = Counter((o.get("strategy_id"), o.get("signal_type")) for o in observations)
    fit_dist = Counter(o.get("strategy_environment_fit") for o in observations)
    lifecycle_dist = Counter(o.get("lifecycle_stage") for o in observations)

    # Verdict
    fit_ordering_valid = False
    if "best_fit" in fit_table and "weak_fit" in fit_table:
        fit_ordering_valid = fit_table["best_fit"]["mean_excess"] > fit_table["weak_fit"]["mean_excess"]

    result = {
        "schema_version": "us_validation_v1",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_signals": total_signals,
            "labeled_signals": labeled_count,
            "label_rate": round(labeled_count / max(total_signals, 1), 4),
            "date_range": {
                "earliest": min((o["date"] for o in observations), default="N/A"),
                "latest": max((o["date"] for o in observations), default="N/A"),
            },
        },
        "signal_distribution": {
            "by_strategy_type": {f"{k[0]}:{k[1]}": v for k, v in sorted(signal_dist.items())},
            "by_fit_level": dict(sorted(fit_dist.items())),
            "by_lifecycle": dict(sorted(lifecycle_dist.items())),
        },
        "fit_return_table": fit_table,
        "strategy_return_table": strategy_table,
        "lifecycle_return_table": lifecycle_table,
        "backtest_summary": {
            "total_return": backtest.get("total_return"),
            "spy_return": backtest.get("spy_return"),
            "excess_return": backtest.get("excess_return"),
            "max_drawdown": backtest.get("max_drawdown"),
            "sharpe_ratio": backtest.get("sharpe_ratio"),
            "total_trades": backtest.get("total_trades"),
            "win_rate": backtest.get("win_rate"),
        } if backtest else None,
        "verdict": {
            "fit_ordering_valid": fit_ordering_valid,
            "overall": "pass" if fit_ordering_valid else "review_needed",
            "note": "US stock validation - forward observation accumulating",
        },
        "comparison_with_a_share": {
            "a_share_vcp_excess": 0.0167,
            "a_share_bollinger_vol0_excess": 0.0059,
            "us_vcp_excess": strategy_table.get("vcp", {}).get("mean_excess"),
            "us_bollinger_excess": strategy_table.get("bollinger_bandit", {}).get("mean_excess"),
        },
        "research_only": True,
    }

    # Write outputs
    out_json = OUT_DIR / f"us_validation_{ymd(date_str)}.json"
    out_latest = OUT_DIR / "us_validation_latest.json"
    text = json.dumps(result, ensure_ascii=False, indent=2)
    out_json.write_text(text, encoding="utf-8")
    out_latest.write_text(text, encoding="utf-8")

    # Write markdown
    md_lines = [
        f"# US Stock Validation Report — {date_str}",
        "",
        f"Generated: {result['generated_at']}",
        "",
        "## Summary",
        f"- Total signals: {total_signals}",
        f"- Labeled signals: {labeled_count}",
        f"- Label rate: {result['summary']['label_rate']:.1%}",
        "",
        "## Fit Level → Return Table (20d excess vs SPY)",
        "",
        "| Fit Level | n | Mean Excess | Win Rate | Median |",
        "|---|---:|---:|---:|---:|",
    ]
    for fit, stats in fit_table.items():
        md_lines.append(
            f"| {fit} | {stats['n']} | {stats['mean_excess']:.2%} | "
            f"{stats['win_rate']:.1%} | {stats['median_excess']:.2%} |"
        )

    md_lines.extend([
        "",
        "## Strategy Return Table (20d excess vs SPY)",
        "",
        "| Strategy | n | Mean Excess | Win Rate |",
        "|---|---:|---:|---:|",
    ])
    for sid, stats in strategy_table.items():
        md_lines.append(
            f"| {sid} | {stats['n']} | {stats['mean_excess']:.2%} | {stats['win_rate']:.1%} |"
        )

    md_lines.extend([
        "",
        "## Lifecycle Return Table",
        "",
        "| Lifecycle | n | Mean Excess | Win Rate |",
        "|---|---:|---:|---:|",
    ])
    for lc, stats in lifecycle_table.items():
        md_lines.append(
            f"| {lc} | {stats['n']} | {stats['mean_excess']:.2%} | {stats['win_rate']:.1%} |"
        )

    if backtest:
        md_lines.extend([
            "",
            "## Backtest Summary",
            f"- Total return: {backtest.get('total_return', 0):.2%}",
            f"- SPY return: {backtest.get('spy_return', 0):.2%}",
            f"- Excess: {backtest.get('excess_return', 0):.2%}",
            f"- Max drawdown: {backtest.get('max_drawdown', 0):.2%}",
            f"- Sharpe: {backtest.get('sharpe_ratio', 0):.3f}",
            f"- Trades: {backtest.get('total_trades', 0)}",
            f"- Win rate: {backtest.get('win_rate', 0):.2%}",
        ])

    md_lines.extend([
        "",
        "## Verdict",
        f"- Fit ordering valid: {fit_ordering_valid}",
        f"- Overall: {result['verdict']['overall']}",
        "",
        "## A-Share Comparison",
        f"- A-share VCP excess: +1.67%",
        f"- A-share Bollinger vol=0 excess: +0.59%",
        f"- US VCP excess: {strategy_table.get('vcp', {}).get('mean_excess', 'N/A')}",
        f"- US Bollinger excess: {strategy_table.get('bollinger_bandit', {}).get('mean_excess', 'N/A')}",
        "",
        "*Research-only. Not investment advice.*",
    ])

    md_path = OUT_DIR / f"us_validation_{ymd(date_str)}.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    result = build_validation_report(args.date)

    print(f"\nUS Stock Validation Report: {args.date}")
    print(f"  Total signals: {result['summary']['total_signals']}")
    print(f"  Labeled: {result['summary']['labeled_signals']}")
    print(f"  Fit ordering: {'VALID' if result['verdict']['fit_ordering_valid'] else 'REVIEW NEEDED'}")
    print(f"\nFit Return Table:")
    for fit, stats in result.get("fit_return_table", {}).items():
        print(f"  {fit}: n={stats['n']}, excess={stats['mean_excess']:.2%}, wr={stats['win_rate']:.1%}")
    print(f"\nStrategy Return Table:")
    for sid, stats in result.get("strategy_return_table", {}).items():
        print(f"  {sid}: n={stats['n']}, excess={stats['mean_excess']:.2%}, wr={stats['win_rate']:.1%}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
