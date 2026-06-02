# Hermass Observer Product - Makefile
# 全自动运行，不依赖 IDE
# 用法: make daily DATE=2026-05-20

SHELL := /bin/bash
PYTHON := python3
VENV := .venv
PIP := $(VENV)/bin/pip
PYTHON_VENV := $(VENV)/bin/python
DATE ?= $(shell date +%Y-%m-%d)
YMD = $(subst -,,$(DATE))

# ─── 目录 ───────────────────────────────────────────
ROOT := $(CURDIR)
DATA_DIR := $(ROOT)/data
FIXTURES_DIR := $(ROOT)/fixtures
OUTPUTS_DIR := $(ROOT)/outputs
PUBLIC_DIR := $(ROOT)/public
REPORTS_DIR := $(ROOT)/reports

# ─── 默认目标 ────────────────────────────────────────
.PHONY: help
help:
	@echo ""
	@echo "  Hermass Observer Product"
	@echo "  ─────────────────────────────────────────"
	@echo ""
	@echo "  make install          安装依赖"
	@echo "  make daily            每日全流程 (下载+计算+筛选+输出)"
	@echo "  make foundation       只跑数据基础层 (DuckDB)"
	@echo "  make screen           只跑筛选+输出"
	@echo "  make backtest         回测 E/F 策略历史表现"
	@echo "  make backtest-report  生成回测报告"
	@echo "  make recommend        生成今日推荐组合"
	@echo "  make serve            启动本地 HTTP 查看服务"
	@echo "  make serve-lark       启动飞书 Bot 服务"
	@echo "  make serve-dingtalk   启动钉钉 Bot 服务 (Stream 模式)"
	@echo "  make serve-console    启动内部控制台 (开发模式, 127.0.0.1:8020)"
	@echo "  make serve-console-prod  启动内部控制台 (生产模式, 0.0.0.0:8020)"
	@echo "  make clean            清理临时文件"
	@echo "  make verify           验证当日产物完整性"
	@echo ""
	@echo "  DATE=2026-05-20       指定日期 (默认今天)"
	@echo ""

# ─── 安装依赖 ────────────────────────────────────────
.PHONY: install
install:
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(PIP) install --quiet pyyaml numpy pandas requests duckdb jinja2 pytest pytest-cov dingtalk-stream
	@echo "✓ 依赖安装完成"

# ─── 每日全流程 ──────────────────────────────────────
.PHONY: daily
daily: install
	@echo "════════════════════════════════════════════"
	@echo "  Daily Pipeline - $(DATE)"
	@echo "════════════════════════════════════════════"
	@echo ""
	@echo "[1/5] 下载数据..."
	$(PYTHON_VENV) scripts/data_download/download_daily.py --date $(DATE) || echo "⚠ 下载跳过（使用已有数据）"
	@echo ""
	@echo "[2/5] 构建数据基础 (DuckDB)..."
	$(PYTHON_VENV) scripts/build_p116_foundation.py --date $(DATE)
	@echo ""
	@echo "[3/5] 筛选 E/F 观察池..."
	$(PYTHON_VENV) scripts/run_daily_all_three_ef_workflow.py --date $(DATE) --skip-foundation
	@echo ""
	@echo "[4/5] 生成推荐组合..."
	$(PYTHON_VENV) -m recommend.build_portfolio --date $(DATE) || echo "⚠ 推荐模块待回测验证后启用"
	@echo ""
	@echo "[5/5] 推送通知..."
	$(PYTHON_VENV) -m scripts.notify.push_to_lark --date $(DATE) || echo "⚠ 通知推送跳过（未配置飞书）"
	@echo ""
	@echo "════════════════════════════════════════════"
	@echo "  ✓ Daily pipeline complete: $(DATE)"
	@echo "════════════════════════════════════════════"

# ─── 数据基础层 ──────────────────────────────────────
.PHONY: foundation
foundation: install
	$(PYTHON_VENV) scripts/build_p116_foundation.py --date $(DATE)

