#!/usr/bin/env bash
# Hermass Internal Console — 服务器部署脚本
# 用法: sudo bash deploy/setup.sh
#
# 执行内容:
#   1. 安装 Nginx、apache2-utils (htpasswd)
#   2. 创建 hermass 用户
#   3. 配置 systemd 服务
#   4. 生成 Basic Auth 密码文件
#   5. 配置 Nginx 反向代理
#   6. 启动服务

set -euo pipefail

# ═══════════════════════════════════════════════════════════════
# 配置项（按需修改）
# ═══════════════════════════════════════════════════════════════
DOMAIN="${DOMAIN:-supertrader.world}"       # 你的域名
APP_DIR="${APP_DIR:-/opt/hermass}"          # 代码部署路径
HTTP_PORT="${HTTP_PORT:-80}"                # Nginx 监听端口
ADMIN_USER="${ADMIN_USER:-admin}"           # Basic Auth 用户名
# ADMIN_PASS 如果不设置，脚本会交互式提示输入

# ═══════════════════════════════════════════════════════════════
# 颜色输出
# ═══════════════════════════════════════════════════════════════
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

detect_pkg_manager() {
    if command -v apt-get &>/dev/null; then
        echo "apt"
        return
    fi
    if command -v dnf &>/dev/null; then
        echo "dnf"
        return
    fi
    if command -v yum &>/dev/null; then
        echo "yum"
        return
    fi
    echo "unknown"
}

install_system_packages() {
    local pkg_mgr
    pkg_mgr="$(detect_pkg_manager)"
    case "$pkg_mgr" in
        apt)
            apt-get update -qq
            apt-get install -y -qq nginx apache2-utils curl
            ;;
        dnf)
            dnf install -y nginx httpd-tools curl
            ;;
        yum)
            yum install -y nginx httpd-tools curl
            ;;
        *)
            error "未识别系统包管理器。请手动安装 nginx、htpasswd(httpd-tools/apache2-utils) 和 curl。"
            exit 1
            ;;
    esac
}

detect_nginx_group() {
    if getent group www-data >/dev/null 2>&1; then
        echo "www-data"
        return
    fi
    if getent group nginx >/dev/null 2>&1; then
        echo "nginx"
        return
    fi
    echo "root"
}

detect_nginx_conf_target() {
    if [[ -d /etc/nginx/sites-available ]] && [[ -d /etc/nginx/sites-enabled ]]; then
        echo "debian"
        return
    fi
    if [[ -d /etc/nginx/conf.d ]]; then
        echo "rhel"
        return
    fi
    echo "unknown"
}

# ═══════════════════════════════════════════════════════════════
# 检查 root 权限
# ═══════════════════════════════════════════════════════════════
if [[ $EUID -ne 0 ]]; then
    error "请用 sudo 运行此脚本"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════
# 1. 安装依赖
# ═══════════════════════════════════════════════════════════════
info "安装 Nginx 和 apache2-utils..."
install_system_packages

# 检查是否已安装 uvicorn
if ! command -v uvicorn &>/dev/null && [[ ! -f "$APP_DIR/.venv/bin/uvicorn" ]]; then
    warn "未找到 uvicorn，尝试安装..."
    if [[ -f "$APP_DIR/.venv/bin/pip" ]]; then
        "$APP_DIR/.venv/bin/pip" install -q uvicorn
    else
        error "找不到虚拟环境 pip，请先在 $APP_DIR 安装依赖"
        exit 1
    fi
fi

# ═══════════════════════════════════════════════════════════════
# 2. 创建 hermass 用户（如果不存在）
# ═══════════════════════════════════════════════════════════════
if ! id -u hermass &>/dev/null; then
    info "创建 hermass 用户..."
    useradd --system --user-group --home-dir "$APP_DIR" --shell /bin/false hermass
else
    info "hermass 用户已存在"
fi

# ═══════════════════════════════════════════════════════════════
# 3. 确保目录存在并设置权限
# ═══════════════════════════════════════════════════════════════
info "设置目录权限..."
mkdir -p "$APP_DIR"
mkdir -p /var/log/nginx
chown -R hermass:hermass "$APP_DIR"
chmod 750 "$APP_DIR"

# ═══════════════════════════════════════════════════════════════
# 4. 配置 systemd 服务
# ═══════════════════════════════════════════════════════════════
info "配置 systemd 服务..."
cp "$(dirname "$0")/systemd/hermass-console.service" /etc/systemd/system/hermass-console.service

# 根据实际路径修改 service 文件
sed -i "s|/opt/hermass|$APP_DIR|g" /etc/systemd/system/hermass-console.service

systemctl daemon-reload
systemctl enable hermass-console.service

# ═══════════════════════════════════════════════════════════════
# 5. 生成 Basic Auth 密码文件
# ═══════════════════════════════════════════════════════════════
HTPASSWD_FILE="/etc/nginx/.htpasswd_hermass"

if [[ -f "$HTPASSWD_FILE" ]]; then
    warn "密码文件已存在: $HTPASSWD_FILE"
    read -rp "是否重新生成? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        rm -f "$HTPASSWD_FILE"
    fi
fi

