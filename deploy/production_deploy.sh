#!/bin/bash
# Hermass Lark Bot 生产环境一键部署脚本
# 适用于 Ubuntu 22.04 / CentOS 8+
# 用法: ./production_deploy.sh <LARK_VERIFICATION_TOKEN>

set -e
TOKEN="${1:-${LARK_VERIFICATION_TOKEN}}"
if [ -z "$TOKEN" ]; then
    echo "用法: ./production_deploy.sh <LARK_VERIFICATION_TOKEN>"
    exit 1
fi

INSTALL_DIR="/opt/hermass-observer"
DOMAIN="${HERMASS_DOMAIN:-lark-bot.yourdomain.com}"

echo "══════════════════════════════════════════"
echo "  Hermass Bot 生产部署"
echo "  目录: $INSTALL_DIR"
echo "  域名: $DOMAIN"
echo "══════════════════════════════════════════"

# 1. 安装系统依赖
echo "[1/6] 安装系统依赖..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx certbot python3-certbot-nginx rsync git

# 2. 部署代码
echo "[2/6] 部署代码..."
mkdir -p "$INSTALL_DIR"
rsync -avz --exclude='.venv' --exclude='.git' --exclude='data/blackwolf_*' \
  /Users/lv111101/Documents/hermass-observer-product/ "$INSTALL_DIR/"

# 3. 创建虚拟环境
echo "[3/6] 创建 Python 虚拟环境..."
cd "$INSTALL_DIR"
python3 -m venv .venv
.venv/bin/pip install -q pyyaml numpy pandas requests duckdb jinja2

# 4. 创建 Systemd 服务
echo "[4/6] 配置 Systemd..."
cat > /etc/systemd/system/hermass-lark.service << EOL
[Unit]
Description=Hermass Lark Bot Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment=LARK_VERIFICATION_TOKEN=${TOKEN}
ExecStart=${INSTALL_DIR}/.venv/bin/python ${INSTALL_DIR}/hermass_platform/api/lark_server.py --port 8080 --host 127.0.0.1
Restart=always
RestartSec=5
StandardOutput=append:/var/log/hermass-lark.log
StandardError=append:/var/log/hermass-lark.log

[Install]
WantedBy=multi-user.target
EOL

systemctl daemon-reload
systemctl enable hermass-lark

# 5. 配置 Nginx
echo "[5/6] 配置 Nginx..."
cat > /etc/nginx/sites-available/hermass-lark << EOL
server {
    listen 80;
    server_name ${DOMAIN};

    location /lark/callback {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /health {
        proxy_pass http://127.0.0.1:8080;
        access_log off;
    }
}
EOL

ln -sf /etc/nginx/sites-available/hermass-lark /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# 6. 启动服务
echo "[6/6] 启动 Bot 服务..."
systemctl start hermass-lark
sleep 2
systemctl status hermass-lark --no-pager

echo ""
echo "══════════════════════════════════════════"
echo "  ✅ 部署完成"
echo "══════════════════════════════════════════"
echo ""
echo "  飞书回调地址: http://${DOMAIN}/lark/callback"
echo "  健康检查:     http://${DOMAIN}/health"
echo ""
echo "  查看日志: journalctl -u hermass-lark -f"
echo "  重启服务: systemctl restart hermass-lark"
echo ""
echo "  下一步: 配置 HTTPS"
echo "  certbot --nginx -d ${DOMAIN}"
echo "══════════════════════════════════════════"
