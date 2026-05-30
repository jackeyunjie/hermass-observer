# Hermass Observer Product

**项目定位**：P116 市场状态观察产品，当前提供 A 股 `D1 Agent` 的多结构状态（MN1/W1/D1）计算、筛选与展示能力。

> 范围声明：本仓库的活跃系统范围仅限 A 股。MT5、美股/US、Alpaca 等相关内容均视为历史归档，不作为当前设计、开发或运行范围。

**核心能力**：
- 黑狼数据下载（A 股日线/5 分钟线）
- D1 Agent 多结构 State 计算（MN1/W1/D1）
- E/F 状态筛选（至少 2 周期为 E 或 F）
- 每日观察池生成（固定字段顺序，一行一天）
- 可打开的本地 HTML 页面交付

## 项目结构

```
hermass-observer-product/
├── config/                    # 配置文件
│   ├── settings.yaml          # 全局配置（黑狼 API、State 参数、筛选条件）
│   └── fixed_columns.yaml     # 固定 34 字段顺序定义
├── scripts/
│   ├── data_download/         # 数据下载模块
│   │   ├── blackwolf_client.py    # 黑狼 API 客户端
│   │   └── download_daily.py      # 日线数据下载
│   ├── state_calc/            # State 计算模块
│   │   ├── p116_core.py           # P116 核心计算（当前为 D1 Agent）
│   │   ├── sr_calculator.py       # MT4 风格 SR 计算
│   │   └── d1_perspective.py      # 多周期对齐（bisect 前向填充）
│   ├── filter/                # 筛选模块
│   │   └── ef_screener.py         # E/F 条件筛选器
│   ├── output/                # 输出模块
│   │   ├── csv_gen.py             # CSV 生成（UTF-8-BOM，固定字段）
│   │   └── html_gen.py            # HTML 生成（可点击本地页面）
│   ├── pipeline.py            # 主控流水线入口
│   └── generate_observation_pool.py  # 观察池生成（固定字段顺序）
├── data/                      # 原始数据（K 线 CSV）
├── fixtures/                  # 产物数据（JSON/CSV）
├── public/                    # 可访问的 HTML 页面
└── .qoder/skills/             # Qoder Skill 封装
    └── p116-observer-pipeline/    # 完整流水线 Skill
```

## 核心原则

### 1. 当前实现：D1 Agent（天条）
当前 Foundation DB 实现的是 `D1 Agent`，其内部所有结构周期的 position 计算都使用 **D1 收盘价** 比较各自周期的 SR：
- MN1 position = D1 close vs MN1 SR
- W1 position = D1 close vs W1 SR
- D1 position = D1 close vs D1 SR

抽象层统一命名见 [docs/AGENT_PERSPECTIVE_ARCHITECTURE.md](/Users/lv111101/Documents/hermass-observer-product/docs/AGENT_PERSPECTIVE_ARCHITECTURE.md)：
- `mn1_state_hex = state_hex(D1, MN1)`
- `w1_state_hex = state_hex(D1, W1)`
- `d1_state_hex = state_hex(D1, D1)`

### 2. State Score 位运算
```
score = base + (trend_bit × 4) + (position_bit × 2) + volatility_bit
```
- base: 0=缩, 8=扩
- trend: 0=平, 1=牛/熊
- position: 0=下突, 1=中, 2=上突
- volatility: 0=稳, 1=波扩

### 3. E/F 筛选条件
- E = 14, F = 15（最高状态）
- 筛选：至少 2 个周期为 E 或 F
- 展示：前 100 只 × 最近 3 天

### 4. 固定字段顺序（34 字段）
```
股票代码 | 股票简称 | 日期 | EF周期数 |
MN1_state_hex | MN1_state_score | W1_state_hex | W1_state_score | D1_state_hex | D1_state_score |
[MN1/W1/D1 详细字段...]
```

## 快速开始

### 安装依赖
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pyyaml numpy pandas requests
```

### 运行流水线
```bash
# 生成指定日期的观察池
python3 scripts/pipeline.py --date 2026-05-20

# 或使用 Skill
/p116-observer-pipeline --date 2026-05-20
```

### 生成观察池（从已有数据）
```bash
python3 scripts/generate_observation_pool.py --date 2026-05-20
```

### 启动本地 HTTP 服务查看
```bash
cd public && python3 -m http.server 8080
# 访问 http://localhost:8080/observation_pool_20260520.html
```

## 输出产物

| 产物 | 路径 | 说明 |
|------|------|------|
| CSV | `fixtures/observation_pool_YYYYMMDD.csv` | 300 行（100 只 × 3 天），34 字段 |
| HTML | `public/observation_pool_YYYYMMDD.html` | 可点击本地页面，彩色高亮 |
| JSON | `fixtures/observation_pool_YYYYMMDD.json` | 结构化数据 |

## 数据来源

- **黑狼数据 API**：`https://api.fxyz.site`
- **A 股股票池**：A250 成分股

## 重要说明

**Research-Only**：本结果仅为技术状态观察，不构成任何投资建议。

