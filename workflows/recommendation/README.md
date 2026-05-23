# P116 独立量化交易组合推荐模块

这是一个完全可以**独立运行**的程序模块，采用“突破状态共振 + 基本面精选 + 智能文本生成”的量化交易推荐系统。中间大模型使用 **DeepSeek**（`deepseek-chat`），生成对外的每日市场观察和防守价提醒报告。

## 核心设计原则

1. **零 IDE 依赖**：全部脚本和配置均使用 CLI 命令行运行，便于部署于 Cron 或 Docker 容器后台。
2. **三周期共振突破**：只选择月线（MN1）、周线（W1）和日线（D1）同时处于 **E**（趋势形成+关键位突破）或 **F**（强震荡波扩+突破）状态的强共振股票。
3. **基本面双重过滤**：使用黑狼数据 API (`/wolf/financemetric`)，剔除 `ROE < 8.0%` 或 `扣非净利润增长率 < 0` 的公司，从源头规避雷区和低流动性垃圾股。
4. **DeepSeek 智能解读**：读取最终入池股票的结构化数据，自动生成行业聚焦分析、突破异动解读，以及具体的防守（支撑参考）位置。
5. **合规性天条**：严格遵守 [PRODUCT_PRD.md](file:///Users/lv111101/Documents/hermass-observer-product/docs/PRODUCT_PRD.md) 合规话术限制，严禁在提示词和输出中包含“买入/卖出/加仓”等字眼。

---

## 模块结构

此模块所有脚本与配置都封装在此独立文件夹下，与主观测系统的 UI 展示解耦：

```text
workflows/recommendation/
├── config.yaml          # 量化策略与 LLM 参数配置
├── recommend.py         # 独立运行的推荐流水线程序
└── README.md            # 本说明文档
```

---

## 运行指南

### 1. 配置环境变量

在运行前，需要配置必要的 API Key 与 Token：

```bash
# 配置 DeepSeek 接口 Key 与 Endpoint
export DEEPSEEK_API_KEY="your-deepseek-api-key"
export DEEPSEEK_API_BASE="https://api.deepseek.com"  # 支持自定义网关

# 配置黑狼数据 API Token (用于基本面数据获取)
export BLACKWOLF_TOKEN="your-blackwolf-token"
```

### 2. 独立运行推荐命令

你可以使用 Python 直接执行 `recommend.py` 脚本，传入指定的交易日期（需要主系统已生成对应的每日基础数据）：

```bash
python3 workflows/recommendation/recommend.py --date 2026-05-20
```

### 3. 查看输出产物

执行成功后，会在同级目录下生成 `outputs/` 文件夹：

- **Markdown 报告**：`workflows/recommendation/outputs/recommendation_YYYYMMDD.md`
- **结构化 JSON 组合**：`workflows/recommendation/outputs/recommendation_YYYYMMDD.json`
- **最新组合副本**（便于 Web 挂载服务）：`public/recommendation_latest.md`

---

## 最佳实践与自动纪律

- **支撑位即防守线**：组合推荐只提供客观的“支撑参考价”。如果某只股票收盘跌破其对应的 `d1_sr_support`（或 EF 状态个数降为0），系统会在次日自动将其“移出观察池”。
- **长期盈利法则**：极简体验。用户每日只需查看“新入池品种”进行复核关注，并对已持有品种核对“支撑价”，破位即客观离场，无需看盘，无需复杂判断。
