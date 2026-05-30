# Agently-Compatible Stockpool DAG

> Scope: active production scope is A-share only. Archived MT5/US-related files are not part of this workflow.

This folder defines the stock pool daily update as an Action/DAG style workflow.

The production runner is pure Python and works without Agently installed:

```bash
python3 agently_adapter/stockpool_daily_runner.py run \
  --date 2026-05-22 \
  --previous-date 2026-05-21 \
  --foundation-db outputs/p116_foundation_20260522/p116_foundation.duckdb
```

The `run` command now executes the daily closed loop: all-three E/F pool,
industry ETF coverage, State cache, VCP/2560 evidence, recommendation, strategy
signal ledger, reminder brief, forward observation, daily research brief, and
2560 market-match diagnostics.

For the new A-share-only Agently core flow, use:

```bash
cd /tmp
/Users/lv111101/Documents/hermass-observer-product/.venv/bin/python \
  /Users/lv111101/Documents/hermass-observer-product/agently_adapter/agently_a_share_flow.py \
  --date 2026-05-22 \
  --previous-date 2026-05-21 \
  --foundation-db /Users/lv111101/Documents/hermass-observer-product/outputs/p116_foundation_20260522/p116_foundation.duckdb
```

This core flow is the A-share-only Agently entry for the deterministic pipeline. It is the preferred entry for new integrations; the older `agently_daily_flow.py` remains as the full workflow compatibility flow:

- `preflight`
- `build_foundation`
- `build_state_cache`
- `build_strategy_evidence`
- `build_strategy_signal_ledger`
- `build_forward_observation`
- `build_daily_brief`
- `verify_core_outputs`

Here `verify_core_outputs` only validates the minimal A-share core chain (core outputs). The older `verify_public_outputs` command validates the full closed-loop public-output for `stockpool_daily_runner.py run`, and is modeled as `core outputs + public extensions`.

The shared implementation for this minimal A-share path now lives in
`agently_adapter/a_share_core.py`. The runner compatibility layer,
`a_share_actions.py`, and the FastAPI service should reuse this core module
instead of duplicating shell-level command orchestration.

The older `agently_daily_flow.py` is the full workflow compatibility flow — a wrapper around the larger `stockpool_daily_runner.py run` command. It is preserved for backward compatibility but is no longer the recommended main entry.

To execute the full workflow compatibility flow through Agently `TriggerFlow`, run it from a directory outside the project root. The project contains a business package named `signal/`, so launching from outside the root avoids shadowing Python's stdlib `signal` module while Agently starts its event loop.

```bash
cd /tmp
/Users/lv111101/Documents/hermass-observer-product/.venv/bin/python \
  /Users/lv111101/Documents/hermass-observer-product/agently_adapter/agently_daily_flow.py \
  --date 2026-05-22 \
  --previous-date 2026-05-21 \
  --foundation-db outputs/p116_foundation_20260522/p116_foundation.duckdb
```

Full chain after the Blackwolf token is configured:

```bash
python3 agently_adapter/stockpool_daily_runner.py run \
  --date YYYY-MM-DD \
  --previous-date YYYY-MM-DD \
  --download \
  --download-moneyflow \
  --build-raw \
  --build-foundation
```

For a no-risk download test, use:

```bash
python3 agently_adapter/stockpool_daily_runner.py download_daily \
  --date 2026-05-21 \
  --previous-date 2026-05-20 \
  --test-download
```

## Blackwolf Download Actions

Configure the token once:

```bash
python3 blackwolf_actions/configure_token.py --stdin
```

Then daily OHLCV and recent moneyflow can run as actions:

```bash
python3 blackwolf_actions/download_daily.py --date 2026-05-21 --base-date 2026-05-20 --test
python3 blackwolf_actions/download_moneyflow_recent.py --end-date 2026-05-21 --days 5 --limit 10
```

Moneyflow is a required base data layer in the daily DAG, not a recommendation-only enhancement. The daily DAG downloads only the target trading date, imports it into the long-lived DuckDB, then builds 5-day evidence from the database.

Long-lived moneyflow DB:

```text
outputs/blackwolf_moneyflow/blackwolf_moneyflow.duckdb
```

Bootstrap or repair the latest 5 trading days:

```bash
python3 agently_adapter/stockpool_daily_runner.py download_moneyflow \
  --date 2026-05-21 \
  --moneyflow-days 5

python3 agently_adapter/stockpool_daily_runner.py import_moneyflow_db_range \
  --date 2026-05-21 \
  --moneyflow-days 5

python3 agently_adapter/stockpool_daily_runner.py build_moneyflow_evidence \
  --date 2026-05-21 \
  --moneyflow-days 5
```

Normal daily update after bootstrap:

