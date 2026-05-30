# GitHub First Release Commands

目标：把当前仓库整理成“内部控制台首发”可提交状态。

本文档只定义 **建议提交范围** 与 **命令顺序**，不直接执行部署。

## 1. 首发目标

本次首发只聚焦：

- 内部控制台 `web/`
- research evidence / formatter / API 支撑
- 基础部署脚手架 `deploy/`
- 必要配置与脚本

不把历史研究资料、临时日志、US/MT5 方向内容一起推上 GitHub。

## 2. 推荐提交范围

建议只加入以下内容：

```bash
git add .gitignore
git add pyproject.toml
git add README.md
git add deploy/
git add web/
git add hermass_platform/research/
git add hermass_platform/agents/
git add hermass_platform/api/__init__.py
git add hermass_platform/api/a_share_service.py
git add hermass_platform/api/dingtalk_server.py
git add hermass_platform/api/lark_server.py
git add hermass_platform/api/pipeline_daemon.py
git add config/hermes_cron.json
git add config/models/
git add config/platform/
git add config/prompts/
git add scripts/build_daily_snapshot.py
git add scripts/build_external_research_evidence.py
git add scripts/render_external_research_cards.py
git add scripts/ifind_fundamental_collector.py
git add scripts/run_daily_pipeline.sh
git add scripts/run_morning_brief.sh
git add tests/
git add docs/GITHUB_RELEASE_SCOPE_CHECKLIST.md
git add docs/GITHUB_FIRST_RELEASE_COMMANDS.md
```

## 3. 不要加入的内容

以下内容本次不要 `git add`：

```bash
docs/
data/
outputs/
logs/
scripts/us_*
scripts/build_us_*
scripts/alpaca_*
config/deepseek_context.md
config/industry_rotation_assets.auto_*.json
config/industry_rotation_assets.direct_additions_*.json
config/industry_rotation_assets.expanded_*.json
```

说明：

- `docs/` 里当前混有大量阶段性研究文档，不适合和网站首发绑在一起
- `data/` / `outputs/` / `logs/` 都是本地或运行产物
- US / Alpaca / 归档方向不应混进 A 股内部控制台首发

## 4. 提交前检查

执行：

```bash
git status --short
```

你应该看到：

- `web/`
- `deploy/`
- `hermass_platform/research/`
- `hermass_platform/api/`
- `hermass_platform/agents/`
- `tests/`
- 少量必要 `config/` / `scripts/`

你不应该看到准备提交的：

- `data/Kimi_Agent_*`
- `_batch*.log`
- `_batch*.txt`
- `logs/`
- `outputs/`
- `docs/US_*`

## 5. 建议 commit 划分

建议拆成三次提交：

1. 内部控制台与 research 页面

```bash
git commit -m "feat: add internal console with direction research and execution views"
```

2. research evidence 与运行脚本

```bash
git commit -m "feat: add research evidence pipeline and card render support"
```

3. 部署脚手架与仓库整理

```bash
git commit -m "chore: add deployment scaffolding and tighten release scope"
```

## 6. 如果只想做一个最小首发 commit

可以压成一个：

```bash
git commit -m "feat: ship hermass internal console and deployment scaffolding"
```

但前提仍然是：先确保提交范围已经按本文收口。
