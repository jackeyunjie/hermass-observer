# Daily Observation Workflow

This workflow publishes the P116 daily observation artifacts from the product-local foundation database.

## Inputs

Foundation database:

```text
outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb
```

## Product workflow

Daily all-three E/F pool, no 100-stock cap:

```bash
python3 scripts/run_daily_all_three_ef_workflow.py \
  --date YYYY-MM-DD \
  --previous-date YYYY-MM-DD \
  --skip-foundation \
  --foundation-db outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb
```

## Output

```text
public/p116_all_three_ef_YYYYMMDD.html
public/p116_all_three_ef_YYYYMMDD.csv
public/p116_all_three_ef_diff_YYYYMMDD.html
public/p116_all_three_ef_diff_YYYYMMDD.csv
outputs/p116_daily_all_three_ef/
```

## Rule

Current foundation calculation uses D1 perspective, ADX/DI trend, BB bandwidth compression, ATR% dynamic volatility, and SR from each timeframe. Downstream report/model steps default to `deepseekV4` and must remain directly runnable by Python/CLI without IDE dependence.
