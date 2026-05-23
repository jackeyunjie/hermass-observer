#!/usr/bin/env python3
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INTRADAY_JSON = ROOT / "fixtures/anlu_688107_h1_terminal_views_20260201_20260519.json"
OUT_JSON = ROOT / "fixtures/anlu_boundary_state_views_20260415_20260519.json"
OUT_HTML = ROOT / "public/index.html"

SYMBOL = "688107.SH"
NAME = "安路科技"
ROW_LIMITS = {"MN1": 12, "W1": 12, "D1": 36, "H4": 36, "H1": 120}
TF_LABELS = {"MN1": "月线", "W1": "周线", "D1": "日线", "H4": "四小时", "H1": "小时"}
COLUMN_CN = {
    "品种": "品种",
    "时间": "时间",
    "MN1state": "月线状态",
    "W1state": "周线状态",
    "D1state": "日线状态",
    "H4state": "四小时状态",
    "H1state": "小时状态",
}
VALUE_CN = {
    None: "无",
    "neutral": "中性",
    "closed": "闭藏",
    "expansion_from_storage": "藏发",
    "expansion_start": "扩张起步",
    "expansion": "扩张",
    "strong_expansion": "强扩张",
    "contraction_start": "收缩起步",
    "contraction": "收缩",
    "active": "触发",
    "above_extreme": "强上破",
    "above": "上方",
    "break_up": "向上突破",
    "below_extreme": "强下破",
    "below": "下方",
    "break_down": "向下突破",
    "near_resistance": "接近压力",
    "near_support": "接近支撑",
    "bull_hidden": "多头潜伏",
    "bear_hidden": "空头潜伏",
    "bull_start": "多头启动",
    "bear_start": "空头启动",
    "bull_trend": "多头趋势",
    "bear_trend": "空头趋势",
    "flat_hidden": "平势潜伏",
    "long_up": "多头止损线上行",
    "short_down": "空头止损线下行",
    "rising": "上行",
    "falling": "下行",
    "double_sky": "双布林天位",
    "double_ground": "双布林地位",
    "high_high": "高位",
    "low_low": "低位",
}
INDICATOR_CN = {
    "kaufman_width_20": "考夫曼二十宽度",
    "bb_width_20": "布林二十宽度",
    "bb_width_50": "布林五十宽度",
    "kaufman_width_50": "考夫曼五十宽度",
    "atr_percent": "真实波幅百分比",
    "atr_percent_up": "真实波幅上轨",
    "atr_percent_up2": "真实波幅二上轨",
    "adx": "趋势强度",
    "plus_di": "正向指标",
    "minus_di": "负向指标",
    "support": "支撑",
    "resistance": "压力",
    "bbp": "布林百分位",
    "bbp_1": "布林百分位一",
}


def cn_value(value: Any) -> str:
    if value is None:
        return "无"
    return VALUE_CN.get(value, str(value))


def cn_formula(bits: dict[str, Any]) -> str:
    sign = "负" if bits.get("sign") == "-" else "正"
    return (
        f"{sign}（底座={bits.get('base')} + 波动={bits.get('volatility_bit')} "
        f"+ 位置={bits.get('position_bit')} + 趋势={bits.get('trend_bit')}）= {bits.get('score')}"
    )


def indicator_text(indicators: dict[str, Any]) -> str:
    parts = []
    for key, label_text in INDICATOR_CN.items():
        if key in indicators:
            parts.append(f"{label_text}={cn_value(indicators.get(key))}")
    return "；".join(parts)


def price_text(item: dict[str, Any]) -> str:
    price = item.get("ohlcv", {})
    fields = [
        ("开盘", price.get("open")),
        ("最高", price.get("high")),
        ("最低", price.get("low")),
        ("收盘", price.get("close")),
        ("成交量", price.get("volume")),
        ("成交额", price.get("amount")),
    ]
    return "；".join(f"{label}={cn_value(value)}" for label, value in fields)


