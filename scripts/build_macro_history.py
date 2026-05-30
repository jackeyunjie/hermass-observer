#!/usr/bin/env python3
"""Build macro indicator history from AKShare and Tushare.

Pull 24-month historical series for active indicators, compute
mom/yoy/percentile/trend, and write to macro_indicator_data.duckdb.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "outputs" / "macro" / "macro_indicator_data.duckdb"
DEFAULT_CONFIG = ROOT / "config" / "ifind_macro_indicators.json"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def norm_date(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y-%m-%d")
        except Exception:
            pass
    text = str(value).strip()
    if not text:
        return None
    text = text.split("T", 1)[0].replace("/", "-").replace(".", "-")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) == 6 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-01"
    # Handle Chinese date format like "2026年04月份"
    import re
    m = re.match(r"(\d{4})年(\d{2})月份", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-01"
    return text


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"--", "-", "NA", "N/A", "nan", "None", "null"}:
        return None
    text = text.replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS macro_indicator_history (
                indicator_code VARCHAR,
                as_of_date DATE,
                indicator_name VARCHAR,
                category VARCHAR,
                value DOUBLE,
                unit VARCHAR,
                frequency VARCHAR,
                source_api VARCHAR,
                source_query VARCHAR,
                collected_at TIMESTAMP,
                updated_at TIMESTAMP,
                PRIMARY KEY (indicator_code, as_of_date, source_api)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS macro_indicator_summary (
                indicator_code VARCHAR PRIMARY KEY,
                indicator_name VARCHAR,
                category VARCHAR,
                frequency VARCHAR,
                unit VARCHAR,
                latest_date DATE,
                latest_value DOUBLE,
                previous_value DOUBLE,
                change DOUBLE,
                change_pct DOUBLE,
                history_count INTEGER,
                percentile DOUBLE,
                trend VARCHAR,
                data_status VARCHAR,
                source_count INTEGER,
                updated_at TIMESTAMP
            )
            """
        )
    finally:
        con.close()


def percentile_rank(values: list[float], latest: float | None) -> float | None:
    if latest is None or not values:
        return None
    less_equal = sum(1 for v in values if v <= latest)
    return round(less_equal * 100.0 / len(values), 2)


def trend_direction(latest: float | None, previous: float | None) -> str:
    if latest is None or previous is None:
        return "data_insufficient"
    change = latest - previous
    threshold = max(abs(previous) * 0.001, 0.0001)
    if abs(change) <= threshold:
        return "flat"
    return "up" if change > 0 else "down"


def data_status(history_count: int) -> str:
    if history_count >= 12:
        return "trend_ready"
    if history_count >= 2:
        return "partial_history"
    if history_count == 1:
        return "single_point"
    return "missing"


def akshare_cpi() -> list[dict[str, Any]]:
    import akshare as ak
    df = ak.macro_china_cpi_yearly()
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        d = norm_date(r.get("日期"))
        v = to_float(r.get("今值"))
        if d and v is not None and not (isinstance(v, float) and math.isnan(v)):
            rows.append({"as_of_date": d, "value": v})
    return rows


def akshare_ppi() -> list[dict[str, Any]]:
    import akshare as ak
    df = ak.macro_china_ppi_yearly()
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        d = norm_date(r.get("日期"))
        v = to_float(r.get("今值"))
        if d and v is not None and not (isinstance(v, float) and math.isnan(v)):
            rows.append({"as_of_date": d, "value": v})
    return rows


def akshare_pmi() -> list[dict[str, Any]]:
    import akshare as ak
    df = ak.macro_china_pmi_yearly()
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        d = norm_date(r.get("日期"))
        v = to_float(r.get("今值"))
        if d and v is not None:
            rows.append({"as_of_date": d, "value": v})
    return rows


def akshare_gdp() -> list[dict[str, Any]]:
    import akshare as ak
    df = ak.macro_china_gdp()
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        q = str(r.get("季度", "")).strip()
        v = to_float(r.get("国内生产总值-同比增长"))
        if q and v is not None:
            # Parse "2026年第1季度" -> 2026-03-31
            import re
            m = re.match(r"(\d{4})年第(\d+)季度", q)
            if m:
                year, qnum = int(m.group(1)), int(m.group(2))
                month_end = qnum * 3
                last_day = {3: 31, 6: 30, 9: 30, 12: 31}.get(month_end, 31)
                d = f"{year}-{month_end:02d}-{last_day:02d}"
                rows.append({"as_of_date": d, "value": v})
    return rows


