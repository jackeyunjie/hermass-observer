#!/usr/bin/env python3
"""Analyze forward outcomes for ma2560_strong_hold by market match level.

This report intentionally reads the full strategy signal ledger, not the daily
reminder brief. `ma2560_strong_hold` is a structure signal and is usually kept
in the research scope, so reminder-only ledgers would undercount the sample.
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
LEDGER_DB = ROOT / "outputs" / "strategy_signals" / "strategy_signals.duckdb"
OUT_DIR = ROOT / "outputs" / "ma2560_market_match_forward"
PUBLIC_DIR = ROOT / "public"
LEVEL_ORDER = ["full_match", "stock_only", "market_unsupported", "not_match"]
LEVEL_LABELS = {
    "full_match": "full_match 个股匹配 + 行业ETF共振",
    "stock_only": "stock_only 个股匹配，行业ETF数据缺失",
    "market_unsupported": "market_unsupported 个股匹配，行业ETF未共振",
    "not_match": "not_match 个股 State 组合不在适配区间",
}


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def code6(value: Any) -> str:
    text = str(value or "").upper().strip()
    digits = "".join(ch for ch in text.split(".", 1)[0] if ch.isdigit())
    return digits[-6:] if digits else text


def pct(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def default_foundation_db(as_of_date: str) -> Path:
    exact = ROOT / "outputs" / f"p116_foundation_{ymd(as_of_date)}" / "p116_foundation.duckdb"
    if exact.exists():
        return exact
    candidates = sorted(ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"))
    if not candidates:
        raise FileNotFoundError("No foundation DB found under outputs/")
    return candidates[-1]


def load_signals(signal_date: str, ledger_db: Path = LEDGER_DB) -> list[dict[str, Any]]:
    con = duckdb.connect(str(ledger_db), read_only=True)
    rows = con.execute(
        """
        SELECT
          signal_date::VARCHAR AS signal_date,
          stock_code,
          stock_name,
          signal_name,
          signal_strength,
          lifecycle_stage,
          strategy_environment_fit,
          fit_reasons,
          ma2560_local_combo_pass,
          ma2560_p116_state_match,
          ma2560_market_match_level,
          ma2560_state_combo
        FROM strategy_signal_daily
        WHERE signal_date = CAST(? AS DATE)
          AND strategy_id = 'ma2560'
          AND raw_signal = 'ma2560_strong_hold'
        ORDER BY ma2560_market_match_level, stock_code
        """,
        (signal_date,),
    ).fetchall()
    cols = [desc[0] for desc in con.description]
    con.close()
    return [dict(zip(cols, row)) for row in rows]


def load_price_window(
    foundation_db: Path,
    codes: set[str],
    signal_date: str,
    max_window: int,
) -> tuple[dict[str, list[tuple[str, float]]], dict[int, float | None], list[str]]:
    if not codes:
        return {}, {}, []
    start = date.fromisoformat(signal_date)
    end = start + timedelta(days=max_window * 3 + 20)
    con = duckdb.connect(str(foundation_db), read_only=True)
    placeholders = ",".join(["?"] * len(codes))
    rows = con.execute(
        f"""
        SELECT stock_code, date::VARCHAR AS date, close
        FROM daily_bars
        WHERE stock_code IN ({placeholders})
          AND date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        ORDER BY stock_code, date
        """,
        (*sorted(codes), signal_date, end.isoformat()),
    ).fetchall()
    all_rows = con.execute(
        """
        SELECT stock_code, date::VARCHAR AS date, close
        FROM daily_bars
        WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        ORDER BY stock_code, date
        """,
        (signal_date, end.isoformat()),
    ).fetchall()
    con.close()

    by_code: dict[str, list[tuple[str, float]]] = defaultdict(list)
    trading_dates: set[str] = set()
    for stock_code, obs_date, close in rows:
        close_val = safe_float(close)
        if close_val is None or close_val <= 0:
            continue
        d = str(obs_date)
        by_code[str(stock_code)].append((d, close_val))
        trading_dates.add(d)

    all_by_code: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for stock_code, obs_date, close in all_rows:
        close_val = safe_float(close)
        if close_val is None or close_val <= 0:
            continue
        all_by_code[str(stock_code)].append((str(obs_date), close_val))
        trading_dates.add(str(obs_date))

    benchmark_by_window: dict[int, float | None] = {}
    for window in [5, 10, 20]:
        values: list[float] = []
        for series in all_by_code.values():
            ret, _, _ = forward_return(series, signal_date, window)
            if ret is not None:
                values.append(ret)
        benchmark_by_window[window] = statistics.fmean(values) if values else None
    return dict(by_code), benchmark_by_window, sorted(trading_dates)


def forward_return(series: list[tuple[str, float]], signal_date: str, window: int) -> tuple[float | None, str | None, float | None]:
    idx = next((i for i, item in enumerate(series) if item[0] >= signal_date), None)
    if idx is None or idx + window >= len(series):
        return None, None, None
    start_close = series[idx][1]
    target_date, target_close = series[idx + window]
    if start_close <= 0 or target_close <= 0:
        return None, None, None
    return target_close / start_close - 1.0, target_date, target_close


def build_rows(signals: list[dict[str, Any]], prices: dict[str, list[tuple[str, float]]], benchmarks: dict[int, float | None]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for signal in signals:
        code = str(signal.get("stock_code") or "")
        series = prices.get(code, [])
        reference_close = series[0][1] if series else None
        item = {
            **signal,
            "stock_code_6": code6(code),
            "reference_close": reference_close,
        }
        for window in [5, 10, 20]:
            ret, target_date, target_close = forward_return(series, str(signal.get("signal_date")), window)
            bench = benchmarks.get(window)
            item[f"target_date_{window}d"] = target_date
            item[f"target_close_{window}d"] = target_close
            item[f"forward_return_{window}d"] = ret
            item[f"market_equal_weight_return_{window}d"] = bench
            item[f"forward_excess_return_{window}d"] = ret - bench if ret is not None and bench is not None else None
        item["label_status"] = (
            "labeled"
            if all(item.get(f"forward_return_{window}d") is not None for window in [5, 10, 20])
            else "pending_future_data"
        )
        rows.append(item)
    return rows


def group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for level in LEVEL_ORDER:
        items = [row for row in rows if (row.get("ma2560_market_match_level") or "not_match") == level]
        data: dict[str, Any] = {"count": len(items)}
        for window in [5, 10, 20]:
            rets = [row.get(f"forward_return_{window}d") for row in items if row.get(f"forward_return_{window}d") is not None]
            excess = [row.get(f"forward_excess_return_{window}d") for row in items if row.get(f"forward_excess_return_{window}d") is not None]
            data[f"labeled_{window}d"] = len(rets)
            data[f"avg_return_{window}d"] = statistics.fmean(rets) if rets else None
            data[f"win_rate_{window}d"] = sum(1 for val in rets if val > 0) / len(rets) if rets else None
            data[f"avg_excess_{window}d"] = statistics.fmean(excess) if excess else None
            data[f"excess_win_rate_{window}d"] = sum(1 for val in excess if val > 0) / len(excess) if excess else None
        out[level] = data
    return out


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
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fieldnames})


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# 2560 State / 市场匹配前向观察",
        "",
        f"- 信号日期：{payload['signal_date']}",
        f"- 样本口径：全量 `strategy_signal_daily` 中的 `ma2560_strong_hold`，不是提醒层子集。",
        f"- 样本数：{payload['total']}",
        f"- 观察底座：`{payload['foundation_db']}`",
        "",
        "## 分层统计",
        "",
        "| 匹配等级 | 样本 | 5日已标注 | 5日均值 | 5日胜率 | 5日超额 | 10日已标注 | 10日均值 | 10日胜率 | 10日超额 | 20日已标注 | 20日均值 | 20日胜率 | 20日超额 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for level in LEVEL_ORDER:
        row = summary[level]
        lines.append(
            "| "
            + " | ".join(
                [
                    LEVEL_LABELS[level],
                    str(row["count"]),
                    str(row["labeled_5d"]),
                    pct(row["avg_return_5d"]),
                    pct(row["win_rate_5d"]),
                    pct(row["avg_excess_5d"]),
                    str(row["labeled_10d"]),
                    pct(row["avg_return_10d"]),
                    pct(row["win_rate_10d"]),
                    pct(row["avg_excess_10d"]),
                    str(row["labeled_20d"]),
                    pct(row["avg_return_20d"]),
                    pct(row["win_rate_20d"]),
                    pct(row["avg_excess_20d"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 2026-05-22 当天生成的样本，未来 5/10/20 个交易日尚未发生时会显示 `pending_future_data`。",
            "- 后续每天重跑同一脚本，已发生窗口会自动填入收益与超额收益。",
            "- `stock_only` 表示个股规则成立但行业ETF数据仍不足，不能宣称市场共振。",
        ]
    )
    return "\n".join(lines) + "\n"


def render_html(payload: dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    summary_rows = []
    for level in LEVEL_ORDER:
        row = payload["summary"][level]
        summary_rows.append(
            f"""
            <tr>
              <td><strong>{esc(level)}</strong><br><span>{esc(LEVEL_LABELS[level])}</span></td>
              <td class="num">{esc(row['count'])}</td>
              <td class="num">{esc(row['labeled_5d'])}</td><td class="num">{pct(row['avg_return_5d'])}</td><td class="num">{pct(row['win_rate_5d'])}</td><td class="num">{pct(row['avg_excess_5d'])}</td>
              <td class="num">{esc(row['labeled_10d'])}</td><td class="num">{pct(row['avg_return_10d'])}</td><td class="num">{pct(row['win_rate_10d'])}</td><td class="num">{pct(row['avg_excess_10d'])}</td>
              <td class="num">{esc(row['labeled_20d'])}</td><td class="num">{pct(row['avg_return_20d'])}</td><td class="num">{pct(row['win_rate_20d'])}</td><td class="num">{pct(row['avg_excess_20d'])}</td>
            </tr>
            """
        )

    detail_rows = []
    for row in payload["rows"]:
        detail_rows.append(
            f"""
            <tr>
              <td><strong>{esc(row.get('stock_code'))}</strong><br><span>{esc(row.get('stock_name') or '')}</span></td>
              <td>{esc(row.get('ma2560_market_match_level'))}<br><span>{esc(row.get('ma2560_state_combo'))}</span></td>
              <td>{esc(row.get('strategy_environment_fit'))}<br><span>{esc(row.get('fit_reasons'))}</span></td>
              <td class="num">{esc(row.get('reference_close'))}</td>
              <td class="num">{pct(row.get('forward_return_5d'))}<br><span>{pct(row.get('forward_excess_return_5d'))}</span></td>
              <td class="num">{pct(row.get('forward_return_10d'))}<br><span>{pct(row.get('forward_excess_return_10d'))}</span></td>
              <td class="num">{pct(row.get('forward_return_20d'))}<br><span>{pct(row.get('forward_excess_return_20d'))}</span></td>
              <td>{esc(row.get('label_status'))}</td>
            </tr>
            """
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>2560 State / 市场匹配前向观察 {esc(payload['signal_date'])}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f8fb; color: #172033; }}
    main {{ max-width: 1440px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    .meta {{ color: #5d6b82; margin: 0 0 18px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e1e6ef; margin-bottom: 20px; }}
    th, td {{ text-align: left; vertical-align: top; padding: 10px 12px; border-bottom: 1px solid #edf1f7; font-size: 13px; }}
    th {{ background: #f0f3f8; color: #344054; font-weight: 650; }}
    td span {{ color: #667085; font-size: 12px; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .table-wrap {{ overflow: auto; max-height: 720px; border: 1px solid #e1e6ef; }}
    .note {{ color: #667085; font-size: 13px; }}
  </style>
</head>
<body>
  <main>
    <h1>2560 State / 市场匹配前向观察</h1>
    <p class="meta">信号日期 {esc(payload['signal_date'])} | 样本 {esc(payload['total'])} | 生成 {esc(payload['generated_at'])}</p>
    <table>
      <thead><tr><th>匹配等级</th><th>样本</th><th>5日标注</th><th>5日均值</th><th>5日胜率</th><th>5日超额</th><th>10日标注</th><th>10日均值</th><th>10日胜率</th><th>10日超额</th><th>20日标注</th><th>20日均值</th><th>20日胜率</th><th>20日超额</th></tr></thead>
      <tbody>{''.join(summary_rows)}</tbody>
    </table>
    <div class="table-wrap">
      <table>
        <thead><tr><th>股票</th><th>匹配等级</th><th>环境适配</th><th>参考收盘</th><th>5日收益/超额</th><th>10日收益/超额</th><th>20日收益/超额</th><th>状态</th></tr></thead>
        <tbody>{''.join(detail_rows)}</tbody>
      </table>
    </div>
    <p class="note">本表使用全量研究账本中的 ma2560_strong_hold，不只看提醒层；未来窗口未完成时保留 pending_future_data。</p>
  </main>
</body>
</html>
"""


