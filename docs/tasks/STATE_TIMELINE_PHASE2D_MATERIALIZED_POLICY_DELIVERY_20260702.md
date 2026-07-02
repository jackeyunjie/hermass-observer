# State Timeline Phase 2D 物化表默认启用策略交付说明

日期：2026-07-02  
执行者：KIMI2  
审计：Codex  

---

## 一、完成内容

### 1. 默认启用策略

- `materialized=None` 时默认走智能 auto 策略：
  - 单日查询 + 物化文件存在且健康 → 优先使用物化表
  - 跨天查询 → 自动回退实时 CTE
  - 文件缺失/损坏 → 自动回退实时 CTE
- 环境变量 `USE_STATE_TIMELINE_MATERIALIZED` 默认值由 `0` 改为 `1`，作为全局默认启用开关；设置为 `0` 可全局关闭默认 auto。

### 2. 自动回退可解释性

API 返回 `meta` 中新增三个字段：

- `materialized_requested`: 调用方传入值（True/False/None）
- `materialized_used`: 实际是否命中物化表
- `materialized_reason`: 决策原因，例如：
  - `auto_single_day_hit`
  - `auto_fallback_multi_day`
  - `auto_fallback_missing_file`
  - `auto_env_disabled`
  - `force_on_hit`
  - `force_on_incompatible_multi_day`
  - `force_on_missing_file`
  - `force_off`

### 3. 显式强制不回退

- `materialized=True` 显式强制时，若条件不满足（跨天 / 文件缺失）直接返回错误，不回退 CTE。
- `materialized=False` 显式强制时，始终使用实时 CTE。

### 4. 状态接口补强

`/api/admin/data-sync-status` 的 `state_timeline_materialized` 字段扩展为：

- `path`
- `exists`
- `size`
- `date`
- `row_count`
- `healthy`
- `enabled_by_default`
- `auto_would_use`

### 5. 页面状态 badge 保留

`web/templates/state-observer.html` 已存在的物化表状态 badge 继续工作，显示文件存在状态与行数。

---

## 二、修改文件

| 文件 | 说明 |
|------|------|
| `web/services/state_timeline_observer.py` | 默认策略、决策 helper、可解释字段、显式强制错误处理 |
| `web/main.py` | 透传 `materialized` 参数；补强 `data-sync-status` |
| `tests/unit/test_state_timeline_runtime_switch.py` | 新增/增强默认策略与强制开关测试 |
| `tests/unit/test_state_timeline_materialize.py` | 更新默认开关断言为默认启用 |
| `docs/tasks/STATE_TIMELINE_PHASE2D_MATERIALIZED_POLICY_DELIVERY_20260702.md` | 本文档 |

未修改：
- `web/templates/state-observer.html` 订阅 UI
- `web/services/state_timeline_export_worker.py`
- `scripts/send_state_timeline_digest_email.py`

---

## 三、本地验收命令与结果

```bash
cd /Users/lv111101/Documents/hermass-observer-product
source .venv/bin/activate

python -m py_compile web/services/state_timeline_observer.py web/main.py
python -m pytest tests/unit/test_state_timeline_runtime_switch.py -q
python -m pytest tests/unit/test_state_timeline_reader.py tests/unit/test_state_timeline_materialize.py tests/unit/test_state_timeline_runtime_switch.py -q
```

结果：
- `py_compile`：通过
- `test_state_timeline_runtime_switch.py`：15 passed
- 全部 State Timeline 单测：37 passed

本地服务冒烟（uvicorn）验证：

```text
默认单日查询 -> materialized_used=True, reason=auto_single_day_hit
跨天查询     -> materialized_used=False, reason=auto_fallback_multi_day
materialized=0 -> materialized_used=False, reason=force_off
materialized=1 -> materialized_used=True, reason=force_on_hit
materialized=1 跨天 -> ok=False, error=materialized=True 仅支持单日查询
data-sync-status -> exists=True, row_count=5519, healthy=True, enabled_by_default=True, auto_would_use=True
```

---

## 四、风险 / 未完成项

### 风险

1. **默认启用变更**：`USE_STATE_TIMELINE_MATERIALIZED` 默认值改为 `True`。如果线上环境不希望默认启用，需要在部署前显式设置 `USE_STATE_TIMELINE_MATERIALIZED=0`，或确认物化文件每日正常生成。
2. **显式 True 报错**：调用方若传 `materialized=1` 做跨天查询，会收到 500（ok=False），而不是以前静默回退。这是预期行为，但需前端/调用方知晓。
3. **物化文件损坏**：`_state_timeline_materialized_status` 会检测连接失败并把 `healthy` 标为 False，但默认 auto 查询仍会在连接失败时回退 CTE（通过 try-except）。

### 未完成项

- 未接入 cron（按任务要求不碰）。
- 未改动导出任务日志实现。
- 未增加邮件/订阅功能。

---

## 五、是否可进入 git add / commit / push

**可以。**

前提：
1. 确认产品主线未在同一时间修改 `web/services/state_timeline_observer.py` 的同一函数，避免合并冲突。
2. 若线上希望默认关闭，在服务器 systemd drop-in 或 `.env` 中设置 `USE_STATE_TIMELINE_MATERIALIZED=0`。
3. 部署后执行固定冒烟：
   ```bash
   curl -s "http://localhost:8020/api/state-observer?symbol_set=top50&days=1&page_size=1" | head -c 200
   curl -s "http://localhost:8020/api/admin/data-sync-status" | grep state_timeline_materialized
   ```
