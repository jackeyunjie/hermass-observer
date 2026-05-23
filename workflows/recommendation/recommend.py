#!/usr/bin/env python3
"""Quantitative Trading Portfolio Recommendation Engine.

Runs independently. Loads P116 daily E/F breakout data, applies fundamental filters 
using Black Wolf API, ranks candidates, and calls DeepSeek to output the daily
observation portfolio report in Markdown and JSON formats.
"""

import argparse
import json
import os
import sys
from pathlib import Path
import requests
import yaml

# Resolve paths relative to this script
MODULE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.deepseek_context import with_deepseek_context


def load_config() -> dict:
    config_path = MODULE_ROOT / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def fetch_fundamental_metrics(stock_code: str, token: str) -> tuple[float | None, float | None]:
    """Fetch ROE and net profit growth for a single stock from Black Wolf API.
    
    Returns (roe, profit_inc) or (None, None) if the API call fails / times out.
    A None result means data is unavailable — the caller should allow the stock to
    pass through the filter rather than treating it as failing the criterion.
    """
    url = "https://api.fxyz.site/wolf/financemetric"
    clean_code = stock_code.split(".")[0]
    params = {"code": clean_code, "token": token}
    
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                latest_report = data[0]
                roe = float(latest_report.get("roe") or 0.0)
                profit_inc = float(latest_report.get("profitInc") or 0.0)
                return roe, profit_inc
    except Exception as e:
        print(f"  [Warning] Failed to fetch fundamentals for {clean_code}: {e}", file=sys.stderr)
    
    # Return None to signal "data unavailable" — do NOT return 0.0 which would
    # incorrectly exclude the stock from the filter.
    return None, None


def run_recommendation(date_str: str, config: dict) -> dict:
    ymd = date_str.replace("-", "")
    
    # Locate inputs from standard output directory of pipeline
    snapshot_path = PROJECT_ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_{ymd}.json"
    diff_path = PROJECT_ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_diff_{ymd}.json"
    
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Missing P116 daily snapshot: {snapshot_path}")
        
    snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    diff_data = json.loads(diff_path.read_text(encoding="utf-8")) if diff_path.exists() else {}
    
    all_candidates = snapshot_data.get("rows", [])
    
    # Get Black Wolf Token for fundamental filters
    bw_token = os.environ.get("BLACKWOLF_TOKEN")
    strat_cfg = config.get("strategy", {})
    enable_filter = strat_cfg.get("enable_fundamental_filter", True)
    
    filtered_candidates = []
    
    print(f"Processing {len(all_candidates)} candidates for {date_str}...", flush=True)
    
    for item in all_candidates:
        symbol = item.get("symbol")
        code = item.get("stock_code")
        name = item.get("stock_name")
        
        roe = None
        profit_inc = None
        passed = True
        
        if enable_filter and bw_token:
            roe, profit_inc = fetch_fundamental_metrics(code, bw_token)
            min_roe = strat_cfg.get("min_roe_pct", 8.0)
            min_growth = strat_cfg.get("min_net_profit_growth_pct", 0.0)
            
            # Only apply filter when we have actual data.
            # If fetch failed (None), let the stock pass — don't penalise API timeouts.
            if roe is not None and profit_inc is not None:
                if roe < min_roe or profit_inc < min_growth:
                    passed = False
        
        if passed:
            enriched_item = dict(item)
            # Store None explicitly so the table shows "-" instead of "0.00%"
            enriched_item["roe"] = roe
            enriched_item["profit_inc"] = profit_inc
            filtered_candidates.append(enriched_item)
            
    # Sort candidates: state_score_sum desc, ef_strength desc, d1_adx14 desc
    # (Matches current database rankings)
    filtered_candidates.sort(
        key=lambda x: (
            -(x.get("state_score_sum") or 0),
            -(x.get("ef_strength") or 0),
            -(x.get("d1_adx14") or 0.0)
        )
    )
    
    # Slice to portfolio size limit
    max_size = strat_cfg.get("max_portfolio_size", 10)
    portfolio = filtered_candidates[:max_size]
    
    # 3. Call DeepSeek to format the investor-facing markdown report
    report_md = call_deepseek_llm(date_str, portfolio, diff_data, config)
    
    # Create outputs folder under workflow
    outputs_dir = MODULE_ROOT / "outputs"
    outputs_dir.mkdir(exist_ok=True)
    
    # Generate Markdown Table
    md_table = build_markdown_table(portfolio)
    full_report_md = f"{report_md}\n\n## 📊 精选组合数据表\n\n{md_table}"
    
    # Save outputs
    md_output_path = outputs_dir / f"recommendation_{ymd}.md"
    json_output_path = outputs_dir / f"recommendation_{ymd}.json"
    html_output_path = outputs_dir / f"recommendation_{ymd}.html"
    
    md_output_path.write_text(full_report_md, encoding="utf-8")
    
    output_json = {
        "date": date_str,
        "generated_at": snapshot_data.get("generated_at"),
        "total_candidates": len(all_candidates),
        "passed_filter_count": len(filtered_candidates),
        "portfolio": portfolio,
        "report_markdown_path": str(md_output_path),
        "report_html_path": str(html_output_path)
    }
    
    with json_output_path.open("w", encoding="utf-8") as f:
        json.dump(output_json, f, ensure_ascii=False, indent=2)
        
    # Copy latest & compile HTML reports
    public_dir = PROJECT_ROOT / "public"
    public_dir.mkdir(exist_ok=True)
    (public_dir / "recommendation_latest.md").write_text(full_report_md, encoding="utf-8")
    
    generated_at = snapshot_data.get("generated_at") or ""
    html_content = build_html_report(date_str, portfolio, diff_data, report_md, generated_at)
    html_output_path.write_text(html_content, encoding="utf-8")
    (public_dir / f"recommendation_{ymd}.html").write_text(html_content, encoding="utf-8")
    (public_dir / "recommendation_latest.html").write_text(html_content, encoding="utf-8")
    
    return {
        "date": date_str,
        "portfolio_size": len(portfolio),
        "markdown_report": str(md_output_path),
        "html_report": str(html_output_path),
        "json_output": str(json_output_path),
        "public_html": str(public_dir / "recommendation_latest.html")
    }


