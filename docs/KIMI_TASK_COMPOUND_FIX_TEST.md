# KIMI 任务 — 支线 A 修复回归测试

版本：v1.0
日期：2026-05-31
执行对象：KIMI
前置条件：修复已部署到 console.supertrader.world
目标：重跑 Test 10 验证修复，确认复合场景在不同 LLM 开关状态下都正确

---

## 0. 修复说明

上轮 Test 10 失败根因：`use_llm=false` 时，`_detect_watch_command()` 规则路径先拦截了输入，复合检测 `_should_compound()` 从未被执行。

修复：在规则路径拦截前加入轻量级复合关键词检测，命中则强制走 LLM 编排。

---

## 1. 测试环境

| 项 | 值 |
|------|------|
| 网址 | http://console.supertrader.world |
| 账号 | hermass-test / Hermass2026!Lab |

---

## 2. 测试用例

### Test 10a — 复合场景 / LLM 开关关 ✅ 核心验证

1. **关闭** LLM 增强开关
2. 输入：`"帮我盯着 000021，这个行业有什么变化"`

验收：

| 字段 | 期望 |
|------|------|
| `provider` | `agently_deepseek`（修复后应自动切换） |
| `task_card` | 存在，非 null |
| `answer` | 包含电子行业分析 |
| `remembered_stock_code` | 000021 |

### Test 10b — 复合场景 / LLM 开关开

1. **打开** LLM 增强开关
2. 输入：`"帮我盯着 000021，这个行业有什么变化"`

验收：

| 字段 | 期望 |
|------|------|
| `provider` | `agently_deepseek` |
| `task_card` | 存在，非 null |
| `answer` | 包含行业分析 |
| `remembered_stock_code` | 000021 |

### Test 11 — 纯盯盘不受影响（回归）

1. 输入：`"帮我盯着 000021"`
2. 验收：task_card 存在，无行业内容
3. 测试两次：LLM 开 + LLM 关

### Test 12 — 纯行业不受影响（回归）

1. 输入：`"电子行业怎么样"`
2. 验收：走纯 industry_scan，无 task_card

---

## 3. 输出

完整 12 项测试表格，重点附 Test 10a / 10b 的完整 JSON 响应。