def observation_text(item: dict[str, Any]) -> str:
    observation = item.get("observation", {})
    fields = [
        ("观察周期", TF_LABELS.get(observation.get("observing_timeframe"), observation.get("observing_timeframe"))),
        ("观察时间", observation.get("observing_time")),
        ("观察收盘价", observation.get("observing_close")),
        ("被观察周期", TF_LABELS.get(observation.get("observed_timeframe"), observation.get("observed_timeframe"))),
        ("被观察周期时间", observation.get("observed_time")),
        ("被观察周期原收盘价", observation.get("native_close")),
        ("被观察周期原状态码", observation.get("native_state_hex")),
    ]
    return "；".join(f"{label}={cn_value(value)}" for label, value in fields)


def audit_block(tf: str, item: dict[str, Any]) -> str:
    components = item.get("components", {})
    bits = item.get("bits", {})
    indicators = item.get("indicators", {})
    return (
        "<div class='audit-block'>"
        f"<h3>{html.escape(TF_LABELS.get(tf, tf))} @ {html.escape(str(item.get('time')))}</h3>"
        f"<p><strong>状态码</strong> {html.escape(str(components.get('state_hex')))}；"
        f"<strong>状态分数</strong> {html.escape(str(components.get('state_score')))}；"
        f"<strong>公式</strong> {html.escape(cn_formula(bits))}</p>"
        "<p>底座互斥规则：底座只能是 0 或 8，不能同时存在；波动、位置、趋势是另外三个独立组件。</p>"
        f"<p><strong>观察</strong>：{html.escape(observation_text(item))}</p>"
        f"<p><strong>被观察周期价格</strong>：{html.escape(price_text(item))}</p>"
        f"<p>底座={html.escape(str(bits.get('base')))}，"
        f"波动位={html.escape(str(bits.get('volatility_bit')))}，"
        f"位置位={html.escape(str(bits.get('position_bit')))}，"
        f"趋势位={html.escape(str(bits.get('trend_bit')))}，"
        f"方向={'负向' if bits.get('sign') == '-' else '正向'}</p>"
        f"<p>压缩={html.escape(cn_value(components.get('compression')))}，"
        f"波动={html.escape(cn_value(components.get('volatility')))}，"
        f"位置={html.escape(cn_value(components.get('position')))}，"
        f"趋势={html.escape(cn_value(components.get('trend')))}，"
        f"吊灯止损={html.escape(cn_value(components.get('atr_stop')))}，"
        f"布林位置={html.escape(cn_value(components.get('blp')))}，"
        f"波动展开={html.escape(cn_value(components.get('tbd')))}</p>"
        f"<p><strong>指标</strong>：{html.escape(indicator_text(indicators))}</p>"
        "</div>"
    )


def render_table(title: str, rows: list[dict[str, Any]], columns: list[str], audits: list[dict[str, Any]]) -> str:
    body = []
    detail_parts = []
    for idx, row in enumerate(rows):
        body.append("<tr>" + "".join(f"<td>{html.escape(str(row.get(col, '')))}</td>" for col in columns) + "</tr>")
        audit = audits[idx] if idx < len(audits) else {}
        row_title = f"{idx + 1}. {row.get('时间', '')}"
        audit_lines = [f"<h3 class='row-title'>{html.escape(row_title)}</h3>"]
        for tf, item in audit.get("states", {}).items():
            audit_lines.append(audit_block(tf, item))
        detail_parts.append(f"<article class='detail-card'>{''.join(audit_lines)}</article>")
    return f"""
<section>
  <div class="section-head">
    <div><h2>{html.escape(title)}</h2><p>左侧是状态结果表；右侧按同一行顺序展示价格和指标明细。</p></div>
    <span class="count">{len(rows)} 行</span>
  </div>
  <div class="result-detail-grid">
    <div class="table-wrap"><table><thead><tr>{''.join(f'<th>{html.escape(COLUMN_CN.get(col, col))}</th>' for col in columns)}</tr></thead><tbody>{''.join(body)}</tbody></table></div>
    <div class="detail-wrap">{''.join(detail_parts)}</div>
  </div>
</section>"""