```bash
python3 agently_adapter/stockpool_daily_runner.py download_moneyflow --date YYYY-MM-DD --moneyflow-days 1
python3 agently_adapter/stockpool_daily_runner.py import_moneyflow_db --date YYYY-MM-DD
python3 agently_adapter/stockpool_daily_runner.py build_moneyflow_evidence --date YYYY-MM-DD --moneyflow-days 5
```

## Mapping to Agently 4.1.x

- `action_type: python_cli` maps to an Agently Action.
- `phases.start` maps to TriggerFlow start.
- `preflight_freshness` is the first required start Action; it prevents stale software/data from running a new task.
- `phases.seal` maps to deterministic calculation and publishing actions.
- `phases.close` maps to output verification and handoff.
- `depends_on` is the DAG dependency boundary.

This design keeps the daily production pipeline independent from the framework runtime while leaving a direct path to wrap each command as an Agently Action later.

## DeepSeek Context Memory

Local DeepSeek calls do not inherit context from the web UI. Project-wide LLM
memory lives in:

```text
config/deepseek_context.md
```

Python scripts call `scripts.deepseek_context.with_deepseek_context(...)` before
sending system prompts to DeepSeek. Agently DAG defaults also reference this
file through `llm_context`.

The context defines the Hermass State boundary: State is a deterministic,
read-only A-share D1-Agent calculation base; DeepSeek may explain and calibrate
upper-layer strategy evidence, but must not modify State formulas or invent
facts.

## Outputs

- `public/p116_all_three_ef_YYYYMMDD.html`
- `public/macro_snapshot_YYYYMMDD.html`
- `public/macro_chain_prior_YYYYMMDD.html`
- `public/industry_etf_coverage_YYYYMMDD.html`
- `public/industry_etf_config_YYYYMMDD.html`
- `public/market_assets_state_YYYYMMDD.html`
- `public/p116_recommendation_YYYYMMDD.html`
- `public/p116_recommendation_shareable_YYYYMMDD.html`
- `public/p116_recommendation_shareable_YYYYMMDD.xlsx`
- `public/strategy_reminder_YYYYMMDD.html`
- `public/forward_observation_YYYYMMDD.html`
- `public/daily_research_brief_YYYYMMDD.html`
- `public/ma2560_market_match_forward_YYYYMMDD.html`
- `public/ma2560_stock_only_gap_audit_YYYYMMDD.html`

Useful single-action commands:

```bash
python3 agently_adapter/stockpool_daily_runner.py build_industry_etf_coverage --date YYYY-MM-DD
python3 agently_adapter/stockpool_daily_runner.py build_ifind_macro --date YYYY-MM-DD
python3 agently_adapter/stockpool_daily_runner.py build_ifind_macro --date YYYY-MM-DD --macro-import-file data/ifind_macro_YYYYMMDD.xlsx
python3 agently_adapter/stockpool_daily_runner.py build_macro_chain_prior --date YYYY-MM-DD
python3 agently_adapter/stockpool_daily_runner.py build_industry_etf_config --date YYYY-MM-DD
python3 agently_adapter/stockpool_daily_runner.py analyze_ma2560_market_match_forward --date YYYY-MM-DD
python3 agently_adapter/stockpool_daily_runner.py audit_ma2560_stock_only_gap --date YYYY-MM-DD
python3 agently_adapter/stockpool_daily_runner.py generate_daily_brief --date YYYY-MM-DD
```

Proxy ETF review lives in `config/industry_etf_proxy_whitelist.json`. Pending proxies stay in audit only; approved proxies are applied by the final ETF config node and become active after the next market-asset download/import/state build.

## iFinD Fundamental Weekly Agent

The iFinD fundamental agent is the slow, database-backed research lane. It keeps
facts in DuckDB, computes deterministic L2 quality scores, then lets DeepSeek
write a research-only interpretation from SQL-selected evidence.

Main command:

```bash
python3 agently_adapter/stockpool_daily_runner.py run_fundamental_weekly \
  --date YYYY-MM-DD
```

Smoke or ledger-limited run:

```bash
python3 agently_adapter/stockpool_daily_runner.py run_fundamental_weekly \
  --date 2026-05-21 \
  --limit 5
```

Expected iFinD GUI Excel files:

```text
data/ifind_stock_income_core_mrq_YYYYMMDD.xlsx
data/ifind_stock_balance_core_mrq_YYYYMMDD.xlsx
data/ifind_stock_cashflow_core_mrq_YYYYMMDD.xlsx
data/ifind_stock_industry_chain_profile_YYYYMMDD.xlsx
```

Override any file explicitly when needed:

```bash
python3 agently_adapter/stockpool_daily_runner.py run_fundamental_weekly \
  --date YYYY-MM-DD \
  --income-core-excel /path/to/income.xlsx \
  --balance-core-excel /path/to/balance.xlsx \
  --cashflow-core-excel /path/to/cashflow.xlsx \
  --industry-chain-excel /path/to/chain.xlsx
```

