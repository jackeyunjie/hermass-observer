# State Timeline Observer Phase 2B 并发分发方案

日期：2026-07-02  
基线提交：`5d320b9`  
当前状态：Phase 2A 已本地和服务器收口，公网已部署  
协调者：Codex  
执行者：`KIMI` / `KIMI1` / `KIMI2`

---

## 一、目标

把 `State Timeline Observer` 从 Phase 2A 推进到 Phase 2B，优先补齐三块能力：

1. 后台异步导出
2. 每日邮件摘要
3. 预计算表与查询切换准备

要求：

- 三路任务尽量不改同一文件
- 先本地实施和验收，不直接上服务器
- 每路都要同步对应文档、注释、验收说明
- 不改 `AGENTS.md`
- 不把 Observer 包装成交易建议系统

---

## 二、当前已知事实

- 代码基线已在 `main`：`5d320b9`
- 服务器 `/opt/hermass` 已部署该提交，`hermass-console` 正常运行
- 公网 `/state-observer`、`/api/state-observer`、`/api/state-observer/timeline` 均已通过冒烟
- `watchlist` 真实接入、变化字段、Agent 只读 SDK 已落地
- `scripts/validate_website_data_sync.py --date 20260701` 已通过
- `scripts/pm_test_preflight.py --date 2026-07-01` 已通过

仍待建设：

- 全市场/大时间窗导出仍是同步
- 缺少邮件摘要脚本
- 缺少 `state_timeline_daily` 预计算产物和切换开关

---

## 三、并发拆分

### 1. `KIMI`

负责：异步导出主线  
目标：新增导出任务 API、后台任务执行、前端导出交互、测试与交付文档

主文件所有权：

- `web/main.py`
- `web/templates/state-observer.html`
- `web/services/state_timeline_export_worker.py`（新）
- `tests/unit/test_state_observer_export*.py`（新）
- `docs/tasks/KIMI_PROMPT_STATE_OBSERVER_PHASE2B_EXPORT_20260702.md`（只读）
- `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2B_EXPORT_DELIVERY_20260702.md`（新）

不要改：

- `config/hermes_cron.json`
- `scripts/send_state_timeline_digest_email.py`
- `scripts/materialize_state_timeline_daily.py`
- `web/services/state_timeline_observer.py`（除非发现阻塞性 bug；如必须改，先在交付说明写明原因）

### 2. `KIMI1`

负责：每日邮件摘要主线  
目标：新增摘要邮件脚本、dry run、cron 条目、文档与最小测试

主文件所有权：

- `scripts/send_state_timeline_digest_email.py`（新）
- `config/hermes_cron.json`
- `tests/unit/test_send_state_timeline_digest_email.py`（新，可选但建议）
- `docs/tasks/KIMI1_PROMPT_STATE_OBSERVER_PHASE2B_EMAIL_20260702.md`（只读）
- `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2B_EMAIL_DELIVERY_20260702.md`（新）

不要改：

- `web/main.py`
- `web/templates/state-observer.html`
- `web/services/state_timeline_observer.py`
- `scripts/materialize_state_timeline_daily.py`

### 3. `KIMI2`

负责：预计算表与切换准备主线  
目标：新增物化脚本、查询层可选切换开关、文档和测试

主文件所有权：

- `scripts/materialize_state_timeline_daily.py`（新）
- `web/services/state_timeline_observer.py`
- `tests/unit/test_materialize_state_timeline_daily.py`（新，可选但建议）
- `docs/tasks/KIMI2_PROMPT_STATE_OBSERVER_PHASE2B_MATERIALIZE_20260702.md`（只读）
- `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2B_MATERIALIZE_DELIVERY_20260702.md`（新）

不要改：

- `web/main.py`
- `web/templates/state-observer.html`
- `config/hermes_cron.json`
- `scripts/send_state_timeline_digest_email.py`

---

## 四、合并顺序

建议合并顺序：

1. `KIMI2` 先合并  
   原因：它会定义物化表结构和查询切换口径，是后续邮件和导出可复用的底层能力。
2. `KIMI` 再合并  
   原因：异步导出需要建立在当前查询接口稳定基础上。
3. `KIMI1` 最后合并  
   原因：邮件摘要是纯消费层，风险最小，最后接 cron 更稳。

如果三路并发同时返回，由 Codex 统一做冲突审计和收口。

---

## 五、统一约束

三路都必须遵守：

1. 先读以下文档再动代码：
   - `docs/STATE_TIMELINE_OBSERVER_SPEC.md`
   - `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2_PLAN_20260701.md`
   - `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2B_IMPLEMENTATION_AUDIT_20260701.md`
   - `docs/tasks/STATE_TIMELINE_OBSERVER_PHASE2A_DELIVERY_20260701.md`
2. 不得把邮件、导出、预计算包装成买卖建议输出
3. 不得引入新的重型外部依赖
4. 服务器不改代码，只做后续部署
5. 本地验收至少包含：
   - `py_compile`
   - 对应单测或最小脚本验收
6. 最终回复必须包含：
   - 改了哪些文件
   - 本地如何验收
   - 还有哪些未做

---

## 六、统一回收格式

要求三路返回时按下面格式：

```text
1. 完成内容
2. 修改文件
3. 本地验收命令与结果
4. 风险 / 未完成项
5. 是否可进入 git add / commit / push
```

---

## 七、Codex 收口职责

Codex 后续负责：

1. 审 KIMI 三路线代码和文档
2. 解决潜在冲突
3. 统一补验收
4. 本地提交与 push
5. 服务器部署与公网冒烟

