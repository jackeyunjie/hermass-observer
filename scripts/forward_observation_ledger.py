#!/usr/bin/env python3
"""Build a forward observation ledger from daily strategy reminders.

This is deliberately not a trading simulator. It records reminder-eligible
strategy signals, their State environment, a reference close, and future return
labels when the data is already available. It does not infer exits, fills,
position sizing, or portfolio actions.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vcp_exit_manager import simulate_vcp_trade
from ma2560_execution_manager import simulate_ma2560_trade
from bollinger_execution_manager import simulate_bollinger_trade
OUT_DIR = ROOT / "outputs" / "forward_observation"
PUBLIC_DIR = ROOT / "public"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def code6(value: Any) -> str:
    text = str(value or "").upper().strip()
    digits = "".join(ch for ch in text.split(".", 1)[0] if ch.isdigit())
    return digits[-6:] if digits else text


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def percent(value: Any) -> str:
    val = safe_float(value)
    if val is None:
        return "-"
    return f"{val * 100:.2f}%"


def parse_windows(value: str) -> list[int]:
    windows: list[int] = []
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        window = int(raw)
        if window <= 0:
            raise ValueError(f"window must be positive: {window}")
        if window not in windows:
            windows.append(window)
    if not windows:
        raise ValueError("at least one forward window is required")
    return sorted(windows)


def foundation_db_for(date_str: str, override: str | None) -> Path:
    if override:
        path = Path(override)
        return path if path.is_absolute() else (ROOT / path).resolve()
    exact = ROOT / "outputs" / f"p116_foundation_{ymd(date_str)}" / "p116_foundation.duckdb"
    if exact.exists():
        return exact
    candidates = sorted(ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"))
    if not candidates:
        raise FileNotFoundError("No p116 foundation DB found under outputs/")
    return candidates[-1]


def load_json(path: Path, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_reminder(date_str: str) -> dict[str, Any]:
    path = ROOT / "outputs" / "strategy_reminders" / f"reminder_{ymd(date_str)}.json"
    return load_json(path, required=True)


def load_state_reference_close(date_str: str) -> dict[str, float]:
    path = ROOT / "outputs" / "state_cache" / f"state_ef_{ymd(date_str)}.json"
    payload = load_json(path, required=True)
    out: dict[str, float] = {}
    for row in payload.get("rows", []) or []:
        close = safe_float(row.get("d1_close"))
        if close is not None and close > 0:
            out[code6(row.get("stock_code"))] = close
    return out


def load_price_window(db_path: Path, date_str: str, max_window: int) -> tuple[
    dict[str, list[tuple[str, float]]],
    dict[str, list[tuple[str, float]]],
    dict[str, list[tuple[str, float]]],
    list[str],
]:
    start = date.fromisoformat(date_str)
    # Ensure enough forward data for VCP time exit (20d) plus buffer
    end = start + timedelta(days=max(max_window * 3 + 15, 90))
    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute(
        """
        SELECT stock_code, date::VARCHAR AS date, close
        FROM daily_bars
        WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        ORDER BY stock_code, date
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    con.close()

    by_code: dict[str, list[tuple[str, float]]] = defaultdict(list)
    ma25_by_code: dict[str, list[tuple[str, float]]] = defaultdict(list)
    ma60_by_code: dict[str, list[tuple[str, float]]] = defaultdict(list)
    trading_dates: set[str] = set()
    for stock_code, obs_date, close in rows:
        close_val = safe_float(close)
        if close_val is None or close_val <= 0:
            continue
        d = str(obs_date)
        key = code6(stock_code)
        by_code[key].append((d, close_val))
        trading_dates.add(d)
    return dict(by_code), {}, {}, sorted(trading_dates)


