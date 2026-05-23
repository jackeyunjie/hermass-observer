#!/usr/bin/env python3
"""Simulate read-heavy iFinD fundamental DB usage scenarios.

This script is intentionally read-only. It validates that the local iFinD
fundamental database can support common research workflows repeatedly and
concurrently without touching source facts.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import duckdb

ROOT = Path(__file__).resolve().parents[1]
FUND_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
P116_ROOT = ROOT / "outputs"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    fn: Callable[[duckdb.DuckDBPyConnection, str, str], dict[str, Any]]


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(FUND_DB), read_only=True)


def load_codes(date_str: str, limit: int) -> list[str]:
    con = connect()
    rows = con.execute(
        """
        SELECT stock_code
        FROM ifind_industry_chain_profile
        WHERE as_of_date = ?
        ORDER BY stock_code
        """,
        (date_str,),
    ).fetchall()
    con.close()
    codes = [r[0] for r in rows]
    if limit > 0:
        return codes[:limit]
    return codes


def scenario_single_stock_snapshot(con: duckdb.DuckDBPyConnection, date_str: str, code: str) -> dict[str, Any]:
    profile = con.execute(
        """
        SELECT p.stock_code, p.stock_name, p.sw_l1, p.sw_l2, p.sw_l3, p.main_business,
               q.quality_score, q.core_business_purity, q.cash_quality, q.earnings_quality
        FROM ifind_industry_chain_profile p
        LEFT JOIN fundamental_quality_score q
          ON p.stock_code = q.stock_code AND q.as_of_date = ?
        WHERE p.stock_code = ? AND p.as_of_date = ?
        """,
        (date_str, code, date_str),
    ).fetchone()
    facts = con.execute(
        """
        SELECT metric_name, metric_value, report_period
        FROM ifind_excel_facts
        WHERE stock_code = ? AND as_of_date = ?
        ORDER BY statement_type, metric_name
        LIMIT 30
        """,
        (code, date_str),
    ).fetchall()
    return {"profile_found": bool(profile), "fact_rows": len(facts)}


def scenario_evidence_packet(con: duckdb.DuckDBPyConnection, date_str: str, code: str) -> dict[str, Any]:
    rows = con.execute(
        """
        SELECT evidence_type, COUNT(*) AS n, AVG(confidence) AS avg_confidence
        FROM fundamental_evidence_packet
        WHERE stock_code = ? AND as_of_date = ? AND COALESCE(unavailable, false) = false
        GROUP BY evidence_type
        ORDER BY evidence_type
        """,
        (code, date_str),
    ).fetchall()
    return {"evidence_groups": len(rows), "evidence_rows": sum(r[1] for r in rows)}


def scenario_quality_screen(con: duckdb.DuckDBPyConnection, date_str: str, code: str) -> dict[str, Any]:
    rows = con.execute(
        """
        SELECT q.stock_code, q.stock_name, p.sw_l1, p.sw_l2, q.quality_score,
               q.core_business_purity, q.cash_quality, q.earnings_quality
        FROM fundamental_quality_score q
        JOIN ifind_industry_chain_profile p
          ON q.stock_code = p.stock_code AND q.as_of_date = p.as_of_date
        WHERE q.as_of_date = ?
          AND q.quality_score >= 80
          AND q.core_business_purity BETWEEN 0.7 AND 3.0
          AND q.cash_quality BETWEEN 0.5 AND 3.0
          AND q.earnings_quality BETWEEN 0.5 AND 3.0
        ORDER BY q.quality_score DESC, q.stock_code
        LIMIT 100
        """,
        (date_str,),
    ).fetchall()
    return {"screen_rows": len(rows)}


def scenario_concept_scan(con: duckdb.DuckDBPyConnection, date_str: str, code: str) -> dict[str, Any]:
    keyword = random.choice(["算力", "机器人", "低空经济", "光伏", "芯片", "国企改革"])
    rows = con.execute(
        """
        SELECT p.stock_code, p.stock_name, p.sw_l1, q.quality_score
        FROM ifind_industry_chain_profile p
        LEFT JOIN fundamental_quality_score q
          ON p.stock_code = q.stock_code AND q.as_of_date = ?
        WHERE p.as_of_date = ? AND p.ths_concepts LIKE ?
        ORDER BY q.quality_score DESC NULLS LAST
        LIMIT 80
        """,
        (date_str, date_str, f"%{keyword}%"),
    ).fetchall()
    return {"keyword": keyword, "concept_rows": len(rows)}


def scenario_industry_rollup(con: duckdb.DuckDBPyConnection, date_str: str, code: str) -> dict[str, Any]:
    rows = con.execute(
        """
        SELECT p.sw_l1, COUNT(*) AS n, AVG(q.quality_score) AS avg_quality,
               AVG(q.core_business_purity) AS avg_purity,
               AVG(q.cash_quality) AS avg_cash
        FROM ifind_industry_chain_profile p
        LEFT JOIN fundamental_quality_score q
          ON p.stock_code = q.stock_code AND p.as_of_date = q.as_of_date
        WHERE p.as_of_date = ?
        GROUP BY p.sw_l1
        HAVING COUNT(*) >= 20
        ORDER BY avg_quality DESC NULLS LAST
        LIMIT 40
        """,
        (date_str,),
    ).fetchall()
    return {"industry_rows": len(rows)}


def scenario_ai_prompt_pack(con: duckdb.DuckDBPyConnection, date_str: str, code: str) -> dict[str, Any]:
    rows = con.execute(
        """
        SELECT p.stock_code, p.stock_name, p.sw_l1, p.sw_l2, p.sw_l3,
               q.quality_score, q.core_business_purity, p.main_business
        FROM ifind_industry_chain_profile p
        LEFT JOIN fundamental_quality_score q
          ON p.stock_code = q.stock_code AND q.as_of_date = ?
        JOIN ifind_tracking_pool t
          ON p.stock_code = t.stock_code AND t.active = true
        WHERE p.as_of_date = ?
        ORDER BY COALESCE(q.quality_score, -1) DESC, p.stock_code
        LIMIT 20
        """,
        (date_str, date_str),
    ).fetchall()
    approx_chars = sum(len("|".join("" if x is None else str(x) for x in row)) for row in rows)
    return {"prompt_rows": len(rows), "approx_chars": approx_chars}


def scenario_ledger_lookup(con: duckdb.DuckDBPyConnection, date_str: str, code: str) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT stock_code, stock_name, confidence, chief_insight, evidence_ids_json
        FROM stock_research_ledger
        WHERE stock_code = ? AND as_of_date = ?
        """,
        (code, date_str),
    ).fetchone()
    if not row:
        return {"ledger_found": False, "evidence_count": 0}
    try:
        evidence_count = len(json.loads(row[4] or "[]"))
    except json.JSONDecodeError:
        evidence_count = 0
    return {"ledger_found": True, "evidence_count": evidence_count}


