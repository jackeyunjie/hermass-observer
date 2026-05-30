#!/bin/bash
# Hermass Observer 周末仓库整理检查
# 用法: 手动执行 ./scripts/weekend_repo_hygiene_check.sh
# 定时任务建议: 每周六本地时间 10:00 执行，仅生成报告，不自动改 git 状态

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PRODUCT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PRODUCT_DIR/logs/repo_hygiene"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
REPORT_PATH="$LOG_DIR/weekend_repo_hygiene_${TIMESTAMP}.md"

mkdir -p "$LOG_DIR"

cd "$PRODUCT_DIR"

head_commit="$(git log --oneline -1 2>/dev/null || echo 'unknown')"
status_short="$(git status --short 2>/dev/null || true)"
staged_count="$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')"
unstaged_count="$(git diff --name-only 2>/dev/null | wc -l | tr -d ' ')"
untracked_count="$(git ls-files --others --exclude-standard 2>/dev/null | wc -l | tr -d ' ')"

{
    echo "# 周末仓库整理检查"
    echo
    echo "- 生成时间: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "- 仓库路径: $PRODUCT_DIR"
    echo "- 最新提交: $head_commit"
    echo
    echo "## 概览"
    echo
    echo "- staged 文件数: $staged_count"
    echo "- unstaged 文件数: $unstaged_count"
    echo "- untracked 文件数: $untracked_count"
    echo
    echo "## 当前状态"
    echo
    if [ -n "$status_short" ]; then
        echo '```text'
        printf '%s\n' "$status_short"
        echo '```'
    else
        echo "工作树干净。"
    fi
    echo
    echo "## 建议动作"
    echo
    if [ "$staged_count" -gt 0 ]; then
        echo "- 存在 staged 内容，优先检查是否混入无关文件后再提交。"
    fi
    if [ "$unstaged_count" -gt 0 ]; then
        echo "- 存在 unstaged 修改，建议先按主题分组，再决定是否纳入下一次 commit。"
    fi
    if [ "$untracked_count" -gt 0 ]; then
        echo "- 存在未跟踪文件，建议确认哪些是临时产物，哪些需要纳入版本管理。"
    fi
    if [ "$staged_count" -eq 0 ] && [ "$unstaged_count" -eq 0 ] && [ "$untracked_count" -eq 0 ]; then
        echo "- 当前无需整理。"
    fi
    echo
    echo "## A 股运行时相关文件快速检查"
    echo
    runtime_targets=(
        "README.md"
        "agently_adapter/a_share_actions.py"
        "agently_adapter/a_share_core.py"
        "agently_adapter/agently_a_share_flow.py"
        "agently_adapter/agently_daily_flow.py"
        "agently_adapter/stockpool_daily_runner.py"
        "docs/AGENTLY_A_SHARE_INTEGRATION_PLAN.md"
        "docs/A_SHARE_SERVICE_API.md"
        "docs/SYSTEM_ARCHITECTURE.md"
        "hermass_platform/api/a_share_service.py"
        "workflows/agently_stockpool_dag/README.md"
    )
    echo '```text'
    for target in "${runtime_targets[@]}"; do
        if git status --short -- "$target" 2>/dev/null | grep -q .; then
            git status --short -- "$target"
        fi
    done
    echo '```'
    echo
    echo "## 手动整理命令建议"
    echo
    echo '```bash'
    echo "# 1. 先查看 staged 文件"
    echo "git diff --cached --name-status"
    echo
    echo "# 2. 如需清空暂存区但保留文件内容"
    echo "git reset"
    echo
    echo "# 3. 只重新暂存当前主题文件"
    echo "git add README.md docs/SYSTEM_ARCHITECTURE.md docs/A_SHARE_SERVICE_API.md"
    echo '```'
} > "$REPORT_PATH"

echo "$REPORT_PATH"
