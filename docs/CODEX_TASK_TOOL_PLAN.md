# Codex Task — 工具链规划文档落盘

版本：v1.0  
日期：2026-05-31  
执行对象：Codex  
目标：将工具链规划写为正式文档 `docs/2026-05-31_TOOL_PLAN.md`

---

## 0. 背景

Hermass 项目当前没有自动化测试、部署脚本、代码质量工具。所有操作靠人工步骤和 Agent 提示词驱动。

你提出的三条工具链规划已获批准，请落盘为正式文档。

---

## 1. 文档要求

输出文件：`docs/2026-05-31_TOOL_PLAN.md`

必须包含以下三个板块：

### 板块 1：测试与回归工具链

- [ ] 问题描述：当前无 pytest，test_agently_chains.py 无法本地直跑
- [ ] 方案：`make test` 或 `scripts/test.sh`，显式激活 `.venv`
- [ ] 分类：smoke tests（需 API key）vs unit tests（mock，无需 key）
- [ ] 增量：`test_e2e_chat_value_llm.py` 增加 mock 路径，允许无 API key 时跑 schema 断言
- [ ] 里程碑：第一版能跑 3 个冒烟用例即达标
- [ ] 验收标准

### 板块 2：部署与回滚工具链

- [ ] 问题描述：部署文档靠人工步骤，SSH 失败后无自动诊断
- [ ] 方案：`scripts/deploy.sh` — rsync → py_compile → systemctl restart → curl 冒烟
- [ ] 方案：`scripts/rollback.sh` — git stash + restart + 自动跑 smoke
- [ ] 失败自动中止，打印最后成功步骤 + 错误
- [ ] 里程碑：一键部署，一键回滚
- [ ] 验收标准

### 板块 3：代码质量与可观测性

- [ ] 问题描述：`_llm_chat_answer()` 超 100 行，异常只 `pass` 不记日志
- [ ] 方案：引入 ruff（格式化/静态检查）
- [ ] 方案：引入 logging.warning 替代裸 `pass`
- [ ] 方案：`_build_memory_context()` 增加 debug endpoint（`/api/debug/memory?session_id=xxx`）
- [ ] 里程碑：ruff 通过 + 异常可追溯
- [ ] 验收标准

---

## 2. 格式要求

- 每个板块包含：问题 → 方案 → 文件清单 → 里程碑 → 验收标准
- 不要写具体实现代码，只规划文件路径和功能描述
- 每个脚本的输入/输出/退出码要明确

---

## 3. 服务器信息（参考）

| 项 | 值 |
|------|------|
| IP | 8.130.125.201 |
| 项目路径 | `/opt/hermass` |
| 服务 | hermass-console (systemd, 8020) |
| Python | .venv 虚拟环境 |

---

## 4. 禁止事项

- 不要写业务逻辑相关的内容（不讨论 Agent、场景、State 等）
- 不要直接写脚本代码（这是规划文档，不是实现）
- 不要涉及主线 Phase 3、支线 A、支线 B 的业务规划
