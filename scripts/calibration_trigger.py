#!/usr/bin/env python3
"""Calibration trigger for forward observation ledger.

Checks triple-gate conditions (time + sample + drift) and triggers
calibration when all gates are met. First calibration skips drift gate.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "calibration_trigger.json"
OUT_DIR = ROOT / "outputs" / "calibration"
LEDGER_DIR = ROOT / "outputs" / "forward_observation"
BASELINE_PATH = OUT_DIR / "calibration_baseline.json"
MANIFEST_PATH = OUT_DIR / "calibration_manifest.json"

# Default config if file missing
DEFAULT_CONFIG = {
    "schema_version": "calibration_trigger_v1",
    "time_threshold_days": 5,
    "sample_threshold_default": 100,
    "sample_threshold_per_strategy": {
        "ma2560": 100,
        "vcp": 50,
        "bollinger_bandit": 80,
    },
    "drift_threshold": 0.10,
    "primary_window": 20,
    "bootstrap_n": 2000,
    "auto_feedback_on_pass": True,
    "alert_on_review_needed": True,
    "first_calibration_skip_drift": True,
}


def parse_date(date_str: str) -> date:
    return date.fromisoformat(date_str)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(path: Path) -> dict[str, Any]:
    if path.exists():
        cfg = load_json(path)
        if cfg:
            return cfg
    return dict(DEFAULT_CONFIG)


# ── Data loading ────────────────────────────────────────────────────────────


def load_last_calibration_date() -> str | None:
    """Read last calibration date from manifest."""
    if not MANIFEST_PATH.exists():
        return None
    manifest = load_json(MANIFEST_PATH)
    return manifest.get("latest_calibration_date")


def load_ledger_start_date() -> str | None:
    """Read forward observation ledger start date from earliest file."""
    files = sorted(LEDGER_DIR.glob("forward_observation_????????.json"))
    if not files:
        return None
    # Extract YYYY-MM-DD from filename like forward_observation_20260521.json
    stem = files[0].stem.replace("forward_observation_", "")
    if len(stem) == 8 and stem.isdigit():
        return f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"
    return None


def load_labeled_observations(date_str: str, strategy_id: str | None) -> list[dict[str, Any]]:
    """Load all labeled forward observation records up to date_str."""
    all_obs: list[dict[str, Any]] = []
    for f in sorted(LEDGER_DIR.glob("forward_observation_????????.json")):
        # Only load files up to date_str
        stem = f.stem.replace("forward_observation_", "")
        file_date = f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"
        if file_date > date_str:
            continue
        payload = load_json(f)
        for row in payload.get("rows", []):
            if row.get("label_status") != "labeled":
                continue
            if strategy_id and row.get("strategy_id") != strategy_id:
                continue
            all_obs.append(row)
    return all_obs


def count_labeled_since_last_calibration(date_str: str, strategy_id: str) -> int:
    """Count labeled samples since last calibration."""
    last = load_last_calibration_date()
    observations = load_labeled_observations(date_str, strategy_id)
    if last is None:
        return len(observations)
    return sum(1 for o in observations if o.get("date", "") >= last)


# ── Distribution computation ────────────────────────────────────────────────


def compute_fit_distribution(date_str: str) -> dict[str, float]:
    """Compute current fit distribution (percentage per level)."""
    observations = load_labeled_observations(date_str, strategy_id=None)
    total = len(observations)
    if total == 0:
        return {}
    counts = Counter(o.get("strategy_environment_fit", "unknown") for o in observations)
    return {level: count / total for level, count in sorted(counts.items())}


def compute_total_variation_distance(p: dict[str, float], q: dict[str, float]) -> float:
    """Compute total variation distance between two distributions."""
    all_keys = set(p) | set(q)
    return sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in all_keys) / 2.0


# ── Baseline management ─────────────────────────────────────────────────────


def load_baseline_distribution() -> dict[str, float] | None:
    if not BASELINE_PATH.exists():
        return None
    payload = load_json(BASELINE_PATH)
    dist = payload.get("distribution")
    if isinstance(dist, dict):
        return dist
    return None


def save_baseline_distribution(date_str: str, distribution: dict[str, float]) -> None:
    payload = {
        "date": date_str,
        "distribution": distribution,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    save_json(BASELINE_PATH, payload)


# ── Triple-gate checks ──────────────────────────────────────────────────────


def check_time_gate(date_str: str, config: dict[str, Any]) -> dict[str, Any]:
    """Check if enough days have passed since last calibration."""
    threshold = config.get("time_threshold_days", 5)
    last_calibration = load_last_calibration_date()

    if last_calibration is None:
        # First calibration: check ledger running days
        ledger_start = load_ledger_start_date()
        if ledger_start is None:
            return {"passed": False, "detail": "账本尚未启动", "days": 0, "first_calibration": True}
        days = (parse_date(date_str) - parse_date(ledger_start)).days
        return {
            "passed": days >= threshold,
            "detail": f"首次校准，账本运行 {days} 天（阈值 {threshold}）",
            "days": days,
            "first_calibration": True,
        }

    days = (parse_date(date_str) - parse_date(last_calibration)).days
    return {
        "passed": days >= threshold,
        "detail": f"距上次校准 {days} 天（阈值 {threshold}）",
        "days": days,
        "first_calibration": False,
    }


def check_sample_gate(date_str: str, config: dict[str, Any], strategy_id: str | None) -> dict[str, Any]:
    """Check if enough labeled samples have accumulated."""
    per_strategy = config.get("sample_threshold_per_strategy", {})
    default_threshold = config.get("sample_threshold_default", 100)

    if strategy_id and strategy_id != "all":
        threshold = per_strategy.get(strategy_id, default_threshold)
        labeled = count_labeled_since_last_calibration(date_str, strategy_id)
        return {
            "passed": labeled >= threshold,
            "detail": f"{strategy_id}: {labeled}/{threshold} 已标注",
            "labeled": labeled,
            "threshold": threshold,
        }

    # All strategies
    total_labeled = 0
    details: dict[str, Any] = {}
    all_passed = True
    for sid in ["vcp", "ma2560", "bollinger_bandit"]:
        t = per_strategy.get(sid, default_threshold)
        l = count_labeled_since_last_calibration(date_str, sid)
        details[sid] = {"labeled": l, "threshold": t, "passed": l >= t}
        total_labeled += l
        if l < t:
            all_passed = False

    return {
        "passed": all_passed,
        "detail": details,
        "total_labeled": total_labeled,
    }


def check_drift_gate(date_str: str, config: dict[str, Any]) -> dict[str, Any]:
    """Check if fit distribution has drifted beyond threshold."""
    threshold = config.get("drift_threshold", 0.10)
    baseline = load_baseline_distribution()

    if baseline is None:
        # First calibration: no baseline, skip drift gate
        return {
            "passed": True,
            "detail": "首次校准，无历史基线，跳过变化门",
            "drift": None,
            "skipped": True,
        }

    current = compute_fit_distribution(date_str)
    drift = compute_total_variation_distance(baseline, current)

    return {
        "passed": drift >= threshold,
        "detail": f"分布偏移 {drift:.3f}（阈值 {threshold}）",
        "drift": drift,
        "baseline": baseline,
        "current": current,
        "skipped": False,
    }


def check_trigger(date_str: str, config: dict[str, Any], strategy_id: str | None = None) -> dict[str, Any]:
    """Check all three gates for calibration trigger."""
    time_gate = check_time_gate(date_str, config)
    sample_gate = check_sample_gate(date_str, config, strategy_id)
    drift_gate = check_drift_gate(date_str, config)

    first_calibration = time_gate.get("first_calibration", False)

    # First calibration: triple gate degenerates to dual gate (skip drift)
    if first_calibration:
        should = time_gate["passed"] and sample_gate["passed"]
        reason = "first_calibration_time_and_sample_met" if should else None
    else:
        should = time_gate["passed"] and sample_gate["passed"] and drift_gate["passed"]
        reason = "all_three_gates_met" if should else None

    return {
        "should_calibrate": should,
        "trigger_reason": reason,
        "first_calibration": first_calibration,
        "gates": {
            "time": time_gate,
            "sample": sample_gate,
            "drift": drift_gate,
        },
    }


# ── Bootstrap CI (inline to avoid dependency issues) ────────────────────────


def _bootstrap_ci(
    values: list[float], stat_fn: callable, n_bootstrap: int = 2000, seed: int = 42
) -> tuple[float | None, float | None]:
    if len(values) < 5:
        return (None, None)
    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=np.float64)
    n = len(arr)
    boot_stats = np.empty(n_bootstrap, dtype=np.float64)
    for i in range(n_bootstrap):
        sample = rng.choice(arr, size=n, replace=True)
        boot_stats[i] = stat_fn(sample)
    alpha = 0.025
    return (
        float(np.percentile(boot_stats, alpha * 100)),
        float(np.percentile(boot_stats, (1.0 - alpha) * 100)),
    )


def _bootstrap_mean_ci(values: list[float], n_bootstrap: int = 2000) -> tuple[float | None, float | None]:
    return _bootstrap_ci(values, np.mean, n_bootstrap)


def _bootstrap_win_rate_ci(values: list[float], n_bootstrap: int = 2000) -> tuple[float | None, float | None]:
    return _bootstrap_ci(values, lambda a: np.mean(a > 0), n_bootstrap)


# ── Metric computation ──────────────────────────────────────────────────────


def _payoff_ratio(values: list[float]) -> float | None:
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    if not wins or not losses:
        return None
    loss_mean = statistics.fmean(losses)
    if loss_mean == 0:
        return None
    return statistics.fmean(wins) / abs(loss_mean)


def metric_row(
    key: str, samples: list[dict[str, Any]], window: int, n_bootstrap: int = 2000
) -> dict[str, Any]:
    """Compute point estimates + 95% Bootstrap CI for a group of samples."""
    field = f"forward_excess_return_{window}d"
    values = [float(s[field]) for s in samples if s.get(field) is not None]
    wins = [v for v in values if v > 0]

    mean = statistics.fmean(values) if values else None
    stdev = statistics.stdev(values) if len(values) > 1 else None
    t_stat = mean / (stdev / math.sqrt(len(values))) if mean is not None and stdev and stdev > 0 else None
    med = statistics.median(values) if values else None
    wr = len(wins) / len(values) if values else None
    pr = _payoff_ratio(values)

    ci_mean = ci_wr = (None, None)
    if len(values) >= 10:
        ci_mean = _bootstrap_mean_ci(values, n_bootstrap)
        ci_wr = _bootstrap_win_rate_ci(values, n_bootstrap)

    return {
        "key": key,
        "n": len(values),
        "mean_excess": mean,
        "mean_excess_ci_lo": ci_mean[0],
        "mean_excess_ci_hi": ci_mean[1],
        "median_excess": med,
        "win_rate": wr,
        "win_rate_ci_lo": ci_wr[0],
        "win_rate_ci_hi": ci_wr[1],
        "payoff_ratio": pr,
        "t_stat": t_stat,
    }


# ── Fit ordering validation ─────────────────────────────────────────────────


def check_fit_ordering(fit_groups: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Check if fit level ordering aligns with excess return direction."""
    levels = ["最佳适配", "适配", "弱适配", "待观察", "不适配"]
    available = [(l, fit_groups[l]) for l in levels if l in fit_groups]

    if len(available) < 2:
        return {"valid": False, "detail": "可用适配度等级不足 2 个", "insufficient": True}

    means = [(l, r["mean_excess"]) for l, r in available if r.get("mean_excess") is not None]
    if len(means) < 2:
        return {"valid": False, "detail": "有效均值不足"}

    sorted_correctly = all(means[i][1] >= means[i + 1][1] for i in range(len(means) - 1))
    best_mean = means[0][1]
    all_mean = sum(r["mean_excess"] for _, r in available if r.get("mean_excess") is not None) / len(means)
    best_above_all = best_mean > all_mean

    valid = sorted_correctly and best_above_all

    return {
        "valid": valid,
        "detail": {
            "sorted_correctly": sorted_correctly,
            "best_above_all": best_above_all,
            "means": {l: round(m, 4) for l, m in means},
        },
    }


