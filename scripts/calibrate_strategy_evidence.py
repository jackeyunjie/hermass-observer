#!/usr/bin/env python3
"""Calibrate strategy evidence score thresholds from historical labels.

This script is deliberately conservative:
- it consumes only existing strategy_evaluation JSON files and foundation prices
- it writes calibration reports/configs under outputs/strategy_evaluation
- it refuses to optimize thresholds when there are too few dates or samples

It does not modify State, State cache, strategy evidence, or recommendation
weights.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "strategy_evidence_calibration_default.json"
OUT_DIR = ROOT / "outputs" / "strategy_evaluation"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def code6(value: Any) -> str:
    text = str(value or "").upper().strip()
    digits = "".join(ch for ch in text.split(".", 1)[0] if ch.isdigit())
    return digits[-6:] if digits else text


def parse_eval_date(path: Path) -> str | None:
    stem = path.stem
    prefix = "strategy_evaluation_"
    if not stem.startswith(prefix):
        return None
    raw = stem.removeprefix(prefix)
    if raw == "latest" or len(raw) != 8 or not raw.isdigit():
        return None
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"


def discover_evaluations(start_date: str, end_date: str) -> list[Path]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    paths = []
    for path in sorted(OUT_DIR.glob("strategy_evaluation_*.json")):
        d = parse_eval_date(path)
        if not d:
            continue
        dd = date.fromisoformat(d)
        if start <= dd <= end:
            paths.append(path)
    return paths


def foundation_db_for(end_date: str) -> Path:
    exact = ROOT / "outputs" / f"p116_foundation_{ymd(end_date)}" / "p116_foundation.duckdb"
    if exact.exists():
        return exact
    candidates = sorted(ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"))
    if not candidates:
        raise FileNotFoundError("No p116 foundation DB found under outputs/")
    return candidates[-1]


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def weighted_score(row: dict[str, Any], weights: dict[str, float]) -> float:
    comp = row.get("factor_breakdown", {}).get("components_0_1", {})
    denom = sum(max(0.0, safe_float(v)) for v in weights.values()) or 1.0
    total = 0.0
    for key, weight in weights.items():
        total += safe_float(comp.get(key)) * max(0.0, safe_float(weight))
    return max(0.0, min(1.0, total / denom))


def load_samples(eval_paths: list[Path], weights: dict[str, float]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for path in eval_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        eval_date = payload.get("date") or parse_eval_date(path)
        for row in payload.get("rows", []) or []:
            samples.append(
                {
                    "date": eval_date,
                    "stock_code": row.get("stock_code"),
                    "stock_code_6": code6(row.get("stock_code")),
                    "evidence_score_raw": safe_float(row.get("evidence_score")) / 100.0,
                    "weighted_score": weighted_score(row, weights),
                    "factors": row.get("factor_breakdown", {}).get("components_0_1", {}),
                    "tier_original": row.get("evidence_tier"),
                }
            )
    return samples


def attach_labels(
    samples: list[dict[str, Any]], db_path: Path, windows: list[int]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not samples:
        return [], {"label_status": "no_samples"}

    dates = sorted({str(s["date"]) for s in samples if s.get("date")})
    start = min(date.fromisoformat(dates[0]), date.fromisoformat(dates[-1]))
    end = date.fromisoformat(dates[-1]) + timedelta(days=max(windows) * 3 + 10)
    con = duckdb.connect(str(db_path), read_only=True)
    price_rows = con.execute(
        """
        SELECT stock_code, date::VARCHAR AS date, close
        FROM daily_bars
        WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        ORDER BY stock_code, date
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    con.close()

    by_code: dict[str, list[tuple[str, float]]] = defaultdict(list)
    market_by_date: dict[str, list[float]] = defaultdict(list)
    for code, d, close in price_rows:
        if close is None or close <= 0:
            continue
        by_code[code6(code)].append((d, float(close)))
        market_by_date[d].append(float(close))

    # Equal-weight benchmark from all stocks with a valid D to D+w return.
    market_return_cache: dict[tuple[str, int], float | None] = {}

    def future_return(code: str, d: str, window: int) -> float | None:
        series = by_code.get(code6(code), [])
        if not series:
            return None
        idx = next((i for i, item in enumerate(series) if item[0] >= d), None)
        if idx is None or idx + window >= len(series):
            return None
        entry = series[idx][1]
        exit_price = series[idx + window][1]
        if entry <= 0:
            return None
        return exit_price / entry - 1.0

    def market_return(d: str, window: int) -> float | None:
        key = (d, window)
        if key in market_return_cache:
            return market_return_cache[key]
        vals = []
        for code in by_code:
            r = future_return(code, d, window)
            if r is not None and math.isfinite(r):
                vals.append(r)
        if not vals:
            market_return_cache[key] = None
            return None
        out = statistics.fmean(vals)
        market_return_cache[key] = out
        return out

    labeled = []
    missing_by_window = Counter()
    for sample in samples:
        item = dict(sample)
        ok_any = False
        for window in windows:
            ret = future_return(sample["stock_code_6"], sample["date"], window)
            bench = market_return(sample["date"], window)
            if ret is None or bench is None:
                missing_by_window[window] += 1
                item[f"ret_{window}d"] = None
                item[f"excess_ret_{window}d"] = None
                continue
            item[f"ret_{window}d"] = ret
            item[f"excess_ret_{window}d"] = ret - bench
            ok_any = True
        if ok_any:
            labeled.append(item)

    diagnostics = {
        "price_db": str(db_path),
        "price_rows": len(price_rows),
        "samples_in": len(samples),
        "samples_labeled": len(labeled),
        "missing_by_window": dict(missing_by_window),
        "date_count": len(dates),
        "date_range": [dates[0], dates[-1]] if dates else [],
    }
    return labeled, diagnostics


