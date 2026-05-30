# AI 助手盯盘指令与邮箱提醒规格

版本：v1.0  
日期：2026-05-30  
状态：Phase 1 设计稿

---

## 1. 目标

允许用户通过网站 AI 助手提交“盯盘 / 长期跟踪”指令，并要求提供邮箱，由系统在命中条件时通过邮件发送提醒。

典型需求：

- 帮我盯 000021
- 000021 突破周线关键位提醒我
- 长期跟踪 600519
- 周线关键位突破时发邮件给我

一句话：

**AI 助手负责采集跟踪意图，后台任务负责判断条件并发邮件。**

---

## 2. 边界

### 2.1 要做

1. AI 助手识别盯盘意图
2. 强制要求用户提供邮箱
3. 把盯盘命令写入本地 watch command ledger
4. 后台定时任务读取 ledger 并判断是否触发
5. 命中后通过已有 SMTP 链路发邮件

### 2.2 不做

1. 不做短信
2. 不做推送 App
3. 不做即时盘中 websocket 提醒
4. 不做买卖建议
5. 不做仓位管理

---

## 3. 指令类型

### 3.1 基础盯盘

示例：

- 盯 000021
- 帮我跟踪 600519

语义：

- 把这只股票加入长期观察对象
- 命中基础状态变化时通知

### 3.2 条件盯盘

示例：

- 000021 突破周线关键位提醒我
- 600519 跌破 D1 支撑发邮件
- 002049 行业共振时通知我

语义：

- 只有命中明确条件时才提醒

### 3.3 长期跟踪

示例：

- 长期跟踪 000858
- 持续跟踪 002594

语义：

- 默认有效期更长
- 允许多次重复提醒，但要去重

---

## 4. 统一输入合同

AI 助手识别出盯盘意图后，不直接下发提醒，而是生成结构化对象：

```json
{
  "stock_code": "000021.SZ",
  "watch_type": "conditional",
  "trigger_type": "w1_breakout",
  "email": "user@example.com",
  "valid_days": 30,
  "note": "突破周线关键位提醒",
  "created_from": "ai_assistant",
  "page_context": "/research"
}
```

---

## 5. 邮箱要求

### 5.1 强制项

所有盯盘命令都必须带邮箱。

如果用户没提供邮箱，AI 助手必须返回：

- 当前结论：可以帮你建立盯盘任务
- 为什么：邮件是当前唯一稳定通知通道
- 暂时不用看什么：先不用重复发送股票代码
- 下一步去哪里：请补充邮箱地址

### 5.2 邮箱格式

最小校验：

- 含 `@`
- 含域名后缀

不做复杂验证，只做格式校验。

---

## 6. 触发条件字典

Phase 1 只支持有限条件，不做自由条件语言解析。

### 6.1 支持的 trigger_type

| trigger_type | 含义 | 数据来源 |
|-------------|------|---------|
| `state_drop` | D1 从 E/F 跌出 | foundation / active alerts |
| `d1_support_break` | 跌破 D1 支撑 | state cache / SR boundary |
| `w1_breakout` | 突破周线关键位 | foundation + W1 boundary |
| `sector_resonance` | 所属行业出现共振 | industry_rotation / resonance |
| `d1_weakening_3d` | D1 连续 3 天走弱 | active alerts |
| `long_term_watch` | 长期跟踪型，按摘要更新 | weekly or daily digest |

### 6.2 Phase 1 不支持

- 任意自然语言条件组合
- 多股票组合条件
- 自定义数学表达式

---

## 7. 存储设计

新增本地账本：

- `outputs/alerts/watch_command_ledger.json`

每条记录：

```json
{
  "watch_id": "watch_20260530_000021SZ_001",
  "stock_code": "000021.SZ",
  "stock_name": "深科技",
  "watch_type": "conditional",
  "trigger_type": "w1_breakout",
  "email": "user@example.com",
  "valid_from": "2026-05-30",
  "valid_to": "2026-06-29",
  "status": "active",
  "note": "突破周线关键位提醒",
  "created_from": "ai_assistant",
  "page_context": "/research",
  "last_triggered_at": null
}
```

---

## 8. AI 助手行为

### 8.1 识别盯盘意图

关键词：

- `盯`
- `跟踪`
- `提醒我`
- `发邮件`
- `突破周线关键位`
- `跌破支撑`

### 8.2 返回结构

AI 助手在识别成功后返回：

- 当前结论：已识别为盯盘请求 / 还缺邮箱
- 为什么：提醒条件说明
- 多周期环境：为什么这个条件和多周期有关
- 单周期位置：当前观察重点是什么
- 暂时不用看什么：先别重复发同样指令
- 下一步去哪里：补邮箱 / 查看执行页

同时新增一个结构化动作：

```json
{
  "watch_command": {
    "stock_code": "...",
    "trigger_type": "...",
    "email_required": true
  }
}
```

---

## 9. 执行链路

### 9.1 创建

1. 用户通过助手发起盯盘
2. AI 助手提取：
   - 股票
   - 条件
   - 邮箱
3. 后端写入 `watch_command_ledger.json`

### 9.2 判断

新增后台任务：

- `scripts/process_watch_command_alerts.py`

职责：

1. 读取 `watch_command_ledger.json`
2. 对所有 `active` 任务检查是否命中条件
3. 命中则生成邮件正文
4. 调用现有 SMTP 链路发送
5. 更新 `last_triggered_at`

### 9.3 发信

复用已有邮件环境变量：

- `HERMASS_SMTP_HOST`
- `HERMASS_SMTP_PORT`
- `HERMASS_SMTP_USER`
- `HERMASS_SMTP_PASS`

---

## 10. 邮件内容要求

邮件不是交易建议，只是状态通知。

示例：

主题：

`Hermass 盯盘提醒 — 000021.SZ 周线关键位突破`

正文：

- 股票代码 / 名称
- 触发条件
- 触发日期
- 当前多周期环境摘要
- 当前单周期位置摘要
- 下一步建议页面：
  - 市场页
  - 执行页
  - 研究页

固定后缀：

> 本邮件仅为系统研究提醒，不构成投资建议。

---

## 11. 去重与节流

### 11.1 去重键

```
{trade_date}:{stock_code}:{email}:{trigger_type}
```

### 11.2 节流

- 同一条件同一日只发一次
- 长期跟踪摘要默认每周最多 1 次

---

## 12. Phase 1 最小实现

1. AI 助手增加盯盘意图识别
2. 若缺邮箱，则提示补充
3. 新增 ledger 文件写入
4. 新增后台脚本读取并发邮件

### 暂不做

- 前端复杂管理页
- 用户自己编辑所有规则
- 多邮箱通知组
- Webhook / 短信 / IM 同步推送

---

## 13. 验收标准

1. 用户能说：
   - `盯 000021，邮箱 xxx@xx.com`
2. 系统能写入 watch command ledger
3. 条件命中时能发邮件
4. 邮件不包含交易建议
5. 重复命中不会重复轰炸

---

## 14. 当前建议

最小先做这 3 类：

1. `w1_breakout`
2. `d1_support_break`
3. `sector_resonance`

这样最贴近 Hermass 当前的多周期和结构观察主线，也最容易解释清楚。 
