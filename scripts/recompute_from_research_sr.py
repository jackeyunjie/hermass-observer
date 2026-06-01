#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")


def state_hex(score: int) -> str:
    return ("-" if score < 0 else "") + format(abs(score), "X")


def classify_position(
    close: float | None, support: float | None, resistance: float | None
) -> tuple[int, str, str]:
    if close is None or support is None or resistance is None:
        return 0, "中", "neutral"
    if resistance and close > resistance:
        return 2, "上突", "above"
    if support and close < support:
        return 2, "下突", "below"
    return 0, "中", "neutral"


def component_state(
    close: float,
    support: float | None,
    resistance: float | None,
    trend: str | None,
    volatility: str | None,
    compression: str | None,
) -> dict:
    position_bit, position_label, position = classify_position(close, support, resistance)
    trend = trend or "neutral"
    volatility = volatility or "neutral"
    compression = compression or "neutral"

    trend_bit = 1 if ("bull" in trend or "bear" in trend) else 0
    trend_label = "牛" if "bull" in trend else ("熊" if "bear" in trend else "平")

    # Compression base follows the P116 merged bit-mask convention. This keeps
    # SQL-smoke insufficient_history from forcing a non-triggered 8 for MN1.
    base = 0 if compression in {"closed", "contracting"} or trend == "closed" else 8
    comp_label = "缩" if base == 0 else "扩"

    volatility_bit = 1 if volatility not in {"neutral", "insufficient_history", None} else 0
    volatility_label = "波扩" if volatility_bit else "稳"

    magnitude = base + trend_bit * 4 + position_bit + volatility_bit
    bear_context = "bear" in trend or position == "below"
    bull_context = "bull" in trend or position == "above"
    score = -magnitude if bear_context and not bull_context else magnitude

    return {
        "state_hex": state_hex(score),
        "state_score": score,
        "base": base,
        "trend_bit": trend_bit,
        "position_bit": position_bit,
        "volatility_bit": volatility_bit,
        "comp_label": comp_label,
        "trend_label": trend_label,
        "position_label": position_label,
        "volatility_label": volatility_label,
        "position": position,
        "trend": trend,
        "compression": compression,
        "volatility": volatility,
    }


def load_rows(date: str) -> list[dict]:
    p116d = (
        RESEARCH_ROOT
        / "outputs"
        / f"p116d_ashare_omni_cycle_alignment_{date.replace('-', '')}"
        / "p116d_ashare_omni_cycle_alignment.duckdb"
    )
    p116b = (
        RESEARCH_ROOT
        / "outputs"
        / f"p116b_ashare_d1_official_sr_key_positions_{date.replace('-', '')}"
        / "p116b_ashare_d1_official_sr_key_positions.duckdb"
    )
    if not p116d.exists():
        raise FileNotFoundError(p116d)
    if not p116b.exists():
        raise FileNotFoundError(p116b)

    conn = duckdb.connect(str(p116d), read_only=True)
    conn.execute(f"ATTACH '{str(p116b).replace("'", "''")}' AS srdb (READ_ONLY)")
    df = conn.execute(
        """
        SELECT
          o.stock_code,
          o.sync_date,
          o.d1_observer_close,
          o.mn1_observer_compression,
          o.mn1_observer_trend,
          o.mn1_observer_volatility,
          o.w1_observer_compression,
          o.w1_observer_trend,
          o.w1_observer_volatility,
          o.d1_observer_compression,
          o.d1_observer_trend,
          o.d1_observer_volatility,
          sr.MN1_sr_support,
          sr.MN1_sr_resistance,
          sr.W_sr_support,
          sr.W_sr_resistance,
          sr.D_sr_support,
          sr.D_sr_resistance
        FROM ashare_omni_cycle_alignment_d1_clock o
        JOIN srdb.ashare_d1_official_sr_key_positions_postclose sr
          ON sr.stock_code = o.stock_code AND sr.base_date = o.sync_date
        WHERE o.sync_date <= ?
        QUALIFY row_number() OVER (PARTITION BY o.stock_code, o.sync_date ORDER BY o.sync_date DESC) = 1
        ORDER BY o.stock_code, o.sync_date DESC
        """,
        [date],
    ).fetchdf()
    conn.close()
    return df.to_dict("records")


def load_names() -> dict[str, str]:
    path = RESEARCH_ROOT / "data" / "symbol_name_mapping.csv"
    if not path.exists():
        return {}
    conn = duckdb.connect(":memory:")
    df = conn.execute(
        f"SELECT upper(trim(symbol)) AS stock_code, name FROM read_csv_auto('{str(path).replace("'", "''")}', header=true)"
    ).fetchdf()
    conn.close()
    return {row["stock_code"]: row["name"] for row in df.to_dict("records") if row.get("stock_code")}


def build_outputs(date: str) -> dict:
    rows = load_rows(date)
    names = load_names()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["stock_code"]].append(row)

    view_rows = []
    for stock_code in sorted(grouped):
        name = names.get(stock_code, "")
        display_code = stock_code.split(".")[0]
        symbol = f"{display_code} {name}".strip()
        for row in sorted(grouped[stock_code], key=lambda x: x["sync_date"], reverse=True)[:6]:
            close = float(row["d1_observer_close"])
            mn1 = component_state(
                close,
                row.get("MN1_sr_support"),
                row.get("MN1_sr_resistance"),
                row.get("mn1_observer_trend"),
                row.get("mn1_observer_volatility"),
                row.get("mn1_observer_compression"),
            )
            w1 = component_state(
                close,
                row.get("W_sr_support"),
                row.get("W_sr_resistance"),
                row.get("w1_observer_trend"),
                row.get("w1_observer_volatility"),
                row.get("w1_observer_compression"),
            )
            d1 = component_state(
                close,
                row.get("D_sr_support"),
                row.get("D_sr_resistance"),
                row.get("d1_observer_trend"),
                row.get("d1_observer_volatility"),
                row.get("d1_observer_compression"),
            )
            view_rows.append(
                {
                    "品种": symbol,
                    "时间": f"{row['sync_date']} 15:00:59",
                    "MN1state": mn1["state_hex"],
                    "W1state": w1["state_hex"],
                    "D1state": d1["state_hex"],
                    "_detail": {"MN1": mn1, "W1": w1, "D1": d1},
                }
            )

    public_rows = [{k: v for k, v in row.items() if k != "_detail"} for row in view_rows]
    ymd = date.replace("-", "")
    view_path = ROOT / "fixtures" / f"all_products_d1_view_6_rows_recomputed_{ymd}.json"
    view = {
        "schema_version": "all_products_d1_view_recomputed_sr_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "p116d components + p116b official SR, D1 close perspective",
        "date": date,
        "row_limit_per_symbol": 6,
        "symbol_count": len(grouped),
        "total_rows": len(public_rows),
        "rows": public_rows,
    }
    view_path.write_text(json.dumps(view, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    detail_path = ROOT / "fixtures" / f"all_products_d1_view_recomputed_detail_{ymd}.json"
    detail_path.write_text(
        json.dumps({"rows": view_rows}, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return {
        "view": view_path,
        "detail": detail_path,
        "symbol_count": len(grouped),
        "total_rows": len(public_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    result = build_outputs(args.date)
    print(json.dumps({k: str(v) for k, v in result.items()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
