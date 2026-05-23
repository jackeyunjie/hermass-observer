#!/usr/bin/env python3
"""Persist strategy-environment fit observations.

This script is a read-only consumer of the normalized strategy signal ledger.
It does not generate signals and does not change fit labels. Its only job is
to store the already-computed lifecycle and environment-fit fields in a durable
query table for future statistics.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "strategy_fit_observer"
FIT_DB = OUT_DIR / "fit_log.duckdb"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def code6(value: Any) -> str:
    text = str(value or "").upper().strip()
    digits = "".join(ch for ch in text.split(".", 1)[0] if ch.isdigit())
    return digits[-6:] if digits else text


def load_signal_payload(date_str: str) -> dict[str, Any]:
    path = ROOT / "outputs" / "strategy_signals" / f"strategy_signal_daily_{ymd(date_str)}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def create_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_fit_log (
            signal_date DATE NOT NULL,
            stock_code VARCHAR NOT NULL,
            stock_code_6 VARCHAR NOT NULL,
            strategy_id VARCHAR NOT NULL,
            signal_type VARCHAR NOT NULL,
            signal_name VARCHAR NOT NULL,
            raw_signal VARCHAR NOT NULL,
            signal_strength DOUBLE,
            reminder_eligible BOOLEAN NOT NULL,
            display_scope VARCHAR NOT NULL,
            lifecycle_stage VARCHAR NOT NULL,
            strategy_environment_fit VARCHAR NOT NULL,
            fit_reasons VARCHAR NOT NULL,
            source_module VARCHAR NOT NULL,
            params_json VARCHAR NOT NULL,
            observed_at VARCHAR NOT NULL,
            research_only BOOLEAN NOT NULL,
            PRIMARY KEY (signal_date, stock_code, strategy_id, raw_signal)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_fit_manifest (
            signal_date DATE PRIMARY KEY,
            observed_at VARCHAR NOT NULL,
            signal_count BIGINT NOT NULL,
            fit_counts_json VARCHAR NOT NULL,
            lifecycle_counts_json VARCHAR NOT NULL,
            strategy_counts_json VARCHAR NOT NULL,
            research_only BOOLEAN NOT NULL
        )
        """
    )


def normalize_row(row: dict[str, Any], observed_at: str) -> dict[str, Any]:
    return {
        "signal_date": row.get("signal_date"),
        "stock_code": row.get("stock_code"),
        "stock_code_6": code6(row.get("stock_code")),
        "strategy_id": row.get("strategy_id"),
        "signal_type": row.get("signal_type"),
        "signal_name": row.get("signal_name"),
        "raw_signal": row.get("raw_signal"),
        "signal_strength": row.get("signal_strength"),
        "reminder_eligible": bool(row.get("reminder_eligible")),
        "display_scope": row.get("display_scope") or "research",
        "lifecycle_stage": row.get("lifecycle_stage") or "未知",
        "strategy_environment_fit": row.get("strategy_environment_fit") or "待观察",
        "fit_reasons": row.get("fit_reasons") or "",
        "source_module": row.get("source_module") or "",
        "params_json": row.get("params_json") or "{}",
        "observed_at": observed_at,
        "research_only": True,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else [
        "signal_date",
        "stock_code",
        "strategy_id",
        "signal_type",
        "lifecycle_stage",
        "strategy_environment_fit",
        "fit_reasons",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_strategy_fit_observer(date_str: str, fit_db: Path = FIT_DB) -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = load_signal_payload(date_str)
    observed_at = datetime.now(timezone.utc).isoformat()
    rows = [normalize_row(row, observed_at) for row in payload.get("rows", []) or []]

    con = duckdb.connect(str(fit_db))
    create_tables(con)
    con.execute("DELETE FROM strategy_fit_log WHERE signal_date = CAST(? AS DATE)", (date_str,))
    con.execute("DELETE FROM strategy_fit_manifest WHERE signal_date = CAST(? AS DATE)", (date_str,))
    if rows:
        con.executemany(
            """
            INSERT OR REPLACE INTO strategy_fit_log
            (signal_date, stock_code, stock_code_6, strategy_id, signal_type,
             signal_name, raw_signal, signal_strength, reminder_eligible,
             display_scope, lifecycle_stage, strategy_environment_fit,
             fit_reasons, source_module, params_json, observed_at, research_only)
            VALUES (CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["signal_date"],
                    row["stock_code"],
                    row["stock_code_6"],
                    row["strategy_id"],
                    row["signal_type"],
                    row["signal_name"],
                    row["raw_signal"],
                    row["signal_strength"],
                    row["reminder_eligible"],
                    row["display_scope"],
                    row["lifecycle_stage"],
                    row["strategy_environment_fit"],
                    row["fit_reasons"],
                    row["source_module"],
                    row["params_json"],
                    row["observed_at"],
                    row["research_only"],
                )
                for row in rows
            ],
        )

    fit_counts = Counter(row["strategy_environment_fit"] for row in rows)
    lifecycle_counts = Counter(row["lifecycle_stage"] for row in rows)
    strategy_counts = Counter(f"{row['strategy_id']}:{row['signal_type']}" for row in rows)
    con.execute(
        """
        INSERT OR REPLACE INTO strategy_fit_manifest
        VALUES (CAST(? AS DATE), ?, ?, ?, ?, ?, true)
        """,
        (
            date_str,
            observed_at,
            len(rows),
            json.dumps(dict(sorted(fit_counts.items())), ensure_ascii=False, sort_keys=True),
            json.dumps(dict(sorted(lifecycle_counts.items())), ensure_ascii=False, sort_keys=True),
            json.dumps(dict(sorted(strategy_counts.items())), ensure_ascii=False, sort_keys=True),
        ),
    )
    con.close()

    out_json = OUT_DIR / f"fit_log_{ymd(date_str)}.json"
    out_csv = OUT_DIR / f"fit_log_{ymd(date_str)}.csv"
    latest_json = OUT_DIR / "fit_log_latest.json"
    latest_csv = OUT_DIR / "fit_log_latest.csv"
    out_payload = {
        "schema_version": "strategy_fit_observer_v1",
        "date": date_str,
        "observed_at": observed_at,
        "fit_db": str(fit_db),
        "signal_count": len(rows),
        "fit_counts": dict(sorted(fit_counts.items())),
        "lifecycle_counts": dict(sorted(lifecycle_counts.items())),
        "strategy_counts": dict(sorted(strategy_counts.items())),
        "rows": rows,
        "research_only": True,
    }
    text = json.dumps(out_payload, ensure_ascii=False, indent=2)
    out_json.write_text(text, encoding="utf-8")
    latest_json.write_text(text, encoding="utf-8")
    write_csv(out_csv, rows)
    write_csv(latest_csv, rows)

    return {
        "ok": True,
        "date": date_str,
        "fit_db": str(fit_db),
        "signal_count": len(rows),
        "fit_counts": out_payload["fit_counts"],
        "lifecycle_counts": out_payload["lifecycle_counts"],
        "strategy_counts": out_payload["strategy_counts"],
        "json": str(out_json),
        "csv": str(out_csv),
        "latest_json": str(latest_json),
        "latest_csv": str(latest_csv),
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist strategy-environment fit observations.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--fit-db", type=Path, default=FIT_DB)
    args = parser.parse_args()
    result = build_strategy_fit_observer(args.date, args.fit_db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