SCENARIOS = [
    Scenario("single_stock_snapshot", "单股基本面账本：产业身份 + L2 质量分 + 财报事实", scenario_single_stock_snapshot),
    Scenario("evidence_packet", "证据包取证：为 LLM/台账读取已约束证据", scenario_evidence_packet),
    Scenario("quality_screen", "高质量池筛选：基本面强、异常比率已过滤", scenario_quality_screen),
    Scenario("concept_scan", "概念主题检索：同花顺概念 + 基本面质量排序", scenario_concept_scan),
    Scenario("industry_rollup", "行业横向聚合：行业质量分和现金质量横截面", scenario_industry_rollup),
    Scenario("ai_prompt_pack", "AI Research Loop 拼包：从 SQL 结果构造 L3 输入", scenario_ai_prompt_pack),
    Scenario("ledger_lookup", "个股首席式台账查询：HTML/API 前端读取", scenario_ledger_lookup),
]


def run_one(date_str: str, codes: list[str], seed: int) -> dict[str, Any]:
    random.seed(seed)
    scenario = random.choice(SCENARIOS)
    code = random.choice(codes)
    started = time.perf_counter()
    con = connect()
    try:
        details = scenario.fn(con, date_str, code)
    finally:
        con.close()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "scenario": scenario.name,
        "description": scenario.description,
        "stock_code": code,
        "elapsed_ms": elapsed_ms,
        "details": details,
    }


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_name: dict[str, list[float]] = {}
    for row in results:
        by_name.setdefault(row["scenario"], []).append(float(row["elapsed_ms"]))
    scenario_stats = {}
    for name, values in sorted(by_name.items()):
        scenario_stats[name] = {
            "count": len(values),
            "min_ms": min(values),
            "avg_ms": statistics.fmean(values),
            "p50_ms": percentile(values, 50),
            "p95_ms": percentile(values, 95),
            "max_ms": max(values),
        }
    all_values = [float(r["elapsed_ms"]) for r in results]
    return {
        "total_queries": len(results),
        "overall": {
            "min_ms": min(all_values) if all_values else 0.0,
            "avg_ms": statistics.fmean(all_values) if all_values else 0.0,
            "p50_ms": percentile(all_values, 50),
            "p95_ms": percentile(all_values, 95),
            "max_ms": max(all_values) if all_values else 0.0,
        },
        "scenario_stats": scenario_stats,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# iFinD Usage Stress Test - {payload['date']}",
        "",
        "## Usage Scenarios",
    ]
    for item in payload["scenarios"]:
        lines.append(f"- `{item['name']}`: {item['description']}")
    lines.extend(
        [
            "",
            "## Summary",
            f"- DB: `{payload['database']}`",
            f"- Codes sampled: `{payload['codes_sampled']}`",
            f"- Workers: `{payload['workers']}`",
            f"- Iterations: `{payload['iterations']}`",
            f"- Total wall time: `{payload['wall_time_sec']:.3f}s`",
            f"- Overall avg: `{payload['summary']['overall']['avg_ms']:.2f} ms/query`",
            f"- Overall p95: `{payload['summary']['overall']['p95_ms']:.2f} ms/query`",
            "",
            "## Scenario Latency",
            "| Scenario | Count | Avg ms | P95 ms | Max ms |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for name, stats in payload["summary"]["scenario_stats"].items():
        lines.append(
            f"| `{name}` | {stats['count']} | {stats['avg_ms']:.2f} | "
            f"{stats['p95_ms']:.2f} | {stats['max_ms']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Verdict",
            payload["verdict"],
            "",
        ]
    )
    return "\n".join(lines)


def run_stress(date_str: str, iterations: int, workers: int, code_limit: int) -> dict[str, Any]:
    if not FUND_DB.exists():
        raise FileNotFoundError(f"fundamental DB not found: {FUND_DB}")
    codes = load_codes(date_str, code_limit)
    if not codes:
        raise RuntimeError(f"no stock codes found for date {date_str}")

    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(run_one, date_str, codes, i + 1009)
            for i in range(iterations)
        ]
        for fut in as_completed(futures):
            results.append(fut.result())
    wall_time = time.perf_counter() - started
    summary = summarize(results)

    p95 = summary["overall"]["p95_ms"]
    max_ms = summary["overall"]["max_ms"]
    if p95 < 250 and max_ms < 2000:
        verdict = "PASS: read-heavy iFinD scenarios are responsive for interactive research use."
    elif p95 < 1000:
        verdict = "PASS_WITH_NOTES: usable, but add materialized query tables if frontend traffic increases."
    else:
        verdict = "ATTENTION: p95 latency is high; introduce precomputed views or narrower lookup tables."

    payload = {
        "schema_version": "ifind_usage_stress_test_v1",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(FUND_DB),
        "codes_sampled": len(codes),
        "iterations": iterations,
        "workers": workers,
        "wall_time_sec": wall_time,
        "scenarios": [{"name": s.name, "description": s.description} for s in SCENARIOS],
        "summary": summary,
        "sample_results": sorted(results, key=lambda x: x["elapsed_ms"], reverse=True)[:20],
        "verdict": verdict,
        "research_only": True,
    }

    out_dir = ROOT / "outputs" / "fundamental"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"ifind_usage_stress_{ymd(date_str)}.json"
    out_md = out_dir / f"ifind_usage_stress_{ymd(date_str)}.md"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(render_markdown(payload), encoding="utf-8")
    return {**payload, "json": str(out_json), "markdown": str(out_md)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress test read-heavy iFinD usage scenarios.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--code-limit", type=int, default=0)
    args = parser.parse_args()

    result = run_stress(args.date, max(1, args.iterations), max(1, args.workers), args.code_limit)
    print(json.dumps({
        "schema_version": result["schema_version"],
        "date": result["date"],
        "iterations": result["iterations"],
        "workers": result["workers"],
        "wall_time_sec": result["wall_time_sec"],
        "overall": result["summary"]["overall"],
        "verdict": result["verdict"],
        "json": result["json"],
        "markdown": result["markdown"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