def load_bollinger_ohlc_window(db_path: Path, date_str: str, max_window: int) -> dict[str, list[dict[str, Any]]]:
    """Load OHLCV data for Bollinger Bandit exit simulation."""
    start = date.fromisoformat(date_str)
    end = start + timedelta(days=max(max_window * 3 + 15, 90))
    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute(
        """
        SELECT stock_code, date::VARCHAR AS date, open, high, low, close, volume
        FROM daily_bars
        WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        ORDER BY stock_code, date
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    con.close()

    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stock_code, d, o, h, l, c, v in rows:
        close_val = safe_float(c)
        if close_val is None or close_val <= 0:
            continue
        by_code[code6(stock_code)].append({
            "date": str(d),
            "open": safe_float(o) or 0,
            "high": safe_float(h) or 0,
            "low": safe_float(l) or 0,
            "close": close_val,
            "volume": safe_float(v) or 0,
        })
    return dict(by_code)


def stock_forward_return(series: list[tuple[str, float]], date_str: str, window: int) -> tuple[float | None, str | None, float | None]:
    if not series:
        return None, None, None
    idx = next((i for i, item in enumerate(series) if item[0] >= date_str), None)
    if idx is None or idx + window >= len(series):
        return None, None, None
    start_close = series[idx][1]
    target_date, target_close = series[idx + window]
    if start_close <= 0:
        return None, None, None
    return target_close / start_close - 1.0, target_date, target_close


def market_equal_weight_return(
    by_code: dict[str, list[tuple[str, float]]],
    date_str: str,
    window: int,
    cache: dict[tuple[str, int], float | None],
) -> float | None:
    key = (date_str, window)
    if key in cache:
        return cache[key]
    values: list[float] = []
    for series in by_code.values():
        ret, _, _ = stock_forward_return(series, date_str, window)
        if ret is not None and math.isfinite(ret):
            values.append(ret)
    if not values:
        cache[key] = None
        return None
    out = statistics.fmean(values)
    cache[key] = out
    return out


def load_mn1_enrichment(db_path: Path, date_str: str) -> dict[str, dict[str, Any]]:
    """Load MN1 state enrichment fields from Foundation DB.

    Returns: {stock_code_6: {mn1_score, mn1_trend, mn1_volatility}}
    """
    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute("""
        SELECT stock_code, mn1_state_score, mn1_trend, mn1_volatility
        FROM d1_perspective_state
        WHERE state_date = CAST(? AS DATE)
    """, [date_str]).fetchall()
    con.close()
    out: dict[str, dict[str, Any]] = {}
    for code, score, trend, vol in rows:
        c6 = code6(code)
        out[c6] = {
            "mn1_score": score,
            "mn1_trend": trend or "",
            "mn1_volatility": vol or "",
        }
    return out


def _classify_mn1_regime(score: int | None, trend: str) -> str:
    """Classify MN1 environment into one of 5 regime types."""
    if score is None:
        return "unknown"
    if score < 0:
        return "破位环境"
    if score in (14, 15):
        return "牛市环境_E/F"
    if score >= 12:
        return "震荡偏强_C/D"
    if score >= 8:
        return "扩张未突破_8-B"
    return "收缩环境_0-7"


def _compute_mn1_regime_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute per-MN1-regime signal count distribution."""
    from collections import Counter, defaultdict
    regime_counts: Counter[str] = Counter()
    regime_strategy: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        score = row.get("mn1_score")
        trend = row.get("mn1_trend", "")
        regime = _classify_mn1_regime(score, trend)
        regime_counts[regime] += 1
        sid = row.get("strategy_id", "")
        regime_strategy[regime][sid] += 1
    return {
        "regime_distribution": dict(sorted(regime_counts.items())),
        "regime_by_strategy": {k: dict(sorted(v.items())) for k, v in sorted(regime_strategy.items())},
        "regime_labels": {
            "牛市环境_E/F": "MN1=E/F：扩张+有趋势+突破，牛市确认",
            "震荡偏强_C/D": "MN1=C/D：扩张但有趋势未突破，震荡偏强",
            "扩张未突破_8-B": "MN1=8-B：扩张但无趋势突破，方向待定",
            "收缩环境_0-7": "MN1=0-7：收缩状态，熊市/底部区域",
            "破位环境": "MN1为负值：月线破位，不交易",
            "unknown": "无法分类（数据缺失）",
        },
    }


def build_observation_rows(
    reminder_payload: dict[str, Any],
    reference_close: dict[str, float],
    by_code: dict[str, list[tuple[str, float]]],
    ma25_by_code: dict[str, list[tuple[str, float]]],
    ma60_by_code: dict[str, list[tuple[str, float]]],
    windows: list[int],
    bollinger_ohlc_by_code: dict[str, list[dict[str, Any]]] | None = None,
    mn1_enrichment: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    date_str = str(reminder_payload.get("date"))
    market_cache: dict[tuple[str, int], float | None] = {}
    rows: list[dict[str, Any]] = []
    for card in reminder_payload.get("reminders", []) or []:
        code = code6(card.get("stock_code"))
        strategy = card.get("strategy") or {}
        state = card.get("state_environment") or {}
        duration = card.get("state_duration") or {}
        evaluation = card.get("strategy_evaluation") or {}
        sr = card.get("sr_position") or {}
        ma2560 = card.get("ma2560_environment") or {}
        ref_close = reference_close.get(code)
        item: dict[str, Any] = {
            "date": date_str,
            "stock_code": card.get("stock_code"),
            "stock_code_6": code,
            "stock_name": card.get("stock_name"),
            "strategy_id": strategy.get("strategy_id"),
            "signal_type": strategy.get("signal_type"),
            "signal_name": strategy.get("signal_name"),
            "signal_strength": strategy.get("signal_strength"),
            "maturity": card.get("maturity"),
            "lifecycle_stage": card.get("lifecycle_stage"),
            "strategy_environment_fit": card.get("strategy_environment_fit"),
            "fit_reasons": card.get("fit_reasons"),
            "ma2560_local_combo_pass": bool(ma2560.get("local_combo_pass")),
            "ma2560_p116_state_match": bool(ma2560.get("p116_state_match")),
            "ma2560_market_match_level": ma2560.get("market_match_level") or "not_match",
            "ma2560_state_combo": ma2560.get("state_combo") or "",
            "vcp_path_match": bool((card.get("vcp_environment") or {}).get("path_match")),
            "local_stat_note": card.get("local_stat_note") or "",
            "environment_tags": card.get("environment_tags") or [],
            "reference_close": ref_close,
            "mn1_state": state.get("mn1_state"),
            "w1_state": state.get("w1_state"),
            "d1_state": state.get("d1_state"),
            "ef_count": state.get("ef_count"),
            "state_score_sum": state.get("state_score_sum"),
            "d1_ef_duration": duration.get("d1_ef_duration"),
            "all_three_ef_duration": duration.get("all_three_ef_duration"),
            "sr_boundary_direction": sr.get("boundary_direction"),
            "sr_distance_pct": sr.get("distance_pct"),
            "evidence_tier": evaluation.get("evidence_tier"),
            "evidence_score": evaluation.get("evidence_score"),
            "calibration_status": (card.get("calibration") or {}).get("status"),
        }
        # ── MN1 enrichment from Foundation DB ──
        mn1 = (mn1_enrichment or {}).get(code, {})
        item["mn1_score"] = mn1.get("mn1_score")
        item["mn1_trend"] = mn1.get("mn1_trend", "")
        item["mn1_volatility"] = mn1.get("mn1_volatility", "")
        # ── VCP real exit simulation (supplements fixed-window returns) ──
        vcp_conf = card.get("vcp_entry_confirmation")
        vcp_stops = card.get("vcp_stop_prices")
        if strategy.get("strategy_id") == "vcp" and strategy.get("signal_type") == "entry" and vcp_stops and ref_close is not None:
            entry_data = {
                "date": date_str,
                "entry_price": ref_close,
                "pivot_point": vcp_stops.get("pivot_point", ref_close),
                "contraction_low": vcp_stops.get("contraction_low", (ref_close or 0) * 0.94),
                "entry_atr": vcp_stops.get("entry_atr", 0),
            }
            trade_result = simulate_vcp_trade(entry_data, by_code.get(code, []))
            item["vcp_exit_status"] = trade_result.get("status")
            item["vcp_exit_date"] = trade_result.get("exit_date") or trade_result.get("last_date")
            item["vcp_exit_price"] = trade_result.get("exit_price") or trade_result.get("last_price")
            item["vcp_hold_days"] = trade_result.get("hold_days")
            item["vcp_exit_reason"] = trade_result.get("exit_reason")
            item["vcp_exit_type"] = trade_result.get("exit_type")
            item["vcp_pnl_pct"] = trade_result.get("pnl_pct")
            pos = trade_result.get("position") or {}
            item["vcp_position_shares"] = pos.get("shares")
            item["vcp_position_value"] = pos.get("position_value")
            item["vcp_conservative_stop"] = (trade_result.get("stop_prices") or {}).get("conservative_stop")
        else:
            item["vcp_exit_status"] = "not_vcp"

        # ── 2560 real exit simulation (supplements fixed-window returns) ──
        ma2560_entry_conf = card.get("ma2560_entry_confirmation")
        if strategy.get("strategy_id") == "ma2560" and strategy.get("signal_type") == "entry" and ref_close is not None:
            entry_data = {
                "date": date_str,
                "entry_price": ref_close,
                "pullback_count": (ma2560_entry_conf or {}).get("pullback_count", 0),
            }
            trade_result = simulate_ma2560_trade(
                entry_data,
                by_code.get(code, []),
                ma25_by_code.get(code, []),
                ma60_by_code.get(code, []),
            )
            item["ma2560_exit_status"] = trade_result.get("status")
            item["ma2560_exit_date"] = trade_result.get("exit_date") or trade_result.get("last_date")
            item["ma2560_exit_price"] = trade_result.get("exit_price") or trade_result.get("last_price")
            item["ma2560_hold_days"] = trade_result.get("hold_days")
            item["ma2560_exit_reason"] = trade_result.get("exit_reason")
            item["ma2560_exit_type"] = trade_result.get("exit_type")
            item["ma2560_exit_pct"] = trade_result.get("exit_pct")
            item["ma2560_pnl_pct"] = trade_result.get("pnl_pct")
            item["ma2560_half_exited"] = trade_result.get("half_exited")
            item["ma2560_full_exited"] = trade_result.get("full_exited")
        else:
            item["ma2560_exit_status"] = "not_ma2560"

        # ── Bollinger Bandit real exit simulation (supplements fixed-window returns) ──
        if strategy.get("strategy_id") == "bollinger_bandit" and strategy.get("signal_type") == "entry" and ref_close is not None:
            ohlc_series = (bollinger_ohlc_by_code or {}).get(code, [])
            if ohlc_series:
                entry_data = {
                    "date": date_str,
                    "entry_price": ref_close,
                    "entry_atr": 0,  # computed from series
                }
                trade_result = simulate_bollinger_trade(entry_data, ohlc_series)
                item["bollinger_exit_status"] = trade_result.get("status")
                item["bollinger_exit_date"] = trade_result.get("exit_date") or trade_result.get("last_date")
                item["bollinger_exit_price"] = trade_result.get("exit_price") or trade_result.get("last_price")
                item["bollinger_hold_days"] = trade_result.get("hold_days")
                item["bollinger_exit_reason"] = trade_result.get("exit_reason")
                item["bollinger_exit_type"] = trade_result.get("exit_type")
                item["bollinger_pnl_pct"] = trade_result.get("pnl_pct")
                pos = trade_result.get("position") or {}
                item["bollinger_position_shares"] = pos.get("shares")
                item["bollinger_position_value"] = pos.get("position_value")
            else:
                item["bollinger_exit_status"] = "no_price_data"
        else:
            item["bollinger_exit_status"] = "not_bollinger"

        missing = False
        for window in windows:
            ret, target_date, target_close = stock_forward_return(by_code.get(code, []), date_str, window)
            bench = market_equal_weight_return(by_code, date_str, window, market_cache)
            item[f"target_date_{window}d"] = target_date
            item[f"target_close_{window}d"] = target_close
            item[f"forward_return_{window}d"] = ret
            item[f"market_equal_weight_return_{window}d"] = bench
            item[f"forward_excess_return_{window}d"] = ret - bench if ret is not None and bench is not None else None
            if ret is None or bench is None:
                missing = True
        item["label_status"] = "pending_future_data" if missing else "labeled"
        rows.append(item)
    return rows


def sample_progress_summary(rows: list[dict[str, Any]], windows: list[int]) -> dict[str, Any]:
    status_counts = Counter(row.get("label_status") for row in rows)
    strategy_counts = Counter(row.get("strategy_id") for row in rows)
    fit_counts = Counter(row.get("strategy_environment_fit") or "待观察" for row in rows)
    lifecycle_counts = Counter(row.get("lifecycle_stage") or row.get("maturity") or "未知" for row in rows)
    vcp_exited = [r for r in rows if r.get("vcp_exit_status") == "exited"]
    vcp_holding = [r for r in rows if r.get("vcp_exit_status") == "holding"]
    ma2560_exited = [r for r in rows if r.get("ma2560_exit_status") == "exited"]
    ma2560_holding = [r for r in rows if r.get("ma2560_exit_status") == "holding"]
    bollinger_exited = [r for r in rows if r.get("bollinger_exit_status") == "exited"]
    bollinger_holding = [r for r in rows if r.get("bollinger_exit_status") == "holding"]
    key_scene_counts = {
        "vcp_path_match": sum(1 for row in rows if row.get("strategy_id") == "vcp" and row.get("vcp_path_match")),
        "vcp_exited": len(vcp_exited),
        "vcp_holding": len(vcp_holding),
        "vcp_avg_hold_days": round(statistics.fmean([r["vcp_hold_days"] for r in vcp_exited if r.get("vcp_hold_days") is not None]), 1) if vcp_exited else 0,
        "vcp_exit_reasons": dict(Counter(r.get("vcp_exit_reason") for r in vcp_exited if r.get("vcp_exit_reason"))),
        "ma2560_exited": len(ma2560_exited),
        "ma2560_holding": len(ma2560_holding),
        "ma2560_avg_hold_days": round(statistics.fmean([r["ma2560_hold_days"] for r in ma2560_exited if r.get("ma2560_hold_days") is not None]), 1) if ma2560_exited else 0,
        "ma2560_exit_reasons": dict(Counter(r.get("ma2560_exit_reason") for r in ma2560_exited if r.get("ma2560_exit_reason"))),
        "bollinger_exited": len(bollinger_exited),
        "bollinger_holding": len(bollinger_holding),
        "bollinger_avg_hold_days": round(statistics.fmean([r["bollinger_hold_days"] for r in bollinger_exited if r.get("bollinger_hold_days") is not None]), 1) if bollinger_exited else 0,
        "bollinger_exit_reasons": dict(Counter(r.get("bollinger_exit_reason") for r in bollinger_exited if r.get("bollinger_exit_reason"))),
        "bollinger_volatility_stable": sum(
            1
            for row in rows
            if row.get("strategy_id") == "bollinger_bandit" and "波动稳定" in str(row.get("local_stat_note") or "")
        ),
        "ma2560_full_match": sum(
            1
            for row in rows
            if row.get("strategy_id") == "ma2560" and row.get("ma2560_market_match_level") == "full_match"
        ),
    }
    window_labeled = {}
    for window in windows:
        window_labeled[f"{window}d"] = sum(
            1
            for row in rows
            if row.get(f"forward_return_{window}d") is not None
            and row.get(f"market_equal_weight_return_{window}d") is not None
        )
    return {
        "total": len(rows),
        "labeled": status_counts.get("labeled", 0),
        "pending": status_counts.get("pending_future_data", 0),
        "status_distribution": dict(sorted(status_counts.items())),
        "strategy_distribution": dict(sorted(strategy_counts.items())),
        "fit_distribution": dict(sorted(fit_counts.items())),
        "lifecycle_distribution": dict(sorted(lifecycle_counts.items())),
        "key_scene_counts": key_scene_counts,
        "window_labeled": window_labeled,
    }


def csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fieldnames})


