# P116 Daily All-Three E/F Workflow

## Purpose

Build and publish the daily full-market list where `MN1`, `W1`, and `D1` are all `E` or `F`.

This workflow is not capped at 100 names. It saves the complete daily membership, then compares it with the previous snapshot:

- `entered`: new names in today's all-three E/F pool
- `left`: names that left today's all-three E/F pool
- `stayed`: names still in the pool

## Calculation Standard

- Foundation source: `outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb`
- Perspective: D1 close compared with each timeframe's own SR
- Trend: ADX/DI
- Compression: Bollinger Band width quantile / expansion
- Volatility: ATR% dynamic comparison
- State requirement: `mn1_state_hex`, `w1_state_hex`, `d1_state_hex` all in `E/F`
- Sign priority: SR position wins over trend conflict. If D1 close is below that timeframe support, the state is negative even when ADX/DI still says bull.
- Quality gate: exclude candidates with weekly closes falling for 3 consecutive W1 bars or W1 close below AMA10.
- Default model for downstream report text: `deepseekV4`

## Daily Command

Use an existing foundation DB:

```bash
python3 scripts/run_daily_all_three_ef_workflow.py \
  --date 2026-05-20 \
  --previous-date 2026-05-19 \
  --skip-foundation \
  --foundation-db outputs/p116_foundation_20260520/p116_foundation.duckdb
```

Rebuild foundation from Blackwolf raw DB first:

```bash
python3 scripts/run_daily_all_three_ef_workflow.py \
  --date 2026-05-20 \
  --previous-date 2026-05-19 \
  --raw-db /path/to/p108_blackwolf_ashare_daily_raw.duckdb
```

## Outputs

```text
outputs/p116_daily_all_three_ef/p116_all_three_ef_YYYYMMDD.json
outputs/p116_daily_all_three_ef/p116_all_three_ef_YYYYMMDD.csv
outputs/p116_daily_all_three_ef/p116_all_three_ef_diff_YYYYMMDD.json
outputs/p116_daily_all_three_ef/p116_all_three_ef_diff_YYYYMMDD.csv
public/p116_all_three_ef_YYYYMMDD.html
public/p116_all_three_ef_YYYYMMDD.csv
public/p116_all_three_ef_diff_YYYYMMDD.html
public/p116_all_three_ef_diff_YYYYMMDD.csv
public/p116_all_three_ef_latest.html
public/p116_all_three_ef_diff_latest.html
```

The `public/*.html` files are directly openable in a browser and are also served by the local HTTP server.