if [[ ! -f "$HTPASSWD_FILE" ]]; then
    if [[ -z "${ADMIN_PASS:-}" ]]; then
        echo ""
        read -rsp "设置 Basic Auth 密码: " ADMIN_PASS
        echo ""
        read -rsp "再次确认密码: " ADMIN_PASS2
        echo ""
        if [[ "$ADMIN_PASS" != "$ADMIN_PASS2" ]]; then
            error "两次输入的密码不一致"
            exit 1
        fi
    fi
    htpasswd -bc "$HTPASSWD_FILE" "$ADMIN_USER" "$ADMIN_PASS"
    chmod 640 "$HTPASSWD_FILE"
    chown "root:$(detect_nginx_group)" "$HTPASSWD_FILE"
    info "Basic Auth 密码文件已生成: $HTPASSWD_FILE"
fi

# ═══════════════════════════════════════════════════════════════
# 6. 配置 Nginx
# ═══════════════════════════════════════════════════════════════
info "配置 Nginx..."
NGINX_LAYOUT="$(detect_nginx_conf_target)"
case "$NGINX_LAYOUT" in
    debian)
        NGINX_CONF="/etc/nginx/sites-available/hermass"
        ;;
    rhel)
        NGINX_CONF="/etc/nginx/conf.d/hermass.conf"
        ;;
    *)
        error "未识别 Nginx 配置目录。请手动放置 deploy/nginx-hermass.conf。"
        exit 1
        ;;
esac

cp "$(dirname "$0")/nginx-hermass.conf" "$NGINX_CONF"

# 替换配置中的域名和路径
sed -i "s/console\\.hermass\\.local/$DOMAIN/g" "$NGINX_CONF"
sed -i "s|/opt/hermass|$APP_DIR|g" "$NGINX_CONF"

if [[ "$NGINX_LAYOUT" == "debian" ]]; then
    if [[ ! -L /etc/nginx/sites-enabled/hermass ]]; then
        ln -s "$NGINX_CONF" /etc/nginx/sites-enabled/hermass
    fi

    if [[ -L /etc/nginx/sites-enabled/default ]]; then
        rm -f /etc/nginx/sites-enabled/default
    fi
fi

# 测试配置
nginx -t

# ═══════════════════════════════════════════════════════════════
# 7. 启动服务
# ═══════════════════════════════════════════════════════════════
info "启动 Hermass Console 服务..."
systemctl start hermass-console.service
sleep 2

info "检查服务状态..."
if systemctl is-active --quiet hermass-console.service; then
    info "✓ hermass-console 服务运行中"
else
    error "服务启动失败，查看日志: journalctl -u hermass-console -n 50 --no-pager"
    exit 1
fi

info "启动 Nginx..."
systemctl restart nginx
systemctl enable nginx

# ═══════════════════════════════════════════════════════════════
# 8. 批量创建内测用户（可选）
# ═══════════════════════════════════════════════════════════════
# 内测阶段需要区分 8 个用户身份，但共用同一个测试账号密码不方便管理。
# 以下示例为每个内测成员创建独立 Basic Auth 账号：
#
#   sudo htpasswd -b /etc/nginx/.htpasswd_hermass 用户名 密码
#
# 然后把所有用户名写入环境变量 HERMASS_HTPASSWD_USERS（逗号分隔），
# 这样后端启动时会自动为每个用户初始化 profile：
#
#   export HERMASS_HTPASSWD_USERS="admin,user1,user2,user3,user4,user5,user6,user7"
#
# 建议把 export 语句写入 /etc/systemd/system/hermass-console.service 的 [Service] 段：
#
#   Environment="HERMASS_HTPASSWD_USERS=admin,user1,user2,user3,user4,user5,user6,user7"
#
# 然后 systemctl daemon-reload && systemctl restart hermass-console

info "Basic Auth 密码文件路径: $HTPASSWD_FILE"
info "当前已有用户: $(htpasswd -b -v "$HTPASSWD_FILE" dummy dummy 2>/dev/null || true)"

# ═══════════════════════════════════════════════════════════════
# 9. 验证
# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Hermass Internal Console 部署完成"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  访问地址: http://$DOMAIN (端口 $HTTP_PORT)"
echo "  用户名:   $ADMIN_USER"
echo "  服务状态: systemctl status hermass-console"
echo "  查看日志: journalctl -u hermass-console -f"
echo "  Nginx日志: /var/log/nginx/hermass_*.log"
echo ""
echo "  常用命令:"
echo "    sudo systemctl start|stop|restart|status hermass-console"
echo "    sudo systemctl reload nginx"
echo "    sudo htpasswd /etc/nginx/.htpasswd_hermass 新用户名"
echo ""
echo "  内测用户管理:"
echo "    1. 添加用户: sudo htpasswd -b /etc/nginx/.htpasswd_hermass 用户名 密码"
echo "    2. 更新环境变量: sudo systemctl edit hermass-console"
echo "       添加: [Service] 段 Environment=HERMASS_HTPASSWD_USERS=用户名1,用户名2,..."
echo "    3. 重启服务: sudo systemctl daemon-reload && sudo systemctl restart hermass-console"
echo ""

# 本地健康检查
curl -sf http://127.0.0.1:8020/health >/dev/null && \
    info "✓ 后端健康检查通过 (http://127.0.0.1:8020/health)" || \
    warn "后端健康检查未通过，请检查日志"
