#!/usr/bin/env python3
"""Build macro indicator time-series DB and trend summary.

The input can be the existing fundamental evidence DB plus optional mapping
CSV.  The output DB is intentionally independent from the fundamental DB so
macro history is not lost when daily evidence snapshots are rebuilt.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import shutil
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
DEFAULT_TIMESERIES_DB = ROOT / "outputs" / "macro" / "macro_indicator_data.duckdb"
DEFAULT_MAPPING_CSV = ROOT / "data" / "macro" / "ifind_indicator_mapping.csv"
DEFAULT_CONFIG = ROOT / "config" / "ifind_macro_indicators.json"
OUT_DIR = ROOT / "outputs" / "macro"
PUBLIC_DIR = ROOT / "public"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def norm_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.split("T", 1)[0].replace("/", "-").replace(".", "-")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) == 6 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-01"
    return text


def date_key(value: Any) -> date | None:
    normalized = norm_date(value)
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        value = float(value)
        if math.isnan(value):
            return None
        return value
    except (TypeError, ValueError):
        return None


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def load_config_metadata(path: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(path)
    out: dict[str, dict[str, Any]] = {}
    for raw in payload.get("indicators", []) or []:
        code = raw.get("code")
        if code:
            out[str(code)] = raw
    multi = load_json(ROOT / "config" / "macro_data_sources.json")
    for raw in multi.get("macro_indicators", []) or []:
        code = raw.get("code")
        if code:
            out.setdefault(str(code), raw)
    return out


def load_mapping_rows(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = {}
        for row in reader:
            code = row.get("ifind_indicator_code") or row.get("candidate_direct_code")
            if code:
                rows[str(code)] = row
        return rows


def init_timeseries_db(path: Path) -> None:
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


def copy_from_source_db(source_db: Path, target_db: Path, metadata: dict[str, dict[str, Any]]) -> int:
    if not source_db.exists():
        return 0
    init_timeseries_db(target_db)
    src = duckdb.connect(str(source_db), read_only=True)
    dst = duckdb.connect(str(target_db))
    copied = 0
    try:
        tables = {row[0] for row in src.execute("SHOW TABLES").fetchall()}
        if "ifind_macro_indicators" not in tables:
            return 0
        rows = src.execute(
            """
            SELECT indicator_code, as_of_date::VARCHAR, indicator_name, value, unit, frequency, source_api, source_query, collected_at
            FROM ifind_macro_indicators
            WHERE value IS NOT NULL
            """
        ).fetchall()
        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            code = str(row[0])
            obs_date = norm_date(row[1])
            if not obs_date:
                continue
            raw_meta = metadata.get(code, {})
            category = raw_meta.get("category") or infer_category(code, row[6])
            dst.execute(
                """
                INSERT OR REPLACE INTO macro_indicator_history
                (indicator_code, as_of_date, indicator_name, category, value, unit, frequency, source_api, source_query, collected_at, updated_at)
                VALUES (?, CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, CAST(? AS TIMESTAMP), CAST(? AS TIMESTAMP))
                """,
                [
                    code,
                    obs_date,
                    row[2] or raw_meta.get("name") or code,
                    category,
                    safe_float(row[3]),
                    row[4] or raw_meta.get("unit") or "",
                    row[5] or raw_meta.get("frequency") or "",
                    row[6] or "unknown",
                    row[7] or "{}",
                    row[8] or now,
                    now,
                ],
            )
            copied += 1
    finally:
        src.close()
        dst.close()
    return copied


def infer_category(code: str, source_api: Any) -> str:
    if code.startswith(("BW:", "TENCENT:", "SINA:")):
        return "market"
    if str(source_api or "").startswith("AKShare") and "pmi" in code.lower():
        return "growth"
    if str(source_api or "").startswith("AKShare"):
        return "inflation"
    if code.startswith("TS:"):
        return "credit"
    return "unknown"


def percentile(values: list[float], latest: float | None) -> float | None:
    if latest is None or not values:
        return None
    return round(sum(1 for value in values if value <= latest) * 100.0 / len(values), 2)


def trend(latest: float | None, previous: float | None) -> str:
    if latest is None or previous is None:
        return "data_insufficient"
    change = latest - previous
    threshold = max(abs(previous) * 0.001, 0.0001)
    if abs(change) <= threshold:
        return "flat"
    return "up" if change > 0 else "down"


def data_status(history_count: int, category: str) -> str:
    if history_count >= 12:
        return "trend_ready"
    if history_count >= 2:
        return "partial_history"
    if history_count == 1:
        return "single_point"
    return "missing"


def build_summary(
    target_db: Path, date_str: str, metadata: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    init_timeseries_db(target_db)
    con = duckdb.connect(str(target_db))
    cutoff = date_key(date_str)
    out: list[dict[str, Any]] = []
    try:
        codes = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT indicator_code FROM macro_indicator_history ORDER BY indicator_code"
            ).fetchall()
        ]
        now = datetime.now(timezone.utc).isoformat()
        con.execute("DELETE FROM macro_indicator_summary")
        for code in codes:
            rows = con.execute(
                """
                SELECT indicator_code, as_of_date::VARCHAR, indicator_name, category, value, unit, frequency, source_api
                FROM macro_indicator_history
                WHERE indicator_code = ? AND as_of_date <= CAST(? AS DATE)
                ORDER BY as_of_date, source_api
                """,
                [code, date_str],
            ).fetchall()
            if cutoff:
                rows = [row for row in rows if date_key(row[1]) and date_key(row[1]) <= cutoff]
            by_date: dict[str, tuple[Any, ...]] = {}
            for row in rows:
                by_date[str(row[1])] = row
            ordered = [by_date[key] for key in sorted(by_date)]
            if not ordered:
                continue
            latest = ordered[-1]
            previous = ordered[-2] if len(ordered) >= 2 else None
            values = [float(row[4]) for row in ordered if safe_float(row[4]) is not None]
            latest_value = safe_float(latest[4])
            previous_value = safe_float(previous[4]) if previous else None
            delta = (
                round(latest_value - previous_value, 6)
                if latest_value is not None and previous_value is not None
                else None
            )
            delta_pct = (
                round(delta * 100.0 / previous_value, 4)
                if delta is not None and previous_value not in (None, 0.0)
                else None
            )
            category = latest[3] or (metadata.get(code, {}) or {}).get("category") or "unknown"
            row_out = {
                "indicator_code": code,
                "indicator_name": latest[2] or (metadata.get(code, {}) or {}).get("name") or code,
                "category": category,
                "frequency": latest[6] or (metadata.get(code, {}) or {}).get("frequency") or "",
                "unit": latest[5] or (metadata.get(code, {}) or {}).get("unit") or "",
                "latest_date": latest[1],
                "latest_value": latest_value,
                "previous_value": previous_value,
                "change": delta,
                "change_pct": delta_pct,
                "history_count": len(ordered),
                "percentile": percentile(values, latest_value),
                "trend": trend(latest_value, previous_value),
                "data_status": data_status(len(ordered), str(category)),
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


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "indicator_code",
        "indicator_name",
        "category",
        "frequency",
        "unit",
        "latest_date",
        "latest_value",
        "previous_value",
        "change",
        "change_pct",
        "history_count",
        "percentile",
        "trend",
        "data_status",
        "source_count",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def render_html(payload: dict[str, Any]) -> str:
    esc = lambda value: html.escape("" if value is None else str(value))
    trs = []
    for row in payload["rows"]:
        trs.append(
            "<tr>"
            f"<td>{esc(row['indicator_code'])}</td>"
            f"<td>{esc(row['indicator_name'])}</td>"
            f"<td>{esc(row['category'])}</td>"
            f"<td>{esc(row['latest_date'])}</td>"
            f"<td>{esc(row['latest_value'])}</td>"
            f"<td>{esc(row['change'])}</td>"
            f"<td>{esc(row['percentile'])}</td>"
            f"<td>{esc(row['trend'])}</td>"
            f"<td>{esc(row['history_count'])}</td>"
            f"<td>{esc(row['data_status'])}</td>"
            "</tr>"
        )
    summary = payload["summary"]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>宏观时间序列 {esc(payload["date"])}</title>
  <style>
    body {{ margin:24px; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:#172033; }}
    .summary {{ margin:12px 0 18px; padding:12px 14px; background:#f4f7f6; border:1px solid #d9e4e0; border-radius:6px; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ border:1px solid #dfe6ee; padding:8px 10px; text-align:left; }}
    th {{ background:#eef3f7; position:sticky; top:0; }}
    td:nth-child(5),td:nth-child(6),td:nth-child(7),td:nth-child(9) {{ text-align:right; font-variant-numeric:tabular-nums; }}
  </style>
</head>
<body>
  <h1>宏观时间序列</h1>
  <div class="summary">
    日期 {esc(payload["date"])} ｜ 指标 {esc(summary["indicator_count"])} ｜
    12期可判趋势 {esc(summary["trend_ready_count"])} ｜
    部分历史 {esc(summary["partial_history_count"])} ｜
    单点 {esc(summary["single_point_count"])}
  </div>
  <table>
    <thead><tr><th>code</th><th>name</th><th>category</th><th>latest</th><th>value</th><th>change</th><th>percentile</th><th>trend</th><th>history</th><th>status</th></tr></thead>
    <tbody>{"".join(trs)}</tbody>
  </table>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build macro indicator time-series DB and trend summary.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB))
    parser.add_argument("--out-db", default=str(DEFAULT_TIMESERIES_DB))
    parser.add_argument("--mapping-csv", default=str(DEFAULT_MAPPING_CSV))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()

    metadata = load_config_metadata(Path(args.config))
    mapping = load_mapping_rows(Path(args.mapping_csv))
    for code, row in mapping.items():
        metadata.setdefault(
            code,
            {
                "name": row.get("indicator_name") or code,
                "category": row.get("category") or "unknown",
                "frequency": row.get("frequency") or "",
                "unit": row.get("unit") or "",
            },
        )
    copied = copy_from_source_db(Path(args.source_db), Path(args.out_db), metadata)
    rows = build_summary(Path(args.out_db), args.date, metadata)
    status_counts = Counter(str(row.get("data_status")) for row in rows)
    category_counts = Counter(str(row.get("category")) for row in rows)
    summary = {
        "indicator_count": len(rows),
        "copied_rows": copied,
        "trend_ready_count": status_counts.get("trend_ready", 0),
        "partial_history_count": status_counts.get("partial_history", 0),
        "single_point_count": status_counts.get("single_point", 0),
        "by_data_status": dict(status_counts),
        "by_category": dict(category_counts),
        "timeseries_db": str(Path(args.out_db)),
        "research_only": True,
    }
    payload = {
        "schema_version": "macro_indicator_timeseries_v1",
        "date": args.date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_db": str(Path(args.source_db)),
        "mapping_csv": str(Path(args.mapping_csv)),
        "summary": summary,
        "rows": rows,
        "research_only": True,
    }
    date_ymd = ymd(args.date)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / f"macro_trend_summary_{date_ymd}.json"
    csv_path = OUT_DIR / f"macro_trend_summary_{date_ymd}.csv"
    html_path = PUBLIC_DIR / f"macro_trend_summary_{date_ymd}.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(rows, csv_path)
    html_path.write_text(render_html(payload), encoding="utf-8")
    shutil.copyfile(json_path, OUT_DIR / "macro_trend_summary_latest.json")
    shutil.copyfile(csv_path, OUT_DIR / "macro_trend_summary_latest.csv")
    shutil.copyfile(html_path, PUBLIC_DIR / "macro_trend_summary_latest.html")
    print(
        json.dumps(
            {
                "ok": True,
                "date": args.date,
                "summary": summary,
                "outputs": {
                    "json": str(json_path),
                    "csv": str(csv_path),
                    "html": str(html_path),
                    "db": str(Path(args.out_db)),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