def render_html(payload: dict[str, Any]) -> str:
    views = payload["views"]
    row_audit = payload["row_audit"]
    sections = [
        render_table("月线视角", views["MN1"], ["品种", "时间", "MN1state"], row_audit["MN1"]),
        render_table("周线视角", views["W1"], ["品种", "时间", "MN1state", "W1state"], row_audit["W1"]),
        render_table("日线视角", views["D1"], ["品种", "时间", "MN1state", "W1state", "D1state"], row_audit["D1"]),
        render_table("四小时视角", views["H4"], ["品种", "时间", "MN1state", "W1state", "D1state", "H4state"], row_audit["H4"]),
        render_table("小时视角", views["H1"], ["品种", "时间", "MN1state", "W1state", "D1state", "H4state", "H1state"], row_audit["H1"]),
    ]
    debug = payload.get("debug", {})
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>安路科技状态审计视角表</title>
  <style>
    :root{{--bg:#f4f6f8;--panel:#fff;--text:#17202a;--muted:#66717f;--line:#dbe2e8;--accent:#0f766e;--soft:#e7f4f2}}
    *{{box-sizing:border-box}}body{{margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--text)}}main{{max-width:1320px;margin:0 auto}}
    header,section{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:20px;margin-bottom:16px}}header{{border-top:6px solid var(--accent)}}h1{{margin:0 0 8px;font-size:30px}}h2{{margin:0;font-size:20px}}h3{{margin:0 0 6px;font-size:15px}}p{{margin:6px 0 0;color:var(--muted);line-height:1.55}}
    .meta{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin-top:16px}}.meta div{{border:1px solid var(--line);border-radius:8px;padding:12px;background:#fbfcfd}}.meta small{{display:block;color:var(--muted);margin-bottom:4px}}
    .section-head{{display:flex;justify-content:space-between;gap:16px;margin-bottom:14px}}.count{{border:1px solid #b9dad5;background:var(--soft);color:#115e59;border-radius:999px;padding:5px 10px;font-size:13px;font-weight:700;height:max-content;white-space:nowrap}}
    .result-detail-grid{{display:grid;grid-template-columns:minmax(420px,.9fr) minmax(520px,1.1fr);gap:14px;align-items:start}}.table-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:8px;position:sticky;top:12px}}table{{width:100%;border-collapse:collapse;min-width:560px}}th,td{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap;font-size:14px;vertical-align:top}}th{{background:#f8fafb;color:#3b4652;font-weight:700}}tr:last-child td{{border-bottom:0}}td:nth-child(n+3){{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:700}}
    .detail-wrap{{display:grid;gap:12px;max-height:760px;overflow:auto;padding-right:4px}}.detail-card{{border:1px solid var(--line);border-radius:8px;padding:12px;background:#fbfcfd}}.row-title{{font-size:15px;margin-bottom:8px;color:#17202a}}.audit-block{{border:1px solid var(--line);border-radius:8px;padding:10px;margin:8px 0;background:#fff}}.audit-block p{{font-size:13px;color:#334155}}
    @media(max-width:980px){{.result-detail-grid{{grid-template-columns:1fr}}.table-wrap{{position:static}}}}
  </style>
</head>
<body>
<main>
  <header>
    <h1>688107 {NAME} 状态审计视角表</h1>
    <p>不使用“上破、区间内、下破”状态捷径；每个状态都按状态编码公式和源码管道重新计算。</p>
    <div class="meta">
      <div><small>公式</small><strong>底座 0 或 8 互斥；状态分数绝对值等于底座加波动、位置、趋势</strong></div>
      <div><small>指标</small><strong>考夫曼宽度、布林宽度、真实波幅、趋势强度、支撑压力、吊灯止损</strong></div>
      <div><small>行数</small><strong>月线 {len(views['MN1'])} / 周线 {len(views['W1'])} / 日线 {len(views['D1'])} / 四小时 {len(views['H4'])} / 小时 {len(views['H1'])}</strong></div>
      <div><small>分钟源</small><strong>五分钟 {html.escape(str(debug.get('raw_5m_rows')))} 行</strong></div>
    </div>
  </header>
  {''.join(sections)}
</main>
</body>
</html>
"""


def main() -> int:
    if not INTRADAY_JSON.exists():
        raise RuntimeError(f"missing auditable source fixture: {INTRADAY_JSON}")
    source = json.loads(INTRADAY_JSON.read_text(encoding="utf-8"))
    payload = {
        **source,
        "schema_version": "anlu_boundary_state_views_auditable_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "row_limits": ROW_LIMITS,
        "homepage_source_fixture": str(INTRADAY_JSON),
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({key: len(payload["views"][key]) for key in ["MN1", "W1", "D1", "H4", "H1"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
