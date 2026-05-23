#!/usr/bin/env python3
"""iFind 财务报表导入器 — Excel → DuckDB。

读取 codex 指定的 4 个标准化 Excel：
  data/ifind_stock_income_core_mrq_YYYYMMDD.xlsx     利润表
  data/ifind_stock_balance_core_mrq_YYYYMMDD.xlsx    资产负债表
  data/ifind_stock_cashflow_core_mrq_YYYYMMDD.xlsx   现金流量表
  data/ifind_stock_quality_metrics_mrq_YYYYMMDD.xlsx 质量指标

统一参数：报告期 MRQ / 合并报表 / 单位元

用法：
  python3 scripts/ifind_financial_importer.py --date 2026-05-22
  python3 scripts/ifind_financial_importer.py --date 2026-05-22 --income data/全部A股利润表_20260522.xlsx
"""

from __future__ import annotations

import argparse
import json
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"


def ymd(d: str) -> str:
    return d.replace("-", "")


# ── 列名映射（iFind 中文 → 标准英文字段名）──
INCOME_COLUMN_MAP = {
    "营业总收入": "total_revenue",
    "营业收入": "operating_revenue",
    "营业成本": "operating_cost",
    "毛利": "gross_profit",
    "营业利润": "operating_profit",
    "利润总额": "total_profit",
    "净利润": "net_profit",
    "归属于母公司所有者的净利润": "net_profit_attr_parent",
    "扣除非经常性损益后的归母净利润": "net_profit_deducted",
    "基本每股收益": "eps_basic",
    "稀释每股收益": "eps_diluted",
}

BALANCE_COLUMN_MAP = {
    "总资产": "total_assets",
    "总负债": "total_liabilities",
    "所有者权益合计": "total_equity",
    "归属于母公司所有者权益合计": "equity_attr_parent",
    "货币资金": "cash_equivalents",
    "应收账款": "accounts_receivable",
    "存货": "inventory",
    "短期借款": "short_term_borrowing",
    "长期借款": "long_term_borrowing",
    "合同负债": "contract_liabilities",
    "商誉": "goodwill",
}

CASHFLOW_COLUMN_MAP = {
    "经营活动产生的现金流量净额": "cfo_operating",
    "投资活动产生的现金流量净额": "cfo_investing",
    "筹资活动产生的现金流量净额": "cfo_financing",
    "销售商品、提供劳务收到的现金": "cash_from_sales",
    "购买商品、接受劳务支付的现金": "cash_for_purchases",
    "期末现金及现金等价物余额": "cash_end_balance",
}

QUALITY_COLUMN_MAP = {
    "ROE": "roe",
    "净资产收益率": "roe",
    "净利率": "net_margin",
    "资产负债率": "debt_ratio",
    "经营现金流/净利润": "cfo_to_profit",
    "营业收入同比增长率": "revenue_yoy",
    "归母净利润同比增长率": "net_profit_yoy",
    "扣非归母净利润同比增长率": "net_profit_deducted_yoy",
    "研发费用率": "rd_expense_ratio",
    "存货周转率": "inventory_turnover",
    "应收账款周转率": "receivable_turnover",
}

# ── codex 建议补充的字段 ──
CODEX_EXTRA_INCOME = [
    "营业总成本",       # 与营业总收入成对，计算成本率
    "研发费用",         # 研发绝对值，不只是比率
    "销售费用",
    "管理费用",
    "财务费用",
    "资产减值损失",
    "投资收益",
]

CODEX_EXTRA_BALANCE = [
    "固定资产",         # 产能基础
    "在建工程",         # 未来产能释放
    "无形资产",         # 技术/品牌资产
    "应付账款",         # 对上游占款能力
    "预收款项",         # 与合同负债互补
]

CODEX_EXTRA_CASHFLOW = [
    "购建固定资产、无形资产和其他长期资产支付的现金",  # 资本开支
    "取得借款收到的现金",
    "偿还债务支付的现金",
    "分配股利、利润或偿付利息支付的现金",
]


def _extend_map(base: dict, extra: list[str]) -> dict:
    for item in extra:
        if item not in base:
            base[item] = item.replace("、", "_").replace("（", "_").replace("）", "").replace("/", "_").replace(" ", "_")
    return base


