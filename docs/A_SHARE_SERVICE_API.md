# A 股专属服务 API

版本：v0.2
日期：2026-05-27
状态：最小可用接口
实现文件：`hermass_platform/api/a_share_service.py`

> 范围声明：本服务只服务当前 A 股活跃系统。MT5、美股/US、Alpaca 相关流程不暴露为服务接口。

---

## 1. 启动

```bash
python3 hermass_platform/api/a_share_service.py --host 127.0.0.1 --port 8010
```

如果使用本地虚拟环境：

```bash
.venv/bin/python hermass_platform/api/a_share_service.py --host 127.0.0.1 --port 8010
```

---

## 2. 接口

### 2.1 `GET /health`

用途：健康检查。

响应示例：

```json
{
  "status": "ok",
  "scope": "a_share_only",
  "research_only": true,
  "service": "hermass-a-share-service"
}
```

### 2.2 `POST /run-daily`

用途：运行 A 股 core flow（最小核心链路）。

请求体：

```json
{
  "date": "2026-05-27",
  "previous_date": "2026-05-26",
  "foundation_db": "outputs/p116_foundation_20260527/p116_foundation.duckdb",
  "boundary_pct": 0.03,
  "lookback_days": 20,
  "min_ef": 2,
  "windows": "5,10,20",
  "timeout": 1800,
  "auto_close_timeout": 1.0
}
```

说明：

- 该接口调用 `agently_adapter/agently_a_share_flow.py` 中定义的 A 股 core flow
- 当前只覆盖最小核心链路（core flow），不替代 `stockpool_daily_runner.py run` 的 full compatibility workflow

### 2.3 `POST /run-full-daily`

用途：运行 full compatibility workflow（runner 兼容全量闭环）。

请求体：

```json
{
  "date": "2026-05-27",
  "previous_date": "2026-05-26",
  "foundation_db": "outputs/p116_foundation_20260527/p116_foundation.duckdb",
  "download": false,
  "build_raw": false,
  "download_moneyflow": false,
  "moneyflow_days": 1,
  "build_foundation": false
}
```

说明：

- 该接口直接调用 `agently_adapter/stockpool_daily_runner.py` 的 full compatibility workflow
- 适用于仍需 `public/recommendation/pattern/diagnostics` 等 public extensions 的全量节点工作流

### 2.4 `POST /generate-brief`

用途：单独重建某日总报，不重跑整条链路。

请求体：

```json
{
  "date": "2026-05-27"
}
```

### 2.5 `GET /query-signal`

用途：只读查询某日某标的的标准化信号事实。

请求示例：

```text
/query-signal?stock_code=600519&date=2026-05-27
```

说明：

- 不查数据库，直接读取 `outputs/strategy_signals/strategy_signal_daily_*.json`
- 未传 `date` 时默认读取 `strategy_signal_daily_latest.json`

### 2.6 `POST /research/evidence`

用途：只读生成一份 external research evidence payload。

请求体：

```json
{
  "stock_code": "000021.SZ",
  "date": "2026-05-27",
  "foundation_db": null,
  "fundamental_db": null
}
```

说明：

- 调用 shared research evidence layer
- 输出符合 `EXTERNAL_RESEARCH_RESPONSE_EVIDENCE_CONTRACT.md` 的结构化 payload
- 不生成交易建议，不改写底座数据

### 2.7 `POST /research/card/quick`

用途：基于 shared evidence payload 生成快速问答卡。

请求体：

```json
{
  "stock_code": "000021.SZ",
  "date": "2026-05-27"
}
```

说明：

- quick card 与 deep/evidence card 共享同一 evidence builder
- 返回 Markdown 文本
- `partial / missing` 按 contract 自动降级

### 2.8 `POST /research/card/deep`

用途：基于 shared evidence payload 生成深度研究卡。

请求体：

```json
{
  "stock_code": "000021.SZ",
  "date": "2026-05-27",
  "render_profile": "full"
}
```

说明：

- 用于用户追问后的扩展回答
- 仍是 `Research-Only`
- 不生成长篇投资报告
- `render_profile` 当前支持：
  - `standard`
  - `full`
- 默认是 `full`
- `standard` 会收敛成中等展开版，不包含 `5.1 券商观点`、`5.2 Enrichment 状态`、`4.1 产业链与竞争格局`、`2.1 商业模式与核心竞争力`

### 2.9 `POST /research/card/evidence`

用途：基于 shared evidence payload 生成证据卡。

请求体：

```json
{
  "stock_code": "000021.SZ",
  "date": "2026-05-27"
}
```

说明：

- 优先展示来源、报告期、completeness、数据局限
- 适合作为飞书/问答系统的可信度兜底层

---

## 3. 边界

- 服务是 `A-share only`
- 服务是 `Research-Only`
- `/run-daily` 是 core flow
- `/run-full-daily` 是 full compatibility workflow
- `/research/evidence` 是 shared evidence payload 入口
- `/research/card/*` 是 external research response formatting layer
- 不提供买卖建议
- 不暴露 MT5、US、Alpaca 路径
- 不允许改写 State 底座
