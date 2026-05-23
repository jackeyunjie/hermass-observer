from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # Keep the workflow runnable on a plain system Python.
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
RECOMMENDATION_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = RECOMMENDATION_ROOT / "config" / "recommendation_rules.yaml"
BUILTIN_CONFIG: dict[str, Any] = {
    "schema_version": "p116_recommendation_rules_v1",
    "llm": {"default_model": "deepseekV4"},
    "portfolio": {"target_size": 10, "watchlist_size": 30, "max_per_sw_l1": 3, "max_per_sw_l2": 2},
    "score_weights": {
        "state_score_sum": 1.0,
        "ef_strength": 4.0,
        "d1_adx14": 0.08,
        "breakout_count": 3.0,
        "new_entry_bonus": 4.0,
        "w1_quality_bonus": 4.0,
        "moneyflow_score": 2.0,
        "strategy_score": 0.08,
        "macro_industry_support": 3.0,
    },
    "output": {
        "research_only_notice": "Research-Only：本结果仅为量化观察与组合研究，不构成任何投资建议。"
    },
}


@dataclass
class RecommendationPaths:
    json_path: Path
    csv_path: Path
    html_path: Path
    public_csv_path: Path
    latest_html_path: Path


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return dict(BUILTIN_CONFIG)
    if yaml is None:
        return dict(BUILTIN_CONFIG)
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_moneyflow(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = normalize_code(row.get("stock_code"))
            if code:
                rows[code] = row
                rows[code.split(".")[0]] = row
    return rows


def load_strategy_evidence(date_str: str) -> dict[str, dict[str, Any]]:
    path = ROOT / "outputs" / "strategy_evidence" / f"strategy_evidence_{ymd(date_str)}.csv"
    if not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            for key in {normalize_code(row.get("symbol")), normalize_code(row.get("stock_code"))}:
                if key:
                    rows[key] = row
    return rows


def load_market_asset_support(date_str: str) -> dict[str, dict[str, Any]]:
    path = ROOT / "outputs" / "market_assets_state" / f"market_assets_state_{ymd(date_str)}.csv"
    if not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sw_l1 = str(row.get("sw_l1") or "").strip()
            if row.get("asset_type") == "industry_etf" and sw_l1:
                rows[sw_l1] = row
    return rows


def normalize_code(value: Any) -> str:
    text = str(value or "").strip()
    if "." in text:
        digits, suffix = text.split(".", 1)
        digits = "".join(ch for ch in digits if ch.isdigit())[-6:]
        suffix = suffix[:2].upper()
        return f"{digits}.{suffix}" if digits and suffix else digits
    digits = "".join(ch for ch in text if ch.isdigit())[-6:]
    return digits


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def bval(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def score_row(
    row: dict[str, Any],
    change_type: str,
    moneyflow: dict[str, Any],
    strategy: dict[str, Any],
    macro: dict[str, Any],
    weights: dict[str, float],
) -> tuple[float, list[str]]:
    breakout_count = sum(
        1
        for field in ["mn1_breakout", "w1_breakout", "d1_breakout"]
        if bval(row.get(field))
    )
    score = 0.0
    score += fnum(row.get("state_score_sum")) * fnum(weights.get("state_score_sum", 1.0))
    score += fnum(row.get("ef_strength")) * fnum(weights.get("ef_strength", 4.0))
    score += fnum(row.get("d1_adx14")) * fnum(weights.get("d1_adx14", 0.08))
    score += breakout_count * fnum(weights.get("breakout_count", 3.0))
    if change_type == "entered":
        score += fnum(weights.get("new_entry_bonus", 4.0))
    if bval(row.get("quality_gate_pass")):
        score += fnum(weights.get("w1_quality_bonus", 4.0))

    mf_score = fnum(moneyflow.get("moneyflow_score")) if moneyflow else 0.0
    score += mf_score * fnum(weights.get("moneyflow_score", 2.0))

    strategy_score = fnum(strategy.get("strategy_score")) if strategy else 0.0
    score += strategy_score * fnum(weights.get("strategy_score", 0.08))

    macro_ef_count = int(fnum(macro.get("ef_count"))) if macro else 0
    macro_state = "/".join(str(macro.get(field) or "") for field in ["mn1_state_hex", "w1_state_hex", "d1_state_hex"]).strip("/")
    if macro_ef_count >= 2:
        score += fnum(weights.get("macro_industry_support", 3.0))

    reasons = [
        f"状态={row.get('mn1_state')}/{row.get('w1_state')}/{row.get('d1_state')}",
        f"分数和={row.get('state_score_sum')}",
        f"D1 ADX={fnum(row.get('d1_adx14')):.1f}",
    ]
    if breakout_count:
        reasons.append(f"SR突破={breakout_count}/3")
    if change_type == "entered":
        reasons.append("今日新进入")
    if moneyflow:
        status = moneyflow.get("moneyflow_status") or ""
        reasons.append(f"资金流={status}/分={moneyflow.get('moneyflow_score')}")
        if bval(moneyflow.get("moneyflow_confirmed")):
            reasons.append("5日资金确认")
        if bval(moneyflow.get("moneyflow_divergence")):
            reasons.append("资金背离复核")
    if strategy:
        if strategy.get("best_selection_signal"):
            reasons.append(f"策略形态={strategy.get('best_selection_signal')}")
        if strategy.get("latest_vcp_signal"):
            reasons.append(f"VCP={strategy.get('latest_vcp_signal')}")
        if strategy.get("latest_2560_signal"):
            reasons.append(f"2560={strategy.get('latest_2560_signal')}")
    if macro:
        reasons.append(f"行业ETF={macro.get('name')}/{macro_state or 'NA'}")
        if macro_ef_count >= 2:
            reasons.append("行业ETF两周期以上E/F")
    if row.get("quality_flags"):
        reasons.append(f"质量标记={row.get('quality_flags')}")
    return score, reasons


def build_candidates(date_str: str, config: dict[str, Any], moneyflow_csv: Path | None = None) -> dict[str, Any]:
    date_ymd = ymd(date_str)
    snapshot_path = ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_{date_ymd}.json"
    diff_path = ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_diff_{date_ymd}.json"
    if not snapshot_path.exists():
        raise FileNotFoundError(snapshot_path)
    if not diff_path.exists():
        raise FileNotFoundError(diff_path)

    snapshot = load_json(snapshot_path)
    diff = load_json(diff_path)
    moneyflow = load_moneyflow(moneyflow_csv)
    strategy_evidence = load_strategy_evidence(date_str)
    macro_support = load_market_asset_support(date_str)
    entered_symbols = {row["symbol"] for row in diff.get("entered", [])}
    left_symbols = {row["symbol"] for row in diff.get("left", [])}
    weights = config.get("score_weights", {})
    portfolio_cfg = config.get("portfolio", {})
    target_size = int(portfolio_cfg.get("target_size", 10))
    watchlist_size = int(portfolio_cfg.get("watchlist_size", 30))
    max_per_l1 = int(portfolio_cfg.get("max_per_sw_l1", 3))
    max_per_l2 = int(portfolio_cfg.get("max_per_sw_l2", 2))

    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for row in snapshot.get("rows", []):
        symbol = row["symbol"]
        change_type = "entered" if symbol in entered_symbols else "stayed"
        mf = moneyflow.get(normalize_code(row.get("symbol"))) or moneyflow.get(normalize_code(row.get("stock_code"))) or {}
        strategy = strategy_evidence.get(normalize_code(row.get("symbol"))) or strategy_evidence.get(normalize_code(row.get("stock_code"))) or {}
        macro = macro_support.get(row.get("sw_l1") or "") or {}
        score, reasons = score_row(row, change_type, mf, strategy, macro, weights)
        quality_flags = row.get("quality_flags") or ""
        record = {
            "rank": 0,
            "stock_code": row.get("stock_code"),
            "symbol": symbol,
            "stock_name": row.get("stock_name"),
            "sw_l1": row.get("sw_l1"),
            "sw_l2": row.get("sw_l2"),
            "sw_l3": row.get("sw_l3"),
            "date": row.get("date"),
            "change_type": change_type,
            "recommendation_score": round(score, 4),
            "state": f"{row.get('mn1_state')}/{row.get('w1_state')}/{row.get('d1_state')}",
            "state_score_sum": row.get("state_score_sum"),
            "ef_strength": row.get("ef_strength"),
            "d1_close": row.get("d1_close"),
            "d1_adx14": row.get("d1_adx14"),
            "mn1_sr_support": row.get("mn1_sr_support"),
            "mn1_sr_resistance": row.get("mn1_sr_resistance"),
            "w1_sr_support": row.get("w1_sr_support"),
            "w1_sr_resistance": row.get("w1_sr_resistance"),
            "d1_sr_support": row.get("d1_sr_support"),
            "d1_sr_resistance": row.get("d1_sr_resistance"),
            "w1_ama10": row.get("w1_ama10"),
            "quality_flags": quality_flags,
            "moneyflow_score": mf.get("moneyflow_score", ""),
            "moneyflow_status": mf.get("moneyflow_status", ""),
            "moneyflow_confirmed": mf.get("moneyflow_confirmed", ""),
            "moneyflow_divergence": mf.get("moneyflow_divergence", ""),
            "moneyflow_days_available": mf.get("moneyflow_days_available", ""),
            "moneyflow_coverage_ratio": mf.get("moneyflow_coverage_ratio", ""),
            "positive_days_5d": mf.get("positive_days_5d", ""),
            "big_positive_days_5d": mf.get("big_positive_days_5d", ""),
            "active_net_5d": mf.get("active_net_5d", ""),
            "big_order_net_5d": mf.get("big_order_net_5d", ""),
            "latest_active_net": mf.get("latest_active_net", ""),
            "latest_big_order_net": mf.get("latest_big_order_net", ""),
            "strategy_score": strategy.get("strategy_score", ""),
            "best_selection_signal": strategy.get("best_selection_signal", ""),
            "latest_vcp_signal": strategy.get("latest_vcp_signal", ""),
            "latest_2560_signal": strategy.get("latest_2560_signal", ""),
            "macro_etf_symbol": macro.get("symbol", ""),
            "macro_etf_name": macro.get("name", ""),
            "macro_etf_state": "/".join(str(macro.get(field) or "") for field in ["mn1_state_hex", "w1_state_hex", "d1_state_hex"]).strip("/"),
            "macro_etf_ef_count": macro.get("ef_count", ""),
            "observation_reason": "；".join(reasons),
            "risk_note": build_risk_note(row),
        }
        if quality_flags:
            excluded.append({**record, "exclude_reason": quality_flags})
        else:
            candidates.append(record)

    candidates.sort(
        key=lambda r: (
            -fnum(r["recommendation_score"]),
            r.get("sw_l1") or "",
            r.get("stock_code") or "",
        )
    )
    for idx, row in enumerate(candidates, 1):
        row["rank"] = idx

    watchlist = candidates[:watchlist_size]
    portfolio = pick_portfolio(candidates, target_size, max_per_l1, max_per_l2)
    left = []
    for row in diff.get("left", []):
        left.append(
            {
                "stock_code": row.get("stock_code"),
                "symbol": row.get("symbol"),
                "stock_name": row.get("stock_name"),
                "sw_l1": row.get("sw_l1"),
                "state": f"{row.get('mn1_state')}/{row.get('w1_state')}/{row.get('d1_state')}",
                "previous_date": diff.get("previous_date"),
                "risk_note": "已离开三周期正向 E/F 池，进入复核名单。",
            }
        )

    return {
        "schema_version": "p116_recommendation_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": date_str,
        "model": config.get("llm", {}).get("default_model", "deepseekV4"),
        "notice": config.get("output", {}).get("research_only_notice", "Research-Only"),
        "source_snapshot": str(snapshot_path),
        "source_diff": str(diff_path),
        "moneyflow_csv": str(moneyflow_csv) if moneyflow_csv else None,
        "strategy_evidence_csv": str(ROOT / "outputs" / "strategy_evidence" / f"strategy_evidence_{date_ymd}.csv"),
        "market_assets_state_csv": str(ROOT / "outputs" / "market_assets_state" / f"market_assets_state_{date_ymd}.csv"),
        "pool_total": snapshot.get("total", len(snapshot.get("rows", []))),
        "candidate_total": len(candidates),
        "portfolio_size": len(portfolio),
        "watchlist_size": len(watchlist),
        "left_count": len(left),
        "industry_summary": industry_summary(candidates),
        "portfolio": portfolio,
        "watchlist": watchlist,
        "candidates": candidates,
        "excluded": excluded,
        "left": left,
        "left_symbols": sorted(left_symbols),
        "moneyflow_status_summary": industry_summary_by_field(candidates, "moneyflow_status"),
    }


def build_risk_note(row: dict[str, Any]) -> str:
    notes = []
    if row.get("d1_sr_support"):
        notes.append(f"D1防守参考={row.get('d1_sr_support')}")
    if row.get("w1_ama10"):
        notes.append(f"W1 AMA10={row.get('w1_ama10')}")
    if row.get("quality_flags"):
        notes.append(str(row.get("quality_flags")))
    return "；".join(notes)


def pick_portfolio(candidates: list[dict[str, Any]], target_size: int, max_per_l1: int, max_per_l2: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    l1_count: dict[str, int] = {}
    l2_count: dict[str, int] = {}
    for row in candidates:
        l1 = row.get("sw_l1") or "未分类"
        l2 = row.get("sw_l2") or "未分类"
        if l1_count.get(l1, 0) >= max_per_l1:
            continue
        if l2_count.get(l2, 0) >= max_per_l2:
            continue
        selected.append({**row, "portfolio_weight": round(1.0 / target_size, 4)})
        l1_count[l1] = l1_count.get(l1, 0) + 1
        l2_count[l2] = l2_count.get(l2, 0) + 1
        if len(selected) >= target_size:
            break
    for idx, row in enumerate(selected, 1):
        row["portfolio_rank"] = idx
    return selected


def industry_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        industry = row.get("sw_l1") or "未分类"
        counts[industry] = counts.get(industry, 0) + 1
    return [
        {"industry": key, "count": value}
        for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def industry_summary_by_field(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "missing")
        counts[key] = counts.get(key, 0) + 1
    return [
        {"name": key, "count": value}
        for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def write_outputs(payload: dict[str, Any], date_str: str) -> RecommendationPaths:
    date_ymd = ymd(date_str)
    out_dir = RECOMMENDATION_ROOT / "outputs"
    public_dir = ROOT / "public"
    out_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"p116_recommendation_{date_ymd}.json"
    csv_path = out_dir / f"p116_recommendation_{date_ymd}.csv"
    html_path = public_dir / f"p116_recommendation_{date_ymd}.html"
    public_csv_path = public_dir / f"p116_recommendation_{date_ymd}.csv"
    latest_html_path = public_dir / "p116_recommendation_latest.html"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(csv_path, payload["watchlist"])
    write_csv(public_csv_path, payload["watchlist"])
    html_text = render_html(payload, public_csv_path.name)
    html_path.write_text(html_text, encoding="utf-8")
    latest_html_path.write_text(html_text, encoding="utf-8")
    return RecommendationPaths(json_path, csv_path, html_path, public_csv_path, latest_html_path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "rank",
        "stock_code",
        "symbol",
        "stock_name",
        "sw_l1",
        "sw_l2",
        "sw_l3",
        "date",
        "change_type",
        "recommendation_score",
        "state",
        "state_score_sum",
        "ef_strength",
        "d1_close",
        "d1_adx14",
        "moneyflow_score",
        "moneyflow_status",
        "moneyflow_confirmed",
        "moneyflow_divergence",
        "moneyflow_days_available",
        "moneyflow_coverage_ratio",
        "positive_days_5d",
        "big_positive_days_5d",
        "active_net_5d",
        "big_order_net_5d",
        "latest_active_net",
        "latest_big_order_net",
        "strategy_score",
        "best_selection_signal",
        "latest_vcp_signal",
        "latest_2560_signal",
        "macro_etf_symbol",
        "macro_etf_name",
        "macro_etf_state",
        "macro_etf_ef_count",
        "observation_reason",
        "risk_note",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def render_html(payload: dict[str, Any], csv_name: str) -> str:
    portfolio_table = render_table(payload["portfolio"], portfolio_fields())
    watchlist_table = render_table(payload["watchlist"], watchlist_fields())
    industry_cards = "".join(
        f"<div class='kpi'><small>{html.escape(row['industry'])}</small><strong>{row['count']}</strong></div>"
        for row in payload["industry_summary"][:10]
    )
    left_table = render_table(payload["left"][:30], ["stock_code", "stock_name", "sw_l1", "state", "risk_note"])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>P116 推荐工作台 - {html.escape(payload['date'])}</title>
  <style>
    body {{ margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; color: #17212b; background: #f6f8f7; }}
    header, section {{ background: #fff; border: 1px solid #dce4df; border-radius: 8px; padding: 20px; margin-bottom: 18px; }}
    h1 {{ margin: 0 0 8px; font-size: 26px; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    p {{ color: #526071; line-height: 1.55; }}
    a {{ color: #0f6b4b; font-weight: 700; text-decoration: none; }}
    .notice {{ background: #fff7ed; border: 1px solid #fed7aa; color: #8a4b12; padding: 12px; border-radius: 8px; }}
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }}
    .kpi {{ border: 1px solid #dce4df; border-radius: 8px; padding: 12px; }}
    .kpi small {{ color: #677486; }}
    .kpi strong {{ display: block; margin-top: 6px; font-size: 22px; }}
    .table-wrap {{ overflow: auto; border: 1px solid #dce4df; max-height: 70vh; }}
    table {{ border-collapse: collapse; width: 100%; min-width: 1400px; font-size: 12px; background: #fff; }}
    th, td {{ border-bottom: 1px solid #e3e9e5; border-right: 1px solid #e3e9e5; padding: 7px 8px; text-align: left; white-space: nowrap; }}
    th {{ position: sticky; top: 0; z-index: 1; background: #eef4f1; }}
    td:nth-child(10), td:nth-child(11) {{ font-weight: 700; color: #0f766e; }}
  </style>
</head>
<body>
  <header>
    <h1>P116 推荐工作台 - {html.escape(payload['date'])}</h1>
    <p class="notice">{html.escape(payload['notice'])}</p>
    <p>输入：三周期正向 E/F 标准池。输出：组合候选、观察名单、行业集中、离开复核。默认模型配置：{html.escape(payload['model'])}；本版推荐分无需大模型即可运行。</p>
    <p><a href="{html.escape(csv_name)}" download>下载观察名单 CSV</a></p>
  </header>
  <section>
    <h2>概览</h2>
    <div class="kpis">
      <div class="kpi"><small>基础池</small><strong>{payload['pool_total']}</strong></div>
      <div class="kpi"><small>有效候选</small><strong>{payload['candidate_total']}</strong></div>
      <div class="kpi"><small>组合候选</small><strong>{payload['portfolio_size']}</strong></div>
      <div class="kpi"><small>观察名单</small><strong>{payload['watchlist_size']}</strong></div>
      <div class="kpi"><small>离开复核</small><strong>{payload['left_count']}</strong></div>
      {industry_cards}
    </div>
  </section>
  <section>
    <h2>组合候选</h2>
    <div class="table-wrap">{portfolio_table}</div>
  </section>
  <section>
    <h2>观察名单 Top 30</h2>
    <div class="table-wrap">{watchlist_table}</div>
  </section>
  <section>
    <h2>离开复核</h2>
    <div class="table-wrap">{left_table}</div>
  </section>
</body>
</html>
"""


def portfolio_fields() -> list[str]:
    return [
        "portfolio_rank",
        "rank",
        "stock_code",
        "stock_name",
        "sw_l1",
        "sw_l2",
        "change_type",
        "recommendation_score",
        "portfolio_weight",
        "state",
        "d1_close",
        "d1_adx14",
        "macro_etf_name",
        "macro_etf_state",
        "strategy_score",
        "best_selection_signal",
        "moneyflow_status",
        "moneyflow_score",
        "positive_days_5d",
        "big_positive_days_5d",
        "observation_reason",
        "risk_note",
    ]


def watchlist_fields() -> list[str]:
    return [
        "rank",
        "stock_code",
        "stock_name",
        "sw_l1",
        "sw_l2",
        "change_type",
        "recommendation_score",
        "state",
        "d1_close",
        "d1_adx14",
        "macro_etf_name",
        "macro_etf_state",
        "strategy_score",
        "best_selection_signal",
        "latest_vcp_signal",
        "latest_2560_signal",
        "moneyflow_score",
        "moneyflow_status",
        "moneyflow_confirmed",
        "moneyflow_divergence",
        "positive_days_5d",
        "big_positive_days_5d",
        "moneyflow_coverage_ratio",
        "observation_reason",
        "risk_note",
    ]


def render_table(rows: list[dict[str, Any]], fields: list[str]) -> str:
    head = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
    body = []
    for row in rows:
        cells = "".join(
            f"<td>{html.escape(str(row.get(field, '') if row.get(field, '') is not None else ''))}</td>"
            for field in fields
        )
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