def build_markdown_table(portfolio: list[dict]) -> str:
    """Build a clean GFM markdown table of the portfolio."""
    headers = [
        "排名", "代码", "股票名称", "行业", 
        "D1收盘价", "支撑参考价(防守)", "阻力参考线", 
        "ROE", "净利润增长", "月/周/日状态", "ADX"
    ]
    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    
    rows = []
    for idx, s in enumerate(portfolio, 1):
        code = s.get("stock_code", "")
        name = s.get("stock_name", "")
        sw_l1 = s.get("sw_l1", "")
        close = f"{s.get('d1_close', 0.0):.2f}" if s.get('d1_close') is not None else "-"
        support = f"{s.get('d1_sr_support', 0.0):.2f}" if s.get('d1_sr_support') is not None else "-"
        resistance = f"{s.get('d1_sr_resistance', 0.0):.2f}" if s.get('d1_sr_resistance') is not None else "-"
        roe = f"{s.get('roe', 0.0):.2f}%" if s.get('roe') is not None else "-"
        profit_inc = f"{s.get('profit_inc', 0.0):.2f}%" if s.get('profit_inc') is not None else "-"
        states = f"{s.get('mn1_state', '')}/{s.get('w1_state', '')}/{s.get('d1_state', '')}"
        adx = f"{s.get('d1_adx14', 0.0):.2f}" if s.get('d1_adx14') is not None else "-"
        
        row_fields = [
            str(idx), code, name, sw_l1, close, support, resistance, roe, profit_inc, states, adx
        ]
        rows.append("| " + " | ".join(row_fields) + " |")
        
    return header_line + "\n" + sep_line + "\n" + "\n".join(rows)


