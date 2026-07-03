# Observation Deck Phase 2B Codex Audit

日期：2026-07-02
执行者：Codex

## 1. 审计范围

本轮覆盖：

- KIMI1：Observation Deck 转折概率首页适配层
- KIMI：Observation Deck Phase 2B 首页 UI 落地

不包含 KIMI2。

## 2. Codex 修正

| 文件 | 修正 |
|---|---|
| `web/templates/index.html` | 修复 `prob_sig.items` 与 Python dict `.items()` 方法冲突导致的首页 500，改用 `prob_sig.get('items', [])` |
| `web/templates/index.html` | 移除系统健康区重复 `</details>` |
| `web/services/observation_deck_probability.py` | 异常 `confidence` 防御，避免非数字值导致首页失败 |
| `web/main.py` | 首页市场摘要中的百分比数字替换为非数字短语，避免裸百分比误读 |
| `tests/unit/test_observation_deck_probability.py` | 增加异常 `confidence` 降级测试 |

## 3. 审计结论

- 首页已从独立时间窗矩阵切换为更收敛的“市场转折信号”结构。
- 概率适配层没有把 `prob_turn_up` / `confidence` 等裸概率字段透给首页模板。
- 首页展示结构标签、证据数量、风险标签，不展示概率百分比。
- 经典策略信号灯保持独立，不参与概率或 State 主判断。
- 系统健康默认折叠。

## 4. 本地验收

```bash
.venv/bin/python -m py_compile \
  web/main.py \
  web/services/observation_deck_probability.py \
  web/services/turning_point_probability_reader.py \
  scripts/validate_website_data_sync.py

.venv/bin/python -m pytest \
  tests/unit/test_observation_deck_probability.py \
  tests/unit/test_turning_point_probability_reader.py \
  tests/unit/test_classic_strategy_sentinel.py -q

HERMASS_SITE_URL=http://127.0.0.1:8020 \
  .venv/bin/python scripts/validate_website_data_sync.py --date 20260702

.venv/bin/python scripts/pm_test_preflight.py --date 2026-07-02
```

结果：

- 相关单测：60 passed
- 本地网站同步：全绿
- PM preflight：17/17 passed

## 5. 页面检查

- 首页 HTTP 200
- 包含：我的观察台、结构扫描、风险扫描、经典策略信号灯、市场转折信号、系统健康
- 交易动作禁用词：无命中
- 裸百分比业务文案：无命中，剩余 `%` 仅在 CSS / SVG 中
- 市场转折信号展示：证据不足、低置信、N 项证据

## 6. 剩余风险

- 当前转折概率 MVP 大多输出“证据不足 / 低置信”，符合保守口径，但产品体验会偏弱。
- 首页 UI 仍是 Jinja2 原生模板，后续如果继续增加交互，需谨慎避免模板字段名与 dict 方法冲突。
