#!/usr/bin/env python3
"""Build an auditable SW L1 industry-to-ETF coverage map from Blackwolf ETF list."""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BLACKWOLF_LIST = (
    Path.home()
    / "Documents"
    / "hongrun-chaos-trading-system"
    / "data"
    / "blackwolf_stock_list_flag0.csv"
)
DEFAULT_CONFIG = ROOT / "config" / "industry_rotation_assets.json"
IFIND_DIR = ROOT / "outputs" / "ifind"
MARKET_ASSETS_STATE_DIR = ROOT / "outputs" / "market_assets_state"
OUT_DIR = ROOT / "outputs" / "etf_coverage"
PUBLIC_DIR = ROOT / "public"


EXCLUDE_KEYWORDS = [
    "港股",
    "恒生",
    "中概",
    "纳斯达克",
    "标普",
    "日经",
    "德国",
    "巴西",
    "亚太",
    "沙特",
    "东南亚",
    "债",
    "货币",
    "现金",
    "黄金",
    "REIT",
]


DIRECT_KEYWORDS: dict[str, list[str]] = {
    "交通运输": ["交通运输"],
    "传媒": ["传媒"],
    "公用事业": ["公用事业"],
    "建筑材料": ["建筑材料", "建材"],
    "房地产": ["房地产", "地产"],
    "机械设备": ["机械ETF", "机械"],
    "环保": ["环保"],
    "石油石化": ["石油", "油气"],
    "计算机": ["计算机"],
    "钢铁": ["钢铁"],
    "商贸零售": ["商贸零售", "零售"],
    "美容护理": ["美容护理", "美妆", "化妆品"],
    "轻工制造": ["轻工", "造纸"],
}


PROXY_KEYWORDS: dict[str, list[str]] = {
    "商贸零售": ["线上消费", "在线消费", "消费服务", "品牌消费"],
    "社会服务": ["旅游", "教育", "消费服务"],
    "纺织服饰": ["纺织", "服装", "服饰", "品牌消费"],
    "美容护理": ["医美", "美妆", "化妆", "美容", "消费龙头", "品牌消费", "可选消费", "消费ETF"],
    "轻工制造": ["家居", "造纸", "品牌消费"],
}


PREFERRED_SYMBOLS: dict[str, list[str]] = {
    # Low-numbered oil ETFs in the Blackwolf list only had short recent history
    # in the 2026-05-22 audit. Prefer a direct oil ETF with full local history.
    "石油石化": ["159588.SZ", "159697.SZ", "561360.SH", "159309.SZ"],
}


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def load_json(path: Path, required: bool = False) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def infer_suffix(code: str) -> str:
    text = str(code or "").strip().upper()
    if "." in text:
        left, right = text.split(".", 1)
        digits = "".join(ch for ch in left if ch.isdigit())[-6:]
        suffix = right[:2]
        return f"{digits}.{suffix}" if digits and suffix else text
    digits = "".join(ch for ch in text if ch.isdigit())[-6:]
    if not digits:
        return text
    if digits.startswith("159"):
        return f"{digits}.SZ"
    return f"{digits}.SH"


