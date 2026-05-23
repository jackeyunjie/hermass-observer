#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")
DEFAULT_NAMES_CSV = RESEARCH_ROOT / "data" / "symbol_name_mapping.csv"
SNAPSHOT_FIELDS = [
    "rank",
    "stock_code",
    "symbol",
    "stock_name",
    "sw_l1",
    "sw_l2",
    "sw_l3",
    "date",
    "d1_close",
    "state_score_sum",
    "ef_strength",
    "mn1_state",
    "w1_state",
    "d1_state",
    "mn1_score",
    "w1_score",
    "d1_score",
    "mn1_sr_support",
    "mn1_sr_resistance",
    "w1_sr_support",
    "w1_sr_resistance",
    "d1_sr_support",
    "d1_sr_resistance",
    "mn1_breakout",
    "w1_breakout",
    "d1_breakout",
    "d1_trend",
    "d1_compression",
    "d1_volatility",
    "d1_adx14",
    "d1_plus_di_14",
    "d1_minus_di_14",
    "mn1_trend",
    "w1_trend",
    "d1_atr_ratio_pct",
    "w1_close",
    "w1_prev_close",
    "w1_prev2_close",
    "w1_down_3bars",
    "w1_ama10",
    "w1_close_above_ama10",
    "quality_gate_pass",
    "quality_flags",
]
DIFF_FIELDS = [
    "change_type",
    "rank",
    "stock_code",
    "symbol",
    "stock_name",
    "sw_l1",
    "sw_l2",
    "sw_l3",
    "date",
    "previous_date",
    "d1_close",
    "state_score_sum",
    "mn1_state",
    "w1_state",
    "d1_state",
    "mn1_score",
    "w1_score",
    "d1_score",
]


