#!/usr/bin/env python3
"""筛选：周线或月线有 E/F，且 D1 也为 E/F 的股票，每个品种 6 行。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_JSON = ROOT / "fixtures/all_products_d1_view_6_rows_20260519.json"
OUTPUT_JSON = ROOT / "fixtures/w_mn1_ef_d1_ef_6_rows.json"
OUTPUT_CSV = ROOT / "fixtures/w_mn1_ef_d1_ef_6_rows.csv"


def main() -> int:
    data = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
    rows = data["rows"]
    row_limit = data.get("row_limit_per_symbol", 6)

    groups: dict[str, list[dict]] = {}
    for row in rows:
        sym = row["品种"]
        groups.setdefault(sym, []).append(row)

    filtered_rows = []
    for sym, sym_rows in groups.items():
        if len(sym_rows) != row_limit:
            continue
        latest = sym_rows[0]
        w_state = latest["W1state"]
        mn1_state = latest["MN1state"]
        d_state = latest["D1state"]
        if (w_state in ("E", "F") or mn1_state in ("E", "F")) and d_state in ("E", "F"):
            filtered_rows.extend(sym_rows)

    output_data = dict(data)
    output_data["symbol_count"] = len(filtered_rows) // row_limit
    output_data["rows"] = filtered_rows
    output_data["filter_description"] = "W1state或MN1state为E/F，且D1state为E/F"
    output_data["generated_at"] = data["generated_at"]

    OUTPUT_JSON.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON 输出 → {OUTPUT_JSON}")

    import csv

    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["品种", "时间", "MN1state", "W1state", "D1state"])
        writer.writeheader()
        writer.writerows(filtered_rows)
    print(f"CSV 输出 → {OUTPUT_CSV}")

    unique_symbols = sorted(set(r["品种"] for r in filtered_rows))
    print(f"符合条件的品种数: {len(unique_symbols)}")
    print(f"总行数: {len(filtered_rows)}")

    print("\n品种清单:")
    for sym in unique_symbols:
        sym_rows = [r for r in filtered_rows if r["品种"] == sym]
        latest = sym_rows[0]
        print(
            f"  {sym} | MN1={latest['MN1state']} W1={latest['W1state']} D1={latest['D1state']} | 最新日={latest['时间'][:10]}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
