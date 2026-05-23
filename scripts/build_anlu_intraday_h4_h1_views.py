#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import importlib.util
import json
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from hermass_five_cycle_agently_contract import 计算视角状态审计


ROOT = Path(__file__).resolve().parents[1]
HERMASS = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")
STATE_SOURCE = HERMASS / "data/mac_handoff_audit_20260508/source"
RAW_DB = HERMASS / "outputs/p108_blackwolf_ashare_daily_raw_20260518/p108_blackwolf_ashare_daily_raw.duckdb"
PATCH_JSON = ROOT / "fixtures/single_symbol_formula_state_tables.json"
RAW_OUT = ROOT / "data" / "blackwolf_ashare_5m_688107_20260201_20260519.csv"
OUT_JSON = ROOT / "fixtures/anlu_688107_h1_terminal_views_20260201_20260519.json"
OUT_HTML = ROOT / "public" / "anlu_688107_h4_h1.html"
API_BASE = "http://api.fxyz.site"

SYMBOL = "688107.SH"
CODE = "688107"
NAME = "安路科技"
VIEW_START = date(2025, 6, 1)
INTRADAY_START = date(2026, 2, 1)
END = date(2026, 5, 19)
ROW_LIMITS = {"MN1": 12, "W1": 12, "D1": 36, "H4": 36, "H1": 120}
STATE_COMPONENTS = ["compression", "trend", "position", "volatility", "atr_stop", "blp", "tbd", "state_score", "state_hex"]
INDICATOR_COLUMNS = [
    "kaufman_width_20",
    "bb_width_20",
    "bb_width_50",
    "kaufman_width_50",
    "atr_percent",
    "atr_percent_up",
    "atr_percent_up2",
    "adx",
    "plus_di",
    "minus_di",
    "support",
    "resistance",
    "bbp",
    "bbp_1",
    "chandelier_long_stop",
    "chandelier_short_stop",
]
TF_LABELS = {"MN1": "月线", "W1": "周线", "D1": "日线", "H4": "四小时", "H1": "小时"}
VIEW_COLUMNS = {
    "MN1": [("品种", "品种"), ("时间", "时间"), ("MN1state", "月线状态")],
    "W1": [("品种", "品种"), ("时间", "时间"), ("MN1state", "月线状态"), ("W1state", "周线状态")],
    "D1": [("品种", "品种"), ("时间", "时间"), ("MN1state", "月线状态"), ("W1state", "周线状态"), ("D1state", "日线状态")],
    "H4": [("品种", "品种"), ("时间", "时间"), ("MN1state", "月线状态"), ("W1state", "周线状态"), ("D1state", "日线状态"), ("H4state", "四小时状态")],
    "H1": [("品种", "品种"), ("时间", "时间"), ("MN1state", "月线状态"), ("W1state", "周线状态"), ("D1state", "日线状态"), ("H4state", "四小时状态"), ("H1state", "小时状态")],
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
COLUMN_CN = {
    "品种": "品种",
    "时间": "时间",
    "MN1state": "月线状态",
    "W1state": "周线状态",
    "D1state": "日线状态",
    "H4state": "四小时状态",
    "H1state": "小时状态",
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
    base = bits.get("base")
    volatility = bits.get("volatility_bit")
    position = bits.get("position_bit")
    trend = bits.get("trend_bit")
    score = bits.get("score")
    return f"{sign}（底座={base} + 波动={volatility} + 位置={position} + 趋势={trend}）= {score}"


def indicator_text(indicators: dict[str, Any]) -> str:
    parts = []
    for key, label_text in INDICATOR_CN.items():
        if key in indicators:
            parts.append(f"{label_text}={cn_value(indicators.get(key))}")
    return "；".join(parts)


def import_source_module(name: str) -> Any:
    path = STATE_SOURCE / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import state source module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mt4 = import_source_module("mt4_indicators_python")
ea = import_source_module("ea_market_state")


def read_token(use_stdin: bool) -> str:
    if use_stdin:
        token = sys.stdin.read().strip()
        if token:
            return token
    raise RuntimeError("missing token: pass --token-stdin and provide token on stdin")


def request_json(path: str, params: dict[str, str], timeout: int = 60) -> Any:
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "HermassResearch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Blackwolf API returned non-JSON response: {text[:240]!r}") from exc


def unwrap_records(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ["data", "rows", "result", "list", "items", "values"]:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        if isinstance(payload.get("data"), dict):
            return unwrap_records(payload["data"])
    return []


def parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)[:10]).date()


