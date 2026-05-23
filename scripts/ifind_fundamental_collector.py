#!/usr/bin/env python3
"""iFind Fundamental Collector — L1 取证 + L2 派生。

三阶段中的 Phase 2：
  L1 确定性证据层：THS_BD / THS_DS / THS_EDB / THS_ReportQuery → DuckDB
  L2 派生比较层：Python 纯计算行业分位/排名/趋势（不调 LLM）

用法：
  python3 scripts/ifind_fundamental_collector.py --date 2026-05-21
  python3 scripts/ifind_fundamental_collector.py --date 2026-05-21 --universe p116_pattern_cross

环境变量：
  IFIND_REFRESH_TOKEN    — iFind Quant API 认证
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
IFIND_API_BASE = "https://quantapi.51ifind.com/api/v1"
EVIDENCE_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"


def ymd(d: str) -> str:
    return d.replace("-", "")


# ═══════════════════════════════════════════════════════════
#  iFind HTTP Auth
# ═══════════════════════════════════════════════════════════

def get_access_token() -> str:
    refresh_token = os.environ.get("IFIND_REFRESH_TOKEN")
    if not refresh_token:
        raise RuntimeError("IFIND_REFRESH_TOKEN environment variable not set")
    url = f"{IFIND_API_BASE}/get_access_token"
    req = urllib.request.Request(
        url,
        data=b"",
        headers={"Content-Type": "application/json", "refresh_token": refresh_token},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read().decode())
    token = result.get("data", {}).get("access_token") or result.get("access_token")
    if not token:
        raise RuntimeError(f"Failed to get access_token: {result}")
    return token


def _to_ths_code(stock_code: str) -> str:
    code = stock_code.split(".")[0]
    suffix = stock_code.split(".")[-1].upper() if "." in stock_code else "SZ"
    return f"{code}.{suffix}"


# ═══════════════════════════════════════════════════════════
#  iFind API — 六大核心接口
# ═══════════════════════════════════════════════════════════

def _post(endpoint: str, payload: dict, access_token: str, timeout: int = 30) -> dict:
    url = f"{IFIND_API_BASE}/{endpoint}"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "access_token": access_token, "ifindlang": "cn"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def api_basic_data(ths_code: str, indicators: str, access_token: str) -> dict | None:
    """THS_BD: 基础资料 / 财务指标"""
    try:
        indipara = [{"indicator": item.strip()} for item in indicators.split(",") if item.strip()]
        return _post("basic_data_service", {"codes": ths_code, "indipara": indipara}, access_token)
    except Exception as e:
        print(f"  [warn] THS_BD {ths_code}: {e}", file=sys.stderr)
        return None


def api_data_series(ths_code: str, indicators: str, start_date: str, end_date: str, access_token: str) -> dict | None:
    """THS_DS: 历史序列数据（按时间维度取历史基本面/技术指标）"""
    try:
        indipara = [{"indicator": item.strip()} for item in indicators.split(",") if item.strip()]
        return _post("date_sequence", {
            "codes": ths_code,
            "startdate": start_date.replace("-", ""),
            "enddate": end_date.replace("-", ""),
            "functionpara": {"Interval": "Q", "Fill": "Blank"},
            "indipara": indipara,
        }, access_token, timeout=60)
    except Exception as e:
        print(f"  [warn] THS_DS {ths_code}: {e}", file=sys.stderr)
        return None


def api_edb(indicator_codes: list[str], access_token: str) -> dict | None:
    """THS_EDB: 宏观/行业经济数据"""
    try:
        return _post("edb_service", {
            "indicators": ",".join(indicator_codes),
            "startdate": "20250101",
            "enddate": datetime.now().strftime("%Y%m%d"),
        }, access_token, timeout=60)
    except Exception as e:
        print(f"  [warn] THS_EDB: {e}", file=sys.stderr)
        return None


def api_report_query(ths_code: str, keyword: str, access_token: str) -> dict | None:
    """THS_ReportQuery: 公告查询"""
    try:
        return _post("report_query", {
            "codes": ths_code,
            "functionpara": {"keyword": keyword},
            "beginrDate": "2023-01-01",
            "endrDate": datetime.now().strftime("%Y-%m-%d"),
            "outputpara": "reportDate:Y,thscode:Y,secName:Y,ctime:Y,reportTitle:Y,pdfURL:Y,seq:Y",
        }, access_token, timeout=30)
    except Exception as e:
        print(f"  [warn] ReportQuery {ths_code}: {e}", file=sys.stderr)
        return None


def api_smart_picking(query: str, access_token: str) -> dict | None:
    """THS_WCQuery: 问财语义选股"""
    try:
        return _post("smart_stock_picking", {"searchstring": query, "searchtype": "stock"}, access_token, timeout=30)
    except Exception as e:
        print(f"  [warn] WCQuery: {e}", file=sys.stderr)
        return None


# ═══════════════════════════════════════════════════════════
#  iFind 指标码映射 — 基本面质量 + 产业链地位 + 发展周期
# ═══════════════════════════════════════════════════════════

# L1 基本面指标 (THS_BD)
BASIC_FINANCIAL_INDICATORS = "ths_roe_ttm,ths_gross_profit_margin_ttm,ths_net_profit_margin_ttm,ths_revenue_yoy,ths_net_profit_yoy,ths_operating_cash_flow_ttm,ths_debt_to_asset_ratio,ths_pe_ttm,ths_pb,ths_ps_ttm"

# L1 基本面历史序列 (THS_DS)
SERIES_INDICATORS = "ths_revenue_yoy,ths_net_profit_yoy,ths_gross_profit_margin_ttm,ths_roe_ttm,ths_operating_cash_flow_ttm,ths_capital_expenditure,ths_inventory,ths_account_receivable"

# L1 基本资料 (THS_BD)
BASIC_PROFILE_INDICATORS = "ths_stock_short_name,ths_sw_l1_industry_name,ths_sw_l2_industry_name,ths_sw_l3_industry_name,ths_main_business,ths_total_market_cap,ths_total_share,ths_rd_expense_ratio"

# L1 公告类型 (THS_ReportQuery)
REPORT_KEYWORDS = {
    "private_placement": "定增",
    "merger_acquisition": "并购",
    "performance_forecast": "业绩预告",
}

# L1 宏观指标 (THS_EDB) — 按需选取
MACRO_INDICATORS = [
    "M0043257",  # GDP:累计同比
    "M1001666",  # PMI
    "M0017135",  # 1年期LPR
]


def result_ok(result: dict | None) -> bool:
    return bool(result) and int(result.get("errorcode", -1) or 0) == 0 and int(result.get("dataVol", 0) or 0) > 0


def extract_latest_table_values(result: dict | None) -> dict[str, Any]:
    if not result_ok(result):
        return {}
    tables = result.get("tables") or []
    if not tables:
        return {}
    table = tables[0].get("table") or {}
    out: dict[str, Any] = {}
    for key, values in table.items():
        if isinstance(values, list):
            out[key] = next((v for v in values if v is not None), None)
        else:
            out[key] = values
    return out


def summarize_values(title: str, values: dict[str, Any]) -> str:
    available = {k: v for k, v in values.items() if v is not None}
    if not available:
        return f"{title}: iFind returned no non-null fields."
    lines = [f"{title}:"]
    for key, value in available.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def summarize_series(result: dict | None, title: str) -> str:
    if not result_ok(result):
        return f"{title}: iFind returned no usable series data."
    tables = result.get("tables") or []
    if not tables:
        return f"{title}: iFind returned no tables."
    table_obj = tables[0]
    times = table_obj.get("time") or []
    table = table_obj.get("table") or {}
    lines = [f"{title}: latest non-null observations"]
    useful = 0
    for key, values in table.items():
        if not isinstance(values, list):
            continue
        pairs = [(times[i] if i < len(times) else "", v) for i, v in enumerate(values) if v is not None]
        if not pairs:
            continue
        latest = pairs[-3:]
        lines.append(f"- {key}: " + "; ".join(f"{t}={v}" for t, v in latest))
        useful += 1
    if useful == 0:
        lines.append("- no non-null series fields")
    return "\n".join(lines)


def summarize_reports(result: dict | None, keyword: str) -> str:
    if not result_ok(result):
        err = (result or {}).get("errmsg") or "no data"
        return f"公告查询({keyword}): no usable announcements. errmsg={err}"
    tables = result.get("tables") or []
    if not tables:
        return f"公告查询({keyword}): no announcement tables."
    table = tables[0].get("table") or {}
    titles = table.get("reportTitle") or table.get("report_title") or []
    dates = table.get("reportDate") or table.get("report_date") or []
    if not isinstance(titles, list):
        titles = [titles]
    if not isinstance(dates, list):
        dates = [dates]
    lines = [f"公告查询({keyword}): {len(titles)} announcements"]
    for idx, title in enumerate(titles[:5]):
        date = dates[idx] if idx < len(dates) else ""
        lines.append(f"- {date}: {title}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  Universe
# ═══════════════════════════════════════════════════════════

def load_universe(date_str: str, universe: str) -> list[str]:
    assert universe in ("p116_pattern_cross", "ef_pool", "tracking_pool")
    y = ymd(date_str)
    if universe == "tracking_pool":
        if not EVIDENCE_DB.exists():
            raise FileNotFoundError(f"fundamental DB not found: {EVIDENCE_DB}. Run ifind_tracking_pool.py first.")
        con = duckdb.connect(str(EVIDENCE_DB), read_only=True)
        try:
            rows = con.execute(
                "SELECT stock_code FROM ifind_tracking_pool WHERE active ORDER BY priority_tier, stock_code"
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            con.close()
    elif universe == "p116_pattern_cross":
        path = ROOT / "outputs" / "pattern_lifecycle" / f"pattern_cross_ef_{y}.json"
        if not path.exists():
            raise FileNotFoundError(f"pattern_cross_ef not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        codes = [r["stock_code"] for r in data.get("ef_with_structure", [])]
        return sorted(set(codes))
    else:
        path = ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_{y}.json"
        if not path.exists():
            raise FileNotFoundError(f"all_three_ef not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        codes = [r.get("symbol") or r.get("stock_code") for r in data.get("rows", []) if r.get("ef_count", 0) >= 2]
        return sorted(set(codes))


# ═══════════════════════════════════════════════════════════
#  L1: 确定性证据 — iFind 原始数据写入 DuckDB
# ═══════════════════════════════════════════════════════════

def collect_l1_basic_profile(con, stock_codes, access_token, collected_at, date_str):
    count = 0
    for code in stock_codes:
        ths_code = _to_ths_code(code)
        result = api_basic_data(ths_code, BASIC_PROFILE_INDICATORS, access_token)
        values = extract_latest_table_values(result)
        if not values:
            continue
        con.execute("""
            INSERT OR REPLACE INTO fundamental_evidence_packet
            (evidence_id, stock_code, as_of_date, evidence_type, evidence_text,
             source_vendor, source_api, source_query, confidence, collected_at)
            VALUES (?, ?, ?, 'basic_profile', ?, 'iFind', 'THS_BD', ?, 0.95, ?)
        """, (f"profile_{code}_{ymd(date_str)}", code, date_str,
              summarize_values("iFind basic profile", values)[:4000],
              BASIC_PROFILE_INDICATORS, collected_at))
        count += 1
    return count


def collect_l1_financials(con, stock_codes, access_token, collected_at, date_str):
    fin_count = 0
    ev_count = 0
    for code in stock_codes:
        ths_code = _to_ths_code(code)
        result = api_basic_data(ths_code, BASIC_FINANCIAL_INDICATORS, access_token)
        values = extract_latest_table_values(result)
        if not values:
            ev_id = f"no_fin_{code}_{ymd(date_str)}"
            con.execute("""
                INSERT OR REPLACE INTO fundamental_evidence_packet
                (evidence_id, stock_code, as_of_date, evidence_type, evidence_text,
                 source_vendor, source_api, source_query, confidence, collected_at, unavailable)
                VALUES (?, ?, ?, 'financials', 'iFind returned no data', 'iFind', 'THS_BD', ?, 0, ?, TRUE)
            """, (ev_id, code, date_str, BASIC_FINANCIAL_INDICATORS, collected_at))
            ev_count += 1
            continue
        ev_id = f"fin_{code}_{ymd(date_str)}"
        con.execute("""
            INSERT OR REPLACE INTO fundamental_evidence_packet
            (evidence_id, stock_code, as_of_date, evidence_type, evidence_text,
             source_vendor, source_api, source_query, confidence, collected_at)
            VALUES (?, ?, ?, 'financials', ?, 'iFind', 'THS_BD', ?, 0.90, ?)
        """, (ev_id, code, date_str, summarize_values("iFind latest financial metrics", values)[:4000],
              BASIC_FINANCIAL_INDICATORS, collected_at))
        ev_count += 1
        try:
            con.execute("""
                INSERT OR REPLACE INTO ifind_financial_metrics
                (stock_code, report_period, report_type, pe_ttm, pb, roe, gross_margin,
                 revenue_yoy, net_profit_yoy, operating_cashflow, debt_ratio,
                 source_vendor, source_api, source_query, collected_at)
                VALUES (?, 'latest', 'TTM', ?, ?, ?, ?, ?, ?, ?, ?, 'iFind', 'THS_BD', ?, ?)
            """, (code,
                  values.get("ths_pe_ttm"), values.get("ths_pb"),
                  values.get("ths_roe_ttm"), values.get("ths_gross_profit_margin_ttm"),
                  values.get("ths_revenue_yoy"), values.get("ths_net_profit_yoy"),
                  values.get("ths_operating_cash_flow_ttm"), values.get("ths_debt_to_asset_ratio"),
                  BASIC_FINANCIAL_INDICATORS, collected_at))
            fin_count += 1
        except Exception:
            pass
    return fin_count, ev_count


def collect_l1_financial_series(con, stock_codes, access_token, collected_at, date_str):
    count = 0
    for code in stock_codes:
        ths_code = _to_ths_code(code)
        result = api_data_series(ths_code, SERIES_INDICATORS, "2023-01-01", date_str, access_token)
        if not result_ok(result):
            continue
        con.execute("""
            INSERT OR REPLACE INTO fundamental_evidence_packet
            (evidence_id, stock_code, as_of_date, evidence_type, evidence_text,
             source_vendor, source_api, source_query, confidence, collected_at)
            VALUES (?, ?, ?, 'financial_series', ?, 'iFind', 'THS_DS', ?, 0.90, ?)
        """, (f"series_{code}_{ymd(date_str)}", code, date_str,
              summarize_series(result, "iFind financial series")[:4000],
              SERIES_INDICATORS, collected_at))
        count += 1
    return count


def collect_l1_capital_events(con, stock_codes, access_token, collected_at, date_str):
    count = 0
    for code in stock_codes:
        ths_code = _to_ths_code(code)
        for rtype, keyword in REPORT_KEYWORDS.items():
            result = api_report_query(ths_code, keyword, access_token)
            data = result.get("data", result)
            con.execute("""
                INSERT OR REPLACE INTO fundamental_evidence_packet
                (evidence_id, stock_code, as_of_date, evidence_type, evidence_text,
                 source_vendor, source_api, source_query, confidence, collected_at)
                VALUES (?, ?, ?, ?, ?, 'iFind', 'THS_ReportQuery', ?, 0.85, ?)
            """, (f"report_{code}_{rtype}_{ymd(date_str)}", code, date_str, f"capital_{rtype}",
                  summarize_reports(result, keyword)[:4000],
                  keyword, collected_at))
            if result_ok(result):
                count += 1
    return count


def collect_l1_macro(con, access_token, collected_at, date_str):
    result = api_edb(MACRO_INDICATORS, access_token)
    if not result:
        return 0
    data = result.get("data", result)
    count = 0
    if isinstance(data, list):
        for item in data:
            code = item.get("indicator_code") or item.get("code") or "unknown"
            val = item.get("value")
            con.execute("""
                INSERT OR REPLACE INTO ifind_macro_indicators
                (indicator_code, as_of_date, indicator_name, value, unit, frequency,
                 source_query, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (str(code), date_str, item.get("indicator_name", ""), val,
                  item.get("unit", ""), item.get("frequency", ""),
                  json.dumps(MACRO_INDICATORS), collected_at))
            count += 1
    return count


