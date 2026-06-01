#!/usr/bin/env python3
"""
Build unified daily data view.

Aggregates State environment, strategy signals, SR boundaries, moneyflow,
industry chain prosperity, and macro quadrant data into a single DuckDB
table keyed by (stock_code, date).

Usage:
    python3 scripts/build_unified_daily_view.py --date 2026-05-22

Dependencies: duckdb, pandas, numpy (all available in project env)
"""

import argparse
import json
import os
import sys
import logging
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field, asdict

import duckdb
import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("unified_view")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
PUBLIC_DIR = PROJECT_ROOT / "public"
RECOMMENDATION_DIR = PROJECT_ROOT / "recommendation" / "outputs"
UNIFIED_VIEW_DIR = OUTPUTS_DIR / "unified_view"


def _fmt_date(date: str) -> str:
    """Normalize date to YYYYMMDD for filenames."""
    return date.replace("-", "")


def json_path(subdir: str, name_template: str, date: str) -> Path:
    return OUTPUTS_DIR / subdir / name_template.format(date=_fmt_date(date))


def csv_path(subdir: str, name_template: str, date: str) -> Path:
    return OUTPUTS_DIR / subdir / name_template.format(date=_fmt_date(date))


# ---------------------------------------------------------------------------
# Safe JSON loader
# ---------------------------------------------------------------------------
def safe_load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        logger.warning("Missing file: %s", path)
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.warning("JSON parse error in %s: %s", path, e)
        return None
    except Exception as e:
        logger.warning("Read error for %s: %s", path, e)
        return None


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def load_state_ef(date: str) -> pd.DataFrame:
    """Load state_ef JSON and return rows as DataFrame."""
    path = json_path("state_cache", "state_ef_{date}.json", date)
    data = safe_load_json(path)
    if data is None or "rows" not in data:
        logger.error("state_ef missing or malformed for %s", date)
        return pd.DataFrame()
    rows = data["rows"]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["snapshot_date"] = date
    return df


def load_state_duration(date: str) -> pd.DataFrame:
    path = json_path("state_cache", "state_duration_{date}.json", date)
    data = safe_load_json(path)
    if data is None or "rows" not in data:
        logger.warning("state_duration missing for %s", date)
        return pd.DataFrame()
    df = pd.DataFrame(data["rows"])
    # Rename to avoid collision with state_ef; drop redundant state hex cols
    rename = {
        "d1_close": "duration_d1_close",
        "ef_count": "duration_ef_count",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    # Drop state hex columns already present in state_ef
    drop_cols = ["mn1_state_hex", "w1_state_hex", "d1_state_hex"]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore")
    return df


def load_sr_boundary(date: str) -> pd.DataFrame:
    """Load SR boundary and pick the best (smallest abs distance_pct) per stock."""
    path = json_path("state_cache", "sr_boundary_{date}.json", date)
    data = safe_load_json(path)
    if data is None or "rows" not in data:
        logger.warning("sr_boundary missing for %s", date)
        return pd.DataFrame()
    df = pd.DataFrame(data["rows"])
    if df.empty:
        return df
    # Pick boundary with smallest absolute distance per stock
    df["abs_distance"] = df["distance_pct"].abs()
    df = df.sort_values("abs_distance").groupby("stock_code", as_index=False).first()
    # Rename for clarity
    df = df.rename(
        columns={
            "boundary_type": "sr_boundary_type",
            "distance_pct": "sr_distance_pct",
            "boundary_direction": "sr_boundary_direction",
            "above_resistance": "sr_above_resistance",
            "below_support": "sr_below_support",
            "boundary_price": "sr_boundary_price",
            "boundary_period": "sr_boundary_period",
        }
    )
    cols = [
        "stock_code",
        "sr_boundary_type",
        "sr_distance_pct",
        "sr_boundary_direction",
        "sr_above_resistance",
        "sr_below_support",
        "sr_boundary_price",
        "sr_boundary_period",
    ]
    return df[[c for c in cols if c in df.columns]]


def compute_reward_risk(df: pd.DataFrame) -> pd.DataFrame:
    """Compute upside/downside potential and RR ratio from SR boundary data.

    Requires columns: d1_close, sr_boundary_price, sr_boundary_type
    Adds columns: estimated_rr_ratio, upside_potential, downside_risk, rr_confidence
    """
    # Initialize
    df["upside_potential"] = np.nan
    df["downside_risk"] = np.nan
    df["estimated_rr_ratio"] = np.nan
    df["rr_confidence"] = np.nan

    # Need full SR data (all boundaries per stock) to compute both S and R
    # The current df only has the "best" boundary (smallest distance).
    # We need to load the full SR cache again to get both support and resistance.
    date = str(df["snapshot_date"].iloc[0]) if "snapshot_date" in df.columns and not df.empty else ""
    if not date:
        return df

    path = json_path("state_cache", "sr_boundary_{date}.json", date)
    data = safe_load_json(path)
    rows = data.get("rows", [])

    # Group by stock_code
    from collections import defaultdict

    by_stock: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"resistance": None, "support": None, "close": None}
    )
    for row in rows:
        code = row.get("stock_code")
        if not code:
            continue
        btype = row.get("boundary_type")
        price = row.get("boundary_price")
        close = row.get("d1_close")
        entry = by_stock[code]
        if close is not None:
            entry["close"] = float(close)
        if btype in ("resistance", "support") and price is not None:
            # Keep the nearest (most relevant) boundary of each type
            current = entry[btype]
            dist = abs(float(row.get("distance_pct", 999)))
            if current is None or dist < current.get("dist", 999):
                entry[btype] = {"price": float(price), "dist": dist}

    # Compute RR for each stock
    for code, data in by_stock.items():
        close = data.get("close")
        resistance = data.get("resistance")
        support = data.get("support")
        if close is None or close <= 0:
            continue

        upside = None
        if resistance is not None:
            r_price = resistance["price"]
            if r_price > close:
                upside = (r_price - close) / close

        downside = None
        if support is not None:
            s_price = support["price"]
            if s_price < close:
                downside = (close - s_price) / close

        rr = None
        if upside is not None and downside is not None and downside > 0:
            rr = upside / downside

        confidence = 0.0
        if resistance is not None and support is not None:
            confidence = 1.0
        elif resistance is not None or support is not None:
            confidence = 0.5
        if upside is None or downside is None:
            confidence *= 0.5

        mask = df["stock_code"] == code
        df.loc[mask, "upside_potential"] = upside
        df.loc[mask, "downside_risk"] = downside
        df.loc[mask, "estimated_rr_ratio"] = rr
        df.loc[mask, "rr_confidence"] = confidence

    return df


