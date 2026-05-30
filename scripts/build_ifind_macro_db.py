#!/usr/bin/env python3
"""Build iFinD macro indicator evidence and daily snapshot."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fundamental_evidence_schema import init_schema  # noqa: E402
from import_ifind_excel_facts import read_xlsx  # noqa: E402
from ifind_fundamental_collector import _post, get_access_token  # noqa: E402

DEFAULT_CONFIG = ROOT / "config" / "ifind_macro_indicators.json"
DEFAULT_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
DEFAULT_MULTI_SOURCE_CONFIG = ROOT / "config" / "macro_data_sources.json"


@dataclass(frozen=True)
class Indicator:
    code: str | None
    name: str
    category: str
    frequency: str
    unit: str
    use: str
    status: str


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def norm_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.split("T", 1)[0].replace("/", "-").replace(".", "-")
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if re.fullmatch(r"\d{6}", text):
        return f"{text[:4]}-{text[4:6]}-01"
    quarter = re.fullmatch(r"(\d{4})Q([1-4])", text, flags=re.IGNORECASE)
    if quarter:
        month_day = {"1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31"}[quarter.group(2)]
        return f"{quarter.group(1)}-{month_day}"
    if re.fullmatch(r"\d{4}-\d{1,2}$", text):
        year, month = text.split("-")
        return f"{int(year):04d}-{int(month):02d}-01"
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text):
        year, month, day = text.split("-")[:3]
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return text


def date_key(value: str | None) -> date | None:
    normalized = norm_date(value)
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"--", "-", "NA", "N/A", "nan", "None"}:
        return None
    text = text.replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def load_config(path: Path) -> tuple[dict[str, Any], list[Indicator]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_indicators = list(payload.get("indicators", []) or [])
    seen_codes = {str(item.get("code")) for item in raw_indicators if item.get("code")}
    if DEFAULT_MULTI_SOURCE_CONFIG.exists():
        external = json.loads(DEFAULT_MULTI_SOURCE_CONFIG.read_text(encoding="utf-8"))
        for raw in external.get("macro_indicators", []) or []:
            code = raw.get("code")
            if code and str(code) in seen_codes:
                continue
            merged = dict(raw)
            merged.setdefault("status", "external_active")
            merged.setdefault("source", str(DEFAULT_MULTI_SOURCE_CONFIG.relative_to(ROOT)))
            raw_indicators.append(merged)
            if code:
                seen_codes.add(str(code))
        payload["_merged_indicator_raws"] = raw_indicators
        payload["external_indicator_config"] = str(DEFAULT_MULTI_SOURCE_CONFIG)
    else:
        payload["_merged_indicator_raws"] = raw_indicators
    indicators: list[Indicator] = []
    for raw in raw_indicators:
        indicators.append(
            Indicator(
                code=raw.get("code"),
                name=str(raw.get("name") or raw.get("code") or ""),
                category=str(raw.get("category") or "unknown"),
                frequency=str(raw.get("frequency") or ""),
                unit=str(raw.get("unit") or ""),
                use=str(raw.get("use") or ""),
                status=str(raw.get("status") or "needs_ifind_code"),
            )
        )
    return payload, indicators


def get_first(mapping: dict[str, Any], keys: list[str]) -> Any:
    lower_map = {str(k).lower(): v for k, v in mapping.items()}
    for key in keys:
        if key in mapping:
            return mapping[key]
        if key.lower() in lower_map:
            return lower_map[key.lower()]
    return None


def normalize_header(value: Any) -> str:
    return re.sub(r"[\s_:\-\[\]（）()]+", "", str(value or "").strip().lower())


def gui_indicator_code(name: str) -> str:
    return f"GUI:{str(name or '').strip()}"


def read_table_file(path: Path) -> list[list[Any]]:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return read_xlsx(path)
    if suffix in {".csv", ".txt", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return [row for row in csv.reader(f, delimiter=delimiter)]
    raise ValueError(f"unsupported macro import file type: {path.suffix}")


def find_column(headers: list[Any], aliases: list[str]) -> int | None:
    normalized = [normalize_header(item) for item in headers]
    alias_set = {normalize_header(item) for item in aliases}
    for idx, header in enumerate(normalized):
        if header in alias_set:
            return idx
    for idx, header in enumerate(normalized):
        if any(alias and alias in header for alias in alias_set):
            return idx
    return None


def parse_gui_import_rows(path: Path, indicators: list[Indicator], fallback_date: str) -> list[dict[str, Any]]:
    rows = read_table_file(path)
    if not rows:
        return []
    code_aliases = ["indicator_code", "indicator", "code", "edb_code", "ths_code", "指标代码", "指标编码", "指标id", "代码"]
    name_aliases = ["indicator_name", "name", "指标名称", "名称", "指标"]
    date_aliases = ["as_of_date", "date", "time", "datetime", "日期", "时间", "数据日期", "报告期", "统计日期"]
    value_aliases = ["value", "data", "指标值", "数值", "最新值", "收盘价", "VALUE"]
    unit_aliases = ["unit", "单位"]
    frequency_aliases = ["frequency", "freq", "频率"]

    header_index: int | None = None
    mapping: dict[str, int | None] = {}
    for idx, row in enumerate(rows[:30]):
        current = {
            "code": find_column(row, code_aliases),
            "name": find_column(row, name_aliases),
            "date": find_column(row, date_aliases),
            "value": find_column(row, value_aliases),
            "unit": find_column(row, unit_aliases),
            "frequency": find_column(row, frequency_aliases),
        }
        if current["value"] is not None and (current["code"] is not None or current["name"] is not None):
            header_index = idx
            mapping = current
            break
    if header_index is None:
        raise ValueError(f"cannot identify macro import header in {path}")

    known_by_code = {item.code: item for item in indicators if item.code}
    known_by_name = {item.name: item for item in indicators}
    parsed: list[dict[str, Any]] = []
    for row in rows[header_index + 1 :]:
        if not any(cell not in (None, "") for cell in row):
            continue
        code = None
        name = None
        if mapping["code"] is not None and mapping["code"] < len(row):
            raw_code = str(row[mapping["code"]] or "").strip()
            code = raw_code or None
        if mapping["name"] is not None and mapping["name"] < len(row):
            raw_name = str(row[mapping["name"]] or "").strip()
            name = raw_name or None
        indicator = known_by_code.get(code) if code else None
        if not indicator and name:
            indicator = known_by_name.get(name)
        if not code and indicator:
            code = indicator.code or gui_indicator_code(indicator.name)
        if not code and name:
            code = gui_indicator_code(name)
        if not code:
            continue
        value = None
        if mapping["value"] is not None and mapping["value"] < len(row):
            value = to_float(row[mapping["value"]])
        if value is None:
            continue
        obs_date = fallback_date
        if mapping["date"] is not None and mapping["date"] < len(row):
            obs_date = norm_date(row[mapping["date"]]) or fallback_date
        unit = indicator.unit if indicator else ""
        if mapping["unit"] is not None and mapping["unit"] < len(row):
            unit = str(row[mapping["unit"]] or unit)
        frequency = indicator.frequency if indicator else ""
        if mapping["frequency"] is not None and mapping["frequency"] < len(row):
            frequency = str(row[mapping["frequency"]] or frequency)
        parsed.append(
            {
                "indicator_code": code,
                "as_of_date": obs_date,
                "indicator_name": name or (indicator.name if indicator else code),
                "value": value,
                "unit": unit,
                "frequency": frequency,
            }
        )
    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in parsed:
        dedup[(row["indicator_code"], row["as_of_date"])] = row
    return sorted(dedup.values(), key=lambda item: (item["indicator_code"], item["as_of_date"]))


def extract_record_rows(
    records: list[dict[str, Any]],
    active_by_code: dict[str, Indicator],
    fallback_date: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in records:
        code = get_first(item, ["indicator_code", "indicator", "code", "edb_code", "ths_code", "thscode"])
        if code is None:
            continue
        code = str(code)
        indicator = active_by_code.get(code)
        if not indicator:
            continue
        obs_date = norm_date(get_first(item, ["as_of_date", "date", "time", "datetime", "report_date", "period"])) or fallback_date
        value = to_float(get_first(item, ["value", "data", "close", "指标值", "VALUE"]))
        if value is None:
            continue
        rows.append(
            {
                "indicator_code": code,
                "as_of_date": obs_date,
                "indicator_name": str(get_first(item, ["indicator_name", "name", "指标名称"]) or indicator.name),
                "value": value,
                "unit": str(get_first(item, ["unit", "单位"]) or indicator.unit),
                "frequency": str(get_first(item, ["frequency", "freq", "频率"]) or indicator.frequency),
            }
        )
    return rows


def extract_table_rows(
    result: dict[str, Any],
    active_by_code: dict[str, Indicator],
    fallback_date: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table_obj in result.get("tables") or []:
        if not isinstance(table_obj, dict):
            continue
        times = get_first(table_obj, ["time", "times", "date", "dates"]) or []
        if not isinstance(times, list):
            times = [times]
        table = get_first(table_obj, ["table", "data", "Table"]) or {}
        table_code = get_first(table_obj, ["indicator_code", "indicator", "code", "edb_code", "ths_code", "thscode"])
        if isinstance(table, list) and all(isinstance(item, dict) for item in table):
            rows.extend(extract_record_rows(table, active_by_code, fallback_date))
            continue
        if not isinstance(table, dict):
            continue
        for key, values in table.items():
            code = str(key) if str(key) in active_by_code else (str(table_code) if table_code else str(key))
            indicator = active_by_code.get(code)
            if not indicator:
                continue
            if isinstance(values, list):
                for idx, raw_value in enumerate(values):
                    value = to_float(raw_value)
                    if value is None:
                        continue
                    obs_date = norm_date(times[idx] if idx < len(times) else fallback_date) or fallback_date
                    rows.append(
                        {
                            "indicator_code": code,
                            "as_of_date": obs_date,
                            "indicator_name": indicator.name,
                            "value": value,
                            "unit": indicator.unit,
                            "frequency": indicator.frequency,
                        }
                    )
            else:
                value = to_float(values)
                if value is None:
                    continue
                rows.append(
                    {
                        "indicator_code": code,
                        "as_of_date": norm_date(times[-1] if times else fallback_date) or fallback_date,
                        "indicator_name": indicator.name,
                        "value": value,
                        "unit": indicator.unit,
                        "frequency": indicator.frequency,
                    }
                )
    return rows


def extract_edb_rows(result: dict[str, Any] | None, indicators: list[Indicator], fallback_date: str) -> list[dict[str, Any]]:
    if not result:
        return []
    active_by_code = {item.code: item for item in indicators if item.code and item.status == "active"}
    rows: list[dict[str, Any]] = []
    data = result.get("data")
    if isinstance(data, list) and all(isinstance(item, dict) for item in data):
        rows.extend(extract_record_rows(data, active_by_code, fallback_date))
    rows.extend(extract_table_rows(result, active_by_code, fallback_date))
    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        dedup[(row["indicator_code"], row["as_of_date"])] = row
    return sorted(dedup.values(), key=lambda item: (item["indicator_code"], item["as_of_date"]))


def download_edb(codes: list[str], start_date: str, end_date: str, access_token: str) -> dict[str, Any] | None:
    return _post(
        "edb_service",
        {
            "indicators": ",".join(codes),
            "startdate": ymd(start_date),
            "enddate": ymd(end_date),
        },
        access_token,
        timeout=60,
    )


def insert_rows(db_path: Path, rows: list[dict[str, Any]], source_query: dict[str, Any], collected_at: str) -> int:
    if not rows:
        return 0
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_schema(db_path)
    con = duckdb.connect(str(db_path))
    try:
        for row in rows:
            con.execute(
                """
                INSERT OR REPLACE INTO ifind_macro_indicators
                (indicator_code, as_of_date, indicator_name, value, unit, frequency, source_query, source_api, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'THS_EDB', ?)
                """,
                (
                    row["indicator_code"],
                    row["as_of_date"],
                    row.get("indicator_name", ""),
                    row.get("value"),
                    row.get("unit", ""),
                    row.get("frequency", ""),
                    json.dumps(source_query, ensure_ascii=False),
                    collected_at,
                ),
            )
    finally:
        con.close()
    return len(rows)


def read_history(con: duckdb.DuckDBPyConnection, code: str, cutoff: str) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT indicator_code, as_of_date, indicator_name, value, unit, frequency, source_query, collected_at
        FROM ifind_macro_indicators
        WHERE indicator_code = ?
        """,
        [code],
    ).fetchall()
    cutoff_key = date_key(cutoff)
    history: list[dict[str, Any]] = []
    for row in rows:
        obs_key = date_key(row[1])
        if cutoff_key and obs_key and obs_key > cutoff_key:
            continue
        history.append(
            {
                "indicator_code": row[0],
                "as_of_date": norm_date(row[1]) or row[1],
                "indicator_name": row[2],
                "value": row[3],
                "unit": row[4],
                "frequency": row[5],
                "source_query": row[6],
                "collected_at": row[7],
                "_date_key": obs_key,
            }
        )
    return sorted(history, key=lambda item: (item["_date_key"] or date.min, item["as_of_date"]))