def generate_html(payload: dict[str, Any], windows: list[int]) -> str:
    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    def tag_text(value: Any) -> str:
        if isinstance(value, list):
            return " / ".join(str(item) for item in value) or "-"
        return str(value or "-")

    def row(item: dict[str, Any]) -> str:
        window_cells = []
        for window in windows:
            ret = item.get(f"forward_return_{window}d")
            excess = item.get(f"forward_excess_return_{window}d")
            target = item.get(f"target_date_{window}d")
            window_cells.append(
                f"<td>{percent(ret)}<br><span>超额 {percent(excess)} {esc(target or '待更新')}</span></td>"
            )
        ma2560_text = "-"
        if item.get("strategy_id") == "ma2560":
            ma2560_text = (
                f"{esc(item.get('ma2560_market_match_level') or 'not_match')}<br>"
                f"<span>{esc(item.get('ma2560_state_combo') or '')} "
                f"个股:{esc('是' if item.get('ma2560_local_combo_pass') else '否')} "
                f"P116:{esc('是' if item.get('ma2560_p116_state_match') else '否')}</span>"
            )
        # VCP real exit display
        vcp_text = "-"
        if item.get("strategy_id") == "vcp":
            vcp_status = item.get("vcp_exit_status")
            if vcp_status == "exited":
                vcp_text = (
                    f"{esc(item.get('vcp_exit_reason'))}<br>"
                    f"<span>{percent(item.get('vcp_pnl_pct'))} | {esc(item.get('vcp_hold_days'))}日 | "
                    f"{esc(item.get('vcp_exit_date'))}</span>"
                )
            elif vcp_status == "holding":
                vcp_text = (
                    f"持有中<br>"
                    f"<span>{percent(item.get('vcp_pnl_pct'))} | {esc(item.get('vcp_hold_days'))}日</span>"
                )
            elif vcp_status == "no_price_data":
                vcp_text = "无价格数据<br><span>无法模拟</span>"
            else:
                vcp_text = "未触发<br><span>非VCP入场</span>"

        # 2560 real exit display
        ma2560_text_exit = "-"
        if item.get("strategy_id") == "ma2560":
            ma2560_status = item.get("ma2560_exit_status")
            if ma2560_status == "exited":
                exit_pct = item.get("ma2560_exit_pct") or 1.0
                pct_text = "全部清仓" if exit_pct >= 1.0 else "减仓50%"
                ma2560_text_exit = (
                    f"{esc(item.get('ma2560_exit_reason'))}<br>"
                    f"<span>{percent(item.get('ma2560_pnl_pct'))} | {esc(item.get('ma2560_hold_days'))}日 | "
                    f"{esc(item.get('ma2560_exit_date'))} | {pct_text}</span>"
                )
            elif ma2560_status == "holding":
                ma2560_text_exit = (
                    f"持有中<br>"
                    f"<span>{percent(item.get('ma2560_pnl_pct'))} | {esc(item.get('ma2560_hold_days'))}日</span>"
                )
            elif ma2560_status == "no_price_data":
                ma2560_text_exit = "无价格数据<br><span>无法模拟</span>"
            else:
                ma2560_text_exit = "未触发<br><span>非2560入场</span>"

        # Bollinger real exit display
        bollinger_text_exit = "-"
        if item.get("strategy_id") == "bollinger_bandit":
            bollinger_status = item.get("bollinger_exit_status")
            if bollinger_status == "exited":
                bollinger_text_exit = (
                    f"{esc(item.get('bollinger_exit_reason'))}<br>"
                    f"<span>{percent(item.get('bollinger_pnl_pct'))} | {esc(item.get('bollinger_hold_days'))}日 | "
                    f"{esc(item.get('bollinger_exit_date'))}</span>"
                )
            elif bollinger_status == "holding":
                bollinger_text_exit = (
                    f"持有中<br>"
                    f"<span>{percent(item.get('bollinger_pnl_pct'))} | {esc(item.get('bollinger_hold_days'))}日</span>"
                )
            elif bollinger_status == "no_price_data":
                bollinger_text_exit = "无价格数据<br><span>无法模拟</span>"
            else:
                bollinger_text_exit = "未触发<br><span>非布林强盗入场</span>"

        return f"""
        <tr>
          <td><strong>{esc(item.get("stock_code"))}</strong><br><span>{esc(item.get("stock_name") or "")}</span></td>
          <td>{esc(item.get("strategy_id"))}<br><span>{esc(item.get("signal_name"))}</span></td>
          <td>{esc(item.get("lifecycle_stage") or item.get("maturity"))}<br><span>{esc(item.get("strategy_environment_fit") or "待观察")}</span></td>
          <td>{esc(item.get("fit_reasons") or "-")}<br><span>{esc(tag_text(item.get("environment_tags")))}</span></td>
          <td>{ma2560_text}</td>
          <td>MN1 {esc(item.get("mn1_state"))} / W1 {esc(item.get("w1_state"))} / D1 {esc(item.get("d1_state"))}<br><span>ef {esc(item.get("ef_count"))}, all-three {esc(item.get("all_three_ef_duration"))}</span></td>
          <td>{esc(item.get("reference_close"))}<br><span>{esc(item.get("label_status"))}</span></td>
          <td>{vcp_text}</td>
          <td>{ma2560_text_exit}</td>
          <td>{bollinger_text_exit}</td>
          {''.join(window_cells)}
        </tr>
        """

    headers = "".join(f"<th>{window}日观察</th>" for window in windows)
    rows = "\n".join(row(item) for item in payload.get("rows", []) or [])
    progress = payload.get("sample_progress") or {}
    scenes = progress.get("key_scene_counts") or {}
    strategy_dist = " / ".join(f"{key}:{value}" for key, value in (progress.get("strategy_distribution") or {}).items()) or "-"
    fit_dist = " / ".join(f"{key}:{value}" for key, value in (progress.get("fit_distribution") or {}).items()) or "-"
    window_dist = " / ".join(f"{key}:{value}" for key, value in (progress.get("window_labeled") or {}).items()) or "-"
    vcp_reasons = scenes.get("vcp_exit_reasons") or {}
    vcp_reason_text = " / ".join(f"{k}:{v}" for k, v in vcp_reasons.items()) if vcp_reasons else "-"
    ma2560_reasons = scenes.get("ma2560_exit_reasons") or {}
    ma2560_reason_text = " / ".join(f"{k}:{v}" for k, v in ma2560_reasons.items()) if ma2560_reasons else "-"
    bollinger_reasons = scenes.get("bollinger_exit_reasons") or {}
    bollinger_reason_text = " / ".join(f"{k}:{v}" for k, v in bollinger_reasons.items()) if bollinger_reasons else "-"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>前向观察账本 {esc(payload["date"])}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f8fb; color: #172033; }}
    main {{ max-width: 1440px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 26px; }}
    .meta {{ color: #5d6b82; margin: 0 0 18px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 0 0 18px; }}
    .metric {{ background: #fff; border: 1px solid #e1e6ef; border-radius: 6px; padding: 12px; }}
    .metric b {{ display: block; font-size: 20px; margin-top: 4px; }}
    .metric.wide {{ grid-column: span 2; }}
    .guardrails {{ background: #fff; border: 1px solid #e1e6ef; padding: 12px 14px; margin-bottom: 18px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e1e6ef; }}
    th, td {{ text-align: left; vertical-align: top; padding: 10px 12px; border-bottom: 1px solid #edf1f7; font-size: 13px; }}
    th {{ background: #f0f3f8; color: #344054; font-weight: 650; }}
    td span {{ color: #667085; font-size: 12px; }}
    tr:last-child td {{ border-bottom: 0; }}
  </style>
</head>
<body>
  <main>
    <h1>前向观察账本</h1>
    <p class="meta">日期 {esc(payload["date"])} | 样本 {payload["total"]} 条 | 已标注 {payload["labeled"]} 条 | 待更新 {payload["pending"]} 条</p>
    <div class="grid">
      <div class="metric">总样本<b>{esc(progress.get("total") or 0)}</b><span>提醒信号累计</span></div>
      <div class="metric">已标注<b>{esc(progress.get("labeled") or 0)}</b><span>未来窗口已可计算</span></div>
      <div class="metric">待更新<b>{esc(progress.get("pending") or 0)}</b><span>等待未来行情</span></div>
      <div class="metric">VCP已离场<b>{esc(scenes.get("vcp_exited") or 0)}</b><span>真实出场模拟</span></div>
      <div class="metric">VCP持有中<b>{esc(scenes.get("vcp_holding") or 0)}</b><span>未触发出场</span></div>
      <div class="metric">VCP平均持仓<b>{esc(scenes.get("vcp_avg_hold_days") or 0)}</b><span>交易日</span></div>
      <div class="metric wide">VCP出场分布<b>{esc(vcp_reason_text)}</b><span>按出场原因统计</span></div>
      <div class="metric">2560已离场<b>{esc(scenes.get("ma2560_exited") or 0)}</b><span>真实出场模拟</span></div>
      <div class="metric">2560持有中<b>{esc(scenes.get("ma2560_holding") or 0)}</b><span>未触发出场</span></div>
      <div class="metric">2560平均持仓<b>{esc(scenes.get("ma2560_avg_hold_days") or 0)}</b><span>交易日</span></div>
      <div class="metric wide">2560出场分布<b>{esc(ma2560_reason_text)}</b><span>按出场原因统计</span></div>
      <div class="metric">布林已离场<b>{esc(scenes.get("bollinger_exited") or 0)}</b><span>真实出场模拟</span></div>
      <div class="metric">布林持有中<b>{esc(scenes.get("bollinger_holding") or 0)}</b><span>未触发出场</span></div>
      <div class="metric">布林平均持仓<b>{esc(scenes.get("bollinger_avg_hold_days") or 0)}</b><span>交易日</span></div>
      <div class="metric wide">布林出场分布<b>{esc(bollinger_reason_text)}</b><span>按出场原因统计</span></div>
      <div class="metric">布林波动稳定<b>{esc(scenes.get("bollinger_volatility_stable") or 0)}</b><span>volatility_bit=0样本</span></div>
      <div class="metric">2560 full_match<b>{esc(scenes.get("ma2560_full_match") or 0)}</b><span>个股+行业共振样本</span></div>
      <div class="metric wide">策略分布<b>{esc(strategy_dist)}</b><span>样本积累进度</span></div>
      <div class="metric wide">适配分布<b>{esc(fit_dist)}</b><span>环境过滤样本</span></div>
      <div class="metric wide">窗口标注<b>{esc(window_dist)}</b><span>各观察窗口可用样本</span></div>
    </div>
    <div class="guardrails">VCP、2560 与布林强盗信号使用真实出场规则模拟；其他策略保留固定窗口观察。</div>
    <table>
      <thead>
        <tr>
          <th>代码</th>
          <th>策略信号</th>
          <th>生命周期/适配</th>
          <th>适配依据</th>
          <th>2560匹配</th>
          <th>State</th>
          <th>参考收盘</th>
          <th>VCP真实出场</th>
          <th>2560真实出场</th>
          <th>布林强盗真实出场</th>
          {headers}
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </main>
</body>
</html>
"""


def build_forward_observation(
    date_str: str,
    foundation_db: str | None = None,
    windows: list[int] | None = None,
    update_latest: bool = True,
) -> dict[str, Any]:
    windows = windows or [5, 10, 20]
    db_path = foundation_db_for(date_str, foundation_db)
    reminder = load_reminder(date_str)
    reference_close = load_state_reference_close(date_str)
    by_code, ma25_by_code, ma60_by_code, trading_dates = load_price_window(db_path, date_str, max(windows))

    # Load OHLC data for Bollinger Bandit exit simulation when needed
    has_bollinger = any(
        (card.get("strategy") or {}).get("strategy_id") == "bollinger_bandit"
        and (card.get("strategy") or {}).get("signal_type") == "entry"
        for card in reminder.get("reminders", [])
    )
    bollinger_ohlc_by_code = load_bollinger_ohlc_window(db_path, date_str, max(windows)) if has_bollinger else {}

    mn1_enrichment = load_mn1_enrichment(db_path, date_str)

    rows = build_observation_rows(reminder, reference_close, by_code, ma25_by_code, ma60_by_code, windows, bollinger_ohlc_by_code, mn1_enrichment)
    status_counts = Counter(row.get("label_status") for row in rows)
    strategy_counts = Counter(row.get("strategy_id") for row in rows)
    sample_progress = sample_progress_summary(rows, windows)

    mn1_regime_summary = _compute_mn1_regime_summary(rows)

    payload = {
        "schema_version": "forward_observation_v3_mn1_enriched",
        "mode": "observation_ledger",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "foundation_db": str(db_path),
        "windows": windows,
        "available_trading_dates": trading_dates,
        "total": len(rows),
        "labeled": status_counts.get("labeled", 0),
        "pending": status_counts.get("pending_future_data", 0),
        "status_distribution": dict(sorted(status_counts.items())),
        "strategy_distribution": dict(sorted(strategy_counts.items())),
        "sample_progress": sample_progress,
        "mn1_regime_summary": mn1_regime_summary,
        "guardrails": [
            "Consumes only strategy reminder rows generated from reminder_eligible signals.",
            "Records reference close and future return labels only when available.",
            "VCP, 2560 and Bollinger Bandit signals use real exit rule simulation.",
            "Other strategies retain fixed-window observation for backward compatibility.",
            "No advice language is generated.",
        ],
        "rows": rows,
        "research_only": True,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    date_ymd = ymd(date_str)
    json_path = OUT_DIR / f"forward_observation_{date_ymd}.json"
    csv_path = OUT_DIR / f"forward_observation_{date_ymd}.csv"
    html_path = PUBLIC_DIR / f"forward_observation_{date_ymd}.html"
    latest_json = OUT_DIR / "forward_observation_latest.json"
    latest_csv = OUT_DIR / "forward_observation_latest.csv"
    latest_html = PUBLIC_DIR / "forward_observation_latest.html"

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(text, encoding="utf-8")
    write_csv(csv_path, rows)
    html_text = generate_html(payload, windows)
    html_path.write_text(html_text, encoding="utf-8")

    if update_latest:
        latest_json.write_text(text, encoding="utf-8")
        write_csv(latest_csv, rows)
        latest_html.write_text(html_text, encoding="utf-8")

    return {
        "ok": True,
        "mode": "observation_ledger",
        "date": date_str,
        "foundation_db": str(db_path),
        "windows": windows,
        "total": len(rows),
        "labeled": payload["labeled"],
        "pending": payload["pending"],
        "status_distribution": payload["status_distribution"],
        "strategy_distribution": payload["strategy_distribution"],
        "json": str(json_path),
        "csv": str(csv_path),
        "html": str(html_path),
        "latest_json": str(latest_json) if update_latest else None,
        "latest_csv": str(latest_csv) if update_latest else None,
        "latest_html": str(latest_html) if update_latest else None,
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build forward observation ledger from strategy reminders.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--foundation-db")
    parser.add_argument("--windows", default="5,10,20", help="Comma-separated forward windows in trading days.")
    parser.add_argument("--no-update-latest", action="store_true", help="Do not update latest output aliases.")
    args = parser.parse_args()

    result = build_forward_observation(
        args.date,
        foundation_db=args.foundation_db,
        windows=parse_windows(args.windows),
        update_latest=not args.no_update_latest,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