def load_blackwolf_etfs(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            name = str(row.get("name") or "").strip()
            if "ETF" not in name.upper():
                continue
            symbol = infer_suffix(row.get("stock_code") or row.get("code") or "")
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            rows.append({"symbol": symbol, "name": name, "raw_code": str(row.get("code") or "").strip()})
    return rows


def load_ifind_industry_counts(date_str: str) -> dict[str, int]:
    payload = load_json(IFIND_DIR / f"industry_{ymd(date_str)}.json", required=True)
    counts = payload.get("industry_counts") or {}
    return {str(key): int(value) for key, value in counts.items()}


def load_current_config(path: Path) -> dict[str, Any]:
    payload = load_json(path, required=True)
    payload.setdefault("index_assets", [])
    payload.setdefault("industry_etf_assets", [])
    return payload


def load_market_state(date_str: str) -> dict[str, list[dict[str, str]]]:
    path = MARKET_ASSETS_STATE_DIR / f"market_assets_state_{ymd(date_str)}.csv"
    if not path.exists():
        return {}
    out: dict[str, list[dict[str, str]]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sw_l1 = str(row.get("sw_l1") or "").strip()
            if row.get("asset_type") == "industry_etf" and sw_l1:
                out.setdefault(sw_l1, []).append(row)
    return out


def is_excluded(name: str) -> bool:
    upper = name.upper()
    return any(keyword.upper() in upper for keyword in EXCLUDE_KEYWORDS)


def candidate_score(name: str, keywords: list[str], match_type: str) -> tuple[int, str]:
    best_score = -10_000
    best_keyword = ""
    for index, keyword in enumerate(keywords):
        if keyword.upper() not in name.upper():
            continue
        score = 1000 if match_type == "direct" else 500
        score += (len(keywords) - index) * 40
        score += len(keyword) * 8
        if name.startswith(keyword):
            score += 80
        if f"{keyword}ETF" in name:
            score += 60
        score -= len(name)
        if score > best_score:
            best_score = score
            best_keyword = keyword
    return best_score, best_keyword


def find_candidates(
    etfs: list[dict[str, str]],
    sw_l1: str,
    keywords_by_industry: dict[str, list[str]],
    match_type: str,
) -> list[dict[str, Any]]:
    keywords = keywords_by_industry.get(sw_l1) or []
    if not keywords:
        return []
    rows: list[dict[str, Any]] = []
    for etf in etfs:
        name = etf["name"]
        if is_excluded(name):
            continue
        score, keyword = candidate_score(name, keywords, match_type)
        if not keyword:
            continue
        preferred = PREFERRED_SYMBOLS.get(sw_l1) or []
        if etf["symbol"] in preferred:
            score += 300 - preferred.index(etf["symbol"])
        rows.append(
            {
                "symbol": etf["symbol"],
                "name": name,
                "source": etf.get("source", ""),
                "match_type": match_type,
                "match_keyword": keyword,
                "score": score,
                "sw_l1": sw_l1,
                "asset_type": "industry_etf",
            }
        )
    rows.sort(key=lambda item: (-int(item["score"]), len(str(item["name"])), str(item["symbol"])))
    return rows


def fnum(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def best_market_state(rows: list[dict[str, str]]) -> dict[str, str]:
    if not rows:
        return {}
    return sorted(
        rows,
        key=lambda row: (
            -(fnum(row.get("ef_count")) or -1),
            -sum(fnum(row.get(field)) or 0 for field in ["mn1_state_score", "w1_state_score", "d1_state_score"]),
            str(row.get("symbol") or ""),
        ),
    )[0]


def join_symbols(rows: list[dict[str, Any]]) -> str:
    return "；".join(f"{row.get('symbol')} {row.get('name')}" for row in rows)


def compact_candidates(rows: list[dict[str, Any]], limit: int = 8) -> str:
    return "；".join(
        f"{row.get('symbol')} {row.get('name')}[{row.get('match_keyword')}/{row.get('score')}]"
        for row in rows[:limit]
    )


def build_payload(date_str: str, stock_list: Path, config_path: Path) -> dict[str, Any]:
    etfs = load_blackwolf_etfs(stock_list)
    ifind_counts = load_ifind_industry_counts(date_str)
    config = load_current_config(config_path)
    market_state = load_market_state(date_str)

    current_by_industry: dict[str, list[dict[str, Any]]] = {}
    for row in config.get("industry_etf_assets", []) or []:
        sw_l1 = str(row.get("sw_l1") or "").strip()
        if sw_l1:
            current_by_industry.setdefault(sw_l1, []).append(dict(row))

    coverage_rows: list[dict[str, Any]] = []
    additions: list[dict[str, Any]] = []
    for sw_l1, stock_count in sorted(ifind_counts.items()):
        current = current_by_industry.get(sw_l1, [])
        state = best_market_state(market_state.get(sw_l1, []))
        direct = find_candidates(etfs, sw_l1, DIRECT_KEYWORDS, "direct")
        proxy = find_candidates(etfs, sw_l1, PROXY_KEYWORDS, "proxy")
        selected = direct[0] if direct else {}
        if current:
            status = "configured"
            action = "already_configured"
        elif selected:
            status = "direct_candidate"
            action = "add_direct_candidate"
            additions.append(
                {
                    "symbol": selected["symbol"],
                    "name": selected["name"],
                    "asset_type": "industry_etf",
                    "sw_l1": sw_l1,
                    "candidate_source": "blackwolf_stock_list_flag0",
                    "match_keyword": selected["match_keyword"],
                }
            )
        elif proxy:
            status = "proxy_only"
            action = "manual_review_proxy_only"
            selected = proxy[0]
        else:
            status = "missing"
            action = "manual_review_no_candidate"
        coverage_rows.append(
            {
                "sw_l1": sw_l1,
                "ifind_stock_count": stock_count,
                "coverage_status": status,
                "recommended_action": action,
                "current_config_symbols": join_symbols(current),
                "market_state_best_symbol": state.get("symbol", ""),
                "market_state_best_name": state.get("name", ""),
                "market_state_best_ef_count": state.get("ef_count", ""),
                "selected_symbol": selected.get("symbol", ""),
                "selected_name": selected.get("name", ""),
                "selected_match_type": selected.get("match_type", ""),
                "selected_match_keyword": selected.get("match_keyword", ""),
                "selected_score": selected.get("score", ""),
                "direct_candidates": compact_candidates(direct),
                "proxy_candidates": compact_candidates(proxy),
            }
        )

    existing_keys = {
        (str(row.get("symbol") or ""), str(row.get("sw_l1") or ""))
        for row in config.get("industry_etf_assets", []) or []
    }
    expanded = json.loads(json.dumps(config, ensure_ascii=False))
    for row in additions:
        key = (row["symbol"], row["sw_l1"])
        if key not in existing_keys:
            expanded["industry_etf_assets"].append(
                {
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "asset_type": "industry_etf",
                    "sw_l1": row["sw_l1"],
                }
            )
            existing_keys.add(key)

    additions_config = {
        "schema_version": "industry_rotation_assets_direct_additions_v1",
        "source_config": str(config_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "index_assets": [],
        "industry_etf_assets": [
            {
                "symbol": row["symbol"],
                "name": row["name"],
                "asset_type": "industry_etf",
                "sw_l1": row["sw_l1"],
            }
            for row in additions
        ],
    }

    return {
        "schema_version": "industry_etf_coverage_v1",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "blackwolf_stock_list": str(stock_list),
        "source_config": str(config_path),
        "ifind_industry_count": len(ifind_counts),
        "blackwolf_etf_count": len(etfs),
        "status_counts": dict(Counter(row["coverage_status"] for row in coverage_rows)),
        "direct_addition_count": len(additions),
        "rows": coverage_rows,
        "direct_additions": additions,
        "expanded_config": expanded,
        "direct_additions_config": additions_config,
        "research_only": True,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def render_html(payload: dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    summary_rows = "".join(
        f"<tr><td>{esc(key)}</td><td class='num'>{esc(value)}</td></tr>"
        for key, value in payload["status_counts"].items()
    )
    detail_rows = []
    for row in payload["rows"]:
        detail_rows.append(
            f"""
            <tr class="{esc(row.get('coverage_status'))}">
              <td><strong>{esc(row.get('sw_l1'))}</strong><br><span>{esc(row.get('ifind_stock_count'))} 只</span></td>
              <td>{esc(row.get('coverage_status'))}<br><span>{esc(row.get('recommended_action'))}</span></td>
              <td>{esc(row.get('current_config_symbols'))}</td>
              <td>{esc(row.get('market_state_best_symbol'))}<br><span>{esc(row.get('market_state_best_name'))} EF={esc(row.get('market_state_best_ef_count'))}</span></td>
              <td><strong>{esc(row.get('selected_symbol'))}</strong><br><span>{esc(row.get('selected_name'))}</span></td>
              <td>{esc(row.get('selected_match_type'))}<br><span>{esc(row.get('selected_match_keyword'))} / {esc(row.get('selected_score'))}</span></td>
              <td>{esc(row.get('direct_candidates'))}</td>
              <td>{esc(row.get('proxy_candidates'))}</td>
            </tr>
            """
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>行业ETF覆盖审计 - {esc(payload['date'])}</title>
  <style>
    body {{ margin:0; background:#f6f8fb; color:#172033; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    main {{ max-width:1440px; margin:0 auto; padding:24px; }}
    h1 {{ margin:0 0 6px; font-size:26px; }}
    h2 {{ margin:20px 0 10px; font-size:18px; }}
    .meta {{ color:#5d6b82; margin-bottom:18px; }}
    .grid {{ display:grid; grid-template-columns: minmax(260px, 420px) 1fr; gap:16px; align-items:start; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid #e1e6ef; }}
    th,td {{ text-align:left; vertical-align:top; padding:9px 10px; border-bottom:1px solid #edf1f7; border-right:1px solid #edf1f7; font-size:13px; }}
    th {{ position:sticky; top:0; background:#eef4f1; z-index:1; }}
    td span {{ color:#667085; font-size:12px; }}
    .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .wrap {{ max-height:76vh; overflow:auto; }}
    tr.direct_candidate td:first-child {{ border-left:4px solid #0f766e; }}
    tr.proxy_only td:first-child {{ border-left:4px solid #b7791f; }}
    tr.missing td:first-child {{ border-left:4px solid #b42318; }}
  </style>
</head>
<body>
  <main>
    <h1>行业ETF覆盖审计</h1>
    <div class="meta">日期 {esc(payload['date'])} | iFind 行业 {esc(payload['ifind_industry_count'])} 个 | 黑狼ETF候选 {esc(payload['blackwolf_etf_count'])} 条 | 直接新增 {esc(payload['direct_addition_count'])} 个</div>
    <div class="grid">
      <section>
        <h2>覆盖状态</h2>
        <table><thead><tr><th>状态</th><th>数量</th></tr></thead><tbody>{summary_rows}</tbody></table>
      </section>
      <section>
        <h2>行业明细</h2>
        <div class="wrap">
          <table>
            <thead><tr><th>行业</th><th>状态</th><th>当前配置</th><th>当前State</th><th>候选</th><th>匹配</th><th>直接候选</th><th>代理候选</th></tr></thead>
            <tbody>{''.join(detail_rows)}</tbody>
          </table>
        </div>
      </section>
    </div>
  </main>
</body>
</html>
"""


def write_outputs(payload: dict[str, Any]) -> dict[str, str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    date_ymd = ymd(payload["date"])
    json_path = OUT_DIR / f"industry_etf_coverage_{date_ymd}.json"
    csv_path = OUT_DIR / f"industry_etf_coverage_{date_ymd}.csv"
    html_path = PUBLIC_DIR / f"industry_etf_coverage_{date_ymd}.html"
    expanded_config_path = ROOT / "config" / f"industry_rotation_assets.expanded_{date_ymd}.json"
    additions_config_path = ROOT / "config" / f"industry_rotation_assets.direct_additions_{date_ymd}.json"
    latest_json = OUT_DIR / "industry_etf_coverage_latest.json"
    latest_csv = OUT_DIR / "industry_etf_coverage_latest.csv"
    latest_html = PUBLIC_DIR / "industry_etf_coverage_latest.html"

    clean_payload = {key: value for key, value in payload.items() if key not in {"expanded_config", "direct_additions_config"}}
    json_text = json.dumps(clean_payload, ensure_ascii=False, indent=2) + "\n"
    html_text = render_html(payload)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json.write_text(json_text, encoding="utf-8")
    write_csv(csv_path, payload["rows"])
    write_csv(latest_csv, payload["rows"])
    html_path.write_text(html_text, encoding="utf-8")
    latest_html.write_text(html_text, encoding="utf-8")
    expanded_config_path.write_text(json.dumps(payload["expanded_config"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    additions_config_path.write_text(
        json.dumps(payload["direct_additions_config"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "json": str(json_path),
        "csv": str(csv_path),
        "html": str(html_path),
        "expanded_config": str(expanded_config_path),
        "direct_additions_config": str(additions_config_path),
        "latest_json": str(latest_json),
        "latest_csv": str(latest_csv),
        "latest_html": str(latest_html),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build SW L1 industry ETF coverage from Blackwolf ETF list.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--stock-list", type=Path, default=DEFAULT_BLACKWOLF_LIST)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    payload = build_payload(args.date, args.stock_list, args.config)
    outputs = write_outputs(payload)
    print(
        json.dumps(
            {
                "ok": True,
                "date": args.date,
                "status_counts": payload["status_counts"],
                "direct_addition_count": payload["direct_addition_count"],
                **outputs,
                "research_only": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
