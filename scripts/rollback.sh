#!/bin/bash
# Hermass Observer 回滚脚本
# 设计运行环境：服务器 /opt/hermass（或 HERMASS_DEPLOY_DIR 指定）
#
# 用法:
#   bash scripts/rollback.sh              # 回退到上一个 commit + 重启 + 冒烟
#   bash scripts/rollback.sh --help       # 打印用法
#
# 环境变量:
#   HERMASS_DEPLOY_DIR    部署目标目录（默认：/opt/hermass）
#   HERMASS_SERVICE       systemd 服务名（默认：hermass-console）
#   HERMASS_SMOKE_URL     冒烟测试 URL（默认：http://localhost:8020/）
#
# 退出码:
#   0  回滚成功
#   7  回滚失败（git 或环境错误）
#   8  冒烟失败
#   2  参数错误

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PRODUCT_DIR="$(dirname "$SCRIPT_DIR")"

# ── 默认值 ─────────────────────────────────────────────────────────
DEPLOY_DIR="${HERMASS_DEPLOY_DIR:-/opt/hermass}"
SERVICE_NAME="${HERMASS_SERVICE:-hermass-console}"
SMOKE_URL="${HERMASS_SMOKE_URL:-http://localhost:8020/}"

LAST_OK_STEP="初始化"

# ── 帮助 ───────────────────────────────────────────────────────────
print_help() {
    cat << 'EOF'
用法: bash scripts/rollback.sh [选项]

选项:
  --help, -h    打印本帮助信息

流程:
  1. 保存当前未提交变更（git stash）
  2. 回退到上一个 commit（git reset --hard HEAD~1）
  3. 重启服务（systemctl restart）
  4. 冒烟测试（curl 首页）

环境变量:
  HERMASS_DEPLOY_DIR   部署目标目录（默认: /opt/hermass）
  HERMASS_SERVICE      systemd 服务名（默认: hermass-console）
  HERMASS_SMOKE_URL    冒烟测试 URL（默认: http://localhost:8020/）

退出码:
  0  回滚成功
  7  回滚失败（git 或环境错误）
  8  冒烟失败（curl 首页非 200）
  2  参数错误

注意:
  本脚本应在服务器上直接执行，不要在本地 macOS 上运行。
  回滚会执行 git reset --hard，未提交的变更会先 stash。
EOF
}

if [ $# -ge 1 ] && { [ "$1" = "--help" ] || [ "$1" = "-h" ]; }; then
    print_help
    exit 0
fi

# ── 环境检查 ───────────────────────────────────────────────────────
log() {
    echo "[rollback] $(date '+%H:%M:%S') $*"
}

fail_with_context() {
    local code="$1"
    local msg="$2"
    log "========================================"
    log "回滚失败: $msg"
    log "最后成功步骤: $LAST_OK_STEP"
    log "========================================"
    exit "$code"
}

for cmd in git python3 curl; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        fail_with_context 7 "缺少必要命令: $cmd"
    fi
done

if ! command -v systemctl >/dev/null 2>&1; then
    fail_with_context 7 "systemctl 不可用。本脚本应在服务器（systemd 环境）上运行，不要在本地 macOS 上直接执行。"
fi

if [ ! -d "$DEPLOY_DIR" ]; then
    fail_with_context 7 "部署目录不存在: $DEPLOY_DIR"
fi

cd "$DEPLOY_DIR"

if [ ! -d ".git" ]; then
    fail_with_context 7 "$DEPLOY_DIR 不是 git 仓库"
fi

# ── Step 1: 保存当前变更 ───────────────────────────────────────────
log "Step 1/4: 保存当前未提交变更..."

HAS_UNCOMMITTED=false
if ! git diff --quiet HEAD 2>/dev/null || ! git diff --cached --quiet HEAD 2>/dev/null; then
    HAS_UNCOMMITTED=true
    STASH_MSG="rollback-auto-$(date +%Y%m%d-%H%M%S)"
    if git stash push -m "$STASH_MSG" 2>&1; then
        log "已 stash: $STASH_MSG"
    else
        fail_with_context 7 "git stash 失败"
    fi
fi

# ── Step 2: 回退代码 ───────────────────────────────────────────────
log "Step 2/4: 回退代码..."

PREV_COMMIT=$(git rev-parse --short HEAD)
PREV_MSG=$(git log -1 --pretty=format:"%s")

log "当前 commit: $PREV_COMMIT ($PREV_MSG)"

# 检查是否有上一个 commit
if git rev-parse HEAD~1 >/dev/null 2>&1; then
    if git reset --hard HEAD~1 2>&1; then
        LAST_OK_STEP="回退代码"
        NEW_COMMIT=$(git rev-parse --short HEAD)
        NEW_MSG=$(git log -1 --pretty=format:"%s")
        log "已回退到: $NEW_COMMIT ($NEW_MSG)"
    else
        fail_with_context 7 "git reset --hard HEAD~1 失败"
    fi
else
    fail_with_context 7 "没有上一个 commit 可供回退"
fi

# ── Step 3: 重启服务 ───────────────────────────────────────────────
log "Step 3/4: 重启服务（$SERVICE_NAME）..."

if ! sudo systemctl restart "$SERVICE_NAME" 2>&1; then
    fail_with_context 7 "systemctl restart $SERVICE_NAME 失败"
fi

LAST_OK_STEP="重启服务"
log "restart 命令已发出"

sleep 2

# ── Step 4: 冒烟测试 ───────────────────────────────────────────────
log "Step 4/4: 冒烟测试（curl $SMOKE_URL）..."

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$SMOKE_URL" 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    LAST_OK_STEP="冒烟测试"
    log "冒烟通过: HTTP $HTTP_CODE"
else
    fail_with_context 8 "冒烟失败: HTTP $HTTP_CODE（期望 200）"
fi

# ── 完成 ───────────────────────────────────────────────────────────
log "========================================"
log "回滚完成 ✅"
log "目录: $DEPLOY_DIR"
log "服务: $SERVICE_NAME"
log "HTTP: $HTTP_CODE"
if $HAS_UNCOMMITTED; then
    log "提示: 回滚前存在未提交变更，已自动 stash，可通过 'git stash list' 查看"
fi
log "========================================"

exit 0
