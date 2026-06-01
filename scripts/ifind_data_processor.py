#!/usr/bin/env python3
"""Normalize iFinD fundamental facts for reports.

This script converts the existing iFinD evidence database into lightweight JSON
snapshots consumed by reminders and daily briefs. It does not collect data and
does not infer unavailable facts.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
FUND_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
OUT_DIR = ROOT / "outputs" / "ifind"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def quality_label(score: Any) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "数据不足"
    if value >= 80:
        return "质量健康"
    if value >= 50:
        return "质量中性"
    return "质量谨慎"


def ratio_label(
    value: Any, *, high: float, low: float, high_label: str, mid_label: str, low_label: str
) -> str:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return "数据不足"
    if val >= high:
        return high_label
    if val >= low:
        return mid_label
    return low_label


def compact(text: Any, limit: int = 80) -> str:
    raw = str(text or "").replace("\n", " ").strip()
    return raw if len(raw) <= limit else raw[:limit] + "..."


def build_financial_rows(con: duckdb.DuckDBPyConnection, date_str: str) -> list[dict[str, Any]]:
    source_date = latest_source_date(con, "fundamental_quality_score", date_str)
    if source_date is None:
        return []
    rows = con.execute(
        """
        SELECT stock_code, stock_name, core_business_purity, cash_quality,
               earnings_quality, asset_safety_ratio, quality_score,
               final_fundamental_score
        FROM fundamental_quality_score
        WHERE as_of_date = ?
        ORDER BY stock_code
        """,
        (source_date,),
    ).fetchall()
    out = []
    for row in rows:
        (
            stock_code,
            stock_name,
            core_purity,
            cash_quality,
            earnings_quality,
            asset_safety,
            quality_score,
            final_score,
        ) = row
        labels = [
            quality_label(quality_score),
            ratio_label(
                cash_quality,
                high=1.0,
                low=0.5,
                high_label="现金流健康",
                mid_label="现金流中性",
                low_label="现金流谨慎",
            ),
            ratio_label(
                earnings_quality,
                high=0.9,
                low=0.5,
                high_label="盈利质量健康",
                mid_label="盈利质量中性",
                low_label="盈利质量谨慎",
            ),
            ratio_label(
                asset_safety,
                high=0.6,
                low=0.2,
                high_label="资产安全",
                mid_label="资产中性",
                low_label="资产压力",
            ),
        ]
        summary = "；".join(label for label in labels if label != "数据不足") or "基本面数据不足"
        out.append(
            {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "source_as_of_date": source_date,
                "quality_score": quality_score,
                "final_fundamental_score": final_score,
                "core_business_purity": core_purity,
                "cash_quality": cash_quality,
                "earnings_quality": earnings_quality,
                "asset_safety_ratio": asset_safety,
                "quality_label": quality_label(quality_score),
                "cash_quality_label": labels[1],
                "earnings_quality_label": labels[2],
                "asset_safety_label": labels[3],
                "summary": summary,
            }
        )
    return out


def build_industry_rows(con: duckdb.DuckDBPyConnection, date_str: str) -> list[dict[str, Any]]:
    source_date = latest_source_date(con, "ifind_industry_chain_profile", date_str)
    if source_date is None:
        return []
    rows = con.execute(
        """
        SELECT stock_code, stock_name, sw_l1, sw_l2, sw_l3, ths_concepts,
               main_business, main_product_types, main_product_names,
               comparable_companies, competitor_companies
        FROM ifind_industry_chain_profile
        WHERE as_of_date = ?
        ORDER BY stock_code
        """,
        (source_date,),
    ).fetchall()
    out = []
    for row in rows:
        (
            stock_code,
            stock_name,
            sw_l1,
            sw_l2,
            sw_l3,
            concepts,
            main_business,
            product_types,
            product_names,
            comparable,
            competitors,
        ) = row
        chain_identity = "/".join(part for part in [sw_l1, sw_l2, sw_l3] if part) or "未分类"
        out.append(
            {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "source_as_of_date": source_date,
                "sw_l1": sw_l1,
                "sw_l2": sw_l2,
                "sw_l3": sw_l3,
                "industry_climate": "未标注",
                "chain_position": "未标注",
                "chain_identity": chain_identity,
                "ths_concepts": concepts,
                "main_business": main_business,
                "main_product_types": product_types,
                "main_product_names": product_names,
                "comparable_companies": comparable,
                "competitor_companies": competitors,
                "summary": f"{chain_identity}；主营={compact(main_business, 60)}",
            }
        )
    return out


def rows_by_code(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("stock_code")): row for row in rows if row.get("stock_code")}


def latest_source_date(con: duckdb.DuckDBPyConnection, table: str, date_str: str) -> str | None:
    row = con.execute(
        f"""
        SELECT MAX(as_of_date)
        FROM {table}
        WHERE as_of_date <= ?
        """,
        (date_str,),
    ).fetchone()
    return row[0] if row and row[0] else None


def write_payload(path: Path, latest_path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")


def process_ifind_data(date_str: str, db_path: Path = FUND_DB) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    con = duckdb.connect(str(db_path), read_only=True)
    financial_source_date = latest_source_date(con, "fundamental_quality_score", date_str)
    industry_source_date = latest_source_date(con, "ifind_industry_chain_profile", date_str)
    financial_rows = build_financial_rows(con, date_str)
    industry_rows = build_industry_rows(con, date_str)
    con.close()

    quality_counts = Counter(row["quality_label"] for row in financial_rows)
    industry_counts = Counter(row.get("sw_l1") or "未分类" for row in industry_rows)
    financial_payload = {
        "schema_version": "ifind_financial_snapshot_v1",
        "date": date_str,
        "generated_at": generated_at,
        "source_db": str(db_path),
        "source_as_of_date": financial_source_date,
        "total": len(financial_rows),
        "quality_counts": dict(sorted(quality_counts.items())),
        "rows": financial_rows,
        "by_code": rows_by_code(financial_rows),
        "research_only": True,
    }
    industry_payload = {
        "schema_version": "ifind_industry_snapshot_v1",
        "date": date_str,
        "generated_at": generated_at,
        "source_db": str(db_path),
        "source_as_of_date": industry_source_date,
        "total": len(industry_rows),
        "industry_counts": dict(sorted(industry_counts.items())),
        "rows": industry_rows,
        "by_code": rows_by_code(industry_rows),
        "research_only": True,
    }
    date_ymd = ymd(date_str)
    financial_path = OUT_DIR / f"financial_{date_ymd}.json"
    financial_latest = OUT_DIR / "financial_latest.json"
    industry_path = OUT_DIR / f"industry_{date_ymd}.json"
    industry_latest = OUT_DIR / "industry_latest.json"
    write_payload(financial_path, financial_latest, financial_payload)
    write_payload(industry_path, industry_latest, industry_payload)
    return {
        "ok": True,
        "date": date_str,
        "source_db": str(db_path),
        "financial_total": len(financial_rows),
        "industry_total": len(industry_rows),
        "financial_source_as_of_date": financial_source_date,
        "industry_source_as_of_date": industry_source_date,
        "quality_counts": financial_payload["quality_counts"],
        "top_industries": dict(industry_counts.most_common(10)),
        "financial_json": str(financial_path),
        "financial_latest": str(financial_latest),
        "industry_json": str(industry_path),
        "industry_latest": str(industry_latest),
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize existing iFinD data for reports.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--fundamental-db", type=Path, default=FUND_DB)
    args = parser.parse_args()
    result = process_ifind_data(args.date, args.fundamental_db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