Core outputs:

```text
outputs/fundamental/fundamental_evidence.duckdb
outputs/fundamental/ai_research_loop_input_YYYYMMDD.md
outputs/fundamental/ai_research_loop_YYYYMMDD.md
outputs/fundamental/stock_research_ledger_YYYYMMDD.json
public/stock_research_ledger_YYYYMMDD.html
```

Operational notes:

- Excel imports are idempotent. Re-running the same date refreshes evidence
  packets for the active tracking pool without rewriting already imported facts.
- DuckDB allows one writer at a time. Do not run multiple iFinD import commands
  in parallel against `outputs/fundamental/fundamental_evidence.duckdb`.
- L1 facts come from iFinD. L2 scores are deterministic Python calculations.
  L3 DeepSeek output is research-only and must stay evidence-constrained.
- Keep exported iFinD files under ASCII names matching the expected patterns.

### iFinD Usage Stress Test

Use this before wiring the fundamental DB into a UI, chatbot, API endpoint, or
new research workflow:

```bash
python3 agently_adapter/stockpool_daily_runner.py run_ifind_usage_stress \
  --date YYYY-MM-DD \
  --iterations 3000 \
  --workers 32
```

The stress test is read-only. It simulates:

- single-stock ledger lookup
- evidence packet retrieval for LLM prompts
- high-quality fundamental screening
- concept/theme scan with quality ranking
- industry rollup
- AI Research Loop prompt packing
- frontend/API-style ledger lookup

Outputs:

```text
outputs/fundamental/ifind_usage_stress_YYYYMMDD.json
outputs/fundamental/ifind_usage_stress_YYYYMMDD.md
```

For the 2026-05-21 local DB snapshot, 3000 queries with 32 workers completed
with p95 around 18 ms/query, which is responsive enough for interactive
research and local app usage.

## Hermass State Usage Stress Test

Use this before exposing the P116 State system to a UI, chatbot, recommendation
service, or multi-Agent research flow:

```bash
python3 agently_adapter/stockpool_daily_runner.py run_state_usage_stress \
  --date YYYY-MM-DD \
  --iterations 5000 \
  --workers 32
```

The test is read-only. It simulates:

- single-stock latest MN1/W1/D1 state lookup
- single-stock 120-day state trajectory
- full-market all-three E/F SQL screen
- full-market state distribution
- SR boundary-near scan
- recent D1 state transition scan
- daily all-three E/F JSON read
- daily entered/left/stayed diff JSON read
- State x pattern lifecycle cross read
- market regime / ETF state read

Outputs:

```text
outputs/state_stress/state_usage_stress_YYYYMMDD.json
outputs/state_stress/state_usage_stress_YYYYMMDD.md
```

For the 2026-05-21 foundation DB snapshot (`d1_perspective_state` ~8.49M
rows), 5000 queries with 32 workers completed with p95 around 381 ms/query.
This is acceptable for research/Agent use. For high-concurrency UI/API use,
prefer precomputed JSON or small materialized outputs for full-market scans
such as all-three E/F, state distribution, SR boundary scans, and state
transitions.

## Hermass State Cache Layer

Build the daily cache after the foundation DB and all-three E/F export are
ready:

```bash
python3 agently_adapter/stockpool_daily_runner.py build_state_cache \
  --date YYYY-MM-DD \
  --foundation-db outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb
```

The cache keeps the State foundation DB as the read-only source of truth and
materializes the slow full-market scans into a separate DB plus JSON files:

```text
outputs/state_cache/state_cache.duckdb
outputs/state_cache/state_ef_YYYYMMDD.json
outputs/state_cache/state_distribution_YYYYMMDD.json
outputs/state_cache/state_transition_YYYYMMDD.json
outputs/state_cache/sr_boundary_YYYYMMDD.json
outputs/state_cache/state_duration_YYYYMMDD.json
outputs/state_cache/state_cache_manifest_YYYYMMDD.json
```

Tables:

- `state_ef_daily`: raw all-three E/F set from `d1_perspective_state`.
- `state_distribution_daily`: MN1/W1/D1/combo state distribution.
- `state_transition_daily`: recent MN1/W1/D1 state changes.
- `sr_boundary_daily`: MN1/W1/D1 support/resistance boundary-near rows, with signed close-vs-boundary and range direction.
- `state_duration_daily`: current consecutive MN1/W1/D1/all-three E/F duration rows.

The builder validates that `state_ef_daily` matches the direct all-three E/F
SQL count. Strategy, UI, API, and research Agents should prefer this cache for
full-market scans instead of repeatedly scanning the full foundation DB.

## Strategy Evidence Calibration

After `strategy_evaluation_YYYYMMDD.json` includes `factor_breakdown`, the
calibration lane can label historical evidence rows with future 5/10/20-day
excess returns and search A/B/C/watch thresholds:

