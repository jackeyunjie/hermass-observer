# 问题单与里程碑清单

**日期**: 2026-06-01  
**状态**: 动态更新，完成后打勾

---

| # | 问题单 | Owner | Priority | 截止 | 验收标准 | 状态 |
|---|--------|-------|----------|------|----------|------|
| 1 | Test 10 复合场景修复部署验证 | KIMI | P0 | 2026-06-01 | 10a provider=agently_deepseek（非 rule_based）；10b task_card 非 null + 含行业分析；10a/10b intent.scenario 为复合数组 | **待验收** |
| 2 | Ruff/lint 脚本 `scripts/lint.sh` | Codex | P1 | 2026-06-02 | `bash scripts/lint.sh check` 对 web/main.py 通过且无 error；`bash scripts/lint.sh format` 能自动修复格式；退出码 0=通过、9=失败 | 待启动 |
| 3 | pyproject.toml 追加 `[tool.ruff]` 配置 | Codex | P1 | 2026-06-02 | 配置文件包含 line-length、select rules、ignore rules；`ruff check web/main.py` 不报错（或仅报已有问题） | 待启动 |
| 4 | 数据同步阶段文档 `docs/DEPLOY_SYNC_STAGE.md` | Claude | P1 | 2026-06-02 | 文档写明：同步哪些目录、排除哪些文件、失败时如何人工补救、校验 checksum 的方法；不触发实际 rsync/ssh | 待启动 |
| 5 | 测试骨架 `scripts/run_tests.sh` + `tests/smoke/README.md` | KIMI | P0 | 2026-06-01 | `bash scripts/run_tests.sh help` 打印用法；`unit` 跑 pytest tests/unit/；`smoke` 跑 pytest tests/smoke/；退出码 0/1/2/3 有注释说明；README 写明 HERMASS_DEEPSEEK_API_KEY 作用 | **待验收** |
| 6 | 部署脚本 `scripts/deploy.sh` + `scripts/rollback.sh` | Codex | P1 | 2026-06-03 | deploy.sh 执行 rsync → py_compile → systemctl restart → curl 冒烟，任一步失败立即中止并打印最后成功步骤；rollback.sh 能 git 回退并重启服务；均不硬编码密码 | 待启动 |
| 7 | Pipeline 产出清单 `scripts/run_daily_pipeline.sh` | KIMI | P0 | 2026-06-01 | 末尾输出 `[PIPELINE_OUTPUTS]` 前缀的产出清单；每行含相对路径、大小、行数、sha256 前 8 位；末尾有 total 汇总；缺失目录打印 missing 但不中断 | **待验收** |
| 8 | 调试接口 `web/routes_debug.py` `/api/debug/memory` | Claude | P2 | 2026-06-05 | GET `/api/debug/memory?session_id=xxx` 返回脱敏后的 `_build_memory_context()` 结果（含 recent_turns / recent_stock_codes）；不暴露用户敏感信息 | 待启动 |
| 9 | 任务模式识别修复 `mode=task` | — | P2 | TBD | `"mode":"task"` 请求时 `_chat_answer` 返回 `mode_used="task"` 而非 `"chat"`；不破坏现有 chat 路径 | 阻塞 |
| 10 | 连续对话记忆稳定性 Test 7 | — | P2 | TBD | 第 1 轮输入含股票代码后，第 2 轮 `"它是什么行业"` 返回含该股票所属行业（电子）的分析；session_id 一致 | 阻塞 |

---

## 按 Owner 分组速览

### KIMI（待验收 3 项）
- [x] #1 Test 10 部署验证 — 已完成测试，provider/task_card 均符合预期
- [x] #5 测试骨架 — scripts/run_tests.sh + tests/smoke/README.md 已交付
- [x] #7 Pipeline 产出清单 — scripts/run_daily_pipeline.sh 已追加 Step Last

### Codex（待启动 4 项）
- [ ] #2 Ruff/lint 脚本
- [ ] #3 pyproject.toml ruff 配置
- [ ] #6 部署/回滚脚本

### Claude（待启动 2 项）
- [ ] #4 数据同步阶段文档
- [ ] #8 调试接口

### 未分配（阻塞 2 项）
- [ ] #9 任务模式识别 — 需分析 `_chat_answer` 中 mode 透传逻辑
- [ ] #10 连续对话记忆 — 需分析 `_build_memory_context` 中股票代码持久化
