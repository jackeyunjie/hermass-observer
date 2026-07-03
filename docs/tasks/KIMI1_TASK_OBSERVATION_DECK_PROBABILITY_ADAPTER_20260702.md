# KIMI1 任务：Observation Deck 转折概率首页适配层

日期：2026-07-02

## 背景

转折概率只读 API 已上线：

- `/api/turning-point-probability/summary`
- `/api/turning-point-probability/signals`
- `/api/turning-point-probability/stock`

但首页模板不应直接处理概率字段，也不应展示裸概率百分比。需要一个后端适配层，把概率数据转换成 Research-Only 的结构标签，供首页展示。

## 你的任务

新增首页概率适配层：

1. 新增 `web/services/observation_deck_probability.py`
2. 从 `web.services.turning_point_probability_reader` 读取 `3W` / `3M` 窗口信号。
3. 把 `turning_type` 映射为安全展示标签：
   - `turn_up` → `结构转强`
   - `turn_down` → `结构转弱`
   - `continue` → `持续结构`
   - `false_breakout` → `假突破风险`
   - `uncertain` → `证据不足`
4. 不返回裸概率百分比到首页 contract。
5. 在 `web/main.py` 的 `_observation_deck_data()` 中加入：

```python
"probability_signals": build_observation_deck_probability_signals(limit=5)
```

6. 缺产物或读取失败时返回 `ok=true`、`items=[]`、`warning`，不得影响首页。

## 输出契约

```python
{
    "ok": True,
    "date": "2026-07-02",
    "warning": "",
    "items": [
        {
            "stock_code": "000001.SZ",
            "stock_name": "平安银行",
            "window": "3W",
            "label": "证据不足",
            "tone": "muted",
            "evidence_count": 2,
            "risk_label": "低置信",
            "industry_l1": "银行",
            "research_url": "/research?stock_code=000001.SZ"
        }
    ]
}
```

## 可改文件

允许：

- `web/services/observation_deck_probability.py`
- `web/main.py`
- `tests/unit/test_observation_deck_probability.py`
- `docs/tasks/OBSERVATION_DECK_PROBABILITY_ADAPTER_DELIVERY_20260702.md`

不要修改：

- `web/templates/index.html`
- `web/templates/sentinel_*`
- `scripts/build_turning_point_probability.py`
- `web/services/turning_point_probability_reader.py`，除非发现明确 bug
- Agent / Ledger / State Cube 相关代码

## 设计约束

- 只读，不写文件、不写数据库。
- 不调用 HTTP，请直接调用 reader 服务函数。
- 不展示或返回 `prob_turn_up` / `prob_turn_down` / `confidence` 这类裸概率数字到首页 contract。
- 可用 `confidence` 内部决定 `risk_label`，但输出给首页只能是标签。
- `research_url` 必须使用 `urllib.parse.quote` 编码股票代码。

## 验收

```bash
.venv/bin/python -m py_compile web/main.py web/services/observation_deck_probability.py
.venv/bin/python -m pytest tests/unit/test_observation_deck_probability.py -q
.venv/bin/python scripts/validate_website_data_sync.py --date 20260702
.venv/bin/python scripts/pm_test_preflight.py --date 2026-07-02
```

本地可选：

```bash
.venv/bin/python - <<'PY'
from web.services.observation_deck_probability import build_observation_deck_probability_signals
r = build_observation_deck_probability_signals(limit=5)
print(r["ok"], len(r["items"]), r.get("warning", ""))
print(r["items"][0] if r["items"] else "empty")
PY
```

## 返回格式

1. 改了哪些文件
2. 输出契约样例
3. 本地验收结果
4. 风险 / 未完成项
5. 是否可进入 Codex 审计
