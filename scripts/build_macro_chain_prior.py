#!/usr/bin/env python3
"""Build macro-chain prior factors for strategy posterior adjustment."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "macro_chain_prior"
PUBLIC_DIR = ROOT / "public"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def clamp(value: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, value))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def default_paths(date_str: str) -> dict[str, Path]:
    date_ymd = ymd(date_str)
    return {
        "macro_snapshot": ROOT / "outputs" / "macro" / f"macro_snapshot_{date_ymd}.json",
        "macro_trend_summary": ROOT / "outputs" / "macro" / f"macro_trend_summary_{date_ymd}.json",
        "market_assets_state": ROOT / "outputs" / "market_assets_state" / f"market_assets_state_{date_ymd}.json",
        "market_assets_db": ROOT / "outputs" / "market_assets" / "market_assets.duckdb",
        "industry_etf_config": ROOT / "outputs" / "etf_config" / f"industry_etf_config_{date_ymd}.json",
        "ifind_industry": ROOT / "outputs" / "ifind" / f"industry_{date_ymd}.json",
        "industry_chain_db": ROOT / "outputs" / "industry_chain" / "industry_chain_evidence.duckdb",
    }


def indicator_signal(indicator: dict[str, Any]) -> tuple[float | None, str | None]:
    row_status = indicator.get("status") or indicator.get("data_status")
    if row_status not in {"ok", "gui_imported_needs_ifind_code", "trend_ready", "partial_history", "single_point"}:
        return None, None
    name = str(indicator.get("indicator_name") or indicator.get("indicator_code") or "")
    category = str(indicator.get("category") or "")
    if category in {"market", "style", "market_vendor_crosscheck", "valuation"}:
        return None, None
    value = indicator.get("value", indicator.get("latest_value"))
    trend = str(indicator.get("trend") or "")
    percentile = indicator.get("percentile")
    signal = 0.0
    reasons: list[str] = []

    if "PMI" in name and value is not None:
        if safe_float(value) >= 50:
            signal += 1.0
            reasons.append(f"{name}>=50")
        else:
            signal -= 1.0
            reasons.append(f"{name}<50")
    if "GDP" in name or category == "growth":
        if trend == "up":
            signal += 0.5
            reasons.append(f"{name}上行")
        elif trend == "down":
            signal -= 0.5
            reasons.append(f"{name}下行")
    if any(key in name for key in ["LPR", "国债收益率", "DR007"]):
        if trend == "down":
            signal += 1.0
            reasons.append(f"{name}下行")
        elif trend == "up":
            signal -= 1.0
            reasons.append(f"{name}上行")
    if category == "credit":
        if trend == "up":
            signal += 1.0
            reasons.append(f"{name}上行")
        elif trend == "down":
            signal -= 1.0
            reasons.append(f"{name}下行")
    if category == "inflation":
        if percentile is not None and safe_float(percentile) >= 80:
            signal -= 0.5
            reasons.append(f"{name}高分位")
        elif trend == "down":
            signal += 0.3
            reasons.append(f"{name}下行")
    if category in {"liquidity", "external"} and percentile is not None:
        pct = safe_float(percentile)
        if pct <= 40:
            signal += 0.4
            reasons.append(f"{name}低分位")
        elif pct >= 75:
            signal -= 0.4
            reasons.append(f"{name}高分位")

    if not reasons:
        return 0.0, f"{name}有数据但暂无明确方向"
    return max(-1.5, min(1.5, signal)), "、".join(reasons)


def dimension_signal(indicator: dict[str, Any]) -> tuple[float | None, str | None]:
    signal, reason = indicator_signal(indicator)
    if signal is None:
        return None, None
    history_count = safe_int(indicator.get("history_count"))
    if history_count <= 1:
        signal *= 0.35
    elif history_count < 12:
        signal *= 0.7
    return signal, reason


def score_dimension(name: str, indicators: list[dict[str, Any]]) -> dict[str, Any]:
    contributions: list[float] = []
    evidence: list[str] = []
    for indicator in indicators:
        signal, reason = dimension_signal(indicator)
        if signal is None:
            continue
        contributions.append(signal)
        if reason:
            evidence.append(reason)
    if not contributions:
        return {
            "score_0_10": 5.0,
            "confidence": 0.0,
            "status": "data_insufficient",
            "used_indicator_count": 0,
            "evidence": [],
            "summary": f"{name}数据不足，保持中性。",
        }
    avg_signal = sum(contributions) / len(contributions)
    score = clamp(5.0 + avg_signal * 2.0)
    trend_ready = sum(1 for row in indicators if safe_int(row.get("history_count")) >= 12)
    partial = sum(1 for row in indicators if safe_int(row.get("history_count")) >= 2)
    confidence = round(min(1.0, len(contributions) / 3.0) * (0.4 + 0.4 * min(1.0, partial / max(1, len(contributions))) + 0.2 * min(1.0, trend_ready / max(1, len(contributions)))), 4)
    status = "ok" if confidence >= 0.7 else "partial"
    return {
        "score_0_10": round(score, 2),
        "confidence": confidence,
        "status": status,
        "used_indicator_count": len(contributions),
        "evidence": evidence,
        "summary": f"{name}{score:.1f}/10；" + "；".join(evidence[:4]),
    }


def macro_indicators_for_prior(macro_snapshot: dict[str, Any], trend_summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = trend_summary.get("rows") or []
    if rows:
        return rows
    return macro_snapshot.get("indicators", []) or []


def build_macro_prior(macro_snapshot: dict[str, Any], trend_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    indicators = macro_indicators_for_prior(macro_snapshot, trend_summary or {})
    macro_rows = [
        row
        for row in indicators
        if str(row.get("category") or "") not in {"market", "style", "market_vendor_crosscheck", "valuation", "commodity", "external"}
    ]
    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in macro_rows:
        by_category.setdefault(str(row.get("category") or "unknown"), []).append(row)
    sub_scores = {
        "growth_score": score_dimension("增长", by_category.get("growth", [])),
        "liquidity_score": score_dimension("流动性", by_category.get("liquidity", [])),
        "credit_score": score_dimension("信用", by_category.get("credit", [])),
        "inflation_score": score_dimension("通胀", by_category.get("inflation", [])),
    }
    weights = {"growth_score": 0.30, "liquidity_score": 0.30, "credit_score": 0.25, "inflation_score": 0.15}
    weighted_score = 0.0
    weight_sum = 0.0
    weighted_conf = 0.0
    evidence: list[str] = []
    for key, weight in weights.items():
        item = sub_scores[key]
        weighted_score += safe_float(item.get("score_0_10"), 5.0) * weight
        weight_sum += weight
        weighted_conf += safe_float(item.get("confidence")) * weight
        evidence.extend(item.get("evidence") or [])
    score = weighted_score / weight_sum if weight_sum else 5.0
    confidence = round(weighted_conf / weight_sum if weight_sum else 0.0, 4)
    status = "ok" if confidence >= 0.65 else ("partial" if confidence > 0 else "data_insufficient")
    used_count = sum(safe_int(item.get("used_indicator_count")) for item in sub_scores.values())
    if used_count:
        summary = f"宏观先验{score:.1f}/10；增长{sub_scores['growth_score']['score_0_10']}，流动性{sub_scores['liquidity_score']['score_0_10']}，信用{sub_scores['credit_score']['score_0_10']}，通胀{sub_scores['inflation_score']['score_0_10']}。"
    else:
        summary = "宏观先验数据不足，保持中性分数，不参与强化策略判断。"
    return {
        "score_0_10": round(score, 2),
        "confidence": confidence,
        "status": status,
        "summary": summary,
        "sub_scores": sub_scores,
        "used_indicator_count": used_count,
        "available_indicator_count": sum(
            1
            for item in indicators
            if item.get("status") in {"ok", "gui_imported_needs_ifind_code"} or item.get("data_status") in {"trend_ready", "partial_history", "single_point"}
        ),
        "trend_ready_count": sum(1 for item in indicators if safe_int(item.get("history_count")) >= 12),
        "needs_code_count": macro_snapshot.get("regime", {}).get("needs_code_count"),
        "ifind_errorcode": macro_snapshot.get("collection", {}).get("ifind_errorcode"),
        "ifind_errmsg": macro_snapshot.get("collection", {}).get("ifind_errmsg"),
        "evidence": evidence,
    }


def state_combo(row: dict[str, Any]) -> str:
    return f"{row.get('mn1_state_hex') or '-'}/{row.get('w1_state_hex') or '-'}/{row.get('d1_state_hex') or '-'}"


def asset_state_score(row: dict[str, Any] | None) -> float:
    if not row:
        return 5.0
    ef_count = safe_int(row.get("ef_count"))
    score = {0: 4.0, 1: 6.0, 2: 8.0, 3: 9.2}.get(ef_count, 5.0)
    raw_sum = safe_float(row.get("mn1_state_score")) + safe_float(row.get("w1_state_score")) + safe_float(row.get("d1_state_score"))
    if raw_sum >= 40:
        score += 0.4
    elif raw_sum < 10:
        score -= 0.6
    return round(clamp(score), 2)


def load_asset_returns(market_db: Path, date_str: str, symbols: list[str], lookback_rows: int = 21) -> dict[str, dict[str, Any]]:
    if not market_db.exists():
        return {}
    con = duckdb.connect(str(market_db), read_only=True)
    out: dict[str, dict[str, Any]] = {}
    try:
        for symbol in symbols:
            rows = con.execute(
                """
                SELECT date::VARCHAR, close
                FROM market_asset_daily
                WHERE symbol = ? AND date <= CAST(? AS DATE)
                ORDER BY date DESC
                LIMIT ?
                """,
                [symbol, date_str, lookback_rows],
            ).fetchall()
            rows = list(reversed(rows))
            if len(rows) >= 2 and rows[0][1] not in (None, 0):
                out[symbol] = {
                    "start_date": rows[0][0],
                    "end_date": rows[-1][0],
                    "start_close": rows[0][1],
                    "end_close": rows[-1][1],
                    "return": round((float(rows[-1][1]) / float(rows[0][1]) - 1.0) * 100.0, 4),
                    "rows": len(rows),
                }
    finally:
        con.close()
    return out


def build_market_style_prior(market_rows: list[dict[str, Any]], market_db: Path, date_str: str) -> dict[str, Any]:
    by_symbol = {row.get("symbol"): row for row in market_rows}
    broad_symbols = ["000001.SH", "000300.SH", "000852.SH", "000905.SH", "399001.SZ", "399006.SZ"]
    broad_scores = [asset_state_score(by_symbol.get(symbol)) for symbol in broad_symbols if by_symbol.get(symbol)]
    risk_score = sum(broad_scores) / len(broad_scores) if broad_scores else 5.0
    returns = load_asset_returns(market_db, date_str, ["000300.SH", "399006.SZ", "000852.SH", "512880.SH", "512480.SH"])
    hs300 = safe_float((returns.get("000300.SH") or {}).get("return"))
    cyb = safe_float((returns.get("399006.SZ") or {}).get("return"))
    zz1000 = safe_float((returns.get("000852.SH") or {}).get("return"))
    semiconductor = safe_float((returns.get("512480.SH") or {}).get("return"))
    brokerage = safe_float((returns.get("512880.SH") or {}).get("return"))
    growth_diff = cyb - hs300
    small_diff = zz1000 - hs300
    growth_score = clamp(5.0 + growth_diff * 0.6)
    small_cap_score = clamp(5.0 + small_diff * 0.6)
    risk_score = clamp(risk_score + max(-1.0, min(1.0, (semiconductor - brokerage) * 0.2)))
    tags: list[str] = []
    if growth_diff > 1.0:
        tags.append("成长相对强")
    elif growth_diff < -1.0:
        tags.append("成长相对弱")
    if small_diff > 1.0:
        tags.append("小盘相对强")
    elif small_diff < -1.0:
        tags.append("小盘相对弱")
    if risk_score >= 7:
        tags.append("宽风险偏好")
    elif risk_score <= 4.5:
        tags.append("风险偏谨慎")
    else:
        tags.append("市场先验中性")
    return {
        "risk_appetite_score": round(risk_score, 2),
        "growth_style_score": round(growth_score, 2),
        "small_cap_score": round(small_cap_score, 2),
        "confidence": 0.8 if broad_scores else 0.2,
        "tags": tags,
        "relative_strength_20d": {
            "growth_vs_hs300_pct": round(growth_diff, 4),
            "small_vs_hs300_pct": round(small_diff, 4),
            "semiconductor_vs_brokerage_pct": round(semiconductor - brokerage, 4),
        },
        "asset_returns_20d": returns,
        "broad_index_states": [
            {
                "symbol": symbol,
                "name": (by_symbol.get(symbol) or {}).get("name"),
                "state_combo": state_combo(by_symbol.get(symbol) or {}),
                "ef_count": (by_symbol.get(symbol) or {}).get("ef_count"),
                "score_0_10": asset_state_score(by_symbol.get(symbol)),
            }
            for symbol in broad_symbols
            if by_symbol.get(symbol)
        ],
    }


def load_chain_event_counts(chain_db: Path, date_str: str) -> dict[str, int]:
    if not chain_db.exists():
        return {}
    con = duckdb.connect(str(chain_db), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if "chain_dynamics" not in tables:
            return {}
        return {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT industry, COUNT(*) AS event_count
                FROM chain_dynamics
                WHERE event_date <= ?
                GROUP BY industry
                """,
                [date_str],
            ).fetchall()
        }
    finally:
        con.close()


