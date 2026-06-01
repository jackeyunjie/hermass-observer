#!/usr/bin/env python3
"""Collect macro and market proxy observations from non-iFinD sources.

The script writes normalized rows into the existing ifind_macro_indicators
table.  iFinD remains the primary source for formal macro series; this file is
the fallback/cross-check layer for AKShare, Tushare, Tencent, Sina, and
Blackwolf market assets.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import os
import re
import shutil
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_ifind_macro_db import build_snapshot, write_indicator_catalog, write_outputs  # noqa: E402
from fundamental_evidence_schema import init_schema  # noqa: E402

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency in some envs
    requests = None  # type: ignore[assignment]


DEFAULT_CONFIG = ROOT / "config" / "macro_data_sources.json"
DEFAULT_IFIND_CONFIG = ROOT / "config" / "ifind_macro_indicators.json"
DEFAULT_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"


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
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if re.fullmatch(r"\d{6}", text):
        return f"{text[:4]}-{text[4:6]}-01"
    if re.fullmatch(r"\d{4}-\d{1,2}$", text):
        year, month = text.split("-")
        return f"{int(year):04d}-{int(month):02d}-01"
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text):
        year, month, day = text.split("-")[:3]
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return text


def date_key(value: Any) -> date | None:
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
    if not text or text in {"--", "-", "NA", "N/A", "nan", "None", "null"}:
        return None
    text = text.replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_existing_market_asset_file(date_str: str, dirs: list[Path]) -> Path | None:
    target = ymd(date_str)
    candidates: list[tuple[str, int, Path]] = []
    for priority, directory in enumerate(reversed(dirs)):
        if not directory.exists():
            continue
        for path in directory.glob("blackwolf_market_assets_*.csv"):
            match = re.search(r"(\d{8})", path.name)
            if not match:
                continue
            file_date = match.group(1)
            if file_date <= target:
                candidates.append((file_date, priority, path))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item[0], item[1]))[-1][2]


def blackwolf_rows(config: dict[str, Any], date_str: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_dirs = [
        ROOT / "data" / f"blackwolf_market_assets_expanded_v2_{ymd(date_str)}",
        ROOT / "data" / f"blackwolf_market_assets_expanded_{ymd(date_str)}",
        ROOT / "data" / "blackwolf_market_assets",
    ]
    path = latest_existing_market_asset_file(date_str, source_dirs)
    if not path:
        return [], {"status": "missing_local_blackwolf_market_assets", "rows": 0}
    df = pd.read_csv(path)
    wanted = {item["symbol"]: item for item in config.get("blackwolf_market_assets", []) or []}
    rows: list[dict[str, Any]] = []
    for _, raw in df.iterrows():
        symbol = str(raw.get("symbol") or "")
        item = wanted.get(symbol)
        if not item:
            continue
        value = to_float(raw.get("close"))
        obs_date = norm_date(raw.get("date")) or date_str
        if value is None or not obs_date:
            continue
        rows.append(
            {
                "indicator_code": item["indicator_code"],
                "as_of_date": obs_date,
                "indicator_name": item.get("name") or symbol,
                "value": value,
                "unit": "点" if symbol.endswith((".SH", ".SZ")) and symbol[0] in {"0", "3"} else "元",
                "frequency": "daily",
                "source_api": "Blackwolf_market_assets",
                "source_query": {"source_file": str(path), "symbol": symbol, "raw_date": raw.get("date")},
            }
        )
    return rows, {"status": "ok", "rows": len(rows), "source_file": str(path)}


def http_get_text(url: str, *, referer: str = "https://finance.sina.com.cn/") -> str:
    if requests is None:
        raise RuntimeError("requests is not installed")
    response = requests.get(
        url,
        timeout=15,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": referer,
        },
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def tencent_rows(config: dict[str, Any], date_str: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items = config.get("tencent_quotes", []) or []
    if not items:
        return [], {"status": "no_config", "rows": 0}
    symbols = ",".join(str(item["symbol"]) for item in items)
    url = f"https://qt.gtimg.cn/q={quote(symbols, safe=',')}"
    text = http_get_text(url, referer="https://finance.qq.com/")
    parsed: dict[str, list[str]] = {}
    for symbol, body in re.findall(r'v_([a-z0-9]+)="([^"]*)"', text):
        parsed[symbol] = body.split("~")
    rows: list[dict[str, Any]] = []
    for item in items:
        symbol = str(item["symbol"])
        parts = parsed.get(symbol)
        if not parts or len(parts) < 31:
            continue
        value = to_float(parts[3])
        timestamp = parts[30] if len(parts) > 30 else ""
        obs_date = norm_date(timestamp[:8]) or date_str
        if value is None:
            continue
        rows.append(
            {
                "indicator_code": item["indicator_code"],
                "as_of_date": obs_date,
                "indicator_name": item.get("name") or parts[1] or symbol,
                "value": value,
                "unit": "点",
                "frequency": "daily",
                "source_api": "Tencent_finance_quote",
                "source_query": {"url": url, "symbol": symbol},
            }
        )
    return rows, {"status": "ok", "rows": len(rows), "url": url}


def sina_rows(config: dict[str, Any], date_str: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items = config.get("sina_quotes", []) or []
    if not items:
        return [], {"status": "no_config", "rows": 0}
    symbols = ",".join(str(item["symbol"]) for item in items)
    url = f"https://hq.sinajs.cn/list={quote(symbols, safe=',')}"
    text = http_get_text(url, referer="https://finance.sina.com.cn/")
    parsed: dict[str, list[str]] = {}
    for symbol, body in re.findall(r'var hq_str_([a-z0-9]+)="([^"]*)"', text):
        parsed[symbol] = body.split(",")
    rows: list[dict[str, Any]] = []
    for item in items:
        symbol = str(item["symbol"])
        parts = parsed.get(symbol)
        if not parts or len(parts) < 31:
            continue
        value = to_float(parts[3])
        obs_date = norm_date(parts[30] if len(parts) > 30 else date_str) or date_str
        if value is None:
            continue
        rows.append(
            {
                "indicator_code": item["indicator_code"],
                "as_of_date": obs_date,
                "indicator_name": item.get("name") or parts[0] or symbol,
                "value": value,
                "unit": "点",
                "frequency": "daily",
                "source_api": "Sina_finance_quote",
                "source_query": {"url": url, "symbol": symbol},
            }
        )
    return rows, {"status": "ok", "rows": len(rows), "url": url}


def pick_column(df: pd.DataFrame, names: list[str]) -> str | None:
    normalized = {str(col).strip().lower(): str(col) for col in df.columns}
    for name in names:
        key = str(name).strip().lower()
        if key in normalized:
            return normalized[key]
    for col in df.columns:
        col_text = str(col)
        if any(str(name) and str(name) in col_text for name in names):
            return col_text
    return None


def latest_from_df(df: pd.DataFrame, spec: dict[str, Any], date_str: str) -> dict[str, Any] | None:
    if df is None or df.empty:
        return None
    date_col = pick_column(df, spec.get("date_candidates") or ["date", "日期"])
    value_col = pick_column(df, spec.get("value_candidates") or ["value", "今值"])
    if not value_col:
        return None
    working = df.copy()
    if date_col:
        working["_obs_date"] = working[date_col].map(norm_date)
    else:
        working["_obs_date"] = date_str
    working["_date_key"] = working["_obs_date"].map(date_key)
    working["_value"] = working[value_col].map(to_float)
    working = working[working["_value"].notna()]
    cutoff = date_key(date_str)
    if cutoff is not None:
        working = working[(working["_date_key"].isna()) | (working["_date_key"] <= cutoff)]
    if working.empty:
        return None
    working = working.sort_values(by=["_date_key", "_obs_date"], na_position="first")
    latest = working.iloc[-1]
    return {
        "indicator_code": spec["indicator_code"],
        "as_of_date": latest["_obs_date"] or date_str,
        "indicator_name": spec.get("name") or spec["indicator_code"],
        "value": float(latest["_value"]),
        "unit": "%",
        "frequency": "monthly",
    }


def akshare_rows(config: dict[str, Any], date_str: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spec_items = config.get("akshare", []) or []
    if not spec_items:
        return [], {"status": "no_config", "rows": 0}
    ak_spec = importlib.util.find_spec("akshare")
    if ak_spec is None:
        return [], {"status": "missing_package", "package": "akshare", "rows": 0}
    ak = importlib.import_module("akshare")
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for spec in spec_items:
        fn_name = spec.get("function")
        try:
            fn = getattr(ak, str(fn_name))
            df = fn()
            latest = latest_from_df(df, spec, date_str)
            if latest:
                latest["source_api"] = f"AKShare:{fn_name}"
                latest["source_query"] = {"function": fn_name}
                rows.append(latest)
        except Exception as exc:
            errors.append({"function": str(fn_name), "error": str(exc)})
    return rows, {"status": "ok" if rows else "no_rows", "rows": len(rows), "errors": errors}


def tushare_rows(config: dict[str, Any], date_str: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spec_items = config.get("tushare", []) or []
    if not spec_items:
        return [], {"status": "no_config", "rows": 0}
    ts_spec = importlib.util.find_spec("tushare")
    if ts_spec is None:
        return [], {"status": "missing_package", "package": "tushare", "rows": 0}
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        return [], {"status": "missing_token", "env": "TUSHARE_TOKEN", "rows": 0}
    ts = importlib.import_module("tushare")
    ts.set_token(token)
    pro = ts.pro_api()
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    start = date_str[:4] + "0101"
    end = ymd(date_str)
    min_interval = float(config.get("tushare_min_interval_seconds", 61))
    for idx, spec in enumerate(spec_items):
        if idx > 0 and min_interval > 0:
            time.sleep(min_interval)
        api_name = str(spec.get("api"))
        try:
            fn = getattr(pro, api_name)
            try:
                df = fn(start_m=start[:6], end_m=end[:6])
            except TypeError:
                df = fn(start_date=start, end_date=end)
            latest = latest_from_df(df, spec, date_str)
            if latest:
                latest["source_api"] = f"Tushare:{api_name}"
                latest["source_query"] = {"api": api_name, "start": start, "end": end, "auth": "env_auth"}
                rows.append(latest)
        except Exception as exc:
            errors.append({"api": api_name, "error": str(exc)})
    return rows, {"status": "ok" if rows else "no_rows", "rows": len(rows), "errors": errors}


def insert_rows(db_path: Path, rows: list[dict[str, Any]], collected_at: str) -> int:
    if not rows:
        return 0
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_schema(db_path)
    con = duckdb.connect(str(db_path))
    try:
        for row in rows:
            query = dict(row.get("source_query") or {})
            query["collector"] = "collect_macro_multisource.py"
            con.execute(
                """
                INSERT OR REPLACE INTO ifind_macro_indicators
                (indicator_code, as_of_date, indicator_name, value, unit, frequency, source_query, source_api, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["indicator_code"],
                    row["as_of_date"],
                    row.get("indicator_name", ""),
                    row.get("value"),
                    row.get("unit", ""),
                    row.get("frequency", ""),
                    json.dumps(query, ensure_ascii=False),
                    row.get("source_api", "macro_multisource"),
                    collected_at,
                ),
            )
    finally:
        con.close()
    return len(rows)


