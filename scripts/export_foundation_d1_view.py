#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")


def default_foundation_db(date_str: str) -> Path:
    ymd = date_str.replace("-", "")
    return ROOT / "outputs" / f"p116_foundation_{ymd}" / "p116_foundation.duckdb"


def load_names(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    import csv

    names: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = (row.get("symbol") or "").strip()
            name = (row.get("name") or "").strip()
            if symbol and name:
                names[symbol] = name
    return names


def to_jsonable(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def calc_label(base, trend_bit, position_bit, volatility_bit, trend_value) -> str:
    comp = "缩" if int(base or 0) == 0 else "扩"
    if int(trend_bit or 0):
        trend = "熊" if str(trend_value).startswith("bear") else "牛"
    else:
        trend = "平"
    position = "上突" if int(position_bit or 0) else "中"
    volatility = "波扩" if int(volatility_bit or 0) else "稳"
    score = int(base or 0) + int(trend_bit or 0) * 4 + int(position_bit or 0) + int(volatility_bit or 0)
    return f"{comp}+{trend}+{position}+{volatility}={score}"


def export_view(db_path: Path, date_str: str, output_json: Path, row_limit: int) -> dict:
    names = load_names(RESEARCH_ROOT / "data" / "symbol_name_mapping.csv")
    con = duckdb.connect(str(db_path), read_only=True)
    rows = (
        con.execute(
            """
        WITH ranked AS (
          SELECT
            *,
            row_number() OVER (PARTITION BY stock_code ORDER BY state_date DESC) AS rn
          FROM d1_perspective_state
          WHERE state_date <= CAST(? AS DATE)
        )
        SELECT *
        FROM ranked
        WHERE rn <= ?
        ORDER BY stock_code, state_date DESC
        """,
            [date_str, row_limit],
        )
        .fetchdf()
        .to_dict("records")
    )
    con.close()

    out_rows = []
    for row in rows:
        symbol = row["stock_code"]
        code = symbol.split(".")[0]
        name = names.get(symbol, "")
        product = f"{code} {name}".rstrip()
        out_rows.append(
            {
                "品种": product,
                "时间": to_jsonable(row["state_date"]),
                "MN1state": row["mn1_state_hex"],
                "W1state": row["w1_state_hex"],
                "D1state": row["d1_state_hex"],
                "MN1计算": calc_label(
                    row["mn1_base"],
                    row["mn1_trend_bit"],
                    row["mn1_position_bit"],
                    row["mn1_volatility_bit"],
                    row["mn1_trend"],
                ),
                "W1计算": calc_label(
                    row["w1_base"],
                    row["w1_trend_bit"],
                    row["w1_position_bit"],
                    row["w1_volatility_bit"],
                    row["w1_trend"],
                ),
                "D1计算": calc_label(
                    row["d1_base"],
                    row["d1_trend_bit"],
                    row["d1_position_bit"],
                    row["d1_volatility_bit"],
                    row["d1_trend"],
                ),
                "d1_close": row["d1_close"],
                "mn1_sr_support": row["mn1_sr_support"],
                "mn1_sr_resistance": row["mn1_sr_resistance"],
                "w1_sr_support": row["w1_sr_support"],
                "w1_sr_resistance": row["w1_sr_resistance"],
                "d1_sr_support": row["d1_sr_support"],
                "d1_sr_resistance": row["d1_sr_resistance"],
            }
        )

    payload = {
        "schema_version": "p116_foundation_d1_view_v1",
        "date": date_str,
        "source_duckdb": str(db_path),
        "row_limit_per_symbol": row_limit,
        "rows": out_rows,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return {
        "rows": len(out_rows),
        "symbols": len({r["品种"] for r in out_rows}),
        "output_json": str(output_json),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export P116 foundation D1-perspective rows.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--foundation-db", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--row-limit", type=int, default=6)
    args = parser.parse_args()

    db_path = args.foundation_db or default_foundation_db(args.date)
    output_json = (
        args.output_json
        or ROOT / "fixtures" / f"all_products_d1_view_6_rows_foundation_{args.date.replace('-', '')}.json"
    )
    summary = export_view(db_path, args.date, output_json, args.row_limit)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
