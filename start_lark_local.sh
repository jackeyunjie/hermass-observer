#!/bin/bash
# Hermass Lark Bot 本地内测启动脚本（含 ngrok 自动穿透）
# 用法: ./start_lark_local.sh <你的VerificationToken>

set -e

TOKEN="${1:-${LARK_VERIFICATION_TOKEN}}"
if [ -z "$TOKEN" ]; then
    echo "❌ 错误: 缺少 LARK_VERIFICATION_TOKEN"
    echo "用法: ./start_lark_local.sh xxxxxx"
    echo "或先执行: export LARK_VERIFICATION_TOKEN=xxxxxx"
    exit 1
fi

export LARK_VERIFICATION_TOKEN="$TOKEN"
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "══════════════════════════════════════════"
echo "  Hermass W14 内测本地启动器"
echo "══════════════════════════════════════════"
echo ""

# 1. 检查 ngrok
if ! command -v ngrok &> /dev/null; then
    echo "❌ ngrok 未安装，请先安装: brew install ngrok"
    exit 1
fi

# 2. 安装依赖
echo "[1/5] 检查依赖..."
make install > /dev/null 2>&1
echo "   ✓ 依赖就绪"

# 3. 检查数据基础
echo "[2/5] 检查数据基础..."
FOUNDATION=$(python3 -c "from hermass_platform.slice.slice_engine import find_latest_foundation_db; print(find_latest_foundation_db() or '')" 2>/dev/null)
if [ -z "$FOUNDATION" ]; then
    echo "   ⚠ 未找到 foundation DB，Bot 会提示'系统初始化中'"
else
    echo "   ✓ Foundation: $(basename $(dirname $FOUNDATION))"
fi

# 4. 启动 ngrok 后台进程
echo "[3/5] 启动 ngrok 穿透..."
pkill -f "ngrok http 8080" 2>/dev/null || true
sleep 1
ngrok http 8080 > /tmp/ngrok.log 2>&1 &
NGROK_PID=$!
echo "   ngrok PID: $NGROK_PID"

# 等待 ngrok 获取公网地址
for i in {1..15}; do
    sleep 2
    PUBLIC_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['tunnels'][0]['public_url'])" 2>/dev/null || echo "")
    if [ -n "$PUBLIC_URL" ]; then
        break
    fi
    echo "   等待 ngrok 就绪... ($i/15)"
done

if [ -z "$PUBLIC_URL" ]; then
    echo "❌ ngrok 启动失败，请检查网络或 ngrok auth"
    cat /tmp/ngrok.log
    exit 1
fi

CALLBACK_URL="${PUBLIC_URL}/lark/callback"
HEALTH_URL="${PUBLIC_URL}/health"

echo "   ✓ 公网地址: $PUBLIC_URL"
echo ""
echo "══════════════════════════════════════════"
echo "  🚀 飞书后台配置信息（复制粘贴用）"
echo "══════════════════════════════════════════"
echo ""
echo "  请求地址 URL:"
echo "  $CALLBACK_URL"
echo ""
echo "  健康检查:"
echo "  $HEALTH_URL"
echo ""
echo "══════════════════════════════════════════"

# 5. 启动 Bot 服务
echo "[4/5] 启动 Hermass Lark Bot..."
echo "[5/5] 服务运行中，按 Ctrl+C 停止"
echo ""

# 清理函数
cleanup() {
    echo ""
    echo "🛑 停止服务..."
    kill $NGROK_PID 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

python3 .venv/bin/python hermass_platform/api/lark_server.py --port 8080 --host 0.0.0.0
