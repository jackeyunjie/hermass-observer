# Deploy Runbook

> 执行范围声明：本文档仅面向**服务器上的授权执行者**（例如服务器 Codex）或**明确授权的部署人**。
> 本地开发者禁止执行其中的 `ssh root@8.130.125.201 ...`、`curl 8.130.125.201` 等命令，遵循项目 `AGENTS.md` 的“本地只做代码修改 + git push”约束。

125.201 "echo OK"` 应返回 OK |
| 端口未占用 | 8080 未被占用 | `ssh root@8.130.125.201 "ss -tlnp \| grep 8080"` 应无输出 |
| 服务器目录 | `/opt/hermass-observer` 已创建或可写 | `ssh root@8.130.125.201 "ls /opt/"` |
| 本机环境 | 在 `hermass-observer-product` 根目录 | `pwd` |

### 禁止事项

- **不动 `.venv`** 目录（备份方式保留，部署脚本已排除）
- **不远程执行 `pip install`** 或修改服务器 venv
- **不手动改 nginx 配置**（部署脚本自动完成）
- **不改数据库文件**（duckdb 文件由 pipeline 生成）
- **不修改 `DEEPSEEK_API_KEY`**（如有需要则走配密平台）

---

## 主流程（四步）

**执行者提示：以下 Step 1-4 仅限“服务器上的授权执行者”或获得明确授权的部署人本地执行。**

> 普通本地开发者请勿执行以下 `ssh` / `rsync` / `curl` 命令，遵循项目 `AGENTS.md` 中“部署和测试通过提示词交给服务器上的 AI”的规则。



### Step 1 同步

从本机 rsync 代码到服务器：

```bash
cd /Users/lv111101/Documents/hermass-observer-product
bash deploy/production_deploy.sh <LARK_VERIFICATION_TOKEN>
```

该脚本自动完成：
1. `rsync -avz` 同步代码（排除 `.venv`、`.git`、`data/blackwolf_*`）
2. 创建 Python venv + 安装依赖
3. 写入 systemd service 文件 → 自启
4. 写入 nginx 配置 → 反代 `/.well-known/acme-challenge`
5. 启动 lark-bot 服务

> 如需只同步代码不改动服务，直接执行：
> ```bash
> rsync -avz --exclude='.venv' --exclude='.git' --exclude='data/blackwolf_*' \
>   /Users/lv111101/Documents/hermass-observer-product/ root@8.130.125.201:/opt/hermass/observer-product/
> ```

### Step 2 语法校验

```bash
# 确认 Python 语法无误
ssh root@8.130.125.201 "cd /opt/hermass-observer && .venv/bin/python -c 'import hermass_platform.api.lark_server; print(\"OK\")'"
```

预期输出：`OK`

### Step 3 重启

```bash
ssh root@8.130.125.201 "
  systemctl daemon-reload &&
  systemctl restart hermass-lark &&
  sleep 3 &&
  systemctl status hermass-lark --no-pager
"
```

预期输出：`Active: active (running)` 绿色高亮。

### Step 4 冒烟

```bash
# 健康检查
curl -s http://8.130.125.201/health || echo "FAIL"

# 飞书回调验证（替换 <token> 为真实值）
curl -s "http://8.130.125.201/health" | head -200
```

预期输出：`{"status":"ok"}` 类似健康响应。

---

## 回滚表

| 场景 | 检测信号 | 回滚命令 | 预期现象 |
|------|----------|----------|----------|
| **同步失败** | rsync 报错或网络不通 | 检查旧版代码仍可用：`ssh root@8.130.125.201 "ls -lt /opt/hermass-observer/\|\| head -5"` | 若上版本存在则可应急：`git checkout <旧commit>` 后重新同步 |
| **语法失败** | Step 2 import 报错 | 回退到前一次同步的版本：<br>`ssh root@8.130.125.201 "cd /opt/hermass-observer && git log --oneline -5"`<br>确认可回 CS 后本地修正 | 报错信息指向具体文件/行号 |
| **重启失败** | systemctl status 显示 `failed` | 先查日志：<br>`journalctl -u hermass-lark -n 50 --no-pager`<br>确认非代码问题后重试：<br>`systemctl restart hermass-lark` | 若为端口占用：`ss -tlnp \| grep 8080` |
| **冒烟失败** | curl 无响应或非 200 | 先查服务状态：<br>`systemctl status hermass-lark`<br>再查 nginx：<br>`nginx -t && systemctl status nginx` | 重启 nginx：`systemctl restart nginx` |

---

## 日志定位

> 以下命令可能需要 SSH/服务器直连，仅限授权部署人在服务器侧执行。



```bash
# 实时查看服务日志
journalctl -u hermass-lark -f

# 最近 200 行
journalctl -u hermass-lark -n 200 --no-pager

# 查看异常时间点前后
journalctl -u hermass-lark --since "10 minutes ago"

# nginx 错误日志
ssh root@8.130.125.201 "tail -50 /var/log/nginx/error.log"
```

---

## HTTPS 配置（首次部署后）

```bash
ssh root@8.130.125.201 "
  certbot --nginx -d lark-bot.yourdomain.com &&
  systemctl reload nginx
"
```

> 注意：`.well-known/acme-challenge/` 已由部署脚本通过 nginx location 静态头配置，certbot 应能直接验证通过。

---

## 常见问题

**Q: 部署脚本对服务器有什么要求？**

A: Ubuntu 22.04+ 或 CentOS 8+，默认包含 `apt-get`/`yum`。脚本自动安装 `rsync`、`nginx`、`certbot`、`python3-venv`。

**Q: 服务器已有一个旧版本怎么办？**

A: 直接重新跑部署脚本即可。systemd service 覆盖写入，nginx 配置覆盖写入。先前的日志保留在 journalctl 历史中。

**Q: 如何确认部署消灭了旧进程？**

A: `systemctl restart hermass-lark` 会先 stop 再 start，systemd 不会保留旧 PID。

**Q: 防火墙需要放行什么？**

A: 80（HTTP）、443（HTTPS）、22（SSH）。8080 仅监听 127.0.0.1，不对外暴露。