def rank_ic(samples: list[dict[str, Any]], window: int) -> float | None:
    pairs = [
        (safe_float(s.get("weighted_score")), safe_float(s.get(f"excess_ret_{window}d")))
        for s in samples
        if s.get(f"excess_ret_{window}d") is not None
    ]
    if len(pairs) < 3:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    xbar = statistics.fmean(xs)
    ybar = statistics.fmean(ys)
    num = sum((x - xbar) * (y - ybar) for x, y in pairs)
    denx = math.sqrt(sum((x - xbar) ** 2 for x in xs))
    deny = math.sqrt(sum((y - ybar) ** 2 for y in ys))
    if denx == 0 or deny == 0:
        return None
    return num / (denx * deny)


def grade_for(score: float, thresholds: dict[str, float]) -> str:
    if score >= thresholds["A_min"]:
        return "A"
    if score >= thresholds["B_min"]:
        return "B"
    if score >= thresholds["C_min"]:
        return "C"
    return "watch"


def grade_metrics(samples: list[dict[str, Any]], thresholds: dict[str, float], window: int) -> dict[str, Any]:
    by_grade: dict[str, list[float]] = defaultdict(list)
    for s in samples:
        val = s.get(f"excess_ret_{window}d")
        if val is None:
            continue
        by_grade[grade_for(s["weighted_score"], thresholds)].append(float(val))

    out = {}
    for grade in ["A", "B", "C", "watch"]:
        vals = by_grade.get(grade, [])
        wins = [v for v in vals if v > 0]
        losses = [v for v in vals if v < 0]
        out[grade] = {
            "n": len(vals),
            "mean_excess": statistics.fmean(vals) if vals else None,
            "win_rate": len(wins) / len(vals) if vals else None,
            "payoff_ratio": (
                statistics.fmean(wins) / abs(statistics.fmean(losses))
                if wins and losses and statistics.fmean(losses) != 0
                else None
            ),
        }
    return out


