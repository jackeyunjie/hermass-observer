#!/bin/bash
# Hermass Observer 早盘简报 — 隔夜外盘消息汇总
# 运行时间: 北京时间 08:00 (PDT 17:00)
# 内容: 隔夜美股/商品/外汇动态 + 当日A股预开盘提示

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PRODUCT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PRODUCT_DIR/.venv"
LOG_DIR="$PRODUCT_DIR/logs"
DATE_STR="$(date +%Y-%m-%d)"
YMD="${DATE_STR//-/}"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_DIR/morning_brief_${YMD}.log"
}

log "========================================"
log "Hermass 早盘简报开始 - ${DATE_STR}"
log "========================================"

# ── 构建简报内容 ──
log "生成早盘简报..."

BRIEF="Hermass Observer 早盘简报 — ${DATE_STR}

📊 隔夜市场动态
• 美股收盘: 请查看 Bloomberg/Reuters
• 商品: 黄金/原油/铜
• 外汇: 美元指数/离岸人民币

🇨🇳 A股预开盘提示
• 前日收盘状态: 查看 ${PRODUCT_DIR}/public/daily_research_brief_$(date -v-1d +%Y%m%d).html
• 三周期E/F池: 运行中

💡 操作建议
• 09:15 集合竞价前查看板块共振
• 09:30 开盘后关注资金流向

@Bot 市场怎么样 — 实时分析
@Bot 板块共振 — 热点追踪

Research-Only, 不构成投资建议"

# ── 发送邮件 ──
log "发送早盘邮件..."
export HERMASS_SMTP_USER="1300893414@qq.com"
export HERMASS_SMTP_PASS="dyhqeduaqsrnihag"
export HERMASS_REPORT_TO="3393639019@qq.com,447372703@qq.com"

# 使用 Python 发送纯文本邮件
"$VENV_DIR/bin/python" -c "
import os, smtplib, email.message
smtp = {
    'host': 'smtp.qq.com', 'port': 587,
    'user': os.environ['HERMASS_SMTP_USER'],
    'password': os.environ['HERMASS_SMTP_PASS'],
}
to = [t.strip() for t in os.environ['HERMASS_REPORT_TO'].split(',') if t.strip()]
msg = email.message.EmailMessage()
msg['Subject'] = 'Hermass 早盘简报 — ${DATE_STR}'
msg['From'] = smtp['user']
msg['To'] = ', '.join(to)
msg.set_content('''${BRIEF}''')
with smtplib.SMTP(smtp['host'], smtp['port']) as s:
    s.starttls(); s.login(smtp['user'], smtp['password'])
    s.send_message(msg)
print('邮件发送完成')
" 2>&1 | tail -1

# ── 飞书推送 ──
log "飞书推送早盘简报..."
LARK_CONFIG="$PRODUCT_DIR/config/platform/lark_app.yaml"
if [ -f "$LARK_CONFIG" ]; then
    CHAT_ID=$(grep -E '^\s*chat_id:' "$LARK_CONFIG" | head -1 | sed 's/.*chat_id:\s*"\?\([^"]*\)"\?.*/\1/')
    if [ -n "$CHAT_ID" ] && [ "$CHAT_ID" != "oc_xxx" ]; then
        if lark-cli im +messages-send --chat-id "$CHAT_ID" --text "$BRIEF" 2>&1 | tail -1; then
            log " 飞书推送完成"
        else
            log " 飞书推送失败（非致命）"
        fi
    else
        log " 飞书 chat_id 未配置，跳过推送"
    fi
fi

log "========================================"
log "早盘简报完成 - ${DATE_STR}"
log "========================================"