def build_report(signal_date: str, foundation_db: Path | None = None, ledger_db: Path = LEDGER_DB) -> dict[str, Any]:
    foundation_db = foundation_db or default_foundation_db(signal_date)
    signals = load_signals(signal_date, ledger_db)
    codes = {str(row.get("stock_code") or "") for row in signals if row.get("stock_code")}
    prices, benchmarks, trading_dates = load_price_window(foundation_db, codes, signal_date, 20)
    rows = build_rows(signals, prices, benchmarks)
    summary = group_summary(rows)
    payload = {
        "schema_version": "ma2560_market_match_forward_v1",
        "signal_date": signal_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "foundation_db": str(foundation_db),
        "ledger_db": str(ledger_db),
        "source_scope": "strategy_signal_daily.ma2560_strong_hold",
        "total": len(rows),
        "available_trading_dates": trading_dates,
        "benchmark_by_window": benchmarks,
        "level_labels": LEVEL_LABELS,
        "summary": summary,
        "rows": rows,
        "research_only": True,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"ma2560_market_match_forward_{ymd(signal_date)}"
    json_path = OUT_DIR / f"{stem}.json"
    csv_path = OUT_DIR / f"{stem}.csv"
    md_path = OUT_DIR / f"{stem}.md"
    html_path = PUBLIC_DIR / f"{stem}.html"
    latest_json = OUT_DIR / "ma2560_market_match_forward_latest.json"
    latest_csv = OUT_DIR / "ma2560_market_match_forward_latest.csv"
    latest_md = OUT_DIR / "ma2560_market_match_forward_latest.md"
    latest_html = PUBLIC_DIR / "ma2560_market_match_forward_latest.html"

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    markdown = render_markdown(payload)
    html_text = render_html(payload)
    json_path.write_text(text, encoding="utf-8")
    latest_json.write_text(text, encoding="utf-8")
    write_csv(csv_path, rows)
    write_csv(latest_csv, rows)
    md_path.write_text(markdown, encoding="utf-8")
    latest_md.write_text(markdown, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    latest_html.write_text(html_text, encoding="utf-8")
    return {
        "ok": True,
        "signal_date": signal_date,
        "total": len(rows),
        "summary": summary,
        "json": str(json_path),
        "csv": str(csv_path),
        "markdown": str(md_path),
        "html": str(html_path),
        "latest_json": str(latest_json),
        "latest_csv": str(latest_csv),
        "latest_markdown": str(latest_md),
        "latest_html": str(latest_html),
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze ma2560_strong_hold forward outcomes by market match level.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--foundation-db", type=Path)
    parser.add_argument("--ledger-db", type=Path, default=LEDGER_DB)
    args = parser.parse_args()
    print(json.dumps(build_report(args.date, args.foundation_db, args.ledger_db), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