def load_strategy_signals(date: str) -> pd.DataFrame:
    """Load strategy signals from DuckDB ledger for the given date."""
    ledger_db = OUTPUTS_DIR / "strategy_signals" / "strategy_signals.duckdb"
    if not ledger_db.exists():
        logger.warning("Strategy signals DuckDB not found: %s", ledger_db)
        return pd.DataFrame()
    try:
        con = duckdb.connect(str(ledger_db), read_only=True)
        df = con.execute("SELECT * FROM strategy_signal_daily WHERE signal_date = ?", [date]).fetchdf()
        con.close()
    except Exception as e:
        logger.warning("Failed to query strategy_signal_daily: %s", e)
        return pd.DataFrame()
    if df.empty:
        return df

    # Pivot: one row per stock, flags per strategy
    pivot = []
    for stock_code, group in df.groupby("stock_code"):
        row: dict[str, Any] = {"stock_code": stock_code}
        # VCP
        vcp = group[group["strategy_id"] == "vcp"]
        row["has_vcp_entry"] = bool((vcp["signal_type"] == "entry").any())
        row["has_vcp_structure"] = bool((vcp["signal_type"] == "structure").any())
        row["vcp_signal_strength"] = vcp["signal_strength"].max() if not vcp.empty else np.nan
        row["vcp_env_category"] = vcp["env_category"].iloc[0] if not vcp.empty else None

        # MA2560
        ma = group[group["strategy_id"] == "ma2560"]
        row["has_ma2560_entry"] = bool((ma["signal_type"] == "entry").any())
        row["has_ma2560_structure"] = bool((ma["signal_type"] == "structure").any())
        row["has_ma2560_exit"] = bool((ma["signal_type"] == "exit").any())
        row["ma2560_signal_strength"] = ma["signal_strength"].max() if not ma.empty else np.nan
        row["ma2560_env_category"] = ma["env_category"].iloc[0] if not ma.empty else None
        row["ma2560_market_match_level"] = ma["ma2560_market_match_level"].iloc[0] if not ma.empty else None

        # Bollinger Bandit
        bb = group[group["strategy_id"] == "bollinger_bandit"]
        row["has_bollinger_entry"] = bool((bb["signal_type"] == "entry").any())
        row["bollinger_signal_strength"] = bb["signal_strength"].max() if not bb.empty else np.nan
        row["bollinger_env_category"] = bb["env_category"].iloc[0] if not bb.empty else None

        # Best signal across all strategies
        entry_signals = group[group["signal_type"] == "entry"]
        if not entry_signals.empty:
            best = entry_signals.loc[entry_signals["signal_strength"].idxmax()]
            row["best_strategy_id"] = best["strategy_id"]
            row["best_signal_name"] = best["signal_name"]
            row["best_signal_strength"] = best["signal_strength"]
        else:
            row["best_strategy_id"] = None
            row["best_signal_name"] = None
            row["best_signal_strength"] = np.nan

        pivot.append(row)

    return pd.DataFrame(pivot)