# ── Calibration execution ───────────────────────────────────────────────────


def find_earliest_observation(observations: list[dict[str, Any]]) -> str | None:
    if not observations:
        return None
    dates = [o.get("date", "9999-99-99") for o in observations if o.get("date")]
    return min(dates) if dates else None


def build_run_card(
    date_str: str, config: dict[str, Any], observations: list[dict[str, Any]], fit_groups: dict[str, Any]
) -> dict[str, Any]:
    """Build a concise run card for the calibration."""
    return {
        "date": date_str,
        "total_labeled": len(observations),
        "fit_levels_calculated": list(fit_groups.keys()),
        "primary_window": config.get("primary_window", 20),
        "bootstrap_n": config.get("bootstrap_n", 2000),
    }


def run_calibration(date_str: str, config: dict[str, Any], strategy_id: str | None = None) -> dict[str, Any]:
    """Execute calibration after trigger conditions are met."""
    window = config.get("primary_window", 20)
    n_bootstrap = config.get("bootstrap_n", 2000)

    # 1. Load labeled observations
    observations = load_labeled_observations(date_str, strategy_id)

    # 2. Group by fit level
    fit_groups: dict[str, dict[str, Any]] = {}
    for level in ["最佳适配", "适配", "弱适配", "待观察", "不适配"]:
        group = [o for o in observations if o.get("strategy_environment_fit") == level]
        if group:
            values = [o for o in group if o.get(f"forward_excess_return_{window}d") is not None]
            if values:
                fit_groups[level] = metric_row(level, values, window, n_bootstrap)

    # 3. Group by lifecycle stage
    lifecycle_groups: dict[str, dict[str, Any]] = {}
    for stage in ["新生", "行进", "延展", "未知"]:
        group = [o for o in observations if o.get("lifecycle_stage") == stage]
        if group:
            values = [o for o in group if o.get(f"forward_excess_return_{window}d") is not None]
            if values:
                lifecycle_groups[stage] = metric_row(stage, values, window, n_bootstrap)

    # 4. Check fit ordering validity
    fit_ordering = check_fit_ordering(fit_groups)

    # 5. Build report
    return {
        "schema_version": "calibration_report_v1",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "calibration_window": {
            "start_date": find_earliest_observation(observations),
            "end_date": date_str,
            "total_labeled": len(observations),
        },
        "fit_return_table": fit_groups,
        "lifecycle_return_table": lifecycle_groups,
        "verdict": {
            "fit_ordering_valid": fit_ordering["valid"],
            "fit_ordering_detail": fit_ordering["detail"],
            "overall": "pass" if fit_ordering["valid"] else "review_needed",
        },
        "run_card": build_run_card(date_str, config, observations, fit_groups),
        "research_only": True,
    }


