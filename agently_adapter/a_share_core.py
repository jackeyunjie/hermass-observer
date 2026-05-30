#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def foundation_path(date_str: str, override: str | None) -> Path:
    if override:
        return (ROOT / override).resolve() if not Path(override).is_absolute() else Path(override)
    return ROOT / "outputs" / f"p116_foundation_{ymd(date_str)}" / "p116_foundation.duckdb"


def raw_db_path(date_str: str) -> Path:
    return RESEARCH_ROOT / "outputs" / f"p108_blackwolf_ashare_daily_raw_{ymd(date_str)}" / "p108_blackwolf_ashare_daily_raw.duckdb"


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def preflight(date_str: str, previous_date: str) -> dict[str, Any]:
    run(
        [
            sys.executable,
            "agently_adapter/preflight_freshness.py",
            "--date",
            date_str,
            "--previous-date",
            previous_date,
        ]
    )
    return {"ok": True, "date": date_str, "previous_date": previous_date}


def build_foundation(date_str: str, raw_db: str | None = None, foundation_db: str | None = None) -> dict[str, Any]:
    out_db = foundation_path(date_str, foundation_db)
    raw = Path(raw_db) if raw_db else raw_db_path(date_str)
    run(
        [
            sys.executable,
            "scripts/build_p116_foundation.py",
            "--date",
            date_str,
            "--raw-db",
            str(raw),
            "--out-db",
            str(out_db),
        ]
    )
    return {"ok": True, "foundation_db": str(out_db), "raw_db": str(raw)}


def validate_foundation(date_str: str, foundation_db: str | None) -> dict[str, Any]:
    db_path = foundation_path(date_str, foundation_db)
    if not db_path.exists():
        raise FileNotFoundError(f"foundation DB not found: {db_path}")
    return {"ok": True, "foundation_db": str(db_path)}


def _verify_paths(paths: list[Path]) -> list[str]:
    return [str(path) for path in paths if not path.exists()]


def verify_core_outputs(date_str: str, foundation_db: str | None = None) -> dict[str, Any]:
    date_ymd = ymd(date_str)
    required = [
        foundation_path(date_str, foundation_db),
        ROOT / "outputs" / "state_cache" / f"state_cache_manifest_{date_ymd}.json",
        ROOT / "outputs" / "state_cache" / f"state_ef_{date_ymd}.json",
        ROOT / "outputs" / "strategy_evidence" / f"strategy_evidence_{date_ymd}.json",
        ROOT / "public" / f"strategy_evidence_{date_ymd}.html",
        ROOT / "outputs" / "strategy_signals" / f"strategy_signal_daily_{date_ymd}.json",
        ROOT / "outputs" / "forward_observation" / f"forward_observation_{date_ymd}.json",
        ROOT / "public" / f"forward_observation_{date_ymd}.html",
        ROOT / "outputs" / "daily_research_brief" / f"daily_research_brief_{date_ymd}.json",
        ROOT / "public" / f"daily_research_brief_{date_ymd}.html",
    ]
    missing = _verify_paths(required)
    if missing:
        raise FileNotFoundError("missing core outputs: " + ", ".join(missing))
    return {"ok": True, "outputs": [str(path) for path in required]}


def public_extension_paths(date_str: str) -> list[Path]:
    date_ymd = ymd(date_str)
    return [
        ROOT / "public" / f"p116_all_three_ef_{date_ymd}.html",
        ROOT / "public" / f"p116_recommendation_{date_ymd}.html",
        ROOT / "public" / f"macro_snapshot_{date_ymd}.html",
        ROOT / "public" / f"macro_chain_prior_{date_ymd}.html",
        ROOT / "public" / f"market_assets_state_{date_ymd}.html",
        ROOT / "public" / f"industry_etf_coverage_{date_ymd}.html",
        ROOT / "public" / f"industry_etf_config_{date_ymd}.html",
        ROOT / "public" / f"industry_rotation_{date_ymd}.html",
        ROOT / "public" / f"p116_recommendation_shareable_{date_ymd}.html",
        ROOT / "public" / f"p116_recommendation_shareable_{date_ymd}.xlsx",
        ROOT / "public" / f"pattern_cross_ef_{date_ymd}.html",
        ROOT / "public" / f"strategy_reminder_{date_ymd}.html",
        ROOT / "public" / f"ma2560_market_match_forward_{date_ymd}.html",
        ROOT / "public" / f"ma2560_stock_only_gap_audit_{date_ymd}.html",
    ]


