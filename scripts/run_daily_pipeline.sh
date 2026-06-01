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

# 确保项目本地包可被 venv Python 导入
export PYTHONPATH="$PRODUCT_DIR:$RESEARCH_DIR${PYTHONPATH:+:$PYTHONPATH}"

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

# ── Step 10: 更新网站数据 ──
log "Step 10/10: 更新网站数据..."
UPLOAD_SCRIPT="$PRODUCT_DIR/scripts/upload_output_to_server.py"
if [ -f "$UPLOAD_SCRIPT" ]; then
    export HERMASS_UPLOAD_URL="${HERMASS_UPLOAD_URL:-http://8.130.125.201/api/admin/upload-data}"
    export HERMASS_UPLOAD_HOST="${HERMASS_UPLOAD_HOST:-console.supertrader.world}"
    DELTA_SCRIPT="$PRODUCT_DIR/scripts/build_foundation_delta.py"
    if [ -f "$DELTA_SCRIPT" ]; then
        if "$VENV_DIR/bin/python" "$DELTA_SCRIPT" --date "$DATE_STR" 2>&1 | while IFS= read -r line; do log "[website] $line"; done; then
            log " 网站 Foundation 增量包生成完成"
            if "$VENV_DIR/bin/python" "$UPLOAD_SCRIPT" --date "$YMD" --type foundation_delta 2>&1 | while IFS= read -r line; do log "[website] $line"; done; then
                log " 网站 Foundation 增量更新完成"
            else
                log " 网站 Foundation 增量更新失败（非致命）"
            fi
        else
            log " 网站 Foundation 增量包生成失败（非致命）"
        fi
    else
        log " 网站 Foundation 增量脚本不存在，跳过增量上传"
    fi
    if "$VENV_DIR/bin/python" "$UPLOAD_SCRIPT" --date "$YMD" --type snapshot 2>&1 | while IFS= read -r line; do log "[website] $line"; done; then
        log " 网站每日快照更新完成"
    else
        log " 网站每日快照更新失败（非致命）"
    fi
    if [ "${UPLOAD_FOUNDATION:-0}" = "1" ]; then
        if "$VENV_DIR/bin/python" "$UPLOAD_SCRIPT" --date "$YMD" --type foundation 2>&1 | while IFS= read -r line; do log "[website] $line"; done; then
            log " 网站 Foundation DB 更新完成"
        else
            log " 网站 Foundation DB 更新失败（非致命）"
        fi
    else
        log " 网站 Foundation DB 跳过（默认不上传 3.7G 大包；需要时设置 UPLOAD_FOUNDATION=1）"
    fi
else
    log " 网站上传脚本不存在，跳过"
fi

# ── 校验与标记 ──
log "Step 11: 输出校验..."

PIPELINE_OK=true
MARKER_DIR="$PRODUCT_DIR/outputs/.pipeline_markers"
mkdir -p "$MARKER_DIR"

_verify() {
    local label="$1" path="$2" type="$3"
    local ok=false
    case "$type" in
        dir)  [ -d "$path" ] && [ "$(ls -A "$path" 2>/dev/null | wc -l)" -gt 0 ] && ok=true ;;
        file) [ -f "$path" ] && [ -s "$path" ] && ok=true ;;
        db)   [ -f "$path" ] && [ "$(stat -f%z "$path" 2>/dev/null || stat -c%s "$path" 2>/dev/null || echo 0)" -gt 1024 ] && ok=true ;;
    esac
    if $ok; then
        log "  [OK] $label: $path"
    else
        log "  [MISS] $label: $path"
        PIPELINE_OK=false
    fi
}

_verify "Foundation DB"       "${PRODUCT_DIR}/outputs/p116_foundation_${YMD}"         dir
_verify "Foundation DuckDB"   "${PRODUCT_DIR}/outputs/p116_foundation_${YMD}/p116_foundation.duckdb" db
_verify "每日快照"            "${PRODUCT_DIR}/outputs/daily_snapshot.json"             file

# 非关键项（不存在不标记失败）
for d in strategy_signals unified_view market_phase industry_rotation; do
    path="${PRODUCT_DIR}/outputs/${d}"
    if [ -d "$path" ] && [ "$(ls -A "$path" 2>/dev/null | wc -l)" -gt 0 ]; then
        log "  [OK] $d: $path"
    else
        log "  [SKIP] $d: 目录不存在或为空"
    fi
done

if $PIPELINE_OK; then
    echo "$DATE_STR $(date '+%H:%M:%S')" > "$MARKER_DIR/pipeline_success_${YMD}"
    log "校验通过，标记文件已写入: $MARKER_DIR/pipeline_success_${YMD}"
else
    log "校验未通过，请检查上述 [MISS] 项"
fi

# ── Step Last: 产出清单 ──
log "Step Last: 产出清单..."

_outputs_manifest() {
    local total_files=0 total_bytes=0
    local paths=(
        "outputs/p116_foundation_${YMD}"
        "outputs/daily_snapshot.json"
        "outputs/daily_warning.json"
        "outputs/daily_research_brief"
        "outputs/daily_state_excel"
        "outputs/strategy_signals"
        "outputs/forward_observation"
        "public/daily_research_brief_${YMD}.html"
    )

    for rel in "${paths[@]}"; do
        local abs="$PRODUCT_DIR/$rel"
        if [ ! -e "$abs" ]; then
            echo "[PIPELINE_OUTPUTS] missing: $rel"
            continue
        fi

        local sz lines hash
        if [ -d "$abs" ]; then
            sz=$(du -sk "$abs" 2>/dev/null | awk '{print $1*1024}' || echo 0)
            lines="NA"
            hash=$(find "$abs" -type f -exec shasum -a 256 {} + 2>/dev/null | shasum -a 256 | cut -c1-8)
        else
            sz=$(stat -f%z "$abs" 2>/dev/null || stat -c%s "$abs" 2>/dev/null || echo 0)
            lines=$(wc -l < "$abs" 2>/dev/null || echo NA)
            hash=$(shasum -a 256 "$abs" 2>/dev/null | cut -c1-8 || echo N/A)
        fi

        printf '[PIPELINE_OUTPUTS] %-50s %10s %6s %s\n' "$rel" "$sz" "$lines" "$hash"
        total_files=$((total_files + 1))
        total_bytes=$((total_bytes + sz))
    done

    echo "[PIPELINE_OUTPUTS] total=${total_files} files, ${total_bytes} bytes"
}

_outputs_manifest | while IFS= read -r line; do
    log "$line"
done

# ── 流水线结束 ──
log "========================================"
log "流水线完成 - ${DATE_STR}"
log "Foundation DB: ${PRODUCT_DIR}/outputs/p116_foundation_${YMD}/p116_foundation.duckdb"
log "状态: $($PIPELINE_OK && echo 'SUCCESS' || echo 'INCOMPLETE')"
log "========================================" 
