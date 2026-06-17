#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from state_calc.sr_calculator import calculate_atr, calculate_sr


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "research_observer"
DEFAULT_SUBSECTOR_CONFIG = ROOT / "config" / "ai_tech_subsectors.json"
DEFAULT_UNIVERSE_CONFIG = ROOT / "config" / "ai_tech_stock_universe.csv"
REQUIRED_DISCLAIMER = "仅作研究观察，不构成交易建议"
BANNED_TERMS = (
    "买入",
    "卖出",
    "加仓",
    "减仓",
    "满仓",
    "做多",
    "做空",
    "止盈",
    "止损",
    "推荐",
    "建议参与",
)


@dataclass
class UniverseEntry:
    stock_code: str
    stock_name: str
    board: str
    subsector: str
    manual_role: str = ""
    notes: str = ""


@dataclass
class SRZone:
    support_center: float | None
    support_lower: float | None
    support_upper: float | None
    resistance_center: float | None
    resistance_lower: float | None
    resistance_upper: float | None
    position: str
    width_pct: float | None


def detect_latest_foundation_db() -> Path:
    candidates = sorted(ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"))
    # Exclude mt4like variants; prefer YYYYMMDD dated directories
    dated = [p for p in candidates if "mt4like" not in p.parent.name]
    if dated:
        return dated[-1]
    if candidates:
        return candidates[-1]
    raise FileNotFoundError("未找到 outputs/p116_foundation_*/p116_foundation.duckdb")


def load_subsector_names(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("subsectors", payload)
    names = set()
    for row in rows:
        if isinstance(row, dict) and row.get("name"):
            names.add(str(row["name"]).strip())
    if not names:
        raise ValueError(f"子板块配置为空: {path}")
    return names


def load_universe(path: Path, valid_subsectors: set[str]) -> list[UniverseEntry]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]]
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("stocks", payload)
        if not isinstance(rows, list):
            raise ValueError(f"JSON 配置格式错误: {path}")
    else:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))

    universe: list[UniverseEntry] = []
    for row in rows:
        stock_code = str(row.get("stock_code", "")).strip()
        stock_name = str(row.get("stock_name", "")).strip()
        board = str(row.get("board", "AI科技")).strip() or "AI科技"
        subsector = str(row.get("subsector", "")).strip()
        if not stock_code or not stock_name or not subsector:
            continue
        if subsector not in valid_subsectors:
            raise ValueError(f"{stock_code} 的子板块未在配置中声明: {subsector}")
        universe.append(
            UniverseEntry(
                stock_code=stock_code,
                stock_name=stock_name,
                board=board,
                subsector=subsector,
                manual_role=str(row.get("manual_role", "")).strip(),
                notes=str(row.get("notes", "")).strip(),
            )
        )
    if not universe:
        raise ValueError(f"股票配置为空: {path}")
    return universe


def sql_quote(value: str) -> str:
    return value.replace("'", "''")


def load_bars(
    db_path: Path,
    timeframe: str,
    stock_codes: list[str],
    end_date: date,
) -> dict[str, list[dict[str, Any]]]:
    con = duckdb.connect(str(db_path), read_only=True)
    quoted = ", ".join(f"'{sql_quote(code)}'" for code in stock_codes)
    rows = con.execute(
        f"""
        SELECT stock_code, available_date, open, high, low, close, volume
        FROM timeframe_bars
        WHERE timeframe = ?
          AND available_date <= ?
          AND stock_code IN ({quoted})
        ORDER BY stock_code, available_date
        """,
        [timeframe, end_date.isoformat()],
    ).fetchall()
    con.close()
    result: dict[str, list[dict[str, Any]]] = {code: [] for code in stock_codes}
    for stock_code, available_date, open_, high, low, close, volume in rows:
        result.setdefault(stock_code, []).append(
            {
                "date": available_date,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume),
            }
        )
    return result


