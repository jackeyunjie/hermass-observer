#!/usr/bin/env python3
"""Simulate read-heavy Hermass/P116 state system usage scenarios.

Read-only stress test for:
- full-market D1 perspective state DB
- daily all-three E/F JSON outputs
- pattern cross JSON outputs
- optional market asset state DB
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


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def foundation_db(date_str: str) -> Path:
    return ROOT / "outputs" / f"p116_foundation_{ymd(date_str)}" / "p116_foundation.duckdb"


def market_state_db(date_str: str) -> Path:
    return ROOT / "outputs" / f"market_assets_state_{ymd(date_str)}" / "market_assets_state.duckdb"


def all_three_json(date_str: str) -> Path:
    return ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_{ymd(date_str)}.json"


def diff_json(date_str: str) -> Path:
    return ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_diff_{ymd(date_str)}.json"


def pattern_cross_json(date_str: str) -> Path:
    return ROOT / "outputs" / "pattern_lifecycle" / f"pattern_cross_ef_{ymd(date_str)}.json"


def connect_state(date_str: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(foundation_db(date_str)), read_only=True)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    fn: Callable[[str, str], dict[str, Any]]


def load_codes(date_str: str, limit: int) -> list[str]:
    con = connect_state(date_str)
    rows = con.execute(
        """
        SELECT DISTINCT stock_code
        FROM d1_perspective_state
        WHERE state_date = CAST(? AS DATE)
        ORDER BY stock_code
        """,
        (date_str,),
    ).fetchall()
    con.close()
    codes = [r[0] for r in rows]
    if limit > 0:
        return codes[:limit]
    return codes


def scenario_single_stock_latest(date_str: str, code: str) -> dict[str, Any]:
    con = connect_state(date_str)
    row = con.execute(
        """
        SELECT stock_code, state_date, d1_close,
               mn1_state_hex, w1_state_hex, d1_state_hex, ef_count,
               mn1_state_score, w1_state_score, d1_state_score
        FROM d1_perspective_state
        WHERE stock_code = ? AND state_date <= CAST(? AS DATE)
        ORDER BY state_date DESC
        LIMIT 1
        """,
        (code, date_str),
    ).fetchone()
    con.close()
    return {"found": bool(row), "ef_count": row[6] if row else None}


def scenario_single_stock_history(date_str: str, code: str) -> dict[str, Any]:
    con = connect_state(date_str)
    rows = con.execute(
        """
        SELECT state_date, mn1_state_hex, w1_state_hex, d1_state_hex, ef_count
        FROM d1_perspective_state
        WHERE stock_code = ? AND state_date <= CAST(? AS DATE)
        ORDER BY state_date DESC
        LIMIT 120
        """,
        (code, date_str),
    ).fetchall()
    con.close()
    return {"history_rows": len(rows)}


def scenario_all_three_ef_sql(date_str: str, code: str) -> dict[str, Any]:
    con = connect_state(date_str)
    rows = con.execute(
        """
        SELECT stock_code, mn1_state_hex, w1_state_hex, d1_state_hex,
               mn1_state_score + w1_state_score + d1_state_score AS score_sum
        FROM d1_perspective_state
        WHERE state_date = CAST(? AS DATE)
          AND mn1_state_hex IN ('E', 'F')
          AND w1_state_hex IN ('E', 'F')
          AND d1_state_hex IN ('E', 'F')
        ORDER BY score_sum DESC, stock_code
        LIMIT 300
        """,
        (date_str,),
    ).fetchall()
    con.close()
    return {"sql_rows": len(rows)}


def scenario_state_distribution(date_str: str, code: str) -> dict[str, Any]:
    con = connect_state(date_str)
    rows = con.execute(
        """
        SELECT mn1_state_hex, w1_state_hex, d1_state_hex, COUNT(*) AS n
        FROM d1_perspective_state
        WHERE state_date = CAST(? AS DATE)
        GROUP BY 1, 2, 3
        ORDER BY n DESC
        LIMIT 80
        """,
        (date_str,),
    ).fetchall()
    con.close()
    return {"distribution_rows": len(rows)}


def scenario_sr_boundary_scan(date_str: str, code: str) -> dict[str, Any]:
    con = connect_state(date_str)
    rows = con.execute(
        """
        SELECT stock_code, d1_close, d1_sr_support, d1_sr_resistance,
               CASE
                 WHEN d1_sr_resistance IS NOT NULL AND d1_sr_resistance != 0
                 THEN ABS(d1_close / d1_sr_resistance - 1)
                 ELSE NULL
               END AS dist_to_resistance
        FROM d1_perspective_state
        WHERE state_date = CAST(? AS DATE)
          AND d1_sr_ready = true
          AND d1_sr_resistance IS NOT NULL
          AND d1_sr_resistance > 0
          AND d1_close > 0
        ORDER BY dist_to_resistance ASC NULLS LAST
        LIMIT 100
        """,
        (date_str,),
    ).fetchall()
    con.close()
    return {"boundary_rows": len(rows)}


def scenario_transition_scan(date_str: str, code: str) -> dict[str, Any]:
    con = connect_state(date_str)
    rows = con.execute(
        """
        WITH last2 AS (
          SELECT stock_code, state_date, mn1_state_hex, w1_state_hex, d1_state_hex,
                 lag(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_d1_state
          FROM d1_perspective_state
          WHERE state_date BETWEEN CAST(? AS DATE) - INTERVAL 10 DAY AND CAST(? AS DATE)
        )
        SELECT stock_code, prev_d1_state, d1_state_hex, COUNT(*) AS n
        FROM last2
        WHERE state_date = CAST(? AS DATE)
          AND prev_d1_state IS NOT NULL
          AND prev_d1_state != d1_state_hex
        GROUP BY 1, 2, 3
        ORDER BY stock_code
        LIMIT 200
        """,
        (date_str, date_str, date_str),
    ).fetchall()
    con.close()
    return {"transition_rows": len(rows)}


def scenario_json_all_three(date_str: str, code: str) -> dict[str, Any]:
    payload = load_json(all_three_json(date_str))
    rows = payload.get("rows", [])
    sample = rows[:20]
    return {"json_total": payload.get("total", len(rows)), "sample_rows": len(sample)}


def scenario_json_diff(date_str: str, code: str) -> dict[str, Any]:
    payload = load_json(diff_json(date_str))
    return {
        "entered": payload.get("entered_count", 0),
        "left": payload.get("left_count", 0),
        "stayed": payload.get("stayed_count", 0),
    }


def scenario_pattern_cross(date_str: str, code: str) -> dict[str, Any]:
    payload = load_json(pattern_cross_json(date_str))
    return {
        "ef_with_structure": len(payload.get("ef_with_structure", [])),
        "vcp_entered_ef": len(payload.get("vcp_entered_ef", [])),
        "golden_cross_ef": len(payload.get("golden_cross_ef", [])),
    }


def scenario_market_regime(date_str: str, code: str) -> dict[str, Any]:
    path = market_state_db(date_str)
    if not path.exists():
        return {"market_db_found": False}
    con = duckdb.connect(str(path), read_only=True)
    rows = con.execute(
        """
        SELECT symbol, name, asset_type, benchmark_group,
               mn1_state_hex, w1_state_hex, d1_state_hex
        FROM latest_market_asset_state
        ORDER BY asset_type, symbol
        """,
    ).fetchall()
    con.close()
    return {"market_db_found": True, "market_assets": len(rows)}


SCENARIOS = [
    Scenario("single_stock_latest", "单股最新 MN1/W1/D1 state 快照", scenario_single_stock_latest),
    Scenario("single_stock_history", "单股最近 120 日 state 轨迹", scenario_single_stock_history),
    Scenario("all_three_ef_sql", "从 foundation DB 直接筛三周期 E/F", scenario_all_three_ef_sql),
    Scenario("state_distribution", "全市场状态组合分布", scenario_state_distribution),
    Scenario("sr_boundary_scan", "SR 边界附近品种扫描", scenario_sr_boundary_scan),
    Scenario("transition_scan", "D1 state 最近变化扫描", scenario_transition_scan),
    Scenario("json_all_three", "读取每日 all-three E/F JSON 输出", scenario_json_all_three),
    Scenario("json_diff", "读取每日进入/离开/留存 diff JSON", scenario_json_diff),
    Scenario("pattern_cross", "读取 State × VCP/2560 形态交叉结果", scenario_pattern_cross),
    Scenario("market_regime", "读取指数/ETF 市场状态", scenario_market_regime),
]


def run_one(date_str: str, codes: list[str], seed: int) -> dict[str, Any]:
    random.seed(seed)
    scenario = random.choice(SCENARIOS)
    code = random.choice(codes)
    started = time.perf_counter()
    details = scenario.fn(date_str, code)
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
        f"# State Usage Stress Test - {payload['date']}",
        "",
        "## Usage Scenarios",
    ]
    for item in payload["scenarios"]:
        lines.append(f"- `{item['name']}`: {item['description']}")
    lines.extend(
        [
            "",
            "## Summary",
            f"- Foundation DB: `{payload['foundation_db']}`",
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
    lines.extend(["", "## Verdict", payload["verdict"], ""])
    return "\n".join(lines)


def run_stress(date_str: str, iterations: int, workers: int, code_limit: int) -> dict[str, Any]:
    db_path = foundation_db(date_str)
    if not db_path.exists():
        raise FileNotFoundError(f"foundation DB not found: {db_path}")
    codes = load_codes(date_str, code_limit)
    if not codes:
        raise RuntimeError(f"no state rows found for date {date_str}")

    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_one, date_str, codes, i + 4099) for i in range(iterations)]
        for fut in as_completed(futures):
            results.append(fut.result())
    wall_time = time.perf_counter() - started
    summary = summarize(results)

    p95 = summary["overall"]["p95_ms"]
    max_ms = summary["overall"]["max_ms"]
    if p95 < 500 and max_ms < 3000:
        verdict = "PASS: state system read scenarios are responsive for interactive research and Agent use."
    elif p95 < 2000:
        verdict = "PASS_WITH_NOTES: usable, but add materialized latest-state tables for frontend/API load."
    else:
        verdict = (
            "ATTENTION: state query p95 is high; introduce precomputed views or indexes/materialized outputs."
        )

    payload = {
        "schema_version": "state_usage_stress_test_v1",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "foundation_db": str(db_path),
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
    out_dir = ROOT / "outputs" / "state_stress"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"state_usage_stress_{ymd(date_str)}.json"
    out_md = out_dir / f"state_usage_stress_{ymd(date_str)}.md"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(render_markdown(payload), encoding="utf-8")
    return {**payload, "json": str(out_json), "markdown": str(out_md)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress test read-heavy Hermass/P116 state usage scenarios.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--code-limit", type=int, default=0)
    args = parser.parse_args()

    result = run_stress(args.date, max(1, args.iterations), max(1, args.workers), args.code_limit)
    print(
        json.dumps(
            {
                "schema_version": result["schema_version"],
                "date": result["date"],
                "iterations": result["iterations"],
                "workers": result["workers"],
                "wall_time_sec": result["wall_time_sec"],
                "overall": result["summary"]["overall"],
                "verdict": result["verdict"],
                "json": result["json"],
                "markdown": result["markdown"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
