#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.engine import load_state_data_from_duckdb
from backtest.strategy_signals.composite import selection_evidence_signal


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def foundation_path(date_str: str) -> Path:
    return ROOT / "outputs" / f"p116_foundation_{ymd(date_str)}" / "p116_foundation.duckdb"


def pool_path(date_str: str) -> Path:
    return ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_{ymd(date_str)}.json"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def code_keys(value: Any) -> set[str]:
    text = str(value or "").strip().upper()
    if not text:
        return set()
    digits = "".join(ch for ch in text.split(".", 1)[0] if ch.isdigit())
    keys = {text}
    if digits:
        keys.add(digits[-6:])
    return keys


def load_pool(date_str: str) -> list[dict[str, Any]]:
    path = pool_path(date_str)
    if not path.exists():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("rows", [])


def signal_text(result: dict[str, Any] | None, strategy_name: str) -> str:
    if not result:
        return ""
    item = result.get("details", {}).get(strategy_name, {})
    return item.get("signal") or ""


def build_rows(date_str: str, foundation_db: Path, lookback_days: int) -> list[dict[str, Any]]:
    pool = load_pool(date_str)
    target_codes: set[str] = set()
    for row in pool:
        target_codes.update(code_keys(row.get("stock_code")))
        target_codes.update(code_keys(row.get("symbol")))
    start = (date.fromisoformat(date_str) - timedelta(days=lookback_days * 2)).isoformat()
    state_by_date = load_state_data_from_duckdb(foundation_db, start, date_str)

    history_by_code: dict[str, list[dict[str, Any]]] = {}
    for trade_date in sorted(state_by_date):
        for row in state_by_date[trade_date]:
            keys = code_keys(row.get("stock_code"))
            if keys & target_codes:
                for key in keys:
                    history_by_code.setdefault(key, []).append(row)

    out: list[dict[str, Any]] = []
    for pool_row in pool:
        code = pool_row.get("stock_code")
        symbol = pool_row.get("symbol")
        history: list[dict[str, Any]] = []
        for key in [*code_keys(symbol), *code_keys(code)]:
            history = history_by_code.get(key, [])
            if history:
                break
        history = history[-lookback_days:]
        latest_state = history[-1] if history else {}
        latest_result = selection_evidence_signal(latest_state, latest_state) if latest_state else None

        last_vcp = ""
        last_2560 = ""
        vcp_hits = 0
        ma_hits = 0
        best_signal = ""
        best_score = 0.0
        evidence_dates: list[str] = []

        for item in history:
            result = selection_evidence_signal(item, item)
            if not result:
                continue
            vcp_sig = signal_text(result, "vcp")
            ma_sig = signal_text(result, "ma2560")
            if vcp_sig:
                vcp_hits += 1
                last_vcp = f"{item.get('date')}:{vcp_sig}"
            if ma_sig:
                ma_hits += 1
                last_2560 = f"{item.get('date')}:{ma_sig}"
            label = result.get("entry_type") or ""
            score = safe_float(result.get("composite_confidence"))
            if score >= best_score:
                best_score = score
                best_signal = label
            evidence_dates.append(str(item.get("date")))

        latest_vcp = signal_text(latest_result, "vcp")
        latest_2560 = signal_text(latest_result, "ma2560")
        strategy_score = round(best_score * 100 + min(vcp_hits + ma_hits, 5) * 2, 2)
        notes = []
        if latest_vcp:
            notes.append(f"最新VCP={latest_vcp}")
        if latest_2560:
            notes.append(f"最新2560={latest_2560}")
        if last_vcp and not latest_vcp:
            notes.append(f"近{lookback_days}日VCP线索={last_vcp}")
        if last_2560 and not latest_2560:
            notes.append(f"近{lookback_days}日2560线索={last_2560}")
        if not notes:
            notes.append("近窗口未出现VCP/2560形态线索")

        out.append(
            {
                "rank": pool_row.get("rank"),
                "stock_code": code,
                "symbol": symbol,
                "stock_name": pool_row.get("stock_name"),
                "sw_l1": pool_row.get("sw_l1"),
                "sw_l2": pool_row.get("sw_l2"),
                "date": date_str,
                "state": f"{pool_row.get('mn1_state')}/{pool_row.get('w1_state')}/{pool_row.get('d1_state')}",
                "state_score_sum": pool_row.get("state_score_sum"),
                "d1_close": pool_row.get("d1_close"),
                "strategy_score": strategy_score,
                "best_selection_signal": best_signal,
                "latest_vcp_signal": latest_vcp,
                "latest_2560_signal": latest_2560,
                "vcp_hits_lookback": vcp_hits,
                "ma2560_hits_lookback": ma_hits,
                "last_vcp_signal": last_vcp,
                "last_2560_signal": last_2560,
                "evidence_dates": ",".join(evidence_dates[-5:]),
                "selection_note": "；".join(notes),
                "exit_options": "布林强盗动态递减MA；ATR吊灯",
                "exit_note": "离场提醒需要持仓入场日/入场价；不参与入选排序。",
            }
        )

    out.sort(key=lambda r: (-safe_float(r["strategy_score"]), int(r["rank"] or 999999)))
    for idx, row in enumerate(out, 1):
        row["strategy_rank"] = idx
    return out


