#!/usr/bin/env python3
"""
build_m30_observation_state.py
M30 准实时观察状态构建器。

输入：
  - state_cube (D1/W1/MN1 主状态)
  - m30_bars (本地 M30 行情，优先 merged，fallback 当日)

输出：
  - outputs/m30_observation/m30_observation_YYYYMMDD.duckdb
  - 表 m30_observation_state

原则：
  - M30 只做观察层，不单独拍板。
  - observation_label ∈ {confirm, watch, risk, invalid}
"""
import argparse
import sys
import json
import math
from datetime import datetime, date, time, timedelta
from pathlib import Path
from typing import Optional

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parent.parent

# ── paths ───────────────────────────────────────────────────────
STATE_CUBE_DB = ROOT / "outputs" / "state_cube" / "state_cube_m30.duckdb"
M30_MERGED_DB = ROOT / "data" / "blackwolf_m30_merged" / "blackwolf_m30.duckdb"
OUT_DIR = ROOT / "outputs" / "m30_observation"

# ── helpers ─────────────────────────────────────────────────────
def find_m30_db(trade_date: date) -> Optional[Path]:
    """优先 merged DB，其次当日 DB。"""
    p = M30_MERGED_DB
    if p.exists():
        return p
    p = ROOT / f"data/blackwolf_m30_{trade_date.strftime('%Y%m%d')}/blackwolf_m30.duckdb"
    if p.exists():
        return p
    return None


def ma(arr, n):
    if len(arr) < n:
        return [None] * len(arr)
    a = np.array(arr, dtype=float)
    cumsum = np.cumsum(np.insert(a, 0, 0.0))
    return (cumsum[n:] - cumsum[:-n]) / n


def atr14(highs, lows, closes):
    if len(closes) < 15:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    if len(trs) < 14:
        return None
    atr = np.mean(trs[:14])
    for tr in trs[14:]:
        atr = (atr * 13 + tr) / 14
    return float(atr)


def adx14(highs, lows):
    if len(highs) < 15:
        return None
    plus_dms = []
    minus_dms = []
    for i in range(1, len(highs)):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        plus_dm = up if up > down and up > 0 else 0
        minus_dm = down if down > up and down > 0 else 0
        plus_dms.append(plus_dm)
        minus_dms.append(minus_dm)
    trs = []
    for i in range(1, len(highs)):
        tr = highs[i] - lows[i]
        trs.append(tr)
    if len(trs) < 14:
        return None
    atr14_ = np.mean(trs[:14])
    for tr in trs[14:]:
        atr14_ = (atr14_ * 13 + tr) / 14
    if atr14_ == 0:
        return None
    sm_plus = np.mean(plus_dms[:14])
    sm_minus = np.mean(minus_dms[:14])
    for p, m in zip(plus_dms[14:], minus_dms[14:]):
        sm_plus = (sm_plus * 13 + p) / 14
        sm_minus = (sm_minus * 13 + m) / 14
    dx = 100 * abs(sm_plus - sm_minus) / (sm_plus + sm_minus) if (sm_plus + sm_minus) > 0 else 0
    return float(dx)


def bb20_position(close, middle, std):
    if std is None or std == 0 or middle is None:
        return None
    return float((close - middle) / std)


def bb20_width(std, middle):
    if middle is None or middle == 0 or std is None:
        return None
    return float(std / middle)


def classify_bb_width_pct(width_pct: Optional[float]) -> str:
    if width_pct is None:
        return "unknown"
    # 与 D1 保持一致：expanding / squeeze / neutral
    if width_pct > 0.05:
        return "expanding"
    if width_pct < 0.02:
        return "squeeze"
    return "neutral"


