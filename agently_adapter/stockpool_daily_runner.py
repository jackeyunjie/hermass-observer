#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

from agently_adapter import a_share_core


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")
STATE_CACHE_REPLAY_LOCK = threading.Lock()
SIGNAL_LEDGER_REPLAY_LOCK = threading.Lock()


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def parse_steps(value: str | None) -> list[str]:
    if not value:
        return ["state_cache", "signal_ledger", "strategy_evaluation", "reminder"]
    aliases = {
        "state_cache": "state_cache",
        "cache": "state_cache",
        "signal_ledger": "signal_ledger",
        "ledger": "signal_ledger",
        "strategy_signal_ledger": "signal_ledger",
        "strategy_evaluation": "strategy_evaluation",
        "evaluation": "strategy_evaluation",
        "reminder": "reminder",
        "strategy_reminder": "reminder",
    }
    out: list[str] = []
    for item in value.split(","):
        key = item.strip()
        if not key:
            continue
        step = aliases.get(key)
        if not step:
            raise ValueError(f"unsupported replay step: {key}")
        if step not in out:
            out.append(step)
    return out


def date_range(start_date: str, end_date: str) -> list[str]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise ValueError(f"end date before start date: {start_date} > {end_date}")
    out: list[str] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            out.append(current.isoformat())
        current += timedelta(days=1)
    return out


def foundation_path(date_str: str, override: str | None) -> Path:
    if override:
        return (ROOT / override).resolve() if not Path(override).is_absolute() else Path(override)
    return ROOT / "outputs" / f"p116_foundation_{ymd(date_str)}" / "p116_foundation.duckdb"


def raw_db_path(date_str: str) -> Path:
    return RESEARCH_ROOT / "outputs" / f"p108_blackwolf_ashare_daily_raw_{ymd(date_str)}" / "p108_blackwolf_ashare_daily_raw.duckdb"


def daily_zip_path(date_str: str, test: bool = False) -> Path:
    suffix = "_test" if test else ""
    return RESEARCH_ROOT / "data" / f"blackwolf_ashare_daily_mac_format_20180515_{ymd(date_str)}{suffix}.zip"


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def download_daily(date_str: str, previous_date: str, test: bool) -> dict[str, Any]:
    run(
        [
            sys.executable,
            "blackwolf_actions/download_daily.py",
            "--date",
            date_str,
            "--base-date",
            previous_date,
            *("--test".split() if test else []),
        ]
    )
    return {"ok": True, "daily_zip": str(daily_zip_path(date_str, test=test))}


def build_raw_db(date_str: str, source_zip: str | None = None, test: bool = False) -> dict[str, Any]:
    zip_path = Path(source_zip) if source_zip else daily_zip_path(date_str, test=test)
    if not zip_path.is_absolute():
        zip_path = (ROOT / zip_path).resolve()
    out_db = raw_db_path(date_str)
    summary = ROOT / "reports" / "blackwolf_actions" / f"raw_duckdb_{ymd(date_str)}.json"
    run(
        [
            sys.executable,
            str(RESEARCH_ROOT / "scripts" / "build_p108_blackwolf_ashare_raw_duckdb.py"),
            "--zip",
            str(zip_path),
            "--out-db",
            str(out_db),
            "--summary",
            str(summary),
        ]
    )
    return {"ok": True, "raw_db": str(out_db), "source_zip": str(zip_path), "summary": str(summary)}


def download_moneyflow(date_str: str, days: int = 5, limit: int | None = None, workers: int = 16) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "blackwolf_actions/download_moneyflow_recent.py",
        "--end-date",
        date_str,
        "--days",
        str(days),
        "--workers",
        str(workers),
    ]
    if limit:
        cmd.extend(["--limit", str(limit)])
    run(cmd)
    return {"ok": True, "end_date": date_str, "days": days, "limit": limit, "workers": workers}


def import_moneyflow_db(date_str: str) -> dict[str, Any]:
    run(
        [
            sys.executable,
            "blackwolf_actions/import_moneyflow_duckdb.py",
            "--date",
            date_str,
        ]
    )
    return {
        "ok": True,
        "date": date_str,
        "moneyflow_db": str(ROOT / "outputs" / "blackwolf_moneyflow" / "blackwolf_moneyflow.duckdb"),
    }


def download_market_assets(date_str: str, days: int = 1) -> dict[str, Any]:
    run(
        [
            sys.executable,
            "blackwolf_actions/download_market_assets.py",
            "--date",
            date_str,
            "--days",
            str(days),
            "--workers",
            "12",
        ]
    )
    return {"ok": True, "date": date_str, "days": days, "data_dir": str(ROOT / "data" / "blackwolf_market_assets")}


def import_market_assets_db(date_str: str) -> dict[str, Any]:
    run(
        [
            sys.executable,
            "blackwolf_actions/import_market_assets_duckdb.py",
            "--date",
            date_str,
        ]
    )
    return {"ok": True, "date": date_str, "market_assets_db": str(ROOT / "outputs" / "market_assets" / "market_assets.duckdb")}


def import_market_assets_db_range(end_date: str, days: int = 1) -> dict[str, Any]:
    from datetime import date, timedelta

    dates: list[str] = []
    current = date.fromisoformat(end_date)
    while len(dates) < days:
        if current.weekday() < 5:
            dates.append(current.isoformat())
        current -= timedelta(days=1)
    dates = sorted(dates)
    return {"ok": True, "dates": dates, "results": [import_market_assets_db(item) for item in dates]}


def build_industry_rotation(date_str: str) -> dict[str, Any]:
    run(
        [
            sys.executable,
            "recommendation/build_industry_rotation_evidence.py",
            "--date",
            date_str,
        ]
    )
    return {
        "ok": True,
        "date": date_str,
        "industry_rotation_html": str(ROOT / "public" / f"industry_rotation_{ymd(date_str)}.html"),
    }


def build_strategy_evidence(date_str: str, foundation_db: str | None = None, lookback_days: int = 20) -> dict[str, Any]:
    return a_share_core.build_strategy_evidence(date_str, foundation_db=foundation_db, lookback_days=lookback_days)


def evaluate_strategy_evidence(date_str: str, top_n: int = 80) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/evaluate_strategy_evidence.py",
        "--date",
        date_str,
        "--top-n",
        str(top_n),
    ]
    run(cmd)
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "top_n": top_n,
        "strategy_evaluation_json": str(ROOT / "outputs" / "strategy_evaluation" / f"strategy_evaluation_{date_ymd}.json"),
        "strategy_evaluation_csv": str(ROOT / "outputs" / "strategy_evaluation" / f"strategy_evaluation_{date_ymd}.csv"),
        "strategy_evaluation_html": str(ROOT / "public" / f"strategy_evaluation_{date_ymd}.html"),
    }


def calibrate_strategy_evidence(
    date_str: str,
    start_date: str | None = None,
    foundation_db: str | None = None,
    min_dates: int | None = None,
    min_samples_per_grade: int | None = None,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/calibrate_strategy_evidence.py",
        "--end-date",
        date_str,
    ]
    if start_date:
        cmd.extend(["--start-date", start_date])
    if foundation_db:
        cmd.extend(["--foundation-db", foundation_db])
    if min_dates is not None:
        cmd.extend(["--min-dates", str(min_dates)])
    if min_samples_per_grade is not None:
        cmd.extend(["--min-samples-per-grade", str(min_samples_per_grade)])
    run(cmd)
    date_ymd = ymd(date_str)
    calibration_json = ROOT / "outputs" / "strategy_evaluation" / f"strategy_evidence_calibration_{date_ymd}.json"
    status = "unknown"
    if calibration_json.exists():
        try:
            status = json.loads(calibration_json.read_text(encoding="utf-8")).get("status", "unknown")
        except json.JSONDecodeError:
            status = "invalid_json"
    return {
        "ok": status == "ok",
        "status": status,
        "date": date_str,
        "start_date": start_date,
        "calibration_json": str(calibration_json),
        "calibration_markdown": str(ROOT / "outputs" / "strategy_evaluation" / f"strategy_evidence_calibration_{date_ymd}.md"),
    }


def run_classic_backtest(
    date_str: str,
    foundation_db: str | None = None,
    strategy: str = "composite",
    lookback_days: int = 252,
    max_positions: int = 10,
    min_ef: int = 2,
    initial_capital: float = 1_000_000.0,
) -> dict[str, Any]:
    date_ymd = ymd(date_str)
    output_dir = ROOT / "outputs" / f"backtest_{strategy}_{date_ymd}"
    cmd = [
        sys.executable,
        "-m",
        "backtest.engine",
        "--date",
        date_str,
        "--lookback-days",
        str(lookback_days),
        "--output-dir",
        str(output_dir),
        "--max-positions",
        str(max_positions),
        "--min-ef",
        str(min_ef),
        "--initial-capital",
        str(initial_capital),
        "--strategy",
        strategy,
    ]
    if foundation_db:
        cmd.extend(["--foundation-db", foundation_db])
    run(cmd)

    html_path = ROOT / "public" / f"classic_strategy_backtest_{strategy}_{date_ymd}.html"
    run(
        [
            sys.executable,
            "backtest/report.py",
            "--backtest-dir",
            str(output_dir),
            "--out-html",
            str(html_path),
        ]
    )
    return {
        "ok": True,
        "date": date_str,
        "strategy": strategy,
        "foundation_db": foundation_db or str(ROOT / "outputs" / f"p116_foundation_{date_ymd}" / "p116_foundation.duckdb"),
        "lookback_days": lookback_days,
        "max_positions": max_positions,
        "min_ef": min_ef,
        "initial_capital": initial_capital,
        "backtest_json": str(output_dir / "backtest_result.json"),
        "backtest_html": str(html_path),
    }


