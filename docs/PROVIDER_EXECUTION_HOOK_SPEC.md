# Provider Execution Hook Spec

版本：v1.0  
日期：2026-05-28  
范围：A 股 External Research Response / optional enrichment

---

## 目标

本规范定义 enrichment provider 的执行 hook：

1. **何时触发**
2. **输出写回哪里**
3. **失败时如何降级**

它服务的是当前 Hermass research lane：

- local evidence first
- research-only
- supplement only

本规范不允许 provider 反向篡改 core evidence。

---

## 1. 触发时机

### 1.1 默认路径

默认执行顺序：

```text
build core evidence
  -> attach optional enrichment skeleton / provider status
  -> formatter
  -> API / 飞书输出
```

也就是说：

- **默认只挂 provider contract 和 provider status**
- **默认不执行真实外网 provider**
- 当前 `/research/card/*` 和飞书问答默认保持低延迟、稳定、只依赖本地证据

### 1.2 真实 provider 的推荐触发点

真实 provider 的执行 hook 推荐放在：

```text
core evidence build 完成后
formatter 之前
```

原因：

- provider 的输入依赖完整 evidence
- formatter 只消费最终 evidence/enrichment 结果
- 可以保持 `one evidence, multiple formatters`

### 1.3 按需延迟触发

以下场景允许按需延迟触发：

- 用户追问“最近有什么新闻/事件”
- 用户明确要求“补充外部信息”
- evidence card 显示 provider 为 `ready_for_external_*`

也就是：

```text
默认卡片：不执行真实 provider
按需追问：触发真实 provider
```

### 1.4 当前建议

当前阶段采用：

- **默认路径：只挂 skeleton，不跑真实 provider**
- **下一阶段：只对明确追问启用 provider execution hook**

这比直接在每次 quick/deep card 都联网更符合当前边界。

---

## 2. 写回规则

### 2.1 写回层级

provider 输出只能写入：

```json
{
  "enrichment": {
    "providers": {
      "<provider_id>": {
        ...
      }
    }
  }
}
```

**禁止写回**：

- `company_profile`
- `financial_trend`
- `industry_state`
- `state_core`
- `valuation_reference`
- `market_views`
- `risk_flags`

这些仍然属于 core evidence 层。

### 2.2 supplement-only 原则

provider 只能：

- 补充候选 peer
- 补充新闻摘要
- 补充行业结构说明
- 补充 source trace

provider 不能：

- 覆盖已有字段
- 改写本地结论
- 提高或降低 core completeness

其中 `public_news_digest.digest_items` 推荐固定为最小 5 字段：

- `title`
- `date`
- `source`
- `event_type`
- `impact_hint`

不要在 hook 层继续膨胀为大而全新闻对象。

真实 provider 输出写回前，必须先过 validator：

- 缺字段 -> reject
- 日期非法 -> reject
- 枚举值非法 -> reject
- reject 后只更新 provider 状态，不污染 core evidence

### 2.3 推荐写回 shape

```json
{
  "enrichment": {
    "status": "placeholder",
    "local_hints": [...],
    "providers": {
      "public_news_digest": {
        "provider_id": "public_news_digest",
        "status": "ready_for_external_news_supplement",
        "last_attempt_at": "...",
        "last_success_at": "...",
        "error_count": 0,
        "stale_after_hours": 8,
        "expected_output": {
          "digest_items": [...],
          "policy_event_notes": [...],
          "source_trace": [...]
        }
      }
    }
  }
}
```

### 2.4 formatter 读取规则

formatter 只能读取：

- `meta.enrichment_policy`
- `meta.enrichment_status`
- `meta.enrichment_hints`
- `enrichment.providers[*]`

formatter 不得：

- 把 provider 输出当成主事实
- 把 provider 输出写回 core 模块

---

## 3. 失败策略

### 3.1 超时 / 报错 / 空结果

真实 provider 失败时：

- 不影响 core evidence 构建
- 不阻断 formatter
- 不让 API 返回失败

处理方式：

- `error_count += 1`
- 更新 `last_attempt_at`
- 不更新 `last_success_at`
- `status` 切到错误或待补充状态

### 3.2 推荐状态扩展

当真实 provider 接入后，建议状态允许扩展为：

- `placeholder`
- `local_peer_fields_already_present`
- `ready_for_external_peer_supplement`
- `local_market_views_already_present`
- `ready_for_external_news_supplement`
- `timeout`
- `error`
- `stale`
- `empty_result`

### 3.3 用户可见层的降级规则

默认卡片行为：

- quick card：不展示 provider 细节
- deep card：只展示 enrichment 总状态，不展开异常
- evidence card：展示 provider 状态与最小异常信息

如果 provider 失败：

- 仍然输出基于本地 evidence 的正常回答
- 只在 evidence card 写：
  - provider id
  - status
  - error_count

### 3.4 一句话原则

**provider 可以失败，但研究回答主链不能因此失败。**

---

## 4. API / 飞书影响

### 4.1 当前默认行为

当前：

- `/research/evidence`
- `/research/card/quick`
- `/research/card/deep`
- `/research/card/evidence`
- 飞书研究问答入口

都应继续保持：

- 默认不跑真实 provider
- 只挂 enrichment skeleton / status

### 4.2 未来扩展入口

后续若要启用真实 provider，建议新增显式参数，例如：

```text
?enrichment=providers
```

或：

```text
?provider=public_news_digest
```

而不是静默改变现有默认路径。

---

## 5. 当前结论

当前推荐的 hook 规范是：

1. **默认：core evidence 后挂 skeleton，不执行真实 provider**
2. **真实 provider：放在 formatter 之前**
3. **用户追问：允许按需延迟触发**
4. **写回：只写 enrichment.providers**
5. **失败：永不阻断 core evidence / formatter / API**

---

## 一句话总结

Provider execution hook 的本质不是“让联网更聪明”，而是：

**在不破坏本地 research 主链的前提下，让外部补充能力可以安全、可观测、可降级地插入系统。**
