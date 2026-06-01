#!/usr/bin/env python3
"""Diagnose State lifecycle features inside the all-three E/F pool.

This is a read-only research diagnostic. It consumes strategy_evaluation JSON
files and future excess-return labels from the foundation DB. It does not
change State formulas, strategy signals, or calibration thresholds.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from calibrate_strategy_evidence import (
    attach_labels,
    discover_evaluations,
    foundation_db_for,
    safe_float,
    ymd,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "strategy_evaluation"


def rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def corr(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    xbar = statistics.fmean(xs)
    ybar = statistics.fmean(ys)
    num = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))
    denx = math.sqrt(sum((x - xbar) ** 2 for x in xs))
    deny = math.sqrt(sum((y - ybar) ** 2 for y in ys))
    if denx == 0 or deny == 0:
        return None
    return num / (denx * deny)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    return corr(rank(xs), rank(ys))


def load_feature_samples(eval_paths: list[Path]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for path in eval_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        eval_date = payload.get("date")
        for row in payload.get("rows", []) or []:
            breakdown = row.get("factor_breakdown", {}) or {}
            features = {}
            features.update((breakdown.get("components_0_1") or {}))
            features.update((breakdown.get("state_lifecycle_0_1") or {}))
            samples.append(
                {
                    "date": eval_date,
                    "stock_code": row.get("stock_code"),
                    "stock_code_6": row.get("stock_code_6"),
                    "features": {k: safe_float(v) for k, v in features.items()},
                    "weighted_score": safe_float(row.get("evidence_score")) / 100.0,
                }
            )
    return samples


def feature_names(samples: list[dict[str, Any]]) -> list[str]:
    names: set[str] = set()
    for sample in samples:
        names.update(sample.get("features", {}).keys())
    preferred = [
        "state",
        "strategy",
        "pattern",
        "transition",
        "fundamental",
        "ef_purity",
        "expansion_ratio",
        "trend_ratio",
        "position_ratio",
        "volatility_ratio",
        "volatility_stability",
        "d1_recent_contraction_exit",
        "d1_prior_contraction_depth",
        "w1_recent_contraction_exit",
        "w1_prior_contraction_depth",
        "mn1_recent_contraction_exit",
        "mn1_prior_contraction_depth",
    ]
    return [name for name in preferred if name in names] + sorted(names - set(preferred))


def quantile_metrics(values: list[tuple[float, float]], buckets: int = 5) -> list[dict[str, Any]]:
    if not values:
        return []
    if len({item[0] for item in values}) < 2:
        return []
    ordered = sorted(values, key=lambda item: item[0])
    out = []
    for idx in range(buckets):
        start = int(len(ordered) * idx / buckets)
        end = int(len(ordered) * (idx + 1) / buckets)
        chunk = ordered[start:end]
        ys = [item[1] for item in chunk]
        wins = [v for v in ys if v > 0]
        out.append(
            {
                "bucket": idx + 1,
                "n": len(chunk),
                "feature_min": chunk[0][0] if chunk else None,
                "feature_max": chunk[-1][0] if chunk else None,
                "mean_excess": statistics.fmean(ys) if ys else None,
                "win_rate": len(wins) / len(ys) if ys else None,
            }
        )
    return out


def diagnose(args: argparse.Namespace) -> dict[str, Any]:
    eval_paths = discover_evaluations(args.start_date, args.end_date)
    samples = load_feature_samples(eval_paths)
    db_path = args.foundation_db or foundation_db_for(args.end_date)
    labeled, label_diag = attach_labels(samples, db_path, args.windows)

    names = feature_names(labeled)
    diagnostics: dict[str, Any] = {}
    for name in names:
        item: dict[str, Any] = {}
        for window in args.windows:
            pairs = [
                (
                    safe_float(sample.get("features", {}).get(name)),
                    safe_float(sample.get(f"excess_ret_{window}d")),
                )
                for sample in labeled
                if sample.get(f"excess_ret_{window}d") is not None and name in sample.get("features", {})
            ]
            xs = [x for x, _ in pairs]
            ys = [y for _, y in pairs]
            item[f"{window}d"] = {
                "n": len(pairs),
                "spearman_ic": spearman(xs, ys),
                "pearson_ic": corr(xs, ys),
                "quantiles": quantile_metrics(pairs, args.buckets) if window == args.primary_window else [],
            }
        diagnostics[name] = item

    return {
        "schema_version": "state_lifecycle_diagnostic_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "history": {"start_date": args.start_date, "end_date": args.end_date},
        "evaluation_dates": len(eval_paths),
        "labeled_dates": len({sample["date"] for sample in labeled}),
        "samples_labeled": len(labeled),
        "label_windows": args.windows,
        "primary_window": args.primary_window,
        "foundation_db": str(db_path),
        "label_diagnostics": label_diag,
        "features": diagnostics,
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# State Lifecycle Diagnostic - {result['history']['end_date']}",
        "",
        f"- Evaluation dates: `{result['evaluation_dates']}`",
        f"- Labeled dates: `{result['labeled_dates']}`",
        f"- Labeled samples: `{result['samples_labeled']}`",
        f"- Primary window: `{result['primary_window']}d`",
        "",
        "## Feature IC",
        "",
        "| feature | 5d Spearman | 10d Spearman | 20d Spearman |",
        "|---|---:|---:|---:|",
    ]
    for name, item in result["features"].items():
        vals = []
        for window in [5, 10, 20]:
            value = item.get(f"{window}d", {}).get("spearman_ic")
            vals.append("" if value is None else f"{value:.6f}")
        lines.append(f"| {name} | {vals[0]} | {vals[1]} | {vals[2]} |")
    lines.append("")
    lines.append("## Primary Window Quantiles")
    for name, item in result["features"].items():
        quantiles = item.get(f"{result['primary_window']}d", {}).get("quantiles") or []
        if not quantiles:
            continue
        lines.extend(
            [
                "",
                f"### {name}",
                "",
                "| bucket | n | min | max | mean excess | win rate |",
                "|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in quantiles:
            mean = row.get("mean_excess")
            win = row.get("win_rate")
            lines.append(
                f"| {row['bucket']} | {row['n']} | {row['feature_min']:.4f} | {row['feature_max']:.4f} | "
                f"{'' if mean is None else f'{mean:.6f}'} | {'' if win is None else f'{win:.4f}'} |"
            )
    lines.append("")
    return "\n".join(lines)


def write_outputs(result: dict[str, Any], date_tag: str) -> dict[str, str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / f"state_lifecycle_diagnostic_{date_tag}.json"
    md_path = OUT_DIR / f"state_lifecycle_diagnostic_{date_tag}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose State lifecycle features in all-three E/F strategy evaluations."
    )
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--foundation-db", type=Path)
    parser.add_argument("--windows", type=int, nargs="*", default=[5, 10, 20])
    parser.add_argument("--primary-window", type=int, default=20)
    parser.add_argument("--buckets", type=int, default=5)
    args = parser.parse_args()

    result = diagnose(args)
    outputs = write_outputs(result, ymd(args.end_date))
    print(
        json.dumps(
            {
                "ok": True,
                "evaluation_dates": result["evaluation_dates"],
                "labeled_dates": result["labeled_dates"],
                "samples_labeled": result["samples_labeled"],
                "outputs": outputs,
                "research_only": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