def verify_public_outputs(date_str: str, foundation_db: str | None = None) -> dict[str, Any]:
    core_outputs = verify_core_outputs(date_str, foundation_db=foundation_db)["outputs"]
    required = [Path(path) for path in core_outputs]
    required.extend(public_extension_paths(date_str))
    missing = _verify_paths(required)
    if missing:
        raise FileNotFoundError("missing public outputs: " + ", ".join(missing))
    return {"ok": True, "outputs": [str(path) for path in required]}


def build_state_cache(
    date_str: str,
    foundation_db: str | None = None,
    boundary_pct: float = 0.03,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/state_cache_builder.py",
        "--date",
        date_str,
        "--boundary-pct",
        str(boundary_pct),
    ]
    if foundation_db:
        cmd.extend(["--foundation-db", foundation_db])
    run(cmd)
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "boundary_pct": boundary_pct,
        "cache_db": str(ROOT / "outputs" / "state_cache" / "state_cache.duckdb"),
        "manifest": str(ROOT / "outputs" / "state_cache" / f"state_cache_manifest_{date_ymd}.json"),
        "state_ef_json": str(ROOT / "outputs" / "state_cache" / f"state_ef_{date_ymd}.json"),
        "state_distribution_json": str(ROOT / "outputs" / "state_cache" / f"state_distribution_{date_ymd}.json"),
        "state_transition_json": str(ROOT / "outputs" / "state_cache" / f"state_transition_{date_ymd}.json"),
        "sr_boundary_json": str(ROOT / "outputs" / "state_cache" / f"sr_boundary_{date_ymd}.json"),
        "state_duration_json": str(ROOT / "outputs" / "state_cache" / f"state_duration_{date_ymd}.json"),
    }


def build_strategy_evidence(date_str: str, foundation_db: str | None = None, lookback_days: int = 20) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/build_strategy_evidence.py",
        "--date",
        date_str,
        "--lookback-days",
        str(lookback_days),
    ]
    if foundation_db:
        cmd.extend(["--foundation-db", foundation_db])
    run(cmd)
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "strategy_evidence_json": str(ROOT / "outputs" / "strategy_evidence" / f"strategy_evidence_{date_ymd}.json"),
        "strategy_evidence_csv": str(ROOT / "outputs" / "strategy_evidence" / f"strategy_evidence_{date_ymd}.csv"),
        "strategy_evidence_html": str(ROOT / "public" / f"strategy_evidence_{date_ymd}.html"),
    }


def build_strategy_signal_ledger(
    date_str: str,
    foundation_db: str | None = None,
    min_ef: int = 2,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/strategy_signal_ledger.py",
        "--date",
        date_str,
        "--min-ef",
        str(min_ef),
    ]
    if foundation_db:
        cmd.extend(["--foundation-db", foundation_db])
    run(cmd)
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "min_ef": min_ef,
        "ledger_db": str(ROOT / "outputs" / "strategy_signals" / "strategy_signals.duckdb"),
        "ledger_json": str(ROOT / "outputs" / "strategy_signals" / f"strategy_signal_daily_{date_ymd}.json"),
    }


def build_forward_observation(date_str: str, foundation_db: str | None = None, windows: str = "5,10,20") -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/forward_observation_ledger.py",
        "--date",
        date_str,
        "--windows",
        windows,
    ]
    if foundation_db:
        cmd.extend(["--foundation-db", foundation_db])
    run(cmd)
    date_ymd = ymd(date_str)
    output_json = ROOT / "outputs" / "forward_observation" / f"forward_observation_{date_ymd}.json"
    summary: dict[str, Any] = {}
    if output_json.exists():
        try:
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            summary = {
                "total": payload.get("total"),
                "labeled": payload.get("labeled"),
                "pending": payload.get("pending"),
                "status_distribution": payload.get("status_distribution"),
                "strategy_distribution": payload.get("strategy_distribution"),
            }
        except json.JSONDecodeError:
            summary = {"status": "invalid_json"}
    return {
        "ok": True,
        "mode": "observation_ledger",
        "date": date_str,
        "windows": windows,
        **summary,
        "json": str(output_json),
        "csv": str(ROOT / "outputs" / "forward_observation" / f"forward_observation_{date_ymd}.csv"),
        "html": str(ROOT / "public" / f"forward_observation_{date_ymd}.html"),
        "latest_json": str(ROOT / "outputs" / "forward_observation" / "forward_observation_latest.json"),
        "latest_html": str(ROOT / "public" / "forward_observation_latest.html"),
        "research_only": True,
    }


