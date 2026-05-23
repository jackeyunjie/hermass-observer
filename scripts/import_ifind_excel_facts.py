#!/usr/bin/env python3
"""Import iFinD GUI Excel exports into the local fundamental evidence DB."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import duckdb

ROOT = Path(__file__).resolve().parents[1]
FUND_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def ymd(d: str) -> str:
    return d.replace("-", "")


def col_to_index(cell_ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", cell_ref.upper())
    out = 0
    for ch in letters:
        out = out * 26 + (ord(ch) - ord("A") + 1)
    return out - 1


def cell_value(cell: ET.Element, shared: list[str]) -> str | float | None:
    typ = cell.attrib.get("t")
    if typ == "inlineStr":
        text = "".join(t.text or "" for t in cell.findall(".//a:t", NS))
        return text
    value = cell.find("a:v", NS)
    if value is None or value.text is None:
        return None
    raw = value.text
    if typ == "s":
        return shared[int(raw)]
    try:
        return float(raw)
    except ValueError:
        return raw


def read_xlsx(path: Path) -> list[list[str | float | None]]:
    with ZipFile(path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("a:si", NS):
                shared.append("".join(t.text or "" for t in si.findall(".//a:t", NS)))

        sheet = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
        rows: list[list[str | float | None]] = []
        for row in sheet.findall(".//a:row", NS):
            cells: dict[int, str | float | None] = {}
            max_idx = -1
            for cell in row.findall("a:c", NS):
                idx = col_to_index(cell.attrib.get("r", "A1"))
                cells[idx] = cell_value(cell, shared)
                max_idx = max(max_idx, idx)
            rows.append([cells.get(i) for i in range(max_idx + 1)])
        return rows


def parse_metric_header(header: str) -> dict[str, str]:
    lines = [line.strip() for line in str(header or "").splitlines() if line.strip()]
    metric_name = lines[0] if lines else "unknown_metric"
    meta: dict[str, str] = {
        "metric_name": metric_name,
        "report_period": "",
        "report_type": "",
        "unit": "",
    }
    for line in lines[1:]:
        if line.startswith("[报告期]"):
            meta["report_period"] = line.replace("[报告期]", "").strip()
        elif line.startswith("[报表类型]"):
            meta["report_type"] = line.replace("[报表类型]", "").strip()
        elif line.startswith("[单位]"):
            meta["unit"] = line.replace("[单位]", "").strip()
    return meta


def normalize_code(code: str) -> str:
    code = str(code or "").strip().upper()
    if "." not in code:
        return code
    raw, suffix = code.split(".", 1)
    if suffix in {"SH", "SZ", "BJ"}:
        return f"{raw}.{suffix}"
    return code


def upsert_excel_derived(con: duckdb.DuckDBPyConnection, date_str: str, collected_at: str) -> int:
    rows = con.execute(
        """
        WITH latest_revenue AS (
            SELECT stock_code, any_value(stock_name) AS stock_name, max(metric_value) AS revenue
            FROM ifind_excel_facts
            WHERE as_of_date = ?
              AND metric_name = '营业总收入'
              AND metric_value IS NOT NULL
            GROUP BY stock_code
        ),
        ranked AS (
            SELECT stock_code, stock_name, revenue,
                   row_number() OVER (ORDER BY revenue DESC) AS revenue_rank,
                   count(*) OVER () AS peer_count,
                   cume_dist() OVER (ORDER BY revenue ASC) AS revenue_rank_pct
            FROM latest_revenue
        )
        SELECT stock_code, stock_name, revenue, revenue_rank, revenue_rank_pct, peer_count
        FROM ranked
        WHERE stock_code IN (SELECT stock_code FROM ifind_tracking_pool WHERE active)
        ORDER BY stock_code
        """,
        (date_str,),
    ).fetchall()
    for code, name, revenue, rank, rank_pct, peer_count in rows:
        con.execute(
            """
            INSERT OR REPLACE INTO ifind_derived_metrics
            (stock_code, as_of_date, revenue_rank_sw_l2, revenue_rank_pct, peer_count, computed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (code, date_str, rank, rank_pct, peer_count, collected_at),
        )
        text = (
            "iFinD Excel L2 derived metrics:\n"
            f"- stock_name: {name or ''}\n"
            f"- 营业总收入: {float(revenue):g} 元\n"
            f"- 全市场收入排名: {rank}/{peer_count}\n"
            f"- 收入规模分位: {float(rank_pct):.4f}"
        )
        con.execute(
            """
            INSERT OR REPLACE INTO fundamental_evidence_packet
            (evidence_id, stock_code, as_of_date, evidence_type, evidence_text,
             source_vendor, source_api, source_query, source_period, confidence, collected_at)
            VALUES (?, ?, ?, 'ifind_excel_l2_derived', ?, 'iFind', 'Python_Derived_From_GUI_Excel',
                    'ifind_excel_facts:营业总收入', 'MRQ', 0.9, ?)
            """,
            (
                f"ifind_excel_l2_revenue_{code}_{ymd(date_str)}",
                code,
                date_str,
                text,
                collected_at,
            ),
        )
    return len(rows)