def load_optional_intraday_bars(
    db_path: Path | None,
    timeframe: str,
    stock_codes: list[str],
    end_date: date,
) -> dict[str, list[dict[str, Any]]]:
    empty = {code: [] for code in stock_codes}
    if db_path is None or not db_path.exists():
        return empty
    con = duckdb.connect(str(db_path), read_only=True)
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    quoted = ", ".join(f"'{sql_quote(code)}'" for code in stock_codes)
    if "timeframe_bars" in tables:
        rows = con.execute(
            f"""
            SELECT stock_code, available_date, open, high, low, close, volume
            FROM timeframe_bars
            WHERE timeframe = ?
              AND available_date <= ?
              AND stock_code IN ({quoted})
            ORDER BY stock_code, available_date
            """,
            [timeframe, end_date.isoformat()],
        ).fetchall()
    else:
        table_name = f"{timeframe.lower()}_bars"
        if table_name not in tables:
            con.close()
            return empty
        # Auto-detect date column: some sources use available_date, others use bar_date
        cols = {row[1] for row in con.execute(f"PRAGMA table_info('{table_name}')").fetchall()}
        date_col = "available_date" if "available_date" in cols else "bar_date" if "bar_date" in cols else None
        if date_col is None:
            con.close()
            return empty
        rows = con.execute(
            f"""
            SELECT stock_code, {date_col}, open, high, low, close, volume
            FROM {table_name}
            WHERE {date_col} <= ?
              AND stock_code IN ({quoted})
            ORDER BY stock_code, {date_col}
            """,
            [end_date.isoformat()],
        ).fetchall()
    con.close()
    result = {code: [] for code in stock_codes}
    for stock_code, available_date, open_, high, low, close, volume in rows:
        result.setdefault(stock_code, []).append(
            {
                "date": available_date,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume),
            }
        )
    return result


def sma_series(values: list[float], period: int) -> list[float | None]:
    series: list[float | None] = []
    if period <= 0:
        return [None] * len(values)
    rolling_sum = 0.0
    for idx, value in enumerate(values):
        rolling_sum += value
        if idx >= period:
            rolling_sum -= values[idx - period]
        if idx + 1 >= period:
            series.append(rolling_sum / period)
        else:
            series.append(None)
    return series