def build_industry_counts(ifind_industry: dict[str, Any]) -> dict[str, int]:
    if ifind_industry.get("industry_counts"):
        return {str(k): safe_int(v) for k, v in ifind_industry["industry_counts"].items()}
    return dict(Counter((row.get("sw_l1") or "未分类") for row in ifind_industry.get("rows", []) or []))


def build_industry_priors(
    *,
    market_rows: list[dict[str, Any]],
    industry_config: dict[str, Any],
    ifind_industry: dict[str, Any],
    chain_event_counts: dict[str, int],
) -> list[dict[str, Any]]:
    industry_counts = build_industry_counts(ifind_industry)
    etf_by_industry: dict[str, list[dict[str, Any]]] = {}
    for row in market_rows:
        if row.get("asset_type") == "industry_etf" and row.get("sw_l1"):
            etf_by_industry.setdefault(str(row.get("sw_l1")), []).append(row)
    mapping_by_industry = {row.get("sw_l1"): row for row in industry_config.get("mapping_rows", []) or []}
    industries = sorted(set(industry_counts) | set(etf_by_industry) | set(mapping_by_industry))
    out: list[dict[str, Any]] = []
    for industry in industries:
        etfs = etf_by_industry.get(industry, [])
        best_etf = max(etfs, key=asset_state_score) if etfs else None
        mapping = mapping_by_industry.get(industry, {})
        mapping_status = mapping.get("mapping_status") or ("configured_active" if best_etf else "missing")
        event_count = safe_int(chain_event_counts.get(industry))
        if best_etf:
            base = asset_state_score(best_etf)
            confidence = 0.75
            status = "ok"
            evidence = [f"行业ETF {best_etf.get('symbol')} {best_etf.get('name')} State={state_combo(best_etf)} EF={best_etf.get('ef_count')}"]
        elif mapping_status == "proxy_pending_review":
            base = 5.0
            confidence = 0.3
            status = "proxy_pending_review"
            evidence = [f"代理ETF待人工确认：{mapping.get('selected_symbol') or ''} {mapping.get('selected_name') or ''}".strip()]
        elif mapping_status == "no_etf_coverage":
            base = 5.0
            confidence = 0.1
            status = "no_etf_coverage"
            evidence = ["无严格行业ETF覆盖，保持中性"]
        else:
            base = 5.0
            confidence = 0.2
            status = "data_insufficient"
            evidence = ["行业ETF State 缺失，保持中性"]
        if event_count:
            confidence = min(1.0, confidence + 0.1)
            evidence.append(f"产业链动态事件 {event_count} 条")
        if base >= 7.5:
            hint = "positive"
            label = "产业/行业先验支持"
        elif base <= 4.5:
            hint = "cautious"
            label = "产业/行业先验偏谨慎"
        else:
            hint = "neutral"
            label = "产业/行业先验中性"
        out.append(
            {
                "sw_l1": industry,
                "stock_count": safe_int(industry_counts.get(industry)),
                "chain_prior_score": round(base, 2),
                "confidence": round(confidence, 4),
                "status": status,
                "posterior_adjustment_hint": hint,
                "posterior_adjustment_label": label,
                "etf_symbol": best_etf.get("symbol") if best_etf else mapping.get("selected_symbol"),
                "etf_name": best_etf.get("name") if best_etf else mapping.get("selected_name"),
                "etf_state_combo": state_combo(best_etf) if best_etf else mapping.get("selected_market_state_combo") or "",
                "etf_ef_count": best_etf.get("ef_count") if best_etf else mapping.get("selected_market_ef_count") or "",
                "mapping_status": mapping_status,
                "dynamic_event_count": event_count,
                "evidence": evidence,
            }
        )
    out.sort(key=lambda row: (-safe_float(row["chain_prior_score"]), -safe_float(row["confidence"]), row["sw_l1"]))
    return out