# ─── 筛选层 ──────────────────────────────────────────
.PHONY: screen
screen: install
	$(PYTHON_VENV) scripts/run_daily_all_three_ef_workflow.py --date $(DATE) --skip-foundation

# ─── 回测 ────────────────────────────────────────────
.PHONY: backtest
backtest: install
	@echo "════════════════════════════════════════════"
	@echo "  Backtest: E/F Strategy"
	@echo "════════════════════════════════════════════"
	$(PYTHON_VENV) -m backtest.engine \
		--date $(DATE) \
		--lookback-days 252 \
		--output-dir $(OUTPUTS_DIR)/backtest_$(YMD)

.PHONY: backtest-report
backtest-report: backtest
	$(PYTHON_VENV) -m backtest.report \
		--backtest-dir $(OUTPUTS_DIR)/backtest_$(YMD) \
		--out-html $(PUBLIC_DIR)/backtest_report_$(YMD).html
	@echo "✓ 回测报告: $(PUBLIC_DIR)/backtest_report_$(YMD).html"

.PHONY: backtest-walk-forward
backtest-walk-forward: install
	$(PYTHON_VENV) -m backtest.walk_forward \
		--start-date 2025-01-01 \
		--end-date $(DATE) \
		--output-dir $(OUTPUTS_DIR)/walk_forward_$(YMD)

# ─── 推荐 ────────────────────────────────────────────
.PHONY: recommend
recommend: install
	$(PYTHON_VENV) -m recommend.build_portfolio --date $(DATE) \
		--foundation-db $(OUTPUTS_DIR)/p116_foundation_$(YMD)/p116_foundation.duckdb \
		--output-dir $(OUTPUTS_DIR)/recommend_$(YMD)

# ─── 风控检查 ────────────────────────────────────────
.PHONY: risk-check
risk-check: install
	$(PYTHON_VENV) -m risk.portfolio_risk \
		--portfolio $(OUTPUTS_DIR)/recommend_$(YMD)/portfolio.json

# ─── 本地查看服务 ────────────────────────────────────
.PHONY: serve
serve:
	@echo "本地查看: http://localhost:8080"
	@echo "按 Ctrl+C 停止"
	cd $(PUBLIC_DIR) && $(PYTHON) -m http.server 8080

.PHONY: serve-lark
serve-lark: install
	@echo ""
	@echo "Hermass Lark Bot 启动..."
	@echo "  飞书回调: http://localhost:8080/lark/callback"
	@echo "  健康检查: http://localhost:8080/health"
	@echo ""
	$(PYTHON_VENV) hermass_platform/api/lark_server.py --port 8080

.PHONY: serve-dingtalk
serve-dingtalk: install
	@echo ""
	@echo "Hermass DingTalk Bot 启动..."
	@echo "  Stream 模式 — WebSocket 直连，无需公网 IP"
	@echo ""
	$(PYTHON_VENV) hermass_platform/api/dingtalk_server.py

# ─── 内部控制台服务 ──────────────────────────────────
.PHONY: serve-console
serve-console: install
	@echo ""
	@echo "Hermass Internal Console 启动..."
	@echo "  本地地址: http://127.0.0.1:8020"
	@echo "  健康检查: http://127.0.0.1:8020/health"
	@echo "  按 Ctrl+C 停止"
	@echo ""
	cd $(ROOT) && $(PYTHON_VENV) -m uvicorn web.main:app --host 127.0.0.1 --port 8020

.PHONY: serve-console-prod
serve-console-prod: install
	@echo ""
	@echo "Hermass Internal Console 生产模式启动..."
	@echo "  监听: 0.0.0.0:8020"
	@echo ""
	cd $(ROOT) && $(PYTHON_VENV) -m uvicorn web.main:app --host 0.0.0.0 --port 8020 --workers 1

.PHONY: daily-pipeline
daily-pipeline: install
	@echo "运行每日流水线..."
	bash scripts/run_daily_pipeline.sh

