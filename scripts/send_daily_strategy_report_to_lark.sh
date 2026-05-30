#!/bin/bash
# Push Hermass daily strategy report to a configured Lark chat.
# Usage:
#   bash scripts/send_daily_strategy_report_to_lark.sh [YYYY-MM-DD]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PRODUCT_DIR="$(dirname "$SCRIPT_DIR")"
DATE_STR="${1:-$(date +%Y-%m-%d)}"
VENV_PY="$PRODUCT_DIR/.venv/bin/python"
LARK_CONFIG="$PRODUCT_DIR/config/platform/lark_app.yaml"

if [ ! -f "$LARK_CONFIG" ]; then
    echo "lark config not found: $LARK_CONFIG"
    exit 1
fi

CHAT_ID=$(grep -E '^\s*chat_id:' "$LARK_CONFIG" | head -1 | sed 's/.*chat_id:\s*"\?\([^"]*\)"\?.*/\1/')
WEBHOOK_URL=$(grep -E '^\s*webhook_url:' "$LARK_CONFIG" | head -1 | sed 's/.*webhook_url:\s*"\?\([^"]*\)"\?.*/\1/')

if [ -z "$CHAT_ID" ] && [ -z "$WEBHOOK_URL" ]; then
    echo "no chat_id or webhook_url configured in $LARK_CONFIG"
    exit 1
fi

ARGS=(--date "$DATE_STR")
if [ -n "$CHAT_ID" ]; then
    ARGS+=(--chat-id "$CHAT_ID")
fi
if [ -n "$WEBHOOK_URL" ]; then
    ARGS+=(--webhook-url "$WEBHOOK_URL")
fi

"$VENV_PY" -m scripts.notify.push_to_lark "${ARGS[@]}"