def write_outputs(
    rows: list[dict[str, Any]], date_str: str, foundation_db: Path, lookback_days: int
) -> dict[str, Any]:
    out_dir = ROOT / "outputs" / "strategy_evidence"
    public_dir = ROOT / "public"
    out_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"strategy_evidence_{ymd(date_str)}.json"
    csv_path = out_dir / f"strategy_evidence_{ymd(date_str)}.csv"
    html_path = public_dir / f"strategy_evidence_{ymd(date_str)}.html"
    latest_html = public_dir / "strategy_evidence_latest.html"

    payload = {
        "schema_version": "strategy_evidence_v1",
        "date": date_str,
        "foundation_db": str(foundation_db),
        "lookback_days": lookback_days,
        "selection_scope": "P116 all-three E/F pool",
        "selection_strategies": ["VCP", "2560"],
        "classic_strategy_options": ["Bollinger Bandit", "ATR Chandelier Exit"],
        "classic_strategy_note": "完整经典策略保留用于回测/建议选项；布林强盗和ATR吊灯在本表只作为离场提醒选项。",
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    fields = [
        "strategy_rank",
        "rank",
        "stock_code",
        "symbol",
        "stock_name",
        "sw_l1",
        "sw_l2",
        "date",
        "state",
        "state_score_sum",
        "d1_close",
        "strategy_score",
        "best_selection_signal",
        "latest_vcp_signal",
        "latest_2560_signal",
        "vcp_hits_lookback",
        "ma2560_hits_lookback",
        "last_vcp_signal",
        "last_2560_signal",
        "selection_note",
        "exit_options",
        "exit_note",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    html_text = render_html(payload, rows, fields)
    html_path.write_text(html_text, encoding="utf-8")
    latest_html.write_text(html_text, encoding="utf-8")
    return {
        "json": str(json_path),
        "csv": str(csv_path),
        "html": str(html_path),
        "latest_html": str(latest_html),
        "rows": len(rows),
    }


def render_html(payload: dict[str, Any], rows: list[dict[str, Any]], fields: list[str]) -> str:
    head = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
    body = []
    for row in rows:
        body.append(
            "<tr>" + "".join(f"<td>{html.escape(str(row.get(field, '')))}</td>" for field in fields) + "</tr>"
        )
    strong = sum(1 for row in rows if safe_float(row.get("strategy_score")) >= 60)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>策略证据表 - {html.escape(payload["date"])}</title>
  <style>
    body {{ margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; color: #17212b; background: #f7f8f6; }}
    header, section {{ background: #fff; border: 1px solid #dce4df; border-radius: 8px; padding: 18px; margin-bottom: 16px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    p {{ color: #526071; line-height: 1.55; }}
    .kpis {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    .kpi {{ border: 1px solid #dce4df; border-radius: 8px; padding: 10px 12px; min-width: 150px; }}
    .kpi small {{ color: #64748b; display: block; }}
    .kpi strong {{ font-size: 22px; }}
    .table-wrap {{ overflow: auto; border: 1px solid #dce4df; max-height: 78vh; }}
    table {{ border-collapse: collapse; min-width: 1800px; width: 100%; font-size: 12px; }}
    th, td {{ border-bottom: 1px solid #e3e9e5; border-right: 1px solid #e3e9e5; padding: 7px 8px; text-align: left; white-space: nowrap; }}
    th {{ position: sticky; top: 0; background: #eef4f1; z-index: 1; }}
    td:nth-child(12), td:nth-child(13), td:nth-child(14), td:nth-child(15) {{ color: #0f766e; font-weight: 700; }}
  </style>
</head>
<body>
  <header>
    <h1>策略证据表 - {html.escape(payload["date"])}</h1>
    <p>范围：P116 三周期 E/F 股票池。VCP 和 2560 用于入选组合观察增强；布林强盗与 ATR 吊灯保留为完整经典策略/离场提醒选项。</p>
    <div class="kpis">
      <div class="kpi"><small>股票数</small><strong>{len(rows)}</strong></div>
      <div class="kpi"><small>策略证据强</small><strong>{strong}</strong></div>
      <div class="kpi"><small>回看交易日</small><strong>{payload["lookback_days"]}</strong></div>
    </div>
  </header>
  <section>
    <div class="table-wrap">
      <table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>
    </div>
  </section>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build VCP/2560 strategy evidence for the P116 stock pool.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--foundation-db", type=Path)
    parser.add_argument("--lookback-days", type=int, default=20)
    args = parser.parse_args()
    db = args.foundation_db or foundation_path(args.date)
    if not db.exists():
        raise FileNotFoundError(db)
    rows = build_rows(args.date, db, args.lookback_days)
    print(json.dumps(write_outputs(rows, args.date, db, args.lookback_days), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
