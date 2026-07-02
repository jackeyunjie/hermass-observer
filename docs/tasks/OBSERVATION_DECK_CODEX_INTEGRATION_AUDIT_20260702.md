# Observation Deck Codex Integration Audit

日期：2026-07-02
执行者：Codex

## 1. 审计范围

本轮审计覆盖 KIMI / KIMI1 / KIMI2 三条交付线：

- Observation Deck Phase 1 公网验收文档
- Classic Strategy Sentinel MVP
- Turning Point Probability MVP

## 2. Codex 修正

| 文件 | 修正 |
|---|---|
| `web/templates/index.html` | 首页 `<title>` 改为 `我的观察台 · Hermass` |
| `web/main.py` | 首页经典策略信号灯标签改为跳转 `/sentinel/{strategy}?date=...` |
| `scripts/build_turning_point_probability.py` | CLI `--foundation` 参数透传给构建函数 |

## 3. 边界结论

- 经典策略哨兵保持独立：只读策略信号产物，不写 State Cube / Decision Ledger，不进入 Agent 辩论。
- 首页仅展示经典策略标签和数量，不展示原始交易规则条文。
- 原始规则条文只在 `/sentinel/detail` 展示，并带 Research-Only 免责声明。
- 转折概率脚本只生成离线产物，当前不接首页、不接 Agent、不输出交易动作。
- 2026-07-02 State Cube 缺目标日期时，概率脚本降级使用 Foundation DB，符合 MVP 设计。

## 4. 本地验收

```bash
.venv/bin/python -m py_compile \
  web/main.py \
  web/services/classic_strategy_sentinel.py \
  scripts/build_turning_point_probability.py \
  scripts/validate_website_data_sync.py

.venv/bin/python -m pytest \
  tests/unit/test_classic_strategy_sentinel.py \
  tests/unit/test_turning_point_probability.py -q

.venv/bin/python -m pytest \
  tests/unit/test_state_observer_api.py \
  tests/unit/test_strategy_signals.py -q

.venv/bin/python scripts/build_turning_point_probability.py --date 2026-07-02
.venv/bin/python scripts/validate_website_data_sync.py --date 20260702
.venv/bin/python scripts/pm_test_preflight.py --date 2026-07-02
```

结果：

- 哨兵 + 转折概率单测：35 passed
- State Observer + 策略信号回归：70 passed
- 转折概率产物：22,076 行
- Website data sync：全绿
- PM preflight：17/17 passed

## 5. 本地 HTTP 冒烟

- `/sentinel`：200
- `/sentinel/vcp?date=2026-07-02`：200
- `/api/sentinel/overview?date=2026-07-02`：200
- 首页 title：`我的观察台 · Hermass`
- 首页经典策略标签：跳转 `/sentinel/...`
- 首页禁用词扫描：无命中

## 6. 剩余 P2

- 移动端暂无汉堡折叠菜单，作为体验增强留到后续 UI 收口。