def build_market_assets_state(date_str: str) -> dict[str, Any]:
    run(
        [
            sys.executable,
            "scripts/build_market_assets_state.py",
            "--date",
            date_str,
        ]
    )
    return {
        "ok": True,
        "date": date_str,
        "market_assets_state_db": str(ROOT / "outputs" / f"market_assets_state_{ymd(date_str)}" / "market_assets_state.duckdb"),
        "market_assets_state_html": str(ROOT / "public" / f"market_assets_state_{ymd(date_str)}.html"),
        "market_assets_state_csv": str(ROOT / "outputs" / "market_assets_state" / f"market_assets_state_{ymd(date_str)}.csv"),
    }


def build_industry_etf_coverage(date_str: str) -> dict[str, Any]:
    run(
        [
            sys.executable,
            "scripts/build_industry_etf_coverage.py",
            "--date",
            date_str,
        ]
    )
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "json": str(ROOT / "outputs" / "etf_coverage" / f"industry_etf_coverage_{date_ymd}.json"),
        "csv": str(ROOT / "outputs" / "etf_coverage" / f"industry_etf_coverage_{date_ymd}.csv"),
        "html": str(ROOT / "public" / f"industry_etf_coverage_{date_ymd}.html"),
        "expanded_config": str(ROOT / "config" / f"industry_rotation_assets.expanded_{date_ymd}.json"),
        "direct_additions_config": str(ROOT / "config" / f"industry_rotation_assets.direct_additions_{date_ymd}.json"),
        "latest_json": str(ROOT / "outputs" / "etf_coverage" / "industry_etf_coverage_latest.json"),
        "latest_html": str(ROOT / "public" / "industry_etf_coverage_latest.html"),
        "research_only": True,
    }


def build_industry_etf_config(date_str: str, apply_config: bool = False, include_proxy: bool = False) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/build_industry_etf_config.py",
        "--date",
        date_str,
    ]
    if include_proxy:
        cmd.append("--include-proxy")
    if apply_config:
        cmd.append("--apply")
    run(cmd)
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "json": str(ROOT / "outputs" / "etf_config" / f"industry_etf_config_{date_ymd}.json"),
        "csv": str(ROOT / "outputs" / "etf_config" / f"industry_etf_config_{date_ymd}.csv"),
        "candidates_json": str(ROOT / "outputs" / "etf_config" / f"industry_etf_candidates_{date_ymd}.json"),
        "candidates_csv": str(ROOT / "outputs" / "etf_config" / f"industry_etf_candidates_{date_ymd}.csv"),
        "gap_json": str(ROOT / "outputs" / "etf_config" / f"industry_etf_gap_report_{date_ymd}.json"),
        "gap_csv": str(ROOT / "outputs" / "etf_config" / f"industry_etf_gap_report_{date_ymd}.csv"),
        "html": str(ROOT / "public" / f"industry_etf_config_{date_ymd}.html"),
        "generated_config": str(ROOT / "config" / f"industry_rotation_assets.auto_{date_ymd}.json"),
        "proxy_whitelist": str(ROOT / "config" / "industry_etf_proxy_whitelist.json"),
        "latest_html": str(ROOT / "public" / "industry_etf_config_latest.html"),
        "applied": apply_config,
        "include_proxy": include_proxy,
        "research_only": True,
    }


def build_ifind_macro(date_str: str, import_file: str | None = None) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/build_ifind_macro_db.py",
        "--date",
        date_str,
        "--allow-missing-token",
    ]
    if import_file:
        cmd.extend(["--import-file", import_file])
        cmd.append("--skip-api")
    run(cmd)
    date_ymd = ymd(date_str)
    output_json = ROOT / "outputs" / "macro" / f"macro_snapshot_{date_ymd}.json"
    summary: dict[str, Any] = {}
    if output_json.exists():
        try:
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            summary = {
                "auth_status": payload.get("collection", {}).get("auth_status"),
                "collected_rows": payload.get("collection", {}).get("collected_rows"),
                "db_row_count": payload.get("collection", {}).get("db_row_count"),
                "coverage_status": payload.get("regime", {}).get("coverage_status"),
                "needs_code_count": payload.get("regime", {}).get("needs_code_count"),
                "one_sentence": payload.get("regime", {}).get("one_sentence"),
            }
        except json.JSONDecodeError:
            summary = {"status": "invalid_json"}
    return {
        "ok": True,
        "date": date_str,
        **summary,
        "json": str(output_json),
        "csv": str(ROOT / "outputs" / "macro" / f"macro_snapshot_{date_ymd}.csv"),
        "html": str(ROOT / "public" / f"macro_snapshot_{date_ymd}.html"),
        "latest_json": str(ROOT / "outputs" / "macro" / "macro_snapshot_latest.json"),
        "latest_html": str(ROOT / "public" / "macro_snapshot_latest.html"),
        "import_file": import_file,
        "research_only": True,
    }


def collect_macro_multisource(date_str: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/collect_macro_multisource.py",
        "--date",
        date_str,
    ]
    run(cmd)
    date_ymd = ymd(date_str)
    output_json = ROOT / "outputs" / "macro" / f"macro_multisource_collection_{date_ymd}.json"
    summary: dict[str, Any] = {}
    if output_json.exists():
        try:
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            summary = {
                "row_count": payload.get("row_count"),
                "inserted_rows": payload.get("inserted_rows"),
                "sources": {
                    source: {
                        "status": meta.get("status"),
                        "rows": meta.get("rows"),
                    }
                    for source, meta in (payload.get("sources") or {}).items()
                    if isinstance(meta, dict)
                },
            }
        except json.JSONDecodeError:
            summary = {"status": "invalid_json"}
    return {
        "ok": True,
        "date": date_str,
        **summary,
        "json": str(output_json),
        "csv": str(ROOT / "outputs" / "macro" / f"macro_multisource_collection_{date_ymd}.csv"),
        "macro_snapshot_json": str(ROOT / "outputs" / "macro" / f"macro_snapshot_{date_ymd}.json"),
        "macro_snapshot_html": str(ROOT / "public" / f"macro_snapshot_{date_ymd}.html"),
        "latest_json": str(ROOT / "outputs" / "macro" / "macro_multisource_collection_latest.json"),
        "research_only": True,
    }


def build_macro_chain_prior(date_str: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/build_macro_chain_prior.py",
        "--date",
        date_str,
    ]
    run(cmd)
    date_ymd = ymd(date_str)
    output_json = ROOT / "outputs" / "macro_chain_prior" / f"macro_chain_prior_{date_ymd}.json"
    summary: dict[str, Any] = {}
    if output_json.exists():
        try:
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            summary = {
                "macro_score": payload.get("macro_prior", {}).get("score_0_10"),
                "risk_appetite_score": payload.get("market_style_prior", {}).get("risk_appetite_score"),
                "growth_style_score": payload.get("market_style_prior", {}).get("growth_style_score"),
                "industry_count": len(payload.get("industry_priors", []) or []),
            }
        except json.JSONDecodeError:
            summary = {"status": "invalid_json"}
    return {
        "ok": True,
        "date": date_str,
        **summary,
        "json": str(output_json),
        "csv": str(ROOT / "outputs" / "macro_chain_prior" / f"macro_chain_prior_{date_ymd}.csv"),
        "html": str(ROOT / "public" / f"macro_chain_prior_{date_ymd}.html"),
        "latest_json": str(ROOT / "outputs" / "macro_chain_prior" / "macro_chain_prior_latest.json"),
        "latest_html": str(ROOT / "public" / "macro_chain_prior_latest.html"),
        "research_only": True,
    }


def build_recommendation(date_str: str) -> dict[str, Any]:
    run([sys.executable, "recommendation/run_recommendation_workflow.py", "--date", date_str])
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "json": str(ROOT / "recommendation" / "outputs" / f"p116_recommendation_{date_ymd}.json"),
        "csv": str(ROOT / "recommendation" / "outputs" / f"p116_recommendation_{date_ymd}.csv"),
        "html": str(ROOT / "public" / f"p116_recommendation_{date_ymd}.html"),
        "public_csv": str(ROOT / "public" / f"p116_recommendation_{date_ymd}.csv"),
        "latest_html": str(ROOT / "public" / "p116_recommendation_latest.html"),
    }


def build_shareable_table(date_str: str) -> dict[str, Any]:
    run([sys.executable, "recommendation/build_shareable_table.py", "--date", date_str])
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "html": str(ROOT / "public" / f"p116_recommendation_shareable_{date_ymd}.html"),
        "csv": str(ROOT / "public" / f"p116_recommendation_shareable_{date_ymd}.csv"),
        "xlsx": str(ROOT / "public" / f"p116_recommendation_shareable_{date_ymd}.xlsx"),
        "latest_html": str(ROOT / "public" / "p116_recommendation_shareable_latest.html"),
    }


def run_pattern_scan(date_str: str, foundation_db: str | None = None) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/pattern_scanner.py",
        "--date",
        date_str,
    ]
    if foundation_db:
        cmd.extend(["--foundation-db", foundation_db])
    run(cmd)
    return {
        "ok": True,
        "date": date_str,
        "lifecycle_db": str(ROOT / "outputs" / "pattern_lifecycle" / "pattern_lifecycle.duckdb"),
    }


def run_pattern_cross(date_str: str) -> dict[str, Any]:
    run(
        [
            sys.executable,
            "scripts/pattern_cross_p116.py",
            "--date",
            date_str,
        ]
    )
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "pattern_cross_json": str(ROOT / "outputs" / "pattern_lifecycle" / f"pattern_cross_ef_{date_ymd}.json"),
        "pattern_cross_csv": str(ROOT / "outputs" / "pattern_lifecycle" / f"pattern_cross_ef_{date_ymd}.csv"),
        "pattern_cross_html": str(ROOT / "public" / f"pattern_cross_ef_{date_ymd}.html"),
    }


def run_fundamental_plan(date_str: str) -> dict[str, Any]:
    run(
        [
            sys.executable,
            "scripts/fundamental_field_planner.py",
            "--date",
            date_str,
        ]
    )
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "field_plan": str(ROOT / "outputs" / "fundamental" / f"fundamental_field_plan_{date_ymd}.json"),
        "field_plan_latest": str(ROOT / "outputs" / "fundamental" / "fundamental_field_plan_latest.json"),
    }


