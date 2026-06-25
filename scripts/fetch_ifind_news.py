#!/usr/bin/env python3
"""Fetch iFinD news & notices for candidate stocks and cache locally.

L1: 交易所公告 / L2: 正规财经媒体新闻
Output: outputs/ifind/external_clues.json

Usage:
  python scripts/fetch_ifind_news.py --stocks 000021.SZ,600519.SH
  python scripts/fetch_ifind_news.py --from-candidates  # 从首页观察候选自动取
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "ifind"
OUTPUT_FILE = OUTPUT_DIR / "external_clues.json"
MAX_CONCURRENT = 2  # 免费用户每秒最多 2 并发
MAX_STOCKS = 10

# 股票代码 → 简称 映射表（常用）
STOCK_NAME_MAP = {
    "000021.SZ": "深科技",
    "600519.SH": "贵州茅台",
    "000858.SZ": "五粮液",
    "300750.SZ": "宁德时代",
    "000333.SZ": "美的集团",
    "601318.SH": "中国平安",
    "002415.SZ": "海康威视",
    "600036.SH": "招商银行",
    "000651.SZ": "格力电器",
    "002594.SZ": "比亚迪",
    "601012.SH": "隆基绿能",
    "300124.SZ": "汇川技术",
    "002230.SZ": "科大讯飞",
    "000063.SZ": "中兴通讯",
    "002475.SZ": "立讯精密",
    "603259.SH": "药明康德",
    "300274.SZ": "阳光电源",
    "600809.SH": "山西汾酒",
    "000001.SZ": "平安银行",
    "601888.SH": "中国中免",
}


def _find_ifind_skill() -> Path | None:
    candidates = [
        Path.home() / ".trae" / "skills" / "ifind-finance-data",
        Path.home() / ".codex" / ".tmp" / "skills" / "ifind-finance-data",
        ROOT / "ifind-finance-data-1.1.0",
    ]
    for p in candidates:
        node_script = p / "call-node.js"
        config_file = p / "mcp_config.json"
        if node_script.exists() and config_file.exists():
            return p
    return None


def _node_call(skill_dir: Path, server_type: str, tool_name: str, params: dict) -> dict:
    """Call iFinD MCP via Node.js subprocess."""
    script = skill_dir / "call-node.js"
    params_json = json.dumps(params)
    # 转义防止 shell 注入
    safe_params = params_json.replace("\\", "\\\\").replace("'", "'\\''")

    code = f"""
