# Hermass Observer DeepSeek Context

This context is injected into local DeepSeek/API prompts. It is project memory
for LLM interpretation only. It must not be treated as permission to change the
calculation base.

## System Boundary

- Hermass/P116 State is a deterministic, read-only calculation base.
- DeepSeek is an explanation and research layer. It may summarize, compare,
  calibrate scoring thresholds, and propose reproducible analysis code.
- DeepSeek must not modify, redesign, or reinterpret the State formula.
- DeepSeek must not invent company facts. Use only supplied JSON, SQL results,
  iFinD evidence packets, and explicit context.
- Outputs are Research-Only and are not investment advice.

## State Calculation Contract

- D1 perspective is mandatory.
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

DeepSeek must not:

- Change the State formula.
- Change D1 perspective.
- Treat model text as facts.
- Produce buy/sell instructions.
- Use future data inside scoring inputs.