def parse_dt(value: Any) -> datetime:
    text = str(value).strip().replace("/", "-")
    return datetime.fromisoformat(text)


def number_from(record: dict[str, Any], *keys: str) -> float:
    lower = {str(k).lower(): v for k, v in record.items()}
    for key in keys:
        if key.lower() in lower:
            value = lower[key.lower()]
            if value is not None and value != "":
                return float(value)
    raise KeyError(keys[0])


def normalize_5m(record: Any) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    try:
        ts = parse_dt(record.get("t") or record.get("time") or record.get("date"))
        return {
            "stock_code": SYMBOL,
            "timestamp": ts,
            "open": number_from(record, "open", "o"),
            "high": number_from(record, "high", "h"),
            "low": number_from(record, "low", "l"),
            "close": number_from(record, "close", "c"),
            "volume": number_from(record, "volume", "vol", "v"),
            "amount": number_from(record, "amount", "amt", "a"),
        }
    except Exception:
        return None


def chunk_ranges(start: date, end: date, max_days: int = 29) -> list[tuple[date, date]]:
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=max_days))
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def fetch_5m(token: str, start: date, end: date) -> list[dict[str, Any]]:
    rows_by_ts: dict[datetime, dict[str, Any]] = {}
    for chunk_start, chunk_end in chunk_ranges(start, end):
        payload = request_json(
            "/wolf/time/kline",
            {
                "symbol": "stock",
                "code": CODE,
                "period": "5m",
                "cq": "1",
                "startDate": chunk_start.isoformat(),
                "endDate": chunk_end.isoformat(),
                "token": token,
            },
            timeout=90,
        )
        for record in unwrap_records(payload):
            row = normalize_5m(record)
            if row and start <= row["timestamp"].date() <= end:
                rows_by_ts[row["timestamp"]] = row
    return [rows_by_ts[key] for key in sorted(rows_by_ts)]


def write_raw_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["stock_code", "timestamp", "open", "high", "low", "close", "volume", "amount"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "timestamp": row["timestamp"].isoformat(sep=" ")})