const {{ call }} = require('{script}');
(async () => {{
  const r = await call('{server_type}', '{tool_name}', {json.dumps(params)});
  console.log(JSON.stringify(r));
}})().catch(e => console.log(JSON.stringify({{ok: false, error: e.message}})));
"""
    result = subprocess.run(
        ["node", "-e", code],
        capture_output=True,
        text=True,
        timeout=90,
        cwd=str(skill_dir),
    )
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr.strip() or "subprocess error"}

    try:
        return json.loads(result.stdout.strip()) or {"ok": False, "error": "empty response"}
    except json.JSONDecodeError:
        return {"ok": False, "error": result.stdout.strip()[:200]}


def _parse_notices(raw_data: dict, stock_code: str) -> list[dict]:
    """Parse iFinD notice response into structured clues."""
    clues = []
    try:
        content = raw_data.get("data", {}).get("result", {}).get("content", [])
        for block in content:
            text_blob = block.get("text", "{}")
            inner = json.loads(text_blob)
            items_str = inner.get("data", {}).get("data", "[]")
            items = json.loads(items_str) if isinstance(items_str, str) else items_str
            for item in (items or []):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("公告标题") or "").strip()
                snippet = str(item.get("公告片段内容") or "").strip()
                notice_date = str(item.get("日期") or "")
                if not title or "备注" in title:
                    continue
                clues.append({
                    "clue_type": "notice",
                    "source_layer": "L1",
                    "source_name": "上市公司公告",
                    "title": title[:120],
                    "snippet": snippet[:200],
                    "date": notice_date,
                    "stock_code": stock_code,
                    "stock_name": STOCK_NAME_MAP.get(stock_code, ""),
                    "trust_level": "confirmed",
                    "verification_status": "confirmed",
                    "impact": "neutral",
                    "related_stock_codes": [stock_code],
                    "related_industries": [],
                    "risk_note": "",
                })
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return clues


def _parse_news(raw_data: dict, stock_code: str) -> list[dict]:
    """Parse iFinD news response into structured clues."""
    clues = []
    try:
        content = raw_data.get("data", {}).get("result", {}).get("content", [])
        for block in content:
            text_blob = block.get("text", "{}")
            inner = json.loads(text_blob)
            items_str = inner.get("data", {}).get("data", "[]")
            items = json.loads(items_str) if isinstance(items_str, str) else items_str
            for item in (items or []):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("标题") or item.get("新闻标题") or "").strip()
                snippet = str(item.get("内容") or item.get("摘要") or item.get("新闻片段内容") or "").strip()
                news_date = str(item.get("日期") or item.get("发布时间") or "")
                if not title:
                    continue
                clues.append({
                    "clue_type": "news",
                    "source_layer": "L2",
                    "source_name": "财经媒体",
                    "title": title[:120],
                    "snippet": snippet[:200],
                    "date": news_date,
                    "stock_code": stock_code,
                    "stock_name": STOCK_NAME_MAP.get(stock_code, ""),
                    "trust_level": "clue_only",
                    "verification_status": "unverified",
                    "impact": "neutral",
                    "related_stock_codes": [stock_code],
                    "related_industries": [],
                    "risk_note": "媒体信息需交叉验证，不作为独立决策依据",
                })
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return clues


def fetch_stock_clues(
    stock_codes: list[str],
    days_back: int = 7,
    skill_dir: Path | None = None,
) -> dict[str, Any]:
    """Fetch notices + news for a list of stocks."""
    if not stock_codes:
        return {"ok": True, "stocks": {}, "total_clues": 0}

    skill = skill_dir or _find_ifind_skill()
    if not skill:
        return {"ok": False, "error": "iFinD skill directory not found"}

    today = date.today()
    time_start = (today - timedelta(days=days_back)).isoformat()
    time_end = today.isoformat()

    all_clues: list[dict] = []
    stock_results: dict[str, dict] = {}
    request_errors: list[dict] = []

    for stock_code in stock_codes[:MAX_STOCKS]:
        code_clean = stock_code.strip()
        if not code_clean:
            continue
        name = STOCK_NAME_MAP.get(code_clean, code_clean)

        # L1: 公告
        notice_result = _node_call(skill, "news", "search_notice", {
            "query": name,
            "time_start": time_start,
            "time_end": time_end,
            "size": 3,
        })
        notices = _parse_notices(notice_result, code_clean) if notice_result.get("ok") else []
        if not notice_result.get("ok"):
            request_errors.append({
                "stock_code": code_clean,
                "tool": "search_notice",
                "error": str(notice_result.get("error") or "unknown error")[:200],
            })
        time.sleep(0.6)  # 控制并发：免费用户 2 req/s

        # L2: 新闻
        news_result = _node_call(skill, "news", "search_news", {
            "query": name,
            "time_start": time_start,
            "time_end": time_end,
            "size": 3,
        })
        news = _parse_news(news_result, code_clean) if news_result.get("ok") else []
        if not news_result.get("ok"):
            request_errors.append({
                "stock_code": code_clean,
                "tool": "search_news",
                "error": str(news_result.get("error") or "unknown error")[:200],
            })

        stock_results[code_clean] = {
            "stock_name": name,
            "notice_count": len(notices),
            "news_count": len(news),
            "total": len(notices) + len(news),
            "errors": [
                err
                for err in request_errors
                if err.get("stock_code") == code_clean
            ],
        }
        all_clues.extend(notices)
        all_clues.extend(news)
        time.sleep(0.6)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    attempted_requests = len(stock_results) * 2
    all_requests_failed = bool(attempted_requests) and len(request_errors) >= attempted_requests
    payload = {
        "ok": not all_requests_failed,
        "fetched_at": datetime.now().isoformat(),
        "date": today.isoformat(),
        "time_range": f"{time_start} ~ {time_end}",
        "stocks": stock_results,
        "total_stocks": len(stock_results),
        "total_clues": len(all_clues),
        "errors": request_errors,
        "clues": all_clues,
    }
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": payload["ok"],
        "stocks": len(stock_results),
        "clues": len(all_clues),
        "errors": len(request_errors),
        "file": str(OUTPUT_FILE),
    }))
    return payload


def load_cached_clues() -> dict[str, Any]:
    """Load cached clues JSON, return empty if missing or stale (>2 days)."""
    if not OUTPUT_FILE.exists():
        return {"ok": True, "clues": [], "total_clues": 0, "date": str(date.today())}
    try:
        payload = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        cache_date_str = payload.get("date", "")
        if cache_date_str:
            cache_date = date.fromisoformat(cache_date_str)
            if (date.today() - cache_date).days > 2:
                return {"ok": True, "clues": [], "total_clues": 0, "date": str(date.today()), "stale": True}
        return payload
    except Exception:
        return {"ok": True, "clues": [], "total_clues": 0, "date": str(date.today())}


def load_cached_clues_for_stock(stock_code: str) -> list[dict]:
    """Load cached clues filtered to one stock."""
    payload = load_cached_clues()
    all_clues = payload.get("clues", []) or []
    code_upper = str(stock_code or "").strip().upper()
    return [
        c for c in all_clues
        if any(
            str(related).strip().upper() == code_upper
            for related in (c.get("related_stock_codes") or [])
        )
    ]


def main():
    parser = argparse.ArgumentParser(description="Fetch iFinD external clues for stocks.")
    parser.add_argument("--stocks", type=str, default="", help="Comma-separated stock codes, e.g. 000021.SZ,600519.SH")
    parser.add_argument("--from-candidates", action="store_true", help="Auto-detect stocks from today's observation candidates")
    parser.add_argument("--days", type=int, default=7, help="Lookback days (default 7)")
    parser.add_argument("--skill-dir", type=str, default="", help="Override iFinD skill directory")
    args = parser.parse_args()

    stock_codes: list[str] = []

    if args.from_candidates:
        # 从首页简报的 watch_candidates 提取股票
        try:
            sys.path.insert(0, str(ROOT))
            from web import main as web_main  # type: ignore
            brief = web_main._daily_observation_brief()
            for c in (brief.get("watch_candidates") or [])[:MAX_STOCKS]:
                code = str(c.get("stock_code") or "").strip()
                if code and len(code) >= 6:
                    stock_codes.append(code)
            print(f"Auto-detected {len(stock_codes)} candidates: {stock_codes}")
        except Exception as e:
            print(f"Warning: could not auto-detect candidates: {e}", file=sys.stderr)

    if args.stocks:
        stock_codes = [s.strip() for s in args.stocks.split(",") if s.strip()]

    if not stock_codes:
        print("No stocks specified. Use --stocks or --from-candidates.")
        sys.exit(0)

    skill_dir = Path(args.skill_dir) if args.skill_dir else None
    fetch_stock_clues(stock_codes, days_back=args.days, skill_dir=skill_dir)


if __name__ == "__main__":
    main()
