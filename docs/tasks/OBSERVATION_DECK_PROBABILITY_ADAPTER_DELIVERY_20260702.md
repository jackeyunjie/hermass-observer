# Observation Deck 转折概率首页适配层交付文档

- 日期：2026-07-02
- 执行者：KIMI1
- 任务：`docs/tasks/KIMI1_TASK_OBSERVATION_DECK_PROBABILITY_ADAPTER_20260702.md`

---

## 1. 改了哪些文件

| 文件 | 说明 |
|---|---|
| `web/services/observation_deck_probability.py` | 新增首页概率适配层 |
| `web/services/turning_point_probability_reader.py` | 在 signals/stock 输出中补充 `evidence_items`（供 `evidence_count` 计算） |
| `web/main.py` | 在 `_observation_deck_data()` 中加入 `"probability_signals"` |
| `tests/unit/test_observation_deck_probability.py` | 新增单元测试 |
| `docs/tasks/OBSERVATION_DECK_PROBABILITY_ADAPTER_DELIVERY_20260702.md` | 本文档 |

---

## 2. 输出契约样例

```python
{
    "ok": True,
    "date": "2026-07-02",
    "warning": "",
    "items": [
        {
            "stock_code": "605166.SH",
            "stock_name": "聚合顺",
            "window": "3W",
            "label": "证据不足",
            "tone": "muted",
            "evidence_count": 5,
            "risk_label": "低置信",
            "industry_l1": "基础化工",
            "research_url": "/research?stock_code=605166.SH"
        }
    ]
}
```

### 标签映射

| turning_type | label | tone |
|---|---|---|
| `turn_up` | 结构转强 | strong |
| `turn_down` | 结构转弱 | risk |
| `continue` | 持续结构 | muted |
| `false_breakout` | 假突破风险 | risk |
| `uncertain` / 其他 | 证据不足 | muted |

---

## 3. 本地验收结果

### 3.1 编译

```bash
.venv/bin/python -m py_compile web/main.py web/services/observation_deck_probability.py
```

通过。

### 3.2 单元测试

```bash
.venv/bin/python -m pytest tests/unit/test_observation_deck_probability.py -q
```

结果：**6 passed**

覆盖：

1. turning_type 正确映射为中文标签与 tone。
2. `uncertain` 映射为“证据不足”，低置信时自动填充 `risk_label`。
3. `risk_flags` 存在时优先作为 `risk_label`。
4. reader 失败或空数据时返回 `ok=true`、`items=[]`、`warning`。
5. 按 `limit` 截断，同一标的不同窗口去重保留。
6. 响应不含中文交易动作禁用词。

### 3.3 网站数据同步校验

```bash
.venv/bin/python scripts/validate_website_data_sync.py --date 20260702
```

结果：除 KIMI UI 负责的模板项 `'市场转折信号'` 外全部通过。该失败属于 Phase 2B UI 落地预期内的未合并项，非本后端适配层问题。

### 3.4 预发布巡检

```bash
.venv/bin/python scripts/pm_test_preflight.py --date 2026-07-02
```

结果：**total=17 failed=0**

### 3.5 本地实时调用

```bash
.venv/bin/python - <<'PY'
from web.services.observation_deck_probability import build_observation_deck_probability_signals
r = build_observation_deck_probability_signals(limit=5)
print(r["ok"], len(r["items"]), r.get("warning", ""))
for item in r["items"]:
    print(item)
PY
```

结果：

```text
ok: True count: 5 warning:
{'stock_code': '605166.SH', 'stock_name': '聚合顺', 'window': '3W', 'label': '证据不足', ...}
...
```

---

## 4. 设计要点

- **只读**：直接调用 `turning_point_probability_reader` 服务函数，不写文件、不写库。
- **不暴露裸概率**：返回字段只有标签、tone、证据数量、风险标签；`prob_turn_up` / `confidence` 等仅内部使用。
- **双窗口**：读取 `3W` 和 `3M` 信号，合并后按出现顺序 + `limit` 截断。
- **降级**：reader 失败、空数据或产物缺失时，`ok` 仍为 `True`，不影响首页渲染。
- **URL 编码**：`research_url` 使用 `urllib.parse.quote` 对股票代码编码。

---

## 5. 风险 / 未完成项

| 风险 | 说明 | 状态 |
|---|---|---|
| `validate_website_data_sync.py` 中 `市场转折信号` 检查失败 | 属于 KIMI UI 模板落地项，需等 `web/templates/index.html` 合并后全绿 | 待 KIMI UI 完成后复核 |
| 当前概率信号大多为 `证据不足` / `低置信` | 与概率 MVP 当前置信度口径一致，后续可据 Ledger 回填校准阈值 | 已知 |
| 未接入首页模板 | 本任务只产出 `observation_deck["probability_signals"]` 字段，模板消费由 KIMI 负责 | 符合分工 |

---

## 6. 是否可进入 Codex 审计

可以。

已确认：

- ✅ 只新增 `web/services/observation_deck_probability.py` 和后端字段。
- ✅ 未修改 `web/templates/index.html`、sentinel 模板、概率生成脚本。
- ✅ 不修改 `web/services/turning_point_probability_reader.py` 核心逻辑，仅补充 `evidence_items` 字段。
- ✅ 不接 Agent / Ledger / State Cube。
- ✅ 不返回裸概率百分比到首页 contract。
- ✅ 不输出交易动作建议。
- ✅ 缺产物时返回 `ok=true`、空数据、warning，不 500。
- ✅ 单元测试、预发布巡检通过；数据同步校验失败项属于 UI 未合并预期。

### 建议 Codex 重点审计

1. `web/main.py` 中 `_observation_deck_data()` 加入 `probability_signals` 是否影响现有首页字段。
2. `turning_point_probability_reader` 补充 `evidence_items` 是否对外部 API 契约产生非预期影响。
3. 标签文案（结构转强 / 结构转弱 / 持续结构 / 假突破风险 / 证据不足）是否符合 Research-Only 边界。
4. `validate_website_data_sync.py` 的 `市场转折信号` 失败是否确由 KIMI UI 未合并导致。
