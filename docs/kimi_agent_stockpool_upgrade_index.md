# Kimi Agent 股票服务升级材料索引

Source folder:

```text
data/Kimi_Agent_股票服务升级/
```

## What To Reuse

- `Agently_DAG_StockPool_Technical_Design.md`
  - Use as the conceptual DAG / TriggerFlow design reference.
  - Current production mapping lives in `workflows/agently_stockpool_dag/`.

- `stockpool.agent.final.md` and `research/*.md`
  - Use as product strategy, compliance, user segmentation, and roadmap references.
  - Do not treat market-size or compliance claims as final legal advice without source verification.

- `app/`
  - React/Vite product presentation site.
  - Keep isolated from the production stockpool pipeline until we intentionally build a public marketing site.

## What Not To Directly Replace

- `heilang_data_toolkit.py`
  - Useful as a conceptual toolkit, but it uses a different base URL/token convention than our current Blackwolf production scripts.
  - Production download actions are in `blackwolf_actions/`.

## Current Production Modules

- Blackwolf Actions: `blackwolf_actions/`
- Agently-compatible DAG: `workflows/agently_stockpool_dag/`
- Local DAG runner: `agently_adapter/stockpool_daily_runner.py`
- Recommendation workbench: `recommendation/`
- Shareable table / Excel: `public/p116_recommendation_shareable_YYYYMMDD.html`, `.xlsx`

## Current Full-Chain Command

After configuring the Blackwolf token:

```bash
python3 agently_adapter/stockpool_daily_runner.py run \
  --date YYYY-MM-DD \
  --previous-date YYYY-MM-DD \
  --download \
  --build-raw \
  --build-foundation
```

For a non-destructive daily download test:

```bash
python3 agently_adapter/stockpool_daily_runner.py download_daily \
  --date YYYY-MM-DD \
  --previous-date YYYY-MM-DD \
  --test-download
```
