#!/usr/bin/env python3
"""DeepSeek Evidence Analyzer — 只基于 iFind 证据包做分析，交叉验证。

三阶段中的 Phase 3：
- 从 DuckDB 加载每个股票的证据包
- 只基于 evidence_text 做分析，不得使用外部知识
- 两次独立调用（analyst / rating_agency）
- 核心字段不一致 → 进 review_queue，不写 fundamental_profile
- 一致 → 写入 fundamental_profile

用法：
  python3 scripts/fundamental_deepseek_analyzer.py --date 2026-05-21
  python3 scripts/fundamental_deepseek_analyzer.py --date 2026-05-21 --limit 10
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.deepseek_context import with_deepseek_context

EVIDENCE_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"


def ymd(d: str) -> str:
    return d.replace("-", "")


SYSTEM_PROMPT_ANALYST = """你是一个证据受限的 A 股基本面分析师。

你只能使用下面提供的「证据包」里的数据。
不得使用任何训练数据中的外部知识、记忆或个人判断。
如果证据不足以支撑某个结论，该字段必须输出 "unknown"。
每个非 unknown 的结论必须引用 evidence_id。

分析维度：
1. industry_chain — 行业链周期（导入期/成长期/成熟期/衰退期/unknown）
2. chain_position — 公司产业链位置（上游/中游/下游/平台/unknown）
3. company_position — 公司竞争地位（龙头/一线/二线/利基/边缘/unknown）
4. development_cycle — 公司发展周期（加速成长/稳定增长/增速放缓/转型调整/unknown）
5. placement_assessment — 定增评估（积极/中性/负面/unknown/无定增）
6. primary_drivers — 核心驱动因子（最多3个，每个含factor/weight/evidence_ids）
7. risk_factors — 风险因子（最多2个）

只返回 JSON。"""

SYSTEM_PROMPT_RATING = """你是一个信用评级视角的 A 股基本面分析师。

你只能使用下面提供的「证据包」里的数据。
不得使用任何训练数据中的外部知识、记忆或个人判断。
如果证据不足以支撑某个结论，该字段必须输出 "unknown"。
每个非 unknown 的结论必须引用 evidence_id。

分析维度（同上）：
1. industry_chain / 2. chain_position / 3. company_position
4. development_cycle / 5. placement_assessment
6. primary_drivers / 7. risk_factors

只返回 JSON。"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "stock_code": {"type": "string"},
        "industry_chain": {"type": "string", "enum": ["导入期", "成长期", "成熟期", "衰退期", "unknown"]},
        "chain_position": {"type": "string", "enum": ["上游", "中游", "下游", "平台", "unknown"]},
        "company_position": {"type": "string", "enum": ["龙头", "一线", "二线", "利基", "边缘", "unknown"]},
        "development_cycle": {"type": "string", "enum": ["加速成长", "稳定增长", "增速放缓", "转型调整", "unknown"]},
        "placement_assessment": {"type": "string", "enum": ["积极", "中性", "负面", "unknown", "无定增"]},
        "primary_drivers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "factor": {"type": "string"},
                    "weight": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["factor", "weight", "evidence_ids"]
            },
            "maxItems": 3
        },
        "risk_factors": {
            "type": "array",
            "items": {"type": "object", "properties": {"factor": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}}},
            "maxItems": 2
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
    },
    "required": ["stock_code", "industry_chain", "chain_position", "company_position", "development_cycle", "placement_assessment", "confidence"]
}


def call_deepseek(system_prompt: str, user_prompt: str, api_key: str, api_base: str) -> dict:
    url = f"{api_base}/v1/chat/completions"
    body = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": with_deepseek_context(system_prompt)},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 1500,
        "response_format": {"type": "json_object"}
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    })
    with urllib.request.urlopen(req, timeout=90) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return json.loads(result["choices"][0]["message"]["content"])


def load_evidence(con: duckdb.DuckDBPyConnection, stock_code: str, as_of_date: str) -> list[dict]:
    rows = con.execute("""
        SELECT evidence_id, evidence_type, evidence_text, source_api, unmapped, unavailable
        FROM fundamental_evidence_packet
        WHERE stock_code = ? AND as_of_date = ?
        ORDER BY evidence_type, evidence_id
    """, (stock_code, as_of_date)).fetchall()
    return [
        {
            "evidence_id": r[0],
            "evidence_type": r[1],
            "evidence_text": (r[2] or "")[:3000],
            "source_api": r[3],
            "unmapped": r[4],
            "unavailable": r[5],
        }
        for r in rows
    ]


