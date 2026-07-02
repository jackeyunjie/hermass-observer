# KIMI1 提示词：State Timeline Observer Phase 2B 每日邮件摘要

日期：2026-07-02  
执行者：KIMI1  
协调与收口：Codex

---

## 一、使用方式

把下面整段直接发给 `KIMI1` 执行。

---

## 二、发给 KIMI1 的完整提示词

你现在在 Hermass Observer 项目里执行 `State Timeline Observer` Phase 2B 的“每日邮件摘要”子任务。

先读以下文档，再动代码：

- `docs/STATE_TIMELINE_OBSERVER_SPEC.md`
- `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2_PLAN_20260701.md`
- `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2B_IMPLEMENTATION_AUDIT_20260701.md`
- `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2A_DELIVERY_20260701.md`

再参考现有邮件脚本风格：

- `scripts/send_m30_second_wave_email.py`
- `config/hermes_cron.json`

当前基线：

- `main` 已到 `5d320b9`
- State Timeline 查询层与页面已上线
- `watchlist` 与变化字段已可读

你的目标只有一条：

```text
增加一个可 dry-run 的 State Timeline 每日摘要邮件脚本，并把 cron 配置接好。
```

---

### A. 任务边界

你只负责邮件摘要，不负责：

- 异步导出 API
- 预计算表脚本
- 服务器部署

优先修改文件：

- `scripts/send_state_timeline_digest_email.py`（新建）
- `config/hermes_cron.json`
- `tests/unit/test_send_state_timeline_digest_email.py`（可新建，建议）
- `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2B_EMAIL_DELIVERY_20260702.md`（新建）

不要改：

- `web/main.py`
- `web/templates/state-observer.html`
- `web/services/state_timeline_observer.py`
- `scripts/materialize_state_timeline_daily.py`

---

### B. 要实现的能力

新增脚本：

```text
scripts/send_state_timeline_digest_email.py
```

脚本要求：

1. 支持：
   - `--date YYYY-MM-DD`
   - `--dry`
   - 可选 `--symbol-set`
   - 可选 `--days`
2. `--dry` 时只输出 HTML，不发送真实邮件
3. 邮件读取环境变量：
   - `HERMASS_SMTP_HOST`
   - `HERMASS_SMTP_PORT`
   - `HERMASS_SMTP_USER`
   - `HERMASS_SMTP_PASS`
   - `HERMASS_REPORT_TO`
4. 数据来源直接复用现有 State Timeline 查询/SDK，不绕 HTTP
5. 邮件正文必须包含免责语：
   - `仅作研究观察，不构成交易建议`

邮件内容结构必须至少包含：

1. 顶部摘要：日期、样本数、变化数
2. 月线 EF 样本
3. 周线 EF 样本
4. 日线 EF 样本
5. 月线 A/B 样本
6. 周线 A/B 样本
7. 日线 A/B 样本
8. 月线 0 样本
9. 周线 0 样本
10. 日线 0 样本
11. 最近状态变化 TopN
12. 如 watchlist 有数据，附上 watchlist 最近 3 天变化
13. 底部回链 `/state-observer`

注意：

- 不输出买入、卖出、止损、目标价
- 不把 `ef_count` 作为唯一主口径
- 分周期事件族必须保留

---

### C. cron 要求

请直接修改：

```text
config/hermes_cron.json
```

至少新增 2 个条目：

1. `State Timeline 每日邮件摘要`
2. `State Timeline 导出产物清理`

其中：

- 邮件摘要建议在交易日 `16:30`
- 导出清理建议在每日 `02:00`

如果你认为导出清理不应由邮件线来接，也可以只先写邮件 cron，但要在交付文档中明确说明。

---

### D. 风险控制

1. 不要直接发真实邮件做验收，默认用 `--dry`
2. 不要改 Web 页面
3. 不要引入新的邮件库，优先用标准库或项目已有模式
4. 不要把 watchlist 缺失当成错误
5. 不要把 cron 写到别的文件

---

### E. 本地验收要求

至少执行并记录结果：

```bash
cd /Users/lv111101/Documents/hermass-observer-product
.venv/bin/python -m py_compile scripts/send_state_timeline_digest_email.py
.venv/bin/python scripts/send_state_timeline_digest_email.py --date 2026-07-01 --dry > /tmp/state_timeline_digest_20260701.html
```

如果你补了单测，也要给出：

```bash
.venv/bin/python -m pytest tests/unit/test_send_state_timeline_digest_email.py -q
```

---

### F. 回复格式

完成后只按下面格式回复：

```text
1. 完成内容
2. 修改文件
3. 本地验收命令与结果
4. 风险 / 未完成项
5. 是否可进入 git add / commit / push
```