def default_foundation_db(date_str: str) -> Path:
    return ROOT / "outputs" / f"p116_foundation_{date_str.replace('-', '')}" / "p116_foundation.duckdb"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def to_jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def clean_float(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        return round(value, 6)
    return value


def load_symbol_meta(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    meta: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = (row.get("symbol") or "").strip()
            if not symbol:
                continue
            meta[symbol] = {
                "stock_name": (row.get("name") or "").strip(),
                "sw_l1": (row.get("sw_l1") or "").strip(),
                "sw_l2": (row.get("sw_l2") or "").strip(),
                "sw_l3": (row.get("sw_l3") or "").strip(),
            }
    return meta


def fetch_all_three_ef(db_path: Path, date_str: str, names_csv: Path, apply_quality_gate: bool) -> list[dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"foundation DB not found: {db_path}")

    con = duckdb.connect(str(db_path), read_only=True)
    result = con.execute(
        """
        WITH w1_quality AS (
          SELECT
            stock_code,
            period_start,
            close AS w1_close,
            lag(close, 1) OVER w AS w1_prev_close,
            lag(close, 2) OVER w AS w1_prev2_close,
            avg(close) OVER (
              PARTITION BY stock_code ORDER BY period_start ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
            ) AS w1_ama10
          FROM weekly_bars
          WINDOW w AS (PARTITION BY stock_code ORDER BY period_start)
        ),
        candidate AS (
          SELECT
            s.*,
            q.w1_close,
            q.w1_prev_close,
            q.w1_prev2_close,
            q.w1_ama10,
            (q.w1_close < q.w1_prev_close AND q.w1_prev_close < q.w1_prev2_close) AS w1_down_3bars,
            (q.w1_close >= q.w1_ama10) AS w1_close_above_ama10,
            (
              NOT coalesce((q.w1_close < q.w1_prev_close AND q.w1_prev_close < q.w1_prev2_close), false)
              AND coalesce((q.w1_close >= q.w1_ama10), true)
            ) AS quality_gate_pass,
            concat_ws(
              ';',
              CASE WHEN (q.w1_close < q.w1_prev_close AND q.w1_prev_close < q.w1_prev2_close) THEN 'W1连续3根收盘下跌' ELSE NULL END,
              CASE WHEN NOT coalesce((q.w1_close >= q.w1_ama10), true) THEN 'W1收盘低于AMA10' ELSE NULL END
            ) AS quality_flags,
            (CASE s.d1_state_hex WHEN 'F' THEN 2 WHEN 'E' THEN 1 ELSE 0 END
             + CASE s.w1_state_hex WHEN 'F' THEN 2 WHEN 'E' THEN 1 ELSE 0 END
             + CASE s.mn1_state_hex WHEN 'F' THEN 2 WHEN 'E' THEN 1 ELSE 0 END) AS ef_strength,
            (coalesce(s.d1_state_score, 0) + coalesce(s.w1_state_score, 0) + coalesce(s.mn1_state_score, 0)) AS state_score_sum
          FROM d1_perspective_state s
          LEFT JOIN w1_quality q
            ON q.stock_code = s.stock_code AND q.period_start = s.w1_period_start
          WHERE s.state_date = CAST(? AS DATE)
            AND s.mn1_state_hex IN ('E', 'F')
            AND s.w1_state_hex IN ('E', 'F')
            AND s.d1_state_hex IN ('E', 'F')
            AND (
              ? = false
              OR (
                NOT coalesce((q.w1_close < q.w1_prev_close AND q.w1_prev_close < q.w1_prev2_close), false)
                AND coalesce((q.w1_close >= q.w1_ama10), true)
              )
            )
        )
        SELECT
          row_number() OVER (
            ORDER BY state_score_sum DESC, ef_strength DESC, d1_adx14 DESC NULLS LAST, stock_code ASC
          ) AS rank,
          stock_code AS symbol,
          CAST(state_date AS VARCHAR) AS date,
          d1_close,
          state_score_sum,
          ef_strength,
          mn1_state_hex AS mn1_state,
          w1_state_hex AS w1_state,
          d1_state_hex AS d1_state,
          mn1_state_score AS mn1_score,
          w1_state_score AS w1_score,
          d1_state_score AS d1_score,
          mn1_sr_support,
          mn1_sr_resistance,
          w1_sr_support,
          w1_sr_resistance,
          d1_sr_support,
          d1_sr_resistance,
          (d1_close > mn1_sr_resistance) AS mn1_breakout,
          (d1_close > w1_sr_resistance) AS w1_breakout,
          (d1_close > d1_sr_resistance) AS d1_breakout,
          d1_trend,
          d1_compression,
          d1_volatility,
          d1_adx14,
          d1_plus_di_14,
          d1_minus_di_14,
          mn1_trend,
          w1_trend,
          d1_atr_ratio_pct,
          w1_close,
          w1_prev_close,
          w1_prev2_close,
          w1_down_3bars,
          w1_ama10,
          w1_close_above_ama10,
          quality_gate_pass,
          quality_flags
        FROM candidate
        ORDER BY rank
        """,
        [date_str, apply_quality_gate],
    )
    columns = [desc[0] for desc in result.description]
    rows = [dict(zip(columns, row)) for row in result.fetchall()]
    con.close()

    meta = load_symbol_meta(names_csv)
    output: list[dict[str, Any]] = []
    for row in rows:
        symbol = row["symbol"]
        info = meta.get(symbol, {})
        record = {
            "rank": int(row["rank"]),
            "stock_code": str(symbol).split(".")[0],
            "symbol": symbol,
            "stock_name": info.get("stock_name", ""),
            "sw_l1": info.get("sw_l1", ""),
            "sw_l2": info.get("sw_l2", ""),
            "sw_l3": info.get("sw_l3", ""),
        }
        for field in SNAPSHOT_FIELDS:
            if field in record:
                continue
            record[field] = clean_float(to_jsonable(row.get(field)))
        output.append(record)
    return output


def read_snapshot(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_previous_snapshot(out_dir: Path, current_date: str) -> Path | None:
    candidates: list[tuple[str, Path]] = []
    for path in out_dir.glob("p116_all_three_ef_*.json"):
        stem_date = path.stem.replace("p116_all_three_ef_", "")
        if len(stem_date) != 8 or not stem_date.isdigit():
            continue
        normalized = f"{stem_date[:4]}-{stem_date[4:6]}-{stem_date[6:]}"
        if normalized < current_date:
            candidates.append((normalized, path))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0])[-1][1]


def build_diff(current_rows: list[dict[str, Any]], previous_payload: dict[str, Any] | None) -> dict[str, Any]:
    current_by_symbol = {row["symbol"]: row for row in current_rows}
    previous_rows = previous_payload.get("rows", []) if previous_payload else []
    previous_by_symbol = {row["symbol"]: row for row in previous_rows}
    previous_date = previous_payload.get("date") if previous_payload else None

    entered_symbols = sorted(set(current_by_symbol) - set(previous_by_symbol))
    left_symbols = sorted(set(previous_by_symbol) - set(current_by_symbol))
    stayed_symbols = sorted(set(current_by_symbol) & set(previous_by_symbol))

    rows: list[dict[str, Any]] = []
    for symbol in entered_symbols:
        rows.append(diff_row("entered", current_by_symbol[symbol], previous_date))
    for symbol in left_symbols:
        rows.append(diff_row("left", previous_by_symbol[symbol], previous_date))
    for symbol in stayed_symbols:
        rows.append(diff_row("stayed", current_by_symbol[symbol], previous_date))

    return {
        "previous_date": previous_date,
        "entered": [current_by_symbol[s] for s in entered_symbols],
        "left": [previous_by_symbol[s] for s in left_symbols],
        "stayed": [current_by_symbol[s] for s in stayed_symbols],
        "rows": rows,
    }


def diff_row(change_type: str, row: dict[str, Any], previous_date: str | None) -> dict[str, Any]:
    return {
        "change_type": change_type,
        "rank": row.get("rank"),
        "stock_code": row.get("stock_code"),
        "symbol": row.get("symbol"),
        "stock_name": row.get("stock_name"),
        "sw_l1": row.get("sw_l1"),
        "sw_l2": row.get("sw_l2"),
        "sw_l3": row.get("sw_l3"),
        "date": row.get("date"),
        "previous_date": previous_date or "",
        "d1_close": row.get("d1_close"),
        "state_score_sum": row.get("state_score_sum"),
        "mn1_state": row.get("mn1_state"),
        "w1_state": row.get("w1_state"),
        "d1_state": row.get("d1_state"),
        "mn1_score": row.get("mn1_score"),
        "w1_score": row.get("w1_score"),
        "d1_score": row.get("d1_score"),
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def html_table(rows: list[dict[str, Any]], fields: list[str], row_limit: int | None = None) -> str:
    visible = rows if row_limit is None else rows[:row_limit]
    head = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
    body_rows = []
    for row in visible:
        cells = "".join(f"<td>{html.escape(str(row.get(field, '') if row.get(field, '') is not None else ''))}</td>" for field in fields)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def industry_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        key = row.get("sw_l1") or "未分类"
        counts[key] = counts.get(key, 0) + 1
    return [
        {"industry": industry, "count": count}
        for industry, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def write_snapshot_html(path: Path, date_str: str, rows: list[dict[str, Any]], csv_name: str) -> None:
    industries = industry_summary(rows)[:12]
    industry_cards = "".join(
        f"<div class='kpi'><small>{html.escape(item['industry'])}</small><strong>{item['count']}</strong></div>"
        for item in industries
    )
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>P116 三周期全 E/F 清单 - {html.escape(date_str)}</title>
  <style>
    body {{ margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; color: #17212b; background: #f6f8f7; }}
    header, section {{ background: #fff; border: 1px solid #dce4df; border-radius: 8px; padding: 20px; margin-bottom: 18px; }}
    h1 {{ margin: 0 0 8px; font-size: 26px; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    p {{ color: #526071; line-height: 1.55; }}
    a {{ color: #0f6b4b; font-weight: 700; text-decoration: none; }}
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }}
    .kpi {{ border: 1px solid #dce4df; border-radius: 8px; padding: 12px; }}
    .kpi small {{ color: #677486; }}
    .kpi strong {{ display: block; margin-top: 6px; font-size: 22px; }}
    .table-wrap {{ overflow: auto; max-height: 78vh; border: 1px solid #dce4df; }}
    table {{ border-collapse: collapse; width: 100%; min-width: 1900px; font-size: 12px; background: #fff; }}
    th, td {{ border-bottom: 1px solid #e3e9e5; border-right: 1px solid #e3e9e5; padding: 7px 8px; text-align: left; white-space: nowrap; }}
    th {{ position: sticky; top: 0; z-index: 1; background: #eef4f1; }}
    td:nth-child(12), td:nth-child(13), td:nth-child(14) {{ font-weight: 700; color: #0f766e; }}
  </style>
</head>
<body>
  <header>
    <h1>P116 三周期全 E/F 清单 - {html.escape(date_str)}</h1>
    <p>标准筛选：MN1、W1、D1 三个周期 state 全部为 E/F；不限制 100 只。排序：三周期分数合计、E/F 强度、D1 ADX、代码。</p>
    <p><a href="{html.escape(csv_name)}" download>下载 CSV</a></p>
  </header>
  <section>
    <h2>概览</h2>
    <div class="kpis">
      <div class="kpi"><small>全三周期 E/F</small><strong>{len(rows)}</strong></div>
      {industry_cards}
    </div>
  </section>
  <section>
    <h2>完整清单</h2>
    <div class="table-wrap">{html_table(rows, SNAPSHOT_FIELDS)}</div>
  </section>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")


def write_diff_html(path: Path, date_str: str, diff: dict[str, Any], csv_name: str) -> None:
    previous_date = diff["previous_date"] or "无上一版"
    sections = [
        ("新进入", "entered", diff["entered"]),
        ("离开", "left", diff["left"]),
        ("留存", "stayed", diff["stayed"]),
    ]
    tables = []
    for title, key, rows in sections:
        tables.append(
            f"<section><h2>{title} ({len(rows)})</h2><div class='table-wrap'>{html_table(rows, SNAPSHOT_FIELDS)}</div></section>"
        )
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>P116 三周期全 E/F 变动 - {html.escape(date_str)}</title>
  <style>
    body {{ margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; color: #17212b; background: #f6f8f7; }}
    header, section {{ background: #fff; border: 1px solid #dce4df; border-radius: 8px; padding: 20px; margin-bottom: 18px; }}
    h1 {{ margin: 0 0 8px; font-size: 26px; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    p {{ color: #526071; line-height: 1.55; }}
    a {{ color: #0f6b4b; font-weight: 700; text-decoration: none; }}
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }}
    .kpi {{ border: 1px solid #dce4df; border-radius: 8px; padding: 12px; }}
    .kpi small {{ color: #677486; }}
    .kpi strong {{ display: block; margin-top: 6px; font-size: 22px; }}
    .table-wrap {{ overflow: auto; max-height: 52vh; border: 1px solid #dce4df; }}
    table {{ border-collapse: collapse; width: 100%; min-width: 1900px; font-size: 12px; background: #fff; }}
    th, td {{ border-bottom: 1px solid #e3e9e5; border-right: 1px solid #e3e9e5; padding: 7px 8px; text-align: left; white-space: nowrap; }}
    th {{ position: sticky; top: 0; z-index: 1; background: #eef4f1; }}
  </style>
</head>
<body>
  <header>
    <h1>P116 三周期全 E/F 变动 - {html.escape(date_str)}</h1>
    <p>对比基准：{html.escape(previous_date)}。口径：每天最新 state 中 MN1/W1/D1 全部为 E/F 的完整品种集合。</p>
    <p><a href="{html.escape(csv_name)}" download>下载变动 CSV</a></p>
  </header>
  <section>
    <h2>变动概览</h2>
    <div class="kpis">
      <div class="kpi"><small>新进入</small><strong>{len(diff['entered'])}</strong></div>
      <div class="kpi"><small>离开</small><strong>{len(diff['left'])}</strong></div>
      <div class="kpi"><small>留存</small><strong>{len(diff['stayed'])}</strong></div>
    </div>
  </section>
  {''.join(tables)}
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=to_jsonable) + "\n", encoding="utf-8")


def copy_text(src: Path, dst: Path) -> None:
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def export(args: argparse.Namespace) -> dict[str, Any]:
    date_str = args.date
    db_path = args.foundation_db or default_foundation_db(date_str)
    out_dir = args.out_dir
    public_dir = args.public_dir
    rows = fetch_all_three_ef(db_path, date_str, args.names_csv, not args.no_quality_gate)

    snapshot_json = out_dir / f"p116_all_three_ef_{ymd(date_str)}.json"
    snapshot_csv = out_dir / f"p116_all_three_ef_{ymd(date_str)}.csv"
    public_html = public_dir / f"p116_all_three_ef_{ymd(date_str)}.html"
    public_csv = public_dir / f"p116_all_three_ef_{ymd(date_str)}.csv"

    payload = {
        "schema_version": "p116_all_three_ef_snapshot_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": date_str,
        "source_duckdb": str(db_path),
        "screening_rule": "mn1_state_hex,w1_state_hex,d1_state_hex all in E/F",
        "quality_gate": "exclude W1 3-bar close decline and W1 close below AMA10" if not args.no_quality_gate else "disabled",
        "rank_rule": "state_score_sum desc, ef_strength desc, d1_adx14 desc, stock_code asc",
        "total": len(rows),
        "rows": rows,
    }
    write_json(snapshot_json, payload)
    write_csv(snapshot_csv, rows, SNAPSHOT_FIELDS)
    write_csv(public_csv, rows, SNAPSHOT_FIELDS)
    write_snapshot_html(public_html, date_str, rows, public_csv.name)

    previous_payload = None
    previous_path = None
    if args.previous_date:
        candidate = out_dir / f"p116_all_three_ef_{ymd(args.previous_date)}.json"
        if candidate.exists():
            previous_path = candidate
            previous_payload = read_snapshot(candidate)
    else:
        previous_path = find_previous_snapshot(out_dir, date_str)
        if previous_path:
            previous_payload = read_snapshot(previous_path)

    diff = build_diff(rows, previous_payload)
    diff_payload = {
        "schema_version": "p116_all_three_ef_diff_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": date_str,
        "previous_date": diff["previous_date"],
        "source_snapshot": str(snapshot_json),
        "previous_snapshot": str(previous_path) if previous_path else None,
        "entered_count": len(diff["entered"]),
        "left_count": len(diff["left"]),
        "stayed_count": len(diff["stayed"]),
        "entered": diff["entered"],
        "left": diff["left"],
        "stayed": diff["stayed"],
    }
    diff_json = out_dir / f"p116_all_three_ef_diff_{ymd(date_str)}.json"
    diff_csv = out_dir / f"p116_all_three_ef_diff_{ymd(date_str)}.csv"
    public_diff_html = public_dir / f"p116_all_three_ef_diff_{ymd(date_str)}.html"
    public_diff_csv = public_dir / f"p116_all_three_ef_diff_{ymd(date_str)}.csv"
    write_json(diff_json, diff_payload)
    write_csv(diff_csv, diff["rows"], DIFF_FIELDS)
    write_csv(public_diff_csv, diff["rows"], DIFF_FIELDS)
    write_diff_html(public_diff_html, date_str, diff, public_diff_csv.name)

    latest_html = public_dir / "p116_all_three_ef_latest.html"
    latest_diff_html = public_dir / "p116_all_three_ef_diff_latest.html"
    copy_text(public_html, latest_html)
    copy_text(public_diff_html, latest_diff_html)

    return {
        "date": date_str,
        "total": len(rows),
        "entered": len(diff["entered"]),
        "left": len(diff["left"]),
        "stayed": len(diff["stayed"]),
        "previous_date": diff["previous_date"],
        "snapshot_json": str(snapshot_json),
        "snapshot_csv": str(snapshot_csv),
        "public_html": str(public_html),
        "public_csv": str(public_csv),
        "diff_json": str(diff_json),
        "diff_csv": str(diff_csv),
        "public_diff_html": str(public_diff_html),
        "public_diff_csv": str(public_diff_csv),
        "latest_html": str(latest_html),
        "latest_diff_html": str(latest_diff_html),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export daily P116 all-three E/F snapshot and membership diff.")
    parser.add_argument("--date", required=True, help="Trading date, e.g. 2026-05-20")
    parser.add_argument("--foundation-db", type=Path, help="Foundation DuckDB. Defaults to outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb")
    parser.add_argument("--previous-date", help="Previous snapshot date to compare, e.g. 2026-05-19")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "outputs" / "p116_daily_all_three_ef")
    parser.add_argument("--public-dir", type=Path, default=ROOT / "public")
    parser.add_argument("--names-csv", type=Path, default=DEFAULT_NAMES_CSV)
    parser.add_argument("--no-quality-gate", action="store_true", help="Disable W1 decline / AMA quality filters.")
    args = parser.parse_args()

    summary = export(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
