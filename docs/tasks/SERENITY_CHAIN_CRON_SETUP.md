# Serenity 产业链瓶颈分析 — 定时任务注册文档

## 目标

每日收盘后自动运行 Serenity 产业链瓶颈分析，生成 Markdown 报告并写入 AgentMemory。

## 执行命令

```bash
cd /opt/hermass
source .venv/bin/activate
.venv/bin/python scripts/run_serenity_chain_analysis.py --all
```

## config/hermes_cron.json 新增任务

在 `jobs` 数组中新增以下条目（建议放在 `build_daily_snapshot` 之后）：

```json
{
  "id": "serenity_chain_analysis_daily",
  "name": "Serenity 产业链瓶颈分析",
  "enabled": true,
  "schedule": "0 22 * * *",
  "timezone": "Asia/Shanghai",
  "command": ".venv/bin/python scripts/run_serenity_chain_analysis.py --all",
  "working_dir": "/opt/hermass",
  "timeout_minutes": 30,
  "env": {
    "PYTHONPATH": "/opt/hermass"
  },
  "depends_on": ["build_daily_snapshot"],
  "outputs": [
    "outputs/industry_chain/serenity_reports/",
    "outputs/agent_memory/AgentMemory.duckdb"
  ],
  "alert_on_failure": true,
  "tags": ["industry_chain", "serenity", "daily"]
}
```

## 说明

| 字段 | 值 | 说明 |
|------|-----|------|
| `schedule` | `0 22 * * *` | 每日 22:00 CST（收盘后约 2 小时） |
| `timeout_minutes` | 30 | 产业链分析通常 5-15 分钟完成 |
| `depends_on` | `build_daily_snapshot` | 依赖日报价数据和 State Cube 已更新 |
| `outputs` | 见上 | Markdown 报告 + AgentMemory 判断记录 |

## 依赖数据

任务运行前必须已存在：

- `outputs/industry_chain/industry_chain_evidence.duckdb`
  - 表：`chain_studio_overview`
  - 表：`chain_studio_nodes`
  - 表：`chain_studio_events`
  - 表：`chain_studio_candidates`
- `outputs/state_cube/state_cube.duckdb`
  - 表：`state_cube`

## 产出物位置

- Markdown 报告：`outputs/industry_chain/serenity_reports/serenity_{chain_id}_{state_date}.md`
- AgentMemory 记录：`outputs/agent_memory/AgentMemory.duckdb` -> `agent_judgments`

## P0 产业链列表

当前支持自动分析的产业链：

- `ai_compute` — AI 算力产业链
- `semiconductor` — 半导体产业链
- `nev` — 新能源汽车产业链

## 验证方式

部署后次日检查：

```bash
ls -lt outputs/industry_chain/serenity_reports/ | head
```

应看到 `serenity_ai_compute_YYYY-MM-DD.md` 等文件。

## 排障

| 现象 | 原因 | 处理 |
|------|------|------|
| 报告未生成 | `industry_chain_evidence.duckdb` 中无当日数据 | 检查 `build_daily_snapshot` / `build_chain_studio.py` 是否成功 |
| `node_ranking` 为空 | `chain_studio_candidates` 表缺失 | 运行 `scripts/build_chain_studio.py` |
| score 全部偏低 | 本地数据的 `position_score` / `fund_flow_score` 原始值不高 | 接入真实高分辨率产业数据后分数会自然上升 |
| AgentMemory 写入失败 | schema 不兼容 | 已内置 `ALTER TABLE ADD COLUMN IF NOT EXISTS`，如仍失败查看日志 |

## 首次手动触发

部署后立即手动跑一次，验证链路：

```bash
cd /opt/hermass
.venv/bin/python scripts/run_serenity_chain_analysis.py --all
```
