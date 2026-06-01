#!/usr/bin/env python3
"""
分析 688107 (安路科技) 资金流数据
按 1天、3天、累计(4天) 维度观察
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from datetime import datetime
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HERMASS = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")
DATA_DIR = HERMASS / "data"
OUT_DIR = ROOT / "public"

# 可用数据日期（按时间顺序）
DATES = ["2026-05-14", "2026-05-15", "2026-05-18", "2026-05-19"]


def load_moneyflow(date: str) -> dict[str, Any] | None:
    path = DATA_DIR / f"blackwolf_ashare_moneyflow_{date.replace('-', '')}_{date.replace('-', '')}.csv"
    if not path.exists():
        return None
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if row.get("stock_code") == "688107.SH":
            return row
    return None


def parse_float(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def analyze_day(row: dict[str, Any] | None, date: str) -> dict[str, Any]:
    if row is None:
        return {"date": date, "available": False}

    buy_tdd = parse_float(row.get("buytddcje"))  # 主买特大单
    buy_dd = parse_float(row.get("buyddcje"))  # 主买大单
    buy_zd = parse_float(row.get("buyzdcje"))  # 主买中单
    buy_sd = parse_float(row.get("buysdcje"))  # 主买小单
    sell_tdd = parse_float(row.get("selltddcje"))  # 主卖特大单
    sell_dd = parse_float(row.get("sellddcje"))  # 主卖大单
    sell_zd = parse_float(row.get("sellzdcje"))  # 主卖中单
    sell_sd = parse_float(row.get("sellxdcje"))  # 主卖小单

    buy_num = parse_float(row.get("buynum"))
    sell_num = parse_float(row.get("sellnum"))

    active_buy = buy_tdd + buy_dd + buy_zd + buy_sd
    active_sell = sell_tdd + sell_dd + sell_zd + sell_sd
    net_flow = active_buy - active_sell

    large_buy = buy_tdd + buy_dd
    large_sell = sell_tdd + sell_dd
    large_net = large_buy - large_sell

    super_buy = buy_tdd
    super_sell = sell_tdd
    super_net = super_buy - super_sell

    mid_buy = buy_zd
    mid_sell = sell_zd
    mid_net = mid_buy - mid_sell

    small_buy = buy_sd
    small_sell = sell_sd
    small_net = small_buy - small_sell

    total_turnover = active_buy + active_sell
    buy_ratio = active_buy / total_turnover * 100 if total_turnover > 0 else 0
    sell_ratio = active_sell / total_turnover * 100 if total_turnover > 0 else 0

    return {
        "date": date,
        "available": True,
        "主买总额": round(active_buy, 2),
        "主卖总额": round(active_sell, 2),
        "主动净额": round(net_flow, 2),
        "特大单主买": round(super_buy, 2),
        "特大单主卖": round(super_sell, 2),
        "特大单净额": round(super_net, 2),
        "大单主买": round(buy_dd, 2),
        "大单主卖": round(sell_dd, 2),
        "大单净额": round(buy_dd - sell_dd, 2),
        "大额主买(特大+大)": round(large_buy, 2),
        "大额主卖(特大+大)": round(large_sell, 2),
        "大额净额": round(large_net, 2),
        "中单净额": round(mid_net, 2),
        "小单净额": round(small_net, 2),
        "主买单数": int(buy_num),
        "主卖单数": int(sell_num),
        "总成交额": round(total_turnover, 2),
        "主买占比%": round(buy_ratio, 2),
        "主卖占比%": round(sell_ratio, 2),
    }


def aggregate(days: list[dict[str, Any]]) -> dict[str, Any]:
    """聚合多天的资金流数据"""
    if not days or not all(d.get("available") for d in days):
        return {"available": False, "days": len(days)}

    result = {
        "period": f"{days[0]['date']} ~ {days[-1]['date']}",
        "days": len(days),
        "available": True,
        "主买总额": round(sum(d["主买总额"] for d in days), 2),
        "主卖总额": round(sum(d["主卖总额"] for d in days), 2),
        "主动净额": round(sum(d["主动净额"] for d in days), 2),
        "特大单主买": round(sum(d["特大单主买"] for d in days), 2),
        "特大单主卖": round(sum(d["特大单主卖"] for d in days), 2),
        "特大单净额": round(sum(d["特大单净额"] for d in days), 2),
        "大单主买": round(sum(d["大单主买"] for d in days), 2),
        "大单主卖": round(sum(d["大单主卖"] for d in days), 2),
        "大单净额": round(sum(d["大单净额"] for d in days), 2),
        "大额主买(特大+大)": round(sum(d["大额主买(特大+大)"] for d in days), 2),
        "大额主卖(特大+大)": round(sum(d["大额主卖(特大+大)"] for d in days), 2),
        "大额净额": round(sum(d["大额净额"] for d in days), 2),
        "中单净额": round(sum(d["中单净额"] for d in days), 2),
        "小单净额": round(sum(d["小单净额"] for d in days), 2),
        "主买单数": sum(d["主买单数"] for d in days),
        "主卖单数": sum(d["主卖单数"] for d in days),
        "总成交额": round(sum(d["总成交额"] for d in days), 2),
    }

    total = result["总成交额"]
    if total > 0:
        result["主买占比%"] = round(result["主买总额"] / total * 100, 2)
        result["主卖占比%"] = round(result["主卖总额"] / total * 100, 2)

    return result


def fmt_money(v: float) -> str:
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}亿"
    elif abs(v) >= 1e4:
        return f"{v / 1e4:.2f}万"
    else:
        return f"{v:.2f}"


def row_color(v: float) -> str:
    if v > 0:
        return "color:#d32f2f;font-weight:bold"
    elif v < 0:
        return "color:#388e3c;font-weight:bold"
    return ""


def td(val, style=""):
    s = row_color(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else ""
    if style:
        s = style + ";" + s if s else style
    display = fmt_money(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else str(val)
    return f'<td style="{s}">{display}</td>'


def generate_html(daily: list[dict], agg_1d: list[dict], agg_3d: dict, agg_all: dict) -> str:
    """生成 HTML 分析报告"""

    # 日报表
    daily_rows = ""
    for d in daily:
        if not d.get("available"):
            daily_rows += f'<tr><td>{d["date"]}</td><td colspan="10">数据不可用</td></tr>'
            continue
        daily_rows += f"""<tr>
            <td>{d["date"]}</td>
            {td(d["主动净额"])}
            {td(d["特大单净额"])}
            {td(d["大单净额"])}
            {td(d["大额净额"])}
            {td(d["中单净额"])}
            {td(d["小单净额"])}
            <td>{d["主买占比%"]}%</td>
            <td>{d["主卖占比%"]}%</td>
            <td>{fmt_money(d["总成交额"])}</td>
            <td>{d["主买单数"]}/{d["主卖单数"]}</td>
        </tr>"""

    # 聚合报表
    def agg_row(label: str, data: dict):
        if not data.get("available"):
            return f'<tr><td>{label}</td><td colspan="10">数据不可用</td></tr>'
        return f"""<tr>
            <td>{label}<br><small>{data.get("period", "")}</small></td>
            {td(data["主动净额"])}
            {td(data["特大单净额"])}
            {td(data["大单净额"])}
            {td(data["大额净额"])}
            {td(data["中单净额"])}
            {td(data["小单净额"])}
            <td>{data.get("主买占比%", "N/A")}%</td>
            <td>{data.get("主卖占比%", "N/A")}%</td>
            <td>{fmt_money(data["总成交额"])}</td>
            <td>{data["主买单数"]}/{data["主卖单数"]}</td>
        </tr>"""

    # 生成图表数据 JSON
    chart_data = {
        "dates": [d["date"] for d in daily if d.get("available")],
        "netFlow": [d["主动净额"] for d in daily if d.get("available")],
        "largeNet": [d["大额净额"] for d in daily if d.get("available")],
        "superNet": [d["特大单净额"] for d in daily if d.get("available")],
        "midNet": [d["中单净额"] for d in daily if d.get("available")],
        "smallNet": [d["小单净额"] for d in daily if d.get("available")],
        "buyRatio": [d["主买占比%"] for d in daily if d.get("available")],
        "turnover": [round(d["总成交额"] / 1e8, 2) for d in daily if d.get("available")],
    }

    # 卡片颜色类
    def card_cls(v):
        if v > 0:
            return "pos"
        elif v < 0:
            return "neg"
        return "neu"

    # 分析文字
    analysis = generate_analysis_text(daily, agg_3d, agg_all)

    chart_data_json = json.dumps(chart_data, ensure_ascii=False)

    html = (
        """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>688107 安路科技 - 资金流分析</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