def build_strategy_priors(macro_prior: dict[str, Any], market_style: dict[str, Any]) -> dict[str, Any]:
    macro_score = safe_float(macro_prior.get("score_0_10"), 5.0)
    macro_conf = safe_float(macro_prior.get("confidence"))
    risk = safe_float(market_style.get("risk_appetite_score"), 5.0)
    growth = safe_float(market_style.get("growth_style_score"), 5.0)
    small = safe_float(market_style.get("small_cap_score"), 5.0)
    return {
        "vcp": {
            "prior_fit_score": round((growth * 0.45 + risk * 0.35 + macro_score * 0.20), 2),
            "confidence": round(max(0.45, macro_conf) * safe_float(market_style.get("confidence"), 0.5), 4),
            "logic": "VCP 更依赖成长风格、风险偏好和宏观增长/流动性共振。",
        },
        "ma2560": {
            "prior_fit_score": round((risk * 0.40 + macro_score * 0.35 + small * 0.25), 2),
            "confidence": round(max(0.45, macro_conf) * safe_float(market_style.get("confidence"), 0.5), 4),
            "logic": "2560 更依赖市场不弱、个股回调结构和行业共振。",
        },
        "bollinger_bandit": {
            "prior_fit_score": round((risk * 0.55 + growth * 0.25 + macro_score * 0.20), 2),
            "confidence": round(max(0.45, macro_conf) * safe_float(market_style.get("confidence"), 0.5), 4),
            "logic": "布林强盗突破类信号更吃风险偏好和趋势扩散环境。",
        },
    }


