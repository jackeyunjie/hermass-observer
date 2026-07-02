# State Timeline Phase 2C UI Finish · 2026-07-02

## 本次补齐范围

在既有 Phase 2C 后端、订阅派发、物化表运行时开关基础上，补齐产品闭环缺口：

1. 站内订阅入口
2. 订阅参数校验加固
3. 导出与查询对 `materialized` 选择的一致性

## 修改文件

- `web/templates/state-observer.html`
- `web/services/state_timeline_export_worker.py`
- `agently_adapter/tools/user_tasks.py`
- `web/main.py`
- `tests/unit/test_state_observer_export.py`
- `tests/unit/test_user_tasks_api.py`

## 具体变更

### 1. State Observer 页面新增站内订阅入口

页面新增「邮件订阅」区域，支持：

- 输入接收邮箱
- 选择订阅集合：`Top50 / 自选池 / 全市场`
- 选择时间窗口：`1..120` 天
- 创建订阅
- 刷新订阅列表
- 取消当前用户自己的订阅

访客与登录用户都走同一套 API；访客依赖 `hermass_visitor_id` 做隔离。

### 2. 查询参数新增物化表模式选择

页面查询区新增「查询模式」：

- 跟随系统默认
- 强制预计算表
- 强制实时查询

该选择同时透传到：

- `GET /api/state-observer`
- `POST /api/state-observer/export`
- 同步 CSV 导出 URL

避免页面查询与导出走不同数据路径。

### 3. 订阅参数后端校验加固

`create_state_timeline_subscription()` 新增：

- 非法邮箱返回 `invalid_email`
- 非法天数返回 `invalid_days`
- 非法集合返回 `invalid_symbol_set`

允许集合仅为：

- `top50`
- `watchlist`
- `all`

`web/main.py` 订阅创建接口对以上错误统一返回 HTTP `400`。

### 4. 导出 worker 保留 materialized 选择

异步导出任务原先会丢失 `materialized` 参数，现已修复：

- 任务归一化参数保留 `materialized`
- 行数估算保留 `materialized`
- 后台导出查询保留 `materialized`
- 同步导出 URL 保留 `materialized`

## 本地验收

```bash
cd /Users/lv111101/Documents/hermass-observer-product
source .venv/bin/activate

python -m py_compile \
  web/main.py \
  web/services/state_timeline_export_worker.py \
  agently_adapter/tools/user_tasks.py \
  scripts/send_state_timeline_digest_email.py \
  tests/unit/test_user_tasks_api.py \
  tests/unit/test_state_observer_export.py

python -m pytest \
  tests/unit/test_state_observer_api.py \
  tests/unit/test_user_tasks_api.py \
  tests/unit/test_state_observer_export.py \
  tests/unit/test_send_state_timeline_digest_email.py \
  tests/unit/test_state_timeline_runtime_switch.py -q
```

结果：

- `py_compile` 全部通过
- `pytest`：`55 passed`

## 当前状态

Phase 2C 现在具备完整最小闭环：

- 异步导出 owner 隔离
- 邮件订阅 CRUD
- 订阅派发 cron
- 物化表运行时开关
- 站内订阅入口

## 下一步

1. 合并并提交当前 Phase 2C 本地改动
2. 部署到服务器
3. 公网验证：
   - `/state-observer` 页面
   - 订阅创建 / 列表 / 取消
   - 导出 owner 403
   - `materialized=1/0` 查询
