#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")
DEFAULT_DB = ROOT / "outputs" / "blackwolf_moneyflow" / "blackwolf_moneyflow.duckdb"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def fnum(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def inum(value: Any) -> int | None:
    number = fnum(value)
    return int(number) if number is not None else None


def normalize_code(value: Any) -> str:
    text = str(value or "").strip()
    if "." in text:
        digits, suffix = text.split(".", 1)
        digits = "".join(ch for ch in digits if ch.isdigit())[-6:]
        suffix = suffix[:2].upper()
        return f"{digits}.{suffix}" if digits and suffix else digits
    digits = "".join(ch for ch in text if ch.isdigit())[-6:]
    if not digits:
        return ""
    if digits.startswith(("6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("0", "2", "3")):
        return f"{digits}.SZ"
    if digits.startswith(("4", "8")):
        return f"{digits}.BJ"
    return digits


def discover_best_csv(trade_date: str) -> tuple[Path, int]:
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
    if best_path is None:
        raise FileNotFoundError(f"moneyflow CSV not found for {trade_date} under {root}")
    return best_path, max(best_rows, 0)


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS moneyflow_raw (
            stock_code VARCHAR NOT NULL,
            date DATE NOT NULL,
            c VARCHAR,
            t TIMESTAMP,
            buynum BIGINT,
            sellnum BIGINT,
            totalnum BIGINT,
            buytddcje DOUBLE,
            buyddcje DOUBLE,
            buyzdcje DOUBLE,
            buysdcje DOUBLE,
            buyxdcje DOUBLE,
            selltddcje DOUBLE,
            sellddcje DOUBLE,
            sellzdcje DOUBLE,
            sellxdcje DOUBLE,
            sellsdcje DOUBLE,
            buytddcjl DOUBLE,
            buyddcjl DOUBLE,
            buyzdcjl DOUBLE,
            buyxdcjl DOUBLE,
            buysdcjl DOUBLE,
            selltddcjl DOUBLE,
            sellddcjl DOUBLE,
            sellzdcjl DOUBLE,
            sellxdcjl DOUBLE,
            sellsdcjl DOUBLE,
            source_csv VARCHAR,
            imported_at TIMESTAMP,
            PRIMARY KEY (stock_code, date)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS moneyflow_daily (
            stock_code VARCHAR NOT NULL,
            date DATE NOT NULL,
            buy_total DOUBLE,
            sell_total DOUBLE,
            active_net DOUBLE,
            big_order_net DOUBLE,
            active_net_ratio DOUBLE,
            buynum BIGINT,
            sellnum BIGINT,
            totalnum BIGINT,
            source_csv VARCHAR,
            imported_at TIMESTAMP,
            PRIMARY KEY (stock_code, date)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS moneyflow_import_log (
            date DATE,
            source_csv VARCHAR,
            csv_row_count BIGINT,
            imported_raw_rows BIGINT,
            imported_daily_rows BIGINT,
            imported_at TIMESTAMP
        )
        """
    )


def derive(row: dict[str, Any]) -> dict[str, float]:
    buy_total = sum(
        value or 0
        for value in [
            fnum(row.get("buytddcje")),
            fnum(row.get("buyddcje")),
            fnum(row.get("buyzdcje")),
            fnum(row.get("buysdcje") or row.get("buyxdcje")),
        ]
    )
    sell_total = sum(
        value or 0
        for value in [
            fnum(row.get("selltddcje")),
            fnum(row.get("sellddcje")),
            fnum(row.get("sellzdcje")),
            fnum(row.get("sellxdcje") or row.get("sellsdcje")),
        ]
    )
    big_order_net = (fnum(row.get("buytddcje")) or 0) + (fnum(row.get("buyddcje")) or 0) - (
        (fnum(row.get("selltddcje")) or 0) + (fnum(row.get("sellddcje")) or 0)
    )
    active_net = buy_total - sell_total
    return {
        "buy_total": buy_total,
        "sell_total": sell_total,
        "active_net": active_net,
        "big_order_net": big_order_net,
        "active_net_ratio": active_net / buy_total if buy_total else 0.0,
    }


def load_csv_rows(csv_path: Path, trade_date: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    imported_at = datetime.now(timezone.utc).replace(tzinfo=None)
    raw_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            stock_code = normalize_code(row.get("stock_code") or row.get("c"))
            if not stock_code:
                continue
            row_date = str(row.get("date") or row.get("t") or trade_date)[:10].replace("/", "-")
            source_csv = str(csv_path)
            raw_rows.append(
                {
                    "stock_code": stock_code,
                    "date": row_date,
                    "c": row.get("c") or stock_code.split(".")[0],
                    "t": row.get("t"),
                    "buynum": inum(row.get("buynum")),
                    "sellnum": inum(row.get("sellnum")),
                    "totalnum": inum(row.get("totalnum")),
                    "buytddcje": fnum(row.get("buytddcje")),
                    "buyddcje": fnum(row.get("buyddcje")),
                    "buyzdcje": fnum(row.get("buyzdcje")),
                    "buysdcje": fnum(row.get("buysdcje")),
                    "buyxdcje": fnum(row.get("buyxdcje")),
                    "selltddcje": fnum(row.get("selltddcje")),
                    "sellddcje": fnum(row.get("sellddcje")),
                    "sellzdcje": fnum(row.get("sellzdcje")),
                    "sellxdcje": fnum(row.get("sellxdcje")),
                    "sellsdcje": fnum(row.get("sellsdcje")),
                    "buytddcjl": fnum(row.get("buytddcjl")),
                    "buyddcjl": fnum(row.get("buyddcjl")),
                    "buyzdcjl": fnum(row.get("buyzdcjl")),
                    "buyxdcjl": fnum(row.get("buyxdcjl")),
                    "buysdcjl": fnum(row.get("buysdcjl")),
                    "selltddcjl": fnum(row.get("selltddcjl")),
                    "sellddcjl": fnum(row.get("sellddcjl")),
                    "sellzdcjl": fnum(row.get("sellzdcjl")),
                    "sellxdcjl": fnum(row.get("sellxdcjl")),
                    "sellsdcjl": fnum(row.get("sellsdcjl")),
                    "source_csv": source_csv,
                    "imported_at": imported_at,
                }
            )
            derived = derive(row)
            daily_rows.append(
                {
                    "stock_code": stock_code,
                    "date": row_date,
                    **derived,
                    "buynum": inum(row.get("buynum")),
                    "sellnum": inum(row.get("sellnum")),
                    "totalnum": inum(row.get("totalnum")),
                    "source_csv": source_csv,
                    "imported_at": imported_at,
                }
            )
    return raw_rows, daily_rows


def import_moneyflow(date_str: str, csv_path: Path | None, db_path: Path) -> dict[str, Any]:
    if csv_path is None:
        csv_path, csv_rows = discover_best_csv(date_str)
    else:
        csv_path = csv_path.resolve()
        csv_rows = max(0, sum(1 for _ in csv_path.open(encoding="utf-8-sig")) - 1)
    raw_rows, daily_rows = load_csv_rows(csv_path, date_str)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM moneyflow_raw WHERE date = CAST(? AS DATE)", [date_str])
        con.execute("DELETE FROM moneyflow_daily WHERE date = CAST(? AS DATE)", [date_str])
        if raw_rows:
            con.executemany(
                """
                INSERT INTO moneyflow_raw VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [[row[field] for field in RAW_FIELDS] for row in raw_rows],
            )
        if daily_rows:
            con.executemany(
                """
                INSERT INTO moneyflow_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [[row[field] for field in DAILY_FIELDS] for row in daily_rows],
            )
        con.execute(
            "INSERT INTO moneyflow_import_log VALUES (CAST(? AS DATE), ?, ?, ?, ?, ?)",
            [date_str, str(csv_path), csv_rows, len(raw_rows), len(daily_rows), datetime.now(timezone.utc).replace(tzinfo=None)],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    coverage = con.execute(
        """
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT date) AS date_count,
            MIN(date) AS min_date,
            MAX(date) AS max_date
        FROM moneyflow_daily
        """
    ).fetchone()
    con.close()
    return {
        "schema_version": "blackwolf_moneyflow_duckdb_import_v1",
        "date": date_str,
        "db": str(db_path),
        "source_csv": str(csv_path),
        "csv_rows": csv_rows,
        "imported_raw_rows": len(raw_rows),
        "imported_daily_rows": len(daily_rows),
        "database_total_rows": coverage[0],
        "database_date_count": coverage[1],
        "database_min_date": str(coverage[2]) if coverage[2] is not None else None,
        "database_max_date": str(coverage[3]) if coverage[3] is not None else None,
    }


RAW_FIELDS = [
    "stock_code",
    "date",
    "c",
    "t",
    "buynum",
    "sellnum",
    "totalnum",
    "buytddcje",
    "buyddcje",
    "buyzdcje",
    "buysdcje",
    "buyxdcje",
    "selltddcje",
    "sellddcje",
    "sellzdcje",
    "sellxdcje",
    "sellsdcje",
    "buytddcjl",
    "buyddcjl",
    "buyzdcjl",
    "buyxdcjl",
    "buysdcjl",
    "selltddcjl",
    "sellddcjl",
    "sellzdcjl",
    "sellxdcjl",
    "sellsdcjl",
    "source_csv",
    "imported_at",
]

DAILY_FIELDS = [
    "stock_code",
    "date",
    "buy_total",
    "sell_total",
    "active_net",
    "big_order_net",
    "active_net_ratio",
    "buynum",
    "sellnum",
    "totalnum",
    "source_csv",
    "imported_at",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Blackwolf moneyflow L0 CSV into the long-lived DuckDB.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    result = import_moneyflow(args.date, args.csv, args.db)
    summary_dir = ROOT / "reports" / "blackwolf_actions" / "moneyflow_duckdb"
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_dir / f"moneyflow_duckdb_import_{ymd(args.date)}.json"
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "summary": str(summary_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