def run_ifind_pool(date_str: str, limit: int = 0) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/ifind_tracking_pool.py",
        "--date",
        date_str,
    ]
    if limit > 0:
        cmd.extend(["--limit", str(limit)])
    run(cmd)
    return {
        "ok": True,
        "date": date_str,
        "limit": limit,
        "fundamental_db": str(ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"),
    }


def run_fundamental_collect(
    date_str: str,
    universe: str = "p116_pattern_cross",
    limit: int = 0,
    refresh: bool = False,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/ifind_fundamental_collector.py",
        "--date",
        date_str,
        "--universe",
        universe,
    ]
    if limit > 0:
        cmd.extend(["--limit", str(limit)])
    if refresh:
        cmd.append("--refresh")
    if "IFIND_REFRESH_TOKEN" not in __import__("os").environ:
        cmd.append("--allow-missing-token")
    run(cmd)
    return {
        "ok": True,
        "date": date_str,
        "universe": universe,
        "limit": limit,
        "refresh": refresh,
        "fundamental_db": str(ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"),
    }


def run_ifind_excel_import(date_str: str, file_path: str, statement_type: str) -> dict[str, Any]:
    if not file_path:
        raise ValueError("--excel-file is required for run_ifind_excel_import")
    cmd = [
        sys.executable,
        "scripts/import_ifind_excel_facts.py",
        "--date",
        date_str,
        "--file",
        file_path,
        "--statement-type",
        statement_type,
    ]
    run(cmd)
    return {
        "ok": True,
        "date": date_str,
        "excel_file": file_path,
        "statement_type": statement_type,
        "fundamental_db": str(ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"),
    }


def run_ifind_chain_import(date_str: str, file_path: str) -> dict[str, Any]:
    if not file_path:
        raise ValueError("--excel-file is required for run_ifind_chain_import")
    cmd = [
        sys.executable,
        "scripts/import_ifind_industry_chain_excel.py",
        "--date",
        date_str,
        "--file",
        file_path,
    ]
    run(cmd)
    return {
        "ok": True,
        "date": date_str,
        "excel_file": file_path,
        "fundamental_db": str(ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"),
    }


def run_fundamental_score(date_str: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/fundamental_scorer.py",
        "--date",
        date_str,
    ]
    run(cmd)
    return {
        "ok": True,
        "date": date_str,
        "fundamental_db": str(ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"),
    }


def run_ai_research_loop(date_str: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/fundamental_ai_research_loop.py",
        "--date",
        date_str,
    ]
    run(cmd)
    return {
        "ok": True,
        "date": date_str,
        "report": str(ROOT / "outputs" / "fundamental" / f"ai_research_loop_{ymd(date_str)}.md"),
    }


def run_fundamental_analyze(date_str: str, limit: int = 20) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/fundamental_deepseek_analyzer.py",
        "--date",
        date_str,
        "--limit",
        str(limit),
    ]
    run(cmd)
    return {
        "ok": True,
        "date": date_str,
        "limit": limit,
        "fundamental_db": str(ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"),
    }


def run_stock_ledger(date_str: str, limit: int = 0) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/build_stock_research_ledger.py",
        "--date",
        date_str,
    ]
    if limit > 0:
        cmd.extend(["--limit", str(limit)])
    run(cmd)
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "limit": limit,
        "ledger_json": str(ROOT / "outputs" / "fundamental" / f"stock_research_ledger_{date_ymd}.json"),
        "ledger_html": str(ROOT / "public" / f"stock_research_ledger_{date_ymd}.html"),
    }


def run_event_radar(date_str: str, import_json: str | None = None) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/ifind_event_radar.py",
        "--date",
        date_str,
    ]
    if import_json:
        cmd.extend(["--import-json", import_json])
    run(cmd)
    return {
        "ok": True,
        "date": date_str,
        "event_digest_db": str(ROOT / "outputs" / "event_digest" / "ifind_event_digest.duckdb"),
        "source": import_json or "no_import",
    }


def run_industry_chain(date_str: str, import_json: str | None = None) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/ifind_industry_chain.py",
        "--date",
        date_str,
    ]
    if import_json:
        cmd.extend(["--import-json", import_json])
    run(cmd)
    return {
        "ok": True,
        "date": date_str,
        "chain_db": str(ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"),
        "source": import_json or "no_import",
    }


def default_ifind_excel_paths(date_str: str) -> dict[str, str]:
    date_ymd = ymd(date_str)
    return {
        "income_core": str(ROOT / "data" / f"ifind_stock_income_core_mrq_{date_ymd}.xlsx"),
        "balance_core": str(ROOT / "data" / f"ifind_stock_balance_core_mrq_{date_ymd}.xlsx"),
        "cashflow_core": str(ROOT / "data" / f"ifind_stock_cashflow_core_mrq_{date_ymd}.xlsx"),
        "industry_chain": str(ROOT / "data" / f"ifind_stock_industry_chain_profile_{date_ymd}.xlsx"),
    }


def require_file(path_str: str, label: str) -> str:
    path = Path(path_str)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"{label} not found or empty: {path}")
    return str(path)


def run_fundamental_weekly(
    date_str: str,
    limit: int = 0,
    universe: str = "tracking_pool",
    income_core_excel: str | None = None,
    balance_core_excel: str | None = None,
    cashflow_core_excel: str | None = None,
    industry_chain_excel: str | None = None,
    skip_api_collect: bool = True,
    skip_ai_profile: bool = False,
) -> dict[str, Any]:
    defaults = default_ifind_excel_paths(date_str)
    excel_paths = {
        "income_core": require_file(income_core_excel or defaults["income_core"], "income_core_excel"),
        "balance_core": require_file(balance_core_excel or defaults["balance_core"], "balance_core_excel"),
        "cashflow_core": require_file(cashflow_core_excel or defaults["cashflow_core"], "cashflow_core_excel"),
        "industry_chain": require_file(industry_chain_excel or defaults["industry_chain"], "industry_chain_excel"),
    }

    steps: list[dict[str, Any]] = []
    steps.append({"run_ifind_pool": run_ifind_pool(date_str, limit)})
    steps.append({"import_income_core_excel": run_ifind_excel_import(date_str, excel_paths["income_core"], "income_core")})
    steps.append({"import_balance_core_excel": run_ifind_excel_import(date_str, excel_paths["balance_core"], "balance_core")})
    steps.append({"import_cashflow_core_excel": run_ifind_excel_import(date_str, excel_paths["cashflow_core"], "cashflow_core")})
    steps.append({"import_industry_chain_excel": run_ifind_chain_import(date_str, excel_paths["industry_chain"])})

    if not skip_api_collect:
        steps.append({"run_fundamental_plan": run_fundamental_plan(date_str)})
        steps.append({"run_fundamental_collect": run_fundamental_collect(date_str, universe, limit, refresh=False)})

    steps.append({"run_fundamental_score": run_fundamental_score(date_str)})

    if not skip_ai_profile:
        steps.append({"run_fundamental_analyze": run_fundamental_analyze(date_str, limit or 20)})

    steps.append({"run_ai_research_loop": run_ai_research_loop(date_str)})
    steps.append({"run_stock_ledger": run_stock_ledger(date_str, limit)})

    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "universe": universe,
        "limit": limit,
        "skip_api_collect": skip_api_collect,
        "skip_ai_profile": skip_ai_profile,
        "excel_paths": excel_paths,
        "steps": steps,
        "outputs": {
            "fundamental_db": str(ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"),
            "ai_research_input": str(ROOT / "outputs" / "fundamental" / f"ai_research_loop_input_{date_ymd}.md"),
            "ai_research_report": str(ROOT / "outputs" / "fundamental" / f"ai_research_loop_{date_ymd}.md"),
            "stock_ledger_json": str(ROOT / "outputs" / "fundamental" / f"stock_research_ledger_{date_ymd}.json"),
            "stock_ledger_html": str(ROOT / "public" / f"stock_research_ledger_{date_ymd}.html"),
        },
    }


def run_ifind_usage_stress(
    date_str: str,
    iterations: int = 200,
    workers: int = 8,
    code_limit: int = 0,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/ifind_usage_stress_test.py",
        "--date",
        date_str,
        "--iterations",
        str(iterations),
        "--workers",
        str(workers),
    ]
    if code_limit > 0:
        cmd.extend(["--code-limit", str(code_limit)])
    run(cmd)
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "iterations": iterations,
        "workers": workers,
        "code_limit": code_limit,
        "json": str(ROOT / "outputs" / "fundamental" / f"ifind_usage_stress_{date_ymd}.json"),
        "markdown": str(ROOT / "outputs" / "fundamental" / f"ifind_usage_stress_{date_ymd}.md"),
    }


def run_state_usage_stress(
    date_str: str,
    iterations: int = 300,
    workers: int = 8,
    code_limit: int = 0,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/state_usage_stress_test.py",
        "--date",
        date_str,
        "--iterations",
        str(iterations),
        "--workers",
        str(workers),
    ]
    if code_limit > 0:
        cmd.extend(["--code-limit", str(code_limit)])
    run(cmd)
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "iterations": iterations,
        "workers": workers,
        "code_limit": code_limit,
        "json": str(ROOT / "outputs" / "state_stress" / f"state_usage_stress_{date_ymd}.json"),
        "markdown": str(ROOT / "outputs" / "state_stress" / f"state_usage_stress_{date_ymd}.md"),
    }


def build_state_cache(
    date_str: str,
    foundation_db: str | None = None,
    boundary_pct: float = 0.03,
) -> dict[str, Any]:
    return a_share_core.build_state_cache(date_str, foundation_db=foundation_db, boundary_pct=boundary_pct)


def build_strategy_signal_ledger(
    date_str: str,
    foundation_db: str | None = None,
    min_ef: int = 2,
) -> dict[str, Any]:
    return a_share_core.build_strategy_signal_ledger(date_str, foundation_db=foundation_db, min_ef=min_ef)


