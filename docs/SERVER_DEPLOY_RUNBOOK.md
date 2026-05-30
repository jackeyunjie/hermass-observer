# Server Deploy Runbook

日期：2026-05-29  
目标：把 `Hermass 多周期观察台` 部署到 `supertrader.world`

本手册只覆盖三件事：

1. 整理首发提交范围
2. 服务器部署命令
3. 部署后最终验收

---

## 1. 首发提交范围

本次首发只围绕内部网站与部署脚手架。

### 1.1 建议提交的目录

```bash
git add .gitignore
git add pyproject.toml
git add README.md
git add deploy/
git add web/
git add hermass_platform/agents/
git add hermass_platform/api/
git add hermass_platform/research/
git add config/hermes_cron.json
git add config/models/
git add config/platform/
git add config/prompts/
git add scripts/build_daily_snapshot.py
git add scripts/build_external_research_evidence.py
git add scripts/render_external_research_cards.py
git add scripts/ifind_fundamental_collector.py
git add scripts/run_daily_pipeline.sh
git add scripts/run_morning_brief.sh
git add tests/
git add docs/GITHUB_RELEASE_SCOPE_CHECKLIST.md
git add docs/GITHUB_FIRST_RELEASE_COMMANDS.md
git add docs/PREDEPLOY_SCOPE_FREEZE.md
git add docs/INTERNAL_CONSOLE_PREDEPLOY_ACCEPTANCE_CHECKLIST.md
git add docs/INTERNAL_CONSOLE_PREDEPLOY_ACCEPTANCE_REPORT.md
git add docs/SERVER_DEPLOY_RUNBOOK.md
```

### 1.2 本次不要一起推的内容

```bash
docs/               # 除明确纳入首发的少量文档外
data/
outputs/
logs/
_batch*.log
_batch*.txt
scripts/us_*
scripts/build_us_*
scripts/alpaca_*
docs/US_*
docs/HERMASS_STATE_MT5_PORTING_GUIDE.md
docs/mt5_package/
```

### 1.3 提交前检查

```bash
git status --short
python3 -m py_compile web/main.py
```

要求：

- `web/main.py` 语法检查通过
- 不再把 `data/ outputs/ logs/` 误加入暂存区

### 1.4 建议 commit

如果压成一个首发提交：

```bash
git commit -m "feat: ship hermass multi-cycle internal console and deploy scaffolding"
```

---

## 2. GitHub 推送

### 2.1 添加远程仓库

```bash
git remote add origin https://github.com/<YOUR_USER>/<YOUR_REPO>.git
```

### 2.2 推送

```bash
git push -u origin main
```

如果本地默认分支不是 `main`，按实际分支名替换。

---

## 3. 服务器准备

服务器信息：

- 公网 IP：`8.130.125.201`
- 系统：`Alibaba Cloud Linux 3`
- 目标域名：`supertrader.world`

### 3.1 登录服务器

```bash
ssh root@8.130.125.201
```

### 3.2 安装 git（若缺失）

```bash
dnf install -y git python3
```

---

## 4. 服务器代码部署

### 4.1 克隆代码

```bash
cd /opt
git clone https://github.com/<YOUR_USER>/<YOUR_REPO>.git hermass
cd /opt/hermass
```

### 4.2 创建虚拟环境

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install fastapi uvicorn jinja2 duckdb pandas numpy pyyaml requests python-multipart httpx
```

如果你有完整依赖文件，也可以改成：

```bash
.venv/bin/pip install -r requirements.txt
```

---

## 5. 启动前自检

在服务器上先做一次最小检查：

```bash
cd /opt/hermass
.venv/bin/python -m py_compile web/main.py
.venv/bin/python - <<'PY'
from fastapi.testclient import TestClient
from web.main import app
client = TestClient(app)
for route in [
    '/?mode=direction',
    '/?mode=research',
    '/?mode=execution',
    '/market',
    '/industry',
    '/watchlist',
    '/research?stock_code=000021.SZ',
    '/backtest',
]:
    resp = client.get(route)
    print(resp.status_code, route)
PY
```

预期：

- 所有路由返回 `200`

---

## 6. systemd + Nginx 部署

### 6.1 运行部署脚本

```bash
cd /opt/hermass
DOMAIN=supertrader.world APP_DIR=/opt/hermass sudo bash deploy/setup.sh
```

说明：

- 脚本已兼容 `apt / dnf / yum`
- 脚本已兼容 Debian 风格与 RHEL 风格 Nginx 目录
- 脚本会交互要求输入 Basic Auth 密码

### 6.2 部署完成后检查

```bash
systemctl status hermass-console --no-pager
systemctl status nginx --no-pager
curl -I http://127.0.0.1:8020/health
```

---

## 7. 域名与访问

如果 DNS 已经把 `supertrader.world` 指向服务器公网 IP，则可以直接访问：

```text
http://supertrader.world
```

当前默认有 Basic Auth。

如果要做 HTTPS，后续再加：

```bash
dnf install -y certbot python3-certbot-nginx
certbot --nginx -d supertrader.world
```

这不作为本次首发阻塞项。

---

## 8. 部署后最终验收

部署后在真实域名上人工检查：

### 8.1 首页三模式

- `/?mode=direction`
- `/?mode=research`
- `/?mode=execution`

检查：

- 首屏标题是否是 `Hermass 多周期观察台`
- 是否有 `从这里开始`
- 是否有 `State / EF / RR / Cron` 术语说明

### 8.2 市场页

`/market`

检查：

- 有“现在先看什么 / 暂时少看什么”
- 有策略降权提示

### 8.3 执行页

`/watchlist`

检查：

- 主列是 `共振路径`
- 有资金流确认 / 资金背离 / 板块承接 / 真假突破 / 持续性

### 8.4 研究页

`/research?stock_code=000021.SZ`

检查：

- 有决策收束
- 有多因子共振判断
- 页面不是空壳

### 8.5 回测页

`/backtest`

检查：

- 页面可打开
- 提交 30 天参数不崩
- 有最小 tearsheet 或空结果说明

---

## 9. 更新流程

后续更新：

```bash
cd /opt/hermass
git pull
systemctl restart hermass-console
systemctl reload nginx
```

---

## 10. 本次不做的事

本次部署明确不包含：

- NL→SQL 查询层
- 多 Agent 推理链
- AI 每日叙事
- 自由策略实验室
- 自动交易执行

这些统一进入 Phase 2。
