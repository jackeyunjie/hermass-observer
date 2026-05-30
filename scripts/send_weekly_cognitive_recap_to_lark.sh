#!/bin/bash
# Push weekly cognitive recap to configured Lark chat.

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

MESSAGE="$("$VENV_PY" "$PRODUCT_DIR/scripts/build_weekly_cognitive_recap.py" --date "$DATE_STR")"

if [ -z "$CHAT_ID" ] && [ -z "$WEBHOOK_URL" ]; then
    echo "no chat_id or webhook_url configured in $LARK_CONFIG"
    exit 1
fi

if [ -n "$WEBHOOK_URL" ]; then
    lark-cli im +send --webhook "$WEBHOOK_URL" --text "$MESSAGE"
else
    lark-cli im +send --chat-id "$CHAT_ID" --text "$MESSAGE"
fi