def dedup_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dedup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("indicator_code")), str(row.get("as_of_date")), str(row.get("source_api")))
        dedup[key] = row
    return sorted(
        dedup.values(), key=lambda item: (str(item.get("indicator_code")), str(item.get("as_of_date")))
    )


def collect_sources(
    config: dict[str, Any], date_str: str, sources: list[str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    collectors = {
        "blackwolf": blackwolf_rows,
        "tencent": tencent_rows,
        "sina": sina_rows,
        "akshare": akshare_rows,
        "tushare": tushare_rows,
    }
    all_rows: list[dict[str, Any]] = []
    status: dict[str, Any] = {}
    for source in sources:
        fn = collectors.get(source)
        if not fn:
            status[source] = {"status": "unknown_source", "rows": 0}
            continue
        try:
            rows, meta = fn(config, date_str)
            all_rows.extend(rows)
            status[source] = meta
        except Exception as exc:
            status[source] = {"status": "error", "rows": 0, "error": str(exc)}
    return dedup_rows(all_rows), status


def write_collection_outputs(payload: dict[str, Any]) -> dict[str, str]:
    out_dir = ROOT / "outputs" / "macro"
    out_dir.mkdir(parents=True, exist_ok=True)
    date_ymd = ymd(payload["date"])
    json_path = out_dir / f"macro_multisource_collection_{date_ymd}.json"
    csv_path = out_dir / f"macro_multisource_collection_{date_ymd}.csv"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["indicator_code", "indicator_name", "as_of_date", "value", "unit", "frequency", "source_api"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(payload["rows"])
    shutil.copyfile(json_path, out_dir / "macro_multisource_collection_latest.json")
    shutil.copyfile(csv_path, out_dir / "macro_multisource_collection_latest.csv")
    return {"json": str(json_path), "csv": str(csv_path)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect fallback macro data from Blackwolf/Tencent/Sina/AKShare/Tushare."
    )
    parser.add_argument("--date", required=True)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--ifind-config", default=str(DEFAULT_IFIND_CONFIG))
    parser.add_argument("--fundamental-db", default=str(DEFAULT_DB))
    parser.add_argument(
        "--sources",
        default="blackwolf,tencent,sina,akshare,tushare",
        help="Comma-separated source list: blackwolf,tencent,sina,akshare,tushare",
    )
    parser.add_argument(
        "--no-snapshot", action="store_true", help="Only collect/insert rows; do not rebuild macro snapshot."
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    ifind_config_path = Path(args.ifind_config)
    db_path = Path(args.fundamental_db)
    config = load_json(config_path)
    sources = [item.strip() for item in args.sources.split(",") if item.strip()]
    collected_at = datetime.now(timezone.utc).isoformat()
    rows, source_status = collect_sources(config, args.date, sources)
    inserted = insert_rows(db_path, rows, collected_at)
    collection_payload = {
        "schema_version": "macro_multisource_collection_v1",
        "date": args.date,
        "generated_at": collected_at,
        "config": str(config_path),
        "db": str(db_path),
        "sources": source_status,
        "requested_sources": sources,
        "row_count": len(rows),
        "inserted_rows": inserted,
        "rows": rows,
        "research_only": True,
    }
    collection_outputs = write_collection_outputs(collection_payload)
    snapshot_outputs: dict[str, str] = {}
    snapshot_summary: dict[str, Any] = {}
    if not args.no_snapshot:
        snapshot = build_snapshot(
            date_str=args.date,
            config_path=ifind_config_path,
            db_path=db_path,
            start_date="2025-01-01",
            allow_missing_token=True,
            skip_api=True,
            import_files=[],
        )
        snapshot_outputs = write_outputs(snapshot)
        write_indicator_catalog(ifind_config_path, args.date)
        snapshot_summary = {
            "coverage_status": snapshot.get("regime", {}).get("coverage_status"),
            "one_sentence": snapshot.get("regime", {}).get("one_sentence"),
            "db_row_count": snapshot.get("collection", {}).get("db_row_count"),
            "active_no_observation_count": snapshot.get("regime", {}).get("active_no_observation_count"),
        }
    result = {
        "ok": True,
        "date": args.date,
        "sources": source_status,
        "row_count": len(rows),
        "inserted_rows": inserted,
        "collection_outputs": collection_outputs,
        "snapshot_outputs": snapshot_outputs,
        "snapshot_summary": snapshot_summary,
        "research_only": True,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