def percentile_rank(values: list[float], latest: float | None) -> float | None:
    if latest is None or not values:
        return None
    less_equal = sum(1 for value in values if value <= latest)
    return round(less_equal * 100.0 / len(values), 2)


def trend_label(latest: float | None, previous: float | None) -> str:
    if latest is None or previous is None:
        return "data_insufficient"
    change = latest - previous
    threshold = max(abs(previous) * 0.001, 0.0001)
    if abs(change) <= threshold:
        return "flat"
    return "up" if change > 0 else "down"


def stale_limit_days(frequency: str) -> int:
    text = str(frequency or "").lower()
    if "daily" in text:
        return 10
    if "monthly" in text:
        return 100
    if "quarter" in text:
        return 190
    if "annual" in text:
        return 450
    return 120


def is_stale_observation(latest_date: Any, as_of_date: str, frequency: str) -> bool:
    latest_key = date_key(str(latest_date) if latest_date is not None else None)
    cutoff_key = date_key(as_of_date)
    if not latest_key or not cutoff_key:
        return False
    if latest_key > cutoff_key:
        return False
    return (cutoff_key - latest_key).days > stale_limit_days(frequency)


def build_indicator_snapshot(con: duckdb.DuckDBPyConnection, indicators: list[Indicator], as_of_date: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for indicator in indicators:
        if indicator.status not in {"active", "external_active"} or not indicator.code:
            gui_code = gui_indicator_code(indicator.name)
            history = read_history(con, gui_code, as_of_date)
            if history:
                values = [float(item["value"]) for item in history if item.get("value") is not None]
                latest = history[-1]
                previous = history[-2] if len(history) >= 2 else None
                latest_value = float(latest["value"]) if latest.get("value") is not None else None
                previous_value = float(previous["value"]) if previous and previous.get("value") is not None else None
                change = round(latest_value - previous_value, 6) if latest_value is not None and previous_value is not None else None
                change_pct = round(change * 100.0 / previous_value, 4) if change is not None and previous_value not in (None, 0.0) else None
                observed_frequency = latest.get("frequency") or indicator.frequency
                stale = is_stale_observation(latest.get("as_of_date"), as_of_date, observed_frequency)
                out.append(
                    {
                        "indicator_code": gui_code,
                        "indicator_name": latest.get("indicator_name") or indicator.name,
                        "category": indicator.category,
                        "frequency": observed_frequency,
                        "unit": latest.get("unit") or indicator.unit,
                        "use": indicator.use,
                        "status": "stale_observation" if stale else "gui_imported_needs_ifind_code",
                        "latest_date": latest.get("as_of_date"),
                        "value": latest_value,
                        "previous_value": previous_value,
                        "change": change,
                        "change_pct": change_pct,
                        "trend": trend_label(latest_value, previous_value),
                        "history_count": len(history),
                        "percentile": percentile_rank(values, latest_value),
                    }
                )
                continue
            out.append(
                {
                    "indicator_code": indicator.code,
                    "indicator_name": indicator.name,
                    "category": indicator.category,
                    "frequency": indicator.frequency,
                    "unit": indicator.unit,
                    "use": indicator.use,
                    "status": indicator.status,
                    "latest_date": None,
                    "value": None,
                    "previous_value": None,
                    "change": None,
                    "change_pct": None,
                    "trend": "needs_ifind_code",
                    "history_count": 0,
                    "percentile": None,
                }
            )
            continue
        history = read_history(con, indicator.code, as_of_date)
        values = [float(item["value"]) for item in history if item.get("value") is not None]
        latest = history[-1] if history else None
        previous = history[-2] if len(history) >= 2 else None
        latest_value = float(latest["value"]) if latest and latest.get("value") is not None else None
        previous_value = float(previous["value"]) if previous and previous.get("value") is not None else None
        change = round(latest_value - previous_value, 6) if latest_value is not None and previous_value is not None else None
        change_pct = round(change * 100.0 / previous_value, 4) if change is not None and previous_value not in (None, 0.0) else None
        observed_frequency = latest.get("frequency") if latest and latest.get("frequency") else indicator.frequency
        stale = bool(latest and is_stale_observation(latest.get("as_of_date"), as_of_date, observed_frequency))
        out.append(
            {
                "indicator_code": indicator.code,
                "indicator_name": latest.get("indicator_name") if latest and latest.get("indicator_name") else indicator.name,
                "category": indicator.category,
                "frequency": observed_frequency,
                "unit": latest.get("unit") if latest and latest.get("unit") else indicator.unit,
                "use": indicator.use,
                "status": "stale_observation" if stale else ("ok" if latest else "no_observation"),
                "latest_date": latest.get("as_of_date") if latest else None,
                "value": latest_value,
                "previous_value": previous_value,
                "change": change,
                "change_pct": change_pct,
                "trend": trend_label(latest_value, previous_value),
                "history_count": len(history),
                "percentile": percentile_rank(values, latest_value),
            }
        )
    return out


def macro_regime(indicators: list[dict[str, Any]]) -> dict[str, Any]:
    by_code = {item.get("indicator_code"): item for item in indicators if item.get("indicator_code")}
    pmi = by_code.get("M002043802") or by_code.get("M1001666")
    gdp = by_code.get("M0043257")
    lpr = by_code.get("M0017135")

    if pmi and pmi.get("value") is not None:
        growth = "制造业扩张" if float(pmi["value"]) >= 50 else "制造业收缩"
    else:
        growth = "增长数据不足"
    if gdp and gdp.get("trend") in {"up", "down", "flat"}:
        growth = f"{growth}，GDP累计同比{gdp['trend']}"

    if lpr and lpr.get("trend") == "down":
        liquidity = "贷款利率边际宽松"
    elif lpr and lpr.get("trend") == "up":
        liquidity = "贷款利率边际收紧"
    elif lpr and lpr.get("value") is not None:
        liquidity = "贷款利率基本稳定"
    else:
        liquidity = "流动性数据不足"

    needs_code = [item for item in indicators if item.get("status") == "needs_ifind_code"]
    formula_only = [item for item in indicators if item.get("status") == "formula_catalog_only"]
    legacy_needs_validation = [item for item in indicators if item.get("status") == "legacy_code_needs_validation"]
    active_no_observation = [item for item in indicators if item.get("status") == "no_observation"]
    stale_observation = [item for item in indicators if item.get("status") == "stale_observation"]
    ok_count = sum(1 for item in indicators if item.get("status") == "ok")
    coverage = "partial" if (needs_code or formula_only or legacy_needs_validation or active_no_observation or stale_observation) else "complete"
    one_sentence = f"{coverage}覆盖：{growth}；{liquidity}。"
    gaps: list[str] = []
    if active_no_observation:
        gaps.append(f"{len(active_no_observation)}个active指标暂无观测值")
    if stale_observation:
        gaps.append(f"{len(stale_observation)}个指标观测值已过期")
    if formula_only:
        gaps.append(f"{len(formula_only)}个GUI公式指标等待数值导出或直连码")
    if legacy_needs_validation:
        gaps.append(f"{len(legacy_needs_validation)}个旧指标码待验证")
    if needs_code:
        gaps.append(f"{len(needs_code)}个指标等待iFinD指标码")
    if gaps:
        one_sentence += " " + "，".join(gaps) + "；不能做完整首席级宏观定性。"
    return {
        "coverage_status": coverage,
        "one_sentence": one_sentence,
        "growth_regime": growth,
        "liquidity_regime": liquidity,
        "active_ok_count": ok_count,
        "needs_code_count": len(needs_code),
        "formula_catalog_only_count": len(formula_only),
        "legacy_code_needs_validation_count": len(legacy_needs_validation),
        "active_no_observation_count": len(active_no_observation),
        "stale_observation_count": len(stale_observation),
        "needs_code_by_category": dict(Counter(str(item.get("category") or "unknown") for item in needs_code)),
        "formula_catalog_only_by_category": dict(Counter(str(item.get("category") or "unknown") for item in formula_only)),
    }


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "indicator_code",
        "indicator_name",
        "category",
        "frequency",
        "unit",
        "status",
        "latest_date",
        "value",
        "previous_value",
        "change",
        "change_pct",
        "trend",
        "percentile",
        "history_count",
        "use",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_html(snapshot: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = snapshot["indicators"]
    row_html = []
    for item in rows:
        row_html.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('indicator_code') or ''))}</td>"
            f"<td>{html.escape(str(item.get('indicator_name') or ''))}</td>"
            f"<td>{html.escape(str(item.get('category') or ''))}</td>"
            f"<td>{html.escape(str(item.get('frequency') or ''))}</td>"
            f"<td>{html.escape(str(item.get('status') or ''))}</td>"
            f"<td>{html.escape(str(item.get('latest_date') or ''))}</td>"
            f"<td>{html.escape(str(item.get('value') if item.get('value') is not None else ''))}</td>"
            f"<td>{html.escape(str(item.get('trend') or ''))}</td>"
            f"<td>{html.escape(str(item.get('percentile') if item.get('percentile') is not None else ''))}</td>"
            f"<td>{html.escape(str(item.get('use') or ''))}</td>"
            "</tr>"
        )
    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>iFinD Macro Snapshot {html.escape(snapshot['date'])}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #17212b; }}
    h1 {{ font-size: 22px; margin: 0 0 10px; }}
    .summary {{ margin: 12px 0 18px; padding: 12px 14px; background: #f4f7f6; border: 1px solid #d9e4e0; border-radius: 6px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #dfe7e3; padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #edf3f1; position: sticky; top: 0; }}
    td:nth-child(7), td:nth-child(9) {{ text-align: right; font-variant-numeric: tabular-nums; }}
  </style>
</head>
<body>
  <h1>iFinD 宏观快照 - {html.escape(snapshot['date'])}</h1>
  <div class="summary">
    <strong>{html.escape(snapshot['regime']['one_sentence'])}</strong><br>
    auth_status: {html.escape(snapshot['collection']['auth_status'])};
    collected_rows: {html.escape(str(snapshot['collection']['collected_rows']))};
    active_indicators: {html.escape(str(snapshot['collection']['active_indicator_count']))};
    needs_code: {html.escape(str(snapshot['regime']['needs_code_count']))}
  </div>
  <table>
    <thead>
      <tr>
        <th>code</th><th>indicator</th><th>category</th><th>frequency</th><th>status</th>
        <th>latest_date</th><th>value</th><th>trend</th><th>percentile</th><th>use</th>
      </tr>
    </thead>
    <tbody>
      {''.join(row_html)}
    </tbody>
  </table>
</body>
</html>
"""
    path.write_text(body, encoding="utf-8")


def copy_latest(src: Path, latest: Path) -> None:
    latest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, latest)


def build_snapshot(
    *,
    date_str: str,
    config_path: Path,
    db_path: Path,
    start_date: str,
    allow_missing_token: bool,
    skip_api: bool,
    import_files: list[Path] | None = None,
) -> dict[str, Any]:
    config, indicators = load_config(config_path)
    active = [item for item in indicators if item.status == "active" and item.code]
    collected_at = datetime.now(timezone.utc).isoformat()
    collection: dict[str, Any] = {
        "auth_status": "not_attempted",
        "collected_rows": 0,
        "active_indicator_count": len(active),
        "config": str(config_path),
        "db": str(db_path),
        "start_date": start_date,
        "end_date": date_str,
        "imported_files": [],
        "imported_rows": 0,
    }

    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_schema(db_path)

    if import_files:
        imported_rows = 0
        for import_file in import_files:
            path = import_file.expanduser()
            if not path.is_absolute():
                path = (ROOT / path).resolve()
            imported = parse_gui_import_rows(path, indicators, date_str)
            source_query = {"source_file": str(path), "source": "iFind GUI export"}
            inserted = insert_rows(db_path, imported, source_query, collected_at)
            imported_rows += inserted
            collection["imported_files"].append({"path": str(path), "rows": inserted})
        collection["imported_rows"] = imported_rows

    access_token: str | None = None
    if skip_api:
        collection["auth_status"] = "skipped_api"
    elif active:
        try:
            access_token = get_access_token()
            collection["auth_status"] = "ok"
        except Exception as exc:
            if not allow_missing_token:
                raise
            collection["auth_status"] = "missing_or_invalid_token"
            collection["auth_error"] = str(exc)

    if access_token and active:
        codes = [str(item.code) for item in active if item.code]
        source_query = {"indicators": codes, "startdate": ymd(start_date), "enddate": ymd(date_str)}
        result = download_edb(codes, start_date, date_str, access_token)
        rows = extract_edb_rows(result, indicators, date_str)
        collection["ifind_errorcode"] = result.get("errorcode") if isinstance(result, dict) else None
        collection["ifind_errmsg"] = (
            result.get("errmsg")
            or result.get("message")
            or result.get("errorMsg")
            if isinstance(result, dict)
            else None
        )
        collection["ifind_datavol"] = result.get("dataVol") if isinstance(result, dict) else None
        collection["collected_rows"] = insert_rows(db_path, rows, source_query, collected_at)

    con = duckdb.connect(str(db_path))
    try:
        indicator_snapshot = build_indicator_snapshot(con, indicators, date_str)
        db_row_count = con.execute("SELECT COUNT(*) FROM ifind_macro_indicators").fetchone()[0]
    finally:
        con.close()

    snapshot = {
        "schema_version": config.get("schema_version", "ifind_macro_indicators_v1"),
        "date": date_str,
        "generated_at": collected_at,
        "collection": {**collection, "db_row_count": db_row_count},
        "regime": macro_regime(indicator_snapshot),
        "indicators": indicator_snapshot,
    }
    return snapshot


def write_outputs(snapshot: dict[str, Any]) -> dict[str, str]:
    date_ymd = ymd(snapshot["date"])
    out_dir = ROOT / "outputs" / "macro"
    json_path = out_dir / f"macro_snapshot_{date_ymd}.json"
    csv_path = out_dir / f"macro_snapshot_{date_ymd}.csv"
    html_path = ROOT / "public" / f"macro_snapshot_{date_ymd}.html"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(snapshot["indicators"], csv_path)
    write_html(snapshot, html_path)
    copy_latest(json_path, out_dir / "macro_snapshot_latest.json")
    copy_latest(csv_path, out_dir / "macro_snapshot_latest.csv")
    copy_latest(html_path, ROOT / "public" / "macro_snapshot_latest.html")
    return {"json": str(json_path), "csv": str(csv_path), "html": str(html_path)}


def write_indicator_catalog(config_path: Path, date_str: str) -> dict[str, str]:
    config, indicators = load_config(config_path)
    out_dir = ROOT / "outputs" / "macro"
    public_dir = ROOT / "public"
    out_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    date_ymd = ymd(date_str)
    raw_indicators = config.get("_merged_indicator_raws") or config.get("indicators", [])
    rows = []
    for raw, item in zip(raw_indicators, indicators, strict=False):
        rows.append(
            {
                "indicator_code": item.code,
                "indicator_name": item.name,
                "category": item.category,
                "frequency": item.frequency,
                "unit": item.unit,
                "status": item.status,
                "formula_id": raw.get("formula_id"),
                "formula_source_file": raw.get("formula_source_file"),
                "source_indicator_name": raw.get("source_indicator_name"),
                "source": raw.get("source"),
                "api_note": raw.get("api_note"),
                "use": item.use,
            }
        )
    payload = {
        "schema_version": "macro_indicator_catalog_v1",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_config": str(config_path),
        "indicator_source_file": config.get("indicator_source_file"),
        "active_count": sum(1 for item in indicators if item.status == "active"),
        "pending_count": sum(1 for item in indicators if item.status != "active"),
        "rows": rows,
        "research_only": True,
    }
    json_path = out_dir / f"macro_indicator_catalog_{date_ymd}.json"
    csv_path = out_dir / f"macro_indicator_catalog_{date_ymd}.csv"
    html_path = public_dir / f"macro_indicator_catalog_{date_ymd}.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        catalog_fields = [
            "indicator_code",
            "indicator_name",
            "category",
            "frequency",
            "unit",
            "status",
            "formula_id",
            "formula_source_file",
            "source_indicator_name",
            "source",
            "api_note",
            "use",
        ]
        writer = csv.DictWriter(
            f,
            fieldnames=catalog_fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    trs = []
    for row in rows:
        trs.append(
            "<tr>"
            f"<td>{html.escape(str(row['indicator_code'] or ''))}</td>"
            f"<td>{html.escape(str(row['indicator_name'] or ''))}</td>"
            f"<td>{html.escape(str(row['category'] or ''))}</td>"
            f"<td>{html.escape(str(row['frequency'] or ''))}</td>"
            f"<td>{html.escape(str(row['unit'] or ''))}</td>"
            f"<td>{html.escape(str(row['status'] or ''))}</td>"
            f"<td>{html.escape(str(row.get('formula_id') or ''))}</td>"
            f"<td>{html.escape(str(row.get('source') or row.get('formula_source_file') or ''))}</td>"
            f"<td>{html.escape(str(row.get('api_note') or ''))}</td>"
            f"<td>{html.escape(str(row['use'] or ''))}</td>"
            "</tr>"
        )
    html_path.write_text(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>宏观指标目录 {html.escape(date_str)}</title>
  <style>
    body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; margin:24px; color:#172033; }}
    table {{ border-collapse:collapse; width:100%; font-size:13px; }}
    th,td {{ border:1px solid #dfe6ee; padding:8px 10px; text-align:left; vertical-align:top; }}
    th {{ background:#eef3f7; }}
  </style>
</head>
<body>
  <h1>宏观指标目录 - {html.escape(date_str)}</h1>
  <p>active={payload['active_count']} pending={payload['pending_count']} source={html.escape(str(payload.get('indicator_source_file') or ''))}</p>
  <table>
    <thead><tr><th>code</th><th>name</th><th>category</th><th>frequency</th><th>unit</th><th>status</th><th>formula_id</th><th>source</th><th>api_note</th><th>use</th></tr></thead>
    <tbody>{''.join(trs)}</tbody>
  </table>
</body>
</html>
""",
        encoding="utf-8",
    )
    copy_latest(json_path, out_dir / "macro_indicator_catalog_latest.json")
    copy_latest(csv_path, out_dir / "macro_indicator_catalog_latest.csv")
    copy_latest(html_path, public_dir / "macro_indicator_catalog_latest.html")
    return {"json": str(json_path), "csv": str(csv_path), "html": str(html_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build iFinD macro DB evidence and daily snapshot.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--fundamental-db", default=str(DEFAULT_DB))
    parser.add_argument("--start-date")
    parser.add_argument("--import-file", action="append", default=[], help="iFinD GUI macro export file (.xlsx/.csv/.tsv). Can be repeated.")
    parser.add_argument("--skip-api", action="store_true", help="Only build from existing DB and optional GUI import files.")
    parser.add_argument("--allow-missing-token", action="store_true")
    args = parser.parse_args()

    config_payload = json.loads(Path(args.config).read_text(encoding="utf-8"))
    start_date = args.start_date or config_payload.get("default_start_date") or "2025-01-01"
    snapshot = build_snapshot(
        date_str=args.date,
        config_path=Path(args.config),
        db_path=Path(args.fundamental_db),
        start_date=start_date,
        allow_missing_token=args.allow_missing_token,
        skip_api=args.skip_api,
        import_files=[Path(item) for item in args.import_file],
    )
    outputs = write_outputs(snapshot)
    catalog_outputs = write_indicator_catalog(Path(args.config), args.date)
    result = {
        "ok": True,
        "date": args.date,
        "outputs": outputs,
        "catalog_outputs": catalog_outputs,
        "collection": snapshot["collection"],
        "regime": snapshot["regime"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