def refresh_excel_evidence(
    con: duckdb.DuckDBPyConnection,
    path: Path,
    date_str: str,
    statement_type: str,
    collected_at: str,
) -> tuple[int, int]:
    evidence_count = 0
    tracking_codes = {
        row[0]
        for row in con.execute("SELECT stock_code FROM ifind_tracking_pool WHERE active").fetchall()
    }
    for code in sorted(tracking_codes):
        facts = con.execute(
            """
            SELECT metric_name, metric_value, report_period, report_type, unit
            FROM ifind_excel_facts
            WHERE stock_code = ? AND as_of_date = ? AND source_file = ?
            ORDER BY metric_name
            """,
            (code, date_str, str(path)),
        ).fetchall()
        if not facts:
            continue
        lines = [f"iFinD Excel facts ({statement_type}):"]
        for metric_name, metric_value, report_period, report_type, unit in facts:
            suffix = f"{report_period} {report_type} {unit}".strip()
            lines.append(f"- {metric_name}: {metric_value:g}" + (f" ({suffix})" if suffix else ""))
        evidence_id = f"ifind_excel_{statement_type}_{code}_{ymd(date_str)}"
        con.execute(
            """
            INSERT OR REPLACE INTO fundamental_evidence_packet
            (evidence_id, stock_code, as_of_date, evidence_type, evidence_text,
             source_vendor, source_api, source_query, source_period, confidence, collected_at)
            VALUES (?, ?, ?, ?, ?, 'iFind', 'GUI_Excel', ?, ?, 0.95, ?)
            """,
            (
                evidence_id,
                code,
                date_str,
                f"ifind_excel_{statement_type}",
                "\n".join(lines)[:4000],
                str(path),
                ",".join(sorted({str(f[2] or "") for f in facts if f[2]})),
                collected_at,
            ),
        )
        evidence_count += 1

        all_facts = con.execute(
            """
            SELECT metric_name, metric_value, report_period, report_type, unit,
                   string_agg(DISTINCT statement_type, ', ' ORDER BY statement_type) AS statement_types
            FROM ifind_excel_facts
            WHERE stock_code = ? AND as_of_date = ?
              AND metric_value IS NOT NULL
            GROUP BY metric_name, metric_value, report_period, report_type, unit
            ORDER BY metric_name
            """,
            (code, date_str),
        ).fetchall()
        if all_facts:
            lines = ["iFinD Excel aggregate facts (all imported GUI files):"]
            for metric_name, metric_value, report_period, report_type, unit, stmts in all_facts:
                suffix = f"{stmts} {report_period} {report_type} {unit}".strip()
                lines.append(
                    f"- {metric_name}: {metric_value:g}" + (f" ({suffix})" if suffix else "")
                )
            aggregate_id = f"ifind_excel_aggregate_{code}_{ymd(date_str)}"
            con.execute(
                """
                INSERT OR REPLACE INTO fundamental_evidence_packet
                (evidence_id, stock_code, as_of_date, evidence_type, evidence_text,
                 source_vendor, source_api, source_query, source_period, confidence, collected_at)
                VALUES (?, ?, ?, 'ifind_excel_aggregate', ?, 'iFind', 'GUI_Excel', ?, 'MRQ/all_imported', 0.95, ?)
                """,
                (
                    aggregate_id,
                    code,
                    date_str,
                    "\n".join(lines)[:6000],
                    "ifind_excel_facts",
                    collected_at,
                ),
            )

    derived_count = upsert_excel_derived(con, date_str, collected_at)
    return evidence_count, derived_count


