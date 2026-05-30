# Research Enrichment Provider Contracts

版本：v1.0  
日期：2026-05-28  
范围：A 股 External Research Response

---

## 目标

本文件定义 research enrichment 层的 provider contract。  
这些 provider 只做**补充增强**，不替代本地 `evidence payload`。

统一边界：

- local evidence first
- research-only
- source traceable
- supplement only

---

## Provider 1

### `industry_competition_external_peers`

**用途**

在 `182242 | 产业链与竞争格局` 的基础上，补充：

- 外部 peer 候选
- 行业结构观察
- 竞争格局补充说明

**不允许做的事**

- 不覆盖 `company_profile.comparable_companies`
- 不覆盖 `company_profile.competitor_companies`
- 不生成投资建议
- 不生成目标价/评级
- 不把外部信息直接升级为主证据

**输入**

- `company_profile.sw_l1/sw_l2/sw_l3`
- `company_profile.main_business`
- `company_profile.ths_concepts`
- `industry_state.prosperity_score`
- `industry_state.sector_resonance`

**输出 shape**

```json
{
  "provider_id": "industry_competition_external_peers",
  "enabled": true,
  "status": "placeholder | local_peer_fields_already_present | ready_for_external_peer_supplement",
  "priority": "supplement_only",
  "last_attempt_at": "2026-05-28T12:00:00Z",
  "last_success_at": "2026-05-28T12:00:00Z",
  "error_count": 0,
  "stale_after_hours": 24,
  "expected_output": {
    "peer_candidates": [
      {"name": "兆易创新", "source": "local_ifind", "confidence": 0.95}
    ],
    "industry_structure_notes": [],
    "source_trace": []
  }
}
```

**状态解释**

- `placeholder`
  - provider 只完成合同注册，尚无可用本地提示
- `local_peer_fields_already_present`
  - 本地 evidence 已有 peer 字段，外部 provider 只需做补充
- `ready_for_external_peer_supplement`
  - 本地已有行业/概念/板块线索，但 peer 不足，适合后续联网增强

**运行时字段**

- `last_attempt_at`
  - 最近一次 provider 运行尝试时间
- `last_success_at`
  - 最近一次成功产出时间
- `error_count`
  - 连续失败计数或当前累计错误计数
- `stale_after_hours`
  - 过期阈值，便于判断 provider 结果是否已过时

---

## 实施顺序

### Phase 1

- 注册 provider contract
- 在 enrichment payload 中暴露 provider 状态
- 不接真实外网

### Phase 2

- 接入真实 external search / public info provider
- 输出 `peer_candidates`
- 输出 `source_trace`
- 保持 supplement-only 边界

---

## 一句话原则

Enrichment provider 只能增强解释层，不能篡改本地证据层。  
`industry_competition_external_peers` 是第一个 provider，服务行业竞争格局模块，但永远不是主证据源。

---

## Provider 2

### `public_news_digest`

**用途**

补充公司与行业相关的公开事件、政策、新闻摘要，优先服务：

- 风险提示补充
- 市场事件观察
- 行业政策变化提示

**不允许做的事**

- 不覆盖 `risk_flags`
- 不覆盖 `market_views`
- 不把新闻标题直接转成投资建议或交易信号
- 不把新闻流替代本地结构化 evidence

**输入**

- `company_profile.stock_name`
- `company_profile.ths_concepts`
- `industry_state.sw_l1`
- `industry_state.sector_resonance`
- `risk_flags`
- `market_views`

**输出 shape**

```json
{
  "provider_id": "public_news_digest",
  "enabled": true,
  "status": "placeholder | local_market_views_already_present | ready_for_external_news_supplement",
  "priority": "supplement_only",
  "last_attempt_at": "2026-05-28T12:00:00Z",
  "last_success_at": "2026-05-28T12:00:00Z",
  "error_count": 0,
  "stale_after_hours": 8,
  "expected_output": {
    "digest_items": [
      {
        "title": "紫光国微发布 2025Q1 业绩预告",
        "date": "2026-04-15",
        "source": "公司公告",
        "event_type": "earnings",
        "impact_hint": "neutral"
      }
    ],
    "policy_event_notes": [],
    "source_trace": []
  }
}
```

**状态解释**

- `placeholder`
  - provider 只完成合同注册，尚未发现可用本地事件提示
- `local_market_views_already_present`
  - 本地 `market_views` 已有机构研报信息，外部新闻只需做补充
- `ready_for_external_news_supplement`
  - 本地已有风险或概念/板块线索，但缺少公开事件摘要，适合后续联网增强

**digest_items 最小字段合同**

每条新闻摘要只保留 5 个字段：

| 字段 | 用途 |
|------|------|
| `title` | 卡片展示标题 |
| `date` | 时效性过滤，例如超过 30 天可降级或不展示 |
| `source` | 来源标注 |
| `event_type` | 用于后续映射到 `earnings / policy / capital / tech` |
| `impact_hint` | `positive / neutral / negative`，仅做 provider 初判，不构成投资建议 |

约束：

- 不追加目标价、评级、建议字段
- 不把 `impact_hint` 当成交易指令
- 若来源仅是本地 `market_views`，应写入 `policy_event_notes`，而不是伪装成新闻 `digest_items`

**实现要求**

- 真实 provider 接入前，必须通过统一 validator
- validator 至少校验：
  - `digest_items` 为列表
  - 每条必须含 `title/date/source/event_type/impact_hint`
  - `date` 必须是 `YYYY-MM-DD`
  - `event_type` 只能是 `earnings / policy / capital / tech`
  - `impact_hint` 只能是 `positive / neutral / negative`

**优先价值**

相较 peer 补充，`public_news_digest` 更直接填补事件驱动与政策变化空白，更适合作为下一步真实 provider 的优先接入对象。