def build_payload(date_str: str, paths: dict[str, Path]) -> dict[str, Any]:
    macro_snapshot = load_json(paths["macro_snapshot"])
    macro_trend_summary = load_json(paths["macro_trend_summary"])
    market_rows = load_json(paths["market_assets_state"], default=[])
    industry_config = load_json(paths["industry_etf_config"])
    ifind_industry = load_json(paths["ifind_industry"])
    chain_events = load_chain_event_counts(paths["industry_chain_db"], date_str)
    macro_prior = build_macro_prior(macro_snapshot, macro_trend_summary)
    market_style = build_market_style_prior(market_rows if isinstance(market_rows, list) else [], paths["market_assets_db"], date_str)
    industry_priors = build_industry_priors(
        market_rows=market_rows if isinstance(market_rows, list) else [],
        industry_config=industry_config,
        ifind_industry=ifind_industry,
        chain_event_counts=chain_events,
    )
    return {
        "schema_version": "macro_chain_prior_v1",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_sources": {key: str(value) for key, value in paths.items()},
        "macro_prior": macro_prior,
        "market_style_prior": market_style,
        "strategy_priors": build_strategy_priors(macro_prior, market_style),
        "industry_priors": industry_priors,
        "by_industry": {row["sw_l1"]: row for row in industry_priors},
        "guardrails": [
            "Research-only prior layer.",
            "Does not modify State formulas.",
            "Does not change strategy scores until forward calibration validates weighting.",
            "Missing macro or chain dynamic data is kept neutral and explicitly labeled.",
        ],
        "research_only": True,
    }


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "sw_l1",
        "stock_count",
        "chain_prior_score",
        "confidence",
        "status",
        "posterior_adjustment_hint",
        "posterior_adjustment_label",
        "etf_symbol",
        "etf_name",
        "etf_state_combo",
        "etf_ef_count",
        "mapping_status",
        "dynamic_event_count",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def render_html(payload: dict[str, Any]) -> str:
    esc = lambda value: html.escape("" if value is None else str(value))
    macro = payload["macro_prior"]
    market = payload["market_style_prior"]
    strategy = payload["strategy_priors"]
    rows = payload["industry_priors"]
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{esc(row['sw_l1'])}</td>"
            f"<td>{esc(row['chain_prior_score'])}</td>"
            f"<td>{esc(row['confidence'])}</td>"
            f"<td>{esc(row['posterior_adjustment_label'])}</td>"
            f"<td>{esc(row['status'])}</td>"
            f"<td>{esc(row.get('etf_symbol'))}<br><span>{esc(row.get('etf_name'))}</span></td>"
            f"<td>{esc(row.get('etf_state_combo'))}<br><span>EF={esc(row.get('etf_ef_count'))}</span></td>"
            f"<td>{esc(row.get('stock_count'))}</td>"
            f"<td>{esc('；'.join(row.get('evidence') or []))}</td>"
            "</tr>"
        )
    strategy_text = " / ".join(f"{name}:{item['prior_fit_score']}" for name, item in strategy.items())
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>宏观-产业链先验 {esc(payload['date'])}</title>
  <style>
    body {{ margin:0; padding:24px; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:#172033; background:#f6f8fb; }}
    h1 {{ margin:0 0 8px; font-size:24px; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:18px 0; }}
    .card {{ background:#fff; border:1px solid #dfe6ee; padding:14px; border-radius:8px; }}
    .card small {{ display:block; color:#667085; }}
    .card strong {{ display:block; font-size:22px; margin-top:4px; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid #dfe6ee; font-size:13px; }}
    th, td {{ border-bottom:1px solid #edf1f6; padding:9px 10px; text-align:left; vertical-align:top; }}
    th {{ background:#eef3f7; }}
    td span {{ color:#667085; font-size:12px; }}
    @media (max-width:900px) {{ .grid {{ grid-template-columns:1fr 1fr; }} table {{ display:block; overflow-x:auto; }} }}
  </style>
</head>
<body>
  <h1>宏观-产业链先验</h1>
  <p>日期：{esc(payload['date'])} ｜ Research-only，不直接修改 State 或策略排序。</p>
  <div class="grid">
    <div class="card"><small>宏观先验</small><strong>{esc(macro['score_0_10'])}</strong><small>{esc(macro['status'])}</small></div>
    <div class="card"><small>风险偏好</small><strong>{esc(market['risk_appetite_score'])}</strong><small>{esc(' / '.join(market.get('tags') or []))}</small></div>
    <div class="card"><small>成长风格</small><strong>{esc(market['growth_style_score'])}</strong><small>相对沪深300 {esc(market['relative_strength_20d']['growth_vs_hs300_pct'])}%</small></div>
    <div class="card"><small>策略先验</small><strong>{esc(strategy_text)}</strong></div>
  </div>
  <p>{esc(macro['summary'])}</p>
  <table>
    <thead>
      <tr><th>行业</th><th>产业先验</th><th>置信</th><th>后验提示</th><th>状态</th><th>ETF</th><th>ETF State</th><th>股票数</th><th>证据</th></tr>
    </thead>
    <tbody>{''.join(body)}</tbody>
  </table>
</body>
</html>
"""


def write_outputs(payload: dict[str, Any]) -> dict[str, str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    date_ymd = ymd(payload["date"])
    json_path = OUT_DIR / f"macro_chain_prior_{date_ymd}.json"
    csv_path = OUT_DIR / f"macro_chain_prior_{date_ymd}.csv"
    html_path = PUBLIC_DIR / f"macro_chain_prior_{date_ymd}.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(payload["industry_priors"], csv_path)
    html_path.write_text(render_html(payload), encoding="utf-8")
    shutil.copyfile(json_path, OUT_DIR / "macro_chain_prior_latest.json")
    shutil.copyfile(csv_path, OUT_DIR / "macro_chain_prior_latest.csv")
    shutil.copyfile(html_path, PUBLIC_DIR / "macro_chain_prior_latest.html")
    return {"json": str(json_path), "csv": str(csv_path), "html": str(html_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build macro-chain prior for posterior strategy adjustment.")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    payload = build_payload(args.date, default_paths(args.date))
    outputs = write_outputs(payload)
    result = {
        "ok": True,
        "date": args.date,
        "outputs": outputs,
        "macro_prior": payload["macro_prior"],
        "market_style_prior": payload["market_style_prior"],
        "top_industries": payload["industry_priors"][:5],
        "research_only": True,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
