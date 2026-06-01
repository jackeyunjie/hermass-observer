#!/bin/bash
# Hermass Observer 部署脚本
# 设计运行环境：服务器 /opt/hermass（或 HERMASS_DEPLOY_DIR 指定）
#
# 用法:
#   bash scripts/deploy.sh              # 默认：git pull + 编译 + 重启 + 冒烟
#   bash scripts/deploy.sh /src/path    # 从指定路径 rsync 同步后部署
#   bash scripts/deploy.sh --help       # 打印用法
#
# 环境变量:
#   HERMASS_DEPLOY_DIR    部署目标目录（默认：/opt/hermass）
#   HERMASS_SERVICE       systemd 服务名（默认：hermass-console）
#   HERMASS_SMOKE_URL     冒烟测试 URL（默认：http://localhost:8020/）
#
# 退出码:
#   0  成功
#   3  同步失败
#   4  语法校验失败
#   5  重启失败
#   6  冒烟失败
#   2  参数错误
#   7  环境错误（不在服务器或缺少必要命令）

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
用法: bash scripts/deploy.sh [选项] [rsync源路径]

选项:
  --help, -h    打印本帮助信息

参数:
  rsync源路径   可选。若提供，先执行 rsync 同步到 HERMASS_DEPLOY_DIR，
                再执行编译+重启+冒烟。
                若省略，默认在 HERMASS_DEPLOY_DIR 内执行 git pull。

环境变量:
  HERMASS_DEPLOY_DIR   部署目标目录（默认: /opt/hermass）
  HERMASS_SERVICE      systemd 服务名（默认: hermass-console）
  HERMASS_SMOKE_URL    冒烟测试 URL（默认: http://localhost:8020/）

示例:
  bash scripts/deploy.sh
  bash scripts/deploy.sh /backup/hermass-staging/

退出码:
  0  部署成功
  3  同步失败（rsync 或 git pull）
  4  语法校验失败（py_compile）
  5  重启失败（systemctl restart）
  6  冒烟失败（curl 首页非 200）
  2  参数错误
  7  环境错误（不在服务器或缺少必要命令）

注意:
  本脚本应在服务器上直接执行，不要在本地 macOS 上运行。
  若 systemctl 不可用，脚本会拒绝执行。
EOF
}

if [ $# -ge 1 ] && { [ "$1" = "--help" ] || [ "$1" = "-h" ]; }; then
    print_help
    exit 0
fi

# ── 环境检查 ───────────────────────────────────────────────────────
log() {
    echo "[deploy] $(date '+%H:%M:%S') $*"
}

fail_with_context() {
    local code="$1"
    local msg="$2"
    log "========================================"
    log "部署失败: $msg"
    log "最后成功步骤: $LAST_OK_STEP"
    log "========================================"
    exit "$code"
}

# 检查必要命令
for cmd in git python3 curl; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        fail_with_context 7 "缺少必要命令: $cmd"
    fi
done

# 检查 systemctl（服务器环境标志）
if ! command -v systemctl >/dev/null 2>&1; then
    fail_with_context 7 "systemctl 不可用。本脚本应在服务器（systemd 环境）上运行，不要在本地 macOS 上直接执行。"
fi

# 检查目标目录
if [ ! -d "$DEPLOY_DIR" ]; then
    fail_with_context 7 "部署目录不存在: $DEPLOY_DIR"
fi

cd "$DEPLOY_DIR"

# 检查是否为 git 仓库
if [ ! -d ".git" ]; then
    fail_with_context 7 "$DEPLOY_DIR 不是 git 仓库"
fi

# ── Step 1: 同步代码 ───────────────────────────────────────────────
log "Step 1/5: 同步代码..."

RSYNC_SRC="${1:-}"

if [ -n "$RSYNC_SRC" ]; then
    # rsync 模式
    if ! command -v rsync >/dev/null 2>&1; then
        fail_with_context 7 "指定了 rsync 源路径，但 rsync 命令不可用"
    fi
    if [ ! -d "$RSYNC_SRC" ]; then
        fail_with_context 3 "rsync 源路径不存在: $RSYNC_SRC"
    fi
    # 排除 .venv / node_modules / outputs / .git 等大目录
    if rsync -a --delete \
        --exclude='.venv/' \
        --exclude='node_modules/' \
        --exclude='__pycache__/' \
        --exclude='outputs/' \
        --exclude='.git/' \
        --exclude='*.pyc' \
        --exclude='.DS_Store' \
        "$RSYNC_SRC" "$DEPLOY_DIR/"; then
        LAST_OK_STEP="同步代码（rsync）"
        log "rsync 完成: $RSYNC_SRC -> $DEPLOY_DIR"
    else
        fail_with_context 3 "rsync 失败: $RSYNC_SRC -> $DEPLOY_DIR"
    fi
else
    # git pull 模式
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    log "当前分支: $CURRENT_BRANCH"
    if git pull --ff-only 2>&1; then
        LAST_OK_STEP="同步代码（git pull）"
        NEW_COMMIT=$(git rev-parse --short HEAD)
        log "git pull 完成，当前 commit: $NEW_COMMIT"
    else
        fail_with_context 3 "git pull 失败（可能存在本地冲突，请人工处理）"
    fi
fi

# ── Step 2: 语法校验 ───────────────────────────────────────────────
log "Step 2/5: 语法校验（py_compile）..."

COMPILE_ERRORS=""
# 编译关键入口文件
for pyfile in web/main.py agently_adapter/qa_entry.py; do
    if [ -f "$pyfile" ]; then
        if ! python3 -m py_compile "$pyfile" 2>&1; then
            COMPILE_ERRORS="${COMPILE_ERRORS}\n  - $pyfile"
        fi
    fi
done

if [ -n "$COMPILE_ERRORS" ]; then
    fail_with_context 4 "py_compile 发现语法错误:$COMPILE_ERRORS"
fi

LAST_OK_STEP="语法校验"
log "py_compile 通过"

# ── Step 3: 重启服务 ───────────────────────────────────────────────
log "Step 3/5: 重启服务（$SERVICE_NAME）..."

if ! sudo systemctl restart "$SERVICE_NAME" 2>&1; then
    fail_with_context 5 "systemctl restart $SERVICE_NAME 失败"
fi

LAST_OK_STEP="重启服务"
log "restart 命令已发出"

# ── Step 4: 服务状态检查 ───────────────────────────────────────────
log "Step 4/5: 检查服务状态..."

sleep 2
STATUS_OUTPUT=$(systemctl status "$SERVICE_NAME" --no-pager 2>&1 || true)

if echo "$STATUS_OUTPUT" | grep -q "active (running)"; then
    LAST_OK_STEP="服务状态检查"
    log "服务状态: active (running)"
else
    log "警告: 服务状态未显示 active (running)"
    log "$STATUS_OUTPUT"
    # 不立即失败，继续冒烟
fi

# ── Step 5: 冒烟测试 ───────────────────────────────────────────────
log "Step 5/5: 冒烟测试（curl $SMOKE_URL）..."

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$SMOKE_URL" 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    LAST_OK_STEP="冒烟测试"
    log "冒烟通过: HTTP $HTTP_CODE"
else
    fail_with_context 6 "冒烟失败: HTTP $HTTP_CODE（期望 200）"
fi

# ── 完成 ───────────────────────────────────────────────────────────
log "========================================"
log "部署完成 ✅"
log "目录: $DEPLOY_DIR"
log "服务: $SERVICE_NAME"
log "HTTP: $HTTP_CODE"
log "========================================"

exit 0
