# Hermass Upload 413 Troubleshooting Runbook

日期：2026-06-01

用途：以后遇到“上传网站数据失败 / HTTP 413 / Nginx 拦截 / 容器入口不清楚”时，按本文件快速定位。

## 已确认的服务器结构

- Hermass 后端服务：`hermass-console`
- Hermass 后端端口：`8020`
- Hermass 后端地址：`http://127.0.0.1:8020`
- 对外访问域名：`console.supertrader.world`
- 对外入口端口：`80 / 443`
- 对外入口容器：`company-pager-nginx`
- 容器镜像：`nginx:alpine`
- 宿主机 Nginx 状态：可能是 failed，不是当前真实入口
- 真实 Nginx 配置宿主机路径：`/opt/company-pager/nginx-backend.conf`
- 容器内配置路径：`/etc/nginx/conf.d/default.conf`
- 挂载模式：`ro` 只读挂载

重要结论：

`company-pager-nginx` 名字看起来像另一个项目，但它是当前服务器 80/443 的统一入口。只要它的配置里存在 `server_name console.supertrader.world;` 和 `proxy_pass http://172.17.0.1:8020;`，它就是 Hermass 网站上传链路的真实入口。

## 这次 413 的根因

本地上传：

```bash
http://8.130.125.201/api/admin/upload-data
```

返回：

```text
HTTP 413 Request Entity Too Large
nginx/1.29.4
```

根因不是 FastAPI，也不是上传接口不存在，而是 Nginx 请求体大小限制没有在真实处理请求的 server/location 中生效。

具体原因：

1. 最初只改了宿主机文件，但容器内 `nginx -T` 看不到 `client_max_body_size 5G;`。
2. 配置文件是只读挂载，reload 不一定重新读取到最新挂载内容。
3. 重启 `company-pager-nginx` 后，容器内配置才显示生效。
4. IP 直接访问 `/api/admin/upload-data` 可能先命中第一个 server 块，也就是 `superalpha.com.cn www.superalpha.com.cn` 那个 server。
5. 因此只在 `console.supertrader.world` 的 server 块加限制不够，第一个 server 块和 `/api/` location 也要加。

## 快速判断是否改对入口

在服务器执行：

```bash
docker ps --format "table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Ports}}"
docker exec company-pager-nginx nginx -T | grep -n "console.supertrader.world" -C 30
docker exec company-pager-nginx nginx -T | grep -n "proxy_pass http://172.17.0.1:8020" -C 10
```

判断：

- 能看到 `server_name console.supertrader.world;`：这是 Hermass 的真实入口。
- 能看到 `proxy_pass http://172.17.0.1:8020;`：该入口确实代理到 Hermass 后端。
- 看不到这两项：停止修改这个容器，继续查真实入口。

## 查看宿主机挂载文件

```bash
docker inspect company-pager-nginx | grep -nE '"Source"|"Destination"|"Mode"' -C 2
```

当前应看到：

```text
"Source": "/opt/company-pager/nginx-backend.conf"
"Destination": "/etc/nginx/conf.d/default.conf"
"Mode": "ro"
```

以后要改的是宿主机文件：

```bash
/opt/company-pager/nginx-backend.conf
```

不要直接改容器内文件，因为容器内是挂载目标。

## 正确配置位置

需要在两个 server 块和关键 location 块都配置：

```nginx
client_max_body_size 5G;
```

当前应覆盖：

1. `server_name superalpha.com.cn www.superalpha.com.cn;`
2. 该 server 下的 `location /api/`
3. 该 server 下的 `location /`
4. `server_name console.supertrader.world;`
5. 该 server 下的 `location /`
6. 该 server 下的 `location /health`

原因：

- 通过域名 `console.supertrader.world` 访问时，命中 Hermass server 块。
- 通过 IP `8.130.125.201` 访问时，可能命中第一个/default server 块。
- 上传接口路径是 `/api/admin/upload-data`，如果命中第一个 server，会进入 `/api/` location。

## 修改后必须重启容器

宿主机文件改完后执行：

```bash
docker restart company-pager-nginx
docker exec company-pager-nginx nginx -t
docker exec company-pager-nginx nginx -T | grep -n "client_max_body_size"
```

验收：

```text
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

并且至少能看到多处：

```text
client_max_body_size 5G;
```

如果只执行 reload 后 `nginx -T` 看不到新配置，直接重启容器。

## 本地复测上传

先测小的 snapshot：

```bash
source .venv/bin/activate
HERMASS_UPLOAD_URL='http://8.130.125.201/api/admin/upload-data' \
HERMASS_UPLOAD_USER='hermass-test' \
HERMASS_UPLOAD_PASS='Hermass2026!Lab' \
python scripts/upload_output_to_server.py --date 20260601 --type snapshot
```

再测大的 foundation：

```bash
source .venv/bin/activate
HERMASS_UPLOAD_URL='http://8.130.125.201/api/admin/upload-data' \
HERMASS_UPLOAD_USER='hermass-test' \
HERMASS_UPLOAD_PASS='Hermass2026!Lab' \
python scripts/upload_output_to_server.py --date 20260601 --type foundation
```

成功标准：

```text
[OK] 上传成功
```

如果还返回 413，说明真实处理请求的 server/location 仍然没有生效的 `client_max_body_size 5G;`，继续用：

```bash
docker exec company-pager-nginx nginx -T
```

查看完整配置，不要只看宿主机文件。

## 给服务器 Codex 的最短提示词

```text
排查 Hermass 上传 HTTP 413。

服务器真实入口不是宿主机 nginx，而是 Docker 容器 company-pager-nginx。
配置挂载关系：
- 宿主机：/opt/company-pager/nginx-backend.conf
- 容器内：/etc/nginx/conf.d/default.conf

请执行：
1. docker exec company-pager-nginx nginx -T | grep -nE "server_name|client_max_body_size|location|proxy_pass|console.supertrader.world|superalpha.com.cn" -C 3
2. 确认 console.supertrader.world 代理到 http://172.17.0.1:8020
3. 在 superalpha.com.cn server、console.supertrader.world server、/api/、/、/health 这些位置都加 client_max_body_size 5G;
4. 修改宿主机文件 /opt/company-pager/nginx-backend.conf
5. docker restart company-pager-nginx
6. docker exec company-pager-nginx nginx -t
7. docker exec company-pager-nginx nginx -T | grep -n "client_max_body_size"

验收：
- nginx -t successful
- nginx -T 能看到多处 client_max_body_size 5G
- 本地重新上传 snapshot 不再返回 HTTP 413
```

## 不要重复犯的错

- 不要被 `company-pager-nginx` 名字误导。它可能属于 company-pager 项目，但它也是当前服务器的统一 Nginx 入口。
- 不要只看宿主机 Nginx。80/443 是 Docker Nginx 容器在监听。
- 不要只改 `console.supertrader.world` server。IP 访问可能命中第一个 server。
- 不要只 reload。只读挂载场景下，改完宿主机文件后优先重启容器验证。
- 不要只看文件内容。最终以 `docker exec company-pager-nginx nginx -T` 输出为准。
