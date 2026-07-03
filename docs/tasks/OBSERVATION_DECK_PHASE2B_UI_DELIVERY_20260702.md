# KIMI 交付报告：Observation Deck Phase 2B 首页 UI 落地

日期：2026-07-02
执行者：KIMI

---

## 1. 改了哪些文件

| 文件 | 改动 |
|------|------|
| `web/templates/index.html` | 首页结构收敛为 4 层递进 + 新增胶囊 + 时间窗矩阵移除 + 市场转折信号 + 系统健康折叠 |
| `scripts/validate_website_data_sync.py` | 适配新模块名：移除"3D / 3W / 3M / 6M"，"全市场转折 Top" → "市场转折信号" |

---

## 2. 做了什么

### 2.1 首页结构从 8 个平级模块收敛为 4 层递进

```text
L0: 观象指令栏 → 5 颗胶囊（新增 结构扫描 / 风险扫描）
L1: 状态脉冲 → 6 格数据摘要
L2: 我的标的转折雷达 → 表格 + 行内时间窗标签（3D/3W/3M/6M 已内嵌）
L3: 市场转折信号 → probability_signals 优先，market_top 兜底
   经典策略信号灯 → 一行标签
  系统健康 → 默认折叠
```

### 2.2 具体修改项

| 改动 | 说明 |
|------|------|
| 输入框占位符 | 改为「输入股票代码、State 条件，或点击下方快捷指令」 |
| 新增 2 颗胶囊 | 「结构扫描」「风险扫描」——分别覆盖 D1/W1 转强/转弱扫描和 W1/MN1 逆风/ADX/BB 风险扫描 |
| 移除时间窗矩阵 | 独立 `3D/3W/3M/6M` 全宽卡片已移除；时间窗标签已在雷达表格行内展示 |
| 全市场转折 Top → 市场转折信号 | 新增 `probability_signals` 数据源优先展示；`market_top` 兜底；无数据时显示「暂无市场转折信号数据」 |
| 概率信号展示 | 展示标签（结构转强/结构转弱/持续结构/证据不足）+ 风险标注 + 证据数 + 行业；不展示裸概率百分比 |
| 经典策略信号灯 | 保留不变，一行标签 |
| 系统健康 | 默认折叠（`<details>` 无 `open`），点击展开 |

### 2.3 数据兜底逻辑

```jinja2
{% set prob_sig = observation_deck.probability_signals or {} %}
{% if prob_sig.ok and prob_sig.items %}
  → 展示 probability_signals 数据
{% elif observation_deck.market_top %}
  → 展示 market_top 旧数据（兜底）
{% else %}
  → 显示"暂无市场转折信号数据"
{% endif %}
```

模板不感知 `probability_signals` 字段缺失时不会 500——`or {}` 确保兜底安全。

---

## 3. 本地验收结果

### 3.1 py_compile

```bash
py_compile OK
```

### 3.2 pm_test_preflight.py

```text
17/17 passed
```

完整结果：所有页面 HTTP 200、AI 对话认 401/200、数据日期 2026-07-02、观象词禁通过。

### 3.3 validate_website_data_sync.py

```text
[FAIL] home observation deck missing '市场转折信号'  ← 公网尚未部署新模板，预期行为
```

其余 30+ 条全部通过。部署后该 FAIL 自动消除。

### 3.4 模板文案合规检查

```text
OK: No banned words
  我的观察台: FOUND
  观象指令栏: FOUND
  状态脉冲: FOUND
  我的标的转折雷达: FOUND
  经典策略信号灯: FOUND
  市场转折信号: FOUND
  系统健康: FOUND
  结构扫描: FOUND
  风险扫描: FOUND
  仅作研究观察: FOUND
```

---

## 4. 风险

| 等级 | 内容 | 缓解 |
|------|------|------|
| P0 | 无 | — |
| P1 | `probability_signals` 字段尚未由 KIMI1 写入 `observation_deck` → 前端自动 fallback 到 `market_top` | 兜底逻辑已就位，不阻塞 |
| P2 | 移动端 5 颗胶囊会在窄屏下换行为 2 行 | `flex-wrap: wrap` 已处理 |

---

## 5. 是否可进入 Codex 审计

**可进入。**

Codex 审计重点：
1. `index.html` 模板中 `probability_signals` 兜底逻辑是否正确（不会因字段缺失 500）
2. 系统健康 `<details>` 嵌套是否正确
3. 部署后 `validate_website_data_sync.py` 是否全绿
4. `pm_test_preflight.py` 是否仍 17/17
