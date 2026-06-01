#!/bin/bash
# Hermass 数据同步到生产服务器
# 职责：rsync outputs/ → 服务器，原子替换 + 校验 + 可观测
#
# 用法：
#   ./scripts/sync_outputs_to_server.sh --date 2026-06-01
#   ./scripts/sync_outputs_to_server.sh --date 2026-06-01 --verify-only
#
# 环境变量：
#   HERMASS_SYNC_SERVER  默认 root@8.130.125.201
#   HERMASS_SYNC_DEST    默认 /opt/hermass/outputs
#
# 退出码：
#   0  全部成功
#   1  预检失败（SSH 不通等）
#   2  部分成功（非关键目录失败）
#   3  关键失败（Foundation DB 同步失败）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PRODUCT_DIR="$(dirname "$SCRIPT_DIR")"

SERVER="${HERMASS_SYNC_SERVER:-root@8.130.125.201}"
DEST="${HERMASS_SYNC_DEST:-/opt/hermass/outputs}"
INCOMING="$DEST/_incoming"

DATE_STR=""
VERIFY_ONLY=false

usage() {
    echo "用法: $0 --date YYYY-MM-DD [--verify-only]"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --date) DATE_STR="$2"; shift 2 ;;
        --verify-only) VERIFY_ONLY=true; shift ;;
        *) usage ;;
    esac
done

if [ -z "$DATE_STR" ]; then
    echo "[ERROR] 缺少 --date 参数"
    usage
fi

YMD="${DATE_STR//-/}"
LOG_TAG="[sync_outputs $DATE_STR]"

log() { echo "$LOG_TAG $(date '+%H:%M:%S') $*"; }
warn() { echo "$LOG_TAG $(date '+%H:%M:%S') [WARN] $*" >&2; }
err() { echo "$LOG_TAG $(date '+%H:%M:%S') [ERROR] $*" >&2; }

# ══════════════════════════════════════════════════════════════════════════════
# 预检
# ══════════════════════════════════════════════════════════════════════════════

log "=== 开始数据同步 ==="
log "目标: ${SERVER}:${DEST}"

log "预检: SSH 连通性..."
if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$SERVER" true 2>/dev/null; then
    err "SSH 连通性测试失败，请确认免密登录已配置"
    err "手动验证: ssh -o BatchMode=yes $SERVER true"
    exit 1
fi
log "SSH 连通性 OK"

if $VERIFY_ONLY; then
    log "=== 仅校验模式 ==="
fi

# ══════════════════════════════════════════════════════════════════════════════
# 同步函数
# ══════════════════════════════════════════════════════════════════════════════

CRITICAL_FAILURES=0
PARTIAL_FAILURES=0

sync_dir_atomic() {
    local label="$1"
    local local_path="$2"
    local remote_rel="$3"
    local remote_final="${DEST}/${remote_rel}"
    local remote_tmp="${INCOMING}/${remote_rel}"

    if [ ! -e "$local_path" ]; then
        warn "跳过 ${label}: 本地路径不存在 ${local_path}"
        return 0
    fi

    log "同步 ${label}: ${local_path} → ${remote_rel}"

    # 确保远程临时目录存在
    ssh "$SERVER" "mkdir -p $(dirname "$remote_tmp")" || true

    # rsync 到临时目录（不加 --delete，避免清空）
    if rsync -avz --timeout=30 \
        "$local_path/" \
        "${SERVER}:${remote_tmp}/" 2>&1 | tail -1; then
        :
    else
        local rc=$?
        err "${label} rsync 失败，退出码=${rc}"
        return 1
    fi

    # 校验：检查关键文件存在且非空
    if ! ssh "$SERVER" "test -s ${remote_tmp}/$(basename "$local_path")* 2>/dev/null || test -n \"\$(ls -A ${remote_tmp}/ 2>/dev/null)\""; then
        err "${label} 校验失败: 临时目录为空"
        return 1
    fi

    # 原子替换
    ssh "$SERVER" "
        if [ -d '${remote_final}' ]; then
            rm -rf '${remote_final}.prev' 2>/dev/null || true
            mv '${remote_final}' '${remote_final}.prev' 2>/dev/null || true
        fi
        mv '${remote_tmp}' '${remote_final}'
    " || {
        err "${label} 原子替换失败"
        return 1
    }

    log "${label} 同步完成 ✓"
    return 0
}