INCOME_COLUMN_MAP = _extend_map(INCOME_COLUMN_MAP, CODEX_EXTRA_INCOME)
BALANCE_COLUMN_MAP = _extend_map(BALANCE_COLUMN_MAP, CODEX_EXTRA_BALANCE)
CASHFLOW_COLUMN_MAP = _extend_map(CASHFLOW_COLUMN_MAP, CODEX_EXTRA_CASHFLOW)


# ── 核心导入逻辑 ──

def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace(" ", "")
    if s == "" or s == "-" or s == "N/A":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_code(v: Any) -> str:
    s = str(v).strip().replace(" ", "")
    if "." in s:
        return s
    if s.endswith("SH") or s.endswith("SZ"):
        return s[:6] + "." + s[-2:]
    if s.startswith("6"):
        return s + ".SH"
    return s + ".SZ"


def read_excel_rows(filepath: Path, column_map: dict[str, str], category: str) -> list[dict]:
    """读取 iFind 导出的 Excel，用 zipfile+xml 解析以避免依赖 openpyxl."""
    import zipfile
    import xml.etree.ElementTree as ET

    if not filepath.exists():
        print(f"  [warn] {filepath.name} not found, skipping")
        return []

    z = zipfile.ZipFile(str(filepath))
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    # Shared strings
    ss: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        tree = ET.parse(z.open("xl/sharedStrings.xml"))
        for si in tree.findall(f".//{{{ns}}}si"):
            t = si.find(f".//{{{ns}}}t")
            ss.append(t.text if t is not None and t.text else "")
    else:
        # Excel may use inline strings
        pass

    # Read sheet data
    sheet_tree = ET.parse(z.open("xl/worksheets/sheet1.xml"))
    rows_elem = sheet_tree.findall(f".//{{{ns}}}row")

    # Find header row (first row with meaningful text)
    header: list[str] = []
    data_start = 0

    for row_idx, row_elem in enumerate(rows_elem):
        cells = {}
        for c in row_elem.findall(f".//{{{ns}}}c"):
            ref = c.get("r", "")
            col_letter = "".join(ch for ch in ref if ch.isalpha())
            cell_type = c.get("t", "")
            v_elem = c.find(f".//{{{ns}}}v")
            val: str = ""
            if v_elem is not None and v_elem.text:
                if cell_type == "s":
                    idx = int(v_elem.text)
                    val = ss[idx] if idx < len(ss) else ""
                else:
                    val = v_elem.text
            cells[col_letter] = val

        # Try to identify header
        sorted_cols = sorted(cells.keys())
        row_vals = [cells.get(c, "") for c in sorted_cols]
        # A column usually has stock codes or "证券代码"
        if "证券代码" in str(row_vals) or "股票代码" in str(row_vals) or "code" in str(row_vals).lower():
            header = row_vals
            data_start = row_idx + 1
            break

    if not header:
        # If no explicit header found, try row 0
        sorted_cols_first = sorted(
            {c.get("r", ""): c for c in rows_elem[0].findall(f".//{{{ns}}}c")}.keys()
        ) if rows_elem else []
        if rows_elem:
            cells = {}
            for c in rows_elem[0].findall(f".//{{{ns}}}c"):
                ref = c.get("r", "")
                col_letter = "".join(ch for ch in ref if ch.isalpha())
                cell_type = c.get("t", "")
                v_elem = c.find(f".//{{{ns}}}v")
                val = ""
                if v_elem is not None and v_elem.text:
                    if cell_type == "s":
                        idx = int(v_elem.text)
                        val = ss[idx] if idx < len(ss) else ""
                    else:
                        val = v_elem.text
                cells[col_letter] = val
            sorted_cols = sorted(cells.keys())
            header = [cells.get(c, "") for c in sorted_cols]
            data_start = 1

    # Map header column names to standard fields
    col_to_field: dict[int, str] = {}
    col_to_name: dict[int, str] = {}

    for idx, col_name in enumerate(header):
        cn = str(col_name).strip()
        # Remove trailing spaces / newlines
        cn_clean = cn.replace("\n", "").replace("\r", "")
        mapped = None
        for key, val in column_map.items():
            if key in cn_clean:
                mapped = val
                break
        if mapped:
            col_to_field[idx] = mapped
            col_to_name[idx] = cn_clean

    # Always map code column
    if "证券代码" not in str(header) and "代码" in str(header):
        pass  # already handled

    # Find code column
    code_col = -1
    for idx, h in enumerate(header):
        if "代码" in str(h) or "code" in str(h).lower() or "证券" in str(h):
            code_col = idx
            break

    if code_col < 0:
        # Try column A
        code_col = 0

    result: list[dict] = []
    for row_elem in rows_elem[data_start:]:
        cells = {}
        for c in row_elem.findall(f".//{{{ns}}}c"):
            ref = c.get("r", "")
            col_letter = "".join(ch for ch in ref if ch.isalpha())
            cell_type = c.get("t", "")
            v_elem = c.find(f".//{{{ns}}}v")
            val = ""
            if v_elem is not None and v_elem.text:
                if cell_type == "s":
                    idx_s = int(v_elem.text)
                    val = ss[idx_s] if idx_s < len(ss) else ""
                else:
                    val = v_elem.text
            cells[col_letter] = val

        sorted_cols = sorted(cells.keys())
        row_vals = [cells.get(c, "") for c in sorted_cols]

        code = _to_code(row_vals[code_col]) if code_col < len(row_vals) else ""
        if not code or len(code) < 6:
            continue
        if code.startswith("000") and not code.endswith((".SZ", ".SH")):
            # Skip non-standard codes
            pass

        record: dict[str, Any] = {"stock_code": code, "category": category, "source_file": filepath.name}
        for col_idx, field_name in col_to_field.items():
            if col_idx < len(row_vals):
                record[field_name] = _to_float(row_vals[col_idx])
        result.append(record)

    z.close()
    return result