def build_prompt(stock_code: str, evidence: list[dict]) -> str:
    ev_lines = []
    for ev in evidence:
        tag = ""
        if ev["unmapped"]:
            tag = " [不可用-未映射到iFind]"
        elif ev["unavailable"]:
            tag = " [不可用-iFind未认证]"
        ev_lines.append(f"[{ev['evidence_type']}]{tag}\n  ID: {ev['evidence_id']}\n  {ev['evidence_text']}")
    if not ev_lines:
        ev_lines.append("（无可用证据 — 所有字段应输出 unknown）")
    return f"股票代码: {stock_code}\n\n证据包:\n" + "\n".join(ev_lines)


CORE_FIELDS = [
    "industry_chain",
    "company_position",
    "development_cycle",
    "placement_assessment",
]


def cross_validate(r1: dict, r2: dict) -> tuple[bool, list[str]]:
    conflicts = []
    for field in CORE_FIELDS:
        v1 = r1.get(field, "")
        v2 = r2.get(field, "")
        if v1 != v2 and v1 != "unknown" and v2 != "unknown":
            conflicts.append(f"{field}: {v1} vs {v2}")
    return len(conflicts) == 0, conflicts


def analyze(date_str: str, limit: int = 20) -> dict:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    api_base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com")

    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")

    db_path = EVIDENCE_DB
    if not db_path.exists():
        raise FileNotFoundError("Evidence DB not found. Run ifind_fundamental_collector.py first.")

    con = duckdb.connect(str(db_path))

    stocks = con.execute("""
        SELECT DISTINCT stock_code FROM fundamental_evidence_packet
        WHERE as_of_date = ?
        ORDER BY stock_code
    """, (date_str,)).fetchall()

    stock_list = [r[0] for r in stocks]
    if limit and limit > 0:
        stock_list = stock_list[:limit]

    print(f"Analyzing {len(stock_list)} stocks with cross-validation...")

    passed = 0
    failed = 0
    skipped_no_evidence = 0

    for code in stock_list:
        evidence = load_evidence(con, code, date_str)
        valid_evidence = [e for e in evidence if not e.get("unmapped") and not e.get("unavailable")]
        if len(valid_evidence) <= 1:
            skipped_no_evidence += 1
            continue

        prompt = build_prompt(code, evidence)

        try:
            r1 = call_deepseek(SYSTEM_PROMPT_ANALYST, prompt, api_key, api_base)
        except Exception as e:
            print(f"  [warn] analyst call failed for {code}: {e}", file=sys.stderr)
            continue
        try:
            r2 = call_deepseek(SYSTEM_PROMPT_RATING, prompt, api_key, api_base)
        except Exception as e:
            print(f"  [warn] rating_agency call failed for {code}: {e}", file=sys.stderr)
            continue

        ok, conflicts = cross_validate(r1, r2)
        drivers = r1.get("primary_drivers") or []
        risks = r1.get("risk_factors") or []
        confidence = min(r1.get("confidence", 0), r2.get("confidence", 0))

        if not ok:
            con.execute("""
                INSERT OR REPLACE INTO fundamental_review_queue
                (stock_code, as_of_date, conflict_type, analyst_result, rating_agency_result, conflict_detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (code, date_str, "cross_validation_mismatch",
                   json.dumps(r1, ensure_ascii=False)[:3000],
                   json.dumps(r2, ensure_ascii=False)[:3000],
                   json.dumps(conflicts, ensure_ascii=False)[:1000],
                   datetime.now(timezone.utc).isoformat()))
            failed += 1
            print(f"  ✗ {code} → review_queue ({'; '.join(conflicts[:2])})")
            continue

        ev_ids = [e["evidence_id"] for e in evidence]
        con.execute("""
            INSERT OR REPLACE INTO fundamental_profile
            (stock_code, as_of_date, industry_chain, chain_position, company_position,
             development_cycle, placement_assessment, primary_drivers_json,
             risk_factors_json, evidence_ids_json, llm_model, llm_confidence,
             analyst_pass, rating_agency_pass, cross_validated, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'deepseek-chat', ?, TRUE, TRUE, TRUE, ?)
        """, (code, date_str,
               r1.get("industry_chain", "unknown"),
               r1.get("chain_position", "unknown"),
               r1.get("company_position", "unknown"),
               r1.get("development_cycle", "unknown"),
               r1.get("placement_assessment", "unknown"),
               json.dumps(drivers, ensure_ascii=False),
               json.dumps(risks, ensure_ascii=False),
               json.dumps(ev_ids, ensure_ascii=False),
               confidence,
               datetime.now(timezone.utc).isoformat()))
        passed += 1
        print(f"  ✓ {code} → profile (conf={confidence:.2f})")

    con.close()

    return {
        "schema_version": "fundamental_analysis_v1",
        "date": date_str,
        "stocks_analyzed": len(stock_list),
        "passed": passed,
        "failed_cross_validation": failed,
        "skipped_no_evidence": skipped_no_evidence,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="DeepSeek Evidence Analyzer")
    parser.add_argument("--date", required=True)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    result = analyze(args.date, args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
