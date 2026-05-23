#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import urllib.parse
import urllib.request
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from token_provider import read_token


ROOT = Path(__file__).resolve().parents[1]
API_BASE = "http://api.fxyz.site"
DEFAULT_CONFIG = ROOT / "config" / "industry_rotation_assets.json"
DEFAULT_OUT_DIR = ROOT / "data" / "blackwolf_market_assets"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def recent_weekdays(end_date: str, days: int) -> list[str]:
    out: list[str] = []
    current = date.fromisoformat(end_date)
    while len(out) < days:
        if current.weekday() < 5:
            out.append(current.isoformat())
        current -= timedelta(days=1)
    return sorted(out)


def load_assets(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assets: list[dict[str, Any]] = []
    for key in ["index_assets", "industry_etf_assets"]:
        for item in payload.get(key, []) or []:
            assets.append(dict(item))
    return assets


def unwrap_records(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ["data", "rows", "result", "list", "items", "values"]:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        if isinstance(payload.get("data"), dict):
            return unwrap_records(payload["data"])
    return []


def parse_date(value: Any, fallback: str) -> str:
    if value in (None, ""):
        return fallback
    text = str(value).strip().replace("/", "-")
    if len(text) >= 10:
        return datetime.fromisoformat(text[:10]).date().isoformat()
    return fallback


def fnum(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_record(record: Any, asset: dict[str, Any], target_date: str) -> dict[str, Any] | None:
    symbol = str(asset["symbol"])
    if isinstance(record, (list, tuple)):
        if len(record) < 6:
            return None
        offset = 1 if isinstance(record[0], str) and any(ch.isdigit() for ch in record[0]) else 0
        return {
            "symbol": symbol,
            "date": parse_date(record[offset], target_date),
            "open": fnum(record[offset + 1]),
            "high": fnum(record[offset + 2]),
            "low": fnum(record[offset + 3]),
            "close": fnum(record[offset + 4]),
            "volume": fnum(record[offset + 5]),
            "amount": fnum(record[offset + 6]) if len(record) > offset + 6 else None,
        }
    if not isinstance(record, dict):
        return None
    row = {
        "symbol": symbol,
        "date": parse_date(record.get("date") or record.get("tradeDate") or record.get("t") or record.get("time"), target_date),
        "open": first_number(record, "open", "o", "kp"),
        "high": first_number(record, "high", "h", "zg"),
        "low": first_number(record, "low", "l", "zd"),
        "close": first_number(record, "close", "c", "zxj", "sp"),
        "volume": first_number(record, "volume", "vol", "v", "cjl"),
        "amount": first_number(record, "amount", "amt", "a", "cje"),
    }
    if any(row[key] is None for key in ["open", "high", "low", "close", "volume"]):
        return None
    return row


def first_number(record: dict[str, Any], *keys: str) -> float | None:
    lower = {str(k).lower(): v for k, v in record.items()}
    for key in keys:
        value = lower.get(key.lower())
        number = fnum(value)
        if number is not None:
            return number
    return None


def symbol_param_candidates(asset: dict[str, Any]) -> list[str]:
    asset_type = str(asset.get("asset_type") or "")
    if asset_type == "industry_etf":
        return ["etf"]
    if asset_type == "broad_index":
        return ["index"]
    return ["stock"]


def request_asset(token: str, asset: dict[str, Any], target_date: str, period: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    code = str(asset["symbol"]).split(".")[0]
    errors = []
    for symbol_param in symbol_param_candidates(asset):
        params = {
            "symbol": symbol_param,
            "code": code,
            "period": period,
            "cq": "1",
            "startDate": target_date,
            "endDate": target_date,
            "token": token,
        }
        url = f"{API_BASE}/wolf/time/kline?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "HermassResearch/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                payload = json.loads(resp.read().decode("utf-8-sig", errors="replace"))
            rows = []
            for record in unwrap_records(payload):
                row = normalize_record(record, asset, target_date)
                if row and row["date"] == target_date:
                    rows.append(
                        {
                            **row,
                            "name": asset.get("name", ""),
                            "asset_type": asset.get("asset_type", ""),
                            "sw_l1": asset.get("sw_l1", ""),
                            "benchmark_group": asset.get("benchmark_group", ""),
                        }
                    )
            if rows:
                return rows[-1:], {"symbol": asset["symbol"], "symbol_param": symbol_param, "row_count": len(rows)}
            errors.append({"symbol_param": symbol_param, "row_count": 0})
        except Exception as exc:
            errors.append({"symbol_param": symbol_param, "error": f"{type(exc).__name__}: {str(exc)[:180]}"})
    return [], {"symbol": asset["symbol"], "row_count": 0, "attempts": errors}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "symbol",
        "name",
        "asset_type",
        "sw_l1",
        "benchmark_group",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def download_one_date(token: str, assets: list[dict[str, Any]], date_str: str, out_dir: Path, period: str, workers: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    attempts = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(request_asset, token, asset, date_str, period) for asset in assets]
        for future in as_completed(futures):
            one_rows, attempt = future.result()
            rows.extend(one_rows)
            attempts.append(attempt)
    out_csv = out_dir / f"blackwolf_market_assets_{ymd(date_str)}.csv"
    write_csv(out_csv, rows)
    return {
        "date": date_str,
        "asset_count": len(assets),
        "row_count": len(rows),
        "output_csv": str(out_csv),
        "detail_error_count": sum(1 for item in attempts if item.get("error")),
        "attempts": attempts,
    }


def download_assets(date_str: str, config: Path, out_dir: Path, period: str, days: int = 1, workers: int = 12) -> dict[str, Any]:
    token = read_token()
    assets = load_assets(config)
    dates = recent_weekdays(date_str, days)
    results = []
    for idx, trade_date in enumerate(dates, 1):
        result = download_one_date(token, assets, trade_date, out_dir, period, workers)
        results.append(result)
        if idx % 10 == 0 or idx == len(dates):
            print(json.dumps({"progress_dates": idx, "total_dates": len(dates), "latest_date": trade_date, "row_count": result["row_count"]}, ensure_ascii=False), file=sys.stderr)
    summary = {
        "schema_version": "blackwolf_market_assets_download_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "end_date": date_str,
        "dates": dates,
        "asset_count": len(assets),
        "workers": workers,
        "row_count": sum(item["row_count"] for item in results),
        "results": results,
        "detail_error_count": sum(item["detail_error_count"] for item in results),
        "token_written_to_logs": False,
    }
    summary_dir = ROOT / "reports" / "blackwolf_actions" / "market_assets"
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_dir / f"market_assets_download_{ymd(date_str)}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**summary, "summary": str(summary_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Blackwolf index and industry ETF daily bars.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--period", default="1d")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    print(json.dumps(download_assets(args.date, args.config, args.out_dir, args.period, args.days, args.workers), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
