#!/bin/bash
# Serenity 产业链瓶颈分析上线脚本（本地 -> 服务器）
# 用法：bash scripts/deploy_serenity_chain.sh

set -euo pipefail

echo "=== Serenity Chain 上线脚本 ==="
echo ""

# ── 1. 确认 commit 范围 ──
echo "[1/6] 确认 commit 范围..."
git status --short

echo ""
echo "建议 selective commit（ serenity 本期内容）："
echo "  hermass_platform/agents/serenity_chain_analyzer.py"
echo "  scripts/run_serenity_chain_analysis.py"
echo "  scripts/deploy_serenity_chain.sh"
echo "  config/skills/serenity-skill/"
echo "  web/main.py  # 含 serenity-analysis API + workflow_bridge 相关"
echo ""

# 自动 add serenity 相关文件
git add hermass_platform/agents/serenity_chain_analyzer.py \
        scripts/run_serenity_chain_analysis.py \
        scripts/deploy_serenity_chain.sh \
        config/skills/serenity-skill/ \
        web/main.py \
        agently_adapter/workflow_bridge.py \
        tests/unit/test_workflow_bridge.py \
        tests/unit/test_chat_query_fallback.py \
        tests/integration/test_guanxiang_workflow_e2e.py \
        docs/tasks/ \
        docs/workflow/ \
        scripts/mock_external_workflow.py \
        scripts/run_guanxiang_30q_coverage.py \
        2>/dev/null || true

echo "[2/6] 语法与导入检查..."
.venv/bin/python -m py_compile \
  hermass_platform/agents/serenity_chain_analyzer.py \
  agently_adapter/workflow_bridge.py \
  web/main.py

echo "[3/6] 目标回归测试..."
.venv/bin/python -m pytest \
  tests/unit/test_workflow_bridge.py \
  tests/unit/test_chat_query_fallback.py \
  tests/integration/test_guanxiang_workflow_e2e.py \
  -q

echo "[4/6] serenity analyzer 冒烟..."
python3 -c "
import sys, base64
sys.path.insert(0, '.')
from fastapi.testclient import TestClient
from web.main import app
client = TestClient(app)

# anonymous -> 401
r = client.get('/api/chain/ai_compute/serenity-analysis?state_date=2026-06-05')
assert r.status_code == 401, f'anonymous should 401, got {r.status_code}'
print('  anonymous 401: OK')

# Basic Auth -> 200
creds = base64.b64encode(b'testuser:testpass').decode()
r = client.get('/api/chain/ai_compute/serenity-analysis?state_date=2026-06-05',
               headers={'Authorization': f'Basic {creds}'})
assert r.status_code == 200, f'auth should 200, got {r.status_code}'
data = r.json()
assert data['ok'] is True
print(f'  auth 200: OK, top_score={data[\"node_ranking\"][0][\"score\"]}')
"

echo ""
echo "[5/6] 准备提交..."
git diff --stat --cached

echo ""
echo "[6/6] 请手动执行："
echo "  git commit -m 'feat: serenity-skill 产业链瓶颈分析 + workflow_bridge 外部工作流扩展'"
echo "  git push"
echo ""
echo "=== 本地验证完成 ==="
