#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path
from typing import Any

import xlsxwriter


ROOT = Path(__file__).resolve().parents[1]
FIELDS = [
    "portfolio_rank",
    "rank",
    "stock_code",
    "stock_name",
    "sw_l1",
    "sw_l2",
    "sw_l3",
    "change_type",
    "recommendation_score",
    "state",
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
    "d1_sr_support",
    "w1_ama10",
    "observation_reason",
    "risk_note",
]


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def load_payload(date_str: str) -> dict[str, Any]:
    path = ROOT / "recommendation" / "outputs" / f"p116_recommendation_{ymd(date_str)}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def build_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    portfolio_by_symbol = {row["symbol"]: row for row in payload.get("portfolio", [])}
    rows = []
    for row in payload.get("candidates") or payload.get("watchlist", []):
        out = {field: row.get(field, "") for field in FIELDS}
        if row["symbol"] in portfolio_by_symbol:
            out["portfolio_rank"] = portfolio_by_symbol[row["symbol"]].get("portfolio_rank", "")
            out["is_portfolio"] = True
        else:
            out["portfolio_rank"] = ""
            out["is_portfolio"] = False
        out["symbol"] = row.get("symbol", "")
        rows.append(out)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ["is_portfolio", "symbol", *FIELDS]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_xlsx(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ["is_portfolio", "symbol", *FIELDS]
    labels = {
        "is_portfolio": "是否组合候选",
        "symbol": "完整代码",
        "portfolio_rank": "组合序",
        "rank": "总排名",
        "stock_code": "代码",
        "stock_name": "名称",
        "sw_l1": "一级行业",
        "sw_l2": "二级行业",
        "sw_l3": "三级行业",
        "change_type": "变动",
        "recommendation_score": "推荐分",
        "state": "三周期",
        "d1_close": "收盘",
        "d1_adx14": "D1 ADX",
        "moneyflow_score": "资金流分",
        "moneyflow_status": "资金状态",
        "moneyflow_confirmed": "资金确认",
        "moneyflow_divergence": "资金背离",
        "moneyflow_days_available": "资金天数",
        "moneyflow_coverage_ratio": "资金覆盖",
        "positive_days_5d": "5日主动正天数",
        "big_positive_days_5d": "5日大额正天数",
        "active_net_5d": "5日主动净额",
        "big_order_net_5d": "5日大额净额",
        "latest_active_net": "最新主动净额",
        "latest_big_order_net": "最新大额净额",
        "d1_sr_support": "D1防守",
        "w1_ama10": "W1 AMA10",
        "observation_reason": "观察理由",
        "risk_note": "风险复核",
    }
    workbook = xlsxwriter.Workbook(str(path))
    worksheet = workbook.add_worksheet("推荐清单")
    header_fmt = workbook.add_format({"bold": True, "bg_color": "#EAF3EF", "border": 1})
    text_fmt = workbook.add_format({"border": 1})
    num_fmt = workbook.add_format({"border": 1, "num_format": "0.00"})
    money_fmt = workbook.add_format({"border": 1, "num_format": "#,##0"})
    bool_fmt = workbook.add_format({"border": 1, "align": "center"})

    for col, field in enumerate(fields):
        worksheet.write(0, col, labels.get(field, field), header_fmt)

    numeric_fields = {
        "recommendation_score",
        "d1_close",
        "d1_adx14",
        "moneyflow_score",
        "moneyflow_days_available",
        "moneyflow_coverage_ratio",
        "positive_days_5d",
        "big_positive_days_5d",
        "d1_sr_support",
        "w1_ama10",
    }
    money_fields = {"active_net_5d", "big_order_net_5d", "latest_active_net", "latest_big_order_net"}
    for row_idx, row in enumerate(rows, 1):
        for col, field in enumerate(fields):
            value = row.get(field, "")
            if field == "is_portfolio":
                worksheet.write(row_idx, col, "是" if value else "", bool_fmt)
            elif field in numeric_fields or field in money_fields:
                try:
                    number = float(value)
                    worksheet.write_number(row_idx, col, number, money_fmt if field in money_fields else num_fmt)
                except (TypeError, ValueError):
                    worksheet.write(row_idx, col, value, text_fmt)
            else:
                worksheet.write(row_idx, col, value, text_fmt)

    worksheet.freeze_panes(1, 0)
    worksheet.autofilter(0, 0, len(rows), len(fields) - 1)
    widths = {
        "is_portfolio": 12,
        "symbol": 12,
        "portfolio_rank": 10,
        "rank": 8,
        "stock_code": 10,
        "stock_name": 14,
        "sw_l1": 12,
        "sw_l2": 16,
        "sw_l3": 18,
        "change_type": 10,
        "recommendation_score": 12,
        "state": 10,
        "observation_reason": 58,
        "risk_note": 32,
    }
    for col, field in enumerate(fields):
        worksheet.set_column(col, col, widths.get(field, 14))
    workbook.close()


def render_html(payload: dict[str, Any], rows: list[dict[str, Any]], csv_name: str) -> str:
    data_json = json.dumps(rows, ensure_ascii=False)
    industries = sorted({row.get("sw_l1") or "未分类" for row in rows})
    states = sorted({row.get("state") or "" for row in rows if row.get("state")})
    industry_options = "".join(f"<option value='{html.escape(i)}'>{html.escape(i)}</option>" for i in industries)
    state_options = "".join(f"<option value='{html.escape(s)}'>{html.escape(s)}</option>" for s in states)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>P116 可分享推荐清单 - {html.escape(payload['date'])}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; color: #17212b; background: #f6f8f7; }}
    header {{ padding: 20px 24px; background: #fff; border-bottom: 1px solid #dce4df; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    p {{ color: #526071; margin: 6px 0; line-height: 1.55; }}
    main {{ padding: 16px 24px 24px; }}
    .notice {{ background: #fff7ed; border: 1px solid #fed7aa; color: #8a4b12; padding: 10px 12px; border-radius: 8px; }}
    .toolbar {{ display: grid; grid-template-columns: 2fr repeat(4, minmax(140px, 1fr)); gap: 10px; align-items: end; margin-bottom: 12px; }}
    label {{ display: block; font-size: 12px; color: #657385; margin-bottom: 4px; }}
    input, select, button {{ width: 100%; box-sizing: border-box; border: 1px solid #cfd9d3; border-radius: 6px; padding: 9px 10px; background: #fff; color: #17212b; font-size: 14px; }}
    button {{ background: #0f6b4b; color: #fff; font-weight: 700; cursor: pointer; }}
    .stats {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 12px 0; }}
    .pill {{ background: #fff; border: 1px solid #dce4df; border-radius: 999px; padding: 7px 10px; font-size: 13px; }}
    .table-wrap {{ overflow: auto; border: 1px solid #dce4df; background: #fff; max-height: 76vh; }}
    table {{ border-collapse: collapse; width: 100%; min-width: 1900px; font-size: 12px; }}
    th, td {{ border-bottom: 1px solid #e3e9e5; border-right: 1px solid #e3e9e5; padding: 7px 8px; text-align: left; white-space: nowrap; }}
    th {{ position: sticky; top: 0; background: #eef4f1; cursor: pointer; user-select: none; }}
    td.score, td.state, td.portfolio {{ font-weight: 700; color: #0f766e; }}
    tr.portfolio-row {{ background: #f2faf6; }}
    @media (max-width: 900px) {{ .toolbar {{ grid-template-columns: 1fr 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>P116 可分享推荐清单 - {html.escape(payload['date'])}</h1>
    <p class="notice">{html.escape(payload.get('notice', 'Research-Only'))}</p>
    <p>支持搜索、行业筛选、状态筛选、新进/留存筛选、组合候选筛选、表头排序，并可导出当前筛选结果。</p>
  </header>
  <main>
    <div class="toolbar">
      <div>
        <label>搜索代码 / 名称 / 行业</label>
        <input id="q" placeholder="例如：688107、光迅、电子">
      </div>
      <div>
        <label>行业</label>
        <select id="industry"><option value="">全部行业</option>{industry_options}</select>
      </div>
      <div>
        <label>状态</label>
        <select id="state"><option value="">全部状态</option>{state_options}</select>
      </div>
      <div>
        <label>变动</label>
        <select id="change"><option value="">全部</option><option value="entered">新进入</option><option value="stayed">留存</option></select>
      </div>
      <div>
        <label>范围</label>
        <select id="scope"><option value="">全部候选</option><option value="portfolio">仅组合候选</option><option value="top30">仅Top30观察</option></select>
      </div>
    </div>
    <div class="toolbar" style="grid-template-columns: 1fr 1fr 1fr 1fr;">
      <button id="reset">重置筛选</button>
      <button id="export">导出当前结果 CSV</button>
      <button onclick="location.href='{html.escape(csv_name.replace('.csv', '.xlsx'))}'">下载 Excel</button>
      <button onclick="location.href='p116_recommendation_{payload['date'].replace('-', '')}.html'">打开摘要页</button>
    </div>
    <div class="stats">
      <span class="pill">基础池：{payload.get('pool_total')}</span>
      <span class="pill">有效候选：<b id="visibleCount">0</b> / {len(rows)}</span>
      <span class="pill">组合候选：{payload.get('portfolio_size')}</span>
      <span class="pill">观察名单：{payload.get('watchlist_size')}</span>
    </div>
    <div class="table-wrap">
      <table id="table"></table>
    </div>
  </main>
  <script>
    const DATA = {data_json};
    const FIELDS = {json.dumps(["portfolio_rank", "rank", "stock_code", "stock_name", "sw_l1", "sw_l2", "change_type", "recommendation_score", "state", "d1_close", "d1_adx14", "moneyflow_status", "moneyflow_score", "positive_days_5d", "big_positive_days_5d", "active_net_5d", "big_order_net_5d", "d1_sr_support", "w1_ama10", "observation_reason", "risk_note"], ensure_ascii=False)};
    const LABELS = {{
      portfolio_rank: "组合序",
      rank: "总排名",
      stock_code: "代码",
      stock_name: "名称",
      sw_l1: "一级行业",
      sw_l2: "二级行业",
      change_type: "变动",
      recommendation_score: "推荐分",
      state: "三周期",
      d1_close: "收盘",
      d1_adx14: "D1 ADX",
      moneyflow_status: "资金状态",
      moneyflow_score: "资金流分",
      positive_days_5d: "5日主动正天数",
      big_positive_days_5d: "5日大额正天数",
      active_net_5d: "5日主动净额",
      big_order_net_5d: "5日大额净额",
      d1_sr_support: "D1防守",
      w1_ama10: "W1 AMA10",
      observation_reason: "观察理由",
      risk_note: "风险复核"
    }};
    let sortKey = "recommendation_score";
    let sortDir = -1;

    function text(v) {{ return (v ?? "").toString(); }}
    function num(v) {{ const n = Number(v); return Number.isFinite(n) ? n : -Infinity; }}
    function currentRows() {{
      const q = document.getElementById("q").value.trim().toLowerCase();
      const industry = document.getElementById("industry").value;
      const state = document.getElementById("state").value;
      const change = document.getElementById("change").value;
      const scope = document.getElementById("scope").value;
      return DATA.filter(r => {{
        const hay = [r.stock_code, r.symbol, r.stock_name, r.sw_l1, r.sw_l2, r.sw_l3, r.observation_reason].map(text).join(" ").toLowerCase();
        if (q && !hay.includes(q)) return false;
        if (industry && r.sw_l1 !== industry) return false;
        if (state && r.state !== state) return false;
        if (change && r.change_type !== change) return false;
        if (scope === "portfolio" && !r.is_portfolio) return false;
        if (scope === "top30" && num(r.rank) > 30) return false;
        return true;
      }}).sort((a, b) => {{
        const av = ["recommendation_score","rank","portfolio_rank","d1_adx14","moneyflow_score","positive_days_5d","big_positive_days_5d","active_net_5d","big_order_net_5d","d1_close"].includes(sortKey) ? num(a[sortKey]) : text(a[sortKey]);
        const bv = ["recommendation_score","rank","portfolio_rank","d1_adx14","moneyflow_score","positive_days_5d","big_positive_days_5d","active_net_5d","big_order_net_5d","d1_close"].includes(sortKey) ? num(b[sortKey]) : text(b[sortKey]);
        if (av < bv) return -1 * sortDir;
        if (av > bv) return 1 * sortDir;
        return num(a.rank) - num(b.rank);
      }});
    }}
    function render() {{
      const rows = currentRows();
      document.getElementById("visibleCount").textContent = rows.length;
      const head = "<thead><tr>" + FIELDS.map(f => `<th data-field="${{f}}">${{LABELS[f] || f}}</th>`).join("") + "</tr></thead>";
      const body = rows.map(r => "<tr class='" + (r.is_portfolio ? "portfolio-row" : "") + "'>" + FIELDS.map(f => {{
        const cls = f === "recommendation_score" ? "score" : (f === "state" ? "state" : (f === "portfolio_rank" ? "portfolio" : ""));
        return `<td class="${{cls}}">${{escapeHtml(text(r[f]))}}</td>`;
      }}).join("") + "</tr>").join("");
      document.getElementById("table").innerHTML = head + "<tbody>" + body + "</tbody>";
      document.querySelectorAll("th").forEach(th => th.onclick = () => {{
        const field = th.dataset.field;
        if (sortKey === field) sortDir *= -1; else {{ sortKey = field; sortDir = field === "recommendation_score" ? -1 : 1; }}
        render();
      }});
    }}
    function escapeHtml(s) {{
      return s.replace(/[&<>"']/g, ch => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[ch]));
    }}
    function csvEscape(v) {{
      const s = text(v);
      return /[",\\n]/.test(s) ? '"' + s.replaceAll('"', '""') + '"' : s;
    }}
    function exportCsv() {{
      const rows = currentRows();
      const csv = [FIELDS.map(f => LABELS[f] || f).join(",")].concat(rows.map(r => FIELDS.map(f => csvEscape(r[f])).join(","))).join("\\n");
      const blob = new Blob(["\\ufeff" + csv], {{ type: "text/csv;charset=utf-8" }});
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "p116_recommendation_filtered_{payload['date'].replace('-', '')}.csv";
      a.click();
      URL.revokeObjectURL(a.href);
    }}
    ["q","industry","state","change","scope"].forEach(id => document.getElementById(id).addEventListener("input", render));
    document.getElementById("reset").onclick = () => {{
      ["q","industry","state","change","scope"].forEach(id => document.getElementById(id).value = "");
      render();
    }};
    document.getElementById("export").onclick = exportCsv;
    render();
  </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build shareable filterable P116 recommendation table.")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    payload = load_payload(args.date)
    rows = build_rows(payload)
    public_dir = ROOT / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    csv_path = public_dir / f"p116_recommendation_shareable_{ymd(args.date)}.csv"
    xlsx_path = public_dir / f"p116_recommendation_shareable_{ymd(args.date)}.xlsx"
    html_path = public_dir / f"p116_recommendation_shareable_{ymd(args.date)}.html"
    latest_path = public_dir / "p116_recommendation_shareable_latest.html"
    write_csv(csv_path, rows)
    write_xlsx(xlsx_path, rows)
    html_text = render_html(payload, rows, csv_path.name)
    html_path.write_text(html_text, encoding="utf-8")
    latest_path.write_text(html_text, encoding="utf-8")
    print(json.dumps({"rows": len(rows), "html": str(html_path), "csv": str(csv_path), "xlsx": str(xlsx_path), "latest": str(latest_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
