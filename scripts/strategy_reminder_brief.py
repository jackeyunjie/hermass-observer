#!/usr/bin/env python3
"""Assemble the daily strategy reminder brief.

This is a pure read-only composition layer. It consumes the normalized strategy
signal ledger, State cache, SR boundary cache, optional fundamental ledger, and
optional calibration output. It does not calculate strategy triggers, infer
missing signals, or write back to source fact tables.
"""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "outputs"
REMINDER_DIR = OUTPUT_ROOT / "strategy_reminders"
PUBLIC_DIR = ROOT / "public"

ALLOWED_MATURITY_LABELS = {"趋势新生", "趋势行进", "趋势延展", "防守参考线", "状态值得复核"}
ENTRY_MATURITY = "趋势新生"
MA2560_MATCH_LABELS = {
    "full_match": "2560 full_match",
    "stock_only": "2560 stock_only",
    "market_unsupported": "2560 market_unsupported",
    "not_match": "2560 not_match",
}


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def code6(value: Any) -> str:
    text = str(value or "").upper().strip()
    digits = "".join(ch for ch in text.split(".", 1)[0] if ch.isdigit())
    return digits[-6:] if digits else text


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def load_json(path: Path, required: bool = False) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def default_paths(date_str: str) -> dict[str, Path]:
    date_ymd = ymd(date_str)
    return {
        "signals": OUTPUT_ROOT / "strategy_signals" / f"strategy_signal_daily_{date_ymd}.json",
        "state_ef": OUTPUT_ROOT / "state_cache" / f"state_ef_{date_ymd}.json",
        "state_duration": OUTPUT_ROOT / "state_cache" / f"state_duration_{date_ymd}.json",
        "sr_boundary": OUTPUT_ROOT / "state_cache" / f"sr_boundary_{date_ymd}.json",
        "fundamental_ledger": OUTPUT_ROOT / "fundamental" / f"stock_research_ledger_{date_ymd}.json",
        "strategy_evaluation": OUTPUT_ROOT / "strategy_evaluation" / f"strategy_evaluation_{date_ymd}.json",
        "calibration": OUTPUT_ROOT / "strategy_evaluation" / f"strategy_evidence_calibration_{date_ymd}.json",
        "ifind_financial": OUTPUT_ROOT / "ifind" / f"financial_{date_ymd}.json",
        "ifind_industry": OUTPUT_ROOT / "ifind" / f"industry_{date_ymd}.json",
    }


def load_reminder_signals(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path, required=True)
    out: list[dict[str, Any]] = []
    for row in payload.get("rows", []) or []:
        if row.get("reminder_eligible") is True and row.get("display_scope") == "reminder":
            out.append(row)
    return out