def load_daily_rows() -> list[dict[str, Any]]:
    con = duckdb.connect(str(RAW_DB), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT stock_code, date, open, high, low, close, volume, amount
            FROM blackwolf_ashare_daily_raw
            WHERE stock_code = ?
            ORDER BY date
            """,
            [SYMBOL],
        ).fetchall()
    finally:
        con.close()

    daily = [
        {
            "stock_code": stock_code,
            "date": parse_date(d),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": float(v),
            "amount": float(a),
        }
        for stock_code, d, o, h, l, c, v, a in rows
    ]

    patch = json.loads(PATCH_JSON.read_text(encoding="utf-8"))["downloaded_daily"]
    patch_row = {
        "stock_code": patch["stock_code"],
        "date": parse_date(patch["date"]),
        "open": float(patch["open"]),
        "high": float(patch["high"]),
        "low": float(patch["low"]),
        "close": float(patch["close"]),
        "volume": float(patch["volume"]),
        "amount": float(patch["amount"]),
    }
    by_date = {row["date"]: row for row in daily}
    by_date[patch_row["date"]] = patch_row
    return [by_date[d] for d in sorted(by_date)]


def aggregate_daily(rows: list[dict[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    if timeframe == "D1":
        return [
            {
                **row,
                "timeframe": "D1",
                "period_start": row["date"],
                "period_end": row["date"],
                "available_at": datetime.combine(row["date"], time(15, 0, 59)),
                "close_at": datetime.combine(row["date"], time(15, 0, 59)),
                "source_bar_count": 1,
            }
            for row in rows
        ]

    groups: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        d = row["date"]
        start = d - timedelta(days=d.weekday()) if timeframe == "W1" else d.replace(day=1)
        groups[start].append(row)

    bars = []
    for start in sorted(groups):
        items = sorted(groups[start], key=lambda item: item["date"])
        end = items[-1]["date"]
        close_at = datetime.combine(end, time(15, 0, 59))
        bars.append(
            {
                "stock_code": SYMBOL,
                "timeframe": timeframe,
                "period_start": start,
                "period_end": end,
                "available_at": close_at,
                "close_at": close_at,
                "date": end,
                "open": items[0]["open"],
                "high": max(item["high"] for item in items),
                "low": min(item["low"] for item in items),
                "close": items[-1]["close"],
                "volume": sum(item["volume"] for item in items),
                "amount": sum(item["amount"] for item in items),
                "source_bar_count": len(items),
            }
        )
    return bars


def h1_bucket(ts: datetime) -> datetime:
    t = ts.time()
    if t <= time(10, 30, 59):
        return datetime.combine(ts.date(), time(10, 30, 59))
    if t <= time(11, 30, 59):
        return datetime.combine(ts.date(), time(11, 30, 59))
    if t <= time(14, 0, 59):
        return datetime.combine(ts.date(), time(14, 0, 59))
    return datetime.combine(ts.date(), time(15, 0, 59))


def h4_bucket(ts: datetime) -> datetime:
    return datetime.combine(ts.date(), time(15, 0, 59))


def aggregate_intraday(rows: list[dict[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    bucket_fn = h1_bucket if timeframe == "H1" else h4_bucket
    groups: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[bucket_fn(row["timestamp"])].append(row)

    bars = []
    for close_at in sorted(groups):
        items = sorted(groups[close_at], key=lambda item: item["timestamp"])
        bars.append(
            {
                "stock_code": SYMBOL,
                "timeframe": timeframe,
                "period_start": items[0]["timestamp"],
                "period_end": items[-1]["timestamp"],
                "available_at": close_at,
                "close_at": close_at,
                "date": close_at.date(),
                "open": items[0]["open"],
                "high": max(item["high"] for item in items),
                "low": min(item["low"] for item in items),
                "close": items[-1]["close"],
                "volume": sum(item["volume"] for item in items),
                "amount": sum(item["amount"] for item in items),
                "source_bar_count": len(items),
            }
        )
    return bars


def bars_to_ohlcv(bars: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for row in bars:
        rows.append(
            {
                "date": pd.Timestamp(row["close_at"]),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row.get("volume"),
                "amount": row.get("amount"),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "amount"])
    return pd.DataFrame(rows).set_index("date").sort_index()


def clean_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ")
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return round(value, 10)
    return value


def decode_state(score: Any) -> dict[str, Any]:
    if score is None or pd.isna(score):
        return {
            "base": None,
            "volatility_bit": None,
            "position_bit": None,
            "trend_bit": None,
            "sign": None,
            "score": None,
            "formula": "NA",
        }
    score_i = int(score)
    sign = -1 if score_i < 0 else 1
    magnitude = abs(score_i)
    base = 0 if magnitude < 8 else 8
    remainder = magnitude - base
    volatility_bit = 1 if remainder & 1 else 0
    position_bit = 2 if remainder & 2 else 0
    trend_bit = 4 if remainder & 4 else 0
    sign_text = "-" if sign < 0 else "+"
    return {
        "base": base,
        "volatility_bit": volatility_bit,
        "position_bit": position_bit,
        "trend_bit": trend_bit,
        "sign": sign_text,
        "score": score_i,
        "formula": f"{sign_text}（底座={base} + 波动={volatility_bit} + 位置={position_bit} + 趋势={trend_bit}）= {score_i}",
        "base_rule": "底座只能是 0 或 8，二者互斥，不能同时存在",
    }


def compute_state_levels(bars: list[dict[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    ohlcv = bars_to_ohlcv(bars)
    if ohlcv.empty:
        return []
    frames = [
        mt4.bollinger_bands_percent_b(ohlcv),
        mt4.sq_adx_adx(ohlcv),
        mt4.chandelier_exit(ohlcv)[["long_stop", "short_stop"]].rename(
            columns={"long_stop": "chandelier_long_stop", "short_stop": "chandelier_short_stop"}
        ),
        mt4.acd_kaufman_bandwidth(ohlcv),
        mt4.bollinger_bands_on_kaufman_width(ohlcv),
        mt4.bollinger_bands_on_atr_percent(ohlcv),
    ]
    indicators = pd.concat(frames, axis=1)
    indicators["close"] = ohlcv["close"]
    sr = mt4.multi_timeframe_fractal_sr(ohlcv, {"D": ohlcv}, fractal=5).rename(
        columns={"D_support": "support", "D_resistance": "resistance"}
    )
    indicators = indicators.join(sr[["support", "resistance"]])
    state = ea.build_market_state_frame(indicators)
    by_time = {pd.Timestamp(row["close_at"]): row for row in bars}
    out = []
    for ts, state_row in state.iterrows():
        base = by_time[pd.Timestamp(ts)]
        indicators_row = indicators.loc[ts]
        state_score = clean_value(state_row.get("state_score"))
        audit = {
            "timeframe": timeframe,
            "time": pd.Timestamp(ts).isoformat(sep=" "),
            "ohlcv": {key: clean_value(base.get(key)) for key in ["open", "high", "low", "close", "volume", "amount"]},
            "components": {key: clean_value(state_row.get(key)) for key in STATE_COMPONENTS},
            "bits": decode_state(state_score),
            "indicators": {key: clean_value(indicators_row.get(key)) for key in INDICATOR_COLUMNS if key in indicators_row.index},
        }
        out.append(
            {
                **base,
                "state_hex": clean_value(state_row.get("state_hex")),
                "state_score": state_score,
                "compression": clean_value(state_row.get("compression")),
                "trend": clean_value(state_row.get("trend")),
                "position": clean_value(state_row.get("position")),
                "volatility": clean_value(state_row.get("volatility")),
                "audit": audit,
            }
        )
    return out


def latest_level_index(levels: list[dict[str, Any]], asof: datetime) -> int | None:
    latest: int | None = None
    for idx, row in enumerate(levels):
        if row["available_at"] <= asof:
            latest = idx
        else:
            break
    return latest


def observed_state_audit(
    observing_bar: dict[str, Any],
    observed_name: str,
    observed_levels: list[dict[str, Any]],
    observed_idx: int,
) -> dict[str, Any]:
    return 计算视角状态审计(
        observing_bar,
        observed_name,
        observed_levels,
        observed_idx,
        ea,
        pd,
        decode_state,
        clean_value,
    )


def label() -> str:
    return f"{CODE} {NAME}"


def view_row(bar: dict[str, Any], level_names: list[str], levels: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, Any], dict[str, Any]]:
    asof = bar["close_at"]
    row: dict[str, Any] = {"品种": label(), "时间": asof.isoformat(sep=" ")}
    audit: dict[str, Any] = {"品种": label(), "时间": asof.isoformat(sep=" "), "states": {}}
    for name in level_names:
        idx = latest_level_index(levels[name], asof)
        if idx is None:
            row[f"{name}state"] = "NA"
            audit["states"][name] = {"timeframe": name, "time": None, "state_hex": "NA"}
            continue
        observed_audit = observed_state_audit(bar, name, levels[name], idx)
        row[f"{name}state"] = observed_audit["components"]["state_hex"]
        audit["states"][name] = observed_audit
    return row, audit


def build_views(rows_5m: list[dict[str, Any]]) -> dict[str, Any]:
    daily_rows = load_daily_rows()
    levels = {
        "MN1": compute_state_levels(aggregate_daily(daily_rows, "MN1"), "MN1"),
        "W1": compute_state_levels(aggregate_daily(daily_rows, "W1"), "W1"),
        "D1": compute_state_levels(aggregate_daily(daily_rows, "D1"), "D1"),
        "H4": compute_state_levels(aggregate_intraday(rows_5m, "H4"), "H4"),
        "H1": compute_state_levels(aggregate_intraday(rows_5m, "H1"), "H1"),
    }

    selected = {
        "MN1": [row for row in levels["MN1"] if VIEW_START <= row["date"] <= END],
        "W1": [row for row in levels["W1"] if VIEW_START <= row["date"] <= END],
        "D1": [row for row in levels["D1"] if VIEW_START <= row["date"] <= END],
        "H4": [row for row in levels["H4"] if INTRADAY_START <= row["date"] <= END],
        "H1": [row for row in levels["H1"] if INTRADAY_START <= row["date"] <= END],
    }
    specs = {
        "MN1": ["MN1"],
        "W1": ["MN1", "W1"],
        "D1": ["MN1", "W1", "D1"],
        "H4": ["MN1", "W1", "D1", "H4"],
        "H1": ["MN1", "W1", "D1", "H4", "H1"],
    }
    views: dict[str, list[dict[str, Any]]] = {}
    audits: dict[str, list[dict[str, Any]]] = {}
    for tf, names in specs.items():
        rows = []
        row_audits = []
        for bar in reversed(selected[tf][-ROW_LIMITS[tf] :]):
            view, audit = view_row(bar, names, levels)
            rows.append(view)
            row_audits.append(audit)
        views[tf] = rows
        audits[tf] = row_audits

    return {
        **views,
        "row_audit": audits,
        "native_audit": {
            tf: [row["audit"] for row in reversed(selected[tf][-ROW_LIMITS[tf] :])]
            for tf in ["MN1", "W1", "D1", "H4", "H1"]
        },
        "debug": {
            "raw_5m_rows": len(rows_5m),
            "mn1_bar_count": len(selected["MN1"]),
            "w1_bar_count": len(selected["W1"]),
            "d1_bar_count": len(selected["D1"]),
            "h4_bar_count": len(selected["H4"]),
            "h1_bar_count": len(selected["H1"]),
            "latest_5m_timestamp": rows_5m[-1]["timestamp"].isoformat(sep=" ") if rows_5m else None,
            "latest_h4_close": selected["H4"][-1]["close"] if selected["H4"] else None,
            "latest_h1_close": selected["H1"][-1]["close"] if selected["H1"] else None,
            "row_limits": ROW_LIMITS,
        },
    }


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


def render_table(title: str, rows: list[dict[str, Any]], columns: list[str], audits: list[dict[str, Any]]) -> str:
    body_parts = []
    for idx, row in enumerate(rows):
        body_parts.append("<tr>" + "".join(f"<td>{html.escape(str(row.get(col, '')))}</td>" for col in columns) + "</tr>")
        audit = audits[idx] if idx < len(audits) else {}
        audit_lines = []
        for tf, item in audit.get("states", {}).items():
            components = item.get("components", {})
            bits = item.get("bits", {})
            indicators = item.get("indicators", {})
            audit_lines.append(
                "<div class='audit-block'>"
                f"<h3>{html.escape(TF_LABELS.get(tf, tf))} @ {html.escape(str(item.get('time')))}</h3>"
                f"<p><strong>状态码</strong> {html.escape(str(components.get('state_hex')))}；"
                f"<strong>状态分数</strong> {html.escape(str(components.get('state_score')))}；"
                f"<strong>公式</strong> {html.escape(cn_formula(bits))}</p>"
                f"<p>底座互斥规则：底座只能是 0 或 8，不能同时存在；波动、位置、趋势是另外三个独立组件。</p>"
                f"<p>观察：{html.escape(observation_text(item))}</p>"
                f"<p>被观察周期价格：{html.escape(price_text(item))}</p>"
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
                f"<p>指标：{html.escape(indicator_text(indicators))}</p>"
                "</div>"
            )
        body_parts.append(f"<tr class='audit-row'><td colspan='{len(columns)}'>{''.join(audit_lines)}</td></tr>")
    return f"""
<section>
  <div class="section-head"><h2>{html.escape(title)}</h2><span>{len(rows)} 行</span></div>
  <div class="table-wrap"><table><thead><tr>{''.join(f'<th>{html.escape(COLUMN_CN.get(col, col))}</th>' for col in columns)}</tr></thead><tbody>{''.join(body_parts)}</tbody></table></div>
</section>"""


def render_html(payload: dict[str, Any]) -> str:
    mn1_cols = ["品种", "时间", "MN1state"]
    w1_cols = ["品种", "时间", "MN1state", "W1state"]
    d1_cols = ["品种", "时间", "MN1state", "W1state", "D1state"]
    h4_cols = ["品种", "时间", "MN1state", "W1state", "D1state", "H4state"]
    h1_cols = ["品种", "时间", "MN1state", "W1state", "D1state", "H4state", "H1state"]
    views = payload["views"]
    row_audit = payload["row_audit"]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>688107 安路科技五视角状态审计表</title>
  <style>
    *{{box-sizing:border-box}}body{{margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f5f7f9;color:#17202a}}main{{max-width:1280px;margin:0 auto}}header,section{{background:#fff;border:1px solid #dbe3ea;border-radius:8px;padding:18px;margin-bottom:16px}}header{{border-top:6px solid #0f766e}}h1{{margin:0 0 8px;font-size:28px}}h2{{margin:0;font-size:20px}}h3{{margin:0 0 6px;font-size:15px}}p{{margin:6px 0 0;color:#66717f;line-height:1.55}}.meta{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px;margin-top:14px}}.meta div{{border:1px solid #dbe3ea;border-radius:8px;padding:10px;background:#fafbfc}}.meta small{{display:block;color:#66717f;margin-bottom:4px}}.section-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}}.section-head span{{border:1px solid #b9dad5;background:#e7f4f2;color:#115e59;border-radius:999px;padding:4px 10px;font-weight:700;font-size:13px}}.table-wrap{{overflow-x:auto;border:1px solid #dbe3ea;border-radius:8px}}table{{width:100%;border-collapse:collapse;min-width:860px}}th,td{{padding:10px 12px;border-bottom:1px solid #dbe3ea;text-align:left;white-space:nowrap;vertical-align:top}}th{{background:#f8fafb;color:#3b4652}}tr:last-child td{{border-bottom:0}}td:nth-child(n+3){{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:700}}.audit-row td{{background:#fbfcfd;white-space:normal;font-family:inherit;font-weight:400}}.audit-block{{border:1px solid #dbe3ea;border-radius:8px;padding:10px;margin:8px 0;background:#fff}}.audit-block p{{font-size:13px;color:#334155}}code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}
  </style>
</head>
<body>
<main>
  <header>
    <h1>688107 安路科技五视角状态审计表</h1>
    <p>状态值按状态编码公式计算：底座在 0 和 8 中二选一，绝不同时存在；状态分数绝对值 = 底座 + 波动位 + 位置位 + 趋势位，再按方向转为状态码。</p>
    <div class="meta">
      <div><small>指标管道</small><strong>状态源码与指标源码</strong></div>
      <div><small>核心指标</small><strong>考夫曼宽度、布林宽度、真实波幅、趋势强度、支撑压力、吊灯止损</strong></div>
      <div><small>分钟源</small><strong>五分钟原始数据 {payload['debug']['raw_5m_rows']} 行</strong></div>
      <div><small>五视角行数</small><strong>月线 {len(views['MN1'])} / 周线 {len(views['W1'])} / 日线 {len(views['D1'])} / 四小时 {len(views['H4'])} / 小时 {len(views['H1'])}</strong></div>
    </div>
  </header>
  {render_table('月线视角', views['MN1'], mn1_cols, row_audit['MN1'])}
  {render_table('周线视角', views['W1'], w1_cols, row_audit['W1'])}
  {render_table('日线视角', views['D1'], d1_cols, row_audit['D1'])}
  {render_table('四小时视角', views['H4'], h4_cols, row_audit['H4'])}
  {render_table('小时视角', views['H1'], h1_cols, row_audit['H1'])}
</main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Blackwolf 5m data and build 688107 auditable state_hex view tables.")
    parser.add_argument("--token-stdin", action="store_true")
    parser.add_argument("--use-existing-raw", action="store_true")
    args = parser.parse_args()

    if args.use_existing_raw and RAW_OUT.exists():
        with RAW_OUT.open(encoding="utf-8", newline="") as f:
            rows_5m = [
                {
                    **row,
                    "timestamp": parse_dt(row["timestamp"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "amount": float(row["amount"]),
                }
                for row in csv.DictReader(f)
            ]
    else:
        token = read_token(args.token_stdin)
        rows_5m = fetch_5m(token, INTRADAY_START, END)
        if not rows_5m:
            raise RuntimeError("Blackwolf returned no 5m rows")
        write_raw_csv(rows_5m, RAW_OUT)

    views = build_views(rows_5m)
    payload = {
        "schema_version": "anlu_688107_auditable_state_hex_views_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "symbol": SYMBOL,
        "name": NAME,
        "date_range": {
            "view_start": VIEW_START.isoformat(),
            "intraday_start": INTRADAY_START.isoformat(),
            "end": END.isoformat(),
        },
        "state_hex_contract": {
            "formula": "底座只能在 0 和 8 中二选一，不能同时存在；状态分数绝对值=底座+波动位一+位置位二+趋势位四；状态码=带方向的大写十六进制状态分数",
            "source": [
                str(STATE_SOURCE / "ea_market_state.py"),
                str(STATE_SOURCE / "mt4_indicators_python.py"),
            ],
            "禁止支撑压力关系直接映射状态码": True,
        },
        "source": {
            "api": "/wolf/time/kline",
            "period": "5m",
            "raw_csv": str(RAW_OUT),
            "token_written_to_disk": False,
        },
        "views": {key: views[key] for key in ["MN1", "W1", "D1", "H4", "H1"]},
        "row_audit": views["row_audit"],
        "native_audit": views["native_audit"],
        "debug": views["debug"],
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({"status": "PASS", "json": str(OUT_JSON), "html": str(OUT_HTML), **views["debug"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
