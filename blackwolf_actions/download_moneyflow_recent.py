#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

from token_provider import read_token


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def parse_date(date_str: str) -> date:
    return date.fromisoformat(date_str)


def recent_weekdays(end_date: str, days: int) -> list[str]:
    out: list[str] = []
    current = parse_date(end_date)
    while len(out) < days:
        if current.weekday() < 5:
            out.append(current.isoformat())
        current -= timedelta(days=1)
    return sorted(out)


def load_codes(code_list: Path, limit: int | None) -> list[str]:
    with code_list.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    codes = [(row.get("code") or row.get("stock_code") or "").split(".")[0] for row in rows]
    codes = [code for code in codes if code]
    return codes[:limit] if limit else codes


def suffix_code(code: str) -> str:
    digits = "".join(ch for ch in str(code).split(".")[0] if ch.isdigit())[-6:]
    if digits.startswith(("6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("0", "2", "3")):
        return f"{digits}.SZ"
    if digits.startswith(("4", "8")):
        return f"{digits}.BJ"
    return digits


def unwrap_records(payload):
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


def fetch_one_moneyflow(token: str, trade_date: str, code: str) -> tuple[list[dict], dict]:
    params = urllib.parse.urlencode({"code": code, "tradeDate": trade_date, "token": token})
    req = urllib.request.Request(
        f"http://api.fxyz.site/wolf/money?{params}",
        headers={"User-Agent": "HermassResearch/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            payload = json.loads(resp.read().decode("utf-8-sig", errors="replace"))
        rows = []
        for record in unwrap_records(payload):
            if not isinstance(record, dict):
                continue
            row = dict(record)
            row["stock_code"] = suffix_code(row.get("stock_code") or row.get("c") or code)
            row["date"] = str(row.get("date") or row.get("t") or trade_date)[:10].replace("/", "-")
            rows.append(row)
        return rows, {"code": code, "row_count": len(rows)}
    except Exception as exc:
        return [], {"code": code, "error": f"{type(exc).__name__}: {str(exc)[:180]}"}


def write_moneyflow_csv(path: Path, rows: list[dict]) -> list[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    preferred = ["stock_code", "date"]
    fields = preferred + [field for field in fields if field not in preferred]
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)
    return fields


def download_one_date_parallel(token: str, trade_date: str, codes: list[str], out_csv: Path, workers: int) -> dict:
    rows: list[dict] = []
    attempts: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_one_moneyflow, token, trade_date, code) for code in codes]
        for idx, future in enumerate(as_completed(futures), 1):
            one_rows, attempt = future.result()
            rows.extend(one_rows)
            attempts.append(attempt)
            if idx % 500 == 0:
                print(json.dumps({"date": trade_date, "progress": idx, "rows": len(rows)}, ensure_ascii=False), file=sys.stderr)
    fields = write_moneyflow_csv(out_csv, rows)
    return {
        "date": trade_date,
        "status": "PASS",
        "row_count": len(rows),
        "output_csv": str(out_csv),
        "fields": fields,
        "detail_attempt_count": len(attempts),
        "detail_error_count": sum(1 for item in attempts if item.get("error")),
        "attempts_sample": attempts[:20],
    }


def build_code_list_from_raw_daily(end_date: str, output: Path) -> Path:
    raw_db = RESEARCH_ROOT / "outputs" / f"p108_blackwolf_ashare_daily_raw_{ymd(end_date)}" / "p108_blackwolf_ashare_daily_raw.duckdb"
    if not raw_db.exists():
        raise FileNotFoundError(raw_db)
    import duckdb

    con = duckdb.connect(str(raw_db), read_only=True)
    rows = con.execute(
        """
        SELECT DISTINCT stock_code
        FROM blackwolf_ashare_daily_raw
        WHERE date = CAST(? AS DATE)
        ORDER BY stock_code
        """,
        [end_date],
    ).fetchall()
    con.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["code", "stock_code"])
        writer.writeheader()
        for (stock_code,) in rows:
            writer.writerow({"code": stock_code.split(".")[0], "stock_code": stock_code})
    return output


def download_moneyflow(end_date: str, days: int, code_list: Path | None, limit: int | None, workers: int) -> dict:
    token = read_token()
    if code_list is None:
        code_list = build_code_list_from_raw_daily(
            end_date,
            ROOT / "data" / "blackwolf_moneyflow_recent" / f"code_list_all_market_{ymd(end_date)}.csv",
        )
    codes = load_codes(code_list, limit)
    dates = recent_weekdays(end_date, days)
    run_tag = f"full_{ymd(end_date)}" if not limit else f"sample{limit}_{ymd(end_date)}"
    effective_code_list = ROOT / "data" / "blackwolf_moneyflow_recent" / f"effective_code_list_{ymd(end_date)}_{len(codes)}.csv"
    effective_code_list.parent.mkdir(parents=True, exist_ok=True)
    with effective_code_list.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["code"])
        writer.writeheader()
        for code in codes:
            writer.writerow({"code": code})

    out_dir = RESEARCH_ROOT / "data" / "blackwolf_moneyflow_recent" / f"{ymd(dates[0])}_{ymd(dates[-1])}_{run_tag}"
    summary_dir = ROOT / "reports" / "blackwolf_actions" / "moneyflow_recent"
    summary_dir.mkdir(parents=True, exist_ok=True)
    script = RESEARCH_ROOT / "scripts" / "download_blackwolf_ashare_moneyflow_api.py"
    env = dict(os.environ)
    env["BLACKWOLF_TOKEN"] = token
    results = []
    for trade_date in dates:
        summary = summary_dir / f"moneyflow_{ymd(trade_date)}.json"
        out_csv = out_dir / f"blackwolf_ashare_moneyflow_{ymd(trade_date)}_{ymd(trade_date)}.csv"
        if out_csv.exists():
            try:
                row_count = max(0, sum(1 for _ in out_csv.open(encoding="utf-8")) - 1)
            except OSError:
                row_count = 0
            if row_count >= len(codes):
                results.append({"date": trade_date, "status": "SKIP_EXISTS", "row_count": row_count, "output_csv": str(out_csv)})
                continue
        payload = download_one_date_parallel(token, trade_date, codes, out_csv, workers)
        summary.write_text(json.dumps({**payload, "token_written_to_disk": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        results.append({k: payload.get(k) for k in ["date", "status", "row_count", "output_csv", "detail_error_count"]})

    final = {
        "schema_version": "blackwolf_moneyflow_recent_action_v1",
        "end_date": end_date,
        "dates": dates,
        "code_count": len(codes),
        "code_list": str(effective_code_list),
        "run_tag": run_tag,
        "workers": workers,
        "out_dir": str(out_dir),
        "results": results,
        "token_written_to_logs": False,
    }
    final_summary = ROOT / "reports" / "blackwolf_actions" / f"moneyflow_recent_{ymd(end_date)}.json"
    final_summary.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return final


def sanitize_output(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if "token" not in line.lower())[:2000]


def main() -> int:
    parser = argparse.ArgumentParser(description="Download recent Blackwolf moneyflow for the P116 pool.")
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--code-list", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    result = download_moneyflow(args.end_date, args.days, args.code_list, args.limit, args.workers)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
