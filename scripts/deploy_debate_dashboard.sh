#!/usr/bin/env bash
# 重建本地 JSON + 上传 + 冒烟 /debate-dashboard 部署脚本。
#
# P2-3 架构变更：不再上传静态 HTML，而是上传 debate_dashboard_data.json
# 供服务器上的 Jinja2 模板动态渲染。本地指标（如 macOS launchd 状态）
# 在此脚本运行时收集。
#
# 流程：
#   1. 跑 scripts/build_debate_dashboard_data.py 生成 outputs/debate/debate_dashboard_data.json
#   2. 跑 scripts/upload_output_to_server.py --type debate_dashboard
#   3. curl 冒烟 /debate-dashboard 确认 200 + 关键标记

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV_PY="$ROOT/.venv/bin/python"
SERVER_HOST="console.supertrader.world"
AUTH="-u hermass-test:Hermass2026!Lab"

echo "==> [1/3] build_debate_dashboard_data.py"
"$VENV_PY" "$ROOT/scripts/build_debate_dashboard_data.py"

echo
echo "==> [2/3] upload via /api/admin/upload-data (type=debate_dashboard)"
TODAY="$(date +%Y-%m-%d)"
"$VENV_PY" "$ROOT/scripts/upload_output_to_server.py" --date "$TODAY" --type debate_dashboard

echo
echo "==> [3/3] smoke /debate-dashboard (公网 HTTP，Nginx 80 入口)"
SMOKE_URL="http://$SERVER_HOST/debate-dashboard"
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