def monotonic_score(metrics: dict[str, Any], min_samples: int) -> float:
    means = [metrics[g]["mean_excess"] for g in ["A", "B", "C", "watch"]]
    counts = [metrics[g]["n"] for g in ["A", "B", "C", "watch"]]
    if any(v is None for v in means):
        return -999.0
    penalty = sum(max(0, min_samples - n) for n in counts) * 0.001
    return (means[0] - means[1]) + (means[1] - means[2]) + (means[2] - means[3]) - penalty


def monotonic_blockers(metrics: dict[str, Any], min_samples: int, require_monotonic: bool) -> list[str]:
    blockers: list[str] = []
    for grade in ["A", "B", "C", "watch"]:
        n = int(metrics.get(grade, {}).get("n") or 0)
        if n < min_samples:
            blockers.append(f"{grade}_samples {n} < min_samples_per_grade {min_samples}")

    if require_monotonic:
        means = {grade: metrics.get(grade, {}).get("mean_excess") for grade in ["A", "B", "C", "watch"]}
        if any(value is None for value in means.values()):
            blockers.append("grade_mean_excess_missing")
        elif not (means["A"] > means["B"] > means["C"] > means["watch"]):
            blockers.append(
                "grade_mean_excess_not_monotonic "
                f"A={means['A']:.6f}, B={means['B']:.6f}, C={means['C']:.6f}, watch={means['watch']:.6f}"
            )
    return blockers


def search_thresholds(samples: list[dict[str, Any]], window: int, min_samples: int) -> dict[str, Any]:
    candidates = [x / 100.0 for x in range(30, 96, 5)]
    best: dict[str, Any] | None = None
    for a in candidates:
        for b in candidates:
            for c in candidates:
                if not (a > b > c):
                    continue
                thresholds = {"A_min": a, "B_min": b, "C_min": c, "watch_below": c}
                metrics = grade_metrics(samples, thresholds, window)
                score = monotonic_score(metrics, min_samples)
                if best is None or score > best["objective_score"]:
                    best = {"thresholds": thresholds, "metrics": metrics, "objective_score": score}
    return best or {}


def calibrate(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args.config)
    history = config.get("calibration_history", {})
    start_date = args.start_date or history.get("start_date") or "2023-01-01"
    end_date = args.end_date or history.get("end_date") or datetime.now().date().isoformat()
    windows = args.windows or config.get("label_windows", [5, 10, 20])
    weights = config.get("weights", {})
    requirements = config.get("stability_requirements", {})
    min_dates = int(args.min_dates or requirements.get("min_dates", 60))
    min_samples = int(args.min_samples_per_grade or requirements.get("min_samples_per_grade", 30))
    require_monotonic = bool(requirements.get("min_grade_monotonicity", True))

    eval_paths = discover_evaluations(start_date, end_date)
    samples = load_samples(eval_paths, weights)
    db_path = args.foundation_db or foundation_db_for(end_date)
    labeled, label_diag = attach_labels(samples, db_path, windows)

    unique_dates = sorted({s["date"] for s in labeled})
    status = "ok"
    blockers = []
    if len(eval_paths) < min_dates:
        status = "insufficient_history"
        blockers.append(f"evaluation_dates {len(eval_paths)} < min_dates {min_dates}")
    if len(labeled) < min_samples * 4:
        status = "insufficient_history"
        blockers.append(f"labeled_samples {len(labeled)} < {min_samples * 4}")

    result: dict[str, Any] = {
        "schema_version": "strategy_evidence_calibration_result_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "blockers": blockers,
        "research_only": True,
        "input_config": str(args.config),
        "history": {"start_date": start_date, "end_date": end_date},
        "evaluation_files": [str(p) for p in eval_paths],
        "evaluation_dates": len(eval_paths),
        "labeled_dates": len(unique_dates),
        "label_windows": windows,
        "weights": weights,
        "label_diagnostics": label_diag,
        "rank_ic": {str(w): rank_ic(labeled, w) for w in windows},
    }

    if status == "ok":
        primary_window = int(args.primary_window or (10 if 10 in windows else windows[0]))
        best = search_thresholds(labeled, primary_window, min_samples)
        result["primary_window"] = primary_window
        result["best"] = best
        quality_blockers = monotonic_blockers(best.get("metrics", {}), min_samples, require_monotonic)
        if best.get("objective_score") is not None and best.get("objective_score") < 0:
            quality_blockers.append(f"objective_score {best['objective_score']:.6f} < 0")
        if quality_blockers:
            result["status"] = "unstable_calibration"
            result["blockers"] = quality_blockers
            result["next_steps"] = [
                "Keep the reminder layer in 待校准 state for these statistics.",
                "Generate a longer historical replay window or improve factor coverage before trusting thresholds.",
                "Do not change State formulas to force monotonic calibration.",
            ]
        else:
            calibrated = dict(config)
            calibrated["thresholds"] = best.get("thresholds", config.get("thresholds", {}))
            calibrated["calibration_history"] = {"start_date": start_date, "end_date": end_date}
            calibrated["generated_at"] = result["generated_at"]
            calibrated["calibration_status"] = "calibrated"
            result["calibrated_config"] = calibrated
    else:
        result["next_steps"] = [
            "Generate historical state_cache and strategy_evaluation files for enough trading dates.",
            "Rerun calibration after future 5/10/20-day labels are available.",
            "Do not change State formulas to force calibration.",
        ]
    return result


