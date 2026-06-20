#!/usr/bin/env bash
# 重建 + 上传 + 冒烟 /debate-dashboard 部署脚本。
#
# 解决的问题（Codex 2026-06-19 审计风险1）：
#   outputs/debate_dashboard.html 被 .gitignore 整体忽略，标准 git pull 不会带上
#   这个文件，导致 /debate-dashboard 出现 404。
# 解决方式：把 "build -> upload -> smoke" 收成一条命令，每一步失败立即退出。
#
# 用法：
#   bash scripts/deploy_debate_dashboard.sh
#
# 流程：
#   1. 跑 scripts/build_debate_dashboard.py 重新生成 outputs/debate_dashboard.html
#      （把"系统关键指标"区从硬编码换成运行时真相源）
#   2. 跑 scripts/upload_output_to_server.py --type debate_dashboard
#      通过 /api/admin/upload-data 上传到服务器
#   3. curl 冒烟 /debate-dashboard 确认 200 + 关键标记

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV_PY="$ROOT/.venv/bin/python"
SERVER_HOST="console.supertrader.world"
SERVER_LOCAL="http://localhost:8020"
SERVER_PUBLIC="https://$SERVER_HOST"
AUTH="-u hermass-test:Hermass2026!Lab"

echo "==> [1/3] build_debate_dashboard.py"
"$VENV_PY" "$ROOT/scripts/build_debate_dashboard.py"

echo
echo "==> [2/3] upload via /api/admin/upload-data (type=debate_dashboard)"
TODAY="$(date +%Y-%m-%d)"
"$VENV_PY" "$ROOT/scripts/upload_output_to_server.py" --date "$TODAY" --type debate_dashboard

echo
echo "==> [3/3] smoke /debate-dashboard (公网)"
SMOKE_URL="https://$SERVER_HOST/debate-dashboard"
HTTP_CODE=$(curl -s -o /tmp/dd_smoke.html -w "%{http_code}" $AUTH "$SMOKE_URL")
echo "  $SMOKE_URL  http=$HTTP_CODE"

# 关键标记验证（公网页面）
echo
echo "==> 关键标记验证（公网返回 /tmp/dd_smoke.html）"
for k in "口径：五方加权平均" "数据新鲜度" "hermes_cron" "web/main.py" "看今日推荐" "/chain-studio" "bar5d"; do
  if grep -q "$k" /tmp/dd_smoke.html; then
    printf "  %-25s : OK\n" "$k"
  else
    printf "  %-25s : MISSING\n" "$k"
    exit 1
  fi
done

if [ "$HTTP_CODE" != "200" ]; then
  echo
  echo "[FAIL] /debate-dashboard http 不为 200：http=$HTTP_CODE"
  exit 1
fi

echo
echo "[OK] /debate-dashboard 部署 + 冒烟全通"
