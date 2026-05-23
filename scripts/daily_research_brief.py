#!/usr/bin/env python3
"""Build the daily strategy-environment research brief.

The brief answers one question:
Which stocks triggered strategy signals in environments that fit those
strategies today?

It is a read-only report generator. It consumes existing reminder/evaluation
outputs and does not create strategy signals, infer actions, or publish
statistics that have not passed calibration.
"""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "daily_research_brief"
PUBLIC_DIR = ROOT / "public"

FIT_ORDER = {"最佳适配": 0, "适配": 1, "弱适配": 2, "待观察": 3}
STRATEGY_ORDER = {"vcp": 0, "ma2560": 1, "bollinger_bandit": 2}


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def load_json(path: Path, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def percent(value: Any, scale: float = 1.0) -> str:
    try:
        if value is None:
            return "-"
        return f"{float(value) * scale:.2f}%"
    except (TypeError, ValueError):
        return "-"


def paths_for(date_str: str) -> dict[str, Path]:
    date_ymd = ymd(date_str)
    return {
        "reminder": ROOT / "outputs" / "strategy_reminders" / f"reminder_{date_ymd}.json",
        "evaluation": ROOT / "outputs" / "strategy_evaluation" / f"strategy_evaluation_{date_ymd}.json",
        "state_ef": ROOT / "outputs" / "state_cache" / f"state_ef_{date_ymd}.json",
        "calibration": ROOT / "outputs" / "strategy_evaluation" / f"strategy_evidence_calibration_{date_ymd}.json",
        "ifind_financial": ROOT / "outputs" / "ifind" / f"financial_{date_ymd}.json",
        "ifind_industry": ROOT / "outputs" / "ifind" / f"industry_{date_ymd}.json",
    }


def previous_state_ef_path(date_str: str) -> Path | None:
    current = ymd(date_str)
    candidates = []
    for path in (ROOT / "outputs" / "state_cache").glob("state_ef_*.json"):
        stem = path.stem.removeprefix("state_ef_")
        if stem == "latest" or not stem.isdigit() or stem >= current:
            continue
        candidates.append((stem, path))
    if not candidates:
        return None
    return sorted(candidates)[-1][1]


def card_industry(card: dict[str, Any]) -> str:
    evaluation = card.get("strategy_evaluation") or {}
    return evaluation.get("sw_l1") or "未分类"


def card_strategy(card: dict[str, Any]) -> str:
    return (card.get("strategy") or {}).get("strategy_id") or "unknown"


def build_market_summary(date_str: str, evaluation_payload: dict[str, Any], state_payload: dict[str, Any]) -> dict[str, Any]:
    rows = evaluation_payload.get("rows", []) or []
    total_ef = len(state_payload.get("rows", []) or rows)
    previous_path = previous_state_ef_path(date_str)
    previous_total = None
    previous_date = None
    if previous_path:
        previous_payload = load_json(previous_path, required=False)
        previous_total = len(previous_payload.get("rows", []) or [])
        previous_date = previous_payload.get("date") or previous_path.stem.removeprefix("state_ef_")

    industry_counts = Counter((row.get("sw_l1") or "未分类") for row in rows)
    industry_rows = []
    for industry, count in industry_counts.most_common():
        share = count / total_ef if total_ef else 0.0
        industry_rows.append({"industry": industry, "count": count, "share": share})

    hot = [row for row in industry_rows if row["share"] >= 0.20]
    if not hot:
        hot = industry_rows[:3]

    return {
        "all_three_ef_count": total_ef,
        "previous_all_three_ef_count": previous_total,
        "previous_state_ef_date": previous_date,
        "all_three_ef_delta": total_ef - previous_total if previous_total is not None else None,
        "industry_distribution": industry_rows,
        "focus_industries": hot,
    }


def display_rows(reminder_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for card in reminder_payload.get("reminders", []) or []:
        fit = card.get("strategy_environment_fit") or "待观察"
        if fit not in {"最佳适配", "适配"}:
            continue
        rows.append(card)
    rows.sort(
        key=lambda card: (
            FIT_ORDER.get(card.get("strategy_environment_fit") or "待观察", 99),
            card_industry(card),
            STRATEGY_ORDER.get(card_strategy(card), 99),
            -(float(((card.get("strategy_evaluation") or {}).get("evidence_score") or 0.0))),
            str(card.get("stock_code") or ""),
        )
    )
    return rows


def ifind_summary(card: dict[str, Any]) -> str:
    ifind = card.get("ifind") or {}
    financial = ifind.get("financial") or {}
    industry = ifind.get("industry") or {}
    parts = []
    if financial.get("summary"):
        parts.append(financial["summary"])
    if industry.get("chain_identity"):
        parts.append(industry["chain_identity"])
    return "；".join(parts) or "-"


def scene_tags(card: dict[str, Any]) -> str:
    tags = card.get("scene_tags") or []
    return " / ".join(str(item) for item in tags if item) or "-"


def ifind_focus_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for card in rows:
        ifind = card.get("ifind") or {}
        financial = ifind.get("financial") or {}
        industry = ifind.get("industry") or {}
        if card.get("strategy_environment_fit") != "最佳适配":
            continue
        if financial.get("quality_label") not in {"质量健康", "质量中性"}:
            continue
        if not industry.get("chain_identity"):
            continue
        out.append(card)
    return out


def brief_stats(reminder_payload: dict[str, Any]) -> dict[str, Any]:
    cards = reminder_payload.get("reminders", []) or []
    strategy_counts = Counter(card_strategy(card) for card in cards)
    fit_counts = Counter((card.get("strategy_environment_fit") or "待观察") for card in cards)
    lifecycle_counts = Counter((card.get("lifecycle_stage") or card.get("maturity") or "未知") for card in cards)
    by_strategy_fit: dict[str, dict[str, int]] = defaultdict(dict)
    for card in cards:
        strategy = card_strategy(card)
        fit = card.get("strategy_environment_fit") or "待观察"
        by_strategy_fit[strategy][fit] = by_strategy_fit[strategy].get(fit, 0) + 1
    return {
        "total_reminders": len(cards),
        "strategy_counts": dict(sorted(strategy_counts.items())),
        "fit_counts": dict(sorted(fit_counts.items(), key=lambda item: FIT_ORDER.get(item[0], 99))),
        "lifecycle_counts": dict(sorted(lifecycle_counts.items())),
        "by_strategy_fit": {key: dict(sorted(val.items(), key=lambda item: FIT_ORDER.get(item[0], 99))) for key, val in sorted(by_strategy_fit.items())},
    }


def calibration_summary(calibration_payload: dict[str, Any]) -> dict[str, Any]:
    status = calibration_payload.get("status")
    if status == "ok":
        return {
            "status": "已校准",
            "reason": "",
        }
    return {
        "status": "待校准",
        "reason": calibration_payload.get("reason") or status or "calibration_not_available",
    }


def compact_state(card: dict[str, Any]) -> str:
    state = card.get("state_environment") or {}
    return f"MN1:{state.get('mn1_state') or '-'} W1:{state.get('w1_state') or '-'} D1:{state.get('d1_state') or '-'}"


def compact_duration(card: dict[str, Any]) -> str:
    duration = card.get("state_duration") or {}
    return f"D1 {duration.get('d1_ef_duration') or '-'} / 共振 {duration.get('all_three_ef_duration') or '-'}"


def compact_sr(card: dict[str, Any]) -> str:
    sr = card.get("sr_position") or {}
    if not sr:
        return "-"
    direction = sr.get("boundary_direction") or "-"
    distance = sr.get("distance_pct")
    return f"{direction} {percent(distance, 100.0)}"


def markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "暂无最佳适配或适配信号。\n"
    lines = [
        "| 股票 | 行业 | 策略 | 生命周期 | 适配度 | 适配理由 | State | 持续 | SR位置 | 统计 |",
        "|------|------|------|----------|--------|----------|-------|------|--------|------|",
    ]
    for card in rows:
        strategy = card.get("strategy") or {}
        cal = card.get("calibration") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{card.get('stock_code') or ''} {card.get('stock_name') or ''}".strip(),
                    card_industry(card),
                    str(strategy.get("strategy_id") or "-"),
                    str(card.get("lifecycle_stage") or card.get("maturity") or "-"),
                    str(card.get("strategy_environment_fit") or "-"),
                    str(card.get("fit_reasons") or "-").replace("|", "/"),
                    compact_state(card),
                    compact_duration(card),
                    compact_sr(card),
                    str(cal.get("status") or "待校准"),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def ifind_markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "暂无同时具备策略最佳适配和 iFinD 质量摘要的信号。\n"
    lines = [
        "| 股票 | 行业 | 策略 | 生命周期 | 场景标签 | iFinD摘要 | 适配理由 |",
        "|------|------|------|----------|----------|-----------|----------|",
    ]
    for card in rows:
        strategy = card.get("strategy") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{card.get('stock_code') or ''} {card.get('stock_name') or ''}".strip(),
                    card_industry(card),
                    str(strategy.get("strategy_id") or "-"),
                    str(card.get("lifecycle_stage") or card.get("maturity") or "-"),
                    scene_tags(card).replace("|", "/"),
                    ifind_summary(card).replace("|", "/"),
                    str(card.get("fit_reasons") or "-").replace("|", "/"),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def build_markdown(payload: dict[str, Any]) -> str:
    summary = payload["market_summary"]
    stats = payload["signal_stats"]
    cal = payload["calibration"]
    focus = "、".join(row["industry"] for row in summary["focus_industries"]) or "无"
    delta = summary.get("all_three_ef_delta")
    delta_text = "无前日对比" if delta is None else f"{delta:+d}"

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in payload["display_rows"]:
        grouped[card_industry(row)].append(row)
    focus_ifind = payload["ifind_focus_rows"]

    sections = []
    for industry in [row["industry"] for row in summary["focus_industries"]]:
        items = grouped.pop(industry, [])
        if not items:
            continue
        sections.append(f"### {industry}\n\n{markdown_table(items)}")
    remaining = [item for items in grouped.values() for item in items]
    if remaining:
        sections.append(f"### 其他行业\n\n{markdown_table(remaining)}")

    return f"""# 每日策略环境匹配报告

**日期：{payload["date"]}**

## 市场环境速览

- 全三 E/F 池：{summary["all_three_ef_count"]} 只 | 较前一缓存日：{delta_text}
- 行业聚焦：{focus}
- 校准状态：{cal["status"]}（{cal["reason"] or "质量闸门已通过"}）

## 策略信号分布

- 今日提醒信号：{stats["total_reminders"]} 条
- 按策略：{json.dumps(stats["strategy_counts"], ensure_ascii=False)}
- 按适配度：{json.dumps(stats["fit_counts"], ensure_ascii=False)}
- 按生命周期：{json.dumps(stats["lifecycle_counts"], ensure_ascii=False)}

## 最佳适配与适配信号

{chr(10).join(sections) if sections else "暂无最佳适配或适配信号。"}

## iFinD 场景聚焦

{ifind_markdown_table(focus_ifind)}

## 说明

- 本报告只展示策略信号与环境匹配事实。
- 不输出具体操作指令。
- 历史统计只有在校准质量闸门通过后才展示。
"""


def build_html(payload: dict[str, Any], markdown: str) -> str:
    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    rows = payload["display_rows"]
    ifind_rows = payload["ifind_focus_rows"]
    row_html = []
    for card in rows:
        strategy = card.get("strategy") or {}
        cal = card.get("calibration") or {}
        row_html.append(
            f"""
            <tr>
              <td><strong>{esc(card.get("stock_code"))}</strong><br><span>{esc(card.get("stock_name") or "")}</span></td>
              <td>{esc(card_industry(card))}</td>
              <td>{esc(strategy.get("strategy_id"))}<br><span>{esc(strategy.get("signal_name"))}</span></td>
              <td>{esc(card.get("lifecycle_stage") or card.get("maturity"))}</td>
              <td>{esc(card.get("strategy_environment_fit"))}</td>
              <td>{esc(card.get("fit_reasons") or "-")}</td>
              <td>{esc(scene_tags(card))}<br><span>{esc(ifind_summary(card))}</span></td>
              <td>{esc(compact_state(card))}<br><span>{esc(compact_duration(card))}</span></td>
              <td>{esc(compact_sr(card))}</td>
              <td>{esc(cal.get("status") or "待校准")}</td>
            </tr>
            """
        )

    summary = payload["market_summary"]
    stats = payload["signal_stats"]
    cal = payload["calibration"]
    focus = "、".join(row["industry"] for row in summary["focus_industries"]) or "无"
    delta = summary.get("all_three_ef_delta")
    delta_text = "无前日对比" if delta is None else f"{delta:+d}"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>每日策略环境匹配报告 {esc(payload["date"])}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f8fb; color: #172033; }}
    main {{ max-width: 1440px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    .meta {{ color: #5d6b82; margin: 0 0 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }}
    .metric {{ background: #fff; border: 1px solid #e1e6ef; padding: 12px; }}
    .metric b {{ display: block; font-size: 20px; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e1e6ef; }}
    th, td {{ text-align: left; vertical-align: top; padding: 10px 12px; border-bottom: 1px solid #edf1f7; font-size: 13px; }}
    th {{ background: #f0f3f8; color: #344054; font-weight: 650; }}
    td span {{ color: #667085; font-size: 12px; }}
    .note {{ margin-top: 16px; color: #667085; font-size: 13px; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr 1fr; }} table {{ display: block; overflow-x: auto; }} }}
  </style>
</head>
<body>
  <main>
    <h1>每日策略环境匹配报告</h1>
    <p class="meta">日期 {esc(payload["date"])} | 生成 {esc(payload["generated_at"])}</p>
    <div class="grid">
      <div class="metric">全三 E/F 池<b>{esc(summary["all_three_ef_count"])}</b><span>{esc(delta_text)}</span></div>
      <div class="metric">提醒信号<b>{esc(stats["total_reminders"])}</b></div>
      <div class="metric">展示信号<b>{esc(len(rows))}</b><span>最佳适配/适配</span></div>
      <div class="metric">校准状态<b>{esc(cal["status"])}</b><span>{esc(cal["reason"] or "")}</span></div>
    </div>
    <p class="meta">行业聚焦：{esc(focus)}</p>
    <table>
      <thead>
        <tr>
          <th>股票</th>
          <th>行业</th>
          <th>策略</th>
          <th>生命周期</th>
          <th>适配度</th>
          <th>适配理由</th>
          <th>iFinD场景</th>
          <th>State</th>
          <th>SR</th>
          <th>统计</th>
        </tr>
      </thead>
      <tbody>{''.join(row_html)}</tbody>
    </table>
    <p class="note">本报告只展示策略信号与环境匹配事实；不输出具体操作指令；历史统计仅在校准质量闸门通过后展示。</p>
    <p class="note">iFinD 场景聚焦：{esc(len(ifind_rows))} 条同时具备策略最佳适配和公司质量摘要的信号。</p>
  </main>
</body>
</html>
"""


def build_daily_research_brief(date_str: str) -> dict[str, Any]:
    paths = paths_for(date_str)
    reminder = load_json(paths["reminder"], required=True)
    evaluation = load_json(paths["evaluation"], required=False)
    state_ef = load_json(paths["state_ef"], required=False)
    calibration = load_json(paths["calibration"], required=False)

    display = display_rows(reminder)
    ifind_focus = ifind_focus_rows(display)
    payload = {
        "schema_version": "daily_research_brief_v1",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_summary": build_market_summary(date_str, evaluation, state_ef),
        "signal_stats": brief_stats(reminder),
        "calibration": calibration_summary(calibration),
        "display_rows": display,
        "ifind_focus_rows": ifind_focus,
        "data_sources": {name: str(path) for name, path in paths.items()},
        "guardrails": [
            "Shows only strategy-environment matching facts.",
            "Does not generate strategy signals.",
            "Does not output action instructions.",
            "Unstable or missing calibration remains 待校准.",
        ],
        "research_only": True,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    date_ymd = ymd(date_str)
    json_path = OUT_DIR / f"daily_research_brief_{date_ymd}.json"
    md_path = OUT_DIR / f"daily_research_brief_{date_ymd}.md"
    latest_json = OUT_DIR / "daily_research_brief_latest.json"
    latest_md = OUT_DIR / "daily_research_brief_latest.md"
    html_path = PUBLIC_DIR / f"daily_research_brief_{date_ymd}.html"
    latest_html = PUBLIC_DIR / "daily_research_brief_latest.html"

    markdown = build_markdown(payload)
    html_text = build_html(payload, markdown)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(text, encoding="utf-8")
    latest_json.write_text(text, encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    latest_md.write_text(markdown, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    latest_html.write_text(html_text, encoding="utf-8")

    return {
        "ok": True,
        "date": date_str,
        "total_reminders": payload["signal_stats"]["total_reminders"],
        "display_count": len(display),
        "ifind_focus_count": len(ifind_focus),
        "fit_counts": payload["signal_stats"]["fit_counts"],
        "lifecycle_counts": payload["signal_stats"]["lifecycle_counts"],
        "focus_industries": payload["market_summary"]["focus_industries"],
        "calibration": payload["calibration"],
        "json": str(json_path),
        "markdown": str(md_path),
        "html": str(html_path),
        "latest_json": str(latest_json),
        "latest_markdown": str(latest_md),
        "latest_html": str(latest_html),
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build daily strategy-environment research brief.")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    result = build_daily_research_brief(args.date)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
