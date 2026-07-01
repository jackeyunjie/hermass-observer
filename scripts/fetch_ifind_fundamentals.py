#!/usr/bin/env python3
"""Fetch iFinD stock fundamentals (PE/PB/ROE/growth) and cache locally.

Usage:
  python scripts/fetch_ifind_fundamentals.py 600519.SH [000858.SZ ...]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "ifind"
OUTPUT_FILE = OUTPUT_DIR / "stock_fundamentals.json"


def _find_skill() -> Path | None:
    for p in [
        Path.home() / ".trae" / "skills" / "ifind-finance-data",
        Path.home() / ".codex" / ".tmp" / "skills" / "ifind-finance-data",
        ROOT / "ifind-finance-data-1.1.0",
    ]:
        if (p / "call-node.js").exists() and (p / "mcp_config.json").exists():
            return p
    return None


def _node_call(skill_dir: Path, server: str, tool: str, params: dict) -> dict:
    js_code = [
        f'const {{ call }} = require("{skill_dir / "call-node.js"}");',
        "(async () => {",
        f'  const r = await call("{server}", "{tool}", {json.dumps(params, ensure_ascii=False)});',
        "  console.log(JSON.stringify(r));",
        "})().catch(e => console.log('{\"ok\":false,\"error\":\"'+e.message+'\"}'));",
    ]
    fd, tmp = tempfile.mkstemp(suffix=".js", prefix="ifnd_")
    os.close(fd)
    try:
        Path(tmp).write_text("\n".join(js_code), encoding="utf-8")
        r = subprocess.run(["node", tmp], capture_output=True, text=True, timeout=60, cwd=str(skill_dir))
        out = r.stdout.strip()
        return json.loads(out) if out else {"ok": False, "error": "empty"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _extract_answer(raw: dict) -> str:
    try:
        text = raw.get("data", {}).get("result", {}).get("content", [{}])[0].get("text", "")
        return json.loads(text).get("data", {}).get("answer", "") if text else ""
    except Exception:
        return ""


def _floatish(val: any) -> float | None:
    if val is None or val == "":
        return None
    try:
        s = str(val).replace(",", "").replace("亿", "").replace("\\t", "").replace("\t", "").strip()
        if s in ("", "-", "--"):
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def _cell_value(row: str, col_index: int) -> str:
    """Extract cell value from a pipe-delimited row by column index."""
    cells = [c.strip() for c in row.split("|")]
    # cells[0] is empty (before first |), cells[-1] is empty (after last |)
    cells = [c for c in cells if c]  # remove empty entries... no, keep indexing
    if col_index < len(cells):
        return cells[col_index]
    return ""


def _parse_summary(answer: str) -> dict:
    """Parse get_stock_summary pipe table."""
    result: dict = {}
    lines = answer.split("\n")
    for i, line in enumerate(lines):
        if "市盈率(PE,TTM)" in line and "|" in line:
            next_non_sep = ""
            for j in range(i + 1, min(i + 5, len(lines))):
                lj = lines[j].strip()
                if "---" in lj:
                    continue
                if lj.startswith("|") and lj.count("|") > 2:
                    next_non_sep = lj
                    break
            if next_non_sep:
                cells = [c.strip().replace("\\t", "") for c in next_non_sep.split("|")]
                # cells: ["", "stock_code", "name", "PE", "PB", "PS", "PCF", "PEG", "EV/EBITDA", ""]
                if len(cells) >= 6:
                    result["pe_ttm"] = _floatish(cells[3])
                    result["pb"] = _floatish(cells[4])
                if len(cells) >= 7:
                    result["ps"] = _floatish(cells[5])
                if len(cells) >= 8:
                    result["peg"] = _floatish(cells[7])
        if "总市值" in line and "|" in line:
            next_non_sep = ""
            for j in range(i + 1, min(i + 5, len(lines))):
                lj = lines[j].strip()
                if "---" in lj:
                    continue
                if lj.startswith("|") and lj.count("|") > 2:
                    next_non_sep = lj
                    break
            if next_non_sep:
                cells = [c.strip().replace("\\t", "") for c in next_non_sep.split("|")]
                if len(cells) >= 4:
                    result["market_cap"] = _floatish(cells[3])
                if len(cells) >= 6:
                    result["total_assets"] = _floatish(cells[5])
                if len(cells) >= 7:
                    result["revenue_ttm"] = _floatish(cells[6])
    return result


def _parse_financials(answer: str) -> dict:
    """Parse get_stock_financials pipe table. Find ROE TTM and revenue growth by header position."""
    result: dict = {}
    lines = [l.strip() for l in answer.split("\n") if l.strip().startswith("|")]
    if len(lines) < 3:
        return result

    # Find header column indices
    header_cells = [c.strip() for c in lines[0].split("|")]
    roe_idx = -1
    roe_ttm_idx = -1
    rev_growth_idx = -1
    np_growth_idx = -1
    date_idx = -1
    for i, h in enumerate(header_cells):
        if "净资产收益率ROE(加权,公布值)" in h or "ROE(加权" in h:
            roe_idx = i
        if "ROE(TTM)" in h and "平均" not in h:
            roe_ttm_idx = i
        if "营业收入" in h and "增长" in h and "单季度" not in h:
            rev_growth_idx = i
        if "归属母公司股东的净利润" in h and "增长" in h:
            np_growth_idx = i
        if h == "日期":
            date_idx = i

    # Find first data row with non-empty ROE
    for line in lines[2:]:  # skip header and separator
        if "---" in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        if roe_idx < len(cells):
            raw_roe = cells[roe_idx].replace("\\t", "").strip()
            roe = _floatish(raw_roe)
            if roe is not None:
                result["roe"] = roe
                result["roe_ttm"] = _floatish(cells[roe_ttm_idx].replace("\\t", "").strip()) if 0 <= roe_ttm_idx < len(cells) else None
                result["revenue_growth"] = _floatish(cells[rev_growth_idx].replace("\\t", "").strip()) if 0 <= rev_growth_idx < len(cells) else None
                result["net_profit_growth"] = _floatish(cells[np_growth_idx].replace("\\t", "").strip()) if 0 <= np_growth_idx < len(cells) else None
                result["report_date"] = cells[date_idx].strip() if 0 <= date_idx < len(cells) else ""
                break
    return result


def load_cached_fundamentals() -> dict[str, dict]:
    if not OUTPUT_FILE.exists():
        return {}
    try:
        data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        cached = data.get("cached_at", "")
        if cached:
            try:
                if (datetime.now() - datetime.fromisoformat(cached)).days > 5:
                    return {}
            except Exception:
                return {}
        return data.get("stocks", {}) or {}
    except Exception:
        return {}


def fetch_stock_fundamentals(codes: list[str], skill_dir: Path | None = None) -> dict:
    skill = skill_dir or _find_skill()
    if not skill:
        return {}
    cache = load_cached_fundamentals()
    results: dict = {}
    for code in codes:
        code = str(code or "").strip()
        if not code:
            continue
        if code in cache and cache[code].get("pe_ttm") is not None:
            results[code] = cache[code]
            continue
        summary = _node_call(skill, "stock", "get_stock_summary", {"query": f"{code} PE 市值"})
        time.sleep(0.6)
        financials = _node_call(skill, "stock", "get_stock_financials", {"query": f"{code} 最新 ROE 净利润增速 营收增速"})
        time.sleep(0.6)
        parsed = {**_parse_summary(_extract_answer(summary)), **_parse_financials(_extract_answer(financials))}
        parsed["fetched_at"] = datetime.now().isoformat()
        results[code] = parsed
        cache[code] = parsed
        # 每拉一只就写缓存，避免超时/中断导致全部丢失
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(
            json.dumps({"cached_at": datetime.now().isoformat(), "stocks": cache}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fetch_ifind_fundamentals.py 600519.SH [000858.SZ ...]")
        sys.exit(1)
    r = fetch_stock_fundamentals(sys.argv[1:])
    print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])
