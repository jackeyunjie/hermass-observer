#!/usr/bin/env python3
"""
Build US stock foundation DB from yfinance data.
Reuses P116 foundation SQL logic for indicator/SR/state computation.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "us_stock"
FOUNDATION_DB = OUTPUT_DIR / "us_foundation.duckdb"
CACHE_DB = OUTPUT_DIR / "us_state_cache.duckdb"

import requests
from bs4 import BeautifulSoup


def fetch_sp500_tickers() -> list[str]:
    """Fetch S&P 500 constituents from Wikipedia."""
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    resp = requests.get(url, headers=headers, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"id": "constituents"})
    rows = table.find_all("tr")[1:]  # skip header
    tickers = []
    for row in rows:
        cols = row.find_all("td")
        if len(cols) >= 2:
            symbol = cols[0].get_text(strip=True).replace(".", "-")
            tickers.append(symbol)
    return sorted(set(tickers))


def fetch_nasdaq100_tickers() -> list[str]:
    """Fetch Nasdaq-100 constituents from Wikipedia."""
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    resp = requests.get(url, headers=headers, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table", {"class": "wikitable"})
    tickers = []
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) > 50:  # constituents table has ~101 rows
            header = rows[0]
            header_text = [c.get_text(strip=True).lower() for c in header.find_all("th")]
            if "ticker" in header_text:
                for row in rows[1:]:
                    cols = row.find_all("td")
                    if len(cols) >= 2:
                        ticker = cols[0].get_text(strip=True).replace(".", "-")
                        if ticker and ticker.isalpha():
                            tickers.append(ticker)
                break
    return sorted(set(tickers))


def build_us_stock_pool() -> list[str]:
    """
    Build US stock pool: S&P 500 + Nasdaq-100 + founder trades + key ETFs.
    Target: ~600 tickers.
    """
    print("Fetching S&P 500 constituents from Wikipedia...")
    sp500 = fetch_sp500_tickers()
    print(f"  S&P 500: {len(sp500)} tickers")

    print("Fetching Nasdaq-100 constituents from Wikipedia...")
    ndx = fetch_nasdaq100_tickers()
    print(f"  Nasdaq-100: {len(ndx)} tickers")

    # Merge core indices
    core = sorted(set(sp500 + ndx))
    overlap = sorted(set(sp500) & set(ndx))
    print(f"  Core pool (S&P 500 + NDX): {len(core)} tickers (overlap: {len(overlap)})")

    # Founder trades not in core indices (small/mid caps from case studies)
    founder_extra = [
        "ANF", "STAA", "NNOX", "UAVS", "MP", "YETI", "ZIM", "BNTX",
        "SKY", "PAG", "OLN", "UPST", "ASYS",
        # Note: GBOX, HSKA, TSP are delisted/acquired; keep for completeness
        # "GBOX", "HSKA", "TSP",
    ]

    # Key ETFs and benchmarks
    etfs = ["SPY", "QQQ", "VOO", "IVV", "GLD", "USO", "SH", "FAS"]

    all_tickers = sorted(set(core + founder_extra + etfs))
    print(f"  Final pool: {len(all_tickers)} tickers")
    print(f"    - S&P 500: {len(sp500)}")
    print(f"    - Nasdaq-100 only: {len(set(ndx) - set(sp500))}")
    print(f"    - Founder extras: {len([t for t in founder_extra if t in all_tickers])}")
    print(f"    - ETFs: {len(etfs)}")

    return all_tickers


# Placeholder; actual pool built in main() to avoid import-time side effects
US_TICKERS: list[str] = []


def fetch_us_daily(tickers: list[str], start: str, end: str) -> list[dict]:
    """Fetch daily OHLCV from yfinance."""
    print(f"Fetching {len(tickers)} tickers from {start} to {end}...")
    df = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,
        group_by="ticker",
        progress=True,
        threads=True,
    )
    rows: list[dict] = []
    if isinstance(df.columns, pd.MultiIndex):
        for ticker in tickers:
            if ticker not in df.columns.levels[0]:
                continue
            tdf = df[ticker].dropna()
            for idx, row in tdf.iterrows():
                rows.append({
                    "stock_code": ticker,
                    "date": idx.date(),
                    "open": float(row.get("Open", 0) or 0),
                    "high": float(row.get("High", 0) or 0),
                    "low": float(row.get("Low", 0) or 0),
                    "close": float(row.get("Close", 0) or 0),
                    "volume": int(row.get("Volume", 0) or 0),
                    "amount": float(row.get("Volume", 0) or 0) * float(row.get("Close", 0) or 0),
                })
    else:
        # Single ticker
        tdf = df.dropna()
        for idx, row in tdf.iterrows():
            rows.append({
                "stock_code": tickers[0],
                "date": idx.date(),
                "open": float(row.get("Open", 0) or 0),
                "high": float(row.get("High", 0) or 0),
                "low": float(row.get("Low", 0) or 0),
                "close": float(row.get("Close", 0) or 0),
                "volume": int(row.get("Volume", 0) or 0),
                "amount": float(row.get("Volume", 0) or 0) * float(row.get("Close", 0) or 0),
            })
    print(f"  Total rows fetched: {len(rows)}")
    return rows


def build_foundation(rows: list[dict], out_db: Path, cutoff_date: str) -> dict:
    """Build foundation DB using P116 SQL logic."""
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()

    conn = duckdb.connect(str(out_db))
    tmp_dir = out_db.parent / "duckdb_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    conn.execute("SET preserve_insertion_order=false")
    conn.execute("SET threads=4")
    conn.execute(f"SET temp_directory='{str(tmp_dir).replace(chr(39), chr(39)+chr(39))}'")

    # 1. daily_bars
    conn.execute("CREATE TABLE daily_bars (stock_code VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT, amount DOUBLE)")
    for batch in [rows[i:i+10000] for i in range(0, len(rows), 10000)]:
        conn.executemany(
            "INSERT INTO daily_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(r["stock_code"], r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"], r["amount"]) for r in batch]
        )
    print(f"  daily_bars: {conn.execute('SELECT COUNT(*) FROM daily_bars').fetchone()[0]} rows")

    # 2. weekly_bars
    conn.execute(
        """
        CREATE TABLE weekly_bars AS
        WITH src AS (
          SELECT *, CAST(date_trunc('week', date) AS DATE) AS period_start
          FROM daily_bars
        )
        SELECT
          stock_code,
          period_start,
          max(date)::DATE AS period_end,
          CAST(period_start + INTERVAL 6 DAY AS DATE) AS available_date,
          arg_min(open, date) AS open,
          max(high) AS high,
          min(low) AS low,
          arg_max(close, date) AS close,
          sum(volume) AS volume,
          sum(amount) AS amount,
          count(*)::BIGINT AS source_bar_count
        FROM src
        GROUP BY stock_code, period_start
        ORDER BY stock_code, period_start
        """
    )

    # 3. monthly_bars
    conn.execute(
        """
        CREATE TABLE monthly_bars AS
        WITH src AS (
          SELECT *, CAST(date_trunc('month', date) AS DATE) AS period_start
          FROM daily_bars
        )
        SELECT
          stock_code,
          period_start,
          max(date)::DATE AS period_end,
          CAST(period_start + INTERVAL 1 MONTH - INTERVAL 1 DAY AS DATE) AS available_date,
          arg_min(open, date) AS open,
          max(high) AS high,
          min(low) AS low,
          arg_max(close, date) AS close,
          sum(volume) AS volume,
          sum(amount) AS amount,
          count(*)::BIGINT AS source_bar_count
        FROM src
        GROUP BY stock_code, period_start
        ORDER BY stock_code, period_start
        """
    )

    # 4. timeframe_bars
    conn.execute(
        """
        CREATE TABLE timeframe_bars AS
        SELECT stock_code, 'D1' AS timeframe, date AS period_start, date AS period_end, date AS available_date,
               open, high, low, close, volume, amount, 1::BIGINT AS source_bar_count
        FROM daily_bars
        UNION ALL
        SELECT stock_code, 'W1' AS timeframe, period_start, period_end, available_date,
               open, high, low, close, volume, amount, source_bar_count
        FROM weekly_bars
        UNION ALL
        SELECT stock_code, 'MN1' AS timeframe, period_start, period_end, available_date,
               open, high, low, close, volume, amount, source_bar_count
        FROM monthly_bars
        """
    )

    # 5. sr_levels (SqFractal 5, confirm 3)
    conn.execute(
        """
        CREATE TABLE sr_levels AS
        WITH ordered AS (
          SELECT
            *,
            row_number() OVER (PARTITION BY stock_code, timeframe ORDER BY period_start)::BIGINT AS tf_bar_index,
            lag(high, 1) OVER w AS high_lag_1,
            lag(high, 2) OVER w AS high_lag_2,
            lead(high, 1) OVER w AS high_lead_1,
            lead(high, 2) OVER w AS high_lead_2,
            lag(low, 1) OVER w AS low_lag_1,
            lag(low, 2) OVER w AS low_lag_2,
            lead(low, 1) OVER w AS low_lead_1,
            lead(low, 2) OVER w AS low_lead_2
          FROM timeframe_bars
          WINDOW w AS (PARTITION BY stock_code, timeframe ORDER BY period_start)
        ),
        center_fractal AS (
          SELECT
            *,
            CASE WHEN high_lag_2 < high AND high_lag_1 < high AND high_lead_1 < high AND high_lead_2 < high THEN high ELSE NULL END AS center_fractal_resistance,
            CASE WHEN low_lag_2 > low AND low_lag_1 > low AND low_lead_1 > low AND low_lead_2 > low THEN low ELSE NULL END AS center_fractal_support
          FROM ordered
        ),
        confirmed AS (
          SELECT
            *,
            lag(center_fractal_resistance, 3) OVER (PARTITION BY stock_code, timeframe ORDER BY period_start) AS fractal_resistance,
            lag(center_fractal_support, 3) OVER (PARTITION BY stock_code, timeframe ORDER BY period_start) AS fractal_support
          FROM center_fractal
        ),
        filled AS (
          SELECT
            *,
            last_value(fractal_resistance IGNORE NULLS) OVER (PARTITION BY stock_code, timeframe ORDER BY period_start ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS sr_resistance,
            last_value(fractal_support IGNORE NULLS) OVER (PARTITION BY stock_code, timeframe ORDER BY period_start ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS sr_support
          FROM confirmed
        )
        SELECT
          stock_code, timeframe, period_start, period_end, available_date,
          open, high, low, close, volume, amount, source_bar_count, tf_bar_index,
          fractal_resistance, fractal_support, sr_resistance, sr_support,
          (sr_resistance IS NOT NULL AND sr_support IS NOT NULL) AS sr_ready,
          5::INTEGER AS fractal_period,
          3::INTEGER AS confirm_lag_bars
        FROM filled
        ORDER BY stock_code, timeframe, period_start
        """
    )

    # 6. timeframe_indicators (ADX, BB, ATR)
    conn.execute(
        """
        CREATE TABLE timeframe_indicators AS
        WITH ordered AS (
          SELECT
            *,
            lag(close) OVER w AS prev_close,
            lag(high) OVER w AS prev_high,
            lag(low) OVER w AS prev_low,
            avg(close) OVER w20 AS bb_middle_20,
            stddev_samp(close) OVER w20 AS bb_std_20
          FROM timeframe_bars
          WINDOW
            w AS (PARTITION BY stock_code, timeframe ORDER BY period_start),
            w20 AS (PARTITION BY stock_code, timeframe ORDER BY period_start ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
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
          SELECT *,
            avg(true_range) OVER w14 AS atr14,
            avg(plus_dm) OVER w14 AS plus_dm14,
            avg(minus_dm) OVER w14 AS minus_dm14
          FROM directional
          WINDOW w14 AS (PARTITION BY stock_code, timeframe ORDER BY period_start ROWS BETWEEN 13 PRECEDING AND CURRENT ROW)
        ),
        di AS (
          SELECT *,
            CASE WHEN atr14 IS NOT NULL AND atr14 <> 0 THEN 100.0 * plus_dm14 / atr14 ELSE NULL END AS plus_di_14,
            CASE WHEN atr14 IS NOT NULL AND atr14 <> 0 THEN 100.0 * minus_dm14 / atr14 ELSE NULL END AS minus_di_14,
            CASE WHEN close IS NOT NULL AND close <> 0 AND atr14 IS NOT NULL THEN 100.0 * atr14 / close ELSE NULL END AS atr_ratio_pct
          FROM smoothed
        ),
        dx AS (
          SELECT *,
            CASE WHEN plus_di_14 IS NOT NULL AND minus_di_14 IS NOT NULL AND (plus_di_14 + minus_di_14) <> 0
              THEN 100.0 * abs(plus_di_14 - minus_di_14) / (plus_di_14 + minus_di_14)
              ELSE NULL
            END AS dx14
          FROM di
        ),
        ranked_base AS (
          SELECT *,
            avg(dx14) OVER w14 AS adx14,
            quantile_cont(bb_width_pct, 0.20) OVER w20prev AS bb_width_q20_20,
            quantile_cont(bb_width_pct, 0.50) OVER w20prev AS bb_width_median_20,
            quantile_cont(bb_width_pct, 0.80) OVER w20prev AS bb_width_q80_20,
            quantile_cont(atr_ratio_pct, 0.75) OVER w60prev AS atr_ratio_q75_60,
            avg(atr_ratio_pct) OVER w60prev AS atr_ratio_avg60
          FROM dx
          WINDOW
            w14 AS (PARTITION BY stock_code, timeframe ORDER BY period_start ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),
            w20prev AS (PARTITION BY stock_code, timeframe ORDER BY period_start ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
            w60prev AS (PARTITION BY stock_code, timeframe ORDER BY period_start ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
        ),
        ranked AS (
          SELECT *,
            lag(bb_width_pct) OVER w AS prev_bb_width_pct,
            lag(atr_ratio_pct) OVER w AS prev_atr_ratio_pct,
            lag(adx14) OVER w AS prev_adx14,
            adx14 - lag(adx14, 3) OVER w AS adx_slope_3
          FROM ranked_base
          WINDOW w AS (PARTITION BY stock_code, timeframe ORDER BY period_start)
        )
        SELECT
          *,
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
            WHEN bb_width_pct >= bb_width_q80_20 AND prev_bb_width_pct IS NOT NULL AND bb_width_pct > prev_bb_width_pct * 1.05 THEN 'strong_expansion'
            WHEN prev_bb_width_pct IS NOT NULL AND bb_width_pct > prev_bb_width_pct * 1.05 THEN 'expansion_start'
            ELSE 'neutral'
          END AS compression,
          (adx14 >= 25 AND adx_slope_3 > 0) AS adx_trend_on,
          (adx14 <= 13 AND adx_slope_3 < 0) AS adx_squeeze_on,
          (bb_width_pct <= bb_width_q20_20) AS bb_width_squeeze_on,
          (prev_bb_width_pct IS NOT NULL AND bb_width_pct > prev_bb_width_pct * 1.05) AS bb_width_expanding
        FROM ranked
        ORDER BY stock_code, timeframe, period_start
        """
    )

    # 7. d1_d_sr, d1_w_sr, d1_m_sr (ASOF JOIN SR levels)
    conn.execute(
        f"""
        CREATE TABLE d1_d_sr AS
        SELECT
          b.stock_code, b.date AS state_date, b.close AS d1_close,
          s.period_start AS d1_period_start, s.sr_support AS d1_sr_support,
          s.sr_resistance AS d1_sr_resistance, s.sr_ready AS d1_sr_ready
        FROM (SELECT stock_code, date, close FROM daily_bars WHERE date <= DATE '{cutoff_date}' ORDER BY stock_code, date) b
        ASOF LEFT JOIN
          (SELECT stock_code, available_date, period_start, sr_support, sr_resistance, sr_ready FROM sr_levels WHERE timeframe = 'D1' ORDER BY stock_code, available_date) s
          ON b.stock_code = s.stock_code AND b.date >= s.available_date
        """
    )
    conn.execute(
        """
        CREATE TABLE d1_w_sr AS
        SELECT
          b.stock_code, b.date AS state_date, b.close AS d1_close,
          s.period_start AS w1_period_start, s.sr_support AS w1_sr_support,
          s.sr_resistance AS w1_sr_resistance, s.sr_ready AS w1_sr_ready
        FROM (SELECT stock_code, date, close FROM daily_bars ORDER BY stock_code, date) b
        ASOF LEFT JOIN
          (SELECT stock_code, available_date, period_start, sr_support, sr_resistance, sr_ready FROM sr_levels WHERE timeframe = 'W1' ORDER BY stock_code, available_date) s
          ON b.stock_code = s.stock_code AND b.date >= s.available_date
        """
    )
    conn.execute(
        """
        CREATE TABLE d1_m_sr AS
        SELECT
          b.stock_code, b.date AS state_date, b.close AS d1_close,
          s.period_start AS mn1_period_start, s.sr_support AS mn1_sr_support,
          s.sr_resistance AS mn1_sr_resistance, s.sr_ready AS mn1_sr_ready
        FROM (SELECT stock_code, date, close FROM daily_bars ORDER BY stock_code, date) b
        ASOF LEFT JOIN
          (SELECT stock_code, available_date, period_start, sr_support, sr_resistance, sr_ready FROM sr_levels WHERE timeframe = 'MN1' ORDER BY stock_code, available_date) s
          ON b.stock_code = s.stock_code AND b.date >= s.available_date
        """
    )

    # 8. d1_sr_context
    conn.execute(
        """
        CREATE TABLE d1_sr_context AS
        SELECT
          d.stock_code, d.state_date, d.d1_close,
          d.d1_period_start, d.d1_sr_support, d.d1_sr_resistance, d.d1_sr_ready,
          w.w1_period_start, w.w1_sr_support, w.w1_sr_resistance, w.w1_sr_ready,
          m.mn1_period_start, m.mn1_sr_support, m.mn1_sr_resistance, m.mn1_sr_ready
        FROM d1_d_sr d
        LEFT JOIN d1_w_sr w ON d.stock_code = w.stock_code AND d.state_date = w.state_date
        LEFT JOIN d1_m_sr m ON d.stock_code = m.stock_code AND d.state_date = m.state_date
        """
    )

    # 9. d1_perspective_state (the core state computation)
    conn.execute(
        """
        CREATE TABLE d1_perspective_state AS
        WITH c AS (
          SELECT
            ctx.*,
            id.trend AS d1_trend, id.volatility AS d1_volatility, id.compression AS d1_compression,
            id.adx14 AS d1_adx14, id.plus_di_14 AS d1_plus_di_14, id.minus_di_14 AS d1_minus_di_14,
            id.adx_slope_3 AS d1_adx_slope_3, id.bb_width_pct AS d1_bb_width_pct,
            id.bb_width_q20_20 AS d1_bb_width_q20_20, id.bb_width_q80_20 AS d1_bb_width_q80_20,
            id.atr_ratio_pct AS d1_atr_ratio_pct, id.atr_ratio_avg60 AS d1_atr_ratio_avg60,
            iw.trend AS w1_trend, iw.volatility AS w1_volatility, iw.compression AS w1_compression,
            iw.adx14 AS w1_adx14, iw.plus_di_14 AS w1_plus_di_14, iw.minus_di_14 AS w1_minus_di_14,
            iw.adx_slope_3 AS w1_adx_slope_3, iw.bb_width_pct AS w1_bb_width_pct,
            iw.bb_width_q20_20 AS w1_bb_width_q20_20, iw.bb_width_q80_20 AS w1_bb_width_q80_20,
            iw.atr_ratio_pct AS w1_atr_ratio_pct, iw.atr_ratio_avg60 AS w1_atr_ratio_avg60,
            im.trend AS mn1_trend, im.volatility AS mn1_volatility, im.compression AS mn1_compression,
            im.adx14 AS mn1_adx14, im.plus_di_14 AS mn1_plus_di_14, im.minus_di_14 AS mn1_minus_di_14,
            im.adx_slope_3 AS mn1_adx_slope_3, im.bb_width_pct AS mn1_bb_width_pct,
            im.bb_width_q20_20 AS mn1_bb_width_q20_20, im.bb_width_q80_20 AS mn1_bb_width_q80_20,
            im.atr_ratio_pct AS mn1_atr_ratio_pct, im.atr_ratio_avg60 AS mn1_atr_ratio_avg60
          FROM d1_sr_context ctx
          LEFT JOIN timeframe_indicators id
            ON id.stock_code = ctx.stock_code AND id.timeframe = 'D1' AND id.period_start = ctx.d1_period_start
          LEFT JOIN timeframe_indicators iw
            ON iw.stock_code = ctx.stock_code AND iw.timeframe = 'W1' AND iw.period_start = ctx.w1_period_start
          LEFT JOIN timeframe_indicators im
            ON im.stock_code = ctx.stock_code AND im.timeframe = 'MN1' AND im.period_start = ctx.mn1_period_start
        ),
        bits AS (
          SELECT
            *,
            CASE WHEN d1_close > mn1_sr_resistance THEN 2 WHEN d1_close < mn1_sr_support THEN 2 ELSE 0 END AS mn1_position_bit,
            CASE WHEN d1_close > w1_sr_resistance THEN 2 WHEN d1_close < w1_sr_support THEN 2 ELSE 0 END AS w1_position_bit,
            CASE WHEN d1_close > d1_sr_resistance THEN 2 WHEN d1_close < d1_sr_support THEN 2 ELSE 0 END AS d1_position_bit,
            CASE WHEN mn1_trend LIKE 'bull%' OR mn1_trend LIKE 'bear%' THEN 1 ELSE 0 END AS mn1_trend_bit,
            CASE WHEN w1_trend LIKE 'bull%' OR w1_trend LIKE 'bear%' THEN 1 ELSE 0 END AS w1_trend_bit,
            CASE WHEN d1_trend LIKE 'bull%' OR d1_trend LIKE 'bear%' THEN 1 ELSE 0 END AS d1_trend_bit,
            CASE WHEN mn1_volatility = 'atr_expanding' THEN 1 ELSE 0 END AS mn1_volatility_bit,
            CASE WHEN w1_volatility = 'atr_expanding' THEN 1 ELSE 0 END AS w1_volatility_bit,
            CASE WHEN d1_volatility = 'atr_expanding' THEN 1 ELSE 0 END AS d1_volatility_bit,
            CASE WHEN mn1_compression = 'closed' OR mn1_trend = 'closed' THEN 0 ELSE 8 END AS mn1_base,
            CASE WHEN w1_compression = 'closed' OR w1_trend = 'closed' THEN 0 ELSE 8 END AS w1_base,
            CASE WHEN d1_compression = 'closed' OR d1_trend = 'closed' THEN 0 ELSE 8 END AS d1_base,
            (mn1_trend LIKE 'bull%' OR d1_close > mn1_sr_resistance) AS mn1_bull_context,
            (w1_trend LIKE 'bull%' OR d1_close > w1_sr_resistance) AS w1_bull_context,
            (d1_trend LIKE 'bull%' OR d1_close > d1_sr_resistance) AS d1_bull_context,
            (mn1_trend LIKE 'bear%' OR d1_close < mn1_sr_support) AS mn1_bear_context,
            (w1_trend LIKE 'bear%' OR d1_close < w1_sr_support) AS w1_bear_context,
            (d1_trend LIKE 'bear%' OR d1_close < d1_sr_support) AS d1_bear_context
          FROM c
        ),
        magnitudes AS (
          SELECT
            *,
            (mn1_base + mn1_trend_bit * 4 + mn1_position_bit + mn1_volatility_bit)::INTEGER AS mn1_state_magnitude,
            (w1_base + w1_trend_bit * 4 + w1_position_bit + w1_volatility_bit)::INTEGER AS w1_state_magnitude,
            (d1_base + d1_trend_bit * 4 + d1_position_bit + d1_volatility_bit)::INTEGER AS d1_state_magnitude
          FROM bits
        ),
        scored AS (
          SELECT
            *,
            CASE
              WHEN d1_close < mn1_sr_support THEN -mn1_state_magnitude
              WHEN d1_close > mn1_sr_resistance THEN mn1_state_magnitude
              WHEN mn1_bear_context AND NOT mn1_bull_context THEN -mn1_state_magnitude
              ELSE mn1_state_magnitude
            END AS mn1_state_score,
            CASE
              WHEN d1_close < w1_sr_support THEN -w1_state_magnitude
              WHEN d1_close > w1_sr_resistance THEN w1_state_magnitude
              WHEN w1_bear_context AND NOT w1_bull_context THEN -w1_state_magnitude
              ELSE w1_state_magnitude
            END AS w1_state_score,
            CASE
              WHEN d1_close < d1_sr_support THEN -d1_state_magnitude
              WHEN d1_close > d1_sr_resistance THEN d1_state_magnitude
              WHEN d1_bear_context AND NOT d1_bull_context THEN -d1_state_magnitude
              ELSE d1_state_magnitude
            END AS d1_state_score
          FROM magnitudes
        )
        SELECT
          *,
          CASE WHEN mn1_state_score < 0 THEN '-' || to_hex(abs(mn1_state_score)::UBIGINT) ELSE to_hex(mn1_state_score::UBIGINT) END AS mn1_state_hex,
          CASE WHEN w1_state_score < 0 THEN '-' || to_hex(abs(w1_state_score)::UBIGINT) ELSE to_hex(w1_state_score::UBIGINT) END AS w1_state_hex,
          CASE WHEN d1_state_score < 0 THEN '-' || to_hex(abs(d1_state_score)::UBIGINT) ELSE to_hex(d1_state_score::UBIGINT) END AS d1_state_hex,
          ((mn1_state_score IN (14, 15))::INTEGER + (w1_state_score IN (14, 15))::INTEGER + (d1_state_score IN (14, 15))::INTEGER) AS ef_count
        FROM scored
        ORDER BY stock_code, state_date
        """
    )

    # Stats
    stats = {
        "daily_rows": conn.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0],
        "weekly_rows": conn.execute("SELECT COUNT(*) FROM weekly_bars").fetchone()[0],
        "monthly_rows": conn.execute("SELECT COUNT(*) FROM monthly_bars").fetchone()[0],
        "state_rows": conn.execute("SELECT COUNT(*) FROM d1_perspective_state").fetchone()[0],
        "latest_date": str(conn.execute("SELECT MAX(state_date) FROM d1_perspective_state").fetchone()[0]),
        "tickers": conn.execute("SELECT COUNT(DISTINCT stock_code) FROM daily_bars").fetchone()[0],
    }

    conn.execute(
        """
        CREATE TABLE foundation_run_log AS
        SELECT
          'us_foundation_v0_1' AS schema_version,
          ? AS generated_at,
          'yfinance' AS source_raw_db,
          ? AS output_duckdb,
          ?::BIGINT AS daily_rows,
          ?::BIGINT AS state_rows,
          ? AS latest_date,
          true AS research_only_flag
        """,
        [datetime.now(timezone.utc).isoformat(timespec="seconds"), str(out_db), stats["daily_rows"], stats["state_rows"], stats["latest_date"]],
    )

    conn.close()
    print(f"  Foundation built: {out_db}")
    print(f"    tickers={stats['tickers']}, daily={stats['daily_rows']}, state={stats['state_rows']}, latest={stats['latest_date']}")
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--tickers", default=None, help="Comma-separated tickers or JSON file")
    parser.add_argument("--foundation-db", type=Path, default=FOUNDATION_DB)
    parser.add_argument("--batch-size", type=int, default=25, help="yfinance batch size")
    args = parser.parse_args()

    if args.tickers:
        if Path(args.tickers).exists():
            tickers = json.loads(Path(args.tickers).read_text())
        else:
            tickers = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        tickers = build_us_stock_pool()

    print(f"Stock pool: {len(tickers)} tickers")
    print(f"Date range: {args.start} ~ {args.end}")

    # yfinance works best with batches; download all at once for speed
    all_rows = []
    for i in range(0, len(tickers), args.batch_size):
        batch = tickers[i:i + args.batch_size]
        print(f"Batch {i//args.batch_size + 1}/{(len(tickers) + args.batch_size - 1)//args.batch_size}: {batch[:5]}...")
        rows = fetch_us_daily(batch, args.start, args.end)
        all_rows.extend(rows)

    if not all_rows:
        print("No data fetched.")
        return

    stats = build_foundation(all_rows, args.foundation_db, args.end)
    print(f"\n✅ US Foundation complete: {args.foundation_db}")
    print(f"   Tickers: {stats['tickers']}, Daily rows: {stats['daily_rows']}, State rows: {stats['state_rows']}")


if __name__ == "__main__":
    main()
