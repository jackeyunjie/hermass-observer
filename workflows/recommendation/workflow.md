# P116 Recommendation Workflow

## Purpose

Convert the daily all-three E/F observation pool into a research-only portfolio candidate list, watchlist, risk-review list, and directly openable HTML/CSV.

## Standard

- Runs by Python/CLI only; no IDE dependency.
- Default downstream LLM model: `deepseekV4`.
- First version is deterministic and does not require an LLM.
- Input pool: daily positive `MN1/W1/D1` all E/F snapshot.
- Optional enhancement: moneyflow CSV.
- Output language must be research-only and must not promise returns.

## Command

```bash
python3 recommendation/run_recommendation_workflow.py --date YYYY-MM-DD
```

With optional moneyflow:

```bash
python3 recommendation/run_recommendation_workflow.py \
  --date YYYY-MM-DD \
  --moneyflow-csv public/p116_moneyflow_enhanced_top10_YYYYMMDD.csv
```

## Outputs

```text
recommendation/outputs/p116_recommendation_YYYYMMDD.json
recommendation/outputs/p116_recommendation_YYYYMMDD.csv
public/p116_recommendation_YYYYMMDD.html
public/p116_recommendation_YYYYMMDD.csv
public/p116_recommendation_latest.html
```

## Scoring

The first version uses:

- state score sum
- E/F strength
- D1 ADX
- SR breakout count
- new-entry bonus
- W1 quality gate bonus
- optional moneyflow score

Portfolio selection adds industry concentration controls:

- max 3 per SW level-1 industry
- max 2 per SW level-2 industry
- target size 10
