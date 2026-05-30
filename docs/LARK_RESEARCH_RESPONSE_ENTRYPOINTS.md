# 飞书 Bot 研究回答入口

版本：v0.1  
日期：2026-05-28  
状态：最小可用  
实现文件：`hermass_platform/chat/lark_handler.py`

> 范围声明：本入口只服务当前 A 股外部研究回答能力，不提供投资建议，不暴露 MT5 / US / Alpaca 路径。

---

## 1. 当前已支持的研究回答类型

飞书 Bot 当前支持三类个股研究回答：

1. 快速研究卡
2. 深度研究卡
3. 证据卡

三者都共享同一份 evidence payload：

- `shared evidence layer` = `hermass_platform/research/external_research_evidence.py`
- `formatter layer` = `hermass_platform/research/external_research_formatters.py`

---

## 2. 触发方式

当前版本采用 **6 位股票代码 + 关键词** 触发。

### 2.1 快速研究卡

支持示例：

- `000021 快速研究`
- `000021 怎么看`
- `研究一下 000021`
- `000021 个股研究`

Quick Card 会直接展示动态 State 节奏先验，例如：

```text
State：E/E/F（大周期保持扩张趋势，D1 处于突破后的活跃推进段，先验上更容易先出现短周期节奏切换。）
```

### 2.2 深度研究卡

支持示例：

- `深度分析 000021`
- `000021 深度研究`
- `000021 详细分析`
- `000021 标准版研究`
- `000021 完整版研究`

说明：

- `深度分析 / 深度研究 / 详细分析 / 完整版研究` 默认走 `render_profile=full`
- `标准版研究` 显式走 `render_profile=standard`
- 这是展示策略层差异，不改变 shared evidence payload

### 2.3 证据卡

支持示例：

- `000021 证据卡`
- `000021 数据来源`
- `000021 可信度`

---

## 3. 当前实现边界

当前版本已实现：

- 直接在飞书消息入口识别研究卡请求
- 自动构建 shared evidence payload
- 自动渲染 quick / deep / evidence 三类卡片
- 自动追加 research-only 免责声明

当前版本暂未实现：

- 公司名模糊识别
- 多股票比较
- 自然语言多轮追问记忆
- 通过飞书直接选择卡片类型的按钮交互

---

## 4. 路由原则

飞书研究入口当前遵循：

1. 优先识别“研究卡请求”
2. 命中后不再走旧 market / strategy / coach agent 分发
3. 只使用 A 股 research response lane
4. 不输出买入/卖出/推荐类表达

---

## 5. 后续建议

下一步优先级建议：

1. 增加公司名 → 股票代码映射
2. 增加“最新交易日”而不是 `date.today()` 的 research 查询日期逻辑
3. 把 quick / deep / evidence 三类结果接成飞书富文本或卡片消息

## 6. 固定计划推送

当前仓内已经支持把每日策略报告按固定计划推送到飞书群：

- 脚本入口：
  - `scripts/send_daily_strategy_report_to_lark.sh`
- 推送内容：
  - 基于 `scripts.notify.push_to_lark` 的每日策略报告消息
- 配置来源：
  - `config/platform/lark_app.yaml` 中的 `push.chat_id` 或 `push.webhook_url`
- 定时计划：
  - `config/hermes_cron.json`
  - 默认安排在交易日 `15:18`

说明：

- 这条推送路径服务“每日策略报告”
- 与飞书 Bot 的对话式 quick / deep / evidence 研究卡是两条独立路径

## 7. 后续主动推送方向

已定义的后续规范：

- [ACTIVE_STATE_ALERTS_SPEC.md](/Users/lv111101/Documents/hermass-observer-product/docs/ACTIVE_STATE_ALERTS_SPEC.md)
- [WEEKLY_COGNITIVE_RECAP_SPEC.md](/Users/lv111101/Documents/hermass-observer-product/docs/WEEKLY_COGNITIVE_RECAP_SPEC.md)

当前阶段先定边界，不直接把它们并入现有飞书 Bot 回答链。

### Phase 1 已落地

- 主动 State 提醒脚本：
  - `scripts/send_active_state_alerts_to_lark.py`
- 默认定时：
  - 交易日 `15:25`
- 提醒范围：
  - 最近 7 天被问过的股票
- 提醒类型：
  - D1 从 `E/F` 跌出
  - D1 连续 3 个交易日走弱
  - 所在行业出现板块共振

- 每周认知复盘卡：
  - `scripts/build_weekly_cognitive_recap.py`
  - `scripts/send_weekly_cognitive_recap_to_lark.sh`
  - 默认定时：每周五 `15:35`