def load_moneyflow(date: str) -> pd.DataFrame:
    """Load moneyflow evidence from CSV."""
    path = csv_path("moneyflow_evidence", "moneyflow_evidence_{date}.csv", date)
    if not path.exists():
        logger.warning("Moneyflow CSV missing: %s", path)
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype={"stock_code": str})
    except Exception as e:
        logger.warning("Failed to read moneyflow CSV: %s", e)
        return pd.DataFrame()
    # Rename for clarity
    rename = {
        "end_date": "moneyflow_end_date",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    return df


def load_recommendation(date: str) -> pd.DataFrame:
    """Load recommendation CSV for industry mapping and enriched scores."""
    # Try multiple locations
    for base in [RECOMMENDATION_DIR, PUBLIC_DIR]:
        path = base / f"p116_recommendation_{_fmt_date(date)}.csv"
        if path.exists():
            break
    else:
        logger.warning("Recommendation CSV missing for %s", date)
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype={"stock_code": str})
    except Exception as e:
        logger.warning("Failed to read recommendation CSV: %s", e)
        return pd.DataFrame()
    # Keep only columns we need
    # Use 'symbol' (full code with suffix) as stock_code for consistent joins
    if "symbol" in df.columns:
        df = df.drop(columns=["stock_code"], errors="ignore")
        df = df.rename(columns={"symbol": "stock_code"})
    keep = [
        "stock_code",
        "stock_name",
        "sw_l1",
        "sw_l2",
        "sw_l3",
        "recommendation_score",
        "state",
        "state_score_sum",
        "ef_strength",
        "d1_close",
        "d1_adx14",
        "best_selection_signal",
        "latest_vcp_signal",
        "latest_2560_signal",
        "macro_etf_symbol",
        "macro_etf_name",
        "macro_etf_state",
        "macro_etf_ef_count",
        "observation_reason",
        "risk_note",
    ]
    cols = [c for c in keep if c in df.columns]
    df = df[cols].copy()
    # Rename d1_close to avoid collision
    if "d1_close" in df.columns:
        df = df.rename(columns={"d1_close": "rec_d1_close"})
    return df


def load_ifind_industry(date: str) -> pd.DataFrame:
    """Load ifind industry mapping JSON (rich fallback for sw_l1/l2/l3)."""
    path = json_path("ifind", "industry_{date}.json", date)
    data = safe_load_json(path)
    if data is None:
        return pd.DataFrame()
    rows = data.get("rows", [])
    if not rows:
        logger.warning("ifind industry JSON has no rows for %s", date)
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # Keep only industry mapping columns
    keep = ["stock_code", "sw_l1", "sw_l2", "sw_l3"]
    cols = [c for c in keep if c in df.columns]
    if not cols:
        logger.warning("ifind industry JSON missing expected columns for %s", date)
        return pd.DataFrame()
    return df[cols].copy()


def load_ifind_industry_xlsx(date: str) -> pd.DataFrame:
    """Load ifind_stock_industry_chain_profile xlsx as fallback."""
    # Try exact date match first, then any available file
    base_dir = PROJECT_ROOT / "data"
    exact_path = base_dir / f"ifind_stock_industry_chain_profile_{_fmt_date(date)}.xlsx"
    if exact_path.exists():
        path = exact_path
    else:
        # Fallback: find any ifind_stock_industry_chain_profile_*.xlsx
        candidates = sorted(base_dir.glob("ifind_stock_industry_chain_profile_*.xlsx"))
        if not candidates:
            logger.warning("No ifind industry xlsx found in %s", base_dir)
            return pd.DataFrame()
        path = candidates[-1]  # Use latest
        logger.info("Using latest ifind xlsx fallback: %s", path.name)
    try:
        df = pd.read_excel(path, dtype={"证券代码": str})
    except Exception as e:
        logger.warning("Failed to read ifind xlsx: %s", e)
        return pd.DataFrame()
    # Map Chinese column names
    sw_l1_col = None
    sw_l2_col = None
    sw_l3_col = None
    for c in df.columns:
        if "申万" in c and "一级" in c:
            sw_l1_col = c
        elif "申万" in c and "二级" in c:
            sw_l2_col = c
        elif "申万" in c and "三级" in c:
            sw_l3_col = c
    if not sw_l1_col:
        logger.warning("ifind xlsx missing sw_l1 column")
        return pd.DataFrame()
    rename = {"证券代码": "stock_code"}
    if sw_l1_col:
        rename[sw_l1_col] = "sw_l1"
    if sw_l2_col:
        rename[sw_l2_col] = "sw_l2"
    if sw_l3_col:
        rename[sw_l3_col] = "sw_l3"
    df = df.rename(columns=rename)
    keep = ["stock_code", "sw_l1", "sw_l2", "sw_l3"]
    cols = [c for c in keep if c in df.columns]
    return df[cols].copy()


