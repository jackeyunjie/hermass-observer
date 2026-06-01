#!/usr/bin/env python3
"""Build the standard industry ETF data-config-audit loop.

This script keeps the production config conservative by default:
- existing manual config remains authoritative;
- exact/direct ETF candidates can be written into a generated compatible config;
- proxy candidates are surfaced for review unless --include-proxy is explicit.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_industry_etf_coverage import (
    DEFAULT_BLACKWOLF_LIST,
    DEFAULT_CONFIG,
    DIRECT_KEYWORDS,
    PROXY_KEYWORDS,
    candidate_score,
    find_candidates,
    infer_suffix,
    is_excluded,
    load_blackwolf_etfs,
    load_current_config,
    load_ifind_industry_counts,
    load_json,
    load_market_state,
    ymd,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "etf_config"
PUBLIC_DIR = ROOT / "public"
IFIND_DIR = ROOT / "outputs" / "ifind"
STOCK_ONLY_AUDIT_DIR = ROOT / "outputs" / "ma2560_market_match_forward"
DEFAULT_PROXY_WHITELIST = ROOT / "config" / "industry_etf_proxy_whitelist.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def empty_proxy_whitelist() -> dict[str, Any]:
    return {
        "schema_version": "industry_etf_proxy_whitelist_v1",
        "auto_approve": False,
        "no_etf_coverage": [],
        "proxy_mappings": {},
    }


def load_proxy_whitelist(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_proxy_whitelist()
    payload = load_json(path, required=True)
    payload.setdefault("schema_version", "industry_etf_proxy_whitelist_v1")
    payload.setdefault("auto_approve", False)
    payload.setdefault("no_etf_coverage", [])
    payload.setdefault("proxy_mappings", {})
    return payload


def proxy_status(proxy_whitelist: dict[str, Any], sw_l1: str) -> str:
    row = (proxy_whitelist.get("proxy_mappings") or {}).get(sw_l1) or {}
    return str(row.get("status") or "").strip()


def is_proxy_approved(proxy_whitelist: dict[str, Any], sw_l1: str, selected: dict[str, Any]) -> bool:
    row = (proxy_whitelist.get("proxy_mappings") or {}).get(sw_l1) or {}
    status = str(row.get("status") or "").strip()
    if status != "approved":
        return False
    symbol = str(selected.get("symbol") or "")
    return not row.get("proxy_etf_code") or str(row.get("proxy_etf_code")) == symbol


def upsert_proxy_candidate(
    proxy_whitelist: dict[str, Any],
    sw_l1: str,
    selected: dict[str, Any],
    now: str,
) -> None:
    if not selected:
        return
    mappings = proxy_whitelist.setdefault("proxy_mappings", {})
    existing = dict(mappings.get(sw_l1) or {})
    status = str(existing.get("status") or "pending_review")
    if status in {"approved", "rejected"}:
        return
    mappings[sw_l1] = {
        "proxy_etf_code": existing.get("proxy_etf_code") or selected.get("symbol", ""),
        "proxy_etf_name": existing.get("proxy_etf_name") or selected.get("name", ""),
        "status": status,
        "reviewed_by": existing.get("reviewed_by"),
        "reviewed_date": existing.get("reviewed_date"),
        "notes": existing.get("notes")
        or f"{selected.get('name', '')} 为 {sw_l1} 的自动代理候选；请人工确认是否允许参与行业State匹配。",
        "first_seen": existing.get("first_seen") or now,
        "last_seen": now,
        "match_keyword": existing.get("match_keyword") or selected.get("match_keyword", ""),
        "match_score": existing.get("match_score") or selected.get("score", ""),
    }


def write_proxy_whitelist(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_rank(source: str) -> int:
    if source == "blackwolf_stock_list":
        return 0
    if source == "ifind_etf_snapshot":
        return 1
    return 9


def normalize_etf_row(row: dict[str, Any], source: str) -> dict[str, Any] | None:
    code = row.get("symbol") or row.get("stock_code") or row.get("code") or row.get("ts_code")
    name = str(row.get("name") or row.get("stock_name") or row.get("security_name") or "").strip()
    symbol = infer_suffix(str(code or ""))
    if not symbol or not name:
        return None
    if "ETF" not in name.upper():
        return None
    return {"symbol": symbol, "name": name, "raw_code": str(code or ""), "source": source}


def load_ifind_etfs(date_str: str, path: Path | None = None) -> list[dict[str, Any]]:
    candidates = []
    if path is not None:
        candidates.append(path)
    candidates.extend(
        [
            IFIND_DIR / f"etf_{ymd(date_str)}.json",
            IFIND_DIR / f"etf_{ymd(date_str)}.csv",
            IFIND_DIR / "etf_latest.json",
            IFIND_DIR / "etf_latest.csv",
        ]
    )
    chosen = next((item for item in candidates if item.exists()), None)
    if chosen is None:
        return []
    rows: list[dict[str, Any]] = []
    if chosen.suffix.lower() == ".csv":
        with chosen.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                item = normalize_etf_row(row, "ifind_etf_snapshot")
                if item:
                    rows.append(item)
    else:
        payload = load_json(chosen, required=True)
        raw_rows = payload if isinstance(payload, list) else payload.get("rows") or payload.get("data") or []
        for row in raw_rows:
            if isinstance(row, dict):
                item = normalize_etf_row(row, "ifind_etf_snapshot")
                if item:
                    rows.append(item)
    return rows


def merge_etf_sources(
    blackwolf_rows: list[dict[str, Any]], ifind_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    for source_name, rows in [("blackwolf_stock_list", blackwolf_rows), ("ifind_etf_snapshot", ifind_rows)]:
        for row in rows:
            item = dict(row)
            item.setdefault("source", source_name)
            existing = by_symbol.get(item["symbol"])
            if existing is None:
                by_symbol[item["symbol"]] = item
                continue
            sources = set(str(existing.get("source") or "").split("+"))
            sources.add(str(item.get("source") or source_name))
            existing["source"] = "+".join(sorted(sources, key=source_rank))
            if len(str(item.get("name") or "")) > len(str(existing.get("name") or "")):
                existing["name"] = item["name"]
    return sorted(by_symbol.values(), key=lambda item: (item["symbol"], item["name"]))


def load_stock_only_gap_counts(date_str: str) -> tuple[Counter[str], dict[str, list[dict[str, Any]]]]:
    path = STOCK_ONLY_AUDIT_DIR / f"ma2560_stock_only_gap_audit_{ymd(date_str)}.json"
    payload = load_json(path)
    counter: Counter[str] = Counter()
    rows_by_industry: dict[str, list[dict[str, Any]]] = {}
    for row in payload.get("rows", []) or []:
        industry = str(row.get("sw_l1") or "未分类").strip() or "未分类"
        counter[industry] += 1
        rows_by_industry.setdefault(industry, []).append(row)
    return counter, rows_by_industry


def current_by_industry(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in config.get("industry_etf_assets", []) or []:
        sw_l1 = str(row.get("sw_l1") or "").strip()
        if sw_l1:
            out.setdefault(sw_l1, []).append(dict(row))
    return out


def market_state_indexes(
    market_state: dict[str, list[dict[str, str]]],
) -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, dict[str, str]]]:
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    by_symbol: dict[str, dict[str, str]] = {}
    for rows in market_state.values():
        for row in rows:
            symbol = str(row.get("symbol") or "")
            sw_l1 = str(row.get("sw_l1") or "")
            if symbol and sw_l1:
                by_key[(symbol, sw_l1)] = row
            if symbol and symbol not in by_symbol:
                by_symbol[symbol] = row
    return by_key, by_symbol


def fnum(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def market_adjusted_candidates(
    rows: list[dict[str, Any]],
    by_key: dict[tuple[str, str], dict[str, str]],
    by_symbol: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    adjusted = []
    for row in rows:
        item = dict(row)
        symbol = str(item.get("symbol") or "")
        sw_l1 = str(item.get("sw_l1") or "")
        state = by_key.get((symbol, sw_l1)) or {}
        other_state = by_symbol.get(symbol) if not state else {}
        item["in_market_state"] = bool(state)
        item["symbol_used_by_other_industry"] = bool(other_state)
        item["other_industry_sw_l1"] = other_state.get("sw_l1", "") if other_state else ""
        item["market_ef_count"] = state.get("ef_count", "")
        item["market_state_combo"] = "/".join(
            str(state.get(field) or "") for field in ["mn1_state_hex", "w1_state_hex", "d1_state_hex"]
        ).strip("/")
        item["_sort_score"] = (
            int(item.get("score") or 0)
            + (180 if item["in_market_state"] else 0)
            - (120 if item["symbol_used_by_other_industry"] else 0)
            + int((fnum(item.get("market_ef_count")) or 0) * 25)
        )
        adjusted.append(item)
    adjusted.sort(
        key=lambda item: (
            -int(item.get("_sort_score") or 0),
            -int(item.get("score") or 0),
            len(str(item.get("name") or "")),
            str(item.get("symbol") or ""),
        )
    )
    for item in adjusted:
        item.pop("_sort_score", None)
    return adjusted


def compact_candidates(rows: list[dict[str, Any]], limit: int = 10) -> str:
    return "；".join(
        f"{row.get('symbol')} {row.get('name')}[{row.get('match_type')}/{row.get('match_keyword')}/{row.get('score')}/EF={row.get('market_ef_count', '')}]"
        for row in rows[:limit]
    )


def join_assets(rows: list[dict[str, Any]]) -> str:
    return "；".join(f"{row.get('symbol')} {row.get('name')}" for row in rows)


def build_candidate_pool(etfs: list[dict[str, Any]], industries: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for etf in etfs:
        matches: list[dict[str, Any]] = []
        excluded = is_excluded(etf["name"])
        if not excluded:
            for sw_l1 in industries:
                for match_type, keywords in [("direct", DIRECT_KEYWORDS), ("proxy", PROXY_KEYWORDS)]:
                    score, keyword = candidate_score(etf["name"], keywords.get(sw_l1, []), match_type)
                    if keyword:
                        matches.append(
                            {
                                "sw_l1": sw_l1,
                                "match_type": match_type,
                                "match_keyword": keyword,
                                "score": score,
                            }
                        )
        matches.sort(key=lambda item: (-int(item["score"]), item["match_type"], item["sw_l1"]))
        best = matches[0] if matches else {}
        rows.append(
            {
                "symbol": etf["symbol"],
                "name": etf["name"],
                "source": etf.get("source", ""),
                "excluded": excluded,
                "matched": bool(best),
                "best_sw_l1": best.get("sw_l1", ""),
                "best_match_type": best.get("match_type", ""),
                "best_match_keyword": best.get("match_keyword", ""),
                "best_score": best.get("score", ""),
                "all_matches": "；".join(
                    f"{item['sw_l1']}:{item['match_type']}:{item['match_keyword']}:{item['score']}"
                    for item in matches[:12]
                ),
            }
        )
    return rows


def make_asset(row: dict[str, Any], source: str, status: str) -> dict[str, Any]:
    return {
        "symbol": row["symbol"],
        "name": row["name"],
        "asset_type": "industry_etf",
        "sw_l1": row["sw_l1"],
        "source": source,
        "status": status,
        "match_type": row.get("match_type", ""),
        "match_keyword": row.get("match_keyword", ""),
    }


def add_assets_to_config(config: dict[str, Any], auto_assets: list[dict[str, Any]]) -> None:
    existing = {
        (str(row.get("symbol") or ""), str(row.get("sw_l1") or ""))
        for row in config.get("industry_etf_assets", []) or []
    }
    for row in auto_assets:
        key = (str(row.get("symbol") or ""), str(row.get("sw_l1") or ""))
        if key not in existing:
            config.setdefault("industry_etf_assets", []).append(row)
            existing.add(key)


def build_compatible_config(
    config: dict[str, Any],
    auto_assets: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    merged = json.loads(json.dumps(config, ensure_ascii=False))
    meta = dict(merged.get("_meta") or {})
    meta.update(
        {
            "last_auto_build": generated_at,
            "data_sources": ["blackwolf_stock_list", "ifind_industry_snapshot"],
            "note": "Existing manual assets are preserved; generated candidates are append-only.",
        }
    )
    merged["_meta"] = meta
    add_assets_to_config(merged, auto_assets)
    return merged


def build_payload(
    date_str: str,
    stock_list: Path,
    config_path: Path,
    ifind_etf_file: Path | None = None,
    include_proxy: bool = False,
    proxy_whitelist_path: Path = DEFAULT_PROXY_WHITELIST,
) -> dict[str, Any]:
    generated_at = utc_now()
    blackwolf_etfs = load_blackwolf_etfs(stock_list)
    ifind_etfs = load_ifind_etfs(date_str, ifind_etf_file)
    etfs = merge_etf_sources(blackwolf_etfs, ifind_etfs)
    ifind_counts = load_ifind_industry_counts(date_str)
    industries = sorted(ifind_counts)
    config = load_current_config(config_path)
    proxy_whitelist = load_proxy_whitelist(proxy_whitelist_path)
    no_etf_coverage = {
        str(item).strip() for item in proxy_whitelist.get("no_etf_coverage", []) if str(item).strip()
    }
    configured = current_by_industry(config)
    market_state = load_market_state(date_str)
    state_by_key, state_by_symbol = market_state_indexes(market_state)
    stock_only_counts, stock_only_rows = load_stock_only_gap_counts(date_str)

    candidate_pool = build_candidate_pool(etfs, industries)
    mapping_rows: list[dict[str, Any]] = []
    auto_assets: list[dict[str, Any]] = []

    for sw_l1 in industries:
        current = configured.get(sw_l1, [])
        configured_symbols = {str(row.get("symbol") or "") for row in current}
        configured_state_rows = [
            state_by_key[(symbol, sw_l1)] for symbol in configured_symbols if (symbol, sw_l1) in state_by_key
        ]
        direct = market_adjusted_candidates(
            find_candidates(etfs, sw_l1, DIRECT_KEYWORDS, "direct"), state_by_key, state_by_symbol
        )
        proxy = market_adjusted_candidates(
            find_candidates(etfs, sw_l1, PROXY_KEYWORDS, "proxy"), state_by_key, state_by_symbol
        )
        selected: dict[str, Any] = {}

        proxy_review_status = proxy_status(proxy_whitelist, sw_l1)
        if current:
            mapping_status = "configured_active" if configured_state_rows else "configured_pending_download"
            recommended_action = (
                "keep_current_config" if configured_state_rows else "download_or_refresh_configured_asset"
            )
            if direct:
                selected = direct[0]
            elif proxy:
                selected = proxy[0]
        elif sw_l1 in no_etf_coverage:
            mapping_status = "no_etf_coverage"
            recommended_action = "skip_no_etf_coverage"
        elif direct:
            selected = direct[0]
            mapping_status = "auto_direct_candidate"
            recommended_action = "add_to_generated_config_and_download"
            if selected.get("symbol_used_by_other_industry"):
                recommended_action = "manual_review_symbol_reused_by_other_industry"
            else:
                auto_assets.append(
                    make_asset(selected, "auto_mapped_from_blackwolf_ifind", "auto_direct_candidate")
                )
        elif proxy:
            selected = proxy[0]
            upsert_proxy_candidate(proxy_whitelist, sw_l1, selected, generated_at)
            proxy_review_status = proxy_status(proxy_whitelist, sw_l1)
            if is_proxy_approved(proxy_whitelist, sw_l1, selected):
                mapping_status = "proxy_approved"
                recommended_action = "add_approved_proxy_to_generated_config_and_download"
            else:
                mapping_status = f"proxy_{proxy_review_status or 'pending_review'}"
                recommended_action = "manual_review_proxy_candidate"
            if include_proxy or is_proxy_approved(proxy_whitelist, sw_l1, selected):
                auto_assets.append(
                    make_asset(selected, "auto_mapped_proxy_from_blackwolf_ifind", "proxy_review_candidate")
                )
        else:
            mapping_status = "missing_candidate"
            recommended_action = "manual_research_or_ifind_etf_scan"

        configured_best = sorted(
            configured_state_rows,
            key=lambda row: (
                -(fnum(row.get("ef_count")) or -1),
                str(row.get("symbol") or ""),
            ),
        )
        best_state = configured_best[0] if configured_best else {}
        if selected.get("in_market_state"):
            data_status = "active_in_market_state"
        elif selected.get("symbol_used_by_other_industry"):
            data_status = f"symbol_state_under_{selected.get('other_industry_sw_l1')}"
        else:
            data_status = "pending_download" if selected else ""
        stock_only_examples = stock_only_rows.get(sw_l1, [])[:5]
        mapping_rows.append(
            {
                "sw_l1": sw_l1,
                "ifind_stock_count": ifind_counts.get(sw_l1, 0),
                "stock_only_gap_count": stock_only_counts.get(sw_l1, 0),
                "mapping_status": mapping_status,
                "recommended_action": recommended_action,
                "proxy_review_status": proxy_review_status,
                "configured_symbols": join_assets(current),
                "configured_asset_count": len(current),
                "configured_market_best_symbol": best_state.get("symbol", ""),
                "configured_market_best_name": best_state.get("name", ""),
                "configured_market_best_ef_count": best_state.get("ef_count", ""),
                "selected_symbol": selected.get("symbol", ""),
                "selected_name": selected.get("name", ""),
                "selected_source": selected.get("source", ""),
                "selected_match_type": selected.get("match_type", ""),
                "selected_match_keyword": selected.get("match_keyword", ""),
                "selected_score": selected.get("score", ""),
                "selected_data_status": data_status,
                "selected_market_ef_count": selected.get("market_ef_count", ""),
                "selected_market_state_combo": selected.get("market_state_combo", ""),
                "direct_candidates": compact_candidates(direct),
                "proxy_candidates": compact_candidates(proxy),
                "stock_only_examples": "；".join(
                    f"{row.get('stock_code')} {row.get('stock_name')} {row.get('ma2560_state_combo')}"
                    for row in stock_only_examples
                ),
            }
        )

    status_counts = dict(Counter(row["mapping_status"] for row in mapping_rows).most_common())
    action_counts = dict(Counter(row["recommended_action"] for row in mapping_rows).most_common())
    generated_config = build_compatible_config(config, auto_assets, generated_at)
    gap_rows = [
        row
        for row in mapping_rows
        if row["mapping_status"] not in {"configured_active", "no_etf_coverage"}
        or int(row.get("stock_only_gap_count") or 0) > 0
    ]
    return {
        "schema_version": "industry_etf_config_loop_v1",
        "date": date_str,
        "generated_at": generated_at,
        "blackwolf_stock_list": str(stock_list),
        "source_config": str(config_path),
        "proxy_whitelist": str(proxy_whitelist_path),
        "data_sources": {
            "blackwolf_stock_list": len(blackwolf_etfs),
            "ifind_etf_snapshot": len(ifind_etfs),
            "merged_etf_candidates": len(etfs),
            "ifind_industries": len(industries),
        },
        "include_proxy": include_proxy,
        "status_counts": status_counts,
        "action_counts": action_counts,
        "auto_asset_count": len(auto_assets),
        "stock_only_gap_total": sum(stock_only_counts.values()),
        "candidate_pool": candidate_pool,
        "mapping_rows": mapping_rows,
        "gap_rows": gap_rows,
        "auto_assets": auto_assets,
        "proxy_whitelist_payload": proxy_whitelist,
        "generated_config": generated_config,
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

    status_rows = "".join(
        f"<tr><td>{esc(key)}</td><td class='num'>{esc(value)}</td></tr>"
        for key, value in payload["status_counts"].items()
    )
    action_rows = "".join(
        f"<tr><td>{esc(key)}</td><td class='num'>{esc(value)}</td></tr>"
        for key, value in payload["action_counts"].items()
    )
    map_rows = []
    for row in payload["mapping_rows"]:
        map_rows.append(
            f"""
            <tr class="{esc(row.get("mapping_status"))}">
              <td><strong>{esc(row.get("sw_l1"))}</strong><br><span>{esc(row.get("ifind_stock_count"))} 只 / stock_only {esc(row.get("stock_only_gap_count"))}</span></td>
              <td>{esc(row.get("mapping_status"))}<br><span>{esc(row.get("recommended_action"))}</span></td>
              <td>{esc(row.get("proxy_review_status"))}</td>
              <td>{esc(row.get("configured_symbols"))}</td>
              <td>{esc(row.get("configured_market_best_symbol"))}<br><span>{esc(row.get("configured_market_best_name"))} EF={esc(row.get("configured_market_best_ef_count"))}</span></td>
              <td><strong>{esc(row.get("selected_symbol"))}</strong><br><span>{esc(row.get("selected_name"))}</span></td>
              <td>{esc(row.get("selected_match_type"))}<br><span>{esc(row.get("selected_match_keyword"))} / {esc(row.get("selected_score"))}</span></td>
              <td>{esc(row.get("selected_data_status"))}<br><span>EF={esc(row.get("selected_market_ef_count"))} {esc(row.get("selected_market_state_combo"))}</span></td>
              <td>{esc(row.get("direct_candidates"))}</td>
              <td>{esc(row.get("proxy_candidates"))}</td>
              <td>{esc(row.get("stock_only_examples"))}</td>
            </tr>
            """
        )
    candidate_rows = []
    for row in payload["candidate_pool"]:
        if not row.get("matched"):
            continue
        candidate_rows.append(
            f"""
            <tr>
              <td><strong>{esc(row.get("symbol"))}</strong><br><span>{esc(row.get("source"))}</span></td>
              <td>{esc(row.get("name"))}</td>
              <td>{esc(row.get("best_sw_l1"))}</td>
              <td>{esc(row.get("best_match_type"))}<br><span>{esc(row.get("best_match_keyword"))} / {esc(row.get("best_score"))}</span></td>
              <td>{esc(row.get("all_matches"))}</td>
            </tr>
            """
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>行业ETF配置闭环 - {esc(payload["date"])}</title>
  <style>
    body {{ margin:0; background:#f6f8fb; color:#172033; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    main {{ max-width:1500px; margin:0 auto; padding:24px; }}
    h1 {{ margin:0 0 6px; font-size:26px; }}
    h2 {{ margin:22px 0 10px; font-size:18px; }}
    .meta {{ color:#5d6b82; margin-bottom:18px; }}
    .grid {{ display:grid; grid-template-columns: repeat(2, minmax(260px, 1fr)); gap:16px; align-items:start; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid #e1e6ef; }}
    th,td {{ text-align:left; vertical-align:top; padding:9px 10px; border-bottom:1px solid #edf1f7; border-right:1px solid #edf1f7; font-size:13px; }}
    th {{ position:sticky; top:0; background:#eef4f1; z-index:1; }}
    td span {{ color:#667085; font-size:12px; }}
    .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .wrap {{ max-height:74vh; overflow:auto; border:1px solid #e1e6ef; }}
    tr.auto_direct_candidate td:first-child {{ border-left:4px solid #0f766e; }}
    tr.auto_proxy_candidate td:first-child {{ border-left:4px solid #b7791f; }}
    tr.missing_candidate td:first-child {{ border-left:4px solid #b42318; }}
    tr.configured_pending_download td:first-child {{ border-left:4px solid #6941c6; }}
  </style>
</head>
<body>
  <main>
    <h1>行业ETF配置闭环</h1>
    <div class="meta">日期 {esc(payload["date"])} | 黑狼ETF {esc(payload["data_sources"]["blackwolf_stock_list"])} | iFind ETF {esc(payload["data_sources"]["ifind_etf_snapshot"])} | 合并候选 {esc(payload["data_sources"]["merged_etf_candidates"])} | 自动资产 {esc(payload["auto_asset_count"])} | stock_only缺口 {esc(payload["stock_only_gap_total"])}</div>
    <div class="grid">
      <section>
        <h2>映射状态</h2>
        <table><thead><tr><th>状态</th><th>数量</th></tr></thead><tbody>{status_rows}</tbody></table>
      </section>
      <section>
        <h2>建议动作</h2>
        <table><thead><tr><th>动作</th><th>数量</th></tr></thead><tbody>{action_rows}</tbody></table>
      </section>
    </div>
    <h2>行业映射审计</h2>
    <div class="wrap">
      <table>
        <thead><tr><th>行业</th><th>状态</th><th>代理审核</th><th>当前配置</th><th>当前State</th><th>候选</th><th>匹配</th><th>候选数据</th><th>直接候选</th><th>代理候选</th><th>stock_only样本</th></tr></thead>
        <tbody>{"".join(map_rows)}</tbody>
      </table>
    </div>
    <h2>ETF候选池（已命中关键词）</h2>
    <div class="wrap">
      <table>
        <thead><tr><th>代码</th><th>名称</th><th>最佳行业</th><th>最佳匹配</th><th>全部匹配</th></tr></thead>
        <tbody>{"".join(candidate_rows)}</tbody>
      </table>
    </div>
  </main>
</body>
</html>
"""


