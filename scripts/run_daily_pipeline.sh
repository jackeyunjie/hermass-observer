#!/bin/bash
# Hermass Observer 每日自动化数据流水线
# 运行时间: 每个交易日 15:15 CST (07:15 UTC)
# Crontab: 15 7 * * 1-5 /path/to/scripts/run_daily_pipeline.sh
# 用法: cron 调用或手动执行 ./scripts/run_daily_pipeline.sh [YYYY-MM-DD]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PRODUCT_DIR="$(dirname "$SCRIPT_DIR")"
RESEARCH_DIR="/Users/lv111101/Documents/hongrun-chaos-trading-system"
VENV_DIR="$PRODUCT_DIR/.venv"
LOG_DIR="$PRODUCT_DIR/logs"
DATE_STR="${1:-$(date +%Y-%m-%d)}"
YMD="${DATE_STR//-/}"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_DIR/daily_pipeline_${YMD}.log"
}

log "========================================"
log "Hermass 每日流水线开始 - ${DATE_STR}"
log "========================================"

# ── Step 1: 下载日线数据 ──
log "Step 1/8: 下载日线数据..."
PREV_DATE=$(date -j -v-1d -f "%Y-%m-%d" "$DATE_STR" "+%Y-%m-%d" 2>/dev/null || date -d "yesterday" "+%Y-%m-%d")

if "$VENV_DIR/bin/python" "$PRODUCT_DIR/blackwolf_actions/download_daily.py" \
    --date "$DATE_STR" --base-date "$PREV_DATE" 2>&1 | tail -1; then
    log " 日线下载完成"
else
    log " 日线下载跳过（使用已有数据）"
fi

# ── Step 2: 构建 Raw DB ──
log "Step 2/8: 构建 Raw DB..."
RAW_DB="$RESEARCH_DIR/outputs/p108_blackwolf_ashare_daily_raw_${YMD}/p108_blackwolf_ashare_daily_raw.duckdb"
if [ ! -f "$RAW_DB" ]; then
    mkdir -p "$(dirname "$RAW_DB")"
    "$VENV_DIR/bin/python" "$PRODUCT_DIR/agently_adapter/stockpool_daily_runner.py" \
        build_raw_db --date "$DATE_STR" 2>&1 | tail -1
    log " Raw DB 构建完成"
else
    log " Raw DB 已存在，跳过"
fi

# ── Step 3: 构建 Foundation DB ──
log "Step 3/8: 构建 Foundation DB..."
FOUNDATION_DB="$PRODUCT_DIR/outputs/p116_foundation_${YMD}/p116_foundation.duckdb"
if [ ! -f "$FOUNDATION_DB" ]; then
    "$VENV_DIR/bin/python" "$PRODUCT_DIR/scripts/build_p116_foundation.py" \
        --date "$DATE_STR" --raw-db "$RAW_DB" 2>&1 | tail -1
    log " Foundation DB 构建完成"
else
    log " Foundation DB 已存在，跳过"
fi

# ── Step 4: 策略信号账本 ──
log "Step 4/8: 构建策略信号账本..."
if "$VENV_DIR/bin/python" "$PRODUCT_DIR/scripts/strategy_signal_ledger.py" \
    --date "$DATE_STR" 2>&1 | tail -1; then
    log " 策略信号账本生成完成"
else
    log " 策略信号账本生成失败（非致命）"
fi

# ── Step 5: 策略提醒 ──
log "Step 5/8: 生成策略提醒..."
if "$VENV_DIR/bin/python" "$PRODUCT_DIR/scripts/strategy_reminder_brief.py" \
    --date "$DATE_STR" 2>&1 | tail -1; then
    log " 策略提醒生成完成"
else
    log " 策略提醒生成跳过（非致命）"
fi

# ── Step 6: 前向观察账本 ──
log "Step 6/8: 更新前向观察账本..."
if "$VENV_DIR/bin/python" "$PRODUCT_DIR/scripts/forward_observation_ledger.py" \
    --date "$DATE_STR" 2>&1 | tail -1; then
    log " 前向观察更新完成"
else
    log " 前向观察更新失败（非致命）"
fi

# ── Step 7: 每日快照 ──
log "Step 7/8: 构建每日快照..."
if "$VENV_DIR/bin/python" "$PRODUCT_DIR/scripts/build_daily_snapshot.py" \
    --date "$DATE_STR" 2>&1 | tail -1; then
    log " 每日快照完成"
else
    log " 每日快照构建失败（非致命）"
fi

# ── Step 7.5: 每日预警 ──
log "Step 7.5/9: 生成每日预警..."
if "$VENV_DIR/bin/python" "$PRODUCT_DIR/scripts/build_daily_warning.py" \
    --date "$DATE_STR" 2>&1 | tail -1; then
    log " 每日预警完成"
else
    log " 每日预警跳过（非致命）"
fi

# ── Step 8: 生成Excel并发送邮件 ──
log "Step 9/10: 生成Excel并发送邮件..."
export HERMASS_SMTP_USER="1300893414@qq.com"
export HERMASS_SMTP_PASS="dyhqeduaqsrnihag"
export HERMASS_REPORT_TO="3393639019@qq.com,447372703@qq.com"

if "$VENV_DIR/bin/python" "$PRODUCT_DIR/scripts/send_daily_report.py" 2>&1 | tail -1; then
    log " 邮件发送完成"
else
    log " 邮件发送失败（非致命）"
fi

# ── Step 9: 飞书推送 (可选) ──
log "Step 10: 飞书推送每日摘要..."
LARK_CONFIG="$PRODUCT_DIR/config/platform/lark_app.yaml"
if [ -f "$LARK_CONFIG" ]; then
    # 尝试读取配置的 chat_id
    CHAT_ID=$(grep -E '^\s*chat_id:' "$LARK_CONFIG" | head -1 | sed 's/.*chat_id:\s*"\?\([^"]*\)"\?.*/\1/')
    if [ -n "$CHAT_ID" ] && [ "$CHAT_ID" != "oc_xxx" ]; then
        # 构建简洁的每日摘要
        SUMMARY="Hermass Observer 每日流水线完成 - ${DATE_STR}
Foundation DB: ${FOUNDATION_DB}

可通过以下方式查看详情：
• 本地 HTML: public/daily_research_brief_${YMD}.html
• 邮件已发送至: ${HERMASS_REPORT_TO}

@Bot 市场怎么样  — 查看市场分析
@Bot 板块共振    — 查看板块信号"

        if lark-cli im +messages-send --chat-id "$CHAT_ID" --text "$SUMMARY" 2>&1 | tail -1; then
            log " 飞书推送完成"
        else
            log " 飞书推送失败（非致命）"
        fi
    else
        log " 飞书 chat_id 未配置，跳过推送"
    fi
else
    log " 飞书配置未找到，跳过推送"
fi

log "========================================"
log "流水线完成 - ${DATE_STR}"
log "Foundation DB: $FOUNDATION_DB"
log "========================================"
