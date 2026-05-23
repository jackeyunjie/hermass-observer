#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
API_BASE = "http://api.fxyz.site"


def read_token() -> str:
    token = os.environ.get("BLACKWOLF_TOKEN", "").strip()
    if token:
        return token
    token = sys.stdin.read().strip()
    if token:
        return token
    raise RuntimeError("missing BLACKWOLF_TOKEN")


def suffix_code(code: str) -> str:
    code = code.strip().upper()
    if "." in code:
        return code
    digits = "".join(ch for ch in code if ch.isdigit())[-6:]
    if digits.startswith(("6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("0", "2", "3")):
        return f"{digits}.SZ"
    if digits.startswith(("4", "8")):
        return f"{digits}.BJ"
    return digits


def request_money(token: str, code: str, date: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"code": code, "tradeDate": date, "token": token})
    req = urllib.request.Request(f"{API_BASE}/wolf/money?{params}", headers={"User-Agent": "HermassResearch/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        payload = json.loads(resp.read().decode("utf-8-sig", errors="replace"))
    if isinstance(payload, dict):
        records = payload.get("data") or payload.get("rows") or payload.get("result") or []
        if isinstance(records, dict):
            records = records.get("data") or records.get("rows") or []
    else:
        records = payload
    out = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        row = dict(record)
        row["stock_code"] = suffix_code(str(row.get("stock_code") or row.get("c") or code))
        row["date"] = str(row.get("date") or row.get("t") or date)[:10].replace("/", "-")
        out.append(row)
    return out


def write_rows(rows: list[dict[str, Any]], path: Path) -> list[str]:
    fields = sorted({k for row in rows for k in row})
    preferred = ["stock_code", "date"]
    fields = preferred + [k for k in fields if k not in preferred]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return fields


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--codes", nargs="+", required=True)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data" / "p116_top10_moneyflow_5d")
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--sleep", type=float, default=0.05)
    args = parser.parse_args()

    token = read_token()
    rows: list[dict[str, Any]] = []
    attempts = []
    for code in args.codes:
        try:
            one = request_money(token, code, args.date)
            rows.extend(one)
            attempts.append({"code": code, "row_count": len(one)})
        except Exception as exc:
            attempts.append({"code": code, "error": f"{type(exc).__name__}: {str(exc)[:180]}"})
        if args.sleep:
            time.sleep(args.sleep)

    out_csv = args.out_dir / f"blackwolf_ashare_moneyflow_{args.date.replace('-', '')}_{args.date.replace('-', '')}.csv"
    fields = write_rows(rows, out_csv)
    summary_path = args.summary or ROOT / "reports" / "p112_capital_flow_evidence_layer" / "p116_top10_moneyflow_5d" / f"summary_{args.date.replace('-', '')}.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "blackwolf_moneyflow_product_download_v0_1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target_date": args.date,
        "code_count": len(args.codes),
        "row_count": len(rows),
        "output_csv": str(out_csv),
        "fields": fields,
        "attempts": attempts,
        "detail_error_count": sum(1 for item in attempts if item.get("error")),
        "token_written_to_disk": False,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
