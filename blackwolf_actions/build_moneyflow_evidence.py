#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")
DEFAULT_DB = ROOT / "outputs" / "blackwolf_moneyflow" / "blackwolf_moneyflow.duckdb"


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


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_code(value: Any) -> str:
    text = str(value or "").strip()
    if "." in text and len(text.split(".")[0]) >= 6:
        digits = "".join(ch for ch in text.split(".")[0] if ch.isdigit())[-6:]
    else:
        digits = "".join(ch for ch in text if ch.isdigit())[-6:]
    if not digits:
        return ""
    if text.endswith((".SH", ".SZ", ".BJ")):
        return f"{digits}.{text[-2:]}"
    if digits.startswith(("6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("0", "2", "3")):
        return f"{digits}.SZ"
    if digits.startswith(("4", "8")):
        return f"{digits}.BJ"
    return digits


def discover_best_csv(trade_date: str) -> tuple[Path | None, int]:
    root = RESEARCH_ROOT / "data" / "blackwolf_moneyflow_recent"
    pattern = f"**/blackwolf_ashare_moneyflow_{ymd(trade_date)}_{ymd(trade_date)}.csv"
    candidates = list(root.glob(pattern))
    best_path: Path | None = None
    best_rows = -1
    for path in candidates:
        try:
            rows = max(0, sum(1 for _ in path.open(encoding="utf-8-sig")) - 1)
        except OSError:
            rows = -1
        if rows > best_rows:
            best_path = path
            best_rows = rows
    return best_path, max(best_rows, 0)


def load_daily_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_from_duckdb(db_path: Path, target_dates: list[str]) -> tuple[dict[str, dict[str, dict[str, Any]]], list[dict[str, Any]]]:
    by_code: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    if not db_path.exists():
        return by_code, []
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT
                stock_code,
                CAST(date AS VARCHAR) AS date,
                buy_total,
                sell_total,
                active_net,
                big_order_net,
                active_net_ratio,
                totalnum
            FROM moneyflow_daily
            WHERE date IN (SELECT CAST(value AS DATE) FROM (SELECT UNNEST(?::VARCHAR[]) AS value))
            ORDER BY stock_code, date
            """,
            [target_dates],
        ).fetchall()
        counts = dict(
            con.execute(
                """
                SELECT CAST(date AS VARCHAR), COUNT(*)
                FROM moneyflow_daily
                WHERE date IN (SELECT CAST(value AS DATE) FROM (SELECT UNNEST(?::VARCHAR[]) AS value))
                GROUP BY 1
                ORDER BY 1
                """,
                [target_dates],
            ).fetchall()
        )
    finally:
        con.close()
    for stock_code, row_date, buy_total, sell_total, active_net, big_order_net, active_net_ratio, totalnum in rows:
        by_code[normalize_code(stock_code)][str(row_date)[:10]] = {
            "buy_total": buy_total,
            "sell_total": sell_total,
            "active_net": active_net,
            "big_order_net": big_order_net,
            "active_net_ratio": active_net_ratio,
            "totalnum": totalnum,
        }
    sources = [
        {"date": trade_date, "duckdb": str(db_path), "row_count": int(counts.get(trade_date, 0))}
        for trade_date in target_dates
    ]
    return by_code, sources


def derive_daily(row: dict[str, Any]) -> dict[str, Any]:
    buy_total = (
        fnum(row.get("buytddcje"))
        + fnum(row.get("buyddcje"))
        + fnum(row.get("buyzdcje"))
        + fnum(row.get("buysdcje") or row.get("buyxdcje"))
    )
    sell_total = (
        fnum(row.get("selltddcje"))
        + fnum(row.get("sellddcje"))
        + fnum(row.get("sellzdcje"))
        + fnum(row.get("sellxdcje") or row.get("sellsdcje"))
    )
    big_order_net = (fnum(row.get("buytddcje")) + fnum(row.get("buyddcje"))) - (
        fnum(row.get("selltddcje")) + fnum(row.get("sellddcje"))
    )
    active_net = buy_total - sell_total
    return {
        "buy_total": buy_total,
        "sell_total": sell_total,
        "active_net": active_net,
        "big_order_net": big_order_net,
        "active_net_ratio": active_net / buy_total if buy_total else 0.0,
        "totalnum": fnum(row.get("totalnum")),
    }


def evidence_status(score: int, divergence: bool, days_available: int, required_days: int) -> str:
    if days_available == 0:
        return "missing"
    if days_available < min(3, required_days):
        return "insufficient"
    if divergence:
        return "divergence"
    if score >= 5:
        return "confirmed"
    if score >= 3:
        return "partial"
    return "neutral"


def build_evidence(end_date: str, days: int = 5, db_path: Path | None = DEFAULT_DB, use_csv_fallback: bool = True) -> dict[str, Any]:
    target_dates = recent_weekdays(end_date, days)
    if db_path:
        by_code, sources = load_from_duckdb(db_path, target_dates)
    else:
        by_code, sources = defaultdict(dict), []
    missing_dates = {item["date"] for item in sources if item.get("row_count", 0) == 0}
    if (not sources or missing_dates) and use_csv_fallback:
        csv_sources = []
        for trade_date in target_dates:
            if sources and trade_date not in missing_dates:
                continue
            path, row_count = discover_best_csv(trade_date)
            csv_sources.append({"date": trade_date, "csv": str(path) if path else None, "row_count": row_count})
            if not path:
                continue
            for raw in load_daily_rows(path):
                code = normalize_code(raw.get("stock_code") or raw.get("c"))
                row_date = str(raw.get("date") or raw.get("t") or trade_date)[:10]
                if not code:
                    continue
                by_code[code][row_date] = derive_daily(raw)
        source_by_date = {item["date"]: item for item in sources}
        for item in csv_sources:
            source_by_date[item["date"]] = item
        sources = [source_by_date.get(trade_date, {"date": trade_date, "row_count": 0}) for trade_date in target_dates]

    rows: list[dict[str, Any]] = []
    latest_date = target_dates[-1]
    for code, dated in sorted(by_code.items()):
        values = [dated[d] for d in target_dates if d in dated]
        days_available = len(values)
        active_net_5d = sum(fnum(item.get("active_net")) for item in values)
        big_order_net_5d = sum(fnum(item.get("big_order_net")) for item in values)
        buy_total_5d = sum(fnum(item.get("buy_total")) for item in values)
        sell_total_5d = sum(fnum(item.get("sell_total")) for item in values)
        positive_days_5d = sum(1 for item in values if fnum(item.get("active_net")) > 0)
        big_positive_days_5d = sum(1 for item in values if fnum(item.get("big_order_net")) > 0)
        latest = dated.get(latest_date, {})
        latest_active_net = fnum(latest.get("active_net"))
        latest_big_order_net = fnum(latest.get("big_order_net"))
        confirmation_score = 0
        confirmation_score += int(positive_days_5d >= 3)
        confirmation_score += int(big_positive_days_5d >= 3)
        confirmation_score += int(active_net_5d > 0)
        confirmation_score += int(big_order_net_5d > 0)
        confirmation_score += int(latest_active_net > 0)
        divergence = bool(days_available >= 3 and (active_net_5d < 0 or big_order_net_5d < 0))
        moneyflow_score = confirmation_score - (2 if divergence else 0)
        rows.append(
            {
                "stock_code": code,
                "end_date": end_date,
                "window_days": days,
                "target_dates": "|".join(target_dates),
                "moneyflow_days_available": days_available,
                "moneyflow_coverage_ratio": round(days_available / len(target_dates), 4) if target_dates else 0,
                "buy_total_5d": round(buy_total_5d, 2),
                "sell_total_5d": round(sell_total_5d, 2),
                "active_net_5d": round(active_net_5d, 2),
                "big_order_net_5d": round(big_order_net_5d, 2),
                "positive_days_5d": positive_days_5d,
                "big_positive_days_5d": big_positive_days_5d,
                "latest_active_net": round(latest_active_net, 2),
                "latest_big_order_net": round(latest_big_order_net, 2),
                "active_net_ratio_5d": round(active_net_5d / buy_total_5d, 6) if buy_total_5d else 0,
                "moneyflow_score": moneyflow_score,
                "moneyflow_confirmed": confirmation_score >= 5 and not divergence,
                "moneyflow_divergence": divergence,
                "moneyflow_status": evidence_status(confirmation_score, divergence, days_available, days),
            }
        )

    out_dir = ROOT / "outputs" / "moneyflow_evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"moneyflow_evidence_{ymd(end_date)}.csv"
    json_path = out_dir / f"moneyflow_evidence_{ymd(end_date)}.json"
    fields = [
        "stock_code",
        "end_date",
        "window_days",
        "moneyflow_days_available",
        "moneyflow_coverage_ratio",
        "moneyflow_status",
        "moneyflow_confirmed",
        "moneyflow_divergence",
        "moneyflow_score",
        "positive_days_5d",
        "big_positive_days_5d",
        "active_net_5d",
        "big_order_net_5d",
        "latest_active_net",
        "latest_big_order_net",
        "active_net_ratio_5d",
        "buy_total_5d",
        "sell_total_5d",
        "target_dates",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    payload = {
        "schema_version": "p116_moneyflow_evidence_v1",
        "end_date": end_date,
        "window_days": days,
        "target_dates": target_dates,
        "source_files": sources,
        "source_duckdb": str(db_path) if db_path else None,
        "row_count": len(rows),
        "csv": str(csv_path),
        "status_counts": count_by(rows, "moneyflow_status"),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**payload, "json": str(json_path)}


def count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build derived P116 moneyflow evidence from Blackwolf L0 CSVs.")
    parser.add_argument("--date", required=True, help="End trading date, e.g. 2026-05-21")
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--no-csv-fallback", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build_evidence(args.date, args.days, args.db, not args.no_csv_fallback), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
