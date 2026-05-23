#!/usr/bin/env python3
"""Build a forward observation ledger from daily strategy reminders.

This is deliberately not a trading simulator. It records reminder-eligible
strategy signals, their State environment, a reference close, and future return
labels when the data is already available. It does not infer exits, fills,
position sizing, or portfolio actions.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "forward_observation"
PUBLIC_DIR = ROOT / "public"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def code6(value: Any) -> str:
    text = str(value or "").upper().strip()
    digits = "".join(ch for ch in text.split(".", 1)[0] if ch.isdigit())
    return digits[-6:] if digits else text


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def percent(value: Any) -> str:
    val = safe_float(value)
    if val is None:
        return "-"
    return f"{val * 100:.2f}%"


def parse_windows(value: str) -> list[int]:
    windows: list[int] = []
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        window = int(raw)
        if window <= 0:
            raise ValueError(f"window must be positive: {window}")
        if window not in windows:
            windows.append(window)
    if not windows:
        raise ValueError("at least one forward window is required")
    return sorted(windows)


def foundation_db_for(date_str: str, override: str | None) -> Path:
    if override:
        path = Path(override)
        return path if path.is_absolute() else (ROOT / path).resolve()
    exact = ROOT / "outputs" / f"p116_foundation_{ymd(date_str)}" / "p116_foundation.duckdb"
    if exact.exists():
        return exact
    candidates = sorted(ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"))
    if not candidates:
        raise FileNotFoundError("No p116 foundation DB found under outputs/")
    return candidates[-1]


def load_json(path: Path, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_reminder(date_str: str) -> dict[str, Any]:
    path = ROOT / "outputs" / "strategy_reminders" / f"reminder_{ymd(date_str)}.json"
    return load_json(path, required=True)


def load_state_reference_close(date_str: str) -> dict[str, float]:
    path = ROOT / "outputs" / "state_cache" / f"state_ef_{ymd(date_str)}.json"
    payload = load_json(path, required=True)
    out: dict[str, float] = {}
    for row in payload.get("rows", []) or []:
        close = safe_float(row.get("d1_close"))
        if close is not None and close > 0:
            out[code6(row.get("stock_code"))] = close
    return out


def load_price_window(db_path: Path, date_str: str, max_window: int) -> tuple[dict[str, list[tuple[str, float]]], list[str]]:
    start = date.fromisoformat(date_str)
    end = start + timedelta(days=max_window * 3 + 15)
    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute(
        """
        SELECT stock_code, date::VARCHAR AS date, close
        FROM daily_bars
        WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        ORDER BY stock_code, date
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    con.close()

    by_code: dict[str, list[tuple[str, float]]] = defaultdict(list)
    trading_dates: set[str] = set()
    for stock_code, obs_date, close in rows:
        close_val = safe_float(close)
        if close_val is None or close_val <= 0:
            continue
        d = str(obs_date)
        by_code[code6(stock_code)].append((d, close_val))
        trading_dates.add(d)
    return dict(by_code), sorted(trading_dates)


def stock_forward_return(series: list[tuple[str, float]], date_str: str, window: int) -> tuple[float | None, str | None, float | None]:
    if not series:
        return None, None, None
    idx = next((i for i, item in enumerate(series) if item[0] >= date_str), None)
    if idx is None or idx + window >= len(series):
        return None, None, None
    start_close = series[idx][1]
    target_date, target_close = series[idx + window]
    if start_close <= 0:
        return None, None, None
    return target_close / start_close - 1.0, target_date, target_close


def market_equal_weight_return(
    by_code: dict[str, list[tuple[str, float]]],
    date_str: str,
    window: int,
    cache: dict[tuple[str, int], float | None],
) -> float | None:
    key = (date_str, window)
    if key in cache:
        return cache[key]
    values: list[float] = []
    for series in by_code.values():
        ret, _, _ = stock_forward_return(series, date_str, window)
        if ret is not None and math.isfinite(ret):
            values.append(ret)
    if not values:
        cache[key] = None
        return None
    out = statistics.fmean(values)
    cache[key] = out
    return out