def build_strategy_reminder(date_str: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/strategy_reminder_brief.py",
        "--date",
        date_str,
    ]
    run(cmd)
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "date": date_str,
        "reminder_json": str(ROOT / "outputs" / "strategy_reminders" / f"reminder_{date_ymd}.json"),
        "reminder_html": str(ROOT / "public" / f"strategy_reminder_{date_ymd}.html"),
    }


def forward_sim(date_str: str, foundation_db: str | None = None, windows: str = "5,10,20") -> dict[str, Any]:
    return a_share_core.build_forward_observation(date_str, foundation_db=foundation_db, windows=windows)


def search_2560_optimal_state(
    date_str: str,
    start_date: str | None,
    foundation_db: str | None = None,
    raw_signal: str = "ma2560_golden_cross",
    min_samples: int = 20,
    primary_window: int = 20,
    min_ef_count: int | None = None,
    max_ef_count: int | None = None,
) -> dict[str, Any]:
    if not start_date:
        raise ValueError("search_2560_optimal_state requires --start-date")
    cmd = [
        sys.executable,
        "scripts/search_2560_optimal_state.py",
        "--start-date",
        start_date,
        "--end-date",
        date_str,
        "--raw-signal",
        raw_signal,
        "--primary-window",
        str(primary_window),
        "--min-samples",
        str(min_samples),
    ]
    if foundation_db:
        cmd.extend(["--foundation-db", foundation_db])
    if min_ef_count is not None:
        cmd.extend(["--min-ef-count", str(min_ef_count)])
    if max_ef_count is not None:
        cmd.extend(["--max-ef-count", str(max_ef_count)])
    run(cmd)

    tag_signal = raw_signal.replace("ma2560_", "")
    scope = "all"
    if min_ef_count is not None or max_ef_count is not None:
        scope = f"ef{'' if min_ef_count is None else min_ef_count}to{'' if max_ef_count is None else max_ef_count}"
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "research_only": True,
        "date": date_str,
        "start_date": start_date,
        "raw_signal": raw_signal,
        "json": str(ROOT / "outputs" / "strategy_evaluation" / f"ma2560_optimal_state_search_{date_ymd}_{tag_signal}_{scope}.json"),
        "markdown": str(ROOT / "outputs" / "strategy_evaluation" / f"ma2560_optimal_state_search_{date_ymd}_{tag_signal}_{scope}.md"),
    }


def search_bollinger_optimal_state(
    date_str: str,
    start_date: str | None,
    foundation_db: str | None = None,
    min_samples: int = 30,
    primary_window: int = 20,
    min_ef_count: int | None = None,
    max_ef_count: int | None = None,
) -> dict[str, Any]:
    if not start_date:
        raise ValueError("search_bollinger_optimal_state requires --start-date")
    cmd = [
        sys.executable,
        "scripts/search_bollinger_optimal_state.py",
        "--start-date",
        start_date,
        "--end-date",
        date_str,
        "--primary-window",
        str(primary_window),
        "--min-samples",
        str(min_samples),
    ]
    if foundation_db:
        cmd.extend(["--foundation-db", foundation_db])
    if min_ef_count is not None:
        cmd.extend(["--min-ef-count", str(min_ef_count)])
    if max_ef_count is not None:
        cmd.extend(["--max-ef-count", str(max_ef_count)])
    run(cmd)

    scope = "all"
    if min_ef_count is not None or max_ef_count is not None:
        scope = f"ef{'' if min_ef_count is None else min_ef_count}to{'' if max_ef_count is None else max_ef_count}"
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "research_only": True,
        "date": date_str,
        "start_date": start_date,
        "json": str(ROOT / "outputs" / "strategy_evaluation" / f"bollinger_optimal_state_search_{date_ymd}_entry_{scope}.json"),
        "markdown": str(ROOT / "outputs" / "strategy_evaluation" / f"bollinger_optimal_state_search_{date_ymd}_entry_{scope}.md"),
        "project_markdown": str(ROOT / "outputs" / "project" / "bollinger_optimal_state_search.md"),
    }


def search_vcp_optimal_state(
    date_str: str,
    start_date: str | None,
    foundation_db: str | None = None,
    raw_signal: str | None = None,
    min_samples: int = 30,
    primary_window: int = 20,
    min_ef_count: int | None = None,
    max_ef_count: int | None = None,
) -> dict[str, Any]:
    if not start_date:
        raise ValueError("search_vcp_optimal_state requires --start-date")
    cmd = [
        sys.executable,
        "scripts/search_vcp_optimal_state.py",
        "--start-date",
        start_date,
        "--end-date",
        date_str,
        "--primary-window",
        str(primary_window),
        "--min-samples",
        str(min_samples),
    ]
    if raw_signal:
        cmd.extend(["--raw-signal", raw_signal])
    if foundation_db:
        cmd.extend(["--foundation-db", foundation_db])
    if min_ef_count is not None:
        cmd.extend(["--min-ef-count", str(min_ef_count)])
    if max_ef_count is not None:
        cmd.extend(["--max-ef-count", str(max_ef_count)])
    run(cmd)

    scope = "all"
    if min_ef_count is not None or max_ef_count is not None:
        scope = f"ef{'' if min_ef_count is None else min_ef_count}to{'' if max_ef_count is None else max_ef_count}"
    signal_tag = (raw_signal or "breakout_breakout_no_vol_breakout_weak_vol").replace("vcp_", "")
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "research_only": True,
        "date": date_str,
        "start_date": start_date,
        "json": str(ROOT / "outputs" / "strategy_evaluation" / f"vcp_optimal_state_search_{date_ymd}_{signal_tag}_{scope}.json"),
        "markdown": str(ROOT / "outputs" / "strategy_evaluation" / f"vcp_optimal_state_search_{date_ymd}_{signal_tag}_{scope}.md"),
        "project_markdown": str(ROOT / "outputs" / "project" / "vcp_optimal_state_search.md"),
    }


def verify_strategy_environment(
    date_str: str,
    start_date: str | None,
    foundation_db: str | None,
    verify_strategy: str = "all",
    raw_signal: str | None = None,
    min_samples: int = 30,
    primary_window: int = 20,
    min_ef_count: int | None = None,
    max_ef_count: int | None = None,
    macro_snapshot: str | None = None,
) -> dict[str, Any]:
    if not start_date:
        raise ValueError("verify_strategy_environment requires --start-date")
    if not foundation_db:
        foundation_db = str(foundation_path(date_str, None))
    cmd = [
        sys.executable,
        "scripts/strategy_environment_verifier.py",
        "--strategy",
        verify_strategy,
        "--start-date",
        start_date,
        "--end-date",
        date_str,
        "--foundation-db",
        foundation_db,
        "--primary-window",
        str(primary_window),
        "--min-samples",
        str(min_samples),
    ]
    if raw_signal:
        cmd.extend(["--raw-signal", raw_signal])
    if min_ef_count is not None:
        cmd.extend(["--min-ef-count", str(min_ef_count)])
    if max_ef_count is not None:
        cmd.extend(["--max-ef-count", str(max_ef_count)])
    if macro_snapshot:
        cmd.extend(["--macro-snapshot", macro_snapshot])
    run(cmd)

    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "research_only": True,
        "date": date_str,
        "start_date": start_date,
        "strategy": verify_strategy,
        "json": str(ROOT / "outputs" / "project" / f"strategy_environment_verification_{verify_strategy}_{date_ymd}.json"),
        "markdown": str(ROOT / "outputs" / "project" / f"strategy_environment_verification_{verify_strategy}_{date_ymd}.md"),
    }


def run_strategy_fit_observer(date_str: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/strategy_fit_observer.py",
        "--date",
        date_str,
    ]
    run(cmd)
    date_ymd = ymd(date_str)
    output_json = ROOT / "outputs" / "strategy_fit_observer" / f"fit_log_{date_ymd}.json"
    summary: dict[str, Any] = {}
    if output_json.exists():
        try:
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            summary = {
                "signal_count": payload.get("signal_count"),
                "fit_counts": payload.get("fit_counts"),
                "lifecycle_counts": payload.get("lifecycle_counts"),
                "strategy_counts": payload.get("strategy_counts"),
            }
        except json.JSONDecodeError:
            summary = {"status": "invalid_json"}
    return {
        "ok": True,
        "date": date_str,
        **summary,
        "fit_db": str(ROOT / "outputs" / "strategy_fit_observer" / "fit_log.duckdb"),
        "json": str(output_json),
        "csv": str(ROOT / "outputs" / "strategy_fit_observer" / f"fit_log_{date_ymd}.csv"),
        "latest_json": str(ROOT / "outputs" / "strategy_fit_observer" / "fit_log_latest.json"),
        "research_only": True,
    }


def process_ifind_data(date_str: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/ifind_data_processor.py",
        "--date",
        date_str,
    ]
    run(cmd)
    date_ymd = ymd(date_str)
    output_json = ROOT / "outputs" / "ifind" / f"financial_{date_ymd}.json"
    summary: dict[str, Any] = {}
    if output_json.exists():
        try:
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            summary = {
                "financial_total": payload.get("total"),
                "quality_counts": payload.get("quality_counts"),
            }
        except json.JSONDecodeError:
            summary = {"status": "invalid_json"}
    return {
        "ok": True,
        "date": date_str,
        **summary,
        "financial_json": str(output_json),
        "industry_json": str(ROOT / "outputs" / "ifind" / f"industry_{date_ymd}.json"),
        "financial_latest": str(ROOT / "outputs" / "ifind" / "financial_latest.json"),
        "industry_latest": str(ROOT / "outputs" / "ifind" / "industry_latest.json"),
        "research_only": True,
    }


def generate_daily_brief(date_str: str) -> dict[str, Any]:
    return a_share_core.build_daily_brief(date_str)