def import_excel(path: Path, date_str: str, statement_type: str) -> dict:
    import importlib.util

    path = path.expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    else:
        path = path.resolve()

    spec = importlib.util.spec_from_file_location(
        "fundamental_evidence_schema",
        str(ROOT / "scripts" / "fundamental_evidence_schema.py"),
    )
    schema_mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(schema_mod)
    schema_mod.init_schema(FUND_DB)

    collected_at = datetime.now(timezone.utc).isoformat()
    con = duckdb.connect(str(FUND_DB))
    existing_count = con.execute(
        """
        SELECT COUNT(*)
        FROM ifind_excel_facts
        WHERE as_of_date = ? AND statement_type = ? AND source_file = ?
        """,
        (date_str, statement_type, str(path)),
    ).fetchone()[0]
    if existing_count:
        evidence_count, derived_count = refresh_excel_evidence(
            con, path, date_str, statement_type, collected_at
        )
        con.close()
        return {
            "schema_version": "ifind_excel_import_v1",
            "date": date_str,
            "source_file": str(path),
            "statement_type": statement_type,
            "rows_parsed": 0,
            "facts_imported": 0,
            "existing_facts": existing_count,
            "skipped_existing_import": True,
            "tracking_evidence_packets": evidence_count,
            "l2_derived_packets": derived_count,
            "research_only": True,
        }
    con.close()

    rows = read_xlsx(path)
    if not rows:
        raise RuntimeError(f"No rows parsed from {path}")

    headers = [str(x or "") for x in rows[0]]
    metric_headers = [(idx, parse_metric_header(headers[idx])) for idx in range(2, len(headers))]

    con = duckdb.connect(str(FUND_DB))
    fact_count = 0
    fact_rows: list[tuple] = []

    def flush_fact_rows() -> None:
        nonlocal fact_rows
        if not fact_rows:
            return
        con.execute("BEGIN")
        con.executemany(
            """
            INSERT OR REPLACE INTO ifind_excel_facts
            (stock_code, stock_name, as_of_date, statement_type, metric_name, metric_value,
             report_period, report_type, unit, source_file, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            fact_rows,
        )
        con.execute("COMMIT")
        fact_rows = []

    for row in rows[1:]:
        if len(row) < 3:
            continue
        code = normalize_code(str(row[0] or ""))
        name = str(row[1] or "").strip() or None
        if not code:
            continue
        for idx, meta in metric_headers:
            value = row[idx] if idx < len(row) else None
            if value in (None, ""):
                continue
            try:
                num_value = float(value)
            except (TypeError, ValueError):
                continue
            fact_rows.append(
                (
                code,
                name,
                date_str,
                statement_type,
                meta["metric_name"],
                num_value,
                meta["report_period"],
                meta["report_type"],
                meta["unit"],
                str(path),
                collected_at,
                )
            )
            fact_count += 1
            if len(fact_rows) >= 20000:
                flush_fact_rows()

    flush_fact_rows()

    evidence_count, derived_count = refresh_excel_evidence(
        con, path, date_str, statement_type, collected_at
    )
    con.close()
    return {
        "schema_version": "ifind_excel_import_v1",
        "date": date_str,
        "source_file": str(path),
        "statement_type": statement_type,
        "rows_parsed": max(0, len(rows) - 1),
        "facts_imported": fact_count,
        "tracking_evidence_packets": evidence_count,
        "l2_derived_packets": derived_count,
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import iFinD GUI Excel facts.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--statement-type", default="financial_statement")
    args = parser.parse_args()

    result = import_excel(Path(args.file), args.date, args.statement_type)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
