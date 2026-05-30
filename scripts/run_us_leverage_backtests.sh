#!/bin/bash
# Run 9 US strategy backtests (3 strategies × 3 leverage levels)
# Usage: bash scripts/run_us_leverage_backtests.sh

set -e
ROOT="/Users/lv111101/Documents/hermass-observer-product"
START="2023-01-01"
END="2025-12-30"
CAPITAL=1000000
MAX_POS=10
MIN_EF=2
OUT_DIR="$ROOT/outputs/us_stock/backtest"

mkdir -p "$OUT_DIR/logs"

run_backtest() {
    local strategy=$1
    local leverage=$2
    local logfile="$OUT_DIR/logs/${strategy}_lev${leverage}.log"
    echo "[$(date '+%H:%M:%S')] Starting $strategy @ ${leverage}x → $logfile"
    python3 "$ROOT/scripts/us_strategy_backtest.py" \
        --start-date "$START" \
        --end-date "$END" \
        --capital "$CAPITAL" \
        --max-positions "$MAX_POS" \
        --min-ef "$MIN_EF" \
        --strategy "$strategy" \
        --leverage "$leverage" \
        > "$logfile" 2>&1
    echo "[$(date '+%H:%M:%S')] Finished $strategy @ ${leverage}x"
}

# Run all 9 backtests in parallel
run_backtest vcp 1.0 &
run_backtest vcp 2.0 &
run_backtest vcp 3.0 &
run_backtest ma2560 1.0 &
run_backtest ma2560 2.0 &
run_backtest ma2560 3.0 &
run_backtest bollinger_bandit 1.0 &
run_backtest bollinger_bandit 2.0 &
run_backtest bollinger_bandit 3.0 &

wait
echo "[$(date '+%H:%M:%S')] All 9 backtests completed!"
