#!/usr/bin/env python3
"""Build US stock daily State Scan Brief.

Reads from us_state_cache.duckdb and us_foundation.duckdb to generate
a daily brief of stocks in E/F state environments, categorized by quality.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
US_CACHE_DB = ROOT / "outputs" / "us_stock" / "us_state_cache.duckdb"
US_FOUNDATION_DB = ROOT / "outputs" / "us_stock" / "us_foundation.duckdb"
OUT_DIR = ROOT / "outputs" / "us_stock" / "daily_brief"
PUBLIC_DIR = ROOT / "public"


def fetch_dicts(con: duckdb.DuckDBPyConnection, sql: str, params: tuple = ()) -> list[dict]:
    cur = con.execute(sql, params)
    cols = [item[0] for item in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_latest_date(cache_db: Path) -> date:
    con = duckdb.connect(str(cache_db), read_only=True)
    try:
        return con.execute("SELECT MAX(obs_date) FROM state_ef_daily").fetchone()[0]
    finally:
        con.close()


def load_stock_metadata(foundation_db: Path) -> dict[str, dict]:
    """Load latest state data as metadata (close, hex, ADX, etc.) for all stocks."""
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        latest = con.execute("SELECT MAX(state_date) FROM d1_perspective_state").fetchone()[0]
        rows = fetch_dicts(
            con,
            """
            SELECT
                stock_code,
                state_date,
                d1_close,
                mn1_state_hex, w1_state_hex, d1_state_hex,
                mn1_adx14, w1_adx14, d1_adx14,
                mn1_trend, w1_trend, d1_trend,
                ef_count
            FROM d1_perspective_state
            WHERE state_date = ?
            """,
            (latest,),
        )
        return {r["stock_code"]: r for r in rows}
    finally:
        con.close()


def _ef_count_from_hex(mn1: str, w1: str, d1: str) -> int:
    return sum(1 for s in (mn1, w1, d1) if s in ("E", "F"))


def build_brief(cache_db: Path, foundation_db: Path, target_date: date | None = None) -> dict[str, Any]:
    """Build the daily brief for the given date (or latest)."""
    cache_con = duckdb.connect(str(cache_db), read_only=True)
    try:
        if target_date is None:
            target_date = get_latest_date(cache_db)
        date_str = str(target_date)

        # 1. Load ALL stocks' state from foundation (not just state_ef_daily)
        foundation_con = duckdb.connect(str(foundation_db), read_only=True)
        try:
            all_states = fetch_dicts(
                foundation_con,
                """
                SELECT
                    stock_code, state_date, d1_close,
                    mn1_state_hex, w1_state_hex, d1_state_hex,
                    mn1_state_score, w1_state_score, d1_state_score,
                    mn1_adx14, w1_adx14, d1_adx14,
                    mn1_trend, w1_trend, d1_trend,
                    d1_sr_support, d1_sr_resistance,
                    w1_sr_support, w1_sr_resistance
                FROM d1_perspective_state
                WHERE state_date = ?
                """,
                (date_str,),
            )
        finally:
            foundation_con.close()

        # 2. Load duration data from cache
        duration_rows = fetch_dicts(
            cache_con,
            "SELECT * FROM state_duration_daily WHERE obs_date = ?",
            (date_str,),
        )
        duration_map = {r["stock_code"]: r for r in duration_rows}

        # 3. Load SR boundary data (closest boundary per stock)
        sr_rows = fetch_dicts(
            cache_con,
            """
            SELECT
                stock_code,
                boundary_period,
                boundary_type,
                distance_pct,
                boundary_price,
                boundary_direction,
                close_vs_boundary
            FROM sr_boundary_daily
            WHERE obs_date = ?
            QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY ABS(distance_pct)) = 1
            """,
            (date_str,),
        )
        sr_map = {r["stock_code"]: r for r in sr_rows}

        # Combine and categorize
        entries: list[dict] = []
        for st in all_states:
            ticker = st["stock_code"]
            dur = duration_map.get(ticker, {})
            sr = sr_map.get(ticker, {})

            mn1_hex = st.get("mn1_state_hex", "-")
            w1_hex = st.get("w1_state_hex", "-")
            d1_hex = st.get("d1_state_hex", "-")
            ef_count = _ef_count_from_hex(mn1_hex, w1_hex, d1_hex)
            score_sum = (st.get("mn1_state_score") or 0) + (st.get("w1_state_score") or 0) + (st.get("d1_state_score") or 0)

            d1_days_since_exit = dur.get("d1_days_since_contraction_exit")
            if d1_days_since_exit is None:
                d1_days_since_exit = 999
            all_three_ef_dur = dur.get("all_three_ef_duration") or 0

            # Categorize
            if ef_count == 3 and d1_days_since_exit <= 5:
                grade = "A"
                grade_label = "🎯 三周期E/F刚释放"
            elif ef_count >= 2:
                grade = "B"
                grade_label = "🔥 双周期E/F"
            elif ef_count == 1:
                grade = "C"
                grade_label = "⚡ 单周期E/F"
            else:
                grade = "D"
                grade_label = "📊 无E/F"

            entry = {
                "ticker": ticker,
                "close": round(st.get("d1_close", 0), 2),
                "grade": grade,
                "grade_label": grade_label,
                "mn1": mn1_hex,
                "w1": w1_hex,
                "d1": d1_hex,
                "ef_count": ef_count,
                "score_sum": score_sum,
                "d1_adx14": round(st.get("d1_adx14", 0) or 0, 1),
                "d1_trend": st.get("d1_trend", "-"),
                "all_three_ef_duration": all_three_ef_dur,
                "d1_days_since_contraction_exit": d1_days_since_exit if d1_days_since_exit < 999 else None,
                "sr_direction": sr.get("boundary_direction", "-"),
                "sr_distance_pct": round(sr.get("distance_pct", 0) * 100, 2) if sr else None,
                "sr_boundary_price": round(sr.get("boundary_price", 0), 2) if sr else None,
            }
            entries.append(entry)

        # Sort: A first, then by score_sum desc
        entries.sort(key=lambda e: (
            0 if e["grade"] == "A" else 1 if e["grade"] == "B" else 2 if e["grade"] == "C" else 3,
            -(e["score_sum"] or 0),
            e["ticker"],
        ))

        # Stats
        stats = {
            "total": len(entries),
            "grade_A": sum(1 for e in entries if e["grade"] == "A"),
            "grade_B": sum(1 for e in entries if e["grade"] == "B"),
            "grade_C": sum(1 for e in entries if e["grade"] == "C"),
            "grade_D": sum(1 for e in entries if e["grade"] == "D"),
        }

        return {
            "date": date_str,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stats": stats,
            "entries": entries,
        }
    finally:
        cache_con.close()


def generate_html(brief: dict) -> str:
    """Generate a responsive HTML brief."""
    date_str = brief["date"]
    stats = brief["stats"]
    entries = brief["entries"]

    grade_colors = {
        "A": "#ff6b6b",  # red
        "B": "#f9ca24",  # yellow
        "C": "#6c5ce7",  # purple
        "D": "#74b9ff",  # blue
    }

    rows_html = ""
    for e in entries:
        color = grade_colors.get(e["grade"], "#888")
        sr_info = ""
        if e.get("sr_direction") and e.get("sr_direction") != "-":
            sr_info = f"{e['sr_direction']} ({e.get('sr_distance_pct', 0)}%)"

        adx = e.get("d1_adx14")
        adx_str = f"{adx:.1f}" if adx is not None else "-"

        dur = ""
        if e.get("all_three_ef_duration"):
            dur = f"3EF持续{e['all_three_ef_duration']}天"
        elif e.get("d1_days_since_contraction_exit") is not None:
            dur = f"距收缩退出{e['d1_days_since_contraction_exit']}天"

        rows_html += f"""
        <tr class="grade-{e['grade']}">
            <td><span class="badge" style="background:{color}">{e['grade']}</span></td>
            <td><strong>{e['ticker']}</strong></td>
            <td>${e['close']}</td>
            <td>{e['mn1']}</td>
            <td>{e['w1']}</td>
            <td>{e['d1']}</td>
            <td>{e['ef_count']}</td>
            <td>{e['score_sum']}</td>
            <td>{adx_str}</td>
            <td>{e.get('d1_trend', '-')}</td>
            <td>{sr_info}</td>
            <td class="notes">{dur}</td>
        </tr>
        """

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>美股 State Scan - {date_str}</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#0f0f23; color:#e0e0e0; margin:0; padding:20px; }}
    h1 {{ color:#fff; margin-bottom:5px; }}
    .subtitle {{ color:#888; font-size:14px; margin-bottom:20px; }}
    .stats {{ display:flex; gap:15px; margin-bottom:20px; flex-wrap:wrap; }}
    .stat-card {{ background:#1a1a2e; border-radius:8px; padding:15px 20px; min-width:100px; text-align:center; }}
    .stat-card .num {{ font-size:24px; font-weight:bold; color:#fff; }}
    .stat-card .label {{ font-size:12px; color:#888; margin-top:5px; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th {{ background:#1a1a2e; color:#888; padding:10px; text-align:left; font-weight:500; position:sticky; top:0; }}
    td {{ padding:10px; border-bottom:1px solid #222; }}
    tr:hover {{ background:#1a1a2e; }}
    .badge {{ display:inline-block; padding:3px 8px; border-radius:4px; font-size:11px; font-weight:bold; color:#fff; }}
    .grade-A {{ border-left:3px solid #ff6b6b; }}
    .grade-B {{ border-left:3px solid #f9ca24; }}
    .grade-C {{ border-left:3px solid #6c5ce7; }}
    .grade-D {{ border-left:3px solid #74b9ff; }}
    .notes {{ color:#888; font-size:12px; }}
    .guardrail {{ background:#1a1a2e; border-left:3px solid #e74c3c; padding:15px; margin:20px 0; border-radius:4px; font-size:13px; color:#ccc; }}
</style>
</head>
<body>
<h1>📊 美股 State Scan 日报</h1>
<div class="subtitle">{date_str} | 共 {stats['total']} 只 | 生成于 {brief['generated_at'][:19]}</div>

<div class="stats">
    <div class="stat-card"><div class="num" style="color:#ff6b6b">{stats['grade_A']}</div><div class="label">🎯 A级 刚释放</div></div>
    <div class="stat-card"><div class="num" style="color:#f9ca24">{stats['grade_B']}</div><div class="label">🔥 B级 双周期</div></div>
    <div class="stat-card"><div class="num" style="color:#6c5ce7">{stats['grade_C']}</div><div class="label">⚡ C级 单周期</div></div>
    <div class="stat-card"><div class="num" style="color:#74b9ff">{stats['grade_D']}</div><div class="label">📊 D级 无E/F</div></div>
</div>

<div class="guardrail">
    <strong>⚠️ 研究用途声明</strong><br>
    本报告仅为 State 环境扫描，不构成买入/卖出建议。State 信号 ≠ 交易信号，具体入场需结合价格行为、成交量确认和风险管理。
</div>

<table>
<thead>
<tr>
    <th>等级</th>
    <th>代码</th>
    <th>收盘价</th>
    <th>MN1</th>
    <th>W1</th>
    <th>D1</th>
    <th>EF</th>
    <th>分数</th>
    <th>D1 ADX</th>
    <th>D1 趋势</th>
    <th>SR位置</th>
    <th>备注</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>

</body>
</html>
"""


