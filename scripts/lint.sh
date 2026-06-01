#!/bin/bash
# Hermass Observer Lint 入口脚本
# 用法:
#   bash scripts/lint.sh check [targets...]   # 静态检查 + 格式校验，不动文件
#   bash scripts/lint.sh format [targets...]  # 自动格式化 Python 文件
#   bash scripts/lint.sh help                 # 打印用法
#
# targets 参数: 以空格分隔的目录/文件路径（默认覆盖全项目 Python 文件）
#
# 示例:
#   bash scripts/lint.sh check
#   bash scripts/lint.sh check scripts/ hermass_platform/
#   bash scripts/lint.sh format scripts/
#
# 依赖: .venv/bin/ruff
# 退出码: 0=通过, 9=lint 失败, 2=参数错误
#
# ─── 注意事项 ───
#   - 开始前自动安装 ruff（若不存在）
#   - 行宽限制 110

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PRODUCT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PRODUCT_DIR"

# ── 帮助 ────────────────────────────────────────────────────
print_help() {
    cat << 'EOF'
用法: bash scripts/lint.sh <check|format|help> [targets...]

targets 为以空格分隔的目录或 glob，默认覆盖全项目 Python 目录:
  scripts/ hermass_platform/ agently_adapter/ web/ tests/

示例:
  bash scripts/lint.sh check
  bash scripts/lint.sh format scripts/ web/ agently_adapter/ tests/

退出码: 0=通过, 9=lint 失败, 2=参数错误
EOF
}

if [ $# -ge 1 ] && { [ "$1" = "help" ] || [ "$1" = "--help" ] || [ "$1" = "-h" ]; }; then
    print_help
    exit 0
fi

# ── 参数校验 ────────────────────────────────────────────────
if [ $# -eq 0 ]; then
    echo "用法: bash scripts/lint.sh <check|format|help> [targets...]"
    exit 2
fi

# ── 确保 ruff 可用 ─────────────────────────────────────────
RUFF_BIN=".venv/bin/ruff"
if [ ! -x "$RUFF_BIN" ]; then
    echo "[lint] ruff 未安装，正在 pip install..."
    .venv/bin/pip install ruff -q
fi

RUFF_ARGS="--line-length 110 --exclude .venv --exclude '__pycache__' --exclude '*.sh'"
export PYTHONPATH="$PRODUCT_DIR:/Users/lv111101/Documents/hongrun-chaos-trading-system${PYTHONPATH:+:$PYTHONPATH}"

# ── 模式路由 ────────────────────────────────────────────────
case "$1" in
check)
    shift
    if [ $# -eq 0 ]; then
        TARGETS="scripts/ hermass_platform/ agently_adapter/ web/ tests/"
    else
        TARGETS="$*"
    fi

    echo "[lint] ruff check (E,F,I) on ${TARGETS}..."
    CHECK_OUTPUT=$($RUFF_BIN check $RUFF_ARGS --select E,F,I $TARGETS 2>&1 || true)
    FORMAT_OUTPUT=$($RUFF_BIN format $RUFF_ARGS --check $TARGETS 2>&1 || true)

    if [ -n "$CHECK_OUTPUT" ]; then
        echo "$CHECK_OUTPUT"
    fi
    if [ -n "$FORMAT_OUTPUT" ]; then
        echo "$FORMAT_OUTPUT"
    fi

    if [ -z "$CHECK_OUTPUT" ] && [ -z "$FORMAT_OUTPUT" ]; then
        echo "LINT OK"
        exit 0
    else
        FIRST_ERR=$(
            printf '%s\n%s' "$CHECK_OUTPUT" "$FORMAT_OUTPUT" \
                | grep -oE '[-a-zA-Z_/]+/[a-zA-Z_]+/[a-zA-Z_./-]+\.py:[0-9]+' \
                | head -1
        )
        if [ -z "$FIRST_ERR" ]; then
            FIRST_ERR="unknown file"
        fi
        echo "FAILED: $FIRST_ERR"
        exit 9
    fi
    ;;
format)
    shift
    if [ $# -eq 0 ]; then
        TARGETS="scripts/ hermass_platform/ agently_adapter/ web/ tests/"
    else
        TARGETS="$*"
    fi

    echo "[lint] ruff format on ${TARGETS}..."
    $RUFF_BIN format $RUFF_ARGS $TARGETS

    echo "[lint] verifying..."
    REMAINING=$($RUFF_BIN format $RUFF_ARGS --check $TARGETS 2>&1 || true)
    if [ -n "$REMAINING" ]; then
        FIRST_ERR=$(echo "$REMAINING" | grep -oE '\.py:[0-9]+' | tail -1)
        echo "FAILED: $FIRST_ERR"
        exit 9
    else
        echo "LINT OK"
        exit 0
    fi
    ;;
help|-h|--help)
    print_help
    exit 0
    ;;
*)
    echo "未知模式: $1（支持 check / format / help）"
    exit 2
    ;;
esac
