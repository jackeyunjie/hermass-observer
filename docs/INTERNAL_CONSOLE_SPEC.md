# Internal Console

## Goal

为内部团队提供一个轻量工作台，用于：

- 查看每日核心产物是否生成
- 预览最新 quick / deep / evidence research cards
- 查看主动提醒与周复盘相关产物
- 查看 cron / pipeline 基本运行配置

## Scope

第一版只做内部使用，不做：

- 对外官网
- 用户登录系统
- 复杂前端
- 交易下单或账户管理

## Entry

```bash
.venv/bin/uvicorn web.main:app --host 127.0.0.1 --port 8020
```

Local URL:

```text
http://127.0.0.1:8020/
```

团队内网访问时可改为 `--host 0.0.0.0`，但必须先加反向代理鉴权或内网访问控制，不直接裸露到公网。

## Tabs

### 1. Outputs

- Foundation DB
- Daily Brief
- Strategy Ledger
- Forward Observation
- Active Alerts Ledger

### 2. Research

- 输入股票代码
- 预览 Quick / Deep / Evidence 三张卡
- Deep 支持 `standard / full`

### 3. Push

- 主动提醒账本
- 周复盘快照

### 4. Runtime

- cron 任务列表
- enabled / schedule 状态

### 5. Quant

- strategy signal daily count
- strategy distribution
- forward observation pending / labeled
- reward-risk summary
- high reward-risk samples

## Positioning

- 钉钉：推送与快速交互
- Internal Console：内部查看、核对、排障与预览

## Frontend References

只借鉴信息架构和交互形态，不直接复制第三方代码，避免许可证和适配成本。

- Freqtrade / FreqUI：一屏概览、状态卡、表格与图表混排。
- BEC：每日产物、定时任务、回测归档。
- TradeSight：策略信号卡片、日志查看、简洁研究工作台布局。
- UltraTrader：FastAPI + WebSocket 实时状态流，作为后续升级参考。

当前实现先采用 FastAPI + Jinja2 单体轻页面，原因是：

- 与现有 Python evidence / formatter / pipeline 直接复用。
- 服务器部署比 Streamlit 更稳。
- 先满足内部团队可看、可查、可排障，再决定是否拆独立前端。