def generate_markdown(brief: dict) -> str:
    """Generate a Markdown brief."""
    date_str = brief["date"]
    stats = brief["stats"]
    entries = brief["entries"]

    md = f"""# 📊 美股 State Scan 日报 — {date_str}

> 生成时间: {brief['generated_at'][:19]}  
> 股票池: 534 只 (S&P 500 + Nasdaq-100)  
> 总扫描: {stats['total']} 只进入 E/F 环境

## 统计概览

| 等级 | 数量 | 说明 |
|---|---|---|
| 🎯 A级 | {stats['grade_A']} | 三周期 E/F 刚释放 |
| 🔥 B级 | {stats['grade_B']} | 双周期 E/F |
| ⚡ C级 | {stats['grade_C']} | 单周期 E/F |
| 📊 D级 | {stats['grade_D']} | 无 E/F |

> ⚠️ **研究用途声明**: 本报告仅为 State 环境扫描，不构成买入/卖出建议。

## 详细列表

| 等级 | 代码 | 收盘价 | MN1 | W1 | D1 | EF | 分数 | D1 ADX | D1 趋势 | SR位置 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|
"""
    for e in entries:
        sr = ""
        if e.get("sr_direction") and e.get("sr_direction") != "-":
            sr = f"{e['sr_direction']} ({e.get('sr_distance_pct', 0)}%)"
        adx = e.get("d1_adx14")
        adx_str = f"{adx:.1f}" if adx is not None else "-"
        dur = ""
        if e.get("all_three_ef_duration"):
            dur = f"3EF持续{e['all_three_ef_duration']}天"
        elif e.get("d1_days_since_contraction_exit") is not None:
            dur = f"距收缩退出{e['d1_days_since_contraction_exit']}天"
        md += f"| {e['grade']} | {e['ticker']} | ${e['close']} | {e['mn1']} | {e['w1']} | {e['d1']} | {e['ef_count']} | {e['score_sum']} | {adx_str} | {e.get('d1_trend', '-')} | {sr} | {dur} |\n"

    return md


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="Target date (YYYY-MM-DD), default=latest")
    parser.add_argument("--cache-db", type=Path, default=US_CACHE_DB)
    parser.add_argument("--foundation-db", type=Path, default=US_FOUNDATION_DB)
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date) if args.date else None

    print("Building US daily State Scan brief...")
    brief = build_brief(args.cache_db, args.foundation_db, target_date)
    date_str = brief["date"].replace("-", "")

    # Save JSON
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / f"us_state_scan_{date_str}.json"
    json_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    json_latest = OUT_DIR / "us_state_scan_latest.json"
    json_latest.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  JSON: {json_path}")

    # Save HTML
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    html = generate_html(brief)
    html_path = PUBLIC_DIR / f"us_state_scan_{date_str}.html"
    html_path.write_text(html, encoding="utf-8")
    html_latest = PUBLIC_DIR / "us_state_scan_latest.html"
    html_latest.write_text(html, encoding="utf-8")
    print(f"  HTML: {html_path}")

    # Save Markdown
    md = generate_markdown(brief)
    md_path = OUT_DIR / f"us_state_scan_{date_str}.md"
    md_path.write_text(md, encoding="utf-8")
    md_latest = OUT_DIR / "us_state_scan_latest.md"
    md_latest.write_text(md, encoding="utf-8")
    print(f"  MD:   {md_path}")

    print(f"\n✅ US State Scan Brief complete: {brief['date']}")
    print(f"   Total: {brief['stats']['total']} | A: {brief['stats']['grade_A']} | B: {brief['stats']['grade_B']} | C: {brief['stats']['grade_C']} | D: {brief['stats']['grade_D']}")


if __name__ == "__main__":
    main()