def import_to_duckdb(records: list[dict], date_str: str, collected_at: str) -> int:
    db_path = EVIDENCE_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)

    import importlib.util
    spec = importlib.util.spec_from_file_location("fundamental_evidence_schema",
        str(ROOT / "scripts" / "fundamental_evidence_schema.py"))
    schema_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(schema_mod)
    schema_mod.init_schema(db_path)

    con = duckdb.connect(str(db_path))

    # Build dynamic columns
    all_keys = set()
    for r in records:
        all_keys.update(r.keys())

    con.execute("DROP TABLE IF EXISTS _temp_fin_import")
    cols_sql = ", ".join(f'"{k}" VARCHAR' for k in all_keys if k not in ("stock_code", "category", "source_file"))
    con.execute(f"CREATE TEMP TABLE _temp_fin_import (stock_code VARCHAR, category VARCHAR, source_file VARCHAR, {cols_sql})")

    for r in records:
        col_names = ["stock_code", "category", "source_file"] + [k for k in all_keys if k not in ("stock_code", "category", "source_file")]
        vals = [r.get(k) for k in col_names]
        placeholders = ",".join("?" * len(col_names))
        con.execute(f"INSERT INTO _temp_fin_import VALUES ({placeholders})", vals)

    # Upsert into financial_metrics
    for r in records:
        con.execute("""
            INSERT OR REPLACE INTO ifind_financial_metrics
            (stock_code, report_period, report_type, source_vendor, source_api, source_query, collected_at)
            VALUES (?, 'MRQ', 'consolidated', 'iFind', 'THS_BD', ?, ?)
        """, (r["stock_code"], f"Excel: {r.get('source_file', '')}", collected_at))

    # Write evidence packets
    ev_count = 0
    for r in records:
        ev_id = f"fs_mrq_{r['stock_code']}_{ymd(date_str)}"
        con.execute("""
            INSERT OR REPLACE INTO fundamental_evidence_packet
            (evidence_id, stock_code, as_of_date, evidence_type, evidence_text,
             source_vendor, source_api, source_query, confidence, collected_at)
            VALUES (?, ?, ?, 'financial_statement_mrq', ?, 'iFind', 'manual_export', ?, 0.95, ?)
        """, (ev_id, r["stock_code"], date_str,
              json.dumps({k: v for k, v in r.items() if k not in ("stock_code", "category", "source_file")}, ensure_ascii=False)[:4000],
              r.get("source_file", ""), collected_at))
        ev_count += 1

    # Compute quality metrics from financial statements
    derived_count = _compute_derived_from_fs(con, records, date_str, collected_at)

    con.close()
    return ev_count + derived_count