def build_daily_brief(date_str: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/daily_research_brief.py",
        "--date",
        date_str,
    ]
    run(cmd)
    date_ymd = ymd(date_str)
    output_json = ROOT / "outputs" / "daily_research_brief" / f"daily_research_brief_{date_ymd}.json"
    summary: dict[str, Any] = {}
    if output_json.exists():
        try:
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            summary = {
                "total_reminders": payload.get("signal_stats", {}).get("total_reminders"),
                "display_count": len(payload.get("display_rows", []) or []),
                "fit_counts": payload.get("signal_stats", {}).get("fit_counts"),
                "lifecycle_counts": payload.get("signal_stats", {}).get("lifecycle_counts"),
                "calibration": payload.get("calibration"),
            }
        except json.JSONDecodeError:
            summary = {"status": "invalid_json"}
    return {
        "ok": True,
        "date": date_str,
        **summary,
        "json": str(output_json),
        "markdown": str(ROOT / "outputs" / "daily_research_brief" / f"daily_research_brief_{date_ymd}.md"),
        "html": str(ROOT / "public" / f"daily_research_brief_{date_ymd}.html"),
        "latest_json": str(ROOT / "outputs" / "daily_research_brief" / "daily_research_brief_latest.json"),
        "latest_html": str(ROOT / "public" / "daily_research_brief_latest.html"),
        "research_only": True,
    }


CORE_STEP_ORDER = [
    "build_state_cache",
    "build_strategy_evidence",
    "build_strategy_signal_ledger",
    "build_forward_observation",
    "build_daily_brief",
    "verify_core_outputs",
]


def run_core_steps_from_foundation(
    date_str: str,
    foundation_db: str,
    *,
    boundary_pct: float = 0.03,
    lookback_days: int = 20,
    min_ef: int = 2,
    windows: str = "5,10,20",
    steps: list[str] | None = None,
) -> dict[str, Any]:
    selected_steps = steps or CORE_STEP_ORDER
    out: dict[str, Any] = {}
    for step_name in selected_steps:
        if step_name == "build_state_cache":
            out[step_name] = build_state_cache(
                date_str,
                foundation_db=foundation_db,
                boundary_pct=boundary_pct,
            )
        elif step_name == "build_strategy_evidence":
            out[step_name] = build_strategy_evidence(
                date_str,
                foundation_db=foundation_db,
                lookback_days=lookback_days,
            )
        elif step_name == "build_strategy_signal_ledger":
            out[step_name] = build_strategy_signal_ledger(
                date_str,
                foundation_db=foundation_db,
                min_ef=min_ef,
            )
        elif step_name == "build_forward_observation":
            out[step_name] = build_forward_observation(
                date_str,
                foundation_db=foundation_db,
                windows=windows,
            )
        elif step_name == "build_daily_brief":
            out[step_name] = build_daily_brief(date_str)
        elif step_name == "verify_core_outputs":
            out[step_name] = verify_core_outputs(date_str, foundation_db=foundation_db)
        else:
            raise ValueError(f"unsupported core step: {step_name}")
    return out


def run_core_flow(
    date_str: str,
    previous_date: str,
    foundation_db: str,
    *,
    boundary_pct: float = 0.03,
    lookback_days: int = 20,
    min_ef: int = 2,
    windows: str = "5,10,20",
) -> dict[str, Any]:
    steps: dict[str, Any] = {}
    steps["preflight"] = preflight(date_str, previous_date)
    steps["build_foundation"] = build_foundation(date_str, foundation_db=foundation_db)
    resolved_foundation_db = steps["build_foundation"]["foundation_db"]
    steps.update(
        run_core_steps_from_foundation(
            date_str,
            resolved_foundation_db,
            boundary_pct=boundary_pct,
            lookback_days=lookback_days,
            min_ef=min_ef,
            windows=windows,
        )
    )
    return {
        "ok": True,
        "scope": "a_share_only",
        "framework": "core",
        "flow": "hermass-a-share-d1-core-flow",
        "date": date_str,
        "previous_date": previous_date,
        "foundation_db": resolved_foundation_db,
        "steps": steps,
        "research_only": True,
    }