def median_ignore_none(values: list[float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None
    return float(statistics.median(clean))


def count_consecutive_close_above_ma25(closes: list[float], ma25: list[float | None]) -> int:
    streak = 0
    for close, ma in zip(reversed(closes), reversed(ma25)):
        if ma is None or close <= ma:
            break
        streak += 1
    return streak


def count_vma_crosses(vma5: list[float | None], vma60: list[float | None], lookback: int = 20) -> int:
    start = max(0, len(vma5) - lookback)
    crosses = 0
    prev_sign = 0
    for short_ma, long_ma in zip(vma5[start:], vma60[start:]):
        if short_ma is None or long_ma is None:
            continue
        diff = short_ma - long_ma
        sign = 1 if diff > 0 else -1 if diff < 0 else 0
        if prev_sign and sign and sign != prev_sign:
            crosses += 1
        if sign:
            prev_sign = sign
    return crosses


def classify_long_cycle_arrangement(ma144: float | None, ma169: float | None, ma200: float | None) -> str:
    if ma144 is None or ma169 is None or ma200 is None:
        return "数据不足"
    if ma144 > ma169 > ma200:
        return "多头排列"
    if ma144 < ma169 < ma200:
        return "空头排列"
    return "混合排列"


def is_long_ma_converging(
    ma144: list[float | None],
    ma169: list[float | None],
    ma200: list[float | None],
    closes: list[float],
    threshold: float = 0.02,
    days: int = 3,
) -> bool:
    if len(closes) < days:
        return False
    for idx in range(len(closes) - days, len(closes)):
        if idx < 0:
            return False
        v144, v169, v200 = ma144[idx], ma169[idx], ma200[idx]
        close = closes[idx]
        if None in (v144, v169, v200) or close <= 0:
            return False
        span = max(v144, v169, v200) - min(v144, v169, v200)
        if (span / close) >= threshold:
            return False
    return True


def is_vma_contracting(vma5: list[float | None], vma60: list[float | None], days: int = 5) -> bool:
    if len(vma5) < days or len(vma60) < days:
        return False
    short_values = vma5[-days:]
    long_values = vma60[-days:]
    if any(value is None for value in short_values) or any(value is None for value in long_values):
        return False
    if short_values[-1] >= long_values[-1]:
        return False
    return all(short_values[idx] < short_values[idx - 1] for idx in range(1, days))


def compute_sr_width_ratio(bars: list[dict[str, Any]]) -> float | None:
    if len(bars) < 20:
        return None
    widths: list[float] = []
    for idx in range(19, len(bars)):
        window = bars[idx - 19 : idx + 1]
        close = float(window[-1]["close"])
        if close <= 0:
            continue
        width = (max(item["high"] for item in window) - min(item["low"] for item in window)) / close
        widths.append(width)
    if not widths:
        return None
    current_width = widths[-1]
    median_width = float(statistics.median(widths[-60:]))
    if median_width <= 0:
        return None
    return current_width / median_width


def build_sr_zone(bars: list[dict[str, Any]]) -> SRZone:
    highs = [float(item["high"]) for item in bars]
    lows = [float(item["low"]) for item in bars]
    closes = [float(item["close"]) for item in bars]
    close = closes[-1]
    sr = calculate_sr(highs, lows, closes, lookback=min(120, len(closes)))
    atr, _ = calculate_atr(highs, lows, closes, period=14)
    half_width = atr / 2.0 if atr > 0 else max(close * 0.005, 0.01)
    if not sr.ready or sr.support is None or sr.resistance is None:
        return SRZone(None, None, None, None, None, None, "未知", None)

    support_lower = float(sr.support - half_width)
    support_upper = float(sr.support + half_width)
    resistance_lower = float(sr.resistance - half_width)
    resistance_upper = float(sr.resistance + half_width)
    width_pct = ((resistance_upper - support_lower) / close) if close > 0 else None

    if close < support_lower:
        position = "支撑区下方"
    elif support_lower <= close <= support_upper:
        position = "支撑区"
    elif resistance_lower <= close <= resistance_upper:
        position = "阻力区"
    elif close > resistance_upper:
        position = "阻力区上方"
    else:
        position = "中部"

    return SRZone(
        support_center=float(sr.support),
        support_lower=support_lower,
        support_upper=support_upper,
        resistance_center=float(sr.resistance),
        resistance_lower=resistance_lower,
        resistance_upper=resistance_upper,
        position=position,
        width_pct=width_pct,
    )


def summarize_timeframe(
    timeframe: str,
    bars: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(bars) < 25:
        return {
            "timeframe": timeframe,
            "available": False,
            "reason": "bars_insufficient",
            "matrix": {"trend": "N/A", "volume": "N/A", "sr_position": "N/A"},
        }

    closes = [float(item["close"]) for item in bars]
    opens = [float(item["open"]) for item in bars]
    volumes = [float(item["volume"]) for item in bars]
    ma25 = sma_series(closes, 25)
    ma144 = sma_series(closes, 144)
    ma169 = sma_series(closes, 169)
    ma200 = sma_series(closes, 200)
    vma5 = sma_series(volumes, 5)
    vma60 = sma_series(volumes, 60)
    close = closes[-1]
    open_ = opens[-1]
    current_ma25 = ma25[-1]
    ma25_ref = ma25[-6] if len(ma25) >= 6 else None
    ma25_slope = None
    if current_ma25 is not None and ma25_ref not in (None, 0):
        ma25_slope = (current_ma25 - ma25_ref) / ma25_ref

    arrangement = classify_long_cycle_arrangement(ma144[-1], ma169[-1], ma200[-1])
    ma_converging = is_long_ma_converging(ma144, ma169, ma200, closes)
    vma_contracting = is_vma_contracting(vma5, vma60)
    sr_zone = build_sr_zone(bars)
    sr_ratio = compute_sr_width_ratio(bars)

    if current_ma25 is None or ma25_slope is None:
        trend_arrow = "→"
    elif close > current_ma25 and ma25_slope >= 0:
        trend_arrow = "↑"
    elif close < current_ma25 and ma25_slope < 0:
        trend_arrow = "↓"
    else:
        trend_arrow = "→"

    volume_symbol = "≈"
    if vma5[-1] is not None and vma60[-1] is not None:
        if vma5[-1] > vma60[-1]:
            volume_symbol = "+"
        elif vma5[-1] < vma60[-1]:
            volume_symbol = "-"

    return {
        "timeframe": timeframe,
        "available": True,
        "close": close,
        "open": open_,
        "is_green_candle": close > open_,
        "is_red_candle": close < open_,
        "ma25": current_ma25,
        "ma25_slope": ma25_slope,
        "ma144": ma144[-1],
        "ma169": ma169[-1],
        "ma200": ma200[-1],
        "vma5": vma5[-1],
        "vma60": vma60[-1],
        "long_cycle_arrangement": arrangement,
        "long_ma_converging": ma_converging,
        "volume_contracting": vma_contracting,
        "sr_zone": asdict(sr_zone),
        "sr_contraction_ratio": sr_ratio,
        "sr_contracting": sr_ratio is not None and sr_ratio < 0.6,
        "matrix": {
            "trend": trend_arrow,
            "volume": volume_symbol,
            "sr_position": sr_zone.position,
        },
        "close_above_ma25_streak": count_consecutive_close_above_ma25(closes, ma25),
        "vma_crosses_20": count_vma_crosses(vma5, vma60),
        "return_20d": ((closes[-1] / closes[-21]) - 1.0) if len(closes) >= 21 and closes[-21] else None,
    }


def apply_three_layer_filter(d1_summary: dict[str, Any]) -> dict[str, Any]:
    result = {
        "long_cycle": {
            "evaluated": True,
            "passed": False,
            "status": "未通过",
        },
        "trend": {
            "evaluated": False,
            "passed": False,
            "status": "未执行",
        },
        "volume_trigger": {
            "evaluated": False,
            "status": "未执行",
        },
        "final_status": "未纳入观察",
        "included": False,
    }
    arrangement = d1_summary["long_cycle_arrangement"]
    ma_converging = bool(d1_summary["long_ma_converging"])
    if arrangement == "空头排列":
        result["long_cycle"]["status"] = "空头排列排除"
        return result
    if arrangement == "多头排列" or ma_converging:
        result["long_cycle"]["passed"] = True
        result["long_cycle"]["status"] = "通过"
    else:
        result["long_cycle"]["status"] = "混合排列待跟踪"
        return result

    result["trend"]["evaluated"] = True
    ma25 = d1_summary["ma25"]
    ma25_slope = d1_summary["ma25_slope"]
    close = d1_summary["close"]
    if ma25 is not None and ma25_slope is not None and close > ma25 and ma25_slope >= 0:
        result["trend"]["passed"] = True
        result["trend"]["status"] = "通过"
    else:
        result["trend"]["status"] = "掉队"
        result["final_status"] = "掉队观察"
        return result

    result["volume_trigger"]["evaluated"] = True
    vma5 = d1_summary["vma5"]
    vma60 = d1_summary["vma60"]
    is_green = d1_summary["is_green_candle"]
    is_red = d1_summary["is_red_candle"]
    if vma5 is not None and vma60 is not None and vma5 > vma60 and is_green:
        result["volume_trigger"]["status"] = "核心观察"
        result["final_status"] = "核心观察"
        result["included"] = True
        return result
    if vma5 is not None and vma60 is not None and vma5 < vma60 and is_green:
        result["volume_trigger"]["status"] = "缩量观察"
        result["final_status"] = "缩量观察"
        result["included"] = True
        return result
    if vma5 is not None and vma60 is not None and vma5 > vma60 and is_red:
        result["volume_trigger"]["status"] = "放量阴线否决"
        result["final_status"] = "放量阴线否决"
        return result
    result["volume_trigger"]["status"] = "量能未确认"
    result["final_status"] = "量能未确认"
    return result


def assign_roles(observations: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in observations:
        grouped.setdefault(row["subsector"], []).append(row)

    for rows in grouped.values():
        ranked = sorted(
            [row for row in rows if row["d1"]["return_20d"] is not None],
            key=lambda item: item["d1"]["return_20d"],
            reverse=True,
        )
        leader_codes = {row["stock_code"] for row in ranked[:2]}
        for row in rows:
            d1 = row["d1"]
            filter_result = row["serial_filter"]
            role = "掉队股"
            if row["manual_role"]:
                role = row["manual_role"]
            elif (
                row["stock_code"] in leader_codes
                and d1["ma25"] is not None
                and d1["close"] > d1["ma25"]
                and d1["vma5"] is not None
                and d1["vma60"] is not None
                and d1["vma5"] > d1["vma60"]
            ):
                role = "领头羊"
            elif (
                d1["close_above_ma25_streak"] >= 5
                and d1["vma5"] is not None
                and d1["vma60"] is not None
                and d1["vma5"] > d1["vma60"]
            ):
                role = "核心股"
            elif (
                d1["ma25"] is not None
                and d1["close"] > d1["ma25"]
                and d1["vma_crosses_20"] >= 2
            ):
                role = "弹性股"
            elif filter_result["final_status"] == "掉队观察":
                role = "掉队股"
            row["role"] = role


def build_resonance_summary(matrix: dict[str, dict[str, str]]) -> str:
    available = {tf: cell for tf, cell in matrix.items() if cell["trend"] in {"↑", "↓", "→"}}
    if not available:
        return "多周期数据暂缺"
    d1_trend = available.get("D1", {}).get("trend")
    same_as_d1 = sum(1 for cell in available.values() if cell["trend"] == d1_trend)
    total = len(available)
    if total == 1:
        return "D1 单周期观察"
    if same_as_d1 == total:
        return f"{total}/{total} 同向"
    if same_as_d1 >= 2:
        return f"{same_as_d1}/{total} 与 D1 同向"
    return "存在冲突，以 D1 为准"


def build_contraction_summary(d1_summary: dict[str, Any], w1_summary: dict[str, Any], m30_summary: dict[str, Any]) -> str:
    flags: list[str] = []
    d1_conv = d1_summary.get("long_ma_converging")
    d1_vc = d1_summary.get("volume_contracting")
    d1_sc = d1_summary.get("sr_contracting")
    w1_conv = w1_summary.get("long_ma_converging") if w1_summary.get("available") else None
    w1_sc = w1_summary.get("sr_contracting") if w1_summary.get("available") else None

    # MA convergence
    if d1_conv and w1_conv:
        flags.append("MA144/169/200 收敛(W1+D1确认)")
    elif d1_conv:
        flags.append("MA144/169/200 收敛(D1待确认)")
    # Volume contraction
    if d1_vc:
        flags.append("量能收缩")
    # SR contraction
    if d1_sc and w1_sc:
        flags.append("SR收缩(W1+D1确认)")
    elif d1_sc:
        flags.append("SR收缩(D1待确认)")
    if not flags:
        return "无显著收缩"
    return "；".join(flags)


def build_invalidation_text(d1_summary: dict[str, Any], filter_result: dict[str, Any]) -> str:
    sr_zone = d1_summary["sr_zone"]
    conditions = []
    if d1_summary["ma25"] is not None:
        conditions.append("日线收盘回到 MA25 下方且 MA25 斜率转负")
    if sr_zone["support_lower"] is not None:
        conditions.append(f"价格落出支撑区下沿 {sr_zone['support_lower']:.2f}")
    if filter_result["volume_trigger"]["status"] == "核心观察":
        conditions.append("VMA5 高于 60日均量线 但收盘转阴")
        conditions.append("次日K线未突破当前高点则信号降权")
    else:
        conditions.append("量能跟随未恢复")
    return "；".join(conditions)


def assert_no_banned_terms(text: str) -> None:
    sanitized = text.replace(REQUIRED_DISCLAIMER, "")
    for term in BANNED_TERMS:
        if term in sanitized:
            raise ValueError(f"输出包含禁词: {term}")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 2560 + 长周期均线 + SR 收缩研究观察系统",
        "",
        f"- 观察日期: `{report['observation_date']}`",
        f"- 样本数量: `{report['stock_count']}`",
        f"- Foundation DB: `{report['foundation_db']}`",
        "",
    ]
    for subsector in report["subsectors"]:
        counts = subsector["role_counts"]
        lines.extend(
            [
                f"## {subsector['board']} / {subsector['subsector']}",
                "",
                f"- 子板块状态: 领头羊 {counts.get('领头羊', 0)}，核心股 {counts.get('核心股', 0)}，弹性股 {counts.get('弹性股', 0)}，掉队股 {counts.get('掉队股', 0)}",
                "",
            ]
        )
        for stock in subsector["stocks"]:
            d1 = stock["d1"]
            sr_zone = d1["sr_zone"]
            matrix = stock["matrix"]
            lines.extend(
                [
                    f"### {stock['stock_code']} {stock['stock_name']}",
                    "",
                    f"- 板块/子板块: {stock['board']} / {stock['subsector']}",
                    f"- 个股角色: {stock['role']}",
                    f"- 长周期框架: {d1['long_cycle_arrangement']}；{'收敛中' if d1['long_ma_converging'] else '未收敛'}；过滤状态 {stock['serial_filter']['long_cycle']['status']}",
                    f"- MA25方向: close {'上方' if d1['ma25'] is not None and d1['close'] > d1['ma25'] else '下方或贴近'} MA25；斜率 {((d1['ma25_slope'] or 0.0) * 100):.2f}%",
                    f"- VMA5/VMA60状态: {format_vma_relation(d1)}；过滤状态 {stock['serial_filter']['volume_trigger']['status']}",
                    f"- SR支撑区/阻力区/当前位置: {format_sr_zone(sr_zone)}",
                    f"- W1/D1/M30多周期矩阵: W1({matrix['W1']['trend']},{matrix['W1']['volume']},{matrix['W1']['sr_position']}) / D1({matrix['D1']['trend']},{matrix['D1']['volume']},{matrix['D1']['sr_position']}) / M30({matrix['M30']['trend']},{matrix['M30']['volume']},{matrix['M30']['sr_position']})",
                    f"- 共振评估: {stock['resonance']}",
                    f"- 收缩观察: {stock['contraction_summary']}",
                    f"- 失效条件: {stock['invalidations']}",
                    "",
                ]
            )
    lines.extend(["---", "", REQUIRED_DISCLAIMER, ""])
    markdown = "\n".join(lines)
    assert_no_banned_terms(markdown)
    return markdown


def format_vma_relation(summary: dict[str, Any]) -> str:
    vma5 = summary["vma5"]
    vma60 = summary["vma60"]
    if vma5 is None or vma60 is None:
        return "VMA 数据不足"
    if vma5 > vma60:
        relation = "VMA5 > 60日均量线"
    elif vma5 < vma60:
        relation = "VMA5 < 60日均量线"
    else:
        relation = "VMA5 ≈ 60日均量线"
    candle = "收阳" if summary["is_green_candle"] else "收阴" if summary["is_red_candle"] else "平收"
    return f"{relation}；{candle}"


def format_sr_zone(zone: dict[str, Any]) -> str:
    if zone["support_lower"] is None or zone["resistance_upper"] is None:
        return "SR 数据不足"
    return (
        f"支撑区 {zone['support_lower']:.2f}-{zone['support_upper']:.2f}；"
        f"阻力区 {zone['resistance_lower']:.2f}-{zone['resistance_upper']:.2f}；"
        f"当前位置 {zone['position']}"
    )


def write_outputs(report: dict[str, Any], output_dir: Path, stem: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    assert_no_banned_terms(payload)
    json_path.write_text(payload, encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def build_report(
    foundation_db: Path,
    observation_date: date,
    universe: list[UniverseEntry],
    intraday_db: Path | None = None,
) -> dict[str, Any]:
    stock_codes = [item.stock_code for item in universe]
    d1_bars = load_bars(foundation_db, "D1", stock_codes, observation_date)
    w1_bars = load_bars(foundation_db, "W1", stock_codes, observation_date)
    m30_bars = load_optional_intraday_bars(intraday_db, "M30", stock_codes, observation_date)

    observations: list[dict[str, Any]] = []
    for item in universe:
        bars = d1_bars.get(item.stock_code, [])
        if len(bars) < 25:
            continue
        d1_summary = summarize_timeframe("D1", bars)
        w1_summary = summarize_timeframe("W1", w1_bars.get(item.stock_code, []))
        m30_summary = summarize_timeframe("M30", m30_bars.get(item.stock_code, []))
        serial_filter = apply_three_layer_filter(d1_summary)
        matrix = {
            "D1": d1_summary["matrix"],
            "W1": w1_summary["matrix"],
            "M30": m30_summary["matrix"],
        }
        observations.append(
            {
                "stock_code": item.stock_code,
                "stock_name": item.stock_name,
                "board": item.board,
                "subsector": item.subsector,
                "manual_role": item.manual_role,
                "notes": item.notes,
                "d1": d1_summary,
                "w1": w1_summary,
                "m30": m30_summary,
                "serial_filter": serial_filter,
                "matrix": matrix,
            }
        )

    assign_roles(observations)
    for row in observations:
        row["resonance"] = build_resonance_summary(row["matrix"])
        row["contraction_summary"] = build_contraction_summary(row["d1"], row["w1"], row["m30"])
        row["invalidations"] = build_invalidation_text(row["d1"], row["serial_filter"])

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in observations:
        grouped.setdefault(row["subsector"], []).append(row)

    subsector_rows: list[dict[str, Any]] = []
    for subsector, rows in grouped.items():
        rows = sorted(rows, key=lambda item: (item["role"], item["stock_code"]))
        role_counts: dict[str, int] = {}
        for row in rows:
            role_counts[row["role"]] = role_counts.get(row["role"], 0) + 1
        subsector_rows.append(
            {
                "board": rows[0]["board"],
                "subsector": subsector,
                "role_counts": role_counts,
                "stocks": rows,
            }
        )
    subsector_rows.sort(key=lambda item: item["subsector"])

    return {
        "schema_version": "ma2560_sr_observation_v1",
        "observation_date": observation_date.isoformat(),
        "foundation_db": str(foundation_db),
        "intraday_db": str(intraday_db) if intraday_db else "",
        "stock_count": len(observations),
        "subsectors": subsector_rows,
        "disclaimer": REQUIRED_DISCLAIMER,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build 2560 + long MA + SR contraction research observation report.")
    parser.add_argument("--date", default=date.today().isoformat(), help="观察日期 YYYY-MM-DD")
    parser.add_argument("--foundation-db", default="", help="p116_foundation.duckdb 路径，默认自动取最新")
    parser.add_argument("--intraday-db", default="", help="可选 M30 DuckDB 路径")
    parser.add_argument("--subsector-config", default=str(DEFAULT_SUBSECTOR_CONFIG), help="8 个 AI 子板块配置 JSON")
    parser.add_argument("--universe-config", default=str(DEFAULT_UNIVERSE_CONFIG), help="股票映射 JSON/CSV")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    observation_date = date.fromisoformat(args.date)
    foundation_db = Path(args.foundation_db) if args.foundation_db else detect_latest_foundation_db()
    intraday_db = Path(args.intraday_db) if args.intraday_db else None
    valid_subsectors = load_subsector_names(Path(args.subsector_config))
    universe = load_universe(Path(args.universe_config), valid_subsectors)
    report = build_report(foundation_db, observation_date, universe, intraday_db=intraday_db)
    stem = f"ma2560_sr_observation_{observation_date.strftime('%Y%m%d')}"
    json_path, md_path = write_outputs(report, Path(args.output_dir), stem)
    print(json.dumps({"ok": True, "json": str(json_path), "markdown": str(md_path), "stock_count": report["stock_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
