#!/usr/bin/env python3
"""Build per-stock research ledgers from local Hermass + iFinD evidence.

This does not download data. It composes a durable "chief analyst style" ledger
from local DuckDB/JSON evidence so each pool member can be tracked persistently.
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
FUND_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def init_schema() -> None:
    spec = importlib.util.spec_from_file_location(
        "fundamental_evidence_schema",
        str(ROOT / "scripts" / "fundamental_evidence_schema.py"),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load fundamental_evidence_schema.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.init_schema(FUND_DB)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_technical(date_str: str) -> dict[str, dict[str, Any]]:
    path = ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_{ymd(date_str)}.json"
    payload = load_json(path)
    rows = {}
    for row in payload.get("rows", []):
        code = row.get("symbol") or row.get("stock_code")
        if code:
            rows[code] = row
    return rows


def load_pattern(date_str: str) -> dict[str, dict[str, Any]]:
    path = ROOT / "outputs" / "pattern_lifecycle" / f"pattern_cross_ef_{ymd(date_str)}.json"
    payload = load_json(path)
    rows = {}
    for row in payload.get("ef_with_structure", []):
        code = row.get("stock_code")
        if code:
            rows[code] = row
    return rows


def safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def extract_fact_summary(evidence: list[dict[str, Any]]) -> str:
    preferred = [ev for ev in evidence if ev.get("evidence_type") == "ifind_industry_chain_profile"]
    preferred += [ev for ev in evidence if ev.get("evidence_type") == "ifind_excel_l2_derived"]
    preferred += [ev for ev in evidence if ev.get("evidence_type") == "ifind_excel_aggregate"]
    lines: list[str] = []
    for ev in preferred:
        for line in str(ev.get("evidence_text") or "").splitlines():
            line = line.strip()
            if line.startswith("- "):
                lines.append(line[2:])
    seen = set()
    out = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return "；".join(out[:6])


def build_insight(code: str, tech: dict[str, Any], pattern: dict[str, Any], profile: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    states = "/".join(str(tech.get(k, "")) for k in ("mn1_state", "w1_state", "d1_state")).strip("/")
    structure = pattern.get("structure_type") or "none"
    company_position = profile.get("company_position") or "unknown"
    development_cycle = profile.get("development_cycle") or "unknown"
    placement = profile.get("placement_assessment") or "unknown"
    evidence_quality = len([ev for ev in evidence if not ev.get("unavailable")])
    facts = extract_fact_summary(evidence)

    industry = profile.get("industry_profile") or {}
    industry_line = ""
    if industry:
        industry_line = (
            f"产业身份={industry.get('sw_l1') or 'unknown'}/"
            f"{industry.get('sw_l2') or 'unknown'}/"
            f"{industry.get('sw_l3') or 'unknown'}，"
            f"主营={industry.get('main_business') or 'unknown'}。"
        )

    chief = (
        f"{code} 当前技术状态={states or 'unknown'}，结构标签={structure}；"
        f"{industry_line}"
        f"iFinD 基本面画像显示公司地位={company_position}、发展阶段={development_cycle}、资本事件={placement}。"
        f"iFinD 确定事实：{facts or '待补充'}。"
        f"当前账本证据数={evidence_quality}，结论仅作 research-only 跟踪。"
    )
    bull = "技术形态与 P116 状态若继续共振，同时 iFinD 后续证据确认盈利质量或产业地位改善，可提高观察优先级。"
    bear = "若后续证据仍大量 unknown、财务指标缺失，或 P116/形态生命周期降级，应降低账本优先级。"
    watch = [
        "P116 MN1/W1/D1 是否继续保持 E/F 或 constructive 状态",
        "VCP/2560 生命周期是否由形成转向确认或降级",
        "iFinD 财务字段是否补齐 ROE、毛利率、营收/净利增速",
        "公告侧是否出现定增、并购、业绩预告等事件证据",
    ]
    confidence = 0.25
    if states:
        confidence += 0.2
    if structure != "none":
        confidence += 0.15
    if company_position != "unknown" or development_cycle != "unknown":
        confidence += 0.2
    if industry:
        confidence += 0.1
    if evidence_quality >= 3:
        confidence += 0.1
    return {
        "chief_insight": chief,
        "bull_case": bull,
        "bear_case": bear,
        "watch_points": watch,
        "confidence": min(confidence, 0.95),
        "fact_summary": facts,
    }


def build_ledgers(date_str: str, limit: int = 0) -> dict[str, Any]:
    init_schema()
    tech_by_code = load_technical(date_str)
    pattern_by_code = load_pattern(date_str)
    generated_at = datetime.now(timezone.utc).isoformat()

    con = duckdb.connect(str(FUND_DB))
    pool_rows = con.execute(
        """
        SELECT stock_code, stock_name, sw_l1, sw_l2, sw_l3, priority_tier
        FROM ifind_tracking_pool
        WHERE active
        ORDER BY priority_tier, stock_code
        """
    ).fetchall()
    if limit > 0:
        pool_rows = pool_rows[:limit]

    count = 0
    for stock_code, stock_name, sw_l1, sw_l2, sw_l3, priority_tier in pool_rows:
        tech = tech_by_code.get(stock_code, {})
        pattern = pattern_by_code.get(stock_code, {})
        profile_row = con.execute(
            """
            SELECT industry_chain, chain_position, company_position, development_cycle,
                   placement_assessment, primary_drivers_json, risk_factors_json,
                   evidence_ids_json, llm_confidence, cross_validated
            FROM fundamental_profile
            WHERE stock_code = ? AND as_of_date = ?
            """,
            (stock_code, date_str),
        ).fetchone()
        profile = {}
        if profile_row:
            profile = {
                "industry_chain": profile_row[0],
                "chain_position": profile_row[1],
                "company_position": profile_row[2],
                "development_cycle": profile_row[3],
                "placement_assessment": profile_row[4],
                "primary_drivers": json.loads(profile_row[5] or "[]"),
                "risk_factors": json.loads(profile_row[6] or "[]"),
                "evidence_ids": json.loads(profile_row[7] or "[]"),
                "llm_confidence": profile_row[8],
                "cross_validated": profile_row[9],
            }
        industry_row = con.execute(
            """
            SELECT stock_name, sw_l1, sw_l2, sw_l3, ths_concepts, main_business,
                   comparable_companies, competitor_companies, main_product_types, main_product_names
            FROM ifind_industry_chain_profile
            WHERE stock_code = ? AND as_of_date = ?
            """,
            (stock_code, date_str),
        ).fetchone()
        if industry_row:
            profile["industry_profile"] = {
                "stock_name": industry_row[0],
                "sw_l1": industry_row[1],
                "sw_l2": industry_row[2],
                "sw_l3": industry_row[3],
                "ths_concepts": industry_row[4],
                "main_business": industry_row[5],
                "comparable_companies": industry_row[6],
                "competitor_companies": industry_row[7],
                "main_product_types": industry_row[8],
                "main_product_names": industry_row[9],
            }
        evidence_rows = con.execute(
            """
            SELECT evidence_id, evidence_type, evidence_text, source_api, confidence, unavailable
            FROM fundamental_evidence_packet
            WHERE stock_code = ? AND as_of_date = ?
            ORDER BY evidence_type, evidence_id
            """,
            (stock_code, date_str),
        ).fetchall()
        evidence = [
            {
                "evidence_id": r[0],
                "evidence_type": r[1],
                "evidence_text": r[2],
                "source_api": r[3],
                "confidence": r[4],
                "unavailable": r[5],
            }
            for r in evidence_rows
        ]
        insight = build_insight(stock_code, tech, pattern, profile, evidence)
        evidence_ids = [ev["evidence_id"] for ev in evidence]
        con.execute(
            """
            INSERT OR REPLACE INTO stock_research_ledger
                (stock_code, as_of_date, stock_name, sw_l1, sw_l2, sw_l3, ledger_status,
                 technical_snapshot_json, pattern_snapshot_json, fundamental_snapshot_json,
                 event_digest_json, chief_insight, bull_case, bear_case, watch_points_json,
                 evidence_ids_json, confidence, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stock_code,
                date_str,
                stock_name or profile.get("industry_profile", {}).get("stock_name") or tech.get("stock_name"),
                sw_l1 or profile.get("industry_profile", {}).get("sw_l1") or tech.get("sw_l1"),
                sw_l2 or profile.get("industry_profile", {}).get("sw_l2") or tech.get("sw_l2"),
                sw_l3 or profile.get("industry_profile", {}).get("sw_l3") or tech.get("sw_l3"),
                safe_json(tech),
                safe_json(pattern),
                safe_json(profile),
                "[]",
                insight["chief_insight"],
                insight["bull_case"],
                insight["bear_case"],
                safe_json(insight["watch_points"]),
                safe_json(evidence_ids),
                insight["confidence"],
                generated_at,
            ),
        )
        count += 1

    rows = con.execute(
        """
        SELECT stock_code, stock_name, sw_l1, chief_insight, confidence, evidence_ids_json
        FROM stock_research_ledger
        WHERE as_of_date = ?
        ORDER BY confidence DESC, stock_code
        """,
        (date_str,),
    ).fetchall()
    con.close()

    out_dir = ROOT / "outputs" / "fundamental"
    public_dir = ROOT / "public"
    out_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"stock_research_ledger_{ymd(date_str)}.json"
    html_path = public_dir / f"stock_research_ledger_{ymd(date_str)}.html"
    payload = {
        "schema_version": "stock_research_ledger_v1",
        "date": date_str,
        "generated_at": generated_at,
        "ledger_count": count,
        "rows": [
            {
                "stock_code": r[0],
                "stock_name": r[1],
                "sw_l1": r[2],
                "chief_insight": r[3],
                "confidence": r[4],
                "evidence_count": len(json.loads(r[5] or "[]")),
            }
            for r in rows
        ],
        "research_only": True,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(payload), encoding="utf-8")
    (public_dir / "stock_research_ledger_latest.html").write_text(render_html(payload), encoding="utf-8")
    return {**payload, "json": str(json_path), "html": str(html_path)}


