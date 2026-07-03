# Observation Deck Phase 2B 双线分发

日期：2026-07-02
协调者：Codex

## 当前基线

已上线：

- 首页：我的观察台 / 转折雷达
- 经典策略哨兵：`/sentinel`
- 转折概率只读 API：
  - `/api/turning-point-probability/summary`
  - `/api/turning-point-probability/signals`
  - `/api/turning-point-probability/stock`
- 最新部署 commit：`89077ab`
- 2026-07-02 验收：`validate_website_data_sync.py` 全绿，`pm_test_preflight.py` 17/17 passed

## 目标

进入 Phase 2B：把首页从“模块平铺”收敛成“观察终端”，但不引入交易动作建议。

本轮只分发给：

- KIMI
- KIMI1

不再分发给 KIMI2。

## 分工

| 执行者 | 任务 | 允许改代码 | 文件边界 |
|---|---|---:|---|
| KIMI | 首页 Phase 2B UI 落地 | 是 | `web/templates/index.html`、`scripts/validate_website_data_sync.py`、文档 |
| KIMI1 | 首页转折概率适配层 | 是 | `web/services/observation_deck_probability.py`、`web/main.py`、测试、文档 |

## 共享数据契约

KIMI1 负责在 `observation_deck` 中新增：

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

KIMI 只按这个字段做模板展示，不在模板里计算概率、不展示裸概率百分比。

## 合并顺序

1. KIMI1 后端适配层先合并。
2. KIMI UI 模板后合并。
3. Codex 统一审计、提交、部署和公网冒烟。

## 红线

- 首页不得出现：买入、卖出、加仓、减仓、清仓、空仓、加杠杆、止盈、止损、目标价、收益承诺、推荐买、推荐卖、适合交易。
- 首页不得展示裸概率百分比。
- 概率只转换成结构标签：结构转强、结构转弱、持续结构、证据不足、低置信。
- 经典策略信号继续独立，不参与概率、不混入 State 主判断。
- Web 请求不得跑重计算脚本。

## 返回格式

每个执行者返回：

1. 改了哪些文件
2. 做了什么
3. 本地验收命令与结果
4. 风险 / 未完成项
5. 是否可进入 Codex 审计
