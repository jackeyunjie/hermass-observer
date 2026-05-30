# hermes-agent Runtime 模板

适用对象：

- hermes-agent gateway
- hermes-agent skills
- hermes-agent cron

---

## 必载规则源

1. `config/prompts/runtime_architecture_prompt.md`
2. `config/deepseek_context.md`
3. `config/hermes_skills/*.md`

如涉及仓外落地，再参考：

4. `docs/HERMES_LOCAL_RUNTIME_ALIGNMENT_CHECKLIST.md`

---

## 在 Hermass 中的角色

hermes-agent 是：

- 渠道运行时
- 定时任务运行时
- 技能路由层
- 多平台网关

hermes-agent 不是：

- State 底座
- 核心业务计算层
- 主架构定义层

---

## 技能层规则

所有 hermes skills 必须：

- 使用仓内 `config/hermes_skills/*.md` 作为主副本
- 保持 A 股范围
- 查询类优先只读
- 执行类优先调用 API / Flow / Runner 主入口
- 不新增 MT5/US 活跃语境

---

## Cron 规则

- cron 只负责触发
- 不在 cron 命令里塞入大量业务编排
- 长期目标是调用 API 或 Flow 主入口，而不是堆 shell

---

## 一句话规则

> hermes-agent 负责把 Hermass 能力送到用户面前，但不重新定义 Hermass 本体。