def markdown_to_html(md_text: str) -> str:
    """Simple parser to convert markdown structure to formatted HTML."""
    import re
    html_lines = []
    for line in md_text.splitlines():
        line = line.strip()
        if not line:
            html_lines.append("<br>")
            continue
        if line.startswith("### "):
            html_lines.append(f"<h3 style='color: #bc8cff; margin-top: 20px; margin-bottom: 8px;'>{line[4:]}</h3>")
        elif line.startswith("## "):
            html_lines.append(f"<h2 style='color: #58a6ff; margin-top: 25px; margin-bottom: 12px; border-bottom: 1px solid #30363d; padding-bottom: 6px;'>{line[3:]}</h2>")
        elif line.startswith("# "):
            html_lines.append(f"<h1 style='color: #ffffff; margin-top: 30px; margin-bottom: 15px;'>{line[2:]}</h1>")
        elif line.startswith("- ") or line.startswith("* "):
            processed = line[2:]
            processed = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', processed)
            html_lines.append(f"<li style='margin-left: 20px; margin-bottom: 6px; color: #c9d1d9; list-style-type: square;'>{processed}</li>")
        elif len(line) > 2 and line[0].isdigit() and line[1:3] == ". ":
            processed = line[3:]
            processed = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', processed)
            html_lines.append(f"<li style='margin-left: 20px; margin-bottom: 6px; color: #c9d1d9;'>{processed}</li>")
        else:
            processed = line
            processed = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', processed)
            html_lines.append(f"<p style='color: #c9d1d9; line-height: 1.6; margin-bottom: 8px;'>{processed}</p>")
    return "\n".join(html_lines)