def build_observation_rows(
    reminder_payload: dict[str, Any],
    reference_close: dict[str, float],
    by_code: dict[str, list[tuple[str, float]]],
    windows: list[int],
) -> list[dict[str, Any]]:
    date_str = str(reminder_payload.get("date"))
    market_cache: dict[tuple[str, int], float | None] = {}
    rows: list[dict[str, Any]] = []
    for card in reminder_payload.get("reminders", []) or []:
        code = code6(card.get("stock_code"))
        strategy = card.get("strategy") or {}
        state = card.get("state_environment") or {}
        duration = card.get("state_duration") or {}
        evaluation = card.get("strategy_evaluation") or {}
        sr = card.get("sr_position") or {}
        ref_close = reference_close.get(code)
        item: dict[str, Any] = {
            "date": date_str,
            "stock_code": card.get("stock_code"),
            "stock_code_6": code,
            "stock_name": card.get("stock_name"),
            "strategy_id": strategy.get("strategy_id"),
            "signal_type": strategy.get("signal_type"),
            "signal_name": strategy.get("signal_name"),
            "signal_strength": strategy.get("signal_strength"),
            "maturity": card.get("maturity"),
            "lifecycle_stage": card.get("lifecycle_stage"),
            "strategy_environment_fit": card.get("strategy_environment_fit"),
            "fit_reasons": card.get("fit_reasons"),
            "environment_tags": card.get("environment_tags") or [],
            "reference_close": ref_close,
            "mn1_state": state.get("mn1_state"),
            "w1_state": state.get("w1_state"),
            "d1_state": state.get("d1_state"),
            "ef_count": state.get("ef_count"),
            "state_score_sum": state.get("state_score_sum"),
            "d1_ef_duration": duration.get("d1_ef_duration"),
            "all_three_ef_duration": duration.get("all_three_ef_duration"),
            "sr_boundary_direction": sr.get("boundary_direction"),
            "sr_distance_pct": sr.get("distance_pct"),
            "evidence_tier": evaluation.get("evidence_tier"),
            "evidence_score": evaluation.get("evidence_score"),
            "calibration_status": (card.get("calibration") or {}).get("status"),
        }
        missing = False
        for window in windows:
            ret, target_date, target_close = stock_forward_return(by_code.get(code, []), date_str, window)
            bench = market_equal_weight_return(by_code, date_str, window, market_cache)
            item[f"target_date_{window}d"] = target_date
            item[f"target_close_{window}d"] = target_close
            item[f"forward_return_{window}d"] = ret
            item[f"market_equal_weight_return_{window}d"] = bench
            item[f"forward_excess_return_{window}d"] = ret - bench if ret is not None and bench is not None else None
            if ret is None or bench is None:
                missing = True
        item["label_status"] = "pending_future_data" if missing else "labeled"
        rows.append(item)
    return rows


def csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fieldnames})


