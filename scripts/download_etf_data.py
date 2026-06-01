#!/usr/bin/env python3
"""Download ETF historical data and compute monthly MN1 State.

Outputs:
    data/etf_daily/          — ETF daily bars CSV
    outputs/state_cache/etf_monthly_state_YYYYMM.json — ETF monthly state
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "state_cache"
DATA_DIR = ROOT / "data" / "etf_daily"

# Core benchmark ETFs
BENCHMARK_ETFS = {
    "510300": "510300.SH",  # 沪深300ETF
    "510050": "510050.SH",  # 上证50ETF
    "510500": "510500.SH",  # 中证500ETF
    "159915": "159915.SZ",  # 创业板ETF
}

# Industry ETFs from config
INDUSTRY_ETFS = {
    "512480": "512480.SH",  # 半导体ETF
    "515050": "515050.SH",  # 5GETF
    "512880": "512880.SH",  # 证券ETF
    "512800": "512800.SH",  # 银行ETF
    "512660": "512660.SH",  # 军工ETF
    "512010": "512010.SH",  # 医药ETF
    "515790": "515790.SH",  # 光伏ETF
    "516160": "516160.SH",  # 新能源ETF
    "515700": "515700.SH",  # 新能车ETF
    "159996": "159996.SZ",  # 家电ETF
    "159928": "159928.SZ",  # 消费ETF
    "159825": "159825.SZ",  # 农业ETF
    "516970": "516970.SH",  # 基建ETF
    "516020": "516020.SH",  # 化工ETF
    "512400": "512400.SH",  # 有色金属ETF
    "515220": "515220.SH",  # 煤炭ETF
    "159666": "159666.SZ",  # 交通运输ETF
    "159805": "159805.SZ",  # 传媒ETF
    "159301": "159301.SZ",  # 公用事业ETF
    "159745": "159745.SZ",  # 建材ETF
    "159768": "159768.SZ",  # 房地产ETF
    "159886": "159886.SZ",  # 机械ETF
    "512580": "512580.SH",  # 环保ETF
    "159588": "159588.SZ",  # 石油ETF
    "159586": "159586.SZ",  # 计算机ETF
    "515210": "515210.SH",  # 钢铁ETF
}

ALL_ETFS = {**BENCHMARK_ETFS, **INDUSTRY_ETFS}


def download_etf(symbol: str, name: str) -> pd.DataFrame | None:
    """Download ETF daily data from yfinance."""
    try:
        import yfinance as yf

        # Convert SH/SZ suffix to yfinance format
        yf_symbol = name
        if name.endswith(".SH"):
            yf_symbol = name.replace(".SH", ".SS")
        df = yf.download(yf_symbol, start="2018-01-01", end="2026-05-23", progress=False, auto_adjust=False)
        if df is None or df.empty:
            return None
        df = df.reset_index()
        # Flatten multi-index columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [" ".join(col).strip() if col[1] else col[0] for col in df.columns.values]
        # Find columns by suffix/pattern
        cols = {c.lower().replace(" ", "_"): c for c in df.columns}
        date_col = next((c for c in df.columns if "date" in c.lower() or c.lower() == "index"), df.columns[0])
        open_col = next((c for c in df.columns if "open" in c.lower() and "adj" not in c.lower()), None)
        close_col = next((c for c in df.columns if "close" in c.lower() and "adj" not in c.lower()), None)
        high_col = next((c for c in df.columns if "high" in c.lower()), None)
        low_col = next((c for c in df.columns if "low" in c.lower()), None)
        vol_col = next((c for c in df.columns if "volume" in c.lower()), None)
        if not all([open_col, close_col, high_col, low_col, vol_col]):
            print(
                f"  Missing columns in {symbol}: open={open_col}, close={close_col}, high={high_col}, low={low_col}, vol={vol_col}"
            )
            return None
        result = pd.DataFrame(
            {
                "stock_code": name,
                "date": pd.to_datetime(df[date_col]).dt.tz_localize(None).dt.strftime("%Y-%m-%d"),
                "open": df[open_col].astype(float).values,
                "high": df[high_col].astype(float).values,
                "low": df[low_col].astype(float).values,
                "close": df[close_col].astype(float).values,
                "volume": df[vol_col].astype(float).values,
                "amount": 0.0,
            }
        )
        return result
    except Exception as e:
        print(f"  Failed to download {symbol} ({name}): {e}")
        return None


def compute_monthly_state(df: pd.DataFrame) -> pd.DataFrame:
    """Compute monthly bars and MN1 state from daily bars."""
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M")

    monthly = (
        df.groupby(["stock_code", "month"])
        .agg(
            month_start_date=("date", "min"),
            month_end_date=("date", "max"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .reset_index()
    )

    monthly["month_start_date"] = monthly["month_start_date"].dt.strftime("%Y-%m-%d")
    monthly["month_end_date"] = monthly["month_end_date"].dt.strftime("%Y-%m-%d")
    monthly["ym"] = monthly["month"].astype(str).str.replace("-", "")
    monthly["month"] = monthly["month"].astype(str)

    return monthly


def build_monthly_states(monthly_df: pd.DataFrame) -> None:
    """Compute MN1 state using same logic as build_p116_foundation."""
    con = duckdb.connect(":memory:")

    # Register dataframe
    con.execute("CREATE TABLE monthly_bars AS SELECT * FROM monthly_df")

    # Compute SR levels (5-period fractal, 3-bar confirmation)
    con.execute("""
        CREATE TABLE sr_levels AS
        WITH ordered AS (
          SELECT
            *,
            row_number() OVER (PARTITION BY stock_code ORDER BY month_start_date)::BIGINT AS bar_index,
            lag(high, 1) OVER w AS high_lag_1,
            lag(high, 2) OVER w AS high_lag_2,
            lead(high, 1) OVER w AS high_lead_1,
            lead(high, 2) OVER w AS high_lead_2,
            lag(low, 1) OVER w AS low_lag_1,
            lag(low, 2) OVER w AS low_lag_2,
            lead(low, 1) OVER w AS low_lead_1,
            lead(low, 2) OVER w AS low_lead_2
          FROM monthly_bars
          WINDOW w AS (PARTITION BY stock_code ORDER BY month_start_date)
        ),
        center_fractal AS (
          SELECT
            *,
            CASE
              WHEN high_lag_2 < high AND high_lag_1 < high AND high_lead_1 < high AND high_lead_2 < high
              THEN high ELSE NULL
            END AS center_fractal_resistance,
            CASE
              WHEN low_lag_2 > low AND low_lag_1 > low AND low_lead_1 > low AND low_lead_2 > low
              THEN low ELSE NULL
            END AS center_fractal_support
          FROM ordered
        ),
        confirmed AS (
          SELECT
            *,
            lag(center_fractal_resistance, 3) OVER (
              PARTITION BY stock_code ORDER BY month_start_date
            ) AS fractal_resistance,
            lag(center_fractal_support, 3) OVER (
              PARTITION BY stock_code ORDER BY month_start_date
            ) AS fractal_support
          FROM center_fractal
        ),
        filled AS (
          SELECT
            *,
            last_value(fractal_resistance IGNORE NULLS) OVER (
              PARTITION BY stock_code ORDER BY month_start_date
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS sr_resistance,
            last_value(fractal_support IGNORE NULLS) OVER (
              PARTITION BY stock_code ORDER BY month_start_date
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS sr_support
          FROM confirmed
        )
        SELECT
          stock_code,
          month_start_date,
          month_end_date,
          open, high, low, close, volume,
          sr_resistance,
          sr_support,
          (sr_resistance IS NOT NULL AND sr_support IS NOT NULL) AS sr_ready
        FROM filled
        ORDER BY stock_code, month_start_date
    """)

    # Compute indicators (ADX, DI, ATR, BB width)
    con.execute("""
        CREATE TABLE indicators AS
        WITH ordered AS (
          SELECT
            stock_code, month_start_date, month_end_date, close, high, low,
            lag(close) OVER w AS prev_close,
            lag(high) OVER w AS prev_high,
            lag(low) OVER w AS prev_low,
            avg(close) OVER w20 AS bb_middle_20,
            stddev_samp(close) OVER w20 AS bb_std_20
          FROM sr_levels
          WINDOW
            w AS (PARTITION BY stock_code ORDER BY month_start_date),
            w20 AS (PARTITION BY stock_code ORDER BY month_start_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
        ),
        directional AS (
          SELECT
            *,
            greatest(high - low, abs(high - coalesce(prev_close, close)), abs(low - coalesce(prev_close, close))) AS true_range,
            CASE
              WHEN prev_high IS NULL THEN NULL
              WHEN (high - prev_high) > (prev_low - low) AND (high - prev_high) > 0 THEN high - prev_high
              ELSE 0
            END AS plus_dm,
            CASE
              WHEN prev_low IS NULL THEN NULL
              WHEN (prev_low - low) > (high - prev_high) AND (prev_low - low) > 0 THEN prev_low - low
              ELSE 0
            END AS minus_dm,
            CASE
              WHEN bb_middle_20 IS NOT NULL AND bb_middle_20 <> 0 AND bb_std_20 IS NOT NULL
              THEN (4.0 * bb_std_20) / bb_middle_20
              ELSE NULL
            END AS bb_width_pct
          FROM ordered
        ),
        smoothed AS (
          SELECT
            *,
            avg(true_range) OVER w14 AS atr14,
            avg(plus_dm) OVER w14 AS plus_dm14,
            avg(minus_dm) OVER w14 AS minus_dm14
          FROM directional
          WINDOW w14 AS (
            PARTITION BY stock_code ORDER BY month_start_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
          )
        ),
        di AS (
          SELECT
            *,
            CASE WHEN atr14 IS NOT NULL AND atr14 <> 0 THEN 100.0 * plus_dm14 / atr14 ELSE NULL END AS plus_di_14,
            CASE WHEN atr14 IS NOT NULL AND atr14 <> 0 THEN 100.0 * minus_dm14 / atr14 ELSE NULL END AS minus_di_14,
            CASE WHEN close IS NOT NULL AND close <> 0 AND atr14 IS NOT NULL THEN 100.0 * atr14 / close ELSE NULL END AS atr_ratio_pct
          FROM smoothed
        ),
        dx AS (
          SELECT
            *,
            CASE
              WHEN plus_di_14 IS NOT NULL AND minus_di_14 IS NOT NULL AND (plus_di_14 + minus_di_14) <> 0
              THEN 100.0 * abs(plus_di_14 - minus_di_14) / (plus_di_14 + minus_di_14)
              ELSE NULL
            END AS dx14
          FROM di
        ),
        ranked_base AS (
          SELECT
            *,
            avg(dx14) OVER w14 AS adx14,
            quantile_cont(bb_width_pct, 0.20) OVER w20prev AS bb_width_q20_20,
            quantile_cont(bb_width_pct, 0.50) OVER w20prev AS bb_width_median_20,
            quantile_cont(bb_width_pct, 0.80) OVER w20prev AS bb_width_q80_20,
            quantile_cont(atr_ratio_pct, 0.75) OVER w60prev AS atr_ratio_q75_60,
            avg(atr_ratio_pct) OVER w60prev AS atr_ratio_avg60
          FROM dx
          WINDOW
            w14 AS (PARTITION BY stock_code ORDER BY month_start_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),
            w20prev AS (PARTITION BY stock_code ORDER BY month_start_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
            w60prev AS (PARTITION BY stock_code ORDER BY month_start_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
        ),
        ranked AS (
          SELECT
            *,
            lag(bb_width_pct) OVER w AS prev_bb_width_pct,
            lag(atr_ratio_pct) OVER w AS prev_atr_ratio_pct,
            lag(adx14) OVER w AS prev_adx14,
            adx14 - lag(adx14, 3) OVER w AS adx_slope_3
          FROM ranked_base
          WINDOW w AS (PARTITION BY stock_code ORDER BY month_start_date)
        )
        SELECT
          stock_code, month_start_date, month_end_date, close,
          atr14, atr_ratio_pct, atr_ratio_avg60, atr_ratio_q75_60,
          plus_di_14, minus_di_14, adx14, adx_slope_3,
          bb_width_pct, bb_width_q20_20, bb_width_q80_20, prev_bb_width_pct,
          CASE
            WHEN adx14 IS NULL OR plus_di_14 IS NULL OR minus_di_14 IS NULL THEN 'insufficient_history'
            WHEN adx14 <= 13 AND adx_slope_3 < 0 THEN 'closed'
            WHEN adx14 >= 25 AND adx_slope_3 > 0 AND plus_di_14 > minus_di_14 THEN 'bull_trend'
            WHEN adx14 >= 25 AND adx_slope_3 > 0 AND minus_di_14 > plus_di_14 THEN 'bear_trend'
            WHEN adx14 > 20 AND plus_di_14 > minus_di_14 THEN 'bull_start'
            WHEN adx14 > 20 AND minus_di_14 > plus_di_14 THEN 'bear_start'
            ELSE 'neutral'
          END AS trend,
          CASE
            WHEN atr_ratio_pct IS NULL OR atr_ratio_avg60 IS NULL THEN 'insufficient_history'
            WHEN atr_ratio_pct >= atr_ratio_avg60 * 1.25 OR atr_ratio_pct >= atr_ratio_q75_60 THEN 'atr_expanding'
            WHEN atr_ratio_pct <= atr_ratio_avg60 * 0.75 THEN 'atr_contracting'
            ELSE 'neutral'
          END AS volatility,
          CASE
            WHEN bb_width_pct IS NULL OR bb_width_q20_20 IS NULL THEN 'insufficient_history'
            WHEN adx14 <= 13 AND adx_slope_3 < 0 AND bb_width_pct <= bb_width_q20_20 THEN 'closed'
            WHEN bb_width_pct <= bb_width_q20_20 THEN 'contracting'
            WHEN bb_width_pct >= bb_width_q80_20
             AND prev_bb_width_pct IS NOT NULL
             AND bb_width_pct > prev_bb_width_pct * 1.05 THEN 'strong_expansion'
            WHEN prev_bb_width_pct IS NOT NULL AND bb_width_pct > prev_bb_width_pct * 1.05 THEN 'expansion_start'
            ELSE 'neutral'
          END AS compression
        FROM ranked
        ORDER BY stock_code, month_start_date
    """)

    # Compute native MN1 State
    con.execute("""
        CREATE TABLE native_mn1_state AS
        SELECT
          i.stock_code,
          i.month_start_date,
          i.month_end_date,
          i.close AS mn1_close,
          s.sr_support AS mn1_sr_support,
          s.sr_resistance AS mn1_sr_resistance,
          s.sr_ready AS mn1_sr_ready,
          i.trend AS mn1_trend_label,
          i.volatility AS mn1_volatility_label,
          i.compression AS mn1_compression_label,
          i.adx14 AS mn1_adx14,
          i.bb_width_pct AS mn1_bb_width_pct,
          i.atr_ratio_pct AS mn1_atr_ratio_pct,
          CASE WHEN i.trend LIKE 'bull%' OR i.trend LIKE 'bear%' THEN 1 ELSE 0 END AS trend_bit,
          CASE WHEN i.volatility = 'atr_expanding' THEN 1 ELSE 0 END AS volatility_bit,
          CASE WHEN i.compression = 'closed' OR i.trend = 'closed' THEN 0 ELSE 8 END AS base,
          CASE
            WHEN s.sr_ready = false OR s.sr_support IS NULL OR s.sr_resistance IS NULL THEN 0
            WHEN i.close > s.sr_resistance THEN 2
            WHEN i.close < s.sr_support THEN 2
            ELSE 0
          END AS position_bit,
          (i.trend LIKE 'bull%' OR i.close > s.sr_resistance) AS bull_context,
          (i.trend LIKE 'bear%' OR i.close < s.sr_support) AS bear_context
        FROM indicators i
        LEFT JOIN sr_levels s
          ON s.stock_code = i.stock_code AND s.month_start_date = i.month_start_date
        ORDER BY i.stock_code, i.month_start_date
    """)

    rows = con.execute("""
        SELECT
          stock_code,
          month_start_date,
          month_end_date,
          mn1_close,
          mn1_sr_support,
          mn1_sr_resistance,
          mn1_sr_ready,
          base,
          trend_bit,
          position_bit,
          volatility_bit,
          bull_context,
          bear_context
        FROM native_mn1_state
        ORDER BY month_start_date, stock_code
    """).fetchall()

    con.close()

    # Compute state in Python
    months: dict[str, dict[str, Any]] = {}

    for row in rows:
        (
            stock_code,
            month_start,
            month_end,
            mn1_close,
            sr_support,
            sr_resistance,
            sr_ready,
            base,
            trend_bit,
            position_bit,
            volatility_bit,
            bull_context,
            bear_context,
        ) = row

        ym = month_start[:4] + month_start[5:7]
        if ym not in months:
            months[ym] = {
                "schema_version": "etf_monthly_state_v1",
                "ym": ym,
                "month_start_date": month_start,
                "month_end_date": month_end,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "akshare_fund_etf_hist_em",
                "total_stocks": 0,
                "data": [],
            }

        magnitude = base + trend_bit * 4 + position_bit + volatility_bit

        if sr_ready and sr_support is not None and mn1_close < sr_support:
            state_score = -magnitude
        elif sr_ready and sr_resistance is not None and mn1_close > sr_resistance:
            state_score = magnitude
        elif bear_context and not bull_context:
            state_score = -magnitude
        else:
            state_score = magnitude

        if state_score < 0:
            state_hex = f"-{abs(state_score):X}"
        else:
            state_hex = f"{state_score:X}"

        months[ym]["data"].append(
            {
                "stock_code": stock_code,
                "mn1_state_score": state_score,
                "mn1_state_hex": state_hex,
                "mn1_base": base,
                "mn1_trend_bit": trend_bit,
                "mn1_position_bit": position_bit,
                "mn1_volatility_bit": volatility_bit,
                "mn1_close": round(mn1_close, 4) if mn1_close else None,
                "mn1_sr_support": round(sr_support, 4) if sr_support else None,
                "mn1_sr_resistance": round(sr_resistance, 4) if sr_resistance else None,
                "mn1_sr_ready": bool(sr_ready) if sr_ready is not None else False,
                "mn1_trend": str(row[6]) if len(row) > 6 else None,
            }
        )
        months[ym]["total_stocks"] += 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ym, data in sorted(months.items()):
        path = OUT_DIR / f"etf_monthly_state_{ym}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write latest
    if months:
        latest_ym = max(months.keys())
        latest_path = OUT_DIR / "etf_monthly_state_latest.json"
        latest_path.write_text(json.dumps(months[latest_ym], ensure_ascii=False, indent=2), encoding="utf-8")

    return len(months)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    all_dfs = []
    for symbol, name in ALL_ETFS.items():
        csv_path = DATA_DIR / f"{name.replace('.', '_')}.csv"
        if csv_path.exists():
            print(f"Reading cached {symbol} ({name})...")
            df = pd.read_csv(csv_path)
        else:
            print(f"Downloading {symbol} ({name})...")
            df = download_etf(symbol, name)
            if df is not None:
                df.to_csv(csv_path, index=False)
        if df is not None:
            all_dfs.append(df)
            print(f"  {len(df)} rows")

    if not all_dfs:
        print("No ETF data downloaded.")
        return

    combined = pd.concat(all_dfs, ignore_index=True)
    print(f"\nTotal daily records: {len(combined):,}")

    monthly = compute_monthly_state(combined)
    print(f"Monthly records: {len(monthly):,}")

    num_months = build_monthly_states(monthly)
    print(f"\nWrote {num_months} monthly state files to {OUT_DIR}")


if __name__ == "__main__":
    main()