def compute_m30_metrics(bars_df, snapshot_time: datetime) -> dict:
    """
    bars_df: list of dicts with keys close, high, low, period_start (datetime)
    返回最新指标快照。
    """
    bars_df = [b for b in bars_df if b["period_start"] <= snapshot_time]
    bars_df = sorted(bars_df, key=lambda x: x["period_start"])
    if len(bars_df) < 5:
        return {"data_quality_flags": "insufficient_bars", "valid": False}

    closes = [b["close"] for b in bars_df]
    highs = [b["high"] for b in bars_df]
    lows = [b["low"] for b in bars_df]

    result = {
        "m30_close": closes[-1],
        "valid": True,
        "data_quality_flags": "ok",
    }

    # BB20 (需要至少20根)
    if len(closes) >= 20:
        arr = np.array(closes[-20:])
        middle = float(np.mean(arr))
        std = float(np.std(arr, ddof=0))
        result["m30_bb20_position"] = bb20_position(closes[-1], middle, std)
        result["m30_bb20_width"] = classify_bb_width_pct(bb20_width(std, middle))
    else:
        result["m30_bb20_position"] = None
        result["m30_bb20_width"] = "unknown"
        result["data_quality_flags"] = "short_history"

    # ATR14
    atr = atr14(highs, lows, closes)
    result["m30_atr14"] = atr

    # ADX14 简化：用 DX 代替（因为没有足够历史做平滑）
    adx = adx14(highs, lows)
    result["m30_adx14"] = adx

    # ADX slope 3 (最近4根 DX 的斜率)
    if len(highs) >= 4 and adx is not None:
        # 取最近 4 根分别算 dx，然后线性回归斜率
        dxs = []
        for end in range(4, 0, -1):
            h = highs[-end-14:-end] if len(highs) >= end+14 else highs[:len(highs)-end]
            l = lows[-end-14:-end] if len(lows) >= end+14 else lows[:len(lows)-end]
            if len(h) < 14:
                continue
            dxs.append(adx14(h, l))
        dxs = [d for d in dxs if d is not None]
        if len(dxs) >= 2:
            x = np.arange(len(dxs))
            slope = np.polyfit(x, dxs, 1)[0]
            result["m30_adx_slope_3"] = float(slope)
        else:
            result["m30_adx_slope_3"] = None
    else:
        result["m30_adx_slope_3"] = None

    # 上一段高低点（最近 20 根）
    result["m30_intraday_prev_high"] = max(highs[-20:]) if len(highs) >= 1 else None
    result["m30_intraday_prev_low"] = min(lows[-20:]) if len(lows) >= 1 else None

    return result


def breakout_signal(m30_close, prev_high, d1_bb20_position, d1_state_hex):
    """突破信号：M30 收盘价突破前高，且 D1 处于可突破状态。"""
    if prev_high is None or m30_close is None:
        return False
    if m30_close > prev_high * 1.005:
        # D1 状态需处于收敛/低位/整理态
        if d1_bb20_position in ("below_lower", "near_lower", "below_middle", "squeeze"):
            return True
        if d1_state_hex and d1_state_hex.endswith(("C", "D", "E", "F")):
            return True
    return False


def false_breakout_risk(m30_close, m30_high, prev_high, bars_recent):
    """假突破风险：突破前高后快速回落，或上影线过长。"""
    if prev_high is None or m30_close is None or m30_high is None:
        return False
    if m30_high > prev_high * 1.005 and m30_close < prev_high * 1.002:
        return True
    if len(bars_recent) >= 2:
        prev = bars_recent[-2]
        if prev["close"] > prev_high and m30_close < prev["close"] * 0.995:
            return True
    return False


def overheat_risk(m30_close, m30_bb20_pos, m30_adx14, d1_bb20_position):
    """过热风险：远离 BB 上轨 + ADX 高位，或 D1 已极度偏离。"""
    if m30_bb20_pos is not None and m30_bb20_pos > 2.0:
        return True
    if m30_adx14 is not None and m30_adx14 > 70:
        return True
    if d1_bb20_position == "above_upper":
        return True
    return False


