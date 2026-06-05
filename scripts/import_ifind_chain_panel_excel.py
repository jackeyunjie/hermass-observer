#!/usr/bin/env python3
"""import_ifind_chain_panel_excel.py — 导入 iFinD 产业链节点成分股 Excel。

用于将研究员从 iFinD 终端"产业链中心/产业智绘"手动导出的节点成分股清单
结构化入库到 ifind_chain_panel 表。

用法：
    source .venv/bin/activate
    python3 scripts/import_ifind_chain_panel_excel.py --date 2026-06-04 --file chain_panel_ai_compute.xlsx
    python3 scripts/import_ifind_chain_panel_excel.py --date 2026-06-04 --file chain_panel.xlsx --dry-run

Excel 标准格式（config/chain_panel_import_template.xlsx）：
    chain_id | chain_name | node_id | node_name | node_position | stock_code | stock_name | role

输出：
    outputs/industry_chain/industry_chain_evidence.duckdb → ifind_chain_panel

字段规范（按 Codex 要求）：
    chain_id, chain_name, node_id, node_name, node_position,
    stock_code, stock_name, role,
    source_type='ifind_terminal_excel',
    evidence_level='manual_export',
    confidence=0.90,
    node_match_method='manual_terminal_export',
    manual_verified=true,
    raw_source_ref=Excel文件路径,
    as_of_date, updated_at
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
CHAIN_DB = ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

CREATE_IFIND_CHAIN_PANEL = """
CREATE TABLE IF NOT EXISTS ifind_chain_panel (
    chain_id          VARCHAR    NOT NULL,
    chain_name        VARCHAR    NOT NULL,
    node_id           VARCHAR    NOT NULL,
    node_name         VARCHAR    NOT NULL,
    node_position     VARCHAR,
    stock_code        VARCHAR    NOT NULL,
    stock_name        VARCHAR,
    role              VARCHAR,
    source_type       VARCHAR    NOT NULL DEFAULT 'ifind_terminal_excel',
    evidence_level    VARCHAR    NOT NULL DEFAULT 'manual_export',
    confidence        DOUBLE     NOT NULL DEFAULT 0.90,
    node_match_method VARCHAR,
    manual_verified   BOOLEAN    NOT NULL DEFAULT true,
    raw_source_ref    VARCHAR,
    as_of_date        VARCHAR    NOT NULL,
    updated_at        VARCHAR    NOT NULL,
    PRIMARY KEY (chain_id, node_id, stock_code, as_of_date)
);
"""

# ---------------------------------------------------------------------------
# Excel reader
# ---------------------------------------------------------------------------


def load_excel_reader():
    spec = importlib.util.spec_from_file_location(
        "import_ifind_excel_facts",
        str(ROOT / "scripts" / "import_ifind_excel_facts.py"),
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.read_xlsx, module.normalize_code


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "--":
        return None
    return re.sub(r"\s+", " ", text)


# ---------------------------------------------------------------------------
# Import logic
# ---------------------------------------------------------------------------


def import_chain_panel_excel(path: Path, date_str: str, dry_run: bool = False) -> dict[str, Any]:
    path = path.expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    else:
        path = path.resolve()

    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    read_xlsx, normalize_code = load_excel_reader()
    rows = read_xlsx(path)
    if not rows:
        raise RuntimeError(f"No rows parsed from {path}")

    headers = [str(x or "").strip().lower().replace(" ", "_") for x in rows[0]]

    # Normalize header mapping
    header_map = {}
    for idx, h in enumerate(headers):
        if h in ("chain_id", "chain_name", "node_id", "node_name", "node_position",
                 "stock_code", "stock_name", "role"):
            header_map[h] = idx

    required = ["chain_id", "chain_name", "node_id", "node_name", "stock_code"]
    missing = [r for r in required if r not in header_map]
    if missing:
        raise ValueError(f"Excel missing required columns: {missing}. Found headers: {headers}")

    updated_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    errors: list[str] = []

    for i, row in enumerate(rows[1:], start=2):
        if len(row) < max(header_map.values()) + 1:
            continue

        chain_id = _clean_text(row[header_map["chain_id"]])
        chain_name = _clean_text(row[header_map["chain_name"]])
        node_id = _clean_text(row[header_map["node_id"]])
        node_name = _clean_text(row[header_map["node_name"]])
        stock_code_raw = _clean_text(row[header_map["stock_code"]])

        if not chain_id or not node_id or not stock_code_raw:
            continue

        stock_code = normalize_code(stock_code_raw)
        if not stock_code:
            errors.append(f"Row {i}: cannot normalize stock_code '{stock_code_raw}'")
            continue

        node_position = _clean_text(row[header_map.get("node_position", -1)]) if "node_position" in header_map else None
        stock_name = _clean_text(row[header_map.get("stock_name", -1)]) if "stock_name" in header_map else None
        role = _clean_text(row[header_map.get("role", -1)]) if "role" in header_map else None

        raw_source_ref = json.dumps(
            {"source_file": str(path), "source_row": i, "import_method": "manual_terminal_excel"},
            ensure_ascii=False,
        )

        records.append(
            {
                "chain_id": chain_id,
                "chain_name": chain_name or chain_id,
                "node_id": node_id,
                "node_name": node_name or node_id,
                "node_position": node_position,
                "stock_code": stock_code,
                "stock_name": stock_name,
                "role": role or "待确认",
                "source_type": "ifind_terminal_excel",
                "evidence_level": "manual_export",
                "confidence": 0.90,
                "node_match_method": "manual_terminal_export",
                "manual_verified": True,
                "raw_source_ref": raw_source_ref,
                "as_of_date": date_str,
                "updated_at": updated_at,
            }
        )

    # Write to DB
    if not dry_run and records:
        CHAIN_DB.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(CHAIN_DB))
        try:
            con.execute(CREATE_IFIND_CHAIN_PANEL)
            for rec in records:
                con.execute(
                    """
                    INSERT OR REPLACE INTO ifind_chain_panel
                    (chain_id, chain_name, node_id, node_name, node_position,
                     stock_code, stock_name, role, source_type, evidence_level,
                     confidence, node_match_method, manual_verified, raw_source_ref,
                     as_of_date, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec["chain_id"], rec["chain_name"], rec["node_id"], rec["node_name"],
                        rec["node_position"], rec["stock_code"], rec["stock_name"], rec["role"],
                        rec["source_type"], rec["evidence_level"], rec["confidence"],
                        rec["node_match_method"], rec["manual_verified"], rec["raw_source_ref"],
                        rec["as_of_date"], rec["updated_at"],
                    ),
                )
        finally:
            con.close()

    return {
        "ok": True,
        "date": date_str,
        "source_file": str(path),
        "dry_run": dry_run,
        "records_imported": len(records),
        "errors": errors,
        "db": str(CHAIN_DB),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Import iFinD chain panel Excel into DuckDB.")
    parser.add_argument("--date", required=True, help="as_of_date YYYY-MM-DD")
    parser.add_argument("--file", required=True, help="Path to Excel file")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, do not write DB")
    args = parser.parse_args()

    result = import_chain_panel_excel(Path(args.file), args.date, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
