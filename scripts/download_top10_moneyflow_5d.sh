#!/usr/bin/env bash
set -euo pipefail

RESEARCH_ROOT="/Users/lv111101/Documents/hongrun-chaos-trading-system"
PRODUCT_ROOT="/Users/lv111101/Documents/hermass-observer-product"
DATES=(2026-05-14 2026-05-15 2026-05-18 2026-05-19 2026-05-20)
CODES=(688069 601991 300054 688112 600500 002443 603773 001378 300666 002887)

if [[ -z "${BLACKWOLF_TOKEN:-}" ]]; then
  echo "BLACKWOLF_TOKEN is not set in this shell" >&2
  exit 2
fi

mkdir -p "$PRODUCT_ROOT/data/p116_top10_moneyflow_5d"
mkdir -p "$PRODUCT_ROOT/reports/p112_capital_flow_evidence_layer/p116_top10_moneyflow_5d"

for date in "${DATES[@]}"; do
  code_list="$PRODUCT_ROOT/data/p116_top10_moneyflow_5d/code_list_${date//-/}.csv"
  {
    echo "code"
    for code in "${CODES[@]}"; do
      echo "$code"
    done
  } > "$code_list"

  "$RESEARCH_ROOT/.venv/bin/python" "$RESEARCH_ROOT/scripts/download_blackwolf_ashare_moneyflow_api.py" \
    --date "$date" \
    --code-list "$code_list" \
    --out-dir "$PRODUCT_ROOT/data/p116_top10_moneyflow_5d" \
    --summary "$PRODUCT_ROOT/reports/p112_capital_flow_evidence_layer/p116_top10_moneyflow_5d/summary_${date//-/}.json" \
    --min-rows 10 \
    --sleep-seconds 0.05
done

echo "done: $PRODUCT_ROOT/data/p116_top10_moneyflow_5d"