def analyze_ma2560_market_match_forward(date_str: str, foundation_db: str | None = None) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/analyze_ma2560_market_match_forward.py",
        "--date",
        date_str,
    ]
    if foundation_db:
        cmd.extend(["--foundation-db", foundation_db])
    run(cmd)
    date_ymd = ymd(date_str)
    output_json = ROOT / "outputs" / "ma2560_market_match_forward" / f"ma2560_market_match_forward_{date_ymd}.json"
    summary: dict[str, Any] = {}
    if output_json.exists():
        try:
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            summary = {
                "total": payload.get("total"),
                "summary": payload.get("summary"),
            }
        except json.JSONDecodeError:
            summary = {"status": "invalid_json"}
    return {
        "ok": True,
        "date": date_str,
        **summary,
        "json": str(output_json),
        "csv": str(ROOT / "outputs" / "ma2560_market_match_forward" / f"ma2560_market_match_forward_{date_ymd}.csv"),
        "markdown": str(ROOT / "outputs" / "ma2560_market_match_forward" / f"ma2560_market_match_forward_{date_ymd}.md"),
        "html": str(ROOT / "public" / f"ma2560_market_match_forward_{date_ymd}.html"),
        "latest_json": str(ROOT / "outputs" / "ma2560_market_match_forward" / "ma2560_market_match_forward_latest.json"),
        "latest_html": str(ROOT / "public" / "ma2560_market_match_forward_latest.html"),
        "research_only": True,
    }


def audit_ma2560_stock_only_gap(date_str: str) -> dict[str, Any]:
    run(
        [
            sys.executable,
            "scripts/audit_ma2560_stock_only_industry_gap.py",
            "--date",
            date_str,
        ]
    )
    date_ymd = ymd(date_str)
    output_json = ROOT / "outputs" / "ma2560_market_match_forward" / f"ma2560_stock_only_gap_audit_{date_ymd}.json"
    summary: dict[str, Any] = {}
    if output_json.exists():
        try:
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            summary = {
                "total": payload.get("total"),
                "gap_counts": payload.get("gap_counts"),
                "industry_counts": payload.get("industry_counts"),
            }
        except json.JSONDecodeError:
            summary = {"status": "invalid_json"}
    return {
        "ok": True,
        "date": date_str,
        **summary,
        "json": str(output_json),
        "csv": str(ROOT / "outputs" / "ma2560_market_match_forward" / f"ma2560_stock_only_gap_audit_{date_ymd}.csv"),
        "html": str(ROOT / "public" / f"ma2560_stock_only_gap_audit_{date_ymd}.html"),
        "latest_json": str(ROOT / "outputs" / "ma2560_market_match_forward" / "ma2560_stock_only_gap_audit_latest.json"),
        "latest_html": str(ROOT / "public" / "ma2560_stock_only_gap_audit_latest.html"),
        "research_only": True,
    }


def generate_strategy_outcome_report(
    signal_date: str,
    as_of_date: str,
    foundation_db: str | None = None,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/strategy_outcome_report.py",
        "--signal-date",
        signal_date,
        "--as-of-date",
        as_of_date,
    ]
    if foundation_db:
        cmd.extend(["--foundation-db", foundation_db])
    run(cmd)
    signal_ymd = ymd(signal_date)
    as_of_ymd = ymd(as_of_date)
    output_json = ROOT / "outputs" / "strategy_outcome_report" / f"strategy_outcome_{signal_ymd}_to_{as_of_ymd}.json"
    summary: dict[str, Any] = {}
    if output_json.exists():
        try:
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            summary = {
                "input_reminders": payload.get("meta", {}).get("input_reminders"),
                "tracked_rows": payload.get("meta", {}).get("rows"),
                "aggregate": payload.get("aggregate"),
            }
        except json.JSONDecodeError:
            summary = {"status": "invalid_json"}
    return {
        "ok": True,
        "signal_date": signal_date,
        "as_of_date": as_of_date,
        **summary,
        "json": str(output_json),
        "markdown": str(ROOT / "outputs" / "strategy_outcome_report" / f"strategy_outcome_{signal_ymd}_to_{as_of_ymd}.md"),
        "html": str(ROOT / "public" / f"strategy_outcome_{signal_ymd}_to_{as_of_ymd}.html"),
        "latest_html": str(ROOT / "public" / "strategy_outcome_latest.html"),
        "research_only": True,
    }


def generate_strategy_outcome_range_report(
    start_date: str,
    end_date: str,
    as_of_date: str,
    foundation_db: str | None = None,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/strategy_outcome_report.py",
        "--start-date",
        start_date,
        "--end-date",
        end_date,
        "--as-of-date",
        as_of_date,
    ]
    if foundation_db:
        cmd.extend(["--foundation-db", foundation_db])
    run(cmd)
    start_ymd = ymd(start_date)
    end_ymd = ymd(end_date)
    as_of_ymd = ymd(as_of_date)
    output_json = ROOT / "outputs" / "strategy_outcome_report" / f"strategy_outcome_range_{start_ymd}_{end_ymd}_to_{as_of_ymd}.json"
    summary: dict[str, Any] = {}
    if output_json.exists():
        try:
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            summary = {
                "signal_date_count": payload.get("meta", {}).get("signal_date_count"),
                "input_reminders": payload.get("meta", {}).get("input_reminders"),
                "tracked_rows": payload.get("meta", {}).get("rows"),
                "aggregate": payload.get("aggregate"),
            }
        except json.JSONDecodeError:
            summary = {"status": "invalid_json"}
    return {
        "ok": True,
        "start_date": start_date,
        "end_date": end_date,
        "as_of_date": as_of_date,
        **summary,
        "json": str(output_json),
        "top50_json": str(ROOT / "outputs" / "strategy_outcome_report" / f"strategy_outcome_range_{start_ymd}_{end_ymd}_to_{as_of_ymd}_top50.json"),
        "markdown": str(ROOT / "outputs" / "strategy_outcome_report" / f"strategy_outcome_range_{start_ymd}_{end_ymd}_to_{as_of_ymd}.md"),
        "html": str(ROOT / "public" / f"strategy_outcome_range_{start_ymd}_{end_ymd}_to_{as_of_ymd}.html"),
        "latest_html": str(ROOT / "public" / "strategy_outcome_range_latest.html"),
        "research_only": True,
    }


def replay_output_paths(date_str: str) -> dict[str, Path]:
    date_ymd = ymd(date_str)
    return {
        "state_cache": ROOT / "outputs" / "state_cache" / f"state_cache_manifest_{date_ymd}.json",
        "signal_ledger": ROOT / "outputs" / "strategy_signals" / f"strategy_signal_daily_{date_ymd}.json",
        "strategy_evaluation": ROOT / "outputs" / "strategy_evaluation" / f"strategy_evaluation_{date_ymd}.json",
        "reminder": ROOT / "outputs" / "strategy_reminders" / f"reminder_{date_ymd}.json",
    }


def replay_latest_paths(steps: list[str]) -> list[Path]:
    paths: list[Path] = []
    if "state_cache" in steps:
        paths.extend(
            [
                ROOT / "outputs" / "state_cache" / "state_ef_latest.json",
                ROOT / "outputs" / "state_cache" / "state_distribution_latest.json",
                ROOT / "outputs" / "state_cache" / "state_transition_latest.json",
                ROOT / "outputs" / "state_cache" / "sr_boundary_latest.json",
                ROOT / "outputs" / "state_cache" / "state_duration_latest.json",
                ROOT / "outputs" / "state_cache" / "state_cache_manifest_latest.json",
            ]
        )
    if "signal_ledger" in steps:
        paths.append(ROOT / "outputs" / "strategy_signals" / "strategy_signal_daily_latest.json")
    if "strategy_evaluation" in steps:
        paths.extend(
            [
                ROOT / "outputs" / "strategy_evaluation" / "strategy_evaluation_latest.json",
                ROOT / "public" / "strategy_evaluation_latest.html",
            ]
        )
    if "reminder" in steps:
        paths.extend(
            [
                ROOT / "outputs" / "strategy_reminders" / "reminder_latest.json",
                ROOT / "public" / "strategy_reminder_latest.html",
            ]
        )
    return paths


