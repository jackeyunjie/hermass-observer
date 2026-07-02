# Observation Deck Phase 2 Codex Audit

日期：2026-07-02
执行者：Codex

## 1. 审计范围

本轮审计覆盖三条并发任务：

- KIMI：Observation Deck Phase 2 产品 / UI 收敛方案
- KIMI1：Turning Point Probability 只读消费 API
- KIMI2：Classic Strategy Sentinel 加固验收

## 2. Codex 修正

| 文件 | 修正 |
|---|---|
| `web/services/turning_point_probability_reader.py` | 规范化 `window` 大小写；限制 `limit` 到 `[1, 500]`；规范化 `stock_code` 大写；固定输出字段顺序 |
| `tests/unit/test_turning_point_probability_reader.py` | 增加 `window=3w`、`limit=9999`、小写股票代码的回归测试 |

## 3. 审计结论

- 概率 API 是只读消费层，不接首页、不写 Ledger、不进入 Agent 辩论。
- 概率 API 缺产物时返回 `ok=true` + warning + 空结构，不 500。
- 经典策略哨兵加固保持隔离：只读策略信号产物，不混入 State 概率。
- 哨兵模板已对 URL 参数和 HTML 文本做转义。
- 首页仍保持 Research-Only，禁用词扫描无命中。

## 4. 本地验收

```bash
.venv/bin/python -m py_compile \
  web/main.py \
  web/services/classic_strategy_sentinel.py \
  web/services/turning_point_probability_reader.py

.venv/bin/python -m pytest \
  tests/unit/test_classic_strategy_sentinel.py \
  tests/unit/test_turning_point_probability_reader.py -q

.venv/bin/python scripts/validate_website_data_sync.py --date 20260702
.venv/bin/python scripts/pm_test_preflight.py --date 2026-07-02
```

结果：

- 相关单测：53 passed
- `validate_website_data_sync.py`：全绿
- `pm_test_preflight.py`：17/17 passed

## 5. 本地 HTTP 冒烟

- `/api/turning-point-probability/summary`：200，`row_count=22076`
- `/api/turning-point-probability/signals?window=3w&limit=9999`：200，返回 `window=3W`，`limit=500`
- `/api/turning-point-probability/stock?stock_code=000001.sz`：200，返回 `stock_code=000001.SZ`
- `/sentinel`：200
- `/api/sentinel/overview?date=2026-07-02`：200
- 概率 summary 禁用词扫描：无命中

## 6. 剩余风险

- KIMI 的 Phase 2 UI 收敛目前是方案文档，尚未实施首页模块收敛。
- 概率 API 暴露裸概率字段，仅限 API 层；未来接首页时必须转换为结构标签，不直接展示百分比。
- 服务器 `.venv` 目前未安装 `pytest`，服务器侧部署验收以 py_compile、网站数据同步、PM preflight 和公网冒烟为准。
