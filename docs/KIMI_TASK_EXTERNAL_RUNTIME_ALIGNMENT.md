# KIMI 任务：对齐 hermes-agent 与本地模型运行时

状态：可执行  
日期：2026-05-28  
适用模型：KIMI / Claude

---

## 任务目标

将仓外运行环境也统一到 Hermass 当前 A 股主架构口径，包括：

- hermes-agent skills / prompt / cron
- 飞书 Bot 运行时提示词
- 本地模型 system prompt

---

## 必读文件

1. `README.md`
2. `docs/SYSTEM_ARCHITECTURE.md`
3. `docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md`
4. `docs/HERMES_LOCAL_RUNTIME_ALIGNMENT_CHECKLIST.md`
5. `config/prompts/runtime_architecture_prompt.md`
6. `config/prompts/local_model_architecture_prompt.md`
7. `config/deepseek_context.md`

---

## 架构事实

必须统一：

- `shared core layer = agently_adapter/a_share_core.py`
- `core flow = agently_adapter/agently_a_share_flow.py`
- `full compatibility workflow = agently_adapter/agently_daily_flow.py`
- `API service layer = hermass_platform/api/a_share_service.py`

---

## 范围限制

1. 系统只服务 A 股。
2. 不引用 MT5 / US / Alpaca 为当前活跃路线。
3. 不修改 State 底座契约。
4. 不把 shell 脚本写成长期主入口。
5. 不做 destructive git 操作。

---

## 执行任务

如果你能访问仓外运行环境，请检查并对齐：

1. `~/.hermes/skills/` 下 skill 名称与仓内 `config/hermes_skills/*.md` 是否一致
2. hermes-agent 的全局 prompt 是否包含 `runtime_architecture_prompt.md` 的核心规则
3. 本地模型的 system prompt 是否包含 `local_model_architecture_prompt.md` 的核心规则
4. cron 是否只负责触发，而不是承载业务编排
5. 飞书运行时是否把 `a_share_service.py` 视为服务边界

如果你不能访问仓外环境，则输出：

- 应同步的文件清单
- 应注入的 prompt 清单
- 建议的落地步骤

---

## 标准输出格式

1. 检查范围
2. 已确认一致的项
3. 需要人工同步的项
4. 风险或不确定点

