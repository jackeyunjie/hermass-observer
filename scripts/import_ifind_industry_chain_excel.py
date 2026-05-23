#!/usr/bin/env python3
"""Import iFinD industry chain / business profile Excel into DuckDB."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
FUND_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"


def ymd(d: str) -> str:
    return d.replace("-", "")


def load_excel_reader():
    spec = importlib.util.spec_from_file_location(
        "import_ifind_excel_facts",
        str(ROOT / "scripts" / "import_ifind_excel_facts.py"),
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.read_xlsx, module.normalize_code


def init_schema() -> None:
    spec = importlib.util.spec_from_file_location(
        "fundamental_evidence_schema",
        str(ROOT / "scripts" / "fundamental_evidence_schema.py"),
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.init_schema(FUND_DB)


def parse_header(header: str) -> dict[str, str]:
    lines = [line.strip() for line in str(header or "").splitlines() if line.strip()]
    metric_name = lines[0] if lines else "unknown_metric"
    meta = {
        "metric_name": metric_name,
        "report_period": "",
        "segment_basis": "",
        "rank_label": "",
        "unit": "",
    }
    for line in lines[1:]:
        if line.startswith("[报告期]"):
            meta["report_period"] = line.replace("[报告期]", "").strip()
        elif line.startswith("[分类标准]"):
            meta["segment_basis"] = line.replace("[分类标准]", "").strip()
        elif line.startswith("[排名]"):
            meta["rank_label"] = line.replace("[排名]", "").strip()
        elif "[排名]" in line:
            meta["rank_label"] = line.split("[排名]", 1)[1].replace("[单位]%", "").strip()
        elif line.startswith("[单位]"):
            meta["unit"] = line.replace("[单位]", "").strip()
    return meta


PROFILE_COLUMNS = {
    "所属申万行业": "sw",
    "所属同花顺概念指数": "ths_concepts",
    "主营业务": "main_business",
    "经营范围": "business_scope",
    "可比公司": "comparable_companies",
    "竞争公司": "competitor_companies",
    "主营产品类型": "main_product_types",
    "主营产品名称": "main_product_names",
}


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "--":
        return None
    return re.sub(r"\s+", " ", text)


def refresh_chain_evidence(
    con: duckdb.DuckDBPyConnection,
    path: Path,
    date_str: str,
    collected_at: str,
) -> int:
    tracking = con.execute("SELECT stock_code FROM ifind_tracking_pool WHERE active").fetchall()
    evidence_count = 0
    for (code,) in tracking:
        row = con.execute(
            """
            SELECT stock_name, sw_l1, sw_l2, sw_l3, ths_concepts, main_business,
                   comparable_companies, competitor_companies, main_product_types, main_product_names
            FROM ifind_industry_chain_profile
            WHERE stock_code = ? AND as_of_date = ?
            """,
            (code, date_str),
        ).fetchone()
        if not row:
            continue
        labels = [
            "证券名称",
            "申万一级",
            "申万二级",
            "申万三级",
            "同花顺概念",
            "主营业务",
            "可比公司",
            "竞争公司",
            "主营产品类型",
            "主营产品名称",
        ]
        lines = ["iFinD industry chain profile:"]
        for label, value in zip(labels, row):
            if value:
                lines.append(f"- {label}: {value}")
        segments = con.execute(
            """
            SELECT metric_name, metric_value, report_period, segment_basis, rank_label, unit
            FROM ifind_business_segment_facts
            WHERE stock_code = ? AND as_of_date = ?
            ORDER BY report_period DESC, metric_name
            LIMIT 20
            """,
            (code, date_str),
        ).fetchall()
        for metric, value, period, basis, rank, unit in segments:
            suffix = " ".join(x for x in [period, basis, rank, unit] if x)
            lines.append(f"- {metric}: {value:g}" + (f" ({suffix})" if suffix else ""))
        con.execute(
            """
            INSERT OR REPLACE INTO fundamental_evidence_packet
            (evidence_id, stock_code, as_of_date, evidence_type, evidence_text,
             source_vendor, source_api, source_query, source_period, confidence, collected_at)
            VALUES (?, ?, ?, 'ifind_industry_chain_profile', ?, 'iFind', 'GUI_Excel',
                    ?, 'latest/annual/quarterly', 0.95, ?)
            """,
            (
                f"ifind_industry_chain_{code}_{ymd(date_str)}",
                code,
                date_str,
                "\n".join(lines)[:6000],
                str(path),
                collected_at,
            ),
        )
        evidence_count += 1
    return evidence_count


def import_chain_excel(path: Path, date_str: str) -> dict[str, Any]:
    path = path.expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    else:
        path = path.resolve()

    init_schema()
    collected_at = datetime.now(timezone.utc).isoformat()
    con = duckdb.connect(str(FUND_DB))

    existing_profiles = con.execute(
        """
        SELECT COUNT(*)
        FROM ifind_industry_chain_profile
        WHERE as_of_date = ?
        """,
        (date_str,),
    ).fetchone()[0]
    existing_segments = con.execute(
        """
        SELECT COUNT(*)
        FROM ifind_business_segment_facts
        WHERE as_of_date = ?
        """,
        (date_str,),
    ).fetchone()[0]
    if existing_profiles and existing_segments:
        evidence_count = refresh_chain_evidence(con, path, date_str, collected_at)
        con.close()
        return {
            "schema_version": "ifind_industry_chain_import_v1",
            "date": date_str,
            "source_file": str(path),
            "profiles_imported": 0,
            "segment_facts_imported": 0,
            "existing_profiles": existing_profiles,
            "existing_segment_facts": existing_segments,
            "skipped_existing_import": True,
            "tracking_evidence_packets": evidence_count,
            "fundamental_db": str(FUND_DB),
            "research_only": True,
        }

    read_xlsx, normalize_code = load_excel_reader()
    rows = read_xlsx(path)
    if not rows:
        raise RuntimeError(f"No rows parsed from {path}")

    headers = [str(x or "") for x in rows[0]]
    metas = [parse_header(h) for h in headers]

    profile_rows: list[tuple] = []
    segment_rows: list[tuple] = []

    for row in rows[1:]:
        if len(row) < 2:
            continue
        code = normalize_code(str(row[0] or ""))
        name = _clean_text(row[1])
        if not code:
            continue
        profile = {
            "sw_l1": None,
            "sw_l2": None,
            "sw_l3": None,
            "ths_concepts": None,
            "main_business": None,
            "business_scope": None,
            "comparable_companies": None,
            "competitor_companies": None,
            "main_product_types": None,
            "main_product_names": None,
        }
        for idx, header in enumerate(headers[2:], start=2):
            value = row[idx] if idx < len(row) else None
            text = _clean_text(value)
            metric = metas[idx]["metric_name"]
            if metric == "所属申万行业":
                if "一级行业" in header:
                    profile["sw_l1"] = text
                elif "二级行业" in header:
                    profile["sw_l2"] = text
                elif "三级行业" in header:
                    profile["sw_l3"] = text
                continue
            if metric in PROFILE_COLUMNS:
                key = PROFILE_COLUMNS[metric]
                if key != "sw":
                    profile[key] = text
                continue
            try:
                num_value = float(value)
            except (TypeError, ValueError):
                continue
            segment_rows.append(
                (
                    code,
                    name,
                    date_str,
                    metric,
                    num_value,
                    metas[idx]["report_period"],
                    metas[idx]["segment_basis"],
                    metas[idx]["rank_label"],
                    metas[idx]["unit"],
                    str(path),
                    collected_at,
                )
            )
        profile_rows.append(
            (
                code,
                name,
                date_str,
                profile["sw_l1"],
                profile["sw_l2"],
                profile["sw_l3"],
                profile["ths_concepts"],
                profile["main_business"],
                profile["business_scope"],
                profile["comparable_companies"],
                profile["competitor_companies"],
                profile["main_product_types"],
                profile["main_product_names"],
                str(path),
                collected_at,
            )
        )

    if profile_rows:
        con.executemany(
            """
            INSERT OR REPLACE INTO ifind_industry_chain_profile
            (stock_code, stock_name, as_of_date, sw_l1, sw_l2, sw_l3, ths_concepts,
             main_business, business_scope, comparable_companies, competitor_companies,
             main_product_types, main_product_names, source_file, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            profile_rows,
        )
    for start in range(0, len(segment_rows), 20000):
        con.executemany(
            """
            INSERT OR REPLACE INTO ifind_business_segment_facts
            (stock_code, stock_name, as_of_date, metric_name, metric_value, report_period,
             segment_basis, rank_label, unit, source_file, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            segment_rows[start : start + 20000],
        )

    evidence_count = refresh_chain_evidence(con, path, date_str, collected_at)

    con.close()
    return {
        "schema_version": "ifind_industry_chain_import_v1",
        "date": date_str,
        "source_file": str(path),
        "profiles_imported": len(profile_rows),
        "segment_facts_imported": len(segment_rows),
        "tracking_evidence_packets": evidence_count,
        "fundamental_db": str(FUND_DB),
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import iFinD industry chain Excel.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--file", required=True)
    args = parser.parse_args()
    print(json.dumps(import_chain_excel(Path(args.file), args.date), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