def _compute_derived_from_fs(con, records: list[dict], date_str: str, collected_at: str) -> int:
    count = 0
    for r in records:
        code = r["stock_code"]
        rev = r.get("operating_revenue") or r.get("total_revenue")
        cost = r.get("operating_cost")
        profit = r.get("net_profit") or r.get("net_profit_attr_parent")
        equity = r.get("total_equity") or r.get("equity_attr_parent")
        assets = r.get("total_assets")
        liab = r.get("total_liabilities")
        cfo = r.get("cfo_operating")
        rd = r.get("研发费用") or r.get("rd_expense")

        gm = None
        if rev and cost and rev > 0:
            gm = round((rev - cost) / rev * 100, 2)

        nm = None
        if profit and rev and rev > 0:
            nm = round(profit / rev * 100, 2)

        roe_val = None
        if profit and equity and equity > 0:
            roe_val = round(profit / equity * 100, 2)

        debt_r = None
        if liab and assets and assets > 0:
            debt_r = round(liab / assets * 100, 2)

        rd_r = None
        if rd and rev and rev > 0:
            rd_r = round(rd / rev * 100, 2)

        con.execute("""
            INSERT OR REPLACE INTO ifind_derived_metrics
            (stock_code, as_of_date, gross_margin_rank_pct, roe_rank_pct,
             debt_ratio, computed_at)
            VALUES (?, ?, NULL, NULL, ?, ?)
        """, (code, date_str, debt_r, collected_at))
        count += 1

        # Also store computed metrics as evidence
        derived = {"gross_margin_calculated": gm, "net_margin_calculated": nm,
                   "roe_calculated": roe_val, "debt_ratio_calculated": debt_r,
                   "rd_ratio_calculated": rd_r}
        con.execute("""
            INSERT OR REPLACE INTO fundamental_evidence_packet
            (evidence_id, stock_code, as_of_date, evidence_type, evidence_text,
             source_vendor, source_api, confidence, collected_at)
            VALUES (?, ?, ?, 'derived_metrics', ?, 'iFind', 'python_computed', 0.85, ?)
        """, (f"derived_{code}_{ymd(date_str)}", code, date_str,
              json.dumps(derived, ensure_ascii=False), collected_at))
        count += 1

    return count


# ── 主入口 ──

def run(date_str: str,
        income_file: str | None = None,
        balance_file: str | None = None,
        cashflow_file: str | None = None,
        quality_file: str | None = None) -> dict:
    collected_at = datetime.now(timezone.utc).isoformat()
    y = ymd(date_str)

    # Default file paths
    income_path = Path(income_file) if income_file else ROOT / "data" / f"ifind_stock_income_core_mrq_{y}.xlsx"
    balance_path = Path(balance_file) if balance_file else ROOT / "data" / f"ifind_stock_balance_core_mrq_{y}.xlsx"
    cashflow_path = Path(cashflow_file) if cashflow_file else ROOT / "data" / f"ifind_stock_cashflow_core_mrq_{y}.xlsx"
    quality_path = Path(quality_file) if quality_file else ROOT / "data" / f"ifind_stock_quality_metrics_mrq_{y}.xlsx"

    all_records: list[dict] = []
    for path, col_map, cat in [
        (income_path, INCOME_COLUMN_MAP, "income"),
        (balance_path, BALANCE_COLUMN_MAP, "balance"),
        (cashflow_path, CASHFLOW_COLUMN_MAP, "cashflow"),
        (quality_path, QUALITY_COLUMN_MAP, "quality"),
    ]:
        rows = read_excel_rows(path, col_map, cat)
        print(f"  [{cat}] {path.name}: {len(rows)} rows")
        all_records.extend(rows)

    total_count = import_to_duckdb(all_records, date_str, collected_at)

    # Stats
    codes = sorted(set(r["stock_code"] for r in all_records))

    return {
        "schema_version": "ifind_financial_import_v1",
        "date": date_str,
        "files_processed": {
            "income": str(income_path),
            "balance": str(balance_path),
            "cashflow": str(cashflow_path),
            "quality": str(quality_path),
        },
        "total_records": len(all_records),
        "unique_stocks": len(codes),
        "total_evidence_packets": total_count,
        "generated_at": collected_at,
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="iFind 财务报表导入器 → DuckDB")
    parser.add_argument("--date", required=True)
    parser.add_argument("--income", help="利润表 Excel 路径（默认 data/ifind_stock_income_core_mrq_YYYYMMDD.xlsx）")
    parser.add_argument("--balance", help="资产负债表 Excel")
    parser.add_argument("--cashflow", help="现金流量表 Excel")
    parser.add_argument("--quality", help="质量指标 Excel")
    args = parser.parse_args()

    result = run(args.date, args.income, args.balance, args.cashflow, args.quality)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