def snapshot_files(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def restore_files(snapshots: dict[Path, bytes | None]) -> None:
    for path, data in snapshots.items():
        if data is None:
            if path.exists():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def has_foundation_data(foundation_db: Path, date_str: str) -> dict[str, Any]:
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        state_rows = con.execute(
            "SELECT COUNT(*) FROM d1_perspective_state WHERE state_date = CAST(? AS DATE)",
            (date_str,),
        ).fetchone()[0]
        daily_columns = {
            row[1]
            for row in con.execute("PRAGMA table_info('daily_bars')").fetchall()
        }
        daily_date_col = "trade_date" if "trade_date" in daily_columns else "date"
        bar_rows = con.execute(
            f"SELECT COUNT(*) FROM daily_bars WHERE {daily_date_col} = CAST(? AS DATE)",
            (date_str,),
        ).fetchone()[0]
    finally:
        con.close()
    return {
        "ok": state_rows > 0 and bar_rows > 0,
        "state_rows": state_rows,
        "daily_bar_rows": bar_rows,
        "daily_date_column": daily_date_col,
    }


def replay_date(
    date_str: str,
    foundation_db: Path,
    steps: list[str],
    *,
    skip_existing: bool,
    force: bool,
    top_n: int,
) -> dict[str, Any]:
    paths = replay_output_paths(date_str)
    selected_paths = {step: paths[step] for step in steps}
    if skip_existing and not force and all(path.exists() for path in selected_paths.values()):
        return {
            "date": date_str,
            "status": "skipped",
            "reason": "outputs_exist",
            "steps": {step: "skipped_existing" for step in steps},
        }

    coverage = has_foundation_data(foundation_db, date_str)
    if not coverage["ok"]:
        return {
            "date": date_str,
            "status": "missing_foundation_data",
            "coverage": coverage,
            "steps": {},
        }

    step_status: dict[str, str] = {}
    try:
        if "state_cache" in steps:
            if force or not skip_existing or not paths["state_cache"].exists():
                with STATE_CACHE_REPLAY_LOCK:
                    build_state_cache(date_str, str(foundation_db))
                step_status["state_cache"] = "ok"
            else:
                step_status["state_cache"] = "skipped_existing"
        if "signal_ledger" in steps:
            if force or not skip_existing or not paths["signal_ledger"].exists():
                with SIGNAL_LEDGER_REPLAY_LOCK:
                    build_strategy_signal_ledger(date_str, str(foundation_db))
                step_status["signal_ledger"] = "ok"
            else:
                step_status["signal_ledger"] = "skipped_existing"
        if "strategy_evaluation" in steps:
            if force or not skip_existing or not paths["strategy_evaluation"].exists():
                evaluate_strategy_evidence(date_str, top_n)
                step_status["strategy_evaluation"] = "ok"
            else:
                step_status["strategy_evaluation"] = "skipped_existing"
        if "reminder" in steps:
            if force or not skip_existing or not paths["reminder"].exists():
                build_strategy_reminder(date_str)
                step_status["reminder"] = "ok"
            else:
                step_status["reminder"] = "skipped_existing"
    except Exception as exc:
        return {
            "date": date_str,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "steps": step_status,
        }

    return {
        "date": date_str,
        "status": "success",
        "coverage": coverage,
        "steps": step_status,
    }


def replay_history(
    start_date: str,
    end_date: str,
    foundation_db: str | None = None,
    steps_arg: str | None = None,
    workers: int = 4,
    skip_existing: bool = True,
    force: bool = False,
    auto_calibrate: bool = False,
    calibration_date: str | None = None,
    update_latest: bool = False,
    top_n: int = 80,
) -> dict[str, Any]:
    dates = date_range(start_date, end_date)
    db_path = foundation_path(end_date, foundation_db)
    if not db_path.exists():
        raise FileNotFoundError(f"foundation DB not found: {db_path}")
    steps = parse_steps(steps_arg)
    if force:
        skip_existing = False
    latest_snapshots: dict[Path, bytes | None] = {}
    if not update_latest:
        latest_snapshots = snapshot_files(replay_latest_paths(steps))

    results: list[dict[str, Any]] = []
    max_workers = max(1, workers)
    print(
        f"Replay {len(dates)} dates from {start_date} to {end_date}; "
        f"steps={','.join(steps)} workers={max_workers}",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                replay_date,
                item,
                db_path,
                steps,
                skip_existing=skip_existing,
                force=force,
                top_n=top_n,
            ): item
            for item in dates
        }
        completed = 0
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            results.append(result)
            step_summary = " ".join(f"{k}:{v}" for k, v in result.get("steps", {}).items())
            print(f"[{result['date']}] {completed}/{len(dates)} {result['status']} {step_summary}", flush=True)

    if latest_snapshots:
        restore_files(latest_snapshots)

    results.sort(key=lambda item: item["date"])
    status_counts: dict[str, int] = {}
    for item in results:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1

    report = {
        "ok": status_counts.get("failed", 0) == 0,
        "start_date": start_date,
        "end_date": end_date,
        "foundation_db": str(db_path),
        "steps": steps,
        "workers": max_workers,
        "skip_existing": skip_existing,
        "force": force,
        "update_latest": update_latest,
        "total_dates": len(dates),
        "status_counts": status_counts,
        "success": status_counts.get("success", 0),
        "skipped": status_counts.get("skipped", 0),
        "failed": status_counts.get("failed", 0),
        "missing_foundation_data": status_counts.get("missing_foundation_data", 0),
        "failed_dates": [item["date"] for item in results if item["status"] == "failed"],
        "missing_foundation_dates": [item["date"] for item in results if item["status"] == "missing_foundation_data"],
        "results": results,
    }

    if auto_calibrate:
        calibration_end = calibration_date or end_date
        report["calibration"] = calibrate_strategy_evidence(
            calibration_end,
            start_date=start_date,
            foundation_db=str(db_path),
        )
        report["ok"] = report["ok"] and bool(report["calibration"].get("ok"))

    out_dir = ROOT / "outputs" / "replay_history"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"replay_history_{ymd(start_date)}_{ymd(end_date)}.json"
    report["report_json"] = str(out_path)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return report


def import_moneyflow_db_range(end_date: str, days: int = 5) -> dict[str, Any]:
    from datetime import date, timedelta

    target_dates: list[str] = []
    current = date.fromisoformat(end_date)
    while len(target_dates) < days:
        if current.weekday() < 5:
            target_dates.append(current.isoformat())
        current -= timedelta(days=1)
    target_dates = sorted(target_dates)
    results = []
    for trade_date in target_dates:
        results.append(import_moneyflow_db(trade_date))
    return {"ok": True, "dates": target_dates, "results": results}


def build_moneyflow_evidence(date_str: str, days: int = 5) -> dict[str, Any]:
    run(
        [
            sys.executable,
            "blackwolf_actions/build_moneyflow_evidence.py",
            "--date",
            date_str,
            "--days",
            str(days),
            "--no-csv-fallback",
        ]
    )
    date_ymd = ymd(date_str)
    return {
        "ok": True,
        "moneyflow_evidence_csv": str(ROOT / "outputs" / "moneyflow_evidence" / f"moneyflow_evidence_{date_ymd}.csv"),
        "moneyflow_evidence_json": str(ROOT / "outputs" / "moneyflow_evidence" / f"moneyflow_evidence_{date_ymd}.json"),
    }


def preflight(date_str: str, previous_date: str) -> dict[str, Any]:
    return a_share_core.preflight(date_str, previous_date)


def build_foundation(date_str: str, raw_db: str | None = None, foundation_db: str | None = None) -> dict[str, Any]:
    return a_share_core.build_foundation(date_str, raw_db=raw_db, foundation_db=foundation_db)


def validate_foundation(date_str: str, foundation_db: str | None) -> dict[str, Any]:
    return a_share_core.validate_foundation(date_str, foundation_db)


def verify_public_outputs(date_str: str, foundation_db: str | None = None) -> dict[str, Any]:
    return a_share_core.verify_public_outputs(date_str, foundation_db=foundation_db)


def _append_step(steps: list[dict[str, Any]], name: str, result: dict[str, Any]) -> None:
    steps.append({name: result})


def _run_export_all_three_ef(date_str: str, previous_date: str, foundation_db: str) -> dict[str, Any]:
    run(
        [
            sys.executable,
            "scripts/export_daily_all_three_ef.py",
            "--date",
            date_str,
            "--previous-date",
            previous_date,
            "--foundation-db",
            foundation_db,
        ]
    )
    return {"ok": True, "date": date_str, "foundation_db": foundation_db}


def _run_optional_data_prep(
    steps: list[dict[str, Any]],
    *,
    date_str: str,
    previous_date: str,
    download: bool,
    build_raw: bool,
    download_moneyflow_flag: bool,
    moneyflow_days: int,
    test_download: bool,
) -> None:
    if download:
        _append_step(steps, "download_daily", download_daily(date_str, previous_date, test_download))
    if build_raw:
        _append_step(steps, "build_raw_db", build_raw_db(date_str, test=test_download))
    if not download_moneyflow_flag:
        return
    _append_step(steps, "download_moneyflow_recent", download_moneyflow(date_str, days=moneyflow_days))
    if moneyflow_days > 1:
        _append_step(steps, "import_moneyflow_db_range", import_moneyflow_db_range(date_str, moneyflow_days))
    else:
        _append_step(steps, "import_moneyflow_db", import_moneyflow_db(date_str))
    _append_step(steps, "build_moneyflow_evidence", build_moneyflow_evidence(date_str, days=5))
    _append_step(steps, "download_market_assets", download_market_assets(date_str, days=1))
    _append_step(steps, "import_market_assets_db", import_market_assets_db(date_str))
    _append_step(steps, "build_market_assets_state", build_market_assets_state(date_str))


def _run_base_macro_prep(
    steps: list[dict[str, Any]],
    *,
    date_str: str,
    foundation_db: str | None,
    build_foundation_flag: bool,
) -> str:
    _append_step(steps, "build_ifind_macro", build_ifind_macro(date_str))
    _append_step(steps, "collect_macro_multisource", collect_macro_multisource(date_str))
    if build_foundation_flag:
        _append_step(steps, "build_foundation", build_foundation(date_str, foundation_db=foundation_db))
    validation = validate_foundation(date_str, foundation_db)
    return validation["foundation_db"]


def _run_core_public_lane(
    steps: list[dict[str, Any]],
    *,
    date_str: str,
    previous_date: str,
    foundation_db: str,
) -> None:
    _append_step(steps, "export_all_three_ef", _run_export_all_three_ef(date_str, previous_date, foundation_db))
    _append_step(steps, "build_industry_etf_coverage", build_industry_etf_coverage(date_str))
    _append_step(steps, "build_industry_etf_config_pre_audit", build_industry_etf_config(date_str))
    _append_step(steps, "build_macro_chain_prior", build_macro_chain_prior(date_str))
    core_steps = a_share_core.run_core_steps_from_foundation(
        date_str,
        foundation_db,
        steps=["build_state_cache", "build_strategy_evidence"],
    )
    _append_step(steps, "build_state_cache", core_steps["build_state_cache"])
    _append_step(steps, "build_strategy_evidence", core_steps["build_strategy_evidence"])
    _append_step(steps, "run_pattern_scan", run_pattern_scan(date_str, foundation_db))
    _append_step(steps, "run_pattern_cross", run_pattern_cross(date_str))
    _append_step(steps, "evaluate_strategy_evidence", evaluate_strategy_evidence(date_str))
    _append_step(steps, "build_recommendation", build_recommendation(date_str))
    _append_step(steps, "build_industry_rotation", build_industry_rotation(date_str))
    _append_step(steps, "build_shareable_table", build_shareable_table(date_str))
    post_recommendation_core_steps = a_share_core.run_core_steps_from_foundation(
        date_str,
        foundation_db,
        steps=["build_strategy_signal_ledger", "build_forward_observation", "build_daily_brief"],
    )
    _append_step(steps, "build_strategy_signal_ledger", post_recommendation_core_steps["build_strategy_signal_ledger"])
    _append_step(steps, "build_strategy_reminder", build_strategy_reminder(date_str))
    _append_step(steps, "forward_sim", post_recommendation_core_steps["build_forward_observation"])
    _append_step(steps, "run_strategy_fit_observer", run_strategy_fit_observer(date_str))
    _append_step(steps, "generate_daily_brief", post_recommendation_core_steps["build_daily_brief"])