def generate_html(payload: dict[str, Any], windows: list[int]) -> str:
    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    def tag_text(value: Any) -> str:
        if isinstance(value, list):
            return " / ".join(str(item) for item in value) or "-"
        return str(value or "-")

    def row(item: dict[str, Any]) -> str:
        window_cells = []
        for window in windows:
            ret = item.get(f"forward_return_{window}d")
            excess = item.get(f"forward_excess_return_{window}d")
            target = item.get(f"target_date_{window}d")
            window_cells.append(
                f"<td>{percent(ret)}<br><span>超额 {percent(excess)} {esc(target or '待更新')}</span></td>"
            )
        return f"""
        <tr>
          <td><strong>{esc(item.get("stock_code"))}</strong><br><span>{esc(item.get("stock_name") or "")}</span></td>
          <td>{esc(item.get("strategy_id"))}<br><span>{esc(item.get("signal_name"))}</span></td>
          <td>{esc(item.get("lifecycle_stage") or item.get("maturity"))}<br><span>{esc(item.get("strategy_environment_fit") or "待观察")}</span></td>
          <td>{esc(item.get("fit_reasons") or "-")}<br><span>{esc(tag_text(item.get("environment_tags")))}</span></td>
          <td>MN1 {esc(item.get("mn1_state"))} / W1 {esc(item.get("w1_state"))} / D1 {esc(item.get("d1_state"))}<br><span>ef {esc(item.get("ef_count"))}, all-three {esc(item.get("all_three_ef_duration"))}</span></td>
          <td>{esc(item.get("reference_close"))}<br><span>{esc(item.get("label_status"))}</span></td>
          {''.join(window_cells)}
        </tr>
        """

    headers = "".join(f"<th>{window}日观察</th>" for window in windows)
    rows = "\n".join(row(item) for item in payload.get("rows", []) or [])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>前向观察账本 {esc(payload["date"])}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f8fb; color: #172033; }}
    main {{ max-width: 1440px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 26px; }}
    .meta {{ color: #5d6b82; margin: 0 0 18px; }}
    .guardrails {{ background: #fff; border: 1px solid #e1e6ef; padding: 12px 14px; margin-bottom: 18px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e1e6ef; }}
    th, td {{ text-align: left; vertical-align: top; padding: 10px 12px; border-bottom: 1px solid #edf1f7; font-size: 13px; }}
    th {{ background: #f0f3f8; color: #344054; font-weight: 650; }}
    td span {{ color: #667085; font-size: 12px; }}
    tr:last-child td {{ border-bottom: 0; }}
  </style>
</head>
<body>
  <main>
    <h1>前向观察账本</h1>
    <p class="meta">日期 {esc(payload["date"])} | 样本 {payload["total"]} 条 | 已标注 {payload["labeled"]} 条 | 待更新 {payload["pending"]} 条</p>
    <div class="guardrails">只记录正式提醒信号与后续价格标签；不模拟成交，不推断离场，不生成仓位。</div>
    <table>
      <thead>
        <tr>
          <th>代码</th>
          <th>策略信号</th>
          <th>生命周期/适配</th>
          <th>适配依据</th>
          <th>State</th>
          <th>参考收盘</th>
          {headers}
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </main>
</body>
</html>
"""


def build_forward_observation(
    date_str: str,
    foundation_db: str | None = None,
    windows: list[int] | None = None,
    update_latest: bool = True,
) -> dict[str, Any]:
    windows = windows or [5, 10, 20]
    db_path = foundation_db_for(date_str, foundation_db)
    reminder = load_reminder(date_str)
    reference_close = load_state_reference_close(date_str)
    by_code, trading_dates = load_price_window(db_path, date_str, max(windows))
    rows = build_observation_rows(reminder, reference_close, by_code, windows)
    status_counts = Counter(row.get("label_status") for row in rows)
    strategy_counts = Counter(row.get("strategy_id") for row in rows)

    payload = {
        "schema_version": "forward_observation_v1",
        "mode": "observation_ledger",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "foundation_db": str(db_path),
        "windows": windows,
        "available_trading_dates": trading_dates,
        "total": len(rows),
        "labeled": status_counts.get("labeled", 0),
        "pending": status_counts.get("pending_future_data", 0),
        "status_distribution": dict(sorted(status_counts.items())),
        "strategy_distribution": dict(sorted(strategy_counts.items())),
        "guardrails": [
            "Consumes only strategy reminder rows generated from reminder_eligible signals.",
            "Records reference close and future return labels only when available.",
            "Does not simulate fills, exits, sizing, portfolio turnover, or discretionary decisions.",
            "No advice language is generated.",
        ],
        "rows": rows,
        "research_only": True,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    date_ymd = ymd(date_str)
    json_path = OUT_DIR / f"forward_observation_{date_ymd}.json"
    csv_path = OUT_DIR / f"forward_observation_{date_ymd}.csv"
    html_path = PUBLIC_DIR / f"forward_observation_{date_ymd}.html"
    latest_json = OUT_DIR / "forward_observation_latest.json"
    latest_csv = OUT_DIR / "forward_observation_latest.csv"
    latest_html = PUBLIC_DIR / "forward_observation_latest.html"

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(text, encoding="utf-8")
    write_csv(csv_path, rows)
    html_text = generate_html(payload, windows)
    html_path.write_text(html_text, encoding="utf-8")

    if update_latest:
        latest_json.write_text(text, encoding="utf-8")
        write_csv(latest_csv, rows)
        latest_html.write_text(html_text, encoding="utf-8")

    return {
        "ok": True,
        "mode": "observation_ledger",
        "date": date_str,
        "foundation_db": str(db_path),
        "windows": windows,
        "total": len(rows),
        "labeled": payload["labeled"],
        "pending": payload["pending"],
        "status_distribution": payload["status_distribution"],
        "strategy_distribution": payload["strategy_distribution"],
        "json": str(json_path),
        "csv": str(csv_path),
        "html": str(html_path),
        "latest_json": str(latest_json) if update_latest else None,
        "latest_csv": str(latest_csv) if update_latest else None,
        "latest_html": str(latest_html) if update_latest else None,
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build forward observation ledger from strategy reminders.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--foundation-db")
    parser.add_argument("--windows", default="5,10,20", help="Comma-separated forward windows in trading days.")
    parser.add_argument("--no-update-latest", action="store_true", help="Do not update latest output aliases.")
    args = parser.parse_args()

    result = build_forward_observation(
        args.date,
        foundation_db=args.foundation_db,
        windows=parse_windows(args.windows),
        update_latest=not args.no_update_latest,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