def write_outputs(payload: dict[str, Any], config_path: Path, apply: bool = False) -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    date_ymd = ymd(payload["date"])
    stem = f"industry_etf_config_{date_ymd}"
    mapping_json = OUT_DIR / f"{stem}.json"
    mapping_csv = OUT_DIR / f"{stem}.csv"
    candidates_json = OUT_DIR / f"industry_etf_candidates_{date_ymd}.json"
    candidates_csv = OUT_DIR / f"industry_etf_candidates_{date_ymd}.csv"
    gap_json = OUT_DIR / f"industry_etf_gap_report_{date_ymd}.json"
    gap_csv = OUT_DIR / f"industry_etf_gap_report_{date_ymd}.csv"
    generated_config_path = ROOT / "config" / f"industry_rotation_assets.auto_{date_ymd}.json"
    proxy_whitelist_path = Path(str(payload.get("proxy_whitelist") or DEFAULT_PROXY_WHITELIST))
    html_path = PUBLIC_DIR / f"{stem}.html"

    mapping_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"candidate_pool", "generated_config", "proxy_whitelist_payload"}
    }
    mapping_json.write_text(
        json.dumps(mapping_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_csv(mapping_csv, payload["mapping_rows"])
    write_proxy_whitelist(proxy_whitelist_path, payload["proxy_whitelist_payload"])
    candidates_json.write_text(
        json.dumps(
            {
                "schema_version": "industry_etf_candidate_pool_v1",
                "date": payload["date"],
                "generated_at": payload["generated_at"],
                "rows": payload["candidate_pool"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_csv(candidates_csv, payload["candidate_pool"])
    gap_json.write_text(
        json.dumps(
            {
                "schema_version": "industry_etf_gap_report_v1",
                "date": payload["date"],
                "generated_at": payload["generated_at"],
                "rows": payload["gap_rows"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_csv(gap_csv, payload["gap_rows"])
    generated_config_path.write_text(
        json.dumps(payload["generated_config"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    html_path.write_text(render_html(payload), encoding="utf-8")

    latest_pairs = [
        (mapping_json, OUT_DIR / "industry_etf_config_latest.json"),
        (mapping_csv, OUT_DIR / "industry_etf_config_latest.csv"),
        (candidates_json, OUT_DIR / "industry_etf_candidates_latest.json"),
        (candidates_csv, OUT_DIR / "industry_etf_candidates_latest.csv"),
        (gap_json, OUT_DIR / "industry_etf_gap_report_latest.json"),
        (gap_csv, OUT_DIR / "industry_etf_gap_report_latest.csv"),
        (html_path, PUBLIC_DIR / "industry_etf_config_latest.html"),
    ]
    for src, dst in latest_pairs:
        shutil.copyfile(src, dst)

    applied = False
    backup_path = ""
    if apply and payload.get("auto_assets"):
        backup = config_path.with_name(
            f"{config_path.stem}.bak_{date_ymd}_{datetime.now().strftime('%H%M%S')}{config_path.suffix}"
        )
        shutil.copyfile(config_path, backup)
        production_config = load_current_config(config_path)
        add_assets_to_config(production_config, payload["auto_assets"])
        config_path.write_text(
            json.dumps(production_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        applied = True
        backup_path = str(backup)

    return {
        "mapping_json": str(mapping_json),
        "mapping_csv": str(mapping_csv),
        "candidates_json": str(candidates_json),
        "candidates_csv": str(candidates_csv),
        "gap_json": str(gap_json),
        "gap_csv": str(gap_csv),
        "generated_config": str(generated_config_path),
        "proxy_whitelist": str(proxy_whitelist_path),
        "html": str(html_path),
        "latest_html": str(PUBLIC_DIR / "industry_etf_config_latest.html"),
        "applied": applied,
        "applied_asset_count": len(payload.get("auto_assets") or []) if applied else 0,
        "backup": backup_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build industry ETF config candidates and gap audit.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--stock-list", type=Path, default=DEFAULT_BLACKWOLF_LIST)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--proxy-whitelist", type=Path, default=DEFAULT_PROXY_WHITELIST)
    parser.add_argument("--ifind-etf-file", type=Path)
    parser.add_argument(
        "--include-proxy", action="store_true", help="Include proxy candidates in generated config."
    )
    parser.add_argument(
        "--apply", action="store_true", help="Write generated compatible config back to config path."
    )
    args = parser.parse_args()
    payload = build_payload(
        args.date, args.stock_list, args.config, args.ifind_etf_file, args.include_proxy, args.proxy_whitelist
    )
    outputs = write_outputs(payload, args.config, apply=args.apply)
    print(
        json.dumps(
            {
                "ok": True,
                "date": args.date,
                "status_counts": payload["status_counts"],
                "action_counts": payload["action_counts"],
                "auto_asset_count": payload["auto_asset_count"],
                "stock_only_gap_total": payload["stock_only_gap_total"],
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
