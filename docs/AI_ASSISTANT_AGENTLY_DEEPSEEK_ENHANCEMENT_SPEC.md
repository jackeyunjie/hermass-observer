# AI 助手 Agently + DeepSeek 增强规格

版本：v1.0  
日期：2026-05-30  
状态：Phase 1.2 设计稿

---

## 1. 目标

在不破坏当前规则型 AI 助手稳定性的前提下，为 Hermass 网站助手增加一个可控的 `Agently + DeepSeek` 增强模式。

增强模式的定位不是替换当前助手，而是：

- 让回答更自然
- 让解释层更像“读过数据的人在说话”
- 保持 `多周期环境 + 单周期位置 + 风险控制` 主线
- 严格失败回退到当前规则答案

一句话：

**规则型助手继续做主路径，DeepSeek 只做增强层。**

---

## 2. 当前事实

### 2.1 已存在能力

- 网站助手接口：`POST /api/chat/query`
- 当前实现：`web/main.py::_chat_answer()`
- 当前输出合同：
  - `answer`
  - `why`
  - `multi_cycle_view`
  - `single_cycle_position`
  - `avoid`
  - `next_actions`
  - `sources`
  - `freshness_note`

### 2.2 项目中已存在的 DeepSeek / Agently 基础

- `agently_adapter/agently_a_share_flow.py`
- `agently_adapter/agently_daily_flow.py`
- `config/deepseek_context.md`
- `config/models/deepseek_runtime.md`
- `hermass_platform/api/a_share_service.py`

### 2.3 当前未接入

- 网站 AI 助手当前 **没有** 调用 Agently
- 当前 **没有** 使用 DeepSeek API Key
- 当前 **没有** 在线 LLM 回答链路

---

## 3. 增强模式的边界

### 3.1 要做

1. 在网站助手接口中增加可选增强模式
2. 仅对“解释型问题”允许走 DeepSeek
3. LLM 输出仍必须符合当前 JSON 合同
4. 失败时自动回退规则答案
5. 保持 Research-Only 边界

### 3.2 不做

1. 不做自由 SQL
2. 不做自动策略生成
3. 不做多 Agent 长链推理
4. 不做交易建议、仓位建议、目标价
5. 不让 LLM 直接读数据库执行查询

---

## 4. 接入策略

### 4.1 路由原则

当前接口继续保留：

`POST /api/chat/query`

新增可选字段：

```json
{
  "message": "现在能不能做",
  "page_context": "/market",
  "stock_code": null,
  "use_llm": true
}
```

默认：

- `use_llm = false`

说明：

- 默认仍走规则答案
- 只有显式开启时才尝试 DeepSeek 增强

---

## 5. 哪些问题允许走 DeepSeek

### 5.1 允许

#### A. 市场解释类

例如：

- 现在能不能做
- 今天市场怎么样
- 当前更适合等待还是试错

原因：

- 这类问题对“解释质量”敏感
- 底层字段比较结构化
- 合规风险较低

#### B. 行业方向解释类

例如：

- 今天先看什么方向
- 电子行业当前处于什么位置
- 哪些行业先少看

原因：

- 适合用自然语言做方向缩圈和节奏解释

### 5.2 暂不允许

#### A. 个股研究主回答

例如：

- 000021 怎么看
- 这只是刚突破还是高位延展

原因：

- 这类问题当前更依赖确定性 research evidence
- 不宜让 LLM 成为主结论来源

处理方式：

- 个股问题继续走规则答案
- DeepSeek 最多只做“补充解释”，不改主结论

#### B. 导航类

例如：

- 我应该先看哪里

原因：

- 规则答案已足够
- 没必要为导航引入额外延迟

---

## 6. DeepSeek 输入合同

网站助手不能把全量页面原文丢给模型。  
只允许传结构化摘要。

### 6.1 市场类输入

```json
{
  "question_type": "market",
  "message": "...",
  "market_phase": {...},
  "daily_snapshot": {...},
  "market_assets_state": {...},
  "macro_chain_prior": {...},
  "freshness": {...}
}
```

### 6.2 行业类输入

```json
{
  "question_type": "industry",
  "message": "...",
  "industry_rotation": {...},
  "industry_position_summary": {...},
  "market_assets_state": {...},
  "freshness": {...}
}
```

---

## 7. Prompt 组成

### 7.1 System Prompt

必须加载：

1. `config/prompts/runtime_architecture_prompt.md`
2. `config/deepseek_context.md`
3. `docs/AI_ASSISTANT_RESPONSE_CONTRACT.md`

### 7.2 任务指令

额外追加一个网站助手专用任务提示，要求：

- 只做解释和导航
- 不做投资建议
- 输出 JSON
- 必须包含：
  - `answer`
  - `why`
  - `multi_cycle_view`
  - `single_cycle_position`
  - `avoid`
  - `next_actions`
  - `sources`
  - `freshness_note`

---

## 8. API Key 配置

### 8.1 建议环境变量

- `HERMASS_DEEPSEEK_API_KEY`
- `HERMASS_DEEPSEEK_BASE_URL`（可选）
- `HERMASS_DEEPSEEK_MODEL`

默认模型名建议：

- `deepseekV4`

### 8.2 禁止

- 不要把 key 写进代码
- 不要把 key 写进模板
- 不要把 key 放进前端可见返回

---

## 9. 回退策略

这是增强模式最关键的一条。

### 9.1 任何下列情况都必须回退规则答案

1. API Key 缺失
2. DeepSeek 请求超时
3. 模型返回非 JSON
4. 模型输出缺少必要字段
5. 合规校验不通过

### 9.2 回退原则

- 不报 500
- 不暴露内部错误细节给用户
- 直接返回当前规则型 `_chat_answer()` 的结果

---

## 10. 最小实现路径

### Phase 1.2

1. 扩展 `ChatQuery`
   - 增加 `use_llm: bool = false`
2. 新增：
   - `_chat_answer_rule_based()`
   - `_chat_answer_with_deepseek()`
3. 在 `/api/chat/query` 中：
   - 先看 `use_llm`
   - 再判断问题类型是否允许增强
   - 如果允许，尝试 DeepSeek
   - 失败则回退规则答案

---

## 11. 验收标准

1. `use_llm=false` 时行为完全不变
2. `use_llm=true` 时市场/行业问题可返回增强答案
3. 返回 JSON 结构与当前合同一致
4. 失败时自动回退，不影响网站
5. 不输出交易建议

---

## 12. 当前建议

当前最合理的推进方式：

1. 继续保留规则型助手为默认
2. 只在内部测试中开启 `use_llm=true`
3. 首先对市场 / 行业问题做 DeepSeek 增强
4. 个股研究仍以 Research Card 为主

这能在不破坏当前上线体验的前提下，逐步把助手从“规则型 MVP”推进到“AI 增强助手”。