def akshare_lpr() -> list[dict[str, Any]]:
    import akshare as ak
    df = ak.macro_china_lpr()
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        d = norm_date(r.get("TRADE_DATE") or r.get("日期"))
        v = to_float(r.get("LPR1Y"))
        if d and v is not None:
            rows.append({"as_of_date": d, "value": v})
    return rows


def akshare_industrial() -> list[dict[str, Any]]:
    import akshare as ak
    # Try multiple possible function names
    candidates = [
        "macro_china_industrial_production_yearly",
        "macro_china_industrial_production",
        "macro_china_industrial_growth",
        "macro_china_gdzctz",
    ]
    for fn_name in candidates:
        try:
            fn = getattr(ak, fn_name)
            df = fn()
            rows: list[dict[str, Any]] = []
            for _, r in df.iterrows():
                d = norm_date(r.get("日期") or r.get("月份") or r.get("时间") or r.get("TRADE_DATE"))
                v = to_float(r.get("今值") or r.get("当月同比") or r.get("同比") or r.get("同比增长"))
                if d and v is not None:
                    rows.append({"as_of_date": d, "value": v})
            if rows:
                return rows
        except Exception as exc:
            print(f"[akshare_industrial] {fn_name} failed: {exc}")
            continue
    return []


def akshare_bond_yield_10y() -> list[dict[str, Any]]:
    import akshare as ak
    # Primary: bond_zh_us_rate has longer history (2002-present)
    try:
        df = ak.bond_zh_us_rate()
        if df is not None and not df.empty:
            rows: list[dict[str, Any]] = []
            for _, r in df.iterrows():
                d = norm_date(r.get("日期"))
                v = to_float(r.get("中国国债收益率10年"))
                if d and v is not None:
                    rows.append({"as_of_date": d, "value": v})
            if rows:
                return rows
    except Exception:
        pass
    # Fallback: bond_china_yield (shorter history)
    try:
        df = ak.bond_china_yield()
        if df is not None and not df.empty:
            rows: list[dict[str, Any]] = []
            for _, r in df.iterrows():
                curve = str(r.get("曲线名称", ""))
                if "国债收益率曲线" not in curve:
                    continue
                d = norm_date(r.get("日期"))
                v = to_float(r.get("10年"))
                if d and v is not None:
                    rows.append({"as_of_date": d, "value": v})
            if rows:
                return rows
    except Exception:
        pass
    return []


def tushare_money_supply() -> list[dict[str, Any]]:
    import importlib.util
    ts_spec = importlib.util.find_spec("tushare")
    if ts_spec is None:
        return []
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        return []
    import tushare as ts
    ts.set_token(token)
    pro = ts.pro_api()
    rows: list[dict[str, Any]] = []
    try:
        df = pro.cn_m(start_m="202401", end_m="202605")
        for _, r in df.iterrows():
            d = norm_date(r.get("month"))
            v = to_float(r.get("m2_yoy"))
            if d and v is not None:
                rows.append({"as_of_date": d, "value": v, "sub_indicator": "M2同比"})
    except Exception:
        pass
    try:
        df = pro.sf_month(start_m="202401", end_m="202605")
        for _, r in df.iterrows():
            d = norm_date(r.get("month"))
            v = to_float(r.get("inc_month"))
            if d and v is not None:
                rows.append({"as_of_date": d, "value": v, "sub_indicator": "社融增量"})
    except Exception:
        pass
    return rows


