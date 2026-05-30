# KIMI 任务：统一采用 Hermass 主架构路径

状态：可执行  
日期：2026-05-28  
适用模型：KIMI / Claude / 本地模型  
任务类型：架构对齐 / 文档同步 / 提示词执行

---

## 任务目标

让模型在回答、改文档、写说明、补 skill 时，统一采用 Hermass 当前 A 股活跃系统的主架构路径，而不是走历史脚本、归档文档或模糊命名。

---

## 必读文件

执行前先阅读：

1. `README.md`
2. `docs/SYSTEM_ARCHITECTURE.md`
3. `docs/A_SHARE_SERVICE_API.md`
4. `docs/AGENTLY_A_SHARE_INTEGRATION_PLAN.md`
5. `docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md`

如涉及 State 语义，再补读：

6. `docs/STATE_BASE_CONTRACT.md`
7. `docs/AGENT_PERSPECTIVE_ARCHITECTURE.md`

---

## 架构事实

以下表述必须严格统一：

- `shared core layer` = `agently_adapter/a_share_core.py`
- `core flow` = `agently_adapter/agently_a_share_flow.py`
- `full compatibility workflow` = `agently_adapter/agently_daily_flow.py`
- `API service layer` = `hermass_platform/api/a_share_service.py`
- `verify_core_outputs` = core outputs
- `verify_public_outputs` = core outputs + public extensions

---

## 范围限制

1. 系统只服务 A 股。
2. MT5 / US / Alpaca 仅允许作为历史归档出现。
3. 不修改任何 State 底座契约。
4. 不把 shell 脚本写成长期主架构入口。
5. 不做 destructive git 操作。

---

## 执行规则

### 文档任务

如果你在修改文档，统一采用以下描述：

- 飞书是交付层
- hermes-agent 是渠道/调度/技能运行时
- `a_share_service.py` 是服务边界
- `a_share_core.py` 是唯一共享实现
- shell 脚本仅是过渡入口

### 提示词任务

如果你在写给其他模型的提示词，必须显式写出：

1. 先读哪些文件
2. 哪一层是主入口
3. 哪些内容是历史归档
4. 哪些词必须统一
5. 哪些路径禁止绕过

### 审计任务

如果你在做架构审计，重点检查：

1. 是否把 `agently_daily_flow.py` 误写成主线
2. 是否把 `run_daily_pipeline.sh` 误写成主入口
3. 是否把 MT5/US 文档误当成当前规则源
4. 是否漏写 `a_share_service.py`
5. 是否混淆 core/full workflow

---

## 标准输出格式

输出必须是：

1. 变更摘要
2. 按文件列出修改点
3. 架构一致性检查结果
4. 风险或未决点

---

## 推荐提示词模板

```text
你在 hermass-observer-product 仓库中工作。

先阅读以下文件建立架构上下文：
1. README.md
2. docs/SYSTEM_ARCHITECTURE.md
3. docs/A_SHARE_SERVICE_API.md
4. docs/AGENTLY_A_SHARE_INTEGRATION_PLAN.md
5. docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md

当前活跃系统仅限 A 股。

统一术语：
- shared core layer = agently_adapter/a_share_core.py
- core flow = agently_adapter/agently_a_share_flow.py
- full compatibility workflow = agently_adapter/agently_daily_flow.py
- API service layer = hermass_platform/api/a_share_service.py

禁止事项：
- 不引用 MT5/US/Alpaca 作为当前活跃路线
- 不修改 State 底座契约
- 不把 shell 脚本写成长期主入口

本次任务：
[在这里填具体任务]

输出格式：
1. 变更摘要
2. 按文件列出修改点
3. 风险或不确定点
```