body { margin:0; padding:24px; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f6f8fa; color:#17202a; }
main { max-width:1400px; margin:0 auto; }
header, section { background:white; border:1px solid #dbe3ea; border-radius:8px; padding:20px; margin-bottom:16px; }
h1 { margin:0 0 8px; font-size:22px; }
h2 { margin:0 0 12px; font-size:16px; color:#37474f; }
p { color:#607080; margin:4px 0; }
.wrap { overflow:auto; border:1px solid #e5ebf0; border-radius:6px; }
table { border-collapse:collapse; width:100%; min-width:900px; font-size:13px; }
th, td { padding:10px 12px; border-bottom:1px solid #e5ebf0; text-align:center; white-space:nowrap; }
th { background:#f8fafb; font-weight:600; color:#455a64; position:sticky; top:0; }
tr:hover { background:#f8fafb; }
.chart { width:100%; height:380px; margin:10px 0; }
.summary { display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:12px; margin:12px 0; }
.card { background:#f8fafb; border-radius:6px; padding:14px; text-align:center; }
.card .label { font-size:12px; color:#78909c; margin-bottom:4px; }
.card .value { font-size:20px; font-weight:700; }
.pos { color:#d32f2f; }
.neg { color:#388e3c; }
.neu { color:#607d8b; }
.note { background:#fff8e1; border-left:3px solid #ffc107; padding:10px 14px; margin:10px 0; font-size:13px; color:#5d4037; }
</style>
</head>
<body>
<main>
<header>
<h1>688107 安路科技 - 资金流分析</h1>
<p>观察周期：最近 4 个交易日（API 数据保留限制）</p>
<p>数据日期：2026-05-14 ~ 2026-05-19（5/16-17 为周末）</p>
<div class="note">
<b>数据说明：</b>黑狼数据 API 的资金流历史数据仅保留最近 4 个交易日。5/16-17 为周末非交易日。分析基于可用 4 天数据，按 1天/3天/累计 维度展开。
</div>
</header>

<section>
<h2>一、每日资金流明细</h2>
<div class="wrap">
<table>
<thead>
<tr>
<th>日期</th>
<th>主动净额</th>
<th>特大单净额</th>
<th>大单净额</th>
<th>大额净额<br>(特大+大)</th>
<th>中单净额</th>
<th>小单净额</th>
<th>主买占比</th>
<th>主卖占比</th>
<th>总成交额</th>
<th>主买/卖单数</th>
</tr>
</thead>
<tbody>
"""
        + daily_rows
        + """
</tbody>
</table>
</div>
</section>

<section>
<h2>二、多维度聚合对比</h2>
<div class="wrap">
<table>
<thead>
<tr>
<th>观察维度</th>
<th>主动净额</th>
<th>特大单净额</th>
<th>大单净额</th>
<th>大额净额<br>(特大+大)</th>
<th>中单净额</th>
<th>小单净额</th>
<th>主买占比</th>
<th>主卖占比</th>
<th>总成交额</th>
<th>主买/卖单数</th>
</tr>
</thead>
<tbody>
"""
        + agg_row("最近1天 (5/19)", agg_1d[-1] if agg_1d else {})
        + """
"""
        + agg_row("最近3天 (5/15-5/19)", agg_3d)
        + """
"""
        + agg_row("累计4天 (5/14-5/19)", agg_all)
        + """
</tbody>
</table>
</div>
</section>

<section>
<h2>三、关键指标汇总卡片</h2>
<div class="summary">
<div class="card">
<div class="label">4天主动净额</div>
<div class="value """
        + card_cls(agg_all.get("主动净额", 0))
        + """">"""
        + fmt_money(agg_all.get("主动净额", 0))
        + """</div>
</div>
<div class="card">
<div class="label">4天大额净额</div>
<div class="value """
        + card_cls(agg_all.get("大额净额", 0))
        + """">"""
        + fmt_money(agg_all.get("大额净额", 0))
        + """</div>
</div>
<div class="card">
<div class="label">4天特大单净额</div>
<div class="value """
        + card_cls(agg_all.get("特大单净额", 0))
        + """">"""
        + fmt_money(agg_all.get("特大单净额", 0))
        + """</div>
</div>
<div class="card">
<div class="label">4天中单净额</div>
<div class="value """
        + card_cls(agg_all.get("中单净额", 0))
        + """">"""
        + fmt_money(agg_all.get("中单净额", 0))
        + """</div>
</div>
<div class="card">
<div class="label">4天小单净额</div>
<div class="value """
        + card_cls(agg_all.get("小单净额", 0))
        + """">"""
        + fmt_money(agg_all.get("小单净额", 0))
        + """</div>
</div>
<div class="card">
<div class="label">总成交额</div>
<div class="value neu">"""
        + fmt_money(agg_all.get("总成交额", 0))
        + """</div>
</div>
</div>
</section>

<section>
<h2>四、资金流趋势图</h2>
<div id="chart1" class="chart"></div>
<div id="chart2" class="chart"></div>
<div id="chart3" class="chart"></div>
</section>

<section>
<h2>五、分析结论</h2>
<div style="font-size:14px;line-height:1.8;color:#37474f;">
"""
        + analysis
        + """
</div>
</section>

</main>
<script>
const chartData = """
        + chart_data_json
        + """;

// 图1：各层级净额对比
const chart1 = echarts.init(document.getElementById('chart1'));
chart1.setOption({
    title: { text: '每日各层级资金净额', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['特大单净额', '大单净额', '中单净额', '小单净额'], bottom: 0 },
    grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
    xAxis: { type: 'category', data: chartData.dates },
    yAxis: { type: 'value', name: '金额(元)', axisLabel: { formatter: v => (v/1e8).toFixed(1)+'亿' } },
    series: [
        { name: '特大单净额', type: 'bar', stack: 'total', data: chartData.superNet, itemStyle: { color: '#d32f2f' } },
        { name: '大单净额', type: 'bar', stack: 'total', data: chartData.largeNet.map((v,i) => v - chartData.superNet[i]), itemStyle: { color: '#f57c00' } },
        { name: '中单净额', type: 'bar', stack: 'total', data: chartData.midNet, itemStyle: { color: '#fbc02d' } },
        { name: '小单净额', type: 'bar', stack: 'total', data: chartData.smallNet, itemStyle: { color: '#388e3c' } },
    ]
});

// 图2：主动净额与成交额
const chart2 = echarts.init(document.getElementById('chart2'));
chart2.setOption({
    title: { text: '主动净额 vs 成交额', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { data: ['主动净额', '成交额'], bottom: 0 },
    grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
    xAxis: { type: 'category', data: chartData.dates },
    yAxis: [
        { type: 'value', name: '净额(元)', axisLabel: { formatter: v => (v/1e8).toFixed(1)+'亿' } },
        { type: 'value', name: '成交额(亿)', axisLabel: { formatter: v => v+'亿' } },
    ],
    series: [
        { name: '主动净额', type: 'bar', data: chartData.netFlow, itemStyle: { color: p => p.value >= 0 ? '#d32f2f' : '#388e3c' } },
        { name: '成交额', type: 'line', yAxisIndex: 1, data: chartData.turnover, itemStyle: { color: '#1976d2' }, lineStyle: { width: 3 } },
    ]
});

// 图3：主买占比趋势
const chart3 = echarts.init(document.getElementById('chart3'));
chart3.setOption({
    title: { text: '主买占比趋势', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '10%', containLabel: true },
    xAxis: { type: 'category', data: chartData.dates },
    yAxis: { type: 'value', name: '占比(%)', min: 40, max: 60, axisLabel: { formatter: v => v+'%' } },
    series: [
        { name: '主买占比', type: 'line', data: chartData.buyRatio, itemStyle: { color: '#d32f2f' }, lineStyle: { width: 3 }, areaStyle: { color: 'rgba(211,47,47,0.1)' }, markLine: { data: [{ yAxis: 50, label: { formatter: '均衡线' } }] } },
    ]
});

window.addEventListener('resize', () => { chart1.resize(); chart2.resize(); chart3.resize(); });
</script>
</body>
</html>"""
    )
    return html


def generate_analysis_text(daily: list[dict], agg_3d: dict, agg_all: dict) -> str:
    """生成分析文字"""
    lines = []

    # 1天视角
    d_last = daily[-1] if daily else {}
    if d_last.get("available"):
        net = d_last["主动净额"]
        large = d_last["大额净额"]
        ratio = d_last["主买占比%"]
        lines.append(f"<b>【1天视角 - 最新交易日 {d_last['date']}】</b>")
        direction = "净流入" if net > 0 else "净流出"
        lines.append(f"当日资金{direction} {fmt_money(abs(net))}，主买占比 {ratio}%。")
        if large > 0:
            lines.append(f"大额资金（特大+大单）净流入 {fmt_money(large)}，显示机构/大户态度积极。")
        else:
            lines.append(f"大额资金（特大+大单）净流出 {fmt_money(abs(large))}，机构/大户态度谨慎。")
        lines.append("")

    # 3天视角
    if agg_3d.get("available"):
        net = agg_3d["主动净额"]
        large = agg_3d["大额净额"]
        ratio = agg_3d.get("主买占比%", 50)
        lines.append(f"<b>【3天视角 - {agg_3d['period']}】</b>")
        direction = "净流入" if net > 0 else "净流出"
        lines.append(f"3日累计资金{direction} {fmt_money(abs(net))}，主买占比 {ratio}%。")
        if large > 0:
            lines.append(f"3日大额资金净流入 {fmt_money(large)}，中期资金面向好。")
        else:
            lines.append(f"3日大额资金净流出 {fmt_money(abs(large))}，中期资金面承压。")
        lines.append("")

    # 累计视角
    if agg_all.get("available"):
        net = agg_all["主动净额"]
        large = agg_all["大额净额"]
        super_net = agg_all["特大单净额"]
        mid = agg_all["中单净额"]
        small = agg_all["小单净额"]
        ratio = agg_all.get("主买占比%", 50)
        lines.append(f"<b>【累计视角 - {agg_all['period']} (4天)】</b>")
        direction = "净流入" if net > 0 else "净流出"
        lines.append(
            f"4日累计资金{direction} {fmt_money(abs(net))}，主买占比 {ratio}%，总成交额 {fmt_money(agg_all['总成交额'])}。"
        )

        # 结构分析
        if super_net > 0 and large > 0:
            lines.append(
                f"特大单净流入 {fmt_money(super_net)}，大额资金整体净流入 {fmt_money(large)}，表明大资金在持续吸筹。"
            )
        elif super_net < 0 and large < 0:
            lines.append(
                f"特大单净流出 {fmt_money(abs(super_net))}，大额资金整体净流出 {fmt_money(abs(large))}，表明大资金在持续撤离。"
            )
        else:
            lines.append(
                f"特大单{'净流入' if super_net > 0 else '净流出'} {fmt_money(abs(super_net))}，大单{'净流入' if agg_all['大单净额'] > 0 else '净流出'} {fmt_money(abs(agg_all['大单净额']))}，大资金态度分化。"
            )

        if mid > 0:
            lines.append(f"中单净流入 {fmt_money(mid)}，中等规模资金参与积极。")
        else:
            lines.append(f"中单净流出 {fmt_money(abs(mid))}，中等规模资金在撤退。")

        if small > 0:
            lines.append(f"小单净流入 {fmt_money(small)}，散户跟风买入。")
        else:
            lines.append(f"小单净流出 {fmt_money(abs(small))}，散户在抛售。")

        lines.append("")

    # 趋势判断
    lines.append("<b>【综合判断】</b>")
    if agg_all.get("available"):
        net = agg_all["主动净额"]
        large = agg_all["大额净额"]
        if net > 0 and large > 0:
            lines.append("资金面整体呈<b>净流入</b>状态，且大额资金同步流入，资金面向好。")
        elif net < 0 and large < 0:
            lines.append("资金面整体呈<b>净流出</b>状态，且大额资金同步流出，资金面偏空。")
        elif net > 0 > large:
            lines.append("资金面整体净流入，但大额资金流出，存在<b>散户买、机构卖</b>的分化迹象，需谨慎。")
        else:
            lines.append(
                "资金面整体净流出，但大额资金流入，存在<b>机构吸筹、散户抛售</b>的可能，关注后续动向。"
            )

    return "<br>".join(lines)


def main() -> int:
    # 加载每日数据
    daily = [analyze_day(load_moneyflow(d), d) for d in DATES]

    # 1天维度（每一天）
    agg_1d = daily

    # 3天维度（最近3天：5/15, 5/18, 5/19）
    available_days = [d for d in daily if d.get("available")]
    agg_3d = aggregate(available_days[-3:])

    # 全部累计
    agg_all = aggregate(available_days)

    # 生成报告
    report = {
        "stock_code": "688107.SH",
        "stock_name": "安路科技",
        "analysis_date": datetime.now().isoformat(),
        "data_dates": DATES,
        "data_limit_note": "API仅保留最近4个交易日资金流历史数据",
        "daily": daily,
        "aggregate_3d": agg_3d,
        "aggregate_all": agg_all,
    }

    # 保存 JSON
    out_json = ROOT / "fixtures/688107_moneyflow_analysis.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 保存 HTML
    out_html = OUT_DIR / "688107_moneyflow_analysis.html"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_html.write_text(generate_html(daily, agg_1d, agg_3d, agg_all), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "PASS",
                "json": str(out_json),
                "html": str(out_html),
                "dates": DATES,
                "aggregate_3d": agg_3d,
                "aggregate_all": agg_all,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
