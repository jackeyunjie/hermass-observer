#!/usr/bin/env python3
"""M30 2560 回调二波信号检测系统

分层架构:
  W1  → 战略资格（一票否决）
  D1  → 健康回调 vs 趋势失败
  M30 → 二次触发（必选条件 + 加分项 = 触发评分 0-100）

用法:
  python3 scripts/build_m30_2560_second_wave.py \
    --date 2026-06-17 \
    --foundation-db outputs/p116_foundation_20260617/p116_foundation.duckdb \
    --m30-db data/blackwolf_m30_20260617/blackwolf_m30.duckdb
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = ROOT / "config" / "ai_tech_stock_universe.csv"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "research_observer"

REQUIRED_DISCLAIMER = "仅作研究观察，不构成交易建议"


# ── SQL helpers ──────────────────────────────────────────────


def sql_quote(value: str) -> str:
    return value.replace("'", "''")


def load_bars(
    db_path: Path, timeframe: str, stock_codes: list[str], end_date: date
) -> dict[str, list[dict[str, Any]]]:
    con = duckdb.connect(str(db_path), read_only=True)
    quoted = ", ".join(f"'{sql_quote(c)}'" for c in stock_codes)
    rows = con.execute(
        f"""SELECT stock_code, available_date, open, high, low, close, volume
           FROM timeframe_bars
           WHERE timeframe = ? AND available_date <= ? AND stock_code IN ({quoted})
           ORDER BY stock_code, available_date""",
        [timeframe, end_date.isoformat()],
    ).fetchall()
    con.close()
    result: dict[str, list[dict[str, Any]]] = {c: [] for c in stock_codes}
    for sc, ad, o, h, l, c, v in rows:
        result.setdefault(sc, []).append(
            {"date": ad, "open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": float(v)}
        )
    return result


def load_m30_bars(
    db_path: Path, stock_codes: list[str], end_date: date
) -> dict[str, list[dict[str, Any]]]:
    con = duckdb.connect(str(db_path), read_only=True)
    # detect date column
    cols = {r[1] for r in con.execute("PRAGMA table_info('m30_bars')").fetchall()}
    dc = "available_date" if "available_date" in cols else "bar_date"
    quoted = ", ".join(f"'{sql_quote(c)}'" for c in stock_codes)
    rows = con.execute(
        f"""SELECT stock_code, {dc}, period_start, open, high, low, close, volume
           FROM m30_bars
           WHERE {dc} <= ? AND stock_code IN ({quoted})
           ORDER BY stock_code, period_start""",
        [end_date.isoformat()],
    ).fetchall()
    con.close()
    result: dict[str, list[dict[str, Any]]] = {c: [] for c in stock_codes}
    for sc, bd, ps, o, h, l, c, v in rows:
        result.setdefault(sc, []).append(
            {"date": str(bd), "ts": str(ps), "open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": float(v)}
        )
    return result


# ── indicators ───────────────────────────────────────────────


def sma(values: list[float], period: int) -> list[float | None]:
    if period <= 0 or len(values) < period:
        return [None] * len(values)
    result: list[float | None] = [None] * (period - 1)
    ws = sum(values[:period])
    result.append(ws / period)
    for i in range(period, len(values)):
        ws += values[i] - values[i - period]
        result.append(ws / period)
    return result


def slope(series: list[float | None], lookback: int = 5) -> float | None:
    """Recent slope as (latest - N bars ago) / N."""
    clean = [v for v in series if v is not None]
    if len(clean) < lookback + 1:
        return None
    prev = clean[-lookback - 1]
    curr = clean[-1]
    if prev == 0:
        return None
    return (curr - prev) / abs(prev) / lookback


def max_retrace_pct(
    closes: list[float], lookback: int = 60
) -> float | None:
    """Retracement from highest close in lookback window to current close."""
    if len(closes) < lookback:
        return None
    peak = max(closes[-lookback:])
    current = closes[-1]
    if peak <= 0:
        return None
    return (peak - current) / peak


# ── W1 战略资格 ─────────────────────────────────────────────


@dataclass
class W1Status:
    qualified: bool
    veto_reason: str = ""
    close: float | None = None
    ma25: float | None = None
    ma25_slope: float | None = None
    ma144: float | None = None
    ma169: float | None = None
    ma200: float | None = None
    arrangement: str = ""


def check_w1(bars: list[dict[str, Any]]) -> W1Status:
    """W1 一票否决检查。"""
    if len(bars) < 60:
        return W1Status(False, veto_reason="W1 数据不足")

    closes = [float(b["close"]) for b in bars]
    ma25 = sma(closes, 25)
    ma144 = sma(closes, 144)
    ma169 = sma(closes, 169)
    ma200 = sma(closes, 200)

    cur_close = closes[-1]
    cur_ma25 = ma25[-1]
    ma25_slope_val = slope(ma25, 5)
    cur_ma144 = ma144[-1]
    cur_ma169 = ma169[-1]
    cur_ma200 = ma200[-1]

    if None in (cur_ma25, cur_ma144, cur_ma169, cur_ma200, ma25_slope_val):
        return W1Status(False, veto_reason="W1 均线数据不足")

    # Arrangement
    if cur_ma144 > cur_ma169 > cur_ma200:
        arrangement = "多头排列"
    elif cur_ma144 < cur_ma169 < cur_ma200:
        arrangement = "空头排列"
    else:
        arrangement = "混合排列"

    # Veto conditions (any one triggers)
    vetoes: list[str] = []

    # 1. close < MA25 AND MA25 slope down
    if cur_close < cur_ma25 and ma25_slope_val < 0:
        vetoes.append("W1 close < MA25 且 MA25 斜率向下")

    # 2. bearish arrangement
    if arrangement == "空头排列":
        vetoes.append("W1 MA144/169/200 空头排列")

    if vetoes:
        reason = "；".join(vetoes)
        return W1Status(
            False,
            veto_reason=reason,
            close=cur_close, ma25=cur_ma25, ma25_slope=ma25_slope_val,
            ma144=cur_ma144, ma169=cur_ma169, ma200=cur_ma200,
            arrangement=arrangement,
        )

    return W1Status(
        True,
        close=cur_close, ma25=cur_ma25, ma25_slope=ma25_slope_val,
        ma144=cur_ma144, ma169=cur_ma169, ma200=cur_ma200,
        arrangement=arrangement,
    )


# ── D1 回调评估 ─────────────────────────────────────────────


@dataclass
class D1Pullback:
    is_healthy: bool
    tier: str = ""  # "强通过" / "边界观察" / "失败"
    status: str = ""  # 中文状态描述
    close: float | None = None
    ma25: float | None = None
    ma25_slope: float | None = None
    vma5: float | None = None
    vma60: float | None = None
    is_green: bool = False
    retrace_pct: float | None = None
    overextension_pct: float | None = None  # D1 close 相对 MA25 的偏离百分比
    consecutive_red: int = 0
    details: list[str] = field(default_factory=list)


def check_d1_pullback(bars: list[dict[str, Any]]) -> D1Pullback:
    """D1 判断：强通过 / 边界观察 / 失败。"""
    if len(bars) < 80:
        return D1Pullback(False, tier="失败", status="数据不足")

    closes = [float(b["close"]) for b in bars]
    opens = [float(b["open"]) for b in bars]
    volumes = [float(b["volume"]) for b in bars]
    ma25 = sma(closes, 25)
    vma5 = sma(volumes, 5)
    vma60 = sma(volumes, 60)

    cur_close = closes[-1]
    cur_open = opens[-1]
    cur_ma25 = ma25[-1]
    ma25_slope_val = slope(ma25, 5)
    cur_vma5 = vma5[-1]
    cur_vma60 = vma60[-1]
    is_green = cur_close > cur_open
    retrace = max_retrace_pct(closes, 60)
    overextension = ((cur_close / cur_ma25) - 1.0) if cur_ma25 and cur_ma25 > 0 else None

    # consecutive red candles (high volume only: volume > VMA60)
    cons_red = 0
    for i in range(len(closes) - 1, max(0, len(closes) - 10) - 1, -1):
        if closes[i] < opens[i] and (vma60[i] is not None and volumes[i] > vma60[i]):
            cons_red += 1
        else:
            break

    if cur_ma25 is None:
        return D1Pullback(False, tier="失败", status="数据不足")

    # ── 失败条件 ──
    fail_flags: list[str] = []

    if retrace is not None and retrace > 0.25:
        fail_flags.append(f"回调深度 {retrace:.1%} > 25%")
    if cons_red >= 3:
        fail_flags.append(f"连续 {cons_red} 天放量阴线")
    if ma25_slope_val is not None and ma25_slope_val < -0.02:
        fail_flags.append("D1 MA25 斜率明确向下")

    if fail_flags:
        return D1Pullback(False, tier="失败", status="趋势失败",
                          close=cur_close, ma25=cur_ma25, ma25_slope=ma25_slope_val,
                          vma5=cur_vma5, vma60=cur_vma60, is_green=is_green,
                          retrace_pct=retrace, overextension_pct=overextension,
                          consecutive_red=cons_red, details=fail_flags)

    # ── 强通过：close > MA25 且 slope >= 0 ──
    if cur_close > cur_ma25 and ma25_slope_val is not None and ma25_slope_val >= 0:
        return D1Pullback(True, tier="强通过", status="正常行进",
                          close=cur_close, ma25=cur_ma25, ma25_slope=ma25_slope_val,
                          vma5=cur_vma5, vma60=cur_vma60, is_green=is_green,
                          retrace_pct=retrace, overextension_pct=overextension,
                          consecutive_red=cons_red)

    # ── 边界观察：close < MA25 但无失败信号，或 slope 轻微走平 ──
    if cur_close < cur_ma25 and cur_vma5 is not None and cur_vma5 < cur_vma60:
        return D1Pullback(True, tier="边界观察", status="缩量回踩",
                          close=cur_close, ma25=cur_ma25, ma25_slope=ma25_slope_val,
                          vma5=cur_vma5, vma60=cur_vma60, is_green=is_green,
                          retrace_pct=retrace, overextension_pct=overextension,
                          consecutive_red=cons_red)

    return D1Pullback(True, tier="边界观察", status="横盘整理",
                      close=cur_close, ma25=cur_ma25, ma25_slope=ma25_slope_val,
                      vma5=cur_vma5, vma60=cur_vma60, is_green=is_green,
                      retrace_pct=retrace, overextension_pct=overextension,
                      consecutive_red=cons_red)


# ── M30 触发评分 ────────────────────────────────────────────


@dataclass
class M30Trigger:
    triggered: bool
    score: int = 0  # 0-100
    close: float | None = None
    ma25: float | None = None
    ma25_slope: float | None = None
    vma5: float | None = None
    vma60: float | None = None
    is_green: bool = False
    broke_recent_high: bool = False
    bounced_off_ma25: bool = False
    ts: str = ""
    details: list[str] = field(default_factory=list)


def check_m30_trigger(bars: list[dict[str, Any]]) -> M30Trigger:
    """M30 二次触发检查 + 评分。"""
    if len(bars) < 80:
        return M30Trigger(False, score=0, details=["M30 数据不足"])

    closes = [float(b["close"]) for b in bars]
    opens = [float(b["open"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    volumes = [float(b["volume"]) for b in bars]
    ma25 = sma(closes, 25)
    vma5 = sma(volumes, 5)
    vma60 = sma(volumes, 60)

    cur_close = closes[-1]
    cur_open = opens[-1]
    cur_ma25 = ma25[-1]
    ma25_slope_val = slope(ma25, 5)
    cur_vma5 = vma5[-1]
    cur_vma60 = vma60[-1]
    is_green = cur_close > cur_open
    ts = bars[-1].get("ts", "")

    if cur_ma25 is None or ma25_slope_val is None:
        return M30Trigger(False, score=0, details=["M30 MA25 数据不足"], ts=ts)

    score = 0
    details: list[str] = []

    # ── 必选条件 (0-50 分) ──
    must_pass = True
    # Must 1: close > MA25 (30 分)
    if cur_close > cur_ma25:
        score += 30
    else:
        must_pass = False
        details.append("M30 close < MA25")

    # Must 2: MA25 slope not down (20 分)
    if ma25_slope_val >= -0.001:
        score += 20
    elif ma25_slope_val < -0.005:
        must_pass = False
        details.append("M30 MA25 斜率向下")

    if not must_pass:
        return M30Trigger(False, score=score, close=cur_close, ma25=cur_ma25,
                          ma25_slope=ma25_slope_val, vma5=cur_vma5, vma60=cur_vma60,
                          is_green=is_green, ts=ts, details=details)

    # ── 加分项 (0-50 分) ──
    # Bonus 1: VMA5 > VMA60 (15 分)
    if cur_vma5 is not None and cur_vma60 is not None and cur_vma5 > cur_vma60:
        score += 15
        details.append("VMA5 > VMA60")
    else:
        details.append("VMA5 ≤ VMA60")

    # Bonus 2: Green candle (10 分)
    if is_green:
        score += 10
        details.append("收阳")
    else:
        details.append("收阴")

    # Bonus 3: Broke recent M30 high in last 16 bars (~1 day) (15 分)
    if len(highs) >= 17:
        recent_high = max(highs[-17:-1])
        if cur_close > recent_high:
            score += 15
            details.append("突破 M30 小平台高点")
            broke_recent_high = True
        else:
            broke_recent_high = False
    else:
        broke_recent_high = False

    # Bonus 4: Bounce off MA25 (10 分) — low of last 8 bars touched near MA25 then recovered
    bounced = False
    if len(lows) >= 9:
        low_8 = min(lows[-9:-1])
        if low_8 <= cur_ma25 * 1.01 and cur_close > cur_ma25 * 1.005:
            score += 10
            bounced = True
            details.append("回踩 MA25 后拉起")

    triggered = score >= 50

    return M30Trigger(
        triggered=triggered, score=score,
        close=cur_close, ma25=cur_ma25, ma25_slope=ma25_slope_val,
        vma5=cur_vma5, vma60=cur_vma60, is_green=is_green,
        broke_recent_high=broke_recent_high, bounced_off_ma25=bounced,
        ts=ts, details=details,
    )


# ── 出场计算 ─────────────────────────────────────────────────


def calc_stop_price(m30_bars: list[dict[str, Any]]) -> float | None:
    """止损价 = 本次 M30 触发前 32 根 bar 的最低点下方 0.5%。"""
    if len(m30_bars) < 33:
        return None
    recent_low = min(float(b["low"]) for b in m30_bars[-33:-1])
    return round(recent_low * 0.995, 2)


def calc_entry_price(m30_bars: list[dict[str, Any]]) -> float | None:
    """入场参考价 = 最新 M30 close。"""
    if not m30_bars:
        return None
    return round(float(m30_bars[-1]["close"]), 2)


# ── 主流程 ───────────────────────────────────────────────────


def scan_signals(
    foundation_db: Path,
    m30_db: Path,
    obs_date: date,
    stock_codes: list[str],
    stock_names: dict[str, str],
) -> list[dict[str, Any]]:
    """扫描所有股票，返回信号列表。"""
    w1_bars = load_bars(foundation_db, "W1", stock_codes, obs_date)
    d1_bars = load_bars(foundation_db, "D1", stock_codes, obs_date)
    m30_bars = load_m30_bars(m30_db, stock_codes, obs_date)

    signals: list[dict[str, Any]] = []
    scanned = 0
    for code in stock_codes:
        wb = w1_bars.get(code, [])
        db_bars = d1_bars.get(code, [])
        mb = m30_bars.get(code, [])

        if not wb or not db_bars or not mb:
            continue
        if len(mb) < 80:
            continue
        scanned += 1

        w1 = check_w1(wb)
        d1 = check_d1_pullback(db_bars)
        m30 = check_m30_trigger(mb)

        # Aggregate
        entry_p = calc_entry_price(mb)
        stop_p = calc_stop_price(mb)
        risk_width = abs((entry_p - stop_p) / entry_p) if entry_p and stop_p and entry_p > 0 else None
        overext_pct = d1.overextension_pct
        overextension = overext_pct is not None and overext_pct > 0.15

        signal: dict[str, Any] = {
            "stock_code": code,
            "stock_name": stock_names.get(code, ""),
            "scan_date": obs_date.isoformat(),
            "signal_time": m30.ts,
            "w1_qualified": w1.qualified,
            "w1_veto_reason": w1.veto_reason,
            "w1_arrangement": w1.arrangement,
            "w1_close_vs_ma25": "上方" if (w1.close is not None and w1.ma25 is not None and w1.close > w1.ma25) else "下方" if w1.close is not None else "N/A",
            "d1_tier": d1.tier,
            "d1_status": d1.status,
            "d1_close": d1.close,
            "d1_ma25": d1.ma25,
            "d1_ma25_slope": f"{d1.ma25_slope:.4f}" if d1.ma25_slope else "N/A",
            "d1_overextension_pct": f"{overext_pct:.1%}" if overext_pct is not None else "N/A",
            "d1_retrace_pct": f"{d1.retrace_pct:.1%}" if d1.retrace_pct else "N/A",
            "d1_consecutive_red": d1.consecutive_red,
            "m30_triggered": m30.triggered,
            "m30_score": m30.score,
            "m30_details": m30.details,
            "m30_close": m30.close,
            "m30_ma25": m30.ma25,
            "m30_ma25_slope": f"{m30.ma25_slope:.4f}" if m30.ma25_slope else "N/A",
            "entry_price": entry_p,
            "stop_price": stop_p,
            "risk_width_pct": f"{risk_width:.1%}" if risk_width is not None else "N/A",
            "overextension_flag": overextension,
            "risk_flags": [],
        }

        # Build risk flags
        if d1.tier == "失败":
            signal["risk_flags"].append("D1 趋势失败")
        if d1.consecutive_red >= 3:
            signal["risk_flags"].append(f"D1 连续 {d1.consecutive_red} 天放量阴线")
        if w1.arrangement == "空头排列":
            signal["risk_flags"].append("W1 空头排列")
        if overextension:
            signal["risk_flags"].append(f"D1 乖离过大 ({overext_pct:.1%})")
        if risk_width is not None and risk_width > 0.25:
            signal["risk_flags"].append(f"止损宽度过大 ({risk_width:.1%})")

        # ── 信号分级 A / B / C ──
        w1_strong = w1.qualified and w1.close is not None and w1.ma25 is not None and w1.close > w1.ma25
        d1_strong = d1.tier == "强通过"
        d1_borderline = d1.tier == "边界观察"
        m30_ok = m30.triggered

        if w1_strong and d1_strong and m30_ok and not overextension and (risk_width is None or risk_width <= 0.25):
            grade = "A"
        elif w1.qualified and d1_borderline and m30_ok and not overextension and (risk_width is None or risk_width <= 0.25):
            grade = "B"
        elif m30.triggered:
            grade = "C"
        else:
            grade = "-"

        signal["signal_grade"] = grade
        eligible = grade in ("A", "B")
        signal["eligible"] = eligible

        signals.append(signal)

    # Sort: eligible first, then by M30 score desc
    signals.sort(key=lambda s: (not s["eligible"], -s["m30_score"]))
    return signals


def render_markdown(signals: list[dict[str, Any]]) -> str:
    a_count = sum(1 for s in signals if s.get("signal_grade") == "A")
    b_count = sum(1 for s in signals if s.get("signal_grade") == "B")
    c_count = sum(1 for s in signals if s.get("signal_grade") == "C")
    lines = [
        "# M30 2560 回调二波信号",
        "",
        f"扫描日期: {signals[0]['scan_date'] if signals else 'N/A'}",
        f"总信号数: {len(signals)} | A类(强): {a_count} | B类(边界): {b_count} | C类(仅观察): {c_count} | 否决: {len(signals)-a_count-b_count-c_count}",
        "",
        f"**{REQUIRED_DISCLAIMER}**",
        "",
        "---",
        "",
    ]

    for s in signals:
        grade = s.get("signal_grade", "-")
        if grade in ("A", "B"):
            tag = f"✅ {grade}类"
        elif grade == "C":
            tag = f"🔶 C类（仅观察）"
        else:
            tag = f"❌ 否决"
        lines.extend([
            f"## {s['stock_code']} {s['stock_name']} {tag}",
            "",
            f"| 层级 | 状态 | 详情 |",
            f"|------|------|------|",
            f"| W1 战略 | {'通过' if s['w1_qualified'] else '否决'} | 排列:{s['w1_arrangement']} close:{s['w1_close_vs_ma25']}MA25 |",
            f"| D1 回调 | {s['d1_tier']} ({s['d1_status']}) | 回撤:{s['d1_retrace_pct']} 乖离:{s['d1_overextension_pct']} 连阴:{s['d1_consecutive_red']}d |",
            f"| M30 触发 | {'触发' if s['m30_triggered'] else '未触发'} | 评分:{s['m30_score']}/100 {' '.join(s['m30_details'])} |",
            "",
            f"入场参考: ¥{s['entry_price']} | 止损参考: ¥{s['stop_price']} | 风险宽度: {s['risk_width_pct']}",
            f"过热标志: {'是' if s.get('overextension_flag') else '否'} | 风险标志: {', '.join(s['risk_flags']) if s['risk_flags'] else '无'}",
            f"否决原因: {s['w1_veto_reason'] if not s['w1_qualified'] else 'W1通过'}",
            "",
        ])

    lines.append(f"*{REQUIRED_DISCLAIMER}*")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="M30 2560 回调二波信号扫描")
    p.add_argument("--date", default=date.today().isoformat(), help="扫描日期")
    p.add_argument("--foundation-db", required=True, help="p116_foundation.duckdb 路径")
    p.add_argument("--m30-db", required=True, help="blackwolf M30 DuckDB 路径")
    p.add_argument("--universe", default=str(DEFAULT_UNIVERSE), help="股票 CSV")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    obs_date = date.fromisoformat(args.date)

    # Load universe
    names: dict[str, str] = {}
    codes: list[str] = []
    with open(args.universe, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            c = row["stock_code"].strip()
            if c:
                codes.append(c)
                names[c] = row.get("stock_name", "").strip()

    signals = scan_signals(
        Path(args.foundation_db), Path(args.m30_db),
        obs_date, codes, names,
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"m30_2560_second_wave_{obs_date.strftime('%Y%m%d')}"

    json_path = out_dir / f"{stem}.json"
    json_path.write_text(
        json.dumps({"scan_date": obs_date.isoformat(), "signals": signals, "disclaimer": REQUIRED_DISCLAIMER},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    md_path = out_dir / f"{stem}.md"
    md_path.write_text(render_markdown(signals), encoding="utf-8")

    a_count = sum(1 for s in signals if s.get("signal_grade") == "A")
    b_count = sum(1 for s in signals if s.get("signal_grade") == "B")
    c_count = sum(1 for s in signals if s.get("signal_grade") == "C")
    print(json.dumps({
        "ok": True,
        "total": len(signals),
        "grade_A": a_count,
        "grade_B": b_count,
        "grade_C": c_count,
        "json": str(json_path),
        "markdown": str(md_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