def build_html_report(date_str: str, portfolio: list[dict], diff_data: dict, report_md: str, generated_at: str) -> str:
    """Build a premium, high-end HTML report dashboard with responsive table design."""
    
    # Generate table body
    table_rows = []
    for idx, s in enumerate(portfolio, 1):
        code = s.get("stock_code", "")
        name = s.get("stock_name", "")
        sw_l1 = s.get("sw_l1", "") or "未分类"
        close = f"{s.get('d1_close', 0.0):.2f}" if s.get('d1_close') is not None else "-"
        support = f"{s.get('d1_sr_support', 0.0):.2f}" if s.get('d1_sr_support') is not None else "-"
        resistance = f"{s.get('d1_sr_resistance', 0.0):.2f}" if s.get('d1_sr_resistance') is not None else "-"
        roe = f"{s.get('roe', 0.0):.2f}%" if s.get('roe') is not None else "-"
        profit_inc = f"{s.get('profit_inc', 0.0):.2f}%" if s.get('profit_inc') is not None else "-"
        states = f"{s.get('mn1_state', '')}/{s.get('w1_state', '')}/{s.get('d1_state', '')}"
        adx = f"{s.get('d1_adx14', 0.0):.1f}" if s.get('d1_adx14') is not None else "-"
        
        row_html = f"""
        <tr>
            <td style="text-align: center; color: #8b949e; font-weight: bold;">{idx}</td>
            <td style="color: #58a6ff; font-weight: bold;">{code}</td>
            <td style="color: #ffffff; font-weight: bold;">{name}</td>
            <td><span class="badge badge-industry">{sw_l1}</span></td>
            <td style="color: #58a6ff; font-weight: bold; text-align: right;">{close}</td>
            <td style="color: #ff7b72; font-weight: bold; text-align: right;">{support}</td>
            <td style="color: #bc8cff; text-align: right;">{resistance}</td>
            <td style="color: #56d364; text-align: right;">{roe}</td>
            <td style="color: #56d364; text-align: right;">{profit_inc}</td>
            <td style="text-align: center;"><span class="badge badge-state">{states}</span></td>
            <td style="color: #e3b341; text-align: right;">{adx}</td>
        </tr>
        """
        table_rows.append(row_html)
        
    entered_count = len(diff_data.get("entered", []))
    left_count = len(diff_data.get("left", []))
    stayed_count = len(diff_data.get("stayed", []))
    total_ef = entered_count + stayed_count
    
    parsed_report_html = markdown_to_html(report_md)
    
    html_template = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>P116 多周期共振精选推荐 - {date_str}</title>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=Noto+Sans+SC:wght@300;400;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg-color: #0b0f19;
      --card-bg: rgba(22, 27, 34, 0.7);
      --card-border: rgba(48, 54, 61, 0.7);
      --text-main: #c9d1d9;
      --text-header: #ffffff;
      --accent-color: #10b981;
      --accent-glow: rgba(16, 185, 129, 0.2);
    }}
    
    body {{
      margin: 0;
      padding: 24px;
      font-family: 'Outfit', 'Noto Sans SC', -apple-system, sans-serif;
      background-color: var(--bg-color);
      color: var(--text-main);
      background-image: radial-gradient(circle at 10% 20%, rgba(90, 120, 250, 0.05) 0%, transparent 40%),
                        radial-gradient(circle at 90% 80%, rgba(16, 185, 129, 0.05) 0%, transparent 40%);
      background-attachment: fixed;
    }}
    
    .container {{
      max-width: 1300px;
      margin: 0 auto;
    }}
    
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 20px;
    }}
    
    .header h1 {{
      margin: 0;
      font-size: 28px;
      font-weight: 700;
      background: linear-gradient(90deg, #58a6ff, #bc8cff);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    
    .header .meta {{
      font-size: 14px;
      color: #8b949e;
      text-align: right;
    }}
    
    .disclaimer {{
      background: rgba(240, 136, 62, 0.1);
      border: 1px dashed rgba(240, 136, 62, 0.4);
      color: #f0883e;
      border-radius: 8px;
      padding: 12px 16px;
      margin-bottom: 24px;
      font-size: 14px;
      font-weight: 600;
      letter-spacing: 0.5px;
    }}
    
    .kpis-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    
    .kpi-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      backdrop-filter: blur(12px);
      border-radius: 12px;
      padding: 16px;
      text-align: center;
      transition: transform 0.2s ease, box-shadow 0.2s ease;
    }}
    
    .kpi-card:hover {{
      transform: translateY(-2px);
      box-shadow: 0 4px 20px rgba(0,0,0,0.3);
      border-color: #58a6ff;
    }}
    
    .kpi-card small {{
      display: block;
      color: #8b949e;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 6px;
    }}
    
    .kpi-card strong {{
      display: block;
      font-size: 26px;
      color: #ffffff;
      font-weight: 600;
    }}
    
    .main-grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 24px;
    }}
    
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      backdrop-filter: blur(12px);
      border-radius: 16px;
      padding: 24px;
      box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
    }}
    
    .card-title {{
      margin-top: 0;
      margin-bottom: 18px;
      font-size: 20px;
      font-weight: 600;
      color: #ffffff;
      display: flex;
      align-items: center;
      gap: 8px;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 10px;
    }}
    
    .table-wrapper {{
      overflow-x: auto;
    }}
    
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      text-align: left;
    }}
    
    th {{
      color: #8b949e;
      font-weight: 600;
      padding: 12px 14px;
      border-bottom: 2px solid var(--card-border);
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 0.5px;
    }}
    
    td {{
      padding: 14px;
      border-bottom: 1px solid rgba(48, 54, 61, 0.4);
      color: #c9d1d9;
    }}
    
    tr:hover td {{
      background: rgba(56, 139, 253, 0.05);
    }}
    
    .badge {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 600;
    }}
    
    .badge-industry {{
      background: rgba(88, 166, 255, 0.1);
      color: #58a6ff;
      border: 1px solid rgba(88, 166, 255, 0.3);
    }}
    
    .badge-state {{
      background: rgba(188, 140, 255, 0.1);
      color: #bc8cff;
      border: 1px solid rgba(188, 140, 255, 0.3);
      font-family: monospace;
    }}
    
    .report-content {{
      font-size: 14px;
      line-height: 1.6;
    }}
    
    .footer {{
      margin-top: 40px;
      text-align: center;
      padding: 20px 0;
      font-size: 12px;
      color: #8b949e;
      border-top: 1px solid var(--card-border);
    }}
    
    /* Responsive adjustment */
    @media (min-width: 992px) {{
      .main-grid {{
        grid-template-columns: 2fr 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="disclaimer">
      【Research-Only】本结果仅为技术状态观察与基本面条件筛选，不构成任何买卖指令或投资建议。请严格执行支撑位防守纪律。
    </div>
    
    <div class="header">
      <div>
        <h1>P116 多周期共振精选组合</h1>
      </div>
      <div class="meta">
        交易日期: {date_str}<br>
        生成时间: {generated_at.split('T')[0] if generated_at else date_str}
      </div>
    </div>
    
    <div class="kpis-grid">
      <div class="kpi-card">
        <small>共振候选池</small>
        <strong>{total_ef} 只</strong>
      </div>
      <div class="kpi-card">
        <small>今日新入池</small>
        <strong style="color: #56d364;">+{entered_count} 只</strong>
      </div>
      <div class="kpi-card">
        <small>移出观察池</small>
        <strong style="color: #ff7b72;">-{left_count} 只</strong>
      </div>
      <div class="kpi-card" style="border-color: var(--accent-color); box-shadow: 0 0 10px var(--accent-glow);">
        <small>精选组合规模</small>
        <strong style="color: #10b981;">{len(portfolio)} 只</strong>
      </div>
    </div>
    
    <div class="main-grid">
      <!-- Left column: Table -->
      <div class="card">
        <div class="card-title">
          <span>📊 精选组合明细清单</span>
        </div>
        <div class="table-wrapper">
          <table>
            <thead>
              <tr>
                <th style="text-align: center; width: 40px;">#</th>
                <th>代码</th>
                <th>名称</th>
                <th>行业</th>
                <th style="text-align: right;">收盘价</th>
                <th style="text-align: right;">支撑防守价</th>
                <th style="text-align: right;">阻力参考线</th>
                <th style="text-align: right;">ROE</th>
                <th style="text-align: right;">净利增长</th>
                <th style="text-align: center;">月/周/日</th>
                <th style="text-align: right;">ADX</th>
              </tr>
            </thead>
            <tbody>
              {"".join(table_rows)}
            </tbody>
          </table>
        </div>
      </div>
      
      <!-- Right column: DeepSeek narrative -->
      <div class="card">
        <div class="card-title">
          <span>🤖 DeepSeek 智能分析</span>
        </div>
        <div class="report-content">
          {parsed_report_html}
        </div>
      </div>
    </div>
    
    <div class="footer">
      Powered by DeepSeek LLM & Hermass Observer System<br>
      © 2026 Hermass Quant. All Rights Reserved.
    </div>
  </div>
</body>
</html>
"""
    return html_template


def call_deepseek_llm(date_str: str, portfolio: list[dict], diff_data: dict, config: dict) -> str:
    """Invokes DeepSeek API to write the final compliant daily report."""
    llm_cfg = config.get("llm", {})
    model_name = llm_cfg.get("model", "deepseek-chat")
    
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    api_base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com")
    
    # Format portfolio items for prompt
    portfolio_summary = []
    for idx, s in enumerate(portfolio, 1):
        fund_str = f" [ROE={s['roe']:.2f}%, 净利增={s['profit_inc']:.2f}%]" if "roe" in s else ""
        portfolio_summary.append(
            f"{idx}. {s['stock_name']} ({s['symbol']}) - 行业: {s['sw_l1']}/{s['sw_l2']}{fund_str}\n"
            f"   - 今日收盘价: {s['d1_close']} | 支撑参考线(防守价): {s['d1_sr_support']} | 阻力参考线: {s['d1_sr_resistance']}\n"
            f"   - 多周期状态: 月线={s['mn1_state']}, 周线={s['w1_state']}, 日线={s['d1_state']} | 趋势强度(ADX)={s['d1_adx14']:.2f}"
        )
        
    entered_count = len(diff_data.get("entered", []))
    left_count = len(diff_data.get("left", []))
    
    system_prompt = (
        "你是一个专业的量化组合分析助手。你的任务是根据量化过滤后的“三周期共振突破组合”，生成一份专业的投资者观察报告。\n"
        "【合规性天条 - 必须严格遵守】\n"
        "1. 严禁出现以下敏感投资词汇：'买入'、'卖出'、'建仓'、'加仓'、'减仓'、'止盈'、'止损'、'荐股'、'收益承诺'、'赚钱'。\n"
        "2. 必须使用以下合规表述替代：\n"
        "   - 用“观察池/观察名单”替代“推荐买入名单”\n"
        "   - 用“值得复核/重点关注”替代“买入信号”\n"
        "   - 用“状态仍在观察中”或“移出观察池”替代“继续持有/卖出信号”\n"
        "   - 用“防守价/支撑参考价”替代“止损价”\n"
        "   - 用“历史路径相似度高”或者“趋势概率优势”替代“保本/稳赚”\n"
        "3. 在报告的头部和尾部必须注明：'【Research-Only】本结果仅为技术状态观察，不构成任何投资建议。'\n"
    )
    
    user_prompt = f"""请根据以下量化精选观察池的数据，为私域用户撰写一份日期为 {date_str} 的《P116多周期共振精选观察报告》。

【当日大盘概览】
- 满足三周期全 E/F 的总品种数：{diff_data.get('entered_count', 0) + diff_data.get('stayed_count', 0)} 只
- 今日新入池品种数：{entered_count} 只，移出池品种数：{left_count} 只
- 精选出的 Top {len(portfolio)} 观察组合清单：
{chr(10).join(portfolio_summary)}

报告撰写指南：
1. 【免责声明】：头部置顶加粗显示。
2. 【组合特征分析】：分析精选出的个股集中在哪些核心板块？比如有没有半导体、电力、消费等明显的行业聚集度，代表资金的共性流向。
3. 【异动解读与支撑位】：选择 2-3 只最典型的股票进行趋势共振解读，并明确指出每个股票的“日线级支撑参考价（防守价）”。强调“若收盘价低于此参考价，该品种的状态即值得复核，甚至可以自动移出观察名单”。
4. 【客观纪律说明】：向用户灌输客观纪律，比如“状态一旦退化则结束观察，严格遵守防守参考线，不夹杂主观情绪”，这是实现长期稳健观察的核心。
"""

    if not api_key:
        print("Warning: DEEPSEEK_API_KEY environment variable not set. Writing standard output report template.", file=sys.stderr)
        report_text = (
            f"**【Research-Only】本结果仅为技术状态观察，不构成任何投资建议。**\n\n"
            f"# P116 多周期共振精选观察报告 ({date_str})\n\n"
            f"由于未检测到 `DEEPSEEK_API_KEY`，以下为今日精选的 Top {len(portfolio)} 观察池清单：\n\n"
            + "\n".join(portfolio_summary)
            + "\n\n请在配置环境变量后运行，以生成由 DeepSeek AI 驱动的板块资金流与状态多维解读报告。\n"
        )
    else:
        print(f"Calling DeepSeek API via {api_base}...", flush=True)
        try:
            response = requests.post(
                f"{api_base}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": with_deepseek_context(system_prompt)},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": llm_cfg.get("temperature", 0.3),
                    "max_tokens": llm_cfg.get("max_tokens", 1500)
                },
                timeout=60
            )
            response.raise_for_status()
            res_json = response.json()
            report_text = res_json['choices'][0]['message']['content']
        except Exception as e:
            print(f"Error calling DeepSeek API: {e}", file=sys.stderr)
            report_text = f"# 报告生成失败\n\nAPI 调用出错：{e}\n"

    # Append footer disclaimer just in case
    if "Research-Only" not in report_text:
        report_text = "**【Research-Only】本结果仅为技术状态观察，不构成任何投资建议。**\n\n" + report_text
        
    return report_text


def main() -> int:
    parser = argparse.ArgumentParser(description="P116 Independent Portfolio Recommendation Engine")
    parser.add_argument("--date", required=True, help="Trading date, e.g. 2026-05-20")
    args = parser.parse_args()
    
    config = load_config()
    
    try:
        summary = run_recommendation(args.date, config)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
