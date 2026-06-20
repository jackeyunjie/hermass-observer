#!/usr/bin/env bash
# /debate-dashboard 已经重构为动态模板，不再需要本地构建 HTML 和上传静态文件。
# 这个脚本现在只做公网的冒烟测试。
# 
# 部署 SOP: 
#   git commit -am "..."
#   git push
#   在服务器上 git pull 并重启服务

set -euo pipefail

SERVER_HOST="console.supertrader.world"
AUTH="-u hermass-test:Hermass2026!Lab"

echo "==> smoke /debate-dashboard (公网 HTTP，Nginx 80 入口)"
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
echo "[OK] /debate-dashboard 冒烟全通"