def render_html(payload: dict[str, Any]) -> str:
    rows = []
    for row in payload["rows"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(row['stock_code']))}</td>"
            f"<td>{html.escape(str(row.get('stock_name') or ''))}</td>"
            f"<td>{html.escape(str(row.get('sw_l1') or ''))}</td>"
            f"<td>{html.escape(str(row.get('confidence') or ''))}</td>"
            f"<td>{html.escape(str(row.get('evidence_count') or ''))}</td>"
            f"<td>{html.escape(str(row.get('chief_insight') or ''))}</td>"
            "</tr>"
        )
    body = "\n".join(rows)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>单股研究账本 - {html.escape(payload['date'])}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #172033; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f8fafc; position: sticky; top: 0; }}
    .note {{ color: #64748b; margin-bottom: 16px; }}
  </style>
</head>
<body>
  <h1>单股研究账本 - {html.escape(payload['date'])}</h1>
  <div class="note">Research-only. 本页为本地 iFinD 基本面库 + Hermass 技术证据的持续跟踪账本，不构成投资建议。</div>
  <table>
    <thead><tr><th>代码</th><th>名称</th><th>行业</th><th>置信度</th><th>证据数</th><th>首席式洞察</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build per-stock research ledgers.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    print(json.dumps(build_ledgers(args.date, args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
