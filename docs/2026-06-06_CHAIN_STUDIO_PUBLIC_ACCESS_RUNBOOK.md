# Chain Studio 公网访问与恢复验收 Runbook

日期：2026-06-06

用途：以后遇到 `console.supertrader.world/chain-studio` 打不开、接口 `401/404`、怀疑“登录受限”或“服务器没更新”时，按本文件快速判断。

## 当前结论

- `console.supertrader.world` 外层有 Nginx Basic Auth。
- 公网 `401 Authorization Required` 默认表示鉴权生效，不等于应用故障。
- `chain-studio` 当前真实恢复状态应以内网 `localhost:8020` 和带 Basic Auth 的公网验收共同确认。

## 本次恢复后的正确状态

- GitHub `origin/main` 已推进到 `bb215d8`
- 服务器 `/opt/hermass` 已对齐到 `bb215d8`
- `hermass-console` 为 `active (running)`
- `http://localhost:8020/chain-studio` 返回 `200`
- `http://localhost:8020/api/chain-studio` 返回 `200` 且 JSON 中 `"ok": true`
- 带 Basic Auth 访问 `http://console.supertrader.world/chain-studio` 返回 `200`
- 带 Basic Auth 访问 `http://console.supertrader.world/api/chain-studio` 返回 `200` 且 JSON 中 `"ok": true`

## 公网 Basic Auth

当前验收账号：

- 用户名：`hermass-test`
- 密码：`Hermass2026!Lab`

浏览器验收地址：

- `http://console.supertrader.world/chain-studio`

命令行验收：

```bash
curl -s -u 'hermass-test:Hermass2026!Lab' -o /dev/null -w "%{http_code}" \
  http://console.supertrader.world/chain-studio

curl -s -u 'hermass-test:Hermass2026!Lab' \
  http://console.supertrader.world/api/chain-studio | head -c 400
```

判断：

- 未带凭证返回 `401`：正常，说明外层鉴权仍生效
- 带凭证返回 `200` 且 API 中 `"ok": true`：公网正常

## 这次 chain-studio 故障的真实根因

不是“不能登录”，也不是“服务器 SSH 没权限”，而是两段式问题：

1. 代码漏推
   - `web/templates/chain-studio.html` 未进入最初提交
   - 导致服务器 `git pull` 后只有路由代码，没有模板文件

2. 数据底座缺失
   - 服务器 `outputs/industry_chain/industry_chain_evidence.duckdb` 必须包含：
     - `chain_studio_overview`
     - `chain_studio_nodes`
     - `chain_studio_events`
     - `chain_studio_candidates`
   - 缺表时 `/api/chain-studio` 会返回 `ok: false`

## 最短排查顺序

1. 先看服务器服务状态

```bash
ssh root@8.130.125.201 'systemctl is-active hermass-console'
```

2. 再看本机接口

```bash
ssh root@8.130.125.201 'curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/chain-studio && echo && curl -s http://localhost:8020/api/chain-studio | head -c 400'
```

3. 若本机正常但公网 `401`

- 不要误判为应用故障
- 先带上 Basic Auth 再测公网

4. 若本机 API 返回缺表错误

- 检查服务器 `outputs/industry_chain/industry_chain_evidence.duckdb`
- 优先确认四张 `chain_studio_*` 表是否存在

## 验收口径

链路全部恢复，必须同时满足：

1. `origin/main` 为 `bb215d8` 或之后的提交
2. 服务器 `/opt/hermass` 对齐远端主分支
3. `hermass-console` 为 `active`
4. `localhost:8020/chain-studio` 返回 `200`
5. `localhost:8020/api/chain-studio` 返回 `"ok": true`
6. `console.supertrader.world` 在带 Basic Auth 情况下可访问

## 备注

- `company-pager-nginx` 是公网真实入口，不要被名字误导。
- `401` 与 `404/500/ok:false` 不是一类问题，不能混排。
- 以后如果再次遇到“公网打不开”，第一反应先区分：
  - 是 Nginx Basic Auth
  - 还是应用路由/模板/数据故障