## 冻结清单

以下内容当前保留在仓库中，但属于历史归档或冻结范围，不作为 A 股活跃系统的设计、开发或运行入口：

- `docs/HERMASS_STATE_MT5_PORTING_GUIDE.md`
- `docs/mt5_package/`
- `docs/US_STATE_MVP_DEEP_ANALYSIS.md`
- `docs/US_VS_CN_STATE_COMPARISON_FRAMEWORK.md`
- `scripts/us_*.py`
- `scripts/build_us_*.py`
- `scripts/check_founder_trades_us_state.py`
- `scripts/backtest_us_state.py`
- `scripts/alpaca_trading/`

## A 股服务入口

当前最小服务层见：

- [A_SHARE_SERVICE_API.md](/Users/lv111101/Documents/hermass-observer-product/docs/A_SHARE_SERVICE_API.md)
- [SYSTEM_ARCHITECTURE.md](/Users/lv111101/Documents/hermass-observer-product/docs/SYSTEM_ARCHITECTURE.md)
- [MODEL_ARCHITECTURE_USAGE_GUIDE.md](/Users/lv111101/Documents/hermass-observer-product/docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md)

提供四个 A 股专属只读/研究接口：

| 接口 | 类型 | 对应 Flow | 说明 |
|------|------|-----------|------|
| `POST /run-daily` | core flow | `agently_a_share_flow.py` | 最小核心链路（7 步） |
| `POST /run-full-daily` | full compatibility workflow | `agently_daily_flow.py` | 全量兼容闭环（core + public extensions） |
| `POST /generate-brief` | 独立重建 | — | 单独重建某日简报 |
| `GET /query-signal` | 只读查询 | — | 查询某日某标的标准化信号 |

## 模型与技能入口

如果要让 KIMI、本地模型、hermes-agent、飞书 Bot 统一走当前主架构，优先使用：

- [MODEL_ARCHITECTURE_USAGE_GUIDE.md](/Users/lv111101/Documents/hermass-observer-product/docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md)
- [KIMI_TASK_MODEL_ARCHITECTURE_ADOPTION.md](/Users/lv111101/Documents/hermass-observer-product/docs/KIMI_TASK_MODEL_ARCHITECTURE_ADOPTION.md)

当前 hermes skills 路径：

- `config/hermes_skills/market-analyst.md`
- `config/hermes_skills/strategy-advisor.md`
- `config/hermes_skills/coach.md`
- `config/hermes_skills/daily-pipeline.md`
- `config/hermes_skills/sector-resonance.md`

运行时统一提示词：

- [runtime_architecture_prompt.md](/Users/lv111101/Documents/hermass-observer-product/config/prompts/runtime_architecture_prompt.md)
- [local_model_architecture_prompt.md](/Users/lv111101/Documents/hermass-observer-product/config/prompts/local_model_architecture_prompt.md)
- [HERMES_LOCAL_RUNTIME_ALIGNMENT_CHECKLIST.md](/Users/lv111101/Documents/hermass-observer-product/docs/HERMES_LOCAL_RUNTIME_ALIGNMENT_CHECKLIST.md)
- [KIMI_TASK_EXTERNAL_RUNTIME_ALIGNMENT.md](/Users/lv111101/Documents/hermass-observer-product/docs/KIMI_TASK_EXTERNAL_RUNTIME_ALIGNMENT.md)
- [config/models/README.md](/Users/lv111101/Documents/hermass-observer-product/config/models/README.md)

## 最小运行说明

如果你只需要记住两条启动路径，用这两条：

```bash
# Core Flow：最小核心链路
cd /tmp && /Users/lv111101/Documents/hermass-observer-product/.venv/bin/python \
  /Users/lv111101/Documents/hermass-observer-product/agently_adapter/agently_a_share_flow.py \
  --date 2026-05-22 \
  --previous-date 2026-05-21 \
  --foundation-db /Users/lv111101/Documents/hermass-observer-product/outputs/p116_foundation_20260522/p116_foundation.duckdb

# Full Compatibility Workflow：完整兼容闭环
cd /tmp && /Users/lv111101/Documents/hermass-observer-product/.venv/bin/python \
  /Users/lv111101/Documents/hermass-observer-product/agently_adapter/agently_daily_flow.py \
  --date 2026-05-22 \
  --previous-date 2026-05-21 \
  --foundation-db /Users/lv111101/Documents/hermass-observer-product/outputs/p116_foundation_20260522/p116_foundation.duckdb
```

## 周末定时整理检查

仓库已提供一个“每周末固定”的本地整理检查任务，只生成报告，不自动执行危险的 `git` 修复：

```bash
# 手动运行
bash scripts/weekend_repo_hygiene_check.sh

# macOS launchd 安装
cp config/platform/com.hermass.weekend-repo-hygiene.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.hermass.weekend-repo-hygiene.plist
```

默认计划：

- 每周六 10:00 本地时间
- 输出报告目录：`logs/repo_hygiene/`
- 只做审计，不自动 `git reset` / `git commit`

