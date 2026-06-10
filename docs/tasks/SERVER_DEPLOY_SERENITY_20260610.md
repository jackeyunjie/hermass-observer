# 服务器部署提示词：Serenity 产业链瓶颈分析上线

在 /opt/hermass 执行部署：

1. git pull
2. source .venv/bin/activate && python -m py_compile web/main.py hermass_platform/agents/serenity_chain_analyzer.py agently_adapter/workflow_bridge.py
3. sudo systemctl restart hermass-console && sudo systemctl status hermass-console
4. 冒烟验证：
   - curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/
   - curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/api/chain/ai_compute/serenity-analysis
   - curl -s -u 'hermass-test:Hermass2026!Lab' -o /dev/null -w "%{http_code}" http://localhost:8020/chain-studio
   - curl -s -u 'hermass-test:Hermass2026!Lab' -o /dev/null -w "%{http_code}" http://localhost:8020/api/chain/ai_compute/serenity-analysis?state_date=2026-06-05
5. 数据库兼容性验证：
   .venv/bin/python -c "
   import duckdb
   from pathlib import Path
   p = Path('outputs/agent_memory/AgentMemory.duckdb')
   con = duckdb.connect(str(p))
   con.execute('CREATE TABLE IF NOT EXISTS agent_judgments (agent_id VARCHAR, judgment_id VARCHAR PRIMARY KEY, judgment_date DATE, judgment_type VARCHAR, judgment_content JSON, confidence DOUBLE, factors_used JSON, context_snapshot JSON)')
   for col, typ in [('agent_id','VARCHAR'),('judgment_id','VARCHAR'),('judgment_date','DATE'),('judgment_type','VARCHAR'),('judgment_content','JSON'),('confidence','DOUBLE'),('factors_used','JSON'),('context_snapshot','JSON')]:
       try:
           con.execute(f'ALTER TABLE agent_judgments ADD COLUMN IF NOT EXISTS \"{col}\" {typ}')
       except Exception as e:
           print('WARN', col, e)
   con.close()
   print('schema ok')
   "
6. docker exec company-pager-nginx nginx -T | grep -q console.supertrader.world && echo "nginx proxy ok"

验收标准：
- systemd active (running)
- 本地 8020 HTTP 200
- 未带 Auth 的 /api/chain/ai_compute/serenity-analysis 返回 401
- 带 Auth 的返回 200 且 JSON 中 ok=true
- nginx -T 中 console.supertrader.world 代理配置无异常
- schema ok