```bash
python3 agently_adapter/stockpool_daily_runner.py calibrate_strategy_evidence \
  --date YYYY-MM-DD \
  --start-date YYYY-MM-DD
```

Default config:

```text
config/strategy_evidence_calibration_default.json
```

Outputs:

```text
outputs/strategy_evaluation/strategy_evidence_calibration_YYYYMMDD.json
outputs/strategy_evaluation/strategy_evidence_calibration_YYYYMMDD.md
outputs/strategy_evaluation/strategy_evidence_calibrated_config_YYYYMMDD.json
```

The script refuses to optimize when history is insufficient. This is intentional:
thresholds must be learned from enough historical dates and out-of-sample labels,
not from one strong E/F snapshot.

## Strategy Signal Ledger

Reminder and UI layers must not reimplement strategy logic. They should consume
the normalized ledger built from authoritative strategy modules:

```bash
python3 agently_adapter/stockpool_daily_runner.py build_strategy_signal_ledger \
  --date YYYY-MM-DD \
  --foundation-db outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb
```

Outputs:

```text
outputs/strategy_signals/strategy_signals.duckdb
outputs/strategy_signals/strategy_signal_daily_YYYYMMDD.json
outputs/strategy_signals/strategy_signal_daily_latest.json
```

Ledger table:

- `strategy_signal_daily`
  - `signal_date`
  - `stock_code`
  - `strategy_id`
  - `signal_type`: `entry`, `exit`, `risk`, `structure`
  - `signal_name`
  - `signal_strength`
  - `params_json`
  - `raw_signal`
  - `source_module`
  - `research_only`
  - `reminder_eligible`: true only for officially displayable reminder signals.
  - `display_scope`: `reminder`, `research`, or future internal scopes.

Current authoritative sources:

- VCP: `backtest.strategy_signals.vcp.vcp_signal`
- 2560: `backtest.strategy_signals.ma2560.ma2560_signal`
- Bollinger Bandit: `backtest.strategy_signals.bollinger_bandit.bollinger_bandit_signal`

ATR Chandelier requires real position context (`entry_price`,
`highest_since_entry`, and ATR multiple). The ledger does not emit Chandelier
signals without that context, so reminder layers cannot fabricate Chandelier
alerts from price data alone.

## Strategy Reminder Brief

The reminder brief is a pure composition layer. It reads only normalized facts
from the signal ledger and cache outputs, then emits a research-only JSON and
HTML brief:

```bash
python3 agently_adapter/stockpool_daily_runner.py build_strategy_reminder \
  --date YYYY-MM-DD
```

Outputs:

```text
outputs/strategy_reminders/reminder_YYYYMMDD.json
outputs/strategy_reminders/reminder_latest.json
public/strategy_reminder_YYYYMMDD.html
public/strategy_reminder_latest.html
```

Inputs:

- `strategy_signal_daily_YYYYMMDD.json`: only rows with `reminder_eligible=true`
  and `display_scope=reminder`.
- `state_ef_YYYYMMDD.json` and `state_duration_YYYYMMDD.json`.
- `sr_boundary_YYYYMMDD.json`, including signed boundary fields.
- Optional `stock_research_ledger_YYYYMMDD.json`.
- Optional calibration/evaluation outputs. Missing calibration remains `待校准`.

Guardrails:

- It does not calculate, simplify, or infer strategy triggers.
- It does not generate trading instructions.
- Output labels are limited to approved research reminder language such as
  `趋势新生`, `趋势行进`, `趋势延展`, `防守参考线`, and `状态值得复核`.

## Historical Replay

Use `replay_history` to backfill the cache/evidence/reminder consumer layer over
historical dates. It reuses the existing foundation DB as the read-only source,
runs selected steps in dependency order inside each date, and can process dates
in parallel:

```bash
python3 agently_adapter/stockpool_daily_runner.py replay_history \
  --start-date YYYY-MM-DD \
  --end-date YYYY-MM-DD \
  --foundation-db outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb \
  --workers 4 \
  --steps state_cache,signal_ledger,strategy_evaluation,reminder
```

Defaults:

- `--steps`: `state_cache,signal_ledger,strategy_evaluation,reminder`
- `--skip-existing`: enabled by default
- `--force`: rebuild selected outputs
- `--auto-calibrate`: run `calibrate_strategy_evidence` after replay
- `--calibration-date`: end date passed to calibration; defaults to replay end
  date
- `--update-latest`: allow replay to move `*_latest` pointers. By default,
  replay restores existing latest files so daily entry points are not moved to a
  historical date.

Report:

```text
outputs/replay_history/replay_history_START_END.json
```

The command checks that `d1_perspective_state` and `daily_bars` both have rows
for a date before processing it. Missing dates are recorded as
`missing_foundation_data` rather than failing the whole replay.
