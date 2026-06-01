#!/usr/bin/env python3
"""Run backtest v3 with quality score + market breadth filter."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.config import BacktestConfig
from backtest.engine import run_backtest

config = BacktestConfig(
    min_ef_count=3,
    max_positions=15,
    lookback_days=252,
    warmup_days=60,
    hold_days_range=(5, 30),
    trailing_stop_pct=0.10,
    take_profit_atr_mult=4.0,
    max_single_pct=0.05,
)

result = run_backtest("2026-05-20", config)

import json

out = Path("outputs/backtest_v3_20260520")
out.mkdir(parents=True, exist_ok=True)
(out / "backtest_result.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
    encoding="utf-8",
)
print(f"\nSaved to {out}")