sync_file_atomic() {
    local label="$1"
    local local_file="$2"
    local remote_rel="$3"
    local remote_final="${DEST}/${remote_rel}"
    local remote_tmp="${INCOMING}/${remote_rel}"

    if [ ! -f "$local_file" ]; then
        warn "跳过 ${label}: 本地文件不存在 ${local_file}"
        return 0
    fi

    local local_size
    local_size=$(stat -f%z "$local_file" 2>/dev/null || stat -c%s "$local_file" 2>/dev/null || echo 0)
    if [ "$local_size" -eq 0 ]; then
        warn "跳过 ${label}: 本地文件大小为 0"
        return 0
    fi

    log "同步 ${label}: ${local_file} (${local_size} bytes)"

    ssh "$SERVER" "mkdir -p ${INCOMING}" || true

    if rsync -avz --timeout=30 "$local_file" "${SERVER}:${remote_tmp}"; then
        :
    else
        local rc=$?
        err "${label} rsync 失败，退出码=${rc}"
        return 1
    fi

    local remote_size
    remote_size=$(ssh "$SERVER" "stat -c%s ${remote_tmp} 2>/dev/null || echo 0")
    if [ "$remote_size" -ne "$local_size" ]; then
        err "${label} 校验失败: 本地=${local_size} 远程=${remote_size}"
        return 1
    fi

    ssh "$SERVER" "mv ${remote_tmp} ${remote_final}"

    log "${label} 同步完成 ✓ (${remote_size} bytes)"
    return 0
}

# ══════════════════════════════════════════════════════════════════════════════
# 执行同步
# ══════════════════════════════════════════════════════════════════════════════

if $VERIFY_ONLY; then
    log "验证 Foundation DB 远程存在..."
    if ssh "$SERVER" "test -f ${DEST}/p116_foundation_${YMD}/p116_foundation.duckdb"; then
        local db_size
        db_size=$(ssh "$SERVER" "stat -c%s ${DEST}/p116_foundation_${YMD}/p116_foundation.duckdb 2>/dev/null || echo 0")
        log "Foundation DB 存在 (${db_size} bytes)"
    else
        err "Foundation DB 不存在"
        exit 1
    fi
    log "=== 校验完成 ==="
    exit 0
fi

# 1) Foundation DB（关键）
if ! sync_dir_atomic "Foundation DB" \
    "${PRODUCT_DIR}/outputs/p116_foundation_${YMD}" \
    "p116_foundation_${YMD}"; then
    CRITICAL_FAILURES=$((CRITICAL_FAILURES + 1))
fi

# 2) 每日快照
sync_file_atomic "每日快照" \
    "${PRODUCT_DIR}/outputs/daily_snapshot.json" \
    "daily_snapshot.json" \
    || PARTIAL_FAILURES=$((PARTIAL_FAILURES + 1))

# 3) 策略信号
sync_dir_atomic "策略信号" \
    "${PRODUCT_DIR}/outputs/strategy_signals" \
    "strategy_signals" \
    || PARTIAL_FAILURES=$((PARTIAL_FAILURES + 1))

# 4) 统一视图
sync_dir_atomic "统一视图" \
    "${PRODUCT_DIR}/outputs/unified_view" \
    "unified_view" \
    || PARTIAL_FAILURES=$((PARTIAL_FAILURES + 1))

# 5) 市场阶段
if [ -d "${PRODUCT_DIR}/outputs/market_phase" ]; then
    sync_dir_atomic "市场阶段" \
        "${PRODUCT_DIR}/outputs/market_phase" \
        "market_phase" \
        || PARTIAL_FAILURES=$((PARTIAL_FAILURES + 1))
fi

# 6) 行业轮动
if [ -d "${PRODUCT_DIR}/outputs/industry_rotation" ]; then
    sync_dir_atomic "行业轮动" \
        "${PRODUCT_DIR}/outputs/industry_rotation" \
        "industry_rotation" \
        || PARTIAL_FAILURES=$((PARTIAL_FAILURES + 1))
fi

# 清理临时目录
ssh "$SERVER" "rm -rf ${INCOMING}" 2>/dev/null || true

# ══════════════════════════════════════════════════════════════════════════════
# 结果
# ══════════════════════════════════════════════════════════════════════════════

log "=== 同步完成 ==="
log "关键失败: ${CRITICAL_FAILURES}  局部失败: ${PARTIAL_FAILURES}"

if [ "$CRITICAL_FAILURES" -gt 0 ]; then
    err "Foundation DB 同步失败，需人工介入"
    exit 3
fi

if [ "$PARTIAL_FAILURES" -gt 0 ]; then
    warn "部分非关键目录同步失败"
    exit 2
fi

exit 0
