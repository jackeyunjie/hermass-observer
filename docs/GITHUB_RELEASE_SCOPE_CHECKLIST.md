# GitHub Release Scope Checklist

目标：把当前仓库整理到“可推 GitHub、可做服务器部署准备”的状态。

这不是完整产品发布清单，而是 **首发代码范围清单**。

## 1. 本次首发应该包含

以下目录和文件适合进入 GitHub 首发范围：

- `web/`
  - 内部控制台页面与 FastAPI 入口
- `deploy/`
  - `setup.sh`
  - `systemd/hermass-console.service`
  - `nginx-hermass.conf`
- `hermass_platform/`
  - 与网站、research evidence、API 服务直接相关的模块
- `tests/`
  - 与内部控制台、research evidence、API 相关的测试
- `config/`
  - 网站/研究卡/cron/技能说明/平台配置中真正被运行时使用的配置
- `pyproject.toml`
  - 测试与 Python 项目基础配置
- `README.md`
  - 需要更新到当前 A 股内部站主线
- `.gitignore`
  - 必须保持对本地产物、研究资料、临时文件的忽略

## 2. 本次首发建议暂不包含

以下内容不应作为“内部控制台首发”一起推进：

- `data/`
  - 本地研究资料
  - Kimi / Claude 中间产物
  - Excel / parquet / zip / duckdb
- `outputs/`
  - 全部运行产物
- `logs/`
  - 本地日志
- `_batch*.log`
- `_batch*.txt`
- 历史 US / MT5 / Alpaca 方向代码
  - 除非本次明确要一起整理归档，否则不应混入首发提交
- 大体量策略研究文档
  - Founders 对比、历史白皮书、阶段性 brainstorming 文档

## 3. 推荐的首发提交范围

如果目标是先把“内部网站 + 研究卡 + 部署脚手架”推上 GitHub，推荐优先提交：

- `web/`
- `deploy/`
- `hermass_platform/research/`
- `hermass_platform/api/`
- `hermass_platform/agents/`
- `config/hermes_cron.json`
- `config/platform/`
- `config/models/`
- `config/prompts/`
- `config/industry_rotation_assets.json`
- `config/ifind_macro_indicators.json`
- `scripts/build_daily_snapshot.py`
- `scripts/build_external_research_evidence.py`
- `scripts/render_external_research_cards.py`
- `scripts/ifind_fundamental_collector.py`
- `scripts/run_daily_pipeline.sh`
- `scripts/run_morning_brief.sh`
- `tests/`
- `README.md`
- `.gitignore`
- `pyproject.toml`

## 4. 提交前必须检查

提交前至少确认：

1. `git status --short` 中不再出现：
   - `_batch*.log`
   - `_batch*.txt`
   - `logs/`
   - `data/Kimi_Agent_*`
   - `data/project2560/`
   - `data/positions.json`

2. `web` 主要路由本地返回 `200`：
   - `/?mode=direction`
   - `/?mode=research`
   - `/?mode=execution`
   - `/market`
   - `/watchlist`
   - `/research?stock_code=000021.SZ`

3. `deploy/setup.sh` 已通过静态检查：
   - `bash -n deploy/setup.sh`

4. 研究页在基础资料占锁时不会 500。

## 5. 不要做的事

- 不要一次性 `git add .`
- 不要把 `data/` 和 `outputs/` 带上去
- 不要把“内部研究草稿”和“网站首发”混成一个 commit
- 不要把服务器专用 secrets 写入仓库

## 6. 建议的提交策略

建议拆成两到三个 commit：

1. `feat: add internal console and research views`
2. `feat: add deployment scaffolding for internal console`
3. `chore: tighten gitignore and release scope`

这样后续服务器拉取和回滚都更干净。