def decide_observation_label(d1_state_hex, w1_state_hex, m30_breakout, false_risk, overheat, valid):
    if not valid:
        return "invalid"
    # D1 候选存在：D1 处于非强势末端状态
    d1_candidate = d1_state_hex and not d1_state_hex.endswith(("A", "B"))
    if not d1_candidate:
        return "invalid"
    if false_risk:
        return "risk"
    if overheat:
        return "risk"
    if m30_breakout:
        return "confirm"
    return "watch"


# ── main ────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Build M30 Observation State")
    parser.add_argument("--date", required=True, help="Trade date YYYY-MM-DD")
    parser.add_argument("--time", required=True, help="Snapshot time HH:MM")
    parser.add_argument("--state-cube", default=str(STATE_CUBE_DB))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--m30-db", default=None, help="Override M30 DuckDB path")
    args = parser.parse_args()

    trade_date = date.fromisoformat(args.date)
    hh, mm = map(int, args.time.split(":"))
    snapshot_time = datetime.combine(trade_date, time(hh, mm))
    created_at = datetime.now().isoformat()

    # 1. 读 state_cube D1/W1 主状态
    sc_con = duckdb.connect(args.state_cube, read_only=True)
    sc_df = sc_con.execute(f"""
        SELECT stock_code, state_date,
               mn1_state_hex, w1_state_hex, d1_state_hex,
               d1_bb20_position, d1_bb20_width,
               w1_bb20_position, w1_bb20_width,
               d1_close, d1_atr14, d1_adx14
        FROM state_cube
        WHERE state_date = '{args.date}'
    """).fetchdf()
    sc_con.close()

    if sc_df.empty:
        print(f"[WARN] No state_cube data for {args.date}")
        sys.exit(0)

    stock_codes = sc_df["stock_code"].tolist()

    # 2. 读 M30 bars
    m30_db_path = Path(args.m30_db) if args.m30_db else find_m30_db(trade_date)
    if not m30_db_path or not m30_db_path.exists():
        print(f"[WARN] M30 DB not found for {args.date}")
        sys.exit(0)

    m30_con = duckdb.connect(str(m30_db_path), read_only=True)
    # 读取该日期及之前 N 天的 bar（保证至少有 30 根以上）
    lookback_start = (trade_date - timedelta(days=7)).isoformat()
    # DuckDB 不支持 UNNEST 在 IN 子句中的这种写法；读全量后在 Python 过滤
    m30_df = m30_con.execute(f"""
        SELECT stock_code, period_start, open, high, low, close
        FROM m30_bars
        WHERE bar_date >= '{lookback_start}' AND bar_date <= '{args.date}'
        ORDER BY stock_code, period_start
    """).fetchdf()
    m30_df = m30_df[m30_df["stock_code"].isin(stock_codes)]
    m30_con.close()

    if m30_df.empty:
        print(f"[WARN] No M30 bars for {args.date}")
        sys.exit(0)

    # 3. 逐股计算
    rows = []
    for stock_code in stock_codes:
        d1_row = sc_df[sc_df["stock_code"] == stock_code].iloc[0]
        bars = m30_df[m30_df["stock_code"] == stock_code]
        if bars.empty:
            continue
        bar_dicts = bars.to_dict("records")

        metrics = compute_m30_metrics(bar_dicts, snapshot_time)
        valid = metrics.pop("valid")
        flags = metrics.pop("data_quality_flags")

        prev_high = metrics.get("m30_intraday_prev_high")
        prev_low = metrics.get("m30_intraday_prev_low")
        m30_close = metrics.get("m30_close")
        m30_high = bar_dicts[-1]["high"] if bar_dicts else None

        brk = breakout_signal(
            m30_close, prev_high,
            d1_row.get("d1_bb20_position"), d1_row.get("d1_state_hex")
        )
        fbr = false_breakout_risk(m30_close, m30_high, prev_high, bar_dicts)
        ohr = overheat_risk(
            m30_close,
            metrics.get("m30_bb20_position"),
            metrics.get("m30_adx14"),
            d1_row.get("d1_bb20_position")
        )
        label = decide_observation_label(
            d1_row.get("d1_state_hex"),
            d1_row.get("w1_state_hex"),
            brk, fbr, ohr, valid
        )

        rows.append({
            "stock_code": stock_code,
            "trade_date": args.date,
            "snapshot_time": args.time,
            "d1_state_hex": d1_row.get("d1_state_hex"),
            "w1_state_hex": d1_row.get("w1_state_hex"),
            "d1_bb20_position": d1_row.get("d1_bb20_position"),
            "d1_bb20_width": d1_row.get("d1_bb20_width"),
            "m30_close": m30_close,
            "m30_bb20_position": metrics.get("m30_bb20_position"),
            "m30_bb20_width": metrics.get("m30_bb20_width"),
            "m30_atr14": metrics.get("m30_atr14"),
            "m30_adx14": metrics.get("m30_adx14"),
            "m30_adx_slope_3": metrics.get("m30_adx_slope_3"),
            "m30_price_breakout": brk,
            "m30_breakout_signal": brk,
            "m30_false_breakout_risk": fbr,
            "m30_overheat_risk": ohr,
            "m30_data_quality_flags": flags,
            "observation_label": label,
            "created_at": created_at,
        })

    if not rows:
        print(f"[WARN] No observation rows generated for {args.date} {args.time}")
        sys.exit(0)

    # 4. 写入 DuckDB
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_db = out_dir / f"m30_observation_{trade_date.strftime('%Y%m%d')}.duckdb"

    out_con = duckdb.connect(str(out_db))
    out_con.execute("""
        CREATE TABLE IF NOT EXISTS m30_observation_state (
            stock_code VARCHAR,
            trade_date DATE,
            snapshot_time VARCHAR,
            d1_state_hex VARCHAR,
            w1_state_hex VARCHAR,
            d1_bb20_position VARCHAR,
            d1_bb20_width VARCHAR,
            m30_close DOUBLE,
            m30_bb20_position DOUBLE,
            m30_bb20_width VARCHAR,
            m30_atr14 DOUBLE,
            m30_adx14 DOUBLE,
            m30_adx_slope_3 DOUBLE,
            m30_price_breakout BOOLEAN,
            m30_breakout_signal BOOLEAN,
            m30_false_breakout_risk BOOLEAN,
            m30_overheat_risk BOOLEAN,
            m30_data_quality_flags VARCHAR,
            observation_label VARCHAR,
            created_at VARCHAR
        )
    """)
    # 先删同 snapshot 的旧数据
    out_con.execute(f"""
        DELETE FROM m30_observation_state
        WHERE trade_date = '{args.date}' AND snapshot_time = '{args.time}'
    """)
    # DuckDB read_json_auto 需要文件路径，改用 DataFrame 插入
    import pandas as pd
    df = pd.DataFrame(rows)
    out_con.register("obs_df", df)
    out_con.execute("""
        INSERT INTO m30_observation_state
        SELECT * FROM obs_df
    """)
    out_con.close()

    # 5. 写 latest.json
    labels = [r["observation_label"] for r in rows]
    latest = {
        "updated_at": created_at,
        "trade_date": args.date,
        "snapshot_time": args.time,
        "row_count": len(rows),
        "confirm_count": labels.count("confirm"),
        "watch_count": labels.count("watch"),
        "risk_count": labels.count("risk"),
        "invalid_count": labels.count("invalid"),
        "top_confirm": [r["stock_code"] for r in rows if r["observation_label"] == "confirm"][:10],
        "top_risk": [r["stock_code"] for r in rows if r["observation_label"] == "risk"][:10],
    }
    latest_path = out_dir / "m30_observation_latest.json"
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    print(f"[OK] Wrote {len(rows)} rows to {out_db} (snapshot {args.time})")
    print(f"[OK] Labels: confirm={latest['confirm_count']} watch={latest['watch_count']} risk={latest['risk_count']} invalid={latest['invalid_count']}")


if __name__ == "__main__":
    main()
