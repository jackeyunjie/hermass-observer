# Classic Strategy Sentinel 加固验收交付文档

日期：2026-07-02
执行者：KIMI2
任务来源：`docs/tasks/KIMI2_TASK_CLASSIC_SENTINEL_HARDENING_20260702.md`

---

## 1. 改了哪些文件

| 文件 | 修改内容 |
|------|----------|
| `web/services/classic_strategy_sentinel.py` | 增加 `_sanitize_row` 统一清洗字段；`_row_confidence` 对异常值做 [0,1] 钳制；DuckDB 查询结果也经过清洗 |
| `web/templates/sentinel_overview.html` | URL 参数使用 `\|urlencode`，HTML 输出显式使用 `\|e`；空状态文案强化 |
| `web/templates/sentinel_detail.html` | URL 参数使用 `\|urlencode`，HTML 输出显式使用 `\|e`；空状态文案强化 |
| `tests/unit/test_classic_strategy_sentinel.py` | 新增 `TestRealSchemaCompatibility` 和 `TestInjectionSafety` 两类共 17 个用例 |

**未修改：** `web/main.py`、`web/templates/index.html`、State/Ledger/Agent 相关代码、概率脚本。

---

## 2. 加固了哪些边界

### 2.1 真实 schema 兼容

审计 `outputs/strategy_signals/strategy_signal_daily_latest.json`（`strategy_signal_daily_v2`，567 条记录）后，确认并处理以下真实字段风险：

| 字段 | 真实数据情况 | 加固措施 |
|------|-------------|----------|
| `stock_name` | 1 条为空 | 空值/None 统一归为空字符串 |
| `signal_strength` | 范围 0.15–0.9，无异常 | 新增防御：负值、>1、NaN、inf、非数字字符串均钳制到 [0,1] |
| `strategy_id` | 均为允许策略或 atr_chandelier | 空/非法 strategy_id 直接丢弃 |
| `stock_code` | 均非空 | 空 stock_code 直接丢弃 |
| `signal_type` | entry / exit / risk / structure | 空 signal_type 仍保留，按互斥规则处理 |
| 其他可选字段（`vcp_entry_confirmation` 等） | 大量 None | 服务层不依赖这些字段做核心判断 |

### 2.2 模板注入防护

- 所有 URL 查询参数使用 `\|urlencode` 过滤器（`date`、`strategy`、`stock_code`）。
- 所有动态 HTML 文本使用 `\|e` 显式转义（`display_name`、`stock_code`、`stock_name`、`signal_display_text`、`rule.*` 等）。
- `&` 在 href 中写成 `&amp;` 以符合 HTML 规范。

### 2.3 Research-Only 边界

- `/sentinel` 和 `/sentinel/{strategy}` 页面顶部均展示免责声明。
- `/sentinel/detail` 页面顶部固定展示：
  > 以下为经典策略原始规则触发说明，仅作研究观察，不构成交易建议。
- Overview API 文本经单元测试验证，不包含买入/卖出/加仓/减仓/清仓/空仓/加杠杆/止盈/止损/目标价/收益承诺/推荐买/推荐卖/适合交易/入场/出场/买点/卖点/仓位。
- 所有哨兵 API 文本经单元测试验证，不包含「同向/冲突/领先/转折概率」等 State 混合判断词。

### 2.4 空状态文案

- `/sentinel` 无信号时：
  > **当日无规则信号**
  > 未检测到 VCP / 2560 / 布林强盗的 entry / exit / risk 规则触发。
- `/sentinel/{strategy}` 无信号时：
  > **当日无该策略信号**
  > 未找到 {display_name} 在 {date} 的 entry / exit / risk 规则触发。

---

## 3. 本地验收结果

### 3.1 单元测试

```bash
.venv/bin/python -m pytest tests/unit/test_classic_strategy_sentinel.py -q
```

结果：

```text
43 passed
```

### 3.2 验收脚本

```bash
.venv/bin/python scripts/validate_website_data_sync.py --date 20260702
.venv/bin/python scripts/pm_test_preflight.py --date 2026-07-02
```

结果：

- `validate_website_data_sync.py`：全部通过（包含首页「经典策略信号灯」等文案检查）。
- `pm_test_preflight.py`：**17/17 passed**。

### 3.3 本地页面冒烟

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8020/sentinel
curl -s "http://127.0.0.1:8020/api/sentinel/overview?date=2026-07-02" | head -c 500
```

使用 TestClient 验证：

- `/sentinel?date=2026-07-02` → 200，含免责声明，正确展示真实信号。
- `/sentinel/vcp?date=2026-07-02` → 200，含「VCP 收缩释放」。
- `/sentinel/detail?strategy=vcp&stock_code=000021.SZ&date=2026-07-02` → 200，含免责声明与条件检查。

---

## 4. 风险 / 未完成项

| 风险 | 说明 | 处理状态 |
|------|------|---------|
| `trigger_price` 字段缺失 | 真实 schema 无简单 `trigger_price` 字段；`vcp_entry_confirmation` 为结构化对象。本实现未在 API 中暴露价格字段，避免返回不一致结构。 | 已在 MVP 中接受；如需价格需在 signal_ledger 阶段统一补全 |
| 模板 `\|e` 与 Jinja2 autoescape 重复 | 显式 `\|e` 是防御性编码，不影响功能。 | 已保留 |
| DuckDB fallback 路径 | 已用只读连接并统一经过 `_sanitize_row` 清洗。 | 已加固 |

---

## 5. 是否可进入 Codex 审计

是。本次加固：

- 未扩大产品范围；
- 未修改 `web/main.py` 或首页；
- 未触碰 State / Ledger / Agent / 概率脚本；
- 所有验收命令均通过；
- 新增测试覆盖真实 schema、异常 confidence、注入防护等关键边界。