# ── Feedback application ────────────────────────────────────────────────────


def extract_fit_distribution(fit_return_table: dict[str, Any]) -> dict[str, float]:
    """Extract fit level distribution from calibration result."""
    total = sum(r.get("n", 0) for r in fit_return_table.values() if isinstance(r, dict))
    if total == 0:
        return {}
    return {level: r.get("n", 0) / total for level, r in fit_return_table.items() if isinstance(r, dict)}


def update_registry_calibration(date_str: str, calibration_result: dict[str, Any]) -> None:
    """Update strategy_registry.json with latest calibration info."""
    registry_path = ROOT / "config" / "strategy_registry.json"
    if not registry_path.exists():
        return
    registry = load_json(registry_path)
    strategies = registry.get("strategies", {})
    for sid in strategies:
        if "latest_calibration" not in strategies[sid]:
            strategies[sid]["latest_calibration"] = {}
        strategies[sid]["latest_calibration"] = {
            "date": date_str,
            "verdict": calibration_result.get("verdict", {}),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    registry["strategies"] = strategies
    save_json(registry_path, registry)


def write_calibration_report(date_str: str, calibration_result: dict[str, Any]) -> Path:
    """Write calibration report to outputs."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / f"calibration_report_{date_str.replace('-', '')}.json"
    md_path = OUT_DIR / f"calibration_report_{date_str.replace('-', '')}.md"

    save_json(json_path, calibration_result)

    # Render markdown
    lines = [
        f"# 适配度校准报告 - {date_str}",
        "",
        f"- 生成时间: {calibration_result['generated_at']}",
        f"- 校准窗口: {calibration_result['calibration_window']['start_date']} 至 {date_str}",
        f"- 总标注样本: {calibration_result['calibration_window']['total_labeled']}",
        "",
        "## 适配度-收益相关性",
        "",
        "| 适配度等级 | n | 平均超额 | 95% CI | 胜率 | 95% CI | 盈亏比 | t-stat |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for level in ["最佳适配", "适配", "弱适配", "待观察", "不适配"]:
        if level in calibration_result.get("fit_return_table", {}):
            r = calibration_result["fit_return_table"][level]
            ci_mean = (
                f"[{r.get('mean_excess_ci_lo') or 'N/A':.2%}, {r.get('mean_excess_ci_hi') or 'N/A':.2%}]"
                if r.get("mean_excess_ci_lo") is not None
                else "N/A"
            )
            ci_wr = (
                f"[{r.get('win_rate_ci_lo') or 0:.1%}, {r.get('win_rate_ci_hi') or 0:.1%}]"
                if r.get("win_rate_ci_lo") is not None
                else "N/A"
            )
            t_stat_str = f"{r.get('t_stat'):.2f}" if r.get("t_stat") is not None else "N/A"
            lines.append(
                f"| {level} | {r.get('n', 0)} | {r.get('mean_excess') or 0:.2%} | {ci_mean} | "
                f"{r.get('win_rate') or 0:.1%} | {ci_wr} | {r.get('payoff_ratio') or 'N/A'} | {t_stat_str} |"
            )

    lines.extend(
        [
            "",
            "## 校准判定",
            "",
            f"- 适配度排序有效: {'是' if calibration_result['verdict']['fit_ordering_valid'] else '否'}",
            f"- 总体判定: **{calibration_result['verdict']['overall']}**",
            "",
            "## 边界",
            "",
            "- 本报告为研究只读输出，不构成投资建议。",
            '- 校准通过不代表策略"有效"，只代表适配度排序与历史收益方向一致。',
            "- 任何规则变更仍需人工确认。",
            "",
        ]
    )

    md_path.write_text("\n".join(lines), encoding="utf-8")

    # Update latest symlink copies
    latest_json = OUT_DIR / "calibration_report_latest.json"
    latest_md = OUT_DIR / "calibration_report_latest.md"
    latest_json.write_text(json.dumps(calibration_result, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_md.write_text("\n".join(lines), encoding="utf-8")

    return json_path


def generate_calibration_alert(calibration_result: dict[str, Any]) -> dict[str, Any]:
    """Generate alert when calibration needs review."""
    return {
        "alert_type": "calibration_review_needed",
        "date": calibration_result["date"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reason": calibration_result["verdict"].get("fit_ordering_detail", {}),
        "severity": "warning",
        "research_only": True,
    }


def write_alert(date_str: str, alert: dict[str, Any]) -> Path:
    """Write alert to file."""
    alert_path = OUT_DIR / f"calibration_alert_{date_str.replace('-', '')}.json"
    save_json(alert_path, alert)
    return alert_path


def apply_feedback(calibration_result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Apply feedback based on calibration verdict."""
    verdict = calibration_result["verdict"]["overall"]
    date_str = calibration_result["date"]

    if verdict == "pass":
        # 1. Update baseline distribution
        new_baseline = extract_fit_distribution(calibration_result["fit_return_table"])
        save_baseline_distribution(date_str, new_baseline)

        # 2. Update registry
        update_registry_calibration(date_str, calibration_result)

        # 3. Write report
        write_calibration_report(date_str, calibration_result)

        # 4. Update manifest
        manifest = load_json(MANIFEST_PATH) if MANIFEST_PATH.exists() else {}
        manifest["latest_calibration_date"] = date_str
        manifest["calibrations"] = manifest.get("calibrations", []) + [
            {
                "date": date_str,
                "verdict": "pass",
                "baseline_updated": True,
            }
        ]
        save_json(MANIFEST_PATH, manifest)

        return {
            "action": "auto_updated",
            "baseline_updated": True,
            "registry_updated": True,
            "report_written": True,
        }

    elif verdict == "review_needed":
        # 1. Write report (marked as review_needed)
        write_calibration_report(date_str, calibration_result)

        # 2. Generate alert
        alert = generate_calibration_alert(calibration_result)
        alert_path = write_alert(date_str, alert)

        return {
            "action": "alert_generated",
            "alert": alert,
            "alert_path": str(alert_path),
            "report_written": True,
        }

    else:  # insufficient_data
        return {
            "action": "no_action",
            "reason": "数据不足，等待更多样本",
        }


# ── Main entry ──────────────────────────────────────────────────────────────


def run(
    date_str: str, config_path: Path, force: bool = False, dry_run: bool = False, strategy: str = "all"
) -> dict[str, Any]:
    """Main orchestration function."""
    config = load_config(config_path)
    strategy_id = None if strategy == "all" else strategy

    # Check trigger conditions
    trigger = check_trigger(date_str, config, strategy_id)

    # Write daily check record
    check_record = {
        "schema_version": "calibration_check_v1",
        "date": date_str,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "trigger": trigger,
        "config": config,
    }
    check_path = OUT_DIR / f"calibration_check_{date_str.replace('-', '')}.json"
    save_json(check_path, check_record)

    if not trigger["should_calibrate"] and not force:
        return {
            "ok": True,
            "calibrated": False,
            "trigger": trigger,
            "check_path": str(check_path),
        }

    if dry_run:
        return {
            "ok": True,
            "calibrated": False,
            "dry_run": True,
            "trigger": trigger,
            "check_path": str(check_path),
        }

    # Run calibration
    calibration_result = run_calibration(date_str, config, strategy_id)
    calibration_result["trigger"] = trigger

    # Apply feedback
    feedback = apply_feedback(calibration_result, config)
    calibration_result["feedback"] = feedback

    return {
        "ok": True,
        "calibrated": True,
        "trigger": trigger,
        "calibration": calibration_result,
        "feedback": feedback,
        "check_path": str(check_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibration trigger for forward observation ledger.")
    parser.add_argument("--date", required=True, help="Check date, e.g. 2026-05-27")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="Path to calibration_trigger.json")
    parser.add_argument(
        "--force", action="store_true", help="Force calibration regardless of trigger conditions"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Check conditions only, do not run calibration"
    )
    parser.add_argument(
        "--strategy", default="all", help="Strategy to calibrate: all / vcp / ma2560 / bollinger_bandit"
    )
    args = parser.parse_args()

    result = run(
        date_str=args.date,
        config_path=args.config,
        force=args.force,
        dry_run=args.dry_run,
        strategy=args.strategy,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