# ═══════════════════════════════════════════════════════════
#  L2: 派生比较层 — Python 纯计算（不调 LLM）
# ═══════════════════════════════════════════════════════════

def compute_l2_derived(con, stock_codes: list[str], date_str: str, collected_at: str) -> int:
    all_metrics = con.execute("""
        SELECT stock_code, gross_margin, roe, revenue_yoy, operating_cashflow, debt_ratio
        FROM ifind_financial_metrics
        WHERE report_period = 'latest'
    """).fetchall()

    if not all_metrics:
        return 0

    values_by_field: dict[str, list[float]] = {
        "gross_margin": [], "roe": [], "debt_ratio": [],
    }
    stock_metrics: dict[str, dict] = {}
    for code, gm, roe, rev, cf, debt in all_metrics:
        stock_metrics[code] = {"gm": gm, "roe": roe, "rev_growth": rev, "cf": cf, "debt": debt}
        if gm is not None:
            values_by_field["gross_margin"].append(float(gm))
        if roe is not None:
            values_by_field["roe"].append(float(roe))
        if debt is not None:
            values_by_field["debt_ratio"].append(float(debt))

    for key in values_by_field:
        values_by_field[key].sort()

    def percentile(v: float | None, key: str) -> float | None:
        arr = values_by_field.get(key, [])
        if v is None or not arr:
            return None
        n = sum(1 for x in arr if x <= v)
        return round(n / len(arr), 4) if arr else None

    count = 0
    for code in stock_codes:
        sm = stock_metrics.get(code, {})
        gm_pct = percentile(sm.get("gm"), "gross_margin")
        roe_pct = percentile(sm.get("roe"), "roe")

        con.execute("""
            INSERT OR REPLACE INTO ifind_derived_metrics
            (stock_code, as_of_date, gross_margin_rank_pct, roe_rank_pct,
             debt_ratio, peer_count, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (code, date_str, gm_pct, roe_pct, sm.get("debt"),
              len(stock_metrics), collected_at))
        count += 1

    return count


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════

def _count_evidence_for_codes(con, stock_codes: list[str], date_str: str) -> int:
    placeholders = ",".join(["?"] * len(stock_codes))
    if not placeholders:
        return 0
    return con.execute(
        f"""
        SELECT COUNT(*)
        FROM fundamental_evidence_packet
        WHERE as_of_date = ? AND stock_code IN ({placeholders})
        """,
        [date_str, *stock_codes],
    ).fetchone()[0]


def collect(
    date_str: str,
    universe: str,
    limit: int = 0,
    allow_missing_token: bool = False,
    refresh: bool = False,
) -> dict:
    collected_at = datetime.now(timezone.utc).isoformat()
    stock_codes = load_universe(date_str, universe)
    if limit and limit > 0:
        stock_codes = stock_codes[:limit]
    print(f"Universe: {len(stock_codes)} stocks ({universe})")

    # Schema
    db_path = EVIDENCE_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    import importlib.util
    spec = importlib.util.spec_from_file_location("fundamental_evidence_schema",
        str(ROOT / "scripts" / "fundamental_evidence_schema.py"))
    schema_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(schema_mod)
    schema_mod.init_schema(db_path)

    con = duckdb.connect(str(db_path))

    collection_codes = stock_codes
    cached_codes: list[str] = []
    if not refresh and stock_codes:
        placeholders = ",".join(["?"] * len(stock_codes))
        cached_rows = con.execute(
            f"""
            SELECT stock_code, COUNT(*) AS evidence_count
            FROM fundamental_evidence_packet
            WHERE as_of_date = ? AND stock_code IN ({placeholders})
            GROUP BY stock_code
            """,
            [date_str, *stock_codes],
        ).fetchall()
        cached_counts = {r[0]: int(r[1] or 0) for r in cached_rows}
        cached_codes = [code for code in stock_codes if cached_counts.get(code, 0) >= 4]
        collection_codes = [code for code in stock_codes if code not in set(cached_codes)]

    if cached_codes:
        print(f"Cache hit: {len(cached_codes)} stocks already have same-day evidence")
    if not collection_codes:
        total_ev = _count_evidence_for_codes(con, stock_codes, date_str)
        con.close()
        return {
            "schema_version": "fundamental_evidence_v1",
            "date": date_str,
            "universe": universe,
            "stocks": len(stock_codes),
            "cached_stocks": len(cached_codes),
            "downloaded_stocks": 0,
            "total_evidence_packets": total_ev,
            "research_only": True,
        }

    for code in collection_codes:
        con.execute(
            "DELETE FROM fundamental_evidence_packet WHERE stock_code = ? AND as_of_date = ?",
            (code, date_str),
        )
        con.execute(
            "DELETE FROM ifind_financial_metrics WHERE stock_code = ? AND report_period = 'latest'",
            (code,),
        )
        con.execute(
            "DELETE FROM ifind_derived_metrics WHERE stock_code = ? AND as_of_date = ?",
            (code, date_str),
        )
        con.execute(
            "DELETE FROM fundamental_profile WHERE stock_code = ? AND as_of_date = ?",
            (code, date_str),
        )
        con.execute(
            "DELETE FROM fundamental_review_queue WHERE stock_code = ? AND as_of_date = ?",
            (code, date_str),
        )

    try:
        access_token = get_access_token()
    except RuntimeError as exc:
        if not allow_missing_token:
            con.close()
            raise
        print(f"[dry-smoke] {exc}. Writing unavailable evidence placeholders.", file=sys.stderr)
        for code in collection_codes:
            con.execute("""
                INSERT OR REPLACE INTO fundamental_evidence_packet
                (evidence_id, stock_code, as_of_date, evidence_type, evidence_text,
                 source_vendor, source_api, source_query, confidence, collected_at, unavailable)
                VALUES (?, ?, ?, 'ifind_auth', ?, 'iFind', 'auth', 'IFIND_REFRESH_TOKEN', 0, ?, TRUE)
            """, (
                f"ifind_auth_unavailable_{code}_{ymd(date_str)}",
                code,
                date_str,
                "IFIND_REFRESH_TOKEN is not set; collector smoke verified only schema and universe loading.",
                collected_at,
            ))
        total_ev = _count_evidence_for_codes(con, stock_codes, date_str)
        con.close()
        return {
            "schema_version": "fundamental_evidence_v1",
            "date": date_str,
            "universe": universe,
            "stocks": len(stock_codes),
            "cached_stocks": len(cached_codes),
            "downloaded_stocks": 0,
            "auth_available": False,
            "dry_smoke": True,
            "total_evidence_packets": total_ev,
            "research_only": True,
        }
    print(f"iFind authenticated (token len={len(access_token)})")

    # ── L1: 确定性证据 ──
    print(f"[L1] basic_profile: {stock_codes[0] if stock_codes else 'N/A'} ...")
    profile_count = collect_l1_basic_profile(con, collection_codes, access_token, collected_at, date_str)

    print(f"[L1] financials ...")
    fin_count, fin_ev = collect_l1_financials(con, collection_codes, access_token, collected_at, date_str)

    print(f"[L1] financial_series ...")
    series_count = collect_l1_financial_series(con, collection_codes, access_token, collected_at, date_str)

    print(f"[L1] capital_events ...")
    capital_count = collect_l1_capital_events(con, collection_codes, access_token, collected_at, date_str)

    print(f"[L1] macro ...")
    macro_count = collect_l1_macro(con, access_token, collected_at, date_str)

    # ── L2: 派生比较 ──
    print(f"[L2] derived metrics (peer percentile) ...")
    derived_count = compute_l2_derived(con, stock_codes, date_str, collected_at)

    # ── 统计 ──
    total_ev = _count_evidence_for_codes(con, stock_codes, date_str)

    con.close()

    return {
        "schema_version": "fundamental_evidence_v1",
        "date": date_str,
        "universe": universe,
        "stocks": len(stock_codes),
        "cached_stocks": len(cached_codes),
        "downloaded_stocks": len(collection_codes),
        "l1_profile": profile_count,
        "l1_financial_rows": fin_count,
        "l1_financial_evidence": fin_ev,
        "l1_series": series_count,
        "l1_capital_events": capital_count,
        "l1_macro": macro_count,
        "l2_derived": derived_count,
        "total_evidence_packets": total_ev,
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="iFind Fundamental Collector (L1+L2)")
    parser.add_argument("--date", required=True)
    parser.add_argument("--universe", default="p116_pattern_cross",
                        choices=["p116_pattern_cross", "ef_pool", "tracking_pool"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--allow-missing-token", action="store_true", help="Write unavailable evidence placeholders when IFIND_REFRESH_TOKEN is absent.")
    parser.add_argument("--refresh", action="store_true", help="Force same-day iFind re-collection instead of using cached evidence.")
    args = parser.parse_args()

    result = collect(args.date, args.universe, args.limit, args.allow_missing_token, args.refresh)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
