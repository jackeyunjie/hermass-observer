"""Backtest HTML report generator."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def generate_report(
    result: dict,
    out_html: Path,
) -> Path:
    """生成回测 HTML 报告."""
    m = result.get('metrics', {})
    trades = result.get('trades', [])
    equity = result.get('equity_curve', [])

    # equity curve data for JS chart
    chart_labels = [s['date'] for s in equity]
    chart_equity = [s['total_equity'] for s in equity]
    chart_drawdown = [-s['drawdown_pct'] * 100 for s in equity]

    # trades table
    trade_rows = ''
    for t in trades[:200]:  # 最多展示 200 笔
        pnl_class = 'win' if t['net_pnl'] > 0 else 'loss'
        trade_rows += f"""<tr class="{pnl_class}">
  <td>{html.escape(t['stock_code'])}</td><td>{html.escape(t['stock_name'])}</td>
  <td>{t['entry_date']}</td><td>{t['exit_date']}</td>
  <td>{t['entry_price']}</td><td>{t['exit_price']}</td>
  <td>{t['ef_count']}</td><td>{html.escape(t['exit_reason'])}</td>
  <td>{t['return_pct']:.2%}</td><td>{t['net_pnl']:,.0f}</td>
  <td>{t['hold_days']}</td>
</tr>"""

    # exit reasons
    exit_items = ''
    for reason, count in (m.get('exit_reasons') or {}).items():
        exit_items += f'<div class="stat"><div class="label">{html.escape(reason)}</div><div class="value">{count}</div></div>'

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>E/F Strategy Backtest Report</title>
<style>
:root {{ --text:#1f2937; --muted:#667085; --line:#d7dde6; --soft:#f6f8fb;
  --green:#059669; --red:#dc2626; --blue:#2563eb; }}
* {{ margin:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;
  color:var(--text); background:#fff; }}
main {{ max-width:1400px; margin:0 auto; padding:24px; }}
h1 {{ font-size:24px; margin-bottom:8px; }}
h2 {{ font-size:18px; margin:24px 0 12px; color:var(--muted); }}
.disclaimer {{ background:#fef3c7; border:1px solid #f59e0b; border-radius:6px;
  padding:10px 14px; font-size:13px; margin-bottom:20px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:8px; margin:12px 0; }}
.stat {{ border:1px solid var(--line); border-radius:6px; padding:10px 12px; background:var(--soft); }}
.stat .label {{ font-size:12px; color:var(--muted); }}
.stat .value {{ font-size:20px; font-weight:700; margin-top:2px; }}
.stat .value.win {{ color:var(--green); }}
.stat .value.loss {{ color:var(--red); }}
.chart-container {{ width:100%; height:300px; margin:16px 0; position:relative; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; margin-top:12px; }}
th,td {{ border:1px solid var(--line); padding:5px 8px; text-align:left; }}
th {{ background:var(--soft); position:sticky; top:0; font-weight:600; }}
tr.win td {{ color:var(--green); }}
tr.loss td {{ color:var(--red); }}
.table-wrap {{ max-height:500px; overflow:auto; margin-top:12px; }}
</style>
</head>
<body>
<main>
<div class="disclaimer"><strong>Research-Only</strong> - 本回测仅为技术验证，不构成投资建议。历史表现不代表未来收益。</div>
<h1>E/F Strategy Backtest Report</h1>
<p style="color:var(--muted)">{result.get('backtest_date','')} | {result.get('total_trading_days',0)} trading days | {result.get('warmup_days',0)} warmup</p>

<h2>Performance Summary</h2>
<div class="grid">
  <div class="stat"><div class="label">Total Trades</div><div class="value">{m.get('total_trades',0)}</div></div>
  <div class="stat"><div class="label">Win Rate</div><div class="value {'win' if m.get('win_rate',0)>0.5 else 'loss'}">{m.get('win_rate',0):.1%}</div></div>
  <div class="stat"><div class="label">Avg Return</div><div class="value {'win' if m.get('avg_return_pct',0)>0 else 'loss'}">{m.get('avg_return_pct',0):.2%}</div></div>
  <div class="stat"><div class="label">Profit Factor</div><div class="value">{m.get('profit_factor',0):.2f}</div></div>
  <div class="stat"><div class="label">Sharpe Ratio</div><div class="value">{m.get('sharpe_ratio',0):.2f}</div></div>
  <div class="stat"><div class="label">Sortino Ratio</div><div class="value">{m.get('sortino_ratio',0):.2f}</div></div>
  <div class="stat"><div class="label">Max Drawdown</div><div class="value loss">{m.get('max_drawdown_pct',0):.2%}</div></div>
  <div class="stat"><div class="label">Calmar Ratio</div><div class="value">{m.get('calmar_ratio',0):.2f}</div></div>
  <div class="stat"><div class="label">Annual Return</div><div class="value {'win' if m.get('annualized_return',0)>0 else 'loss'}">{m.get('annualized_return',0):.2%}</div></div>
  <div class="stat"><div class="label">Annual Volatility</div><div class="value">{m.get('annualized_volatility',0):.2%}</div></div>
  <div class="stat"><div class="label">Payoff Ratio</div><div class="value">{m.get('payoff_ratio',0):.2f}</div></div>
  <div class="stat"><div class="label">Avg Hold Days</div><div class="value">{m.get('avg_hold_days',0):.1f}</div></div>
  <div class="stat"><div class="label">Max Win Streak</div><div class="value win">{m.get('max_consecutive_wins',0)}</div></div>
  <div class="stat"><div class="label">Max Loss Streak</div><div class="value loss">{m.get('max_consecutive_losses',0)}</div></div>
</div>

<h2>Exit Reasons</h2>
<div class="grid">{exit_items}</div>

<h2>Equity Curve</h2>
<div class="chart-container"><canvas id="equityChart"></canvas></div>

<h2>Drawdown</h2>
<div class="chart-container"><canvas id="ddChart"></canvas></div>

<h2>Trade Log ({len(trades)} trades)</h2>
<div class="table-wrap">
<table>
<thead><tr><th>Code</th><th>Name</th><th>Entry</th><th>Exit</th>
<th>Entry Px</th><th>Exit Px</th><th>EF</th><th>Reason</th>
<th>Return</th><th>PnL</th><th>Days</th></tr></thead>
<tbody>{trade_rows}</tbody>
</table>
</div>
</main>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script>
const labels = {json.dumps(chart_labels)};
const equity = {json.dumps(chart_equity)};
const drawdown = {json.dumps(chart_drawdown)};

new Chart(document.getElementById('equityChart'), {{
  type:'line',
  data:{{ labels, datasets:[{{ label:'Equity', data:equity, borderColor:'#2563eb', borderWidth:1.5, pointRadius:0, fill:false }}] }},
  options:{{ responsive:true, maintainAspectRatio:false, plugins:{{ legend:{{ display:false }} }},
    scales:{{ x:{{ display:true, ticks:{{ maxTicksLimit:12 }} }} }} }}
}});

new Chart(document.getElementById('ddChart'), {{
  type:'line',
  data:{{ labels, datasets:[{{ label:'Drawdown %', data:drawdown, borderColor:'#dc2626', borderWidth:1.5, pointRadius:0, fill:true, backgroundColor:'rgba(220,38,38,0.1)' }}] }},
  options:{{ responsive:true, maintainAspectRatio:false, plugins:{{ legend:{{ display:false }} }},
    scales:{{ x:{{ display:true, ticks:{{ maxTicksLimit:12 }} }}, y:{{ ticks:{{ callback:v=>v.toFixed(1)+'%' }} }} }} }}
}});
</script>
</body>
</html>"""

    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(doc, encoding='utf-8')
    return out_html


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate backtest HTML report')
    parser.add_argument('--backtest-dir', type=Path, required=True)
    parser.add_argument('--out-html', type=Path, required=True)
    args = parser.parse_args()

    result_path = args.backtest_dir / 'backtest_result.json'
    if not result_path.exists():
        raise FileNotFoundError(f"Backtest result not found: {result_path}")

    result = json.loads(result_path.read_text(encoding='utf-8'))
    out = generate_report(result, args.out_html)
    print(f"Report generated: {out}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
