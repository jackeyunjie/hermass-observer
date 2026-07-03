# KIMI 任务：Observation Deck Phase 2B 首页 UI 落地

日期：2026-07-02

## 背景

KIMI 已完成 Phase 2 产品/UI 收敛方案：

- 首页不做加法，只做减法
- 8 个平级模块收敛为 4 层递进阅读结构
- 时间窗矩阵合并入“我的标的转折雷达”
- 全市场转折 Top 吸收转折概率数据，改为“市场转折信号”
- 系统健康默认折叠
- 观象指令栏新增「结构扫描」「风险扫描」两颗胶囊

现在进入 UI 落地。

## 你的任务

只做首页 UI / 模板落地，不做后端概率计算。

实现目标：

1. 首页结构收敛为：
   - L0 观象指令栏
   - L1 今日画面 / 状态脉冲
   - L2 我的标的转折雷达
   - L3 市场转折信号
   - 经典策略信号灯
   - 系统健康折叠区
2. 观象指令栏新增两颗胶囊：
   - 结构扫描
   - 风险扫描
3. 时间窗矩阵不再作为独立大卡片抢空间：
   - 可改为雷达行内 compact 显示
   - 或只保留当前选中标的的轻量化条
4. “全市场转折 Top”改名为“市场转折信号”。
5. 若 `observation_deck.probability_signals.items` 存在，优先展示其结构标签。
6. 若概率数据不存在，保持现有 `observation_deck.market_top` 兜底。
7. 系统健康默认折叠，不占主视觉。

## 可改文件

允许：

- `web/templates/index.html`
- `scripts/validate_website_data_sync.py`
- `docs/tasks/OBSERVATION_DECK_PHASE2B_UI_DELIVERY_20260702.md`

不要修改：

- `web/main.py`
- `web/services/*`
- `scripts/build_turning_point_probability.py`
- `web/templates/sentinel_*`

## 数据契约

KIMI1 会在 `observation_deck` 中新增：

```python
observation_deck["probability_signals"] = {
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

模板必须对该字段缺失做兜底，不能因字段不存在 500。

## 文案约束

允许：

- 市场转折信号
- 结构转强
- 结构转弱
- 持续结构
- 证据不足
- 低置信
- 样本不足
- 仅作研究观察

禁止：

- 买入、卖出、加仓、减仓、清仓、空仓、加杠杆
- 止盈、止损、目标价、收益承诺
- 推荐买、推荐卖、适合交易
- 概率百分比，如 `62%`

## 验收

```bash
.venv/bin/python -m py_compile web/main.py scripts/validate_website_data_sync.py
.venv/bin/python scripts/validate_website_data_sync.py --date 20260702
.venv/bin/python scripts/pm_test_preflight.py --date 2026-07-02
```

本地页面检查：

```bash
curl -s http://127.0.0.1:8020/ | rg "我的观察台|市场转折信号|结构扫描|风险扫描|经典策略信号灯"
curl -s http://127.0.0.1:8020/ | rg "买入|卖出|加仓|减仓|清仓|空仓|加杠杆|止盈|止损|目标价|收益承诺|推荐买|推荐卖|适合交易" && echo FAIL || echo OK
```

## 返回格式

1. 改了哪些文件
2. 首页模块如何收敛
3. 本地验收结果
4. P0/P1/P2 风险
5. 是否可进入 Codex 审计