def _run_diagnostics_lane(
    steps: list[dict[str, Any]],
    *,
    date_str: str,
    foundation_db: str,
) -> None:
    _append_step(steps, "analyze_ma2560_market_match_forward", analyze_ma2560_market_match_forward(date_str, foundation_db))
    _append_step(steps, "audit_ma2560_stock_only_gap", audit_ma2560_stock_only_gap(date_str))
    _append_step(steps, "build_industry_etf_config", build_industry_etf_config(date_str, apply_config=True))


def run_full_workflow(
    date_str: str,
    previous_date: str,
    foundation_db: str | None,
    *,
    download: bool = False,
    build_raw: bool = False,
    download_moneyflow_flag: bool = False,
    moneyflow_days: int = 1,
    build_foundation_flag: bool = False,
    test_download: bool = False,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    _append_step(steps, "preflight_freshness", preflight(date_str, previous_date))
    _run_optional_data_prep(
        steps,
        date_str=date_str,
        previous_date=previous_date,
        download=download,
        build_raw=build_raw,
        download_moneyflow_flag=download_moneyflow_flag,
        moneyflow_days=moneyflow_days,
        test_download=test_download,
    )
    db_path = _run_base_macro_prep(
        steps,
        date_str=date_str,
        foundation_db=foundation_db,
        build_foundation_flag=build_foundation_flag,
    )
    _run_core_public_lane(
        steps,
        date_str=date_str,
        previous_date=previous_date,
        foundation_db=db_path,
    )
    _run_diagnostics_lane(
        steps,
        date_str=date_str,
        foundation_db=db_path,
    )
    verification = verify_public_outputs(date_str, foundation_db=db_path)
    return {
        "date": date_str,
        "previous_date": previous_date,
        "foundation_db": db_path,
        "steps": steps,
        "outputs": verification["outputs"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Agently-compatible P116 stock pool DAG runner.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--date", default="2026-05-20")
        p.add_argument("--previous-date", default="2026-05-19")
        p.add_argument("--foundation-db")
        p.add_argument("--download", action="store_true", help="Download Blackwolf daily zip first.")
        p.add_argument("--test-download", action="store_true", help="Write *_test.zip for the daily download action.")
        p.add_argument("--build-raw", action="store_true", help="Build P108 raw DuckDB from downloaded/source zip.")
        p.add_argument("--download-moneyflow", action="store_true", help="Download recent Blackwolf moneyflow as a required data layer.")
        p.add_argument("--moneyflow-days", type=int, default=1, help="Moneyflow trading days to download. Default is current day only for the base update.")
        p.add_argument("--moneyflow-limit", type=int, help="Limit moneyflow codes for smoke tests.")
        p.add_argument("--moneyflow-workers", type=int, default=16)
        p.add_argument("--build-foundation", action="store_true", help="Build P116 foundation DB from raw DuckDB.")
        p.add_argument("--source-zip")
        p.add_argument("--lookback-days", type=int, default=20, help="Lookback trading days for strategy evidence.")
        p.add_argument("--backtest-lookback-days", type=int, default=252, help="Lookback trading days for classic strategy backtest.")
        p.add_argument("--strategy", choices=["ef", "composite"], default="composite", help="Backtest strategy mode. composite uses classic strategy signals.")
        p.add_argument("--max-positions", type=int, default=10, help="Maximum simultaneous positions for backtest.")
        p.add_argument("--min-ef", type=int, default=2, help="Minimum E/F cycle count for backtest entries.")
        p.add_argument("--initial-capital", type=float, default=1_000_000.0, help="Initial capital for backtest.")
        p.add_argument("--universe", default="p116_pattern_cross", choices=["p116_pattern_cross", "ef_pool", "tracking_pool"], help="Universe for fundamental collection.")
        p.add_argument("--limit", type=int, default=0, help="Limit rows/stocks for smoke tests.")
        p.add_argument("--refresh", action="store_true", help="Force same-day iFind re-collection for fundamental collector.")
        p.add_argument("--excel-file", help="iFinD GUI Excel export path for fundamental facts import.")
        p.add_argument("--macro-import-file", help="iFinD GUI macro export path for build_ifind_macro.")
        p.add_argument("--statement-type", default="financial_statement", help="Statement/fact group name for iFinD Excel import.")
        p.add_argument("--income-core-excel", help="iFinD GUI Excel path for core income statement facts.")
        p.add_argument("--balance-core-excel", help="iFinD GUI Excel path for core balance sheet facts.")
        p.add_argument("--cashflow-core-excel", help="iFinD GUI Excel path for core cashflow facts.")
        p.add_argument("--industry-chain-excel", help="iFinD GUI Excel path for industry-chain profile facts.")
        p.add_argument("--with-api-collect", action="store_true", help="Also run iFinD API collector after GUI Excel import.")
        p.add_argument("--with-ai-profile", action="store_true", help="Also run per-stock DeepSeek profile analyzer.")
        p.add_argument("--iterations", type=int, default=200, help="Iterations for read-heavy stress tests.")
        p.add_argument("--workers", type=int, default=8, help="Worker threads for read-heavy stress tests.")
        p.add_argument("--code-limit", type=int, default=0, help="Limit stock universe for stress tests.")
        p.add_argument("--boundary-pct", type=float, default=0.03, help="SR boundary distance threshold for state cache.")
        p.add_argument("--top-n", type=int, default=80, help="Top rows for strategy evidence evaluation.")
        p.add_argument("--start-date", help="Start date for historical calibration.")
        p.add_argument("--end-date", help="End date for historical replay.")
        p.add_argument("--steps", help="Comma-separated replay steps: state_cache,signal_ledger,strategy_evaluation,reminder.")
        p.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
        p.add_argument("--force", action="store_true", help="Rebuild replay outputs even when they already exist.")
        p.add_argument("--auto-calibrate", action="store_true", help="Run strategy evidence calibration after replay.")
        p.add_argument("--calibration-date", help="End date passed to calibration after replay; defaults to replay --end-date.")
        p.add_argument("--update-latest", action="store_true", help="Allow replay to update *_latest outputs.")
        p.add_argument("--min-dates", type=int, help="Minimum evaluation dates required for calibration.")
        p.add_argument("--min-samples-per-grade", type=int, help="Minimum labeled samples per grade for calibration.")
        p.add_argument("--windows", default="5,10,20", help="Comma-separated forward observation windows in trading days.")
        p.add_argument("--signal-date", help="Signal/reminder date for strategy outcome reports.")
        p.add_argument("--raw-signal", help="Raw strategy signal id for research commands.")
        p.add_argument("--verify-strategy", default="all", help="Strategy id for verify_strategy_environment: all, vcp, bollinger_bandit, ma2560.")
        p.add_argument("--macro-snapshot", help="Optional macro snapshot JSON for verify_strategy_environment quadrant metadata/splitting.")
        p.add_argument("--primary-window", type=int, default=20, help="Primary future-return window for research diagnostics.")
        p.add_argument("--min-samples", type=int, default=20, help="Minimum samples per discovered State combo.")
        p.add_argument("--min-ef-count", type=int, help="Optional minimum ef_count filter for State combo searches.")
        p.add_argument("--max-ef-count", type=int, help="Optional maximum ef_count filter for State combo searches.")
        p.add_argument("--apply-industry-etf-config", action="store_true", help="Apply generated industry ETF config to config/industry_rotation_assets.json.")
        p.add_argument("--include-proxy-industry-etf", action="store_true", help="Include proxy ETF candidates in generated industry ETF config.")

    add_common(sub.add_parser("validate_foundation"))
    add_common(sub.add_parser("verify_public_outputs"))
    add_common(sub.add_parser("download_daily"))
    add_common(sub.add_parser("preflight"))
    add_common(sub.add_parser("build_raw_db"))
    add_common(sub.add_parser("download_moneyflow"))
    add_common(sub.add_parser("import_moneyflow_db"))
    add_common(sub.add_parser("import_moneyflow_db_range"))
    add_common(sub.add_parser("build_moneyflow_evidence"))
    add_common(sub.add_parser("download_market_assets"))
    add_common(sub.add_parser("import_market_assets_db"))
    add_common(sub.add_parser("import_market_assets_db_range"))
    add_common(sub.add_parser("build_market_assets_state"))
    add_common(sub.add_parser("build_ifind_macro"))
    add_common(sub.add_parser("collect_macro_multisource"))
    add_common(sub.add_parser("build_macro_chain_prior"))
    add_common(sub.add_parser("build_industry_etf_coverage"))
    add_common(sub.add_parser("build_industry_etf_config"))
    add_common(sub.add_parser("build_recommendation"))
    add_common(sub.add_parser("build_shareable_table"))
    add_common(sub.add_parser("build_strategy_evidence"))
    add_common(sub.add_parser("evaluate_strategy_evidence"))
    add_common(sub.add_parser("calibrate_strategy_evidence"))
    add_common(sub.add_parser("run_classic_backtest"))
    add_common(sub.add_parser("build_industry_rotation"))
    add_common(sub.add_parser("build_foundation"))
    add_common(sub.add_parser("run_pattern_scan"))
    add_common(sub.add_parser("run_pattern_cross"))
    add_common(sub.add_parser("run_ifind_pool"))
    add_common(sub.add_parser("run_fundamental_plan"))
    add_common(sub.add_parser("run_fundamental_collect"))
    add_common(sub.add_parser("run_ifind_excel_import"))
    add_common(sub.add_parser("run_ifind_chain_import"))
    add_common(sub.add_parser("run_fundamental_score"))
    add_common(sub.add_parser("run_ai_research_loop"))
    add_common(sub.add_parser("run_fundamental_weekly"))
    add_common(sub.add_parser("run_ifind_usage_stress"))
    add_common(sub.add_parser("run_state_usage_stress"))
    add_common(sub.add_parser("build_state_cache"))
    add_common(sub.add_parser("build_strategy_signal_ledger"))
    add_common(sub.add_parser("build_strategy_reminder"))
    add_common(sub.add_parser("forward_sim"))
    add_common(sub.add_parser("run_strategy_fit_observer"))
    add_common(sub.add_parser("process_ifind_data"))
    add_common(sub.add_parser("generate_daily_brief"))
    add_common(sub.add_parser("analyze_ma2560_market_match_forward"))
    add_common(sub.add_parser("audit_ma2560_stock_only_gap"))
    add_common(sub.add_parser("generate_strategy_outcome_report"))
    add_common(sub.add_parser("generate_strategy_outcome_range_report"))
    add_common(sub.add_parser("search_2560_optimal_state"))
    add_common(sub.add_parser("search_bollinger_optimal_state"))
    add_common(sub.add_parser("search_vcp_optimal_state"))
    add_common(sub.add_parser("verify_strategy_environment"))
    add_common(sub.add_parser("replay_history"))
    add_common(sub.add_parser("run_fundamental_analyze"))
    add_common(sub.add_parser("run_stock_ledger"))
    add_common(sub.add_parser("run_event_radar"))
    add_common(sub.add_parser("run_industry_chain"))
    add_common(sub.add_parser("run"))
    args = parser.parse_args()

    if args.command == "validate_foundation":
        result = validate_foundation(args.date, args.foundation_db)
    elif args.command == "verify_public_outputs":
        result = verify_public_outputs(args.date)
    elif args.command == "download_daily":
        result = download_daily(args.date, args.previous_date, args.test_download)
    elif args.command == "preflight":
        result = preflight(args.date, args.previous_date)
    elif args.command == "build_raw_db":
        result = build_raw_db(args.date, args.source_zip, args.test_download)
    elif args.command == "download_moneyflow":
        result = download_moneyflow(args.date, days=args.moneyflow_days, limit=args.moneyflow_limit, workers=args.moneyflow_workers)
    elif args.command == "import_moneyflow_db":
        result = import_moneyflow_db(args.date)
    elif args.command == "import_moneyflow_db_range":
        result = import_moneyflow_db_range(args.date, days=max(1, args.moneyflow_days))
    elif args.command == "build_moneyflow_evidence":
        result = build_moneyflow_evidence(args.date, days=max(5, args.moneyflow_days))
    elif args.command == "download_market_assets":
        result = download_market_assets(args.date, days=max(1, args.moneyflow_days))
    elif args.command == "import_market_assets_db":
        result = import_market_assets_db(args.date)
    elif args.command == "import_market_assets_db_range":
        result = import_market_assets_db_range(args.date, days=max(1, args.moneyflow_days))
    elif args.command == "build_market_assets_state":
        result = build_market_assets_state(args.date)
    elif args.command == "build_ifind_macro":
        result = build_ifind_macro(args.date, args.macro_import_file)
    elif args.command == "collect_macro_multisource":
        result = collect_macro_multisource(args.date)
    elif args.command == "build_macro_chain_prior":
        result = build_macro_chain_prior(args.date)
    elif args.command == "build_industry_etf_coverage":
        result = build_industry_etf_coverage(args.date)
    elif args.command == "build_industry_etf_config":
        result = build_industry_etf_config(args.date, args.apply_industry_etf_config, args.include_proxy_industry_etf)
    elif args.command == "build_recommendation":
        result = build_recommendation(args.date)
    elif args.command == "build_shareable_table":
        result = build_shareable_table(args.date)
    elif args.command == "build_strategy_evidence":
        result = build_strategy_evidence(args.date, args.foundation_db, args.lookback_days)
    elif args.command == "evaluate_strategy_evidence":
        result = evaluate_strategy_evidence(args.date, args.top_n)
    elif args.command == "calibrate_strategy_evidence":
        result = calibrate_strategy_evidence(
            args.date,
            args.start_date,
            args.foundation_db,
            args.min_dates,
            args.min_samples_per_grade,
        )
    elif args.command == "run_classic_backtest":
        result = run_classic_backtest(
            args.date,
            args.foundation_db,
            strategy=args.strategy,
            lookback_days=args.backtest_lookback_days,
            max_positions=args.max_positions,
            min_ef=args.min_ef,
            initial_capital=args.initial_capital,
        )
    elif args.command == "build_industry_rotation":
        result = build_industry_rotation(args.date)
    elif args.command == "build_foundation":
        result = build_foundation(args.date, foundation_db=args.foundation_db)
    elif args.command == "run_pattern_scan":
        result = run_pattern_scan(args.date, args.foundation_db)
    elif args.command == "run_pattern_cross":
        result = run_pattern_cross(args.date)
    elif args.command == "run_ifind_pool":
        result = run_ifind_pool(args.date, args.limit)
    elif args.command == "run_fundamental_plan":
        result = run_fundamental_plan(args.date)
    elif args.command == "run_fundamental_collect":
        result = run_fundamental_collect(args.date, args.universe, args.limit, args.refresh)
    elif args.command == "run_ifind_excel_import":
        result = run_ifind_excel_import(args.date, args.excel_file, args.statement_type)
    elif args.command == "run_ifind_chain_import":
        result = run_ifind_chain_import(args.date, args.excel_file)
    elif args.command == "run_fundamental_score":
        result = run_fundamental_score(args.date)
    elif args.command == "run_ai_research_loop":
        result = run_ai_research_loop(args.date)
    elif args.command == "run_fundamental_weekly":
        result = run_fundamental_weekly(
            args.date,
            limit=args.limit,
            universe=args.universe,
            income_core_excel=args.income_core_excel,
            balance_core_excel=args.balance_core_excel,
            cashflow_core_excel=args.cashflow_core_excel,
            industry_chain_excel=args.industry_chain_excel,
            skip_api_collect=not args.with_api_collect,
            skip_ai_profile=not args.with_ai_profile,
        )
    elif args.command == "run_ifind_usage_stress":
        result = run_ifind_usage_stress(args.date, args.iterations, args.workers, args.code_limit)
    elif args.command == "run_state_usage_stress":
        result = run_state_usage_stress(args.date, args.iterations, args.workers, args.code_limit)
    elif args.command == "build_state_cache":
        result = build_state_cache(args.date, args.foundation_db, args.boundary_pct)
    elif args.command == "build_strategy_signal_ledger":
        result = build_strategy_signal_ledger(args.date, args.foundation_db, args.min_ef)
    elif args.command == "build_strategy_reminder":
        result = build_strategy_reminder(args.date)
    elif args.command == "forward_sim":
        result = forward_sim(args.date, args.foundation_db, args.windows)
    elif args.command == "run_strategy_fit_observer":
        result = run_strategy_fit_observer(args.date)
    elif args.command == "process_ifind_data":
        result = process_ifind_data(args.date)
    elif args.command == "generate_daily_brief":
        result = generate_daily_brief(args.date)
    elif args.command == "analyze_ma2560_market_match_forward":
        result = analyze_ma2560_market_match_forward(args.date, args.foundation_db)
    elif args.command == "audit_ma2560_stock_only_gap":
        result = audit_ma2560_stock_only_gap(args.date)
    elif args.command == "generate_strategy_outcome_report":
        result = generate_strategy_outcome_report(args.signal_date or args.previous_date, args.date, args.foundation_db)
    elif args.command == "generate_strategy_outcome_range_report":
        if not args.start_date:
            raise ValueError("generate_strategy_outcome_range_report requires --start-date")
        result = generate_strategy_outcome_range_report(
            args.start_date,
            args.end_date or args.date,
            args.date,
            args.foundation_db,
        )
    elif args.command == "search_2560_optimal_state":
        result = search_2560_optimal_state(
            args.end_date or args.date,
            args.start_date,
            args.foundation_db,
            args.raw_signal or "ma2560_golden_cross",
            args.min_samples,
            args.primary_window,
            args.min_ef_count,
            args.max_ef_count,
            args.macro_snapshot,
        )
    elif args.command == "search_bollinger_optimal_state":
        result = search_bollinger_optimal_state(
            args.end_date or args.date,
            args.start_date,
            args.foundation_db,
            args.min_samples,
            args.primary_window,
            args.min_ef_count,
            args.max_ef_count,
        )
    elif args.command == "search_vcp_optimal_state":
        result = search_vcp_optimal_state(
            args.end_date or args.date,
            args.start_date,
            args.foundation_db,
            args.raw_signal,
            args.min_samples,
            args.primary_window,
            args.min_ef_count,
            args.max_ef_count,
        )
    elif args.command == "verify_strategy_environment":
        result = verify_strategy_environment(
            args.end_date or args.date,
            args.start_date,
            args.foundation_db,
            args.verify_strategy,
            args.raw_signal,
            args.min_samples,
            args.primary_window,
            args.min_ef_count,
            args.max_ef_count,
        )
    elif args.command == "replay_history":
        if not args.start_date:
            raise ValueError("replay_history requires --start-date")
        result = replay_history(
            args.start_date,
            args.end_date or args.date,
            foundation_db=args.foundation_db,
            steps_arg=args.steps,
            workers=args.workers,
            skip_existing=args.skip_existing,
            force=args.force,
            auto_calibrate=args.auto_calibrate,
            calibration_date=args.calibration_date,
            update_latest=args.update_latest,
            top_n=args.top_n,
        )
    elif args.command == "run_fundamental_analyze":
        result = run_fundamental_analyze(args.date, args.limit or 20)
    elif args.command == "run_stock_ledger":
        result = run_stock_ledger(args.date, args.limit)
    elif args.command == "run_event_radar":
        result = run_event_radar(args.date, getattr(args, "import_json", None))
    elif args.command == "run_industry_chain":
        result = run_industry_chain(args.date, getattr(args, "import_json", None))
    else:
        result = run_full_workflow(
            args.date,
            args.previous_date,
            args.foundation_db,
            download=args.download,
            build_raw=args.build_raw,
            download_moneyflow_flag=args.download_moneyflow,
            moneyflow_days=args.moneyflow_days,
            build_foundation_flag=args.build_foundation,
            test_download=args.test_download,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