.PHONY: snapshot
snapshot: install
	$(PYTHON_VENV) scripts/build_daily_snapshot.py

.PHONY: report-dry
report-dry: install
	$(PYTHON_VENV) scripts/send_daily_report.py --dry-run
	@echo "HTML 已保存到: outputs/daily_report.html"

.PHONY: report-send
report-send: install
	$(PYTHON_VENV) scripts/send_daily_report.py

# ─── 验证 ────────────────────────────────────────────
.PHONY: verify
verify:
	$(PYTHON_VENV) scripts/verify_release.py
	@test -f $(PUBLIC_DIR)/p116_all_three_ef_latest.html && echo "✓ HTML产物存在" || echo "✗ HTML产物缺失"
	@test -f $(FIXTURES_DIR)/observation_pool_$(YMD).json && echo "✓ JSON产物存在" || echo "✗ JSON产物缺失"

# ─── 清理 ────────────────────────────────────────────
.PHONY: clean
clean:
	find $(ROOT) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find $(ROOT) -name "*.pyc" -delete 2>/dev/null || true
	rm -rf $(ROOT)/outputs/backtest_* $(ROOT)/outputs/walk_forward_*
	@echo "✓ 临时文件已清理"

# ─── 开发用 ──────────────────────────────────────────
.PHONY: lint
lint:
	$(PYTHON_VENV) -m py_compile backtest/engine.py
	$(PYTHON_VENV) -m py_compile risk/position_sizer.py
	@if [ -f "$(ROOT)/signal_module/quality_score.py" ]; then \
		$(PYTHON_VENV) -m py_compile signal_module/quality_score.py; \
	elif [ -f "$(ROOT)/signal/quality_score.py" ]; then \
		$(PYTHON_VENV) -m py_compile signal/quality_score.py; \
	fi
	@echo "✓ 语法检查通过"

.PHONY: test
test: install
	$(PYTHON_VENV) -m pytest tests/unit/ -v

.PHONY: test-all
test-all: install
	$(PYTHON_VENV) -m pytest tests/ -v --ignore=tests/stress --ignore=tests/regression

.PHONY: test-cov
test-cov: install
	$(PYTHON_VENV) -m pytest tests/unit/ --cov=scripts/state_calc --cov=scripts/filter --cov-report=term

.PHONY: test-cov-html
test-cov-html: install
	$(PYTHON_VENV) -m pytest tests/unit/ --cov=scripts/state_calc --cov=scripts/filter --cov-report=html

.PHONY: test-stress
test-stress: install
	$(PYTHON_VENV) -m pytest tests/stress/ tests/regression/ -v -m slow -s

.PHONY: test-full
test-full: install
	$(PYTHON_VENV) -m pytest tests/ -v

# ─── 数据库迁移 ──────────────────────────────────────
.PHONY: db-migrate
db-migrate: install
	@echo "════════════════════════════════════════════"
	@echo "  DB Migrate - $(DATE)"
	@echo "════════════════════════════════════════════"
	@echo ""
	@echo "[1/3] 数据质量字段..."
	$(PYTHON_VENV) scripts/add_data_quality_fields.py --date $(DATE) || { echo "✗ add_data_quality_fields.py 失败"; exit 1; }
	@echo ""
	@echo "[2/3] AgentMemory DDL..."
	@if [ -f "$(ROOT)/scripts/init_agent_memory.py" ]; then \
		$(PYTHON_VENV) scripts/init_agent_memory.py; \
	else \
		echo "⚠ AgentMemory schema skipped (init_agent_memory.py not found)"; \
	fi
	@echo ""
	@echo "[3/3] 重建 BB/Pivot/ATR 物化视图..."
	$(PYTHON_VENV) scripts/rebuild_bb_pivot_atr.py || { echo "✗ rebuild_bb_pivot_atr.py 失败"; exit 1; }
	@echo ""
	@echo "════════════════════════════════════════════"
	@echo "  ✓ db-migrate complete: $(DATE)"
	@echo "════════════════════════════════════════════"
