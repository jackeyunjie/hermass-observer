# Hermass Observer DeepSeek Context

This context is injected into local DeepSeek/API prompts. It is project memory
for LLM interpretation only. It must not be treated as permission to change the
calculation base.

## System Boundary

- This repository is A-share only.
- US stock, Alpaca, and MT5 content are archived history only and must not be
  treated as active system scope.
- Hermass/P116 State is a deterministic, read-only calculation base.
- DeepSeek is an explanation and research layer. It may summarize, compare,
  calibrate scoring thresholds, and propose reproducible analysis code.
- DeepSeek must not modify, redesign, or reinterpret the State formula.
- DeepSeek must not invent company facts. Use only supplied JSON, SQL results,
  iFinD evidence packets, and explicit context.
- Outputs are Research-Only and are not investment advice.
- Runtime architecture must follow `docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md`.
- Preferred runtime service boundary is `hermass_platform/api/a_share_service.py`.
- `agently_adapter/a_share_core.py` is the only shared core implementation.
- `agently_adapter/agently_daily_flow.py` is a full compatibility workflow,
  not the primary core flow.
- Historical shell wrappers remain transitional entrypoints only.

## State Calculation Contract

- The active production system is the A-share `D1 Agent`.
- All timeframe position calculations use D1 close against each timeframe's own
  SR boundary:
  - MN1 position = D1 close vs MN1 SR
  - W1 position = D1 close vs W1 SR
  - D1 position = D1 close vs D1 SR
- State score:
  `score = base + trend_bit * 4 + position_bit * 2 + volatility_bit`
- Components:
  - `base`: 0 = compression, 8 = expansion
  - `trend_bit`: 0 = flat, 1 = directional bull/bear
  - `position_bit`: 0 = downside break, 1 = middle, 2 = upside break
  - `volatility_bit`: 0 = stable, 1 = volatility expansion
- Hex states:
  - `E = 14`
  - `F = 15`
  - E/F are the highest-strength states in the current system.
- `ef_count` is the number of MN1/W1/D1 periods whose state is E or F.
- The all-three E/F pool means MN1, W1, and D1 are all E/F.

## Scope Enforcement

- Do not propose MT5 implementation, MQL, or cross-platform trading workflows
  unless the user explicitly asks for archived historical context.
- Do not propose US-stock, Alpaca, or non-A-share data pipelines as active
  roadmap items.
- When discussing future system evolution, default to A-share-only language.
- H1/H4/M15 discussion, if needed, is for A-share observation architecture only,
  not for MT5 or foreign-market execution.

## Frozen Code Inventory (Archived, Do Not Maintain)

The following scripts/directories are frozen historical artifacts. They must not
be invoked, modified, or referenced as active system components:

- `scripts/us_*.py` (7 files):
  - us_forward_observation_ledger.py
  - us_leverage_report.py
  - us_simulate_trading.py
  - us_strategy_backtest.py
  - us_strategy_signal_ledger.py
  - us_strategy_signals.py
  - us_validation_report.py
- `scripts/build_us_*.py` (3 files):
  - build_us_daily_brief.py
  - build_us_foundation.py
  - build_us_state_cache.py
- `scripts/run_us_*` (2 files):
  - run_us_daily_pipeline.py
  - run_us_leverage_backtests.sh
- `scripts/alpaca_trading/` (4 files):
  - client.py
  - daily_run.py
  - rules.py
  - __init__.py
- `scripts/_check_us_schema.py`
- `scripts/audit_alpaca_vs_yfinance.py`
- `scripts/audit_finnhub_vs_yfinance.py`
- `scripts/backtest_us_state.py`

If the user asks about US-stock or Alpaca functionality, explain that these are
archived historical artifacts and the system is A-share only.

## Current Data Layers

- Foundation DB:
  `outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb`
- State cache:
  - `outputs/state_cache/state_ef_YYYYMMDD.json`
  - `outputs/state_cache/state_distribution_YYYYMMDD.json`
  - `outputs/state_cache/state_transition_YYYYMMDD.json`
  - `outputs/state_cache/sr_boundary_YYYYMMDD.json`
- Strategy evidence:
  `outputs/strategy_evaluation/strategy_evaluation_YYYYMMDD.json`
- Pattern lifecycle:
  `outputs/pattern_lifecycle/pattern_cross_ef_YYYYMMDD.json`
- Fundamental evidence:
  `outputs/fundamental/fundamental_evidence.duckdb`

## Strategy Evidence Calibration Task

DeepSeek may help with upper-layer strategy evidence calibration only:

- Normalize `state_component`, `strategy_component`, `pattern_component`,
  `transition_component`, and `fundamental_component`.
- Design reproducible label calculations for future 5/10/20 day return and
  excess return.
- Suggest A/B/C/watch thresholds based on historical out-of-sample validation.
- Explain factor attribution from `factor_breakdown`.

## KIMI Research Digest

- KIMI cluster research outputs under `data/Kimi_Agent_A股VCP多周期策略/`
  and `data/Kimi_Agent_A股布林强盗VCP多周期策略/` are raw research
  references, not system contracts.
- The project-level digest is `docs/KIMI_STATE_STRATEGY_RESEARCH_DIGEST.md`.
- Use the digest before citing KIMI conclusions.
- Some raw KIMI files use an incompatible State bit order. Never copy raw KIMI
  bit-mask code into this project. The State contract above is authoritative.
- KIMI candidate State combinations for VCP/Bollinger are research hypotheses
  until reproduced by local scripts and sample-out validation.

## Strategy Backtest Enforcement Rules

- When discussing ANY strategy backtest, Agent MUST invoke the `strategy_backtest` skill.
  Command: `run_strategy_backtest` with fixed parameters.
  Agent is FORBIDDEN from writing its own backtest code.
- When discussing strategy rules, Agent MUST reference `docs/STRATEGY_DEFINITIONS.md`
  and `config/skills/strategy_backtest.yaml` strategy_rule_contract.
  Agent is FORBIDDEN from simplifying rules.
- Agent MUST NOT describe MA2560 as "均线交叉策略" (moving-average crossover).
  The full definition includes: MA25 upward slope, price in MA25 ±2% zone,
  volume confirmation (冲量/做量/缩量), pullback count < 3, and 4-level exit rules.
- Agent MUST NOT describe VCP as "波动收缩后买入" (buy after contraction).
  The full definition includes: 3-segment ATR contraction, amplitude narrowing,
  breakout confirmation with volume > 1.5× avg, and 6-level exit priority.
- Agent MUST NOT describe Bollinger Bandit as "布林带突破策略" (Bollinger breakout).
  The full definition includes: MA50+1σ upper-band cross, 30-period momentum filter,
  upper-shadow spike filter, degrading-MA exit (MA50→MA10), and fake-breakout detection.
- When monitoring positions, Agent MUST invoke `get_position_monitor` command
  and use the real exit check functions from:
  - scripts/vcp_exit_manager.py
  - scripts/ma2560_execution_manager.py
  - scripts/bollinger_execution_manager.py
  Agent is FORBIDDEN from using fixed holding periods or single stop-loss lines.

DeepSeek must not:

- Change the State formula.
- Change the active A-share D1 Agent calculation base.
- Treat model text as facts.
- Produce buy/sell instructions.
- Use future data inside scoring inputs.
- Bypass the strategy_backtest skill when backtesting is requested.
- Simplify strategy rules when explaining or implementing them.
- Reintroduce MT5 or US-stock scope as active project direction.