def build_state_map(state_ef_path: Path, duration_path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in load_json(state_ef_path, required=True).get("rows", []) or []:
        key = code6(row.get("stock_code"))
        out[key] = {
            "stock_code": row.get("stock_code"),
            "d1_close": row.get("d1_close"),
            "mn1_state": row.get("mn1_state_hex"),
            "w1_state": row.get("w1_state_hex"),
            "d1_state": row.get("d1_state_hex"),
            "mn1_state_score": row.get("mn1_state_score"),
            "w1_state_score": row.get("w1_state_score"),
            "d1_state_score": row.get("d1_state_score"),
            "state_score_sum": row.get("score_sum"),
            "ef_count": row.get("ef_count"),
        }

    for row in load_json(duration_path, required=True).get("rows", []) or []:
        key = code6(row.get("stock_code"))
        item = out.setdefault(key, {"stock_code": row.get("stock_code")})
        item.update(
            {
                "mn1_ef_duration": row.get("mn1_ef_duration"),
                "w1_ef_duration": row.get("w1_ef_duration"),
                "d1_ef_duration": row.get("d1_ef_duration"),
                "all_three_ef_duration": row.get("all_three_ef_duration"),
            }
        )
    return out


def build_sr_map(path: Path) -> dict[str, dict[str, Any]]:
    rows = load_json(path, required=True).get("rows", []) or []
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = code6(row.get("stock_code"))
        distance = float(row.get("distance_pct") or 999.0)
        current = best.get(key)
        if current is None or distance < float(current.get("distance_pct") or 999.0):
            best[key] = row
    return best


def build_fundamental_map(path: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(path, required=False)
    out: dict[str, dict[str, Any]] = {}
    for row in payload.get("rows", []) or []:
        out[code6(row.get("stock_code"))] = {
            "stock_code": row.get("stock_code"),
            "stock_name": row.get("stock_name"),
            "sw_l1": row.get("sw_l1"),
            "summary": row.get("chief_insight"),
            "confidence": row.get("confidence"),
            "evidence_count": row.get("evidence_count"),
        }
    return out


def build_ifind_map(financial_path: Path, industry_path: Path) -> dict[str, dict[str, Any]]:
    financial = load_json(financial_path, required=False).get("by_code", {}) or {}
    industry = load_json(industry_path, required=False).get("by_code", {}) or {}
    out: dict[str, dict[str, Any]] = {}
    for code, row in financial.items():
        key = code6(code)
        out.setdefault(key, {})["financial"] = row
    for code, row in industry.items():
        key = code6(code)
        out.setdefault(key, {})["industry"] = row
    return out


def build_evaluation_map(path: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(path, required=False)
    out: dict[str, dict[str, Any]] = {}
    for row in payload.get("rows", []) or []:
        out[code6(row.get("stock_code"))] = {
            "stock_name": row.get("stock_name"),
            "sw_l1": row.get("sw_l1"),
            "sw_l2": row.get("sw_l2"),
            "evidence_score": row.get("evidence_score"),
            "evidence_tier": row.get("evidence_tier"),
            "evidence_rank": row.get("evidence_rank"),
            "environment_tags": row.get("environment_tags"),
            "factor_breakdown": row.get("factor_breakdown"),
            "research_note": row.get("research_note"),
        }
    return out


def calibration_status(path: Path) -> dict[str, Any]:
    payload = load_json(path, required=False)
    status = payload.get("status")
    if status == "ok":
        return {"status": "已校准", "source": str(path)}
    return {
        "status": "待校准",
        "reason": payload.get("reason") or status or "calibration_not_available",
        "source": str(path) if path.exists() else None,
    }


def maturity_label(signal: dict[str, Any]) -> str:
    signal_type = signal.get("signal_type")
    if signal_type == "entry":
        return ENTRY_MATURITY
    if signal_type == "exit":
        return "防守参考线"
    if signal_type == "risk":
        return "状态值得复核"
    return ENTRY_MATURITY


def sr_note(sr: dict[str, Any] | None) -> str | None:
    if not sr:
        return None
    direction = sr.get("boundary_direction")
    boundary_type = sr.get("boundary_type")
    period = sr.get("boundary_period")
    distance = sr.get("distance_pct")
    if direction == "above_resistance":
        return f"{period} 收盘价位于阻力区间上方"
    if direction == "below_support":
        return f"{period} 收盘价位于支撑区间下方"
    if direction == "inside_range" and distance is not None:
        return f"{period} 收盘价接近{boundary_type}边界"
    return None


def percent(value: Any) -> str:
    if value is None:
        return "-"


def ma2560_environment(signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "local_combo_pass": bool(signal.get("ma2560_local_combo_pass")),
        "p116_state_match": bool(signal.get("ma2560_p116_state_match")),
        "market_match_level": signal.get("ma2560_market_match_level") or "not_match",
        "state_combo": signal.get("ma2560_state_combo") or "",
    }
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def build_card(
    signal: dict[str, Any],
    state: dict[str, Any],
    sr: dict[str, Any] | None,
    fundamental: dict[str, Any] | None,
    ifind: dict[str, Any] | None,
    evaluation: dict[str, Any] | None,
    cal: dict[str, Any],
) -> dict[str, Any]:
    label = maturity_label(signal)
    if label not in ALLOWED_MATURITY_LABELS:
        raise ValueError(f"unsupported reminder label: {label}")

    return {
        "stock_code": signal.get("stock_code"),
        "stock_code_6": code6(signal.get("stock_code")),
        "stock_name": (evaluation or {}).get("stock_name") or (fundamental or {}).get("stock_name"),
        "maturity": label,
        "strategy": {
            "strategy_id": signal.get("strategy_id"),
            "signal_type": signal.get("signal_type"),
            "signal_name": signal.get("signal_name"),
            "signal_strength": signal.get("signal_strength"),
            "raw_signal": signal.get("raw_signal"),
            "params_json": signal.get("params_json"),
            "source_module": signal.get("source_module"),
        },
        "lifecycle_stage": signal.get("lifecycle_stage") or label,
        "strategy_environment_fit": signal.get("strategy_environment_fit") or "待观察",
        "fit_reasons": signal.get("fit_reasons") or "",
        "ma2560_environment": ma2560_environment(signal),
        "state_environment": {
            "mn1_state": state.get("mn1_state"),
            "w1_state": state.get("w1_state"),
            "d1_state": state.get("d1_state"),
            "mn1_state_score": state.get("mn1_state_score"),
            "w1_state_score": state.get("w1_state_score"),
            "d1_state_score": state.get("d1_state_score"),
            "state_score_sum": state.get("state_score_sum"),
            "ef_count": state.get("ef_count"),
        },
        "state_duration": {
            "mn1_ef_duration": state.get("mn1_ef_duration"),
            "w1_ef_duration": state.get("w1_ef_duration"),
            "d1_ef_duration": state.get("d1_ef_duration"),
            "all_three_ef_duration": state.get("all_three_ef_duration"),
        },
        "sr_position": {
            "boundary_period": (sr or {}).get("boundary_period"),
            "boundary_type": (sr or {}).get("boundary_type"),
            "boundary_direction": (sr or {}).get("boundary_direction"),
            "distance_pct": (sr or {}).get("distance_pct"),
            "close_vs_boundary": (sr or {}).get("close_vs_boundary"),
            "above_resistance": (sr or {}).get("above_resistance"),
            "below_support": (sr or {}).get("below_support"),
            "note": sr_note(sr),
        }
        if sr
        else None,
        "fundamental": fundamental,
        "ifind": ifind,
        "scene_tags": build_scene_tags(signal, ifind, evaluation),
        "strategy_evaluation": evaluation,
        "environment_tags": parse_tags((evaluation or {}).get("environment_tags")),
        "calibration": cal,
        "research_only": True,
    }


def build_scene_tags(signal: dict[str, Any], ifind: dict[str, Any] | None, evaluation: dict[str, Any] | None) -> list[str]:
    tags: list[str] = []
    financial = (ifind or {}).get("financial") or {}
    industry = (ifind or {}).get("industry") or {}
    if industry.get("industry_climate") and industry.get("industry_climate") != "未标注":
        tags.append(f"行业景气{industry['industry_climate']}")
    quality = financial.get("quality_label")
    if quality and quality != "数据不足":
        tags.append(quality)
    cash = financial.get("cash_quality_label")
    if cash in {"现金流健康", "现金流谨慎"}:
        tags.append(cash)
    strategy_id = signal.get("strategy_id")
    if strategy_id == "ma2560":
        level = signal.get("ma2560_market_match_level") or "not_match"
        tags.append(MA2560_MATCH_LABELS.get(level, f"2560 {level}"))
    env_tags = parse_tags((evaluation or {}).get("environment_tags"))
    if env_tags and strategy_id:
        tags.append(f"{env_tags[0]} + {strategy_id}")
    return tags


def parse_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def card_sort_key(card: dict[str, Any]) -> tuple[Any, ...]:
    state = card.get("state_environment") or {}
    duration = card.get("state_duration") or {}
    evaluation = card.get("strategy_evaluation") or {}
    return (
        -(float(evaluation.get("evidence_score") or 0.0)),
        -(int(state.get("state_score_sum") or 0)),
        -(int(duration.get("all_three_ef_duration") or 0)),
        str(card.get("stock_code") or ""),
    )


def generate_html(payload: dict[str, Any]) -> str:
    cards = payload["reminders"]
    groups: dict[str, list[dict[str, Any]]] = {label: [] for label in ["趋势新生", "趋势行进", "趋势延展", "防守参考线", "状态值得复核"]}
    for card in cards:
        groups.setdefault(card["maturity"], []).append(card)

    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    def row(card: dict[str, Any]) -> str:
        state = card.get("state_environment") or {}
        duration = card.get("state_duration") or {}
        strategy = card.get("strategy") or {}
        sr = card.get("sr_position") or {}
        fundamental = card.get("fundamental") or {}
        ifind = card.get("ifind") or {}
        ifind_financial = ifind.get("financial") or {}
        ifind_industry = ifind.get("industry") or {}
        evaluation = card.get("strategy_evaluation") or {}
        tags = " / ".join(card.get("environment_tags") or []) or "-"
        scene_tags = " / ".join(card.get("scene_tags") or []) or "-"
        fit = card.get("strategy_environment_fit") or "待观察"
        lifecycle = card.get("lifecycle_stage") or card.get("maturity")
        fit_reasons = card.get("fit_reasons") or "-"
        ma2560 = card.get("ma2560_environment") or {}
        ma2560_level = ma2560.get("market_match_level") or "not_match"
        ma2560_line = ""
        if (strategy.get("strategy_id") or "") == "ma2560":
            ma2560_line = (
                f"<br><span>{esc(MA2560_MATCH_LABELS.get(ma2560_level, f'2560 {ma2560_level}'))} "
                f"{esc(ma2560.get('state_combo') or '')}</span>"
            )
        ifind_text = ifind_financial.get("summary") or "-"
        industry_text = ifind_industry.get("summary") or "-"
        return f"""
        <tr>
          <td><strong>{esc(card.get("stock_code"))}</strong><br><span>{esc(card.get("stock_name") or "")}</span></td>
          <td>{esc(lifecycle)}<br><span>{esc(card.get("maturity"))}</span></td>
          <td>{esc(strategy.get("strategy_id"))}<br><span>{esc(strategy.get("signal_name"))}</span></td>
          <td>{esc(fit)}<br><span>{esc(fit_reasons)}</span>{ma2560_line}</td>
          <td>MN1 {esc(state.get("mn1_state"))} / W1 {esc(state.get("w1_state"))} / D1 {esc(state.get("d1_state"))}<br><span>score {esc(state.get("state_score_sum"))}, ef {esc(state.get("ef_count"))}</span></td>
          <td>D1 {esc(duration.get("d1_ef_duration"))}<br><span>all-three {esc(duration.get("all_three_ef_duration"))}</span></td>
          <td>{esc(sr.get("boundary_direction") or "-")}<br><span>{esc(sr.get("boundary_period") or "")} {esc(sr.get("boundary_type") or "")} {percent(sr.get("distance_pct"))}</span></td>
          <td>{esc(tags)}</td>
          <td>{esc(ifind_text)}<br><span>{esc(industry_text)}</span><br><span>{esc(scene_tags)}</span></td>
          <td>{esc(evaluation.get("evidence_tier") or "-")}<br><span>{esc(evaluation.get("evidence_score") or "")}</span></td>
          <td>{esc((fundamental.get("summary") or "")[:120])}</td>
          <td>{esc((card.get("calibration") or {}).get("status"))}</td>
        </tr>
        """

    sections = []
    for label, items in groups.items():
        if not items:
            continue
        rows = "\n".join(row(item) for item in items)
        sections.append(
            f"""
            <section>
              <h2>{esc(label)} <span>{len(items)}</span></h2>
              <table>
                <thead>
                  <tr>
                    <th>代码</th>
                    <th>生命周期</th>
                    <th>策略信号</th>
                    <th>环境适配</th>
                    <th>State环境</th>
                    <th>持续</th>
                    <th>SR位置</th>
                    <th>环境标签</th>
                    <th>iFinD摘要</th>
                    <th>证据档</th>
                    <th>基本面摘要</th>
                    <th>统计</th>
                  </tr>
                </thead>
                <tbody>{rows}</tbody>
              </table>
            </section>
            """
        )

    generated_at = esc(payload["generated_at"])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>策略提醒简报 {esc(payload["date"])}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f7fb; color: #172033; }}
    main {{ max-width: 1440px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    .meta {{ margin: 0 0 20px; color: #5d6b82; }}
    section {{ margin-top: 24px; }}
    h2 {{ font-size: 18px; margin: 0 0 10px; }}
    h2 span {{ color: #667085; font-weight: 500; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e1e6ef; }}
    th, td {{ text-align: left; vertical-align: top; padding: 10px 12px; border-bottom: 1px solid #edf1f7; font-size: 13px; }}
    th {{ background: #f0f3f8; color: #344054; font-weight: 650; }}
    td span {{ color: #667085; font-size: 12px; }}
    tr:last-child td {{ border-bottom: 0; }}
  </style>
</head>
<body>
  <main>
    <h1>策略提醒简报</h1>
    <p class="meta">日期 {esc(payload["date"])} | 提醒 {payload["total_reminders"]} 条 | 生成 {generated_at}</p>
    {''.join(sections)}
  </main>
</body>
</html>
"""


def build_reminder_brief(date_str: str) -> dict[str, Any]:
    paths = default_paths(date_str)
    generated_at = datetime.now(timezone.utc).isoformat()
    signals = load_reminder_signals(paths["signals"])
    state_map = build_state_map(paths["state_ef"], paths["state_duration"])
    sr_map = build_sr_map(paths["sr_boundary"])
    fundamental_map = build_fundamental_map(paths["fundamental_ledger"])
    ifind_map = build_ifind_map(paths["ifind_financial"], paths["ifind_industry"])
    evaluation_map = build_evaluation_map(paths["strategy_evaluation"])
    cal = calibration_status(paths["calibration"])

    cards = []
    missing_state = 0
    for signal in signals:
        key = code6(signal.get("stock_code"))
        state = state_map.get(key)
        if not state:
            missing_state += 1
            continue
        cards.append(
            build_card(
                signal,
                state,
                sr_map.get(key),
                fundamental_map.get(key),
                ifind_map.get(key),
                evaluation_map.get(key),
                cal,
            )
        )
    cards.sort(key=card_sort_key)

    maturity_counts = Counter(card["maturity"] for card in cards)
    strategy_counts = Counter((card.get("strategy") or {}).get("strategy_id") for card in cards)
    payload = {
        "schema_version": "strategy_reminder_brief_v1",
        "date": date_str,
        "generated_at": generated_at,
        "total_signals_input": len(signals),
        "total_reminders": len(cards),
        "missing_state_context": missing_state,
        "maturity_distribution": dict(sorted(maturity_counts.items())),
        "strategy_distribution": dict(sorted(strategy_counts.items())),
        "data_sources": {name: str(path) for name, path in paths.items()},
        "guardrails": [
            "Consumes only reminder_eligible strategy ledger rows.",
            "Does not calculate or infer strategy triggers.",
            "Missing calibration remains 待校准.",
            "All labels are restricted to approved research reminder language.",
        ],
        "reminders": cards,
        "research_only": True,
    }

    REMINDER_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    date_ymd = ymd(date_str)
    json_path = REMINDER_DIR / f"reminder_{date_ymd}.json"
    latest_json = REMINDER_DIR / "reminder_latest.json"
    html_path = PUBLIC_DIR / f"strategy_reminder_{date_ymd}.html"
    latest_html = PUBLIC_DIR / "strategy_reminder_latest.html"

    text = json.dumps(payload, ensure_ascii=False, indent=2, default=json_safe)
    json_path.write_text(text, encoding="utf-8")
    latest_json.write_text(text, encoding="utf-8")
    html_text = generate_html(payload)
    html_path.write_text(html_text, encoding="utf-8")
    latest_html.write_text(html_text, encoding="utf-8")

    return {
        "ok": True,
        "date": date_str,
        "total_signals_input": len(signals),
        "total_reminders": len(cards),
        "missing_state_context": missing_state,
        "maturity_distribution": payload["maturity_distribution"],
        "strategy_distribution": payload["strategy_distribution"],
        "json": str(json_path),
        "latest_json": str(latest_json),
        "html": str(html_path),
        "latest_html": str(latest_html),
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build daily strategy reminder brief.")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    result = build_reminder_brief(args.date)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