def write_outputs(result: dict[str, Any], date_tag: str) -> dict[str, str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / f"strategy_evidence_calibration_{date_tag}.json"
    md_path = OUT_DIR / f"strategy_evidence_calibration_{date_tag}.md"
    latest_json = OUT_DIR / "strategy_evidence_calibration_latest.json"
    json_text = json.dumps(result, ensure_ascii=False, indent=2)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json.write_text(json_text, encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    outputs = {"json": str(json_path), "markdown": str(md_path), "latest_json": str(latest_json)}
    config_path = OUT_DIR / f"strategy_evidence_calibrated_config_{date_tag}.json"
    if result.get("calibrated_config"):
        config_path.write_text(
            json.dumps(result["calibrated_config"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        outputs["calibrated_config"] = str(config_path)
    elif config_path.exists():
        config_path.unlink()
        outputs["removed_stale_calibrated_config"] = str(config_path)
    return outputs


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Strategy Evidence Calibration - {result['history']['end_date']}",
        "",
        f"- Status: `{result['status']}`",
        f"- Evaluation dates: `{result['evaluation_dates']}`",
        f"- Labeled dates: `{result['labeled_dates']}`",
        f"- Label windows: `{result['label_windows']}`",
        "",
        "## Rank IC",
    ]
    for window, value in result.get("rank_ic", {}).items():
        lines.append(f"- {window}d: `{value}`")
    if result.get("blockers"):
        lines.extend(["", "## Blockers"])
        for item in result["blockers"]:
            lines.append(f"- {item}")
    if result.get("best"):
        lines.extend(
            [
                "",
                "## Best Thresholds",
                "```json",
                json.dumps(result["best"], ensure_ascii=False, indent=2),
                "```",
            ]
        )
    if result.get("next_steps"):
        lines.extend(["", "## Next Steps"])
        for item in result["next_steps"]:
            lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calibrate strategy evidence thresholds from historical strategy_evaluation JSON files."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--foundation-db", type=Path)
    parser.add_argument("--windows", type=int, nargs="*")
    parser.add_argument("--primary-window", type=int, default=10)
    parser.add_argument("--min-dates", type=int)
    parser.add_argument("--min-samples-per-grade", type=int)
    args = parser.parse_args()

    result = calibrate(args)
    date_tag = ymd(args.end_date or result["history"]["end_date"])
    outputs = write_outputs(result, date_tag)
    print(
        json.dumps(
            {
                "ok": result["status"] == "ok",
                "status": result["status"],
                "blockers": result.get("blockers", []),
                "evaluation_dates": result["evaluation_dates"],
                "labeled_dates": result["labeled_dates"],
                "rank_ic": result.get("rank_ic", {}),
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
