#!/bin/bash
# Hermass Observer 测试入口脚本
# 用法: bash scripts/run_tests.sh [unit|smoke|help]
#
# 退出码约定:
#   0 — 测试全部通过
#   1 — 测试失败（pytest 返回非 0）
#   2 — 参数错误（用户传了未识别的子命令）
#   3 — 环境错误（pytest 不存在或虚拟环境未就绪）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PRODUCT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PRODUCT_DIR/.venv"

# ── 退出码 3：环境检查 ──────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "[ERROR] 虚拟环境不存在: $VENV_DIR" >&2
    echo "请先执行: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
    exit 3
fi

if [ ! -f "$VENV_DIR/bin/pytest" ]; then
    echo "[ERROR] pytest 未安装。请先在虚拟环境中安装测试依赖。" >&2
    exit 3
fi

# 激活虚拟环境
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

# 确保项目包可被导入
export PYTHONPATH="$PRODUCT_DIR${PYTHONPATH:+:$PYTHONPATH}"

# ── 子命令路由 ─────────────────────────────────────────────────────
run_unit() {
    echo "[run_tests] 运行单元测试 tests/unit/ ..."
    "$VENV_DIR/bin/pytest" tests/unit/ -q
}

run_smoke() {
    echo "[run_tests] 运行冒烟测试 tests/smoke/ ..."
    set +e
    "$VENV_DIR/bin/pytest" tests/smoke/ -q
    RC=$?
    # pytest 退出码 5 = 全部跳过（如缺 API key），视为通过
    if [ "$RC" -eq 0 ] || [ "$RC" -eq 5 ]; then
        exit 0
    else
        exit "$RC"
    fi
}

print_help() {
    cat << 'HELP'
用法: bash scripts/run_tests.sh <命令>

命令:
  unit    运行 pytest tests/unit/ -q
  smoke   运行 pytest tests/smoke/ -q
  help    打印本帮助信息

退出码:
  0  测试全部通过
  1  测试失败（pytest 返回非 0）
  2  参数错误（传入了未识别的子命令）
  3  环境错误（虚拟环境或 pytest 不存在）

环境变量:
  HERMASS_DEEPSEEK_API_KEY  部分 smoke 用例需要真实 DeepSeek API key。
                            若未设置，相关用例会跳过（不会导致失败）。
                            设置方式: export HERMASS_DEEPSEEK_API_KEY=sk-...
HELP
}

# ── 主入口 ─────────────────────────────────────────────────────────
cmd="${1:-help}"

case "$cmd" in
    unit)
        run_unit
        ;;
    smoke)
        run_smoke
        ;;
    help)
        print_help
        ;;
    *)
        # 退出码 2：参数错误
        echo "[ERROR] 未知命令: '$cmd'" >&2
        echo "请使用: bash scripts/run_tests.sh help" >&2
        exit 2
        ;;
esac
