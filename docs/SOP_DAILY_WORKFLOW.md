# Hermass 每日工作流 SOP

> 2026-06-24 固化 · 产品内核：「每日观察任务系统」

---

## 概述

Hermass 定位：A 股主动观察者的多周期观察任务系统。

核心链路：
```
外部线索 → 线索验证体检 → 创建观察任务 → 系统持续盯盘 → 触发提醒
```

---

## 第 0 步：每日数据准备

每天收盘后执行（本地）：

```bash
# 1. 下载 K 线 + 资金流数据
.venv/bin/python blackwolf_actions/download_market_assets.py --date $(date +%Y-%m-%d) --days 3

# 2. 导入市场资产库
.venv/bin/python blackwolf_actions/import_market_assets_duckdb.py --date $(date +%Y-%m-%d)

# 3. 构建 Foundation DB
.venv/bin/python scripts/build_p116_foundation.py --date $(date +%Y-%m-%d)

# 4. 运行全链路脚本
.venv/bin/python scripts/strategy_signal_ledger.py --date $(date +%Y-%m-%d)
.venv/bin/python scripts/estimate_reward_risk.py --date $(date +%Y-%m-%d)
.venv/bin/python scripts/forward_observation_ledger.py --date $(date +%Y-%m-%d)
.venv/bin/python recommendation/run_recommendation_workflow.py --date $(date +%Y-%m-%d)
.venv/bin/python scripts/build_stock_percentiles.py --date $(date +%Y-%m-%d)
.venv/bin/python scripts/build_daily_snapshot.py --date $(date +%Y-%m-%d)
```

## 第 1 步：拉取外部线索

从 iFinD 获取候选标的的公告和财经新闻：

```bash
# 自动从首页观察候选拉取
.venv/bin/python scripts/fetch_ifind_news.py --from-candidates

# 或手动指定标的
.venv/bin/python scripts/fetch_ifind_news.py --stocks "000021.SZ,600519.SH" --days 7
```

**输出**：`outputs/ifind/external_clues.json`（gitignored，不纳入版本控制）

**注意**：
- 免费用户每秒最多 2 个并发请求
- 数据 2 天后自动视为过期
- 不存储全文，仅存标题 + 摘要 + 结构化标签

## 第 2 步：上传产物到服务器

```bash
.venv/bin/python scripts/upload_output_to_server.py --date $(date +%Y%m%d) --type all
```

## 第 3 步：部署到服务器

SSH 到 `8.130.125.201`：

```
在 /opt/hermass 执行部署：

1. git pull
2. source .venv/bin/activate && python -m py_compile web/main.py
3. sudo systemctl restart hermass-console && sudo systemctl status hermass-console
4. 冒烟验证 curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/
```

## 第 4 步：验收公网

```bash
# 首页正常打开
curl -s -o /dev/null -w "%{http_code}" http://console.supertrader.world/

# AI 对话需要认证
curl -s -o /dev/null -w "%{http_code}" -X POST http://console.supertrader.world/api/chat/query -H 'Content-Type: application/json' -d '{"message":"ping","mode":"chat","use_llm":false}'
# 应返回 401

# 认证用户对话
curl -s -u 'hermass-test:Hermass2026!Lab' -o /dev/null -w "%{http_code}" -X POST http://console.supertrader.world/api/chat/query -H 'Content-Type: application/json' -d '{"message":"ping","mode":"chat","use_llm":false}'
# 应返回 200
```

---

## 用户操作流程（从打开网站到完成观察）

### 场景 A：日常复牌

1. 打开首页 `/`
2. 看顶部「今日判断」— 了解今天市场能不能做
3. 看「今日观察候选」— 了解系统推荐盯哪些标的
4. 对感兴趣的标的：
   - 点「创建观察」→ 输入邮箱 → 确认 → 任务创建
   - 或点「问观象」问 AI 怎么看
5. 去 `/watchlist` 管理已有观察任务

### 场景 B：从外部线索验证

1. 从小红书/公众号/朋友那听到一只股票
2. 打开 `/research?stock_code=股票代码`
3. 看「线索验证体检」— 四面体检结论
4. 如果有「外部线索」板块，看公告和新闻
5. 判断是否值得「创建观察」

### 场景 C：委托盯盘

1. 打开观象（点右下角大象图标或右上角按钮）
2. 切换到「任务」模式
3. 发送盯盘指令，如：「盯 000021，突破周线关键位提醒我，邮箱 test@example.com」

---

## 文件分层

| 文件 | 用途 | Git |
|------|------|:---:|
| `config/hermes_cron.json` | 网站定时任务 | ✅ |
| `outputs/user_tasks/user_task_ledger.json` | 用户个人观察任务 | ❌ |
| `outputs/ifind/external_clues.json` | iFinD 外部线索缓存 | ❌ |
| `outputs/alerts/watch_command_ledger.json` | 旧版网站级提醒 | ❌ |

---

## 数据分层

信息源按可信度分 4 层：

| 层级 | 来源 | 用途 | 是否影响推荐 |
|------|------|------|:---:|
| L1 | 交易所公告、公司公告、监管机构 | 事实确认 | ✅ |
| L2 | 正规财经媒体（财联社、证券时报等） | 事件解释 | 可作为证据 |
| L3 | 行业自媒体/公众号 | 早期线索 | 仅提示 |
| L4 | 社区情绪（雪球、股吧） | 热度监测 | 仅 Risk Agent 使用 |

---

## 非阻塞项

- favicon.ico 404 — 不影响功能，可后续补充
- 服务器 `company-pager-nginx` 的 413 错误 — 见 `docs/SERVER_UPLOAD_413_RUNBOOK.md`
- 更多股票简称的 STOCK_NAME_MAP — 目前有 20 个常用标的