## Agently 底座与策略验证

当前系统把“事实底座”和“经典策略验证”分开：

- State 底座：`outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb`
  - 当前正式主产出是 `D1 Agent`：D1 close 分别比较 MN1/W1/D1 各自 SR。
  - 输出 `mn1_state_hex` / `w1_state_hex` / `d1_state_hex`，它们分别对应 `state_hex(D1, MN1)` / `state_hex(D1, W1)` / `state_hex(D1, D1)`，供筛选和回测只读消费。
- 入选证据：`scripts/build_strategy_evidence.py`
  - 只用 VCP/2560 作为候选质量证据。
  - 布林强盗、ATR 吊灯只作为完整经典策略选项，不参与底座筛选。
- 经典策略回测：`workflows/agently_stockpool_dag/classic_strategy_backtest.yaml`
  - 使用 `composite` 模式匹配 VCP、2560、布林强盗、ATR 吊灯等规则。
  - 回测只写 `outputs/backtest_*` 和 `public/classic_strategy_backtest_*.html`，不写回基础事实表。

常用命令：

```bash
# ── Full Compatibility Workflow（推荐用于完整日闭环）──
# 方式 A：直接运行 runner（core flow + public extensions）
python3 agently_adapter/stockpool_daily_runner.py run \
  --date 2026-05-22 \
  --previous-date 2026-05-21 \
  --foundation-db outputs/p116_foundation_20260522/p116_foundation.duckdb

# 方式 B：通过 Agently TriggerFlow 运行（从项目外目录启动，避免 signal/ 包遮蔽标准库）
cd /tmp && /Users/lv111101/Documents/hermass-observer-product/.venv/bin/python \
  /Users/lv111101/Documents/hermass-observer-product/agently_adapter/agently_daily_flow.py \
  --date 2026-05-22 \
  --previous-date 2026-05-21 \
  --foundation-db outputs/p116_foundation_20260522/p116_foundation.duckdb

# ── Core Flow（最小核心链路，7 步）──
cd /tmp && /Users/lv111101/Documents/hermass-observer-product/.venv/bin/python \
  /Users/lv111101/Documents/hermass-observer-product/agently_adapter/agently_a_share_flow.py \
  --date 2026-05-22 \
  --previous-date 2026-05-21 \
  --foundation-db /Users/lv111101/Documents/hermass-observer-product/outputs/p116_foundation_20260522/p116_foundation.duckdb

# State 底座压力测试
python3 agently_adapter/stockpool_daily_runner.py run_state_usage_stress --date 2026-05-21 --iterations 5000 --workers 32

# 生成 State 扫描缓存层（全市场慢扫描每日物化）
python3 agently_adapter/stockpool_daily_runner.py build_state_cache --date 2026-05-21

# 生成入选策略证据（VCP/2560）
python3 agently_adapter/stockpool_daily_runner.py build_strategy_evidence --date 2026-05-21

# 生成 iFinD 宏观事实层快照（可无 token 降级输出缺口审计）
python3 agently_adapter/stockpool_daily_runner.py build_ifind_macro --date 2026-05-22

# API 配额不足时，可用 Mac 版 iFinD 导出的宏观 Excel/CSV 直接落库
python3 agently_adapter/stockpool_daily_runner.py build_ifind_macro --date 2026-05-22 --macro-import-file data/ifind_macro_20260522.xlsx

# 生成宏观-产业链先验层，用于后验概率修正，但不直接改 State 或策略排序
python3 agently_adapter/stockpool_daily_runner.py build_macro_chain_prior --date 2026-05-22

# 生成行业ETF数据-配置-审计闭环报告（默认不覆盖生产配置）
python3 agently_adapter/stockpool_daily_runner.py build_industry_etf_config --date 2026-05-22

# 显式确认后，才把自动直接候选写回生产配置
python3 agently_adapter/stockpool_daily_runner.py build_industry_etf_config --date 2026-05-22 --apply-industry-etf-config

# 经典策略回测（完整进出场规则）
python3 agently_adapter/stockpool_daily_runner.py run_classic_backtest --date 2026-05-21 --strategy composite --backtest-lookback-days 252
```

代理 ETF 的人工审核写在 `config/industry_etf_proxy_whitelist.json`：

- `pending_review`：只进审计报告，不参与 `full_match` 判定。
- `approved`：日流程末尾写入 `config/industry_rotation_assets.json`；下一次市场资产下载后进入行业 State。
- `no_etf_coverage`：如 `综合`，不再作为每日缺口重复报警。

## 历史脚本（保留）

以下脚本来自早期版本，仍保留在项目根目录：
- `import_from_research_repo.py` - 从研究母库导入（旧依赖）
- `verify_release.py` - 发布前验证
- `build_p116_ashare_d1_native_state_v2.py` - P116 State 计算 v2
- `filter_w_mn1_ef_d1_ef.py` - W1+MN1 EF 筛选
- `fix_mn1_w1_sr_data.py` - SR 数据前向填充修复
