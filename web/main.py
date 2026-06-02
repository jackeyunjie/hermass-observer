#!/usr/bin/env python3
"""Hermass internal web console.

Small FastAPI + Jinja2 app for team-visible operational review.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import requests
from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]

import contextlib
import io

from hermass_platform.agents.base_agent import find_foundation_db
from hermass_platform.api.user_profiles import get_current_profile, init_profiles
from hermass_platform.research import (
    build_external_research_evidence,
    format_deep_research_card,
    format_evidence_card,
    format_quick_research_card,
)

# 启动时初始化用户 profile（读取环境变量 HERMASS_HTPASSWD_USERS 中的逗号分隔用户名）
init_profiles([u.strip() for u in os.environ.get("HERMASS_HTPASSWD_USERS", "").split(",") if u.strip()])

from backtest.engine import run_backtest
from backtest.config import BacktestConfig
from scripts.deepseek_context import with_deepseek_context

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
templates.env.cache = None


def _jinja_state_color(state_name: str) -> str:
    """返回 State 名称对应的 CSS 变量。"""
    mapping = {
        "天时": "var(--state-tianshi)",
        "地利": "var(--state-dili)",
        "人和": "var(--state-renhe)",
        "蓄力": "var(--state-xuli)",
        "冬眠": "var(--state-dongmian)",
        "逆位": "var(--state-niwei)",
    }
    return mapping.get(str(state_name).strip(), "#94a3b8")


def _jinja_tag_class(tag: str) -> str:
    """返回共振标签的 Tailwind CSS class。"""
    mapping = {
        "突破": "bg-green-50 text-green-700 border border-green-200",
        "观察": "bg-amber-50 text-amber-700 border border-amber-200",
        "收缩": "bg-slate-100 text-slate-600 border border-slate-200",
    }
    return mapping.get(str(tag).strip(), "bg-slate-100 text-slate-500 border border-slate-200")


def _jinja_severity_badge(severity: str) -> str:
    """返回严重度 badge 的 HTML 字符串。"""
    s = str(severity).strip().lower()
    if s == "high":
        return '<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-50 text-red-700 border border-red-200">高</span>'
    elif s == "medium":
        return '<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">中</span>'
    return '<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-50 text-slate-600 border border-slate-200">低</span>'


templates.env.globals["state_color"] = _jinja_state_color
templates.env.globals["tag_class"] = _jinja_tag_class
templates.env.globals["severity_badge"] = _jinja_severity_badge

app = FastAPI(title="Hermass Internal Console", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


STRATEGY_CATALOG: dict[str, dict[str, str]] = {
    "vcp": {
        "label": "VCP 收缩突破",
        "path_label": "收缩释放共振路径",
        "what": "抓收缩后的突破确认，不是单纯看股价冲高。",
        "how": "要同时看波幅递减、突破确认和量能分级，适合从蓄力转向释放的阶段。",
        "when": "更适合大周期支持、短周期刚完成收缩释放时看。",
        "avoid": "不适合把普通上涨误读成 VCP，也不适合在无共振环境里追突破。",
        "risk": "这不是常驻主策略。只有当市场 breadth 改善、行业方向集中、个股结构完成收缩释放时，VCP 才值得抬高权重。",
    },
    "ma2560": {
        "label": "25/60 趋势跟踪",
        "path_label": "趋势推进共振路径",
        "what": "抓趋势开始形成到延展持有的过程，不是简单的均线金叉。",
        "how": "要同时看 MA25 上斜、价格位置、量能确认和回踩次数控制。",
        "when": "更适合趋势明确、环境支持趋势跟踪时看。",
        "avoid": "不适合震荡环境，也不应把一次金叉直接等同于高质量趋势机会。",
        "risk": "这不是任何时点都能推进的常量策略。市场一旦转入高离散震荡或趋势塌缩，25/60 很容易从趋势工具退化成来回试错。",
    },
    "bollinger_bandit": {
        "label": "布林强盗延展",
        "path_label": "波动扩张共振路径",
        "what": "抓趋势延展与带宽扩张，不是普通的布林带突破。",
        "how": "要同时看上轨突破、动量过滤、量能分级和后续递减均线退出。",
        "when": "更适合已有趋势基础、波动开始释放但还未失控时看。",
        "avoid": "不适合把任何上轨突破都当机会，也不适合忽略退出纪律。",
        "risk": "这是最容易被误用的高波动策略。只有在趋势释放且波动扩张真正有主线承接时才可观察，否则很容易把噪音当趋势。",
    },
    "ef": {
        "label": "E/F State 信号",
        "path_label": "结构过滤共振路径",
        "what": "用三周期 State 共振做环境过滤，不是把 E/F 编码直接当买点。",
        "how": "先看 MN1/W1/D1 的结构环境，再决定是否允许策略继续下钻到个股。",
        "when": "更适合做环境筛选和样本缩圈，不适合作为单独执行策略。",
        "avoid": "不要把 E/F 本身当成独立交易系统，也不要忽略行业与市场阶段。",
        "risk": "它主要是环境过滤层，不是完整执行策略。单看 E/F 容易把结构优势误读成可直接交易的信号。",
    },
    "composite": {
        "label": "复合策略",
        "path_label": "组合验证路径",
        "what": "把多种策略条件组合起来做验证，不代表一定优于单策略。",
        "how": "应先拆开看各子策略在什么环境有效，再决定是否做组合。",
        "when": "更适合研究阶段横向比较，不适合在未拆解归因前直接实用化。",
        "avoid": "不要把组合后的结果当成天然更稳健，也不要用它掩盖单策略失效。",
        "risk": "复合策略最容易把环境差异、样本偏差和归因问题揉在一起。回测结果好看，不代表现实里更易执行。",
    },
}


def _latest_path(pattern: str) -> Path | None:
    matches = sorted(ROOT.glob(pattern))
    return matches[-1] if matches else None


def _digits_only_code(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:6]


def _latest_dated_data_file(directory: Path, prefix: str, suffix: str, as_of_date: str) -> Path | None:
    latest: tuple[str, Path] | None = None
    target = as_of_date.replace("-", "")
    for path in sorted(directory.glob(f"{prefix}_*{suffix}")):
        match = re.search(r"(\d{8})", path.stem)
        if not match:
            continue
        ymd = match.group(1)
        if ymd > target:
            continue
        if latest is None or ymd > latest[0]:
            latest = (ymd, path)
    return latest[1] if latest else None


def _rel(path: Path | str | None) -> str:
    if not path:
        return "-"
    p = Path(path)
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _read_json(path: Path | None) -> dict[str, Any] | list[Any] | None:
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_dateish(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _freshness_info(
    name: str,
    source_date: Any,
    core_date: Any,
    max_lag_days: int,
    cadence_label: str = "日更",
    usage_label: str = "主判断",
    path: Path | str | None = None,
) -> dict[str, Any]:
    source_dt = _parse_dateish(source_date)
    core_dt = _parse_dateish(core_date)
    lag_days = None
    if source_dt and core_dt:
        lag_days = (core_dt - source_dt).days
    usable = bool(source_dt and core_dt and lag_days is not None and lag_days <= max_lag_days)
    status = "missing"
    if source_dt and core_dt:
        status = "ok" if usable else "stale"
    elif source_dt:
        status = "unknown"

    if status == "ok":
        message = (
            f"{name}（{cadence_label}，{usage_label}）当前可用，"
            f"最新日期 {source_dt.isoformat()}。"
        )
    elif status == "stale":
        message = (
            f"{name}（{cadence_label}，{usage_label}）最新仅到 {source_dt.isoformat()}，相对核心日期 {core_dt.isoformat()} "
            f"滞后 {lag_days} 天，当前不纳入前台主判断。"
        )
    elif status == "missing":
        message = f"{name}（{cadence_label}，{usage_label}）当前缺失，前台不使用该模块。"
    else:
        message = f"{name}（{cadence_label}，{usage_label}）日期无法校验，前台按保守方式处理。"

    return {
        "name": name,
        "source_date": source_dt.isoformat() if source_dt else "-",
        "core_date": core_dt.isoformat() if core_dt else "-",
        "lag_days": lag_days,
        "max_lag_days": max_lag_days,
        "cadence_label": cadence_label,
        "usage_label": usage_label,
        "status": status,
        "usable": usable,
        "path": _rel(path),
        "message": message,
    }


def _strategy_definition(strategy_id: str) -> dict[str, str]:
    return STRATEGY_CATALOG.get(
        strategy_id,
        {
            "label": strategy_id or "未定义策略",
            "path_label": strategy_id or "未定义路径",
            "what": "当前没有固定说明。",
            "how": "需结合研究卡进一步解释。",
            "when": "暂无固定场景。",
            "avoid": "暂无固定限制。",
            "risk": "当前没有固定风险提示。",
        },
    )


def _display_path_label(strategy_id: str) -> str:
    return _strategy_definition(strategy_id).get("path_label") or _strategy_definition(strategy_id).get("label") or "未定义路径"


def _display_path_distribution(distribution: dict[str, Any]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for key, value in (distribution or {}).items():
        label = _display_path_label(str(key).split(":", 1)[0])
        try:
            merged[label] = merged.get(label, 0) + int(value)
        except Exception:
            continue
    return merged


def _humanize_fit_reasons(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    replacements = {
        "vcp最佳适配": "收缩释放路径为最佳适配",
        "vcp适配": "收缩释放路径适配",
        "vcp弱适配": "收缩释放路径弱适配",
        "bollinger_bandit最佳适配": "波动扩张路径为最佳适配",
        "bollinger_bandit适配": "波动扩张路径适配",
        "bollinger_bandit弱适配": "波动扩张路径弱适配",
        "ma2560最佳适配": "趋势推进路径为最佳适配",
        "ma2560适配": "趋势推进路径适配",
        "ma2560弱适配": "趋势推进路径弱适配",
        "ef_count=": "E/F 共振数=",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _strategy_signal_total(strategy_counts: dict[str, Any], strategy_id: str) -> int:
    total = 0
    for key, value in (strategy_counts or {}).items():
        key_text = str(key)
        if key_text == strategy_id or key_text.startswith(f"{strategy_id}:"):
            try:
                total += int(value)
            except Exception:
                continue
    return total



def _hex_to_human_label(hex_str: str) -> str:
    raw = str(hex_str or "").strip()
    if not raw or raw == "-":
        return "-"
    mapping = _read_json(ROOT / "config/state_human_mapping.json") or {}
    name_map = {str(k).upper(): str(v) for k, v in mapping.get("hex_to_name", {}).items()}
    negative_name = str(mapping.get("negative_hex_to_name", "逆位"))
    emoji_map = {"天时": "🔥", "地利": "☀️", "人和": "🌤", "蓄力": "🌥", "冬眠": "🌧"}
    is_negative = raw.startswith("-")
    text = raw[1:] if is_negative else raw
    try:
        key = str(int(text, 16))
    except Exception:
        key = text.upper()
    name = name_map.get(key, "未知")
    if is_negative:
        return f"⚡{negative_name}{name}"
    emoji = emoji_map.get(name, "")
    return f"{emoji}{name}" if emoji else name


def _state_hex_to_name_clean(hex_str: str) -> str:
    """将 state hex 映射为中文状态名（无 emoji）。"""
    raw = str(hex_str or "").strip()
    if not raw or raw == "-":
        return "未知"
    mapping = _read_json(ROOT / "config/state_human_mapping.json") or {}
    name_map = {str(k).upper(): str(v) for k, v in mapping.get("hex_to_name", {}).items()}
    negative_name = str(mapping.get("negative_hex_to_name", "逆位"))
    is_negative = raw.startswith("-")
    text = raw[1:] if is_negative else raw
    try:
        key = str(int(text, 16))
    except Exception:
        key = text.upper()
    name = name_map.get(key, "未知")
    if is_negative:
        return f"{negative_name}{name}"
    return name


def _state_score_to_bar(score: Any) -> int:
    """将 state_score 映射为 0-100 的强度条。"""
    try:
        s = abs(int(score or 0))
    except Exception:
        return 0
    return min(100, max(0, int(s / 15 * 100)))


def _latest_existing_path(patterns: list[str]) -> Path | None:
    for pattern in patterns:
        path = _latest_path(pattern)
        if path and path.exists():
            return path
    return None


def _latest_nonempty_signal_path() -> Path | None:
    candidates = sorted(ROOT.glob("outputs/strategy_signals/strategy_signal_daily_*.json"), reverse=True)
    fallback: Path | None = None
    for path in candidates:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        rows = payload.get("rows", [])
        signal_count = payload.get("signal_count", 0)
        if fallback is None:
            fallback = path
        if rows or signal_count:
            return path
    return fallback


def _latest_nonempty_payload_context(
    pattern: str,
    rows_key: str = "rows",
    count_key: str | None = None,
) -> dict[str, Any]:
    candidates = sorted(ROOT.glob(pattern), reverse=True)
    latest_path = candidates[0] if candidates else None
    latest_payload = _read_json(latest_path) if latest_path else None
    effective_path: Path | None = None
    effective_payload: dict[str, Any] = {}

    for path in candidates:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        rows = payload.get(rows_key, [])
        has_rows = bool(rows)
        has_count = bool(payload.get(count_key, 0)) if count_key else False
        if effective_path is None:
            effective_path = path
            effective_payload = payload
        if has_rows or has_count:
            effective_path = path
            effective_payload = payload
            break

    latest_is_empty = False
    if isinstance(latest_payload, dict):
        latest_rows = latest_payload.get(rows_key, [])
        latest_has_count = bool(latest_payload.get(count_key, 0)) if count_key else False
        latest_is_empty = not latest_rows and not latest_has_count

    return {
        "path": effective_path,
        "payload": effective_payload if isinstance(effective_payload, dict) else {},
        "effective_date": effective_payload.get("date", "-") if isinstance(effective_payload, dict) else "-",
        "latest_date": latest_payload.get("date", "-") if isinstance(latest_payload, dict) else "-",
        "used_fallback": bool(effective_path and latest_path and effective_path != latest_path),
        "latest_is_empty": latest_is_empty,
        "effective_relpath": _rel(effective_path),
        "latest_relpath": _rel(latest_path),
    }


def _signal_payload_context() -> dict[str, Any]:
    return _latest_nonempty_payload_context(
        "outputs/strategy_signals/strategy_signal_daily_*.json",
        rows_key="rows",
        count_key="signal_count",
    )


def _state_triplet(row: dict[str, Any]) -> str:
    return "/".join(
        str(row.get(key, "") or "-")
        for key in ("mn1_state_hex", "w1_state_hex", "d1_state_hex")
    )


def _signal_interpretation(
    strategy_id: str,
    signal_name: str = "",
    lifecycle_stage: str = "",
    fit: str = "",
) -> str:
    signal = signal_name or ""
    if strategy_id == "vcp":
        if "突破" in signal:
            base = "当前更像收缩释放后的突破确认段。"
        elif "收缩" in signal:
            base = "当前仍在收缩蓄力阶段，重点是观察而不是抢先下判断。"
        else:
            base = "当前是 VCP 路径里的观察节点。"
    elif strategy_id == "ma2560":
        if "金叉" in signal:
            base = "当前更像趋势刚开始形成的切入节点。"
        elif "强" in signal or "持仓" in signal:
            base = "当前更像趋势延展持有段，重点是确认趋势质量。"
        else:
            base = "当前更像趋势对齐后的跟踪节点。"
    elif strategy_id == "bollinger_bandit":
        if "触发" in signal or "entry" in signal.lower():
            base = "当前更像带宽扩张后的趋势延展触发点。"
        else:
            base = "当前更像布林路径里的趋势观察节点。"
    else:
        base = "当前需要结合完整研究卡理解。"

    if fit:
        return f"{base} 当前环境为{fit}，生命周期={lifecycle_stage or '未标注'}。"
    return f"{base} 生命周期={lifecycle_stage or '未标注'}。"


def _latest_research_as_of_date() -> str:
    foundation_db = find_foundation_db()
    if not foundation_db:
        return str(date.today())
    try:
        con = duckdb.connect(str(foundation_db), read_only=True)
        latest = con.execute(
            "SELECT MAX(state_date) FROM d1_perspective_state"
        ).fetchone()[0]
    except Exception:
        latest = None
    finally:
        try:
            con.close()
        except Exception:
            pass
    return str(latest) if latest else str(date.today())


def _latest_fundamental_as_of_date() -> str:
    fundamental_db = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
    if not fundamental_db.exists():
        return str(date.today())
    con = None
    try:
        con = duckdb.connect(str(fundamental_db), read_only=True)
        candidates = []
        for table in ("ifind_industry_chain_profile", "ifind_excel_facts"):
            try:
                latest = con.execute(f"SELECT MAX(as_of_date) FROM {table}").fetchone()[0]
            except Exception:
                latest = None
            if latest:
                candidates.append(str(latest))
        return max(candidates) if candidates else str(date.today())
    except Exception:
        return str(date.today())
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass


def _load_company_profile(stock_code: str) -> dict[str, Any] | None:
    """Load company profile including industry and main business/products."""
    fundamental_db = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
    if not fundamental_db.exists():
        return None
    try:
        con = duckdb.connect(str(fundamental_db), read_only=True)
        try:
            row = con.execute(
                """
                SELECT stock_name, sw_l1, sw_l2, sw_l3,
                       main_business, main_product_types, main_product_names
                FROM ifind_industry_chain_profile
                WHERE stock_code = ? OR split_part(stock_code, '.', 1) = ?
                ORDER BY as_of_date DESC
                LIMIT 1
                """,
                [_canonical_stock_code(stock_code), _canonical_stock_code(stock_code).split('.')[0]],
            ).fetchone()
            if not row:
                return None
            return {
                'stock_name': row[0] or '',
                'sw_l1': row[1] or '',
                'sw_l2': row[2] or '',
                'sw_l3': row[3] or '',
                'main_business': row[4] or '',
                'main_product_types': row[5] or '',
                'main_product_names': row[6] or '',
            }
        finally:
            con.close()
    except Exception:
        return None


def _industry_rotation_data() -> dict[str, Any]:
    config = _read_json(ROOT / "config/industry_rotation_assets.json")
    signal_ctx = _signal_payload_context()
    latest_signals = signal_ctx["payload"]
    rows = latest_signals.get("rows", []) if isinstance(latest_signals, dict) else []
    date_str = latest_signals.get("date", "-") if isinstance(latest_signals, dict) else "-"

    industry_groups: dict[str, list[dict[str, Any]]] = {}
    for item in (config or {}).get("industry_etf_assets", []):
        sw_l1 = str(item.get("sw_l1", "未分类")).strip() or "未分类"
        industry_groups.setdefault(sw_l1, []).append(item)

    top_industries = []
    for industry, assets in sorted(industry_groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:8]:
        top_industries.append(
            {
                "industry": industry,
                "asset_count": len(assets),
                "sample": ", ".join(str(item.get("name", "")) for item in assets[:2] if item.get("name")),
            }
        )

    top_signals_by_code: dict[str, dict[str, Any]] = {}
    for row in rows:
        stock_code = str(row.get("stock_code", "")).strip()
        if not stock_code:
            continue
        if stock_code not in top_signals_by_code and len(top_signals_by_code) >= 6:
            continue
        strategy_id = row.get("strategy_id", "")
        definition = _strategy_definition(strategy_id)
        signal_read = _signal_interpretation(strategy_id, row.get("signal_name", ""))
        if stock_code not in top_signals_by_code:
            top_signals_by_code[stock_code] = {
                "stock_code": stock_code,
                "stock_name": row.get("stock_name", ""),
                "strategy_id": strategy_id,
                "strategy_label": "",
                "path_label": definition["path_label"],
                "strategy_what": definition["what"],
                "signal_name": row.get("signal_name", ""),
                "signal_read": "",
                "_strategy_labels": [],
                "_signal_reads": [],
            }
        current = top_signals_by_code[stock_code]
        if definition["label"] not in current["_strategy_labels"]:
            current["_strategy_labels"].append(definition["label"])
        if signal_read and signal_read not in current["_signal_reads"]:
            current["_signal_reads"].append(signal_read)

    top_signals = []
    for item in top_signals_by_code.values():
        item["strategy_label"] = " / ".join(item.pop("_strategy_labels", []))
        item["signal_read"] = "；".join(item.pop("_signal_reads", []))
        top_signals.append(item)

    return {
        "date": date_str,
        "industry_count": len(industry_groups),
        "signal_count": len(rows),
        "signal_meta": signal_ctx,
        "top_industries": top_industries,
        "top_signals": top_signals,
    }


def _latest_unified_snapshot_rows() -> tuple[dict[str, dict[str, Any]], str]:
    csv_path = _latest_path("outputs/unified_view/unified_daily_snapshot_*.csv")
    if not csv_path or not csv_path.exists():
        return {}, "-"
    import csv

    rows_by_code: dict[str, dict[str, Any]] = {}
    snapshot_date = "-"
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                code = str(row.get("stock_code", "")).strip().upper()
                if not code:
                    continue
                rows_by_code[code] = row
                snapshot_date = str(
                    row.get("snapshot_date")
                    or row.get("obs_date_x")
                    or row.get("obs_date_y")
                    or snapshot_date
                )
    except Exception:
        return {}, "-"
    return rows_by_code, snapshot_date


def _latest_industry_rotation_map() -> tuple[dict[str, dict[str, Any]], str]:
    payload = _read_json(_latest_path("outputs/industry_rotation/industry_rotation_*.json"))
    if not isinstance(payload, dict):
        return {}, "-"
    items = payload.get("top_industries", []) or []
    mapping = {
        str(item.get("sw_l1", "")).strip(): item
        for item in items
        if str(item.get("sw_l1", "")).strip()
    }
    return mapping, str(payload.get("date", "-"))


def _daily_brief() -> dict[str, Any]:
    daily_snapshot = _read_json(ROOT / "outputs/daily_snapshot.json") or {}
    market = daily_snapshot.get("market", {}) if isinstance(daily_snapshot, dict) else {}
    ef2_count = int(market.get("ef2_count", 0) or 0)
    ef2_pct = float(market.get("ef2_pct", 0) or 0)
    if ef2_pct > 15:
        env_label = "进攻环境"
    elif ef2_pct >= 8:
        env_label = "震荡选择环境"
    else:
        env_label = "防守等待环境"

    industry_payload = _read_json(_latest_path("outputs/industry_rotation/industry_rotation_*.json"))
    top_industries: list[dict[str, Any]] = []
    if isinstance(industry_payload, dict):
        for item in (industry_payload.get("top_industries") or [])[:5]:
            name = str(item.get("sw_l1") or "").strip()
            if not name:
                continue
            score = item.get("rotation_score")
            confirm_rate = item.get("moneyflow_confirm_rate")
            divergence_count = item.get("moneyflow_divergence_count")
            if isinstance(score, (int, float)) and score >= 70:
                resonance = "强势"
            elif isinstance(score, (int, float)) and score >= 50:
                resonance = "中性"
            else:
                resonance = "偏弱"
            if isinstance(confirm_rate, (int, float)) and confirm_rate >= 0.6:
                capital = "流入"
            elif isinstance(divergence_count, (int, float)) and divergence_count >= 1:
                capital = "流出"
            else:
                capital = "中性"
            top_industries.append({
                "name": name,
                "resonance": resonance,
                "capital": capital,
            })

    macro_prior = _read_json(ROOT / "outputs/macro_chain_prior" / "macro_chain_prior_latest.json")
    macro_bg = ""
    if isinstance(macro_prior, dict):
        macro_bg = str(macro_prior.get("quadrant", {}).get("name") or macro_prior.get("summary") or "").strip()

    top_names = [item["name"] for item in top_industries[:2]]
    industry_text = "、".join(top_names) if top_names else "当前暂无明确行业"
    conclusion = (
        f"今日 {ef2_count} 只股票 ef≥2，全市场 {ef2_pct:.1f}%——{env_label}。"
        f"先看 {industry_text}。"
    )
    return {
        "date": str(daily_snapshot.get("date") or date.today()),
        "ef2_count": ef2_count,
        "ef2_pct": ef2_pct,
        "total_stocks": int(market.get("stocks", 0) or 0),
        "env_label": env_label,
        "conclusion": conclusion,
        "top_industries": top_industries[:5],
        "macro_bg": macro_bg,
    }


def _dashboard_data() -> dict[str, Any]:
    """为 /dashboard 页面计算 L1 / L2 / L3 数据。"""
    # ── L1 ────────────────────────────────────────────────────
    daily_snapshot = _read_json(ROOT / "outputs/daily_snapshot.json") or {}
    market = daily_snapshot.get("market", {}) if isinstance(daily_snapshot, dict) else {}
    ef2_count = int(market.get("ef2_count", 0) or 0)

    # 对比上一日
    prev_ef2_count = ef2_count
    prev_snapshots = sorted(
        ROOT.glob("outputs/daily_snapshot/daily_snapshot_*.json"),
        reverse=True,
    )
    if len(prev_snapshots) >= 2:
        prev = _read_json(prev_snapshots[1])
        if isinstance(prev, dict):
            prev_ef2_count = int(prev.get("market", {}).get("ef2_count", 0) or 0)

    ef_change = ef2_count - prev_ef2_count

    # 策略信号总数（entry + structure）
    signals = _read_json(_latest_path("outputs/strategy_signals/strategy_signal_daily_*.json"))
    strategy_trigger_count = 0
    if isinstance(signals, dict):
        strategy_trigger_count = int(signals.get("signal_count", 0) or 0)

    updated_at = str(daily_snapshot.get("built") or daily_snapshot.get("date") or date.today())

    l1 = {
        "ef_change_count": abs(ef_change),
        "ef_change_direction": "up" if ef_change >= 0 else "down",
        "strategy_trigger_count": strategy_trigger_count,
        "updated_at": updated_at,
    }

    # ── L2 — 行业流 ───────────────────────────────────────────
    market_assets = _read_json(_latest_path("outputs/market_assets_state/market_assets_state_*.json"))
    industry_flow: list[dict[str, Any]] = []
    if isinstance(market_assets, list):
        industry_rows = [row for row in market_assets if row.get("asset_type") == "industry_etf"]
        industry_rows.sort(
            key=lambda row: (
                row.get("ef_count", -1),
                (row.get("mn1_state_score", 0) or 0)
                + (row.get("w1_state_score", 0) or 0)
                + (row.get("d1_state_score", 0) or 0),
            ),
            reverse=True,
        )
        for row in industry_rows[:6]:
            industry_flow.append({
                "name": str(row.get("sw_l1", row.get("name", ""))).strip() or "未知",
                "code": str(row.get("symbol", "")).strip() or "-",
                "states": {
                    "MN1": _state_hex_to_name_clean(row.get("mn1_state_hex")),
                    "W1": _state_hex_to_name_clean(row.get("w1_state_hex")),
                    "D1": _state_hex_to_name_clean(row.get("d1_state_hex")),
                    "MN1_label": _hex_to_human_label(row.get("mn1_state_hex")),
                    "W1_label": _hex_to_human_label(row.get("w1_state_hex")),
                    "D1_label": _hex_to_human_label(row.get("d1_state_hex")),
                },
                "bars": {
                    "MN1": _state_score_to_bar(row.get("mn1_state_score")),
                    "W1": _state_score_to_bar(row.get("w1_state_score")),
                    "D1": _state_score_to_bar(row.get("d1_state_score")),
                },
            })

    # ── L2 — 共振热点 ─────────────────────────────────────────
    stocks = daily_snapshot.get("stocks", []) if isinstance(daily_snapshot, dict) else []
    ef3_stocks = [s for s in stocks if s.get("ef") == 3][:5]
    ef2_stocks = [s for s in stocks if s.get("ef") == 2][:5]

    def _fmt_resonance(stock: dict[str, Any], tag: str) -> dict[str, str]:
        hex_vals = stock.get("hex", ["-", "-", "-"])
        tfs = []
        for idx, label in enumerate(["MN1", "W1", "D1"]):
            h = str(hex_vals[idx] if idx < len(hex_vals) else "-").strip().upper()
            if h in ("E", "F"):
                tfs.append(label)
        return {
            "stock": stock.get("c", "-"),
            "code": stock.get("c", "-"),
            "tag": tag,
            "timeframes": "+".join(tfs) if tfs else "-",
            "industry": "-",
        }

    l2_resonance = []
    for s in ef3_stocks:
        l2_resonance.append(_fmt_resonance(s, "突破"))
    for s in ef2_stocks:
        l2_resonance.append(_fmt_resonance(s, "观察"))

    # ── L3 — 异常列表（初始为空，待 AgentMemory 积累后填充）────
    l3_anomalies: list[dict[str, Any]] = []

    return {
        "l1": l1,
        "l2": {
            "industries": industry_flow,
            "resonance": l2_resonance,
        },
        "l3": {
            "anomalies": l3_anomalies,
        },
    }


def _boolish(value: Any) -> bool:
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y"}


def _floatish(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except Exception:
        return None


def _strategy_rows_for_stock(stock_code: str) -> list[dict[str, Any]]:
    latest_signals = _signal_payload_context()["payload"]
    rows = latest_signals.get("rows", []) if isinstance(latest_signals, dict) else []
    target = stock_code.strip().upper()
    fit_rank = {"最佳适配": 0, "待观察": 1, "弱适配": 2, "未标注": 3}
    selected = [
        row for row in rows
        if str(row.get("stock_code", "")).upper() == target
    ]
    selected.sort(key=lambda row: (
        fit_rank.get(str(row.get("strategy_environment_fit") or "未标注"), 99),
        -(row.get("ef_count") or 0),
    ))
    deduped: list[dict[str, Any]] = []
    seen_strategies: set[str] = set()
    for row in selected:
        strategy_id = row.get("strategy_id", "")
        if strategy_id in seen_strategies:
            continue
        seen_strategies.add(strategy_id)
        definition = _strategy_definition(strategy_id)
        deduped.append(
            {
                "strategy_id": strategy_id,
                "strategy_label": definition["label"],
                "signal_name": row.get("signal_name", ""),
                "fit": row.get("strategy_environment_fit", ""),
                "lifecycle_stage": row.get("lifecycle_stage", ""),
                "signal_read": _signal_interpretation(
                    strategy_id,
                    row.get("signal_name", ""),
                    row.get("lifecycle_stage", ""),
                    row.get("strategy_environment_fit", ""),
                ),
                "what": definition["what"],
                "how": definition["how"],
                "when": definition["when"],
                "avoid": definition["avoid"],
                "ef_count": row.get("ef_count"),
            }
        )
    return deduped


def _market_analysis_data() -> dict[str, Any]:
    market_phase_path = _latest_path("outputs/market_phase/market_phase_*.json")
    market_phase = _read_json(market_phase_path)
    macro_prior_path = ROOT / "outputs/macro_chain_prior" / "macro_chain_prior_latest.json"
    macro_prior = _read_json(macro_prior_path)
    daily_snapshot = _read_json(ROOT / "outputs/daily_snapshot.json")
    market_assets_path = _latest_path("outputs/market_assets_state/market_assets_state_*.json")
    market_assets = _read_json(market_assets_path)
    quant = _quant_summary()
    core_date = daily_snapshot.get("date", "-") if isinstance(daily_snapshot, dict) else "-"

    market_phase_freshness = _freshness_info(
        "市场阶段",
        market_phase.get("date", "-") if isinstance(market_phase, dict) else "-",
        core_date,
        0,
        "日更",
        "主判断",
        market_phase_path,
    )
    macro_freshness = _freshness_info(
        "宏观先验",
        macro_prior.get("date", "-") if isinstance(macro_prior, dict) else "-",
        core_date,
        10,
        "低频",
        "背景参考",
        macro_prior_path,
    )
    market_assets_source_date = "-"
    if isinstance(market_assets, list) and market_assets:
        market_assets_source_date = str(market_assets[0].get("state_date") or "-")
    market_assets_freshness = _freshness_info(
        "宽基与行业 ETF",
        market_assets_source_date,
        core_date,
        1,
        "日更",
        "主判断",
        market_assets_path,
    )

    broad_indices: list[dict[str, Any]] = []
    top_industries: list[dict[str, Any]] = []
    weak_industries: list[dict[str, Any]] = []
    if isinstance(market_assets, list) and market_assets_freshness["usable"]:
        broad_order = ["000300.SH", "000852.SH", "399006.SZ", "000905.SH", "399001.SZ", "000001.SH"]
        order_rank = {symbol: idx for idx, symbol in enumerate(broad_order)}
        broad_rows = [row for row in market_assets if row.get("asset_type") == "broad_index"]
        broad_rows.sort(key=lambda row: order_rank.get(str(row.get("symbol")), 999))
        broad_indices = [
            {
                "symbol": row.get("symbol", ""),
                "name": row.get("name", ""),
                "state_combo": _state_triplet(row),
                "ef_count": row.get("ef_count", 0),
                "d1_close": row.get("d1_close"),
            }
            for row in broad_rows
        ]

        industry_rows = [row for row in market_assets if row.get("asset_type") == "industry_etf"]
        industry_rows.sort(
            key=lambda row: (
                row.get("ef_count", -1),
                (row.get("mn1_state_score", 0) or 0)
                + (row.get("w1_state_score", 0) or 0)
                + (row.get("d1_state_score", 0) or 0),
            ),
            reverse=True,
        )
        top_industries = [
            {
                "industry": row.get("sw_l1", ""),
                "name": row.get("name", ""),
                "symbol": row.get("symbol", ""),
                "state_combo": _state_triplet(row),
                "ef_count": row.get("ef_count", 0),
            }
            for row in industry_rows[:6]
        ]
        weak_industries = [
            {
                "industry": row.get("sw_l1", ""),
                "name": row.get("name", ""),
                "symbol": row.get("symbol", ""),
                "state_combo": _state_triplet(row),
                "ef_count": row.get("ef_count", 0),
            }
            for row in list(reversed(industry_rows[-6:]))
        ]

    breadth = {
        "date": daily_snapshot.get("date", "-") if isinstance(daily_snapshot, dict) else "-",
        "total": daily_snapshot.get("market", {}).get("stocks", 0) if isinstance(daily_snapshot, dict) else 0,
        "ef2_count": daily_snapshot.get("market", {}).get("ef2_count", 0) if isinstance(daily_snapshot, dict) else 0,
        "ef2_pct": daily_snapshot.get("market", {}).get("ef2_pct", 0) if isinstance(daily_snapshot, dict) else 0,
        "avg_d1_score": daily_snapshot.get("market", {}).get("avg_d1_score", 0) if isinstance(daily_snapshot, dict) else 0,
        "ef_dist": daily_snapshot.get("ef_dist", {}) if isinstance(daily_snapshot, dict) else {},
    }

    phase_indicators = (
        market_phase.get("indicators", {})
        if isinstance(market_phase, dict) and market_phase_freshness["usable"]
        else {}
    )
    phase_history = (
        market_phase.get("phase_history", {})
        if isinstance(market_phase, dict) and market_phase_freshness["usable"]
        else {}
    )
    strategy_implications = (
        market_phase.get("strategy_implications", {})
        if isinstance(market_phase, dict) and market_phase_freshness["usable"]
        else {}
    )
    strategy_counts = quant["signals"]["strategy_counts"]
    strategy_climate = []
    for strategy_id in ("vcp", "ma2560", "bollinger_bandit"):
        definition = _strategy_definition(strategy_id)
        strategy_climate.append(
            {
                "strategy_id": strategy_id,
                "label": definition["label"],
                "path_label": definition["path_label"],
                "fit": strategy_implications.get(strategy_id, {}).get("fit", "未标注"),
                "factor": strategy_implications.get(strategy_id, {}).get("factor", "-"),
                "signal_count": _strategy_signal_total(strategy_counts, strategy_id),
                "what": definition["what"],
                "risk": definition["risk"],
            }
        )

    macro_scores = []
    macro_sub = (
        macro_prior.get("sub_scores", {})
        if isinstance(macro_prior, dict) and macro_freshness["usable"]
        else {}
    )
    for key, label in (
        ("growth", "增长"),
        ("liquidity", "流动性"),
        ("credit", "信用"),
        ("inflation", "通胀"),
    ):
        row = macro_sub.get(key, {})
        macro_scores.append(
            {
                "label": label,
                "score": row.get("score", "-"),
                "status": row.get("status", "-"),
                "evidence": (row.get("evidence") or ["-"])[0],
            }
        )

    strategy_rank = {"最佳适配": 3, "适配": 2, "弱适配": 1, "待观察": 0, "未标注": -1}
    climate_top = max(
        strategy_climate,
        key=lambda row: (
            strategy_rank.get(str(row.get("fit", "")), -1),
            float(row.get("factor") if row.get("factor") not in ("-", None) else -1),
        ),
        default=None,
    )
    climate_bottom = min(
        strategy_climate,
        key=lambda row: (
            strategy_rank.get(str(row.get("fit", "")), -1),
            float(row.get("factor") if row.get("factor") not in ("-", None) else -1),
        ),
        default=None,
    )

    focus_now = "先看市场 breadth 是否继续扩张，再优先跟踪当前更适配的周期走势。"
    avoid_now = "暂时不要把所有方向都当成机会，弱适配路径和弱行业先少看。"
    if climate_top:
        focus_now = (
            f"先看{climate_top['path_label']}，当前环境判定为{climate_top['fit']}，"
            f"样本信号 {climate_top['signal_count']} 条。"
        )
    if climate_bottom and climate_bottom != climate_top:
        avoid_now = (
            f"暂时少看{climate_bottom['path_label']}，当前环境判定为{climate_bottom['fit']}，"
            "当前不宜作为主视角。"
        )

    stance = "当前更适合做结构跟踪，不适合把局部转暖直接外推成全面进攻。"
    macro_score_value = (
        float(macro_prior.get("score_0_10", 0) or 0)
        if isinstance(macro_prior, dict) and macro_freshness["usable"]
        else 0.0
    )
    if breadth["ef2_pct"] >= 18 and macro_score_value >= 6:
        stance = "当前 breadth 与宏观先验同时偏强，可把重心放在顺风行业中的高质量周期走势。"
    elif breadth["ef2_pct"] >= 10 and climate_top and climate_top.get("fit") == "最佳适配":
        stance = "当前局部结构在改善，但仍应优先做选择题，只看更适配的周期走势和顺风行业。"
    elif breadth["ef2_pct"] < 8:
        stance = "当前 breadth 偏弱，先把市场当成筛选环境，不宜扩大关注面。"

    broad_summary = "宽基结构分化仍然存在，指数层没有形成全面共振。"
    if broad_indices:
        hs300 = next((row for row in broad_indices if row.get("symbol") == "000300.SH"), None)
        csi1000 = next((row for row in broad_indices if row.get("symbol") == "000852.SH"), None)
        cyb = next((row for row in broad_indices if row.get("symbol") == "399006.SZ"), None)
        parts = []
        if hs300:
            parts.append(f"沪深300={hs300['state_combo']}")
        if csi1000:
            parts.append(f"中证1000={csi1000['state_combo']}")
        if cyb:
            parts.append(f"创业板={cyb['state_combo']}")
        if parts:
            broad_summary = " / ".join(parts) + "，说明宽基并非同步强势。"

    industry_summary = "行业层先看少数顺风方向，不宜平均用力。"
    if top_industries and weak_industries:
        leaders = "、".join(row["industry"] for row in top_industries[:2] if row.get("industry"))
        laggards = "、".join(row["industry"] for row in weak_industries[:2] if row.get("industry"))
        if leaders or laggards:
            industry_summary = f"当前更强的方向集中在 {leaders}；相对更弱的方向在 {laggards}。"

    climate_summary = "策略层已经给出区别，不必三套策略一起推进。"
    if climate_top and climate_bottom and climate_top != climate_bottom:
        climate_summary = (
            f"{climate_top['path_label']} 当前最顺风（{climate_top['fit']}），"
            f"{climate_bottom['path_label']} 当前最弱（{climate_bottom['fit']}）。"
        )
    strategy_risk_banner = (
        "策略不是常量工具。先判断当前市场大节奏、行业是否有主线，再决定哪种策略值得提高权重；"
        "其余策略即使出现信号，也默认先降级为观察对象。"
    )
    freshness_rows = [market_phase_freshness, macro_freshness, market_assets_freshness]
    stale_rows = [row for row in freshness_rows if row["status"] in {"stale", "missing", "unknown"}]
    if stale_rows:
        strategy_risk_banner += " 当前存在过旧或缺失的外围数据，已自动弱化相关前台判断。"

    primary_stale_rows = [
        row for row in (market_phase_freshness, market_assets_freshness)
        if row["status"] in {"stale", "missing", "unknown"}
    ]
    if primary_stale_rows:
        presentation_title = f"当前可用数据截至 {core_date}"
        presentation_status = "主判断降级"
        presentation_summary = (
            "市场阶段或宽基/行业 ETF 数据没有与核心快照对齐，先按市场宽度和策略信号做保守判断。"
        )
        presentation_action = "先观察，不扩大关注面；等数据链路补齐后再下钻行业和个股。"
    elif breadth["ef2_pct"] >= 18 and top_industries:
        presentation_title = "局部顺风，优先精选"
        presentation_status = "数据可用"
        presentation_summary = stance
        presentation_action = focus_now
    elif breadth["ef2_pct"] >= 8:
        presentation_title = "结构跟踪，不急进攻"
        presentation_status = "数据可用"
        presentation_summary = stance
        presentation_action = focus_now
    else:
        presentation_title = "防守等待，缩小范围"
        presentation_status = "数据可用"
        presentation_summary = stance
        presentation_action = avoid_now

    return {
        "presentation": {
            "title": presentation_title,
            "status": presentation_status,
            "data_date": core_date,
            "page_date": str(date.today()),
            "summary": presentation_summary,
            "action": presentation_action,
            "avoid": avoid_now,
        },
        "phase": {
            "date": market_phase.get("date", "-") if isinstance(market_phase, dict) else "-",
            "label": market_phase.get("phase_label", "未知阶段") if isinstance(market_phase, dict) else "未知阶段",
            "summary": market_phase.get("phase_summary", "暂无阶段摘要") if isinstance(market_phase, dict) else "暂无阶段摘要",
            "market_phase": market_phase.get("market_phase", "") if isinstance(market_phase, dict) else "",
            "confidence": market_phase.get("confidence", "-") if isinstance(market_phase, dict) else "-",
            "pool_size": phase_indicators.get("pool_size", 0),
            "pool_change_rate_5d": phase_indicators.get("pool_change_rate_5d", 0),
            "pool_change_rate_20d": phase_indicators.get("pool_change_rate_20d", 0),
            "release_density": phase_indicators.get("contraction_release_density", 0),
            "industry_dispersion": phase_indicators.get("industry_dispersion", 0),
            "current_phase_days": phase_history.get("current_phase_days", 0),
            "previous_phase": phase_history.get("previous_phase", "-"),
        },
        "macro": {
            "date": macro_prior.get("date", "-") if isinstance(macro_prior, dict) else "-",
            "score": macro_prior.get("score_0_10", "-") if isinstance(macro_prior, dict) and macro_freshness["usable"] else "-",
            "confidence": macro_prior.get("confidence", "-") if isinstance(macro_prior, dict) and macro_freshness["usable"] else "-",
            "quadrant": (macro_prior.get("quadrant", {}) or {}).get("name", "-") if isinstance(macro_prior, dict) and macro_freshness["usable"] else "-",
            "strategy_adj": macro_prior.get("strategy_adj", {}) if isinstance(macro_prior, dict) and macro_freshness["usable"] else {},
            "scores": macro_scores,
        },
        "breadth": breadth,
        "broad_indices": broad_indices,
        "top_industries": top_industries,
        "weak_industries": weak_industries,
        "strategy_climate": strategy_climate,
        "signal_meta": quant["signals"]["meta"],
        "focus_now": focus_now,
        "avoid_now": avoid_now,
        "stance": stance,
        "broad_summary": broad_summary,
        "industry_summary": industry_summary,
        "climate_summary": climate_summary,
        "strategy_risk_banner": strategy_risk_banner,
        "freshness": freshness_rows,
        "stale_rows": stale_rows,
    }


# ── MECE 状态层 + 转移方向 + 启发式后验概率 ──────────────────────────

# 状态必须 MECE：同一只股票、同一时点，只能给一个当前状态
MECE_STATES = [
    "收缩蓄力",
    "刚突破待确认",
    "推进中段",
    "高位延展",
    "失效回落",
    "等待修复",
]

# 每个状态对应的转移候选库
TRANSITION_CANDIDATES: dict[str, list[str]] = {
    "收缩蓄力": ["收缩释放延续", "横盘再确认", "假突破回落"],
    "刚突破待确认": ["真突破延续", "假突破回落", "横盘再确认"],
    "推进中段": ["趋势推进接力", "板块承接增强", "资金背离转弱"],
    "高位延展": ["趋势推进接力", "资金背离转弱", "横盘再确认"],
    "失效回落": ["等待修复", "横盘再确认"],
    "等待修复": ["收缩蓄力", "横盘再确认"],
}


def _derive_current_state(item: dict[str, Any]) -> str:
    """从现有字段推导唯一的 MECE 当前状态。"""
    direction = str(item.get("sr_boundary_direction") or "").strip()
    sr_distance_pct = item.get("sr_distance_pct")
    fit = str(item.get("strategy_environment_fit") or "").strip()
    stage = str(item.get("lifecycle_stage") or "").strip()
    mf_divergence = bool(item.get("moneyflow_divergence"))
    d1_duration = item.get("d1_ef_duration")

    # 1. 失效回落 — 跌破支撑 或 弱适配 + 资金背离
    if direction == "below_support":
        return "失效回落"
    if fit == "弱适配" and mf_divergence:
        return "失效回落"

    # 2. 刚突破待确认 — 刚突破阻力且距离很近
    if direction == "above_resistance" and isinstance(sr_distance_pct, (int, float)):
        if sr_distance_pct <= 0.015:
            return "刚突破待确认"

    # 3. 推进中段 — 已突破但距离适中，或趋势推进阶段
    if direction == "above_resistance" and isinstance(sr_distance_pct, (int, float)):
        if sr_distance_pct <= 0.05:
            return "推进中段"

    # 4. 高位延展 — 已突破很远 或 D1 活跃持续 > 5天
    if direction == "above_resistance":
        if isinstance(sr_distance_pct, (int, float)) and sr_distance_pct > 0.05:
            return "高位延展"
    if isinstance(d1_duration, (int, float)) and d1_duration >= 5 and fit in ("最佳适配", "待观察"):
        return "高位延展"

    # 5. 收缩蓄力 — 收缩阶段 或 靠近支撑
    if stage in ("收缩蓄力", "蓄力") or "收缩" in stage:
        return "收缩蓄力"
    if direction in ("near_support", "at_support"):
        return "收缩蓄力"

    # 6. 等待修复 — 弱适配且无明确方向
    if fit == "弱适配":
        return "等待修复"

    # 兜底：看阶段
    if stage in ("突破确认", "释放"):
        return "推进中段"
    if stage in ("推进", "延展"):
        return "高位延展"

    return "收缩蓄力"


def _derive_transitions(state: str, item: dict[str, Any]) -> list[str]:
    """基于当前状态和数据特征，筛选并排序最相关的转移候选。"""
    candidates = list(TRANSITION_CANDIDATES.get(state, []))
    if not candidates:
        return ["横盘再确认"]

    direction = str(item.get("sr_boundary_direction") or "").strip()
    mf_confirmed = bool(item.get("moneyflow_confirmed"))
    mf_divergence = bool(item.get("moneyflow_divergence"))
    confirm_rate = item.get("industry_rotation_confirm_rate")
    sr_distance_pct = item.get("sr_distance_pct")
    d1_duration = item.get("d1_ef_duration")

    # 根据数据特征调整候选排序
    scored = []
    for cand in candidates:
        score = 0.0
        if cand in ("真突破延续", "趋势推进接力", "收缩释放延续", "板块承接增强"):
            if mf_confirmed:
                score += 0.3
            if isinstance(confirm_rate, (int, float)) and confirm_rate >= 0.7:
                score += 0.2
            if direction == "above_resistance":
                score += 0.15
        if cand in ("假突破回落", "资金背离转弱"):
            if mf_divergence:
                score += 0.35
            if isinstance(sr_distance_pct, (int, float)) and sr_distance_pct <= 0.01:
                score += 0.1
        if cand == "横盘再确认":
            score += 0.05  # 中性保底
        if cand == "等待修复" and state == "失效回落":
            score += 0.1
        scored.append((score, cand))

    scored.sort(reverse=True)
    return [cand for _, cand in scored]


def _compute_posterior_probs(
    state: str, transitions: list[str], item: dict[str, Any]
) -> dict[str, Any]:
    """启发式后验概率。不要求学术级精确，但和为 1 且可解释。"""
    if not transitions:
        return {"primary": ("横盘再确认", 1.0), "alternates": []}

    direction = str(item.get("sr_boundary_direction") or "").strip()
    sr_distance_pct = item.get("sr_distance_pct")
    mf_confirmed = bool(item.get("moneyflow_confirmed"))
    mf_divergence = bool(item.get("moneyflow_divergence"))
    confirm_rate = item.get("industry_rotation_confirm_rate")
    d1_duration = item.get("d1_ef_duration")
    rr_ratio = item.get("rr_ratio")
    confidence = item.get("confidence")
    fit = str(item.get("strategy_environment_fit") or "").strip()

    # 基础概率分配
    base_probs: dict[str, float] = {}
    n = len(transitions)
    for i, t in enumerate(transitions):
        base_probs[t] = max(0.05, 1.0 / n - i * 0.08)

    # 用数据特征调整
    adjustments: dict[str, float] = {t: 0.0 for t in transitions}

    # 资金流确认 → 延续类 +0.15
    if mf_confirmed:
        for t in transitions:
            if t in ("真突破延续", "趋势推进接力", "收缩释放延续"):
                adjustments[t] += 0.15
            elif t in ("假突破回落", "资金背离转弱"):
                adjustments[t] -= 0.08

    # 资金流背离 → 转弱类 +0.20
    if mf_divergence:
        for t in transitions:
            if t in ("假突破回落", "资金背离转弱"):
                adjustments[t] += 0.20
            elif t in ("真突破延续", "趋势推进接力", "收缩释放延续"):
                adjustments[t] -= 0.10

    # 板块确认率高 → 延续类 +0.10
    if isinstance(confirm_rate, (int, float)) and confirm_rate >= 0.75:
        for t in transitions:
            if t in ("真突破延续", "趋势推进接力", "收缩释放延续", "板块承接增强"):
                adjustments[t] += 0.10

    # 刚突破 → 假突破 +0.10，真突破 -0.05
    if direction == "above_resistance" and isinstance(sr_distance_pct, (int, float)) and sr_distance_pct <= 0.01:
        for t in transitions:
            if "假突破" in t:
                adjustments[t] += 0.10
            if "真突破" in t:
                adjustments[t] -= 0.05

    # D1 活跃久 → 延续 +0.08
    if isinstance(d1_duration, (int, float)) and d1_duration >= 5:
        for t in transitions:
            if t in ("趋势推进接力", "高位延展"):
                adjustments[t] += 0.08

    # D1 活跃短 → 假突破/脉冲 +0.08
    if isinstance(d1_duration, (int, float)) and d1_duration <= 2:
        for t in transitions:
            if t in ("假突破回落", "横盘再确认"):
                adjustments[t] += 0.08

    # 高 RR + 高置信度 → 延续 +0.08
    if isinstance(rr_ratio, (int, float)) and rr_ratio >= 10 and isinstance(confidence, (int, float)) and confidence >= 0.8:
        for t in transitions:
            if t in ("真突破延续", "趋势推进接力"):
                adjustments[t] += 0.08

    # 弱适配 → 转弱/修复类 +0.10
    if fit == "弱适配":
        for t in transitions:
            if t in ("资金背离转弱", "等待修复", "横盘再确认"):
                adjustments[t] += 0.10

    # 合并并归一化
    raw = {t: max(0.01, base_probs[t] + adjustments[t]) for t in transitions}
    total = sum(raw.values())
    normalized = {t: round(raw[t] / total, 2) for t in transitions}

    # 修正舍入误差，确保和为 1.0
    diff = 1.0 - sum(normalized.values())
    if transitions:
        normalized[transitions[0]] = round(normalized[transitions[0]] + diff, 2)

    sorted_items = sorted(normalized.items(), key=lambda x: x[1], reverse=True)
    primary = sorted_items[0]
    alternates = sorted_items[1:]

    return {
        "primary": primary,
        "alternates": alternates,
    }


def _execution_lane() -> dict[str, Any]:
    forward_ctx = _latest_nonempty_payload_context(
        "outputs/forward_observation/forward_observation_*.json",
        rows_key="rows",
        count_key="total",
    )
    forward = forward_ctx["payload"]
    rr = _read_json(_latest_path("outputs/reward_risk/reward_risk_*.json"))
    alert_rows = _alert_rows()
    forward_rows = forward.get("rows", [])[:6] if isinstance(forward, dict) else []
    unified_map, unified_date = _latest_unified_snapshot_rows()
    industry_rotation_map, industry_rotation_date = _latest_industry_rotation_map()
    core_date = forward.get("date", "-") if isinstance(forward, dict) else "-"
    unified_freshness = _freshness_info(
        "个股资金流与统一视图",
        unified_date,
        core_date,
        7,
        "周更/准日更",
        "辅助判断",
        _latest_path("outputs/unified_view/unified_daily_snapshot_*.csv"),
    )
    industry_rotation_freshness = _freshness_info(
        "行业承接",
        industry_rotation_date,
        core_date,
        7,
        "周更/低频",
        "辅助判断",
        _latest_path("outputs/industry_rotation/industry_rotation_*.json"),
    )
    buckets = {
        "priority": [],
        "observe": [],
        "queue": [],
    }
    rr_rows = rr.get("high_value_signals", []) if isinstance(rr, dict) else []
    high_rr_codes = {row.get("stock_code", "") for row in rr_rows}
    rr_map = {}
    for row in rr_rows:
        strategy_id = str(row.get("strategy_id") or row.get("strategy") or "").strip()
        definition = _strategy_definition(strategy_id)
        enriched_row = dict(row)
        enriched_row["strategy_label"] = definition["label"]
        enriched_row["path_label"] = definition["path_label"]
        rr_map[row.get("stock_code", "")] = enriched_row
    raw_items: list[dict[str, Any]] = []
    for row in forward_rows:
        rr_row = rr_map.get(row.get("stock_code", ""), {})
        unified_row = unified_map.get(str(row.get("stock_code", "")).upper(), {}) if unified_freshness["usable"] else {}
        sw_l1 = str(unified_row.get("sw_l1", "")).strip()
        industry_rotation = industry_rotation_map.get(sw_l1, {}) if sw_l1 and industry_rotation_freshness["usable"] else {}
        raw_items.append({
            "stock_code": row.get("stock_code", ""),
            "stock_name": row.get("stock_name", ""),
            "strategy_id": row.get("strategy_id", ""),
            "signal_name": row.get("signal_name", ""),
            "strategy_environment_fit": row.get("strategy_environment_fit", ""),
            "lifecycle_stage": row.get("lifecycle_stage", ""),
            "fit_reasons": row.get("fit_reasons", ""),
            "local_stat_note": row.get("local_stat_note", ""),
            "mn1_state": row.get("mn1_state", ""),
            "w1_state": row.get("w1_state", ""),
            "d1_state": row.get("d1_state", ""),
            "ef_count": row.get("ef_count"),
            "d1_ef_duration": row.get("d1_ef_duration"),
            "reference_close": row.get("reference_close"),
            "sr_boundary_direction": row.get("sr_boundary_direction", ""),
            "sr_distance_pct": row.get("sr_distance_pct"),
            "rr_ratio": rr_row.get("rr_ratio"),
            "confidence": rr_row.get("confidence"),
            "nearest_support": rr_row.get("nearest_support"),
            "nearest_resistance": rr_row.get("nearest_resistance"),
            "upside_pct": rr_row.get("upside_pct"),
            "downside_pct": rr_row.get("downside_pct"),
            "sw_l1": sw_l1,
            "sw_l2": str(unified_row.get("sw_l2", "")).strip(),
            "moneyflow_status": str(unified_row.get("moneyflow_status", "")).strip(),
            "moneyflow_confirmed": _boolish(unified_row.get("moneyflow_confirmed")),
            "moneyflow_divergence": _boolish(unified_row.get("moneyflow_divergence")),
            "moneyflow_score": _floatish(unified_row.get("moneyflow_score")),
            "active_net_5d": _floatish(unified_row.get("active_net_5d")),
            "big_order_net_5d": _floatish(unified_row.get("big_order_net_5d")),
            "latest_active_net": _floatish(unified_row.get("latest_active_net")),
            "latest_big_order_net": _floatish(unified_row.get("latest_big_order_net")),
            "moneyflow_coverage_ratio": _floatish(unified_row.get("moneyflow_coverage_ratio")),
            "industry_posterior_label": str(unified_row.get("industry_posterior_label", "")).strip(),
            "industry_etf_name": str(unified_row.get("industry_etf_name", "")).strip(),
            "industry_etf_state_combo": str(unified_row.get("industry_etf_state_combo", "")).strip(),
            "industry_etf_ef_count": _floatish(unified_row.get("industry_etf_ef_count")),
            "industry_chain_prior_score": _floatish(unified_row.get("industry_chain_prior_score")),
            "industry_rotation_confirm_rate": _floatish(industry_rotation.get("moneyflow_confirm_rate")),
            "industry_rotation_divergence_count": _floatish(industry_rotation.get("moneyflow_divergence_count")),
            "industry_rotation_score": _floatish(industry_rotation.get("rotation_score")),
        })

    fit_rank = {"最佳适配": 0, "待观察": 1, "弱适配": 2}
    grouped_items: dict[str, dict[str, Any]] = {}
    for item in raw_items:
        stock_code = str(item.get("stock_code") or "").strip()
        if not stock_code:
            continue
        existing = grouped_items.get(stock_code)
        if existing is None:
            definition = _strategy_definition(item.get("strategy_id", ""))
            merged = dict(item)
            merged["strategy_ids"] = [item.get("strategy_id", "")]
            merged["signal_names"] = [item.get("signal_name", "")]
            merged["path_labels"] = [definition["path_label"]]
            merged["fit_reason_list"] = [_humanize_fit_reasons(item.get("fit_reasons"))]
            merged["local_stat_notes"] = [str(item.get("local_stat_note", "")).strip()]
            merged["strategy_environment_fits"] = [item.get("strategy_environment_fit", "")]
            grouped_items[stock_code] = merged
            continue

        current_rank = fit_rank.get(str(item.get("strategy_environment_fit") or ""), 99)
        existing_rank = fit_rank.get(str(existing.get("strategy_environment_fit") or ""), 99)
        if current_rank < existing_rank:
            preserved = {
                "strategy_ids": existing.get("strategy_ids", []),
                "signal_names": existing.get("signal_names", []),
                "path_labels": existing.get("path_labels", []),
                "fit_reason_list": existing.get("fit_reason_list", []),
                "local_stat_notes": existing.get("local_stat_notes", []),
                "strategy_environment_fits": existing.get("strategy_environment_fits", []),
            }
            existing.update(item)
            for key, value in preserved.items():
                existing[key] = value

        definition = _strategy_definition(item.get("strategy_id", ""))
        for key, value in (
            ("strategy_ids", item.get("strategy_id", "")),
            ("signal_names", item.get("signal_name", "")),
            ("path_labels", definition["path_label"]),
            ("fit_reason_list", _humanize_fit_reasons(item.get("fit_reasons"))),
            ("local_stat_notes", str(item.get("local_stat_note", "")).strip()),
            ("strategy_environment_fits", item.get("strategy_environment_fit", "")),
        ):
            if value and value not in existing[key]:
                existing[key].append(value)

    for item in grouped_items.values():
        path_labels = [label for label in item.get("path_labels", []) if label]
        signal_names = [label for label in item.get("signal_names", []) if label]
        fit_reasons = [label for label in item.get("fit_reason_list", []) if label]
        stat_notes = [label for label in item.get("local_stat_notes", []) if label]
        fits = [f for f in item.get("strategy_environment_fits", []) if f]
        # 修复2：多策略命中 → 单选 primary_path
        primary_path = ""
        alternate_transitions: list[dict[str, str]] = []
        if fits:
            best_fit = min(fits, key=lambda f: fit_rank.get(f, 99))
            primary_path = best_fit
            for f in fits:
                if f != best_fit:
                    alternate_transitions.append({"path_label": f, "fit_level": f})
        item["primary_path"] = primary_path
        item["alternate_transitions"] = alternate_transitions
        if path_labels:
            # 只保留 primary_path 对应的路径标签
            primary_idx = fits.index(primary_path) if primary_path in fits else 0
            item["path_label"] = path_labels[primary_idx] if primary_idx < len(path_labels) else path_labels[0]
        if signal_names:
            item["signal_name"] = " / ".join(signal_names)
        if fit_reasons:
            if len(fit_reasons) == 1:
                item["fit_reasons"] = fit_reasons[0]
            else:
                item["fit_reasons"] = "同一对象同时命中多条路径：" + "；".join(fit_reasons)
        if stat_notes:
            item["local_stat_note"] = "；".join(dict.fromkeys(stat_notes))

    def enrich(item: dict[str, Any], bucket: str) -> dict[str, Any]:
        # MECE 状态推导 + 转移方向 + 启发式后验概率
        current_state = _derive_current_state(item)
        transitions = _derive_transitions(current_state, item)
        posterior = _compute_posterior_probs(current_state, transitions, item)

        item["current_state"] = current_state
        item["primary_transition"] = posterior["primary"][0]
        item["primary_transition_prob"] = posterior["primary"][1]
        item["alternate_transitions"] = posterior["alternates"]
        item["posterior_probs"] = posterior

        definition = _strategy_definition(item.get("strategy_id", ""))
        fit = item.get("strategy_environment_fit") or "未标注"
        stage = item.get("lifecycle_stage") or "未标注"
        state_triplet = "/".join(
            str(item.get(key) or "-")
            for key in ("mn1_state", "w1_state", "d1_state")
        )
        ef_count = item.get("ef_count")
        state_reason = f"State {state_triplet}"
        if ef_count is not None:
            state_reason += f"，E/F 共振数={ef_count}"
        d1_duration = item.get("d1_ef_duration")
        if d1_duration:
            state_reason += f"，D1 活跃已持续 {d1_duration} 天"
        strategy_reason = item.get("fit_reasons") or f"{fit}，生命周期={stage}"
        rr_reason = item.get("local_stat_note") or "当前没有额外的历史统计说明。"
        support_hint = "D1 支撑位暂缺，不能据此判断回踩质量。"
        nearest_support = item.get("nearest_support")
        reference_close = item.get("reference_close")
        if isinstance(nearest_support, (int, float)) and nearest_support > 0:
            if isinstance(reference_close, (int, float)) and reference_close > 0:
                dist = (reference_close / nearest_support - 1) * 100
                support_hint = f"D1 支撑位约 {nearest_support:.2f}，现价距支撑约 {dist:.1f}% 。"
            else:
                support_hint = f"D1 支撑位约 {nearest_support:.2f}。"
        fake_breakout_risk = "假突破风险未明。"
        direction = str(item.get("sr_boundary_direction") or "")
        sr_distance_pct = item.get("sr_distance_pct")
        if direction == "above_resistance" and isinstance(sr_distance_pct, (int, float)):
            if sr_distance_pct <= 0.01:
                fake_breakout_risk = "刚突破不久，仍要看 1-3 天内能否站稳，假突破风险较高。"
            elif sr_distance_pct <= 0.03:
                fake_breakout_risk = "已突破但离关键边界不远，更适合观察回踩确认。"
            else:
                fake_breakout_risk = "已明显远离突破边界，赔率开始下降，不宜把它当成早期突破。"
        elif direction == "below_support":
            fake_breakout_risk = "已落到支撑下方，优先按失效或降级处理。"

        moneyflow_confirmation = "资金流暂无有效覆盖，只做结构观察。"
        moneyflow_status = item.get("moneyflow_status") or ""
        moneyflow_score = item.get("moneyflow_score")
        mf_cov = item.get("moneyflow_coverage_ratio")
        if isinstance(mf_cov, (int, float)) and mf_cov < 0.6:
            moneyflow_confirmation = "资金流覆盖不足，当前不把资金方向纳入前台判断。"
        elif item.get("moneyflow_divergence"):
            moneyflow_confirmation = "资金流背离：状态偏强，但近 5 日主力/大单未同向确认，需复核。"
        elif item.get("moneyflow_confirmed"):
            if isinstance(moneyflow_score, (int, float)):
                moneyflow_confirmation = f"资金流确认：近 5 日主力/大单同向支持，资金流分={moneyflow_score:.1f}。"
            else:
                moneyflow_confirmation = "资金流确认：近 5 日主力/大单同向支持。"
        elif moneyflow_status:
            moneyflow_confirmation = f"资金状态={moneyflow_status}，当前只作排序参考，不单独裁决。"

        moneyflow_divergence = "暂无明显资金背离。"
        if item.get("moneyflow_divergence"):
            moneyflow_divergence = "高位分歧风险：价格在推进，但主力/大单净流向没有同步跟上。"
        elif direction == "above_resistance" and isinstance(item.get("latest_active_net"), (int, float)) and item["latest_active_net"] < 0:
            moneyflow_divergence = "突破后最新主力净流向转负，先防守假突破或冲高回落。"

        sector_followthrough = "板块承接暂缺，只能看个股自身结构。"
        industry_name = item.get("sw_l1") or "所属板块"
        confirm_rate = item.get("industry_rotation_confirm_rate")
        rotation_score = item.get("industry_rotation_score")
        divergence_count = item.get("industry_rotation_divergence_count")
        if isinstance(confirm_rate, (int, float)):
            if confirm_rate >= 0.75:
                sector_followthrough = f"{industry_name} 承接较强，行业资金确认率 {confirm_rate:.0%}。"
            elif confirm_rate >= 0.6:
                sector_followthrough = f"{industry_name} 有一定承接，行业资金确认率 {confirm_rate:.0%}。"
            else:
                sector_followthrough = f"{industry_name} 承接偏弱，行业资金确认率仅 {confirm_rate:.0%}。"
            if isinstance(divergence_count, (int, float)) and divergence_count >= 1:
                sector_followthrough += f" 行业内已有 {int(divergence_count)} 个分歧样本。"
            if isinstance(rotation_score, (int, float)) and rotation_score >= 80:
                sector_followthrough += " 属于当前更强的顺风方向。"

        persistence_view = "持续性暂无法前台提高判断。"
        all_three_duration = item.get("d1_ef_duration")
        if direction == "above_resistance" and isinstance(sr_distance_pct, (int, float)) and sr_distance_pct <= 0.01:
            persistence_view = "更像刚突破待确认，持续性要看未来 1-3 天是否站稳。"
        elif isinstance(all_three_duration, (int, float)) and all_three_duration >= 5:
            persistence_view = f"D1 活跃已持续 {int(all_three_duration)} 天，若板块继续承接，持续性相对更好。"
        elif isinstance(all_three_duration, (int, float)) and all_three_duration <= 2:
            persistence_view = "刚进入活跃段，持续性未充分展开，先防止单日脉冲。"

        breakout_view = "当前先按结构观察，不轻易定义为真突破。"
        if direction == "above_resistance":
            if item.get("moneyflow_confirmed") and isinstance(confirm_rate, (int, float)) and confirm_rate >= 0.75:
                breakout_view = "更像真突破候选：位置已越过阻力，资金流与板块承接同步确认。"
            elif item.get("moneyflow_divergence"):
                breakout_view = "更像假突破复核样本：价格越过阻力，但资金没有同步确认。"
            elif isinstance(sr_distance_pct, (int, float)) and sr_distance_pct <= 0.01:
                breakout_view = "仍是突破观察样本：刚越过阻力，需等 1-3 天确认真假。"
            else:
                breakout_view = "已越过阻力，但更像中段推进，不应再按早期突破处理。"

        rr_ratio = item.get("rr_ratio")
        confidence = item.get("confidence")
        allocation_tier = "仅观察"
        phase_position = "等待确认"
        # 分桶逻辑切换为 current_state 驱动
        if bucket == "priority":
            phase_position = "顺风跟踪"
            allocation_tier = "标准跟踪"
            if isinstance(rr_ratio, (int, float)) and rr_ratio >= 10 and isinstance(confidence, (int, float)) and confidence >= 0.8:
                allocation_tier = "重点关注"
            elif current_state == "刚突破待确认":
                allocation_tier = "小额试错"
                phase_position = "刚突破待确认"
        elif bucket == "observe":
            allocation_tier = "小额试错"
            phase_position = "等待确认"
        elif bucket == "queue":
            allocation_tier = "仅观察"
            phase_position = "暂不推进"
        if bucket == "priority":
            reason = "当前值得先处理，但先确认结构是否真支持执行。"
            action = "先打开研究卡确认证据完整度，再决定是否进入重点跟踪。"
        elif bucket == "observe":
            reason = "当前更适合观察节奏，不急于推进到执行。"
            action = "优先看 State 节奏和适配度是否改善。"
        else:
            reason = "已进入常规处理队列，但优先级暂不高。"
            action = "快速过一遍研究卡，确认是否需要上调或暂缓。"
        item["strategy_label"] = definition["label"]
        item["path_label"] = item.get("path_label") or definition["path_label"]
        item["strategy_what"] = definition["what"]
        item["signal_read"] = _signal_interpretation(
            item.get("strategy_id", ""),
            item.get("signal_name", ""),
            stage,
            fit,
        )
        item["state_reason"] = state_reason
        item["strategy_reason"] = strategy_reason
        item["rr_reason"] = rr_reason
        item["support_hint"] = support_hint
        item["fake_breakout_risk"] = fake_breakout_risk
        item["moneyflow_confirmation"] = moneyflow_confirmation
        item["moneyflow_divergence_text"] = moneyflow_divergence
        item["sector_followthrough"] = sector_followthrough
        item["breakout_view"] = breakout_view
        item["persistence_view"] = persistence_view
        # 升级 A：退出参考信号
        sid = item.get("strategy_id", "")
        nearest_support = item.get("nearest_support")
        if sid == "vcp":
            exit_ref = "VCP 前低。若跌破最近一次收缩低点则结构失效。"
        elif sid == "ma2560":
            exit_ref = "MA25。若日线收盘 < MA25 且 MA25 走平，趋势破坏。"
        elif sid == "bollinger_bandit":
            exit_ref = "递减均线。持有越久防守线越灵敏，当前等效约 MA20。"
        else:
            support_val = f"{nearest_support:.2f}" if nearest_support is not None else "未知"
            exit_ref = f"D1 支撑位约 {support_val}。若跌破则优先降级到观察队列。"
        item["exit_reference"] = exit_ref
        item["phase_position"] = phase_position
        item["allocation_tier"] = allocation_tier
        item["queue_reason"] = f"{fit} / {stage}。{reason}"
        item["next_action"] = action
        mn1_label = _hex_to_human_label(item.get("mn1_state") or "")
        w1_label = _hex_to_human_label(item.get("w1_state") or "")
        d1_label = _hex_to_human_label(item.get("d1_state") or "")
        ef_count = item.get("ef_count")
        resonance_label = "❄️无共振"
        if isinstance(ef_count, int):
            if ef_count == 3:
                resonance_label = "🔥天时共振"
            elif ef_count == 2:
                resonance_label = "☀️地利共振"
            elif ef_count == 1:
                resonance_label = "🌤单一周期"
            elif ef_count == 0 and (str(item.get("mn1_state") or "").startswith("-") or str(item.get("w1_state") or "").startswith("-") or str(item.get("d1_state") or "").startswith("-")):
                resonance_label = "⚡逆位共振"
        item["resonance_label"] = resonance_label
        item["mn1_label"] = mn1_label
        item["w1_label"] = w1_label
        item["d1_label"] = d1_label
        item["current_state_label"] = resonance_label
        # 修复4：构建合一的 transition_note
        transition_notes = {
            "fresh_breakout": "价格已越过阻力但仅刚站稳。等待 1-3 天内资金流是否确认方向。若资金流出现背离，优先按假突破复核。",
            "extension": "结构+资金双重确认。当前更适合跟踪是否延续，不宜把它当早期突破做高赔率。",
            "charging": "结构处于收缩蓄力阶段。当前不是突破点，适合观察结构和波动率是否继续收窄。",
            "trending": "多周期共振已确立，结构背景较稳。持续性取决于板块承接是否继续同向。",
            "broken": "当前不支持按执行优先级处理。等到价格回到关键支撑上方后再重新评估。",
            "none": "暂无明确状态匹配，建议先观察结构变化。",
        }
        return item

    # 分桶逻辑：基于 MECE 当前状态
    state_bucket_map = {
        "刚突破待确认": "priority",
        "推进中段": "priority",
        "高位延展": "priority",
        "收缩蓄力": "observe",
        "失效回落": "queue",
        "等待修复": "queue",
    }
    for item in grouped_items.values():
        # 先计算状态，用于分桶
        state = _derive_current_state(item)
        item["current_state"] = state
        bucket = state_bucket_map.get(state, "queue")
        buckets[bucket].append(item)

    # 桶内排序：priority 按主转移概率降序，其余保持原序
    for bucket_name in buckets:
        if bucket_name == "priority":
            buckets[bucket_name].sort(
                key=lambda it: it.get("primary_transition_prob", 0),
                reverse=True,
            )

    for bucket_name in buckets:
        buckets[bucket_name] = [enrich(item, bucket_name) for item in buckets[bucket_name]]

    lane_hint = "今天先处理优先队列，其他对象暂不必同步深挖。"
    if not buckets["priority"] and buckets["observe"]:
        lane_hint = "当前没有强执行对象，先观察节奏变化。"
    elif not any(buckets.values()):
        lane_hint = "当前没有待处理执行对象，可以把注意力放回方向和研究。"

    return {
        "pending": forward.get("pending", 0) if isinstance(forward, dict) else 0,
        "total": forward.get("total", 0) if isinstance(forward, dict) else 0,
        "meta": forward_ctx,
        "fit_distribution": forward.get("sample_progress", {}).get("fit_distribution", {}) if isinstance(forward, dict) else {},
        "high_rr": list(rr_map.values())[:5],
        "recent_queue": buckets["queue"][:6],
        "priority_queue": buckets["priority"][:6],
        "observe_queue": buckets["observe"][:6],
        "recent_alerts": alert_rows[:8],
        "lane_hint": lane_hint,
        "unified_date": unified_date,
        "industry_rotation_date": industry_rotation_date,
        "freshness": [unified_freshness, industry_rotation_freshness],
        "stale_rows": [row for row in (unified_freshness, industry_rotation_freshness) if row["status"] in {"stale", "missing", "unknown"}],
    }


def _research_lane(default_code: str) -> dict[str, Any]:
    quant = _quant_summary()
    signals = quant["signals"]["rows"]
    lead = signals[0] if signals else {}
    lead_strategy_id = lead.get("strategy_id", "")
    lead_definition = _strategy_definition(lead_strategy_id)
    fit_rank = {"最佳适配": 0, "待观察": 1, "弱适配": 2, "未标注": 3}
    ordered = sorted(
        [row for row in signals if row.get("stock_code")],
        key=lambda row: (
            fit_rank.get(str(row.get("strategy_environment_fit") or "未标注"), 99),
            -(row.get("ef_count") or 0),
            str(row.get("stock_code") or ""),
        ),
    )
    seen_codes: set[str] = set()
    recent_research: list[dict[str, Any]] = []
    for row in ordered:
        code = str(row.get("stock_code", "")).strip()
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        strategy_id = row.get("strategy_id", "")
        recent_research.append(
            {
                "stock_code": code,
                "stock_name": row.get("stock_name", ""),
                "strategy_id": strategy_id,
                "strategy_label": _strategy_definition(strategy_id).get("label", strategy_id),
                "path_label": _strategy_definition(strategy_id).get("path_label", strategy_id),
                "signal_name": row.get("signal_name", ""),
                "fit": row.get("strategy_environment_fit", ""),
                "signal_read": _signal_interpretation(
                    strategy_id,
                    row.get("signal_name", ""),
                    row.get("lifecycle_stage", ""),
                    row.get("strategy_environment_fit", ""),
                ),
            }
        )
        if len(recent_research) >= 6:
            break

    return {
        "lead_code": lead.get("stock_code", default_code),
        "lead_name": lead.get("stock_name", ""),
        "lead_strategy": lead_strategy_id,
        "lead_strategy_label": lead_definition["label"],
        "lead_signal": lead.get("signal_name", ""),
        "recent_research": recent_research,
    }


def _research_page_context(stock_code: str, render_profile: str) -> dict[str, Any]:
    cards = _render_cards(stock_code, render_profile)
    lead = _research_lane(stock_code)
    strategy_rows = _strategy_rows_for_stock(stock_code)
    unified_map, unified_date = _latest_unified_snapshot_rows()
    industry_rotation_map, industry_rotation_date = _latest_industry_rotation_map()
    core_date = cards.get("as_of_date", "-")
    unified_freshness = _freshness_info(
        "个股资金流与统一视图",
        unified_date,
        core_date,
        7,
        "周更/准日更",
        "辅助判断",
        _latest_path("outputs/unified_view/unified_daily_snapshot_*.csv"),
    )
    industry_rotation_freshness = _freshness_info(
        "行业承接",
        industry_rotation_date,
        core_date,
        7,
        "周更/低频",
        "辅助判断",
        _latest_path("outputs/industry_rotation/industry_rotation_*.json"),
    )
    unified_row = unified_map.get(stock_code.strip().upper(), {}) if unified_freshness["usable"] else {}
    payload: dict[str, Any] = {}
    if cards.get("payload"):
        try:
            payload = json.loads(cards["payload"])
        except Exception:
            payload = {}
    state_core = payload.get("state_core", {}) if isinstance(payload, dict) else {}
    mn1_hex = str(state_core.get("mn1_state_hex") or "")
    w1_hex = str(state_core.get("w1_state_hex") or "")
    d1_hex = str(state_core.get("d1_state_hex") or "")
    ef_count = state_core.get("ef_count")
    resonance_label = "❄️无共振"
    if isinstance(ef_count, int):
        if ef_count == 3:
            resonance_label = "🔥天时共振"
        elif ef_count == 2:
            resonance_label = "☀️地利共振"
        elif ef_count == 1:
            resonance_label = "🌤单一周期"
        elif ef_count == 0 and (mn1_hex.startswith("-") or w1_hex.startswith("-") or d1_hex.startswith("-")):
            resonance_label = "⚡逆位共振"
    state_prior_view = str(state_core.get("state_prior_view") or "").strip()
    summary = {
        "conclusion": "当前更适合研究跟踪，不直接外推为执行结论。",
        "why": "先看 State 结构、策略适配和证据完整度，再决定是否进入执行队列。",
        "next_step": "优先核对 Deep Card 的结构解读与 Evidence Card 的来源一致性。",
    }
    quick_text = cards.get("quick", "")
    if "State：" in quick_text:
        summary["conclusion"] = "当前已有结构判断，可以先用 Quick Card 收敛方向。"
    if "弱适配" in quick_text:
        summary["next_step"] = "暂时不急于执行，先观察适配度是否改善。"
    elif "最佳适配" in quick_text or "适配" in quick_text:
        summary["next_step"] = "可继续下钻 Evidence Card，确认是否进入执行队列。"

    completeness = payload.get("completeness", {}) if isinstance(payload, dict) else {}
    overlay = payload.get("strategy_fit_overlay", {}) if isinstance(payload, dict) else {}
    overlay_strategy_id = overlay.get("fit_strategy", "") if isinstance(overlay, dict) else ""
    overlay_definition = _strategy_definition(overlay_strategy_id)
    required_score = completeness.get("required_modules_score")
    optional_score = completeness.get("optional_modules_score")
    state_core_status = completeness.get("state_core", "missing")
    valuation_status = completeness.get("valuation_reference", "missing")
    overall = completeness.get("overall", "missing")
    missing_modules = [
        name
        for name in (
            "company_profile",
            "financial_trend",
            "industry_state",
            "valuation_reference",
            "market_views",
        )
        if completeness.get(name) == "missing"
    ]
    coverage = [
        {"label": "整体充分度", "value": overall},
        {"label": "State 核心", "value": state_core_status},
        {"label": "估值参考", "value": valuation_status},
        {
            "label": "核心模块分",
            "value": f"{required_score:.2f}" if isinstance(required_score, (int, float)) else "-",
        },
        {
            "label": "扩展模块分",
            "value": f"{optional_score:.2f}" if isinstance(optional_score, (int, float)) else "-",
        },
    ]
    not_needed_now = "当前先不必深挖 market views 或长篇结论，优先看结构与证据完整度。"
    if overall == "sufficient":
        not_needed_now = "当前证据相对完整，先看 Decision Frame，再决定是否继续展开 Deep Card。"
    elif overall == "missing":
        not_needed_now = "当前基础资料缺口较大，先把它当作结构观察对象，而不是深度研究对象。"
    if cards.get("error"):
        summary = {
            "conclusion": "当前研究页已降级展示，先看结构和策略，不把缺失模块当结论。",
            "why": "基础资料或格式化链路暂时不可用，但页面仍保留研究入口和执行语境。",
            "next_step": "先处理可用的 State / 策略视图；等基础资料恢复后再看完整研究卡。",
        }
        coverage = [
            {"label": "整体充分度", "value": "降级"},
            {"label": "页面状态", "value": "Fallback"},
        ]
        missing_modules = ["company_profile", "financial_trend", "formatter_output"]
        not_needed_now = "当前不必等待完整卡片，先用结构与策略视图维持跟踪。"
    ai_summary = {
        "conclusion": summary["conclusion"],
        "multi_cycle_view": "先看 MN1/W1/D1 是否互相支撑。若大周期并未同步，只把当前对象当成局部结构样本，不直接外推成全面进攻机会。",
        "single_cycle_position": "当前优先判断它是刚突破、推进中段、高位延展，还是仍在等待确认。同样强结构，不同位置的概率和盈亏比完全不同。",
        "next_step": summary["next_step"],
    }
    sw_l1 = str(unified_row.get("sw_l1", "")).strip()
    industry_rotation = industry_rotation_map.get(sw_l1, {}) if sw_l1 and industry_rotation_freshness["usable"] else {}
    moneyflow_status = str(unified_row.get("moneyflow_status", "")).strip()
    moneyflow_confirmed = _boolish(unified_row.get("moneyflow_confirmed"))
    moneyflow_divergence = _boolish(unified_row.get("moneyflow_divergence"))
    moneyflow_score = _floatish(unified_row.get("moneyflow_score"))
    moneyflow_coverage_ratio = _floatish(unified_row.get("moneyflow_coverage_ratio"))
    latest_active_net = _floatish(unified_row.get("latest_active_net"))
    sr_direction = str(unified_row.get("sr_boundary_direction", "")).strip()
    sr_distance_pct = _floatish(unified_row.get("sr_distance_pct"))
    d1_duration = _floatish(unified_row.get("d1_ef_duration"))
    confirm_rate = _floatish(industry_rotation.get("moneyflow_confirm_rate"))
    divergence_count = _floatish(industry_rotation.get("moneyflow_divergence_count"))
    rotation_score = _floatish(industry_rotation.get("rotation_score"))

    resonance_summary = {
        "moneyflow_confirmation": "资金流暂无有效覆盖，只做结构观察。",
        "moneyflow_divergence": "暂无明显资金背离。",
        "sector_followthrough": "板块承接暂缺，只能看个股自身结构。",
        "breakout_view": "当前先按结构观察，不轻易定义为真突破。",
        "persistence_view": "持续性暂无法前台提高判断。",
        "sources": f"个股资金流：{unified_date}；行业承接：{industry_rotation_date}",
    }
    if isinstance(moneyflow_coverage_ratio, (int, float)) and moneyflow_coverage_ratio < 0.6:
        resonance_summary["moneyflow_confirmation"] = "资金流覆盖不足，当前不把资金方向纳入前台判断。"
    elif moneyflow_divergence:
        resonance_summary["moneyflow_confirmation"] = "资金流背离：状态偏强，但近 5 日主力/大单未同向确认，需复核。"
    elif moneyflow_confirmed:
        if isinstance(moneyflow_score, (int, float)):
            resonance_summary["moneyflow_confirmation"] = f"资金流确认：近 5 日主力/大单同向支持，资金流分={moneyflow_score:.1f}。"
        else:
            resonance_summary["moneyflow_confirmation"] = "资金流确认：近 5 日主力/大单同向支持。"
    elif moneyflow_status:
        resonance_summary["moneyflow_confirmation"] = f"资金状态={moneyflow_status}，当前只作排序参考，不单独裁决。"

    if moneyflow_divergence:
        resonance_summary["moneyflow_divergence"] = "高位分歧风险：价格在推进，但主力/大单净流向没有同步跟上。"
    elif sr_direction == "above_resistance" and isinstance(latest_active_net, (int, float)) and latest_active_net < 0:
        resonance_summary["moneyflow_divergence"] = "突破后最新主力净流向转负，先防守假突破或冲高回落。"

    if sw_l1 and isinstance(confirm_rate, (int, float)):
        if confirm_rate >= 0.75:
            resonance_summary["sector_followthrough"] = f"{sw_l1} 承接较强，行业资金确认率 {confirm_rate:.0%}。"
        elif confirm_rate >= 0.6:
            resonance_summary["sector_followthrough"] = f"{sw_l1} 有一定承接，行业资金确认率 {confirm_rate:.0%}。"
        else:
            resonance_summary["sector_followthrough"] = f"{sw_l1} 承接偏弱，行业资金确认率仅 {confirm_rate:.0%}。"
        if isinstance(divergence_count, (int, float)) and divergence_count >= 1:
            resonance_summary["sector_followthrough"] += f" 行业内已有 {int(divergence_count)} 个分歧样本。"
        if isinstance(rotation_score, (int, float)) and rotation_score >= 80:
            resonance_summary["sector_followthrough"] += " 属于当前更强的顺风方向。"

    if sr_direction == "above_resistance" and isinstance(sr_distance_pct, (int, float)) and sr_distance_pct <= 0.01:
        resonance_summary["persistence_view"] = "更像刚突破待确认，持续性要看未来 1-3 天是否站稳。"
    elif isinstance(d1_duration, (int, float)) and d1_duration >= 5:
        resonance_summary["persistence_view"] = f"D1 活跃已持续 {int(d1_duration)} 天，若板块继续承接，持续性相对更好。"
    elif isinstance(d1_duration, (int, float)) and d1_duration <= 2:
        resonance_summary["persistence_view"] = "刚进入活跃段，持续性未充分展开，先防止单日脉冲。"

    if sr_direction == "above_resistance":
        if moneyflow_confirmed and isinstance(confirm_rate, (int, float)) and confirm_rate >= 0.75:
            resonance_summary["breakout_view"] = "更像真突破候选：位置已越过阻力，资金流与板块承接同步确认。"
        elif moneyflow_divergence:
            resonance_summary["breakout_view"] = "更像假突破复核样本：价格越过阻力，但资金没有同步确认。"
        elif isinstance(sr_distance_pct, (int, float)) and sr_distance_pct <= 0.01:
            resonance_summary["breakout_view"] = "仍是突破观察样本：刚越过阻力，需等 1-3 天确认真假。"
        else:
            resonance_summary["breakout_view"] = "已越过阻力，但更像中段推进，不应再按早期突破处理。"

    strategy_risk_lines = []
    for row in strategy_rows:
        risk = row.get("risk")
        if risk:
            strategy_risk_lines.append(f"{row.get('strategy_label', '当前策略')}：{risk}")
    research_warnings = []
    if cards.get("warnings"):
        research_warnings.extend(cards["warnings"])
    if cards.get("error"):
        research_warnings.append(cards["error"])
    for freshness in (unified_freshness, industry_rotation_freshness):
        if freshness["status"] in {"stale", "missing", "unknown"}:
            research_warnings.append(freshness["message"])

    return {
        "stock_code": stock_code.strip().upper(),
        "render_profile": render_profile,
        "cards": cards,
        "research_lane": lead,
        "strategy_rows": strategy_rows,
        "summary": summary,
        "ai_summary": ai_summary,
        "coverage": coverage,
        "missing_modules": missing_modules,
        "research_warnings": research_warnings,
        "not_needed_now": not_needed_now,
        "strategy_risk_lines": strategy_risk_lines,
        "resonance_summary": resonance_summary,
        "freshness": [unified_freshness, industry_rotation_freshness],
        "strategy_view": {
            "strategy_id": overlay_strategy_id,
            "label": overlay_definition["label"],
            "what": overlay_definition["what"],
            "how": overlay_definition["how"],
            "when": overlay_definition["when"],
            "avoid": overlay_definition["avoid"],
            "risk": overlay_definition["risk"],
            "signal_read": _signal_interpretation(
                overlay_strategy_id,
                cards.get("quick", ""),
                overlay.get("lifecycle_stage", "") if isinstance(overlay, dict) else "",
                overlay.get("strategy_environment_fit", "") if isinstance(overlay, dict) else "",
            ),
        },
        "state_core": state_core,
        "mn1_label": _hex_to_human_label(mn1_hex),
        "w1_label": _hex_to_human_label(w1_hex),
        "d1_label": _hex_to_human_label(d1_hex),
        "resonance_label": resonance_label,
        "state_prior_view": state_prior_view,
    }


def _view_mode_summary(mode: str) -> dict[str, Any]:
    quant = _quant_summary()
    industry = _industry_rotation_data()
    outputs = _output_status()
    execution = _execution_lane()
    research = _research_lane("000021.SZ")
    market = _market_analysis_data()
    stale_overview = market.get("stale_rows", [])

    modes = {
        "direction": {
            "label": "方向模式",
            "headline": "先看多周期结构是否共振，再判断当前更适配哪类周期走势。",
            "judgment": market["stance"],
            "why": market["broad_summary"],
            "next_step": market["focus_now"],
            "starter_title": "第一次使用建议",
            "starter_steps": [
                "先看市场页，确认现在更适合等待、试错还是顺风跟踪。",
                "再看行业页，只挑少数顺风方向，不平均用力。",
                "最后进入研究或执行页，处理真正值得跟踪的样本。",
            ],
            "focus": [
                f"行业覆盖 {industry['industry_count']} 个，先看最有代表性的方向。",
                f"最新信号 {industry['signal_count']} 条，但不是都值得处理。",
                f"高风报比样本 {quant['reward_risk']['high_value_count']} 个，优先看少数高质量机会。",
            ],
            "primary_cta": "/market",
            "primary_label": "查看市场判断",
        },
        "research": {
            "label": "研究模式",
            "headline": "先看多周期相互影响与单周期运行位置，再展开证据细节。",
            "judgment": "当前研究更适合做结构观察，不适合把证据缺口强行补成强结论。",
            "why": "多数研究对象仍以 State 核心为主，基本面和行业模块并不总是完整。",
            "next_step": f"先打开 {research['lead_code']} 的研究卡，确认证据充分度后再下钻。",
            "starter_title": "第一次使用建议",
            "starter_steps": [
                "先打开一只样本股的研究页，不必一开始看长篇内容。",
                "先读决策收束和多因子共振判断，再决定是否看深度卡。",
                "遇到证据缺口时，把它当观察对象，不强行补成结论。",
            ],
            "focus": [
                "用 quick / deep / evidence 三层结构收敛认知负担。",
                f"当前优先研究 {research['lead_code']} {research['lead_name']}。",
                f"核心产物状态 {sum(1 for row in outputs if row['status'] == 'OK')} / {len(outputs)} 正常。",
            ],
            "primary_cta": "#research-preview",
            "primary_label": "进入研究卡",
        },
        "execution": {
            "label": "执行模式",
            "headline": "只处理当前周期位置最清晰、概率与盈亏比更划算的样本。",
            "judgment": execution["lane_hint"],
            "why": "执行页不需要再看全市场，只看优先队列、观察队列和高风报比参考。",
            "next_step": "先处理 priority queue，再决定是否把观察对象升级。",
            "starter_title": "第一次使用建议",
            "starter_steps": [
                "先看优先队列，不要同时处理所有样本。",
                "再看资金流确认、板块承接和真假突破，不要只看路径标签。",
                "最后才决定是继续跟踪，还是降级回观察。",
            ],
            "focus": [
                f"Forward observation 待标注 {execution['pending']} 条。",
                f"主动提醒账本最近记录 {len(execution['recent_alerts'])} 条。",
                f"高风报比候选 {quant['reward_risk']['high_value_count']} 个，优先少量处理。",
            ],
            "primary_cta": "/watchlist",
            "primary_label": "进入执行队列",
        },
    }
    selected = modes.get(mode, modes["direction"])
    selected["stale_overview"] = stale_overview
    return selected


def _output_status() -> list[dict[str, str]]:
    items: list[tuple[str, Path | str | None]] = [
        ("Foundation DB", find_foundation_db()),
        (
            "Daily Brief",
            _latest_existing_path(
                [
                    "outputs/daily_research_brief/daily_research_brief_*.md",
                    "outputs/daily_research_brief/chief_research_report_*.md",
                    "outputs/reports/daily_brief_*.md",
                ]
            ),
        ),
        ("Strategy Ledger", _latest_path("outputs/strategy_signals/strategy_signal_daily_*.json")),
        ("Forward Observation", _latest_path("outputs/forward_observation/forward_observation_*.json")),
        ("Active Alerts Ledger", ROOT / "outputs/alerts/active_state_alerts_sent.json"),
        ("Cron Config", ROOT / "config/hermes_cron.json"),
    ]
    rows = []
    for name, value in items:
        path = Path(value) if value else None
        ok = bool(path and path.exists())
        rows.append({"name": name, "status": "OK" if ok else "Missing", "path": _rel(path) if ok else "-"})
    return rows


def _cron_rows() -> list[dict[str, Any]]:
    config = _read_json(ROOT / "config/hermes_cron.json")
    if not isinstance(config, dict):
        return []
    rows = []
    for job in config.get("jobs", []) + config.get("tasks", []):
        rows.append(
            {
                "name": job.get("name", ""),
                "cron": job.get("cron", job.get("schedule", "")),
                "enabled": job.get("enabled", True),
                "command": job.get("command", ""),
                "delivery": job.get("delivery", ""),
            }
        )
    return rows


def _alert_rows() -> list[dict[str, str]]:
    ledger = _read_json(ROOT / "outputs/alerts/active_state_alerts_sent.json")
    if not isinstance(ledger, dict):
        return []
    rows = []
    for key in ledger.get("sent_keys", [])[-20:]:
        rows.append({"key": str(key)})
    return rows


def _quant_summary() -> dict[str, Any]:
    signal_ctx = _signal_payload_context()
    signals = signal_ctx["payload"]
    forward = _read_json(_latest_path("outputs/forward_observation/forward_observation_*.json"))
    rr = _read_json(_latest_path("outputs/reward_risk/reward_risk_*.json"))
    strategy_counts = signals.get("strategy_counts", {}) if isinstance(signals, dict) else {}
    strategy_totals = {
        strategy_id: _strategy_signal_total(strategy_counts, strategy_id)
        for strategy_id in ("vcp", "ma2560", "bollinger_bandit")
    }
    display_strategy_totals = _display_path_distribution(strategy_totals)
    strategy_distribution = forward.get("strategy_distribution", {}) if isinstance(forward, dict) else {}
    display_strategy_distribution = _display_path_distribution(strategy_distribution)
    high_value_signals = []
    if isinstance(rr, dict):
        for row in rr.get("high_value_signals", [])[:8]:
            strategy_id = str(row.get("strategy_id") or row.get("strategy") or "").strip()
            item = dict(row)
            item["strategy_label"] = _strategy_definition(strategy_id)["label"]
            item["path_label"] = _display_path_label(strategy_id)
            high_value_signals.append(item)
    return {
        "signals": {
            "date": signals.get("date", "-") if isinstance(signals, dict) else "-",
            "count": signals.get("signal_count", 0) if isinstance(signals, dict) else 0,
            "strategy_counts": strategy_counts,
            "strategy_totals": strategy_totals,
            "display_strategy_totals": display_strategy_totals,
            "meta": signal_ctx,
            "rows": (signals.get("rows", [])[:12] if isinstance(signals, dict) else []),
        },
        "forward": {
            "date": forward.get("date", "-") if isinstance(forward, dict) else "-",
            "total": forward.get("total", 0) if isinstance(forward, dict) else 0,
            "labeled": forward.get("labeled", 0) if isinstance(forward, dict) else 0,
            "pending": forward.get("pending", 0) if isinstance(forward, dict) else 0,
            "strategy_distribution": strategy_distribution,
            "display_strategy_distribution": display_strategy_distribution,
        },
        "reward_risk": {
            "signal_date": rr.get("signal_date", "-") if isinstance(rr, dict) else "-",
            "total_signals": rr.get("total_signals", 0) if isinstance(rr, dict) else 0,
            "computable_rr": rr.get("computable_rr", 0) if isinstance(rr, dict) else 0,
            "high_value_count": rr.get("high_value_count", 0) if isinstance(rr, dict) else 0,
            "summary": rr.get("summary", {}) if isinstance(rr, dict) else {},
            "high_value_signals": high_value_signals,
        },
    }


def _render_cards(stock_code: str, render_profile: str) -> dict[str, Any]:
    foundation_db = find_foundation_db()
    if not foundation_db:
        return {"error": "未找到 foundation DB。"}
    as_of_date = _latest_research_as_of_date()
    try:
        evidence = build_external_research_evidence(
            stock_code=stock_code.strip().upper(),
            as_of_date=as_of_date,
            foundation_db=foundation_db,
        )
        return {
            "quick": format_quick_research_card(evidence),
            "deep": format_deep_research_card(evidence, render_profile=render_profile),
            "evidence": format_evidence_card(evidence),
            "payload": json.dumps(evidence, ensure_ascii=False, indent=2),
            "warnings": (evidence.get("meta", {}) or {}).get("warnings", []),
            "as_of_date": as_of_date,
        }
    except Exception as exc:
        return {
            "error": f"研究卡构建失败：{exc}",
            "quick": "",
            "deep": "",
            "evidence": "",
            "payload": "",
            "warnings": [],
            "as_of_date": as_of_date,
        }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "hermass-internal-console"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, mode: str = "") -> HTMLResponse:
    profile = get_current_profile(request)
    user_type = profile.get("user_type", "执行型")
    # 若未传 mode，按 user_type 映射到对应首页视角
    mode_map = {"方向型": "direction", "研究型": "research", "执行型": "execution"}
    mode = mode or mode_map.get(user_type, "direction")
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "today": str(date.today()),
            "mode": mode,
            "mode_summary": _view_mode_summary(mode),
            "industry": _industry_rotation_data(),
            "execution": _execution_lane(),
            "research_lane": _research_lane("000021.SZ"),
            "outputs": _output_status(),
            "cron_rows": _cron_rows(),
            "alert_rows": _alert_rows(),
            "quant": _quant_summary(),
            "cards": None,
            "stock_code": "000021.SZ",
            "render_profile": "full",
            "daily_brief": _daily_brief(),
            "current_user": profile,
        },
    )


@app.post("/", response_class=HTMLResponse)
def preview_cards(
    request: Request,
    stock_code: str = Form("000021.SZ"),
    render_profile: str = Form("full"),
    mode: str = Form("direction"),
) -> HTMLResponse:
    profile = get_current_profile(request)
    cards = _render_cards(stock_code, render_profile)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "today": str(date.today()),
            "mode": mode,
            "mode_summary": _view_mode_summary(mode),
            "industry": _industry_rotation_data(),
            "execution": _execution_lane(),
            "research_lane": _research_lane(stock_code),
            "outputs": _output_status(),
            "cron_rows": _cron_rows(),
            "alert_rows": _alert_rows(),
            "quant": _quant_summary(),
            "cards": cards,
            "stock_code": stock_code,
            "render_profile": render_profile,
            "daily_brief": _daily_brief(),
            "current_user": profile,
        },
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, mode: str = "") -> HTMLResponse:
    """认知仪表板（新模板测试路由）。"""
    profile = get_current_profile(request)
    user_type = profile.get("user_type", "执行型")
    mode_map = {"方向型": "direction", "研究型": "research", "执行型": "execution"}
    mode = mode or mode_map.get(user_type, "direction")
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "today": str(date.today()),
            "mode": mode,
            "mode_summary": _view_mode_summary(mode),
            "industry": _industry_rotation_data(),
            "execution": _execution_lane(),
            "research_lane": _research_lane("000021.SZ"),
            "outputs": _output_status(),
            "cron_rows": _cron_rows(),
            "alert_rows": _alert_rows(),
            "quant": _quant_summary(),
            "cards": None,
            "stock_code": "000021.SZ",
            "render_profile": "full",
            "daily_brief": _daily_brief(),
            "current_user": profile,
            "dashboard": _dashboard_data(),
        },
    )


@app.get("/industry", response_class=HTMLResponse)
def industry_page(request: Request) -> HTMLResponse:
    profile = get_current_profile(request)
    return templates.TemplateResponse(
        request,
        "industry.html",
        {
            "request": request,
            "today": str(date.today()),
            "industry": _industry_rotation_data(),
            "current_user": profile,
        },
    )


@app.get("/market", response_class=HTMLResponse)
def market_page(request: Request) -> HTMLResponse:
    profile = get_current_profile(request)
    return templates.TemplateResponse(
        request,
        "market.html",
        {
            "request": request,
            "today": str(date.today()),
            "market": _market_analysis_data(),
            "current_user": profile,
        },
    )


@app.get("/watchlist", response_class=HTMLResponse)
def watchlist_page(request: Request) -> HTMLResponse:
    profile = get_current_profile(request)
    return templates.TemplateResponse(
        request,
        "watchlist.html",
        {
            "request": request,
            "today": str(date.today()),
            "execution": _execution_lane(),
            "current_user": profile,
        },
    )


@app.get("/research", response_class=HTMLResponse)
def research_page(
    request: Request,
    stock_code: str = "000021.SZ",
    render_profile: str = "full",
) -> HTMLResponse:
    profile = get_current_profile(request)
    ctx = _research_page_context(stock_code, render_profile)
    ctx["request"] = request
    ctx["today"] = str(date.today())
    ctx["current_user"] = profile
    return templates.TemplateResponse(
        request,
        "research.html",
        ctx,
    )


# ─── 回测页面 ────────────────────────────────────────


def _backtest_form_defaults() -> dict[str, Any]:
    latest = _latest_research_as_of_date()
    return {
        "strategy": "ef",
        "end_date": latest,
        "lookback_days": 30,
        "max_positions": 10,
        "min_ef": 2,
        "initial_capital": 1_000_000,
    }


def _run_backtest_safe(params: dict[str, Any]) -> dict[str, Any]:
    """安全执行回测，捕获输出和异常。"""
    foundation_db = find_foundation_db()
    if not foundation_db:
        return {"error": "未找到 Foundation DB，无法运行回测。"}

    config = BacktestConfig(
        strategy_name=params["strategy"],
        lookback_days=int(params["lookback_days"]),
        max_positions=int(params["max_positions"]),
        min_ef_count=int(params["min_ef"]),
        initial_capital=float(params["initial_capital"]),
    )

    stdout_capture = io.StringIO()
    advisory = {
        "strategy": params["strategy"],
        "lookback_days": int(params["lookback_days"]),
        "state_validation": "当前回测属于 Hermass State 环境下的策略验证，不是独立指标策略回测。",
        "runtime_note": "Foundation DB 较大时，首次回测仍可能偏慢；建议先用 30 天窗口做快速验证，再拉长周期比较环境适配度。",
    }
    started_at = time.perf_counter()
    try:
        with contextlib.redirect_stdout(stdout_capture):
            result = run_backtest(
                date_str=params["end_date"],
                config=config,
                foundation_db=Path(foundation_db),
            )
        advisory["runtime_seconds"] = round(time.perf_counter() - started_at, 2)
        metrics = result.get("metrics", {})
        if metrics.get("total_trades", 0) == 0:
            advisory["empty_result_note"] = (
                "本次窗口内未形成满足门槛的有效交易。更常见的原因是：窗口较短、"
                "min_ef 过滤较严，或当前 State 环境下策略本就不活跃。"
            )
        return {
            "ok": True,
            "result": result,
            "logs": stdout_capture.getvalue(),
            "advisory": advisory,
        }
    except FileNotFoundError as exc:
        advisory["runtime_seconds"] = round(time.perf_counter() - started_at, 2)
        return {
            "error": f"数据文件缺失：{exc}",
            "advisory": advisory,
        }
    except Exception as exc:
        advisory["runtime_seconds"] = round(time.perf_counter() - started_at, 2)
        return {
            "error": f"回测执行失败：{exc}",
            "logs": stdout_capture.getvalue(),
            "advisory": advisory,
        }


@app.get("/backtest", response_class=HTMLResponse)
def backtest_page(request: Request) -> HTMLResponse:
    profile = get_current_profile(request)
    defaults = _backtest_form_defaults()
    return templates.TemplateResponse(
        request,
        "backtest.html",
        {
            "request": request,
            "today": str(date.today()),
            "defaults": defaults,
            "result": None,
            "error": None,
            "logs": "",
            "advisory": {
                "strategy": defaults["strategy"],
                "lookback_days": defaults["lookback_days"],
                "state_validation": "回测页验证的是 Hermass State 环境下的策略适配，不是简单指标回测。",
                "runtime_note": "Foundation DB 较大时，单次运行可能需要更久，请优先用 30 天窗口做快速验证。",
                "runtime_seconds": None,
            },
            "current_user": profile,
        },
    )


@app.post("/backtest", response_class=HTMLResponse)
def backtest_run(
    request: Request,
    strategy: str = Form("ef"),
    end_date: str = Form(""),
    lookback_days: str = Form("30"),
    max_positions: str = Form("10"),
    min_ef: str = Form("2"),
    initial_capital: str = Form("1000000"),
) -> HTMLResponse:
    profile = get_current_profile(request)
    params = {
        "strategy": strategy,
        "end_date": end_date or _latest_research_as_of_date(),
        "lookback_days": int(lookback_days),
        "max_positions": int(max_positions),
        "min_ef": int(min_ef),
        "initial_capital": float(initial_capital),
    }
    outcome = _run_backtest_safe(params)
    return templates.TemplateResponse(
        request,
        "backtest.html",
        {
            "request": request,
            "today": str(date.today()),
            "defaults": params,
            "result": outcome.get("result") if outcome.get("ok") else None,
            "error": outcome.get("error"),
            "logs": outcome.get("logs", ""),
            "advisory": outcome.get("advisory"),
            "current_user": profile,
        },
    )


@app.get("/mystrategies", response_class=HTMLResponse)
def mystrategies_page(request: Request) -> HTMLResponse:
    """策略编辑器页面 —— Phase 1：条件块 UI + 即时预览。"""
    profile = get_current_profile(request)
    return templates.TemplateResponse(
        request,
        "strategy-editor.html",
        {
            "request": request,
            "today": str(date.today()),
            "current_user": profile,
        },
    )


@app.get("/strategy-editor", response_class=HTMLResponse)
def strategy_editor_page(request: Request) -> HTMLResponse:
    """策略编辑器页面（新路由别名）。"""
    profile = get_current_profile(request)
    return templates.TemplateResponse(
        request,
        "strategy-editor.html",
        {
            "request": request,
            "today": str(date.today()),
            "current_user": profile,
        },
    )


# ─── AI 助手接口 ─────────────────────────────────────


class ChatQuery(BaseModel):
    message: str
    page_context: str = ""
    stock_code: str | None = None
    session_id: str | None = None
    session_context: dict[str, Any] | None = None
    mode: str = "chat"
    use_llm: bool = False


class ChatResponse(BaseModel):
    answer: str
    why: str
    multi_cycle_view: str = ""
    single_cycle_position: str = ""
    avoid: str
    next_actions: list[dict[str, str]]
    sources: list[str]
    freshness_note: str = ""
    remembered_stock_code: str = ""
    remembered_email: str = ""
    mode_used: str = "chat"
    provider: str = "rule_based"
    enhancement_used: bool = False
    task_card: dict[str, Any] | None = None


WATCH_COMMAND_LEDGER = ROOT / "outputs" / "alerts" / "watch_command_ledger.json"


def _load_watch_command_ledger() -> dict[str, Any]:
    if not WATCH_COMMAND_LEDGER.exists():
        return {"version": "1.0.0", "commands": []}
    try:
        return json.loads(WATCH_COMMAND_LEDGER.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "1.0.0", "commands": []}


def _save_watch_command_ledger(data: dict[str, Any]) -> None:
    WATCH_COMMAND_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    WATCH_COMMAND_LEDGER.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _canonical_stock_code(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) != 6:
        return value.upper()
    if digits.startswith(("6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("8", "4")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def _extract_stock_code_from_message(message: str) -> str:
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", message)
    if not match:
        return ""
    return _canonical_stock_code(match.group(1))


def _extract_email_from_message(message: str) -> str:
    match = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", message)
    return match.group(1).strip() if match else ""


def _chat_email(query: ChatQuery) -> str:
    direct = _extract_email_from_message(query.message)
    if direct:
        return direct
    ctx = query.session_context or {}
    return str(ctx.get("email") or "").strip()


def _chat_stock_code(query: ChatQuery) -> str:
    direct = query.stock_code or _extract_stock_code_from_message(query.message)
    if direct:
        return direct
    ctx = query.session_context or {}
    remembered = str(ctx.get("stock_code") or "").strip()
    if remembered:
        return _canonical_stock_code(remembered)
    return ""


def _fmt_chat_num(value: Any, digits: int = 2) -> str:
    if value in (None, ""):
        return "暂无"
    try:
        return f"{float(value):,.{digits}f}"
    except Exception:
        return str(value)


def _fmt_chat_yi(value: Any, digits: int = 2) -> str:
    if value in (None, ""):
        return "暂无"
    try:
        return f"{float(value) / 1e8:.{digits}f}亿"
    except Exception:
        return str(value)


def _fmt_chat_percent(value: Any, digits: int = 1) -> str:
    if value in (None, ""):
        return "暂无"
    try:
        return f"{float(value):.{digits}f}%"
    except Exception:
        return str(value)


def _value_research_chat_summary(stock_code: str) -> dict[str, str] | None:
    foundation_db = find_foundation_db()
    if not foundation_db:
        return None
    try:
        evidence = build_external_research_evidence(
            stock_code=stock_code,
            as_of_date=_latest_research_as_of_date(),
            foundation_db=foundation_db,
        )
    except Exception:
        return None

    profile = evidence.get("company_profile", {}) or {}
    financial = (evidence.get("financial_trend", {}) or {}).get("period_rows", []) or []
    latest = financial[0] if financial else {}
    valuation = evidence.get("valuation_reference", {}) or {}
    market_views = evidence.get("market_views", {}) or {}
    industry = evidence.get("industry_state", {}) or {}
    state_core = evidence.get("state_core", {}) or {}
    stock_name = str(profile.get("stock_name") or stock_code)
    sw_l1 = str(profile.get("sw_l1") or "所在行业")
    main_business = str(profile.get("main_business") or "").strip()
    comparable = str(profile.get("comparable_companies") or profile.get("competitor_companies") or "").strip()
    business_text = main_business if main_business else "当前主营描述覆盖不足，需结合研究页补充阅读。"
    comparable_text = comparable if comparable else "本地可比公司覆盖有限，竞争格局先按产业链位置理解。"
    prosperity = industry.get("prosperity_score")
    etf_state = str(industry.get("etf_state_hex") or "暂无")
    revenue = _fmt_chat_yi(latest.get("revenue"))
    net_profit = _fmt_chat_yi(latest.get("net_profit"))
    roe = _fmt_chat_percent(latest.get("roe"))
    pe = valuation.get("pe_ttm")
    pb = valuation.get("pb")
    pe_text = "暂无" if pe in (None, "") else ("亏损（PE 不适用）" if float(pe) <= 0 else f"{float(pe):.2f}")
    pb_text = _fmt_chat_num(pb)
    latest_report = (market_views.get("latest_report") or {})
    latest_inst = str(latest_report.get("institution") or "暂无")
    latest_rating = str(latest_report.get("rating") or "暂无")
    latest_date = str(latest_report.get("date") or "暂无")
    answer = (
        f"可以。先给你一版 {stock_name} 的价值摘要：主营上，它主要围绕「{business_text}」展开；"
        f"行业上归在 {sw_l1}，当前景气分 {_fmt_chat_num(prosperity)}、ETF State 为 {etf_state}；"
        f"财务上最近一期营收 {revenue}、净利润 {net_profit}、ROE {roe}；"
        f"估值参考上 PE(TTM) {pe_text}、PB {pb_text}。"
    )
    why = (
        f"这不是恢复长报告，而是先把行业位置、公司主营、财务健康、估值参考和公开市场预期压成一版可读摘要。"
        f"可比/竞争线索当前优先看：{comparable_text}"
    )
    multi_cycle_view = (
        f"{stock_name} 的价值阅读也不能绕开多周期。先看 MN1/W1/D1 是否配合："
        f"当前 State 组合为 {state_core.get('mn1_state_hex') or '-'} / {state_core.get('w1_state_hex') or '-'} / {state_core.get('d1_state_hex') or '-'}，"
        "只有大级别和中级别环境不拖后腿，行业与公司层面的结论才更有结构支撑。"
    )
    single_cycle_position = (
        "单周期上仍要区分刚突破、推进中段和高位延展。"
        "同样的基本面，如果日线已经高位延展，赔率与节奏就和刚起步完全不同。"
    )
    avoid = (
        f"先不要把这版价值摘要理解成买卖建议。公开市场最新观点仅显示为 {latest_inst} 于 {latest_date} 给出的 {latest_rating}，"
        "它只是研究参考，不代表系统结论。"
    )
    freshness_note = (
        f"当前摘要复用的研究数据日期为 {evidence.get('meta', {}).get('as_of_date', '-')}"
        f"，财务期数为 {evidence.get('financial_trend', {}).get('latest_report_period', '暂无')}。"
    )
    return {
        "answer": answer,
        "why": why,
        "multi_cycle_view": multi_cycle_view,
        "single_cycle_position": single_cycle_position,
        "avoid": avoid,
        "freshness_note": freshness_note,
    }


def _load_top10_holders_context(stock_code: str, as_of_date: str) -> list[dict[str, Any]]:
    parquet_path = _latest_dated_data_file(
        ROOT / "data" / "akshare_fundamental",
        "stock_holder_top10",
        ".parquet",
        as_of_date,
    )
    digits = _digits_only_code(stock_code)
    if not parquet_path or not digits:
        return []

    con = duckdb.connect()
    try:
        rows = con.execute(
            f"""
            SELECT 股东名称, 股东类型, 报告期, "期末持股-数量", "期末持股-数量变化",
                   "期末持股-数量变化比例", "期末持股-持股变动", "期末持股-流通市值", 公告日
            FROM read_parquet('{parquet_path.as_posix()}')
            WHERE 股票代码 = ?
              AND 报告期 <= ?
            ORDER BY 报告期 DESC, 序号 ASC
            LIMIT 10
            """,
            [digits, as_of_date],
        ).fetchall()
    finally:
        con.close()

    holders: list[dict[str, Any]] = []
    for row in rows:
        holders.append(
            {
                "holder_name": row[0] or "",
                "holder_type": row[1] or "",
                "report_date": str(row[2]) if row[2] else "",
                "share_count": row[3],
                "share_change": row[4],
                "share_change_pct": row[5],
                "change_label": row[6] or "",
                "market_value_yi": round(float(row[7]) / 1e8, 2) if row[7] is not None else None,
                "announcement_date": str(row[8]) if row[8] else "",
            }
        )
    return holders


def _build_search_data_context(market_views: dict[str, Any]) -> dict[str, Any]:
    latest_report = market_views.get("latest_report") or {}
    rating_distribution = market_views.get("rating_distribution") or {}
    status = "local_market_views_already_present" if (latest_report or rating_distribution) else "placeholder"
    notes: list[str] = []
    if latest_report:
        notes.append(
            f"本地 market_views 已有公开机构观点：{latest_report.get('institution') or '暂无'} 于 "
            f"{latest_report.get('date') or '暂无'} 给出 {latest_report.get('rating') or '暂无'}。"
        )
    return {
        "status": status,
        "source": "local_market_views",
        "latest_report": latest_report,
        "rating_distribution": rating_distribution,
        "target_price_count": market_views.get("target_price_count", 0),
        "digest_items": [],
        "policy_event_notes": notes,
    }

def _has_compound_intent(msg: str) -> bool:
    """轻量级复合意图检测：规则路径拦截前判断是否需要 LLM 编排。

    当前覆盖：盯盘 + 行业扫描 = watch_command + industry_scan
    """
    watch_kws = ["盯着", "帮我盯", "突破提醒", "止损提醒"]
    industry_kws = ["行业", "板块", "什么行业", "它的行业", "这个行业"]
    return (
        any(k in msg for k in watch_kws)
        and any(k in msg for k in industry_kws)
    )


def _detect_watch_command(query: ChatQuery) -> dict[str, Any] | None:
    msg = query.message.strip()
    if not any(keyword in msg for keyword in ("盯", "跟踪", "提醒我", "发邮件", "通知我")):
        return None
    stock_code = _chat_stock_code(query)
    if not stock_code:
        return {
            "needs_stock_code": True,
            "email": _extract_email_from_message(msg),
        }
    email = _chat_email(query)
    trigger_type = "long_term_watch"
    note = "长期跟踪提醒"
    watch_type = "long_term"
    valid_days = 90

    if "周线关键位" in msg and any(k in msg for k in ("突破", "站上")):
        trigger_type = "w1_breakout"
        note = "突破周线关键位提醒"
        watch_type = "conditional"
        valid_days = 30
    elif "跌破" in msg and any(k in msg for k in ("支撑", "D1")):
        trigger_type = "d1_support_break"
        note = "跌破 D1 支撑提醒"
        watch_type = "conditional"
        valid_days = 30
    elif any(k in msg for k in ("行业共振", "板块共振")):
        trigger_type = "sector_resonance"
        note = "行业共振提醒"
        watch_type = "conditional"
        valid_days = 30
    elif any(k in msg for k in ("走弱", "连续 3 天")):
        trigger_type = "d1_weakening_3d"
        note = "D1 连续走弱提醒"
        watch_type = "conditional"
        valid_days = 30
    elif any(k in msg for k in ("跌出", "从 E/F 跌出")):
        trigger_type = "state_drop"
        note = "D1 从 E/F 跌出提醒"
        watch_type = "conditional"
        valid_days = 30

    return {
        "stock_code": stock_code,
        "email": email,
        "trigger_type": trigger_type,
        "watch_type": watch_type,
        "valid_days": valid_days,
        "note": note,
        "page_context": query.page_context,
    }


def _register_watch_command(command: dict[str, Any]) -> dict[str, Any]:
    ledger = _load_watch_command_ledger()
    commands = ledger.setdefault("commands", [])
    today = date.today()
    valid_to = today + timedelta(days=int(command["valid_days"]))
    watch_id = f"watch_{today.strftime('%Y%m%d')}_{command['stock_code'].replace('.', '')}_{len(commands)+1:03d}"
    record = {
        "watch_id": watch_id,
        "stock_code": command["stock_code"],
        "watch_type": command["watch_type"],
        "trigger_type": command["trigger_type"],
        "email": command["email"],
        "valid_from": today.isoformat(),
        "valid_to": valid_to.isoformat(),
        "status": "active",
        "note": command["note"],
        "created_from": "ai_assistant",
        "page_context": command.get("page_context") or "",
        "last_triggered_at": None,
    }
    commands.append(record)
    ledger["commands"] = commands[-500:]
    _save_watch_command_ledger(ledger)
    return record


def _deepseek_enabled() -> bool:
    return bool(os.environ.get("HERMASS_DEEPSEEK_API_KEY", "").strip() or os.environ.get("DEEPSEEK_API_KEY", "").strip())


def _agently_enabled() -> bool:
    if not _deepseek_enabled():
        return False
    try:
        from agently import Agently  # noqa: F401
        return True
    except Exception:
        return False


def _is_value_question(message: str) -> bool:
    return any(k in message for k in ("价值分析", "价值投研", "深度价值", "基本面深度", "8 大块", "八大块"))


def _is_industry_question(message: str) -> bool:
    return any(k in message for k in ("方向", "行业", "先看什么", "哪些", "顺风"))


def _is_market_question(message: str) -> bool:
    return any(k in message for k in ("能不能", "能做", "市场", "现在能", "今天能", "等待", "试错"))



def _user_wants_llm(query: ChatQuery) -> bool:
    """用户是否打开了 LLM 增强开关。

    语义：只检查用户意愿（前端 use_llm 开关），不做问题类型判断。
    高价值/低价值问题的路由由 agently_adapter 层内部决定。
    2026-05-31 修复：不再对高价值问题强制走 LLM。
    """
    mode = "agent" if str(query.mode or "").lower() == "agent" else "chat"
    if mode != "chat":
        return False
    return bool(query.use_llm)


def _requires_managed_llm(query: ChatQuery) -> bool:
    """判断当前问题是否属于高价值解释类，需要 LLM 增强。

    2026-05-31 修复：use_llm=false 时不强制要求 LLM。
    """
    mode = "agent" if str(query.mode or "").lower() == "agent" else "chat"
    if mode != "chat":
        return False
    if not query.use_llm:
        return False
    msg = query.message.strip().lower()
    return _is_value_question(msg) or _is_industry_question(msg) or _is_market_question(msg)


def _deepseek_prompt_contract() -> str:
    contract_path = ROOT / "docs" / "AI_ASSISTANT_RESPONSE_CONTRACT.md"
    if not contract_path.exists():
        return ""
    return contract_path.read_text(encoding="utf-8")


def _coze_value_prompt_pack() -> str:
    path = ROOT / "config" / "prompts" / "coze_value_research_prompt_pack.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _deepseek_system_prompt() -> str:
    system_prompt = (
        "你是 Hermass 网站内的 AI 助手。你只做解释、翻译和导航，不做投资建议。"
        "你必须坚持多周期环境、单周期位置、风险控制这条主线。"
        "输出必须是 JSON，且字段必须包含 answer, why, multi_cycle_view, single_cycle_position, avoid, next_actions, sources, freshness_note。"
        "回答语气随问题类型变化：市场问题用简报语气（简洁、判断明确），"
        "个股问题用体检报告语气（分层、有数据、有未知项标注），"
        "导航问题用导航员语气（一句话指引方向）。"
    )
    return with_deepseek_context(system_prompt + "\n\n" + _deepseek_prompt_contract())


def _deepseek_value_system_prompt() -> str:
    system_prompt = (
        "你是 Hermass 网站内的价值研究增强助手。你只做价值研究解释、翻译和导航，不做投资建议。"
        "你必须坚持 Research-Only 边界，并把多周期环境、单周期位置与价值分析并行表达。"
        "输出必须是 JSON，且字段必须包含 answer, why, multi_cycle_view, single_cycle_position, avoid, next_actions, sources, freshness_note。"
    )
    prompt_pack = _coze_value_prompt_pack()
    combined = system_prompt + "\n\n" + _deepseek_prompt_contract()
    if prompt_pack:
        combined += "\n\n---\n\n以下是价值研究增强的专业输出提示词资产，仅用于解释层增强，不代表投资建议：\n\n" + prompt_pack
    return with_deepseek_context(combined)


def _agently_deepseek_call(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not _agently_enabled():
        return None
    try:
        from agently_adapter.deepseek import call as deepseek_call
        return deepseek_call(
            payload,
            system_prompt=_deepseek_system_prompt(),
            instruct="你只做解释与导航，不做投资建议，必须严格输出 JSON。",
        )
    except Exception:
        return None


def _agently_value_deepseek_call(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not _agently_enabled():
        return None
    try:
        from agently_adapter.deepseek import call as deepseek_call
        instruct = (
            "你只做价值研究解释与导航，不做投资建议，必须严格输出 JSON。"
            "分析时必须包含以下要素："
            "1. 先用 main_business 一句话说明公司主营业务；"
            "2. 再用 latest_financial_report 中的营收、利润、现金流数据支撑基本面判断；"
            "3. 最后结合多周期 State 给出综合结论。"
        )
        return deepseek_call(
            payload,
            system_prompt=_deepseek_value_system_prompt(),
            instruct=instruct,
        )
    except Exception:
        return None


def _enhance_result_defaults(
    result: dict[str, Any],
    query: ChatQuery,
    *,
    next_actions: list[dict[str, str]],
    sources: list[str],
    provider: str,
) -> dict[str, Any]:
    result.setdefault("next_actions", next_actions)
    result.setdefault("sources", sources)
    result.setdefault("remembered_stock_code", _chat_stock_code(query))
    result.setdefault("remembered_email", _chat_email(query))
    result.setdefault("mode_used", "chat")
    if result.get("provider") is None:
        result["provider"] = provider
    if result.get("enhancement_used") is None:
        result["enhancement_used"] = provider != "rule_based"
    return result


def _build_memory_context(session_id: str) -> dict[str, Any]:
    """从最近 3 轮对话中规则提取记忆上下文。零外部依赖，不调用 LLM。"""
    import json as _json
    from collections import Counter
    from hermass_platform.chat.conversation_manager import get_conversation_manager

    conv_mgr = get_conversation_manager()
    session = conv_mgr.get_session(session_id)
    if session is None:
        return {"recent_topics": [], "recent_stock_codes": [], "user_focus": "", "user_preferred_scenarios": []}

    recent_turns = session.turns[-3:]
    user_turns = [t for t in recent_turns if t.role == "user"]

    # 提取股票代码（6 位数字，去重保序）
    stock_codes: list[str] = []
    for turn in recent_turns:
        codes = re.findall(r"(?<!\d)\d{6}(?!\d)", turn.message)
        for c in codes:
            if c not in stock_codes:
                stock_codes.append(c)

    # 统计高频中文词（2–4 字，出现 >1 次）
    all_text = " ".join(t.message for t in recent_turns)
    words = re.findall(r"[\u4e00-\u9fa5]{2,4}", all_text)
    word_counter = Counter(words)
    top_words = [w for w, _ in word_counter.most_common(5) if word_counter[w] > 1]

    # 当前焦点：最近一条用户消息前 50 字
    user_focus = user_turns[-1].message[:50] if user_turns else ""

    # 用户偏好场景：从 turn.intent（JSON）解析 scenario 并统计频次
    scenario_counts: dict[str, int] = {}
    for turn in recent_turns:
        raw = turn.intent
        if raw and raw.startswith("{"):
            try:
                obj = _json.loads(raw)
                sc = obj.get("scenario")
                if sc:
                    scenario_counts[sc] = scenario_counts.get(sc, 0) + 1
            except Exception:
                pass
    preferred = [s for s, _ in sorted(scenario_counts.items(), key=lambda x: -x[1])[:2]]

    recent_turns_data = [
        {"role": t.role, "message": t.message[:200]}
        for t in recent_turns
    ]

    return {
        "recent_topics": top_words,
        "recent_stock_codes": stock_codes,
        "user_focus": user_focus,
        "user_preferred_scenarios": preferred,
        "recent_turns": recent_turns_data,
    }


def _check_watch_commands() -> list[dict[str, Any]]:
    """检查盯盘命令触发条件，命中则写入 watch_alerts.json。返回命中的提醒列表。"""
    cmd_path = ROOT / "outputs" / "watch_commands.json"
    if not cmd_path.exists():
        return []
    try:
        commands = json.loads(cmd_path.read_text())
    except Exception:
        return []
    if not commands:
        return []

    foundation_db = find_foundation_db(str(date.today()))
    if not foundation_db:
        return []

    alerts: list[dict[str, Any]] = []
    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        for cmd in commands:
            symbol = cmd.get("symbol", "")
            condition = cmd.get("condition", "")
            if not symbol or not condition:
                continue

            rows = con.execute(
                """
                SELECT trade_date, ef_count, d1_close, d1_sr_support,
                       d1_sr_resistance, w1_sr_resistance, mn1_sr_resistance, d1_position_bit
                FROM d1_perspective_state
                WHERE stock_code = ?
                ORDER BY trade_date DESC
                LIMIT 2
                """,
                [symbol],
            ).fetchall()
            if len(rows) < 2:
                continue

            today = rows[0]
            yesterday = rows[1]
            today_ef = today[1]
            yesterday_ef = yesterday[1]
            d1_close = today[2]
            d1_support = today[3]
            w1_resist = today[5]
            mn1_resist = today[6]
            d1_pos = today[7]

            triggered = False
            trigger_desc = ""
            if condition == "突破周线":
                triggered = d1_close > w1_resist and d1_pos == 2
                trigger_desc = "日线收盘突破周线阻力且处于突破位"
            elif condition == "突破月线":
                triggered = d1_close > mn1_resist and d1_pos == 2
                trigger_desc = "日线收盘突破月线阻力且处于突破位"
            elif condition == "跌破支撑":
                triggered = d1_close < d1_support
                trigger_desc = "日线收盘跌破 D1 支撑位"
            elif condition == "ef降级":
                triggered = yesterday_ef >= 2 and today_ef == 0
                trigger_desc = f"EF 从 {yesterday_ef} 降级到 0"

            if triggered:
                alerts.append({
                    "symbol": symbol,
                    "condition": condition,
                    "trigger_desc": trigger_desc,
                    "triggered_at": datetime.now(timezone.utc).isoformat(),
                })
    finally:
        con.close()

    if alerts:
        alert_path = ROOT / "outputs" / "watch_alerts.json"
        alert_path.write_text(json.dumps(alerts, ensure_ascii=False, indent=2))
    return alerts


def _llm_chat_answer(query: ChatQuery) -> dict[str, Any] | None:
    """通过 Agently 场景化多 Agent 编排获取 LLM 增强回答。

    2026-05-31 升级：从单 Agent qa_ask 升级到场景化多 Agent 链（qa_entry.handle）。
    web/main.py 只负责构造上下文和转发，所有路由、编排、融合都在 agently_adapter 层完成。
    """
    if not _user_wants_llm(query):
        return None

    try:
        from agently_adapter.qa_entry import handle
    except Exception:
        return None

    msg = query.message.strip().lower()

    # ── 数据预取区：记忆上下文 ──────────────────────────────────────────────
    memory: dict[str, Any] = {}
    if query.session_id:
        try:
            memory = _build_memory_context(query.session_id)
        except Exception:
            pass  # 记忆提取失败不阻塞主链路

    symbol = query.stock_code or _chat_stock_code(query) or ""
    # 代词解析：从记忆上下文中还原"它/这个/这只"
    if not symbol:
        recent_codes = memory.get("recent_stock_codes", [])
        if recent_codes and any(p in msg for p in ("它", "这个", "这只", "那个", "那只")):
            symbol = recent_codes[0]

    context = {
        "user_type": "执行型",
        "current_page": query.page_context or "",
        "symbol": symbol,
        "mode": query.mode or "chat",
        "recent_topics": memory.get("recent_topics", []),
        "recent_stock_codes": memory.get("recent_stock_codes", []),
        "user_focus": memory.get("user_focus", ""),
        "user_preferred_scenarios": memory.get("user_preferred_scenarios", []),
        "recent_turns": memory.get("recent_turns", []),
        "value_call": _agently_value_deepseek_call,
    }

    # ── 数据预取区：市场/行业/价值数据（场景编排消费） ──────────────────────
    if _is_market_question(msg) or _is_industry_question(msg) or _is_value_question(msg):
        try:
            context["market_data"] = _market_analysis_data()
        except Exception:
            context["market_data"] = {}

    if _is_industry_question(msg):
        try:
            context["industry_distribution"] = _industry_rotation_data()
        except Exception:
            context["industry_distribution"] = {}
        # 如果已解析出股票代码，预取该股票所属行业名称
        if symbol:
            try:
                foundation_db = find_foundation_db(str(date.today()))
                if foundation_db:
                    con = duckdb.connect(str(foundation_db), read_only=True)
                    try:
                        canonical = _canonical_stock_code(symbol)
                        row = con.execute(
                            "SELECT sw_l1_name FROM foundation WHERE symbol = ? LIMIT 1",
                            [canonical],
                        ).fetchone()
                        if row and row[0]:
                            context["industry_name"] = str(row[0])
                    finally:
                        con.close()
            except Exception:
                pass

    if _is_value_question(msg):
        try:
            code = context["symbol"] or "000021.SZ"
            context["stock_states"] = _stock_context_for_agent(code)
            value_ctx = _value_context_for_agent(code)
            context["stock_states"].update(value_ctx)
            context["value_prompt_pack"] = True
            context["value_payload"] = {
                "stock_code": code,
                "stock_name": context["stock_states"].get("stock_name", code),
                "theme_info": context["stock_states"].get("industry_name", ""),
                "target_businesses": context["stock_states"].get("industry_name", ""),
                "context": context["stock_states"].get("stock_states", {}),
                "capital_flow": context["stock_states"].get("capital_flow", {}),
                "market_data": context.get("market_data", {}),
                "main_business": context["stock_states"].get("main_business", "【待接入】主营业务描述"),
                "latest_financial_report": context["stock_states"].get("latest_financial_report", {}),
                "annual_report_2024": context["stock_states"].get("annual_report_2024", {}),
                "top10_holders": context["stock_states"].get("top10_holders", []),
                "search_data": context["stock_states"].get("search_data", {}),
            }
        except Exception:
            context["stock_states"] = {}
            context["value_prompt_pack"] = False

    # 非价值问题但有股票代码（如代词解析）：为 stock_checkup 场景预取基础数据
    elif symbol and not context.get("value_prompt_pack"):
        try:
            context["stock_states"] = _stock_context_for_agent(symbol)
        except Exception:
            context["stock_states"] = {}

    # ── 统一入口：转发到 agently 场景化多 Agent 链 ──────────────────────────
    return handle(query.message, context)


def _value_context_for_agent(symbol: str) -> dict[str, Any]:
    """从外部研究证据层提取价值分析专用上下文。"""
    as_of_date = _latest_fundamental_as_of_date()
    top10_holders = _load_top10_holders_context(symbol, as_of_date)
    try:
        evidence = build_external_research_evidence(symbol, as_of_date)
    except Exception:
        return {
            "main_business": "",
            "latest_financial_report": {},
            "annual_report_2024": {},
            "top10_holders": top10_holders,
            "search_data": {
                "status": "placeholder",
                "source": "local_market_views",
                "latest_report": {},
                "rating_distribution": {},
                "target_price_count": 0,
                "digest_items": [],
                "policy_event_notes": [],
            },
        }

    company_profile = evidence.get("company_profile", {})
    financial_trend = evidence.get("financial_trend", {})
    market_views = evidence.get("market_views", {})
    period_rows = financial_trend.get("period_rows", [])

    latest_report = period_rows[0] if period_rows else {}
    annual_2024 = next(
        (r for r in period_rows if "2024" in str(r.get("report_period", ""))),
        {},
    )

    return {
        "main_business": company_profile.get("main_business", ""),
        "latest_financial_report": latest_report,
        "annual_report_2024": annual_2024,
        "top10_holders": top10_holders,
        "search_data": _build_search_data_context(market_views),
    }


def _stock_context_for_agent(symbol: str) -> dict[str, Any]:
    """从统一快照 CSV 提取个股状态，供 Agent 场景编排与 value 增强消费。"""
    unified_map, _ = _latest_unified_snapshot_rows()
    row = unified_map.get(symbol.strip().upper(), {}) if unified_map else {}
    if not row:
        return {
            "stock_name": symbol,
            "industry_name": "",
            "stock_states": {},
            "ef_count": 0,
        }
    return {
        "stock_name": str(row.get("stock_name", "")).strip() or symbol,
        "industry_name": str(row.get("sw_l1", "")).strip(),
        "stock_states": {
            "mn1": str(row.get("mn1_state_hex", "")).strip(),
            "w1": str(row.get("w1_state_hex", "")).strip(),
            "d1": str(row.get("d1_state_hex", "")).strip(),
            "mn1_score": row.get("mn1_state_score", ""),
            "w1_score": row.get("w1_state_score", ""),
            "d1_score": row.get("d1_state_score", ""),
        },
        "ef_count": int(row.get("ef_count", 0) or 0),
        "capital_flow": {
            "status": str(row.get("moneyflow_status", "")).strip(),
            "confirmed": bool(row.get("moneyflow_confirmed")),
            "divergence": bool(row.get("moneyflow_divergence")),
            "score": row.get("moneyflow_score", ""),
        },
        "breakout_status": str(row.get("sr_boundary_type", "")).strip(),
        "sustained_days": int(float(row.get("duration_d1_close", 0) or 0)),
        # 以下字段待后续数据源接入，当前留空占位
        "main_business": "",
        "latest_financial_report": {},
        "annual_report_2024": {},
        "top10_holders": [],
        "search_data": {},
    }


def _llm_required_failure_response(query: ChatQuery) -> dict[str, Any] | None:
    if not _requires_managed_llm(query):
        return None
    if not _deepseek_enabled():
        return {
            "answer": "当前这类问题优先走 Agently 架构的大模型回答，但服务器未检测到可用的模型配置，以下内容将回退为规则摘要。",
            "why": "价值分析、市场解释和行业方向属于高价值解释问题。当前 Agently 模型链路未就绪，所以只能提供带说明的规则回退结果。",
            "multi_cycle_view": "这不是结构判断失败，而是大模型链路未就绪；下面的内容仍可作为基础研究摘要阅读。",
            "single_cycle_position": "当模型恢复后，这类问题会重新回到大模型优先回答。",
            "avoid": "先不要把“规则回退”误解成模型回答；它只是保底结果。",
            "next_actions": [],
            "sources": ["agently_deepseek", "rule_fallback"],
            "freshness_note": "当前未检测到可用的 Agently 模型配置，已触发规则回退。",
            "remembered_stock_code": _chat_stock_code(query),
            "remembered_email": _chat_email(query),
            "mode_used": "chat",
            "provider": "agently_deepseek",
            "enhancement_used": False,
        }
    return {
        "answer": "当前这类问题优先走 Agently 架构的大模型回答，但本次模型调用失败，以下内容将回退为规则摘要。",
        "why": "价值分析、市场解释和行业方向已改为 Agently 模型优先；当 Agently 返回异常、超时或结构化输出失败时，不再静默冒充模型回答。",
        "multi_cycle_view": "当前失败只说明 Agently 模型链路异常，不代表多周期环境本身有问题；下面仍会提供保底规则摘要。",
        "single_cycle_position": "请稍后重试；如果持续失败，应检查 Agently 运行时、模型配置和 JSON 输出合同。",
        "avoid": "先不要把这个失败提示误解成市场或个股结论；它是在解释为什么当前结果属于规则回退。",
        "next_actions": [],
        "sources": ["agently_deepseek", "rule_fallback"],
        "freshness_note": "Agently 模型调用失败，已切换到规则回退结果。",
        "remembered_stock_code": _chat_stock_code(query),
        "remembered_email": _chat_email(query),
        "mode_used": "chat",
        "provider": "agently_deepseek",
        "enhancement_used": False,
    }


def _chat_answer(query: ChatQuery) -> dict[str, Any]:
    """基于用户问题调用现有数据返回回答。"""
    msg = query.message.strip()
    msg_lower = msg.lower()
    mode = "agent" if str(query.mode or "").lower() == "agent" else "chat"

    llm_result = _llm_chat_answer(query)
    if llm_result:
        return _enhance_result_defaults(
            llm_result,
            query,
            next_actions=llm_result.get("next_actions", []),
            sources=llm_result.get("sources", []),
            provider=llm_result.get("provider", "agently_deepseek"),
        )

    # 复合意图检测：rule_based 路径拦截前，先检查是否是盯盘+行业等复合场景
    if not query.use_llm and _has_compound_intent(msg_lower):
        fake = ChatQuery(
            message=query.message,
            page_context=query.page_context,
            stock_code=query.stock_code,
            session_id=query.session_id,
            session_context=query.session_context,
            mode=query.mode,
            use_llm=True,
        )
        llm_result = _llm_chat_answer(fake)
        if llm_result:
            return llm_result

    llm_required_failure = _llm_required_failure_response(query)
    if llm_required_failure:
        return llm_required_failure

    watch_command = _detect_watch_command(query)
    if watch_command is not None:
        if watch_command.get("needs_stock_code"):
            return {
                "answer": "我可以帮你建立盯盘任务，但还需要你给出 6 位股票代码。",
                "why": "盯盘指令至少需要明确跟踪对象，才能绑定后续提醒条件。",
                "multi_cycle_view": "盯盘本质上是在多周期环境里持续观察一只股票是否进入你关心的状态。",
                "single_cycle_position": "先明确股票，再判断是盯周线关键位、D1 支撑，还是长期跟踪。",
                "avoid": "先不用重复描述条件，先把股票代码补完整。",
                "next_actions": [{"label": "打开研究页", "url": "/research?stock_code=000021.SZ"}],
                "sources": ["watch_command"],
                "freshness_note": "",
                "remembered_stock_code": "",
                "remembered_email": watch_command.get("email", ""),
                "mode_used": mode,
            }
        if not watch_command.get("email"):
            return {
                "answer": f"我已经识别到你想盯 {watch_command['stock_code']}，但还缺一个接收提醒的邮箱。",
                "why": "邮件是当前唯一稳定的外部通知通道，没有邮箱就无法把盯盘信号发给你。",
                "multi_cycle_view": "盯盘条件会围绕多周期环境展开，比如周线关键位突破、行业共振、或大周期结构变化。",
                "single_cycle_position": "当前先把提醒通道补齐，后续再按你指定的单周期位置条件触发通知。",
                "avoid": "先不用重复发送股票代码或条件，直接补邮箱即可。",
                "next_actions": [{"label": "打开执行页", "url": "/watchlist"}],
                "sources": ["watch_command"],
                "freshness_note": "",
                "remembered_stock_code": watch_command["stock_code"],
                "remembered_email": "",
                "mode_used": mode,
            }
        record = _register_watch_command(watch_command)
        return {
            "answer": f"已为 {record['stock_code']} 建立盯盘任务，后续会按「{record['note']}」发邮件到 {record['email']}。",
            "why": "当前指令已被结构化写入盯盘账本，后续由后台任务按条件检查并触发提醒。",
            "multi_cycle_view": "这类提醒会优先检查多周期环境是否进入你指定的条件，例如周线关键位突破、行业共振或大周期共振变化。",
            "single_cycle_position": "邮件提醒不会盲发，而是结合当前单周期是否进入刚突破、跌破支撑或持续走弱等位置来触发。",
            "avoid": "暂时不用反复提交同一条命令；后续同日同条件会自动去重。",
            "next_actions": [
                {"label": "打开执行页", "url": "/watchlist"},
                {"label": "打开研究页", "url": f"/research?stock_code={record['stock_code']}"},
            ],
            "sources": ["watch_command_ledger"],
            "freshness_note": f"盯盘任务创建日期为 {record['valid_from']}，默认有效至 {record['valid_to']}。",
            "remembered_stock_code": record["stock_code"],
            "remembered_email": record["email"],
            "mode_used": "agent",
            "task_card": {
                "title": "任务确认",
                "task_type": "盯盘提醒",
                "stock_code": record["stock_code"],
                "trigger_type": record["trigger_type"],
                "email": record["email"],
                "valid_from": record["valid_from"],
                "valid_to": record["valid_to"],
                "status": record["status"],
                "note": record["note"],
            },
        }

    if mode == "agent":
        stock_code = _chat_stock_code(query)
        if stock_code:
            return {
                "answer": f"当前是任务模式。我可以继续围绕 {stock_code} 帮你建立盯盘、长期跟踪，或直接跳到更合适的研究视图。",
                "why": "任务模式不只回答问题，而是把后续动作接下来，例如记住对象、建立提醒、收盘后检查条件并发邮件。",
                "multi_cycle_view": "任务模式下仍先看多周期环境：大周期是否支持、周线是否跟上、日线是否只是局部噪音，这决定提醒条件该设在 W1 还是 D1。",
                "single_cycle_position": "如果当前更像刚突破，就更适合设关键位提醒；如果已经高位延展，就更适合设走弱或跌破支撑提醒。",
                "avoid": "先不要把任务模式理解成自动交易。当前只做研究任务、盯盘任务和提醒，不替你下单。",
                "next_actions": [
                    {"label": "打开价值研究组合", "url": f"/research?stock_code={stock_code}&render_profile=value"},
                    {"label": "打开标准研究页", "url": f"/research?stock_code={stock_code}"},
                    {"label": f"盯盘 {stock_code}", "url": "#watch-command"},
                ],
                "sources": ["session_context", "watch_command"],
                "freshness_note": "任务模式当前可执行的动作以盯盘、长期跟踪和邮件提醒为主。",
                "remembered_stock_code": stock_code,
                "remembered_email": _chat_email(query),
                "mode_used": mode,
            }
        return {
            "answer": "当前是任务模式。我更适合接任务，而不是只做解释。",
            "why": "你可以把股票和动作一起交给我，比如长期跟踪、周线关键位提醒、跌破支撑提醒，后续由系统持续检查并发邮件。",
            "multi_cycle_view": "任务模式依然以多周期为底座：先分清你关心的是大周期环境变化，还是周线 / 日线位置触发。",
            "single_cycle_position": "如果你已经有具体股票，就把股票代码和提醒条件一起说出来，我会直接进入可执行任务。",
            "avoid": "先不要只问泛问题。任务模式更适合明确对象、条件和邮箱。",
            "next_actions": [
                {"label": "打开执行页", "url": "/watchlist"},
                {"label": "打开研究页", "url": "/research?stock_code=000021.SZ"},
            ],
            "sources": ["watch_command"],
            "freshness_note": "任务模式当前支持盯盘命令、长期跟踪和邮件提醒的最小闭环。",
            "remembered_stock_code": "",
            "remembered_email": _chat_email(query),
            "mode_used": mode,
        }

    # 问题 1：市场/能不能做
    if _is_market_question(msg_lower):
        market = _market_analysis_data()
        return {
            "answer": market["stance"],
            "why": market["broad_summary"],
            "multi_cycle_view": "先看 MN1/W1/D1 是否同步共振。当前更像大周期未全面同步、日线局部改善的环境，不宜把局部转暖直接外推成全面进攻。",
            "single_cycle_position": "当前单周期节奏更偏日线活跃推进与局部修复，适合先观察结构延续性，再决定是否从等待切到试错。",
            "avoid": market["avoid_now"],
            "next_actions": [
                {"label": "打开市场页", "url": "/market"},
            ],
            "sources": ["market_phase", "daily_snapshot"],
            "freshness_note": f"市场阶段与快照按 {market['phase']['date']} 口径展示。",
            "remembered_stock_code": _chat_stock_code(query),
            "remembered_email": _chat_email(query),
            "mode_used": mode,
        }

    # 问题 2：行业/方向
    if _is_industry_question(msg_lower):
        industry = _industry_rotation_data()
        focus_code = _chat_stock_code(query)
        focus_industry_name = ""
        focus_main_business = ""
        focus_main_products = ""
        try:
            if focus_code:
                focus_profile = _load_company_profile(focus_code)
                if focus_profile:
                    focus_industry_name = str(focus_profile.get("sw_l1") or "").strip()
                    focus_main_business = str(focus_profile.get("main_business") or "").strip()
                    focus_main_products = str(
                        focus_profile.get("main_product_types") or focus_profile.get("main_product_names") or ""
                    ).strip()
        except Exception:
            focus_profile = None
        if not focus_industry_name:
            try:
                if focus_code:
                    foundation_db = find_foundation_db(str(date.today()))
                    if foundation_db:
                        import duckdb as _duck
                        con = _duck.connect(str(foundation_db), read_only=True)
                        try:
                            row = con.execute(
                                "SELECT sw_l1_name FROM foundation WHERE symbol = ? LIMIT 1",
                                [_canonical_stock_code(focus_code)],
                            ).fetchone()
                            if row and row[0]:
                                focus_industry_name = str(row[0]).strip()
                        finally:
                            con.close()
            except Exception:
                focus_industry_name = ""

        top = ", ".join(row["industry"] for row in industry.get("top_industries", [])[:3])
        if focus_code and focus_industry_name:
            details = ""
            if focus_main_products:
                details = f" 它的主要产品/业务方向包括：{focus_main_products}。"
            elif focus_main_business:
                details = f" 它的主营业务描述是：{focus_main_business}。"
            answer = (
                f"{focus_code} 对应的所属行业按现有口径为 {focus_industry_name}；"
                f"当前行业覆盖 {industry.get('industry_count', '?')} 个，建议先看：{top}。{details}"
            )
        else:
            answer = f"当前行业覆盖 {industry.get('industry_count', '?')} 个，建议先看：{top}。"

        return {
            "answer": answer,
            "why": "多周期结构并非全市场共振，更适合做选择题；如果已锁定标的，就优先看该标的所在行业的共振位置。",
            "multi_cycle_view": "行业回答先看大级别环境是否支持扩散，再看行业自身是否进入共振。当前更适合先做方向缩圈，而不是把所有行业都当成同级机会。",
            "single_cycle_position": "行业当前更应判断是起势初期、扩散中段还是高位延展。先找结构刚改善且承接清晰的方向，不急于追已经高位扩张的分支。",
            "avoid": "暂时不要平均用力看所有行业。",
            "next_actions": [
                {"label": "打开行业页", "url": "/industry"},
                {"label": f"打开 {focus_code or '标的'} 研究页", "url": f"/research?stock_code={focus_code or ''}"},
            ],
            "sources": ["industry_rotation", "ifind_industry_chain_profile"],
            "freshness_note": f"行业回答按 {industry.get('date', str(date.today()))} 快照展示。",
            "remembered_stock_code": focus_code or _chat_stock_code(query),
            "remembered_email": _chat_email(query),
            "mode_used": mode,
        }

    # 问题 3.1：价值分析 / 深度价值投研
    if _is_value_question(msg):
        code = _chat_stock_code(query) or "000021.SZ"
        value_summary = _value_research_chat_summary(code)
        return {
            "answer": (value_summary or {}).get("answer") or f"可以，我会把 {code} 切到价值组合研究视图，用行业、公司、财务、估值和公开市场预期的组合框架来读。",
            "why": (value_summary or {}).get("why") or "价值分析不是恢复长报告，而是在当前研究链路里，把 8 大块中可保留的部分按合规边界组合输出。",
            "multi_cycle_view": (value_summary or {}).get("multi_cycle_view") or "价值分析也不会绕开多周期环境。先看 MN1/W1/D1 是否支持，再决定行业和公司层面的结论是否有结构支撑。",
            "single_cycle_position": (value_summary or {}).get("single_cycle_position") or "单周期上仍要区分刚突破、推进中段和高位延展。同样的公司基本面，在不同位置上的概率与盈亏比不同。",
            "avoid": (value_summary or {}).get("avoid") or "先不用把价值分析理解成买卖建议；估值、盈利趋势和公开市场观点都只作为研究参考。",
            "next_actions": [
                {"label": "打开价值研究组合", "url": f"/research?stock_code={code}&render_profile=value"},
                {"label": "打开标准研究页", "url": f"/research?stock_code={code}"},
                {"label": f"盯盘 {code}", "url": "#watch-command"},
            ],
            "sources": ["research_evidence", "valuation_reference", "market_views"],
            "freshness_note": (value_summary or {}).get("freshness_note") or "价值组合会复用当前已加载的研究证据、财务趋势、估值参考和公开市场观点数据。",
            "remembered_stock_code": code,
            "remembered_email": _chat_email(query),
            "mode_used": mode,
        }

    # 问题 3：个股/股票
    if any(k in msg_lower for k in ("股票", "个股", "看一只", "怎么看", "000", "300", "600")):
        code = _chat_stock_code(query) or "000021.SZ"
        match = re.search(r'(\d{6}\.?(SZ|sh|SH|sz)?)', msg)
        if match:
            raw = match.group(1)
            if '.' not in raw:
                raw += '.SZ'
            code = raw.upper()
        return {
            "answer": f"我可以帮你查看 {code} 的多周期结构、策略适配和证据完整度。",
            "why": "个股判断需要先看 State 结构、再看策略适配、最后验证证据链。",
            "multi_cycle_view": "个股先看 MN1/W1/D1 的相互关系：大周期是否支持，周线是否跟上，日线是独立走强还是只是局部噪音。",
            "single_cycle_position": "单周期上要区分刚突破、推进中段、高位延展还是等待确认。同样是强结构，不同位置的概率和盈亏比完全不同。",
            "avoid": "不要只看单一周期信号就下结论。",
            "next_actions": [
                {"label": "打开研究页", "url": f"/research?stock_code={code}"},
                {"label": "看价值组合", "url": f"/research?stock_code={code}&render_profile=value"},
                {"label": f"盯盘 {code}", "url": "#watch-command"},
            ],
            "sources": ["research_evidence"],
            "freshness_note": "个股研究会结合当前已加载的研究证据与观察数据。",
            "remembered_stock_code": code,
            "remembered_email": _chat_email(query),
            "mode_used": mode,
        }

    # 问题 4：导航/先去哪
    if any(k in msg_lower for k in ("去哪", "先去", "导航", "开始", "第一次", "从哪")):
        return {
            "answer": "建议按「市场 → 行业 → 研究/执行」的顺序看。",
            "why": "先确认大环境是否支持，再缩小到方向，最后看个股。",
            "multi_cycle_view": "导航顺序本身就是先看多周期环境，再看局部方向，最后才看个股执行。",
            "single_cycle_position": "进入个股前，优先确认当前单周期是等待、试错还是顺风推进，不要跳过位置判断直接下钻。",
            "avoid": "不要跳过市场判断直接看个股。",
            "next_actions": [
                {"label": "打开市场页", "url": "/market"},
                {"label": "打开行业页", "url": "/industry"},
                {"label": "打开执行页", "url": "/watchlist"},
            ],
            "sources": ["page_context"],
            "freshness_note": "",
            "remembered_stock_code": _chat_stock_code(query),
            "remembered_email": _chat_email(query),
            "mode_used": mode,
        }

    # 默认回答
    return {
        "answer": "当前更适合做结构跟踪，不适合把局部转暖直接外推成全面进攻。",
        "why": "多周期结构并非同步强势，当前更偏局部改善。",
        "multi_cycle_view": "先看大周期共振是否成立，再判断周线和日线是不是在同一个方向上推进。",
        "single_cycle_position": "当前更像局部修复和中段推进，不宜把所有样本都当成刚起步机会。",
        "avoid": "暂时少看高位延展样本，不把所有突破都当成早期机会。",
        "next_actions": [
            {"label": "打开市场页", "url": "/market"},
        ],
        "sources": ["market_phase"],
        "freshness_note": "",
        "remembered_stock_code": _chat_stock_code(query),
        "remembered_email": _chat_email(query),
        "mode_used": mode,
    }


@app.post("/api/strategy/preview")
def strategy_preview(request: Request, payload: dict[str, Any] | None = None) -> JSONResponse:
    """即时预览：基于 daily_snapshot 计算条件命中数，不连 DuckDB，<50ms。"""
    if payload is None:
        payload = {}
    entry_conditions = payload.get("conditions", [])
    filter_conditions = payload.get("filters", [])
    exit_conditions = payload.get("exit_conditions", [])

    snapshot = _latest_daily_snapshot()
    stocks = snapshot.get("stocks", [])
    total = len(stocks)
    today = snapshot.get("date", str(date.today()))

    entry_hits = _count_hits(stocks, entry_conditions)
    filtered_hits = _count_hits(stocks, entry_conditions + filter_conditions)
    all_hits = _count_hits(stocks, entry_conditions + filter_conditions + exit_conditions)

    return JSONResponse(content={
        "date": today,
        "total": total,
        "entry_hits": entry_hits,
        "filtered_hits": filtered_hits,
        "all_hits": all_hits,
    })


def _latest_daily_snapshot() -> dict[str, Any]:
    snap_dir = ROOT / "outputs" / "daily_snapshot"
    files = sorted(snap_dir.glob("daily_snapshot_*.json"))
    if not files:
        return {}
    try:
        return json.loads(files[-1].read_text())
    except Exception:
        return {}


def _count_hits(stocks: list[dict[str, Any]], conditions: list[dict[str, Any]]) -> int:
    return sum(1 for s in stocks if _matches_all(s, conditions))


def _matches_all(stock: dict[str, Any], conditions: list[dict[str, Any]]) -> bool:
    return all(_matches(stock, c) for c in conditions)


def _matches(stock: dict[str, Any], condition: dict[str, Any]) -> bool:
    t = condition.get("type")
    if t == "ef_count":
        ef = stock.get("ef", 0)
        compare = condition.get("compare", ">=")
        value = int(condition.get("value", 0))
        if compare == ">=":
            return ef >= value
        if compare == ">":
            return ef > value
        if compare == "==":
            return ef == value
        if compare == "<=":
            return ef <= value
        if compare == "<":
            return ef < value
        return False
    if t == "state_filter":
        values = condition.get("values", [])
        if not values:
            return True
        target = condition.get("target", "d1")
        hex_idx = {"mn1": 0, "w1": 1, "d1": 2}
        idx = hex_idx.get(target, 2)
        stock_hex = stock.get("hex", ["", "", ""])
        return idx < len(stock_hex) and stock_hex[idx] in values
    if t == "price_cross":
        direction = condition.get("direction", "above")
        ma_period = int(condition.get("ma_period", 20))
        p = stock.get("p", 0) or 0
        sr = stock.get("sr", {})
        level = sr.get("w" if ma_period >= 50 else "d", [0, 0])
        if not level or len(level) < 2:
            return False
        support, resistance = level[0], level[1]
        if support is None or resistance is None:
            return False
        if direction == "above":
            return p > resistance
        return p < support
    if t == "volume_ratio":
        # daily_snapshot 无原始成交量，暂不支持即时预览
        return False
    if t == "industry_filter":
        # daily_snapshot 无行业数据，暂不支持即时预览
        return False
    if t == "price_change":
        # daily_snapshot 无涨跌幅数据，暂不支持即时预览
        return False
    if t == "stop_loss":
        # 需要入场价，daily_snapshot 不支持
        return False
    return True


@app.get("/journal", response_class=HTMLResponse)
def journal_page(request: Request) -> HTMLResponse:
    profile = get_current_profile(request)
    username = profile.get("username", "web_user")

    from hermass_platform.trade_journal import get_filters, get_trade_stats, list_trades

    trades = list_trades(username, page=1)
    stats = get_trade_stats(username)
    filters = get_filters(username)

    return templates.TemplateResponse(
        request,
        "journal.html",
        {
            "request": request,
            "today": str(date.today()),
            "current_user": profile,
            "journal": {
                "trades": trades["trades"],
                "total": trades["total"],
                "page": trades["page"],
                "pages": trades["pages"],
                "stats": stats,
                "filters": filters,
            },
        },
    )


@app.post("/api/journal/add")
def journal_add(request: Request, payload: dict[str, Any] | None = None) -> JSONResponse:
    profile = get_current_profile(request)
    username = profile.get("username", "web_user")
    payload = payload or {}

    from hermass_platform.trade_journal import add_trade

    trade = add_trade(
        username=username,
        trade_date=payload.get("trade_date") or str(date.today()),
        stock_code=payload.get("stock_code", ""),
        stock_name=payload.get("stock_name", ""),
        direction=payload.get("direction", "long"),
        entry_price=float(payload.get("entry_price", 0)),
        exit_price=float(payload["exit_price"]) if payload.get("exit_price") is not None else None,
        strategy_id=payload.get("strategy_id", ""),
        stop_loss=float(payload["stop_loss"]) if payload.get("stop_loss") is not None else None,
        mn1_state_name=payload.get("mn1_state_name"),
        note=payload.get("note", ""),
    )
    return JSONResponse(content={"ok": True, "trade": trade})


@app.get("/api/journal/list")
def journal_list(
    request: Request,
    page: int = 1,
    strategy: str = "",
    state: str = "",
) -> JSONResponse:
    profile = get_current_profile(request)
    username = profile.get("username", "web_user")

    from hermass_platform.trade_journal import list_trades

    data = list_trades(username, strategy_filter=strategy, state_filter=state, page=page)
    return JSONResponse(content=data)


@app.get("/api/journal/stats")
def journal_stats(request: Request) -> JSONResponse:
    profile = get_current_profile(request)
    username = profile.get("username", "web_user")

    from hermass_platform.trade_journal import get_trade_stats

    return JSONResponse(content=get_trade_stats(username))


@app.delete("/api/journal/{trade_id}")
def journal_delete(request: Request, trade_id: int) -> JSONResponse:
    profile = get_current_profile(request)
    username = profile.get("username", "web_user")

    from hermass_platform.trade_journal import delete_trade

    return JSONResponse(content={"ok": delete_trade(trade_id, username)})


@app.post("/api/chat/query")
def chat_query(request: Request, query: ChatQuery) -> JSONResponse:
    profile = get_current_profile(request)
    user_id = profile.get("username", "web_user")

    # Phase 1：session 管理（创建/复用 + 持久化用户输入）
    try:
        from hermass_platform.chat.conversation_manager import get_conversation_manager
        conv_mgr = get_conversation_manager()
        if not query.session_id:
            session = conv_mgr.get_or_create(user_id, query.session_id)
            query.session_id = session.session_id
        else:
            session = conv_mgr.get_or_create(user_id, query.session_id)
        # 回填会话上下文：将 store 中已提取的 remembered_stock_code 等注入 query
        # 保证 _chat_stock_code() 在第二轮"它"提问时能找到历史股票代码
        if session.context and not query.session_context:
            query.session_context = dict(session.context)
        conv_mgr.add_message(session.session_id, "user", query.message)
    except Exception:
        # 会话层失败不阻塞主链路，降级为无状态
        if not query.session_id:
            query.session_id = ""

    try:
        result = _chat_answer(query)
        if result.get("provider") is None:
            result["provider"] = "rule_based"
        if result.get("enhancement_used") is None:
            result["enhancement_used"] = False
        result["user_id"] = user_id  # 绑定会话到当前用户
        result["session_id"] = query.session_id or ""

        # Phase 1：持久化助手回复（下一轮可读取）
        if query.session_id:
            try:
                intent_meta = result.get("intent")
                intent_str = json.dumps(intent_meta, ensure_ascii=False) if isinstance(intent_meta, dict) else ""
                conv_mgr.add_message(
                    query.session_id, "assistant", result.get("answer", ""), intent=intent_str
                )
            except Exception:
                pass
        return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "answer": "回答出了点问题，重试或直接看页面内容。",
                "why": "",
                "multi_cycle_view": "",
                "single_cycle_position": "",
                "avoid": "",
                "freshness_note": "",
                "next_actions": [{"label": "打开首页", "url": "/"}],
                "sources": [],
                "remembered_stock_code": "",
                "remembered_email": "",
                "mode_used": str(query.mode or "chat").lower(),
                "provider": "rule_based",
                "enhancement_used": False,
                "user_id": user_id,
                "session_id": query.session_id or "",
                "error": str(exc),
            },
        )


FOUNDATION_DELTA_KEYS = {
    "daily_bars": ["stock_code", "date"],
    "weekly_bars": ["stock_code", "period_start"],
    "monthly_bars": ["stock_code", "period_start"],
    "timeframe_bars": ["stock_code", "timeframe", "period_start"],
    "sr_levels": ["stock_code", "timeframe", "period_start"],
    "timeframe_indicators": ["stock_code", "timeframe", "period_start"],
    "d1_d_sr": ["stock_code", "state_date"],
    "d1_w_sr": ["stock_code", "state_date"],
    "d1_mn1_sr": ["stock_code", "state_date"],
    "d1_sr_context": ["stock_code", "state_date"],
    "d1_perspective_state": ["stock_code", "state_date"],
}


WEBSITE_UPLOAD_TARGETS = {
    "state_ef": ("state_cache", "state_ef_{ymd}.json", None),
    "state_duration": ("state_cache", "state_duration_{ymd}.json", None),
    "sr_boundary": ("state_cache", "sr_boundary_{ymd}.json", None),
    "market_phase": ("market_phase", "market_phase_{ymd}.json", "market_phase_latest.json"),
    "market_assets_state": ("market_assets_state", "market_assets_state_{ymd}.json", None),
    "unified_view": ("unified_view", "unified_daily_snapshot_{date}.csv", None),
    "forward_observation": ("forward_observation", "forward_observation_{ymd}.json", None),
    "macro_chain_prior": ("macro_chain_prior", "macro_chain_prior_{ymd}.json", "macro_chain_prior_latest.json"),
    "industry_rotation": ("industry_rotation", "industry_rotation_{ymd}.json", None),
}


def _normalize_upload_date(date_str: str) -> str:
    if re.fullmatch(r"\d{8}", date_str or ""):
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return date_str


def _merge_foundation_delta(delta_db: Path, date_str: str) -> dict[str, Any]:
    normalized_date = _normalize_upload_date(date_str)
    foundation_db = find_foundation_db(normalized_date) or find_foundation_db()
    if not foundation_db:
        raise FileNotFoundError("foundation DB not found on server")

    safe_delta = str(delta_db).replace("'", "''")
    merged: dict[str, Any] = {
        "date": normalized_date,
        "foundation_db": str(foundation_db),
        "tables": {},
    }
    con = duckdb.connect(str(foundation_db))
    try:
        con.execute(f"ATTACH '{safe_delta}' AS delta (READ_ONLY)")
        for table, keys in FOUNDATION_DELTA_KEYS.items():
            exists = con.execute(
                """
                SELECT count(*)
                FROM information_schema.tables
                WHERE table_catalog = 'delta' AND table_schema = 'main' AND table_name = ?
                """,
                [table],
            ).fetchone()[0]
            if not exists:
                continue

            incoming = con.execute(f"SELECT count(*) FROM delta.{table}").fetchone()[0]
            if not incoming:
                merged["tables"][table] = {"deleted": 0, "inserted": 0, "after": 0}
                continue

            join_sql = " AND ".join(f"target.{key} = source.{key}" for key in keys)
            before = con.execute(
                f"""
                SELECT count(*)
                FROM {table} target
                WHERE EXISTS (
                  SELECT 1 FROM delta.{table} source
                  WHERE {join_sql}
                )
                """
            ).fetchone()[0]
            con.execute(
                f"""
                DELETE FROM {table} target
                WHERE EXISTS (
                  SELECT 1 FROM delta.{table} source
                  WHERE {join_sql}
                )
                """
            )
            con.execute(f"INSERT INTO {table} SELECT * FROM delta.{table}")
            after = con.execute(
                f"""
                SELECT count(*)
                FROM {table} target
                WHERE EXISTS (
                  SELECT 1 FROM delta.{table} source
                  WHERE {join_sql}
                )
                """
            ).fetchone()[0]
            merged["tables"][table] = {"deleted": before, "inserted": incoming, "after": after}

        con.execute(
            """
            UPDATE foundation_run_log
            SET latest_date = greatest(latest_date, CAST(? AS DATE)),
                generated_at = ?
            """,
            [normalized_date, datetime.now().isoformat(timespec="seconds")],
        )
    finally:
        con.close()
    return merged


def _json_status(path: Path, date_key: str = "date") -> dict[str, Any]:
    payload = _read_json(path)
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    return {
        "path": str(path),
        "exists": path.exists(),
        "size": path.stat().st_size if path.exists() else 0,
        "date": str(payload.get(date_key, "")) if isinstance(payload, dict) else "",
        "row_count": len(rows) if isinstance(rows, list) else 0,
        "signal_count": payload.get("signal_count", len(rows)) if isinstance(payload, dict) else 0,
    }


def _json_list_status(path: Path, date_key: str = "state_date") -> dict[str, Any]:
    payload = _read_json(path)
    rows = payload if isinstance(payload, list) else []
    dates = [
        str(row.get(date_key, ""))
        for row in rows
        if isinstance(row, dict) and row.get(date_key)
    ]
    return {
        "path": str(path),
        "exists": path.exists(),
        "size": path.stat().st_size if path.exists() else 0,
        "date": max(dates) if dates else "",
        "row_count": len(rows),
    }


def _csv_status(path: Path, expected_date: str) -> dict[str, Any]:
    row_count = 0
    if path.exists():
        try:
            with path.open("r", encoding="utf-8-sig") as fh:
                row_count = max(0, sum(1 for _ in fh) - 1)
        except Exception:
            row_count = 0
    return {
        "path": str(path),
        "exists": path.exists(),
        "size": path.stat().st_size if path.exists() else 0,
        "date": expected_date if path.exists() else "",
        "row_count": row_count,
    }


def _foundation_status(date_str: str) -> dict[str, Any]:
    db_path = find_foundation_db(date_str) or find_foundation_db()
    status: dict[str, Any] = {
        "path": str(db_path) if db_path else "",
        "exists": bool(db_path and db_path.exists()),
        "size": db_path.stat().st_size if db_path and db_path.exists() else 0,
        "latest_date": "",
        "daily_rows": 0,
        "state_rows": 0,
    }
    if not db_path:
        return status
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        latest = con.execute("SELECT max(state_date) FROM d1_perspective_state").fetchone()[0]
        daily_rows = con.execute(
            "SELECT count(*) FROM daily_bars WHERE date = CAST(? AS DATE)",
            [date_str],
        ).fetchone()[0]
        state_rows = con.execute(
            "SELECT count(*) FROM d1_perspective_state WHERE state_date = CAST(? AS DATE)",
            [date_str],
        ).fetchone()[0]
        status.update({
            "latest_date": str(latest or ""),
            "daily_rows": daily_rows,
            "state_rows": state_rows,
        })
    finally:
        con.close()
    return status


@app.get("/api/admin/data-sync-status")
def admin_data_sync_status(date: str = "") -> JSONResponse:
    """Machine-readable data sync status for post-upload acceptance checks."""
    normalized_date = _normalize_upload_date(date or datetime.now().strftime("%Y%m%d"))
    compact_date = normalized_date.replace("-", "")
    outputs = ROOT / "outputs"
    strategy_dir = outputs / "strategy_signals"
    delta_path = outputs / f"foundation_delta_{compact_date}" / "foundation_delta.duckdb"
    state_dir = outputs / "state_cache"
    market_phase_dir = outputs / "market_phase"
    market_assets_dir = outputs / "market_assets_state"
    unified_dir = outputs / "unified_view"
    forward_dir = outputs / "forward_observation"
    payload = {
        "ok": True,
        "expected_date": normalized_date,
        "daily_snapshot": _json_status(outputs / "daily_snapshot.json"),
        "strategy_signal_daily": _json_status(strategy_dir / f"strategy_signal_daily_{compact_date}.json"),
        "strategy_signal_latest": _json_status(strategy_dir / "strategy_signal_daily_latest.json"),
        "state_cache": {
            "state_ef": _json_status(state_dir / f"state_ef_{compact_date}.json"),
            "state_duration": _json_status(state_dir / f"state_duration_{compact_date}.json"),
            "sr_boundary": _json_status(state_dir / f"sr_boundary_{compact_date}.json"),
        },
        "market_phase": _json_status(market_phase_dir / f"market_phase_{compact_date}.json"),
        "market_assets_state": _json_list_status(
            market_assets_dir / f"market_assets_state_{compact_date}.json"
        ),
        "unified_view": _csv_status(
            unified_dir / f"unified_daily_snapshot_{normalized_date}.csv",
            normalized_date,
        ),
        "forward_observation": _json_status(forward_dir / f"forward_observation_{compact_date}.json"),
        "macro_chain_prior": _json_status(outputs / "macro_chain_prior" / "macro_chain_prior_latest.json"),
        "foundation_delta": {
            "path": str(delta_path),
            "exists": delta_path.exists(),
            "size": delta_path.stat().st_size if delta_path.exists() else 0,
        },
        "foundation_db": _foundation_status(normalized_date),
    }
    return JSONResponse(content=payload)


@app.post("/api/admin/upload-data")
async def admin_upload_data(
    file: UploadFile,
    type: str = Form(""),
    date: str = Form(""),
    upload_id: str = Form(""),
    chunk_index: str = Form(""),
    total_chunks: str = Form(""),
    chunk_hash: str = Form(""),
) -> JSONResponse:
    """接收 pipeline 产出的数据文件，写入 outputs/ 目录。支持 gzip 压缩传输。"""
    if not type:
        return JSONResponse(content={"ok": False, "error": "missing type"}, status_code=400)

    raw = await file.read()
    if not raw:
        return JSONResponse(content={"ok": False, "error": "empty file"}, status_code=400)

    filename = file.filename or ""
    if filename.endswith(".gz"):
        import gzip as _gz
        raw = _gz.decompress(raw)

    dest_dir = ROOT / "outputs"
    if type == "foundation":
        dest_dir = dest_dir / f"p116_foundation_{date}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / "p116_foundation.duckdb"
    elif type == "snapshot":
        dest_path = dest_dir / "daily_snapshot.json"
    elif type == "strategy_signal_daily":
        if not date:
            return JSONResponse(content={"ok": False, "error": "missing date"}, status_code=400)
        dest_dir = dest_dir / "strategy_signals"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"strategy_signal_daily_{date}.json"
    elif type == "foundation_delta":
        if not date:
            return JSONResponse(content={"ok": False, "error": "missing date"}, status_code=400)
        dest_dir = dest_dir / f"foundation_delta_{date}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / "foundation_delta.duckdb"
    elif type == "foundation_chunk":
        upload_id = upload_id or date  # fallback
        chunk_index_str = chunk_index or "0"
        total_chunks_str = total_chunks or "1"
        chunk_hash = chunk_hash or ""
        try:
            chunk_index = int(chunk_index_str)
            total_chunks = int(total_chunks_str)
        except ValueError:
            return JSONResponse(content={"ok": False, "error": "invalid chunk params"}, status_code=400)
        if not upload_id:
            return JSONResponse(content={"ok": False, "error": "missing upload_id"}, status_code=400)
        chunk_dir = ROOT / "tmp" / "upload_chunks" / upload_id
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_path = chunk_dir / f"chunk_{chunk_index}"
        chunk_path.write_bytes(raw)
        if chunk_hash:
            import hashlib as _hl
            if _hl.sha256(raw).hexdigest() != chunk_hash:
                chunk_path.unlink()
                return JSONResponse(content={"ok": False, "error": "chunk hash mismatch"}, status_code=400)
        return JSONResponse(content={"ok": True, "type": type, "chunk_index": chunk_index, "total_chunks": total_chunks})
    elif type == "foundation_merge":
        upload_id = upload_id or date
        total_chunks_str = total_chunks or "1"
        try:
            total_chunks = int(total_chunks_str)
        except ValueError:
            return JSONResponse(content={"ok": False, "error": "invalid total_chunks"}, status_code=400)
        if not upload_id or not date:
            return JSONResponse(content={"ok": False, "error": "missing upload_id or date"}, status_code=400)
        chunk_dir = ROOT / "tmp" / "upload_chunks" / upload_id
        missing = [i for i in range(total_chunks) if not (chunk_dir / f"chunk_{i}").exists()]
        if missing:
            return JSONResponse(content={"ok": False, "error": f"missing chunks: {missing}"}, status_code=400)
        merged = b""
        for i in range(total_chunks):
            merged += (chunk_dir / f"chunk_{i}").read_bytes()
        if filename.endswith(".gz") or not filename:
            import gzip as _gz
            raw = _gz.decompress(merged)
        else:
            raw = merged
        dest_dir = ROOT / "outputs" / f"p116_foundation_{date}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / "p116_foundation.duckdb"
        tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
        tmp_path.write_bytes(raw)
        tmp_path.rename(dest_path)
        import shutil
        shutil.rmtree(chunk_dir, ignore_errors=True)
        return JSONResponse(content={"ok": True, "type": "foundation", "path": str(dest_path), "size": len(raw)})
    elif type in WEBSITE_UPLOAD_TARGETS:
        if not date:
            return JSONResponse(content={"ok": False, "error": "missing date"}, status_code=400)
        normalized_date = _normalize_upload_date(date)
        compact_date = normalized_date.replace("-", "")
        subdir, filename_template, _latest_name = WEBSITE_UPLOAD_TARGETS[type]
        dest_dir = dest_dir / subdir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename_template.format(date=normalized_date, ymd=compact_date)
    else:
        return JSONResponse(content={"ok": False, "error": f"unknown type: {type}"}, status_code=400)

    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
    tmp_path.write_bytes(raw)
    tmp_path.rename(dest_path)
    if type == "strategy_signal_daily":
        latest_path = dest_path.parent / "strategy_signal_daily_latest.json"
        latest_tmp_path = latest_path.with_suffix(latest_path.suffix + ".tmp")
        latest_tmp_path.write_bytes(raw)
        latest_tmp_path.rename(latest_path)
    if type in WEBSITE_UPLOAD_TARGETS:
        latest_name = WEBSITE_UPLOAD_TARGETS[type][2]
        if latest_name:
            latest_path = dest_path.parent / latest_name
            latest_tmp_path = latest_path.with_suffix(latest_path.suffix + ".tmp")
            latest_tmp_path.write_bytes(raw)
            latest_tmp_path.rename(latest_path)

    merged = None
    if type == "foundation_delta":
        try:
            merged = _merge_foundation_delta(dest_path, date)
        except Exception as exc:
            return JSONResponse(
                content={"ok": False, "error": f"merge foundation_delta failed: {exc}"},
                status_code=500,
            )

    return JSONResponse(content={
        "ok": True,
        "type": type,
        "path": str(dest_path),
        "size": len(raw),
        "merged": merged,
    })


# ─── Kill Switch Admin API ──────────────────────────────────────

@app.post("/api/admin/kill-switch")
def admin_kill_switch_activate(request: Request, payload: dict[str, Any] | None = None) -> JSONResponse:
    """激活 Kill Switch，暂停所有自进化功能。"""
    profile = get_current_profile(request)
    if not profile.get("username"):
        return JSONResponse(content={"ok": False, "error": "unauthorized"}, status_code=401)

    from hermass_platform.red_lines import activate_kill_switch

    payload = payload or {}
    result = activate_kill_switch(
        reason=payload.get("reason", "admin_triggered"),
        activated_by=profile.get("username", "admin"),
        duration_hours=payload.get("duration_hours", 24),
    )
    return JSONResponse(content={"ok": True, "kill_switch": result.get("kill_switch", {})})


@app.get("/api/admin/kill-switch/status")
def admin_kill_switch_status(request: Request) -> JSONResponse:
    """查询 Kill Switch 当前状态。"""
    from hermass_platform.red_lines import is_kill_switch_active, get_kill_switch_state

    active = is_kill_switch_active()
    state = get_kill_switch_state()
    return JSONResponse(content={
        "ok": True,
        "active": active,
        "state": state,
    })