def load_stock_research_ledger(date: str) -> pd.DataFrame:
    """Load stock_research_ledger JSON as last-resort industry fallback."""
    path = json_path("fundamental", "stock_research_ledger_{date}.json", date)
    data = safe_load_json(path)
    if data is None:
        return pd.DataFrame()
    rows = data.get("rows", [])
    if not rows:
        logger.warning("stock_research_ledger has no rows for %s", date)
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    keep = ["stock_code", "sw_l1"]
    cols = [c for c in keep if c in df.columns]
    if not cols:
        return pd.DataFrame()
    return df[cols].copy()


def load_industry_chain(date: str) -> pd.DataFrame:
    """Load industry chain prosperity keyed by sw_l1."""
    path = json_path("industry_chain", "industry_position_summary_{date}.json", date)
    data = safe_load_json(path)
    if data is None:
        return pd.DataFrame()
    records = data.get("records", [])
    if not records:
        logger.warning("No industry_position_summary records for %s", date)
        return pd.DataFrame()
    df = pd.DataFrame(records)
    # Rename for clarity
    rename = {
        "rating": "chain_rating",
        "chain_position": "chain_position",
        "prosperity_score": "chain_prosperity_score",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    # Only keep join key + enrichment columns
    keep = [
        "sw_l1",
        "chain_position",
        "chain_prosperity_score",
        "chain_rating",
        "prosperity_change",
        "rating_change",
        "policy_support",
        "etf_symbol",
        "etf_ef_count",
    ]
    cols = [c for c in keep if c in df.columns]
    return df[cols]


def load_macro(date: str) -> pd.DataFrame:
    """Load macro snapshot (market-wide, to be broadcast)."""
    path = json_path("macro", "macro_snapshot_{date}.json", date)
    data = safe_load_json(path)
    if data is None:
        return pd.DataFrame()
    regime = data.get("regime", {})
    row: dict[str, Any] = {
        "macro_growth_regime": regime.get("growth_regime"),
        "macro_liquidity_regime": regime.get("liquidity_regime"),
        "macro_coverage_status": regime.get("coverage_status"),
    }
    # Extract any available indicator values by category
    indicators = data.get("indicators", [])
    for ind in indicators:
        cat = ind.get("category", "")
        code = ind.get("indicator_code", "")
        val = ind.get("value")
        trend = ind.get("trend")
        if val is not None:
            row[f"macro_ind_{code}_value"] = val
        if trend is not None:
            row[f"macro_ind_{code}_trend"] = trend
    # Also compute a simple macro_score if possible
    # (count of indicators with valid values)
    valid_count = sum(1 for i in indicators if i.get("value") is not None)
    row["macro_valid_indicator_count"] = valid_count
    row["macro_total_indicator_count"] = len(indicators)
    return pd.DataFrame([row])


def load_macro_chain_prior(date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load macro_chain_prior: strategy priors, industry priors, macro_prior.
    Returns (market_wide_df, industry_specific_df).
    """
    path = json_path("macro_chain_prior", "macro_chain_prior_{date}.json", date)
    data = safe_load_json(path)
    if data is None:
        return pd.DataFrame(), pd.DataFrame()

    # Market-wide priors (broadcast later)
    market_row: dict[str, Any] = {}

    macro_prior = data.get("macro_prior", {})
    market_row["macro_prior_score"] = macro_prior.get("score_0_10")
    market_row["macro_prior_confidence"] = macro_prior.get("confidence")

    msp = data.get("market_style_prior", {})
    market_row["market_risk_appetite_score"] = msp.get("risk_appetite_score")
    market_row["market_growth_style_score"] = msp.get("growth_style_score")
    market_row["market_small_cap_score"] = msp.get("small_cap_score")

    strategy_priors = data.get("strategy_priors", {})
    for sid, pri in strategy_priors.items():
        market_row[f"{sid}_prior_fit_score"] = pri.get("prior_fit_score")
        market_row[f"{sid}_prior_confidence"] = pri.get("confidence")

    # Industry-specific priors (to be joined by sw_l1)
    industry_priors = data.get("industry_priors", [])
    industry_df = pd.DataFrame()
    if industry_priors:
        industry_df = pd.DataFrame(industry_priors)
        industry_df = industry_df.rename(
            columns={
                "chain_prior_score": "industry_chain_prior_score",
                "confidence": "industry_chain_prior_confidence",
                "posterior_adjustment_hint": "industry_posterior_hint",
                "posterior_adjustment_label": "industry_posterior_label",
                "etf_symbol": "industry_etf_symbol",
                "etf_name": "industry_etf_name",
                "etf_state_combo": "industry_etf_state_combo",
                "etf_ef_count": "industry_etf_ef_count",
            }
        )
        keep = [
            "sw_l1",
            "industry_chain_prior_score",
            "industry_chain_prior_confidence",
            "industry_posterior_hint",
            "industry_posterior_label",
            "industry_etf_symbol",
            "industry_etf_name",
            "industry_etf_state_combo",
            "industry_etf_ef_count",
            "mapping_status",
        ]
        cols = [c for c in keep if c in industry_df.columns]
        industry_df = industry_df[cols]

    market_df = pd.DataFrame([market_row])
    return market_df, industry_df


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_unified_view(date: str) -> pd.DataFrame:
    """Build the unified daily view DataFrame for the given date."""
    logger.info("Building unified view for %s", date)

    # 1. Base universe: state_ef
    df = load_state_ef(date)
    if df.empty:
        logger.error("No state_ef data for %s — aborting", date)
        return pd.DataFrame()
    logger.info("State EF rows: %d", len(df))

    # 2. Merge state_duration
    dur = load_state_duration(date)
    if not dur.empty:
        df = df.merge(dur, on="stock_code", how="left")
        logger.info("Merged state_duration: +%d cols", len(dur.columns) - 1)

    # 3. Merge SR boundary (best per stock)
    sr = load_sr_boundary(date)
    if not sr.empty:
        df = df.merge(sr, on="stock_code", how="left")
        logger.info("Merged sr_boundary: +%d cols", len(sr.columns) - 1)

    # 4. Merge strategy signals (pivoted)
    sig = load_strategy_signals(date)
    if not sig.empty:
        df = df.merge(sig, on="stock_code", how="left")
        logger.info("Merged strategy signals: +%d cols", len(sig.columns) - 1)

    # 5. Merge moneyflow
    mf = load_moneyflow(date)
    if not mf.empty:
        df = df.merge(mf, on="stock_code", how="left")
        logger.info("Merged moneyflow: +%d cols", len(mf.columns) - 1)

    # 6. Merge recommendation (industry mapping + enriched scores)
    rec = load_recommendation(date)
    if not rec.empty:
        # Use recommendation's stock_name if state_ef lacks it
        df = df.merge(rec, on="stock_code", how="left")
        logger.info("Merged recommendation: +%d cols", len(rec.columns) - 1)
        # If state_ef has no stock_name, fill from recommendation
        if "stock_name" not in df.columns or df["stock_name"].isna().all():
            if "stock_name" in rec.columns:
                df["stock_name"] = df["stock_name"]

    # 6.5 Fallback industry mapping: recommendation > ifind JSON > ifind xlsx > research ledger
    def _apply_industry_fallback(fallback_df: pd.DataFrame, source_name: str) -> None:
        """Fill sw_l1/l2/l3 NULLs from fallback_df."""
        nonlocal df
        if fallback_df.empty:
            return
        if "sw_l1" not in df.columns:
            df["sw_l1"] = pd.NA
        # Identify rows needing fill
        need_fill = df["sw_l1"].isna()
        if not need_fill.any():
            return
        # Join fallback on stock_code
        fill_df = df.loc[need_fill, ["stock_code"]].merge(fallback_df, on="stock_code", how="left")
        filled_mask = fill_df["sw_l1"].notna()
        filled_count = filled_mask.sum()
        if filled_count == 0:
            return
        # Update original df
        idx = df.index[need_fill]
        for col in ["sw_l1", "sw_l2", "sw_l3"]:
            if col in fill_df.columns:
                df.loc[idx, col] = fill_df[col].values
        logger.info(
            "Industry fallback %s filled %d/%d NULLs",
            source_name,
            filled_count,
            need_fill.sum(),
        )

    # Apply fallbacks in priority order
    _apply_industry_fallback(load_ifind_industry(date), "ifind_json")
    _apply_industry_fallback(load_ifind_industry_xlsx(date), "ifind_xlsx")
    _apply_industry_fallback(load_stock_research_ledger(date), "research_ledger")

    # Report coverage
    if "sw_l1" in df.columns:
        coverage = df["sw_l1"].notna().mean() * 100
        logger.info(
            "sw_l1 coverage after fallbacks: %.1f%% (%d/%d)", coverage, df["sw_l1"].notna().sum(), len(df)
        )

    # 7. Industry chain (joined by sw_l1)
    chain = load_industry_chain(date)
    if not chain.empty:
        if "sw_l1" in df.columns:
            df = df.merge(chain, on="sw_l1", how="left")
            logger.info("Merged industry chain: +%d cols", len(chain.columns) - 1)
        else:
            logger.warning("Cannot join industry chain: sw_l1 not in base data")

    # 8. Macro snapshot (broadcast)
    macro = load_macro(date)
    if not macro.empty:
        for col in macro.columns:
            df[col] = macro[col].iloc[0]
        logger.info("Broadcast macro snapshot: +%d cols", len(macro.columns))

    # 9. Macro chain prior (market-wide + industry-specific)
    market_prior, industry_prior = load_macro_chain_prior(date)
    if not market_prior.empty:
        for col in market_prior.columns:
            df[col] = market_prior[col].iloc[0]
        logger.info("Broadcast macro chain prior: +%d cols", len(market_prior.columns))
    else:
        logger.warning("Macro chain prior missing for %s", date)
    if not industry_prior.empty and "sw_l1" in df.columns:
        df = df.merge(industry_prior, on="sw_l1", how="left")
        logger.info("Merged industry chain prior: +%d cols", len(industry_prior.columns) - 1)

    # 9.5 Reward/Risk estimate (compute from SR boundaries)
    if not sr.empty and "d1_close" in df.columns:
        df = compute_reward_risk(df)
        logger.info("Computed reward/risk estimates")

    # 10. Final cleanup
    # Ensure snapshot_date is present
    if "snapshot_date" not in df.columns:
        df["snapshot_date"] = date

    # Coerce boolean columns robustly
    bool_cols = [
        c
        for c in df.columns
        if c.startswith("has_") or c in ("sr_above_resistance", "sr_below_support", "moneyflow_confirmed")
    ]
    for c in bool_cols:
        if c in df.columns:
            # Handle strings like "True"/"False", numeric 1/0, and actual bools
            s = df[c]
            if s.dtype == object or s.dtype.name == "string":
                df[c] = s.map(
                    lambda x: (
                        True
                        if str(x).lower() == "true"
                        else (False if str(x).lower() == "false" else None)
                        if pd.notna(x)
                        else None
                    )
                ).astype("boolean")
            else:
                df[c] = s.astype("boolean")

    # Sort
    df = df.sort_values(["snapshot_date", "stock_code"]).reset_index(drop=True)

    logger.info("Final unified view: %d rows × %d cols", len(df), len(df.columns))
    return df


# ---------------------------------------------------------------------------
# DuckDB persistence
# ---------------------------------------------------------------------------


def ensure_table_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the unified_daily_snapshot table if not exists."""
    con.execute("""
    CREATE TABLE IF NOT EXISTS unified_daily_snapshot (
        snapshot_date                           DATE,
        stock_code                              VARCHAR,
        stock_name                              VARCHAR,

        -- State
        mn1_state_hex                           VARCHAR,
        w1_state_hex                            VARCHAR,
        d1_state_hex                            VARCHAR,
        ef_count                                INTEGER,
        state_score_sum                         DOUBLE,
        ef_strength                             DOUBLE,

        -- State duration
        d1_close                                DOUBLE,
        mn1_ef_duration                         INTEGER,
        w1_ef_duration                          INTEGER,
        d1_ef_duration                          INTEGER,
        all_three_ef_duration                   INTEGER,
        mn1_contraction_duration                INTEGER,
        w1_contraction_duration                 INTEGER,
        d1_contraction_duration                 INTEGER,
        mn1_days_since_contraction_exit         INTEGER,
        w1_days_since_contraction_exit          INTEGER,
        d1_days_since_contraction_exit          INTEGER,
        mn1_prev_contraction_duration           INTEGER,
        w1_prev_contraction_duration            INTEGER,
        d1_prev_contraction_duration            INTEGER,

        -- SR boundary
        sr_boundary_type                        VARCHAR,
        sr_distance_pct                         DOUBLE,
        sr_boundary_direction                   VARCHAR,
        sr_above_resistance                     BOOLEAN,
        sr_below_support                        BOOLEAN,
        sr_boundary_price                       DOUBLE,
        sr_boundary_period                      VARCHAR,

        -- Reward/Risk estimate
        estimated_rr_ratio                      DOUBLE,
        upside_potential                        DOUBLE,
        downside_risk                           DOUBLE,
        rr_confidence                           DOUBLE,

        -- Strategy signals
        has_vcp_entry                           BOOLEAN,
        has_vcp_structure                       BOOLEAN,
        vcp_signal_strength                     DOUBLE,
        vcp_env_category                        VARCHAR,
        has_ma2560_entry                        BOOLEAN,
        has_ma2560_structure                    BOOLEAN,
        has_ma2560_exit                         BOOLEAN,
        ma2560_signal_strength                  DOUBLE,
        ma2560_env_category                     VARCHAR,
        ma2560_market_match_level               VARCHAR,
        has_bollinger_entry                     BOOLEAN,
        bollinger_signal_strength               DOUBLE,
        bollinger_env_category                  VARCHAR,
        best_strategy_id                        VARCHAR,
        best_signal_name                        VARCHAR,
        best_signal_strength                    DOUBLE,

        -- Moneyflow
        moneyflow_end_date                      VARCHAR,
        window_days                             INTEGER,
        moneyflow_days_available                INTEGER,
        moneyflow_coverage_ratio                DOUBLE,
        moneyflow_status                        VARCHAR,
        moneyflow_confirmed                     BOOLEAN,
        moneyflow_divergence                    VARCHAR,
        moneyflow_score                         DOUBLE,
        positive_days_5d                        INTEGER,
        big_positive_days_5d                    INTEGER,
        active_net_5d                           DOUBLE,
        big_order_net_5d                        DOUBLE,
        latest_active_net                       DOUBLE,
        latest_big_order_net                    DOUBLE,
        active_net_ratio_5d                     DOUBLE,
        buy_total_5d                            DOUBLE,
        sell_total_5d                           DOUBLE,

        -- Recommendation / industry mapping
        sw_l1                                   VARCHAR,
        sw_l2                                   VARCHAR,
        sw_l3                                   VARCHAR,
        recommendation_score                    DOUBLE,
        state                                   VARCHAR,
        d1_adx14                                DOUBLE,
        best_selection_signal                   VARCHAR,
        latest_vcp_signal                       VARCHAR,
        latest_2560_signal                      VARCHAR,
        macro_etf_symbol                        VARCHAR,
        macro_etf_name                          VARCHAR,
        macro_etf_state                         VARCHAR,
        macro_etf_ef_count                      INTEGER,
        observation_reason                      VARCHAR,
        risk_note                               VARCHAR,

        -- Industry chain
        chain_position                          VARCHAR,
        chain_prosperity_score                  DOUBLE,
        chain_rating                            VARCHAR,
        prosperity_change                       VARCHAR,
        rating_change                           VARCHAR,
        policy_support                          VARCHAR,
        etf_symbol                              VARCHAR,
        etf_ef_count                            INTEGER,

        -- Macro
        macro_growth_regime                     VARCHAR,
        macro_liquidity_regime                  VARCHAR,
        macro_coverage_status                   VARCHAR,
        macro_valid_indicator_count             INTEGER,
        macro_total_indicator_count             INTEGER,

        -- Macro chain prior (market-wide)
        macro_prior_score                       DOUBLE,
        macro_prior_confidence                  DOUBLE,
        market_risk_appetite_score              DOUBLE,
        market_growth_style_score               DOUBLE,
        market_small_cap_score                  DOUBLE,
        vcp_prior_fit_score                     DOUBLE,
        vcp_prior_confidence                    DOUBLE,
        ma2560_prior_fit_score                  DOUBLE,
        ma2560_prior_confidence                 DOUBLE,
        bollinger_bandit_prior_fit_score        DOUBLE,
        bollinger_bandit_prior_confidence       DOUBLE,

        -- Macro chain prior (industry-specific)
        industry_chain_prior_score              DOUBLE,
        industry_chain_prior_confidence         DOUBLE,
        industry_posterior_hint                 VARCHAR,
        industry_posterior_label                VARCHAR,
        industry_etf_symbol                     VARCHAR,
        industry_etf_name                       VARCHAR,
        industry_etf_state_combo                VARCHAR,
        industry_etf_ef_count                   INTEGER,
        mapping_status                          VARCHAR,

        -- Extensibility
        extra_json                              VARCHAR,

        PRIMARY KEY (snapshot_date, stock_code)
    )
    """)


def write_to_duckdb(df: pd.DataFrame, date: str) -> Path:
    UNIFIED_VIEW_DIR.mkdir(parents=True, exist_ok=True)
    db_path = UNIFIED_VIEW_DIR / "unified_daily_snapshot.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_table_schema(con)

    # Incremental: delete existing rows for this date
    con.execute("DELETE FROM unified_daily_snapshot WHERE snapshot_date = ?", [date])
    logger.info("Deleted existing rows for %s (if any)", date)

    # Build column list from actual DataFrame, mapping to table columns
    table_cols = set()
    try:
        desc = con.execute("DESCRIBE unified_daily_snapshot").fetchdf()
        table_cols = set(desc["column_name"].tolist())
    except Exception:
        pass

    # Only insert columns that exist in both DataFrame and table schema
    df_cols = [c for c in df.columns if c in table_cols]
    # Add extra_json for anything not in schema
    extra_cols = [c for c in df.columns if c not in table_cols]
    if extra_cols:
        df["extra_json"] = df[extra_cols].apply(
            lambda row: json.dumps(row.dropna().to_dict(), ensure_ascii=False, default=str),
            axis=1,
        )
        df_cols.append("extra_json")

    insert_df = df[df_cols].copy()
    # Clean: replace empty strings with None/NaN for numeric columns
    for c in insert_df.columns:
        if insert_df[c].dtype == object or insert_df[c].dtype.name == "string":
            # Replace empty strings and literal 'None'/'null' with NA
            insert_df[c] = insert_df[c].replace(["", "None", "null", "NULL"], pd.NA)
    # Ensure snapshot_date is DATE type
    insert_df["snapshot_date"] = pd.to_datetime(insert_df["snapshot_date"]).dt.date

    con.register("insert_df", insert_df)
    col_list = ", ".join(f'"{c}"' for c in insert_df.columns)
    con.execute(f"INSERT INTO unified_daily_snapshot ({col_list}) SELECT {col_list} FROM insert_df")
    con.unregister("insert_df")

    # Stats
    total = con.execute(
        "SELECT COUNT(*) FROM unified_daily_snapshot WHERE snapshot_date = ?", [date]
    ).fetchone()[0]
    logger.info("Written %d rows to unified_daily_snapshot for %s", total, date)

    con.close()
    return db_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Build unified daily data view")
    parser.add_argument("--date", required=True, help="Snapshot date (YYYY-MM-DD)")
    parser.add_argument("--validate", action="store_true", help="Run validation queries after build")
    parser.add_argument("--output-csv", action="store_true", help="Also write CSV snapshot")
    args = parser.parse_args()

    date = args.date

    # Build
    df = build_unified_view(date)
    if df.empty:
        logger.error("No data produced for %s", date)
        return 1

    # Persist
    db_path = write_to_duckdb(df, date)
    logger.info("DuckDB: %s", db_path)

    # Optional CSV
    if args.output_csv:
        csv_path = UNIFIED_VIEW_DIR / f"unified_daily_snapshot_{date}.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        logger.info("CSV: %s", csv_path)

    # Optional validation
    if args.validate:
        con = duckdb.connect(str(db_path), read_only=True)
        logger.info("=== Validation ===")

        # Row count
        cnt = con.execute(
            "SELECT COUNT(*) FROM unified_daily_snapshot WHERE snapshot_date = ?", [date]
        ).fetchone()[0]
        logger.info("Rows for %s: %d", date, cnt)

        # NULL fractions for key columns
        key_cols = [
            "mn1_state_hex",
            "w1_state_hex",
            "d1_state_hex",
            "ef_count",
            "moneyflow_status",
            "sw_l1",
            "macro_growth_regime",
            "best_strategy_id",
        ]
        for col in key_cols:
            try:
                null_frac = con.execute(
                    f"""SELECT COUNT(CASE WHEN "{col}" IS NULL THEN 1 END) * 1.0 / COUNT(*)
                        FROM unified_daily_snapshot WHERE snapshot_date = ?""",
                    [date],
                ).fetchone()[0]
                logger.info("NULL fraction %s: %.2f%%", col, (null_frac or 0) * 100)
            except Exception as e:
                logger.warning("Validation error for %s: %s", col, e)

        # Strategy signal counts
        for flag in ["has_vcp_entry", "has_ma2560_entry", "has_bollinger_entry"]:
            try:
                true_cnt = con.execute(
                    f"""SELECT COUNT(*) FROM unified_daily_snapshot
                        WHERE snapshot_date = ? AND "{flag}" = TRUE""",
                    [date],
                ).fetchone()[0]
                logger.info("%s = TRUE: %d", flag, true_cnt)
            except Exception as e:
                logger.warning("Validation error for %s: %s", flag, e)

        con.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
