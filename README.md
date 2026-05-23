# Hermass Observer Product

**项目定位**：P116 市场状态观察产品，提供 A 股多周期（MN1/W1/D1）状态计算、筛选与展示能力。

**核心能力**：
- 黑狼数据下载（A 股日线/5 分钟线）
- D1 视角多周期 State 计算（MN1/W1/D1）
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
│   │   ├── p116_core.py           # P116 核心计算（D1 视角）
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

### 1. D1 视角（天条）
所有周期的 position 计算都使用 **D1 收盘价** 比较各自周期的 SR：
- MN1 position = D1 close vs MN1 SR
- W1 position = D1 close vs W1 SR
- D1 position = D1 close vs D1 SR

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

## Agently 底座与策略验证

当前系统把“事实底座”和“经典策略验证”分开：

- State 底座：`outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb`
  - 唯一计算方式是 D1 视角：D1 close 分别比较 MN1/W1/D1 各自 SR。
  - 输出 `mn1_state_hex` / `w1_state_hex` / `d1_state_hex`，供筛选和回测只读消费。
- 入选证据：`scripts/build_strategy_evidence.py`
  - 只用 VCP/2560 作为候选质量证据。
  - 布林强盗、ATR 吊灯只作为完整经典策略选项，不参与底座筛选。
- 经典策略回测：`workflows/agently_stockpool_dag/classic_strategy_backtest.yaml`
  - 使用 `composite` 模式匹配 VCP、2560、布林强盗、ATR 吊灯等规则。
  - 回测只写 `outputs/backtest_*` 和 `public/classic_strategy_backtest_*.html`，不写回基础事实表。

常用命令：

```bash
# State 底座压力测试
python3 agently_adapter/stockpool_daily_runner.py run_state_usage_stress --date 2026-05-21 --iterations 5000 --workers 32

# 生成 State 扫描缓存层（全市场慢扫描每日物化）
python3 agently_adapter/stockpool_daily_runner.py build_state_cache --date 2026-05-21

# 生成入选策略证据（VCP/2560）
python3 agently_adapter/stockpool_daily_runner.py build_strategy_evidence --date 2026-05-21

# 经典策略回测（完整进出场规则）
python3 agently_adapter/stockpool_daily_runner.py run_classic_backtest --date 2026-05-21 --strategy composite --backtest-lookback-days 252
```

## 历史脚本（保留）

以下脚本来自早期版本，仍保留在项目根目录：
- `import_from_research_repo.py` - 从研究母库导入（旧依赖）
- `verify_release.py` - 发布前验证
- `build_p116_ashare_d1_native_state_v2.py` - P116 State 计算 v2
- `filter_w_mn1_ef_d1_ef.py` - W1+MN1 EF 筛选
- `fix_mn1_w1_sr_data.py` - SR 数据前向填充修复