def insert_history_rows(
    db_path: Path,
    code: str,
    name: str,
    category: str,
    unit: str,
    frequency: str,
    source_api: str,
    rows: list[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    init_db(db_path)
    con = duckdb.connect(str(db_path))
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    try:
        for row in rows:
            d = row.get("as_of_date")
            v = row.get("value")
            if not d or v is None:
                continue
            query = {"collector": "build_macro_history.py", "sub_indicator": row.get("sub_indicator", "")}
            con.execute(
                """
                INSERT OR REPLACE INTO macro_indicator_history
                (indicator_code, as_of_date, indicator_name, category, value, unit, frequency, source_api, source_query, collected_at, updated_at)
                VALUES (?, CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, CAST(? AS TIMESTAMP), CAST(? AS TIMESTAMP))
                """,
                [
                    code,
                    d,
                    name,
                    category,
                    v,
                    unit,
                    frequency,
                    source_api,
                    json.dumps(query, ensure_ascii=False),
                    now,
                    now,
                ],
            )
            inserted += 1
    finally:
        con.close()
    return inserted


def build_summary(db_path: Path, metadata: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    init_db(db_path)
    con = duckdb.connect(str(db_path))
    out: list[dict[str, Any]] = []
    try:
        codes = [row[0] for row in con.execute("SELECT DISTINCT indicator_code FROM macro_indicator_history ORDER BY indicator_code").fetchall()]
        now = datetime.now(timezone.utc).isoformat()
        con.execute("DELETE FROM macro_indicator_summary")
        for code in codes:
            rows = con.execute(
                """
                SELECT indicator_code, as_of_date::VARCHAR, indicator_name, category, value, unit, frequency, source_api
                FROM macro_indicator_history
                WHERE indicator_code = ?
                ORDER BY as_of_date, source_api
                """,
                [code],
            ).fetchall()
            by_date: dict[str, tuple[Any, ...]] = {}
            for row in rows:
                by_date[str(row[1])] = row
            ordered = [by_date[key] for key in sorted(by_date)]
            if not ordered:
                continue
            latest = ordered[-1]
            previous = ordered[-2] if len(ordered) >= 2 else None
            values = [float(row[4]) for row in ordered if to_float(row[4]) is not None]
            latest_value = to_float(latest[4])
            previous_value = to_float(previous[4]) if previous else None
            delta = round(latest_value - previous_value, 6) if latest_value is not None and previous_value is not None else None
            delta_pct = round(delta * 100.0 / previous_value, 4) if delta is not None and previous_value not in (None, 0.0) else None
            meta = metadata.get(code, {})
            category = latest[3] or meta.get("category") or "unknown"
            row_out = {
                "indicator_code": code,
                "indicator_name": latest[2] or meta.get("name") or code,
                "category": category,
                "frequency": latest[6] or meta.get("frequency") or "",
                "unit": latest[5] or meta.get("unit") or "",
                "latest_date": latest[1],
                "latest_value": latest_value,
                "previous_value": previous_value,
                "change": delta,
                "change_pct": delta_pct,
                "history_count": len(ordered),
                "percentile": percentile_rank(values, latest_value),
                "trend": trend_direction(latest_value, previous_value),
                "data_status": data_status(len(ordered)),
                "source_count": len({str(row[7]) for row in rows}),
            }
            con.execute(
                """
                INSERT OR REPLACE INTO macro_indicator_summary
                (indicator_code, indicator_name, category, frequency, unit, latest_date, latest_value, previous_value, change, change_pct,
                 history_count, percentile, trend, data_status, source_count, updated_at)
                VALUES (?, ?, ?, ?, ?, CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS TIMESTAMP))
                """,
                [
                    row_out["indicator_code"],
                    row_out["indicator_name"],
                    row_out["category"],
                    row_out["frequency"],
                    row_out["unit"],
                    row_out["latest_date"],
                    row_out["latest_value"],
                    row_out["previous_value"],
                    row_out["change"],
                    row_out["change_pct"],
                    row_out["history_count"],
                    row_out["percentile"],
                    row_out["trend"],
                    row_out["data_status"],
                    row_out["source_count"],
                    now,
                ],
            )
            out.append(row_out)
    finally:
        con.close()
    out.sort(key=lambda item: (str(item.get("category")), str(item.get("indicator_code"))))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Build macro indicator history from AKShare/Tushare.")
    parser.add_argument("--out-db", default=str(DEFAULT_DB))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()

    db_path = Path(args.out_db)
    config = load_json(Path(args.config))
    metadata: dict[str, dict[str, Any]] = {}
    for raw in config.get("indicators", []) or []:
        code = raw.get("code")
        if code:
            metadata[str(code)] = raw

    # Also load macro_data_sources.json for AKShare/Tushare mapping
    multi = load_json(ROOT / "config" / "macro_data_sources.json")
    for raw in multi.get("macro_indicators", []) or []:
        code = raw.get("code")
        if code:
            metadata.setdefault(str(code), raw)

    results: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    # AKShare indicators
    ak_indicators = [
        ("AK:macro_china_cpi_yearly", "CPI:当月同比", "inflation", "%", "monthly", akshare_cpi),
        ("AK:macro_china_ppi_yearly", "PPI:当月同比", "inflation", "%", "monthly", akshare_ppi),
        ("AK:macro_china_pmi_yearly", "制造业PMI", "growth", "%", "monthly", akshare_pmi),
        ("AK:macro_china_gdp", "GDP:累计同比", "growth", "%", "quarterly", akshare_gdp),
        ("AK:macro_china_lpr", "1年期LPR", "liquidity", "%", "monthly", akshare_lpr),
        ("AK:macro_china_industrial", "工业增加值:当月同比", "growth", "%", "monthly", akshare_industrial),
    ]

    for code, name, category, unit, freq, fn in ak_indicators:
        try:
            rows = fn()
            inserted = insert_history_rows(db_path, code, name, category, unit, freq, f"AKShare:{fn.__name__}", rows)
            results.append({"code": code, "source": "akshare", "rows": len(rows), "inserted": inserted, "status": "ok"})
        except Exception as exc:
            results.append({"code": code, "source": "akshare", "rows": 0, "inserted": 0, "status": "error", "error": str(exc)})

    # 10-year bond yield
    try:
        rows = akshare_bond_yield_10y()
        inserted = insert_history_rows(db_path, "AK:bond_10y", "中债国债到期收益率:10年", "liquidity", "%", "daily", "AKShare:bond_china_yield", rows)
        results.append({"code": "AK:bond_10y", "source": "akshare", "rows": len(rows), "inserted": inserted, "status": "ok" if rows else "no_data"})
    except Exception as exc:
        results.append({"code": "AK:bond_10y", "source": "akshare", "rows": 0, "inserted": 0, "status": "error", "error": str(exc)})

    # Tushare indicators
    try:
        ts_rows = tushare_money_supply()
        # Split by sub_indicator
        by_sub: dict[str, list[dict[str, Any]]] = {}
        for row in ts_rows:
            sub = row.get("sub_indicator", "unknown")
            by_sub.setdefault(sub, []).append(row)
        for sub, rows in by_sub.items():
            if sub == "M2同比":
                code, name, category = "TS:cn_m", "M2:同比", "credit"
            elif sub == "社融增量":
                code, name, category = "TS:sf_month", "社会融资规模增量", "credit"
            else:
                continue
            inserted = insert_history_rows(db_path, code, name, category, "%" if "同比" in sub else "亿元", "monthly", "Tushare", rows)
            results.append({"code": code, "source": "tushare", "rows": len(rows), "inserted": inserted, "status": "ok"})
    except Exception as exc:
        results.append({"code": "TS:cn_m/sf_month", "source": "tushare", "rows": 0, "inserted": 0, "status": "error", "error": str(exc)})

    # Build summary
    summary_rows = build_summary(db_path, metadata)

    # Print coverage report
    print("\n=== 宏观指标历史数据覆盖报告 ===\n")
    print(f"{'指标代码':<30s} | {'指标名称':<20s} | {'历史长度':>8s} | {'最新值':>10s} | {'趋势':>8s} | {'12月分位':>10s} | {'状态':<15s}")
    print("-" * 120)
    for row in summary_rows:
        code = row["indicator_code"]
        name = row["indicator_name"][:18]
        cnt = row["history_count"]
        val = f"{row['latest_value']:.2f}" if row["latest_value"] is not None else "N/A"
        trend = row["trend"]
        pct = f"{row['percentile']:.1f}%" if row["percentile"] is not None else "N/A"
        status = row["data_status"]
        print(f"{code:<30s} | {name:<20s} | {cnt:>8d} | {val:>10s} | {trend:>8s} | {pct:>10s} | {status:<15s}")

    print(f"\n总计: {len(summary_rows)} 个指标")
    trend_ready = sum(1 for r in summary_rows if r["data_status"] == "trend_ready")
    partial = sum(1 for r in summary_rows if r["data_status"] == "partial_history")
    print(f"趋势可判(>=12期): {trend_ready} | 部分历史: {partial} | 其他: {len(summary_rows) - trend_ready - partial}")

    # Save JSON report
    report = {
        "schema_version": "macro_history_report_v1",
        "generated_at": now,
        "db_path": str(db_path),
        "indicator_count": len(summary_rows),
        "trend_ready_count": trend_ready,
        "partial_history_count": partial,
        "collection_results": results,
        "summary": summary_rows,
    }
    out_dir = ROOT / "outputs" / "macro"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "macro_history_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已保存: {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
